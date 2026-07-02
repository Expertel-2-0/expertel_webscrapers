"""Replay harness: exercise the full self-healing loop on demand, without
waiting for a carrier to actually break. Loads a local HTML fixture (or any
saved page snapshot), asks for a deliberately broken selector, and runs the
real heal path end-to-end (evidence -> Claude -> validation -> override).

Requires: ANTHROPIC_API_KEY, playwright browsers installed.

Usage:
  poetry run python scripts/healing_replay.py                       # bundled fixture
  poetry run python scripts/healing_replay.py path/to/snapshot.html "//old/broken/xpath"

Also the regression test for prompt changes: run it after touching
healer._SYSTEM_PROMPT and confirm the healed selector still lands on the
download button.
"""

import os
import sys
import tempfile

os.environ.setdefault("HEALING_ENABLED", "true")

# Django is optional here: the healing modules have no Django dependency, but
# on the executor box settings load the .env. Skip silently when absent.
try:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    import django

    django.setup()
except Exception:
    pass

from playwright.sync_api import sync_playwright  # noqa: E402

from web_scrapers.infrastructure.healing.config import load_config  # noqa: E402
from web_scrapers.infrastructure.healing.healing_wrapper import HealingPlaywrightWrapper  # noqa: E402

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "healing_fixture.html")
# The fixture's download button has id="download-all-statements"; this xpath
# pretends the carrier moved it (the old absolute path no longer matches).
BROKEN_SELECTOR = "/html/body/div[1]/main/section[2]/div[3]/button[1]"


def main() -> int:
    html_path = sys.argv[1] if len(sys.argv) > 1 else FIXTURE
    broken = sys.argv[2] if len(sys.argv) > 2 else BROKEN_SELECTOR

    with tempfile.TemporaryDirectory() as job_dir, sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(f"file://{os.path.abspath(html_path)}")

        config = load_config()
        # Isolated override store so replay runs don't pollute the real one.
        object.__setattr__(config, "overrides_path", os.path.join(job_dir, "overrides.json"))
        wrapper = HealingPlaywrightWrapper(page, config)
        wrapper.set_healing_context("replay", "ReplayHarness", job_dir)

        print(f"Fixture: {html_path}")
        print(f"Broken selector: {broken}")
        print("Attempting click through healing wrapper (5s primary timeout)...")
        try:
            wrapper.click_element(broken, timeout=5000, selector_type="xpath")
            healed = wrapper.override_store.get("replay", "ReplayHarness", broken)
            print(f"\nHEALED and clicked. Override stored: {healed}")
            print(f"Page marker after click: {page.locator('#click-result').inner_text()}")
            return 0
        except Exception as exc:
            print(f"\nHealing did not recover: {type(exc).__name__}: {exc}")
            print(f"Evidence in: {job_dir} (deleted on exit - rerun with a persistent dir to inspect)")
            return 1
        finally:
            browser.close()


if __name__ == "__main__":
    sys.exit(main())
