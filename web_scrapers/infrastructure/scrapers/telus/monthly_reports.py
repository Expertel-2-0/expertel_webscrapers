import logging
import os
import time
from typing import Any, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    FileDownloadInfo,
    MonthlyReportsScraperStrategy,
)
from web_scrapers.domain.enums import TelusFileSlug

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class TelusMonthlyReportsScraperStrategy(MonthlyReportsScraperStrategy):
    """Monthly reports scraper for Telus."""

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navigates to Telus monthly reports section."""
        try:
            self.logger.info("Navigating to Telus monthly reports...")

            # 1. Navigate to My Telus
            self.logger.info("Navigating to My Telus...")
            self.browser_wrapper.goto("https://www.telus.com/my-telus")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(5)

            self.logger.info("Initial navigation completed - ready for file download")
            return {"section": "monthly_reports", "ready_for_download": True}

        except Exception as e:
            self.logger.error(f"Error navigating to monthly reports: {str(e)}")
            return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Downloads Telus monthly report files."""
        downloaded_files = []

        # Map BillingCycleFiles by slug
        billing_cycle_file_map = {}
        if billing_cycle.billing_cycle_files:
            for bcf in billing_cycle.billing_cycle_files:
                if bcf.carrier_report and bcf.carrier_report.slug:
                    billing_cycle_file_map[bcf.carrier_report.slug] = bcf
                    self.logger.info(f"Mapping BillingCycleFile ID {bcf.id} -> Slug: '{bcf.carrier_report.slug}'")

        try:
            # === PART 1: DOWNLOAD ZIP FROM BILLS SECTION ===
            self.logger.info("=== PART 1: DOWNLOADING ZIP FROM BILLS SECTION ===")

            # 1. Click on bill options button
            bill_options_xpath = (
                "/html/body/div[5]/div/div/div/div[1]/div/div[3]/div/div/div/div/div/div[3]/div/div/div/div"
            )
            self.logger.info("Clicking on bill options...")
            self.browser_wrapper.click_element(bill_options_xpath)

            # 2. Immediate click on text-bill link (menu appears and disappears from DOM)
            text_bill_xpath = "//a[@href='/my-telus/text-bill?intcmp=tcom_mt_overview_button_download-text-bill']"
            self.logger.info("Clicking on text-bill link...")
            time.sleep(0.5)  # Brief wait for menu to appear
            self.browser_wrapper.click_element(text_bill_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)

            # 3. Handle possible account selection screen (first time)
            if not self._handle_account_selection(billing_cycle):
                self.logger.error("Initial account selection failed - aborting scraper")
                return downloaded_files
            time.sleep(2)

            # 4. Verify current account is correct (case of previous session with different account)
            if not self._verify_current_account(billing_cycle):
                self.logger.error("Current account verification failed - aborting scraper")
                return downloaded_files
            time.sleep(2)

            # 5. Find and click on correct month based on end_date
            target_month = billing_cycle.end_date.strftime("%B")
            target_year = billing_cycle.end_date.year

            self.logger.info(f"Searching for month: {target_month} {target_year}")

            # 6. Download ZIP by clicking on month (click directly downloads ZIP)
            zip_file_path = self._click_month_and_download_zip(target_month, target_year)

            if zip_file_path:
                # 7. Process files extracted from ZIP
                zip_files = self._process_downloaded_zip(zip_file_path, billing_cycle_file_map)
                downloaded_files.extend(zip_files)
                self.logger.info(f"Part 1 completed: {len(zip_files)} files from ZIP")
            else:
                self.logger.info("Could not download ZIP for target month")

            # === PART 2: DOWNLOAD MOBILITY DEVICE SUMMARY FROM DETAIL REPORTS ===
            # ZIP files (group_summary, individual_detail) were obtained in Part 1.
            # Here we download mobility_device from Detail Reports in Telus IQ.

            self.logger.info("=== PART 2: DOWNLOADING MOBILITY DEVICE FROM DETAIL REPORTS ===")

            # 1. Navigate to billing header (Telus IQ)
            billing_header_xpath = '//*[@id="navOpen"]/li[2]/a'
            self.logger.info("Clicking on billing header...")
            self.browser_wrapper.click_element(billing_header_xpath)
            self.logger.info("Waiting 30 seconds...")
            time.sleep(30)

            # 1.1. Detect and close Bill Analyzer modal if it appears
            self._dismiss_bill_analyzer_modal()

            # 2. Click on reports header
            reports_header_xpath = '//*[@id="navMenuGroupReports"]'
            self.logger.info("Clicking on reports header...")
            self.browser_wrapper.click_element(reports_header_xpath)
            time.sleep(2)

            # 3. Click on Detail Reports
            detail_reports_xpath = '//*[@id="navMenuItem6"]'
            self.logger.info("Clicking on Detail Reports...")
            self.browser_wrapper.click_element(detail_reports_xpath)
            self.browser_wrapper.wait_for_page_load()
            self.logger.info("Waiting 30 seconds...")
            time.sleep(30)

            # 4. Download Mobility Device Summary (includes Scope and Date Range filter configuration)
            individual_files = self._download_individual_reports(billing_cycle, billing_cycle_file_map)
            downloaded_files.extend(individual_files)
            self.logger.info(f"Part 2 completed: {len(individual_files)} individual files")

            # Reset to main screen
            self._reset_to_main_screen()

            self.logger.info(f"TOTAL DOWNLOAD COMPLETED: {len(downloaded_files)} files")
            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error downloading files: {str(e)}")
            try:
                self._reset_to_main_screen()
            except:
                pass
            return downloaded_files

    def _handle_account_selection(self, billing_cycle: BillingCycle) -> bool:
        """Handles account selection screen if it appears (for credentials with multiple accounts)."""
        try:
            # Check if we are on "Find your account" screen
            find_account_header_xpath = (
                "//*[@id='__next']/div/div[1]/div/div/div/div[1]/div/div[2]/div/div/div/div[1]/div/h1"
            )

            header_element = self.browser_wrapper.find_element_by_xpath(find_account_header_xpath)
            if not header_element:
                self.logger.info("Account selection screen not found, continuing...")
                return True

            # Verify header text
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
        """Selects the correct account from the list of available accounts."""
        try:

            target_account_number = billing_cycle.account.number
            self.logger.info(f"Searching for account: {target_account_number}")

            # Search for div containing specific account number
            account_number_xpath = (
                f"//div[@data-testid='account-card-north-star']//div[contains(text(), '{target_account_number}')]"
            )

            if self.browser_wrapper.find_element_by_xpath(account_number_xpath):
                self.logger.info(f"Account {target_account_number} found, clicking...")
                target_card_xpath = f"//div[@data-testid='account-card-north-star'][.//div[contains(text(), '{target_account_number}')]]"
                self.browser_wrapper.click_element(target_card_xpath)
                self.browser_wrapper.wait_for_page_load()
                time.sleep(3)
                self.logger.info(f"Account {target_account_number} selected successfully")
                return True
            else:
                self.logger.error(f"Account {target_account_number} NOT found in available accounts list")
                return False

        except Exception as e:
            self.logger.error(f"Error selecting account from list: {str(e)}")
            return False

    def _verify_current_account(self, billing_cycle: BillingCycle) -> bool:
        """
        Verifies that currently selected account is correct.
        This method is used right before downloading ZIP, where header shows 'Account #XXXXXXXX'.
        If account doesn't match, clicks 'Change' and selects correct account.
        """
        try:
            target_account_number = billing_cycle.account.number
            self.logger.info(f"Verifying current account vs target: {target_account_number}")

            # Search for element showing current account
            # Structure: <div>Account #42680715</div> followed by <a>Change</a>
            account_header_xpath = "//*[@id='app']/div/div[2]/div/div[1]/div/div[2]"

            if not self.browser_wrapper.find_element_by_xpath(account_header_xpath):
                self.logger.info("Account header not found (single account credentials), continuing...")
                return True

            # Get account header text
            account_header_text = self.browser_wrapper.get_text(account_header_xpath)
            self.logger.info(f"Account header found: '{account_header_text}'")

            # Verify target account number is in header
            if target_account_number in account_header_text:
                self.logger.info(f"Correct account confirmed: {target_account_number}")
                return True

            # Account doesn't match, need to change it
            self.logger.info(
                f"Incorrect account detected. Expected: {target_account_number}, Actual: {account_header_text}"
            )
            self.logger.info("Clicking 'Change' to switch account...")

            # Find and click 'Change' link
            change_link_xpath = "//*[@id='app']/div/div[2]/div/div[1]/div/div[2]//a[contains(text(), 'Change')]"
            # More specific alternative based on provided structure
            change_link_alt_xpath = "//a[.//div[contains(text(), 'Change')]]"

            if self.browser_wrapper.find_element_by_xpath(change_link_xpath):
                self.browser_wrapper.click_element(change_link_xpath)
            elif self.browser_wrapper.find_element_by_xpath(change_link_alt_xpath):
                self.browser_wrapper.click_element(change_link_alt_xpath)
            else:
                self.logger.error("'Change' link not found")
                return False

            time.sleep(5)

            self.logger.info("Navigating to account selection screen...")
            return self._select_account_from_list(billing_cycle)

        except Exception as e:
            self.logger.error(f"Error verifying current account: {str(e)}")
            return True

    def _click_month_and_download_zip(self, target_month: str, target_year: int) -> Optional[str]:
        """Searches for target month within year section and downloads ZIP."""
        try:
            self.logger.info(f"Download directory configured: {self.job_downloads_dir}")

            # Find the year header
            year_xpath = f"//h2[contains(text(), '{target_year}')]"
            if not self.browser_wrapper.find_element_by_xpath(year_xpath):
                self.logger.error(f"Year {target_year} not found")
                return None

            self.logger.info(f"Found year {target_year}")

            # Find month whose closest preceding h2 is the target year
            month_in_year_xpath = (
                f"//div[@role='link'][.//div[contains(text(), '{target_month}')]]"
                f"[preceding::h2[1][contains(text(), '{target_year}')]]"
            )

            if not self.browser_wrapper.find_element_by_xpath(month_in_year_xpath):
                self.logger.error(f"Month {target_month} not found in year {target_year}")
                return None

            self.logger.info(f"Found month {target_month} in year {target_year}, downloading ZIP...")

            # Log for debugging
            try:
                element_text = self.browser_wrapper.get_text(month_in_year_xpath)
                self.logger.info(f"Element to click: '{element_text[:100] if element_text else 'None'}...'")
            except Exception as e:
                self.logger.warning(f"Could not get element text: {str(e)}")

            zip_file_path = self.browser_wrapper.expect_download_and_click(
                month_in_year_xpath, timeout=60000, downloads_dir=self.job_downloads_dir
            )

            if zip_file_path:
                self.logger.info(f"ZIP downloaded successfully: {zip_file_path}")
                return zip_file_path
            else:
                self.logger.error("expect_download_and_click returned None")
                # Check if file was downloaded anyway
                if self.job_downloads_dir and os.path.exists(self.job_downloads_dir):
                    files_in_dir = os.listdir(self.job_downloads_dir)
                    self.logger.info(f"Files in download directory: {files_in_dir}")
                    # Search for ZIP files
                    zip_files = [f for f in files_in_dir if f.endswith(".zip")]
                    if zip_files:
                        zip_file_path = os.path.join(self.job_downloads_dir, zip_files[0])
                        self.logger.info(f"ZIP found manually: {zip_file_path}")
                        return zip_file_path
                return None

        except Exception as e:
            self.logger.error(f"Error downloading month ZIP: {str(e)}")
            return None

    def _process_downloaded_zip(self, zip_file_path: str, file_map: dict) -> List[FileDownloadInfo]:
        """
        Processes downloaded ZIP, extracts files and maps to BillingCycleFiles.
        IMPORTANT: Only files with valid mapping are added to downloaded_files.
        Only needed from ZIP: individual_detail, group_summary
        """
        downloaded_files = []

        try:
            self.logger.info(f"Processing ZIP: {os.path.basename(zip_file_path)}")

            # Extract files from ZIP
            extracted_files = self._extract_zip_files(zip_file_path)
            if not extracted_files:
                self.logger.error("Could not extract files from ZIP")
                return downloaded_files

            self.logger.info(f"Extracted {len(extracted_files)} files from ZIP")

            # Process extracted files and map them
            # ONLY add files with valid mapping (individual_detail, group_summary)
            for file_path in extracted_files:
                original_filename = os.path.basename(file_path)
                self.logger.info(f"Processing file: {original_filename}")

                # Find corresponding BillingCycleFile
                corresponding_bcf = self._find_matching_billing_cycle_file(original_filename, file_map)

                if corresponding_bcf:
                    self.logger.info(f"Mapping {original_filename} -> BillingCycleFile ID {corresponding_bcf.id}")
                    file_info = FileDownloadInfo(
                        file_id=corresponding_bcf.id,
                        file_name=original_filename,
                        download_url="N/A",
                        file_path=file_path,
                        billing_cycle_file=corresponding_bcf,
                    )
                    downloaded_files.append(file_info)
                else:
                    self.logger.info(f"File {original_filename} without mapping - NOT added to upload list")

            self.logger.info(f"Total ZIP files with valid mapping: {len(downloaded_files)}")
            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error processing ZIP: {str(e)}")
            return downloaded_files

    def _download_and_process_zip(self, billing_cycle: BillingCycle, file_map: dict) -> List[FileDownloadInfo]:
        """Downloads and processes ZIP with month files."""
        downloaded_files = []

        try:
            self.logger.info(f"Download directory configured: {self.job_downloads_dir}")

            # Possible XPaths for ZIP download link
            zip_download_xpaths = [
                "//a[contains(@href, '.zip') or contains(text(), 'download') or contains(text(), 'Download')]",
                "//button[contains(text(), 'download') or contains(text(), 'Download')]",
                "//div[contains(@class, 'download')]//a",
            ]

            zip_file_path = None
            for xpath in zip_download_xpaths:
                try:
                    if self.browser_wrapper.find_element_by_xpath(xpath):
                        self.logger.info(f"Element found with xpath: {xpath}")
                        self.logger.info(f"Attempting ZIP download to: {self.job_downloads_dir}")
                        zip_file_path = self.browser_wrapper.expect_download_and_click(
                            xpath, timeout=60000, downloads_dir=self.job_downloads_dir
                        )
                        self.logger.info(f"Download result: {zip_file_path}")
                        if zip_file_path:
                            break
                except Exception as e:
                    self.logger.error(f"Error with xpath {xpath}: {str(e)}")
                    continue

            if not zip_file_path:
                self.logger.error(f"Could not download ZIP. Checking directory: {self.job_downloads_dir}")
                # List files in download directory for diagnostics
                if self.job_downloads_dir and os.path.exists(self.job_downloads_dir):
                    files_in_dir = os.listdir(self.job_downloads_dir)
                    self.logger.info(f"Files in download directory: {files_in_dir}")
                return downloaded_files

            self.logger.info(f"ZIP downloaded: {os.path.basename(zip_file_path)}")

            # Extract files from ZIP
            extracted_files = self._extract_zip_files(zip_file_path)
            if not extracted_files:
                self.logger.info("Could not extract files from ZIP")
                return downloaded_files

            self.logger.info(f"Extracted {len(extracted_files)} files from ZIP")

            # Process extracted files and map them
            for i, file_path in enumerate(extracted_files):
                original_filename = os.path.basename(file_path)
                self.logger.info(f"Processing file: {original_filename}")

                # Find corresponding BillingCycleFile
                corresponding_bcf = self._find_matching_billing_cycle_file(original_filename, file_map)

                if corresponding_bcf:
                    self.logger.info(f"Mapping {original_filename} -> BillingCycleFile ID {corresponding_bcf.id}")
                else:
                    self.logger.info(f"No mapping found for {original_filename}")

                file_info = FileDownloadInfo(
                    file_id=corresponding_bcf.id if corresponding_bcf else (i + 1000),  # Offset for ZIP files
                    file_name=original_filename,
                    download_url="N/A",
                    file_path=file_path,
                    billing_cycle_file=corresponding_bcf,
                )
                downloaded_files.append(file_info)

            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error processing ZIP: {str(e)}")
            return downloaded_files

    def _find_matching_billing_cycle_file(self, filename: str, file_map: dict) -> Optional[Any]:
        """
        Finds BillingCycleFile matching the filename.
        NOTE: Only maps ZIP files (individual_detail, group_summary).
        mobility_device comes from individual reports (Part 2).
        """
        filename_lower = filename.lower()

        # Mapping of ZIP filename patterns to Telus slugs
        # Only 2 slugs from ZIP: individual_detail, group_summary
        # mobility_device is obtained from Part 2 (individual reports)
        pattern_to_slug = {
            "group_summary": TelusFileSlug.GROUP_SUMMARY.value,
            "individual_detail": TelusFileSlug.INDIVIDUAL_DETAIL.value,
        }

        for pattern, slug in pattern_to_slug.items():
            if pattern in filename_lower:
                bcf = file_map.get(slug)
                if bcf:
                    return bcf

        return None

    def _dismiss_bill_analyzer_modal(self) -> bool:
        """
        Detects and closes Bill Analyzer modal if it appears.
        This modal may appear when navigating to reports section.
        Returns True if modal was closed or if it didn't appear.
        """
        try:
            modal_button_xpath = "//*[@id='tandc-content']/div[3]/button"

            # Check if modal is present (with short timeout)
            if self.browser_wrapper.is_element_visible(modal_button_xpath, timeout=3000):
                self.logger.info("Bill Analyzer modal detected, closing...")
                self.browser_wrapper.click_element(modal_button_xpath)
                time.sleep(2)
                self.logger.info("Bill Analyzer modal closed")
                return True
            else:
                self.logger.info("Bill Analyzer modal not detected, continuing...")
                return True

        except Exception as e:
            self.logger.warning(f"Error handling Bill Analyzer modal: {str(e)}")
            return True  # Continue anyway

    def _configure_date_selection(self, billing_cycle: BillingCycle):
        """Configures date selection for individual reports."""
        try:
            # 1. Click on date selection
            date_selection_xpath = (
                "/html[1]/body[1]/div[2]/form[1]/div[1]/div[1]/div[2]/div[1]/div[1]/div[1]/button[1]"
            )
            self.logger.info("Clicking on date selection...")
            self.browser_wrapper.click_element(date_selection_xpath)
            time.sleep(2)

            # 2. Configure date dropdown
            target_period = billing_cycle.end_date.strftime("%B %Y") + " statements"
            select_date_dropdown_xpath = "/html[1]/body[1]/div[2]/form[1]/div[1]/div[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/div[1]/div[1]/select[1]"
            self.logger.info(f"Selecting period: {target_period}")

            try:
                self.browser_wrapper.select_dropdown_option(select_date_dropdown_xpath, target_period)
            except:
                # Fallback: search only by month and year without "statements"
                fallback_period = billing_cycle.end_date.strftime("%B %Y")
                self.logger.info(f"Fallback - Selecting: {fallback_period}")
                self.browser_wrapper.select_dropdown_option(select_date_dropdown_xpath, fallback_period)

            time.sleep(2)

            # 3. Click on confirm button
            confirm_button_xpath = "/html[1]/body[1]/div[2]/form[1]/div[1]/div[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/div[1]/div[5]/button[1]"
            self.logger.info("Clicking on confirm button...")
            self.browser_wrapper.click_element(confirm_button_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(5)

        except Exception as e:
            self.logger.error(f"Error configuring date: {str(e)}")
            raise

    def _configure_scope_filter(self, billing_cycle: BillingCycle) -> bool:
        """
        Configures Scope (account) filter in Telus IQ.
        Flow: open dropdown, select Accounts, search account, confirm with OK.
        """
        try:
            target_account = billing_cycle.account.number
            self.logger.info(f"Configuring Scope filter for account: {target_account}")

            # 1. Click on Scope dropdown button
            scope_button_xpath = "//*[@id='LevelDataDropdownButton']"
            self.logger.info("Clicking on Scope dropdown button...")
            self.browser_wrapper.click_element(scope_button_xpath)
            time.sleep(2)

            # 2. Click on "Accounts" option to show account list
            accounts_option_xpath = "//*[@id='LevelDataDropdownList_multipleaccounts']"
            self.logger.info("Selecting 'Accounts' option...")
            self.browser_wrapper.click_element(accounts_option_xpath)
            time.sleep(3)

            # 3. Search for account in search field or list
            search_input_xpath = "//input[contains(@placeholder, 'Search') or contains(@class, 'search')]"
            if self.browser_wrapper.find_element_by_xpath(search_input_xpath, timeout=2000):
                self.logger.info(f"Searching for account: {target_account}")
                self.browser_wrapper.clear_and_type(search_input_xpath, target_account)
                time.sleep(2)

            # 4. Find and select account in list
            account_option_xpath = f"//*[contains(text(), '{target_account}')]"
            if not self.browser_wrapper.find_element_by_xpath(account_option_xpath):
                self.logger.error(f"Account {target_account} not found in list")
                return False

            self.logger.info(f"Account {target_account} found, selecting...")
            self.browser_wrapper.click_element(account_option_xpath)
            time.sleep(2)

            # 5. Click on checkbox if it appears
            first_item_xpath = "//div[contains(@class, 'checkbox')]//input | //li[contains(@class, 'list-group-item')]//input[@type='checkbox']"
            if self.browser_wrapper.find_element_by_xpath(first_item_xpath, timeout=2000):
                self.browser_wrapper.click_element(first_item_xpath)
                time.sleep(1)

            # 6. Click on OK button to confirm Scope selection
            scope_ok_button_xpath = "//*[@id='scopeExpandedAccountMenu']/div[4]/button"
            if not self.browser_wrapper.find_element_by_xpath(scope_ok_button_xpath, timeout=3000):
                self.logger.error("Scope OK button not found")
                return False

            self.logger.info("Clicking OK button to confirm Scope...")
            self.browser_wrapper.click_element(scope_ok_button_xpath)
            time.sleep(3)

            self.logger.info(f"Scope configured for account: {target_account}")
            return True

        except Exception as e:
            self.logger.error(f"Error configuring Scope filter: {str(e)}")
            return False

    def _configure_date_range_filter(self, billing_cycle: BillingCycle) -> bool:
        """
        Configures Date Range filter in Telus IQ.
        Flow:
        1. Click on CIDPendingDataDropdownButton to open menu
        2. Iterate options in bmtype_data to find one matching year/month pattern
        3. Click on btnApply to confirm

        Value pattern: bYYYYMMDD - we search for options starting with bYYYYMM
        """
        try:
            target_month = billing_cycle.end_date.month
            target_year = billing_cycle.end_date.year
            # Pattern to search: bYYYYMM (without day)
            target_pattern = f"b{target_year}{target_month:02d}"

            self.logger.info(f"Configuring Date Range filter for: {target_month:02d}/{target_year}")
            self.logger.info(f"Searching for options starting with: {target_pattern}")

            # 1. Click on Date Range dropdown button to open menu
            date_button_xpath = "//*[@id='CIDPendingDataDropdownButton']"
            self.logger.info("Clicking on CIDPendingDataDropdownButton...")
            self.browser_wrapper.click_element(date_button_xpath)
            time.sleep(2)

            # 2. Find matching option by iterating through all options
            bmtype_select_xpath = "//*[@id='bmtype_data']"
            matching_value = self._find_matching_date_option(bmtype_select_xpath, target_pattern)

            if not matching_value:
                self.logger.error(f"No option found matching pattern: {target_pattern}")
                return False

            self.logger.info(f"Found matching option: {matching_value}")
            self.browser_wrapper.select_dropdown_by_value(bmtype_select_xpath, matching_value)
            time.sleep(1)

            # 3. Click OK to apply
            if not self._click_date_range_ok_button():
                self.logger.error("Error applying Date Range (OK button)")
                return False

            self.logger.info(f"Date Range configured successfully for {target_month:02d}/{target_year}")
            return True

        except Exception as e:
            self.logger.error(f"Error configuring Date Range filter: {str(e)}")
            return False

    def _find_matching_date_option(self, select_xpath: str, pattern: str) -> Optional[str]:
        """
        Iterates through SELECT options to find one matching the year/month pattern.

        Args:
            select_xpath: XPath of the SELECT element
            pattern: Pattern to match (e.g., 'b202511' for November 2025)

        Returns:
            The value of the matching option, or None if not found.
        """
        try:
            page = self.browser_wrapper.page

            # Get all options from the SELECT
            options = page.query_selector_all(f"xpath={select_xpath}//option")
            self.logger.info(f"Found {len(options)} options in dropdown")

            for option in options:
                value = option.get_attribute("value")
                text = option.inner_text().strip() if option else ""

                if value and value.startswith(pattern):
                    self.logger.info(f"Match found: value='{value}', text='{text}'")
                    return value

            # Log available options for debugging
            self.logger.warning(f"No match found for pattern '{pattern}'. Available options:")
            for option in options[:10]:  # Log first 10 options
                value = option.get_attribute("value")
                text = option.inner_text().strip() if option else ""
                self.logger.warning(f"  - value='{value}', text='{text}'")

            return None

        except Exception as e:
            self.logger.error(f"Error finding matching date option: {str(e)}")
            return None

    def _click_date_range_ok_button(self) -> bool:
        """Click on OK/Apply button to confirm date selection."""
        try:
            ok_button_xpath = "//*[@id='btnApply']"
            if self.browser_wrapper.find_element_by_xpath(ok_button_xpath, timeout=2000):
                self.logger.info("Clicking OK button to apply Date Range...")
                self.browser_wrapper.click_element(ok_button_xpath)
                time.sleep(3)
                return True
            return False
        except Exception as e:
            self.logger.warning(f"Error clicking OK button: {str(e)}")
            return False

    def _download_individual_reports(self, billing_cycle: BillingCycle, file_map: dict) -> List[FileDownloadInfo]:
        """
        Downloads Mobility Device Summary report from Detail Reports.
        Flow:
        1. Configure Scope (account) filter
        2. Configure Date Range filter
        3. Find "Mobility Device Summary" section in accordion
        4. Click on "Mobility Device Summary Report"
        5. Download report
        """
        downloaded_files = []

        try:
            self.logger.info("=== DOWNLOADING MOBILITY DEVICE SUMMARY ===")

            # 1. Configure Scope filter (account)
            self.logger.info("Configuring Scope filter...")
            if not self._configure_scope_filter(billing_cycle):
                self.logger.error("Could not configure Scope filter - file marked as failed")
                return downloaded_files
            time.sleep(3)

            # 2. Configure Date Range filter (REQUIRED - no fallback)
            self.logger.info("Configuring Date Range filter...")
            if not self._configure_date_range_filter(billing_cycle):
                self.logger.error("Could not configure Date Range filter - file marked as failed")
                return downloaded_files
            time.sleep(3)

            # 3. Find and expand "Mobility Device Summary" section in accordion
            # Accordion has id="accordion" and Mobility Device Summary section has id="collapse42"
            mobility_section_header_xpath = "//*[@id='heading42']"
            mobility_section_collapse_xpath = "//*[@id='collapse42']"

            # Check if section exists
            if not self.browser_wrapper.find_element_by_xpath(mobility_section_header_xpath):
                self.logger.error("'Mobility Device Summary' section not found in accordion")
                return downloaded_files

            self.logger.info("'Mobility Device Summary' section found")

            # Check if section is collapsed and expand if needed
            # Find toggle button in header
            toggle_button_xpath = "//*[@id='heading42']//button[@data-toggle='collapse']"
            if self.browser_wrapper.find_element_by_xpath(toggle_button_xpath):
                # Check if collapsed (aria-expanded="false")
                is_collapsed = self.browser_wrapper.get_attribute(toggle_button_xpath, "aria-expanded")
                if is_collapsed == "false":
                    self.logger.info("Expanding 'Mobility Device Summary' section...")
                    self.browser_wrapper.click_element(toggle_button_xpath)
                    time.sleep(2)

            # 4. Find "Mobility Device Summary Report" within section
            # Search for any button with btnSelectSummaryReport containing "Mobility Device"
            mobility_report_xpath = "//*[@id='collapse42']//button[contains(@id, 'btnSelectSummaryReport')][contains(., 'Mobility Device')]"
            # Alternative: search by partial text
            mobility_report_alt_xpath = "//*[@id='collapse42']//button[contains(text(), 'Mobility Device')]"

            report_found = False
            report_xpath_to_use = None

            if self.browser_wrapper.find_element_by_xpath(mobility_report_xpath):
                report_xpath_to_use = mobility_report_xpath
                report_found = True
            elif self.browser_wrapper.find_element_by_xpath(mobility_report_alt_xpath):
                report_xpath_to_use = mobility_report_alt_xpath
                report_found = True

            if not report_found:
                self.logger.error("'Mobility Device Summary Report' not found in Mobility Device Summary section")
                return downloaded_files

            # Verify button text
            button_text = self.browser_wrapper.get_text(report_xpath_to_use)
            self.logger.info(f"Report found: {button_text}")

            corresponding_bcf = file_map.get(TelusFileSlug.MOBILITY_DEVICE.value)
            if corresponding_bcf:
                self.logger.info(f"Using BillingCycleFile ID {corresponding_bcf.id} for mobility_device")

            # 5. Click on report to open report view
            self.logger.info("Clicking on 'Mobility Device Summary Report'...")
            self.browser_wrapper.click_element(report_xpath_to_use)
            self.logger.info("Waiting 1 minute for report to load...")
            time.sleep(60)

            # 6. Click on Export/Download button
            export_button_xpath = "//*[@id='export']"
            if not self.browser_wrapper.find_element_by_xpath(export_button_xpath, timeout=10000):
                self.logger.error("Export button not found")
                return downloaded_files

            self.logger.info("Clicking on Export button...")
            self.browser_wrapper.click_element(export_button_xpath)
            time.sleep(3)

            # 7. Select CSV format
            csv_label_xpath = "//*[@id='radCsvLabel']"
            if self.browser_wrapper.find_element_by_xpath(csv_label_xpath, timeout=5000):
                self.logger.info("Selecting CSV format...")
                self.browser_wrapper.click_element(csv_label_xpath)
                time.sleep(1)
            else:
                self.logger.warning("CSV label not found, continuing...")

            # 8. Click on OK button to download
            ok_button_xpath = "//*[@id='hrefOK']"
            if not self.browser_wrapper.find_element_by_xpath(ok_button_xpath, timeout=5000):
                self.logger.error("OK button not found")
                return downloaded_files

            self.logger.info("Clicking on OK button to download...")
            downloaded_file_path = self.browser_wrapper.expect_download_and_click(
                ok_button_xpath, timeout=60000, downloads_dir=self.job_downloads_dir
            )

            if downloaded_file_path:
                actual_filename = os.path.basename(downloaded_file_path)
                self.logger.info(f"Mobility Device downloaded: {actual_filename}")

                file_info = FileDownloadInfo(
                    file_id=corresponding_bcf.id if corresponding_bcf else len(downloaded_files) + 1,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=downloaded_file_path,
                    billing_cycle_file=corresponding_bcf,
                )
                downloaded_files.append(file_info)

                if corresponding_bcf:
                    self.logger.info(
                        f"MAPPING CONFIRMED: {actual_filename} -> BillingCycleFile ID {corresponding_bcf.id}"
                    )
            else:
                self.logger.error("Could not download Mobility Device report")

            time.sleep(5)

        except Exception as e:
            self.logger.error(f"Error downloading Mobility Device Summary: {str(e)}")

        return downloaded_files

    def _reset_to_main_screen(self):
        """Reset to Telus main screen using My Telus."""
        try:
            self.logger.info("Resetting to My Telus...")
            self.browser_wrapper.goto("https://www.telus.com/my-telus")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)
            self.logger.info("Reset completed")
        except Exception as e:
            self.logger.error(f"Error in reset: {str(e)}")
