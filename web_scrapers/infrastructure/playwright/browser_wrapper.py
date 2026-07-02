import os
import random
import time

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError

from web_scrapers.domain.entities.browser_wrapper import BrowserWrapper


class PlaywrightWrapper(BrowserWrapper):

    def __init__(self, page: Page):
        self.page = page
        # Optional callback fired after every navigation-like action. Opt-in
        # via set_post_action_hook(). Used by TelusAuthStrategy to detect and
        # resolve Cloudflare challenges that appear mid-flow (between pages,
        # after a click, etc.) — see _post_action() for the recursion guard.
        self._post_action_hook = None
        self._in_post_action = False

    def set_post_action_hook(self, callback) -> None:
        """Register a no-arg callable that runs after goto / click / wait_for_page_load /
        wait_for_navigation. Pass None to clear. The hook is reentrancy-protected so
        the callback itself can call wrapper methods without infinite recursion.
        """
        self._post_action_hook = callback

    def _post_action(self) -> None:
        if self._post_action_hook is None or self._in_post_action:
            return
        self._in_post_action = True
        try:
            self._post_action_hook()
        except Exception:
            # Hook failures should never break the underlying navigation
            pass
        finally:
            self._in_post_action = False

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

    def _wait_for(self, resolved: str, timeout: int, raw_selector: str, selector_type: str) -> str:
        """Single choke point for element waits on action methods. Returns the
        resolved selector the caller should act on. Base behavior is identical
        to the previous inline page.wait_for_selector call; the self-healing
        subclass overrides this to recover from selector breaks (see
        web_scrapers/infrastructure/healing/).
        """
        self.page.wait_for_selector(resolved, timeout=timeout)
        return resolved

    def goto(self, url: str, wait_until: str = "domcontentloaded") -> None:
        self.page.goto(url, wait_until=wait_until)
        self._post_action()

    def find_element_by_xpath(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> bool:
        try:
            resolved = self._resolve_selector(selector, selector_type)
            self.page.wait_for_selector(resolved, timeout=timeout)
            return True
        except PlaywrightTimeoutError:
            return False

    def click_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        self.page.click(resolved)
        self._post_action()

    def double_click_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        self.page.dblclick(resolved)

    def type_text(self, selector: str, text: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        self.page.type(resolved, text)

    def clear_and_type(self, selector: str, text: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        locator = self.page.locator(resolved)
        locator.fill(text)

    # ------------------------------------------------------------------
    # Human-like interaction primitives (opt-in)
    # ------------------------------------------------------------------
    # reCAPTCHA Enterprise and similar adaptive anti-bot systems score the
    # browser partly on behavioral biometrics: mouse trajectory, keystroke
    # cadence, and time-on-page. The plain type_text()/click_element() helpers
    # emit a robotic signature — page.type() sends every character at ~0ms with
    # uniform spacing, and page.click() teleports to the element center with no
    # approach path. These methods reproduce the human-like mouse trajectory
    # already used for the Telus Cloudflare checkbox
    # (TelusAuthStrategy._humanlike_click_iframe) but generalized to any element,
    # plus per-character typing with randomized delays. They are opt-in: callers
    # that don't need them keep using the plain methods unchanged.

    def human_pause(self, min_seconds: float = 0.4, max_seconds: float = 1.2) -> None:
        """Sleep a randomized amount so inter-step pacing isn't machine-regular."""
        time.sleep(random.uniform(min_seconds, max_seconds))

    def human_click(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        """Click an element by driving page.mouse along a curved trajectory with a
        hover dwell and randomized button down/up timing, instead of Playwright's
        instant center-click. Falls back to a normal click if the element has no
        bounding box (e.g. zero-size / off-screen).
        """
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        locator = self.page.locator(resolved).first
        try:
            locator.scroll_into_view_if_needed(timeout=timeout)
        except Exception:
            pass

        box = locator.bounding_box()
        if not box:
            # No geometry to aim at — fall back to a normal click so the flow still works.
            self.page.click(resolved)
            self._post_action()
            return

        # Aim near the center with a little jitter so the click point isn't pixel-perfect.
        target_x = box["x"] + box["width"] / 2 + random.uniform(-box["width"] / 6, box["width"] / 6)
        target_y = box["y"] + box["height"] / 2 + random.uniform(-box["height"] / 6, box["height"] / 6)
        # Approach from an off-target waypoint so the path is curved, not a straight teleport.
        waypoint_x = target_x + random.uniform(-160, 160)
        waypoint_y = target_y - random.uniform(60, 160)

        self.page.mouse.move(waypoint_x, waypoint_y, steps=random.randint(8, 14))
        time.sleep(random.uniform(0.04, 0.12))
        self.page.mouse.move(target_x, target_y, steps=random.randint(18, 30))
        time.sleep(random.uniform(0.12, 0.35))  # hover dwell before pressing
        self.page.mouse.down()
        time.sleep(random.uniform(0.04, 0.11))
        self.page.mouse.up()
        self._post_action()

    def human_type(
        self,
        selector: str,
        text: str,
        timeout: int = 10000,
        selector_type: str = "xpath",
        clear_first: bool = True,
    ) -> None:
        """Focus the field with a human-like click, then type one character at a
        time with randomized inter-keystroke delays (and occasional longer
        pauses), instead of page.type()'s zero-delay uniform burst.
        """
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        # Click into the field like a person would, so focus + mouse activity register.
        self.human_click(selector, timeout=timeout, selector_type=selector_type)
        if clear_first:
            try:
                self.page.locator(resolved).first.fill("")
            except Exception:
                pass

        for char in text:
            self.page.keyboard.type(char)
            time.sleep(random.uniform(0.05, 0.18))
            # Occasionally hesitate a little longer, the way humans do mid-entry.
            if random.random() < 0.06:
                time.sleep(random.uniform(0.25, 0.6))

    def select_dropdown_option(
        self, selector: str, option_text: str, timeout: int = 10000, selector_type: str = "xpath"
    ) -> None:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        self.page.select_option(resolved, label=option_text)

    def select_dropdown_by_value(
        self, selector: str, value: str, timeout: int = 10000, selector_type: str = "xpath"
    ) -> None:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        self.page.select_option(resolved, value=value)

    def get_text(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> str:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        return self.page.text_content(resolved) or ""

    def get_attribute(self, selector: str, attribute: str, timeout: int = 10000, selector_type: str = "xpath") -> str:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        return self.page.get_attribute(resolved, attribute) or ""

    def wait_for_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)

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
        self._post_action()

    def wait_for_page_load(self, timeout: int = 60000) -> None:
        # Used by ~20 auth/scraper callsites that previously relied on a method removed
        # in commit 18db7ae. Restored with `domcontentloaded` instead of the original
        # `networkidle` (and the playwright default `load`) because both wait for
        # subresources/long-poll connections that on SPAs like Telus/Rogers/Bell never
        # settle, causing 60s timeouts that kill the run even though the page is
        # interactive. `domcontentloaded` returns as soon as the HTML is parsed, which
        # is what the callsites actually need before probing for selectors.
        self.page.wait_for_load_state("domcontentloaded", timeout=timeout)
        self._post_action()

    def press_key(self, selector: str, key: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        self.page.press(resolved, key)

    def hover_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
        self.page.hover(resolved)

    def scroll_to_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        resolved = self._resolve_selector(selector, selector_type)
        resolved = self._wait_for(resolved, timeout, selector, selector_type)
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
