import calendar
import logging
import os
import time
import traceback
from datetime import datetime
from typing import Any, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    FileDownloadInfo,
    MonthlyReportsScraperStrategy,
)
from web_scrapers.domain.enums import ATTFileSlug

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class ATTMonthlyReportsScraperStrategy(MonthlyReportsScraperStrategy):
    """Scraper de reportes mensuales para AT&T con 6 reportes específicos."""

    # Configuración de reportes por slug
    REPORT_CONFIG = {
        ATTFileSlug.ALL_BILLING_CYCLE_CHARGES.value: {
            "tab": "charges_and_usage",
            "section": "Bill summary",
            "report_names": ["All charges"],
            "needs_date_filter": True,
        },
        ATTFileSlug.WIRELESS_CHARGES.value: {
            "tab": "charges_and_usage",
            "section": "Wireless number summary",
            "report_names": ["All wireless charges and usage (GB usage)", "All wireless charges and usage"],
            "needs_date_filter": True,
        },
        ATTFileSlug.USAGE_DETAILS.value: {
            "tab": "charges_and_usage",
            "section": "Billed usage",
            "report_names": ["All data export - usage details (GB usage)", "All data export - usage details"],
            "needs_date_filter": True,
        },
        # DESHABILITADO: Reporte monthly_charges no requerido actualmente
        # ATTFileSlug.MONTHLY_CHARGES.value: {
        #     "tab": "charges_and_usage",
        #     "section": "Bill summary",
        #     "report_names": ["Monthly charges"],
        #     "needs_date_filter": True,
        # },
        ATTFileSlug.DEVICE_INSTALLMENT.value: {
            "tab": "charges_and_usage",
            "section": "Equipment installment",
            "report_names": ["Device installment details"],
            "needs_date_filter": True,
        },
        ATTFileSlug.UPGRADE_AND_INVENTORY.value: {
            "tab": "inventory",
            "section": "Inventory",
            "report_names": ["Upgrade eligibility and inventory"],
            "needs_date_filter": False,
        },
    }

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.report_dictionary = {
            ATTFileSlug.WIRELESS_CHARGES.value: None,
            ATTFileSlug.USAGE_DETAILS.value: None,
            # ATTFileSlug.MONTHLY_CHARGES.value: None,  # DESHABILITADO
            ATTFileSlug.DEVICE_INSTALLMENT.value: None,
            ATTFileSlug.UPGRADE_AND_INVENTORY.value: None,
            ATTFileSlug.ALL_BILLING_CYCLE_CHARGES.value: None,
        }
        self._filters_configured = False

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Busca la sección de archivos mensuales en el portal de AT&T."""
        return self._find_files_section_with_retry(config, billing_cycle, max_retries=1)

    def _find_files_section_with_retry(
        self, config: ScraperConfig, billing_cycle: BillingCycle, max_retries: int = 1
    ) -> Optional[Any]:
        """Busca la sección de archivos con reintento automático en caso de error."""
        for attempt in range(max_retries + 1):
            try:
                self.logger.info(f"Searching for AT&T files section (attempt {attempt + 1}/{max_retries + 1})")

                # 1. Click en Billing tab
                billing_tab_xpath = "//*[@id='primaryNav']/li[3]/a"
                self.logger.info("Clicking Billing tab...")

                if self.browser_wrapper.is_element_visible(billing_tab_xpath, timeout=10000):
                    billing_text = self.browser_wrapper.get_text(billing_tab_xpath)
                    if billing_text and "BILLING" in billing_text.upper():
                        self.logger.info(f"Billing tab verified: '{billing_text}'")
                        self.browser_wrapper.click_element(billing_tab_xpath)
                        time.sleep(15)  # Esperar 15 segundos después de redirección
                    else:
                        self.logger.warning(f"Billing tab text mismatch: '{billing_text}'")
                        continue
                else:
                    self.logger.warning("Billing tab not found")
                    continue

                # 2. Click en Reports dropdown
                reports_dropdown_xpath = "//*[@id='navMenuGroupReports']"
                self.logger.info("Clicking Reports dropdown...")

                if self.browser_wrapper.is_element_visible(reports_dropdown_xpath, timeout=10000):
                    reports_text = self.browser_wrapper.get_text(reports_dropdown_xpath)
                    if reports_text and "Reports" in reports_text:
                        self.logger.info(f"Reports dropdown verified: '{reports_text}'")
                        self.browser_wrapper.click_element(reports_dropdown_xpath)
                        time.sleep(2)
                    else:
                        self.logger.warning(f"Reports dropdown text mismatch: '{reports_text}'")
                        continue
                else:
                    self.logger.warning("Reports dropdown not found")
                    continue

                # 3. Click en Detail option dentro del dropdown
                detail_option_xpath = "//*[@id='mainNavMenu']/ul[1]/li[4]/ul/li[3]/a"
                self.logger.info("Clicking Detail option...")

                if self.browser_wrapper.is_element_visible(detail_option_xpath, timeout=5000):
                    detail_text = self.browser_wrapper.get_text(detail_option_xpath)
                    if detail_text and "Detail" in detail_text:
                        self.logger.info(f"Detail option verified: '{detail_text}'")
                        self.browser_wrapper.click_element(detail_option_xpath)
                        time.sleep(10)  # Esperar 10 segundos
                    else:
                        self.logger.warning(f"Detail option text mismatch: '{detail_text}'")
                        continue
                else:
                    self.logger.warning("Detail option not found")
                    continue

                # 4. Verificar que estamos en la zona de reportes
                tabs_xpath = "//*[@id='thisForm']/div/div[1]/ul"
                if self.browser_wrapper.is_element_visible(tabs_xpath, timeout=10000):
                    tabs_text = self.browser_wrapper.get_text(tabs_xpath)
                    if tabs_text and ("Charges and usage" in tabs_text or "Unbilled usage" in tabs_text):
                        self.logger.info("Reports section found successfully")
                        return {"section": "monthly_reports", "ready_for_download": True}
                    else:
                        self.logger.warning(f"Tabs text does not match expected: '{tabs_text}'")
                        continue
                else:
                    self.logger.warning("Reports tabs not found")
                    continue

            except Exception as e:
                self.logger.error(f"Error on attempt {attempt + 1}: {str(e)}\n{traceback.format_exc()}")
                if attempt < max_retries:
                    continue

        self.logger.error("Could not find files section after all attempts")
        return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Descarga los 5 archivos mensuales de AT&T."""
        downloaded_files = []

        # Header del proceso de descarga
        self.logger.info("#" * 80)
        self.logger.info("# ATT MONTHLY REPORTS - STARTING DOWNLOAD PROCESS")
        self.logger.info("#" * 80)
        self.logger.info(f"Account Number: {billing_cycle.account.number}")
        self.logger.info(f"Billing Period: {billing_cycle.start_date} to {billing_cycle.end_date}")
        self.logger.info(f"Job Downloads Dir: {self.job_downloads_dir}")

        # Mapear BillingCycleFiles por slug del carrier_report para asociación exacta
        billing_cycle_file_map = {}
        self.logger.info("-" * 40)
        self.logger.info("BillingCycleFile Mappings:")
        if billing_cycle.billing_cycle_files:
            for bcf in billing_cycle.billing_cycle_files:
                if bcf.carrier_report and bcf.carrier_report.slug:
                    slug = bcf.carrier_report.slug
                    billing_cycle_file_map[slug] = bcf
                    self.logger.info(f"  - Slug '{slug}' -> BillingCycleFile ID {bcf.id}")
        else:
            self.logger.warning("  No BillingCycleFiles provided!")
        self.logger.info("-" * 40)

        try:
            # Orden de descarga: primero todos los de "Charges and usage", luego "Inventory"
            charges_reports = [
                ATTFileSlug.ALL_BILLING_CYCLE_CHARGES.value,
                ATTFileSlug.WIRELESS_CHARGES.value,
                ATTFileSlug.USAGE_DETAILS.value,
                # ATTFileSlug.MONTHLY_CHARGES.value,  # DESHABILITADO
                ATTFileSlug.DEVICE_INSTALLMENT.value,
            ]
            inventory_reports = [ATTFileSlug.UPGRADE_AND_INVENTORY.value]

            # 1. Procesar reportes de "Charges and usage"
            self.logger.info("Processing Charges and usage reports...")
            self._click_tab("Charges and usage")
            time.sleep(3)

            # CRÍTICO: El filtro de cuenta DEBE configurarse correctamente
            # Si falla, no podemos continuar ya que descargaríamos archivos de otra cuenta
            if not self._ensure_filters_configured(billing_cycle, needs_date_filter=True):
                error_msg = (
                    f"FATAL: Failed to configure filters for account {billing_cycle.account.number}. "
                    "Check previous logs for details on which filter (account or date) failed. "
                    "Cannot proceed with downloads."
                )
                self.logger.error(error_msg)
                self._reset_to_main_screen()
                raise RuntimeError(error_msg)

            for slug in charges_reports:
                report_config = self.REPORT_CONFIG.get(slug)
                if report_config:
                    file_info = self._download_single_report(
                        slug, report_config, billing_cycle_file_map, billing_cycle
                    )
                    if file_info:
                        downloaded_files.append(file_info)

            # 2. Procesar reportes de "Inventory"
            self.logger.info("Processing Inventory reports...")
            self._click_tab("Inventory")
            time.sleep(5)

            # CRÍTICO: El filtro de cuenta DEBE configurarse correctamente para Inventory también
            if not self._ensure_filters_configured(billing_cycle, needs_date_filter=False):
                error_msg = (
                    f"FATAL: Failed to configure account filter for Inventory tab (account {billing_cycle.account.number}). "
                    "Cannot proceed with Inventory downloads."
                )
                self.logger.error(error_msg)
                self._reset_to_main_screen()
                raise RuntimeError(error_msg)

            for slug in inventory_reports:
                report_config = self.REPORT_CONFIG.get(slug)
                if report_config:
                    file_info = self._download_single_report(
                        slug, report_config, billing_cycle_file_map, billing_cycle
                    )
                    if file_info:
                        downloaded_files.append(file_info)

            # 3. Reset a pantalla principal
            self._reset_to_main_screen()

            # Resumen final del proceso
            self.logger.info("#" * 80)
            self.logger.info("# ATT MONTHLY REPORTS - DOWNLOAD PROCESS COMPLETED")
            self.logger.info("#" * 80)
            self.logger.info(f"Total files downloaded: {len(downloaded_files)}/5")
            self.logger.info("Downloaded files:")
            for idx, file_info in enumerate(downloaded_files, 1):
                self.logger.info(f"  {idx}. {file_info.file_name}")
                self.logger.info(f"     -> BillingCycleFile ID: {file_info.billing_cycle_file.id if file_info.billing_cycle_file else 'N/A'}")

            # Verificar si faltaron reportes
            expected_slugs = {
                ATTFileSlug.ALL_BILLING_CYCLE_CHARGES.value,
                ATTFileSlug.WIRELESS_CHARGES.value,
                ATTFileSlug.USAGE_DETAILS.value,
                ATTFileSlug.DEVICE_INSTALLMENT.value,
                ATTFileSlug.UPGRADE_AND_INVENTORY.value,
            }
            downloaded_slugs = set()
            for file_info in downloaded_files:
                if file_info.billing_cycle_file and file_info.billing_cycle_file.carrier_report:
                    downloaded_slugs.add(file_info.billing_cycle_file.carrier_report.slug)

            missing_slugs = expected_slugs - downloaded_slugs
            if missing_slugs:
                self.logger.warning(f"Missing reports: {missing_slugs}")
            else:
                self.logger.info("All expected reports downloaded successfully!")
            self.logger.info("#" * 80)

            return downloaded_files

        except RuntimeError:
            # Re-lanzar errores críticos de filtro de cuenta sin capturarlos
            raise
        except Exception as e:
            self.logger.error(f"[EXCEPTION] Error during file download: {str(e)}")
            self.logger.error(traceback.format_exc())
            try:
                self._reset_to_main_screen()
            except:
                pass
            raise

    def _ensure_filters_configured(self, billing_cycle: BillingCycle, needs_date_filter: bool = True) -> bool:
        """Verifica que los filtros estén configurados correctamente, si no, los configura.

        Returns:
            True if filters are configured successfully, False otherwise.
        """
        self.logger.info("[FILTERS] Verifying filter configuration...")
        self.logger.info(f"[FILTERS] Required account: {billing_cycle.account.number}")
        if needs_date_filter:
            self.logger.info(f"[FILTERS] Required date: {billing_cycle.end_date.strftime('%B %Y')}")

        # Verificar filtro de cuenta
        if not self._is_account_filter_configured(billing_cycle):
            self.logger.info("[FILTERS] Account filter NOT configured, configuring now...")
            if not self._configure_account_filter(billing_cycle):
                self.logger.error("[FILTERS] FAILED to configure account filter")
                return False
            # Verify the filter was actually applied
            if not self._is_account_filter_configured(billing_cycle):
                self.logger.error("[FILTERS] Account filter configuration FAILED - filter not applied correctly after configuration")
                return False
            self.logger.info("[FILTERS] Account filter configured successfully")
        else:
            self.logger.info("[FILTERS] Account filter already configured correctly")

        # Verificar filtro de fecha (solo si es necesario)
        if needs_date_filter:
            if not self._is_date_filter_configured(billing_cycle):
                self.logger.info("[FILTERS] Date filter NOT configured, configuring now...")
                if not self._configure_date_range(billing_cycle):
                    self.logger.error("[FILTERS] FAILED to configure date range filter")
                    return False
                # Trust that select_dropdown_by_value worked - the SELECT may not be accessible after Apply
                self.logger.info("[FILTERS] Date filter configured successfully (trusting select_dropdown_by_value)")
            else:
                self.logger.info("[FILTERS] Date filter already configured correctly")

        self.logger.info("[FILTERS] All required filters verified OK")
        return True

    def _is_account_filter_configured(self, billing_cycle: BillingCycle) -> bool:
        """Verifica si el filtro de cuenta está configurado correctamente."""
        try:
            account_number = billing_cycle.account.number
            view_by_xpath = "//*[@id='thisForm']/div/div[2]/div[1]/div[1]"

            if self.browser_wrapper.is_element_visible(view_by_xpath, timeout=5000):
                current_text = self.browser_wrapper.get_text(view_by_xpath)
                self.logger.info(f"[FILTERS] Current account filter value: '{current_text}'")
                self.logger.info(f"[FILTERS] Expected account number: '{account_number}'")
                if current_text and account_number in current_text:
                    self.logger.info(f"[FILTERS] Account filter MATCH: '{account_number}' found in '{current_text}'")
                    return True
                else:
                    self.logger.warning(f"[FILTERS] Account filter MISMATCH: '{account_number}' NOT in '{current_text}'")

            return False
        except Exception as e:
            self.logger.error(f"[FILTERS] Error checking account filter: {str(e)}")
            return False

    def _is_date_filter_configured(self, billing_cycle: BillingCycle) -> bool:
        """Verifica si el filtro de fecha está configurado correctamente.

        Intenta obtener la fecha seleccionada de múltiples fuentes:
        1. SELECT #bmtype_data (cuando el dropdown está abierto)
        2. Elemento visual que muestra la fecha seleccionada
        """
        try:
            end_date = billing_cycle.end_date
            month_name = calendar.month_name[end_date.month]
            year = end_date.year
            expected_text = f"{month_name} {year}"
            expected_text_bills = f"{month_name} {year} bills"
            # AT&T value pattern: cYYYYMM01 (e.g., c20251001 for October 2025)
            expected_value = f"c{year}{end_date.month:02d}01"

            # Intentar múltiples formas de obtener la fecha seleccionada
            result = self.browser_wrapper.page.evaluate(f"""
                () => {{
                    // 1. Intentar SELECT #bmtype_data
                    const select = document.querySelector('#bmtype_data');
                    if (select && select.selectedIndex >= 0 && select.options[select.selectedIndex].value) {{
                        return {{
                            text: select.options[select.selectedIndex].text,
                            value: select.options[select.selectedIndex].value,
                            source: 'bmtype_data'
                        }};
                    }}

                    // 2. Buscar texto visual que contenga el mes/año esperado
                    const dateArea = document.querySelector('#thisForm .filter-area, #thisForm [class*="date"], #thisForm [class*="filter"]');
                    if (dateArea && dateArea.textContent.includes('{month_name} {year}')) {{
                        return {{
                            text: '{month_name} {year} bills',
                            value: '{expected_value}',
                            source: 'visual_text'
                        }};
                    }}

                    // 3. Buscar cualquier elemento visible con el texto del mes/año
                    const allElements = document.querySelectorAll('*');
                    for (const el of allElements) {{
                        if (el.offsetParent !== null && el.textContent &&
                            el.textContent.includes('{month_name} {year}') &&
                            el.children.length === 0) {{
                            return {{
                                text: el.textContent.trim(),
                                value: '',
                                source: 'any_visible'
                            }};
                        }}
                    }}

                    return {{ text: '', value: '', source: 'none' }};
                }}
            """)

            selected_text = result.get('text', '')
            selected_value = result.get('value', '')
            source = result.get('source', 'none')

            self.logger.info(f"[FILTERS] Current selected date: '{selected_text}' (value={selected_value}, source={source})")
            self.logger.info(f"[FILTERS] Expected date: '{expected_text_bills}' (value={expected_value})")

            if selected_value == expected_value:
                self.logger.info(f"[FILTERS] Date filter MATCH by value: '{expected_value}'")
                return True
            elif selected_text and (expected_text in selected_text or expected_text_bills in selected_text):
                self.logger.info(f"[FILTERS] Date filter MATCH by text: '{expected_text}' found in '{selected_text}'")
                return True
            else:
                self.logger.warning(f"[FILTERS] Date filter MISMATCH: Expected value '{expected_value}' or text '{expected_text}', got value='{selected_value}', text='{selected_text}'")

            return False
        except Exception as e:
            self.logger.error(f"[FILTERS] Error checking date filter: {str(e)}")
            return False

    def _click_tab(self, tab_name: str):
        """Hace click en una pestaña específica del listado de reportes."""
        try:
            tabs_xpath = "//*[@id='thisForm']/div/div[1]/ul"
            self.logger.info(f"Clicking tab: {tab_name}")

            # Buscar el tab por texto usando xpath con contains
            if tab_name == "Charges and usage":
                tab_xpath = f"{tabs_xpath}/li[1]/a"
            elif tab_name == "Inventory":
                tab_xpath = f"{tabs_xpath}/li[3]/a"
            else:
                # Fallback genérico
                tab_xpath = f"{tabs_xpath}//a[contains(., '{tab_name}')]"

            if self.browser_wrapper.is_element_visible(tab_xpath, timeout=5000):
                self.browser_wrapper.click_element(tab_xpath)
                time.sleep(3)
                self.logger.info(f"Tab '{tab_name}' clicked successfully")
            else:
                self.logger.warning(f"Tab '{tab_name}' not found")

        except Exception as e:
            self.logger.error(f"Error clicking tab '{tab_name}': {str(e)}\n{traceback.format_exc()}")

    def _download_single_report(
        self, slug: str, report_config: dict, billing_cycle_file_map: dict, billing_cycle: BillingCycle
    ) -> Optional[FileDownloadInfo]:
        """Descarga un reporte individual y retorna FileDownloadInfo."""
        try:
            report_names = report_config["report_names"]
            section_name = report_config["section"]
            needs_date_filter = report_config.get("needs_date_filter", True)

            # Header visual para identificar cada reporte en los logs
            self.logger.info("=" * 70)
            self.logger.info(f"DOWNLOADING REPORT: {slug}")
            self.logger.info(f"  Section: {section_name}")
            self.logger.info(f"  Expected names: {report_names}")
            self.logger.info(f"  Account: {billing_cycle.account.number}")
            self.logger.info(f"  Period: {billing_cycle.end_date.strftime('%Y-%m')}")
            self.logger.info("=" * 70)

            # 1. Buscar y hacer click en el reporte dentro del accordion
            self.logger.info("[Step 1/7] Searching for report button in accordion...")
            if not self._find_and_click_report(section_name, report_names):
                self.logger.error(f"[FAILED] Report button not found for '{slug}' in section '{section_name}'")
                self.logger.error(f"[FAILED] Expected exact names: {report_names}")
                return None

            # 2. Esperar a que cargue el reporte
            self.logger.info("[Step 2/7] Waiting 30 seconds for report data to load...")
            time.sleep(30)

            # 3. Click en Export button
            self.logger.info("[Step 3/7] Looking for Export button...")
            export_button_xpath = "//*[@id='export']"
            if not self.browser_wrapper.is_element_visible(export_button_xpath, timeout=10000):
                self.logger.error(f"[FAILED] Export button not found for '{slug}'")
                self._go_back_to_reports()
                self._ensure_filters_configured(billing_cycle, needs_date_filter=needs_date_filter)
                return None

            self.logger.info("[Step 3/7] Clicking Export button...")
            self.browser_wrapper.click_element(export_button_xpath)
            time.sleep(2)

            # 4. Seleccionar CSV en el modal
            self.logger.info("[Step 4/7] Selecting CSV format in export modal...")
            csv_option_xpath = "//*[@id='radCsvLabel']"
            if self.browser_wrapper.is_element_visible(csv_option_xpath, timeout=5000):
                self.browser_wrapper.click_element(csv_option_xpath)
                self.logger.info("[Step 4/7] CSV option selected")
                time.sleep(1)
            else:
                self.logger.error(f"[FAILED] CSV option not found in export modal for '{slug}'")
                self._close_export_modal_if_open()
                self._go_back_to_reports()
                self._ensure_filters_configured(billing_cycle, needs_date_filter=needs_date_filter)
                return None

            # 5. Click en OK y esperar descarga
            self.logger.info("[Step 5/7] Initiating download (timeout: 120s)...")
            ok_button_xpath = "//*[@id='hrefOK']"

            file_path = self.browser_wrapper.expect_download_and_click(
                ok_button_xpath, timeout=120000, downloads_dir=self.job_downloads_dir
            )

            if file_path:
                original_filename = os.path.basename(file_path)
                self.logger.info(f"[Step 5/7] Download complete: {original_filename}")

                # 6. Renombrar archivo para identificarlo por slug
                self.logger.info("[Step 6/7] Renaming file with slug identifier...")
                file_path, actual_filename = self._rename_file_with_slug(file_path, slug, billing_cycle)
                self.logger.info(f"[Step 6/7] Renamed: {original_filename} -> {actual_filename}")

                corresponding_bcf = billing_cycle_file_map.get(slug)

                file_download_info = FileDownloadInfo(
                    file_id=corresponding_bcf.id if corresponding_bcf else 0,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=file_path,
                    billing_cycle_file=corresponding_bcf,
                )

                # Log de mapeo
                if corresponding_bcf:
                    self.logger.info(f"[Step 6/7] MAPPING: File '{actual_filename}' -> BillingCycleFile ID {corresponding_bcf.id}")
                else:
                    self.logger.warning(f"[Step 6/7] WARNING: No BillingCycleFile mapping found for slug '{slug}'")

                # 7. Regresar a la sección de reportes
                self.logger.info("[Step 7/7] Returning to reports section...")
                self._go_back_to_reports()
                self._ensure_filters_configured(billing_cycle, needs_date_filter=needs_date_filter)

                # Resumen de éxito
                self.logger.info("-" * 70)
                self.logger.info(f"[SUCCESS] Report '{slug}' downloaded successfully")
                self.logger.info(f"  File: {actual_filename}")
                self.logger.info(f"  Path: {file_path}")
                self.logger.info(f"  BillingCycleFile ID: {corresponding_bcf.id if corresponding_bcf else 'N/A'}")
                self.logger.info("-" * 70)

                return file_download_info
            else:
                self.logger.error(f"[FAILED] Download failed for '{slug}' - no file received")
                self._go_back_to_reports()
                self._ensure_filters_configured(billing_cycle, needs_date_filter=needs_date_filter)
                return None

        except Exception as e:
            self.logger.error(f"[EXCEPTION] Error downloading report '{slug}': {str(e)}")
            self.logger.error(traceback.format_exc())
            try:
                self._go_back_to_reports()
                self._ensure_filters_configured(
                    billing_cycle, needs_date_filter=report_config.get("needs_date_filter", True)
                )
            except:
                pass
            return None

    def _find_and_click_report(self, section_name: str, report_names: List[str]) -> bool:
        """Busca y hace click en un reporte dentro del accordion.

        IMPORTANTE: Usa match EXACTO para evitar confusión entre reportes con nombres similares.
        """
        try:
            accordion_xpath = "//*[@id='accordion']"

            if not self.browser_wrapper.is_element_visible(accordion_xpath, timeout=10000):
                self.logger.error("Accordion not found")
                return False

            # Usar page directamente para buscar elementos
            page = self.browser_wrapper.page

            # Buscar todos los paneles del accordion
            panels = page.query_selector_all(f"xpath={accordion_xpath}//div[contains(@class, 'panel-reports')]")

            # Normalizar nombres esperados para comparación exacta
            normalized_report_names = [name.strip().lower() for name in report_names]

            self.logger.info(f"Searching for report in section '{section_name}' with EXACT names: {report_names}")

            for panel in panels:
                # Obtener el título del panel
                try:
                    panel_title_element = panel.query_selector(".panel-title span")
                    if panel_title_element:
                        panel_title = panel_title_element.inner_text().strip()

                        if section_name.lower() in panel_title.lower():
                            self.logger.info(f"Found section: {panel_title}")

                            # Buscar los reportes dentro de este panel
                            report_buttons = panel.query_selector_all("button[name='ViewReport']")

                            # Log todos los reportes disponibles en esta sección para debug
                            available_reports = []
                            for btn in report_buttons:
                                btn_text = btn.inner_text().strip()
                                available_reports.append(btn_text)
                            self.logger.info(f"Available reports in section: {available_reports}")

                            for button in report_buttons:
                                button_text = button.inner_text().strip()
                                normalized_button_text = button_text.lower()

                                # MATCH EXACTO: el texto del botón debe ser exactamente igual a uno de los nombres esperados
                                if normalized_button_text in normalized_report_names:
                                    self.logger.info(f"EXACT MATCH found: '{button_text}' matches expected name")
                                    button.click()
                                    time.sleep(3)
                                    return True
                                else:
                                    self.logger.debug(f"No match: '{button_text}' != {report_names}")

                except Exception as inner_e:
                    self.logger.debug(f"Error checking panel: {str(inner_e)}")
                    continue

            self.logger.warning(f"Report not found in section '{section_name}' with EXACT names: {report_names}")
            return False

        except Exception as e:
            self.logger.error(f"Error finding report: {str(e)}\n{traceback.format_exc()}")
            return False

    def _close_export_modal_if_open(self):
        """Cierra el modal de export si está abierto."""
        try:
            # Buscar botón de cerrar/cancelar en el modal de export
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
                # Intentar presionar Escape para cerrar el modal
                self.logger.info("Attempting to close modal with Escape key...")
                self.browser_wrapper.page.keyboard.press("Escape")
                time.sleep(1)

        except Exception as e:
            self.logger.debug(f"Error closing export modal: {str(e)}")

    def _go_back_to_reports(self):
        """Regresa a la sección de reportes."""
        try:
            # Primero intentar cerrar cualquier modal abierto
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
            self.logger.error(f"Error going back to reports: {str(e)}\n{traceback.format_exc()}")

    def _configure_account_filter(self, billing_cycle: BillingCycle) -> bool:
        """Configura el filtro de cuenta basado en el billing cycle.

        Returns:
            True if account filter was configured successfully, False otherwise.
        """
        try:
            account_number = billing_cycle.account.number
            self.logger.info("[ACCOUNT CONFIG] Starting account filter configuration")
            self.logger.info(f"[ACCOUNT CONFIG] Target account: {account_number}")

            # 1. Click en View by dropdown
            view_by_xpath = "//*[@id='thisForm']/div/div[2]/div[1]/div[1]"
            self.logger.info("[ACCOUNT CONFIG] Step 1/5: Clicking View by dropdown...")
            if not self.browser_wrapper.is_element_visible(view_by_xpath, timeout=5000):
                self.logger.error("[ACCOUNT CONFIG] FAILED: View by dropdown not found")
                return False
            self.browser_wrapper.click_element(view_by_xpath)
            time.sleep(2)

            # 2. Seleccionar opción "Accounts"
            accounts_option_xpath = "//*[@id='LevelDataDropdownList_multipleaccounts']"
            self.logger.info("[ACCOUNT CONFIG] Step 2/5: Selecting 'Accounts' option...")
            if not self.browser_wrapper.is_element_visible(accounts_option_xpath, timeout=5000):
                self.logger.error("[ACCOUNT CONFIG] FAILED: 'Accounts' option not found in dropdown")
                return False
            self.browser_wrapper.click_element(accounts_option_xpath)
            time.sleep(2)

            # 3. Escribir número de cuenta en el input
            account_input_xpath = "//*[@id='scopeExpandedAccountMenu']/div[1]/div/div[2]/input"
            self.logger.info(f"[ACCOUNT CONFIG] Step 3/5: Entering account number: {account_number}")
            if not self.browser_wrapper.is_element_visible(account_input_xpath, timeout=5000):
                self.logger.error("[ACCOUNT CONFIG] FAILED: Account input field not found")
                return False
            self.browser_wrapper.clear_and_type(account_input_xpath, account_number)
            self.logger.info("[ACCOUNT CONFIG] Waiting 3s for account list to update...")
            time.sleep(3)

            # 4. Buscar y logear las opciones disponibles
            self.logger.info("[ACCOUNT CONFIG] Step 4/5: Looking for account in results list...")
            page = self.browser_wrapper.page
            options_list_xpath = "//*[@id='scopeExpandedAccountMenu']/div[3]/ul/li"
            options = page.query_selector_all(f"xpath={options_list_xpath}")

            # Logear todas las opciones encontradas
            available_accounts = []
            for opt in options:
                opt_text = opt.inner_text().strip() if opt else ""
                available_accounts.append(opt_text)
            self.logger.info(f"[ACCOUNT CONFIG] Available accounts in list ({len(available_accounts)}): {available_accounts}")

            first_option_xpath = "//*[@id='scopeExpandedAccountMenu']/div[3]/ul/li[1]"
            if self.browser_wrapper.is_element_visible(first_option_xpath, timeout=5000):
                first_option_text = self.browser_wrapper.get_text(first_option_xpath)
                self.logger.info(f"[ACCOUNT CONFIG] First option text: '{first_option_text}'")

                # Verificar que la primera opción contiene el número de cuenta esperado
                if account_number not in (first_option_text or ""):
                    self.logger.error(f"[ACCOUNT CONFIG] FAILED: First option '{first_option_text}' does not contain expected account '{account_number}'")
                    self.logger.error(f"[ACCOUNT CONFIG] Available options were: {available_accounts}")
                    return False

                self.logger.info("[ACCOUNT CONFIG] Selecting first account option...")
                checkbox_xpath = f"{first_option_xpath}/input"
                if self.browser_wrapper.is_element_visible(checkbox_xpath, timeout=2000):
                    self.browser_wrapper.click_element(checkbox_xpath)
                else:
                    self.browser_wrapper.click_element(first_option_xpath)
                time.sleep(1)
            else:
                self.logger.error(f"[ACCOUNT CONFIG] FAILED: No account options found in list for account: {account_number}")
                self.logger.error(f"[ACCOUNT CONFIG] Available options were: {available_accounts}")
                return False

            # 5. Click en OK button
            ok_button_xpath = "//*[@id='scopeExpandedAccountMenu']/div[4]/button"
            self.logger.info("[ACCOUNT CONFIG] Step 5/5: Clicking OK button to apply...")
            if not self.browser_wrapper.is_element_visible(ok_button_xpath, timeout=5000):
                self.logger.error("[ACCOUNT CONFIG] FAILED: OK button not found")
                return False
            self.browser_wrapper.click_element(ok_button_xpath)
            self.logger.info("[ACCOUNT CONFIG] Waiting 3s for filter to apply...")
            time.sleep(3)

            self.logger.info(f"[ACCOUNT CONFIG] SUCCESS: Account filter configured for {account_number}")
            return True

        except Exception as e:
            self.logger.error(f"[ACCOUNT CONFIG] EXCEPTION: {str(e)}")
            self.logger.error(traceback.format_exc())
            return False

    def _configure_date_range(self, billing_cycle: BillingCycle) -> bool:
        """Configura el rango de fechas basado en el billing cycle.

        Flow:
        1. Click en Date Range dropdown button para abrir menú
        2. Iterate options in bmtype_data to find one matching year/month pattern
        3. Click en btnApply para confirmar

        AT&T value pattern: cYYYYMMDD - we search for options starting with cYYYYMM

        Returns:
            True if date range was configured successfully, False otherwise.
        """
        try:
            end_date = billing_cycle.end_date
            month_name = calendar.month_name[end_date.month]
            year = end_date.year
            # Pattern to search: cYYYYMM (without day)
            target_pattern = f"c{year}{end_date.month:02d}"
            target_text = f"{month_name} {year}"

            self.logger.info("[DATE CONFIG] Starting date range configuration")
            self.logger.info(f"[DATE CONFIG] Target: {target_text}")
            self.logger.info(f"[DATE CONFIG] Searching for options starting with: {target_pattern}")

            # 1. Click en Date Range dropdown button para abrir menú
            date_range_xpath = "//*[@id='thisForm']/div/div[2]/div[1]/div[2]"
            self.logger.info("[DATE CONFIG] Step 1/3: Opening Date Range dropdown...")
            if not self.browser_wrapper.is_element_visible(date_range_xpath, timeout=5000):
                self.logger.error("[DATE CONFIG] FAILED: Date Range dropdown not found")
                return False
            self.browser_wrapper.click_element(date_range_xpath)
            time.sleep(2)

            # 2. Find matching option by iterating through all options
            bmtype_select_xpath = "//*[@id='bmtype_data']"
            matching_value = self._find_matching_date_option(bmtype_select_xpath, target_pattern)

            if not matching_value:
                self.logger.error(f"[DATE CONFIG] FAILED: No option found matching pattern: {target_pattern}")
                return False

            self.logger.info(f"[DATE CONFIG] Step 2/3: Found matching option: {matching_value}")
            self.browser_wrapper.select_dropdown_by_value(bmtype_select_xpath, matching_value)
            time.sleep(1)

            # 3. Click en Apply button para aplicar los cambios
            apply_button_xpath = "//*[@id='btnApply']"
            self.logger.info("[DATE CONFIG] Step 3/3: Clicking Apply button...")
            if self.browser_wrapper.is_element_visible(apply_button_xpath, timeout=5000):
                self.browser_wrapper.click_element(apply_button_xpath)
                self.logger.info("[DATE CONFIG] Waiting 5s for changes to apply...")
                time.sleep(5)
            else:
                self.logger.error("[DATE CONFIG] FAILED: Apply button not found")
                return False

            self.logger.info(f"[DATE CONFIG] SUCCESS: Date range configured for {target_text}")
            return True

        except Exception as e:
            self.logger.error(f"[DATE CONFIG] EXCEPTION: {str(e)}")
            self.logger.error(traceback.format_exc())
            return False

    def _find_matching_date_option(self, select_xpath: str, pattern: str) -> Optional[str]:
        """
        Iterates through SELECT options to find one matching the year/month pattern.

        Args:
            select_xpath: XPath of the SELECT element
            pattern: Pattern to match (e.g., 'c202510' for October 2025)

        Returns:
            The value of the matching option, or None if not found.
        """
        try:
            page = self.browser_wrapper.page

            # Get all options from the SELECT
            options = page.query_selector_all(f"xpath={select_xpath}//option")
            self.logger.info(f"[DATE CONFIG] Found {len(options)} options in dropdown")

            for option in options:
                value = option.get_attribute("value")
                text = option.inner_text().strip() if option else ""

                if value and value.startswith(pattern):
                    self.logger.info(f"[DATE CONFIG] Match found: value='{value}', text='{text}'")
                    return value

            # Log available options for debugging
            self.logger.warning(f"[DATE CONFIG] No match found for pattern '{pattern}'. Available options:")
            for option in options[:10]:  # Log first 10 options
                value = option.get_attribute("value")
                text = option.inner_text().strip() if option else ""
                self.logger.warning(f"[DATE CONFIG]   - value='{value}', text='{text}'")

            return None

        except Exception as e:
            self.logger.error(f"[DATE CONFIG] Error finding matching date option: {str(e)}")
            return None

    def _reset_to_main_screen(self):
        """Reset a la pantalla inicial de AT&T."""
        try:
            self.logger.info("Resetting to AT&T initial screen...")
            self.browser_wrapper.goto("https://www.wireless.att.com/premiercare/")
            time.sleep(10)
            self.logger.info("Reset to AT&T completed")
        except Exception as e:
            self.logger.error(f"Error in AT&T reset: {str(e)}\n{traceback.format_exc()}")

    def _rename_file_with_slug(
        self, file_path: str, slug: str, billing_cycle: BillingCycle
    ) -> tuple[str, str]:
        """Renombra el archivo descargado para incluir el slug y periodo de facturación.

        Args:
            file_path: Ruta original del archivo descargado.
            slug: Identificador del tipo de reporte (ej: 'wireless_charges').
            billing_cycle: Ciclo de facturación para obtener el periodo.

        Returns:
            Tuple con (nueva_ruta, nuevo_nombre).
        """
        try:
            original_filename = os.path.basename(file_path)
            file_dir = os.path.dirname(file_path)

            # Obtener extensión del archivo original
            _, extension = os.path.splitext(original_filename)

            # Crear nombre descriptivo: ATT_{slug}_{YYYY-MM}.csv
            end_date = billing_cycle.end_date
            period = f"{end_date.year}-{end_date.month:02d}"
            new_filename = f"ATT_{slug}_{period}{extension}"

            new_file_path = os.path.join(file_dir, new_filename)

            # Si ya existe un archivo con ese nombre, agregar contador
            counter = 1
            while os.path.exists(new_file_path):
                new_filename = f"ATT_{slug}_{period}_{counter}{extension}"
                new_file_path = os.path.join(file_dir, new_filename)
                counter += 1

            # Renombrar el archivo
            os.rename(file_path, new_file_path)
            self.logger.info(f"Renamed: {original_filename} -> {new_filename}")

            return new_file_path, new_filename

        except Exception as e:
            self.logger.error(f"Error renaming file: {str(e)}\n{traceback.format_exc()}")
            # Si falla el renombrado, retornar los valores originales
            return file_path, os.path.basename(file_path)


# =============================================================================
# LEGACY CLASS - DEPRECATED
# =============================================================================


class ATTMonthlyReportsScraperStrategyLegacy(MonthlyReportsScraperStrategy):
    """LEGACY: Scraper de reportes mensuales para AT&T - DEPRECATED.

    Esta clase está deprecada. Usar ATTMonthlyReportsScraperStrategy en su lugar.
    Se mantiene para compatibilidad con implementaciones anteriores.
    """

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.report_dictionary = {
            "wireless_charges": None,
            "usage_details": None,
            "monthly_charges": None,
            "device_installment": None,
            "upgrade_and_inventory": None,
        }

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Busca la sección de archivos mensuales en el portal de AT&T."""
        return self._find_files_section_with_retry(config, billing_cycle, max_retries=1)

    def _find_files_section_with_retry(
        self, config: ScraperConfig, billing_cycle: BillingCycle, max_retries: int = 1
    ) -> Optional[Any]:
        """Busca la sección de archivos con reintento automático en caso de error."""
        for attempt in range(max_retries + 1):
            try:
                self.logger.info(
                    f"[LEGACY] Searching for AT&T files section (attempt {attempt + 1}/{max_retries + 1})"
                )

                # 1. Click en billing header y esperar 2 minutos
                billing_header_xpath = "/html/body/div[1]/div/ul/li[3]/a"
                self.logger.info("[LEGACY] Clicking Billing header...")
                self.browser_wrapper.click_element(billing_header_xpath)
                time.sleep(120)  # Esperar 2 minutos como especificado

                # 2. Click en reports tab
                reports_tab_xpath = "/html/body/div[1]/main/div[1]/div/div/div/div/div[3]/ul[1]/li[4]/a/span"
                self.logger.info("[LEGACY] Clicking Reports tab...")
                self.browser_wrapper.click_element(reports_tab_xpath)
                time.sleep(3)

                # 3. Click en detail option
                detail_option_xpath = "/html/body/div[1]/main/div[1]/div/div/div/div/div[3]/ul[1]/li[4]/ul/li[3]/a"
                self.logger.info("[LEGACY] Clicking Detail option...")
                self.browser_wrapper.click_element(detail_option_xpath)
                time.sleep(5)

                # 4. Verificar que encontramos la sección correcta
                charges_tab_section_xpath = "/html/body/div[1]/main/div[2]/form/div/div[1]/ul/li[1]/a/span"
                if self.browser_wrapper.is_element_visible(charges_tab_section_xpath, timeout=10000):
                    section_text = self.browser_wrapper.get_text(charges_tab_section_xpath)
                    if section_text and "Charges and usage" in section_text:
                        self.logger.info("[LEGACY] Reports section found successfully")
                        return {"section": "monthly_reports", "ready_for_download": True}
                    else:
                        self.logger.warning(f"[LEGACY] Section text does not match: {section_text}")
                        continue
                else:
                    self.logger.warning("[LEGACY] Reports section not found")
                    continue

            except Exception as e:
                self.logger.error(f"[LEGACY] Error on attempt {attempt + 1}: {str(e)}")
                if attempt < max_retries:
                    continue

        self.logger.error("[LEGACY] Could not find files section after all attempts")
        return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Descarga los 5 archivos mensuales de AT&T."""
        downloaded_files = []

        slug_to_report_config = {
            "wireless_charges": {
                "name": "All wireless charges and usage",
                "text_to_verify": "All wireless charges and usage",
                "section_xpath": "/html/body/div[1]/main/div[2]/form/div/div[2]/div[3]/div[3]/div/div[2]/ul/li[1]/button",
                "tab": "charges",
            },
            "usage_details": {
                "name": "All data export - usage details",
                "text_to_verify": "All data export - usage details",
                "section_xpath": "/html/body/div[1]/main/div[2]/form/div/div[2]/div[3]/div[2]/div/div[2]/ul/li[1]/button",
                "tab": "charges",
            },
            "monthly_charges": {
                "name": "Monthly charges",
                "text_to_verify": "Monthly charges",
                "section_xpath": "/html/body/div[1]/main/div[2]/form/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[8]/button",
                "tab": "charges",
            },
            "device_installment": {
                "name": "Device installment details",
                "text_to_verify": "Device installment details",
                "section_xpath": "/html/body/div[1]/main/div[2]/form/div/div[2]/div[3]/div[1]/div/div[2]/ul/li[8]/button",
                "tab": "charges",
            },
            "upgrade_and_inventory": {
                "name": "Upgrade eligibility and inventory",
                "text_to_verify": "Upgrade eligibility and inventory",
                "section_xpath": "/html/body/div[1]/main/div[2]/form/div/div[2]/div[3]/div/div/div[2]/ul/li[3]/button",
                "tab": "unbilled",
            },
        }

        billing_cycle_file_map = {}
        if billing_cycle.billing_cycle_files:
            for bcf in billing_cycle.billing_cycle_files:
                if bcf.carrier_report and bcf.carrier_report.slug:
                    slug = bcf.carrier_report.slug
                    billing_cycle_file_map[slug] = bcf
                    self.logger.info(f"[LEGACY] Mapping BillingCycleFile ID {bcf.id} -> Slug: '{slug}'")

        try:
            charges_tab_xpath = "/html/body/div[1]/main/div[2]/form/div/div[1]/ul/li[1]/a"
            self.logger.info("[LEGACY] Clicking Charges tab...")
            self.browser_wrapper.click_element(charges_tab_xpath)
            time.sleep(3)

            self._configure_date_range(billing_cycle)

            charges_reports = [slug for slug, cfg in slug_to_report_config.items() if cfg["tab"] == "charges"]
            for slug in charges_reports:
                self._download_single_report(
                    slug, slug_to_report_config[slug], billing_cycle_file_map, downloaded_files
                )

            self.logger.info("[LEGACY] Switching to Unbilled Usage tab...")
            unbilled_tab_xpath = "/html/body/div[1]/main/div[2]/form/div/div[1]/ul/li[3]/a"
            self.browser_wrapper.click_element(unbilled_tab_xpath)
            time.sleep(3)

            unbilled_reports = [slug for slug, cfg in slug_to_report_config.items() if cfg["tab"] == "unbilled"]
            for slug in unbilled_reports:
                self._download_single_report(
                    slug, slug_to_report_config[slug], billing_cycle_file_map, downloaded_files
                )

            self._reset_to_main_screen()

            self.logger.info(f"[LEGACY] Download completed. Total files: {len(downloaded_files)}")
            return downloaded_files

        except Exception as e:
            self.logger.error(f"[LEGACY] Error during file download: {str(e)}")
            try:
                self._reset_to_main_screen()
            except:
                pass
            return downloaded_files

    def _configure_date_range(self, billing_cycle: BillingCycle):
        """Configura el rango de fechas basado en el billing cycle."""
        try:
            self.logger.info(f"[LEGACY] Configuring date for period: {billing_cycle.end_date}")

            date_dropdown_xpath = "/html/body/div[1]/main/div[2]/form/div/div[2]/div[1]/div[2]/div/div/div/button"
            self.browser_wrapper.click_element(date_dropdown_xpath)
            time.sleep(2)

            option_dropdown_xpath = "/html/body/div[1]/main/div[2]/form/div/div[2]/div[1]/div[2]/div/div/div/div/div/div[2]/div/div[1]/select"
            self.browser_wrapper.click_element(option_dropdown_xpath)
            time.sleep(1)

            end_date = billing_cycle.end_date
            month_name = calendar.month_name[end_date.month]
            year = end_date.year
            option_text = f"{month_name} {year} bills"

            self.logger.debug(f"[LEGACY] Searching for option: {option_text}")

            select_xpath = "/html/body/div[1]/main/div[2]/form/div/div[2]/div[1]/div[2]/div/div/div/div/div/div[2]/div/div[1]/select"
            self.browser_wrapper.select_dropdown_option(select_xpath, option_text)
            time.sleep(1)

            apply_button_xpath = "/html/body/div[1]/main/div[2]/form/div/div[2]/div[1]/div[2]/div/div/div/div/div/div[2]/div/div[5]/button"
            self.logger.info("[LEGACY] Applying date changes...")
            self.browser_wrapper.click_element(apply_button_xpath)
            time.sleep(5)

        except Exception as e:
            self.logger.error(f"[LEGACY] Error configuring date: {str(e)}")

    def _download_single_report(
        self, slug: str, report_config: dict, billing_cycle_file_map: dict, downloaded_files: list
    ):
        """Descarga un reporte individual."""
        try:
            self.logger.info(f"[LEGACY] Processing report: {report_config['name']} (slug: {slug})")

            section_xpath = report_config["section_xpath"]

            if self.browser_wrapper.is_element_visible(section_xpath, timeout=5000):
                button_text = self.browser_wrapper.get_text(section_xpath)
                if button_text and report_config["text_to_verify"] in button_text:
                    self.logger.debug(f"[LEGACY] Text verified: '{button_text}'")
                    self.browser_wrapper.click_element(section_xpath)
                    time.sleep(3)
                else:
                    self.logger.warning(
                        f"[LEGACY] Text mismatch for {slug}. Expected: '{report_config['text_to_verify']}', Found: '{button_text}'. Skipping..."
                    )
                    return
            else:
                self.logger.warning(f"[LEGACY] Section not found for {slug}. Skipping...")
                return

            download_button_xpath = "/html/body/div[1]/main/div[2]/form/div[2]/div[2]/div/div/button[2]"
            self.logger.info("[LEGACY] Clicking Download Report...")
            self.browser_wrapper.click_element(download_button_xpath)
            time.sleep(2)

            csv_option_xpath = "/html/body/div[1]/div[3]/div/div/div[2]/form/div[1]/div/div/fieldset/label[2]"
            self.logger.info("[LEGACY] Selecting CSV option...")
            self.browser_wrapper.click_element(csv_option_xpath)
            time.sleep(1)

            ok_button_xpath = "/html/body/div[1]/div[3]/div/div/div[3]/button[1]"
            self.logger.info("[LEGACY] Clicking OK...")

            file_path = self.browser_wrapper.expect_download_and_click(
                ok_button_xpath, timeout=60000, downloads_dir=self.job_downloads_dir
            )

            if file_path:
                actual_filename = os.path.basename(file_path)
                self.logger.info(f"[LEGACY] File downloaded: {actual_filename}")

                corresponding_bcf = billing_cycle_file_map.get(slug)

                file_download_info = FileDownloadInfo(
                    file_id=corresponding_bcf.id if corresponding_bcf else len(downloaded_files) + 1,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=file_path,
                    billing_cycle_file=corresponding_bcf,
                )
                downloaded_files.append(file_download_info)

                if corresponding_bcf:
                    self.logger.info(
                        f"[LEGACY] MAPPING CONFIRMED: {actual_filename} -> BillingCycleFile ID {corresponding_bcf.id} (Slug: '{slug}')"
                    )
                else:
                    self.logger.warning(f"[LEGACY] File downloaded without specific BillingCycleFile mapping")
            else:
                self.logger.error(f"[LEGACY] Could not download file for {slug}")

            go_back_xpath = "/html/body/div[1]/main/div[2]/form/div[1]/div[1]/a"
            self.logger.info("[LEGACY] Going back...")
            self.browser_wrapper.click_element(go_back_xpath)
            time.sleep(3)

        except Exception as e:
            self.logger.error(f"[LEGACY] Error downloading report {slug}: {str(e)}")
            try:
                go_back_xpath = "/html/body/div[1]/main/div[2]/form/div[1]/div[1]/a"
                self.browser_wrapper.click_element(go_back_xpath)
                time.sleep(2)
            except:
                pass

    def _reset_to_main_screen(self):
        """Reset a la pantalla inicial de AT&T."""
        try:
            self.logger.info("[LEGACY] Resetting to AT&T initial screen...")
            self.browser_wrapper.goto("https://www.wireless.att.com/premiercare/")
            time.sleep(10)
            self.logger.info("[LEGACY] Reset to AT&T completed")
        except Exception as e:
            self.logger.error(f"[LEGACY] Error in AT&T reset: {str(e)}")
