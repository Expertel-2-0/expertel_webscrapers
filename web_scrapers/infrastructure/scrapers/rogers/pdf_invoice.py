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


class RogersPDFInvoiceScraperStrategy(PDFInvoiceScraperStrategy):
    """Scraper de facturas PDF para Rogers."""

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navega a la seccion de facturas PDF de Rogers."""
        try:
            print("Navigating to Rogers PDF invoices...")
            # Implementar navegacion especifica de Rogers
            print("Navigation completed")
            return {"section": "pdf_invoices", "ready_for_download": True}

        except Exception as e:
            print(f"Error navigating to PDF invoices: {str(e)}")
            return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Descarga las facturas PDF de Rogers."""
        downloaded_files = []

        try:
            print("Downloading PDF invoices...")
            # Implementar logica de descarga especifica de Rogers

            # Reset a pantalla principal
            self._reset_to_main_screen()

            print(f"PDF download completed: {len(downloaded_files)} file(s)")
            return downloaded_files

        except Exception as e:
            print(f"Error during PDF download: {str(e)}")
            try:
                self._reset_to_main_screen()
            except:
                pass
            return downloaded_files

    def _reset_to_main_screen(self):
        """Reset a la pantalla inicial de Rogers."""
        try:
            print("Resetting to Rogers...")
            time.sleep(3)
            print("Reset completed")
        except Exception as e:
            print(f"Error during reset: {str(e)}")
