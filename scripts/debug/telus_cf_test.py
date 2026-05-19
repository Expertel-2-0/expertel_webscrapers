"""
Telus Cloudflare debug runner.

Opens real Chrome via CDP (same path the production Telus scraper uses),
navigates to the Telus login page, and lets you watch what Cloudflare's
Turnstile does in real time. Browser stays open at the end until you press
Enter — useful for poking at the DOM in DevTools.

Forces BROWSER_HEADLESS=false so you can actually see the page.

Usage:
    poetry run python scripts/debug/telus_cf_test.py
        # Just opens the login page and waits on Cloudflare. No login attempt.

    poetry run python scripts/debug/telus_cf_test.py --credential-id 42
        # Pulls username/password from CarrierPortalCredential row 42 and tries to log in.

    poetry run python scripts/debug/telus_cf_test.py --username foo --password bar
        # Inline credentials (avoid for shared shells).
"""

import argparse
import io
import logging
import os
import sys
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", line_buffering=True)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

# Force headful BEFORE any factory imports — env is read at module load
os.environ["BROWSER_HEADLESS"] = "false"

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from web_scrapers.domain.entities.session import Carrier as CarrierEnum, Credentials  # noqa: E402
from web_scrapers.infrastructure.django.models import CarrierPortalCredential  # noqa: E402
from web_scrapers.infrastructure.playwright.auth_strategies import TelusAuthStrategy  # noqa: E402
from web_scrapers.infrastructure.playwright.browser_factory import BrowserManager  # noqa: E402
from web_scrapers.infrastructure.playwright.browser_wrapper import PlaywrightWrapper  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("telus_cf_test")


def resolve_credentials(args) -> Credentials | None:
    if args.credential_id:
        row = CarrierPortalCredential.objects.select_related("carrier", "client").get(id=args.credential_id)
        logger.info(
            f"Using credential id={row.id} carrier={row.carrier.name} "
            f"client={row.client.name} username={row.username}"
        )
        return Credentials(id=row.id, username=row.username, password=row.password, carrier=CarrierEnum.TELUS)
    if args.username and args.password:
        return Credentials(username=args.username, password=args.password, carrier=CarrierEnum.TELUS)
    return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--credential-id", type=int, help="CarrierPortalCredential.id to use for login")
    p.add_argument("--username", help="Inline username (overrides --credential-id if both set)")
    p.add_argument("--password", help="Inline password")
    p.add_argument(
        "--no-login",
        action="store_true",
        help="Skip login attempt — just open the login page and watch Cloudflare",
    )
    args = p.parse_args()

    creds = None if args.no_login else resolve_credentials(args)

    manager = BrowserManager()
    browser, context = manager.get_browser(cdp=True)
    page = context.new_page()
    wrapper = PlaywrightWrapper(page)
    auth = TelusAuthStrategy(wrapper)

    try:
        if creds:
            logger.info("Running full login flow with credentials — watch the Cloudflare phase")
            ok = auth.login(creds)
            logger.info(f"login() returned: {ok}")
        else:
            logger.info("Navigating to Telus login URL — no credential entry will be attempted")
            wrapper.goto(auth.get_login_url(), wait_until="domcontentloaded")
            wrapper.wait_for_page_load()
            if auth._is_cloudflare_challenge():
                logger.info("Cloudflare challenge detected — calling _wait_for_cloudflare_resolution()")
                resolved = auth._wait_for_cloudflare_resolution()
                logger.info(f"Cloudflare resolved: {resolved}")
            else:
                logger.info("No Cloudflare challenge detected on first load")

        print("\n" + "=" * 70)
        print("Browser is left open. Inspect freely in DevTools.")
        print("Press Enter in this terminal to close the browser and exit.")
        print("=" * 70)
        try:
            input()
        except EOFError:
            pass

    finally:
        try:
            page.close()
        except Exception:
            pass
        try:
            context.close()
        except Exception:
            pass
        if browser:
            try:
                browser.close()
            except Exception:
                pass
        manager.cleanup_all()


if __name__ == "__main__":
    main()
