"""The AI heal step: given failure evidence and step intent, ask Claude for a
replacement locator, validate it against the live page, and return it.

Guardrails (non-negotiable, enforced here):
- Never heals authentication/MFA/CAPTCHA steps (caller-context + URL deny).
- Candidate must resolve to exactly one element on the current page.
- Candidate element's text/accessible name must not match the destructive
  denylist (delete / cancel service / purchase / submit order / pay ...).
- Global daily call cap; per-job attempt cap enforced by the wrapper.
- DOM sent to the API has scripts stripped and input values blanked
  (evidence.trim_dom); credentials never leave the box.
"""

import base64
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional

from web_scrapers.infrastructure.healing.config import HealingConfig
from web_scrapers.infrastructure.healing.evidence import Evidence

logger = logging.getLogger(__name__)

# Login/MFA pages are never healed - a wrong AI click there risks lockouts.
_AUTH_URL_RE = re.compile(r"login|signin|sign-in|auth|mfa|otp|verify|password|2fa", re.IGNORECASE)
# Caller-side deny: if the failing call originated in an auth strategy module
# or an auth-ish method, healing is skipped.
_AUTH_CONTEXT_RE = re.compile(r"auth|login|mfa|otp|password|captcha|2fa", re.IGNORECASE)
# A healed element whose visible text matches this is rejected outright.
_DESTRUCTIVE_RE = re.compile(
    r"delete|remove|cancel (?:service|plan|line|account)|deactivate|suspend|purchase|buy now|"
    r"submit order|place order|pay(?:ment)? now|confirm order|checkout|upgrade|add line",
    re.IGNORECASE,
)

_SYSTEM_PROMPT = (
    "You repair broken web-scraper locators. A Playwright selector stopped matching on a telecom "
    "carrier portal, most likely because the carrier changed their UI. Using the page DOM (and "
    "screenshot when provided), find the element the step intended to interact with and return a "
    "replacement locator.\n\n"
    "Rules:\n"
    "- Prefer resilient locators: id, stable data-* attributes, aria-label, visible text. Use CSS "
    "where possible; XPath only when text-matching requires it (e.g. //button[contains(., 'Download')]). "
    "Never return absolute positional XPaths like /html/body/div[3]/...\n"
    "- The locator must match exactly ONE element.\n"
    "- Never target login, password, MFA, CAPTCHA, purchase, or cancellation controls.\n"
    "- If you cannot confidently identify the intended element, return {\"found\": false}.\n\n"
    'Respond with ONLY a JSON object: {"found": true, "selector_type": "css"|"xpath", '
    '"selector": "...", "reason": "one sentence"}'
)


@dataclass
class HealResult:
    healed: bool
    selector: str = ""
    selector_type: str = "css"
    reason: str = ""


class DailyCallBudget:
    """Counts Claude calls per UTC day in a sidecar JSON file."""

    def __init__(self, overrides_path: str, max_calls: int):
        self.path = f"{overrides_path}.budget"
        self.max_calls = max_calls

    def try_consume(self) -> bool:
        today = time.strftime("%Y-%m-%d")
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}
        count = data.get(today, 0)
        if count >= self.max_calls:
            logger.warning(f"Healing daily call cap reached ({self.max_calls}); skipping AI heal")
            return False
        try:
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump({today: count + 1}, f)
        except Exception as exc:
            logger.warning(f"Could not persist healing budget ({exc}); allowing call")
        return True


def is_auth_context(intent: str, url: str) -> bool:
    return bool(_AUTH_CONTEXT_RE.search(intent or "")) or bool(_AUTH_URL_RE.search(url or ""))


class SelectorHealer:
    def __init__(self, config: HealingConfig):
        self.config = config
        self.budget = DailyCallBudget(config.overrides_path, config.daily_max_calls)
        self._client = None

    def _get_client(self):
        if self._client is None:
            import anthropic  # deferred: only imported when healing actually runs

            self._client = anthropic.Anthropic()
        return self._client

    def heal(self, page, evidence: Evidence, intent: str, failed_selector: str) -> HealResult:
        """Ask Claude for a replacement locator and validate it on the live page.
        Any failure returns HealResult(healed=False) - the caller then fails the
        step exactly as it would have without healing.
        """
        if is_auth_context(intent, evidence.url):
            logger.info(f"Healing denied for auth context: intent={intent!r} url={evidence.url}")
            return HealResult(False, reason="auth_context_denied")
        if not evidence.trimmed_dom:
            return HealResult(False, reason="no_dom_captured")
        if not self.budget.try_consume():
            return HealResult(False, reason="daily_budget_exhausted")

        try:
            proposal = self._ask_claude(evidence, intent, failed_selector)
        except Exception as exc:
            logger.warning(f"Healing API call failed (job continues as normal failure): {exc}")
            return HealResult(False, reason=f"api_error: {exc}")

        if not proposal or not proposal.get("found"):
            return HealResult(False, reason="model_could_not_identify_element")

        selector = (proposal.get("selector") or "").strip()
        selector_type = proposal.get("selector_type", "css")
        if not selector or selector_type not in ("css", "xpath"):
            return HealResult(False, reason="invalid_proposal")

        ok, why = self._validate_on_page(page, selector, selector_type)
        if not ok:
            logger.info(f"Healed candidate rejected ({why}): {selector!r}")
            return HealResult(False, reason=f"validation_failed: {why}")

        logger.info(
            f"HEALED selector. intent={intent!r} original={failed_selector!r} "
            f"-> {selector_type}={selector!r} ({proposal.get('reason', '')})"
        )
        return HealResult(True, selector=selector, selector_type=selector_type, reason=proposal.get("reason", ""))

    def _ask_claude(self, evidence: Evidence, intent: str, failed_selector: str) -> Optional[dict]:
        content = [
            {
                "type": "text",
                "text": (
                    f"Step intent (derived from scraper code context): {intent}\n"
                    f"Failed selector: {failed_selector}\n"
                    f"Current URL: {evidence.url}\n\n"
                    f"Page DOM (scripts/styles stripped, input values blanked):\n{evidence.trimmed_dom}"
                ),
            }
        ]
        if self.config.include_screenshot and evidence.screenshot_path:
            try:
                with open(evidence.screenshot_path, "rb") as f:
                    img_b64 = base64.standard_b64encode(f.read()).decode("utf-8")
                content.insert(
                    0,
                    {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                )
            except Exception:
                pass  # DOM-only healing still works

        response = self._get_client().messages.create(
            model=self.config.model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
        )
        text = next((b.text for b in response.content if b.type == "text"), "")
        usage = getattr(response, "usage", None)
        if usage:
            logger.info(f"Healing API usage: in={usage.input_tokens} out={usage.output_tokens} model={self.config.model}")
        return _parse_json_object(text)

    def _validate_on_page(self, page, selector: str, selector_type: str) -> tuple:
        resolved = f"xpath={selector}" if selector_type == "xpath" else selector
        try:
            locator = page.locator(resolved)
            count = locator.count()
        except Exception as exc:
            return False, f"locator_error: {exc}"
        if count != 1:
            return False, f"matches_{count}_elements"
        try:
            text = (locator.inner_text(timeout=2000) or "")[:200]
        except Exception:
            text = ""
        try:
            aria = locator.get_attribute("aria-label", timeout=1000) or ""
        except Exception:
            aria = ""
        if _DESTRUCTIVE_RE.search(f"{text} {aria}"):
            return False, "destructive_control"
        return True, ""


def _parse_json_object(text: str) -> Optional[dict]:
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            try:
                return json.loads(match.group(0))
            except json.JSONDecodeError:
                return None
    return None
