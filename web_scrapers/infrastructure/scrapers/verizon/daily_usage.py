import logging
import os
import time
from typing import Any, List, Optional

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    DailyUsageScraperStrategy,
    FileDownloadInfo,
)

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class VerizonDailyUsageScraperStrategy(DailyUsageScraperStrategy):
    """Daily usage scraper for Verizon.

    Downloads Account unbilled usage report.

    Flow:
    1. Navigate to Reports tab -> Reports Home
    2. Click on Usage tab
    3. Click on "Account unbilled usage" report
    4. Configure filters (View by: Account number, Select number: account)
    5. Apply changes and download report
    """

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navigates to Verizon Usage reports section."""
        try:
            self.logger.info("Navigating to Verizon daily usage reports...")

            # Dismiss the post-login promotional modal ("Exclusive savings for
            # you") before navigating. Its React-rendered backdrop intercepts
            # pointer events over the global nav, so every navigation click
            # times out while it is open.
            self._dismiss_promo_modal()

            # 1. Click on Reports tab
            reports_tab_xpath = '//*[@id="gNavHeader"]/div/div/div[1]/div[2]/header/div/div/div[2]/nav/ul/li[4]/a'
            self.logger.info("Clicking on Reports tab...")

            if self.browser_wrapper.is_element_visible(reports_tab_xpath, timeout=10000):
                self.browser_wrapper.click_element(reports_tab_xpath)
                time.sleep(2)
            else:
                self.logger.error("Reports tab not found")
                self._reset_to_main_screen()
                return None

            # 2. Click on Reports Home
            reports_home_xpath = '//*[@id="gNavHeader"]/div/div/div[1]/div[2]/header/div/div/div[2]/nav/ul/li[4]/div/div/div[1]/div/ul/li[1]/a'
            self.logger.info("Clicking on Reports Home...")

            if self.browser_wrapper.is_element_visible(reports_home_xpath, timeout=5000):
                self.browser_wrapper.click_element(reports_home_xpath)
                self.logger.info("Waiting 15 seconds for Reports page to load...")
                time.sleep(15)
            else:
                self.logger.error("Reports Home option not found")
                self._reset_to_main_screen()
                return None

            # 3. Click on Usage tab
            usage_tab_xpath = '//li[@data-track="Usage"]'
            self.logger.info("Clicking on Usage tab...")

            if self.browser_wrapper.is_element_visible(usage_tab_xpath, timeout=10000):
                self.browser_wrapper.click_element(usage_tab_xpath)
                self.logger.info("Waiting 5 seconds for Usage reports to load...")
                time.sleep(5)
            else:
                self.logger.error("Usage tab not found")
                self._reset_to_main_screen()
                return None

            self.logger.info("Navigation to Usage section completed")
            return {"section": "daily_usage", "ready_for_download": True}

        except Exception as e:
            self.logger.error(f"Error navigating to daily usage: {str(e)}")
            self._reset_to_main_screen()
            return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Downloads the Account unbilled usage report."""
        downloaded_files = []

        # Get the BillingCycleDailyUsageFile from billing_cycle
        daily_usage_file = billing_cycle.daily_usage_files[0] if billing_cycle.daily_usage_files else None
        if daily_usage_file:
            self.logger.info(f"Mapping to BillingCycleDailyUsageFile ID {daily_usage_file.id}")

        try:
            self.logger.info("Starting download of Account unbilled usage report...")

            # 1. Click on "Account unbilled usage" report
            account_unbilled_xpath = '//div[@data-track="Usage reports: Account unbilled usage"]'
            self.logger.info("Clicking on Account unbilled usage report...")

            if self.browser_wrapper.is_element_visible(account_unbilled_xpath, timeout=10000):
                self.browser_wrapper.click_element(account_unbilled_xpath)
                self.logger.info("Waiting 10 seconds for report page to load...")
                time.sleep(10)
            else:
                self.logger.error("Account unbilled usage report not found")
                self._reset_to_main_screen()
                return downloaded_files

            # 2. Configure filters
            account_number = billing_cycle.account.number
            self.logger.info(f"Configuring filters for account: {account_number}")
            self._configure_filters(account_number)

            # 3. Click Apply changes
            self._click_apply_filters()
            self.logger.info("Waiting 10 seconds after applying filters...")
            time.sleep(10)

            # 4. Download full report
            file_path = self._download_full_report()

            if file_path:
                actual_filename = os.path.basename(file_path)
                self.logger.info(f"Account unbilled usage downloaded: {actual_filename}")

                file_info = FileDownloadInfo(
                    file_id=daily_usage_file.id if daily_usage_file else 0,
                    file_name=actual_filename,
                    download_url="N/A",
                    file_path=file_path,
                    daily_usage_file=daily_usage_file,
                )
                downloaded_files.append(file_info)

                if daily_usage_file:
                    self.logger.info(
                        f"MAPPING CONFIRMED: {actual_filename} -> BillingCycleDailyUsageFile ID {daily_usage_file.id}"
                    )
            else:
                self.logger.error("Could not download Account unbilled usage report")

            # Reset to main screen
            self._reset_to_main_screen()

            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error downloading daily usage: {str(e)}")
            try:
                self._reset_to_main_screen()
            except:
                pass
            return downloaded_files

    # ==================== HELPER METHODS ====================

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

    def _configure_filters(self, account_number: str):
        """Configures View by and Select number filters."""
        try:
            # View by dropdown - click to open
            view_by_xpath = (
                "//div[contains(@class, 'filter-inputs') and contains(@class, 'viewby')]"
                "//app-dropdown//div[@role='combobox']"
            )

            if self.browser_wrapper.is_element_visible(view_by_xpath, timeout=5000):
                self.browser_wrapper.click_element(view_by_xpath)
                time.sleep(1)

                # Select "Account number" option
                account_option_xpath = (
                    "//ul[@role='listbox']//li[@role='option' and contains(text(), 'Account number')]"
                )
                if self.browser_wrapper.is_element_visible(account_option_xpath, timeout=3000):
                    self.browser_wrapper.click_element(account_option_xpath)
                    self.logger.info("Selected 'Account number' in View by")
                    time.sleep(1)

            # Select number dropdown - click to open
            select_number_xpath = (
                "//span[contains(@class, 'font-10') and contains(text(), 'Select number')]"
                "/following-sibling::div//app-dropdown//div[@role='combobox']"
            )

            if self.browser_wrapper.is_element_visible(select_number_xpath, timeout=5000):
                self.browser_wrapper.click_element(select_number_xpath)
                time.sleep(1)

                # Select account that contains the number
                account_option_xpath = (
                    f"//ul[@role='listbox']//li[@role='option' and contains(text(), '{account_number}')]"
                )
                if self.browser_wrapper.is_element_visible(account_option_xpath, timeout=3000):
                    self.browser_wrapper.click_element(account_option_xpath)
                    self.logger.info(f"Selected account: {account_number}")

        except Exception as e:
            self.logger.warning(f"Error configuring filters: {str(e)}")

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
