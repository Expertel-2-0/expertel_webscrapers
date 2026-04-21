import logging
import os
import time
from datetime import date
from typing import Any, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    FileDownloadInfo,
    MonthlyReportsScraperStrategy,
)
from web_scrapers.domain.enums import VerizonFileSlug

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class VerizonMonthlyReportsScraperStrategy(MonthlyReportsScraperStrategy):
    """Monthly reports scraper for Verizon.

    Downloads 5 files total:
    - 2 from Raw Data Download ZIP (account_wireless, wireless_charges_detail)
    - Device Report (individual)
    - Activation & Deactivation Report (individual)
    - Suspended Wireless Numbers Report (individual)
    """

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navigates to Verizon reports section and opens Raw Data Download modal."""
        try:
            self.logger.info("Navigating to Verizon monthly reports...")

            # 1. Click on Reports tab
            reports_tab_xpath = '//*[@id="gNavHeader"]/div/div/div[1]/div[2]/header/div/div/div[2]/nav/ul/li[4]/a'
            self.logger.info("[Step 1/3] Clicking on Reports tab...")

            if self.browser_wrapper.is_element_visible(reports_tab_xpath, timeout=10000):
                self.browser_wrapper.click_element(reports_tab_xpath)
                time.sleep(2)
            else:
                self.logger.error("[Step 1/3 FAILED] Reports tab not found")
                self._reset_to_main_screen()
                return None

            # 2. Click on Raw Data Download (this opens a MODAL, not a new page)
            raw_data_xpath = '//*[@id="gNavHeader"]/div/div/div[1]/div[2]/header/div/div/div[2]/nav/ul/li[4]/div/div/div[1]/div/ul/li[4]/a'
            self.logger.info("[Step 2/3] Clicking on Raw Data Download...")

            if self.browser_wrapper.is_element_visible(raw_data_xpath, timeout=5000):
                self.browser_wrapper.click_element(raw_data_xpath)
                # Don't call wait_for_page_load() - this opens a modal, not a new page
                time.sleep(3)
            else:
                self.logger.error("[Step 2/3 FAILED] Raw Data Download option not found")
                self._reset_to_main_screen()
                return None

            # 3. Verify the modal is open by checking for the modal element
            modal_xpath = "//div[contains(@class, 'Modal') and contains(@class, 'is-active')]"
            self.logger.info("[Step 3/3] Waiting for Raw Data Download modal to open...")

            if self.browser_wrapper.is_element_visible(modal_xpath, timeout=10000):
                self.logger.info("[Step 3/3 SUCCESS] Modal is open - ready for file download")
                return {"section": "monthly_reports", "ready_for_download": True, "modal_open": True}
            else:
                self.logger.error("[Step 3/3 FAILED] Modal did not open after clicking Raw Data Download")
                self._reset_to_main_screen()
                return None

        except Exception as e:
            self.logger.error(f"Error navigating to monthly reports: {str(e)}")
            self._reset_to_main_screen()
            return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Downloads 5 Verizon monthly report files."""
        downloaded_files = []

        # Map BillingCycleFiles by slug
        billing_cycle_file_map = {}
        if billing_cycle.billing_cycle_files:
            for bcf in billing_cycle.billing_cycle_files:
                if bcf.carrier_report and bcf.carrier_report.slug:
                    billing_cycle_file_map[bcf.carrier_report.slug] = bcf
                    self.logger.info(f"Mapping BillingCycleFile ID {bcf.id} -> Slug: '{bcf.carrier_report.slug}'")

        try:
            # === PART 1: RAW DATA DOWNLOAD ZIP ===
            self.logger.info("=== PART 1: DOWNLOADING RAW DATA ZIP ===")
            zip_files = self._download_raw_data_zip(billing_cycle, billing_cycle_file_map)
            downloaded_files.extend(zip_files)
            self.logger.info(f"Part 1 completed: {len(zip_files)} files from ZIP")

            # === PART 2: DEVICE REPORT ===
            self.logger.info("=== PART 2: DOWNLOADING DEVICE REPORT ===")
            device_file = self._download_device_report(billing_cycle, billing_cycle_file_map)
            if device_file:
                downloaded_files.append(device_file)
                self.logger.info("Device Report downloaded")

            # === PART 3: ACTIVATION & DEACTIVATION REPORT ===
            self.logger.info("=== PART 3: DOWNLOADING ACTIVATION & DEACTIVATION REPORT ===")
            activation_file = self._download_activation_deactivation_report(billing_cycle, billing_cycle_file_map)
            if activation_file:
                downloaded_files.append(activation_file)
                self.logger.info("Activation & Deactivation Report downloaded")

            # === PART 4: SUSPENDED WIRELESS NUMBERS REPORT ===
            self.logger.info("=== PART 4: DOWNLOADING SUSPENDED WIRELESS NUMBERS REPORT ===")
            suspended_file = self._download_suspended_wireless_report(billing_cycle, billing_cycle_file_map)
            if suspended_file:
                downloaded_files.append(suspended_file)
                self.logger.info("Suspended Wireless Numbers Report downloaded")

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

    def _download_raw_data_zip(self, billing_cycle: BillingCycle, file_map: dict) -> List[FileDownloadInfo]:
        """Downloads Raw Data ZIP and extracts relevant files."""
        downloaded_files = []

        try:
            self.logger.info("=== Starting Raw Data ZIP download ===")

            # 1. Click on dropdown to open it (inside the modal)
            # Using a more robust selector that targets the dropdown inside the modal
            dropdown_xpath = "//div[contains(@class, 'Modal') and contains(@class, 'is-active')]//app-dropdown//div[@role='combobox']"
            self.logger.info("[RDD Step 1/4] Opening month dropdown...")

            if self.browser_wrapper.is_element_visible(dropdown_xpath, timeout=10000):
                self.browser_wrapper.click_element(dropdown_xpath)
                time.sleep(2)
            else:
                self.logger.error("[RDD Step 1/4 FAILED] Month dropdown not found in modal")
                self._close_modal_if_open()
                return downloaded_files

            # 2. Select month based on billing cycle end_date
            target_month_option = self._format_month_option(billing_cycle.end_date)
            self.logger.info(f"[RDD Step 2/4] Selecting month: {target_month_option}")

            # Find and click option using XPath with contains
            option_xpath = f"//ul[@role='listbox']//li[@role='option' and contains(text(), '{target_month_option}')]"
            if self.browser_wrapper.is_element_visible(option_xpath, timeout=5000):
                self.browser_wrapper.click_element(option_xpath)
                self.logger.info(f"[RDD Step 2/4 SUCCESS] Selected: {target_month_option}")
                time.sleep(1)
            else:
                self.logger.error(f"[RDD Step 2/4 FAILED] Could not find month option: {target_month_option}")
                self._close_modal_if_open()
                return downloaded_files

            # 3. Click download button inside the modal
            # Using a more robust selector that targets the Download button inside the active modal
            download_button_xpath = "//div[contains(@class, 'Modal') and contains(@class, 'is-active')]//button[contains(text(), 'Download')]"
            self.logger.info("[RDD Step 3/4] Clicking Download button...")

            zip_file_path = self.browser_wrapper.expect_download_and_click(
                download_button_xpath, timeout=120000, downloads_dir=self.job_downloads_dir
            )

            if not zip_file_path:
                self.logger.error("[RDD Step 3/4 FAILED] Could not download ZIP")
                self._close_modal_if_open()
                return downloaded_files

            self.logger.info(f"[RDD Step 3/4 SUCCESS] ZIP downloaded: {os.path.basename(zip_file_path)}")

            # Modal should close automatically after download starts, but just in case
            time.sleep(2)
            self._close_modal_if_open()

            # 4. Extract ZIP files
            self.logger.info("[RDD Step 4/4] Extracting ZIP files...")
            extracted_files = self._extract_zip_files(zip_file_path)
            if not extracted_files:
                self.logger.error("[RDD Step 4/4 FAILED] Could not extract files from ZIP")
                return downloaded_files

            self.logger.info(f"[RDD Step 4/4 SUCCESS] Extracted {len(extracted_files)} files from ZIP")

            # 5. Process only relevant files (2 out of 4)
            for file_path in extracted_files:
                original_filename = os.path.basename(file_path)
                self.logger.info(f"Processing file: {original_filename}")

                corresponding_bcf = self._find_matching_zip_file(original_filename, file_map)

                if corresponding_bcf:
                    self.logger.info(
                        f"Relevant file - Mapping {original_filename} -> BillingCycleFile ID {corresponding_bcf.id}"
                    )
                    file_info = FileDownloadInfo(
                        file_id=corresponding_bcf.id,
                        file_name=original_filename,
                        download_url="N/A",
                        file_path=file_path,
                        billing_cycle_file=corresponding_bcf,
                    )
                    downloaded_files.append(file_info)
                else:
                    self.logger.info(f"File ignored (not relevant): {original_filename}")

            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error downloading Raw Data ZIP: {str(e)}")
            self._close_modal_if_open()
            return downloaded_files

    def _find_matching_zip_file(self, filename: str, file_map: dict) -> Optional[Any]:
        """Finds BillingCycleFile for the 2 relevant ZIP files only."""
        filename_lower = filename.lower()

        zip_pattern_to_slug = {
            "account & wireless summary": VerizonFileSlug.ACCOUNT_AND_WIRELESS.value,
            "account_wireless_summary": VerizonFileSlug.ACCOUNT_AND_WIRELESS.value,
            "acct & wireless charges detail": VerizonFileSlug.WIRELESS_CHARGES_DETAIL.value,
            "wireless_charges_detail": VerizonFileSlug.WIRELESS_CHARGES_DETAIL.value,
        }

        for pattern, slug in zip_pattern_to_slug.items():
            if pattern in filename_lower:
                return file_map.get(slug)

        return None

    def _download_device_report(self, billing_cycle: BillingCycle, file_map: dict) -> Optional[FileDownloadInfo]:
        """Downloads Device Report from Device tab."""
        try:
            self.logger.info("Downloading Device Report...")

            # 1. Click on Others tab
            others_tab_selector = 'li[data-track="Others"]'
            self.logger.info("Clicking on Others tab...")

            if self.browser_wrapper.is_element_visible(others_tab_selector, timeout=5000, selector_type="css"):
                self.browser_wrapper.click_element(others_tab_selector, selector_type="css")
                time.sleep(2)
            else:
                self.logger.error("Others tab not found")
                return None

            # 2. Click on Offer recovery & early termination fees report
            device_report_selector = 'div[data-track="Other reports: Offer recovery & early termination fees"]'
            self.logger.info("Clicking on Offer recovery & early termination fees report...")

            if self.browser_wrapper.is_element_visible(device_report_selector, timeout=5000, selector_type="css"):
                self.browser_wrapper.click_element(device_report_selector, selector_type="css")
                self.logger.info("Waiting 45 seconds for report to load...")
                time.sleep(45)
            else:
                self.logger.error("Offer recovery & early termination fees report not found")
                return None

            # 3. Configure filters
            account_number = billing_cycle.account.number
            self.logger.info(f"Configuring filters for account: {account_number}")
            if not self._configure_filters(account_number):
                self.logger.error(f"Failed to configure filters for Device Report, aborting")
                self._navigate_back_to_reports()
                return None

            # 4. Select latest available bill cycle (same month for from/to)
            if not self._select_latest_bill_cycle_both():
                self.logger.error("Failed to select latest bill cycle, aborting")
                self._navigate_back_to_reports()
                return None

            # 5. Click Apply filters
            self._click_apply_filters()
            self.logger.info("Waiting 15 seconds after applying filters...")
            time.sleep(15)

            # 6. Download full report
            file_path = self._download_full_report()

            if file_path:
                actual_filename = os.path.basename(file_path)
                self.logger.info(f"Device Report downloaded: {actual_filename}")

                corresponding_bcf = file_map.get(VerizonFileSlug.DEVICE_REPORT.value)

                file_info = FileDownloadInfo(
                    file_id=corresponding_bcf.id if corresponding_bcf else 0,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=file_path,
                    billing_cycle_file=corresponding_bcf,
                )

                if corresponding_bcf:
                    self.logger.info(
                        f"MAPPING CONFIRMED: {actual_filename} -> BillingCycleFile ID {corresponding_bcf.id}"
                    )

                self._navigate_back_to_reports()
                return file_info

            self.logger.error("Could not download Device Report")
            self._navigate_back_to_reports()
            return None

        except Exception as e:
            self.logger.error(f"Error downloading Device Report: {str(e)}")
            try:
                self._navigate_back_to_reports()
            except:
                pass
            return None

    def _download_activation_deactivation_report(
        self, billing_cycle: BillingCycle, file_map: dict
    ) -> Optional[FileDownloadInfo]:
        """Downloads Activation & Deactivation Report from Others tab."""
        try:
            self.logger.info("Downloading Activation & Deactivation Report...")

            # 1. Click on Others tab
            others_tab_selector = 'li[data-track="Others"]'
            self.logger.info("Clicking on Others tab...")

            if self.browser_wrapper.is_element_visible(others_tab_selector, timeout=5000, selector_type="css"):
                self.browser_wrapper.click_element(others_tab_selector, selector_type="css")
                time.sleep(2)
            else:
                self.logger.error("Others tab not found")
                return None

            # 2. Click on Activation & deactivation report
            activation_report_selector = 'div[data-track="Other reports: Activation & deactivation"]'
            self.logger.info("Clicking on Activation & deactivation report...")

            if self.browser_wrapper.is_element_visible(activation_report_selector, timeout=5000, selector_type="css"):
                self.browser_wrapper.click_element(activation_report_selector, selector_type="css")
                self.logger.info("Waiting 15 seconds for report to load...")
                time.sleep(15)
            else:
                self.logger.error("Activation & deactivation report not found")
                return None

            # 3. Configure filters
            account_number = billing_cycle.account.number
            self.logger.info(f"Configuring filters for account: {account_number}")
            if not self._configure_filters(account_number):
                self.logger.error(f"Failed to configure filters for Activation & Deactivation Report, aborting")
                self._navigate_back_to_reports()
                return None

            # Configure date range (this report uses date picker inputs, not month dropdowns)
            if not self._set_date_range(billing_cycle.start_date, billing_cycle.end_date):
                self.logger.error("Failed to set date range, aborting")
                self._navigate_back_to_reports()
                return None

            # 4. Click Apply filters
            self._click_apply_filters()
            self.logger.info("Waiting 10 seconds after applying filters...")
            time.sleep(10)

            # 5. Download full report
            file_path = self._download_full_report()

            if file_path:
                actual_filename = os.path.basename(file_path)
                self.logger.info(f"Activation & Deactivation Report downloaded: {actual_filename}")

                corresponding_bcf = file_map.get(VerizonFileSlug.ACTIVATION_AND_DEACTIVATION.value)

                file_info = FileDownloadInfo(
                    file_id=corresponding_bcf.id if corresponding_bcf else 0,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=file_path,
                    billing_cycle_file=corresponding_bcf,
                )

                if corresponding_bcf:
                    self.logger.info(
                        f"MAPPING CONFIRMED: {actual_filename} -> BillingCycleFile ID {corresponding_bcf.id}"
                    )

                self._navigate_back_to_reports()
                return file_info

            self.logger.error("Could not download Activation & Deactivation Report")
            self._navigate_back_to_reports()
            return None

        except Exception as e:
            self.logger.error(f"Error downloading Activation & Deactivation Report: {str(e)}")
            try:
                self._navigate_back_to_reports()
            except:
                pass
            return None

    def _download_suspended_wireless_report(
        self, billing_cycle: BillingCycle, file_map: dict
    ) -> Optional[FileDownloadInfo]:
        """Downloads Suspended Wireless Numbers Report from Others tab."""
        try:
            self.logger.info("Downloading Suspended Wireless Numbers Report...")

            # 1. Click on Others tab
            others_tab_selector = 'li[data-track="Others"]'
            self.logger.info("Clicking on Others tab...")

            if self.browser_wrapper.is_element_visible(others_tab_selector, timeout=5000, selector_type="css"):
                self.browser_wrapper.click_element(others_tab_selector, selector_type="css")
                time.sleep(2)
            else:
                self.logger.error("Others tab not found")
                return None

            # 2. Click on Suspended wireless number report
            suspended_report_selector = 'div[data-track="Other reports: Suspended wireless number"]'
            self.logger.info("Clicking on Suspended wireless number report...")

            if self.browser_wrapper.is_element_visible(suspended_report_selector, timeout=5000, selector_type="css"):
                self.browser_wrapper.click_element(suspended_report_selector, selector_type="css")
                self.logger.info("Waiting 15 seconds for report to load...")
                time.sleep(15)
            else:
                self.logger.error("Suspended wireless number report not found")
                return None

            # 3. Configure filters
            account_number = billing_cycle.account.number
            self.logger.info(f"Configuring filters for account: {account_number}")
            if not self._configure_filters(account_number):
                self.logger.error(f"Failed to configure filters for Suspended Wireless Numbers Report, aborting")
                self._navigate_back_to_reports()
                return None

            # 4. Click Apply filters
            self._click_apply_filters()
            self.logger.info("Waiting 10 seconds after applying filters...")
            time.sleep(10)

            # 5. Download full report
            file_path = self._download_full_report()

            if file_path:
                actual_filename = os.path.basename(file_path)
                self.logger.info(f"Suspended Wireless Numbers Report downloaded: {actual_filename}")

                corresponding_bcf = file_map.get(VerizonFileSlug.SUSPENDED_WIRELESS_NUMBERS.value)

                file_info = FileDownloadInfo(
                    file_id=corresponding_bcf.id if corresponding_bcf else 0,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=file_path,
                    billing_cycle_file=corresponding_bcf,
                )

                if corresponding_bcf:
                    self.logger.info(
                        f"MAPPING CONFIRMED: {actual_filename} -> BillingCycleFile ID {corresponding_bcf.id}"
                    )

                self._navigate_back_to_reports()
                return file_info

            self.logger.error("Could not download Suspended Wireless Numbers Report")
            self._navigate_back_to_reports()
            return None

        except Exception as e:
            self.logger.error(f"Error downloading Suspended Wireless Numbers Report: {str(e)}")
            try:
                self._navigate_back_to_reports()
            except:
                pass
            return None

    # ==================== HELPER METHODS ====================

    def _format_month_option(self, target_date: date) -> str:
        """Formats date to 'Nov 2025' for Raw Data dropdown."""
        return f"{target_date.strftime('%b')} {target_date.year}"

    def _format_short_month_option(self, target_date: date) -> str:
        """Formats date to 'Nov-25' for Bill cycle dropdowns."""
        return f"{target_date.strftime('%b')}-{target_date.strftime('%y')}"

    def _configure_filters(self, account_number: str) -> bool:
        """Configures View by and Select number filters.

        Returns:
            True if filters were configured successfully, False otherwise.
        """
        try:
            # View by dropdown
            view_by_xpath = (
                "//div[contains(@class, 'filter-inputs') and contains(@class, 'viewby')]"
                "//app-dropdown//div[@role='combobox']"
            )

            if not self.browser_wrapper.is_element_visible(view_by_xpath, timeout=5000):
                self.logger.error("View by dropdown not found")
                return False

            self.browser_wrapper.click_element(view_by_xpath)
            time.sleep(1)

            # Select "Account number" option
            account_option_xpath = (
                "//ul[@role='listbox']//li[@role='option' and contains(text(), 'Account number')]"
            )
            if not self.browser_wrapper.is_element_visible(account_option_xpath, timeout=3000):
                self.logger.error("'Account number' option not found in View by dropdown")
                return False

            self.browser_wrapper.click_element(account_option_xpath)
            self.logger.info("Selected 'Account number' in View by")
            time.sleep(1)

            # Select number dropdown
            select_number_xpath = (
                "//span[contains(@class, 'font-10') and contains(text(), 'Select number')]"
                "/following-sibling::div//app-dropdown//div[@role='combobox']"
            )

            if not self.browser_wrapper.is_element_visible(select_number_xpath, timeout=5000):
                self.logger.error("Select number dropdown not found")
                return False

            self.browser_wrapper.click_element(select_number_xpath)
            time.sleep(1)

            # Select account that contains the number
            account_option_xpath = (
                f"//ul[@role='listbox']//li[@role='option' and contains(text(), '{account_number}')]"
            )
            if not self.browser_wrapper.is_element_visible(account_option_xpath, timeout=3000):
                self.logger.error(f"Account number '{account_number}' not found in dropdown options")
                return False

            self.browser_wrapper.click_element(account_option_xpath)
            self.logger.info(f"Selected account: {account_number}")
            return True

        except Exception as e:
            self.logger.error(f"Error configuring filters: {str(e)}")
            return False

    def _select_bill_cycle_from(self, month_option: str) -> bool:
        """Selects Bill cycle from dropdown.

        Returns:
            True if the option was selected successfully, False otherwise.
        """
        try:
            bill_cycle_from_xpath = '//*[@id="monthRangeFrom"]//div[@role="combobox"]'

            if not self.browser_wrapper.is_element_visible(bill_cycle_from_xpath, timeout=5000):
                self.logger.error("Bill cycle from dropdown not found")
                return False

            self.browser_wrapper.click_element(bill_cycle_from_xpath)
            time.sleep(1)

            option_xpath = f"//ul[@role='listbox']//li[@role='option' and contains(text(), '{month_option}')]"
            if not self.browser_wrapper.is_element_visible(option_xpath, timeout=3000):
                self.logger.error(f"Bill cycle from option '{month_option}' not found")
                return False

            self.browser_wrapper.click_element(option_xpath)
            self.logger.info(f"Selected Bill cycle from: {month_option}")
            return True

        except Exception as e:
            self.logger.error(f"Error selecting Bill cycle from: {str(e)}")
            return False

    def _select_bill_cycle_to(self, month_option: str) -> bool:
        """Selects Bill cycle to dropdown.

        Returns:
            True if the option was selected successfully, False otherwise.
        """
        try:
            bill_cycle_to_xpath = '//*[@id="monthRangeTo"]//div[@role="combobox"]'

            if not self.browser_wrapper.is_element_visible(bill_cycle_to_xpath, timeout=5000):
                self.logger.error("Bill cycle to dropdown not found")
                return False

            self.browser_wrapper.click_element(bill_cycle_to_xpath)
            time.sleep(1)

            option_xpath = f"//ul[@role='listbox']//li[@role='option' and contains(text(), '{month_option}')]"
            if not self.browser_wrapper.is_element_visible(option_xpath, timeout=3000):
                self.logger.error(f"Bill cycle to option '{month_option}' not found")
                return False

            self.browser_wrapper.click_element(option_xpath)
            self.logger.info(f"Selected Bill cycle to: {month_option}")
            return True

        except Exception as e:
            self.logger.error(f"Error selecting Bill cycle to: {str(e)}")
            return False

    def _select_latest_bill_cycle_both(self) -> bool:
        """Selects the latest available month-year in both Bill cycle from/to dropdowns.

        Used only by the Offer recovery & early termination fees report, which does not
        keep historical data — it always needs the most recent available bill cycle for
        both from and to. Reads the first option (DOM is ordered desc) in monthRangeFrom,
        then selects the same value in monthRangeTo.

        Returns:
            True if both dropdowns were set successfully, False otherwise.
        """
        try:
            # 1. Open Bill cycle from dropdown
            from_dropdown_xpath = '//*[@id="monthRangeFrom"]//div[@role="combobox"]'

            if not self.browser_wrapper.is_element_visible(from_dropdown_xpath, timeout=5000):
                self.logger.error("Bill cycle from dropdown not found")
                return False

            self.browser_wrapper.click_element(from_dropdown_xpath)
            time.sleep(1)

            # 2. Read first option (most recent)
            first_option_xpath = '//*[@id="monthRangeFrom"]//ul[@role="listbox"]//li[@role="option"][1]'

            if not self.browser_wrapper.is_element_visible(first_option_xpath, timeout=3000):
                self.logger.error("No options available in Bill cycle from dropdown")
                return False

            latest_month = self.browser_wrapper.get_text(first_option_xpath).strip()
            self.logger.info(f"Latest available month detected: {latest_month}")

            # 3. Click the first option
            self.browser_wrapper.click_element(first_option_xpath)
            self.logger.info(f"Selected Bill cycle from: {latest_month}")
            time.sleep(1)

            # 4. Open Bill cycle to dropdown
            to_dropdown_xpath = '//*[@id="monthRangeTo"]//div[@role="combobox"]'

            if not self.browser_wrapper.is_element_visible(to_dropdown_xpath, timeout=5000):
                self.logger.error("Bill cycle to dropdown not found")
                return False

            self.browser_wrapper.click_element(to_dropdown_xpath)
            time.sleep(1)

            # 5. Click matching option in Bill cycle to
            to_option_xpath = (
                f'//*[@id="monthRangeTo"]//ul[@role="listbox"]'
                f'//li[@role="option" and contains(text(), "{latest_month}")]'
            )

            if not self.browser_wrapper.is_element_visible(to_option_xpath, timeout=3000):
                self.logger.error(f"Option '{latest_month}' not found in Bill cycle to dropdown")
                return False

            self.browser_wrapper.click_element(to_option_xpath)
            self.logger.info(f"Selected Bill cycle to: {latest_month}")
            time.sleep(1)

            return True

        except Exception as e:
            self.logger.error(f"Error selecting latest bill cycle: {str(e)}")
            return False

    def _set_date_range(self, start_date: date, end_date: date) -> bool:
        """Sets date range using Material date picker inputs (used by Activation & Deactivation report).

        Args:
            start_date: The start date of the billing cycle.
            end_date: The end date of the billing cycle.

        Returns:
            True if dates were set successfully, False otherwise.
        """
        try:
            date_from_css = "#dateFrom"
            date_to_css = "#dateTo"

            # Format dates as MM/DD/YYYY for the Material date picker
            from_date_str = start_date.strftime("%m/%d/%Y")
            to_date_str = end_date.strftime("%m/%d/%Y")

            self.logger.info(f"Setting date range: {from_date_str} - {to_date_str}")

            if not self.browser_wrapper.is_element_visible(date_from_css, timeout=5000, selector_type="css"):
                self.logger.error("Date From input not found")
                return False

            self.browser_wrapper.clear_and_type(date_from_css, from_date_str, selector_type="css")
            self.logger.info(f"Set Date From: {from_date_str}")
            time.sleep(1)

            if not self.browser_wrapper.is_element_visible(date_to_css, timeout=5000, selector_type="css"):
                self.logger.error("Date To input not found")
                return False

            self.browser_wrapper.clear_and_type(date_to_css, to_date_str, selector_type="css")
            self.logger.info(f"Set Date To: {to_date_str}")
            time.sleep(1)

            return True

        except Exception as e:
            self.logger.error(f"Error setting date range: {str(e)}")
            return False

    def _click_apply_filters(self):
        """Clicks Apply filters button if enabled."""
        try:
            apply_button_xpath = '//*[@id="apply-changes"]'

            if self.browser_wrapper.is_element_visible(apply_button_xpath, timeout=3000):
                # Check if button is enabled by getting its attribute
                button_class = self.browser_wrapper.get_attribute(apply_button_xpath, "class")

                if "disabled" not in button_class.lower():
                    self.logger.info("Clicking Apply filters button...")
                    self.browser_wrapper.click_element(apply_button_xpath)
                else:
                    self.logger.info("Apply filters button is disabled")

        except Exception as e:
            self.logger.warning(f"Error clicking Apply filters: {str(e)}")

    def _download_full_report(self) -> Optional[str]:
        """Downloads full report and returns file path."""
        try:
            download_xpath = (
                "/html/body/app-root/app-secure-layout/div/main/div/app-reports-landing/div[1]/"
                "app-reporting-dashboard/div/div[2]/div/div[1]/div/div[1]/div[2]/div"
            )

            if self.browser_wrapper.is_element_visible(download_xpath, timeout=10000):
                download_text = self.browser_wrapper.get_text(download_xpath)

                if "Download full report" in download_text:
                    self.logger.info("Clicking Download full report...")
                    return self.browser_wrapper.expect_download_and_click(
                        download_xpath, timeout=60000, downloads_dir=self.job_downloads_dir
                    )
                else:
                    self.logger.warning(f"Download text mismatch: '{download_text}'")

            self.logger.error("Download element not found")
            return None

        except Exception as e:
            self.logger.error(f"Error downloading report: {str(e)}")
            return None

    def _navigate_back_to_reports(self):
        """Navigates back to reports section."""
        try:
            back_xpath = (
                "/html/body/app-root/app-secure-layout/div/main/div/app-reports-landing/div[1]/"
                "app-reporting-dashboard/div/div[1]/a"
            )
            self.logger.info("Navigating back to reports...")

            if self.browser_wrapper.is_element_visible(back_xpath, timeout=5000):
                self.browser_wrapper.click_element(back_xpath)
                time.sleep(3)

        except Exception as e:
            self.logger.error(f"Error navigating back: {str(e)}")

    def _close_modal_if_open(self) -> bool:
        """Closes any open modal if present. Returns True if a modal was closed."""
        try:
            modal_close_xpath = "//div[contains(@class, 'Modal') and contains(@class, 'is-active')]//button[contains(@class, 'Modal-close')]"

            if self.browser_wrapper.is_element_visible(modal_close_xpath, timeout=2000):
                self.logger.info("Modal detected - closing it...")
                self.browser_wrapper.click_element(modal_close_xpath)
                time.sleep(1)
                self.logger.info("Modal closed")
                return True
            return False
        except Exception as e:
            self.logger.warning(f"Error closing modal: {str(e)}")
            return False

    def _reset_to_main_screen(self):
        """Resets to Verizon main screen."""
        try:
            self.logger.info("Resetting to Verizon main screen...")

            # First, close any open modal that might be blocking clicks
            self._close_modal_if_open()

            home_xpath = '//*[@id="gNavHeader"]/div/div/div[1]/div[2]/header/div/div/div[1]/div/a'

            if self.browser_wrapper.is_element_visible(home_xpath, timeout=5000):
                self.browser_wrapper.click_element(home_xpath)
                self.browser_wrapper.wait_for_page_load()
                time.sleep(3)
                self.logger.info("Reset completed")

        except Exception as e:
            self.logger.error(f"Error resetting: {str(e)}")
