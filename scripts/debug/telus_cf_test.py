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

    poetry run python scripts/debug/telus_cf_test.py --provoke
        # Wipes the persistent telus_cdp profile dir first to force a fresh CF
        # challenge (useful from a residential IP where Turnstile usually
        # auto-resolves quickly).

    poetry run python scripts/debug/telus_cf_test.py --humanlike
        # When CF appears and doesn't auto-resolve in ~10s, run a human-like
        # mouse trajectory + click instead of the production el.click().
        # Prints iframe selector + bounding box so you can compare against
        # what was clicked.

    poetry run python scripts/debug/telus_cf_test.py --credential-id 42
        # Pulls username/password from CarrierPortalCredential row 42 and
        # tries to log in (after CF resolves).
"""

import argparse
import io
import logging
import os
import random
import shutil
import sys
import time
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


def wipe_telus_cdp_profile() -> None:
    """Delete the persistent telus_cdp profile dir so Chrome starts cookie-less.
    Cleanest way to provoke a fresh CF challenge from a residential IP.
    """
    profile = Path.cwd() / "browser_profiles" / "telus_cdp_profile"
    if profile.exists():
        logger.info(f"[provoke] wiping {profile}")
        shutil.rmtree(profile, ignore_errors=True)
    else:
        logger.info(f"[provoke] no profile to wipe at {profile}")


def find_cf_iframe(page):
    """Returns (frame_element, frame, selector_used) for the Turnstile iframe, or (None, None, None)."""
    selectors = [
        "//iframe[contains(@src, 'challenges.cloudflare.com')]",
        "//iframe[contains(@src, 'turnstile')]",
        "//iframe[contains(@title, 'challenge')]",
    ]
    for sel in selectors:
        try:
            frame_element = page.query_selector(sel)
            if frame_element:
                frame = frame_element.content_frame()
                if frame:
                    return frame_element, frame, sel
        except Exception:
            continue
    return None, None, None


def humanlike_iframe_click(
    page,
    frame_element,
    target_offset=(28, 30),
    jitter_px=4,
    hover_ms_range=(180, 420),
    move_steps=25,
) -> dict:
    """Click the Turnstile checkbox using a curved-ish mouse trajectory + hover dwell.

    The Turnstile widget puts its checkbox at roughly (25-30, 25-30) inside the
    iframe; we click in main-page coordinates so the event has a real mouse
    history. Returns a dict with what we did so the caller can log it.
    """
    box = frame_element.bounding_box()
    if not box:
        return {"clicked": False, "reason": "iframe has no bounding_box"}

    jitter = lambda: random.uniform(-jitter_px, jitter_px)
    target_x = box["x"] + target_offset[0] + jitter()
    target_y = box["y"] + target_offset[1] + jitter()

    # Bounce off a random waypoint above the iframe to leave a more natural trail
    waypoint_x = target_x + random.uniform(-180, 180)
    waypoint_y = target_y - random.uniform(60, 180)

    page.mouse.move(waypoint_x, waypoint_y, steps=max(8, move_steps // 3))
    time.sleep(random.uniform(0.04, 0.12))
    page.mouse.move(target_x, target_y, steps=move_steps)
    time.sleep(random.uniform(*hover_ms_range) / 1000)
    page.mouse.down()
    time.sleep(random.uniform(0.04, 0.11))
    page.mouse.up()

    return {
        "clicked": True,
        "iframe_box": box,
        "waypoint": (round(waypoint_x, 1), round(waypoint_y, 1)),
        "target": (round(target_x, 1), round(target_y, 1)),
    }


def diagnose_cf(page, auth) -> None:
    """Print what CF state we see and the iframe geometry, for triage."""
    is_challenge = auth._is_cloudflare_challenge()
    logger.info(f"[diag] _is_cloudflare_challenge() = {is_challenge}")
    if not is_challenge:
        return
    frame_element, frame, sel = find_cf_iframe(page)
    logger.info(f"[diag] iframe selector matched: {sel}")
    if frame_element:
        box = frame_element.bounding_box()
        logger.info(f"[diag] iframe bounding_box: {box}")
    if frame:
        state = auth._cloudflare_widget_state(frame)
        logger.info(f"[diag] widget state: {state}")


def resolve_credentials(args):
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


def watch_cf_with_humanlike(page, auth, pre_click_wait=10, post_click_wait=60, force_click=False) -> bool:
    """Variant of _wait_for_cloudflare_resolution that swaps the production click
    for humanlike_iframe_click(). Returns True if CF cleared.

    When force_click=True, skips the pre-click auto-resolve wait and goes
    straight to the click. Useful for verifying the click implementation
    visually on residential IPs where CF would otherwise auto-resolve in
    a couple seconds before the click path runs.
    """
    if not force_click:
        deadline = time.time() + pre_click_wait
        while time.time() < deadline:
            time.sleep(1)
            if not auth._is_cloudflare_challenge():
                logger.info("CF auto-resolved during pre-click wait")
                return True
    else:
        logger.info("[force-click] skipping pre-click wait, going straight to click")

    diagnose_cf(page, auth)
    frame_element, frame, sel = find_cf_iframe(page)
    if not frame_element:
        logger.error("No CF iframe found; cannot click")
        return False

    # Wait until widget is actionable (idle/unknown), not mid-verifying
    actionable_deadline = time.time() + 10
    while time.time() < actionable_deadline:
        state = auth._cloudflare_widget_state(frame)
        if state == "success":
            return True
        if state in ("fail", "timeout", "expired", "error"):
            logger.warning(f"Widget in '{state}' state before click; skipping")
            return False
        if state == "verifying":
            time.sleep(1)
            continue
        break

    result = humanlike_iframe_click(page, frame_element)
    logger.info(f"[humanlike-click] result: {result}")

    # Watch the widget evolve
    deadline = time.time() + post_click_wait
    last_state = None
    while time.time() < deadline:
        time.sleep(2)
        if not auth._is_cloudflare_challenge():
            logger.info("CF cleared after humanlike click")
            return True
        frame_element, frame, _ = find_cf_iframe(page)
        if frame:
            state = auth._cloudflare_widget_state(frame)
            if state != last_state:
                logger.info(f"[post-click] widget state -> {state}")
                last_state = state
            if state == "success":
                return True
            if state in ("fail", "timeout", "expired", "error"):
                logger.error(f"Widget reports '{state}' after humanlike click")
                return False

    logger.error("CF did not clear within post-click window")
    return False


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
    p.add_argument(
        "--provoke",
        action="store_true",
        help="Wipe the telus_cdp profile dir before launching so CF challenges from scratch",
    )
    p.add_argument(
        "--humanlike",
        action="store_true",
        help="If CF appears, use a humanlike mouse trajectory + click instead of the production el.click()",
    )
    p.add_argument(
        "--force-click",
        action="store_true",
        help="Skip the pre-click auto-resolve wait and dispatch the humanlike click immediately (implies --humanlike)",
    )
    args = p.parse_args()

    if args.provoke:
        wipe_telus_cdp_profile()

    creds = None if args.no_login else resolve_credentials(args)

    manager = BrowserManager()
    browser, context = manager.get_browser(cdp=True)
    page = context.new_page()
    wrapper = PlaywrightWrapper(page)
    auth = TelusAuthStrategy(wrapper)

    try:
        logger.info(f"Navigating to {auth.get_login_url()}")
        wrapper.goto(auth.get_login_url(), wait_until="domcontentloaded")
        wrapper.wait_for_page_load()
        time.sleep(2)

        use_humanlike = args.humanlike or args.force_click
        if auth._is_cloudflare_challenge():
            logger.warning("Cloudflare challenge detected on initial load")
            if use_humanlike:
                ok = watch_cf_with_humanlike(page, auth, force_click=args.force_click)
                logger.info(f"watch_cf_with_humanlike() returned: {ok}")
            else:
                resolved = auth._wait_for_cloudflare_resolution()
                logger.info(f"_wait_for_cloudflare_resolution() returned: {resolved}")
        else:
            logger.info("No Cloudflare challenge on initial load")

        if creds and not auth._is_cloudflare_challenge():
            logger.info("Proceeding to full login flow")
            ok = auth.login(creds)
            logger.info(f"login() returned: {ok}")

        print("\n" + "=" * 70)
        print("Browser left open. Inspect freely in DevTools.")
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
