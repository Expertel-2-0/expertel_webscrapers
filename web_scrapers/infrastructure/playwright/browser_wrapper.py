import os
import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper


class PlaywrightWrapper(BrowserWrapper):

    def __init__(self, page: Page):
        self.page = page

    def _resolve_selector(self, selector: str, selector_type: str = "xpath") -> str:
        strategies = {
            "xpath": lambda s: f"xpath={s}",
            "css": lambda s: s,
            "pierce": lambda s: f"pierce={s}",
        }

        try:
            return strategies[selector_type](selector)
        except KeyError:
            raise ValueError(f"Invalid selector_type: {selector_type}")

    def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        self.page.goto(url, wait_until=wait_until)

    def find_element_by_xpath(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> bool:
        try:
            resolved = self._resolve_selector(selector, selector_type)
            self.page.wait_for_selector(resolved, timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            return False

    def click_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)
        self.page.click(resolved)

    def double_click_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)
        self.page.dblclick(resolved)

    def type_text(self, selector: str, text: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)
        self.page.type(resolved, text)

    def clear_and_type(self, selector: str, text: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)
        locator = self.page.locator(resolved)
        locator.fill(text)

    def select_dropdown_option(
        self, selector: str, option_text: str, timeout: int = 10000, selector_type: str = "xpath"
    ) -> None:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)
        self.page.select_option(resolved, label=option_text)

    def select_dropdown_by_value(
        self, selector: str, value: str, timeout: int = 10000, selector_type: str = "xpath"
    ) -> None:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)
        self.page.select_option(resolved, value=value)

    def get_text(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> str:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)
        return self.page.text_content(resolved) or ""

    def get_attribute(self, selector: str, attribute: str, timeout: int = 10000, selector_type: str = "xpath") -> str:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)
        return self.page.get_attribute(resolved, attribute) or ""

    def wait_for_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)

    def wait_for_page_load(self, timeout: int = 60000) -> None:
        self.page.wait_for_load_state("networkidle", timeout=timeout)

    def is_element_visible(self, selector: str, timeout: int = 5000, selector_type: str = "xpath") -> bool:
        try:
            resolved = self._resolve_selector(selector, selector_type)
            self.page.wait_for_selector(resolved, timeout=timeout)
            return self.page.is_visible(resolved)
        except PlaywrightTimeoutError:
            return False

    def get_current_url(self) -> str:
        return self.page.url

    def take_screenshot(self, path: str) -> None:
        self.page.screenshot(path=path)

    def wait_for_navigation(self, timeout: int = 30000) -> None:
        self.page.wait_for_load_state("networkidle", timeout=timeout)

    def press_key(self, selector: str, key: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)
        self.page.press(resolved, key)

    def hover_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)
        self.page.hover(resolved)

    def scroll_to_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        self.page.wait_for_selector(resolved, timeout=timeout)
        self.page.locator(resolved).scroll_into_view_if_needed()

    def get_page_title(self) -> str:
        return self.page.title()

    def reload_page(self) -> None:
        self.page.reload()

    def refresh(self) -> None:
        self.page.reload()

    def go_back(self) -> None:
        self.page.go_back()

    def go_forward(self) -> None:
        self.page.go_forward()

    def wait_for_new_tab(self, timeout: int = 10000) -> None:
        raise NotImplementedError

    def switch_to_new_tab(self) -> None:
        pages = self.page.context.pages
        for page in reversed(pages):
            if not page.is_closed():
                self.page = page
                self.page.bring_to_front()
                return
        raise RuntimeError("No new tab available or all tabs are closed.")

    def close_current_tab(self) -> None:
        self.page.close()
        remaining_pages = [p for p in self.page.context.pages if not p.is_closed()]
        if remaining_pages:
            self.page = remaining_pages[-1]
            self.page.bring_to_front()
        else:
            raise RuntimeError("All tabs have been closed.")

    def switch_to_previous_tab(self) -> None:
        pages = self.page.context.pages
        current_index = self.get_current_tab_index()
        previous_index = current_index - 1
        if 0 <= previous_index < len(pages):
            page = pages[previous_index]
            if not page.is_closed():
                self.page = page
                self.page.bring_to_front()
                return
        raise RuntimeError("Could not switch to the previous tab.")

    def switch_to_tab_by_index(self, index: int) -> None:
        pages = self.page.context.pages
        if 0 <= index < len(pages):
            page = pages[index]
            if not page.is_closed():
                self.page = page
                self.page.bring_to_front()
                return
            else:
                raise RuntimeError(f"The tab at index {index} is closed.")
        raise ValueError(f"Index out of range: {index}")

    def get_tab_count(self) -> int:
        return len(self.page.context.pages)

    def clear_browser_data(
        self, clear_cookies: bool = True, clear_storage: bool = True, clear_cache: bool = True
    ) -> None:
        try:
            context = self.page.context
            if clear_cookies:
                context.clear_cookies()
            if clear_storage or clear_cache:
                self.page.evaluate(
                    """
                    () => {
                        if (localStorage) localStorage.clear();
                        if (sessionStorage) sessionStorage.clear();
                    }
                """
                )
        except Exception as e:
            print(f"⚠️ Error clearing browser data: {e}")

    def close_all_tabs_except_main(self) -> None:
        try:
            pages = self.page.context.pages
            main_page = pages[0] if pages else None
            for i in range(len(pages) - 1, 0, -1):
                try:
                    pages[i].close()
                except:
                    pass
            if main_page and not main_page.is_closed():
                self.page = main_page
                self.page.bring_to_front()
        except Exception as e:
            print(f"❌ Error closing tabs: {e}")

    def get_current_tab_index(self) -> int:
        try:
            pages = self.page.context.pages
            for i, page in enumerate(pages):
                if page == self.page:
                    return i
            return -1
        except:
            return -1

    def change_button_attribute(self, xpath: str, attribute: str, value: str) -> None:
        self.page.evaluate(
            f"""
            () => {{
                const el = document.evaluate("{xpath}", document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
                if (el) {{
                    el.setAttribute("{attribute}", "{value}");
                    if ("{attribute}" === "disabled" && "{value}" === "false") {{
                        el.disabled = false;
                    }}
                }}
            }}
            """
        )

    def expect_download_and_click(
        self, selector: str, timeout: int = 30000, selector_type: str = "xpath", downloads_dir: str = None
    ) -> str | None:
        resolved = self._resolve_selector(selector, selector_type)
        try:
            with self.page.expect_download(timeout=timeout) as download_info:
                self.page.click(resolved)

            download = download_info.value
            suggested_filename = download.suggested_filename

            if downloads_dir is None:
                downloads_dir = os.path.abspath("downloads")
            os.makedirs(downloads_dir, exist_ok=True)
            file_path = os.path.join(downloads_dir, suggested_filename)

            download.save_as(file_path)
            return file_path

        except Exception as e:
            print(f"Error during download: {str(e)}")
            return None

    def get_page_content(self) -> str:
        return self.page.content()

    def click_and_switch_to_new_tab(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        with self.page.context.expect_page(timeout=timeout) as new_page_info:
            self.page.click(resolved)

        new_tab = new_page_info.value
        new_tab.bring_to_front()
        self.page = new_tab
        self.page.wait_for_load_state("load")
