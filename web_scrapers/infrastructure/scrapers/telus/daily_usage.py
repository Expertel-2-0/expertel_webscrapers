import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    DailyUsageScraperStrategy,
    FileDownloadInfo,
)

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class TelusDailyUsageScraperStrategy(DailyUsageScraperStrategy):
    """Daily usage scraper for Telus.

    This scraper:
    1. Navigates to Usage tab to get pool_size and pool_used
    2. Navigates to Telus IQ via Overview
    3. Generates and downloads the Daily Usage Report
    """

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.pool_size: Optional[int] = None  # In bytes
        self.pool_used: Optional[int] = None  # In bytes

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navigates to daily usage section in Telus and gets pool data."""
        try:
            self.logger.info("=== STARTING TELUS DAILY USAGE SCRAPER ===")

            # 1. Verify we are in My Telus
            current_url = self.browser_wrapper.get_current_url()
            if "my-telus" not in current_url:
                self.logger.info("Navigating to My Telus...")
                self.browser_wrapper.goto("https://www.telus.com/my-telus")
                self.browser_wrapper.wait_for_page_load()
                time.sleep(5)

            # 2. Click on Usage tab
            usage_tab_xpath = '//*[@id="navOpen"]/li[3]/a'
            self.logger.info("Clicking on Usage tab...")
            self.browser_wrapper.click_element(usage_tab_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(5)

            # 3. Handle possible "Find your account" screen
            if not self._handle_account_selection(billing_cycle):
                self.logger.error("Account selection failed - aborting scraper")
                return None

            # 4. Verify current account is correct
            if not self._verify_current_account(billing_cycle):
                self.logger.error("Account verification failed - aborting scraper")
                return None

            time.sleep(3)

            # 5. Extract pool_size and pool_used
            pool_data = self._extract_pool_data()
            if pool_data:
                self.pool_used, self.pool_size = pool_data
                self.logger.info(f"Pool data extracted: used={self.pool_used} bytes, size={self.pool_size} bytes")
            else:
                self.logger.warning("Could not extract pool data, continuing without pool data...")

            # 6. Navigate to Overview tab
            overview_tab_xpath = '//*[@id="navOpen"]/li[1]/a'
            self.logger.info("Clicking on Overview tab...")
            self.browser_wrapper.click_element(overview_tab_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(5)

            # 7. Click on "Go to Telus IQ"
            telus_iq_button_xpath = (
                "/html/body/div[5]/div/div/div/div[1]/div/div[3]/div/div/div/div/div/div[3]/div/div/a"
            )
            self.logger.info("Clicking on 'Go to Telus IQ' button...")
            self.browser_wrapper.click_element(telus_iq_button_xpath)
            self.logger.info("Waiting 30 seconds for Telus IQ to load...")
            time.sleep(30)

            # 8. Handle Bill Analyzer modal if it appears
            self._dismiss_bill_analyzer_modal()

            # 9. Click on Manage tab
            manage_tab_xpath = '//*[@id="site-header__root"]/div[1]/div/div/div/div/ul[1]/li[2]/a'
            self.logger.info("Clicking on Manage tab...")
            self.browser_wrapper.click_element(manage_tab_xpath)
            time.sleep(3)

            # 10. Click on Usage View option
            usage_view_xpath = '//*[@id="site-header__root"]/div[2]/div/div/div/div/div[2]/div[1]/div[3]/div/a'
            self.logger.info("Verifying 'Usage view' option...")

            # Validate it actually says "Usage view"
            if self.browser_wrapper.find_element_by_xpath(usage_view_xpath, timeout=5000):
                link_text = self.browser_wrapper.get_text(usage_view_xpath)
                if "Usage view" in link_text:
                    self.logger.info("Clicking on 'Usage view' option...")
                    self.browser_wrapper.click_element(usage_view_xpath)
                else:
                    self.logger.warning(f"Unexpected text in link: '{link_text}', attempting click anyway...")
                    self.browser_wrapper.click_element(usage_view_xpath)
            else:
                self.logger.error("'Usage view' option not found")
                return None

            self.logger.info("Waiting 15 seconds for Usage View to load...")
            time.sleep(15)

            # 11. Configure advanced search with BAN
            if not self._configure_advanced_search(billing_cycle):
                self.logger.error("Advanced search configuration failed")
                return None

            self.logger.info("Navigation to daily usage section completed")
            return {
                "section": "daily_usage",
                "ready_for_export": True,
                "pool_size": self.pool_size,
                "pool_used": self.pool_used,
            }

        except Exception as e:
            self.logger.error(f"Error navigating to daily usage section: {str(e)}")
            return None

    def _handle_account_selection(self, billing_cycle: BillingCycle) -> bool:
        """Handles account selection screen if it appears."""
        try:
            # Check if we are on "Find your account" screen
            find_account_header_xpath = (
                "//*[@id='__next']/div/div[1]/div/div/div/div[1]/div/div[2]/div/div/div/div[1]/div/h1"
            )

            header_element = self.browser_wrapper.find_element_by_xpath(find_account_header_xpath, timeout=3000)
            if not header_element:
                self.logger.info("Account selection screen not found, continuing...")
                return True

            header_text = self.browser_wrapper.get_text(find_account_header_xpath)
            if "Find your account" not in header_text:
                self.logger.info(f"Header found but different text: '{header_text}', continuing...")
                return True

            self.logger.info("'Find your account' screen detected - selecting correct account...")
            return self._select_account_from_list(billing_cycle)

        except Exception as e:
            self.logger.error(f"Error handling account selection: {str(e)}")
            return False

    def _select_account_from_list(self, billing_cycle: BillingCycle) -> bool:
        """Selects the correct account from the available accounts list."""
        try:
            target_account_number = billing_cycle.account.number
            self.logger.info(f"Searching for account: {target_account_number}")

            # Search for div containing the specific account number
            account_number_xpath = (
                f"//div[@data-testid='account-card-north-star']//div[contains(text(), '{target_account_number}')]"
            )

            if self.browser_wrapper.find_element_by_xpath(account_number_xpath, timeout=5000):
                self.logger.info(f"Account {target_account_number} found, clicking...")
                target_card_xpath = f"//div[@data-testid='account-card-north-star'][.//div[contains(text(), '{target_account_number}')]]"
                self.browser_wrapper.click_element(target_card_xpath)
                self.browser_wrapper.wait_for_page_load()
                time.sleep(3)
                self.logger.info(f"Account {target_account_number} selected successfully")
                return True
            else:
                self.logger.error(f"Account {target_account_number} NOT found in the list")
                return False

        except Exception as e:
            self.logger.error(f"Error selecting account from list: {str(e)}")
            return False

    def _verify_current_account(self, billing_cycle: BillingCycle) -> bool:
        """Verifies that the currently selected account is correct."""
        try:
            target_account_number = billing_cycle.account.number
            self.logger.info(f"Verifying current account vs target: {target_account_number}")

            # Search for element showing current account number
            account_number_xpath = '//*[@data-testid="accountNumber"]'

            if not self.browser_wrapper.find_element_by_xpath(account_number_xpath, timeout=5000):
                self.logger.info("Account number element not found, continuing...")
                return True

            current_account = self.browser_wrapper.get_text(account_number_xpath)
            self.logger.info(f"Current account: '{current_account}'")

            if target_account_number in current_account or current_account in target_account_number:
                self.logger.info(f"Correct account confirmed: {target_account_number}")
                return True

            # Account doesn't match, need to change it
            self.logger.info(f"Incorrect account. Expected: {target_account_number}, Actual: {current_account}")
            self.logger.info("Searching for 'Change account' link...")

            # Search for "Change account" link
            change_account_xpath = '//*[@data-testid="link"]//div[contains(text(), "Change account")]'
            change_account_parent_xpath = '//*[@data-testid="link"]'

            if self.browser_wrapper.find_element_by_xpath(change_account_xpath, timeout=3000):
                self.logger.info("Clicking on 'Change account'...")
                self.browser_wrapper.click_element(change_account_parent_xpath)
                self.browser_wrapper.wait_for_page_load()
                time.sleep(5)
                return self._select_account_from_list(billing_cycle)
            else:
                self.logger.error("'Change account' link not found")
                return False

        except Exception as e:
            self.logger.error(f"Error verifying current account: {str(e)}")
            return True  # Continue if there's an error

    def _extract_pool_data(self) -> Optional[Tuple[int, int]]:
        """Extracts pool_used and pool_size from usage div and converts to bytes."""
        try:
            self.logger.info("Extracting pool data...")

            # XPath of div containing usage data
            usage_container_xpath = (
                '//*[@id="app"]/div[2]/div/div/div/div[3]/div[7]/div/div[2]/div/div[3]/div/div/div[5]'
            )

            if not self.browser_wrapper.find_element_by_xpath(usage_container_xpath, timeout=5000):
                self.logger.warning("Usage container not found")
                return None

            # Extract individual values using data-testid
            usage_used_xpath = '//*[@data-testid="usage-used"]'
            usage_allowance_xpath = '//*[@data-testid="usage-allowance"]'

            pool_used_text = None
            pool_size_text = None

            if self.browser_wrapper.find_element_by_xpath(usage_used_xpath, timeout=3000):
                pool_used_text = self.browser_wrapper.get_text(usage_used_xpath)
                self.logger.info(f"Usage used raw: '{pool_used_text}'")

            if self.browser_wrapper.find_element_by_xpath(usage_allowance_xpath, timeout=3000):
                pool_size_text = self.browser_wrapper.get_text(usage_allowance_xpath)
                self.logger.info(f"Usage allowance raw: '{pool_size_text}'")

            if not pool_used_text or not pool_size_text:
                self.logger.warning("Could not extract usage values")
                return None

            # Parse values and convert to bytes
            pool_used_bytes = self._parse_gb_to_bytes(pool_used_text)
            pool_size_bytes = self._parse_gb_to_bytes(pool_size_text)

            if pool_used_bytes is not None and pool_size_bytes is not None:
                self.logger.info(f"Pool used: {pool_used_bytes} bytes ({pool_used_text})")
                self.logger.info(f"Pool size: {pool_size_bytes} bytes ({pool_size_text})")
                return (pool_used_bytes, pool_size_bytes)
            else:
                self.logger.warning("Error parsing pool values")
                return None

        except Exception as e:
            self.logger.error(f"Error extracting pool data: {str(e)}")
            return None

    def _parse_gb_to_bytes(self, value_text: str) -> Optional[int]:
        """Parses a GB value to bytes."""
        try:
            # Clean text and extract number
            # Examples: "47.13", "601 GB", "47.13 GB"
            cleaned = value_text.strip().replace(",", "")

            # Extract only the number (may have decimals)
            match = re.search(r"([\d.]+)", cleaned)
            if not match:
                return None

            value = float(match.group(1))

            # Convert GB to bytes (1 GB = 1024^3 bytes)
            bytes_value = int(value * (1024**3))
            return bytes_value

        except Exception as e:
            self.logger.error(f"Error parsing '{value_text}' to bytes: {str(e)}")
            return None

    def _dismiss_bill_analyzer_modal(self) -> bool:
        """Detects and closes Bill Analyzer modal if it appears."""
        try:
            # Search for "don't show again" button in Bill Analyzer modal
            dont_show_again_xpath = "/html/body/div[1]/html/body/div/div/div/div[2]/div/div[2]/div[2]/div[1]/div/div/div[3]/div/div[2]/p/div/a"

            if self.browser_wrapper.find_element_by_xpath(dont_show_again_xpath, timeout=5000):
                self.logger.info("Bill Analyzer modal detected, closing...")
                self.browser_wrapper.click_element(dont_show_again_xpath)
                time.sleep(2)
                self.logger.info("Bill Analyzer modal closed")
                return True
            else:
                self.logger.info("Bill Analyzer modal not detected, continuing...")
                return True

        except Exception as e:
            self.logger.warning(f"Error handling Bill Analyzer modal: {str(e)}")
            return True  # Continue anyway

    def _configure_advanced_search(self, billing_cycle: BillingCycle) -> bool:
        """Configures advanced search with account BAN."""
        try:
            target_account = billing_cycle.account.number
            self.logger.info(f"Configuring advanced search for account: {target_account}")

            # 1. Click on Advanced search toggle
            advanced_toggle_xpath = '//*[@id="advanced__search__toggle"]'
            self.logger.info("Clicking on Advanced search toggle...")
            self.browser_wrapper.click_element(advanced_toggle_xpath)
            time.sleep(2)

            # 2. Verify advanced search panel is open
            advanced_panel_xpath = '//*[@id="advanced__search"]'
            if not self.browser_wrapper.find_element_by_xpath(advanced_panel_xpath, timeout=5000):
                self.logger.error("Advanced search panel did not open")
                return False

            self.logger.info("Advanced search panel opened")

            # 3. Select "Account number (BAN)" in first dropdown
            filter_select_xpath = '//*[@id="advancedsearchselect"]'
            self.logger.info("Selecting 'Account number (BAN)' in filter dropdown...")
            self.browser_wrapper.select_dropdown_by_value(filter_select_xpath, "accountnum")
            time.sleep(2)

            # 4. Select account number in second dropdown
            account_input_xpath = '//*[@id="advancedsearchinput"]'
            self.logger.info(f"Selecting account {target_account} in value dropdown...")
            self.browser_wrapper.select_dropdown_by_value(account_input_xpath, target_account)
            time.sleep(2)

            # 5. Click on Add button
            add_button_xpath = "//a[contains(@class, 'advanced__search__button')]"
            self.logger.info("Clicking on Add button...")
            self.browser_wrapper.click_element(add_button_xpath)
            time.sleep(2)

            # 6. Click on Show results button
            show_results_xpath = "//button[contains(@class, 'show__result__button')]"
            self.logger.info("Clicking on Show results button...")

            # Verify button is not disabled
            if self.browser_wrapper.find_element_by_xpath(show_results_xpath, timeout=3000):
                # Check if it has 'disabled' class
                button_class = self.browser_wrapper.get_attribute(show_results_xpath, "class")
                if "disabled" not in button_class:
                    self.browser_wrapper.click_element(show_results_xpath)
                    self.logger.info("Waiting for results...")
                    time.sleep(10)
                else:
                    self.logger.warning("Show results button is disabled, continuing...")

            self.logger.info("Advanced search configured successfully")
            return True

        except Exception as e:
            self.logger.error(f"Error configuring advanced search: {str(e)}")
            return False

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Downloads daily usage files from Telus IQ."""
        downloaded_files = []

        # Get BillingCycleDailyUsageFile from billing_cycle
        daily_usage_file = billing_cycle.daily_usage_files[0] if billing_cycle.daily_usage_files else None
        if daily_usage_file:
            self.logger.info(f"Mapping Daily Usage file -> BillingCycleDailyUsageFile ID {daily_usage_file.id}")

        try:
            self.logger.info("=== STARTING EXPORT PROCESS ===")

            # 1. Click on Export View button
            export_view_xpath = (
                '//*[@id="app"]/html/body/div/div/div/div[2]/div[3]/div[1]/div[11]/div[2]/div/div[2]/div/div[2]'
            )
            # More specific alternative XPath
            export_view_alt_xpath = "//div[contains(@class, 'export')]//div[contains(text(), 'Export')]"

            self.logger.info("Searching for Export View button...")
            if self.browser_wrapper.find_element_by_xpath(export_view_xpath, timeout=5000):
                self.logger.info("Clicking on Export View button...")
                self.browser_wrapper.click_element(export_view_xpath)
            elif self.browser_wrapper.find_element_by_xpath(export_view_alt_xpath, timeout=3000):
                self.logger.info("Clicking on Export View button (alternative)...")
                self.browser_wrapper.click_element(export_view_alt_xpath)
            else:
                self.logger.error("Export View button not found")
                return downloaded_files

            time.sleep(3)

            # 2. Generate report name: "Daily Usage Report" + date mm-dd-yyyy
            current_date = datetime.now()
            report_name = f"Daily Usage Report {current_date.strftime('%m-%d-%Y')}"
            self.logger.info(f"Report name: {report_name}")

            # 3. Write in modal input
            report_input_xpath = '//*[@id="reportname"]'
            if self.browser_wrapper.find_element_by_xpath(report_input_xpath, timeout=5000):
                self.logger.info("Writing report name...")
                self.browser_wrapper.clear_and_type(report_input_xpath, report_name)
                time.sleep(1)
            else:
                self.logger.error("Report name input not found")
                return downloaded_files

            # 4. Click on Continue button
            continue_button_xpath = '//*[@id="confirmation__dialog1"]/div/div[2]/a[2]'
            self.logger.info("Clicking on Continue button...")
            self.browser_wrapper.click_element(continue_button_xpath)
            self.logger.info("Waiting 3 minutes for report generation...")
            time.sleep(180)

            # 5. Monitor results table and download
            # Pass account number to validate BAN in table
            target_account = billing_cycle.account.number
            download_info = self._monitor_results_table_and_download(report_name, daily_usage_file, target_account)

            if download_info:
                downloaded_files.append(download_info)
                self.logger.info(f"Report downloaded: {download_info.file_name}")
            else:
                self.logger.error("Could not download report")

            # 6. Reset to main screen
            self._reset_to_main_screen()

            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error in daily usage download: {str(e)}")
            try:
                self._reset_to_main_screen()
            except:
                pass
            return downloaded_files

    def _monitor_results_table_and_download(
        self, report_name: str, daily_usage_file, target_account: str
    ) -> Optional[FileDownloadInfo]:
        """Monitors results table and downloads when ready.

        Args:
            report_name: Report name to search for
            daily_usage_file: Daily usage file for mapping
            target_account: Account number (BAN) to validate
        """
        max_attempts = 2  # Maximum 2 attempts (3 min + 3 min = 6 min total)
        attempt = 0

        while attempt < max_attempts:
            try:
                attempt += 1
                self.logger.info(f"Attempt {attempt}/{max_attempts} - Checking results table...")

                # Check if dynamic table exists
                dynamic_table_xpath = '//*[@id="dynamicTable"]'

                if not self.browser_wrapper.find_element_by_xpath(dynamic_table_xpath, timeout=10000):
                    self.logger.info("Dynamic table not found, waiting 3 more minutes...")
                    time.sleep(180)
                    continue

                self.logger.info("Dynamic table found")

                # Find correct row: name + BAN + most recent date
                report_row = self._find_best_report_row(report_name, target_account)

                if not report_row:
                    self.logger.info(
                        f"Report '{report_name}' with BAN '{target_account}' not found, waiting 3 more minutes..."
                    )
                    time.sleep(180)
                    continue

                self.logger.info(f"Report '{report_name}' found in row {report_row}")

                # Check status (column 3 - Status)
                download_link = self._get_download_link_for_report(report_row)

                if download_link:
                    link_text = self.browser_wrapper.get_text(download_link)
                    self.logger.info(f"Report status: {link_text}")

                    if "Download" in link_text:
                        self.logger.info("Report ready for download!")

                        # Download file
                        downloaded_file_path = self.browser_wrapper.expect_download_and_click(
                            download_link, timeout=60000, downloads_dir=self.job_downloads_dir
                        )

                        if downloaded_file_path:
                            actual_filename = os.path.basename(downloaded_file_path)
                            self.logger.info(f"File downloaded: {actual_filename}")

                            file_info = FileDownloadInfo(
                                file_id=daily_usage_file.id if daily_usage_file else 1,
                                file_name=actual_filename,
                                download_url="N/A",
                                file_path=downloaded_file_path,
                                daily_usage_file=daily_usage_file,
                            )

                            if daily_usage_file:
                                self.logger.info(
                                    f"MAPPING CONFIRMED: {actual_filename} -> BillingCycleDailyUsageFile ID {daily_usage_file.id}"
                                )

                            return file_info
                        else:
                            self.logger.error("Error downloading file")
                            return None

                    elif "In Queue" in link_text or "queue" in link_text.lower():
                        self.logger.info("Report in queue, waiting 3 more minutes...")
                        time.sleep(180)
                        continue
                    else:
                        self.logger.info(f"Unknown status: {link_text}, waiting 3 more minutes...")
                        time.sleep(180)
                        continue
                else:
                    self.logger.info("Download link not found, waiting 3 more minutes...")
                    time.sleep(180)
                    continue

            except Exception as e:
                self.logger.error(f"Error in attempt {attempt}: {str(e)}")
                if attempt < max_attempts:
                    time.sleep(180)
                continue

        self.logger.error("Maximum attempts reached without being able to download report")
        return None

    def _find_best_report_row(self, report_name: str, target_account: str) -> Optional[int]:
        """Finds the best row matching the report.

        Criteria:
        1. Report name must match (column 2)
        2. BAN must match target_account OR say "Multiple" (column 5)
        3. From matches, choose the one with most recent Date generated (column 8)

        Table has separated column structure:
        - Column 1: empty (firstColumnId)
        - Column 2: Report name
        - Column 3: Status (Download/In Queue)
        - Column 4: Report type
        - Column 5: BAN
        - Column 6: Submitted by
        - Column 7: Date submitted
        - Column 8: Date generated
        - Column 9: empty (lastColumnId)

        Returns:
            int: Row index (1-based) or None if not found
        """
        try:
            self.logger.info(f"Searching for report '{report_name}' with BAN '{target_account}'...")

            candidates = []  # List of tuples: (row_index, date_generated_text)

            # Scan up to 10 rows looking for matches
            for i in range(1, 11):
                # Get report name (column 2)
                name_xpath = (
                    f"//div[contains(@class, 'new__dynamic__table__column')][2]"
                    f"//div[contains(@class, 'new-dynamic-table__table__cell')][{i}]//span"
                )

                if not self.browser_wrapper.find_element_by_xpath(name_xpath, timeout=1000):
                    break  # No more rows

                name_text = self.browser_wrapper.get_text(name_xpath).strip()

                # Check if name matches
                if report_name not in name_text:
                    self.logger.debug(f"Row {i}: name '{name_text}' doesn't match")
                    continue

                self.logger.debug(f"Row {i}: name matches '{name_text}'")

                # Get BAN (column 5)
                ban_xpath = (
                    f"//div[contains(@class, 'new__dynamic__table__column')][5]"
                    f"//div[contains(@class, 'new-dynamic-table__table__cell')][{i}]//span"
                )

                if self.browser_wrapper.find_element_by_xpath(ban_xpath, timeout=1000):
                    ban_text = self.browser_wrapper.get_text(ban_xpath).strip()
                    self.logger.debug(f"Row {i}: BAN = '{ban_text}'")

                    # Validate BAN: must be account number OR "Multiple"
                    if target_account not in ban_text and "Multiple" not in ban_text:
                        self.logger.debug(f"Row {i}: BAN doesn't match (expected: {target_account})")
                        continue
                else:
                    self.logger.debug(f"Row {i}: could not get BAN")
                    continue

                # Get Date generated (column 8)
                date_xpath = (
                    f"//div[contains(@class, 'new__dynamic__table__column')][8]"
                    f"//div[contains(@class, 'new-dynamic-table__table__cell')][{i}]//span"
                )

                date_text = ""
                if self.browser_wrapper.find_element_by_xpath(date_xpath, timeout=1000):
                    date_text = self.browser_wrapper.get_text(date_xpath).strip()
                    self.logger.debug(f"Row {i}: Date generated = '{date_text}'")

                # This row is a candidate
                candidates.append((i, date_text))
                self.logger.info(f"Row {i} is candidate: name='{name_text}', BAN='{ban_text}', date='{date_text}'")

            if not candidates:
                self.logger.warning(f"No rows found with report '{report_name}' and BAN '{target_account}'")
                return None

            if len(candidates) == 1:
                self.logger.info(f"Single match found: row {candidates[0][0]}")
                return candidates[0][0]

            # Multiple candidates: choose most recent by Date generated
            self.logger.info(f"Found {len(candidates)} candidates, selecting most recent...")
            best_row = self._select_most_recent_row(candidates)
            self.logger.info(f"Selected row (most recent): {best_row}")
            return best_row

        except Exception as e:
            self.logger.error(f"Error searching for report in table: {str(e)}")
            return None

    def _select_most_recent_row(self, candidates: List[Tuple[int, str]]) -> int:
        """Selects the row with most recent date.

        Args:
            candidates: List of tuples (row_index, date_text)
                       date_text format: "Dec 25, 2025 17:37 CST"

        Returns:
            int: Index of most recent row
        """
        try:
            parsed_candidates = []

            for row_index, date_text in candidates:
                try:
                    # Parse date: "Dec 25, 2025 17:37 CST"
                    # Remove timezone for parsing
                    date_clean = date_text.replace(" CST", "").replace(" EST", "").replace(" PST", "").strip()
                    parsed_date = datetime.strptime(date_clean, "%b %d, %Y %H:%M")
                    parsed_candidates.append((row_index, parsed_date))
                except ValueError as e:
                    self.logger.warning(f"Could not parse date '{date_text}': {e}")
                    # Use minimum date if can't parse
                    parsed_candidates.append((row_index, datetime.min))

            # Sort by date descending (most recent first)
            parsed_candidates.sort(key=lambda x: x[1], reverse=True)

            # Return index of most recent row
            return parsed_candidates[0][0]

        except Exception as e:
            self.logger.error(f"Error selecting most recent row: {e}")
            # Fallback: return first candidate
            return candidates[0][0]

    def _get_download_link_for_report(self, row_index: int) -> Optional[str]:
        """Gets XPath of download link for a specific row.

        Args:
            row_index: Row index (1-based)

        Returns:
            str: Download link XPath or None if not found
        """
        try:
            # Status column is the third column
            download_link_xpath = (
                f"//div[contains(@class, 'new__dynamic__table__column')][3]"
                f"//div[contains(@class, 'new-dynamic-table__table__cell')][{row_index}]"
                f"//a[contains(@class, 'download-anchor')]"
            )

            if self.browser_wrapper.find_element_by_xpath(download_link_xpath, timeout=3000):
                return download_link_xpath

            # Alternative: search for link without specific class
            alt_download_xpath = (
                f"//div[contains(@class, 'new__dynamic__table__column')][3]"
                f"//div[contains(@class, 'new-dynamic-table__table__cell')][{row_index}]"
                f"//a"
            )

            if self.browser_wrapper.find_element_by_xpath(alt_download_xpath, timeout=3000):
                return alt_download_xpath

            return None

        except Exception as e:
            self.logger.error(f"Error getting download link: {str(e)}")
            return None

    def _reset_to_main_screen(self):
        """Resets to Telus main screen."""
        try:
            self.logger.info("Resetting to My Telus...")
            self.browser_wrapper.goto("https://www.telus.com/my-telus")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)
            self.logger.info("Reset completed")
        except Exception as e:
            self.logger.error(f"Error in reset: {str(e)}")

    def get_pool_data(self) -> Dict[str, Optional[int]]:
        """Returns pool data extracted during navigation.

        Returns:
            Dict with pool_size and pool_used in bytes
        """
        return {
            "pool_size": self.pool_size,
            "pool_used": self.pool_used,
        }
