import logging
import os
import time
from typing import Any, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    FileDownloadInfo,
    PDFInvoiceScraperStrategy,
)

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class TelusPDFInvoiceScraperStrategy(PDFInvoiceScraperStrategy):
    """PDF invoice scraper for Telus.

    This scraper:
    1. Navigates to Bill Analyzer via My Telus
    2. Configures Scope (account) and Month filters
    3. Downloads the corresponding PDF invoice
    """

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navigates to PDF invoices section in Telus and configures filters."""
        try:
            self.logger.info("=== STARTING TELUS PDF INVOICE SCRAPER ===")

            # 1. Verify we are in My Telus
            current_url = self.browser_wrapper.get_current_url()
            if "my-telus" not in current_url:
                self.logger.info("Navigating to My Telus...")
                self.browser_wrapper.goto("https://www.telus.com/my-telus")
                self.browser_wrapper.wait_for_page_load()
                time.sleep(5)

            # 2. Click on bill options dropdown
            bill_options_xpath = (
                "//div[@data-testid='generic-card-dropdown-button'][.//div[normalize-space(text())='Bill Options']]"
            )
            self.logger.info("Clicking on bill options dropdown...")
            self.browser_wrapper.click_element(bill_options_xpath)
            time.sleep(2)

            # 3. Click on "View bill" option
            view_bill_xpath = "//div[@class='generic_dropdownContainer__h39SV']//a[1]"
            self.logger.info("Clicking on 'View bill' option...")
            self.browser_wrapper.click_element(view_bill_xpath)
            self.logger.info("Waiting 30 seconds for Bill Analyzer to load...")
            time.sleep(30)

            # 4. Handle Bill Analyzer modal if it appears
            self._dismiss_bill_analyzer_modal()

            # 5. Click on Statements tab
            statements_xpath = '//*[@id="navMenuItem14"]'
            self.logger.info("Clicking on Statements tab...")
            self.browser_wrapper.click_element(statements_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(5)

            # 6. Configure Scope filter (account)
            if not self._configure_scope_filter(billing_cycle):
                self.logger.error("Scope filter configuration failed - aborting scraper")
                return None

            # 7. Configure Month filter
            if not self._configure_month_filter(billing_cycle):
                self.logger.error("Month filter configuration failed - aborting scraper")
                return None

            # 8. Click on Apply
            apply_button_xpath = '//*[@id="btnViewList"]'
            self.logger.info("Clicking on Apply button...")
            self.browser_wrapper.click_element(apply_button_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(10)

            self.logger.info("Navigation to PDF invoices section completed")
            return {"section": "pdf_invoices", "ready_for_download": True}

        except Exception as e:
            self.logger.error(f"Error navigating to PDF invoices: {str(e)}")
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

    def _configure_scope_filter(self, billing_cycle: BillingCycle) -> bool:
        """Configures Scope filter to select the correct account."""
        try:
            target_account = billing_cycle.account.number
            self.logger.info(f"Configuring Scope filter for account: {target_account}")

            # 1. Click on Scope dropdown button
            scope_dropdown_xpath = '//*[@id="LevelDataDropdownButton"]'
            self.logger.info("Clicking on Scope dropdown...")
            self.browser_wrapper.click_element(scope_dropdown_xpath)
            time.sleep(2)

            # 2. Click on "Accounts" option
            accounts_option_xpath = '//*[@id="LevelDataDropdownList_multipleaccounts"]'
            self.logger.info("Clicking on 'Accounts' option...")
            self.browser_wrapper.click_element(accounts_option_xpath)
            time.sleep(3)

            # 3. Type account number in search input
            search_input_xpath = '//*[@id="scopeExpandedAccountMenu"]/div[1]/div/div[2]/input'
            self.logger.info(f"Typing account number '{target_account}' in search input...")
            self.browser_wrapper.clear_and_type(search_input_xpath, target_account)
            time.sleep(2)

            # 4. Select account from results list
            # List is at: //*[@id="scopeExpandedAccountMenu"]/div[3]/ul
            # The li contains the account number
            account_list_item_xpath = (
                f'//*[@id="scopeExpandedAccountMenu"]/div[3]/ul//li[contains(., "{target_account}")]'
            )

            if self.browser_wrapper.find_element_by_xpath(account_list_item_xpath, timeout=5000):
                self.logger.info(f"Account {target_account} found in list, selecting...")
                self.browser_wrapper.click_element(account_list_item_xpath)
                time.sleep(1)
            else:
                self.logger.error(f"Account {target_account} NOT found in results list")
                return False

            # 5. Click on OK button to confirm
            ok_button_xpath = '//*[@id="scopeExpandedAccountMenu"]/div[4]/button'
            self.logger.info("Clicking on OK button to confirm account...")
            self.browser_wrapper.click_element(ok_button_xpath)

            time.sleep(2)
            self.logger.info(f"Scope filter configured for account: {target_account}")
            return True

        except Exception as e:
            self.logger.error(f"Error configuring Scope filter: {str(e)}")
            return False

    def _configure_month_filter(self, billing_cycle: BillingCycle) -> bool:
        """Configures Month filter based on billing cycle end_date."""
        try:
            target_month = billing_cycle.end_date.month
            target_year = billing_cycle.end_date.year

            # Month number to English name mapping
            month_names = {
                1: "January",
                2: "February",
                3: "March",
                4: "April",
                5: "May",
                6: "June",
                7: "July",
                8: "August",
                9: "September",
                10: "October",
                11: "November",
                12: "December",
            }
            month_name = month_names[target_month]

            self.logger.info(f"Configuring Month filter for: {month_name} {target_year}")

            # 1. Click on Month dropdown button
            month_dropdown_xpath = '//*[@id="BilledMonthYearPendingDataDropdownButton"]'
            self.logger.info("Clicking on Month dropdown...")
            self.browser_wrapper.click_element(month_dropdown_xpath)
            time.sleep(2)

            # 2. Search and select correct month
            # Options format: "December 2025", "November 2025", etc.
            target_text = f"{month_name} {target_year}"

            # Search in options list
            month_option_xpath = f"//li[@role='option'][contains(text(), '{target_text}')]"

            if self.browser_wrapper.find_element_by_xpath(month_option_xpath, timeout=5000):
                self.logger.info(f"Month '{target_text}' found, selecting...")
                self.browser_wrapper.click_element(month_option_xpath)
                time.sleep(2)
                self.logger.info(f"Month filter configured: {target_text}")
                return True
            else:
                self.logger.error(f"Month '{target_text}' NOT found in list")
                return False

        except Exception as e:
            self.logger.error(f"Error configuring Month filter: {str(e)}")
            return False

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Downloads PDF invoices from Telus."""
        downloaded_files = []

        # Get BillingCyclePDFFile from billing_cycle
        pdf_file = billing_cycle.pdf_files[0] if billing_cycle.pdf_files else None
        if pdf_file:
            self.logger.info(f"Mapping PDF file -> BillingCyclePDFFile ID {pdf_file.id}")

        target_account = billing_cycle.account.number

        try:
            self.logger.info("=== STARTING PDF DOWNLOAD PROCESS ===")

            # 1. Search in DataTable for row with correct account
            data_table_xpath = '//*[@id="DataTable"]'

            if not self.browser_wrapper.find_element_by_xpath(data_table_xpath, timeout=10000):
                self.logger.error("Statements table not found")
                return downloaded_files

            self.logger.info("Statements table found")

            # 2. Search for "PDF Bill" button in correct account row
            # Button has aria-label containing account number
            pdf_button_xpath = (
                f"//button[contains(@aria-label, 'PDF Bill')][contains(@aria-label, '{target_account}')]"
            )

            # Alternative: search in first row
            pdf_button_alt_xpath = "//tbody/tr[1]//button[contains(@aria-label, 'PDF Bill')]"

            if self.browser_wrapper.find_element_by_xpath(pdf_button_xpath, timeout=5000):
                self.logger.info(f"PDF Bill button found for account {target_account}")
                self.browser_wrapper.click_element(pdf_button_xpath)
            elif self.browser_wrapper.find_element_by_xpath(pdf_button_alt_xpath, timeout=3000):
                self.logger.info("PDF Bill button found in first row")
                self.browser_wrapper.click_element(pdf_button_alt_xpath)
            else:
                self.logger.error("PDF Bill button not found")
                return downloaded_files

            time.sleep(3)

            # 3. Verify account in modal is correct
            modal_header_xpath = '//*[@id="bdfModalHeaderText"]'

            if self.browser_wrapper.find_element_by_xpath(modal_header_xpath, timeout=5000):
                modal_text = self.browser_wrapper.get_text(modal_header_xpath)
                self.logger.info(f"Modal header: '{modal_text}'")

                if target_account not in modal_text:
                    self.logger.error(f"Account in modal '{modal_text}' doesn't match '{target_account}'")
                    self._close_modal_and_reset()
                    return downloaded_files

                self.logger.info(f"Account verified in modal: {target_account}")
            else:
                self.logger.warning("Could not verify account in modal header")

            # 4. Click on "PDF copy of your print bill" to expand list
            pdf_copy_xpath = "//a[contains(@class, 'bdfDocType')][contains(., 'PDF copy of your print bill')]"

            if self.browser_wrapper.find_element_by_xpath(pdf_copy_xpath, timeout=5000):
                self.logger.info("Clicking on 'PDF copy of your print bill'...")
                self.browser_wrapper.click_element(pdf_copy_xpath)
                time.sleep(2)
            else:
                self.logger.error("'PDF copy of your print bill' option not found")
                self._close_modal_and_reset()
                return downloaded_files

            # 5. Select correct date based on end_date
            # Options format: "YYYY/MM/DD" (e.g.: "2025/11/21")
            target_year = billing_cycle.end_date.year
            target_month = billing_cycle.end_date.month

            # Search for option with correct year and month
            date_pattern = f"{target_year}/{target_month:02d}"
            date_button_xpath = f"//button[contains(@class, 'bdf-doc-item')][contains(text(), '{date_pattern}')]"

            if self.browser_wrapper.find_element_by_xpath(date_button_xpath, timeout=5000):
                button_text = self.browser_wrapper.get_text(date_button_xpath)
                self.logger.info(f"Date found: '{button_text}', downloading PDF...")

                # Click triggers download automatically
                downloaded_file_path = self.browser_wrapper.expect_download_and_click(
                    date_button_xpath, timeout=60000, downloads_dir=self.job_downloads_dir
                )

                if downloaded_file_path:
                    actual_filename = os.path.basename(downloaded_file_path)
                    self.logger.info(f"PDF downloaded: {actual_filename}")

                    file_info = FileDownloadInfo(
                        file_id=pdf_file.id if pdf_file else 1,
                        file_name=actual_filename,
                        download_url="N/A",
                        file_path=downloaded_file_path,
                        pdf_file=pdf_file,
                    )
                    downloaded_files.append(file_info)

                    if pdf_file:
                        self.logger.info(
                            f"MAPPING CONFIRMED: {actual_filename} -> BillingCyclePDFFile ID {pdf_file.id}"
                        )
                else:
                    self.logger.error("Error downloading PDF")
            else:
                self.logger.error(f"PDF not found for date {date_pattern}")
                # List available options for debug
                self._list_available_pdf_dates()

            # 6. Close modal and reset
            self._close_modal_and_reset()

            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error in PDF download: {str(e)}")
            try:
                self._close_modal_and_reset()
            except:
                pass
            return downloaded_files

    def _list_available_pdf_dates(self):
        """Lists available PDF dates for debug."""
        try:
            self.logger.info("Listing available PDF dates:")

            # Search for all date buttons
            for i in range(1, 20):
                button_xpath = f"(//button[contains(@class, 'bdf-doc-item')])[{i}]"
                if self.browser_wrapper.find_element_by_xpath(button_xpath, timeout=1000):
                    text = self.browser_wrapper.get_text(button_xpath)
                    self.logger.info(f"  - {text}")
                else:
                    break

        except Exception as e:
            self.logger.warning(f"Error listing dates: {str(e)}")

    def _close_modal_and_reset(self):
        """Closes PDF modal and resets to main screen."""
        try:
            # Close modal
            close_button_xpath = '//*[@id="bdfModal"]/div/div/div[1]/button'
            if self.browser_wrapper.find_element_by_xpath(close_button_xpath, timeout=3000):
                self.logger.info("Closing PDF modal...")
                self.browser_wrapper.click_element(close_button_xpath)
                time.sleep(2)

            # Reset to My Telus
            self._reset_to_main_screen()

        except Exception as e:
            self.logger.warning(f"Error closing modal: {str(e)}")
            self._reset_to_main_screen()

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
