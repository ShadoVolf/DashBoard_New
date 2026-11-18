"""Управление протоколами — точка входа.

Модуль разбит на части:
    - Protocol_Constants : теги, sentinels, разделяемое состояние
    - Protocol_Common    : диалоги, статусы, общие display-хелперы
    - Protocol_Create_Tab: вкладка «Создание протокола»
    - Protocol_Archive_Tab: вкладка «Архив протоколов» + заказ/даты/LotRK
"""
import dearpygui.dearpygui as dpg

from Temperature_Measure import _layout

from . import Protocol_Constants as _C
from .Protocol_Create_Tab import _build_create_tab, _pm_bootstrap
from .Protocol_Archive_Tab import _build_archive_tab, _pm_arch_bootstrap
from .Protocol_Data import ensure_order_columns
from .Protocol_Passport import print_passport_for_protocol


def _on_print_passport():
    if not _C._active_archive_id:
        try:
            from .Protocol_Common import _pm_arch_status
            _pm_arch_status('Сначала выберите протокол')
        except Exception:
            pass
        return
    print_passport_for_protocol(_C._active_archive_id)


def _register_for_window_manager():
    try:
        from window_manager import register, rebuild_menu
    except Exception:
        return
    register(_C.WINDOW_TAG, "Протоколы", create_protocol_manager_window)
    try:
        rebuild_menu()
    except Exception:
        pass


def create_protocol_manager_window():
    if dpg.does_item_exist(_C.WINDOW_TAG):
        dpg.show_item(_C.WINDOW_TAG)
        try:
            dpg.focus_item(_C.WINDOW_TAG)
        except Exception:
            pass
        _register_for_window_manager()
        return

    try:
        ensure_order_columns()
    except Exception as e:
        print(f"[Protocol] ensure_order_columns: {e}")

    sw, sh = _layout.screen_size()
    margin = 8
    w = max(900, sw - margin * 2)
    h = max(550, sh - margin * 2)

    with dpg.window(label="Управление протоколами", tag=_C.WINDOW_TAG,
                    width=w, height=h, pos=(margin, margin),
                    no_collapse=True):
        with dpg.menu_bar():
            with dpg.menu(label="Действия с протоколом"):
                from .Protocol_Archive_Tab import (
                    _open_order_dialog, _open_arch_dates_dialog,
                    _on_send_to_lot_rk,
                )
                dpg.add_menu_item(
                    label="Номер заказа / Договор / Контрагент",
                    callback=lambda: _open_order_dialog())
                dpg.add_menu_item(
                    label="Установить даты (MakeDate / MakeDate1)",
                    callback=lambda: _open_arch_dates_dialog())
                dpg.add_separator()
                dpg.add_menu_item(
                    label="Отправить в ОТК (LotRK)",
                    callback=lambda: _on_send_to_lot_rk())
                dpg.add_separator()
                dpg.add_menu_item(
                    label="Печать паспорта",
                    callback=lambda: _on_print_passport())

        with dpg.tab_bar():
            with dpg.tab(label="Создание протокола"):
                _build_create_tab()
            with dpg.tab(label="Архив протоколов"):
                _build_archive_tab()

    _pm_bootstrap()
    _pm_arch_bootstrap()
    _register_for_window_manager()


__all__ = ['create_protocol_manager_window']
