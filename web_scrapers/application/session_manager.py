import logging
import time
from datetime import datetime
from typing import Dict, Optional, Type

from playwright_stealth import Stealth

from web_scrapers.domain.entities.auth_strategies import AuthBaseStrategy
from web_scrapers.domain.entities.session import Carrier, Credentials, SessionState, SessionStatus
from web_scrapers.domain.enums import Navigators, ScraperType
from web_scrapers.infrastructure.playwright.auth_strategies import (
    ATTAuthStrategy,
    BellAuthStrategy,
    BellEnterpriseAuthStrategy,
    RogersAuthStrategy,
    TelusAuthStrategy,
    TMobileAuthStrategy,
    VerizonAuthStrategy,
)
from web_scrapers.infrastructure.playwright.browser_factory import BrowserManager
from web_scrapers.infrastructure.playwright.browser_wrapper import BrowserWrapper, PlaywrightWrapper


class SessionManager:

    # Carriers que requieren perfil persistente para evitar deteccion de bots
    CARRIERS_WITH_PERSISTENT_PROFILE = {Carrier.ROGERS}

    # Carriers que requieren Chrome real via CDP para bypasear Cloudflare
    CARRIERS_WITH_CDP_BROWSER = {Carrier.TELUS}

    def __init__(self, browser_type: Optional[Navigators] = None):
        self.logger = logging.getLogger(self.__class__.__name__)
        self.browser_manager = BrowserManager()
        self.browser_type = browser_type
        self.session_state = SessionState()
        self._use_cdp = False

        self._auth_strategies: dict[tuple[Carrier, ScraperType], Type[AuthBaseStrategy]] = {
            (Carrier.BELL, ScraperType.MONTHLY_REPORTS): BellEnterpriseAuthStrategy,
            (Carrier.BELL, ScraperType.DAILY_USAGE): BellAuthStrategy,
            (Carrier.BELL, ScraperType.PDF_INVOICE): BellAuthStrategy,
            (Carrier.TELUS, ScraperType.MONTHLY_REPORTS): TelusAuthStrategy,
            (Carrier.TELUS, ScraperType.DAILY_USAGE): TelusAuthStrategy,
            (Carrier.TELUS, ScraperType.PDF_INVOICE): TelusAuthStrategy,
            (Carrier.ROGERS, ScraperType.MONTHLY_REPORTS): RogersAuthStrategy,
            (Carrier.ROGERS, ScraperType.DAILY_USAGE): RogersAuthStrategy,
            (Carrier.ROGERS, ScraperType.PDF_INVOICE): RogersAuthStrategy,
            (Carrier.ATT, ScraperType.MONTHLY_REPORTS): ATTAuthStrategy,
            (Carrier.ATT, ScraperType.DAILY_USAGE): ATTAuthStrategy,
            (Carrier.ATT, ScraperType.PDF_INVOICE): ATTAuthStrategy,
            (Carrier.TMOBILE, ScraperType.MONTHLY_REPORTS): TMobileAuthStrategy,
            (Carrier.TMOBILE, ScraperType.DAILY_USAGE): TMobileAuthStrategy,
            (Carrier.TMOBILE, ScraperType.PDF_INVOICE): TMobileAuthStrategy,
            (Carrier.VERIZON, ScraperType.MONTHLY_REPORTS): VerizonAuthStrategy,
            (Carrier.VERIZON, ScraperType.DAILY_USAGE): VerizonAuthStrategy,
            (Carrier.VERIZON, ScraperType.PDF_INVOICE): VerizonAuthStrategy,
        }

        self._current_auth_strategy: Optional[AuthBaseStrategy] = None
        self._scraper_type: Optional[ScraperType] = None
        self._current_login_url: Optional[str] = None  # ← NUEVO: guardar URL de login actual
        self._browser_wrapper: Optional[BrowserWrapper] = None
        self._browser = None
        self._context = None
        self._page = None

    def is_logged_in(self) -> bool:
        return self.refresh_session_status()

    def get_current_carrier(self) -> Optional[Carrier]:
        return self.session_state.carrier

    def get_current_credentials(self) -> Optional[Credentials]:
        return self.session_state.credentials

    def get_session_state(self) -> SessionState:
        return self.session_state

    def refresh_session_status(self) -> bool:
        try:
            if not self._current_auth_strategy:
                return False

            # Verificar si hay elementos de login visibles en la pantalla
            is_active = self._current_auth_strategy.is_logged_in()

            # Si no hay elementos visibles y hay sesión activa, cerrar sesión
            if not is_active:
                if self.session_state.is_logged_in():
                    self.session_state.set_logged_out()
                    self._current_auth_strategy = None
                    self._scraper_type = None
                    self._current_login_url = None
                return False

            # Si el browser confirma que estamos logueados pero session_state está en ERROR,
            # reparar el estado ya que la sesión sigue siendo válida
            if is_active and self.session_state.is_error():
                self.logger.info(
                    f"[SESSION REPAIR] Browser confirms session is active but state was ERROR. "
                    f"Repairing session state for {self.session_state.carrier}."
                )
                self.session_state.status = SessionStatus.LOGGED_IN
                self.session_state.error_message = None

            return is_active

        except Exception as e:
            error_msg = f"Error verifying session state: {str(e)}"
            self.session_state.set_error(error_msg)
            return False

    def force_logout(self) -> None:
        self.session_state.set_logged_out()
        self._current_auth_strategy = None
        self._scraper_type = None
        self._current_login_url = None

    def has_error(self) -> bool:
        return self.session_state.is_error()

    def get_error_message(self) -> Optional[str]:
        return self.session_state.error_message

    def _needs_browser_switch(self, carrier: Optional[Carrier] = None) -> bool:
        """Detecta si necesitamos destruir el browser actual y crear uno nuevo.

        Esto ocurre cuando el modo cambia (CDP <-> normal/persistent), lo cual
        pasa al cambiar entre carriers que usan Chrome real (Telus) y los demas.
        """
        if not self._browser_wrapper:
            return False  # No hay browser, no hay nada que switchear

        needs_cdp = carrier is not None and carrier in self.CARRIERS_WITH_CDP_BROWSER
        if needs_cdp != self._use_cdp:
            return True

        return False

    def _destroy_browser(self) -> None:
        """Destruye la instancia actual del browser (pagina, contexto, browser, subprocess).

        No toca el session_state — eso lo maneja login()/logout().
        """
        self.logger.info("[BROWSER DESTROY] Tearing down current browser instance")
        self._browser_wrapper = None

        if self._page:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None

        if self._context:
            try:
                self._context.close()
            except Exception:
                pass
            self._context = None

        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None

        # Cleanup del factory (mata subprocess de Chrome si existe)
        self.browser_manager.cleanup_all()
        # Re-inicializar el BrowserManager singleton para la siguiente creacion
        self.browser_manager = BrowserManager()

    def _initialize_browser(self, carrier: Optional[Carrier] = None) -> BrowserWrapper:

        # Si el browser existe pero el modo necesita cambiar, destruirlo primero
        if self._needs_browser_switch(carrier):
            self.logger.info(
                f"[BROWSER SWITCH] Browser mode change detected "
                f"(cdp={self._use_cdp} -> cdp={carrier in self.CARRIERS_WITH_CDP_BROWSER}), "
                f"destroying current browser"
            )
            self._destroy_browser()

        if not self._browser_wrapper:
            # Determinar modo de browser segun carrier
            self._use_cdp = carrier is not None and carrier in self.CARRIERS_WITH_CDP_BROWSER

            if self._use_cdp:
                # Chrome real via CDP - bypasea Cloudflare
                self.logger.info(f"[CDP MODE] Using real Chrome via CDP for {carrier}")
                self._browser, self._context = self.browser_manager.get_browser(cdp=True)
                self._page = self._context.new_page()
                # NO aplicar Stealth: Chrome real no lo necesita y puede causar deteccion
            else:
                # Determinar si el carrier requiere perfil persistente
                profile_name = None
                if carrier and carrier in self.CARRIERS_WITH_PERSISTENT_PROFILE:
                    profile_name = carrier.value.lower()  # "rogers", "bell", etc.

                self._browser, self._context = self.browser_manager.get_browser(
                    self.browser_type,
                    profile_name=profile_name
                )
                self._page = self._context.new_page()
                Stealth().apply_stealth_sync(self._page)  # Aplicar stealth a la pagina

            self._browser_wrapper = PlaywrightWrapper(self._page)

        return self._browser_wrapper

    def get_new_browser_wrapper(self) -> BrowserWrapper:
        if self._context:
            self._page = self._context.new_page()
            if not self._use_cdp:
                Stealth().apply_stealth_sync(self._page)
            self._browser_wrapper = PlaywrightWrapper(self._page)
        return self._browser_wrapper

    def get_browser_wrapper(self) -> Optional[BrowserWrapper]:
        return self._browser_wrapper

    def login(self, credentials: Credentials, scraper_type: ScraperType) -> bool:
        try:
            self.logger.info(
                f"[SESSION CHECK] Evaluating session reuse for {credentials.carrier}, "
                f"scraper_type={scraper_type}, session_state.status={self.session_state.status}"
            )

            if self.session_state.is_logged_in():
                if (
                    self.session_state.carrier == credentials.carrier
                    and self.session_state.credentials
                    and self.session_state.credentials.id == credentials.id
                    and self._scraper_type == scraper_type
                ):
                    self.logger.info(
                        f"[SESSION REUSE] Reusing existing session for {credentials.carrier} "
                        f"(same carrier, credentials, scraper_type)"
                    )
                    return True

                # Si cambió el scraper_type, verificar si la URL de login también cambió
                if self._scraper_type != scraper_type:
                    auth_strategy_class = self._auth_strategies.get((credentials.carrier, scraper_type))
                    if auth_strategy_class:
                        # Crear instancia temporal para obtener la URL sin afectar la actual
                        temp_strategy = auth_strategy_class(self._browser_wrapper)
                        new_login_url = temp_strategy.get_login_url()

                        # Solo hacer logout si la URL de login cambió
                        if new_login_url != self._current_login_url:
                            self.logger.info(
                                f"[SESSION LOGOUT] Login URL changed from {self._current_login_url} "
                                f"to {new_login_url}, logging out"
                            )
                            self.logout()
                        else:
                            # La URL es la misma, solo actualizar scraper_type y reutilizar sesión
                            self.logger.info(
                                f"[SESSION REUSE] Reusing session - same login URL, "
                                f"updating scraper_type from {self._scraper_type} to {scraper_type}"
                            )
                            self._scraper_type = scraper_type
                            return True
                    else:
                        self.logger.info(f"[SESSION LOGOUT] No auth strategy found for new scraper_type, logging out")
                        self.logout()
                else:
                    self.logger.info(
                        f"[SESSION LOGOUT] Credentials changed (current_id={self.session_state.credentials.id if self.session_state.credentials else None}, "
                        f"new_id={credentials.id}), logging out"
                    )
                    self.logout()
            else:
                self.logger.info(
                    f"[SESSION NEW] session_state.is_logged_in()=False, proceeding with fresh login"
                )

            # CAMBIO CLAVE: Búsqueda con tupla (carrier, scraper_type)
            auth_strategy_class = self._auth_strategies.get((credentials.carrier, scraper_type))

            if not auth_strategy_class:
                error_msg = f"No auth strategy for carrier: {credentials.carrier}, scraper_type: {scraper_type}"
                self.session_state.set_error(error_msg)
                return False
            browser_wrapper = self._initialize_browser(carrier=credentials.carrier)
            self._current_auth_strategy = auth_strategy_class(browser_wrapper)
            self._scraper_type = scraper_type
            self._current_login_url = self._current_auth_strategy.get_login_url()  # ← CAMBIO: guardar URL de login

            login_success = self._current_auth_strategy.login(credentials)
            if login_success:
                self.session_state.set_logged_in(carrier=credentials.carrier, credentials=credentials)
                return True
            else:
                error_msg = f"Login failed for {credentials.carrier}"
                self.session_state.set_error(error_msg)
                return False

        except Exception as e:
            error_msg = f"Error during login process: {str(e)}"
            self.session_state.set_error(error_msg)
            return False

    def logout(self) -> bool:
        try:
            if not self.session_state.is_logged_in():
                return True

            if not self._current_auth_strategy:
                self.session_state.set_logged_out()
                return True

            logout_success = self._current_auth_strategy.logout()

            if logout_success:
                self.session_state.set_logged_out()
                self._current_auth_strategy = None
                self._scraper_type = None
                self._current_login_url = None  # ← CAMBIO: limpiar URL de login
                return True
            else:
                error_msg = "Logout failed"
                self.session_state.set_error(error_msg)
                return False

        except Exception as e:
            error_msg = f"Error during logout process: {str(e)}"
            self.session_state.set_error(error_msg)
            return False

    def cleanup(self) -> None:
        if self._current_auth_strategy:
            try:
                self._current_auth_strategy.logout()
            except Exception as e:
                self.logger.warning(f"Logout failed during cleanup: {e}")

        self.session_state.set_logged_out()
        self._current_auth_strategy = None
        self._scraper_type = None
        self._current_login_url = None

        self._destroy_browser()

    def clear_error(self) -> None:
        """Clears error state and returns to appropriate status based on current auth state."""
        if self.session_state.is_error():
            self.session_state.error_message = None
            # Determine correct status based on actual authentication state
            if self._current_auth_strategy and self._current_auth_strategy.is_logged_in():
                self.session_state.status = SessionStatus.LOGGED_IN
            else:
                self.session_state.status = SessionStatus.LOGGED_OUT

    def close_all_pages_and_open_new(self):
        if self._context:
            for page in self._context.pages:
                page.close()
            self._page = self._context.new_page()
            if not self._use_cdp:
                Stealth().apply_stealth_sync(self._page)
            self._browser_wrapper = PlaywrightWrapper(self._page)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
