"""Окно просмотра архива БД — только сборка окна и регистрация."""
import dearpygui.dearpygui as dpg

from Temperature_Measure import _layout
from .Archive_Constants import WINDOW_TAG, TABLE_GROUP, TABLE_CONTAINER
from .Archive_UI import _build_filter_bar, _build_info_panel
from .Archive_Cascade import _bootstrap


def _register_for_window_manager():
    try:
        from window_manager import register, rebuild_menu
    except Exception:
        return
    register(WINDOW_TAG, "Архив БД", create_archive_view_window)
    try:
        rebuild_menu()
    except Exception:
        pass


def create_archive_view_window(dpg_ctx=None):
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
    w = max(900, sw - margin * 2)
    h = max(550, sh - margin * 2)
    right_w = 340
    left_w = max(500, w - right_w - 24)

    with dpg.window(label="Просмотр архива БД",
                    width=w, height=h, pos=(margin, margin),
                    tag=WINDOW_TAG, no_collapse=True):
        _build_filter_bar()
        with dpg.group(horizontal=True):
            with dpg.child_window(tag=TABLE_GROUP, width=left_w,
                                  height=-1, border=False):
                dpg.add_text("Результаты поиска",
                             tag='archive_status_text')
                dpg.add_separator()
                with dpg.group(tag=TABLE_CONTAINER):
                    dpg.add_text(
                        "- нажмите <Загрузить> для поиска -",
                        tag='archive_table_hint', color=(140, 140, 140))
            with dpg.child_window(width=right_w, height=-1, border=True):
                _build_info_panel()

    _bootstrap()
    _register_for_window_manager()