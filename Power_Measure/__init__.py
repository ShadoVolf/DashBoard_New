# Power_Measure/__init__.py
"""Модуль измерения мощности (Power_Measure) для DashBoard_New.

Регистрирует окно в меню «Окна» так же, как это делают остальные модули
(см. Archive_View/Archive_Window.py, Temperature_Measure и др.).
"""
import dearpygui.dearpygui as dpg
from .main_gui import App

_app_instance = None
_WIN_TAG_DEFAULT = "power_measure_window"
_WIN_LABEL = "Измерение мощности"


def _window_manager():
    """Возвращает модуль window_manager DashBoard_New или None."""
    try:
        import window_manager
        return window_manager
    except ImportError:
        return None


def _register_in_window_menu(win_tag):
    """Регистрирует окно в меню «Окна» главного меню DashBoard_New.

    Повторяет поведение других модулей: register() + rebuild_menu().
    Имена функций подобраны с запасом — сработает та, что есть в проекте.
    """
    wm = _window_manager()
    if wm is None:
        return

    # 1) Регистрация окна
    register_fn = (
        getattr(wm, "register", None)
        or getattr(wm, "register_window", None)
        or getattr(wm, "add_window", None)
    )
    if register_fn is not None:
        try:
            register_fn(win_tag, _WIN_LABEL, create_power_measure_window)
        except TypeError:
            # возможная другая сигнатура: (tag, label)
            try:
                register_fn(win_tag, _WIN_LABEL)
            except Exception:
                pass
        except Exception:
            pass

    # 2) Перестроение меню «Окна»
    rebuild_fn = (
        getattr(wm, "rebuild_menu", None)
        or getattr(wm, "rebuild_windows_menu", None)
        or getattr(wm, "refresh_menu", None)
    )
    if rebuild_fn is not None:
        try:
            rebuild_fn()
        except Exception:
            pass


def create_power_measure_window():
    """Создаёт или показывает окно модуля измерения мощности.

    Вызывается из меню «Измерения» и из меню «Окна» (через window_manager).
    """
    global _app_instance

    if _app_instance is None:
        _app_instance = App()

    win_tag = getattr(_app_instance, "win_tag", _WIN_TAG_DEFAULT)

    if dpg.does_item_exist(win_tag):
        # Окно уже создано — показываем и фокусируем
        dpg.configure_item(win_tag, show=True)
        try:
            dpg.focus_item(win_tag)
        except Exception:
            pass
    else:
        # Создаём окно (размер вычисляется внутри build() по _layout.screen_size())
        _app_instance.build()

    # Регистрация в меню «Окна» — как в остальных модулях
    _register_in_window_menu(win_tag)
    return _app_instance