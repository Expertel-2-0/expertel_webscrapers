"""HealingPlaywrightWrapper: PlaywrightWrapper with selector self-healing.

Only constructed when HEALING_ENABLED=true (see factory.build_browser_wrapper).
Overrides the single _wait_for choke point that all action methods route
through, so every strategy gets healing with zero per-strategy changes.

On a selector timeout, in order:
 1. Known override for (carrier, strategy, selector)? Try it (no AI call).
 2. Classify the page: CAPTCHA / bot-detection pages are never healed - they
    raise typed errors so the failure is legible and retries don't burn.
 3. Ask Claude for a replacement locator (healer.py guardrails apply),
    validate it live, persist it as an override, continue the job.
 4. Anything fails -> re-raise the original timeout: the job fails exactly as
    it would have without healing, with evidence saved in the job folder.
"""

import inspect
import logging
import time
from typing import Optional

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

from web_scrapers.infrastructure.healing.classifier import (
    BOT_DETECTED,
    CAPTCHA_BLOCKED,
    BotDetectedError,
    CaptchaBlockedError,
    classify_failure,
)
from web_scrapers.infrastructure.healing.config import HealingConfig
from web_scrapers.infrastructure.healing.evidence import capture_evidence
from web_scrapers.infrastructure.healing.healer import SelectorHealer, is_auth_context
from web_scrapers.infrastructure.healing.override_store import OverrideStore
from web_scrapers.infrastructure.playwright.browser_wrapper import PlaywrightWrapper

logger = logging.getLogger(__name__)


def _intent_from_stack() -> str:
    """Derive step intent from the calling strategy frame, e.g.
    'bell/daily_usage.py::_click_download_all'. No per-strategy changes needed;
    strategies can enrich this later with explicit intent strings if the
    auto-context proves too thin."""
    for frame_info in inspect.stack():
        filename = frame_info.filename.replace("\\", "/")
        if "/infrastructure/scrapers/" in filename or "auth_strategies" in filename:
            parts = filename.split("/")
            location = "/".join(parts[-2:])
            return f"{location}::{frame_info.function}"
    return "unknown"


class HealingPlaywrightWrapper(PlaywrightWrapper):
    def __init__(self, page, config: HealingConfig):
        super().__init__(page)
        self.healing_config = config
        self.override_store = OverrideStore(config.overrides_path)
        self.healer = SelectorHealer(config)
        # Per-job context, set by ScraperBaseStrategy._prepare_job_directory()
        self._carrier: str = ""
        self._strategy: str = ""
        self._job_dir: Optional[str] = None
        self._heals_this_job = 0

    def set_healing_context(self, carrier: str, strategy: str, job_dir: str) -> None:
        self._carrier = (carrier or "").lower()
        self._strategy = strategy
        self._job_dir = job_dir
        self._heals_this_job = 0

    def _wait_for(self, resolved: str, timeout: int, raw_selector: str, selector_type: str) -> str:
        try:
            self.page.wait_for_selector(resolved, timeout=timeout)
            return resolved
        except PlaywrightTimeoutError as original_error:
            if not self.healing_config.carrier_enabled(self._carrier):
                raise
            healed = self._attempt_recovery(resolved, timeout, raw_selector, selector_type)
            if healed is not None:
                return healed
            raise original_error

    def _attempt_recovery(
        self, resolved: str, timeout: int, raw_selector: str, selector_type: str
    ) -> Optional[str]:
        """Returns a resolved selector that is present on the page, or None."""
        started = time.monotonic()
        intent = _intent_from_stack()
        logger.warning(f"Selector timeout ({self._carrier}/{self._strategy}, {intent}): {raw_selector!r}")

        # 1. Known override - free, no AI.
        override = self.override_store.get(self._carrier, self._strategy, raw_selector)
        if override:
            override_resolved = self._resolve_selector(override["selector"], override["selector_type"])
            try:
                self.page.wait_for_selector(override_resolved, timeout=min(timeout, 10000))
                self.override_store.record_use(self._carrier, self._strategy, raw_selector)
                logger.info(f"Override applied for {raw_selector!r} -> {override['selector']!r}")
                return override_resolved
            except PlaywrightTimeoutError:
                # Carrier changed again; failure is the invalidation signal.
                self.override_store.invalidate(self._carrier, self._strategy, raw_selector)

        # 2. Classify before healing: challenge pages are not healable.
        evidence = capture_evidence(self.page, self._job_dir, raw_selector, self.healing_config.dom_max_chars)
        failure_class = classify_failure(evidence.trimmed_dom, evidence.url)
        if failure_class == CAPTCHA_BLOCKED:
            raise CaptchaBlockedError(
                f"CAPTCHA/challenge page where selector {raw_selector!r} was expected "
                f"(url={evidence.url}, evidence={evidence.screenshot_path})"
            )
        if failure_class == BOT_DETECTED:
            raise BotDetectedError(
                f"Bot-detection block where selector {raw_selector!r} was expected "
                f"(url={evidence.url}, evidence={evidence.screenshot_path})"
            )

        # 3. AI heal, within per-job and wall-clock budgets.
        if self._heals_this_job >= self.healing_config.max_heals_per_job:
            logger.warning("Per-job heal cap reached; failing step normally")
            return None
        if is_auth_context(intent, evidence.url):
            logger.info("Auth context - healing denied; failing step normally")
            return None
        if time.monotonic() - started > self.healing_config.step_budget_seconds:
            logger.warning("Healing step budget exceeded before AI call; failing step normally")
            return None

        self._heals_this_job += 1
        result = self.healer.heal(self.page, evidence, intent, raw_selector)
        if not result.healed:
            logger.info(f"Healing did not produce a fix ({result.reason}); failing step normally")
            return None

        healed_resolved = self._resolve_selector(result.selector, result.selector_type)
        try:
            self.page.wait_for_selector(healed_resolved, timeout=10000)
        except PlaywrightTimeoutError:
            logger.warning("Healed selector validated but not waitable; failing step normally")
            return None

        self.override_store.put(
            carrier=self._carrier,
            strategy=self._strategy,
            selector=raw_selector,
            healed_selector=result.selector,
            selector_type=result.selector_type,
            url=evidence.url,
            intent=intent,
        )
        return healed_resolved
