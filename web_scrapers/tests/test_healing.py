"""Unit tests for the self-healing module. No browser or API key required.

Run: python manage.py test web_scrapers.tests.test_healing
"""

import json
import os
import tempfile
import unittest
from unittest import mock

from web_scrapers.infrastructure.healing.classifier import (
    BOT_DETECTED,
    CAPTCHA_BLOCKED,
    SELECTOR_NOT_FOUND,
    classify_failure,
)
from web_scrapers.infrastructure.healing.config import HealingConfig, load_config
from web_scrapers.infrastructure.healing.evidence import trim_dom
from web_scrapers.infrastructure.healing.healer import DailyCallBudget, _parse_json_object, is_auth_context
from web_scrapers.infrastructure.healing.override_store import OverrideStore


class ClassifierTests(unittest.TestCase):
    def test_turnstile_is_captcha(self):
        html = '<iframe src="https://challenges.cloudflare.com/turnstile/v0/..."></iframe>'
        self.assertEqual(classify_failure(html, "https://www.telus.com/my-telus"), CAPTCHA_BLOCKED)

    def test_recaptcha_is_captcha(self):
        self.assertEqual(classify_failure('<div class="g-recaptcha"></div>', "https://bell.ca"), CAPTCHA_BLOCKED)

    def test_akamai_denial_is_bot_detected(self):
        html = "<h1>Access Denied</h1><p>Reference #18.abc123</p>"
        self.assertEqual(classify_failure(html, "https://www.rogers.com/x"), BOT_DETECTED)

    def test_normal_page_is_selector_not_found(self):
        html = "<html><body><h1>My Bills</h1><button id='dl'>Download</button></body></html>"
        self.assertEqual(classify_failure(html, "https://businessportal.bell.ca/bills"), SELECTOR_NOT_FOUND)

    def test_captcha_wins_over_bot_markers(self):
        html = "<div class='px-captcha'><div class='g-recaptcha'></div></div>"
        self.assertEqual(classify_failure(html, "https://x.com"), CAPTCHA_BLOCKED)


class TrimDomTests(unittest.TestCase):
    def test_strips_scripts_and_styles(self):
        html = "<html><script>secret()</script><style>.a{}</style><body><p>keep</p></body></html>"
        out = trim_dom(html)
        self.assertNotIn("secret", out)
        self.assertNotIn(".a{}", out)
        self.assertIn("keep", out)

    def test_blanks_input_values(self):
        html = '<input name="password" value="hunter2"><input name="acct" value=\'12345\'>'
        out = trim_dom(html)
        self.assertNotIn("hunter2", out)
        self.assertNotIn("12345", out)
        self.assertIn("password", out)  # structure kept, value gone

    def test_truncates(self):
        out = trim_dom("<p>" + "x" * 100000 + "</p>", max_chars=1000)
        self.assertLess(len(out), 1100)
        self.assertIn("truncated", out)


class OverrideStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = OverrideStore(os.path.join(self.tmp.name, "overrides.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_roundtrip(self):
        self.store.put("bell", "BellDailyUsage", "/html/x", "#download-all", "css", url="u", intent="i")
        got = self.store.get("bell", "BellDailyUsage", "/html/x")
        self.assertEqual(got, {"selector": "#download-all", "selector_type": "css"})

    def test_miss_returns_none(self):
        self.assertIsNone(self.store.get("bell", "X", "nope"))

    def test_invalidate(self):
        self.store.put("bell", "S", "old", "new", "css")
        self.store.invalidate("bell", "S", "old")
        self.assertIsNone(self.store.get("bell", "S", "old"))

    def test_record_use_increments(self):
        self.store.put("telus", "S", "old", "new", "xpath")
        self.store.record_use("telus", "S", "old")
        self.store.record_use("telus", "S", "old")
        data = json.load(open(self.store.path))
        self.assertEqual(data["telus|S|old"]["use_count"], 2)

    def test_corrupt_file_starts_empty(self):
        with open(self.store.path, "w") as f:
            f.write("{not json")
        self.assertIsNone(self.store.get("a", "b", "c"))


class ConfigTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            config = load_config()
            self.assertFalse(config.enabled)
            self.assertFalse(config.carrier_enabled("bell"))

    def test_carrier_allowlist(self):
        with mock.patch.dict(os.environ, {"HEALING_ENABLED": "true", "HEALING_CARRIERS": "bell, telus"}):
            config = load_config()
            self.assertTrue(config.carrier_enabled("bell"))
            self.assertTrue(config.carrier_enabled("Telus"))
            self.assertFalse(config.carrier_enabled("rogers"))

    def test_enabled_empty_allowlist_means_all(self):
        with mock.patch.dict(os.environ, {"HEALING_ENABLED": "true", "HEALING_CARRIERS": ""}):
            self.assertTrue(load_config().carrier_enabled("verizon"))


class HealerGuardrailTests(unittest.TestCase):
    def test_auth_context_denied_by_intent(self):
        self.assertTrue(is_auth_context("playwright/auth_strategies.py::login", "https://bell.ca/bills"))
        self.assertTrue(is_auth_context("bell/daily_usage.py::_enter_otp", "https://bell.ca/bills"))

    def test_auth_context_denied_by_url(self):
        self.assertTrue(is_auth_context("bell/daily_usage.py::_open_usage", "https://bell.ca/Login/x"))

    def test_normal_context_allowed(self):
        self.assertFalse(is_auth_context("bell/daily_usage.py::_click_download", "https://bell.ca/usage"))

    def test_json_parsing_tolerates_prose(self):
        text = 'Here you go:\n{"found": true, "selector_type": "css", "selector": "#x", "reason": "r"}'
        self.assertEqual(_parse_json_object(text)["selector"], "#x")
        self.assertIsNone(_parse_json_object("no json here"))

    def test_daily_budget_caps(self):
        tmp = tempfile.TemporaryDirectory()
        budget = DailyCallBudget(os.path.join(tmp.name, "o.json"), max_calls=2)
        self.assertTrue(budget.try_consume())
        self.assertTrue(budget.try_consume())
        self.assertFalse(budget.try_consume())
        tmp.cleanup()


class FactoryTests(unittest.TestCase):
    def test_disabled_returns_plain_wrapper(self):
        from web_scrapers.infrastructure.healing.factory import build_browser_wrapper
        from web_scrapers.infrastructure.playwright.browser_wrapper import PlaywrightWrapper

        with mock.patch.dict(os.environ, {"HEALING_ENABLED": "false"}):
            wrapper = build_browser_wrapper(page=mock.Mock())
            self.assertIs(type(wrapper), PlaywrightWrapper)

    def test_enabled_returns_healing_wrapper(self):
        from web_scrapers.infrastructure.healing.factory import build_browser_wrapper
        from web_scrapers.infrastructure.healing.healing_wrapper import HealingPlaywrightWrapper

        with mock.patch.dict(os.environ, {"HEALING_ENABLED": "true"}):
            wrapper = build_browser_wrapper(page=mock.Mock())
            self.assertIs(type(wrapper), HealingPlaywrightWrapper)


class HealingWrapperFlowTests(unittest.TestCase):
    """Exercise the _wait_for recovery ladder with a mocked page and healer."""

    def _make_wrapper(self, tmp_dir):
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from web_scrapers.infrastructure.healing.healing_wrapper import HealingPlaywrightWrapper

        with mock.patch.dict(
            os.environ,
            {"HEALING_ENABLED": "true", "HEALING_OVERRIDES_PATH": os.path.join(tmp_dir, "o.json")},
        ):
            config = load_config()
        page = mock.Mock()
        page.url = "https://businessportal.bell.ca/usage"
        page.content.return_value = "<html><body><h1>Usage</h1></body></html>"
        wrapper = HealingPlaywrightWrapper(page, config)
        wrapper.set_healing_context("bell", "BellDaily", tmp_dir)
        return wrapper, page, PlaywrightTimeoutError

    def test_primary_success_no_healing(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapper, page, _ = self._make_wrapper(tmp)
            page.wait_for_selector.return_value = None
            out = wrapper._wait_for("xpath=/x", 1000, "/x", "xpath")
            self.assertEqual(out, "xpath=/x")
            page.content.assert_not_called()

    def test_override_used_without_ai(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapper, page, TimeoutErr = self._make_wrapper(tmp)
            wrapper.override_store.put("bell", "BellDaily", "/x", "#fixed", "css")
            # Primary times out, override wait succeeds
            page.wait_for_selector.side_effect = [TimeoutErr("t"), None]
            wrapper.healer.heal = mock.Mock()
            out = wrapper._wait_for("xpath=/x", 1000, "/x", "xpath")
            self.assertEqual(out, "#fixed")
            wrapper.healer.heal.assert_not_called()

    def test_captcha_raises_typed_error(self):
        from web_scrapers.infrastructure.healing.classifier import CaptchaBlockedError

        with tempfile.TemporaryDirectory() as tmp:
            wrapper, page, TimeoutErr = self._make_wrapper(tmp)
            page.wait_for_selector.side_effect = TimeoutErr("t")
            page.content.return_value = '<div class="g-recaptcha"></div>'
            with self.assertRaises(CaptchaBlockedError):
                wrapper._wait_for("xpath=/x", 1000, "/x", "xpath")

    def test_heal_success_persists_override(self):
        from web_scrapers.infrastructure.healing.healer import HealResult

        with tempfile.TemporaryDirectory() as tmp:
            wrapper, page, TimeoutErr = self._make_wrapper(tmp)
            # Primary timeout, then healed-selector wait succeeds
            page.wait_for_selector.side_effect = [TimeoutErr("t"), None]
            wrapper.healer.heal = mock.Mock(
                return_value=HealResult(True, selector="#dl", selector_type="css", reason="r")
            )
            out = wrapper._wait_for("xpath=/x", 1000, "/x", "xpath")
            self.assertEqual(out, "#dl")
            self.assertEqual(
                wrapper.override_store.get("bell", "BellDaily", "/x"),
                {"selector": "#dl", "selector_type": "css"},
            )

    def test_heal_failure_reraises_original(self):
        from web_scrapers.infrastructure.healing.healer import HealResult

        with tempfile.TemporaryDirectory() as tmp:
            wrapper, page, TimeoutErr = self._make_wrapper(tmp)
            page.wait_for_selector.side_effect = TimeoutErr("t")
            wrapper.healer.heal = mock.Mock(return_value=HealResult(False, reason="nope"))
            with self.assertRaises(TimeoutErr):
                wrapper._wait_for("xpath=/x", 1000, "/x", "xpath")

    def test_disabled_carrier_reraises_immediately(self):
        with tempfile.TemporaryDirectory() as tmp:
            wrapper, page, TimeoutErr = self._make_wrapper(tmp)
            wrapper.healing_config = HealingConfig(enabled=True, carriers={"telus"})
            page.wait_for_selector.side_effect = TimeoutErr("t")
            with self.assertRaises(TimeoutErr):
                wrapper._wait_for("xpath=/x", 1000, "/x", "xpath")
            page.content.assert_not_called()


if __name__ == "__main__":
    unittest.main()
