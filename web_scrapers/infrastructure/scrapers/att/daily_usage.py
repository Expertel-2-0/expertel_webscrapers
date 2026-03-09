import logging
import os
import time
import traceback
from typing import Any, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    DailyUsageScraperStrategy,
    FileDownloadInfo,
)

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class ATTDailyUsageScraperStrategy(DailyUsageScraperStrategy):
    """Scraper de uso diario para AT&T."""

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Busca la seccion de archivos de uso diario en el portal de AT&T."""
        return self._find_files_section_with_retry(config, billing_cycle, max_retries=1)

    def _find_files_section_with_retry(
        self, config: ScraperConfig, billing_cycle: BillingCycle, max_retries: int = 1
    ) -> Optional[Any]:
        """Busca la seccion de archivos de uso diario con reintento automatico."""
        for attempt in range(max_retries + 1):
            try:
                self.logger.info(f"Searching for AT&T daily usage section (attempt {attempt + 1}/{max_retries + 1})")

                # 1. Click en Reports tab
                reports_tab_xpath = '//*[@id="reportsTab"]/a'
                self.logger.info("Clicking Reports tab...")
                self.browser_wrapper.click_element(reports_tab_xpath)
                time.sleep(30)

                # 2. Click en Report section container
                reports_section_xpath = '//*[@id="functionality"]/div/div[2]/div[1]'
                self.logger.info("Clicking Report section container...")
                self.browser_wrapper.click_element(reports_section_xpath)
                time.sleep(60)

                # 3. Click en Internal Reports dropdown
                internal_reports_xpath = '//*[@id="navMenuGroupReports"]'
                self.logger.info("Clicking Internal Reports dropdown...")
                self.browser_wrapper.click_element(internal_reports_xpath)
                time.sleep(3)

                # 4. Click en Summary option
                summary_option_xpath = '//*[@id="navMenuItem5"]'
                self.logger.info("Clicking Summary option...")
                self.browser_wrapper.click_element(summary_option_xpath)
                time.sleep(5)

                # 5. Verificar que encontramos la seccion correcta (tabs visibles)
                tabs_list_xpath = '//*[@id="main-content"]/div[1]/div[2]/div[1]/ul'
                if self.browser_wrapper.is_element_visible(tabs_list_xpath, timeout=10000):
                    tabs_text = self.browser_wrapper.get_text(tabs_list_xpath)
                    if tabs_text and "Unbilled usage" in tabs_text:
                        self.logger.info("Summary section found successfully - Unbilled usage tab available")
                        return {"section": "daily_usage", "ready_for_download": True}
                    else:
                        self.logger.warning(f"Tabs text does not contain 'Unbilled usage': {tabs_text}")
                        # Fallback: intentar click directo en el tab de Unbilled usage
                        unbilled_tab_fallback_xpath = '//*[@id="navTabItem5-2"]'
                        if self.browser_wrapper.is_element_visible(unbilled_tab_fallback_xpath, timeout=5000):
                            self.logger.info("Fallback: Unbilled usage tab found by direct ID, proceeding")
                            return {"section": "daily_usage", "ready_for_download": True}
                        self.logger.warning("Fallback failed: Unbilled usage tab not found by direct ID either")
                        continue
                else:
                    self.logger.warning("Tabs list not found")
                    # Fallback: intentar click directo en el tab de Unbilled usage
                    unbilled_tab_fallback_xpath = '//*[@id="navTabItem5-2"]'
                    if self.browser_wrapper.is_element_visible(unbilled_tab_fallback_xpath, timeout=5000):
                        self.logger.info("Fallback: Unbilled usage tab found by direct ID, proceeding")
                        return {"section": "daily_usage", "ready_for_download": True}
                    self.logger.warning("Fallback failed: Unbilled usage tab not found by direct ID either")
                    continue

            except Exception as e:
                self.logger.error(f"Error on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries:
                    continue

        self.logger.error("Could not find daily usage section after all attempts")
        return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Descarga los archivos de uso diario de AT&T."""
        downloaded_files = []

        # Nombres de reporte a buscar (en orden de prioridad)
        report_names = [
            "Unbilled usage details totals (GB usage)",
            "Unbilled usage details totals",
        ]

        # Mapear BillingCycleDailyUsageFile
        daily_usage_file = None
        if billing_cycle.daily_usage_files:
            daily_usage_file = billing_cycle.daily_usage_files[0]
            self.logger.info(f"Daily usage file found: ID {daily_usage_file.id}")

        try:
            self.logger.info("Downloading daily usage file...")

            # 1. Click en "Unbilled usage" tab
            unbilled_tab_xpath = '//*[@id="navTabItem5-2"]'
            self.logger.info("Clicking Unbilled usage tab...")
            if not self.browser_wrapper.is_element_visible(unbilled_tab_xpath, timeout=10000):
                self.logger.error("Unbilled usage tab not found")
                return downloaded_files
            self.browser_wrapper.click_element(unbilled_tab_xpath)
            time.sleep(5)

            # 2. Configurar filtro de cuenta
            self._configure_account_filter(billing_cycle)

            # 3. Buscar y hacer click en el reporte correcto dentro del accordion
            # El section_name es "Unbilled details" para buscar en el panel correcto
            if not self._find_and_click_report("Unbilled details", report_names):
                self.logger.error("Could not find unbilled usage report")
                self._reset_to_main_screen()
                return downloaded_files

            # 4. Esperar 60 segundos para que cargue el reporte
            self.logger.info("Waiting 60 seconds for report to load...")
            time.sleep(60)

            # 5. Click en Export button
            export_button_xpath = '//*[@id="export"]'
            if not self.browser_wrapper.is_element_visible(export_button_xpath, timeout=10000):
                self.logger.error("Export button not found")
                self._go_back_to_reports()
                self._reset_to_main_screen()
                return downloaded_files

            self.logger.info("Clicking Export button...")
            self.browser_wrapper.click_element(export_button_xpath)
            time.sleep(2)

            # 6. Seleccionar CSV en el modal
            csv_option_xpath = '//*[@id="radCsvLabel"]'
            if self.browser_wrapper.is_element_visible(csv_option_xpath, timeout=5000):
                self.logger.info("Selecting CSV option...")
                self.browser_wrapper.click_element(csv_option_xpath)
                time.sleep(1)
            else:
                self.logger.warning("CSV option not found in modal")
                self._close_export_modal_if_open()
                self._go_back_to_reports()
                self._reset_to_main_screen()
                return downloaded_files

            # 7. Click en OK y esperar descarga
            ok_button_xpath = '//*[@id="hrefOK"]'
            self.logger.info("Clicking OK to download...")

            file_path = self.browser_wrapper.expect_download_and_click(
                ok_button_xpath, timeout=120000, downloads_dir=self.job_downloads_dir
            )

            if file_path:
                actual_filename = os.path.basename(file_path)
                self.logger.info(f"File downloaded: {actual_filename}")

                # Crear FileDownloadInfo
                file_download_info = FileDownloadInfo(
                    file_id=daily_usage_file.id if daily_usage_file else 1,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=file_path,
                    daily_usage_file=daily_usage_file,
                )
                downloaded_files.append(file_download_info)

                if daily_usage_file:
                    self.logger.info(
                        f"MAPPING CONFIRMED: {actual_filename} -> BillingCycleDailyUsageFile ID {daily_usage_file.id}"
                    )
                else:
                    self.logger.warning("File downloaded without specific BillingCycleDailyUsageFile mapping")
            else:
                self.logger.error("Could not download daily usage file")

            # 8. Reset a pantalla principal
            self._reset_to_main_screen()

            self.logger.info(f"Daily usage download completed: {len(downloaded_files)} file(s)")
            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error downloading daily usage files: {str(e)}\n{traceback.format_exc()}")
            try:
                self._reset_to_main_screen()
            except:
                pass
            return downloaded_files

    def _configure_account_filter(self, billing_cycle: BillingCycle):
        """Configura el filtro de cuenta basado en el billing cycle."""
        try:
            account_number = billing_cycle.account.number
            self.logger.info(f"Configuring account filter for: {account_number}")

            # 1. Click en View by dropdown
            view_by_xpath = "//*[@id='main-content']/div[1]/div[2]/div[2]/div[1]/div[1]"
            self.logger.info("Clicking View by dropdown...")
            self.browser_wrapper.click_element(view_by_xpath)
            time.sleep(2)

            # 2. Seleccionar opción "Accounts"
            accounts_option_xpath = "//*[@id='LevelDataDropdownList_multipleaccounts']"
            self.logger.info("Selecting Accounts option...")
            self.browser_wrapper.click_element(accounts_option_xpath)
            time.sleep(2)

            # 3. Escribir número de cuenta en el input
            account_input_xpath = "//*[@id='scopeExpandedAccountMenu']/div[1]/div/div[2]/input"
            self.logger.info(f"Entering account number: {account_number}")
            self.browser_wrapper.clear_and_type(account_input_xpath, account_number)
            time.sleep(3)

            # 4. Seleccionar la primera opción del listado
            first_option_xpath = "//*[@id='scopeExpandedAccountMenu']/div[3]/ul/li[1]"
            if self.browser_wrapper.is_element_visible(first_option_xpath, timeout=5000):
                self.logger.info("Selecting first account option...")
                checkbox_xpath = f"{first_option_xpath}/input"
                if self.browser_wrapper.is_element_visible(checkbox_xpath, timeout=2000):
                    self.browser_wrapper.click_element(checkbox_xpath)
                else:
                    self.browser_wrapper.click_element(first_option_xpath)
                time.sleep(1)
            else:
                self.logger.warning("Account option not found in list")

            # 5. Click en OK button
            ok_button_xpath = "//*[@id='scopeExpandedAccountMenu']/div[4]/button"
            self.logger.info("Clicking OK button...")
            self.browser_wrapper.click_element(ok_button_xpath)
            time.sleep(3)

            self.logger.info("Account filter configured successfully")

        except Exception as e:
            self.logger.error(f"Error configuring account filter: {str(e)}\n{traceback.format_exc()}")

    def _find_and_click_report(self, section_name: str, report_names: List[str]) -> bool:
        """Busca y hace click en un reporte dentro del accordion.

        Idéntico al método del monthly scraper.
        """
        try:
            accordion_xpath = "//*[@id='accordion']"

            if not self.browser_wrapper.is_element_visible(accordion_xpath, timeout=10000):
                self.logger.error("Accordion not found")
                return False

            page = self.browser_wrapper.page

            # Buscar todos los paneles del accordion
            panels = page.query_selector_all(f"xpath={accordion_xpath}//div[contains(@class, 'panel-reports')]")

            for panel in panels:
                try:
                    panel_title_element = panel.query_selector(".panel-title span")
                    if panel_title_element:
                        panel_title = panel_title_element.inner_text().strip()

                        if section_name.lower() in panel_title.lower():
                            self.logger.info(f"Found section: {panel_title}")

                            # Buscar los reportes dentro de este panel
                            report_buttons = panel.query_selector_all("button[name='ViewReport']")

                            for button in report_buttons:
                                button_text = button.inner_text().strip()

                                for report_name in report_names:
                                    if report_name.lower() in button_text.lower():
                                        self.logger.info(f"Found report: {button_text}")
                                        button.click()
                                        time.sleep(3)
                                        return True

                except Exception as inner_e:
                    self.logger.debug(f"Error checking panel: {str(inner_e)}")
                    continue

            self.logger.warning(f"Report not found in section '{section_name}' with names: {report_names}")
            return False

        except Exception as e:
            self.logger.error(f"Error finding report: {str(e)}\n{traceback.format_exc()}")
            return False

    def _go_back_to_reports(self):
        """Regresa a la sección de reportes."""
        try:
            self._close_export_modal_if_open()

            back_button_xpath = "//*[@id='thisForm']/div[1]/div[1]/a"
            self.logger.info("Going back to reports section...")

            if self.browser_wrapper.is_element_visible(back_button_xpath, timeout=5000):
                self.browser_wrapper.click_element(back_button_xpath)
                time.sleep(5)
                self.logger.info("Back to reports section")
            else:
                self.logger.warning("Back button not found")

        except Exception as e:
            self.logger.error(f"Error going back to reports: {str(e)}")

    def _close_export_modal_if_open(self):
        """Cierra el modal de export si está abierto."""
        try:
            close_button_xpath = "//*[@id='exportModal']//button[@class='close']"
            cancel_button_xpath = "//*[@id='exportModal']//button[contains(text(), 'Cancel')]"

            if self.browser_wrapper.is_element_visible(close_button_xpath, timeout=2000):
                self.logger.info("Closing export modal via close button...")
                self.browser_wrapper.click_element(close_button_xpath)
                time.sleep(1)
            elif self.browser_wrapper.is_element_visible(cancel_button_xpath, timeout=2000):
                self.logger.info("Closing export modal via cancel button...")
                self.browser_wrapper.click_element(cancel_button_xpath)
                time.sleep(1)
            else:
                self.logger.info("Attempting to close modal with Escape key...")
                self.browser_wrapper.page.keyboard.press("Escape")
                time.sleep(1)

        except Exception as e:
            self.logger.debug(f"Error closing export modal: {str(e)}")

    def _reset_to_main_screen(self):
        """Reset a la pantalla inicial de AT&T."""
        try:
            self.logger.info("Resetting to AT&T initial screen...")
            self.browser_wrapper.goto("https://www.wireless.att.com/premiercare/")
            time.sleep(3)
            self.logger.info("Reset to AT&T completed")
        except Exception as e:
            self.logger.error(f"Error in AT&T reset: {str(e)}")
