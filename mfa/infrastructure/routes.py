import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

from fastapi import APIRouter, Query
from sse_starlette.sse import EventSourceResponse

from mfa.application.emailmfa import OutlookInboxChecker

router = APIRouter(prefix="/api/v1")

CLIENT_ID = os.environ.get("CLIENT_ID", "")
TENANT_ID = os.environ.get("TENANT_ID", "")
CLIENT_SECRET = os.environ.get("CLIENT_SECRET", "")


def sse_event(event: str, data: dict) -> dict:
    return {"event": event, "data": json.dumps(data)}


def extract_code_from_email(content: str) -> str | None:
    """Extract a 6-8 digit code from email content."""
    match = re.search(r"\b(\d{6,8})\b", content)
    return match.group(1) if match else None


def extract_verizon_allow_deny_link(content: str) -> str | None:
    """Extract the 'Allow or deny' link from Verizon MFA email content."""
    match = re.search(r"Allow or deny\s*<(https?://[^>]+)>", content)
    return match.group(1) if match else None


async def authenticate_checker(checker: OutlookInboxChecker) -> bool:
    return await asyncio.to_thread(checker.authenticate)


async def get_messages_async(
    checker: OutlookInboxChecker,
    email_alias: str,
    date_filter: datetime,
    from_email: str | list[str],
):
    return await asyncio.to_thread(
        checker.get_messages,
        email_alias,
        date_filter,
        10,
        from_email,
    )


async def code_extractor(
    carrier: str, email_alias: str, carrier_from_email: str | list[str]
) -> AsyncGenerator[dict, None]:
    elapsed = 0
    TIMEOUT_SECONDS = 300
    POLL_INTERVAL = 5
    code = None
    checker = OutlookInboxChecker(CLIENT_ID, TENANT_ID, CLIENT_SECRET)
    authenticated = await authenticate_checker(checker)
    if not authenticated:
        yield sse_event(
            "endpoint_error", {"carrier": carrier, "message": "Failed to authenticate with email provider"}
        )
        yield sse_event("done", {"carrier": carrier})
        return

    start_time = datetime.now(timezone.utc) - timedelta(minutes=1)

    while elapsed < TIMEOUT_SECONDS:
        messages = await get_messages_async(checker, email_alias, start_time, carrier_from_email)

        if messages and len(messages) > 0:
            first_message = messages[0]
            code = extract_code_from_email(first_message.body.content)
            if code:
                break
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    if code is None:
        yield sse_event(
            "endpoint_error", {"carrier": carrier, "message": "Timeout: No code received within 5 minutes"}
        )
    else:
        yield sse_event("code", {"carrier": carrier, "code": code})

    yield sse_event("done", {"carrier": carrier})


@router.get("/att")
async def get_att_code(email_alias: str = Query(...)):
    email_alias = "notifications@expertel.com"
    # AT&T has been migrating senders; accept both legacy and new domains.
    carrier_from_emails = [
        "premier@premier.wireless.att-mail.com",
        "noreply@e.online.att-mail.com",
    ]
    return EventSourceResponse(code_extractor("att", email_alias, carrier_from_emails))


@router.get("/bell")
async def get_bell_code(email_alias: str = Query(...)):
    email_alias = "notifications@expertel.com"
    carrier_from_email = "noreply@bell.ca"
    return EventSourceResponse(code_extractor("bell", email_alias, carrier_from_email))


@router.get("/rogers")
async def get_rogers_code(email_alias: str = Query(...)):
    email_alias = "notifications@expertel.com"
    carrier_from_email = "notifications@rci.rogers.com"
    return EventSourceResponse(code_extractor("rogers", email_alias, carrier_from_email))


@router.get("/telus")
async def get_telus_code(email_alias: str = Query(...)):
    email_alias = "notifications@expertel.com"
    carrier_from_email = "telus@example.com"
    return EventSourceResponse(code_extractor("telus", email_alias, carrier_from_email))


@router.get("/tmobile")
async def get_tmobile_code(email_alias: str = Query(...)):
    carrier_from_email = "customercare@notifications.t-mobile.com"
    email_alias = "notifications@expertel.com"  # T-Mobile emails arrive at this mailbox
    return EventSourceResponse(code_extractor("tmobile", email_alias, carrier_from_email))


async def verizon_link_extractor(email_alias: str, carrier_from_email: str) -> AsyncGenerator[dict, None]:
    """Verizon-specific extractor that returns the 'Allow or deny' link instead of a code."""
    elapsed = 0
    TIMEOUT_SECONDS = 300
    POLL_INTERVAL = 5
    link = None

    print(f"[Verizon] Starting link extractor for email: {email_alias}")
    print(f"[Verizon] Looking for emails from: {carrier_from_email}")

    checker = OutlookInboxChecker(CLIENT_ID, TENANT_ID, CLIENT_SECRET)
    authenticated = await authenticate_checker(checker)
    if not authenticated:
        yield sse_event(
            "endpoint_error", {"carrier": "verizon", "message": "Failed to authenticate with email provider"}
        )
        yield sse_event("done", {"carrier": "verizon"})
        return

    # Subtract 2 minutes to account for timing differences between MFA trigger and endpoint call
    start_time = datetime.now(timezone.utc) - timedelta(minutes=2)
    print(f"[Verizon] Start time filter: {start_time}")

    while elapsed < TIMEOUT_SECONDS:
        messages = await get_messages_async(checker, email_alias, start_time, carrier_from_email)

        print(f"[Verizon] Poll {elapsed}s - Found {len(messages) if messages else 0} messages")

        if messages and len(messages) > 0:
            first_message = messages[0]
            print(f"[Verizon] First message subject: {first_message.subject}")
            link = extract_verizon_allow_deny_link(first_message.body.content)
            if link:
                print(f"[Verizon] Link extracted: {link[:50]}...")
                break
            else:
                print("[Verizon] Could not extract link from email body")
        await asyncio.sleep(POLL_INTERVAL)
        elapsed += POLL_INTERVAL

    if link is None:
        yield sse_event(
            "endpoint_error", {"carrier": "verizon", "message": "Timeout: No MFA link received within 5 minutes"}
        )
    else:
        yield sse_event("link", {"carrier": "verizon", "link": link})

    yield sse_event("done", {"carrier": "verizon"})


@router.get("/verizon")
async def get_verizon_link(email_alias: str = Query(...)):
    carrier_from_email = "VZWMail@ecrmemail.verizonwireless.com"
    email_alias = "notifications@expertel.com"
    return EventSourceResponse(verizon_link_extractor(email_alias, carrier_from_email))
