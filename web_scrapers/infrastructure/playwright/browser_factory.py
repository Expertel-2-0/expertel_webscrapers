import atexit
import logging
import os
import signal
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, Optional, Type

from playwright.sync_api import Browser, BrowserContext, Page, Playwright as SyncPlaywright, sync_playwright
from playwright_stealth import Stealth

logger = logging.getLogger(__name__)

# ---- Global CDP subprocess cleanup ----
# Registro global para garantizar que Chrome CDP se mate en CUALQUIER escenario de salida:
# Ctrl+C, kill, crash, exit normal, exception no capturada, etc.
_cdp_subprocesses: set[subprocess.Popen] = set()


def _cleanup_cdp_subprocesses():
    """Mata todos los subprocesses de Chrome CDP registrados."""
    for proc in list(_cdp_subprocesses):
        try:
            if proc.poll() is None:  # Sigue vivo
                logger.info("Cleanup: terminating Chrome CDP subprocess (PID %d)", proc.pid)
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
        except Exception:
            pass
    _cdp_subprocesses.clear()


# atexit cubre: exit normal, sys.exit(), excepciones no capturadas, KeyboardInterrupt
atexit.register(_cleanup_cdp_subprocesses)


# Signal handler para SIGTERM (kill del servicio / docker stop / systemctl stop)
def _sigterm_handler(signum, frame):
    _cleanup_cdp_subprocesses()
    # Re-raise para que el proceso termine normalmente
    raise SystemExit(1)


try:
    signal.signal(signal.SIGTERM, _sigterm_handler)
except (OSError, ValueError):
    # signal.signal puede fallar en threads secundarios — no es critico
    pass

from web_scrapers.domain.entities.ports import NavigatorDriverBuilder
from web_scrapers.domain.enums import Navigators
from web_scrapers.infrastructure.playwright.drivers import (
    ChromeDriverBuilder,
    EdgeDriverBuilder,
    FirefoxDriverBuilder,
    SafariDriverBuilder,
)


def apply_stealth_context(context):
    """Aplica scripts de stealth avanzados para evitar deteccion de automatizacion."""
    context.add_init_script(
        """
        // ========================================
        // 1. WEBDRIVER - Ocultar automatizacion
        // ========================================
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });

        // Eliminar propiedades de automatizacion del prototipo
        try {
            delete navigator.__proto__.webdriver;
        } catch (e) {}

        // ========================================
        // 2. LANGUAGES
        // ========================================
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en', 'es']
        });

        Object.defineProperty(navigator, 'language', {
            get: () => 'en-US'
        });

        // ========================================
        // 3. PLUGINS - Simular plugins reales de Chrome
        // ========================================
        const makePlugin = (name, description, filename, mimeTypes) => {
            const plugin = Object.create(Plugin.prototype);
            Object.defineProperties(plugin, {
                name: { value: name, enumerable: true },
                description: { value: description, enumerable: true },
                filename: { value: filename, enumerable: true },
                length: { value: mimeTypes.length, enumerable: true }
            });
            mimeTypes.forEach((mt, i) => {
                const mimeType = Object.create(MimeType.prototype);
                Object.defineProperties(mimeType, {
                    type: { value: mt.type, enumerable: true },
                    suffixes: { value: mt.suffixes, enumerable: true },
                    description: { value: mt.description, enumerable: true },
                    enabledPlugin: { value: plugin, enumerable: true }
                });
                plugin[i] = mimeType;
            });
            return plugin;
        };

        const plugins = [
            makePlugin(
                'Chrome PDF Plugin',
                'Portable Document Format',
                'internal-pdf-viewer',
                [{ type: 'application/x-google-chrome-pdf', suffixes: 'pdf', description: 'Portable Document Format' }]
            ),
            makePlugin(
                'Chrome PDF Viewer',
                '',
                'mhjfbmdgcfjbbpaeojofohoefgiehjai',
                [{ type: 'application/pdf', suffixes: 'pdf', description: '' }]
            ),
            makePlugin(
                'Native Client',
                '',
                'internal-nacl-plugin',
                [
                    { type: 'application/x-nacl', suffixes: '', description: 'Native Client Executable' },
                    { type: 'application/x-pnacl', suffixes: '', description: 'Portable Native Client Executable' }
                ]
            )
        ];

        const pluginArray = Object.create(PluginArray.prototype);
        plugins.forEach((p, i) => { pluginArray[i] = p; });
        Object.defineProperty(pluginArray, 'length', { value: plugins.length });
        pluginArray.item = (i) => plugins[i] || null;
        pluginArray.namedItem = (name) => plugins.find(p => p.name === name) || null;
        pluginArray.refresh = () => {};

        Object.defineProperty(navigator, 'plugins', {
            get: () => pluginArray
        });

        // ========================================
        // 4. PLATFORM
        // ========================================
        Object.defineProperty(navigator, 'platform', {
            get: () => 'Win32'
        });

        // ========================================
        // 5. HARDWARE CONCURRENCY
        // ========================================
        Object.defineProperty(navigator, 'hardwareConcurrency', {
            get: () => 8
        });

        // ========================================
        // 6. DEVICE MEMORY
        // ========================================
        Object.defineProperty(navigator, 'deviceMemory', {
            get: () => 8
        });

        // ========================================
        // 7. WEBGL - Fingerprint realista
        // ========================================
        const getParameterProxyHandler = {
            apply: function(target, thisArg, args) {
                const param = args[0];
                // UNMASKED_VENDOR_WEBGL
                if (param === 37445) {
                    return 'Google Inc. (NVIDIA)';
                }
                // UNMASKED_RENDERER_WEBGL
                if (param === 37446) {
                    return 'ANGLE (NVIDIA, NVIDIA GeForce GTX 1080 Direct3D11 vs_5_0 ps_5_0, D3D11)';
                }
                return Reflect.apply(target, thisArg, args);
            }
        };

        try {
            WebGLRenderingContext.prototype.getParameter = new Proxy(
                WebGLRenderingContext.prototype.getParameter,
                getParameterProxyHandler
            );
            WebGL2RenderingContext.prototype.getParameter = new Proxy(
                WebGL2RenderingContext.prototype.getParameter,
                getParameterProxyHandler
            );
        } catch (e) {}

        // ========================================
        // 8. PERMISSIONS - Ocultar estado de automatizacion
        // ========================================
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );

        // ========================================
        // 9. CHROME RUNTIME - Simular extension API
        // ========================================
        window.chrome = {
            runtime: {
                connect: () => {},
                sendMessage: () => {},
                onMessage: {
                    addListener: () => {},
                    removeListener: () => {}
                }
            },
            loadTimes: function() {},
            csi: function() {}
        };

        // ========================================
        // 10. SCREEN - Propiedades realistas
        // ========================================
        Object.defineProperty(screen, 'availWidth', { get: () => 1920 });
        Object.defineProperty(screen, 'availHeight', { get: () => 1040 });
        Object.defineProperty(screen, 'width', { get: () => 1920 });
        Object.defineProperty(screen, 'height', { get: () => 1080 });
        Object.defineProperty(screen, 'colorDepth', { get: () => 24 });
        Object.defineProperty(screen, 'pixelDepth', { get: () => 24 });

        // ========================================
        // 11. CONNECTION
        // ========================================
        Object.defineProperty(navigator, 'connection', {
            get: () => ({
                effectiveType: '4g',
                rtt: 50,
                downlink: 10,
                saveData: false
            })
        });

        // ========================================
        // 12. AUTOMATION FLAGS - Limpiar todo rastro
        // ========================================
        const automationProps = [
            'webdriver',
            '__webdriver_script_fn',
            '__driver_evaluate',
            '__webdriver_evaluate',
            '__selenium_evaluate',
            '__fxdriver_evaluate',
            '__driver_unwrapped',
            '__webdriver_unwrapped',
            '__selenium_unwrapped',
            '__fxdriver_unwrapped',
            '_selenium',
            '__nightwatch',
            '__webdriver',
            '_Selenium_IDE_Recorder',
            'calledSelenium',
            '_WEBDRIVER_ELEM_CACHE',
            'ChromeDriverw',
            'driver-hierarchical',
            'domAutomation',
            'domAutomationController',
            'cdc_adoQpoasnfa76pfcZLmcfl_Array',
            'cdc_adoQpoasnfa76pfcZLmcfl_Promise',
            'cdc_adoQpoasnfa76pfcZLmcfl_Symbol'
        ];

        automationProps.forEach(prop => {
            try {
                if (window[prop]) delete window[prop];
                if (document[prop]) delete document[prop];
            } catch (e) {}
        });

        // ========================================
        // 13. FUNCTION TO STRING - Ocultar proxies
        // ========================================
        const oldToString = Function.prototype.toString;
        function customToString() {
            if (this === window.navigator.permissions.query) {
                return 'function query() { [native code] }';
            }
            return oldToString.call(this);
        }

        Object.defineProperty(Function.prototype, 'toString', {
            value: customToString,
            writable: true,
            configurable: true
        });

        // ========================================
        // 14. MEDIA DEVICES
        // ========================================
        if (navigator.mediaDevices) {
            navigator.mediaDevices.enumerateDevices = async () => [
                { deviceId: 'default', kind: 'audioinput', label: '', groupId: 'default' },
                { deviceId: 'default', kind: 'audiooutput', label: '', groupId: 'default' },
                { deviceId: 'default', kind: 'videoinput', label: '', groupId: 'default' }
            ];
        }

        // ========================================
        // 15. BATTERY API
        // ========================================
        if (navigator.getBattery) {
            navigator.getBattery = async () => ({
                charging: true,
                chargingTime: 0,
                dischargingTime: Infinity,
                level: 1,
                addEventListener: () => {},
                removeEventListener: () => {}
            });
        }
    """
    )


class BrowserDriverFactory:

    CHROME_PATHS = [
        "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
        "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/google-chrome-stable",
    ]

    def __init__(self):
        self._driver_builders: Dict[Navigators, Type[NavigatorDriverBuilder]] = {
            Navigators.CHROME: ChromeDriverBuilder,
            Navigators.EDGE: EdgeDriverBuilder,
            Navigators.FIREFOX: FirefoxDriverBuilder,
            Navigators.SAFARI: SafariDriverBuilder,
        }
        self._playwright: Optional[SyncPlaywright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._persistent_context: Optional[BrowserContext] = None
        self._chrome_subprocess: Optional[subprocess.Popen] = None

    def get_profile_dir(self, profile_name: str = "default") -> str:
        """Retorna el directorio del perfil persistente para un scraper especifico."""
        base_dir = Path(os.getcwd()) / "browser_profiles"
        base_dir.mkdir(exist_ok=True)
        profile_dir = base_dir / f"{profile_name}_profile"
        profile_dir.mkdir(exist_ok=True)
        return str(profile_dir)

    def get_default_browser_type(self) -> Navigators:
        browser_type: str = os.getenv("BROWSER_TYPE", "chrome").lower()
        try:
            return Navigators(browser_type)
        except ValueError:
            return Navigators.CHROME

    def get_browser_options(self) -> Dict[str, Any]:
        return {
            "headless": os.getenv("BROWSER_HEADLESS", "false").lower() == "true",
            "slow_mo": int(os.getenv("BROWSER_SLOW_MO", "1000")),
            "timeout": int(os.getenv("BROWSER_TIMEOUT", "30000")),
            "viewport_width": int(os.getenv("BROWSER_VIEWPORT_WIDTH", "1920")),
            "viewport_height": int(os.getenv("BROWSER_VIEWPORT_HEIGHT", "1080")),
            "no_sandbox": os.getenv("BROWSER_NO_SANDBOX", "false").lower() == "true",
            "disable_web_security": os.getenv("BROWSER_DISABLE_WEB_SECURITY", "false").lower() == "true",
        }

    def create_browser(self, browser_type: Optional[Navigators] = None, **kwargs) -> Browser:
        if not browser_type:
            browser_type = self.get_default_browser_type()

        default_options = self.get_browser_options()
        default_options.update(kwargs)

        driver_class: Type[NavigatorDriverBuilder] = self._driver_builders.get(browser_type)
        if not driver_class:
            raise ValueError(f"Navegador no soportado: {browser_type}")

        if not self._playwright:
            self._playwright = sync_playwright().start()

        driver_builder = driver_class(self._playwright)
        driver_builder.set_driver_options(**default_options)
        self._browser = driver_builder.get_browser()
        return self._browser

    def create_context(self, browser: Optional[Browser] = None, **kwargs) -> BrowserContext:
        if not self._browser:
            self._browser = self.create_browser()

        # User-Agent por defecto consistente con Chrome real en Windows
        default_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        context_options = {
            "viewport": {
                "width": int(os.getenv("BROWSER_VIEWPORT_WIDTH", "1920")),
                "height": int(os.getenv("BROWSER_VIEWPORT_HEIGHT", "1080")),
            },
            "user_agent": os.getenv("BROWSER_USER_AGENT", default_user_agent),
            "locale": os.getenv("BROWSER_LOCALE", "en-US"),
            "timezone_id": os.getenv("BROWSER_TIMEZONE", "America/Toronto"),
            "ignore_https_errors": os.getenv("BROWSER_IGNORE_HTTPS_ERRORS", "false").lower() == "true",
        }

        context_options = {k: v for k, v in context_options.items() if v is not None}
        context_options.update(kwargs)

        self._context = self._browser.new_context(**context_options)
        apply_stealth_context(self._context)
        return self._context

    def create_page(self, context: Optional[BrowserContext] = None) -> Page:
        if not context:
            context = self.create_context()
        self._page = context.new_page()

        # Aplicar playwright-stealth a nivel de pagina
        Stealth().apply_stealth_sync(self._page)

        default_timeout = int(os.getenv("BROWSER_DEFAULT_TIMEOUT", "30000"))
        navigation_timeout = int(os.getenv("BROWSER_NAVIGATION_TIMEOUT", "30000"))

        self._page.set_default_timeout(default_timeout)
        self._page.set_default_navigation_timeout(navigation_timeout)

        return self._page

    def create_persistent_context(self, profile_name: str = "default") -> BrowserContext:
        """Crea un contexto persistente con perfil guardado en disco.

        Esto hace que el navegador parezca mas 'real' porque:
        - Mantiene cookies entre sesiones
        - Tiene historial de navegacion
        - Tiene un fingerprint consistente
        - No parece un navegador 'fresco'
        """
        if not self._playwright:
            self._playwright = sync_playwright().start()

        profile_dir = self.get_profile_dir(profile_name)

        # User-Agent consistente con Chrome real
        default_user_agent = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )

        # Chrome args anti-deteccion
        chrome_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-infobars",
            "--disable-dev-shm-usage",
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
            "--window-size=1920,1080",
            "--start-maximized",
        ]

        # launch_persistent_context crea browser + context en uno solo
        self._persistent_context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=profile_dir,
            channel="chrome",
            headless=os.getenv("BROWSER_HEADLESS", "false").lower() == "true",
            slow_mo=int(os.getenv("BROWSER_SLOW_MO", "1000")),
            viewport={"width": 1920, "height": 1080},
            user_agent=os.getenv("BROWSER_USER_AGENT", default_user_agent),
            locale=os.getenv("BROWSER_LOCALE", "en-US"),
            timezone_id=os.getenv("BROWSER_TIMEZONE", "America/Toronto"),
            args=chrome_args,
            ignore_default_args=["--enable-automation"],
            ignore_https_errors=True,
        )

        # Aplicar stealth al contexto persistente
        apply_stealth_context(self._persistent_context)

        # El contexto persistente es tambien el 'browser' en este caso
        self._context = self._persistent_context

        return self._persistent_context

    @staticmethod
    def _find_chrome() -> Optional[str]:
        """Busca el ejecutable de Chrome real en el sistema."""
        for path in BrowserDriverFactory.CHROME_PATHS:
            if os.path.isfile(path):
                return path
        return None

    def create_cdp_browser(self, debug_port: int = 9222) -> tuple[Browser, BrowserContext]:
        """Lanza Chrome real via CDP y conecta Playwright.

        Chrome real bypasea Cloudflare porque no es detectado como bot.
        Usa un user-data-dir persistente para mantener cookies entre ejecuciones.
        """
        chrome_path = self._find_chrome()
        if not chrome_path:
            raise RuntimeError(
                "Google Chrome no encontrado en el sistema. "
                "Instala Chrome para usar el modo CDP. "
                f"Rutas buscadas: {self.CHROME_PATHS}"
            )

        if not self._playwright:
            self._playwright = sync_playwright().start()

        profile_dir = self.get_profile_dir("telus_cdp")

        logger.info("Launching Chrome via CDP (port %d, profile: %s)...", debug_port, profile_dir)
        self._chrome_subprocess = subprocess.Popen(
            [
                chrome_path,
                f"--remote-debugging-port={debug_port}",
                f"--user-data-dir={profile_dir}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-background-timer-throttling",
                "--window-size=1920,1080",
                "--start-maximized",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        _cdp_subprocesses.add(self._chrome_subprocess)
        time.sleep(3)
        logger.info("Chrome launched (PID %d)", self._chrome_subprocess.pid)

        self._browser = self._playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{debug_port}"
        )
        # Usar el contexto existente de Chrome (tiene cookies persistidas)
        if self._browser.contexts:
            self._context = self._browser.contexts[0]
        else:
            self._context = self._browser.new_context()

        return self._browser, self._context

    def create_full_setup(
        self,
        browser_type: Optional[Navigators] = None,
        profile_name: Optional[str] = None,
        cdp: bool = False,
        **kwargs
    ) -> tuple[Optional[Browser], BrowserContext]:
        """Crea browser y contexto. Si profile_name se especifica, usa contexto persistente.
        Si cdp=True, lanza Chrome real via CDP (bypasea Cloudflare)."""
        if cdp:
            browser, context = self.create_cdp_browser()
            return browser, context
        elif profile_name:
            # Usar contexto persistente (no hay browser separado)
            context = self.create_persistent_context(profile_name)
            return None, context
        else:
            # Flujo normal
            self.create_browser(browser_type)
            self.create_context()
            return self._browser, self._context

    def get_available_browsers(self) -> list[Navigators]:
        return list(self._driver_builders.keys())

    def cleanup(self) -> None:
        if self._page:
            self._page.close()
            self._page = None

        if self._context:
            self._context.close()
            self._context = None

        if self._browser:
            self._browser.close()
            self._browser = None

        if self._chrome_subprocess:
            logger.info("Terminating Chrome CDP subprocess (PID %d)...", self._chrome_subprocess.pid)
            self._chrome_subprocess.terminate()
            try:
                self._chrome_subprocess.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._chrome_subprocess.kill()
            _cdp_subprocesses.discard(self._chrome_subprocess)
            self._chrome_subprocess = None

        if self._playwright:
            self._playwright.stop()
            self._playwright = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()


class BrowserManager:

    _instance: Optional["BrowserManager"] = None
    _factory: Optional[BrowserDriverFactory] = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._factory is None:
            self._factory = BrowserDriverFactory()

    @property
    def factory(self) -> BrowserDriverFactory:
        return self._factory

    def get_browser(
        self,
        browser_type: Optional[Navigators] = None,
        profile_name: Optional[str] = None,
        cdp: bool = False,
    ) -> tuple[Optional[Browser], BrowserContext]:
        """Obtiene browser y contexto. Si cdp=True, usa Chrome real via CDP."""
        return self._factory.create_full_setup(browser_type, profile_name=profile_name, cdp=cdp)

    def cleanup_all(self) -> None:
        if self._factory:
            self._factory.cleanup()
            self._factory = None
        BrowserManager._instance = None
