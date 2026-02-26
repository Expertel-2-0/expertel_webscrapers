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

# Mapping of UI report names to system slugs (TmobileFileSlug)
REPORT_NAME_TO_SLUG = {
    "Charges and Usage Summary": TmobileFileSlug.CHARGES_AND_USAGE.value,
    "Usage Detail Report": TmobileFileSlug.USAGE_DETAIL.value,
    "Statement Detail": TmobileFileSlug.STATEMENT_DETAIL.value,
    "Equipment Inventory Report": TmobileFileSlug.INVENTORY_REPORT.value,
    "Equipment Installment and Payment Report": TmobileFileSlug.EQUIPMENT_INSTALLMENT.value,
}

# Reports that include the billing period in the Detail field (e.g. "Mar 2025 | 968283334").
# Equipment reports do not have a period in detail — they are generated from Other templates,
# which has no billing period filter.
REPORTS_WITH_BILLING_PERIOD = {
    "Charges and Usage Summary",
    "Usage Detail Report",
    "Statement Detail",
}


class TMobileMonthlyReportsScraperStrategy(MonthlyReportsScraperStrategy):
    """Monthly reports scraper for T-Mobile."""

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navigate to Billing templates section and configure filters."""
        try:
            self.logger.info("=" * 70)
            self.logger.info("T-MOBILE MONTHLY REPORTS - NAVIGATING TO FILES SECTION")
            self.logger.info("=" * 70)
            self.logger.info(f"Account: {billing_cycle.account.number if billing_cycle.account else 'N/A'}")
            self.logger.info(f"Billing Period: {billing_cycle.end_date.strftime('%B %Y')}")
            self.logger.info(f"Current URL: {self.browser_wrapper.page.url}")
            self.logger.info("-" * 70)

            # Step 1: Navigate to Reporting section
            self.logger.info("[Step 1/4] Navigating to Reporting section...")
            if not self._navigate_to_reporting():
                error_msg = (
                    "FAILED at Step 1: Could not navigate to the Reporting section. "
                    "Possible causes: 'Reporting' panel not visible, sidebar not loaded, "
                    "or 'My Reports' submenu not found."
                )
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            self.logger.info("[Step 1/4] OK - Navigation to Reporting completed")

            # Step 2: Click on Billing templates tab
            self.logger.info("[Step 2/4] Looking for 'Billing templates' tab...")
            if not self._click_billing_templates_tab():
                error_msg = (
                    "FAILED at Step 2: Could not click on 'Billing templates' tab. "
                    "Possible causes: tab header not visible, 'Billing templates' tab does not exist, "
                    "or the page did not load correctly."
                )
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            self.logger.info("[Step 2/4] OK - 'Billing templates' tab selected")

            # Step 3: Select billing period based on billing_cycle.end_date
            expected_period = billing_cycle.end_date.strftime("%B %Y")
            self.logger.info(f"[Step 3/4] Selecting billing period: {expected_period}...")
            if not self._select_billing_period(billing_cycle):
                error_msg = (
                    f"FAILED at Step 3: Could not select billing period '{expected_period}'. "
                    "Possible causes: billing period dropdown not visible, "
                    f"option '{expected_period}' does not exist in the dropdown, or period out of range."
                )
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            self.logger.info(f"[Step 3/4] OK - Billing period '{expected_period}' selected")

            # Step 4: Select account in Hierarchy Level
            account_number = billing_cycle.account.number if billing_cycle.account else None
            if not account_number:
                error_msg = "FAILED at Step 4: Account number not found in billing_cycle.account"
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)

            self.logger.info(f"[Step 4/4] Selecting account {account_number} in Hierarchy Level...")
            if not self._select_hierarchy_level(account_number):
                error_msg = (
                    f"FAILED at Step 4: Could not select account '{account_number}' in Hierarchy Level. "
                    "Possible causes: Hierarchy Level dropdown not visible, "
                    f"account '{account_number}' does not exist in the tree, or tree did not expand correctly."
                )
                self.logger.error(error_msg)
                raise RuntimeError(error_msg)
            self.logger.info(f"[Step 4/4] OK - Account '{account_number}' selected")

            self.logger.info("-" * 70)
            self.logger.info("SUCCESS: Monthly reports section configured correctly")
            self.logger.info("=" * 70)
            return {"section": "billing_templates", "account": account_number}

        except RuntimeError:
            # Reset before re-raise to leave UI clean for the next job
            try:
                self._reset_to_main_screen()
            except:
                pass
            raise
        except Exception as e:
            # Reset before raise to leave UI clean for the next job
            try:
                self._reset_to_main_screen()
            except:
                pass
            error_msg = f"EXCEPTION in _find_files_section: {str(e)}"
            self.logger.error(error_msg)
            import traceback
            self.logger.error(traceback.format_exc())
            raise RuntimeError(error_msg)

    def _navigate_to_reporting(self) -> bool:
        """Navigate to the Reporting section in the sidebar menu."""
        try:
            self.logger.info("[NAV] Looking for Reporting section in the sidebar...")
            self.logger.info(f"[NAV] Current URL: {self.browser_wrapper.page.url}")

            reporting_panel_xpath = '//*[@id="mat-expansion-panel-header-3"]'
            reporting_by_text_xpath = "//mat-expansion-panel-header//span[contains(text(), 'Reporting')]"

            self.logger.info(f"[NAV] Looking for Reporting panel by ID: {reporting_panel_xpath}")
            if self.browser_wrapper.is_element_visible(reporting_panel_xpath, timeout=5000):
                self.logger.info("[NAV] Reporting panel found by ID, clicking...")
                self.browser_wrapper.click_element(reporting_panel_xpath)
                time.sleep(2)
            else:
                self.logger.info(f"[NAV] ID not found, looking by text: {reporting_by_text_xpath}")
                if self.browser_wrapper.is_element_visible(reporting_by_text_xpath, timeout=5000):
                    self.logger.info("[NAV] Reporting panel found by text, clicking...")
                    self.browser_wrapper.click_element(reporting_by_text_xpath)
                    time.sleep(2)
                else:
                    self.logger.error("[NAV] FAILED: Reporting panel not found")
                    self.logger.error(f"[NAV] Tried: ID='{reporting_panel_xpath}', Text='{reporting_by_text_xpath}'")
                    return False

            # My Reports opens automatically after clicking Reporting
            self.logger.info("[NAV] Waiting for My Reports page to load (5s)...")
            time.sleep(5)

            self.logger.info(f"[NAV] Navigation completed. Current URL: {self.browser_wrapper.page.url}")
            return True

        except Exception as e:
            self.logger.error(f"[NAV] EXCEPTION: {str(e)}")
            import traceback
            self.logger.error(traceback.format_exc())
            return False

    def _click_billing_templates_tab(self) -> bool:
        """Click on the Billing templates tab."""
        try:
            self.logger.info("[TAB] Looking for 'Billing templates' tab...")

            tab_header_xpath = (
                '//*[@id="tfb-reporting-container"]/div/div/app-my-reports/div/div[1]/div/mat-tab-group/mat-tab-header'
            )

            self.logger.info(f"[TAB] Checking tab header presence: {tab_header_xpath}")
            if not self.browser_wrapper.is_element_visible(tab_header_xpath, timeout=10000):
                self.logger.error("[TAB] FAILED: Tab header container not found")
                self.logger.error(f"[TAB] Xpath tried: {tab_header_xpath}")
                self.logger.error("[TAB] Possible cause: 'My Reports' page did not load correctly")
                return False

            self.logger.info("[TAB] Tab header found, looking for 'Billing templates' tab...")

            billing_templates_tab_xpath = "//div[@role='tab']//span[contains(text(), 'Billing templates')]"

            if self.browser_wrapper.is_element_visible(billing_templates_tab_xpath, timeout=5000):
                self.logger.info("[TAB] 'Billing templates' tab found, clicking...")
                self.browser_wrapper.click_element(billing_templates_tab_xpath)
                time.sleep(3)
                self.logger.info("[TAB] 'Billing templates' tab selected successfully")
                return True
            else:
                self.logger.error("[TAB] FAILED: 'Billing templates' tab not found")
                self.logger.error(f"[TAB] Xpath tried: {billing_templates_tab_xpath}")
                try:
                    tabs = self.browser_wrapper.page.query_selector_all("div[role='tab']")
                    available_tabs = [tab.inner_text().strip() for tab in tabs]
                    self.logger.error(f"[TAB] Available tabs: {available_tabs}")
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
            # First, check and dismiss any blocking modal
            self._dismiss_blocking_modal()

            end_date = billing_cycle.end_date
            month_name = end_date.strftime("%B")
            year = end_date.strftime("%Y")
            expected_period = f"{month_name} {year}"

            self.logger.info(f"[PERIOD] Looking for billing period: {expected_period}")

            billing_period_dropdown_xpath = '//*[@id="mat-select-0"]'
            billing_period_by_placeholder_xpath = "//mat-select[@placeholder='Select billing period']"

            self.logger.info("[PERIOD] Waiting for dropdown options to load (15s)...")
            time.sleep(15)

            self.logger.info(f"[PERIOD] Looking for dropdown by ID: {billing_period_dropdown_xpath}")
            if self.browser_wrapper.is_element_visible(billing_period_dropdown_xpath, timeout=5000):
                self.logger.info("[PERIOD] Dropdown found by ID, clicking...")
                self.browser_wrapper.click_element(billing_period_dropdown_xpath)
            else:
                self.logger.info(f"[PERIOD] ID not found, looking by placeholder: {billing_period_by_placeholder_xpath}")
                if self.browser_wrapper.is_element_visible(billing_period_by_placeholder_xpath, timeout=5000):
                    self.logger.info("[PERIOD] Dropdown found by placeholder, clicking...")
                    self.browser_wrapper.click_element(billing_period_by_placeholder_xpath)
                else:
                    self.logger.error("[PERIOD] FAILED: Billing period dropdown not found")
                    self.logger.error(f"[PERIOD] Tried: ID='{billing_period_dropdown_xpath}', Placeholder='{billing_period_by_placeholder_xpath}'")
                    return False

            self.logger.info("[PERIOD] Waiting for dropdown to open (2s)...")
            time.sleep(2)

            option_xpath = f"//mat-option//span[contains(text(), '{expected_period}')]"

            self.logger.info(f"[PERIOD] Looking for option: {expected_period}")
            if self.browser_wrapper.is_element_visible(option_xpath, timeout=5000):
                self.logger.info(f"[PERIOD] Option '{expected_period}' found, selecting...")
                self.browser_wrapper.click_element(option_xpath)
                time.sleep(2)
                self.logger.info(f"[PERIOD] Billing period '{expected_period}' selected successfully")
                return True
            else:
                self.logger.error(f"[PERIOD] FAILED: Option '{expected_period}' not found in dropdown")
                try:
                    options = self.browser_wrapper.page.query_selector_all("mat-option")
                    available_options = [opt.inner_text().strip() for opt in options]
                    self.logger.error(f"[PERIOD] Available options: {available_options}")
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
            self.logger.info(f"[HIERARCHY] Looking for account {account_number} in Hierarchy Level...")

            hierarchy_dropdown_xpath = "//mat-select[@name='hierarchyLevel']"
            hierarchy_container_xpath = "//div[contains(@class, 'hierarchy-level-dd')]//mat-select"

            self.logger.info(f"[HIERARCHY] Looking for dropdown by name: {hierarchy_dropdown_xpath}")
            if self.browser_wrapper.is_element_visible(hierarchy_dropdown_xpath, timeout=5000):
                self.logger.info("[HIERARCHY] Dropdown found by name, clicking...")
                self.browser_wrapper.click_element(hierarchy_dropdown_xpath)
            else:
                self.logger.info(f"[HIERARCHY] Name not found, looking by container: {hierarchy_container_xpath}")
                if self.browser_wrapper.is_element_visible(hierarchy_container_xpath, timeout=5000):
                    self.logger.info("[HIERARCHY] Dropdown found by container, clicking...")
                    self.browser_wrapper.click_element(hierarchy_container_xpath)
                else:
                    self.logger.error("[HIERARCHY] FAILED: Hierarchy Level dropdown not found")
                    self.logger.error(f"[HIERARCHY] Tried: name='{hierarchy_dropdown_xpath}', container='{hierarchy_container_xpath}'")
                    return False

            self.logger.info("[HIERARCHY] Waiting for panel to open (2s)...")
            time.sleep(2)

            tree_panel_xpath = "//div[contains(@id, 'mat-select') and contains(@id, '-panel')]//mat-tree"

            self.logger.info(f"[HIERARCHY] Verifying tree panel opened: {tree_panel_xpath}")
            if not self.browser_wrapper.is_element_visible(tree_panel_xpath, timeout=5000):
                self.logger.error("[HIERARCHY] FAILED: Hierarchy tree panel did not open")
                self.logger.error(f"[HIERARCHY] Xpath tried: {tree_panel_xpath}")
                return False

            self.logger.info("[HIERARCHY] Tree panel visible, searching for account...")

            found = self._find_and_select_account_in_tree(account_number)

            if found:
                self.logger.info(f"[HIERARCHY] Account {account_number} selected successfully")
                return True
            else:
                self.logger.error(f"[HIERARCHY] FAILED: Account {account_number} not found in tree")
                self.logger.error("[HIERARCHY] The account may not exist or the tree did not expand correctly")
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
            account_xpath = f"//mat-tree-node//span[contains(text(), '{account_number}')]"

            self.logger.info(f"[TREE] Searching for account {account_number} in tree...")
            self.logger.info(f"[TREE] Search xpath: {account_xpath}")

            if self.browser_wrapper.is_element_visible(account_xpath, timeout=2000):
                self.logger.info(f"[TREE] Account {account_number} found directly (no expansion needed)")
                self.browser_wrapper.click_element(account_xpath)
                time.sleep(2)
                return True

            self.logger.info(f"[TREE] Account not visible, expanding nodes (max depth: {max_depth})...")

            for depth in range(max_depth):
                self.logger.info(f"[TREE] Expansion level {depth + 1}/{max_depth}...")

                expanded_count = self._expand_all_tree_nodes()

                self.logger.info(f"[TREE] Nodes expanded at this level: {expanded_count}")

                if expanded_count == 0:
                    self.logger.info("[TREE] No more expandable nodes")
                    break

                time.sleep(1)

                if self.browser_wrapper.is_element_visible(account_xpath, timeout=2000):
                    self.logger.info(f"[TREE] Account {account_number} found after expansion level {depth + 1}")
                    self.browser_wrapper.click_element(account_xpath)
                    time.sleep(2)
                    return True

            # Final check after all expansions
            self.logger.info("[TREE] Final check after all expansions...")
            if self.browser_wrapper.is_element_visible(account_xpath, timeout=2000):
                self.logger.info(f"[TREE] Account {account_number} found in final check")
                self.browser_wrapper.click_element(account_xpath)
                time.sleep(2)
                return True

            self.logger.error(f"[TREE] FAILED: Account {account_number} not found in tree")
            try:
                visible_nodes = self.browser_wrapper.page.query_selector_all("mat-tree-node")
                node_texts = [node.inner_text().strip()[:50] for node in visible_nodes[:10]]
                self.logger.error(f"[TREE] First visible nodes: {node_texts}")
            except:
                pass

            return False

        except Exception as e:
            self.logger.error(f"[TREE] EXCEPTION in recursive search: {str(e)}")
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

            self.logger.debug(f"Expanded {expanded_count} nodes")
            return expanded_count

        except Exception as e:
            self.logger.error(f"Error expanding nodes: {str(e)}")
            return 0

    # ========== REPORT GENERATION METHODS ==========

    def _expand_accordion_by_title(self, accordion_title: str) -> bool:
        """Expand an accordion by searching for its title (e.g. 'Billing & Statements')."""
        try:
            self.logger.info(f"Expanding accordion: {accordion_title}...")

            accordion_xpath = (
                f"//mat-expansion-panel-header[.//mat-panel-title[contains(text(), '{accordion_title}')]]"
            )

            if not self.browser_wrapper.is_element_visible(accordion_xpath, timeout=5000):
                self.logger.error(f"Accordion '{accordion_title}' not found")
                return False

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
                self.logger.info(f"Accordion '{accordion_title}' already expanded")
                return True

            self.browser_wrapper.click_element(accordion_xpath)
            time.sleep(1)
            self.logger.info(f"Accordion '{accordion_title}' expanded")
            return True

        except Exception as e:
            self.logger.error(f"Error expanding accordion '{accordion_title}': {str(e)}")
            return False

    def _find_report_row_and_click_menu(self, report_title: str) -> bool:
        """Find a report by its title and click the more_vert icon."""
        try:
            self.logger.info(f"Looking for report: {report_title}...")

            report_row_xpath = (
                f"//div[contains(@class, 'template-list')]" f"[.//span[normalize-space(text())='{report_title}']]"
            )

            if not self.browser_wrapper.is_element_visible(report_row_xpath, timeout=5000):
                self.logger.error(f"Report '{report_title}' not found")
                return False

            more_vert_xpath = (
                f"//div[contains(@class, 'template-list')]"
                f"[.//span[normalize-space(text())='{report_title}']]"
                f"//mat-icon[contains(text(), 'more_vert')]"
            )

            if not self.browser_wrapper.is_element_visible(more_vert_xpath, timeout=3000):
                self.logger.error(f"more_vert icon not found for '{report_title}'")
                return False

            self.browser_wrapper.click_element(more_vert_xpath)
            time.sleep(1)
            self.logger.info(f"Menu opened for report '{report_title}'")
            return True

        except Exception as e:
            self.logger.error(f"Error looking for report '{report_title}': {str(e)}")
            return False

    def _click_menu_option(self, option_text: str) -> bool:
        """Click a menu option (e.g. 'Run as is', 'Download')."""
        try:
            self.logger.info(f"Looking for menu option: {option_text}...")

            menu_option_xpath = (
                f"//div[@role='menu' and contains(@class, 'mat-mdc-menu-panel')]"
                f"//span[contains(@class, 'mat-menu-btn-info') and contains(text(), '{option_text}')]"
            )

            menu_option_alt_xpath = (
                f"//div[@role='menu' and contains(@class, 'mat-mdc-menu-panel')]"
                f"//button[@role='menuitem']//span[contains(text(), '{option_text}')]"
            )

            if self.browser_wrapper.is_element_visible(menu_option_xpath, timeout=3000):
                self.browser_wrapper.click_element(menu_option_xpath)
            elif self.browser_wrapper.is_element_visible(menu_option_alt_xpath, timeout=2000):
                self.browser_wrapper.click_element(menu_option_alt_xpath)
            else:
                self.logger.error(f"Option '{option_text}' not found in menu")
                return False

            time.sleep(1)
            self.logger.info(f"Option '{option_text}' selected")
            return True

        except Exception as e:
            self.logger.error(f"Error selecting option '{option_text}': {str(e)}")
            return False

    def _dismiss_blocking_modal(self) -> bool:
        """Detect and dismiss any blocking modal (error or confirmation)."""
        try:
            modal_xpath = "//mat-dialog-container"
            backdrop_xpath = "//div[contains(@class, 'cdk-overlay-backdrop-showing')]"

            if not self.browser_wrapper.is_element_visible(backdrop_xpath, timeout=1000):
                return True  # No blocking modal

            self.logger.warning("[MODAL] Blocking modal detected, attempting to close...")

            error_modal_xpath = "//mat-dialog-container//span[contains(text(), 'Something went wrong')]"
            reload_button_xpath = "//mat-dialog-container//button[contains(., 'Reload reports')]"
            close_button_xpath = "//mat-dialog-container//button[contains(@class, 'close')]"
            close_icon_xpath = "//mat-dialog-container//mat-icon[contains(text(), 'close')]"

            if self.browser_wrapper.is_element_visible(error_modal_xpath, timeout=2000):
                self.logger.warning("[MODAL] 'Something went wrong' error modal detected")

                if self.browser_wrapper.is_element_visible(reload_button_xpath, timeout=2000):
                    self.logger.info("[MODAL] Clicking 'Reload reports'...")
                    self.browser_wrapper.click_element(reload_button_xpath)
                    time.sleep(3)

                    self.logger.info("[MODAL] Waiting for page reload (30s)...")
                    time.sleep(30)
                    return True

            if self.browser_wrapper.is_element_visible(close_button_xpath, timeout=1000):
                self.logger.info("[MODAL] Closing with close button...")
                self.browser_wrapper.click_element(close_button_xpath)
                time.sleep(2)
                if not self.browser_wrapper.is_element_visible(backdrop_xpath, timeout=1000):
                    return True

            if self.browser_wrapper.is_element_visible(close_icon_xpath, timeout=1000):
                self.logger.info("[MODAL] Closing with close icon...")
                self.browser_wrapper.click_element(close_icon_xpath)
                time.sleep(2)
                if not self.browser_wrapper.is_element_visible(backdrop_xpath, timeout=1000):
                    return True

            self.logger.info("[MODAL] Attempting to close with ESC...")
            for _ in range(5):
                self.browser_wrapper.page.keyboard.press("Escape")
                time.sleep(0.5)

            time.sleep(2)
            if not self.browser_wrapper.is_element_visible(backdrop_xpath, timeout=1000):
                return True

            self.logger.warning("[MODAL] Could not close modal, reloading page...")
            self.browser_wrapper.page.reload()
            time.sleep(10)
            return True

        except Exception as e:
            self.logger.error(f"[MODAL] Error handling blocking modal: {str(e)}")
            return False

    def _close_confirmation_modal(self) -> bool:
        """Close the confirmation modal after 'Run as is'."""
        try:
            self.logger.info("Closing confirmation modal...")

            modal_xpath = "//mat-dialog-container"
            backdrop_xpath = "//div[contains(@class, 'cdk-overlay-backdrop')]"
            close_button_xpath = "//mat-dialog-container//button[contains(@class, 'close')]"
            close_icon_xpath = "//mat-dialog-container//mat-icon[contains(text(), 'close')]"

            self.logger.info("Waiting for confirmation modal to appear (max 60s)...")
            modal_appeared = self.browser_wrapper.is_element_visible(modal_xpath, timeout=60000)

            if not modal_appeared:
                self.logger.warning("Confirmation modal did not appear after 60s")
                return True  # Continue anyway

            self.logger.info("Confirmation modal detected, closing...")

            modal_closed = False

            # Method 1: Click close button
            if self.browser_wrapper.is_element_visible(close_button_xpath, timeout=3000):
                self.logger.info("Attempting to close with close button...")
                self.browser_wrapper.click_element(close_button_xpath)
                time.sleep(2)
                modal_closed = not self.browser_wrapper.is_element_visible(modal_xpath, timeout=1000)

            # Method 2: Click close icon
            if not modal_closed and self.browser_wrapper.is_element_visible(close_icon_xpath, timeout=2000):
                self.logger.info("Attempting to close with close icon...")
                self.browser_wrapper.click_element(close_icon_xpath)
                time.sleep(2)
                modal_closed = not self.browser_wrapper.is_element_visible(modal_xpath, timeout=1000)

            # Method 3: Press ESC multiple times
            if not modal_closed:
                self.logger.info("Attempting to close with ESC...")
                for _ in range(3):
                    self.browser_wrapper.page.keyboard.press("Escape")
                    time.sleep(1)
                modal_closed = not self.browser_wrapper.is_element_visible(modal_xpath, timeout=1000)

            # Method 4: Click on the backdrop (outside the modal)
            if not modal_closed and self.browser_wrapper.is_element_visible(backdrop_xpath, timeout=1000):
                self.logger.info("Attempting to close by clicking the backdrop...")
                try:
                    self.browser_wrapper.page.click(backdrop_xpath, force=True)
                    time.sleep(2)
                    modal_closed = not self.browser_wrapper.is_element_visible(modal_xpath, timeout=1000)
                except:
                    pass

            if modal_closed:
                self.logger.info("Confirmation modal closed successfully")
                return True
            else:
                self.logger.warning("Modal could not be closed - backdrop still visible")
                return False

        except Exception as e:
            self.logger.error(f"Error closing modal: {str(e)}")
            return False

    def _queue_report_for_generation(self, report_title: str) -> bool:
        """Full process to queue a report: menu -> Run as is -> close modal."""
        try:
            self.logger.info(f"=== Queuing report: {report_title} ===")

            # 1. Open report menu
            if not self._find_report_row_and_click_menu(report_title):
                return False

            # 2. Click "Run as is"
            if not self._click_menu_option("Run as is"):
                return False

            # 3. Close confirmation modal
            if not self._close_confirmation_modal():
                return False

            self.logger.info(f"Report '{report_title}' queued successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error queuing report '{report_title}': {str(e)}")
            return False

    def _setup_billing_template_filters(self, billing_cycle: BillingCycle, account_number: str) -> bool:
        """Configure Billing templates filters: billing period and account."""
        self.logger.info("Configuring Billing templates filters...")

        # 1. Select billing period
        if not self._select_billing_period(billing_cycle):
            expected_period = billing_cycle.end_date.strftime("%B %Y")
            error_msg = (
                f"FATAL: Billing period '{expected_period}' not found in T-Mobile dropdown. "
                "Cannot continue — generated reports would correspond to an incorrect period."
            )
            self.logger.error(error_msg)
            self._reset_to_main_screen()
            raise RuntimeError(error_msg)

        time.sleep(1)

        # 2. Select account in Hierarchy Level
        if not self._select_hierarchy_level(account_number):
            error_msg = (
                f"FATAL: Account '{account_number}' not found in T-Mobile Hierarchy Level. "
                "Cannot continue — generated reports would correspond to an incorrect account."
            )
            self.logger.error(error_msg)
            self._reset_to_main_screen()
            raise RuntimeError(error_msg)

        time.sleep(1)
        self.logger.info("Billing templates filters configured")
        return True

    def _generate_billing_template_report(
        self, report_title: str, accordion_title: str, billing_cycle: BillingCycle, account_number: str
    ) -> bool:
        """Generate a Billing templates report: filters + accordion + Run as is."""
        try:
            self.logger.info(f"\n>>> Generating report: {report_title}")

            # 1. Configure filters (billing period + account)
            if not self._setup_billing_template_filters(billing_cycle, account_number):
                return False

            time.sleep(1)

            # 2. Expand accordion
            if not self._expand_accordion_by_title(accordion_title):
                self.logger.error(f"Could not expand accordion '{accordion_title}'")
                return False

            time.sleep(1)

            # 3. Queue report (menu -> Run as is -> close modal)
            if not self._queue_report_for_generation(report_title):
                return False

            self.logger.info(f"<<< Report '{report_title}' generated successfully\n")
            return True

        except RuntimeError:
            raise
        except Exception as e:
            self.logger.error(f"Error generating report '{report_title}': {str(e)}")
            return False

    def _select_hierarchy_level_other_templates(self, account_number: str) -> bool:
        """Select the account in Hierarchy Level for Other templates (different xpath)."""
        try:
            self.logger.info(f"Looking for account {account_number} in Hierarchy Level (Other templates)...")

            # Specific xpath for Other templates — different from Billing templates
            hierarchy_dropdown_xpath = (
                '//*[@id="tfb-reporting-container"]/div[1]/div/app-my-reports/div/div[4]'
                "/app-select-template/div/div[3]/div[2]/mat-form-field"
            )

            if not self.browser_wrapper.is_element_visible(hierarchy_dropdown_xpath, timeout=5000):
                self.logger.error("Hierarchy Level dropdown (Other templates) not found")
                return False

            self.logger.info("Clicking Hierarchy Level dropdown (Other templates)...")
            self.browser_wrapper.click_element(hierarchy_dropdown_xpath)
            time.sleep(2)

            tree_panel_xpath = "//mat-tree"

            if not self.browser_wrapper.is_element_visible(tree_panel_xpath, timeout=5000):
                self.logger.error("Hierarchy tree panel did not open")
                return False

            found = self._find_and_select_account_in_tree(account_number)

            if found:
                self.logger.info(f"Account {account_number} selected successfully (Other templates)")
                return True
            else:
                self.logger.error(f"Account {account_number} not found in tree")
                return False

        except Exception as e:
            self.logger.error(f"Error selecting hierarchy level (Other templates): {str(e)}")
            return False

    def _generate_other_template_report(self, report_title: str, accordion_title: str, account_number: str) -> bool:
        """Generate an Other templates report: account + accordion + Run as is."""
        try:
            self.logger.info(f"\n>>> Generating report (Other): {report_title}")

            # 1. Select account in Hierarchy Level (uses specific xpath for Other templates)
            if not self._select_hierarchy_level_other_templates(account_number):
                self.logger.error(f"Could not select account {account_number}")
                return False

            time.sleep(1)

            # 2. Expand accordion
            if not self._expand_accordion_by_title(accordion_title):
                self.logger.error(f"Could not expand accordion '{accordion_title}'")
                return False

            time.sleep(1)

            # 3. Queue report (menu -> Run as is -> close modal)
            if not self._queue_report_for_generation(report_title):
                return False

            self.logger.info(f"<<< Report '{report_title}' generated successfully\n")
            return True

        except Exception as e:
            self.logger.error(f"Error generating report '{report_title}': {str(e)}")
            return False

    def _click_other_templates_tab(self) -> bool:
        """Click on the 'Other templates' tab."""
        try:
            # Check and dismiss any blocking modal first
            self._dismiss_blocking_modal()

            self.logger.info("Switching to Other templates tab...")

            other_templates_xpath = "//div[@role='tab']//span[contains(text(), 'Other templates')]"

            if not self.browser_wrapper.is_element_visible(other_templates_xpath, timeout=5000):
                self.logger.error("Other templates tab not found")
                return False

            self.browser_wrapper.click_element(other_templates_xpath)
            time.sleep(3)
            self.logger.info("Other templates tab selected")
            return True

        except Exception as e:
            self.logger.error(f"Error switching to Other templates tab: {str(e)}")
            return False

    def _click_my_reports_tab(self) -> bool:
        """Click on the 'My reports' tab."""
        try:
            self.logger.info("Switching to My reports tab...")

            my_reports_xpath = "//div[@role='tab']//span[contains(text(), 'My reports')]"

            if not self.browser_wrapper.is_element_visible(my_reports_xpath, timeout=5000):
                self.logger.error("My reports tab not found")
                return False

            self.browser_wrapper.click_element(my_reports_xpath)
            time.sleep(3)
            self.logger.info("My reports tab selected")
            return True

        except Exception as e:
            self.logger.error(f"Error switching to My reports tab: {str(e)}")
            return False

    # ========== DOWNLOAD METHODS ==========

    def _find_completed_reports_for_today(self, account_number: str, billing_cycle: BillingCycle) -> List[Dict[str, Any]]:
        """Find completed reports for today in My Reports.

        Filters by:
        - Exact today's date in run_date (normalized to handle &nbsp; from HTML)
        - Status Completed
        - Account number in detail_text
        - For reports with billing period (Charges, Usage Detail, Statement): also
          verifies the billing_cycle period is in detail_text, to avoid mixing
          reports from different months generated the same day by parallel jobs.
        - For reports without billing period (Equipment): only account is validated.

        Returns at most 1 report per type (max 5 total).
        """
        completed_reports = []
        found_report_types = set()
        target_report_types = set(REPORT_NAME_TO_SLUG.keys())

        # Billing period in "Mar 2025" format — as it appears in the UI detail_text
        billing_period_str = billing_cycle.end_date.strftime("%b %Y")
        today_str = datetime.now().strftime("%b %#d, %Y") if os.name == "nt" else datetime.now().strftime("%b %-d, %Y")

        self.logger.info(f"Searching reports: date={today_str}, period={billing_period_str}, account={account_number}")

        try:
            report_rows = self.browser_wrapper.page.query_selector_all("mat-expansion-panel.history-content")

            for idx, row in enumerate(report_rows):
                if len(found_report_types) >= 5:
                    break

                try:
                    name_elem = row.query_selector(".report-name")
                    report_name = name_elem.inner_text().strip() if name_elem else ""

                    if report_name in found_report_types:
                        continue

                    if report_name not in target_report_types:
                        continue

                    detail_elem = row.query_selector(".report-det")
                    detail_text = detail_elem.inner_text().strip() if detail_elem else ""

                    date_elem = row.query_selector(".run-date")
                    # Normalize run_date: HTML contains &nbsp; (\u00a0) which breaks exact comparison
                    run_date = " ".join((date_elem.inner_text().strip() if date_elem else "").split())

                    status_elem = row.query_selector(".report-status")
                    status = status_elem.inner_text().strip() if status_elem else ""

                    is_today = today_str in run_date
                    is_completed = "Completed" in status
                    has_account = account_number in detail_text

                    # For reports that include billing period in detail, also validate the period
                    if report_name in REPORTS_WITH_BILLING_PERIOD:
                        has_correct_period = billing_period_str in detail_text
                    else:
                        has_correct_period = True  # Equipment reports have no period in detail

                    if is_completed and is_today and has_account and has_correct_period:
                        self.logger.info(f"Report found: {report_name} | {detail_text} | {run_date} | {status}")
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
                    self.logger.debug(f"Error processing row {idx}: {str(e)}")
                    continue

            self.logger.info(f"Total unique reports found: {len(completed_reports)} of 5 expected")
            if len(found_report_types) < 5:
                missing = target_report_types - found_report_types
                self.logger.warning(f"Missing reports: {missing}")

            return completed_reports

        except Exception as e:
            self.logger.error(f"Error searching completed reports: {str(e)}")
            return completed_reports

    def _download_single_report(
        self, report_info: Dict[str, Any], billing_cycle_file_map: Dict[str, Any]
    ) -> Optional[FileDownloadInfo]:
        """Download a single report from My Reports."""
        try:
            report_name = report_info["name"]
            self.logger.info(f"=== Downloading: {report_name} ===")

            row_element = report_info["element"]

            more_vert = row_element.query_selector("mat-icon#meatball, mat-icon.icon_more_vert")
            if not more_vert:
                self.logger.error(f"more_vert icon not found for {report_name}")
                return None

            more_vert.click()
            time.sleep(1)

            if not self._click_menu_option("Download"):
                return None

            time.sleep(1)

            download_button_xpath = (
                "//mat-dialog-container//button[contains(text(), 'Download') or " "contains(@class, 'download')]"
            )
            download_button_alt = "//mat-dialog-container//mat-dialog-actions//button[last()]"

            if self.browser_wrapper.is_element_visible(download_button_xpath, timeout=5000):
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
                self.logger.error("Download button not found in modal")
                return None

            time.sleep(2)

            if file_path:
                actual_filename = os.path.basename(file_path)
                self.logger.info(f"File downloaded: {actual_filename}")

                slug = REPORT_NAME_TO_SLUG.get(report_name)
                corresponding_bcf = billing_cycle_file_map.get(slug) if slug else None

                if corresponding_bcf:
                    self.logger.info(f"Mapped to BCF ID {corresponding_bcf.id} (slug: {slug})")
                else:
                    self.logger.warning(f"No BCF found for slug: {slug}")

                return FileDownloadInfo(
                    file_id=corresponding_bcf.id if corresponding_bcf else 0,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=file_path,
                    billing_cycle_file=corresponding_bcf,
                )
            else:
                self.logger.error(f"Could not download {report_name}")
                return None

        except Exception as e:
            self.logger.error(f"Error downloading report: {str(e)}")
            return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Download T-Mobile monthly files.

        Full flow:
        1. Generate 3 reports in Billing templates (Billing & Statements)
        2. Generate 2 reports in Other templates (Equipment templates)
        3. Wait 7 minutes for generation
        4. Download the 5 completed reports from My Reports
        """
        downloaded_files = []
        account_number = files_section.get("account", "")

        # Map BillingCycleFiles by slug
        billing_cycle_file_map = {}
        if billing_cycle.billing_cycle_files:
            for bcf in billing_cycle.billing_cycle_files:
                if bcf.carrier_report and bcf.carrier_report.slug:
                    billing_cycle_file_map[bcf.carrier_report.slug] = bcf
                    self.logger.info(f"Mapping BillingCycleFile ID {bcf.id} -> Slug: '{bcf.carrier_report.slug}'")

        try:
            self.logger.info("=== STARTING T-MOBILE REPORT GENERATION ===")

            # ========== PHASE 1: Generate Billing templates reports ==========
            self.logger.info("\n--- PHASE 1: Billing templates (3 reports) ---")

            # Filters reset after each Run as is, so they must be reconfigured per report
            billing_reports = [
                "Charges and Usage Summary",
                "Usage Detail",
                "Statement Detail",
            ]

            for report_name in billing_reports:
                if not self._generate_billing_template_report(
                    report_title=report_name,
                    accordion_title="Billing & Statements",
                    billing_cycle=billing_cycle,
                    account_number=account_number,
                ):
                    self.logger.warning(f"Could not generate: {report_name}")
                time.sleep(2)

            # ========== PHASE 2: Generate Other templates reports ==========
            self.logger.info("\n--- PHASE 2: Other templates (2 reports) ---")

            equipment_reports = [
                "Equipment Inventory",
                "Equipment Installment",
            ]

            for report_name in equipment_reports:
                # Switch to Other templates tab (resets after each Run as is)
                if not self._click_other_templates_tab():
                    self.logger.error("Could not switch to Other templates tab")
                    continue

                time.sleep(2)

                if not self._generate_other_template_report(
                    report_title=report_name,
                    accordion_title="Equipment templates",
                    account_number=account_number,
                ):
                    self.logger.warning(f"Could not generate: {report_name}")
                time.sleep(2)

            # ========== PHASE 3: Wait for report generation ==========
            self.logger.info("\n--- PHASE 3: Waiting for report generation ---")
            wait_time_seconds = 420  # 7 minutes
            self.logger.info(f"Waiting {wait_time_seconds // 60} minutes for reports to be generated...")

            self._reset_to_main_screen()
            time.sleep(wait_time_seconds)

            # ========== PHASE 4: Download completed reports ==========
            self.logger.info("\n--- PHASE 4: Downloading completed reports ---")

            if not self._navigate_to_reporting():
                self.logger.error("Could not navigate to Reporting")
                return downloaded_files

            if not self._click_my_reports_tab():
                self.logger.error("Could not switch to My reports tab")
                return downloaded_files

            time.sleep(3)

            completed_reports = self._find_completed_reports_for_today(account_number, billing_cycle)

            if not completed_reports:
                self.logger.warning("No completed reports found for today")
                self.logger.info("Waiting 60 additional seconds and retrying...")
                time.sleep(60)
                self.browser_wrapper.page.reload()
                time.sleep(5)
                if not self._click_my_reports_tab():
                    return downloaded_files
                time.sleep(3)
                completed_reports = self._find_completed_reports_for_today(account_number, billing_cycle)

            for report_info in completed_reports:
                file_info = self._download_single_report(report_info, billing_cycle_file_map)
                if file_info:
                    downloaded_files.append(file_info)
                time.sleep(2)

            self._reset_to_main_screen()

            self.logger.info(f"\n{'='*60}")
            self.logger.info("DOWNLOAD SUMMARY")
            self.logger.info(f"{'='*60}")
            self.logger.info(f"Total files downloaded: {len(downloaded_files)}")
            for idx, file_info in enumerate(downloaded_files, 1):
                if file_info.billing_cycle_file:
                    bcf = file_info.billing_cycle_file
                    slug = bcf.carrier_report.slug if bcf.carrier_report else "N/A"
                    self.logger.info(f"   [{idx}] {file_info.file_name} -> BCF ID {bcf.id} ('{slug}')")
                else:
                    self.logger.info(f"   [{idx}] {file_info.file_name} -> NO MAPPING")
            self.logger.info(f"{'='*60}\n")

            return downloaded_files

        except RuntimeError:
            raise
        except Exception as e:
            self.logger.error(f"[EXCEPTION] Error during file download: {str(e)}")
            try:
                self._reset_to_main_screen()
            except:
                pass
            raise

    def _reset_to_main_screen(self):
        """Reset to the T-Mobile dashboard main screen."""
        try:
            self.logger.info("Resetting to T-Mobile dashboard...")
            self.browser_wrapper.goto("https://tfb.t-mobile.com/apps/tfb_billing/dashboard")
            time.sleep(5)
            self.logger.info("Reset completed")
        except Exception as e:
            self.logger.error(f"Error during reset: {str(e)}")
