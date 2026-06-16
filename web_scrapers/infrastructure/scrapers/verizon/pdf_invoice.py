import logging
import os
import time
from datetime import date
from typing import Any, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    FileDownloadInfo,
    PDFInvoiceScraperStrategy,
)

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class VerizonPDFInvoiceScraperStrategy(PDFInvoiceScraperStrategy):
    """PDF Invoice scraper for Verizon.

    Downloads PDF invoices from the Recent Bills section.

    Flow:
    1. Navigate to Billing -> Bill details -> Previous bills
    2. Wait 45s, click on "Recent bills" tab
    3. Wait 30s, verify account number matches
    4. Find invoice card matching billing_cycle.end_date
    5. Click download icon to download PDF
    """

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navigates to Verizon Recent Bills section."""
        try:
            self.logger.info("Navigating to Verizon PDF invoices...")

            # Dismiss the post-login promotional modal ("Exclusive savings for
            # you") before navigating. Its React-rendered backdrop intercepts
            # pointer events over the global nav, so every navigation click
            # times out while it is open.
            self._dismiss_promo_modal()

            # 1. Click on Billing header
            billing_tab_xpath = '//*[@id="gNavHeader"]/div/div/div[1]/div[2]/header/div/div/div[2]/nav/ul/li[3]/a'
            self.logger.info("Clicking on Billing tab...")

            if self.browser_wrapper.is_element_visible(billing_tab_xpath, timeout=10000):
                self.browser_wrapper.click_element(billing_tab_xpath)
                time.sleep(2)
            else:
                self.logger.error("Billing tab not found")
                self._reset_to_main_screen()
                return None

            # 2. Click on View bill details
            bill_details_xpath = '//*[@id="gNavHeader"]/div/div/div[1]/div[2]/header/div/div/div[2]/nav/ul/li[3]/div/div/div[1]/div/ul/li[2]/a'
            self.logger.info("Clicking on View bill details...")

            if self.browser_wrapper.is_element_visible(bill_details_xpath, timeout=5000):
                self.browser_wrapper.click_element(bill_details_xpath)
                time.sleep(2)
            else:
                self.logger.error("View bill details option not found")
                self._reset_to_main_screen()
                return None

            # 3. Click on Previous bills
            previous_bills_xpath = '//*[@id="billing-view-bills-s"]/div/ul/li[4]/a'
            self.logger.info("Clicking on Previous bills...")

            if self.browser_wrapper.is_element_visible(previous_bills_xpath, timeout=5000):
                self.browser_wrapper.click_element(previous_bills_xpath)
                self.logger.info("Waiting 10 seconds for page to load...")
                time.sleep(10)
            else:
                self.logger.error("Previous bills option not found")
                self._reset_to_main_screen()
                return None

            # 4. Click on "Recent bills" tab in the UL
            recent_bills_tab_xpath = '//li[contains(text(), "Recent bills")]'
            self.logger.info("Clicking on Recent bills tab...")

            if self.browser_wrapper.is_element_visible(recent_bills_tab_xpath, timeout=10000):
                self.browser_wrapper.click_element(recent_bills_tab_xpath)
                self.logger.info("Recent bills tab clicked")
                self.logger.info("Waiting 10 seconds for bills to load...")
                time.sleep(10)
            else:
                self.logger.error("Recent bills tab not found")
                self._reset_to_main_screen()
                return None

            self.logger.info("Navigation to Recent Bills completed successfully")
            return {"section": "pdf_invoices", "ready_for_download": True}

        except Exception as e:
            self.logger.error(f"Error navigating to PDF invoices: {str(e)}")
            self._reset_to_main_screen()
            return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Downloads the PDF invoice for the billing cycle."""
        downloaded_files = []

        # Get the BillingCyclePDFFile from billing_cycle
        pdf_file = billing_cycle.pdf_files[0] if billing_cycle.pdf_files else None
        if pdf_file:
            self.logger.info(f"Mapping to BillingCyclePDFFile ID {pdf_file.id}")

        try:
            self.logger.info("Starting PDF invoice download...")

            # Verify account number matches before downloading
            expected_account = billing_cycle.account.number
            self._verify_account_number(expected_account)

            # Find and click download icon for the matching invoice
            target_month = self._format_month_from_date(billing_cycle.end_date)
            self.logger.info(f"Looking for invoice: {target_month}")

            file_path = self._download_invoice_by_month(target_month)

            if file_path:
                actual_filename = os.path.basename(file_path)
                self.logger.info(f"PDF invoice downloaded: {actual_filename}")

                file_info = FileDownloadInfo(
                    file_id=pdf_file.id if pdf_file else 0,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=file_path,
                    pdf_file=pdf_file,
                )
                downloaded_files.append(file_info)

                if pdf_file:
                    self.logger.info(f"MAPPING CONFIRMED: {actual_filename} -> BillingCyclePDFFile ID {pdf_file.id}")
            else:
                self.logger.error(f"Could not download PDF invoice for {target_month}")

            # Reset to main screen
            self._reset_to_main_screen()

            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error downloading PDF invoice: {str(e)}")
            try:
                self._reset_to_main_screen()
            except:
                pass
            return downloaded_files

    # ==================== HELPER METHODS ====================

    # Dropdown anchored by its "Account number" label; survives layout reshuffles
    ACCOUNT_DROPDOWN_XPATH = '//app-dropdown[.//label[contains(normalize-space(.), "Account number")]]'

    def _verify_account_number(self, expected_account: str) -> None:
        """Ensures the expected account is the one selected on the page.

        The Previous bills page loads a default account in the "Account number"
        dropdown; when it differs from the expected one, the account is picked
        from the dropdown so the bill cards reload for the right account.

        Raises:
            ValueError: If the expected account cannot be selected/verified
        """
        self.logger.info(f"Verifying account number: {expected_account}")

        selected_xpath = f'{self.ACCOUNT_DROPDOWN_XPATH}//div[contains(@class, "selectedOption")]'
        if self.browser_wrapper.is_element_visible(selected_xpath, timeout=15000):
            displayed_account = self.browser_wrapper.get_text(selected_xpath).strip()
            self.logger.info(f"Account selected by default: {displayed_account}")

            if expected_account in displayed_account:
                self.logger.info("Account number verified successfully")
                return

            self._select_account_from_dropdown(expected_account)
            return

        # Fallback: account rendered as plain text (layout without dropdown)
        account_text_xpath = f'//*[contains(normalize-space(text()), "{expected_account}")]'
        if self.browser_wrapper.is_element_visible(account_text_xpath, timeout=5000):
            self.logger.info("Account number found on page, verified successfully")
            return

        self._log_page_diagnostics()
        error_msg = "Could not find account number element on page"
        self.logger.error(error_msg)
        raise ValueError(error_msg)

    def _select_account_from_dropdown(self, expected_account: str) -> None:
        """Opens the Account number dropdown and selects the expected account.

        Raises:
            ValueError: If the account is not listed or selection doesn't stick
        """
        self.logger.info(f"Selecting account {expected_account} from dropdown...")

        combobox_xpath = f'{self.ACCOUNT_DROPDOWN_XPATH}//div[@role="combobox"]'
        self.browser_wrapper.click_element(combobox_xpath)

        option_xpath = (
            f'{self.ACCOUNT_DROPDOWN_XPATH}//ul[@role="listbox"]'
            f'/li[@role="option"][contains(normalize-space(.), "{expected_account}")]'
        )
        if not self.browser_wrapper.is_element_visible(option_xpath, timeout=10000):
            self._log_page_diagnostics()
            error_msg = f"Account {expected_account} not available in Account number dropdown"
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        self.browser_wrapper.click_element(option_xpath)
        self.logger.info("Waiting 10 seconds for bills to reload...")
        time.sleep(10)

        # Switching accounts can reset the active tab back to Previous bills
        recent_bills_tab_xpath = '//li[contains(text(), "Recent bills")]'
        if self.browser_wrapper.is_element_visible(recent_bills_tab_xpath, timeout=5000):
            self.browser_wrapper.click_element(recent_bills_tab_xpath)
            self.logger.info("Recent bills tab re-selected, waiting 10 seconds for bills to load...")
            time.sleep(10)

        selected_xpath = f'{self.ACCOUNT_DROPDOWN_XPATH}//div[contains(@class, "selectedOption")]'
        displayed_account = self.browser_wrapper.get_text(selected_xpath).strip()
        if expected_account not in displayed_account:
            error_msg = (
                f"Account mismatch after selection! Expected: {expected_account}, " f"Found: {displayed_account}"
            )
            self.logger.error(error_msg)
            raise ValueError(error_msg)

        self.logger.info(f"Account {expected_account} selected and verified")

    def _dismiss_promo_modal(self) -> None:
        """Dismisses the post-login promotional modal that blocks navigation.

        After login Verizon shows a React-rendered promo modal ("Exclusive
        savings for you") whose full-page backdrop intercepts pointer events
        over the global nav, so every navigation click times out. Its
        styled-component classes are autogenerated and change between builds,
        so the modal is dismissed via its stable "close icon" affordance, with
        the Escape key as a fallback. No-op when no modal is present.
        """
        close_icon_xpath = '//*[@aria-label="close icon"]'
        try:
            if self.browser_wrapper.is_element_visible(close_icon_xpath, timeout=5000):
                self.logger.info("Promotional modal detected - dismissing it...")
                self.browser_wrapper.click_element(close_icon_xpath)
                time.sleep(2)
                self.logger.info("Promotional modal dismissed")
                return
            self.logger.info("No promotional modal present")
        except Exception as e:
            self.logger.warning(f"Could not dismiss promo modal via close icon ({e}); trying Escape")
            try:
                self.browser_wrapper.page.keyboard.press("Escape")
                time.sleep(2)
            except Exception:
                pass

    def _log_page_diagnostics(self) -> None:
        """Logs the current URL and visible headings to diagnose layout changes."""
        try:
            current_url = self.browser_wrapper.get_current_url()
            headings = self.browser_wrapper.page.evaluate(
                """() => Array.from(document.querySelectorAll('h1, h2, h3'))
                    .map(el => el.innerText.trim())
                    .filter(Boolean)
                    .slice(0, 10)"""
            )
            self.logger.info(f"Page diagnostics - URL: {current_url}, headings: {headings}")
        except Exception as e:
            self.logger.warning(f"Could not collect page diagnostics: {str(e)}")

    def _format_month_from_date(self, target_date: date) -> str:
        """Formats date to match invoice card format: 'Nov 2025'."""
        month_abbr = target_date.strftime("%b")  # 'Nov', 'Dec', etc.
        year = target_date.year
        return f"{month_abbr} {year}"

    def _download_invoice_by_month(self, target_month: str) -> Optional[str]:
        """Finds the invoice card matching the target month and clicks download."""
        try:
            self.logger.info(f"Searching for invoice card: {target_month}")

            # Wait for invoice cards to be visible
            invoice_card_xpath = "//div[contains(@class, 'invoice-card')]"
            if not self.browser_wrapper.is_element_visible(invoice_card_xpath, timeout=15000):
                self.logger.error("No invoice cards visible on page")
                return None

            # Find all invoice cards using Playwright's query_selector_all
            page = self.browser_wrapper.page
            invoice_cards = page.query_selector_all(".invoice-card")

            self.logger.info(f"Found {len(invoice_cards)} invoice cards")

            for idx, card in enumerate(invoice_cards):
                # Get the month text from span.fs-20
                month_span = card.query_selector("span.fs-20")
                if month_span:
                    month_text = month_span.inner_text().strip()
                    self.logger.info(f"Card {idx + 1}: {month_text}")

                    if month_text == target_month:
                        self.logger.info(f"Found matching invoice card: {month_text}")

                        # Find the download icon
                        download_icon = card.query_selector("span.Icon--download")
                        if download_icon:
                            self.logger.info("Downloading PDF invoice...")

                            # Use expect_download_and_click for reliable download
                            download_xpath = (
                                f"(//div[contains(@class, 'invoice-card')])[{idx + 1}]"
                                "//span[contains(@class, 'Icon--download')]"
                            )
                            file_path = self.browser_wrapper.expect_download_and_click(
                                download_xpath,
                                timeout=60000,
                                downloads_dir=self.job_downloads_dir,
                            )

                            if file_path:
                                self.logger.info(f"Download completed: {file_path}")
                                return file_path
                            else:
                                self.logger.error("expect_download_and_click returned None")
                                return None
                        else:
                            self.logger.error("Download icon not found in matching card")
                            return None

            self.logger.error(f"No matching invoice card found for {target_month}")
            return None

        except Exception as e:
            self.logger.error(f"Error downloading invoice: {str(e)}")
            return None

    def _reset_to_main_screen(self):
        """Resets to Verizon main screen."""
        try:
            self.logger.info("Resetting to Verizon main screen...")
            home_xpath = '//*[@id="gNavHeader"]/div/div/div[1]/div[2]/header/div/div/div[1]/div/a'

            if self.browser_wrapper.is_element_visible(home_xpath, timeout=5000):
                self.browser_wrapper.click_element(home_xpath)
                self.browser_wrapper.wait_for_page_load()
                time.sleep(3)
                self.logger.info("Reset completed")

        except Exception as e:
            self.logger.error(f"Error resetting: {str(e)}")
