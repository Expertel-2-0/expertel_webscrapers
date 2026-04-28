import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    DailyUsageScraperStrategy,
    FileDownloadInfo,
)

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class TMobileDailyUsageScraperStrategy(DailyUsageScraperStrategy):
    """Scraper de uso diario para T-Mobile.

    Flujo:
    1. Click en Billing en el menu lateral
    2. Buscar cuenta por numero en el input de filtro
    3. Click en el row de la cuenta (unico resultado)
    4. Click en tab "Usage"
    5. Extraer pool_used desde response de britebill (capturada en background)
    6. Seleccionar "All Usage" en el dropdown
    7. Click en Download para descargar CSV
    """

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)
        self._captured_britebill_response: Optional[Dict] = None
        self._britebill_callback = None

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navega a Billing y encuentra la cuenta."""
        try:
            self.logger.info("Navigating to Billing section for daily usage...")

            # 1. Click en Billing en el menu lateral
            if not self._navigate_to_billing():
                self.logger.error("Could not navigate to Billing")
                return None

            # 2. Buscar la cuenta
            account_number = billing_cycle.account.number if billing_cycle.account else None
            if not account_number:
                self.logger.error("Account number not found in billing_cycle")
                return None

            if not self._search_account(account_number):
                self.logger.error(f"Could not search for account {account_number}")
                return None

            # 3. Registrar listener para capturar response de britebill ANTES del click
            self._setup_britebill_listener()

            # 4. Click en el row de la cuenta (esto dispara la peticion a britebill)
            if not self._click_account_row():
                self.logger.error("Could not click on account row")
                return None

            self.logger.info("Daily Usage section found successfully")
            return {"section": "daily_usage", "account_number": account_number}

        except Exception as e:
            self.logger.error(f"Error navigating to files section: {str(e)}")
            return None

    def _navigate_to_billing(self) -> bool:
        """Navega a la seccion Billing en el menu lateral.

        Billing es un item directo en el sidenav con id='billingApp', no un submenu.
        """
        try:
            self.logger.info("Looking for Billing section in side menu...")

            # Billing es un item directo con id="billingApp"
            billing_by_id_xpath = '//*[@id="billingApp"]'
            billing_by_text_xpath = "//mat-panel-title//span[contains(text(), 'Billing')]"

            if self.browser_wrapper.is_element_visible(billing_by_id_xpath, timeout=10000):
                self.logger.info("Clicking on Billing (by ID)...")
                self.browser_wrapper.click_element(billing_by_id_xpath)
            elif self.browser_wrapper.is_element_visible(billing_by_text_xpath, timeout=5000):
                self.logger.info("Clicking on Billing (by text)...")
                self.browser_wrapper.click_element(billing_by_text_xpath)
            else:
                self.logger.error("Billing not found in side menu")
                return False

            time.sleep(5)
            self.logger.info("Navigation to Billing completed")
            return True

        except Exception as e:
            self.logger.error(f"Error navigating to Billing: {str(e)}")
            return False

    def _search_account(self, account_number: str) -> bool:
        """Busca la cuenta por numero en el input de filtro."""
        try:
            self.logger.info(f"Searching for account: {account_number}")

            # Input de busqueda de cuenta - selector mas general sin numero especifico
            # El ID puede variar (mat-input-1, mat-input-2, etc.)
            search_input_xpath = "//input[contains(@id, 'mat-input')]"
            search_input_placeholder_xpath = "//input[@placeholder='Search']"

            if self.browser_wrapper.is_element_visible(search_input_xpath, timeout=10000):
                self.logger.info("Search input found (by mat-input)")
                self.browser_wrapper.clear_and_type(search_input_xpath, account_number)
            elif self.browser_wrapper.is_element_visible(search_input_placeholder_xpath, timeout=5000):
                self.logger.info("Search input found (by placeholder)")
                self.browser_wrapper.clear_and_type(search_input_placeholder_xpath, account_number)
            else:
                self.logger.error("Account search input not found")
                return False

            time.sleep(1)

            # Presionar Enter
            self.browser_wrapper.page.keyboard.press("Enter")
            time.sleep(5)

            self.logger.info(f"Account search for {account_number} completed")
            return True

        except Exception as e:
            self.logger.error(f"Error searching for account: {str(e)}")
            return False

    def _click_account_row(self) -> bool:
        """Hace click en el row de la cuenta (unico resultado)."""
        try:
            self.logger.info("Looking for account row...")

            # Seccion de la tabla
            table_section_xpath = '//*[@id="tfb-billing-container"]/div[1]/div/app-billing/div/section'

            if not self.browser_wrapper.is_element_visible(table_section_xpath, timeout=10000):
                self.logger.error("Table section not found")
                return False

            # Click en el row de datos (billinglist-data)
            row_xpath = "//div[contains(@class, 'billinglist-data')]"

            if not self.browser_wrapper.is_element_visible(row_xpath, timeout=5000):
                self.logger.error("Account row not found")
                return False

            self.logger.info("Clicking on account row...")
            self.browser_wrapper.click_element(row_xpath)
            time.sleep(5)

            self.logger.info("Click on account row completed")
            return True

        except Exception as e:
            self.logger.error(f"Error clicking account row: {str(e)}")
            return False

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Descarga el archivo de uso diario de T-Mobile.

        Flujo:
        1. Click en tab "Usage"
        2. Extraer pool_used desde response britebill (ya capturada para este punto)
        3. Seleccionar "All Usage" en el dropdown
        4. Click en Download
        """
        downloaded_files = []

        # Obtener el DailyUsageFile
        daily_usage_file = None
        if billing_cycle.daily_usage_files:
            daily_usage_file = billing_cycle.daily_usage_files[0]
            self.logger.info(f"DailyUsageFile found: ID {daily_usage_file.id}")

        try:
            self.logger.info("=== STARTING T-MOBILE DAILY USAGE DOWNLOAD ===")

            # 1. Click en tab "Usage"
            if not self._click_usage_tab():
                self.logger.error("Could not click on Usage tab")
                return downloaded_files

            # 2. Extraer pool_used - para este punto la response de britebill ya llego
            #    (el click en Usage tab le dio tiempo al event loop de Playwright para procesarla)
            self._extract_pool_used_from_response(billing_cycle)

            # 3. Seleccionar "All Usage" en el dropdown
            if not self._select_all_usage():
                self.logger.warning("Could not select 'All Usage', continuing...")

            time.sleep(2)

            # 4. Click en Download
            file_path = self._click_download()
            if file_path:
                actual_filename = os.path.basename(file_path)
                self.logger.info(f"File downloaded: {actual_filename}")

                file_info = FileDownloadInfo(
                    file_id=daily_usage_file.id if daily_usage_file else 0,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=file_path,
                    daily_usage_file=daily_usage_file,
                )
                downloaded_files.append(file_info)

                if daily_usage_file:
                    self.logger.info(f"MAPPING CONFIRMED: {actual_filename} -> DailyUsageFile ID {daily_usage_file.id}")
            else:
                self.logger.error("Could not download the file")

            # Reset a pantalla principal
            self._reset_to_main_screen()

            # Log resumen
            self.logger.info(f"\n{'='*60}")
            self.logger.info("DAILY USAGE DOWNLOAD SUMMARY")
            self.logger.info(f"{'='*60}")
            self.logger.info(f"Total files downloaded: {len(downloaded_files)}")
            for idx, file_info in enumerate(downloaded_files, 1):
                if file_info.daily_usage_file:
                    self.logger.info(
                        f"   [{idx}] {file_info.file_name} -> DailyUsageFile ID {file_info.daily_usage_file.id}"
                    )
                else:
                    self.logger.info(f"   [{idx}] {file_info.file_name} -> NO MAPPING")
            self.logger.info(f"{'='*60}\n")

            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error during daily usage download: {str(e)}")
            try:
                self._reset_to_main_screen()
            except:
                pass
            return downloaded_files

    def _click_usage_tab(self) -> bool:
        """Hace click en el tab 'Usage'."""
        try:
            self.logger.info("Looking for Usage tab...")

            # Buscar tab por texto
            usage_tab_xpath = "//div[@role='tab']//div[contains(text(), 'Usage')]"

            if not self.browser_wrapper.is_element_visible(usage_tab_xpath, timeout=10000):
                self.logger.error("Usage tab not found")
                return False

            self.logger.info("Clicking on Usage tab...")
            self.browser_wrapper.click_element(usage_tab_xpath)
            time.sleep(3)

            self.logger.info("Usage tab selected")
            return True

        except Exception as e:
            self.logger.error(f"Error clicking Usage tab: {str(e)}")
            return False

    def _select_all_usage(self) -> bool:
        """Selecciona la opcion 'All Usage' en el dropdown."""
        try:
            self.logger.info("Selecting 'All Usage' from dropdown...")

            # Apuntar al mat-select directamente, no al form-field overlay
            mat_select_xpath = '//*[@id="usage-dropdown"]//mat-select'

            if not self.browser_wrapper.is_element_visible(mat_select_xpath, timeout=5000):
                self.logger.error("Usage mat-select dropdown not found")
                return False

            # Click para abrir el dropdown
            self.browser_wrapper.click_element(mat_select_xpath)
            time.sleep(2)

            # Buscar la opcion "All usage" en el panel
            all_usage_option_xpath = "//mat-option//span[contains(text(), 'All usage')]"

            if not self.browser_wrapper.is_element_visible(all_usage_option_xpath, timeout=5000):
                self.logger.error("'All usage' option not found")
                return False

            self.browser_wrapper.click_element(all_usage_option_xpath)
            time.sleep(2)

            self.logger.info("'All Usage' selected successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error selecting 'All Usage': {str(e)}")
            return False

    def _click_download(self) -> Optional[str]:
        """Hace click en el boton de Download y retorna el path del archivo descargado."""
        try:
            self.logger.info("Looking for Download button...")

            # Boton de download
            download_xpath = (
                '//*[@id="mat-tab-content-0-3"]/div/tfb-usage/div/div[2]/div[1]'
                "/tfb-usage-table/div/tfb-card/mat-card/div[2]/div[1]/div[2]/div/span"
            )

            # Alternativa por texto
            download_text_xpath = "//span[contains(text(), 'Download') or contains(text(), 'download')]"

            if self.browser_wrapper.is_element_visible(download_xpath, timeout=10000):
                self.logger.info("Clicking on Download...")
                file_path = self.browser_wrapper.expect_download_and_click(
                    download_xpath, timeout=60000, downloads_dir=self.job_downloads_dir
                )
                return file_path
            elif self.browser_wrapper.is_element_visible(download_text_xpath, timeout=5000):
                self.logger.info("Clicking on Download (by text)...")
                file_path = self.browser_wrapper.expect_download_and_click(
                    download_text_xpath, timeout=60000, downloads_dir=self.job_downloads_dir
                )
                return file_path
            else:
                self.logger.error("Download button not found")
                return None

        except Exception as e:
            self.logger.error(f"Error clicking Download: {str(e)}")
            return None

    # ==================== BRITEBILL RESPONSE INTERCEPTION ====================

    def _setup_britebill_listener(self):
        """Registra un listener para capturar la response de britebill/documents/query.

        El callback de Playwright se ejecuta dentro del event loop de Playwright,
        NO durante time.sleep(). Se procesa cuando se hace la siguiente llamada
        a Playwright (click, is_element_visible, etc).
        """
        try:
            self._captured_britebill_response = None
            page = self.browser_wrapper.page

            def _on_response(response):
                if "britebill/documents/query" in response.url and response.status == 200:
                    try:
                        body = response.json()
                        self._captured_britebill_response = body
                        self.logger.info("Britebill documents/query response captured")
                    except Exception as e:
                        self.logger.warning(f"Error parsing britebill response: {str(e)}")

            self._britebill_callback = _on_response
            page.on("response", _on_response)
            self.logger.info("Britebill documents/query listener registered")

        except Exception as e:
            self.logger.warning(f"Error registering britebill listener: {str(e)}")

    def _remove_britebill_listener(self):
        """Remueve el listener de britebill para no capturar requests posteriores."""
        try:
            if self._britebill_callback:
                self.browser_wrapper.page.remove_listener("response", self._britebill_callback)
                self._britebill_callback = None
                self.logger.info("Britebill listener removed")
        except Exception as e:
            self.logger.warning(f"Error removing britebill listener: {str(e)}")

    def _extract_pool_used_from_response(self, billing_cycle: BillingCycle):
        """Extrae pool_used desde recentUsageHistory de la response capturada.

        IMPORTANTE: Llamar despues de al menos una interaccion con Playwright
        (click, is_element_visible, etc.) para que el event loop haya procesado
        el callback del listener.
        """
        try:
            # Remover listener inmediatamente - ya no necesitamos capturar mas responses
            self._remove_britebill_listener()

            response_data = self._captured_britebill_response

            if not response_data:
                print("[T-MOBILE POOL] WARNING: No britebill response captured, pool_used will remain 0")
                self.logger.warning("No britebill response captured, pool_used will remain 0")
                return

            print("[T-MOBILE POOL] Response captured, extracting recentUsageHistory...")

            # Extraer recentUsageHistory
            presentation_hints = response_data.get("presentationHints")
            if not presentation_hints:
                print(f"[T-MOBILE POOL] WARNING: presentationHints not found. Keys: {list(response_data.keys())}")
                return

            recent_usage = presentation_hints.get("recentUsageHistory", [])
            if not recent_usage:
                print(f"[T-MOBILE POOL] WARNING: recentUsageHistory empty. Keys: {list(presentation_hints.keys())}")
                return

            print(f"[T-MOBILE POOL] recentUsageHistory has {len(recent_usage)} entries")
            for entry in recent_usage:
                print(f"  -> {entry}")

            # Obtener año y mes del end_date del billing cycle
            end_date = billing_cycle.end_date
            if isinstance(end_date, str):
                end_date = datetime.strptime(end_date, "%Y-%m-%d").date()

            target_year = end_date.year
            target_month = end_date.month
            print(f"[T-MOBILE POOL] Looking for match: year={target_year}, month={target_month} (end_date={billing_cycle.end_date})")

            # Buscar entry que coincida en año y mes
            matched_entry = None
            for entry in recent_usage:
                entry_date_str = entry.get("date", "")
                if not entry_date_str:
                    continue
                try:
                    entry_date = datetime.strptime(entry_date_str, "%Y-%m-%d").date()
                    if entry_date.year == target_year and entry_date.month == target_month:
                        matched_entry = entry
                        break
                except ValueError:
                    continue

            if not matched_entry:
                print(f"[T-MOBILE POOL] WARNING: No match for {target_year}-{target_month:02d}")
                return

            # Extraer data (en GB) y convertir a bytes (base 1024)
            data_gb_str = matched_entry.get("data", "0")
            data_gb = float(data_gb_str)
            pool_used_bytes = int(data_gb * 1024 * 1024 * 1024)

            self.pool_used = pool_used_bytes

            print(f"\n{'='*60}")
            print(f"T-MOBILE POOL DATA (from britebill response)")
            print(f"  recentUsageHistory match: {matched_entry}")
            print(f"  data: {data_gb} GB")
            print(f"  pool_used: {pool_used_bytes} bytes")
            print(f"  pool_size: 0 bytes")
            print(f"{'='*60}\n")

        except Exception as e:
            print(f"[T-MOBILE POOL] ERROR: {str(e)}")
            self.logger.error(f"Error extracting pool_used from britebill response: {str(e)}")

    # ==================== RESET ====================

    def _reset_to_main_screen(self):
        """Reset a la pantalla inicial de T-Mobile dashboard."""
        try:
            self.logger.info("Resetting to T-Mobile dashboard...")
            self.browser_wrapper.goto("https://tfb.t-mobile.com/apps/tfb_billing/dashboard")
            time.sleep(5)
            self.logger.info("Reset completed")
        except Exception as e:
            self.logger.error(f"Error during reset: {str(e)}")