import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    FileDownloadInfo,
    MonthlyReportsScraperStrategy,
)
from web_scrapers.domain.entities.session import Credentials
from web_scrapers.domain.enums import BellFileSlug

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class BellMonthlyReportsScraperStrategyLegacy(MonthlyReportsScraperStrategy):
    """LEGACY: Monthly reports scraper for Bell (old portal). Deprecated - use BellMonthlyReportsScraperStrategy instead."""

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.report_dictionary = {
            "cost_overview": None,
            "enhanced_user_profile_report": None,
            "usage_overview": None,
        }
        self._current_credentials: Optional[Credentials] = None
        self._reauthentication_callback = None

    def set_reauthentication_callback(self, callback):
        """Establece el callback para re-autenticacion despues de limpieza de cache."""
        self._reauthentication_callback = callback

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Busca la seccion de archivos mensuales en el portal de Bell."""
        return self._find_files_section_with_retry(config, billing_cycle, max_retries=1)

    def _find_files_section_with_retry(
        self, config: ScraperConfig, billing_cycle: BillingCycle, max_retries: int = 1
    ) -> Optional[Any]:
        """Busca la seccion de archivos con reintento automatico en caso de error de cache."""
        for attempt in range(max_retries + 1):
            try:
                self.logger.info(f"Searching for files section (attempt {attempt + 1}/{max_retries + 1})")

                # Look for reports
                report_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/nav[1]/ul[1]/li[4]/a[1]"
                self.browser_wrapper.hover_element(report_xpath)
                time.sleep(2)  # Esperar 2 segundos despues del hover

                # e-report (click)
                ereport_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/nav[1]/ul[1]/li[4]/div[1]/ul[1]/li[1]/a[1]/h3[1]"
                current_url: str = self.browser_wrapper.get_current_url()
                self.logger.debug(f"Current url: {current_url}")
                self.browser_wrapper.click_and_switch_to_new_tab(ereport_xpath, 90000)

                # DETECTAR ERROR DE CACHE: Verificar que el header este disponible
                if not self._verify_ereport_header_available():
                    self.logger.warning("Potential cache error detected in e-reports")

                # standard reports (click)
                standard_reports_xpath = (
                    "/html[1]/body[1]/header[1]/div[1]/div[2]/div[1]/div[1]/div[1]/ul[1]/li[2]/div[1]/span[1]/a[1]"
                )
                self.browser_wrapper.click_element(standard_reports_xpath)
                self.browser_wrapper.wait_for_page_load()
                time.sleep(50)

                self.logger.info("Files section found successfully")
                return {"section": "monthly_reports", "ready_for_download": True}

            except Exception as e:
                self.logger.error(f"Error on attempt {attempt + 1}: {str(e)}")
                try:
                    if self.browser_wrapper.get_tab_count() > 1:
                        self.browser_wrapper.close_current_tab()
                        self.browser_wrapper.switch_to_previous_tab()
                except:
                    self.logger.error("Could not close previous window and switch to previous tab")

                if attempt < max_retries:
                    continue

        return None

    def _verify_ereport_header_available(self) -> bool:
        """Verifica que el header de e-reports este disponible (no hay error de cache)."""
        try:
            # Verificar que el header de e-reports este presente
            header_xpath = (
                "/html[1]/body[1]/header[1]/div[1]/div[2]/div[1]/div[1]/div[1]/ul[1]/li[2]/div[1]/span[1]/a[1]"
            )
            is_available = self.browser_wrapper.is_element_visible(header_xpath, timeout=90000)

            if is_available:
                self.logger.info("E-reports header available")
                return True
            else:
                self.logger.warning("E-reports header not available - possible cache error")
                return False

        except Exception as e:
            self.logger.error(f"Error verifying header: {e}")
            return False

    def _handle_cache_recovery(self) -> bool:
        """Maneja la recuperacion cuando se detecta error de cache."""
        try:
            self.logger.info("Starting browser data cleanup...")

            # Cerrar pestanas adicionales y regresar a main
            if self.browser_wrapper.get_tab_count() > 1:
                self.browser_wrapper.close_all_tabs_except_main()
                time.sleep(2)

            # Limpiar datos del navegador (esto invalidara la sesion)
            self.browser_wrapper.clear_browser_data(clear_cookies=True, clear_storage=True, clear_cache=True)
            time.sleep(3)

            # Notificar que necesitamos re-autenticacion
            # La sesion se perdio automaticamente por la limpieza de datos
            self.logger.info("Data cleaned - session lost and automatic re-login required")

            # El SessionManager detectara automaticamente que la sesion no esta activa
            # cuando se llame al siguiente metodo del scraper
            return True

        except Exception as e:
            self.logger.error(f"Error in cache recovery: {e}")
            return False

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        downloaded_files = []

        slug_to_report_name = {
            "cost_overview": "Cost Overview",
            "enhanced_user_profile": "Enhanced User Profile Report",
            "usage_overview": "Usage Overview",
        }

        # Mapeo de nombres de reportes a valores del dropdown
        report_types = {"Cost Overview": 2, "Enhanced User Profile Report": 7, "Usage Overview": 5}

        # Mapear BillingCycleFiles por slug del carrier_report para asociacion exacta
        billing_cycle_file_map = {}
        slug_order = []  # Orden de slugs para mapeo posterior

        if billing_cycle.billing_cycle_files:
            for bcf in billing_cycle.billing_cycle_files:
                if bcf.carrier_report and bcf.carrier_report.slug:
                    slug = bcf.carrier_report.slug
                    billing_cycle_file_map[slug] = bcf
                    slug_order.append(slug)
                    report_name = slug_to_report_name.get(slug, slug)
                    self.logger.info(
                        f"Mapping BillingCycleFile ID {bcf.id} -> Slug: '{slug}' -> Report: '{report_name}'"
                    )

        standard_report_dropdown_xpath = "/html/body/div[3]/div/div/div[1]/div[1]/div/div[1]/div[1]/div[1]/select"
        left_date_dropdown_xpath = "/html[1]/body[1]/div[3]/div[1]/div[1]/div[1]/div[2]/div[2]/div[2]/div[1]/div[7]/div[1]/div[2]/div[1]/select[1]"
        right_date_dropdown_xpath = "/html[1]/body[1]/div[3]/div[1]/div[1]/div[1]/div[2]/div[2]/div[2]/div[1]/div[7]/div[1]/div[2]/div[1]/select[2]"
        apply_button_xpath = (
            "/html[1]/body[1]/div[3]/div[1]/div[1]/div[1]/div[2]/div[2]/div[2]/div[1]/div[11]/div[2]/button[1]"
        )
        excel_image_xpath = "/html[1]/body[1]/div[3]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[3]/img[2]"

        start_date_text = billing_cycle.start_date.strftime("%b %Y")
        end_date_text = billing_cycle.end_date.strftime("%b %Y")

        generated_slugs_order = []
        for slug in slug_order:
            if slug in slug_to_report_name:
                report_name = slug_to_report_name[slug]
                if report_name in report_types:
                    report_value = report_types[report_name]
                    self.logger.info(f"Processing slug '{slug}' -> report: {report_name}")
                    selected_option = self.browser_wrapper.get_text(standard_report_dropdown_xpath)
                    if not selected_option or report_name.lower() != selected_option.lower():
                        self.browser_wrapper.select_dropdown_by_value(
                            standard_report_dropdown_xpath, str(report_value)
                        )
                    time.sleep(2)
                    self.logger.debug(
                        f"Start date text to select: {start_date_text}, end date text to select: {end_date_text}"
                    )
                    self.browser_wrapper.select_dropdown_option(left_date_dropdown_xpath, start_date_text)
                    self.browser_wrapper.select_dropdown_option(right_date_dropdown_xpath, end_date_text)
                    self.logger.debug(f"Dates selected: from: {start_date_text}, to: {end_date_text}")
                    self.browser_wrapper.click_element(apply_button_xpath)
                    self.browser_wrapper.wait_for_page_load()
                    time.sleep(5)
                    self.browser_wrapper.click_element(excel_image_xpath)
                    time.sleep(10)
                    generated_slugs_order.append(slug)
                    self.logger.info(
                        f"Slug '{slug}' ({report_name}) requested (position {len(generated_slugs_order)} in queue)"
                    )
                else:
                    self.logger.warning(f"Report '{report_name}' for slug '{slug}' not found in report_types")
            else:
                self.logger.warning(f"Slug '{slug}' not found in slug_to_report_name mapping")

        self.logger.info(f"Order of generated slugs: {generated_slugs_order}")

        time.sleep(60 * 2)
        try:
            self.logger.info("Waiting for downloads table to appear...")
            table_xpath = "/html/body/div[4]/div[2]/div/table"
            self.browser_wrapper.wait_for_element(table_xpath, timeout=120000)
            time.sleep(5)

            self.logger.info("Downloads table found. Starting download of first 3 files...")

            records_to_download = len(generated_slugs_order)
            for i in range(records_to_download, 0, -1):
                try:
                    # Determinar que slug corresponde a este archivo (orden inverso)
                    slug_index = records_to_download - i  # 0, 1, 2
                    current_slug = (
                        generated_slugs_order[slug_index] if slug_index < len(generated_slugs_order) else None
                    )
                    current_report_name = slug_to_report_name.get(current_slug) if current_slug else None

                    corresponding_bcf = billing_cycle_file_map.get(current_slug) if current_slug else None
                    self.logger.info(
                        f"Downloading file #{i} -> Slug: '{current_slug}' -> Report: '{current_report_name}'"
                    )
                    if corresponding_bcf:
                        self.logger.info(f"    Associated with BillingCycleFile ID: {corresponding_bcf.id}")
                    else:
                        self.logger.warning(f"    BillingCycleFile not found for mapping")

                    # XPath especifico para cada fila: /html/body/div[4]/div[2]/div/table/tbody/tr[i]/td[1]/a
                    download_link_xpath = f"/html/body/div[4]/div[2]/div/table/tbody/tr[{i}]/td[1]/a"

                    # Verificar que el enlace existe antes de hacer clic
                    if not self.browser_wrapper.find_element_by_xpath(download_link_xpath, timeout=5000):
                        self.logger.warning(f"Download link not found for file #{i}")
                        continue

                    # Obtener el texto del enlace para logging
                    try:
                        link_text = self.browser_wrapper.get_text(download_link_xpath)
                        self.logger.info(f"Downloading: {link_text}")
                    except:
                        self.logger.info(f"Downloading file in row #{i}")

                    downloaded_file_path = self.browser_wrapper.expect_download_and_click(
                        download_link_xpath, timeout=30000, downloads_dir=self.job_downloads_dir
                    )
                    self.logger.debug(f"Downloaded file path: {downloaded_file_path}")

                    if downloaded_file_path:
                        actual_file_name = os.path.basename(downloaded_file_path)
                        self.logger.info(f"File downloaded successfully: {actual_file_name}")

                        # Crear FileDownloadInfo con mapeo al BillingCycleFile
                        file_download_info = FileDownloadInfo(
                            file_id=corresponding_bcf.id if corresponding_bcf else i,
                            file_name=actual_file_name,
                            download_url="N/A",
                            file_path=downloaded_file_path,
                            billing_cycle_file=corresponding_bcf,
                        )
                        downloaded_files.append(file_download_info)

                        # Imprimir confirmacion del mapeo
                        if corresponding_bcf:
                            self.logger.info(
                                f"    MAPPING CONFIRMED: {actual_file_name} -> BillingCycleFile ID {corresponding_bcf.id} (Slug: '{current_slug}' -> {current_report_name})"
                            )
                        else:
                            self.logger.warning(f"    File downloaded without specific BillingCycleFile mapping")

                    else:
                        self.logger.warning(
                            f"expect_download_and_click failed for file #{i}, trying traditional method..."
                        )
                        self.browser_wrapper.click_element(download_link_xpath)
                        time.sleep(5)
                        estimated_filename = (
                            f"bell_report_{current_slug}_{datetime.now().timestamp()}.xlsx"
                            if current_slug
                            else f"bell_report_{i}_{datetime.now().timestamp()}.xlsx"
                        )

                        file_download_info = FileDownloadInfo(
                            file_id=corresponding_bcf.id,
                            file_name=estimated_filename,
                            download_url="N/A",
                            file_path=f"{self.job_downloads_dir}/{estimated_filename}",
                            billing_cycle_file=corresponding_bcf,
                        )
                        downloaded_files.append(file_download_info)

                        self.logger.info(f"Download started (traditional method): {estimated_filename}")
                        if corresponding_bcf:
                            self.logger.info(
                                f"    MAPPING CONFIRMED: {estimated_filename} -> BillingCycleFile ID {corresponding_bcf.id} (Slug: '{current_slug}' -> {current_report_name})"
                            )

                    # Pequena pausa entre descargas
                    time.sleep(5)
                except Exception as e:
                    self.logger.error(f"Error trying to download file #{i}: {str(e)}")
                    continue

            # Imprimir resumen final de mapeos
            self.logger.info(f"\nFINAL FILE MAPPING SUMMARY:")
            self.logger.info(f"   Total files downloaded: {len(downloaded_files)}")
            for idx, file_info in enumerate(downloaded_files, 1):
                if file_info.billing_cycle_file:
                    bcf = file_info.billing_cycle_file
                    slug = bcf.carrier_report.slug if hasattr(bcf, "carrier_report") and bcf.carrier_report else "N/A"
                    report_name = slug_to_report_name.get(slug, slug) if slug != "N/A" else "N/A"
                    self.logger.info(
                        f"   [{idx}] {file_info.file_name} -> BillingCycleFile ID {bcf.id} (Slug: '{slug}' -> {report_name})"
                    )
                else:
                    self.logger.info(f"   [{idx}] {file_info.file_name} -> NO MAPPING")
            self.logger.info(f"=====================================")

            self.browser_wrapper.close_current_tab()
            time.sleep(2)
            # Reset a pantalla inicial usando el logo
            self._reset_to_main_screen()
            return downloaded_files
        except Exception as e:
            self.logger.error(f"General error processing downloads table: {e}")
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


class BellMonthlyReportsScraperStrategy(MonthlyReportsScraperStrategy):
    """Monthly reports scraper for Bell Enterprise Centre"""

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.logger.setLevel(logging.DEBUG)
        self.report_dictionary = {
            BellFileSlug.COST_OVERVIEW.value: None,
            BellFileSlug.ENHANCED_USER_PROFILE.value: None,
            BellFileSlug.USAGE_OVERVIEW.value: None,
            BellFileSlug.INVOICE_CHARGE_REPORT.value: None,
        }

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navigate to the My Reports section in Bell Enterprise Centre."""
        try:
            self.logger.info("Navigating to Bell Enterprise Centre reports...")

            # Enhanced Mobility Reports link - used to check if we're already in Service section
            enhanced_mobility_xpath = "//*[@id='ec-goa-reports-app']/div[1]/section/main/div/div/div/ul/li[1]/a"

            # Step 1: Check if we're already in Service section
            already_in_service = False
            try:
                if self.browser_wrapper.find_element_by_xpath(enhanced_mobility_xpath, timeout=3000):
                    self.logger.info("Already in Service section - skipping navigation")
                    already_in_service = True
            except:
                self.logger.info("Not in Service section, navigating there...")

            # Step 2: If NOT in Service, do full navigation (My Reports -> Service)
            if not already_in_service:
                # Step 2a: Click on "My Reports"
                my_reports_selectors = [
                    "#ec-sidebar > div > div > div.ec-sidebar__container > ul:nth-child(1) > li:nth-child(3) > button",
                    "#ec-sidebar > div > div > div.ec-sidebar__container > ul:nth-child(1) > li:nth-child(2) > button",
                ]

                my_reports_button_clicked = False
                for selector in my_reports_selectors:
                    try:
                        self.logger.debug(f"Trying selector: {selector}")
                        if self.browser_wrapper.find_element_by_xpath(selector, selector_type="css"):
                            button_text = self.browser_wrapper.get_text(selector, selector_type="css")
                            if "My Reports" in button_text:
                                self.logger.info(f"Found 'My Reports' button with text: {button_text}")
                                self.browser_wrapper.click_element(selector, selector_type="css")
                                self.browser_wrapper.wait_for_page_load()
                                self.logger.info("My Reports section opened")
                                my_reports_button_clicked = True
                                break
                            else:
                                self.logger.warning(
                                    f"Selector matched but text doesn't contain 'My Reports': {button_text}"
                                )
                    except Exception as e:
                        self.logger.debug(f"Selector failed: {str(e)}, trying next selector...")
                        continue

                if not my_reports_button_clicked:
                    raise Exception("Could not find 'My Reports' button in any of the expected positions")

                # Step 2b: Click on "Service" sub-menu
                service_sub_selectors = [
                    "nav:nth-child(4) > div:nth-child(2) > div:nth-child(1) > div:nth-child(3) > ul:nth-child(1) > li:nth-child(3) > ul:nth-child(2) > li:nth-child(1) > a:nth-child(1) > span:nth-child(1)",
                    "nav:nth-child(4) > div:nth-child(2) > div:nth-child(1) > div:nth-child(3) > ul:nth-child(1) > li:nth-child(2) > ul:nth-child(2) > li:nth-child(1) > a:nth-child(1) > span:nth-child(1)",
                ]

                service_sub_clicked = False
                for selector in service_sub_selectors:
                    try:
                        self.logger.debug(f"Trying selector: {selector}")
                        if self.browser_wrapper.find_element_by_xpath(selector, selector_type="css"):
                            self.logger.info(f"Found 'Service' sub-menu with selector")
                            self.browser_wrapper.click_element(selector, selector_type="css")
                            self.browser_wrapper.wait_for_page_load()
                            self.logger.info("Service sub-menu accessed")
                            service_sub_clicked = True
                            break
                    except Exception as e:
                        self.logger.debug(f"Selector failed: {str(e)}, trying next selector...")
                        continue

                if not service_sub_clicked:
                    raise Exception("Could not find 'Service' sub-menu in any of the expected positions")

            # Step 3: Click on "Enhanced Mobility Reports" link and switch to new tab
            current_url = self.browser_wrapper.get_current_url()
            self.logger.debug(f"Current url before clicking Enhanced Mobility: {current_url}")

            # Click and switch to new tab (similar to legacy implementation)
            self.browser_wrapper.click_and_switch_to_new_tab(enhanced_mobility_xpath, timeout=90000)
            self.logger.info("Switched to Enhanced Mobility Reports new tab")

            self.logger.info("Waiting 30 seconds for reports interface to load...")
            time.sleep(30)

            my_workspace_icon_xpath = (
                "/html/body/div[2]/app-base/section/block-ui/div/div/app-aside-left/div/div/div/ul/li[3]"
            )
            self.browser_wrapper.click_element(my_workspace_icon_xpath)
            self.logger.info("Workspace icon accessed")

            shared_with_me_xpath = "/html[1]/body[1]/div[2]/app-base[1]/section[1]/block-ui[1]/div[1]/div[1]/div[1]/app-workspace[1]/app-ana-page[1]/div[2]/div[1]/div[1]/div[1]/div[1]/app-ws-folder-tree[1]/div[1]/div[1]/p-tree[1]/div[1]/div[1]/ul[1]/p-treenode[2]/li[1]/div[1]/span[3]/span[1]/div[1]"
            self.browser_wrapper.click_element(shared_with_me_xpath)
            self.logger.info("Shared With me accessed")

            enhanced_mobility_reports_xpath = '//*[@id="ws-grid__appfolder_0"]'
            self.browser_wrapper.double_click_element(enhanced_mobility_reports_xpath)
            self.logger.info("enhanced mobility reports accessed (double-clicked)")

            self.logger.info("Navigation to reports section completed successfully")
            return {"section": "enterprise_monthly_reports", "ready_for_download": True}

        except Exception as e:
            self.logger.error(f"Error during navigation to reports: {str(e)}")
            # Close the new tab if it was opened and return to original tab before failing
            try:
                if self.browser_wrapper.get_tab_count() > 1:
                    self.logger.info("Closing Enhanced Mobility Reports tab due to error...")
                    self.browser_wrapper.close_current_tab()
                    self.logger.info("Switched back to original tab after error")
            except Exception as close_error:
                self.logger.warning(f"Error closing tab during error recovery: {str(close_error)}")
            return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Download files for all 4 reports with account and invoice month filters."""
        downloaded_files = []

        # Report configuration
        reports = [
            {
                "name": "cost overview report",
                "slug": BellFileSlug.COST_OVERVIEW.value,
                "workbook_button": "//*[@id='ds-sec-expand']/div[2]/div/div[2]/div/div[12]/button",
            },
            {
                "name": "usage overview report",
                "slug": BellFileSlug.USAGE_OVERVIEW.value,
                "workbook_button": "//*[@id='ds-sec-expand']/div[2]/div/div[2]/div/div[12]/button",
            },
            {
                "name": "enhanced user profile report",
                "slug": BellFileSlug.ENHANCED_USER_PROFILE.value,
                "workbook_button": "//*[@id='ds-sec-expand']/div[2]/div/div[2]/div/div[12]/button",
            },
            {
                "name": "invoice charge report",
                "slug": BellFileSlug.INVOICE_CHARGE_REPORT.value,
                "workbook_button": "//*[@id='ds-sec-expand']/div[2]/div/div[2]/div/div[12]/button",
            },
        ]

        # Mapear BillingCycleFiles por slug
        billing_cycle_file_map = {}
        if billing_cycle.billing_cycle_files:
            for bcf in billing_cycle.billing_cycle_files:
                if bcf.carrier_report and bcf.carrier_report.slug:
                    slug = bcf.carrier_report.slug
                    billing_cycle_file_map[slug] = bcf
                    self.logger.info(f"Mapping BillingCycleFile ID {bcf.id} -> Slug: '{slug}'")

        # Calculate invoice month from billing cycle
        invoice_month = self._calculate_invoice_month(billing_cycle)
        self.logger.info(f"Invoice month for filters: {invoice_month}")

        # Get account number for filtering
        account_number = billing_cycle.account.number if billing_cycle.account else None
        self.logger.info(f"Account number for filters: {account_number}")

        # Generate each report
        generated_reports = []
        for report_config in reports:
            try:
                self.logger.info(f"Processing report: {report_config['name']}")

                # Step 1: Click on the report grid by searching for it dynamically
                self._click_report_by_name(report_config["name"])
                self.browser_wrapper.wait_for_page_load()
                self.logger.info(f"Report grid clicked for {report_config['name']}")

                # Step 2: Click on the workbook button
                self.browser_wrapper.click_element(report_config["workbook_button"])
                self.browser_wrapper.wait_for_page_load()
                self.logger.info(f"Workbook opened for {report_config['name']}")

                # Step 3: Wait 30 seconds for workbook to load
                self.logger.info("Waiting 30 seconds for workbook interface to load...")
                time.sleep(30)

                # Step 4: Expand configuration panel
                expand_config_xpath = "//*[@id='wb-sheet-container']/div/div/div[2]"
                self.browser_wrapper.click_element(expand_config_xpath)
                self.logger.info("Configuration panel expanded")

                # Step 5: Apply filters (account and invoice month)
                self._apply_report_filters(report_config["slug"], account_number, invoice_month, report_config)

                # Step 6: Export to Excel
                self._export_report_to_excel(report_config["slug"])

                generated_reports.append(report_config["slug"])
                self.logger.info(f"Report '{report_config['name']}' generation completed")

                # Step 7: Return to enhanced reports folder
                breadcrumb_xpath = "//*[@id='breadcrumb_item_1']"
                self.browser_wrapper.click_element(breadcrumb_xpath)
                self.browser_wrapper.wait_for_page_load()

            except Exception as e:
                # Persist a single-line, descriptive warning per failed report so
                # the scraper_job log carries the reason (e.g. "Invoice month not
                # available" or "workbook did not render"), not just the file
                # logger noise. main.py:_flush_scraper_warnings drains
                # self.job_warnings into the job's stored log after execute().
                raw_msg = str(e).strip().splitlines()[0] if str(e).strip() else type(e).__name__
                self._record_job_warning(
                    f"Bell monthly report '{report_config['name']}' (slug={report_config['slug']}) "
                    f"failed: {raw_msg}"
                )
                self.logger.error(f"Error processing report '{report_config['name']}': {str(e)}")
                continue

        self.logger.info(f"All reports generated. Order: {generated_reports}")

        # Step 8: Download files from alerts/notifications
        self.logger.info("Downloading generated reports from alerts...")
        downloaded_files = self._wait_for_and_download_reports(generated_reports, billing_cycle_file_map)
        self.logger.info(f"Downloaded {len(downloaded_files)} files from alerts")

        # Step 9: Close the new tab and return to the original tab
        try:
            if self.browser_wrapper.get_tab_count() > 1:
                self.logger.info("Closing Enhanced Mobility Reports tab...")
                self.browser_wrapper.close_current_tab()
                self.logger.info("Switched back to original tab")
            else:
                self.logger.warning("No additional tabs found to close")
        except Exception as e:
            self.logger.warning(f"Error closing tab: {str(e)}")

        return downloaded_files

    def _click_report_by_name(self, report_name: str) -> None:
        """Click on a report by searching for the description div containing the report name.

        Uses a focused search from the main container to find the report cards.
        Handles case-insensitive matching for report names.
        """
        try:
            self.logger.info(f"Searching for report: '{report_name}'...")
            self.logger.info("Waiting 15 seconds for reports to fully load...")
            time.sleep(15)

            # Main container XPath that holds all report cards
            container_xpath = "/html/body/div[2]/app-base/section/block-ui/div/div/div/app-workspace/app-ana-page/div[2]/div/div/div/div/div/app-ws-view/div/app-ws-icon-view/app-ws-my-folder/div/div/div/div[2]"

            # Wait for container to be visible
            self.logger.debug(f"Waiting for report container to be visible...")
            self.browser_wrapper.wait_for_element(container_xpath, timeout=10000)
            self.logger.debug("Report container found")

            # Search for the description div within the container using case-insensitive matching
            # The text in HTML has proper case, so we need to match case-insensitively
            report_xpath = f"{container_xpath}//div[@class='ws-grid__item__description ng-star-inserted' and contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), translate('{report_name.lower()}', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))]"
            self.logger.debug(f"Searching for report within container (case-insensitive): {report_name}")

            # Wait for the specific report to appear
            self.browser_wrapper.wait_for_element(report_xpath, timeout=10000)

            self.logger.info(f"Report '{report_name}' found, clicking it...")
            self.browser_wrapper.click_element(report_xpath)

            self.logger.info(f"Report '{report_name}' found and clicked successfully")

        except Exception as e:
            self.logger.error(f"Error clicking report '{report_name}': {str(e)}")
            # Try alternative approach: search for the parent ws-grid__item div by aria-label
            try:
                self.logger.info(f"Trying alternative search for report '{report_name}'...")

                container_xpath = "/html/body/div[2]/app-base/section/block-ui/div/div/div/app-workspace/app-ana-page/div[2]/div/div/div/div/div/app-ws-view/div/app-ws-icon-view/app-ws-my-folder/div/div/div/div[2]"

                # Search for the parent item div by aria-label (case-insensitive)
                alt_report_xpath = f"{container_xpath}//div[@class and contains(@class, 'ws-grid__item') and contains(translate(@aria-label, 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), translate('{report_name.lower()}', 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'))]"
                self.logger.debug(
                    f"Alternative XPath: searching for parent container with aria-label (case-insensitive)"
                )

                self.browser_wrapper.wait_for_element(alt_report_xpath, timeout=10000)
                self.browser_wrapper.click_element(alt_report_xpath)

                self.logger.info(f"Report '{report_name}' found via alternative method and clicked successfully")

            except Exception as e2:
                self.logger.error(f"Alternative search also failed: {str(e2)}")
                raise e

    def _calculate_invoice_month(self, billing_cycle: BillingCycle) -> str:
        """Calculate the invoice month string from billing cycle end date.

        Returns format like "Oct 2025"
        """
        try:
            end_date = billing_cycle.end_date
            month_name = end_date.strftime("%b")
            year = end_date.strftime("%Y")
            invoice_month = f"{month_name} {year}"
            return invoice_month
        except Exception as e:
            self.logger.error(f"Error calculating invoice month: {str(e)}")
            return ""

    def _parse_notification_time(self, time_text: str) -> Optional[int]:
        """
        Parse notification time text and return minutes ago.
        Returns None if parsing fails or time is invalid.

        Examples:
            "a few seconds ago" -> 0 minutes
            "a minute ago" -> 1 minute
            "3 minutes ago" -> 3 minutes
            "16 hours ago" -> 960 minutes (invalid, too old)
            "2 days ago" -> None (invalid)
        """
        time_text = time_text.strip().lower()

        # Pattern: "a few seconds ago" or "just now"
        if "second" in time_text or "just now" in time_text or "few seconds" in time_text:
            return 0

        # Pattern: "a minute ago"
        if time_text == "a minute ago":
            return 1

        # Pattern: "X minutes ago"
        minutes_match = re.search(r"(\d+)\s*minute", time_text)
        if minutes_match:
            return int(minutes_match.group(1))

        # Pattern: "X hours ago" or "an hour ago"
        hours_match = re.search(r"(\d+)\s*hour", time_text)
        if hours_match:
            return int(hours_match.group(1)) * 60

        if "an hour ago" in time_text or "1 hour ago" in time_text:
            return 60

        # Pattern: "X days ago" - too old, return invalid
        if "day" in time_text or "week" in time_text or "month" in time_text:
            return None

        # Couldn't parse
        self.logger.warning(f"Could not parse time text: '{time_text}'")
        return None

    def _is_notification_recent(self, notification_xpath: str, max_minutes: int = 60) -> bool:
        """
        Check if notification was generated within the last N minutes.

        Args:
            notification_xpath: XPath of the notification <li>
            max_minutes: Maximum age in minutes (default: 60)

        Returns:
            True if notification is recent enough, False otherwise
        """
        try:
            # Find the time element within this notification
            time_xpath = f"{notification_xpath}//div[contains(@class, 'kt-notifi-time')]"

            time_element = self.browser_wrapper.find_element_by_xpath(time_xpath, timeout=3000)
            if not time_element:
                self.logger.warning("Time element not found in notification")
                return False

            time_text = self.browser_wrapper.get_text(time_xpath)
            self.logger.debug(f"Notification time text: '{time_text}'")

            minutes_ago = self._parse_notification_time(time_text)

            if minutes_ago is None:
                self.logger.warning(f"Could not parse time, rejecting notification: '{time_text}'")
                return False

            is_recent = minutes_ago <= max_minutes

            if is_recent:
                self.logger.info(f"Notification is recent: {minutes_ago} minutes ago (max: {max_minutes})")
            else:
                self.logger.warning(f"Notification is too old: {minutes_ago} minutes ago (max: {max_minutes})")

            return is_recent

        except Exception as e:
            self.logger.error(f"Error checking notification time: {e}")
            return False

    def _create_report_name_mappings(self) -> Dict[str, List[str]]:
        """Map slugs to expected notification text (from second <b> tag)."""
        return {
            BellFileSlug.COST_OVERVIEW.value: ["cost overview report"],
            BellFileSlug.USAGE_OVERVIEW.value: ["usage overview report"],
            BellFileSlug.ENHANCED_USER_PROFILE.value: ["enhanced user profile report"],
            BellFileSlug.INVOICE_CHARGE_REPORT.value: ["invoice charge report"],
        }

    def _find_notification_by_report_slug(self, report_slug: str, max_age_minutes: int = 60) -> Optional[str]:
        """
        Find notification by matching the SECOND <b> tag and validating timestamp.

        Args:
            report_slug: Slug of the report to find
            max_age_minutes: Maximum age of notification in minutes

        Returns:
            XPath of the notification if found and recent, None otherwise
        """
        name_mappings = self._create_report_name_mappings()
        possible_names = name_mappings.get(report_slug, [])

        if not possible_names:
            self.logger.warning(f"No name mappings for slug '{report_slug}'")
            return None

        for report_name in possible_names:
            try:
                # XPath: Find <li> containing a <span> with SECOND <b> matching report name
                # Structure:
                # <span class="ng-star-inserted">
                #   <b>Costoverview</b> from <b>Cost overview report</b>
                # </span>
                notification_xpath = (
                    f"//li[contains(@class, 'kt-notifi-li')]"
                    f"[.//span[@class='ng-star-inserted']"
                    f"/b[2][translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz') = "
                    f"'{report_name.lower()}']]"
                )

                # Check if notification exists
                if not self.browser_wrapper.find_element_by_xpath(notification_xpath, timeout=3000):
                    self.logger.debug(f"Notification not found for text '{report_name}'")
                    continue

                self.logger.info(f"Found notification for '{report_slug}' using text '{report_name}'")

                # Validate timestamp
                if not self._is_notification_recent(notification_xpath, max_age_minutes):
                    self.logger.warning(f"Notification for '{report_slug}' is too old, skipping")
                    continue

                # Found and validated!
                return notification_xpath

            except Exception as e:
                self.logger.debug(f"Error searching for '{report_name}': {e}")
                continue

        self.logger.warning(f"No valid recent notification found for '{report_slug}'")
        return None

    def _click_apply_filters_if_needed(self, context: str) -> None:
        """Click Apply Filters button if auto-apply is not enabled.

        Args:
            context: Description of what filter was just applied (for logging)
        """
        auto_apply_checkbox_xpath = "//*[@id='wb-sheet-btn-apply']/div[2]/div//input[@id='autoApplyButton']"
        auto_apply_enabled = False

        try:
            # Check if auto apply checkbox exists and is checked
            if self.browser_wrapper.find_element_by_xpath(auto_apply_checkbox_xpath, timeout=3000):
                auto_apply_enabled = self.browser_wrapper.page.is_checked(f"xpath={auto_apply_checkbox_xpath}")
                if auto_apply_enabled:
                    self.logger.info(f"'Auto apply' is enabled - skipping Apply button after {context}")
                else:
                    self.logger.info(f"'Auto apply' is disabled - will click Apply Filters after {context}")
        except Exception as e:
            self.logger.debug(f"Could not verify 'Auto apply' status: {str(e)}, assuming manual apply is needed")

        # Only click Apply Filters if auto apply is not enabled
        if not auto_apply_enabled:
            apply_filters_xpath = "//*[@id='filter_apply_btn']"
            self.logger.info(f"Clicking Apply Filters after {context}...")
            self.browser_wrapper.click_element(apply_filters_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(30)  # Wait for filters to apply
            self.logger.info(f"Filters applied successfully after {context}")
        else:
            self.logger.info(f"Auto apply active - waiting for automatic filter application after {context}...")
            time.sleep(10)  # Shorter wait for auto-apply

    def _apply_report_filters(
        self, report_slug: str, account_number: Optional[str], invoice_month: str, report_config: dict
    ) -> None:
        """Apply account and invoice month filters to the current report.

        Uses dynamic XPath selectors to handle DOM repositioning.
        Raises exception if filter application fails - caller should abort report processing.
        """
        try:
            # Step 1: Select invoice month (single select)
            self.logger.info(f"Selecting invoice month '{invoice_month}' for {report_slug}...")
            self._select_invoice_month_dynamic(invoice_month)

            # Step 2: Click Apply Filters after invoice month selection
            self._click_apply_filters_if_needed(f"invoice month '{invoice_month}'")

            # Step 3: Select account (multi-select)
            # Note: We don't call Apply Filters after this because:
            # - If single account: already selected, no action needed
            # - If multiple accounts: table filter applies via "Ok" button
            if account_number:
                self.logger.info(f"Selecting account '{account_number}' for {report_slug}...")
                self._select_account_dynamic(account_number)

        except Exception as e:
            self.logger.error(f"Error applying filters for {report_slug}: {str(e)}")
            # Try to return to reports list on error
            try:
                self.logger.warning("Attempting to navigate back to reports list after filter error...")
                breadcrumb_xpath = "//*[@id='breadcrumb_item_1']"
                self.browser_wrapper.click_element(breadcrumb_xpath)
                self.browser_wrapper.wait_for_page_load()
                self.logger.info("Successfully navigated back to reports list")
            except Exception as e2:
                self.logger.warning(f"Could not navigate back to reports list: {str(e2)}")
            raise e

    def _select_month_from_dropdown(self, month_text: str) -> None:
        """Select a month from the invoice month dropdown (aff-ui-multiselect component)."""
        try:
            self.logger.info(f"Looking for month '{month_text}' in dropdown...")

            # XPath para encontrar el li que contiene el texto exacto del mes
            # Usamos contains() para ser robusto con espacios en blanco
            month_li_xpath = f"//li[contains(@class, 'list-item')][.//span[contains(@class, 'singleselect-dropdown-item') and contains(., '{month_text}')]]"

            # Esperar a que el elemento sea visible
            self.browser_wrapper.wait_for_element(month_li_xpath, timeout=10000)

            # Hacer click en el item
            self.browser_wrapper.click_element(month_li_xpath)

            self.logger.info(f"Month '{month_text}' selected from dropdown")

        except Exception as e:
            self.logger.error(f"Error selecting month from dropdown: {str(e)}")
            raise e

    def _select_account_from_dropdown(self, account_number: str) -> None:
        """Select an account from the account number dropdown (aff-ui-multiselect component).

        Steps:
        1. Uncheck "Select all" if it's checked
        2. Find and check the account checkbox
        """
        try:
            self.logger.info(f"Looking for account '{account_number}' in dropdown...")

            # Step 1: Desmarcar "Select all" si esta marcado
            select_all_checkbox_xpath = "//input[@class='select-all-input ng-star-inserted']"
            try:
                is_checked = self.browser_wrapper.page.is_checked(select_all_checkbox_xpath)
                if is_checked:
                    self.logger.info("'Select all' is checked, unchecking it...")
                    self.browser_wrapper.click_element(select_all_checkbox_xpath)
                    self.logger.info("'Select all' unchecked")
                else:
                    self.logger.info("'Select all' is already unchecked")
            except Exception as e:
                self.logger.warning(f"Could not verify/uncheck 'Select all': {str(e)}")

            # Step 2: Encontrar y hacer click en el checkbox de la cuenta especifica
            # XPath para encontrar el li que contiene el numero de cuenta
            account_li_xpath = (
                f"//li[contains(@class, 'list-item multiselect-setting')][.//label[contains(., '{account_number}')]]"
            )

            # Esperar a que el elemento sea visible
            self.browser_wrapper.wait_for_element(account_li_xpath, timeout=10000)

            # Encontrar el checkbox dentro del li
            account_checkbox_xpath = f"{account_li_xpath}//input[@type='checkbox']"
            self.browser_wrapper.click_element(account_checkbox_xpath)

            self.logger.info(f"Account '{account_number}' checkbox checked")

        except Exception as e:
            self.logger.error(f"Error selecting account from dropdown: {str(e)}")
            raise e

    def _select_invoice_month_dynamic(self, month_text: str) -> None:
        """Dynamically select invoice month from dropdown within the filter container.

        Searches within the filter section regardless of filter order, then selects the month.
        """
        try:
            self.logger.info(f"Dynamically selecting invoice month: '{month_text}'...")

            # Step 1: Find the main filter container
            filter_container_xpath = "/html/body/div[2]/app-base/section/block-ui/div/div/div/app-abi/app-ana-page/div[2]/div/div/app-workbook/div/app-wb-sheet/div/div/div/div[1]/div[2]/ngb-tabset/div/div/div/app-wb-sheet-filter/section/app-json-panel[1]/section/div/div[2]/div/div/div/div/section/section"
            self.browser_wrapper.wait_for_element(filter_container_xpath, timeout=10000)
            self.logger.debug("Filter container found")

            # Step 2: Find the invoice month filter section within the container
            # Search for the section that contains "Invoice month" in its header
            invoice_month_section_xpath = f"{filter_container_xpath}//section[.//span[@class='filter-title-ellipsis' and contains(., 'Invoice month')]]"
            self.browser_wrapper.wait_for_element(invoice_month_section_xpath, timeout=10000)
            self.logger.debug("Invoice month filter section found within container")

            # Step 3: Find and click the dropdown button within this section
            invoice_month_dropdown_xpath = f"{invoice_month_section_xpath}//div[@class='c-btn'][contains(@aria-expanded, 'false') or contains(@aria-expanded, 'true')]"
            self.browser_wrapper.wait_for_element(invoice_month_dropdown_xpath, timeout=10000)

            # Click to open the dropdown
            self.logger.info("Clicking invoice month dropdown button...")
            self.browser_wrapper.click_element(invoice_month_dropdown_xpath)
            self.logger.info("Invoice month dropdown opened")

            # Step 4: Use the search box to filter and select the month
            # The dropdown has a search input that filters the virtualized list
            self.logger.info(f"Looking for invoice month option: '{month_text}'...")

            # Find the search input within the dropdown (it appears after dropdown opens)
            # The search input has placeholder="Search" or aria-label="searchbox"
            search_input_xpath = f"{invoice_month_section_xpath}//input[@placeholder='Search' or @aria-label='searchbox']"

            try:
                self.browser_wrapper.wait_for_element(search_input_xpath, timeout=5000)
                self.logger.info(f"Search box found, typing '{month_text}'...")

                # Type the month text to filter the dropdown
                self.browser_wrapper.type_text(search_input_xpath, month_text)

                self.logger.info("Search filter applied, looking for filtered result...")
            except Exception as search_e:
                self.logger.warning(f"Search box not found or failed: {search_e}, trying direct selection...")

            # Now find and click the month option (should be visible after filtering)
            month_option_xpath = f"{invoice_month_section_xpath}//li[contains(@class, 'list-item')][.//span[contains(@class, 'singleselect-dropdown-item') and contains(., '{month_text}')]]"
            month_locator = self.browser_wrapper.page.locator(f"xpath={month_option_xpath}")

            # Wait for the filtered result to appear. If the timeout fires, the
            # month simply isn't in the dropdown — re-raise with that specific
            # cause so upstream logs say "month not available" instead of a raw
            # playwright timeout that hides the real reason.
            try:
                month_locator.wait_for(state="attached", timeout=10000)
            except Exception:
                raise RuntimeError(
                    f"Invoice month '{month_text}' not available in Bell dropdown — "
                    f"report likely not yet published for this billing cycle"
                )
            self.logger.info(f"Month '{month_text}' found in filtered results")

            # Click the month
            month_locator.scroll_into_view_if_needed()
            self.logger.info(f"Clicking invoice month option: '{month_text}'...")
            month_locator.click()

            self.logger.info(f"Invoice month '{month_text}' selected successfully")

        except Exception as e:
            self.logger.error(f"Error dynamically selecting invoice month '{month_text}': {str(e)}")
            raise e

    def _select_account_dynamic(self, account_number: str) -> None:
        """Dynamically select account within the filter container.

        Handles two scenarios:
        1. Single account: Already selected automatically, no action needed
        2. Multiple accounts: Uses table header filter (more reliable than dropdown)
        """
        try:
            self.logger.info(f"Dynamically selecting account: '{account_number}'...")

            # Step 1: Find the main filter container
            filter_container_xpath = "/html/body/div[2]/app-base/section/block-ui/div/div/div/app-abi/app-ana-page/div[2]/div/div/app-workbook/div/app-wb-sheet/div/div/div/div[1]/div[2]/ngb-tabset/div/div/div/app-wb-sheet-filter/section/app-json-panel[1]/section/div/div[2]/div/div/div/div/section/section"
            self.browser_wrapper.wait_for_element(filter_container_xpath, timeout=10000)
            self.logger.debug("Filter container found")

            # Step 2: Find the account filter section within the container
            account_section_xpath = f"{filter_container_xpath}//section[.//span[@class='filter-title-ellipsis' and contains(., 'Account number')]]"
            self.browser_wrapper.wait_for_element(account_section_xpath, timeout=10000)
            self.logger.debug("Account number filter section found within container")

            # Step 3: Find the dropdown button and get current state from the display text
            account_dropdown_xpath = f"{account_section_xpath}//div[@class='c-btn'][contains(@aria-expanded, 'false') or contains(@aria-expanded, 'true')]"
            self.browser_wrapper.wait_for_element(account_dropdown_xpath, timeout=10000)

            # Get the current selected state from the display text
            # This tells us if there are multiple accounts or just one
            display_text_xpath = f"{account_dropdown_xpath}//div[@class='c-list ng-star-inserted']//span"
            try:
                display_text = self.browser_wrapper.get_text(display_text_xpath)
                self.logger.info(f"Current dropdown display state: '{display_text}'")

                # If it shows a single account number, it means there's only one account
                # In that case, it's already selected and we don't need to do anything
                if display_text == account_number:
                    self.logger.info(
                        f"Account '{account_number}' is already the only account selected. No action needed."
                    )
                    return
            except Exception as e:
                self.logger.debug(f"Could not read display text: {str(e)}, continuing with selection...")

            # Multiple accounts detected - use table header filter directly
            # This is more reliable than the dropdown method
            self.logger.info("Multiple accounts detected, using table header filter...")
            self._select_account_via_table_filter(account_number)
            self.logger.info(f"Account '{account_number}' selected successfully via table filter")

        except Exception as e:
            self.logger.error(f"Account selection failed: {str(e)}")
            raise e

    def _select_account_via_table_filter(self, account_number: str) -> None:
        """Alternative method: Select account using the table header filter menu.

        This method is used as a fallback when the primary dropdown selection fails.
        It uses the datatable header's filter menu to search and select the account.

        Args:
            account_number: The account number to filter by
        """
        self.logger.info(f"Using table-based filter for account: '{account_number}'")

        # Step 1: Find the table header container
        # Using a more flexible selector that can match dynamic IDs
        table_header_xpath = "//datatable-header[@class='datatable-header ng-star-inserted']"
        self.browser_wrapper.wait_for_element(table_header_xpath, timeout=10000)
        self.logger.debug("Table header found")

        # Step 2: Find the Account number header cell
        account_header_xpath = f"{table_header_xpath}//datatable-header-cell[contains(@class, 'Accountnumber')]"
        self.browser_wrapper.wait_for_element(account_header_xpath, timeout=10000)
        self.logger.debug("Account number header cell found")

        # Step 3: Click the menu toggle button to open the filter menu
        menu_toggle_xpath = f"{account_header_xpath}//span[@role='button'][contains(@class, 'menu-toggle-btn')]"
        self.browser_wrapper.wait_for_element(menu_toggle_xpath, timeout=10000)
        self.logger.info("Clicking Account number filter menu button...")
        self.browser_wrapper.click_element(menu_toggle_xpath)
        self.logger.info("Filter menu opened")

        # Step 4: Locate the filter menu popup (usually appears as body > div with high z-index)
        filter_menu_xpath = "//div[contains(@class, 'table-column-menu') and contains(@class, 'ui-tieredmenu')]"
        self.browser_wrapper.wait_for_element(filter_menu_xpath, timeout=10000)
        self.logger.debug("Filter menu popup found")

        # Step 5: Uncheck "Select all" if it's checked
        select_all_checkbox_xpath = f"{filter_menu_xpath}//label[contains(., 'Select all')]//input[@type='checkbox']"
        try:
            # Check if checkbox is checked
            is_checked = self.browser_wrapper.page.is_checked(f"xpath={select_all_checkbox_xpath}")
            if is_checked:
                self.logger.info("'Select all' is checked, unchecking it...")
                self.browser_wrapper.click_element(select_all_checkbox_xpath)
                self.logger.info("'Select all' unchecked")
            else:
                self.logger.info("'Select all' is already unchecked")
        except Exception as e:
            self.logger.warning(f"Could not verify/uncheck 'Select all': {str(e)}")

        # Step 6: Type the account number in the search input
        search_input_xpath = f"{filter_menu_xpath}//input[@type='text'][@placeholder='Search...']"
        self.browser_wrapper.wait_for_element(search_input_xpath, timeout=10000)
        self.logger.info(f"Typing account number '{account_number}' in search box...")
        self.browser_wrapper.type_text(search_input_xpath, account_number)

        # Step 7: Wait 8 seconds for results to load
        self.logger.info("Waiting 8 seconds for search results to load...")
        time.sleep(8)

        # Step 8: Select the checkbox for the filtered account
        # The account number appears in a filter-item div with a label
        account_filter_item_xpath = f"{filter_menu_xpath}//div[@class='filter-item ng-star-inserted']//label[contains(@for, '{account_number}')]//input[@type='checkbox']"

        # Alternative: search by the label text instead of the 'for' attribute
        if not self.browser_wrapper.find_element_by_xpath(account_filter_item_xpath, timeout=3000):
            self.logger.debug("Trying alternative checkbox selector...")
            account_filter_item_xpath = f"{filter_menu_xpath}//div[@class='filter-item ng-star-inserted']//span[@class='filter-item-label' and contains(., '{account_number}')]/preceding-sibling::input[@type='checkbox']"

        self.browser_wrapper.wait_for_element(account_filter_item_xpath, timeout=10000)
        self.logger.info(f"Selecting checkbox for account '{account_number}'...")
        self.browser_wrapper.click_element(account_filter_item_xpath)
        self.logger.info(f"Account '{account_number}' checkbox selected")

        # Step 9: Click the "Ok" button to apply the filter
        ok_button_xpath = f"{filter_menu_xpath}//button[@class='btn btn-primary' and text()='Ok']"
        self.browser_wrapper.wait_for_element(ok_button_xpath, timeout=10000)
        self.logger.info("Clicking 'Ok' button to apply filter...")
        self.browser_wrapper.click_element(ok_button_xpath)
        self.logger.info("Filter applied successfully")

    def _export_report_to_excel(self, report_slug: str) -> None:
        """Export the current report to Excel."""
        try:
            # Step 1: Click Export button in toolbar
            export_xpath = "//*[@id='export-btn']"
            self.browser_wrapper.click_element(export_xpath)

            # Step 2: Click XLSX option in popover (search by icon class, avoids dynamic Angular IDs)
            xlsx_xpath = "//ngb-popover-window//div[.//i[contains(@class, 'line-XLSX')]]"
            self.browser_wrapper.click_element(xlsx_xpath)

            # Step 3: Click Export button in the confirmation dialog
            export_btn_xpath = "//*[@id='btn-bc-export']"
            self.browser_wrapper.click_element(export_btn_xpath)
            time.sleep(10)

            self.logger.info(f"Report '{report_slug}' exported to Excel")

        except Exception as e:
            self.logger.error(f"Error exporting report: {str(e)}")

    def _wait_for_and_download_reports(
        self, generated_reports: List[str], billing_cycle_file_map: dict
    ) -> List[FileDownloadInfo]:
        """Wait for reports to appear in alerts/notifications and download them by matching text content.

        Uses intelligent notification matching by report name (second <b> tag) and timestamp validation.
        Continues processing even if individual reports fail to download.

        Args:
            generated_reports: List of report slugs that were successfully generated
            billing_cycle_file_map: Mapping of report slug to BillingCycleFile object

        Returns:
            List of FileDownloadInfo objects for successfully downloaded files
        """
        downloaded_files = []

        try:
            # Step 1: Click on the alerts icon
            alerts_icon_xpath = "//li[contains(@class, 'kt-notification-content')]//span[@aria-label='Notification']"
            self.logger.info("Clicking alerts/notifications icon...")
            self.browser_wrapper.click_element(alerts_icon_xpath)
            self.logger.info("Alerts panel opened")

            # Step 2: Wait for notifications list to appear
            notifications_list_xpath = "//*[@id='m_quick_sidebar_notification-wrap']/div/div/ul"
            self.logger.info("Waiting for notifications list to appear...")
            self.browser_wrapper.wait_for_element(notifications_list_xpath, timeout=10000)
            self.logger.debug("Notifications list found")

            # Step 3: Count available notifications
            notification_items = self.browser_wrapper.page.locator("//li[contains(@class, 'kt-notifi-li')]")
            total_notifications = notification_items.count()
            self.logger.info(
                f"Generated reports: {len(generated_reports)}, Available notifications: {total_notifications}"
            )

            # Step 4: Download each report by identifying it by text content (NOT position)
            for report_slug in generated_reports:
                try:
                    self.logger.info(f"Searching for notification: '{report_slug}'...")

                    # Find notification by text content and validate timestamp (max 60 minutes old)
                    notification_xpath = self._find_notification_by_report_slug(report_slug, max_age_minutes=45)

                    if not notification_xpath:
                        self.logger.warning(f"Skipping '{report_slug}' - notification not found or too old")
                        continue

                    # Find download icon within this specific notification
                    download_icon_xpath = f"{notification_xpath}//em[contains(@class, 'line-download')]"

                    # Wait for download icon
                    self.browser_wrapper.wait_for_element(download_icon_xpath, timeout=10000)

                    # Download the file
                    self.logger.info(f"Downloading '{report_slug}'...")
                    downloaded_file_path = self.browser_wrapper.expect_download_and_click(
                        download_icon_xpath, timeout=30000, downloads_dir=self.job_downloads_dir
                    )

                    if downloaded_file_path:
                        actual_file_name = os.path.basename(downloaded_file_path)
                        self.logger.info(f"Downloaded: {actual_file_name}")

                        # Get corresponding BillingCycleFile
                        corresponding_bcf = billing_cycle_file_map.get(report_slug)

                        # Create FileDownloadInfo
                        file_download_info = FileDownloadInfo(
                            file_id=corresponding_bcf.id if corresponding_bcf else 0,
                            file_name=actual_file_name,
                            download_url="N/A",
                            file_path=downloaded_file_path,
                            billing_cycle_file=corresponding_bcf,
                        )
                        downloaded_files.append(file_download_info)

                        # Log mapping confirmation
                        if corresponding_bcf:
                            self.logger.info(
                                f"MAPPING: {actual_file_name} -> BillingCycleFile ID {corresponding_bcf.id} (Slug: '{report_slug}')"
                            )
                        else:
                            self.logger.warning(f"No BillingCycleFile mapping for '{report_slug}'")

                    else:
                        self.logger.error(f"Download failed for '{report_slug}' - no file path returned")

                    # Clear the notification to avoid duplicates in future runs
                    try:
                        clear_icon_xpath = f"{notification_xpath}//em[contains(@class, 'line-close')]"
                        self.browser_wrapper.click_element(clear_icon_xpath)
                        self.logger.info(f"Notification cleared for '{report_slug}'")
                    except Exception as clear_e:
                        self.logger.warning(f"Could not clear notification for '{report_slug}': {clear_e}")

                except Exception as e:
                    self.logger.error(f"Error downloading '{report_slug}': {str(e)}")
                    # CONTINUE - try next report
                    continue

            # Log final summary
            self.logger.info(f"\n{'='*80}")
            self.logger.info(f"DOWNLOAD SUMMARY")
            self.logger.info(f"{'='*80}")
            self.logger.info(f"Expected: {len(generated_reports)} | Downloaded: {len(downloaded_files)}")

            if len(downloaded_files) < len(generated_reports):
                failed_count = len(generated_reports) - len(downloaded_files)
                self.logger.warning(f"{failed_count} file(s) failed to download")

            for idx, file_info in enumerate(downloaded_files, 1):
                if file_info.billing_cycle_file:
                    bcf = file_info.billing_cycle_file
                    slug = bcf.carrier_report.slug if hasattr(bcf, "carrier_report") and bcf.carrier_report else "N/A"
                    self.logger.info(f"   [{idx}] {file_info.file_name} -> BCF ID {bcf.id} ('{slug}')")
                else:
                    self.logger.info(f"   [{idx}] {file_info.file_name} -> NO MAPPING")
            self.logger.info(f"{'='*80}\n")

        except Exception as e:
            self.logger.error(f"Error in _wait_for_and_download_reports: {str(e)}")

        return downloaded_files
