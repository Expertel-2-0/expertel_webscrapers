import logging
import os
import re
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


class RogersPDFInvoiceScraperStrategy(PDFInvoiceScraperStrategy):
    """Scraper de facturas PDF para Rogers."""

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navega a la seccion de facturas PDF de Rogers."""
        try:
            self.logger.info("Navigating to Rogers PDF invoices...")

            if not self._click_view_bills():
                self.logger.error("Failed to click View Bills link")
                return None

            if not self._select_billing_period(billing_cycle.end_date):
                self.logger.error("Failed to select billing period")
                return None

            if not self._ensure_accounts_only_view():
                self.logger.error("Failed to set 'Accounts Only' view")
                return None

            self.logger.info("Navigation completed - View Bills page configured")
            return {"section": "pdf_invoices", "ready_for_download": True}

        except Exception as e:
            self.logger.error(f"Error navigating to PDF invoices: {str(e)}")
            return None

    def _click_view_bills(self) -> bool:
        """Click en el link 'View Bills' del panel izquierdo de la landing page."""
        try:
            view_bills_xpath = (
                '//*[@id="landing_left_pan"]/div[2]'
                '//a[contains(@href, "prm-bizInvoicePayment") '
                'and normalize-space(.//span)="View Bills"]'
            )
            self.logger.info("Clicking View Bills link...")

            if not self.browser_wrapper.is_element_visible(view_bills_xpath, timeout=10000):
                self.logger.error("View Bills link not found")
                return False

            self.browser_wrapper.click_element(view_bills_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)
            return True

        except Exception as e:
            self.logger.error(f"Error clicking View Bills: {str(e)}")
            return False

    def _select_billing_period(self, end_date: date) -> bool:
        """Selecciona la opcion del dropdown #invoice_dates que coincida con mes/anio del billing cycle.

        El dia se ignora: Rogers usa siempre el bill date (ej. '23-Apr-2026') pero
        el billing_cycle.end_date puede tener otro dia. Se hace match por 'MMM-YYYY'.
        """
        try:
            dropdown_xpath = '//*[@id="invoice_dates"]'

            if not self.browser_wrapper.is_element_visible(dropdown_xpath, timeout=10000):
                self.logger.error("Invoice dates dropdown not found")
                return False

            target_suffix = f"{end_date.strftime('%b')}-{end_date.year}"
            self.logger.info(f"Searching for billing period matching: {target_suffix}")

            options = self.browser_wrapper.page.locator(f"xpath={dropdown_xpath}//option").all()
            for option in options:
                value = option.get_attribute("value") or ""
                if value.endswith(target_suffix):
                    self.logger.info(f"Found matching billing period: {value}")
                    self.browser_wrapper.select_dropdown_by_value(dropdown_xpath, value)
                    time.sleep(2)
                    return True

            self.logger.error(f"No billing period option found for {target_suffix}")
            return False

        except Exception as e:
            self.logger.error(f"Error selecting billing period: {str(e)}")
            return False

    def _normalize_account_number(self, account: str) -> str:
        """Normalizes account number by removing dashes, spaces and other characters."""
        return re.sub(r"[^0-9]", "", account)

    def _find_account_row(self, account_number: str) -> Optional[Any]:
        """Busca en #tableSorterListId la fila cuyo numero de cuenta coincide.

        Normaliza primero el account target y luego cada celda (ej. '6-3294-3981'
        -> '632943981') antes de comparar. Retorna el locator de la <tr> o None.
        """
        try:
            table_xpath = '//*[@id="tableSorterListId"]'

            if not self.browser_wrapper.is_element_visible(table_xpath, timeout=10000):
                self.logger.error("Bills table not found")
                return None

            normalized_account = self._normalize_account_number(account_number)
            if not normalized_account:
                self.logger.error(f"Invalid account number: '{account_number}'")
                return None

            self.logger.info(
                f"Looking for account '{account_number}' (normalized: '{normalized_account}')"
            )

            rows = self.browser_wrapper.page.locator(
                f"xpath={table_xpath}/tbody/tr[contains(@class, 'even') or contains(@class, 'odd')]"
            ).all()
            self.logger.info(f"Found {len(rows)} account rows in bills table")

            for i, row in enumerate(rows):
                account_cell = row.locator("xpath=.//td[contains(@class, 'textData')]")
                if account_cell.count() == 0:
                    continue

                cell_text = (account_cell.first.text_content() or "").strip()
                normalized_cell = self._normalize_account_number(cell_text)

                self.logger.info(
                    f"Row {i}: '{cell_text}' -> normalized: '{normalized_cell}'"
                )

                if normalized_cell == normalized_account:
                    self.logger.info(f"Found matching account row: '{cell_text}'")
                    return row

            self.logger.warning(f"Account '{account_number}' not found in bills table")
            return None

        except Exception as e:
            self.logger.error(f"Error finding account row: {str(e)}")
            return None

    def _ensure_accounts_only_view(self) -> bool:
        """Fuerza el dropdown #invoiceShowTypeList al valor 'accountsView' (Accounts Only)."""
        try:
            dropdown_xpath = '//*[@id="invoiceShowTypeList"]'

            if not self.browser_wrapper.is_element_visible(dropdown_xpath, timeout=10000):
                self.logger.error("Invoice show type dropdown not found")
                return False

            self.browser_wrapper.select_dropdown_by_value(dropdown_xpath, "accountsView")
            time.sleep(2)
            self.logger.info("Selected 'Accounts Only' view")
            return True

        except Exception as e:
            self.logger.error(f"Error setting accounts only view: {str(e)}")
            return False

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Descarga las facturas PDF de Rogers."""
        downloaded_files = []

        pdf_file = billing_cycle.pdf_files[0] if billing_cycle.pdf_files else None
        if pdf_file:
            self.logger.info(f"Mapping PDF Invoice file -> BillingCyclePDFFile ID {pdf_file.id}")
        else:
            self.logger.warning("BillingCyclePDFFile not found for mapping")

        try:
            self.logger.info("Downloading PDF invoices...")

            account_number = billing_cycle.account.number
            account_row = self._find_account_row(account_number)
            if not account_row:
                self.logger.error(f"Account {account_number} not found in bills table")
                self._reset_to_main_screen()
                return downloaded_files

            if not self._click_view_bill(account_row):
                self._reset_to_main_screen()
                return downloaded_files

            downloaded_file_path = self._download_complete_bill_pdf()
            if not downloaded_file_path:
                self.logger.error("Failed to download Complete bill PDF")
                self._reset_to_main_screen()
                return downloaded_files

            actual_file_name = os.path.basename(downloaded_file_path)
            self.logger.info(f"File downloaded successfully: {actual_file_name}")

            file_info = FileDownloadInfo(
                file_id=pdf_file.id if pdf_file else 1,
                file_name=actual_file_name,
                download_url="N/A",
                file_path=downloaded_file_path,
                pdf_file=pdf_file,
            )
            downloaded_files.append(file_info)

            if pdf_file:
                self.logger.info(
                    f"MAPPING CONFIRMED: {actual_file_name} -> BillingCyclePDFFile ID {pdf_file.id}"
                )
            else:
                self.logger.warning("File downloaded without specific BillingCyclePDFFile mapping")

            self._reset_to_main_screen()

            self.logger.info(f"PDF download completed: {len(downloaded_files)} file(s)")
            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error during PDF download: {str(e)}")
            try:
                self._reset_to_main_screen()
            except Exception:
                pass
            return downloaded_files

    def _click_view_bill(self, account_row: Any) -> bool:
        """Click en el link 'View Bill' dentro de la fila de la cuenta encontrada."""
        try:
            view_bill_link = account_row.locator(
                "xpath=.//a[@id='banDownloadBriteBill' and normalize-space(text())='View Bill']"
            )
            if view_bill_link.count() == 0:
                view_bill_link = account_row.locator(
                    "xpath=.//a[normalize-space(text())='View Bill']"
                )

            if view_bill_link.count() == 0:
                self.logger.error("View Bill link not found in account row")
                return False

            self.logger.info("Clicking View Bill link...")
            view_bill_link.first.click()
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)
            return True

        except Exception as e:
            self.logger.error(f"Error clicking View Bill: {str(e)}")
            return False

    def _download_complete_bill_pdf(self) -> Optional[str]:
        """Espera al boton 'Download Bill', lo abre y descarga 'Complete bill' del tooltip.

        La pagina del bill puede tardar hasta 1 min en renderizar el boton de descarga.
        Al hacer click en #save_desktop aparece un tooltip (#tippy-1) con opciones;
        'Complete bill' dispara la descarga inmediatamente.
        """
        try:
            download_bill_xpath = '//*[@id="save_desktop"]'
            self.logger.info("Waiting up to 60s for 'Download Bill' button to appear...")
            self.browser_wrapper.wait_for_element(download_bill_xpath, timeout=60000)

            self.logger.info("Clicking 'Download Bill' to open download options tooltip...")
            self.browser_wrapper.click_element(download_bill_xpath)
            time.sleep(2)

            complete_bill_xpath = (
                '//*[@id="tippy-1"]/div'
                '//span[contains(@class, "downloadPdfEbuLink-rogers") '
                'and normalize-space(text())="Complete bill"]'
            )

            if not self.browser_wrapper.find_element_by_xpath(complete_bill_xpath, timeout=10000):
                self.logger.error("'Complete bill' option not found in tooltip")
                return None

            self.logger.info("Clicking 'Complete bill' and capturing download...")
            downloaded_file_path = self.browser_wrapper.expect_download_and_click(
                complete_bill_xpath, timeout=60000, downloads_dir=self.job_downloads_dir
            )
            self.logger.debug(f"Downloaded file path: {downloaded_file_path}")
            return downloaded_file_path

        except Exception as e:
            self.logger.error(f"Error downloading Complete bill PDF: {str(e)}")
            return None

    def _reset_to_main_screen(self):
        """Reset a la pantalla inicial de Rogers."""
        try:
            self.logger.info("Resetting to Rogers main screen...")
            self.browser_wrapper.goto("https://bss.rogers.com/bizonline/homePage.do")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)
            self.logger.info("Reset completed")
        except Exception as e:
            self.logger.error(f"Error during reset: {str(e)}")
