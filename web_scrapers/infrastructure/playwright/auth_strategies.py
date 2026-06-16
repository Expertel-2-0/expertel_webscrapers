import logging
import os
import random
import shutil
import time
from pathlib import Path
from typing import Optional

import requests
from playwright_stealth import Stealth

from mfa.infrastructure.verizon_captcha_solver import extract_text_from_image
from web_scrapers.domain.entities.auth_strategies import AuthBaseStrategy, InvalidCredentialsError, MFACodeError
from web_scrapers.domain.entities.session import Credentials
from web_scrapers.domain.enums import CarrierPortalUrls
from web_scrapers.infrastructure.playwright.browser_wrapper import BrowserWrapper

# Default MFA webhook URL - can be overridden via environment variable
DEFAULT_MFA_SERVICE_URL = os.getenv("MFA_SERVICE_URL", "http://localhost:8000")


class BellEnterpriseAuthStrategy(AuthBaseStrategy):

    def __init__(self, browser_wrapper: BrowserWrapper, webhook_url: str = None):
        super().__init__(browser_wrapper)
        self.webhook_url = webhook_url or DEFAULT_MFA_SERVICE_URL
        self.logger = logging.getLogger(self.__class__.__name__)

    def login(self, credentials: Credentials) -> bool:
        try:
            self.browser_wrapper.goto(self.get_login_url())
            self.browser_wrapper.wait_for_page_load(60000)
            # Randomized dwell + human-like input below: reCAPTCHA Enterprise scores
            # mouse movement, keystroke cadence, and time-on-page, so the login uses
            # human_type/human_click/human_pause instead of instant type+click.
            self.browser_wrapper.human_pause(2.5, 4.0)

            username_xpath = "//*[@id='Username']"
            if not self._type_and_verify(username_xpath, credentials.username, field_name="username"):
                self.logger.error("Aborting Bell Enterprise login: username could not be typed completely")
                return False
            self.browser_wrapper.human_pause(0.6, 1.4)

            password_xpath = "//*[@id='Password']"
            if not self._type_and_verify(password_xpath, credentials.password, field_name="password"):
                self.logger.error("Aborting Bell Enterprise login: password could not be typed completely")
                return False
            self.browser_wrapper.human_pause(0.6, 1.4)

            login_button_xpath = "//*[@id='loginBtn']"
            self.browser_wrapper.human_click(login_button_xpath)

            self.browser_wrapper.wait_for_page_load()
            self.browser_wrapper.human_pause(8.0, 11.0)

            return self.is_logged_in()

        except Exception as e:
            self.logger.error(f"Error during Enterprise Centre login: {str(e)}")
            return False

    def _type_and_verify(
        self,
        selector: str,
        text: str,
        field_name: str,
        max_attempts: int = 3,
        selector_type: str = "xpath",
    ) -> bool:
        # Bell Enterprise occasionally loses focus mid-typing (window focus stolen,
        # popup, etc.) and the input keeps a partial value. The login still submits
        # and Bell rejects the (now mismatched) credentials, which surfaces as a
        # generic "Login failed". Here we type, read the input value back, and
        # retry up to max_attempts if the length doesn't match. We only log
        # lengths — never the value — so passwords don't leak into logs.
        resolved = self.browser_wrapper._resolve_selector(selector, selector_type)
        expected_len = len(text)
        for attempt in range(1, max_attempts + 1):
            # human_type clears the field (clear_first=True), focuses it with a
            # human-like click, then types char-by-char with randomized delays —
            # raising the behavioral signal reCAPTCHA Enterprise scores. The
            # read-back length check below still guards against focus-steal
            # truncation; a short attempt simply retries.
            try:
                self.browser_wrapper.human_type(selector, text, selector_type=selector_type)
            except Exception as e:
                self.logger.warning(f"Could not type {field_name} on attempt {attempt}: {e}")
            try:
                actual = self.browser_wrapper.page.input_value(resolved) or ""
            except Exception as e:
                self.logger.warning(f"Could not read {field_name} value on attempt {attempt}: {e}")
                actual = ""
            if len(actual) == expected_len:
                if attempt > 1:
                    self.logger.info(
                        f"{field_name} typed correctly on attempt {attempt}/{max_attempts} (len={expected_len})"
                    )
                return True
            self.logger.warning(
                f"{field_name} typing incomplete on attempt {attempt}/{max_attempts}: "
                f"expected len={expected_len}, got len={len(actual)} — retrying"
            )
            time.sleep(0.5)
        self.logger.error(
            f"{field_name} could not be typed completely after {max_attempts} attempts "
            f"(expected len={expected_len})"
        )
        return False

    def logout(self) -> bool:
        try:
            logout_xpath = (
                "#ec-sidebar > div > div > div.ec-sidebar__container > ul:nth-child(2) > li:nth-child(4) > a"
            )
            self.browser_wrapper.click_element(logout_xpath, selector_type="css")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)

            print("Logout successful in Bell Enterprise Centre")
            return not self.is_logged_in()

        except Exception as e:
            print(f"Error during logout: {str(e)}")
            return False

    def is_logged_in(self) -> bool:
        try:
            login_form_xpath = "//*[@id='loginBtn']"
            return not self.browser_wrapper.is_element_visible(login_form_xpath, timeout=5000)
        except Exception:
            return False

    def get_login_url(self) -> str:
        return "https://enterprisecentre.bell.ca"

    def get_logout_xpath(self) -> str:
        return "//*[@id='ec-sidebar']/div/div/div[3]/ul[2]/li[4]/a"

    def get_username_xpath(self) -> str:
        return "//*[@id='Username']"

    def get_password_xpath(self) -> str:
        return "//*[@id='Password']"

    def get_login_button_xpath(self) -> str:
        return "//*[@id='loginBtn']"

    # TODO: Implementar _handle_2fa_if_present si Bell Enterprise Centre requiere 2FA
    # Pasos pendientes:
    # 1. Identificar si el portal requiere 2FA y cómo detectarlo
    # 2. Identificar los XPaths de los elementos de 2FA
    # 3. Usar el método heredado _consume_mfa_sse_stream:
    #     endpoint_url = f"{self.webhook_url}/api/v1/bell"
    #     code = self._consume_mfa_sse_stream(endpoint_url, credentials.username)


class BellAuthStrategy(AuthBaseStrategy):

    def __init__(self, browser_wrapper: BrowserWrapper, webhook_url: str = None):
        super().__init__(browser_wrapper)
        self.webhook_url = webhook_url or DEFAULT_MFA_SERVICE_URL
        self.logger = logging.getLogger(self.__class__.__name__)

    def login(self, credentials: Credentials) -> bool:
        try:
            self.browser_wrapper.goto(self.get_login_url())
            self.browser_wrapper.wait_for_page_load(60000)
            # Human-like input (see BellEnterpriseAuthStrategy): human_type/human_click
            # raise the mouse + keystroke + time-on-page signals reCAPTCHA scores.
            self.browser_wrapper.human_pause(2.5, 4.0)

            email_xpath = (
                "/html[1]/body[1]/main[1]/div[4]/div[1]/div[1]/div[2]/div[2]/div[2]/form[1]/div[1]/div[2]/input[1]"
            )
            self.browser_wrapper.human_type(email_xpath, credentials.username)
            self.browser_wrapper.human_pause(0.6, 1.4)

            password_xpath = (
                "/html[1]/body[1]/main[1]/div[4]/div[1]/div[1]/div[2]/div[2]/div[2]/form[1]/div[2]/div[2]/input[1]"
            )
            self.browser_wrapper.human_type(password_xpath, credentials.password)
            self.browser_wrapper.human_pause(0.6, 1.4)

            login_button_xpath = "/html[1]/body[1]/main[1]/div[4]/div[1]/div[1]/div[2]/div[2]/div[2]/form[1]/button[1]"
            self.browser_wrapper.human_click(login_button_xpath)

            self.browser_wrapper.wait_for_page_load()
            self.browser_wrapper.human_pause(4.0, 6.0)

            # Bell's login form rejects bad credentials inline (no redirect, no 2FA screen):
            # an <p class="error-desc invalid"> appears inside #divEmailAddress with the
            # text "You have entered an incorrect email/password combination". Detect it
            # before falling through to the 2FA check, otherwise the failure cascades into
            # a generic "Login failed for Carrier.BELL" with no trace, which is what the
            # production logs were showing for the Group A Bell jobs.
            self._raise_if_invalid_credentials(credentials)

            if not self._handle_2fa_if_present(credentials):
                self.logger.warning("2FA failed - interrupting login")
                return False

            return self.is_logged_in()

        except InvalidCredentialsError as e:
            self.logger.error(f"Invalid credentials for Bell user {credentials.username}: {str(e)}")
            return False
        except MFACodeError as e:
            self.logger.error(f"MFA error during login in Bell: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Error during login in Bell: {str(e)}")
            return False

    def _raise_if_invalid_credentials(self, credentials: Credentials) -> None:
        """Raise InvalidCredentialsError if Bell rendered the incorrect-credentials alert.

        The alert lives inside the email-address form group as a <p class="error-desc
        invalid">. We also pull the visible text so the log line carries Bell's own
        wording, which makes it unambiguous in the SCRAPER_FAILURES_HISTORY review.
        """
        error_xpath = "//*[@id='divEmailAddress']//p[contains(@class, 'error-desc')]"
        # Short timeout: by this point the form has already had its 5s settle window, so
        # if the alert is going to appear, it's there now. We don't want to delay the
        # 2FA path on the happy case.
        if not self.browser_wrapper.is_element_visible(error_xpath, timeout=2000):
            return

        try:
            message = self.browser_wrapper.get_text(error_xpath, timeout=1000).strip()
        except Exception:
            message = "incorrect email/password combination"
        raise InvalidCredentialsError(message)

    def logout(self) -> bool:
        try:
            bell_logo_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/a[1]"
            self.browser_wrapper.click_element(bell_logo_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)

            user_button_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/div[1]/logout[1]/div[1]/button[1]"
            self.browser_wrapper.click_element(user_button_xpath)
            time.sleep(2)

            logout_button_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/div[1]/logout[1]/div[1]/div[1]/div[2]/div[1]/button[1]"
            self.browser_wrapper.click_element(logout_button_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)

            return not self.is_logged_in()

        except Exception as e:
            return False

    def is_logged_in(self) -> bool:
        try:
            user_button_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/div[1]/logout[1]/div[1]/button[1]"
            return self.browser_wrapper.is_element_visible(user_button_xpath, timeout=10000)
        except Exception:
            return False

    def get_login_url(self) -> str:
        return CarrierPortalUrls.BELL.value

    def get_logout_xpath(self) -> str:
        return "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/div[1]/logout[1]/div[1]/div[1]/div[2]/div[1]/button[1]"

    def get_username_xpath(self) -> str:
        return "/html[1]/body[1]/main[1]/div[4]/div[1]/div[1]/div[2]/div[2]/div[2]/form[1]/div[1]/div[2]/input[1]"

    def get_password_xpath(self) -> str:
        return "/html[1]/body[1]/main[1]/div[4]/div[1]/div[1]/div[2]/div[2]/div[2]/form[1]/div[2]/div[2]/input[1]"

    def get_login_button_xpath(self) -> str:
        return "/html[1]/body[1]/main[1]/div[4]/div[1]/div[1]/div[2]/div[2]/div[2]/form[1]/button[1]"

    def _handle_2fa_if_present(self, credentials: Credentials) -> bool:
        try:
            verification_input_xpath = "/html/body/main/div/div[1]/div/div[2]/uxp-flow/div/identity-verification/div/div[1]/form/div[2]/div[2]/div[3]/div[2]/div[1]/input"
            radio_button = "/html/body/main/div/div[1]/div/div[2]/uxp-flow/div/identity-verification/div/div[1]/form/div[1]/section/div[2]/div/label[1]/input"
            if self.browser_wrapper.is_element_visible(radio_button, timeout=40000):
                print("2FA field detected. Starting verification process...")
                return self._process_2fa(verification_input_xpath, credentials)
            else:
                print("No 2FA field detected")
                time.sleep(10)
                return True

        except MFACodeError:
            raise
        except Exception as e:
            print(f"Error verifying 2FA: {str(e)}")
            return True

    def _process_2fa(self, verification_input_xpath: str, credentials: Credentials) -> bool:
        text_message_radio_xpath = "/html/body/main/div/div[1]/div/div[2]/uxp-flow/div/identity-verification/div/div[1]/form/div[1]/section/div[2]/div/label[1]"
        send_button_xpath = "/html/body/main/div/div[1]/div/div[2]/uxp-flow/div/identity-verification/div/div[1]/form/div[2]/div[2]/div[2]/div[2]/button"
        continue_button_xpath = (
            "/html/body/main/div/div[1]/div/div[2]/uxp-flow/div/identity-verification/div/div[2]/div/button[1]"
        )

        print("Selecting text message option...")
        self.browser_wrapper.click_element(text_message_radio_xpath)
        time.sleep(1)

        print("Sending SMS code request...")
        self.browser_wrapper.click_element(send_button_xpath)
        time.sleep(2)

        print("Waiting for MFA code from SSE endpoint...")
        endpoint_url = f"{self.webhook_url}/api/v1/bell"
        sms_code = self._consume_mfa_sse_stream(endpoint_url, credentials.username)

        print(f"Entering code: {sms_code}")
        self.browser_wrapper.click_element(verification_input_xpath)
        self.browser_wrapper.clear_and_type(verification_input_xpath, sms_code)
        time.sleep(1)

        print("Clicking Continue...")
        self.browser_wrapper.change_button_attribute(continue_button_xpath, "disabled", "false")
        self.browser_wrapper.click_element(continue_button_xpath)
        time.sleep(5)

        if self.browser_wrapper.is_element_visible(verification_input_xpath, timeout=3000):
            print("2FA validation failed - field still visible")
            return False

        print("2FA validation successful")
        return True


class TelusAuthStrategy(AuthBaseStrategy):

    def __init__(self, browser_wrapper: BrowserWrapper, webhook_url: str = None):
        super().__init__(browser_wrapper)
        self.webhook_url = webhook_url or DEFAULT_MFA_SERVICE_URL
        self.logger = logging.getLogger(self.__class__.__name__)

    def login(self, credentials: Credentials) -> bool:
        try:
            self.logger.info("Starting login in Telus...")

            # Wire the CF guard into the wrapper so any goto/click/wait_for_page_load
            # triggers _is_cloudflare_challenge + resolution. Without this, CF
            # challenges that appear AFTER the initial login (subdomain hops,
            # account switches, report navigation) break the flow with no recovery.
            if hasattr(self.browser_wrapper, "set_post_action_hook"):
                self.browser_wrapper.set_post_action_hook(self.ensure_no_cloudflare)

            login_url = self.get_login_url()
            self.browser_wrapper.goto(login_url, wait_until="domcontentloaded")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(5)

            # Step 1: Detect and wait for Cloudflare challenge if present
            if self._is_cloudflare_challenge():
                self.logger.warning("Cloudflare challenge detected, waiting for auto-resolve...")
                if not self._wait_for_cloudflare_resolution():
                    self.logger.error("Cloudflare challenge did not resolve in time")
                    return False

            # Step 2: Check if already logged in (CDP persists cookies via user-data-dir)
            if self._is_already_logged_in():
                self.logger.info("Already logged in (session persisted), skipping credential entry")
                return True

            # Step 3: Dismiss cookie banner if present
            self._dismiss_cookie_banner()

            # Step 4: Handle potential blocking popup with skip button
            self._try_skip_popup()

            # Navigate directly to My Telus — avoids fragile nav button XPaths
            self.logger.info("Navigating to My Telus...")
            self.browser_wrapper.goto("https://www.telus.com/my-telus")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)

            # Check again after navigation — may have been redirected to logged-in state
            if self._is_already_logged_in():
                self.logger.info("Already logged in after My Telus navigation")
                return True

            # Wait for Cloudflare again on login page
            if self._is_cloudflare_challenge():
                self.logger.warning("Cloudflare challenge on login page, waiting...")
                if not self._wait_for_cloudflare_resolution():
                    self.logger.error("Cloudflare challenge did not resolve on login page")
                    return False

            # Selector lists ordered most-stable-first. data-testid attributes are
            # the most resilient anchor (Telus keeps them across redesigns); ids
            # come next; aria-label / structural xpath are last-resort fallbacks.
            email_selectors = [
                ('[data-testid="login-form-email-input"]', "css"),
                ("#idtoken1", "css"),
                ('input[aria-label="Email or username"]', "css"),
                ('//*[@id="login-form"]//input[@type="text"]', "xpath"),
            ]
            password_selectors = [
                ('[data-testid="login-form-password-input"]', "css"),
                ("#idtoken2", "css"),
                ('input[aria-label="Password"]', "css"),
                ('//*[@id="login-form"]//input[@type="password"]', "xpath"),
            ]
            login_button_selectors = [
                ('[data-testid="login-form-submit-button"]', "css"),
                ("#login-btn", "css"),
                ('//*[@id="login-form"]//*[@role="button"]', "xpath"),
            ]

            self.logger.info(f"Entering email: {credentials.username}")
            email_field = self._find_first_visible(email_selectors, total_timeout_ms=20000)
            if email_field is None:
                # Raise so SessionManager.login()'s except path persists the detail
                # in session_state.error_message — without it, the scraper_job log
                # only sees the generic "Login failed for Carrier.TELUS".
                raise RuntimeError(self._build_login_diagnostics("email field"))
            self.logger.info(f"Email field located via {email_field[1]}={email_field[0]}")
            self.browser_wrapper.clear_and_type(email_field[0], credentials.username, selector_type=email_field[1])
            time.sleep(1)

            self.logger.info("Entering password...")
            password_field = self._find_first_visible(password_selectors, total_timeout_ms=10000)
            if password_field is None:
                raise RuntimeError(self._build_login_diagnostics("password field"))
            self.logger.info(f"Password field located via {password_field[1]}={password_field[0]}")
            self.browser_wrapper.clear_and_type(password_field[0], credentials.password, selector_type=password_field[1])
            time.sleep(1)

            self.logger.info("Clicking Login...")
            login_button = self._find_first_visible(login_button_selectors, total_timeout_ms=5000)
            if login_button is None:
                raise RuntimeError(self._build_login_diagnostics("login submit button"))
            self.browser_wrapper.click_element(login_button[0], selector_type=login_button[1])
            time.sleep(5)

            if self.is_logged_in():
                self.logger.info("Login successful in Telus")
                return True
            else:
                self.logger.error("Login failed in Telus")
                return False

        except Exception as e:
            self.logger.error(f"Error during login in Telus: {str(e)}")
            return False

    def _find_first_visible(
        self, selectors: list, total_timeout_ms: int = 15000
    ):
        # Iterate selectors in priority order; returns the first (selector, selector_type)
        # that becomes visible within total_timeout_ms. Each individual probe is short so a
        # late-rendered field is still picked up on a subsequent pass. Returns None on timeout.
        deadline = time.time() + (total_timeout_ms / 1000.0)
        per_probe_ms = 500
        while time.time() < deadline:
            for selector, selector_type in selectors:
                if self.browser_wrapper.is_element_visible(
                    selector, timeout=per_probe_ms, selector_type=selector_type
                ):
                    return (selector, selector_type)
            time.sleep(0.3)
        return None

    def _build_login_diagnostics(self, missing_field: str) -> str:
        # Build the detailed failure message AND log it. The returned string is
        # raised by the caller so SessionManager / main.py persist it in the
        # scraper_job log — otherwise the only signal upstream is the generic
        # "Login failed for Carrier.TELUS", which is what the user flagged as
        # too terse.
        try:
            current_url = self.browser_wrapper.get_current_url()
        except Exception as e:
            current_url = f"<error reading url: {e}>"
        try:
            page_title = self.browser_wrapper.page.title()
        except Exception as e:
            page_title = f"<error reading title: {e}>"
        msg = (
            f"Telus login: {missing_field} not found with any selector. "
            f"Current URL: {current_url}. Page title: {page_title!r}"
        )
        self.logger.error(msg)
        return msg

    def logout(self) -> bool:
        try:
            print("Starting logout in Telus...")
            self.browser_wrapper.goto("https://www.telus.com/my-telus")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)

            avatar_menu_xpath = '//*[@id="ge-top-nav"]/ul[2]/li[3]/button'
            print("Clicking avatar menu...")
            self.browser_wrapper.click_element(avatar_menu_xpath)
            time.sleep(2)

            logout_button_xpath = '//*[@id="ge-top-nav"]/ul[2]/li[3]/nav/div/ul/li[5]/a'
            print("Clicking Logout...")
            self.browser_wrapper.click_element(logout_button_xpath)
            time.sleep(3)

            print("Logout successful in Telus")
            return True

        except Exception as e:
            print(f"Error during logout in Telus: {str(e)}")
            return False

    def is_logged_in(self) -> bool:
        """Verifica si el usuario esta logueado en Telus usando multiples metodos."""
        try:
            current_url = self.browser_wrapper.get_current_url()
            self.logger.info(f"Verifying login at URL: {current_url}")

            # Metodo 1: Verificar si estamos en my-telus (indica login exitoso)
            if "my-telus" in current_url:
                self.logger.info("URL contains 'my-telus' - probably logged in")

                # Verificar elementos que solo aparecen cuando esta logueado
                logged_in_indicators = [
                    # Avatar menu button (multiples variantes)
                    "/html[1]/body[1]/header[1]/div[1]/div[2]/div[1]/nav[1]/ul[2]/li[3]/button[1]",
                    "//button[contains(@class, 'avatar') or contains(@aria-label, 'account')]",
                    "//nav//button[contains(@class, 'user') or contains(@class, 'profile')]",
                    # Elementos del dashboard de my-telus
                    "//div[contains(@class, 'account-overview')]",
                    "//*[@id='__next']//div[contains(@class, 'dashboard')]",
                    # Cualquier elemento que indique balance o cuenta
                    "//*[contains(text(), 'Your balance') or contains(text(), 'Account')]",
                ]

                for xpath in logged_in_indicators:
                    try:
                        if self.browser_wrapper.is_element_visible(xpath, timeout=3000):
                            self.logger.info(f"Login confirmed with element: {xpath[:50]}...")
                            return True
                    except Exception:
                        continue

                # Si estamos en my-telus pero no encontramos indicadores, asumir logueado
                self.logger.info("On my-telus with no visible indicators, assuming logged in")
                return True

            # Metodo 2: Verificar si estamos en pagina de login (indica NO logueado)
            login_page_indicators = [
                "//input[@id='idtoken1']",  # Campo de email en login
                "//input[@id='idtoken2']",  # Campo de password en login
                "//*[@id='login-btn']",  # Boton de login
                "/html/body/div[1]/div/div[1]/div/div/div[1]/form/div[1]/div[1]/div[3]/input",  # Fallback email
                "/html/body/div[1]/div/div[1]/div/div/div[1]/form/div[2]/div[3]/input",  # Fallback password
            ]

            for xpath in login_page_indicators:
                try:
                    if self.browser_wrapper.is_element_visible(xpath, timeout=2000):
                        self.logger.info(f"Login page detected with: {xpath}")
                        return False
                except Exception:
                    continue

            # Metodo 3: Navegar a my-telus para verificar
            self.logger.info("Navigating to my-telus to verify login state...")
            self.browser_wrapper.goto("https://www.telus.com/my-telus")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)

            # Verificar URL despues de navegar
            new_url = self.browser_wrapper.get_current_url()
            if "my-telus" in new_url and "login" not in new_url.lower():
                self.logger.info("Successfully navigated to my-telus - user is logged in")
                return True

            self.logger.info("Could not confirm login")
            return False

        except Exception as e:
            self.logger.error(f"Error verifying login state: {str(e)}")
            return False

    def get_login_url(self) -> str:
        return CarrierPortalUrls.TELUS.value

    def get_logout_xpath(self) -> str:
        return "/html[1]/body[1]/header[1]/div[1]/div[2]/div[1]/nav[1]/ul[2]/li[3]/nav[1]/div[1]/ul[1]/li[5]/a[1]"

    def get_username_xpath(self) -> str:
        return "/html[1]/body[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/form[1]/div[1]/div[1]/div[3]/input[1]"

    def get_password_xpath(self) -> str:
        return "/html[1]/body[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/form[1]/div[2]/div[3]/input[1]"

    def get_login_button_xpath(self) -> str:
        return "/html[1]/body[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/form[1]/div[4]/div[1]"

    def _is_cloudflare_challenge(self) -> bool:
        """Detecta si la pagina actual es un challenge de Cloudflare."""
        try:
            html = self.browser_wrapper.get_page_content()
            markers = [
                "Just a moment",
                "Checking if the site connection is secure",
                "cf-challenge",
                "cf_chl_opt",
            ]
            return any(marker in html for marker in markers)
        except Exception:
            return False

    def ensure_no_cloudflare(self) -> None:
        """Run the resolver if a CF challenge appears at this moment. Designed to
        be wired into PlaywrightWrapper as a post-action hook so any navigation
        the Telus scraper makes after login is also covered — Turnstile shows up
        again on cross-subdomain hops (my-telus -> ebill, account switches, etc.)
        and previously broke the run because nothing checked for it mid-flow.
        """
        if self._is_cloudflare_challenge():
            self.logger.warning("[cf-guard] Cloudflare challenge detected mid-flow, resolving")
            self._wait_for_cloudflare_resolution()

    def _get_cloudflare_iframe(self, timeout_ms: int = 4000):
        """Devuelve (frame_element, frame) del widget Turnstile, o (None, None).

        Cloudflare's interstitial wraps the widget iframe inside a CLOSED shadow
        root on the parent page, so page.query_selector() cannot reach it. We
        iterate page.frames (Playwright tracks every frame via CDP regardless
        of shadow DOM) and recover the parent-page iframe handle via
        frame_element() — its bounding_box() is in main-page coords, which is
        exactly what _humanlike_click_iframe() needs to drive page.mouse.
        """
        deadline = time.time() + (timeout_ms / 1000)
        while time.time() < deadline:
            for frame in self.browser_wrapper.page.frames:
                url = frame.url or ""
                if "challenges.cloudflare.com" in url or "turnstile" in url:
                    try:
                        handle = frame.frame_element()
                        if handle:
                            return handle, frame
                    except Exception:
                        continue
            time.sleep(0.3)
        return None, None

    def _cloudflare_widget_state(self, frame) -> str:
        """Inspecciona el iframe Turnstile y devuelve: success/fail/timeout/expired/error/verifying/idle/unknown."""
        state_checks = [
            ("success", "#success"),
            ("fail", "#fail"),
            ("timeout", "#timeout"),
            ("expired", "#expired"),
            ("error", "#challenge-error"),
            ("verifying", "#verifying"),
        ]
        for name, sel in state_checks:
            try:
                el = frame.query_selector(sel)
                if el and el.is_visible():
                    return name
            except Exception:
                continue
        try:
            cb = frame.query_selector("input[type='checkbox']")
            if cb and cb.is_visible():
                return "idle"
        except Exception:
            pass
        return "unknown"

    def _wait_for_cloudflare_resolution(self, pre_click_wait: int = 15, post_click_wait: int = 30) -> bool:
        """Espera auto-resolve; si no, clickea el checkbox y vuelve a esperar. Aborta temprano si el widget falla."""
        # Phase 1: wait for auto-resolve, watching widget state
        deadline = time.time() + pre_click_wait
        while time.time() < deadline:
            time.sleep(2)
            if not self._is_cloudflare_challenge():
                self.logger.info("Cloudflare challenge auto-resolved")
                return True
            _, frame = self._get_cloudflare_iframe()
            if frame:
                state = self._cloudflare_widget_state(frame)
                if state == "success":
                    self.logger.info("Cloudflare widget reports success during auto-resolve")
                    time.sleep(3)
                    return True
                if state in ("fail", "timeout", "expired", "error"):
                    self.logger.warning("Cloudflare widget in '%s' state during auto-resolve, will attempt click", state)
                    break

        # Phase 2: click the checkbox
        self.logger.warning("Cloudflare did not auto-resolve, attempting to click challenge checkbox...")
        if not self._click_cloudflare_checkbox():
            self.logger.error("Could not click Cloudflare checkbox")
            return False

        # Phase 3: wait for resolution after click
        deadline = time.time() + post_click_wait
        while time.time() < deadline:
            time.sleep(2)
            if not self._is_cloudflare_challenge():
                self.logger.info("Cloudflare resolved after clicking checkbox")
                return True
            _, frame = self._get_cloudflare_iframe()
            if frame:
                state = self._cloudflare_widget_state(frame)
                if state == "success":
                    self.logger.info("Cloudflare widget reports success after click")
                    time.sleep(3)
                    return True
                if state in ("fail", "timeout", "expired", "error"):
                    self.logger.error("Cloudflare widget in '%s' state after click, aborting", state)
                    return False

        self.logger.error("Cloudflare challenge could not be resolved")
        return False

    def _click_cloudflare_checkbox(self) -> bool:
        """Click the Turnstile checkbox using a humanlike mouse trajectory.

        Telus's CF interstitial puts the widget inside a closed shadow root, so
        a query_selector-based click on the iframe contents cannot reach the
        checkbox. We drive page.mouse directly in main-page coordinates derived
        from the iframe's bounding_box — the OS-level mouse pipeline doesn't
        respect shadow DOM, which is the same reason a manual click works.
        """
        try:
            frame_element, frame = self._get_cloudflare_iframe()
            if not frame_element or not frame:
                self.logger.warning("Could not find Cloudflare iframe to click")
                return False

            # Wait until widget is actionable (not mid-verifying)
            actionable_deadline = time.time() + 10
            while time.time() < actionable_deadline:
                state = self._cloudflare_widget_state(frame)
                if state == "success":
                    self.logger.info("Cloudflare already in success state, no click needed")
                    return True
                if state in ("fail", "timeout", "expired", "error"):
                    self.logger.warning("Cloudflare in '%s' state, click unlikely to help", state)
                    return False
                if state == "verifying":
                    time.sleep(1)
                    continue
                break  # idle/unknown -> proceed to click

            return self._humanlike_click_iframe(frame_element)
        except Exception as e:
            self.logger.error(f"Error clicking Cloudflare checkbox: {e}")
            return False

    def _humanlike_click_iframe(
        self,
        frame_element,
        target_offset_x: float = 28,
        target_offset_y: float = 30,
        jitter_px: float = 4,
    ) -> bool:
        """Drive page.mouse with a curved trajectory + hover dwell + natural
        click duration. Coords are in main-page space from the iframe's
        bounding_box, so this works even when the iframe lives inside a closed
        shadow root (which is why a normal element.click() fails on Telus CF).
        """
        box = frame_element.bounding_box()
        if not box:
            self.logger.warning("Cloudflare iframe has no bounding_box, cannot click")
            return False

        jitter = lambda: random.uniform(-jitter_px, jitter_px)
        target_x = box["x"] + target_offset_x + jitter()
        target_y = box["y"] + target_offset_y + jitter()
        waypoint_x = target_x + random.uniform(-180, 180)
        waypoint_y = target_y - random.uniform(60, 180)

        page = self.browser_wrapper.page
        page.mouse.move(waypoint_x, waypoint_y, steps=10)
        time.sleep(random.uniform(0.04, 0.12))
        page.mouse.move(target_x, target_y, steps=25)
        time.sleep(random.uniform(0.18, 0.42))
        page.mouse.down()
        time.sleep(random.uniform(0.04, 0.11))
        page.mouse.up()

        self.logger.info(
            "Humanlike click on CF widget at (%.1f, %.1f) — iframe box x=%.1f y=%.1f w=%.0f h=%.0f",
            target_x, target_y, box["x"], box["y"], box["width"], box["height"],
        )
        return True

    def _dismiss_cookie_banner(self) -> None:
        """Dismiss cookie consent banner if present."""
        try:
            accept_xpath = '//button[contains(text(), "Accept all cookies")]'
            if self.browser_wrapper.is_element_visible(accept_xpath, timeout=3000):
                self.browser_wrapper.click_element(accept_xpath)
                self.logger.info("Dismissed cookie banner")
                time.sleep(1)
        except Exception:
            pass

    def _is_already_logged_in(self) -> bool:
        """Detecta si ya hay sesion activa (util con CDP que persiste cookies)."""
        try:
            current_url = self.browser_wrapper.get_current_url().lower()
            title = self.browser_wrapper.get_page_title().lower()
            if "my-telus" in current_url or "overview" in title or "dashboard" in current_url:
                return True
            return False
        except Exception:
            return False

    def _try_skip_popup(self) -> None:
        """Try to dismiss a blocking popup by clicking the skip button if present."""
        skip_button_xpath = "//*[@id='skip-button']"
        try:
            if self.browser_wrapper.is_element_visible(skip_button_xpath, timeout=3000):
                print("Blocking popup detected, clicking skip button...")
                self.browser_wrapper.click_element(skip_button_xpath)
                time.sleep(1)
                print("Popup dismissed")
            else:
                print("No blocking popup detected, continuing...")
        except Exception as e:
            print(f"Error handling popup (non-critical): {str(e)}")

    # TODO: Implementar _handle_2fa_if_present si Telus requiere 2FA
    # Pasos pendientes:
    # 1. Identificar si el portal requiere 2FA y cómo detectarlo
    # 2. Identificar los XPaths de los elementos de 2FA
    # 3. Usar el método heredado _consume_mfa_sse_stream:
    #     endpoint_url = f"{self.webhook_url}/api/v1/telus"
    #     code = self._consume_mfa_sse_stream(endpoint_url, credentials.username)


class RogersAuthStrategy(AuthBaseStrategy):

    def __init__(self, browser_wrapper: BrowserWrapper, webhook_url: str = None):
        super().__init__(browser_wrapper)
        self.webhook_url = webhook_url or DEFAULT_MFA_SERVICE_URL
        self.logger = logging.getLogger(self.__class__.__name__)

    def login(self, credentials: Credentials) -> bool:
        try:
            self.logger.info("Starting login in Rogers...")

            # The username/password steps are served by Transmit Security
            # (account-business.rogers.com). On a cold browser profile the heavy
            # IdP JS bundle can take well over 30s to render the password field,
            # so the first attempt times out; the bundle is then cached in the
            # persistent profile and a fresh reload renders it quickly. Retry the
            # navigate->Sign In->username->Continue sequence so a cold start
            # self-heals within a single login() call (a reload hits the now-warm
            # cache) instead of failing the whole job and waiting for the next-day
            # retry.
            password_input_xpath = '//*[@id="input_password"]'
            max_password_attempts = 2
            password_field_ready = False
            for attempt in range(1, max_password_attempts + 1):
                try:
                    self._navigate_to_password_step(credentials)
                    self.browser_wrapper.wait_for_element(password_input_xpath, timeout=30000)
                    password_field_ready = True
                    break
                except Exception as e:
                    if attempt < max_password_attempts:
                        self.logger.warning(
                            f"Password field not ready on attempt {attempt}/{max_password_attempts} "
                            f"({e}); reloading the Transmit Security page (now warm) and retrying..."
                        )
                    else:
                        self.logger.error(
                            f"Password field never rendered after {max_password_attempts} attempts: {e}"
                        )
            if not password_field_ready:
                return False

            # Enter password
            self.logger.info("Entering password...")
            self.browser_wrapper.clear_and_type(password_input_xpath, credentials.password)
            time.sleep(1)

            # Click Sign In button
            login_button_xpath = '//*[@id="LoginForm"]/div[4]/button'
            self.logger.info("Clicking Sign In...")
            self.browser_wrapper.click_element(login_button_xpath)
            time.sleep(5)

            # Handle 2FA if present
            if not self._handle_2fa_if_present(credentials):
                self.logger.error("2FA failed - interrupting login")
                return False

            if self.is_logged_in():
                self.logger.info("Login successful in Rogers")
                return True
            else:
                self.logger.error("Login failed in Rogers")
                return False

        except MFACodeError as e:
            self.logger.error(f"MFA error during login in Rogers: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Error during login in Rogers: {str(e)}")
            return False

    def _navigate_to_password_step(self, credentials: Credentials) -> None:
        # Navega desde la URL de login a traves de Sign In + usuario + Continue y
        # deja la pagina en el paso de password de Transmit Security. Es seguro
        # llamarlo varias veces: cada invocacion re-navega a la URL de login desde
        # cero, por lo que el reintento descarta cualquier estado previo.
        self.browser_wrapper.goto(self.get_login_url())
        time.sleep(3)

        # Click on Sign In button (try multiple XPaths as the structure may vary)
        sign_in_button_xpaths = [
            '//*[@id="login"]/div[2]/div[3]/div/input',
            '//*[@id="login"]/div[2]/div[4]/div/input',
        ]
        self.logger.info("Clicking Sign In button...")
        for xpath in sign_in_button_xpaths:
            try:
                if self.browser_wrapper.is_element_visible(xpath, timeout=3000):
                    self.logger.info(f"Sign In button found with xpath: {xpath}")
                    self.browser_wrapper.click_element(xpath)
                    break
            except Exception:
                continue
        else:
            raise Exception("Sign In button not found with any of the known XPaths")
        time.sleep(3)

        # Enter username/email
        username_input_xpath = '//*[@id="ds-form-input-id-0"]'
        self.logger.info(f"Entering username: {credentials.username}")
        self.browser_wrapper.wait_for_element(username_input_xpath, timeout=10000)
        self.browser_wrapper.clear_and_type(username_input_xpath, credentials.username)
        time.sleep(1)

        # Click Continue button
        continue_button_xpath = (
            "/html/body/app-root/div/div/div/div/div/div/div/div/ng-component/form/div[3]/button"
        )
        self.logger.info("Clicking Continue...")
        self.browser_wrapper.click_element(continue_button_xpath)
        time.sleep(5)

    def logout(self) -> bool:
        try:
            self.logger.info("Starting logout in Rogers...")

            # Navigate to home page first
            self.browser_wrapper.goto("https://bss.rogers.com/bizonline/homePage.do")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)

            if not self.is_logged_in():
                self.logger.info("Already logged out")
                return True

            # Click logout button
            logout_button_xpath = '//*[@id="header_greeting"]/a[2]'
            self.logger.info("Clicking Logout...")
            if self.browser_wrapper.is_element_visible(logout_button_xpath, timeout=5000):
                self.browser_wrapper.click_element(logout_button_xpath)
                self.browser_wrapper.wait_for_page_load()
                time.sleep(3)
                self.logger.info("Logout successful in Rogers")
                self._cleanup_persistent_profile()
                return True
            else:
                self.logger.error("Logout button not found")
                return False

        except Exception as e:
            self.logger.error(f"Error during logout in Rogers: {str(e)}")
            return False

    def _cleanup_persistent_profile(self) -> None:
        # Borra el browser_profile persistente de Rogers tras logout exitoso para que
        # el proximo run arranque con perfil limpio. Solo se invoca cuando se hizo click
        # en logout — si nunca se inicio sesion, el dir no se toca.
        # Nota: el proceso del run (main.py bajo flock) muere al final, por lo que los
        # locks del navegador ya se liberaron. ignore_errors cubre el caso de archivos
        # aun bloqueados en entornos donde el proceso siga vivo (dev local).
        profile_dir = Path(os.getcwd()) / "browser_profiles" / "rogers_profile"
        if not profile_dir.exists():
            return
        try:
            shutil.rmtree(profile_dir, ignore_errors=True)
            self.logger.info(f"Rogers persistent profile deleted: {profile_dir}")
        except Exception as e:
            self.logger.warning(f"Could not delete Rogers persistent profile {profile_dir}: {e}")

    def is_logged_in(self) -> bool:
        # Two independent signals: the welcome banner is the most direct, but its class name
        # (`Welcome-Oliver-Gree`) looks autogenerated and could change. The `landing_left_pan`
        # id is functional (not styling) so it survives redesigns. If either is visible we
        # treat the session as active. Previous absolute xpath /html/body/div[1]/div[2]/div[2]
        # was too brittle and produced false negatives right after 2FA finished, before the
        # post-login DOM finished rendering.
        try:
            welcome_xpath = "//div[contains(@class, 'Welcome-Oliver-Gree')]"
            if self.browser_wrapper.is_element_visible(welcome_xpath, timeout=10000):
                welcome_text = self.browser_wrapper.get_text(welcome_xpath)
                if welcome_text and "welcome" in welcome_text.lower():
                    self.logger.info(f"Welcome message found: {welcome_text.strip()}")
                    return True

            landing_pane_xpath = "//div[@id='landing_left_pan']"
            if self.browser_wrapper.is_element_visible(landing_pane_xpath, timeout=2000):
                self.logger.info("Landing pane detected — session is active")
                return True

            return False
        except Exception as e:
            self.logger.error(f"Error checking login status: {str(e)}")
            return False

    def get_login_url(self) -> str:
        return CarrierPortalUrls.ROGERS.value

    def get_logout_xpath(self) -> str:
        return '//*[@id="header_greeting"]/a[2]'

    def get_username_xpath(self) -> str:
        return '//*[@id="ds-form-input-id-0"]'

    def get_password_xpath(self) -> str:
        return '//*[@id="input_password"]'

    def get_login_button_xpath(self) -> str:
        return '//*[@id="LoginForm"]/div[4]/button'

    def _handle_2fa_if_present(self, credentials: Credentials) -> bool:
        """Detect and handle MFA if present for Rogers."""
        try:
            verification_h1_xpath = (
                "/html/body/app-root/div/div/div/div/div/div/div/div/otp-device-list/div/h1"
            )

            if self.browser_wrapper.is_element_visible(verification_h1_xpath, timeout=10000):
                h1_text = self.browser_wrapper.get_text(verification_h1_xpath)
                if h1_text and "receive verification code" in h1_text.lower():
                    self.logger.info("2FA verification screen detected. Starting verification process...")
                    return self._process_2fa(credentials)
                else:
                    self.logger.info(f"H1 found but different content: {h1_text}")
                    return True
            else:
                self.logger.info("No 2FA verification screen detected")
                time.sleep(5)
                return True

        except MFACodeError:
            raise
        except Exception as e:
            self.logger.error(f"Error verifying 2FA: {str(e)}")
            return True

    def _process_2fa(self, credentials: Credentials) -> bool:
        """Process 2FA by selecting Email option and entering the code."""
        email_button_xpath = (
            "/html/body/app-root/div/div/div/div/div/div/div/div/otp-device-list/div/div[2]/button"
        )
        # First input of the ds-code-input component (there are 6 individual inputs)
        first_code_input_xpath = (
            "/html/body/app-root/div/div/div/div/div/div/div/div/otp-waiting-for-input/div/form/div/div[1]"
            "/ds-code-input/div/div[2]/input"
        )
        verify_button_xpath = (
            "/html/body/app-root/div/div/div/div/div/div/div/div/otp-waiting-for-input/div/form/div/button"
        )

        # Verify the button contains "Email" before clicking
        if self.browser_wrapper.is_element_visible(email_button_xpath, timeout=5000):
            button_text = self.browser_wrapper.get_text(email_button_xpath)
            if button_text and "email" in button_text.lower():
                self.logger.info(f"Email option found: {button_text.strip()}")
                self.browser_wrapper.click_element(email_button_xpath)
                time.sleep(2)
            else:
                self.logger.warning(f"Button does not contain 'Email': {button_text}")
                return False
        else:
            self.logger.error("Email button not found")
            return False

        # Wait for MFA code from SSE endpoint
        self.logger.info("Waiting for MFA code from SSE endpoint...")
        endpoint_url = f"{self.webhook_url}/api/v1/rogers"
        mfa_code = self._consume_mfa_sse_stream(endpoint_url, credentials.username)

        # Enter code using keyboard.type() to handle multi-input OTP component
        # The ds-code-input component has 6 individual inputs, clicking the first
        # and typing triggers the component's internal logic to distribute digits
        self.logger.info(f"Entering code: {mfa_code}")
        self.browser_wrapper.wait_for_element(first_code_input_xpath, timeout=10000)
        self.browser_wrapper.click_element(first_code_input_xpath)
        time.sleep(0.3)
        self.browser_wrapper.page.keyboard.type(mfa_code, delay=100)
        time.sleep(1)

        # Click verify button
        self.logger.info("Clicking Verify button...")
        self.browser_wrapper.click_element(verify_button_xpath)

        self.browser_wrapper.wait_for_page_load()
        time.sleep(5)

        # Check if code input is still visible (indicates failure)
        if self.browser_wrapper.is_element_visible(first_code_input_xpath, timeout=3000):
            self.logger.error("2FA validation failed - code input still visible")
            return False

        self.logger.info("2FA validation successful")
        return True


class ATTAuthStrategy(AuthBaseStrategy):

    def __init__(self, browser_wrapper: BrowserWrapper, webhook_url: str = None):
        super().__init__(browser_wrapper)
        self.webhook_url = webhook_url or DEFAULT_MFA_SERVICE_URL
        self.logger = logging.getLogger(self.__class__.__name__)

    def login(self, credentials: Credentials) -> bool:
        try:
            self.logger.info("Starting login in AT&T...")

            self.browser_wrapper.goto(self.get_login_url())
            time.sleep(3)

            # A previous failed run can leave AT&T in pending-MFA state, so navigating to
            # the login URL redirects straight to the delivery form or OTP entry. Detect
            # that and skip credential entry, otherwise the username xpath times out.
            delivery_form_xpath = "//*[@id='deliveryForm']"
            otp_input_xpath = "//*[@id='enterOtp']"
            if self.browser_wrapper.is_element_visible(delivery_form_xpath, timeout=5000) or \
               self.browser_wrapper.is_element_visible(otp_input_xpath, timeout=1000):
                self.logger.info("Pending-MFA state detected on landing — skipping credentials entry")
                if not self._handle_2fa_if_present(credentials):
                    self.logger.warning("2FA failed - interrupting login")
                    return False
                self._dismiss_modal_if_present()
                return self.is_logged_in()

            username_xpath = (
                "/html/body/app-root/div/div/div/div/app-login-general/app-card/div/div/div/form/div[1]/input"
            )
            self.logger.info(f"Entering username: {credentials.username}")
            self.browser_wrapper.type_text(username_xpath, credentials.username)
            time.sleep(1)

            continue_button_xpath = (
                "/html/body/app-root/div/div/div/div/app-login-general/app-card/div/div/div/form/div[3]/button"
            )
            self.logger.info("Clicking Continue...")
            self.browser_wrapper.click_element(continue_button_xpath)
            time.sleep(3)

            password_xpath = (
                "/html/body/app-root/div/div/div/div/app-login-password/app-card/div/div/div/form/div[2]/input"
            )
            self.logger.info("Entering password...")
            self.browser_wrapper.type_text(password_xpath, credentials.password)
            time.sleep(1)

            signin_button_xpath = (
                "/html/body/app-root/div/div/div/div/app-login-password/app-card/div/div/div/form/div[3]/button"
            )
            self.logger.info("Clicking Sign In...")
            self.browser_wrapper.click_element(signin_button_xpath)
            time.sleep(5)

            self.logger.info("Checking for 2FA...")
            if not self._handle_2fa_if_present(credentials):
                self.logger.warning("2FA failed - interrupting login")
                return False

            self._dismiss_modal_if_present()
            return self.is_logged_in()

        except MFACodeError as e:
            self.logger.error(f"MFA error during login in AT&T: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Error during login in AT&T: {str(e)}")
            return False

    def logout(self) -> bool:
        try:
            self.logger.info("Starting logout in AT&T...")

            self.browser_wrapper.goto("https://www.wireless.att.com/premiercare/")
            time.sleep(30)
            if not self.is_logged_in():
                self.logger.info("User already logged out")
                return True

            logout_button_xpath = "/html/body/div[1]/div/div[1]/ul/li[4]/a"
            self.logger.info("Clicking Logout...")
            self.browser_wrapper.click_element(logout_button_xpath)
            time.sleep(15)
            self.logger.info("Logout successful in AT&T")
            return True

        except Exception as e:
            self.logger.error(f"Error during logout in AT&T: {str(e)}")
            return False

    def is_logged_in(self) -> bool:
        try:
            current_url = self.browser_wrapper.get_current_url()
            if "premiercare" not in current_url.lower():
                self.browser_wrapper.goto("https://www.wireless.att.com/premiercare/")
                time.sleep(2)

            my_profile_xpath = "/html/body/div[1]/div/div[2]/p/a"
            if self.browser_wrapper.is_element_visible(my_profile_xpath, timeout=10000):
                element_text = self.browser_wrapper.get_text(my_profile_xpath)
                if element_text and "My Profile" in element_text:
                    return True

            return False

        except Exception as e:
            self.logger.error(f"Error verifying login status: {str(e)}")
            return False

    def get_login_url(self) -> str:
        return CarrierPortalUrls.ATT.value

    def get_logout_xpath(self) -> str:
        return ""

    def get_username_xpath(self) -> str:
        return "/html/body/app-root/div/div/div/div/app-login-general/app-card/div/div/div/form/div[1]/input"

    def get_password_xpath(self) -> str:
        return "/html/body/app-root/div/div/div/div/app-login-password/app-card/div/div/div/form/div[2]/input"

    def get_login_button_xpath(self) -> str:
        return "/html/body/app-root/div/div/div/div/app-login-password/app-card/div/div/div/form/div[3]/button"

    def _handle_2fa_if_present(self, credentials: Credentials) -> bool:
        self.logger.info("Checking if 2FA is required...")

        delivery_form_xpath = "//*[@id='deliveryForm']"
        otp_input_xpath = "//*[@id='enterOtp']"

        # Two possible 2FA states: delivery-method picker OR direct OTP entry
        # (AT&T skips the picker once a preferred method has been saved).
        on_otp_page = self.browser_wrapper.is_element_visible(otp_input_xpath, timeout=5000)
        on_delivery_form = False
        if not on_otp_page:
            on_delivery_form = self.browser_wrapper.is_element_visible(delivery_form_xpath, timeout=5000)

        if not on_otp_page and not on_delivery_form:
            self.logger.info("No 2FA detected (neither delivery form nor OTP input)")
            return True

        if on_delivery_form:
            self.logger.info("2FA delivery form detected, selecting email method...")
            email_option_xpath = self._find_first_email_option()
            if not email_option_xpath:
                self.logger.error("No email option found in 2FA form")
                return False

            self.logger.info(f"Selecting Email option: {email_option_xpath}")
            self.browser_wrapper.click_element(email_option_xpath)
            time.sleep(2)

            preferred_method_checkbox_xpath = "//*[@id='preferredMethodInput']"
            self.logger.info("Marking 'Set as my preferred method' checkbox...")
            self.browser_wrapper.click_element(preferred_method_checkbox_xpath)
            time.sleep(1)

            request_code_button_xpath = "//*[@id='continueButton']"
            self.logger.info("Clicking Continue to request Email code...")
            self.browser_wrapper.click_element(request_code_button_xpath)
            time.sleep(3)
        else:
            self.logger.info("2FA OTP page reached directly (preferred method already set)")

        self.logger.info("Waiting for MFA code from SSE endpoint...")
        endpoint_url = f"{self.webhook_url}/api/v1/att"
        code = self._consume_mfa_sse_stream(endpoint_url, credentials.username)

        self.logger.info(f"Code received: {code}")

        self.logger.info("Entering 2FA code...")
        self.browser_wrapper.type_text(otp_input_xpath, code)
        time.sleep(1)

        # checkbox1FormRow is a wrapping <div>; the actual checkbox <input> is #trustedDevice.
        trust_device_checkbox_xpath = "//*[@id='trustedDevice']"
        try:
            self.logger.info("Ensuring 'Trust this browser' checkbox is marked...")
            self.browser_wrapper.page.locator(f"xpath={trust_device_checkbox_xpath}").check(timeout=5000)
        except Exception as e:
            self.logger.warning(f"Could not mark trust-device checkbox (continuing): {e}")
        time.sleep(1)

        submit_code_button_xpath = "//*[@id='continue']"
        self.logger.info("Submitting 2FA code...")
        self.browser_wrapper.click_element(submit_code_button_xpath)
        time.sleep(30)
        self._dismiss_modal_if_present()

        self.logger.info("2FA processed successfully")
        return True

    def _dismiss_modal_if_present(self) -> None:
        # Verint feedback overlay ("We'd welcome your feedback!"); always decline.
        no_thanks_xpath = '//div[contains(@class, "uws-invite__button-decline")]'
        try:
            if self.browser_wrapper.is_element_visible(no_thanks_xpath, timeout=5000):
                self.logger.info("Feedback modal detected, clicking 'No, thanks'...")
                self.browser_wrapper.click_element(no_thanks_xpath)
                time.sleep(2)
            else:
                self.logger.debug("No feedback modal detected")
        except Exception as e:
            self.logger.warning(f"Could not dismiss feedback modal (continuing): {e}")

    def _find_first_email_option(self) -> Optional[str]:
        # The masked email suffix changes per account, so match radios by `label` starting with "Email".
        email_option_xpath = '(//input[@name="selectCTN" and starts-with(@label, "Email")])[1]'

        if self.browser_wrapper.is_element_visible(email_option_xpath, timeout=5000):
            self.logger.info("Found email radio in MFA delivery form")
            return email_option_xpath

        self.logger.warning("Email option not found")
        return None


class TMobileAuthStrategy(AuthBaseStrategy):

    def __init__(self, browser_wrapper: BrowserWrapper, webhook_url: str = None):
        super().__init__(browser_wrapper)
        self.webhook_url = webhook_url or DEFAULT_MFA_SERVICE_URL
        self.logger = logging.getLogger(self.__class__.__name__)

    def login(self, credentials: Credentials) -> bool:
        try:
            self.logger.info("Starting login in T-Mobile...")

            self.browser_wrapper.goto(self.get_login_url())

            time.sleep(3)

            # Handle language modal if present (select English)
            self._handle_language_modal()

            # Enter email/phone number
            email_xpath = '//*[@id="emailOrPhoneNumberTextBox"]'
            self.logger.info(f"Entering email/phone: {credentials.username}")
            self.browser_wrapper.clear_and_type(email_xpath, credentials.username)
            time.sleep(1)

            # Click Next button
            next_button_xpath = '//*[@id="lp1-next-btn"]'
            self.logger.info("Clicking Next...")
            self.browser_wrapper.click_element(next_button_xpath)
            time.sleep(3)

            # Enter password
            password_xpath = '//*[@id="passwordTextBox"]'
            self.logger.info("Entering password...")
            self.browser_wrapper.clear_and_type(password_xpath, credentials.password)
            time.sleep(1)

            # Click Login button
            login_button_xpath = '//*[@id="lp2-login-btn"]'
            self.logger.info("Clicking Log In...")
            self.browser_wrapper.click_element(login_button_xpath)
            time.sleep(5)

            # Handle 2FA if present
            if not self._handle_2fa_if_present(credentials):
                self.logger.error("Error in 2FA process")
                return False

            if self.is_logged_in():
                self.logger.info("Login successful in T-Mobile")
                return True
            else:
                self.logger.error("Login failed in T-Mobile")
                return False

        except MFACodeError as e:
            self.logger.error(f"MFA error during login in T-Mobile: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Error during login in T-Mobile: {str(e)}")
            return False

    def logout(self) -> bool:
        try:
            self.logger.info("Starting logout in T-Mobile...")

            # First, go to the dashboard
            self.browser_wrapper.goto("https://tfb.t-mobile.com/apps/tfb_billing/dashboard")
            time.sleep(3)

            if not self.is_logged_in():
                self.logger.info("Already logged out")
                return True

            # Logout button is in the second nav-list, 7th panel-title
            logout_xpath = "/html/body/globalnav-root/globalnav-nav/mat-sidenav-container/mat-sidenav/div/mat-nav-list[2]/mat-panel-title[7]/mat-list-item"
            logout_by_text_xpath = "//mat-list-item[.//span[contains(text(), 'Logout') or contains(text(), 'logout')]]"

            if self.browser_wrapper.is_element_visible(logout_xpath, timeout=5000):
                # Verify it says "Logout" before clicking
                # Use xpath= prefix for page.locator()
                logout_text = self.browser_wrapper.page.locator(f"xpath={logout_xpath}").inner_text()
                if "logout" in logout_text.lower():
                    self.logger.info(f"Logout button found: '{logout_text}'")
                    self.browser_wrapper.click_element(logout_xpath)
                    time.sleep(3)
                    self.logger.info("Logout successful in T-Mobile")
                    return True
                else:
                    self.logger.warning(f"Element found but not logout: '{logout_text}'")

            # Fallback: try by text
            if self.browser_wrapper.is_element_visible(logout_by_text_xpath, timeout=3000):
                self.logger.info("Logout button found (by text)")
                self.browser_wrapper.click_element(logout_by_text_xpath)
                time.sleep(3)
                self.logger.info("Logout successful in T-Mobile")
                return True

            self.logger.warning("Logout element not found")
            return False

        except Exception as e:
            self.logger.error(f"Error during logout in T-Mobile: {str(e)}")
            return False

    def is_logged_in(self) -> bool:
        try:
            logged_in_xpath = "/html/body/globalnav-root/globalnav-nav/mat-sidenav-container/mat-sidenav/div/mat-nav-list[1]/mat-panel-title/mat-list-item"
            return self.browser_wrapper.is_element_visible(logged_in_xpath, timeout=5000)
        except Exception:
            return False

    def get_login_url(self) -> str:
        return CarrierPortalUrls.TMOBILE.value

    def get_logout_xpath(self) -> str:
        return "/html/body/globalnav-root/globalnav-nav/mat-sidenav-container/mat-sidenav/div/mat-nav-list[1]/mat-panel-title/mat-list-item"

    def get_username_xpath(self) -> str:
        return '//*[@id="emailOrPhoneNumberTextBox"]'

    def get_password_xpath(self) -> str:
        return '//*[@id="passwordTextBox"]'

    def get_login_button_xpath(self) -> str:
        return '//*[@id="lp2-login-btn"]'

    def _handle_language_modal(self) -> None:
        """Handle the language selection modal if present (select English).

        The language modal is inside an iframe, so we need to switch context.
        """
        iframe_selector = "#lightbox_pop"
        english_button_css = "#en"
        email_field_xpath = '//*[@id="emailOrPhoneNumberTextBox"]'

        page = self.browser_wrapper.page

        # Step 1: actively wait for the iframe to attach to the DOM.
        try:
            self.logger.info("Waiting for language modal iframe to appear...")
            page.locator(iframe_selector).wait_for(state="attached", timeout=15000)
            self.logger.info("Language modal iframe detected, switching context...")
        except Exception:
            self.logger.info("No language modal iframe detected, continuing...")
            return

        # Step 2: wait for the English button *inside* the frame to become visible,
        # then click it. The iframe can attach before its content finishes rendering,
        # so we must wait for the inner element — not just check count().
        try:
            frame = page.frame_locator(iframe_selector)
            english_button = frame.locator(english_button_css)
            english_button.wait_for(state="visible", timeout=20000)
            self.logger.info("English button found inside iframe, clicking...")
            english_button.click()
            self.logger.info("Language set to English")
        except Exception as e:
            self.logger.warning(f"English button not clickable inside iframe: {e}")
            return

        # Step 3: confirm email field becomes visible (modal dismissed).
        try:
            if not self.browser_wrapper.is_element_visible(email_field_xpath, timeout=10000):
                self.logger.warning("Email field not visible after language modal handling")
        except Exception as e:
            self.logger.warning(f"Error verifying email field after language modal: {e}")

    def _handle_2fa_if_present(self, credentials: Credentials) -> bool:
        """Detect and handle MFA if present. Similar to Bell implementation."""
        try:
            mfa_code_input_xpath = '//*[@id="code"]'

            if self.browser_wrapper.is_element_visible(mfa_code_input_xpath, timeout=10000):
                self.logger.info("2FA field detected. Starting verification process...")
                return self._process_2fa(mfa_code_input_xpath, credentials)
            else:
                self.logger.info("No 2FA field detected")
                time.sleep(5)
                return True

        except MFACodeError:
            raise
        except Exception as e:
            self.logger.error(f"Error verifying 2FA: {str(e)}")
            return True

    def _process_2fa(self, code_input_xpath: str, credentials: Credentials) -> bool:
        """Process 2FA by waiting for code from webhook and entering it."""
        continue_button_xpath = '//*[@id="main"]/div[1]/form/div/div/div[2]/div/div[2]/button'

        self.logger.info("Waiting for MFA code from SSE endpoint...")
        endpoint_url = f"{self.webhook_url}/api/v1/tmobile"
        sms_code = self._consume_mfa_sse_stream(endpoint_url, credentials.username)

        self.logger.info(f"Entering code: {sms_code}")
        self.browser_wrapper.click_element(code_input_xpath)
        self.browser_wrapper.clear_and_type(code_input_xpath, sms_code)
        time.sleep(1)

        self.logger.info("Clicking Continue...")
        self.browser_wrapper.click_element(continue_button_xpath)

        self.browser_wrapper.wait_for_page_load()
        time.sleep(5)

        # Check if MFA field is still visible (indicates failure)
        if self.browser_wrapper.is_element_visible(code_input_xpath, timeout=3000):
            self.logger.error("2FA validation failed - field still visible")
            return False

        self.logger.info("2FA validation successful")
        return True


class VerizonAuthStrategy(AuthBaseStrategy):

    def __init__(self, browser_wrapper: BrowserWrapper, webhook_url: str = None):
        super().__init__(browser_wrapper)
        self.webhook_url = webhook_url or DEFAULT_MFA_SERVICE_URL
        self.logger = logging.getLogger(self.__class__.__name__)

    def login(self, credentials: Credentials) -> bool:
        try:
            self.logger.info("Starting login in Verizon...")

            self.browser_wrapper.goto(self.get_login_url())
            self.browser_wrapper.wait_for_page_load(60000)
            time.sleep(3)

            # First login attempt
            if not self._fill_login_form_and_submit(credentials):
                return False

            time.sleep(10)

            # Check for CAPTCHA after first login click
            captcha_img_xpath = '//*[@id="captchaImg"]'
            if self.browser_wrapper.is_element_visible(captcha_img_xpath, timeout=3000):
                self.logger.info("CAPTCHA detected after login attempt...")

                # First CAPTCHA attempt
                if not self._solve_captcha_and_submit():
                    return False

                time.sleep(10)

                # Check if CAPTCHA still exists (failed first attempt)
                if self.browser_wrapper.is_element_visible(captcha_img_xpath, timeout=3000):
                    self.logger.warning("CAPTCHA still present after first attempt")

                    # Second attempt: refill entire form
                    if not self._fill_login_form_and_submit(credentials):
                        return False

                    time.sleep(10)

                    # Check if CAPTCHA is still visible BEFORE trying to solve it
                    # If login succeeded without CAPTCHA, the page will have navigated to dashboard
                    if not self.browser_wrapper.is_element_visible(captcha_img_xpath, timeout=3000):
                        self.logger.info("CAPTCHA no longer visible after second login - login may have succeeded")
                        # Continue to normal login success checking below
                    else:
                        self.logger.info("CAPTCHA still visible - attempting to solve...")
                        if not self._solve_captcha_and_submit():
                            self.logger.error("CAPTCHA failed on second attempt")
                            return False

                        time.sleep(10)

                        # If CAPTCHA still exists after second attempt, fail
                        if self.browser_wrapper.is_element_visible(captcha_img_xpath, timeout=3000):
                            self.logger.error("CAPTCHA failed after two attempts")
                            return False

            # Wait a bit for page to settle
            time.sleep(5)

            # First check if already logged in (no MFA required)
            if self.is_logged_in():
                self.logger.info("Login successful in Verizon (no MFA required)")
                self._dismiss_promo_modal_if_present()
                return True

            # Check for MFA
            if not self._handle_2fa_if_present(credentials):
                self.logger.error("2FA failed - interrupting login")
                return False

            if self.is_logged_in():
                self.logger.info("Login successful in Verizon")
                self._dismiss_promo_modal_if_present()
                return True
            else:
                self.logger.error("Login failed in Verizon")
                return False

        except MFACodeError as e:
            self.logger.error(f"MFA error during login in Verizon: {str(e)}")
            return False
        except Exception as e:
            self.logger.error(f"Error during login in Verizon: {str(e)}")
            return False

    def _fill_login_form_and_submit(self, credentials: Credentials) -> bool:
        """Fill the login form with username and password, then click login."""
        try:
            username_xpath = '//*[@id="ilogin_userid"]'
            password_xpath = '//*[@id="ilogin_password"]'
            login_button_xpath = '//*[@id="ilogin_login_button"]'

            # Bumped from default 10s to 30s: Verizon's login page is slow to render the
            # username field on cold starts and behind transient Cloudflare challenges,
            # which produced spurious "Error filling login form" failures even though the
            # page eventually loaded. 30s gives the field room to appear without hanging
            # the queue too long.
            self.logger.info(f"Entering email: {credentials.username}")
            self.browser_wrapper.clear_and_type(username_xpath, credentials.username, timeout=30000)
            time.sleep(1)

            self.logger.info("Entering password...")
            self.browser_wrapper.clear_and_type(password_xpath, credentials.password)
            time.sleep(1)

            self.logger.info("Clicking Login...")
            self.browser_wrapper.click_element(login_button_xpath)
            time.sleep(3)
            return True
        except Exception as e:
            self.logger.error(f"Error filling login form: {str(e)}")
            return False

    def _solve_captcha_and_submit(self) -> bool:
        """Solve the CAPTCHA and click login."""
        try:
            captcha_input_xpath = '//*[@id="captchaInput"]'
            login_button_xpath = '//*[@id="ilogin_login_button"]'

            screenshot_path = self._take_captcha_screenshot()
            if not screenshot_path:
                self.logger.error("Failed to take CAPTCHA screenshot")
                return False

            captcha_solution = self.send_image_to_ia(screenshot_path)
            self.logger.info(f"CAPTCHA solution (raw): {captcha_solution}")

            if not captcha_solution:
                self.logger.error("Failed to get CAPTCHA solution from AI")
                return False

            # Remove any spaces from the CAPTCHA solution
            captcha_solution = captcha_solution.replace(" ", "")
            self.logger.info(f"CAPTCHA solution (cleaned): {captcha_solution}")

            self.logger.info("Entering CAPTCHA solution...")
            self.browser_wrapper.clear_and_type(captcha_input_xpath, captcha_solution)
            time.sleep(1)

            self.logger.info("Clicking Login after CAPTCHA...")
            self.browser_wrapper.click_element(login_button_xpath)
            return True
        except Exception as e:
            self.logger.error(f"Error solving CAPTCHA: {str(e)}")
            return False

    def _take_captcha_screenshot(self) -> Optional[str]:
        """Take a screenshot of the CAPTCHA element and save it to captcha_screenshots folder."""
        import os
        from datetime import datetime

        try:
            # Create captcha_screenshots folder if it doesn't exist
            screenshots_dir = os.path.join(os.getcwd(), "captcha_screenshots")
            os.makedirs(screenshots_dir, exist_ok=True)

            # Generate unique filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"captcha_{timestamp}.png"
            filepath = os.path.join(screenshots_dir, filename)

            # Take screenshot of the CAPTCHA element
            captcha_element = self.browser_wrapper.page.locator("#captchaImg")
            captcha_element.screenshot(path=filepath)

            self.logger.info(f"CAPTCHA screenshot saved to: {filepath}")
            return filepath

        except Exception as e:
            self.logger.error(f"Error taking CAPTCHA screenshot: {str(e)}")
            return None

    def send_image_to_ia(self, image_path: str) -> Optional[str]:
        """Send CAPTCHA image to AI service for solving."""
        try:
            self.logger.info(f"Sending image to AI for CAPTCHA solving: {image_path}")
            result = extract_text_from_image(Path(image_path))
            self.logger.info(f"AI returned CAPTCHA text: {result}")
            return result
        except Exception as e:
            self.logger.error(f"Error solving CAPTCHA with AI: {str(e)}")
            return None
        finally:
            try:
                Path(image_path).unlink()
                self.logger.info(f"Deleted CAPTCHA image: {image_path}")
            except Exception as e:
                self.logger.warning(f"Could not delete CAPTCHA image: {str(e)}")

    def _dismiss_promo_modal_if_present(self) -> None:
        # Random post-login promo overlay rendered into #on-landing; absence is fine.
        no_thanks_xpath = '//*[@id="on-landing"]//button[@aria-label="No thanks"]'
        try:
            if self.browser_wrapper.is_element_visible(no_thanks_xpath, timeout=5000):
                self.logger.info("Promotional modal detected, clicking 'No thanks'...")
                self.browser_wrapper.click_element(no_thanks_xpath)
                time.sleep(2)
            else:
                self.logger.debug("No promotional modal detected after login")
        except Exception as e:
            self.logger.warning(f"Could not dismiss promotional modal (continuing): {e}")

    def logout(self) -> bool:
        try:
            self.logger.info("Starting logout in Verizon...")

            # Click on user menu
            user_menu_xpath = '//*[@id="gNavHeader"]/div/div/div[1]/div[2]/header/div/div/div[3]/nav/ul/li/div[1]'
            self.logger.info("Clicking user menu...")

            if self.browser_wrapper.is_element_visible(user_menu_xpath, timeout=5000):
                self.browser_wrapper.click_element(user_menu_xpath)
                time.sleep(2)
            else:
                self.logger.error("User menu not found")
                return False

            # Click on logout
            logout_xpath = '//*[@id="gn-logout-li-item"]/a'
            self.logger.info("Clicking Logout...")

            if self.browser_wrapper.is_element_visible(logout_xpath, timeout=5000):
                self.browser_wrapper.click_element(logout_xpath)
                self.browser_wrapper.wait_for_page_load()
                time.sleep(3)
            else:
                self.logger.error("Logout button not found")
                return False

            self.logger.info("Logout successful in Verizon")
            return not self.is_logged_in()

        except Exception as e:
            self.logger.error(f"Error during logout in Verizon: {str(e)}")
            return False

    def is_logged_in(self) -> bool:
        """Check if logged in by looking for the Welcome label.

        Note: Verizon site may show a login form briefly before redirecting to
        dashboard if already logged in. We wait for the page to settle first.
        Accounts with pending onboarding land on the "Welcome Hub" page instead
        of the My Business home; that page is detected and clicked through here.
        """
        try:
            # First, wait for page to settle - Verizon may redirect after initial load
            self.logger.info("Checking Verizon login status (waiting for page to settle)...")
            time.sleep(5)

            # Check if we're on the login page (not logged in)
            login_form_xpath = '//*[@id="ilogin_userid"]'
            if self.browser_wrapper.is_element_visible(login_form_xpath, timeout=3000):
                # Login form is visible - wait longer as it may redirect if session exists
                self.logger.info("Login form detected - waiting 15 seconds for potential redirect...")
                time.sleep(15)

            # Welcome Hub onboarding page means we are logged in; click through to the
            # real home so downstream navigation (#gNavHeader) is available
            if self._handle_welcome_hub_if_present():
                return True

            # Now check for welcome label (flexible: match any h1/h2 whose full text contains "Welcome")
            welcome_xpath = '//*[self::h1 or self::h2][contains(., "Welcome")]'
            if self.browser_wrapper.is_element_visible(welcome_xpath, timeout=10000):
                label_text = self.browser_wrapper.page.locator(welcome_xpath).first.text_content()
                if label_text:
                    self.logger.info(f"Welcome label found: {label_text.strip()}")
                    return True

            # Fallback: the secure app lives on mb.verizonwireless.com/mbt/secure,
            # while the login page lives on mblogin.verizonwireless.com
            current_url = self.browser_wrapper.get_current_url()
            if "mb.verizonwireless.com/mbt/secure" in current_url:
                self.logger.info(f"Logged in based on secure URL: {current_url}")
                return True

            self.logger.info("Welcome label not found - not logged in")
            self._log_page_diagnostics(current_url)
            return False
        except Exception as e:
            self.logger.warning(f"Error checking login status: {str(e)}")
            return False

    def _handle_welcome_hub_if_present(self) -> bool:
        """Detect the post-login Welcome Hub onboarding page and click through to the home page.

        Returns True if the Welcome Hub was detected (i.e. we are logged in), False otherwise.
        """
        # Match the button by its text so the selector survives layout changes
        button_by_text_xpath = (
            '//button[contains(translate(normalize-space(.), '
            '"ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"), '
            '"visit the my business home page")]'
        )
        # Reference xpath observed on the Welcome Hub page, kept as fallback
        button_reference_xpath = '//*[@id="root"]/div/div[2]/div/div[1]/div[2]/div/button'

        try:
            for xpath in (button_by_text_xpath, button_reference_xpath):
                if self.browser_wrapper.is_element_visible(xpath, timeout=5000):
                    self.logger.info(
                        "Welcome Hub onboarding page detected, clicking 'Visit the My Business home page'..."
                    )
                    self.browser_wrapper.click_element(xpath)
                    self.browser_wrapper.wait_for_page_load()
                    time.sleep(5)
                    return True
            return False
        except Exception as e:
            self.logger.warning(f"Error handling Welcome Hub page: {str(e)}")
            return False

    def _log_page_diagnostics(self, current_url: str) -> None:
        """Log the current URL and visible h1/h2 texts to diagnose unrecognized pages."""
        try:
            headings = self.browser_wrapper.page.evaluate(
                """
                () => Array.from(document.querySelectorAll('h1, h2'))
                    .map(h => h.textContent.trim())
                    .filter(Boolean)
                    .slice(0, 10)
            """
            )
            self.logger.info(f"Page diagnostics - URL: {current_url}, h1/h2 headings: {headings}")
        except Exception as e:
            self.logger.warning(f"Could not collect page diagnostics: {str(e)}")

    def get_login_url(self) -> str:
        return CarrierPortalUrls.VERIZON.value

    def get_logout_xpath(self) -> str:
        return "/html/body/app-root/app-secure-layout/app-header/div/div[1]/div/div/div[1]/div[2]/header/div/div/div[3]/nav/ul/li/div[2]/ul/li[6]/a"

    def get_username_xpath(self) -> str:
        return '//*[@id="ilogin_userid"]'

    def get_password_xpath(self) -> str:
        return '//*[@id="ilogin_password"]'

    def get_login_button_xpath(self) -> str:
        return '//*[@id="ilogin_login_button"]'

    def _handle_2fa_if_present(self, credentials: Credentials) -> bool:
        """Detects and handles Verizon MFA by selecting the best Email option."""
        try:
            # Check if MFA options list is visible (short timeout since we already checked is_logged_in)
            mfa_list_xpath = '//*[@id="app"]/div/div/div/div[2]/div/div/div/div/div/div[2]/li'

            if self.browser_wrapper.is_element_visible(mfa_list_xpath, timeout=10000):
                self.logger.info("MFA options detected. Starting verification process...")
                return self._process_2fa(credentials)
            else:
                self.logger.info("No MFA options detected, checking if logged in...")
                return self.is_logged_in()

        except MFACodeError:
            raise
        except Exception as e:
            self.logger.error(f"Error verifying 2FA: {str(e)}")
            return self.is_logged_in()

    def _process_2fa(self, credentials: Credentials) -> bool:
        """Process 2FA by selecting the best Email option and confirming via link."""
        # Find and click the best Email option
        self.logger.info("Finding best Email option for MFA...")
        email_option = self._find_best_email_option(credentials.username)

        if email_option is None:
            self.logger.info("Manual MFA resolution completed")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(5)
            return True

        # Click the selected email option using its section ID
        section_id = email_option.get("sectionId")
        if section_id:
            self.logger.info(f"Selecting Email option with ID: {section_id}...")
            self.browser_wrapper.click_element(f'//*[@id="{section_id}"]')
        else:
            # Fallback: use index-based selector
            index = email_option.get("index", 1)
            self.logger.info(f"Selecting Email option at index {index}...")
            option_xpath = f'(//*[contains(@class, "pwdless_options_section")])[{index}]'
            self.browser_wrapper.click_element(option_xpath)
        time.sleep(2)

        self.logger.info("Waiting for MFA link from SSE endpoint...")
        endpoint_url = f"{self.webhook_url}/api/v1/verizon"
        mfa_link = self._consume_mfa_sse_stream(endpoint_url, credentials.username, event_type="link")

        self.logger.info(f"MFA link received: {mfa_link}")

        # Open link in new tab and confirm Allow
        if not self._confirm_mfa_in_new_tab(mfa_link):
            self.logger.error("Failed to confirm MFA in new tab")
            return False

        # Wait for main page to update after MFA confirmation
        self.logger.info("Waiting for main page to update after MFA confirmation...")
        time.sleep(10)
        self.browser_wrapper.wait_for_page_load()

        self.logger.info("2FA validation completed")
        return True

    def _confirm_mfa_in_new_tab(self, mfa_link: str) -> bool:
        """Open MFA link in new tab, click Allow and confirm, then return to original tab."""
        allow_label_xpath = '//*[@id="dvbtn"]/form/div[1]/label'
        confirm_button_xpath = '//*[@id="dvbtn"]/button'

        try:
            # Save reference to original page
            original_page = self.browser_wrapper.page

            # Open new tab with the MFA link
            self.logger.info("Opening MFA link in new tab...")
            new_page = self.browser_wrapper.page.context.new_page()
            Stealth().apply_stealth_sync(new_page)  # Aplicar stealth a la nueva pagina
            self.browser_wrapper.page = new_page
            new_page.goto(mfa_link)
            new_page.wait_for_load_state("networkidle")
            time.sleep(3)

            # Click on Allow label
            self.logger.info("Looking for Allow option...")
            if self.browser_wrapper.is_element_visible(allow_label_xpath, timeout=10000):
                label_text = new_page.locator(allow_label_xpath).text_content()
                self.logger.info(f"Found label: {label_text}")
                if label_text and "allow" in label_text.lower():
                    self.logger.info("Clicking Allow option...")
                    self.browser_wrapper.click_element(allow_label_xpath)
                    time.sleep(2)
                else:
                    self.logger.warning(f"Label does not contain 'Allow': {label_text}")
            else:
                self.logger.error("Allow label not visible")
                self.browser_wrapper.close_current_tab()
                self.browser_wrapper.page = original_page
                return False

            # Click confirm button
            self.logger.info("Clicking confirm button...")
            if self.browser_wrapper.is_element_visible(confirm_button_xpath, timeout=5000):
                self.browser_wrapper.click_element(confirm_button_xpath)
                time.sleep(3)
            else:
                self.logger.error("Confirm button not visible")
                self.browser_wrapper.close_current_tab()
                self.browser_wrapper.page = original_page
                return False

            # Close the MFA tab and return to original
            self.logger.info("MFA confirmed, closing tab and returning to original...")
            self.browser_wrapper.close_current_tab()
            self.browser_wrapper.page = original_page
            original_page.bring_to_front()
            return True

        except Exception as e:
            self.logger.error(f"Error confirming MFA in new tab: {str(e)}")
            # Try to recover by returning to original page
            try:
                self.browser_wrapper.page = original_page
                original_page.bring_to_front()
            except:
                pass
            return False

    def _find_best_email_option(self, login_email: str) -> Optional[dict]:
        """
        Find the best Email option from the MFA options list.

        Logic:
        1. Get all MFA options from the list
        2. Filter only options with method="Email"
        3. If only one Email option, use it
        4. If two Email options, use the one that is NOT "s***n@e***.com"
        """
        try:
            # Get all MFA options using JavaScript
            mfa_options = self.browser_wrapper.page.evaluate(
                """
                () => {
                    const options = [];
                    const optionSections = document.querySelectorAll('#app li .pwdless_options_section');

                    optionSections.forEach((section, index) => {
                        const deliveryOption = section.querySelector('.delivery_option_with_msg a');
                        const contactEl = section.querySelector('.pwdless_delivery_link');

                        if (deliveryOption && contactEl) {
                            const fullText = deliveryOption.textContent;
                            const method = fullText.split('\\n')[0].trim();

                            options.push({
                                index: index + 1,
                                method: method,
                                contact: contactEl.textContent.trim(),
                                sectionId: section.id || null
                            });
                        }
                    });

                    return options;
                }
            """
            )

            self.logger.info(f"Found {len(mfa_options)} MFA options")

            # Print all options found
            print(f"\n{'='*60}")
            print("ALL MFA OPTIONS FOUND:")
            for opt in mfa_options:
                print(f"  [{opt['index']}] Method: {opt['method']}, Contact: {opt['contact']}, ID: {opt['sectionId']}")
            print(f"{'='*60}\n")

            # Filter only Email options (method starts with "Email")
            email_options = [opt for opt in mfa_options if opt["method"].lower().startswith("email")]

            if not email_options:
                self.logger.warning("No Email options found in MFA list")
                print("Waiting 120 seconds for manual MFA resolution...")
                time.sleep(120)
                return None

            self.logger.info(f"Found {len(email_options)} Email option(s)")

            # If only one Email option, return it
            if len(email_options) == 1:
                self.logger.info(f"Single Email option: {email_options[0]['contact']}")
                return email_options[0]

            # If two Email options, use the one that is NOT "s***n@e***"
            excluded_pattern = "s***n@e***"
            for opt in email_options:
                if opt["contact"].lower() != excluded_pattern.lower():
                    self.logger.info(f"Selected Email option: {opt['contact']} (excluded: {excluded_pattern})")
                    return opt

            # Fallback to first Email option if all match the excluded pattern
            self.logger.warning(f"All options match excluded pattern, using first: {email_options[0]['contact']}")
            return email_options[0]

        except Exception as e:
            self.logger.error(f"Error finding Email option: {str(e)}")
            return None
