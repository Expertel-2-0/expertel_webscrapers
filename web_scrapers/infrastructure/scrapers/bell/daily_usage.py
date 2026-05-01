import logging
import os
import re
import time
from datetime import datetime
from typing import Any, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    DailyUsageScraperStrategy,
    FileDownloadInfo,
)

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class BellDailyUsageScraperStrategy(DailyUsageScraperStrategy):
    """Daily usage scraper for Bell."""

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Busca la seccion de archivos de uso diario en el portal de Bell."""
        try:
            # Detectar si aparece la pantalla de seleccion de cuenta
            account_selection_visible = self.browser_wrapper.find_element_by_xpath(
                "//section[@id='dataContainer']", timeout=20000
            )

            if account_selection_visible:
                self.logger.info("Account selection screen detected")
                self._handle_account_selection(billing_cycle)
            else:
                self.logger.info("Flow A: Account already preselected, continuing direct")

            self._navigate_to_usage_details()

            return {"section": "daily_usage", "ready_for_download": True}

        except Exception as e:
            self.logger.error(f"Error in _find_files_section: {str(e)}")
            return None

    def _handle_account_selection(self, billing_cycle: BillingCycle):
        """Selecciona la cuenta. Flujo B (clic directo) o C (buscar y luego clic)."""
        account_number = billing_cycle.account.number
        select_row_xpath = (
            f"//tr[.//td[@data-table-col='banId' and normalize-space(text())='{account_number}']]"
            f"//button[contains(@aria-label, 'Select')]"
        )

        # Flujo B: la fila del BAN ya esta visible -> clic directo
        if self.browser_wrapper.find_element_by_xpath(select_row_xpath, timeout=5000):
            self.logger.info(f"Flow B: BAN {account_number} visible, clicking Select directly")
            self.browser_wrapper.click_element(select_row_xpath)
            time.sleep(5)
            self.logger.info("Account selected successfully")
            return

        # Flujo C: hay que buscar el BAN primero
        self.logger.info(f"Flow C: BAN {account_number} not visible, searching first")
        search_input_xpath = "//account-search//input[@placeholder='Search by Billing account number']"
        search_button_xpath = "//account-search//button[@name='btn_search']"

        self.browser_wrapper.type_text(search_input_xpath, account_number)
        self.browser_wrapper.click_element(search_button_xpath)
        time.sleep(3)

        self.browser_wrapper.click_element(select_row_xpath)
        time.sleep(5)
        self.logger.info("Account selected successfully")

    def _navigate_to_usage_details(self):
        """Navega a usage details y configura el dropdown (parte comun)."""
        self.logger.info("Navigating to usage details...")

        # usage header (hover)
        usage_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/nav[1]/ul[1]/li[2]/a[1]"
        self.browser_wrapper.hover_element(usage_xpath)
        time.sleep(2)

        # usage details: (click)
        usage_details_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/nav[1]/ul[1]/li[2]/div[1]/ul[1]/li[1]/ul[1]/li[1]/a[1]/span[1]"
        self.browser_wrapper.click_element(usage_details_xpath)
        self.browser_wrapper.wait_for_page_load()
        time.sleep(60)  # Esperar 60 segundos como especificado
        self.logger.info("Reports section found")

        # Extract pool data before configuring dropdown
        self._extract_pool_data()

        # Configurar dropdown con logica de fallback
        self._configure_data_share_dropdown()
        time.sleep(30)  # Esperar 30 segundos como especificado

    def _extract_pool_data(self):
        """Extract pool_size and pool_used from the shared allowance container."""

        def gb_to_bytes(gb_value: float) -> int:
            """Convert GB to bytes."""
            return int(gb_value * 1024 * 1024 * 1024)

        def extract_gb_value(text: str) -> float:
            """Extract numeric GB value from text."""
            match = re.search(r"([\d,]+\.?\d*)\s*GB", text)
            if match:
                return float(match.group(1).replace(",", ""))
            return 0.0

        def extract_used_gb(text: str) -> float:
            """Extract 'used' GB value from text."""
            match = re.search(r"([\d,]+\.?\d*)\s*GB\s*used", text, re.IGNORECASE)
            if match:
                return float(match.group(1).replace(",", ""))
            return 0.0

        total_pool_size_gb = 0.0
        total_pool_used_gb = 0.0

        try:
            # Get all shared allowance containers
            containers_xpath = "//*[@id='sharedAllowanceAdminContainer']/div[2]"
            containers = self.browser_wrapper.page.locator(containers_xpath).all()

            self.logger.info(f"Found {len(containers)} shared allowance containers")

            for i, container in enumerate(containers):
                try:
                    # Extract "Included" value (pool size)
                    included_span = container.locator("xpath=div[1]/span").first
                    if included_span.count() > 0:
                        included_text = included_span.text_content() or ""
                        included_gb = extract_gb_value(included_text)
                        total_pool_size_gb += included_gb
                        self.logger.info(f"Container {i+1} - Included: {included_gb} GB")

                    # Extract "used" value (pool used)
                    used_span = container.locator("xpath=div[2]/span[1]").first
                    if used_span.count() > 0:
                        used_text = used_span.text_content() or ""
                        used_gb = extract_used_gb(used_text)
                        total_pool_used_gb += used_gb
                        self.logger.info(f"Container {i+1} - Used: {used_gb} GB")

                except Exception as e:
                    self.logger.warning(f"Error extracting data from container {i+1}: {str(e)}")
                    continue

            # Convert to bytes and set class attributes
            self.pool_size = gb_to_bytes(total_pool_size_gb)
            self.pool_used = gb_to_bytes(total_pool_used_gb)

            self.logger.info(f"Total Pool Size: {total_pool_size_gb} GB ({self.pool_size} bytes)")
            self.logger.info(f"Total Pool Used: {total_pool_used_gb} GB ({self.pool_used} bytes)")

        except Exception as e:
            self.logger.error(f"Error extracting pool data: {str(e)}")
            self.pool_size = 0
            self.pool_used = 0

    def _configure_data_share_dropdown(self):
        """Configura el dropdown con logica de fallback entre Medium y Corp Business Data Share."""
        dropdown_xpath = "/html[1]/body[1]/div[1]/main[1]/div[1]/div[2]/account-details[1]/div[1]/div[2]/account-shared-data[1]/div[2]/category-usage-details[1]/div[1]/div[2]/div[4]/div[1]/subscriber-usage-details[1]/div[1]/div[2]/filter-selection[1]/div[1]/select[1]"

        try:
            # Intentar primero con "Medium Business Data Share"
            self.logger.info("Trying to select 'Medium Business Data Share'...")
            self.browser_wrapper.select_dropdown_option(dropdown_xpath, "Medium Business Data Share")
            self.logger.info("'Medium Business Data Share' selected")
        except Exception as e:
            self.logger.warning("'Medium Business Data Share' not available, trying 'Corp Business Data Share'...")
            try:
                self.browser_wrapper.select_dropdown_option(dropdown_xpath, "Corp Business Data Share")
                self.logger.info("'Corp Business Data Share' selected")
            except Exception as e2:
                self.logger.error(f"Error configuring dropdown: {str(e2)}")
                raise e2

        self.browser_wrapper.wait_for_page_load()

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Descarga los archivos de uso diario de Bell."""
        downloaded_files = []

        # Obtener el BillingCycleDailyUsageFile del billing_cycle
        daily_usage_file = billing_cycle.daily_usage_files[0] if billing_cycle.daily_usage_files else None
        if daily_usage_file:
            self.logger.info(f"Mapping Daily Usage file -> BillingCycleDailyUsageFile ID {daily_usage_file.id}")
        else:
            self.logger.warning("BillingCycleDailyUsageFile not found for mapping")

        try:
            # download tab: (click) - usando nuevos XPaths
            download_tab_xpath = "/html/body/div[1]/main/div[1]/div[2]/account-details/div/div[2]/account-shared-data/div[2]/category-usage-details/div/div[2]/div[4]/div/subscriber-usage-details/div/div[3]/div/search/nav/ul/li[3]/a"
            self.browser_wrapper.click_element(download_tab_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(5)  # Esperar 5 segundos

            # download all pages: (click) - usando nuevos XPaths
            download_all_pages_xpath = "/html/body/div[1]/main/div[1]/div[2]/account-details/div/div[2]/account-shared-data/div[2]/category-usage-details/div/div[2]/div[4]/div/subscriber-usage-details/div/div[3]/div/search/nav/ul/li[3]/ul/li/a"
            page = self.browser_wrapper.page
            with page.expect_download() as download_info:
                self.browser_wrapper.click_element(download_all_pages_xpath)
                self.browser_wrapper.wait_for_page_load()
                time.sleep(5)

            download = download_info.value
            suggested_filename = f"report_{datetime.now().timestamp()}_{download.suggested_filename}"
            final_path = os.path.join(self.job_downloads_dir, suggested_filename)

            # Guardar en disco
            download.save_as(final_path)

            # Crear FileDownloadInfo con mapeo al BillingCycleDailyUsageFile
            downloaded_file = FileDownloadInfo(
                file_id=daily_usage_file.id,
                file_name=suggested_filename,
                download_url="N/A",
                file_path=final_path,
                daily_usage_file=daily_usage_file,
            )
            downloaded_files.append(downloaded_file)

            # Confirmar mapeo
            if daily_usage_file:
                self.logger.info(
                    f"MAPPING CONFIRMED: {suggested_filename} -> BillingCycleDailyUsageFile ID {daily_usage_file.id}"
                )
            else:
                self.logger.warning(f"File downloaded without specific BillingCycleDailyUsageFile mapping")

            # Reset a pantalla inicial usando el logo
            self._reset_to_main_screen()

            return downloaded_files
        except Exception as e:
            self.logger.error(f"Error downloading Daily Usage file: {str(e)}")
            return downloaded_files

    def _reset_to_main_screen(self):
        """Reset a la pantalla inicial de Bell usando el logo."""
        try:
            self.logger.info("Resetting to Bell initial screen...")
            logo_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/a[1]"
            self.browser_wrapper.click_element(logo_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)
            self.logger.info("Reset to Bell completed")
        except Exception as e:
            self.logger.error(f"Error in Bell reset: {str(e)}")
