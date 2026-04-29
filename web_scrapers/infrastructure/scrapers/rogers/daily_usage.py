import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper
from web_scrapers.domain.entities.models import BillingCycle, ScraperConfig
from web_scrapers.domain.entities.scraper_strategies import (
    DailyUsageScraperStrategy,
    FileDownloadInfo,
)

DOWNLOADS_DIR = os.path.abspath("downloads")
os.makedirs(DOWNLOADS_DIR, exist_ok=True)


class RogersDailyUsageScraperStrategy(DailyUsageScraperStrategy):
    """Scraper de uso diario para Rogers.

    Flow:
    1. Navigate to Manage Data Notifications tab
    2. Search and select account
    3. Click on account in table
    4. Navigate to Data Usage Tracking tab
    5. Extract pool_size and pool_used
    6. Click Shared Group User List
    7. Select all pages of users
    8. Click View Data Usage
    9. Extract all user data from paginated table
    10. Generate Excel file with extracted data
    """

    def __init__(self, browser_wrapper: BrowserWrapper, job_id: int):
        super().__init__(browser_wrapper, job_id=job_id)
        self.logger = logging.getLogger(self.__class__.__name__)
        self.pool_size: Optional[int] = None
        self.pool_used: Optional[int] = None

    # ==================== CONVERSION UTILITIES (same as Bell/Telus) ====================

    def _gb_to_bytes(self, gb_value: float) -> int:
        """Convert GB to bytes."""
        return int(gb_value * 1024 * 1024 * 1024)

    def _extract_gb_value(self, text: str) -> float:
        """Extract numeric GB value from text."""
        match = re.search(r"([\d,]+\.?\d*)\s*GB", text, re.IGNORECASE)
        if match:
            return float(match.group(1).replace(",", ""))
        return 0.0

    def _parse_gb_to_bytes(self, value_text: str) -> int:
        """Parses a GB value to bytes (combines extract and convert)."""
        try:
            if not value_text:
                return 0
            gb_value = self._extract_gb_value(value_text)
            return self._gb_to_bytes(gb_value)
        except Exception as e:
            self.logger.warning(f"Error parsing '{value_text}' to bytes: {str(e)}")
            return 0

    # ==================== NORMALIZATION UTILITIES ====================

    def _normalize_account_number(self, account: str) -> str:
        """Normalizes account number by removing dashes, spaces and other characters."""
        return re.sub(r"[^0-9]", "", account)

    def _normalize_phone_number(self, phone: str) -> str:
        """Normalizes phone number by removing dashes, spaces and other characters."""
        return re.sub(r"[^0-9]", "", phone)

    # ==================== MAIN SCRAPER METHODS ====================

    def _find_files_section(self, config: ScraperConfig, billing_cycle: BillingCycle) -> Optional[Any]:
        """Navega a la seccion de uso diario de Rogers."""
        try:
            self.logger.info("=== STARTING ROGERS DAILY USAGE SCRAPER ===")
            account_number = billing_cycle.account.number

            # Step 1: Click on Manage Data Notifications tab
            if not self._navigate_to_manage_data_notifications():
                return None

            # Step 2: Search and select account
            if not self._search_and_select_account(account_number):
                return None

            # Step 3: Click on account in table
            if not self._click_account_in_table(account_number):
                return None

            # Step 4: Navigate to Data Usage Tracking tab
            if not self._navigate_to_data_usage_tracking():
                return None

            # Step 5: Extract pool_size and pool_used
            self._extract_pool_data()

            self.logger.info("Navigation completed - ready for data extraction")
            return {
                "section": "daily_usage",
                "ready_for_download": True,
                "pool_size": self.pool_size,
                "pool_used": self.pool_used,
            }

        except Exception as e:
            self.logger.error(f"Error navigating to daily usage section: {str(e)}")
            return None

    def _download_files(
        self, files_section: Any, config: ScraperConfig, billing_cycle: BillingCycle
    ) -> List[FileDownloadInfo]:
        """Extrae los datos de uso diario y genera Excel."""
        downloaded_files = []

        daily_usage_file = billing_cycle.daily_usage_files[0] if billing_cycle.daily_usage_files else None
        if daily_usage_file:
            self.logger.info(f"Mapping Daily Usage file -> BillingCycleDailyUsageFile ID {daily_usage_file.id}")

        try:
            self.logger.info("=== STARTING DATA EXTRACTION ===")

            # Step 6: Click Shared Group User List
            if not self._click_shared_group_user_list():
                self._reset_to_main_screen()
                return downloaded_files

            # Step 7: Select all pages of users
            if not self._select_all_user_pages():
                self._reset_to_main_screen()
                return downloaded_files

            # Step 8: Click View Data Usage
            if not self._click_view_data_usage():
                self._reset_to_main_screen()
                return downloaded_files

            # Step 9: Extract all user data from paginated table
            user_data = self._extract_all_user_data()

            if not user_data:
                self.logger.error("No user data extracted")
                self._reset_to_main_screen()
                return downloaded_files

            self.logger.info(f"Extracted {len(user_data)} users")

            # Step 10: Generate Excel file
            file_path = self._generate_excel(user_data)

            if file_path:
                actual_filename = os.path.basename(file_path)
                self.logger.info(f"Excel generated: {actual_filename}")

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

            self._reset_to_main_screen()

            self.logger.info(f"=== DOWNLOAD COMPLETED: {len(downloaded_files)} file(s) ===")
            return downloaded_files

        except Exception as e:
            self.logger.error(f"Error extracting daily usage data: {str(e)}")
            try:
                self._reset_to_main_screen()
            except:
                pass
            return downloaded_files

    # ==================== NAVIGATION METHODS ====================

    def _navigate_to_manage_data_notifications(self) -> bool:
        """Navigates to Manage Data Notifications tab."""
        try:
            self.logger.info("Clicking on Manage Data Notifications tab...")
            tab_xpath = '//*[@id="header_menu"]//a[@href="/bizonline/prm-duns.do"]'

            if not self.browser_wrapper.is_element_visible(tab_xpath, timeout=10000):
                self.logger.error("Manage Data Notifications tab not found")
                return False

            self.browser_wrapper.click_element(tab_xpath)
            time.sleep(5)
            self.logger.info("Navigated to Manage Data Notifications")
            return True

        except Exception as e:
            self.logger.error(f"Error navigating to Manage Data Notifications: {str(e)}")
            return False

    def _search_and_select_account(self, account_number: str) -> bool:
        """Searches for account and selects it from results."""
        try:
            self.logger.info(f"Searching for account: {account_number}")

            search_field_xpath = '//*[@id="searchField"]'
            if not self.browser_wrapper.is_element_visible(search_field_xpath, timeout=10000):
                self.logger.error("Search field not found")
                return False

            # Type account number character by character (like other Rogers scrapers)
            page = self.browser_wrapper.page
            search_field = page.locator(f"xpath={search_field_xpath}")
            search_field.click()
            time.sleep(0.5)
            search_field.fill("")
            search_field.type(account_number, delay=100)
            time.sleep(3)

            # Wait for autocomplete results
            results_div_xpath = "//div[contains(@class, 'ac_results')]"
            if not self.browser_wrapper.is_element_visible(results_div_xpath, timeout=10000):
                self.logger.error("Autocomplete results not found")
                return False

            # Find matching account and click Select
            normalized_account = self._normalize_account_number(account_number)
            self.logger.info(f"Looking for account (normalized): {normalized_account}")

            # Get all result items
            results_items = page.locator(f"xpath={results_div_xpath}//li")
            count = results_items.count()
            self.logger.info(f"Found {count} autocomplete results")

            for i in range(count):
                item = results_items.nth(i)
                row_name_span = item.locator(".rowName").first

                if row_name_span.count() > 0:
                    row_text = row_name_span.text_content() or ""
                    normalized_row = self._normalize_account_number(row_text)

                    self.logger.info(f"Result {i}: '{row_text}' -> normalized: '{normalized_row}'")

                    if normalized_row == normalized_account:
                        self.logger.info(f"Found matching account: {row_text}")
                        select_button = item.locator("a.buttongray")
                        if select_button.count() > 0:
                            select_button.click()
                            time.sleep(5)
                            self.logger.info("Account selected successfully")
                            return True

            self.logger.error(f"Account {account_number} not found in results")
            return False

        except Exception as e:
            self.logger.error(f"Error searching/selecting account: {str(e)}")
            return False

    def _click_account_in_table(self, account_number: str) -> bool:
        """Clicks on account number in the accounts table."""
        try:
            self.logger.info("Looking for account in table...")
            table_xpath = '//*[@id="dunsAccountsListTableId"]'

            if not self.browser_wrapper.is_element_visible(table_xpath, timeout=10000):
                self.logger.error("Accounts table not found")
                return False

            normalized_account = self._normalize_account_number(account_number)
            page = self.browser_wrapper.page

            # Find all account links in table
            account_links = page.locator(f"xpath={table_xpath}//tbody//tr//td//a[contains(@onclick, 'getDunsCtns')]")
            count = account_links.count()
            self.logger.info(f"Found {count} account links in table")

            for i in range(count):
                link = account_links.nth(i)
                link_text = link.text_content() or ""
                normalized_link = self._normalize_account_number(link_text)

                if normalized_link == normalized_account:
                    self.logger.info(f"Found matching account link: {link_text}")
                    link.click()
                    time.sleep(10)
                    self.logger.info("Clicked on account, waiting for page load...")
                    return True

            self.logger.error(f"Account {account_number} not found in table")
            return False

        except Exception as e:
            self.logger.error(f"Error clicking account in table: {str(e)}")
            return False

    def _navigate_to_data_usage_tracking(self) -> bool:
        """Navigates to Data Usage Tracking tab."""
        try:
            self.logger.info("Looking for Data Usage Tracking tab...")
            tab_xpath = '//*[@id="BanUsageTab"]'

            if not self.browser_wrapper.is_element_visible(tab_xpath, timeout=10000):
                self.logger.error("Data Usage Tracking tab not found")
                return False

            # Verify tab text
            tab_text = self.browser_wrapper.get_text(tab_xpath)
            if "Data Usage Tracking" not in tab_text:
                self.logger.warning(f"Tab text mismatch: '{tab_text}', clicking anyway...")

            self.browser_wrapper.click_element(tab_xpath)
            time.sleep(5)
            self.logger.info("Navigated to Data Usage Tracking tab")
            return True

        except Exception as e:
            self.logger.error(f"Error navigating to Data Usage Tracking: {str(e)}")
            return False

    # ==================== DATA EXTRACTION METHODS ====================

    def _extract_pool_data(self) -> None:
        """Extracts pool_used and pool_size from the page."""
        try:
            self.logger.info("Extracting pool data...")

            # Extract pool_used from div
            pool_used_xpath = '//*[@id="spanUsage_pooled"]/div/div/div/div[2]'
            if self.browser_wrapper.is_element_visible(pool_used_xpath, timeout=5000):
                pool_used_text = self.browser_wrapper.get_text(pool_used_xpath)
                self.pool_used = self._parse_gb_to_bytes(pool_used_text)
                self.logger.info(f"Pool used: {pool_used_text} -> {self.pool_used} bytes")
            else:
                self.logger.warning("Pool used element not found")

            # Extract pool_size from span
            pool_size_xpath = '//*[@id="BanUsage"]/div/table[2]/tbody/tr[1]/td/span[2]'
            if self.browser_wrapper.is_element_visible(pool_size_xpath, timeout=5000):
                pool_size_text = self.browser_wrapper.get_text(pool_size_xpath)
                self.pool_size = self._parse_gb_to_bytes(pool_size_text)
                self.logger.info(f"Pool size: {pool_size_text} -> {self.pool_size} bytes")
            else:
                self.logger.warning("Pool size element not found")

        except Exception as e:
            self.logger.error(f"Error extracting pool data: {str(e)}")

    def _click_shared_group_user_list(self) -> bool:
        """Clicks on Shared Group User List button."""
        try:
            self.logger.info("Looking for Shared Group User List button...")
            button_xpath = '//*[@id="getCTNsPGId"]'

            if not self.browser_wrapper.is_element_visible(button_xpath, timeout=10000):
                self.logger.error("Shared Group User List button not found")
                return False

            # Verify button value
            button_value = self.browser_wrapper.get_attribute(button_xpath, "value")
            if "Shared Group User List" not in button_value:
                self.logger.warning(f"Button value mismatch: '{button_value}', clicking anyway...")

            self.browser_wrapper.click_element(button_xpath)
            time.sleep(5)
            self.logger.info("Clicked Shared Group User List")
            return True

        except Exception as e:
            self.logger.error(f"Error clicking Shared Group User List: {str(e)}")
            return False

    def _select_all_user_pages(self) -> bool:
        """Selects all users across all pages."""
        try:
            self.logger.info("Selecting all users across pages...")
            page = self.browser_wrapper.page

            page_count = 0
            while True:
                page_count += 1
                self.logger.info(f"Processing page {page_count}...")

                # Click "select this page"
                select_page_xpath = '//*[@id="dunsSelectPage"]/span'
                if self.browser_wrapper.is_element_visible(select_page_xpath, timeout=5000):
                    select_text = self.browser_wrapper.get_text(select_page_xpath)
                    if "select this page" in select_text.lower():
                        self.browser_wrapper.click_element(select_page_xpath)
                        time.sleep(2)
                        self.logger.info(f"Selected page {page_count}")
                    else:
                        self.logger.warning(f"Unexpected select text: '{select_text}'")
                else:
                    self.logger.warning("Select this page element not found")

                # Check if next button is available (anchor, not span)
                pagination_xpath = '//*[@id="mypagination"]'
                if not self.browser_wrapper.is_element_visible(pagination_xpath, timeout=3000):
                    self.logger.info("No pagination found, single page")
                    break

                # Check if next is an anchor (enabled) or span (disabled)
                next_anchor = page.locator(f"xpath={pagination_xpath}//a[contains(@class, 'next')]")
                next_span = page.locator(f"xpath={pagination_xpath}//span[contains(@class, 'next')]")

                if next_anchor.count() > 0:
                    self.logger.info("Clicking next page...")
                    next_anchor.click()
                    time.sleep(3)
                elif next_span.count() > 0:
                    self.logger.info("Reached last page (next is disabled)")
                    break
                else:
                    self.logger.info("No next button found, assuming single page")
                    break

            self.logger.info(f"Selected users across {page_count} page(s)")
            return True

        except Exception as e:
            self.logger.error(f"Error selecting user pages: {str(e)}")
            return False

    def _click_view_data_usage(self) -> bool:
        """Clicks on View Data Usage button."""
        try:
            self.logger.info("Looking for View Data Usage button...")
            button_xpath = '//*[@id="selectedCtnsId"]'

            if not self.browser_wrapper.is_element_visible(button_xpath, timeout=10000):
                self.logger.error("View Data Usage button not found")
                return False

            # Verify button value
            button_value = self.browser_wrapper.get_attribute(button_xpath, "value")
            if "View Data Usage" not in button_value:
                self.logger.warning(f"Button value mismatch: '{button_value}', clicking anyway...")

            self.browser_wrapper.click_element(button_xpath)
            time.sleep(10)
            self.logger.info("Clicked View Data Usage, waiting for data table...")
            return True

        except Exception as e:
            self.logger.error(f"Error clicking View Data Usage: {str(e)}")
            return False

    def _extract_all_user_data(self) -> List[Dict[str, Any]]:
        """Extracts all user data from paginated table."""
        all_users = []

        try:
            self.logger.info("Extracting user data from table...")
            page = self.browser_wrapper.page

            page_count = 0
            while True:
                page_count += 1
                self.logger.info(f"Extracting data from page {page_count}...")

                # Extract data from current page
                users_on_page = self._extract_users_from_current_page()
                all_users.extend(users_on_page)
                self.logger.info(f"Extracted {len(users_on_page)} users from page {page_count}")

                # Check pagination
                pagination_xpath = '//*[@id="mypagination"]'
                if not self.browser_wrapper.is_element_visible(pagination_xpath, timeout=3000):
                    break

                # Check if next is enabled
                next_anchor = page.locator(f"xpath={pagination_xpath}//a[contains(@class, 'next')]")
                next_span = page.locator(f"xpath={pagination_xpath}//span[contains(@class, 'next')]")

                if next_anchor.count() > 0:
                    self.logger.info("Clicking next page for more data...")
                    next_anchor.click()
                    time.sleep(3)
                elif next_span.count() > 0:
                    self.logger.info("Reached last page of data")
                    break
                else:
                    break

            self.logger.info(f"Total users extracted: {len(all_users)}")
            return all_users

        except Exception as e:
            self.logger.error(f"Error extracting user data: {str(e)}")
            return all_users

    def _extract_users_from_current_page(self) -> List[Dict[str, Any]]:
        """Extracts user data from the current page's table."""
        users = []

        try:
            page = self.browser_wrapper.page
            table_xpath = '//*[@id="dunsAccountsListTableId"]'

            if not self.browser_wrapper.is_element_visible(table_xpath, timeout=5000):
                self.logger.warning("Data table not found on current page")
                return users

            # Get all data rows (skip header rows - those with class extract-table-body in first td)
            rows = page.locator(f"xpath={table_xpath}//tbody//tr[contains(@class, 'odd') or contains(@class, 'even')]")
            row_count = rows.count()

            for i in range(row_count):
                try:
                    row = rows.nth(i)

                    # Skip header/subheader rows
                    first_td = row.locator("td").first
                    if first_td.count() > 0:
                        first_td_class = first_td.get_attribute("class") or ""
                        if "extract-table-body" in first_td_class:
                            continue

                    # Extract Mobile User Name (first td)
                    name_td = row.locator("td").nth(0)
                    mobile_username = (name_td.text_content() or "").strip()

                    # Extract Mobile Number (second td)
                    number_td = row.locator("td").nth(1)
                    mobile_number_raw = (number_td.text_content() or "").strip()
                    mobile_number = self._normalize_phone_number(mobile_number_raw)

                    if not mobile_number:
                        continue

                    # Extract Real-time Usage from span with id spanUsage_{phone}
                    data_used = 0
                    usage_span_id = f"spanUsage_{mobile_number}"
                    usage_div = row.locator(
                        f"xpath=.//span[@id='{usage_span_id}']//div[contains(@style, 'position: absolute')]"
                    )

                    if usage_div.count() > 0:
                        usage_text = (usage_div.first.text_content() or "").strip()
                        data_used = self._parse_gb_to_bytes(usage_text)

                    users.append({
                        "mobile_username": mobile_username,
                        "mobile_number": mobile_number,
                        "data_used": data_used,
                    })

                except Exception as row_error:
                    self.logger.warning(f"Error extracting row {i}: {str(row_error)}")
                    continue

        except Exception as e:
            self.logger.error(f"Error extracting users from page: {str(e)}")

        return users

    # ==================== FILE GENERATION ====================

    def _generate_excel(self, user_data: List[Dict[str, Any]]) -> Optional[str]:
        """Generates Excel file with user data."""
        try:
            self.logger.info("Generating Excel file...")

            # Create DataFrame
            df = pd.DataFrame(user_data)

            # Ensure correct column order
            df = df[["mobile_username", "mobile_number", "data_used"]]

            # Generate filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"rogers_daily_usage_{timestamp}.xlsx"
            file_path = os.path.join(self.job_downloads_dir, filename)

            # Save to Excel
            df.to_excel(file_path, index=False, engine="openpyxl")

            self.logger.info(f"Excel saved: {file_path}")
            return file_path

        except Exception as e:
            self.logger.error(f"Error generating Excel: {str(e)}")
            return None

    # ==================== RESET ====================

    def _reset_to_main_screen(self):
        """Reset a la pantalla inicial de Rogers."""
        try:
            self.logger.info("Resetting to Rogers main screen...")
            self.browser_wrapper.goto("https://bss.rogers.com/bizonline/homePage.do")
            self.browser_wrapper.wait_for_page_load()
            time.sleep(3)
            self.logger.info("Reset completed")
        except Exception as e:
            self.logger.error(f"Error resetting to main screen: {str(e)}")

    def get_pool_data(self) -> Dict[str, Optional[int]]:
        """Returns pool data extracted during navigation."""
        return {
            "pool_size": self.pool_size,
            "pool_used": self.pool_used,
        }
