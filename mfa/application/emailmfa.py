import os
import re
from datetime import datetime, timedelta, timezone

import requests
from dotenv import find_dotenv, load_dotenv
from msal import ConfidentialClientApplication

from mfa.domain.entities import EmailMessage, InboxChecker

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

# logging.basicConfig(
#     level=logging.DEBUG,
#     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
#     handlers=[
#         logging.StreamHandler(sys.stdout),
#         logging.FileHandler('mfa.log', mode='a')
#     ]
# )


class OutlookInboxChecker(InboxChecker):
    """Outlook/Microsoft 365 implementation of InboxChecker using Microsoft Graph API."""

    def __init__(self, client_id: str, tenant_id: str, client_secret: str) -> None:
        self.client_id = client_id
        self.tenant_id = tenant_id
        self.client_secret = client_secret
        self.access_token: str | None = None

    def authenticate(self) -> bool:
        """Authenticate with Microsoft Graph API using Azure AD credentials."""
        authority = f"https://login.microsoftonline.com/{self.tenant_id}"
        scope = ["https://graph.microsoft.com/.default"]

        app = ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=authority,
        )
        try:
            token = app.acquire_token_for_client(scopes=scope)
            if "access_token" not in token:
                raise RuntimeError(f"Token error: {token.get('error')} - {token.get('error_description')}")
            self.access_token = token["access_token"]
            print("Access token obtained successfully")
            return True
        except requests.exceptions.RequestException as e:
            print(f"Error getting access token: {e}")
            return False

    def get_messages(
        self,
        user_email: str,
        date_filter: datetime,
        top: int = 10,
        from_email: str | list[str] | None = None,
    ) -> list[EmailMessage] | None:
        """Retrieve messages from Outlook inbox using Microsoft Graph API.

        `from_email` may be a single sender or a list of senders (combined with OR).
        """
        if not self.access_token:
            print("You must first authenticate")
            return None
        print(user_email)
        url = f"https://graph.microsoft.com/v1.0/users/{user_email}/messages"
        print(url)

        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
            "Prefer": 'outlook.body-content-type="text"',
        }

        formatted_date = date_filter.strftime("%Y-%m-%dT%H:%M:%SZ")
        filters = [f"receivedDateTime ge {formatted_date} "]
        if from_email:
            senders = [from_email] if isinstance(from_email, str) else list(from_email)
            sender_clauses = [f"from/emailAddress/address eq '{s}'" for s in senders]
            joined = " or ".join(sender_clauses)
            if len(sender_clauses) > 1:
                joined = f"({joined})"
            filters.append(f"and {joined} ")

        params = {
            "$top": top,
            "$filter": "".join(filters),
            "$select": "subject,from,toRecipients,receivedDateTime,isRead,body",
            "$orderby": "receivedDateTime desc",
        }

        print(params)
        try:
            response = requests.get(url, headers=headers, params=params)
            response.raise_for_status()
            messages_data = response.json().get("value", [])
            messages = [EmailMessage.model_validate(msg) for msg in messages_data]
            print(f"{len(messages)} messages obtained")
            return messages
        except requests.exceptions.RequestException as e:
            print(f"Error getting messages: {e}")
            if response.text:
                print(f"Details: {response.text}")
            return None


def write_messages_to_file(messages: list[EmailMessage], filepath: str = "emails_output.txt") -> None:
    """Write messages with full body content to a file."""
    if not messages:
        print("No messages to write")
        return

    with open(filepath, "w", encoding="utf-8") as f:
        for i, msg in enumerate(messages, 1):
            f.write("\n" + "=" * 80 + "\n")
            f.write(f"MESSAGE #{i}\n")
            f.write("=" * 80 + "\n")
            f.write(f"Subject: {msg.subject}\n")

            if msg.sender:
                sender_name = msg.sender.email_address.name or "Unknown"
                sender_address = msg.sender.email_address.address or "N/A"
                f.write(f"From: {sender_name} <{sender_address}>\n")

            if msg.to_recipients:
                alias_list = [r.email_address.address or "N/A" for r in msg.to_recipients]
                f.write(f"To: {', '.join(alias_list)}\n")

            f.write(f"Received: {msg.received_date_time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"Status: {'Read' if msg.is_read else 'Unread'}\n")
            f.write(f"Content-Type: {msg.body.content_type}\n")
            f.write("-" * 80 + "\n")
            f.write("BODY:\n")
            f.write("-" * 80 + "\n")
            f.write(msg.body.content + "\n")
            f.write("=" * 80 + "\n")

    print(f"Messages written to {filepath}")


def main():
    # Configuration
    CLIENT_ID = os.environ.get("CLIENT_ID")
    TENANT_ID = os.environ.get("TENANT_ID")
    CLIENT_SECRET = os.environ.get("CLIENT_SECRET")
    USER_EMAIL = os.environ.get("USER_EMAIL")
    checker = OutlookInboxChecker(CLIENT_ID, TENANT_ID, CLIENT_SECRET)

    if not checker.authenticate():
        print("\nCould not get access token.")
        print("Verify that:")
        print("  1. The credentials are correct")
        print("  2. The application has the necessary permissions in Azure AD")
        print("  3. Application type permissions have been granted (not Delegated)")
        return

    now_utc = datetime.now(timezone.utc)
    messages = checker.get_messages(
        USER_EMAIL, date_filter=now_utc - timedelta(hours=2), top=10, from_email="customercare@notifications.t-mobile.com"
    )

    if messages:
        checker.display_messages(messages)
        write_messages_to_file(messages)
    else:
        print("\nCould not get messages.")
        print("Verify that:")
        print("  1. The user email is correct")
        print("  2. The application has 'Mail.Read' or 'Mail.ReadWrite' permissions")
        print("  3. Administrator consent has been given to the permissions")
        print("  4. You're using the right filters")


if __name__ == "__main__":
    main()
