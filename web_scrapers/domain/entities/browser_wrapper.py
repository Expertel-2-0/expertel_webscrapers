from abc import ABC, abstractmethod
from typing import Any, List, Optional


class BrowserWrapper(ABC):
    # CURRENT SCRAPER NAVIGATOR (PAGE)

    @abstractmethod
    def goto(self, url: str, wait_until: str = "load") -> None:
        """Navega a una URL específica."""
        raise NotImplementedError()

    @abstractmethod
    def find_element_by_xpath(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> bool:
        """Encuentra un elemento por XPath, CSS o pierce según selector_type."""
        raise NotImplementedError()

    @abstractmethod
    def click_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        """Hace clic en un elemento usando XPath, CSS o pierce según selector_type."""
        raise NotImplementedError()

    @abstractmethod
    def double_click_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        """Hace doble clic en un elemento usando XPath, CSS o pierce según selector_type."""
        raise NotImplementedError()

    @abstractmethod
    def type_text(self, selector: str, text: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        """Escribe texto en un campo identificado por un selector."""
        raise NotImplementedError()

    @abstractmethod
    def clear_and_type(self, selector: str, text: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        """Limpia un campo y escribe texto nuevo."""
        raise NotImplementedError()

    @abstractmethod
    def select_dropdown_option(
        self, selector: str, option_text: str, timeout: int = 10000, selector_type: str = "xpath"
    ) -> None:
        """Selecciona una opción por texto."""
        raise NotImplementedError()

    @abstractmethod
    def select_dropdown_by_value(
        self, selector: str, value: str, timeout: int = 10000, selector_type: str = "xpath"
    ) -> None:
        """Selecciona una opción por valor."""
        raise NotImplementedError()

    @abstractmethod
    def get_text(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> str:
        """Obtiene el texto de un elemento."""
        raise NotImplementedError()

    @abstractmethod
    def get_attribute(self, selector: str, attribute: str, timeout: int = 10000, selector_type: str = "xpath") -> str:
        """Obtiene un atributo de un elemento."""
        raise NotImplementedError()

    @abstractmethod
    def wait_for_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        """Espera a que un elemento esté visible."""
        raise NotImplementedError()

    @abstractmethod
    def wait_for_page_load(self, timeout: int = 60000) -> None:
        """Espera a que la página cargue completamente."""
        raise NotImplementedError()

    @abstractmethod
    def is_element_visible(self, selector: str, timeout: int = 5000, selector_type: str = "xpath") -> bool:
        """Verifica si un elemento está visible."""
        raise NotImplementedError()

    @abstractmethod
    def get_current_url(self) -> str:
        """Obtiene la URL actual."""
        raise NotImplementedError()

    @abstractmethod
    def take_screenshot(self, path: str) -> None:
        """Toma una captura de pantalla."""
        raise NotImplementedError()

    @abstractmethod
    def wait_for_navigation(self, timeout: int = 30000) -> None:
        """Espera a que la navegación se complete."""
        raise NotImplementedError()

    @abstractmethod
    def press_key(self, selector: str, key: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        """Presiona una tecla en un elemento específico."""
        raise NotImplementedError()

    @abstractmethod
    def hover_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        """Hace hover sobre un elemento."""
        raise NotImplementedError()

    @abstractmethod
    def scroll_to_element(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        """Hace scroll hasta un elemento específico."""
        raise NotImplementedError()

    @abstractmethod
    def get_page_title(self) -> str:
        """Obtiene el título de la página actual."""
        raise NotImplementedError()

    @abstractmethod
    def reload_page(self) -> None:
        """Recarga la página actual."""
        raise NotImplementedError()

    @abstractmethod
    def go_back(self) -> None:
        """Navega hacia atrás en el historial."""
        raise NotImplementedError()

    @abstractmethod
    def go_forward(self) -> None:
        """Navega hacia adelante en el historial."""
        raise NotImplementedError()

    @abstractmethod
    def wait_for_new_tab(self, timeout: int = 10000) -> None:
        """Espera a que se abra una nueva pestaña."""
        raise NotImplementedError()

    @abstractmethod
    def switch_to_new_tab(self) -> None:
        """Cambia a la nueva pestaña abierta."""
        raise NotImplementedError()

    @abstractmethod
    def close_current_tab(self) -> None:
        """Cierra la pestaña actual."""
        raise NotImplementedError()

    @abstractmethod
    def switch_to_previous_tab(self) -> None:
        """Regresa a la pestaña anterior."""
        raise NotImplementedError()

    @abstractmethod
    def switch_to_tab_by_index(self, index: int) -> None:
        """Cambia a una pestaña específica por índice."""
        raise NotImplementedError()

    @abstractmethod
    def get_tab_count(self) -> int:
        """Obtiene el número de pestañas abiertas."""
        raise NotImplementedError()

    @abstractmethod
    def clear_browser_data(
        self, clear_cookies: bool = True, clear_storage: bool = True, clear_cache: bool = True
    ) -> None:
        """Limpia datos del navegador para resolver problemas de caché."""
        raise NotImplementedError()

    @abstractmethod
    def close_all_tabs_except_main(self) -> None:
        """Cierra todas las pestañas excepto la principal (índice 0)."""
        raise NotImplementedError()

    @abstractmethod
    def get_current_tab_index(self) -> int:
        """Obtiene el índice de la pestaña actual."""
        raise NotImplementedError()

    @abstractmethod
    def change_button_attribute(self, xpath: str, attribute: str, value: str) -> None:
        """Cambia un atributo usando JavaScript."""
        raise NotImplementedError()

    @abstractmethod
    def expect_download_and_click(
        self, selector: str, timeout: int = 30000, selector_type: str = "xpath", downloads_dir: str = None
    ) -> Optional[str]:
        """Hace clic esperando una descarga."""
        raise NotImplementedError()

    @abstractmethod
    def get_page_content(self) -> str:
        """Obtiene el contenido HTML completo de la página actual."""
        raise NotImplementedError()

    @abstractmethod
    def click_and_switch_to_new_tab(self, selector: str, timeout: int = 10000, selector_type: str = "xpath") -> None:
        """Hace clic en un enlace que abre una nueva pestaña."""
        raise NotImplementedError()
