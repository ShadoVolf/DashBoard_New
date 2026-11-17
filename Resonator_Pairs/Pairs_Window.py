"""Окно модуля формирования пар — только сборка."""
import dearpygui.dearpygui as dpg

from Temperature_Measure import _layout
from .Pairs_Constants import (
    WINDOW_TAG, SEARCH_CONTAINER, POOL_CONTAINER, PAIRS_CONTAINER,
)
from .Pairs_UI import (
    _build_filter_bar, _build_pairs_controls, _bootstrap_pairs, _build_print_saved_section,
)


def _register_for_window_manager():
    try:
        from window_manager import register, rebuild_menu
    except Exception:
        return
    register(WINDOW_TAG, "Формирование пар резонаторов",
             create_pairs_window)
    try:
        rebuild_menu()
    except Exception:
        pass


def create_pairs_window(dpg_ctx=None):
    if dpg.does_item_exist(WINDOW_TAG):
        dpg.configure_item(WINDOW_TAG, show=True)
        try:
            dpg.focus_item(WINDOW_TAG)
        except Exception:
            pass
        _register_for_window_manager()
        return

    sw, sh = _layout.screen_size()
    margin = 8
    w = max(1000, sw - margin * 2)
    h = max(700, sh - margin * 2)

    with dpg.window(label="Формирование пар резонаторов",
                    width=w, height=h, pos=(margin, margin),
                    tag=WINDOW_TAG, no_collapse=True):

        dpg.add_text("Поиск замеров (аналогично «Архив БД»)",
                     color=(180, 220, 255))
        dpg.add_separator()
        _build_filter_bar()

        dpg.add_text("Результаты поиска",
                     tag='rp_status_text', color=(200, 220, 255))
        dpg.add_group(tag=SEARCH_CONTAINER)

        dpg.add_separator()

        with dpg.group(horizontal=True):
            dpg.add_text("Пул резонаторов", color=(180, 220, 255))
            dpg.add_text("Свободных: —", tag='rp_pool_count',
                         color=(160, 160, 160))
        dpg.add_group(tag=POOL_CONTAINER)

        dpg.add_separator()

        _build_pairs_controls()

        dpg.add_separator()

        dpg.add_text("Сформированные пары",
                     color=(180, 220, 255))
        dpg.add_group(tag=PAIRS_CONTAINER)

        dpg.add_separator()
        _build_print_saved_section()  # <-- новая строка

    _bootstrap_pairs()
    _register_for_window_manager()