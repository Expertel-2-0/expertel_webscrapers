import calendar
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


class BellPDFInvoiceScraperStrategy(PDFInvoiceScraperStrategy):
    """PDF invoice scraper for Bell."""

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Busca la seccion de facturas PDF en el portal de Bell."""
        try:
            # Navegar a la seccion de billing y download PDF
            self._navigate_to_pdf_section()

            # Determine if account selection is needed (Version 1) or already preselected (Version 2)
            search_input_xpath = "/html[1]/body[1]/div[1]/main[1]/div[1]/uxp-flow[1]/div[2]/account-selection[1]/div[2]/section[1]/div[1]/account-selection-global-search[1]/div[1]/div[2]/section[2]/div[1]/div[1]/account-search[1]/div[1]/div[1]/div[1]/input[1]"
            account_selection_needed = self.browser_wrapper.find_element_by_xpath(search_input_xpath, timeout=10000)

            if account_selection_needed:
                self.logger.info("Version 1: Account selection required")
                self._handle_pdf_account_selection(billing_cycle)
            else:
                self.logger.info("Version 2: Account already preselected, continuing direct")

            # Parte comun: Configurar opciones de descarga de PDF
            self._configure_pdf_download_options(billing_cycle)

            return {"section": "pdf_invoices", "ready_for_download": True}

        except Exception as e:
            self.logger.error(f"Error in _find_files_section: {str(e)}")
            return None

    def _navigate_to_pdf_section(self):
        """Navega a la seccion de descarga de PDF (parte inicial comun)."""
        self.logger.info("Navigating to PDF download section...")

        # billing tab (hover)
        billing_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/nav[1]/ul[1]/li[3]/a[1]"
        self.browser_wrapper.hover_element(billing_xpath)
        time.sleep(2)

        # download pdf section (click)
        download_pdf_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[2]/nav[1]/ul[1]/li[3]/div[1]/ul[1]/li[1]/ul[1]/li[3]/a[1]"
        self.browser_wrapper.click_element(download_pdf_xpath)
        self.browser_wrapper.wait_for_page_load()
        time.sleep(5)
        self.logger.info("Navigation to PDF completed")

    def _handle_pdf_account_selection(self, billing_cycle: BillingCycle):
        """Maneja la seleccion de cuenta cuando es necesaria (Version 1)."""
        self.logger.info("Executing account selection for PDF...")

        # search input (enter billing_cycle.account.number)
        search_input_xpath = "/html[1]/body[1]/div[1]/main[1]/div[1]/uxp-flow[1]/div[2]/account-selection[1]/div[2]/section[1]/div[1]/account-selection-global-search[1]/div[1]/div[2]/section[2]/div[1]/div[1]/account-search[1]/div[1]/div[1]/div[1]/input[1]"
        self.browser_wrapper.type_text(search_input_xpath, billing_cycle.account.number)

        # search button (click)
        search_button_xpath = "/html[1]/body[1]/div[1]/main[1]/div[1]/uxp-flow[1]/div[2]/account-selection[1]/div[2]/section[1]/div[1]/account-selection-global-search[1]/div[1]/div[2]/section[2]/div[1]/div[1]/account-search[1]/div[1]/div[1]/div[2]/button[1]"
        self.browser_wrapper.click_element(search_button_xpath)
        time.sleep(3)

        # select account (click)
        select_account_xpath = "/html[1]/body[1]/div[1]/main[1]/div[1]/uxp-flow[1]/div[2]/account-selection[1]/div[2]/section[1]/div[1]/account-selection-global-search[1]/div[1]/section[1]/div[1]/search[1]/div[2]/div[1]/div[2]/table[1]/tbody[1]/tr[1]/td[1]/label[1]/span[1]"
        self.browser_wrapper.click_element(select_account_xpath)
        time.sleep(2)

        # continue (click)
        continue_xpath = "/html[1]/body[1]/div[1]/main[1]/div[1]/uxp-flow[1]/div[2]/account-selection[1]/div[9]/selection-dock[1]/div[1]/div[1]/div[1]/div[4]/button[1]"
        self.browser_wrapper.click_element(continue_xpath)
        self.browser_wrapper.wait_for_page_load()
        time.sleep(5)
        self.logger.info("Account selected successfully")

    def _configure_pdf_download_options(self, billing_cycle: BillingCycle):
        """Configura las opciones de descarga de PDF (parte comun)."""
        self.logger.info("Configuring PDF download options...")

        # Verificar que estamos en la pagina correcta
        complete_invoice_radiobtn_xpath = "//input[@name='invoiceSelect' and @value='Y']"
        if not self.browser_wrapper.find_element_by_xpath(complete_invoice_radiobtn_xpath, timeout=5000):
            raise Exception("No se encontro el radio button de opciones de descarga")

        # complete invoice (click)
        complete_invoice_label_xpath = (
            "//label[.//input[@name='invoiceSelect' and @value='Y']]//span[@class='txt']"
        )
        self.browser_wrapper.click_element(complete_invoice_label_xpath)
        time.sleep(5)
        self.logger.info("Complete invoice selected")

        # Seleccionar fecha mas cercana al end_date del billing_cycle
        self._select_closest_date_checkbox(billing_cycle)

    def _select_closest_date_checkbox(self, billing_cycle: BillingCycle):
        """Selecciona el checkbox de fecha mas cercano al end_date del billing_cycle."""
        self.logger.info("Selecting closest date...")

        target_month = billing_cycle.end_date.month
        target_year = billing_cycle.end_date.year
        target_month_name = calendar.month_name[target_month]
        target_period = f"{target_month_name} {target_year}"

        self.logger.info(f"Searching checkbox for: {target_period}")

        try:
            # Buscar por texto exacto en el label
            checkbox_xpath = f"//label[contains(., '{target_period}')]/span[1]"
            if self.browser_wrapper.find_element_by_xpath(checkbox_xpath, timeout=3000):
                self.browser_wrapper.click_element(checkbox_xpath)
                self.logger.info(f"Checkbox selected for: {target_period}")
                return
        except:
            self.logger.warning(f"Exact checkbox not found for {target_period}")

        try:
            self.logger.info("Searching for available checkboxes...")
            # Buscar todos los checkboxes disponibles en la seccion
            checkboxes_section_xpath = (
                "/html/body/div[1]/main/div[1]/uxp-flow/div[3]/download-options/div/div/section[2]"
            )

            # Como fallback, usar el primer checkbox disponible
            fallback_checkbox_xpath = f"{checkboxes_section_xpath}//div[@class='grd-col-1-4'][1]//label/span[1]"
            self.browser_wrapper.click_element(fallback_checkbox_xpath)
            self.logger.info("Fallback checkbox selected (first available option)")
        except Exception as e:
            self.logger.error(f"Error selecting date checkbox: {str(e)}")
            raise e

        time.sleep(5)

    def _handle_pdf_exit_flow(self):
        """Maneja el flujo de salida especifico para PDF downloads."""
        self.logger.info("Executing PDF exit flow...")

        try:
            # return to back to my account (click)
            back_to_account_xpath = "/html/body/div[1]/header/div/div/div/div[3]/div[1]/div/app-header/button[2]"
            self.browser_wrapper.click_element(back_to_account_xpath)
            self.logger.info("'Back to my account' button clicked")

            # wait 30 seconds
            self.logger.info("Waiting 30 seconds...")
            time.sleep(30)

            # click to leave page
            try:
                leave_page_xpath = (
                    "/html/body/div[1]/header/div/div/div/div[3]/div[1]/div/app-header/div/div/div/div/div/button[2]"
                )
                self.browser_wrapper.click_element(leave_page_xpath)
                self.logger.info("'Leave page' button clicked")
            except Exception as e:
                self.logger.info("Leave button didn't appear, you should see initial site")
            time.sleep(3)  # Pausa adicional antes del reset
            self.logger.info("PDF exit flow completed")

        except Exception as e:
            self.logger.warning(f"Error in PDF exit flow: {str(e)} - continuing with reset...")

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Descarga las facturas PDF de Bell."""
        downloaded_files = []

        # Obtener el BillingCyclePDFFile del billing_cycle
        pdf_file = billing_cycle.pdf_files[0] if billing_cycle.pdf_files else None
        if pdf_file:
            self.logger.info(f"Mapping PDF Invoice file -> BillingCyclePDFFile ID {pdf_file.id}")
        else:
            self.logger.warning("BillingCyclePDFFile not found for mapping")

        try:
            # download button (click) - usando nuevos XPaths
            download_button_xpath = "//*[@id='continueButton']"
            self.browser_wrapper.click_element(download_button_xpath)
            self.logger.info("Initial download button clicked")

            # wait 2 minutes for button to appear then click - usando nuevos XPaths
            self.logger.info("Waiting 2 minutes for final download button to appear...")
            final_download_button_xpath = (
                "/html/body/div[1]/main/div[1]/uxp-flow/div[3]/confirmation/div/div/section[1]/button[1]"
            )
            self.browser_wrapper.wait_for_element(final_download_button_xpath, timeout=120000)  # 2 minutes in ms

            # Descargar archivo PDF usando expect_download_and_click
            downloaded_file_path = self.browser_wrapper.expect_download_and_click(
                final_download_button_xpath, timeout=30000, downloads_dir=self.job_downloads_dir
            )
            self.logger.debug(f"Downloaded file path: {downloaded_file_path}")

            if downloaded_file_path:
                actual_file_name = os.path.basename(downloaded_file_path)
                self.logger.info(f"File downloaded successfully: {actual_file_name}")

                if actual_file_name.lower().endswith(".zip"):
                    self.logger.info("ZIP file detected, proceeding to extract...")
                    extracted_files = self._extract_zip_files(downloaded_file_path)
                    if extracted_files:
                        for i, extracted_file_path in enumerate(extracted_files):
                            extracted_file_name = os.path.basename(extracted_file_path)

                            # Crear FileDownloadInfo para cada archivo extraido
                            file_info = FileDownloadInfo(
                                file_id=pdf_file.id if pdf_file else (i + 1),
                                file_name=extracted_file_name,
                                download_url="N/A",
                                file_path=extracted_file_path,
                                pdf_file=pdf_file,
                            )
                            downloaded_files.append(file_info)

                            # Confirmar mapeo para cada archivo extraido
                            if pdf_file:
                                self.logger.info(
                                    f"MAPPING CONFIRMED: {extracted_file_name} -> BillingCyclePDFFile ID {pdf_file.id}"
                                )
                            else:
                                self.logger.warning(f"Extracted file without specific BillingCyclePDFFile mapping")
                    else:
                        self.logger.error("Could not extract files from ZIP")
                        # Usar el ZIP original como fallback
                        file_info = FileDownloadInfo(
                            file_id=pdf_file.id if pdf_file else 1,
                            file_name=actual_file_name,
                            download_url="N/A",
                            file_path=downloaded_file_path,
                            pdf_file=pdf_file,
                        )
                        downloaded_files.append(file_info)
                else:
                    self.logger.info("Regular file detected (not ZIP)")
                    file_info = FileDownloadInfo(
                        file_id=pdf_file.id if pdf_file else 1,
                        file_name=actual_file_name,
                        download_url="N/A",
                        file_path=downloaded_file_path,
                        pdf_file=pdf_file,
                    )
                    downloaded_files.append(file_info)

                    # Confirmar mapeo
                    if pdf_file:
                        self.logger.info(
                            f"MAPPING CONFIRMED: {actual_file_name} -> BillingCyclePDFFile ID {pdf_file.id}"
                        )
                    else:
                        self.logger.warning(f"File downloaded without specific BillingCyclePDFFile mapping")
            else:
                self.logger.warning("expect_download_and_click failed for PDF, using fallback method...")
                self.browser_wrapper.click_element(final_download_button_xpath)
                time.sleep(5)

                # Considerar que podria ser ZIP o PDF
                estimated_filename = f"bell_invoice_{billing_cycle.end_date.strftime('%Y-%m-%d')}.zip"
                fallback_path = f"{self.job_downloads_dir}/{estimated_filename}"

                file_info = FileDownloadInfo(
                    file_id=pdf_file.id,
                    file_name=estimated_filename,
                    download_url="N/A",
                    file_path=fallback_path,
                    pdf_file=pdf_file,
                )
                downloaded_files.append(file_info)
                self.logger.info(f"Download started (traditional method): {estimated_filename}")
                self.logger.warning(
                    "Note: If downloaded file is ZIP, extract manually or use _extract_zip_files function"
                )

            # Flujo de salida especifico para PDF
            self._handle_pdf_exit_flow()

            # Reset a pantalla inicial usando el logo
            self._reset_to_main_screen()

            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error downloading PDF file: {str(e)}")
            return downloaded_files

    def _reset_to_main_screen(self):
        """Reset a la pantalla inicial de Bell usando el logo."""
        try:
            self.logger.info("Resetting to Bell initial screen...")
            logo_xpath = "/html[1]/body[1]/div[1]/header[1]/div[2]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/div[1]/a[1]"
            self.browser_wrapper.click_element(logo_xpath)
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)
            self.logger.info("Reset to Bell completed")
        except Exception as e:
            self.logger.error(f"Error in Bell reset: {str(e)}")
