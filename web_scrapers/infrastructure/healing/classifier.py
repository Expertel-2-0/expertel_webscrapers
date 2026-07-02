"""Classify a locator failure before deciding what to do about it.

A CAPTCHA or bot-detection page *looks like* a missing selector (the expected
element is gone), so classification runs first: challenge pages must never be
sent to the AI healer - the existing solver stack / session-hygiene work owns
those, and repeated automated poking at a challenge page escalates bot
suspicion on the carrier side.
"""

import re

CAPTCHA_BLOCKED = "captcha_blocked"
BOT_DETECTED = "bot_detected"
SELECTOR_NOT_FOUND = "selector_not_found"

_CAPTCHA_MARKERS = [
    r"challenges\.cloudflare\.com",
    r"cf-turnstile",
    r"g-recaptcha",
    r"grecaptcha",
    r"h-captcha",
    r"hcaptcha\.com",
    r"verify (?:that )?you(?:'re| are) (?:a )?human",
    r"captcha",
    r"arkoselabs",
    r"funcaptcha",
]

_BOT_MARKERS = [
    r"access denied",
    r"request unsuccessful\. incapsula",
    r"perimeterx",
    r"px-captcha",
    r"_abck",  # Akamai
    r"akamai",
    r"reference #\d+\.[0-9a-f]+",  # Akamai denial page reference
    r"you have been blocked",
    r"unusual traffic",
    r"attention required!\s*\|\s*cloudflare",
]

_CAPTCHA_RE = re.compile("|".join(_CAPTCHA_MARKERS), re.IGNORECASE)
_BOT_RE = re.compile("|".join(_BOT_MARKERS), re.IGNORECASE)


def classify_failure(page_content: str, url: str) -> str:
    """Return one of CAPTCHA_BLOCKED / BOT_DETECTED / SELECTOR_NOT_FOUND."""
    haystack = f"{url}\n{page_content or ''}"
    if _CAPTCHA_RE.search(haystack):
        return CAPTCHA_BLOCKED
    if _BOT_RE.search(haystack):
        return BOT_DETECTED
    return SELECTOR_NOT_FOUND


class CaptchaBlockedError(Exception):
    """Challenge page detected where a selector was expected. Not healable by
    AI - route to the carrier's CAPTCHA solver / retry after solving."""


class BotDetectedError(Exception):
    """Hard bot block (Akamai/PerimeterX/access denied). Not healable and not
    solvable - needs session/fingerprint hygiene. Fail fast with evidence."""
