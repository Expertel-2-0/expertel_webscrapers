"""Single decision point for which browser wrapper the system runs with.

HEALING_ENABLED unset/false -> plain PlaywrightWrapper, byte-for-byte the
current production behavior. true -> HealingPlaywrightWrapper.
"""

import logging

from web_scrapers.infrastructure.playwright.browser_wrapper import PlaywrightWrapper

logger = logging.getLogger(__name__)


def build_browser_wrapper(page) -> PlaywrightWrapper:
    from web_scrapers.infrastructure.healing.config import load_config

    config = load_config()
    if not config.enabled:
        return PlaywrightWrapper(page)
    try:
        from web_scrapers.infrastructure.healing.healing_wrapper import HealingPlaywrightWrapper

        logger.info(
            f"Self-healing wrapper active (model={config.model}, "
            f"carriers={sorted(config.carriers) or 'all'})"
        )
        return HealingPlaywrightWrapper(page, config)
    except Exception as exc:
        # Healing must never take the scraper down - fall back to plain wrapper.
        logger.error(f"Failed to initialize healing wrapper, falling back to plain: {exc}")
        return PlaywrightWrapper(page)
