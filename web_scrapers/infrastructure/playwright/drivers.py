from typing import Any, Dict, Optional

from playwright.sync_api._generated import Browser, Playwright as SyncPlaywright

from web_scrapers.domain.entities.ports import NavigatorDriverBuilder
from web_scrapers.domain.enums import Navigators


class BaseNavigatorDriverBuilder(NavigatorDriverBuilder):

    def __init__(self, pw: SyncPlaywright) -> None:
        self.pw: SyncPlaywright = pw
        self.options: Dict[str, Any] = {"headless": False, "slow_mo": 1000, "timeout": 30000}

    def set_driver_options(self, **kwargs) -> None:
        valid_options = {
            "headless",
            "slow_mo",
            "timeout",
            "proxy",
            "downloads_path",
            "executable_path",
            "args",
            "ignore_default_args",
            "handle_sigint",
            "handle_sigterm",
            "handle_sighup",
            "viewport_width",
            "viewport_height",
            "channel",
        }
        for key, value in kwargs.items():
            if key in valid_options:
                self.options[key] = value

    def get_browser(self) -> Browser:
        raise NotImplementedError

    def _get_launch_options(self) -> Dict[str, Any]:
        launch_options = {}

        if "headless" in self.options:
            launch_options["headless"] = self.options["headless"]

        if "slow_mo" in self.options:
            launch_options["slow_mo"] = self.options["slow_mo"]

        if "timeout" in self.options:
            launch_options["timeout"] = self.options["timeout"]

        if "proxy" in self.options:
            launch_options["proxy"] = self.options["proxy"]

        if "downloads_path" in self.options:
            launch_options["downloads_path"] = self.options["downloads_path"]

        if "executable_path" in self.options:
            launch_options["executable_path"] = self.options["executable_path"]

        if "args" in self.options:
            launch_options["args"] = self.options["args"]

        if "ignore_default_args" in self.options:
            launch_options["ignore_default_args"] = self.options["ignore_default_args"]

        if "handle_sigint" in self.options:
            launch_options["handle_sigint"] = self.options["handle_sigint"]

        if "handle_sigterm" in self.options:
            launch_options["handle_sigterm"] = self.options["handle_sigterm"]

        if "handle_sighup" in self.options:
            launch_options["handle_sighup"] = self.options["handle_sighup"]

        return launch_options


class ChromeDriverBuilder(BaseNavigatorDriverBuilder):

    def __init__(self, pw: SyncPlaywright):
        super().__init__(pw)

    def get_browser(self) -> Browser:
        launch_options = self._get_launch_options()
        launch_options["channel"] = Navigators.CHROME.value

        # Ignorar args de automatizacion por defecto
        launch_options["ignore_default_args"] = ["--enable-automation"]

        launch_options.setdefault("args", [])
        launch_options["args"] += [
            # Args originales
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
            "--window-size=1920,1080",
            "--start-maximized",
            # Args anti-deteccion mejorados
            "--disable-blink-features=AutomationControlled",
            "--disable-automation",
            "--disable-extensions",
            "--disable-default-apps",
            "--disable-component-extensions-with-background-pages",
            "--disable-background-networking",
            "--no-default-browser-check",
            "--no-first-run",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--disable-ipc-flooding-protection",
            "--password-store=basic",
            "--use-mock-keychain",
            "--force-color-profile=srgb",
        ]

        return self.pw.chromium.launch(**launch_options)

    def set_driver_options(self, **kwargs):
        super().set_driver_options(**kwargs)

        chrome_args = []

        if kwargs.get("disable_web_security", False):
            chrome_args.append("--disable-web-security")

        if kwargs.get("disable_features_security", False):
            chrome_args.append("--disable-features=VizDisplayCompositor")

        if kwargs.get("no_sandbox", False):
            chrome_args.append("--no-sandbox")

        if kwargs.get("disable_dev_shm_usage", False):
            chrome_args.append("--disable-dev-shm-usage")

        if chrome_args:
            existing_args = self.options.get("args", [])
            self.options["args"] = existing_args + chrome_args


class EdgeDriverBuilder(BaseNavigatorDriverBuilder):

    def __init__(self, pw: SyncPlaywright):
        super().__init__(pw)

    def get_browser(self) -> Browser:
        launch_options = self._get_launch_options()

        # Ignorar args de automatizacion por defecto
        launch_options["ignore_default_args"] = ["--enable-automation"]

        launch_options.setdefault("args", [])
        launch_options["args"] += [
            # Args originales
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
            "--disable-web-security",
            "--disable-features=VizDisplayCompositor",
            "--window-size=1920,1080",
            "--start-maximized",
            # Args anti-deteccion mejorados
            "--disable-blink-features=AutomationControlled",
            "--disable-automation",
            "--disable-extensions",
            "--disable-default-apps",
            "--disable-component-extensions-with-background-pages",
            "--disable-background-networking",
            "--no-default-browser-check",
            "--no-first-run",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-background-timer-throttling",
            "--disable-ipc-flooding-protection",
            "--password-store=basic",
            "--use-mock-keychain",
            "--force-color-profile=srgb",
        ]

        return self.pw.chromium.launch(**launch_options, channel="msedge")

    def set_driver_options(self, **kwargs):
        super().set_driver_options(**kwargs)

        edge_args = []

        if kwargs.get("disable_web_security", False):
            edge_args.append("--disable-web-security")

        if kwargs.get("no_sandbox", False):
            edge_args.append("--no-sandbox")

        if edge_args:
            existing_args = self.options.get("args", [])
            self.options["args"] = existing_args + edge_args


class FirefoxDriverBuilder(BaseNavigatorDriverBuilder):

    def __init__(self, pw: SyncPlaywright):
        super().__init__(pw)

    def get_browser(self) -> Browser:
        launch_options = self._get_launch_options()
        return self.pw.firefox.launch(**launch_options)

    def set_driver_options(self, **kwargs):
        super().set_driver_options(**kwargs)

        firefox_prefs = {
            # Preferencias anti-deteccion originales
            "dom.webdriver.enabled": False,
            "useAutomationExtension": False,
            "media.peerconnection.enabled": False,
            "privacy.trackingprotection.enabled": True,
            "webgl.disabled": False,
            "javascript.enabled": True,
            "intl.accept_languages": "en-US, en",
            # Preferencias anti-deteccion mejoradas
            "privacy.resistFingerprinting": False,  # Evita inconsistencias de fingerprint
            "dom.webaudio.enabled": True,
            "media.navigator.enabled": True,
            "network.http.sendRefererHeader": 2,
            "browser.startup.homepage_override.mstone": "ignore",
            "startup.homepage_welcome_url.additional": "",
            "browser.shell.checkDefaultBrowser": False,
            "browser.tabs.warnOnClose": False,
            "toolkit.telemetry.reportingpolicy.firstRun": False,
            "datareporting.policy.dataSubmissionEnabled": False,
            "toolkit.telemetry.enabled": False,
            "browser.newtabpage.enabled": False,
            "browser.newtabpage.enhanced": False,
            "browser.usedOnWindows10.introURL": "",
            "browser.aboutHomeSnippets.updateUrl": "",
            "browser.safebrowsing.enabled": False,
            "browser.safebrowsing.malware.enabled": False,
        }

        if kwargs.get("disable_images", False):
            firefox_prefs["permissions.default.image"] = 2

        if kwargs.get("disable_javascript", False):
            firefox_prefs["javascript.enabled"] = False

        if "firefox_user_prefs" not in self.options:
            self.options["firefox_user_prefs"] = {}

        self.options["firefox_user_prefs"].update(firefox_prefs)

    def _get_launch_options(self) -> Dict[str, Any]:
        """Obtiene opciones específicas para Firefox."""
        launch_options = super()._get_launch_options()

        # Agregar preferencias de Firefox si existen
        if "firefox_user_prefs" in self.options:
            launch_options["firefox_user_prefs"] = self.options["firefox_user_prefs"]

        return launch_options


class SafariDriverBuilder(BaseNavigatorDriverBuilder):

    def __init__(self, pw: SyncPlaywright):
        super().__init__(pw)

    def get_browser(self) -> Browser:
        launch_options = self._get_launch_options()

        # Safari tiene opciones limitadas
        return self.pw.webkit.launch(**launch_options)

    def set_driver_options(self, **kwargs):
        super().set_driver_options(**kwargs)
        safari_supported = {"headless", "timeout", "proxy"}
        self.options = {k: v for k, v in self.options.items() if k in safari_supported}
