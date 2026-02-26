import logging
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    FileDownloadInfo,
    MonthlyReportsScraperStrategy,
)
from web_scrapers.domain.enums import TmobileFileSlug

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)

# Mapeo de nombres de reportes en la UI a slugs del sistema (TmobileFileSlug)
REPORT_NAME_TO_SLUG = {
    "Charges and Usage Summary": TmobileFileSlug.CHARGES_AND_USAGE.value,
    "Usage Detail Report": TmobileFileSlug.USAGE_DETAIL.value,
    "Statement Detail": TmobileFileSlug.STATEMENT_DETAIL.value,
    "Equipment Inventory Report": TmobileFileSlug.INVENTORY_REPORT.value,
    "Equipment Installment and Payment Report": TmobileFileSlug.EQUIPMENT_INSTALLMENT.value,
}


class TMobileMonthlyReportsScraperStrategy(MonthlyReportsScraperStrategy):
    """Scraper de reportes mensuales para T-Mobile."""

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navega a la seccion de Billing templates y configura los filtros."""
        try:
            self.logger.info("=" * 70)
            self.logger.info("T-MOBILE MONTHLY REPORTS - NAVEGACION A SECCION DE ARCHIVOS")
            self.logger.info("=" * 70)
            self.logger.info(f"Account: {billing_cycle.account.number if billing_cycle.account else 'N/A'}")
            self.logger.info(f"Billing Period: {billing_cycle.end_date.strftime('%B %Y')}")
            self.logger.info(f"Current URL: {self.browser_wrapper.page.url}")
            self.logger.info("-" * 70)

            # Step 1: Navigate to Reporting section
            self.logger.info("[Step 1/4] Navegando a seccion Reporting...")
            if not self._navigate_to_reporting():
                error_msg = (
                    "FAILED at Step 1: No se pudo navegar a la seccion Reporting. "
                    "Posibles causas: Panel 'Reporting' no visible, menu lateral no cargado, "
                    "o submenu 'My Reports' no encontrado."
                )
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            self.logger.info("[Step 1/4] OK - Navegacion a Reporting completada")

            # Step 2: Click on Billing templates tab
            self.logger.info("[Step 2/4] Buscando tab 'Billing templates'...")
            if not self._click_billing_templates_tab():
                error_msg = (
                    "FAILED at Step 2: No se pudo hacer click en tab 'Billing templates'. "
                    "Posibles causas: Tab header no visible, tab 'Billing templates' no existe, "
                    "o la pagina no cargo correctamente."
                )
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            self.logger.info("[Step 2/4] OK - Tab 'Billing templates' seleccionado")

            # Step 3: Select billing period based on billing_cycle.end_date
            expected_period = billing_cycle.end_date.strftime("%B %Y")
            self.logger.info(f"[Step 3/4] Seleccionando billing period: {expected_period}...")
            if not self._select_billing_period(billing_cycle):
                error_msg = (
                    f"FAILED at Step 3: No se pudo seleccionar billing period '{expected_period}'. "
                    "Posibles causas: Dropdown de billing period no visible, "
                    f"opcion '{expected_period}' no existe en el dropdown, o periodo fuera de rango."
                )
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            self.logger.info(f"[Step 3/4] OK - Billing period '{expected_period}' seleccionado")

            # Step 4: Select account in Hierarchy Level
            account_number = billing_cycle.account.number if billing_cycle.account else None
            if not account_number:
                error_msg = "FAILED at Step 4: No se encontro numero de cuenta en billing_cycle.account"
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)

            self.logger.info(f"[Step 4/4] Seleccionando cuenta {account_number} en Hierarchy Level...")
            if not self._select_hierarchy_level(account_number):
                error_msg = (
                    f"FAILED at Step 4: No se pudo seleccionar cuenta '{account_number}' en Hierarchy Level. "
                    "Posibles causas: Dropdown de Hierarchy Level no visible, "
                    f"cuenta '{account_number}' no existe en el arbol, o arbol no se expandio correctamente."
                )
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            self.logger.info(f"[Step 4/4] OK - Cuenta '{account_number}' seleccionada")

            self.logger.info("-" * 70)
            self.logger.info("SUCCESS: Seccion de reportes mensuales configurada correctamente")
            self.logger.info("=" * 70)
            return {"section": "billing_templates", "account": account_number}

        except RuntimeError:
            # Reset antes de re-raise para dejar UI limpia para siguiente job
            try:
                self._reset_to_main_screen()
            except:
                pass
            raise
        except Exception as e:
            # Reset antes de raise para dejar UI limpia para siguiente job
            try:
                self._reset_to_main_screen()
            except:
                pass
            error_msg = f"EXCEPTION en _find_files_section: {str(e)}"
            self.logger.error(error_msg)
            import traceback
            self.logger.error(traceback.format_exc())
            raise RuntimeError(error_msg)

    def _navigate_to_reporting(self) -> bool:
        """Navigate to the Reporting section in the sidebar menu."""
        try:
            self.logger.info("[NAV] Buscando seccion Reporting en el menu lateral...")
            self.logger.info(f"[NAV] Current URL: {self.browser_wrapper.page.url}")

            # First, look for the Reporting expansion panel and click it
            reporting_panel_xpath = '//*[@id="mat-expansion-panel-header-3"]'
            reporting_by_text_xpath = "//mat-expansion-panel-header//span[contains(text(), 'Reporting')]"

            self.logger.info(f"[NAV] Buscando panel Reporting por ID: {reporting_panel_xpath}")
            # Try with ID first
            if self.browser_wrapper.is_element_visible(reporting_panel_xpath, timeout=5000):
                self.logger.info("[NAV] Panel Reporting encontrado por ID, haciendo click...")
                self.browser_wrapper.click_element(reporting_panel_xpath)
                time.sleep(2)
            else:
                self.logger.info(f"[NAV] ID no encontrado, buscando por texto: {reporting_by_text_xpath}")
                if self.browser_wrapper.is_element_visible(reporting_by_text_xpath, timeout=5000):
                    self.logger.info("[NAV] Panel Reporting encontrado por texto, haciendo click...")
                    self.browser_wrapper.click_element(reporting_by_text_xpath)
                    time.sleep(2)
                else:
                    self.logger.error("[NAV] FAILED: No se encontro el panel de Reporting")
                    self.logger.error(f"[NAV] Intentados: ID='{reporting_panel_xpath}', Text='{reporting_by_text_xpath}'")
                    return False

            # My Reports se abre automaticamente al hacer click en Reporting
            self.logger.info("[NAV] Esperando carga de pagina My Reports (5s)...")
            time.sleep(5)

            self.logger.info(f"[NAV] Navegacion completada. URL actual: {self.browser_wrapper.page.url}")
            return True

        except Exception as e:
            self.logger.error(f"[NAV] EXCEPTION: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _click_billing_templates_tab(self) -> bool:
        """Click on the Billing templates tab."""
        try:
            self.logger.info("[TAB] Buscando tab 'Billing templates'...")

            # Wait for tab header to be visible
            tab_header_xpath = (
                '//*[@id="tfb-reporting-container"]/div/div/app-my-reports/div/div[1]/div/mat-tab-group/mat-tab-header'
            )

            self.logger.info(f"[TAB] Verificando presencia de tab header: {tab_header_xpath}")
            if not self.browser_wrapper.is_element_visible(tab_header_xpath, timeout=10000):
                self.logger.error("[TAB] FAILED: Tab header container no encontrado")
                self.logger.error(f"[TAB] Xpath intentado: {tab_header_xpath}")
                self.logger.error("[TAB] Posible causa: La pagina 'My Reports' no cargo correctamente")
                return False

            self.logger.info("[TAB] Tab header encontrado, buscando tab 'Billing templates'...")

            # Find and click the "Billing templates" tab
            billing_templates_tab_xpath = "//div[@role='tab']//span[contains(text(), 'Billing templates')]"

            if self.browser_wrapper.is_element_visible(billing_templates_tab_xpath, timeout=5000):
                self.logger.info("[TAB] Tab 'Billing templates' encontrado, haciendo click...")
                self.browser_wrapper.click_element(billing_templates_tab_xpath)
                time.sleep(3)
                self.logger.info("[TAB] Tab 'Billing templates' seleccionado exitosamente")
                return True
            else:
                self.logger.error("[TAB] FAILED: Tab 'Billing templates' no encontrado")
                self.logger.error(f"[TAB] Xpath intentado: {billing_templates_tab_xpath}")
                # Intentar obtener los tabs disponibles para debug
                try:
                    tabs = self.browser_wrapper.page.query_selector_all("div[role='tab']")
                    available_tabs = [tab.inner_text().strip() for tab in tabs]
                    self.logger.error(f"[TAB] Tabs disponibles: {available_tabs}")
                except:
                    pass
                return False

        except Exception as e:
            self.logger.error(f"[TAB] EXCEPTION: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _select_billing_period(self, billing_cycle: BillingCycle) -> bool:
        """Select the billing period from the dropdown based on billing_cycle.end_date."""
        try:
            # Primero, verificar y cerrar cualquier modal bloqueante
            self._dismiss_blocking_modal()

            # Format the expected option text: "Month Year" (e.g., "December 2025")
            end_date = billing_cycle.end_date
            month_name = end_date.strftime("%B")  # Full month name
            year = end_date.strftime("%Y")
            expected_period = f"{month_name} {year}"

            self.logger.info(f"[PERIOD] Buscando billing period: {expected_period}")

            # Click on the billing period dropdown to open it
            billing_period_dropdown_xpath = '//*[@id="mat-select-0"]'
            billing_period_by_placeholder_xpath = "//mat-select[@placeholder='Select billing period']"

            # Esperar a que el dropdown cargue sus opciones
            self.logger.info("[PERIOD] Esperando carga de opciones del dropdown (15s)...")
            time.sleep(15)

            self.logger.info(f"[PERIOD] Buscando dropdown por ID: {billing_period_dropdown_xpath}")
            if self.browser_wrapper.is_element_visible(billing_period_dropdown_xpath, timeout=5000):
                self.logger.info("[PERIOD] Dropdown encontrado por ID, haciendo click...")
                self.browser_wrapper.click_element(billing_period_dropdown_xpath)
            else:
                self.logger.info(f"[PERIOD] ID no encontrado, buscando por placeholder: {billing_period_by_placeholder_xpath}")
                if self.browser_wrapper.is_element_visible(billing_period_by_placeholder_xpath, timeout=5000):
                    self.logger.info("[PERIOD] Dropdown encontrado por placeholder, haciendo click...")
                    self.browser_wrapper.click_element(billing_period_by_placeholder_xpath)
                else:
                    self.logger.error("[PERIOD] FAILED: Dropdown de billing period no encontrado")
                    self.logger.error(f"[PERIOD] Intentados: ID='{billing_period_dropdown_xpath}', Placeholder='{billing_period_by_placeholder_xpath}'")
                    return False

            self.logger.info("[PERIOD] Esperando apertura del dropdown (2s)...")
            time.sleep(2)

            # Search for the option with the expected period text
            option_xpath = f"//mat-option//span[contains(text(), '{expected_period}')]"

            self.logger.info(f"[PERIOD] Buscando opcion: {expected_period}")
            if self.browser_wrapper.is_element_visible(option_xpath, timeout=5000):
                self.logger.info(f"[PERIOD] Opcion '{expected_period}' encontrada, seleccionando...")
                self.browser_wrapper.click_element(option_xpath)
                time.sleep(2)
                self.logger.info(f"[PERIOD] Billing period '{expected_period}' seleccionado exitosamente")
                return True
            else:
                self.logger.error(f"[PERIOD] FAILED: Opcion '{expected_period}' no encontrada en el dropdown")
                # Intentar obtener las opciones disponibles para debug
                try:
                    options = self.browser_wrapper.page.query_selector_all("mat-option")
                    available_options = [opt.inner_text().strip() for opt in options]
                    self.logger.error(f"[PERIOD] Opciones disponibles: {available_options}")
                except:
                    pass
                return False

        except Exception as e:
            self.logger.error(f"[PERIOD] EXCEPTION: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _select_hierarchy_level(self, account_number: str) -> bool:
        """Navigate the Hierarchy Level tree to find and select the account number."""
        try:
            self.logger.info(f"[HIERARCHY] Buscando cuenta {account_number} en Hierarchy Level...")

            # Click on the Hierarchy Level dropdown to open it
            hierarchy_dropdown_xpath = "//mat-select[@name='hierarchyLevel']"
            hierarchy_container_xpath = "//div[contains(@class, 'hierarchy-level-dd')]//mat-select"

            self.logger.info(f"[HIERARCHY] Buscando dropdown por name: {hierarchy_dropdown_xpath}")
            if self.browser_wrapper.is_element_visible(hierarchy_dropdown_xpath, timeout=5000):
                self.logger.info("[HIERARCHY] Dropdown encontrado por name, haciendo click...")
                self.browser_wrapper.click_element(hierarchy_dropdown_xpath)
            else:
                self.logger.info(f"[HIERARCHY] name no encontrado, buscando por container: {hierarchy_container_xpath}")
                if self.browser_wrapper.is_element_visible(hierarchy_container_xpath, timeout=5000):
                    self.logger.info("[HIERARCHY] Dropdown encontrado por container, haciendo click...")
                    self.browser_wrapper.click_element(hierarchy_container_xpath)
                else:
                    self.logger.error("[HIERARCHY] FAILED: Dropdown de Hierarchy Level no encontrado")
                    self.logger.error(f"[HIERARCHY] Intentados: name='{hierarchy_dropdown_xpath}', container='{hierarchy_container_xpath}'")
                    return False

            self.logger.info("[HIERARCHY] Esperando apertura del panel (2s)...")
            time.sleep(2)

            # Wait for the tree panel to appear
            tree_panel_xpath = "//div[contains(@id, 'mat-select') and contains(@id, '-panel')]//mat-tree"

            self.logger.info(f"[HIERARCHY] Verificando que el arbol se abrio: {tree_panel_xpath}")
            if not self.browser_wrapper.is_element_visible(tree_panel_xpath, timeout=5000):
                self.logger.error("[HIERARCHY] FAILED: Panel del arbol de hierarchy no se abrio")
                self.logger.error(f"[HIERARCHY] Xpath intentado: {tree_panel_xpath}")
                return False

            self.logger.info("[HIERARCHY] Panel del arbol visible, buscando cuenta...")

            # Now we need to expand nodes until we find the account number
            found = self._find_and_select_account_in_tree(account_number)

            if found:
                self.logger.info(f"[HIERARCHY] Cuenta {account_number} seleccionada correctamente")
                return True
            else:
                self.logger.error(f"[HIERARCHY] FAILED: No se encontro la cuenta {account_number} en el arbol")
                self.logger.error("[HIERARCHY] La cuenta puede no existir o el arbol no se expandio correctamente")
                return False

        except Exception as e:
            self.logger.error(f"[HIERARCHY] EXCEPTION: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _find_and_select_account_in_tree(self, account_number: str, max_depth: int = 5) -> bool:
        """
        Recursively expand tree nodes to find and select the account number.

        This method expands all expandable nodes in the tree until it finds
        a node that contains the account number, then clicks on it.
        """
        try:
            # First, check if the account number is already visible
            account_xpath = f"//mat-tree-node//span[contains(text(), '{account_number}')]"

            self.logger.info(f"[TREE] Buscando cuenta {account_number} en el arbol...")
            self.logger.info(f"[TREE] Xpath de busqueda: {account_xpath}")

            if self.browser_wrapper.is_element_visible(account_xpath, timeout=2000):
                self.logger.info(f"[TREE] Cuenta {account_number} encontrada directamente (sin expandir)")
                self.browser_wrapper.click_element(account_xpath)
                time.sleep(2)
                return True

            self.logger.info(f"[TREE] Cuenta no visible, expandiendo nodos (max depth: {max_depth})...")

            # If not visible, we need to expand parent nodes
            for depth in range(max_depth):
                self.logger.info(f"[TREE] Expansion nivel {depth + 1}/{max_depth}...")

                # Use JavaScript to find and expand all expandable nodes
                expanded_count = self._expand_all_tree_nodes()

                self.logger.info(f"[TREE] Nodos expandidos en este nivel: {expanded_count}")

                if expanded_count == 0:
                    self.logger.info("[TREE] No hay mas nodos expandibles")
                    break

                time.sleep(1)

                # After expanding, check if the account is now visible
                if self.browser_wrapper.is_element_visible(account_xpath, timeout=2000):
                    self.logger.info(f"[TREE] Cuenta {account_number} encontrada despues de expansion nivel {depth + 1}")
                    self.browser_wrapper.click_element(account_xpath)
                    time.sleep(2)
                    return True

            # Final check after all expansions
            self.logger.info("[TREE] Verificacion final despues de todas las expansiones...")
            if self.browser_wrapper.is_element_visible(account_xpath, timeout=2000):
                self.logger.info(f"[TREE] Cuenta {account_number} encontrada en verificacion final")
                self.browser_wrapper.click_element(account_xpath)
                time.sleep(2)
                return True

            # Log de nodos visibles para debug
            self.logger.error(f"[TREE] FAILED: Cuenta {account_number} no encontrada en el arbol")
            try:
                visible_nodes = self.browser_wrapper.page.query_selector_all("mat-tree-node")
                node_texts = [node.inner_text().strip()[:50] for node in visible_nodes[:10]]  # Primeros 10 nodos
                self.logger.error(f"[TREE] Primeros nodos visibles: {node_texts}")
            except:
                pass

            return False

        except Exception as e:
            self.logger.error(f"[TREE] EXCEPTION en busqueda recursiva: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _expand_all_tree_nodes(self) -> int:
        """
        Expand all tree nodes that are currently collapsed.

        Uses JavaScript to find and click all expand buttons.
        Returns the number of nodes that were expanded.
        """
        try:
            # Use JavaScript to find and click all expandable nodes
            expanded_count = self.browser_wrapper.page.evaluate(
                """
                () => {
                    const expandableNodes = document.querySelectorAll('mat-tree-node[aria-expanded="false"]');
                    let count = 0;

                    expandableNodes.forEach((node) => {
                        const button = node.querySelector('button[mattreenodetoggle]:not([disabled])');
                        if (button) {
                            button.click();
                            count++;
                        }
                    });

                    return count;
                }
                """
            )

            self.logger.debug(f"Expandidos {expanded_count} nodos")
            return expanded_count

        except Exception as e:
            self.logger.error(f"Error expandiendo nodos: {str(e)}")
            return 0

    # ========== METODOS PARA GENERACION DE REPORTES ==========

    def _expand_accordion_by_title(self, accordion_title: str) -> bool:
        """Expande un accordion buscando por su titulo (ej: 'Billing & Statements')."""
        try:
            self.logger.info(f"Expandiendo accordion: {accordion_title}...")

            # Buscar el panel header que contiene el titulo
            # El texto puede estar en mat-panel-title
            accordion_xpath = (
                f"//mat-expansion-panel-header[.//mat-panel-title[contains(text(), '{accordion_title}')]]"
            )

            if not self.browser_wrapper.is_element_visible(accordion_xpath, timeout=5000):
                self.logger.error(f"Accordion '{accordion_title}' no encontrado")
                return False

            # Verificar si ya esta expandido
            is_expanded = self.browser_wrapper.page.evaluate(
                f"""
                () => {{
                    const header = document.evaluate(
                        "{accordion_xpath}",
                        document,
                        null,
                        XPathResult.FIRST_ORDERED_NODE_TYPE,
                        null
                    ).singleNodeValue;
                    return header ? header.getAttribute('aria-expanded') === 'true' : false;
                }}
                """
            )

            if is_expanded:
                self.logger.info(f"Accordion '{accordion_title}' ya esta expandido")
                return True

            # Click para expandir
            self.browser_wrapper.click_element(accordion_xpath)
            time.sleep(1)
            self.logger.info(f"Accordion '{accordion_title}' expandido")
            return True

        except Exception as e:
            self.logger.error(f"Error expandiendo accordion '{accordion_title}': {str(e)}")
            return False

    def _find_report_row_and_click_menu(self, report_title: str) -> bool:
        """Encuentra un reporte por su titulo y hace click en el icono more_vert."""
        try:
            self.logger.info(f"Buscando reporte: {report_title}...")

            # Buscar el row que contiene el titulo del reporte
            # El titulo esta en .billing-template-title span o .equipment-template-title span
            report_row_xpath = (
                f"//div[contains(@class, 'template-list')]" f"[.//span[normalize-space(text())='{report_title}']]"
            )

            if not self.browser_wrapper.is_element_visible(report_row_xpath, timeout=5000):
                self.logger.error(f"Reporte '{report_title}' no encontrado")
                return False

            # Buscar el icono more_vert dentro de este row
            more_vert_xpath = (
                f"//div[contains(@class, 'template-list')]"
                f"[.//span[normalize-space(text())='{report_title}']]"
                f"//mat-icon[contains(text(), 'more_vert')]"
            )

            if not self.browser_wrapper.is_element_visible(more_vert_xpath, timeout=3000):
                self.logger.error(f"Icono more_vert no encontrado para '{report_title}'")
                return False

            self.browser_wrapper.click_element(more_vert_xpath)
            time.sleep(1)
            self.logger.info(f"Menu abierto para reporte '{report_title}'")
            return True

        except Exception as e:
            self.logger.error(f"Error buscando reporte '{report_title}': {str(e)}")
            return False

    def _click_menu_option(self, option_text: str) -> bool:
        """Hace click en una opcion del menu abierto (ej: 'Run as is', 'Download')."""
        try:
            self.logger.info(f"Buscando opcion de menu: {option_text}...")

            # El menu se abre con clase mat-mdc-menu-panel y role="menu"
            # Buscar el menu visible y la opcion dentro
            menu_option_xpath = (
                f"//div[@role='menu' and contains(@class, 'mat-mdc-menu-panel')]"
                f"//span[contains(@class, 'mat-menu-btn-info') and contains(text(), '{option_text}')]"
            )

            # Alternativa para menus con estructura diferente
            menu_option_alt_xpath = (
                f"//div[@role='menu' and contains(@class, 'mat-mdc-menu-panel')]"
                f"//button[@role='menuitem']//span[contains(text(), '{option_text}')]"
            )

            if self.browser_wrapper.is_element_visible(menu_option_xpath, timeout=3000):
                self.browser_wrapper.click_element(menu_option_xpath)
            elif self.browser_wrapper.is_element_visible(menu_option_alt_xpath, timeout=2000):
                self.browser_wrapper.click_element(menu_option_alt_xpath)
            else:
                self.logger.error(f"Opcion '{option_text}' no encontrada en el menu")
                return False

            time.sleep(1)
            self.logger.info(f"Opcion '{option_text}' seleccionada")
            return True

        except Exception as e:
            self.logger.error(f"Error seleccionando opcion '{option_text}': {str(e)}")
            return False

    def _dismiss_blocking_modal(self) -> bool:
        """Detecta y cierra cualquier modal bloqueante (error o confirmación)."""
        try:
            modal_xpath = "//mat-dialog-container"
            backdrop_xpath = "//div[contains(@class, 'cdk-overlay-backdrop-showing')]"

            # Verificar si hay un modal bloqueante
            if not self.browser_wrapper.is_element_visible(backdrop_xpath, timeout=1000):
                return True  # No hay modal bloqueante

            self.logger.warning("[MODAL] Detectado modal bloqueante, intentando cerrar...")

            # Detectar si es un modal de error "Something went wrong"
            error_modal_xpath = "//mat-dialog-container//span[contains(text(), 'Something went wrong')]"
            reload_button_xpath = "//mat-dialog-container//button[contains(., 'Reload reports')]"
            close_button_xpath = "//mat-dialog-container//button[contains(@class, 'close')]"
            close_icon_xpath = "//mat-dialog-container//mat-icon[contains(text(), 'close')]"

            # Si es un modal de error, hacer click en "Reload reports" o cerrar
            if self.browser_wrapper.is_element_visible(error_modal_xpath, timeout=2000):
                self.logger.warning("[MODAL] Modal de error 'Something went wrong' detectado")

                # Intentar click en "Reload reports"
                if self.browser_wrapper.is_element_visible(reload_button_xpath, timeout=2000):
                    self.logger.info("[MODAL] Clickeando 'Reload reports'...")
                    self.browser_wrapper.click_element(reload_button_xpath)
                    time.sleep(3)

                    # Esperar a que la página recargue
                    self.logger.info("[MODAL] Esperando recarga de página (30s)...")
                    time.sleep(30)
                    return True

            # Intentar cerrar con botón close
            if self.browser_wrapper.is_element_visible(close_button_xpath, timeout=1000):
                self.logger.info("[MODAL] Cerrando con botón close...")
                self.browser_wrapper.click_element(close_button_xpath)
                time.sleep(2)
                if not self.browser_wrapper.is_element_visible(backdrop_xpath, timeout=1000):
                    return True

            # Intentar cerrar con icono close
            if self.browser_wrapper.is_element_visible(close_icon_xpath, timeout=1000):
                self.logger.info("[MODAL] Cerrando con icono close...")
                self.browser_wrapper.click_element(close_icon_xpath)
                time.sleep(2)
                if not self.browser_wrapper.is_element_visible(backdrop_xpath, timeout=1000):
                    return True

            # Intentar con ESC
            self.logger.info("[MODAL] Intentando cerrar con ESC...")
            for _ in range(5):
                self.browser_wrapper.page.keyboard.press("Escape")
                time.sleep(0.5)

            time.sleep(2)
            if not self.browser_wrapper.is_element_visible(backdrop_xpath, timeout=1000):
                return True

            # Último recurso: refrescar la página
            self.logger.warning("[MODAL] No se pudo cerrar modal, refrescando página...")
            self.browser_wrapper.page.reload()
            time.sleep(10)
            return True

        except Exception as e:
            self.logger.error(f"[MODAL] Error manejando modal bloqueante: {str(e)}")
            return False

    def _close_confirmation_modal(self) -> bool:
        """Cierra el modal de confirmacion despues de 'Run as is'."""
        try:
            self.logger.info("Cerrando modal de confirmacion...")

            # Xpaths para el modal y sus elementos
            modal_xpath = "//mat-dialog-container"
            backdrop_xpath = "//div[contains(@class, 'cdk-overlay-backdrop')]"
            close_button_xpath = "//mat-dialog-container//button[contains(@class, 'close')]"
            close_icon_xpath = "//mat-dialog-container//mat-icon[contains(text(), 'close')]"

            # Esperar a que aparezca el modal (puede tardar hasta 60 segundos)
            self.logger.info("Esperando a que aparezca el modal de confirmacion (max 60s)...")
            modal_appeared = self.browser_wrapper.is_element_visible(modal_xpath, timeout=60000)

            if not modal_appeared:
                self.logger.warning("Modal de confirmacion no apareció después de 60s")
                return True  # Continuar de todos modos

            self.logger.info("Modal de confirmacion detectado, cerrando...")

            # Intentar cerrar el modal con diferentes métodos
            modal_closed = False

            # Método 1: Click en botón close
            if self.browser_wrapper.is_element_visible(close_button_xpath, timeout=3000):
                self.logger.info("Intentando cerrar con boton close...")
                self.browser_wrapper.click_element(close_button_xpath)
                time.sleep(2)
                modal_closed = not self.browser_wrapper.is_element_visible(modal_xpath, timeout=1000)

            # Método 2: Click en icono close
            if not modal_closed and self.browser_wrapper.is_element_visible(close_icon_xpath, timeout=2000):
                self.logger.info("Intentando cerrar con icono close...")
                self.browser_wrapper.click_element(close_icon_xpath)
                time.sleep(2)
                modal_closed = not self.browser_wrapper.is_element_visible(modal_xpath, timeout=1000)

            # Método 3: Presionar ESC múltiples veces
            if not modal_closed:
                self.logger.info("Intentando cerrar con ESC...")
                for _ in range(3):
                    self.browser_wrapper.page.keyboard.press("Escape")
                    time.sleep(1)
                modal_closed = not self.browser_wrapper.is_element_visible(modal_xpath, timeout=1000)

            # Método 4: Click en el backdrop (fuera del modal)
            if not modal_closed and self.browser_wrapper.is_element_visible(backdrop_xpath, timeout=1000):
                self.logger.info("Intentando cerrar clickeando el backdrop...")
                try:
                    self.browser_wrapper.page.click(backdrop_xpath, force=True)
                    time.sleep(2)
                    modal_closed = not self.browser_wrapper.is_element_visible(modal_xpath, timeout=1000)
                except:
                    pass

            # Verificación final
            if modal_closed:
                self.logger.info("Modal de confirmacion cerrado exitosamente")
                return True
            else:
                # Último intento: recargar la página y volver a navegar
                self.logger.warning("Modal no se pudo cerrar - el backdrop sigue visible")
                return False

        except Exception as e:
            self.logger.error(f"Error cerrando modal: {str(e)}")
            return False

    def _queue_report_for_generation(self, report_title: str) -> bool:
        """Proceso completo para encolar un reporte: menu -> Run as is -> cerrar modal."""
        try:
            self.logger.info(f"=== Encolando reporte: {report_title} ===")

            # 1. Abrir menu del reporte
            if not self._find_report_row_and_click_menu(report_title):
                return False

            # 2. Click en "Run as is"
            if not self._click_menu_option("Run as is"):
                return False

            # 3. Cerrar modal de confirmacion
            if not self._close_confirmation_modal():
                return False

            self.logger.info(f"Reporte '{report_title}' encolado exitosamente")
            return True

        except Exception as e:
            self.logger.error(f"Error encolando reporte '{report_title}': {str(e)}")
            return False

    def _setup_billing_template_filters(self, billing_cycle: BillingCycle, account_number: str) -> bool:
        """Configura los filtros de Billing templates: billing period y cuenta."""
        self.logger.info("Configurando filtros de Billing templates...")

        # 1. Seleccionar billing period
        if not self._select_billing_period(billing_cycle):
            expected_period = billing_cycle.end_date.strftime("%B %Y")
            error_msg = (
                f"FATAL: Billing period '{expected_period}' no encontrado en el dropdown de T-Mobile. "
                "No se puede continuar, los reportes generados corresponderían a un periodo incorrecto."
            )
            self.logger.error(error_msg)
            self._reset_to_main_screen()
            raise RuntimeError(error_msg)

        time.sleep(1)

        # 2. Seleccionar cuenta en Hierarchy Level
        if not self._select_hierarchy_level(account_number):
            error_msg = (
                f"FATAL: Cuenta '{account_number}' no encontrada en Hierarchy Level de T-Mobile. "
                "No se puede continuar, los reportes generados corresponderían a una cuenta incorrecta."
            )
            self.logger.error(error_msg)
            self._reset_to_main_screen()
            raise RuntimeError(error_msg)

        time.sleep(1)
        self.logger.info("Filtros de Billing templates configurados")
        return True

    def _generate_billing_template_report(
        self, report_title: str, accordion_title: str, billing_cycle: BillingCycle, account_number: str
    ) -> bool:
        """Genera un reporte de Billing templates con todo el flujo: filtros + accordion + Run as is."""
        try:
            self.logger.info(f"\n>>> Generando reporte: {report_title}")

            # 1. Configurar filtros (billing period + cuenta)
            if not self._setup_billing_template_filters(billing_cycle, account_number):
                return False

            time.sleep(1)

            # 2. Expandir accordion
            if not self._expand_accordion_by_title(accordion_title):
                self.logger.error(f"No se pudo expandir accordion '{accordion_title}'")
                return False

            time.sleep(1)

            # 3. Encolar reporte (menu -> Run as is -> cerrar modal)
            if not self._queue_report_for_generation(report_title):
                return False

            self.logger.info(f"<<< Reporte '{report_title}' generado exitosamente\n")
            return True

        except RuntimeError:
            raise
        except Exception as e:
            self.logger.error(f"Error generando reporte '{report_title}': {str(e)}")
            return False

    def _select_hierarchy_level_other_templates(self, account_number: str) -> bool:
        """Selecciona la cuenta en Hierarchy Level para Other templates (xpath diferente)."""
        try:
            self.logger.info(f"Buscando cuenta {account_number} en Hierarchy Level (Other templates)...")

            # Xpath especifico para Other templates - diferente al de Billing templates
            hierarchy_dropdown_xpath = (
                '//*[@id="tfb-reporting-container"]/div[1]/div/app-my-reports/div/div[4]'
                "/app-select-template/div/div[3]/div[2]/mat-form-field"
            )

            if not self.browser_wrapper.is_element_visible(hierarchy_dropdown_xpath, timeout=5000):
                self.logger.error("Dropdown de Hierarchy Level (Other templates) no encontrado")
                return False

            self.logger.info("Click en dropdown Hierarchy Level (Other templates)...")
            self.browser_wrapper.click_element(hierarchy_dropdown_xpath)
            time.sleep(2)

            # Esperar a que aparezca el panel del arbol
            tree_panel_xpath = "//mat-tree"

            if not self.browser_wrapper.is_element_visible(tree_panel_xpath, timeout=5000):
                self.logger.error("Panel del arbol de hierarchy no se abrio")
                return False

            # Buscar y seleccionar la cuenta en el arbol
            found = self._find_and_select_account_in_tree(account_number)

            if found:
                self.logger.info(f"Cuenta {account_number} seleccionada correctamente (Other templates)")
                return True
            else:
                self.logger.error(f"No se encontro la cuenta {account_number} en el arbol")
                return False

        except Exception as e:
            self.logger.error(f"Error selecting hierarchy level (Other templates): {str(e)}")
            return False

    def _generate_other_template_report(self, report_title: str, accordion_title: str, account_number: str) -> bool:
        """Genera un reporte de Other templates con todo el flujo: cuenta + accordion + Run as is."""
        try:
            self.logger.info(f"\n>>> Generando reporte (Other): {report_title}")

            # 1. Seleccionar cuenta en Hierarchy Level (usa xpath especifico para Other templates)
            if not self._select_hierarchy_level_other_templates(account_number):
                self.logger.error(f"No se pudo seleccionar cuenta {account_number}")
                return False

            time.sleep(1)

            # 2. Expandir accordion
            if not self._expand_accordion_by_title(accordion_title):
                self.logger.error(f"No se pudo expandir accordion '{accordion_title}'")
                return False

            time.sleep(1)

            # 3. Encolar reporte (menu -> Run as is -> cerrar modal)
            if not self._queue_report_for_generation(report_title):
                return False

            self.logger.info(f"<<< Reporte '{report_title}' generado exitosamente\n")
            return True

        except Exception as e:
            self.logger.error(f"Error generando reporte '{report_title}': {str(e)}")
            return False

    def _click_other_templates_tab(self) -> bool:
        """Hace click en la tab 'Other templates'."""
        try:
            # Verificar y cerrar cualquier modal bloqueante
            self._dismiss_blocking_modal()

            self.logger.info("Cambiando a tab Other templates...")

            other_templates_xpath = "//div[@role='tab']//span[contains(text(), 'Other templates')]"

            if not self.browser_wrapper.is_element_visible(other_templates_xpath, timeout=5000):
                self.logger.error("Tab Other templates no encontrada")
                return False

            self.browser_wrapper.click_element(other_templates_xpath)
            time.sleep(3)
            self.logger.info("Tab Other templates seleccionada")
            return True

        except Exception as e:
            self.logger.error(f"Error cambiando a Other templates: {str(e)}")
            return False

    def _click_my_reports_tab(self) -> bool:
        """Hace click en la tab 'My reports'."""
        try:
            self.logger.info("Cambiando a tab My reports...")

            my_reports_xpath = "//div[@role='tab']//span[contains(text(), 'My reports')]"

            if not self.browser_wrapper.is_element_visible(my_reports_xpath, timeout=5000):
                self.logger.error("Tab My reports no encontrada")
                return False

            self.browser_wrapper.click_element(my_reports_xpath)
            time.sleep(3)
            self.logger.info("Tab My reports seleccionada")
            return True

        except Exception as e:
            self.logger.error(f"Error cambiando a My reports: {str(e)}")
            return False

    # ========== METODOS PARA DESCARGA DE REPORTES ==========

    def _find_completed_reports_for_today(self, account_number: str) -> List[Dict[str, Any]]:
        """Encuentra los reportes completados con fecha de hoy en My Reports.

        Solo retorna 1 reporte de cada tipo (maximo 5 reportes):
        - Charges and Usage Summary
        - Usage Detail Report
        - Statement Detail
        - Equipment Inventory Report
        - Equipment Installment and Payment Report
        """
        completed_reports = []
        # Set para trackear tipos ya encontrados (solo 1 de cada tipo)
        found_report_types = set()
        target_report_types = set(REPORT_NAME_TO_SLUG.keys())

        try:
            self.logger.info("Buscando reportes completados para hoy (1 de cada tipo, max 5)...")

            # Obtener todos los rows de reportes
            report_rows = self.browser_wrapper.page.query_selector_all("mat-expansion-panel.history-content")

            today_str = datetime.now().strftime("%b %#d, %Y") if os.name == "nt" else datetime.now().strftime("%b %-d, %Y")

            for idx, row in enumerate(report_rows):
                # Si ya tenemos los 5 tipos, salir
                if len(found_report_types) >= 5:
                    break

                try:
                    # Obtener nombre del reporte
                    name_elem = row.query_selector(".report-name")
                    report_name = name_elem.inner_text().strip() if name_elem else ""

                    # Saltar si ya tenemos este tipo de reporte
                    if report_name in found_report_types:
                        continue

                    # Saltar si no es uno de los 5 tipos que buscamos
                    if report_name not in target_report_types:
                        continue

                    # Obtener detalles (cuenta y periodo)
                    detail_elem = row.query_selector(".report-det")
                    detail_text = detail_elem.inner_text().strip() if detail_elem else ""

                    # Obtener fecha de ejecucion
                    date_elem = row.query_selector(".run-date")
                    run_date = date_elem.inner_text().strip() if date_elem else ""

                    # Obtener status
                    status_elem = row.query_selector(".report-status")
                    status = status_elem.inner_text().strip() if status_elem else ""

                    # Verificar si es de hoy y esta completado
                    is_today = today_str in run_date
                    is_completed = "Completed" in status
                    has_account = account_number in detail_text

                    if is_completed and is_today and has_account:
                        self.logger.info(f"Reporte encontrado: {report_name} | {detail_text} | {run_date} | {status}")
                        completed_reports.append(
                            {
                                "index": idx,
                                "name": report_name,
                                "detail": detail_text,
                                "run_date": run_date,
                                "status": status,
                                "element": row,
                            }
                        )
                        found_report_types.add(report_name)

                except Exception as e:
                    self.logger.debug(f"Error procesando row {idx}: {str(e)}")
                    continue

            self.logger.info(f"Total reportes unicos encontrados: {len(completed_reports)} de 5 esperados")
            if len(found_report_types) < 5:
                missing = target_report_types - found_report_types
                self.logger.warning(f"Reportes faltantes: {missing}")

            return completed_reports

        except Exception as e:
            self.logger.error(f"Error buscando reportes completados: {str(e)}")
            return completed_reports

    def _download_single_report(
        self, report_info: Dict[str, Any], billing_cycle_file_map: Dict[str, Any]
    ) -> Optional[FileDownloadInfo]:
        """Descarga un reporte individual desde My Reports."""
        try:
            report_name = report_info["name"]
            self.logger.info(f"=== Descargando: {report_name} ===")

            # Buscar el boton more_vert en este row
            row_element = report_info["element"]

            # Click en el icono more_vert del row
            more_vert = row_element.query_selector("mat-icon#meatball, mat-icon.icon_more_vert")
            if not more_vert:
                self.logger.error(f"No se encontro icono more_vert para {report_name}")
                return None

            more_vert.click()
            time.sleep(1)

            # Click en "Download" del menu
            if not self._click_menu_option("Download"):
                return None

            time.sleep(1)

            # Click en el boton de descarga del modal
            download_button_xpath = (
                "//mat-dialog-container//button[contains(text(), 'Download') or " "contains(@class, 'download')]"
            )
            download_button_alt = "//mat-dialog-container//mat-dialog-actions//button[last()]"

            if self.browser_wrapper.is_element_visible(download_button_xpath, timeout=5000):
                # Usar expect_download_and_click para capturar la descarga
                file_path = self.browser_wrapper.expect_download_and_click(
                    download_button_xpath,
                    timeout=60000,
                    downloads_dir=self.job_downloads_dir,
                )
            elif self.browser_wrapper.is_element_visible(download_button_alt, timeout=3000):
                file_path = self.browser_wrapper.expect_download_and_click(
                    download_button_alt,
                    timeout=60000,
                    downloads_dir=self.job_downloads_dir,
                )
            else:
                self.logger.error("Boton de descarga no encontrado en modal")
                return None

            time.sleep(2)

            if file_path:
                actual_filename = os.path.basename(file_path)
                self.logger.info(f"Archivo descargado: {actual_filename}")

                # Mapear al slug correspondiente
                slug = REPORT_NAME_TO_SLUG.get(report_name)
                corresponding_bcf = billing_cycle_file_map.get(slug) if slug else None

                if corresponding_bcf:
                    self.logger.info(f"Mapeado a BCF ID {corresponding_bcf.id} (slug: {slug})")
                else:
                    self.logger.warning(f"No se encontro BCF para slug: {slug}")

                return FileDownloadInfo(
                    file_id=corresponding_bcf.id if corresponding_bcf else 0,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=file_path,
                    billing_cycle_file=corresponding_bcf,
                )
            else:
                self.logger.error(f"No se pudo descargar {report_name}")
                return None

        except Exception as e:
            self.logger.error(f"Error descargando reporte: {str(e)}")
            return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Descarga los archivos mensuales de T-Mobile.

        Flujo completo:
        1. Generar 3 reportes en Billing templates (Billing & Statements)
        2. Generar 2 reportes en Other templates (Equipment templates)
        3. Esperar 3 minutos para que se generen
        4. Descargar los 5 reportes completados desde My Reports
        """
        downloaded_files = []
        account_number = files_section.get("account", "")

        # Mapear BillingCycleFiles por slug
        billing_cycle_file_map = {}
        if billing_cycle.billing_cycle_files:
            for bcf in billing_cycle.billing_cycle_files:
                if bcf.carrier_report and bcf.carrier_report.slug:
                    billing_cycle_file_map[bcf.carrier_report.slug] = bcf
                    self.logger.info(f"Mapeando BillingCycleFile ID {bcf.id} -> Slug: '{bcf.carrier_report.slug}'")

        try:
            self.logger.info("=== INICIANDO GENERACION DE REPORTES T-MOBILE ===")

            # ========== FASE 1: Generar reportes en Billing templates ==========
            self.logger.info("\n--- FASE 1: Billing templates (3 reportes) ---")

            # Lista de reportes de Billing templates
            # Cada reporte requiere: configurar filtros + expandir accordion + Run as is
            billing_reports = [
                "Charges and Usage Summary",
                "Usage Detail",
                "Statement Detail",
            ]

            for report_name in billing_reports:
                # Cada reporte necesita configurar filtros desde cero porque se resetean
                if not self._generate_billing_template_report(
                    report_title=report_name,
                    accordion_title="Billing & Statements",
                    billing_cycle=billing_cycle,
                    account_number=account_number,
                ):
                    self.logger.warning(f"No se pudo generar: {report_name}")
                time.sleep(2)

            # ========== FASE 2: Generar reportes en Other templates ==========
            self.logger.info("\n--- FASE 2: Other templates (2 reportes) ---")

            # Lista de reportes de Equipment templates
            equipment_reports = [
                "Equipment Inventory",
                "Equipment Installment",
            ]

            for report_name in equipment_reports:
                # Cambiar a tab Other templates (se resetea despues de cada Run as is)
                if not self._click_other_templates_tab():
                    self.logger.error("No se pudo cambiar a Other templates")
                    continue

                time.sleep(2)

                # Generar reporte con filtros y accordion
                if not self._generate_other_template_report(
                    report_title=report_name,
                    accordion_title="Equipment templates",
                    account_number=account_number,
                ):
                    self.logger.warning(f"No se pudo generar: {report_name}")
                time.sleep(2)

            # ========== FASE 3: Esperar generacion de reportes ==========
            self.logger.info("\n--- FASE 3: Esperando generacion de reportes ---")
            wait_time_seconds = 420  # 7 minutos
            self.logger.info(f"Esperando {wait_time_seconds // 60} minutos para que se generen los reportes...")

            # Reset a la pantalla principal mientras esperamos
            self._reset_to_main_screen()
            time.sleep(wait_time_seconds)

            # ========== FASE 4: Descargar reportes completados ==========
            self.logger.info("\n--- FASE 4: Descargando reportes completados ---")

            # Navegar nuevamente a Reporting
            if not self._navigate_to_reporting():
                self.logger.error("No se pudo navegar a Reporting")
                return downloaded_files

            # Click en tab My reports
            if not self._click_my_reports_tab():
                self.logger.error("No se pudo cambiar a My reports")
                return downloaded_files

            time.sleep(3)

            # Buscar reportes completados para hoy
            completed_reports = self._find_completed_reports_for_today(account_number)

            if not completed_reports:
                self.logger.warning("No se encontraron reportes completados para hoy")
                # Intentar una vez mas despues de esperar un poco
                self.logger.info("Esperando 60 segundos adicionales y reintentando...")
                time.sleep(60)
                self.browser_wrapper.page.reload()
                time.sleep(5)
                if not self._click_my_reports_tab():
                    return downloaded_files
                time.sleep(3)
                completed_reports = self._find_completed_reports_for_today(account_number)

            # Descargar cada reporte
            for report_info in completed_reports:
                file_info = self._download_single_report(report_info, billing_cycle_file_map)
                if file_info:
                    downloaded_files.append(file_info)
                time.sleep(2)

            # Reset a pantalla principal
            self._reset_to_main_screen()

            # Log resumen final
            self.logger.info(f"\n{'='*60}")
            self.logger.info("RESUMEN DE DESCARGA")
            self.logger.info(f"{'='*60}")
            self.logger.info(f"Total archivos descargados: {len(downloaded_files)}")
            for idx, file_info in enumerate(downloaded_files, 1):
                if file_info.billing_cycle_file:
                    bcf = file_info.billing_cycle_file
                    slug = bcf.carrier_report.slug if bcf.carrier_report else "N/A"
                    self.logger.info(f"   [{idx}] {file_info.file_name} -> BCF ID {bcf.id} ('{slug}')")
                else:
                    self.logger.info(f"   [{idx}] {file_info.file_name} -> SIN MAPEO")
            self.logger.info(f"{'='*60}\n")

            return downloaded_files

        except RuntimeError:
            raise
        except Exception as e:
            self.logger.error(f"[EXCEPTION] Error en descarga de archivos: {str(e)}")
            try:
                self._reset_to_main_screen()
            except:
                pass
            raise

    def _reset_to_main_screen(self):
        """Reset a la pantalla inicial de T-Mobile dashboard."""
        try:
            self.logger.info("Reseteando a T-Mobile dashboard...")
            self.browser_wrapper.goto("https://tfb.t-mobile.com/apps/tfb_billing/dashboard")
            time.sleep(5)
            self.logger.info("Reset completado")
        except Exception as e:
            self.logger.error(f"Error en reset: {str(e)}")
