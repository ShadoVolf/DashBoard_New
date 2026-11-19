"""Вкладка «Архив протоколов» + заказ + даты + LotRK."""
import pandas as pd
import dearpygui.dearpygui as dpg

from Temperature_Measure import _layout
from Archive_View.Archive_Data import parse_numbers_input
from Archive_View.Archive_Constants import ALL_MSK
from Archive_View.Archive_UI import _screen_safe

from . import Protocol_Constants as _C
from .Protocol_Common import (
    _pm_arch_status, _show_warning, _show_info,
    _pm_load_spc_map_for_display,
    _build_display_cols, _render_data_table,
    _pm_fill_arch_norms, _pm_fill_arch_info,
)
from .Protocol_Data import (
    search_archived_protocols, get_archive_protocol_data,
    add_numbers_to_protocol, remove_numbers_from_protocol,
    delete_protocol_completely, log_action,
    get_protocol_by_id,
    get_protocol_types, get_protocol_specs_by_type,
    get_protocol_msk_list, get_protocol_dates_list,
    get_protocol_files_list,
    save_order_info, save_make_dates,
    update_psidata_make_dates, send_to_lot_rk,
    get_protocol_order_info,
    get_lot_numbers, get_lot_spc_list, get_lot_dates_list, get_lot_details,
)
from .Protocol_Print import print_archived_protocol

from .Protocol_Passport import print_passport_for_protocol
# ============================================================================
# Bootstrap — фикс: каскад запускается ВНЕ suppress
# ============================================================================
def _pm_arch_bootstrap():
    from .Protocol_Common import clear_presentation_params_cache
    clear_presentation_params_cache()  # <-- добавить
    try:
        types = get_protocol_types()
        dpg.configure_item('pm_arch_type_combo', items=types)
        if types:
            # Ставим значение без рекурсивного каскада
            _C._arch_suppress = True
            try:
                dpg.set_value('pm_arch_type_combo', types[0])
            finally:
                _C._arch_suppress = False
            # Явный запуск каскада
            _on_arch_type_changed()
        else:
            _C._arch_suppress = True
            try:
                dpg.configure_item('pm_arch_spc_combo', items=[])
                dpg.set_value('pm_arch_spc_combo', '')
                dpg.configure_item('pm_arch_msk_combo', items=[ALL_MSK])
                dpg.set_value('pm_arch_msk_combo', ALL_MSK)
                dpg.configure_item('pm_arch_date_combo',
                                   items=[_C.ARCH_ALL_DATES])
                dpg.set_value('pm_arch_date_combo', _C.ARCH_ALL_DATES)
                dpg.configure_item('pm_arch_file_combo',
                                   items=[_C.ARCH_ALL_FILES])
                dpg.set_value('pm_arch_file_combo', _C.ARCH_ALL_FILES)
            finally:
                _C._arch_suppress = False
        _refresh_archive_list()
    except Exception as e:
        print(f"[Protocol] Ошибка инициализации архива: {e}")
        import traceback
        traceback.print_exc()


# ============================================================================
# Каскад архива
# ============================================================================
def _on_arch_type_changed(sender=None, data=None):
    if _C._arch_suppress:
        return
    rtype = dpg.get_value('pm_arch_type_combo')
    specs = get_protocol_specs_by_type(rtype) if rtype else []

    _C._arch_suppress = True
    try:
        dpg.configure_item('pm_arch_spc_combo', items=specs)
        dpg.set_value('pm_arch_spc_combo', specs[0] if specs else '')
    finally:
        _C._arch_suppress = False

    _on_arch_spc_changed()


def _on_arch_spc_changed(sender=None, data=None):
    if _C._arch_suppress:
        return
    spc = dpg.get_value('pm_arch_spc_combo') or None
    msks = get_protocol_msk_list(spc)
    items = [ALL_MSK] + msks

    _C._arch_suppress = True
    try:
        dpg.configure_item('pm_arch_msk_combo', items=items)
        dpg.set_value('pm_arch_msk_combo', msks[0] if msks else ALL_MSK)
    finally:
        _C._arch_suppress = False

    _on_arch_msk_changed()


def _on_arch_msk_changed(sender=None, data=None):
    if _C._arch_suppress:
        return
    spc = dpg.get_value('pm_arch_spc_combo') or None
    msk_val = dpg.get_value('pm_arch_msk_combo')
    msk = None if msk_val == ALL_MSK else msk_val

    dates = get_protocol_dates_list(spc, msk)

    _C._arch_suppress = True
    try:
        dpg.configure_item('pm_arch_date_combo',
                           items=[_C.ARCH_ALL_DATES] + dates)
        dpg.set_value('pm_arch_date_combo', _C.ARCH_ALL_DATES)
    finally:
        _C._arch_suppress = False

    _on_arch_date_changed()


def _on_arch_date_changed(sender=None, data=None):
    if _C._arch_suppress:
        return
    if not (dpg.does_item_exist('pm_arch_spc_combo')
            and dpg.does_item_exist('pm_arch_msk_combo')):
        return

    spc = dpg.get_value('pm_arch_spc_combo') or None
    msk_val = dpg.get_value('pm_arch_msk_combo')
    msk = None if msk_val == ALL_MSK else msk_val
    date_val = dpg.get_value('pm_arch_date_combo')
    date = None if date_val in (_C.ARCH_ALL_DATES, '', None) else date_val

    files = get_protocol_files_list(spc, msk, date)

    _C._arch_suppress = True
    try:
        dpg.configure_item('pm_arch_file_combo',
                           items=[_C.ARCH_ALL_FILES] + files)
        dpg.set_value('pm_arch_file_combo', _C.ARCH_ALL_FILES)
    finally:
        _C._arch_suppress = False

    _refresh_archive_list()


def _on_arch_file_changed(sender=None, data=None):
    if _C._arch_suppress:
        return
    _refresh_archive_list()


# ============================================================================
# Построение вкладки
# ============================================================================
def _build_archive_tab():
    with dpg.group(horizontal=True):
        dpg.add_text("ID протокола:", color=(180, 220, 255))
        dpg.add_input_text(tag='pm_arch_id_input', width=120,
                           decimal=True, on_enter=True,
                           callback=_on_archive_load_by_id)
        dpg.add_button(label='Загрузить по ID', width=160,
                       callback=_on_archive_load_by_id)

    dpg.add_separator()

    with dpg.group(horizontal=True):
        with dpg.group(width=160):
            dpg.add_text("Тип резонатора")
            dpg.add_combo([], tag='pm_arch_type_combo', width=160,
                          callback=_on_arch_type_changed)
        with dpg.group(width=200):
            dpg.add_text("Спецификация")
            dpg.add_combo([], tag='pm_arch_spc_combo', width=200,
                          callback=_on_arch_spc_changed)
        with dpg.group(width=160):
            dpg.add_text("МСК")
            dpg.add_combo([], tag='pm_arch_msk_combo', width=160,
                          callback=_on_arch_msk_changed)
        with dpg.group(width=160):
            dpg.add_text("Дата")
            dpg.add_combo([], tag='pm_arch_date_combo', width=160,
                          callback=_on_arch_date_changed)
        with dpg.group(width=180):
            dpg.add_text("Файл")
            dpg.add_combo([], tag='pm_arch_file_combo', width=180,
                          callback=_on_arch_file_changed)

    with dpg.group(horizontal=True):
        with dpg.group(width=360):
            dpg.add_text("Номера (одиночный / список / диапазон)")
            dpg.add_input_text(
                tag='pm_arch_numbers_input', width=360,
                hint="JN4450  |  JN4450,JN4451  |  JN4450-JN4460",
                on_enter=True,
                callback=lambda s, a: _refresh_archive_list())
        with dpg.group(width=260):
            dpg.add_text("МСК (частичный поиск)")
            dpg.add_input_text(
                tag='pm_arch_search_msk', width=260,
                hint="456  |  25-2456",
                on_enter=True,
                callback=lambda s, a: _refresh_archive_list())
        with dpg.group(width=120):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Искать', width=120,
                           callback=_refresh_archive_list)
        with dpg.group(width=120):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Сбросить', width=120,
                           callback=_on_reset_archive_search)

    dpg.add_separator()
    dpg.add_text("", tag=_C.PM_ARCH_STATUS_TAG, color=(100, 255, 100))
    dpg.add_separator()

    with dpg.child_window(tag='pm_arch_list_child', width=-1, height=200,
                          border=False):
        with dpg.group(tag="pm_archive_list_container"):
            dpg.add_text("Идёт инициализация...",
                         color=(140, 140, 140))

    dpg.add_separator()

    with dpg.group(horizontal=True):
        dpg.add_text("Выбранный протокол:", color=(150, 200, 255))
        dpg.add_text("-", tag="pm_archive_selected_info",
                     color=(255, 255, 100))

    with dpg.group(horizontal=True):
        dpg.add_text("Номера для добавления/удаления:",
                     color=(150, 200, 255))
        dpg.add_input_text(tag="pm_archive_edit_input",
                           hint="1, 5-10, AX123", width=400)
        dpg.configure_item("pm_archive_edit_input", enabled=False)

    dpg.add_separator()

    with dpg.child_window(tag='pm_arch_main_area', width=-1, height=-1,
                          border=False):
        with dpg.group(horizontal=True):
            with dpg.child_window(tag='pm_arch_data_child', width=-340,
                                  height=-1, border=False):
                with dpg.group(tag=_C.PM_ARCH_TABLE_CONTAINER):
                    dpg.add_text("Выберите протокол из списка выше",
                                 color=(140, 140, 140))
            with dpg.child_window(width=340, height=-1, border=True):
                _build_pm_arch_info_panel()


def _build_pm_arch_info_panel():
    dpg.add_text("Информация о протоколе", color=(180, 220, 255))
    dpg.add_separator()

    def info_row(label, tag):
        with dpg.group(horizontal=True):
            dpg.add_text(f"{label}:", color=(150, 200, 255))
            dpg.add_text("", tag=tag)

    info_row("Measure_protokol_ID", 'pm_arch_info_protokol_id')
    info_row("Протокол N",          'pm_arch_info_protokol_n')
    info_row("МСК",                 'pm_arch_info_msk')
    info_row("Спецификация",        'pm_arch_info_spc')
    info_row("Дата",                'pm_arch_info_date')
    info_row("ID замера",           'pm_arch_info_measure_id')
    info_row("Записей",             'pm_arch_info_count')

    dpg.add_separator()
    dpg.add_text("Нормы спецификации", color=(180, 220, 255))
    with dpg.group(tag=_C.PM_ARCH_NORMS_GROUP):
        dpg.add_text("- спецификация не выбрана -",
                     tag='pm_arch_norms_hint', color=(140, 140, 140))


# ============================================================================
# Контекстное меню таблицы (привязано к контейнеру)
# ============================================================================
def _attach_arch_table_popup(enabled: bool):
    if dpg.does_item_exist("pm_arch_data_popup"):
        try:
            dpg.delete_item("pm_arch_data_popup")
        except Exception:
            pass

    with dpg.popup(parent=_C.PM_ARCH_TABLE_CONTAINER,
                   mousebutton=dpg.mvMouseButton_Right,
                   tag="pm_arch_data_popup"):
        dpg.add_menu_item(label="Печать",
                          tag="btn_arch_print", enabled=enabled,
                          callback=_on_archive_print)

        dpg.add_menu_item(label="Добавить номера",
                          tag="btn_arch_add", enabled=enabled,
                          callback=_on_archive_add)
        dpg.add_menu_item(label="Удалить номера",
                          tag="btn_arch_remove", enabled=enabled,
                          callback=_on_archive_remove)
        dpg.add_menu_item(label="Отправить в ОТК",
                          tag="btn_arch_lotrk", enabled=enabled,
                          callback=_on_send_to_lot_rk)
        dpg.add_separator()
        dpg.add_menu_item(label="Добавить номер заказа",
                          tag="btn_arch_order", enabled=enabled,
                          callback=lambda: _open_order_dialog())
        dpg.add_menu_item(label="Установить даты",
                          tag="btn_arch_dates", enabled=enabled,
                          callback=lambda: _open_arch_dates_dialog())


# ============================================================================
# Диалог данных заказа
# ============================================================================
def _open_order_dialog():
    if not _C._active_archive_id:
        _pm_arch_status("Сначала выберите протокол из списка")
        return

    info = get_protocol_order_info(_C._active_archive_id) or {}

    if dpg.does_item_exist(_C.PM_ORDER_DIALOG):
        dpg.delete_item(_C.PM_ORDER_DIALOG)

    lot_numbers = get_lot_numbers()
    init_lot = (info.get('LotNumber') or '').strip()
    if init_lot and init_lot not in lot_numbers:
        lot_numbers = [init_lot] + lot_numbers

    spc_display = (info.get('Spc') or '').strip() or '-'

    sw, sh = _layout.screen_size()
    W, H = 640, 460
    with dpg.window(label="Данные заказа (каскад выбора)",
                    tag=_C.PM_ORDER_DIALOG, modal=True,
                    width=W, height=H,
                    pos=(max(20, (sw - W) // 2),
                         max(20, (sh - H) // 2))):
        dpg.add_text(
            f"Протокол ID = {_C._active_archive_id} | Spc = {spc_display}",
            color=(180, 220, 255))
        dpg.add_separator()

        dpg.add_text("1. Номер заказа:")
        dpg.add_combo(lot_numbers, tag='pm_order_lot_combo',
                      width=-1, default_value=init_lot,
                      callback=_on_order_lot_changed)

        dpg.add_text("2. Номенклатура:")
        dpg.add_combo([], tag='pm_order_spc_combo', width=-1,
                      callback=_on_order_spc_changed)

        dpg.add_text("3. Дата заказа:")
        dpg.add_combo([], tag='pm_order_date_combo', width=-1,
                      callback=_on_order_date_changed)

        dpg.add_separator()
        dpg.add_text("Данные выбранной позиции:",
                     color=(180, 220, 255))

        with dpg.table(header_row=False, policy=dpg.mvTable_SizingFixedFit):
            dpg.add_table_column(label="", width_fixed=True,
                                 init_width_or_weight=180)
            dpg.add_table_column(label="")
            with dpg.table_row():
                dpg.add_text("Контрагент:", color=(150, 200, 255))
                dpg.add_text("-", tag='pm_order_contr_lbl',
                             color=(255, 255, 100))
            with dpg.table_row():
                dpg.add_text("Договор:", color=(150, 200, 255))
                dpg.add_text("-", tag='pm_order_dogovor_lbl',
                             color=(255, 255, 100))
            with dpg.table_row():
                dpg.add_text("Остаток по графику:", color=(150, 200, 255))
                dpg.add_text("-", tag='pm_order_remainder_lbl',
                             color=(255, 255, 100))

        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Сохранить", width=170,
                           callback=_save_order_dialog)
            dpg.add_button(label="Отмена", width=170,
                           callback=lambda: dpg.delete_item(_C.PM_ORDER_DIALOG))
            dpg.add_spacer(width=20)
            dpg.add_button(label="Отправить в ОТК", width=170,
                           callback=_on_send_to_lot_rk)

    if init_lot:
        dpg.set_value('pm_order_lot_combo', init_lot)
        prefer = info.get('Spc') or None
        if prefer:
            try:
                from .Protocol_Data import resolve_spc_text
                resolved = resolve_spc_text(prefer)
                if resolved:
                    prefer = resolved
            except Exception:
                pass
        _on_order_lot_changed(prefer_spc=prefer)
    else:
        _on_order_lot_changed()


def _on_order_lot_changed(sender=None, data=None, prefer_spc=None):
    if not (dpg.does_item_exist('pm_order_lot_combo')
            and dpg.does_item_exist('pm_order_spc_combo')):
        return
    lot = (dpg.get_value('pm_order_lot_combo') or '').strip()
    spcs = get_lot_spc_list(lot) if lot else []

    target = ''
    if prefer_spc and prefer_spc in spcs:
        target = prefer_spc
    elif spcs:
        target = spcs[0]

    dpg.configure_item('pm_order_spc_combo', items=spcs)
    dpg.set_value('pm_order_spc_combo', target)
    _on_order_spc_changed()


def _on_order_spc_changed(sender=None, data=None):
    if not all(dpg.does_item_exist(t) for t in (
            'pm_order_lot_combo', 'pm_order_spc_combo',
            'pm_order_date_combo')):
        return
    lot = (dpg.get_value('pm_order_lot_combo') or '').strip()
    spc = (dpg.get_value('pm_order_spc_combo') or '').strip()

    dates = get_lot_dates_list(lot, spc) if (lot and spc) else []
    dpg.configure_item('pm_order_date_combo', items=dates)
    dpg.set_value('pm_order_date_combo', dates[0] if dates else '')
    _on_order_date_changed()


def _on_order_date_changed(sender=None, data=None):
    if not all(dpg.does_item_exist(t) for t in (
            'pm_order_lot_combo', 'pm_order_spc_combo',
            'pm_order_date_combo', 'pm_order_contr_lbl')):
        return
    lot = (dpg.get_value('pm_order_lot_combo') or '').strip()
    spc = (dpg.get_value('pm_order_spc_combo') or '').strip()
    dt  = (dpg.get_value('pm_order_date_combo') or '').strip()

    details = get_lot_details(lot, spc, dt) if (lot and spc and dt) else None

    if details:
        dpg.set_value('pm_order_contr_lbl', details['customer'] or '-')
        dpg.set_value('pm_order_dogovor_lbl', details['dogovor'] or '-')
        rem = details['remainder']
        dpg.set_value('pm_order_remainder_lbl',
                      (str(rem) if rem is not None else '-'))
    else:
        dpg.set_value('pm_order_contr_lbl', '-')
        dpg.set_value('pm_order_dogovor_lbl', '-')
        dpg.set_value('pm_order_remainder_lbl', '-')


def _save_order_dialog():
    if not _C._active_archive_id:
        return
    if not all(dpg.does_item_exist(t) for t in (
            'pm_order_lot_combo', 'pm_order_spc_combo',
            'pm_order_date_combo')):
        return

    lot = (dpg.get_value('pm_order_lot_combo') or '').strip()
    spc = (dpg.get_value('pm_order_spc_combo') or '').strip()
    dt  = (dpg.get_value('pm_order_date_combo') or '').strip()

    if not lot:
        _show_warning("Заказ", "Не выбран номер заказа")
        return
    if not spc:
        _show_warning("Заказ", "Не выбрана номенклатура")
        return
    if not dt:
        _show_warning("Заказ", "Не выбрана дата заказа")
        return

    details = get_lot_details(lot, spc, dt)
    if not details:
        msg = (f"Не найдены данные заказа в таблице [заказы1С_новые]:\n\n"
               f"Заказ        = '{lot}'\n"
               f"Номенклатура = '{spc}'\n"
               f"Дата         = '{dt}'\n\n"
               f"Проверьте, что запись существует и "
               f"ОсталосьВыпуститьПоГрафику > 0.")
        try:
            log_action("SET_ORDER_FAIL", _C._active_archive_id,
                       _C._active_archive_mid or 0,
                       f"Заказ={lot}; Spc={spc}; Дата={dt}; "
                       f"Причина=Данные заказа не найдены в заказы1С_новые",
                       "Admin")
        except Exception as e:
            print(f"[Protocol] log_action SET_ORDER_FAIL error: {e}")
        _show_warning("Заказ", msg)
        return

    dogovor  = details['dogovor'] or ''
    customer = details['customer'] or ''
    if not dogovor and not customer:
        msg = (f"У позиции нет ни Договора, ни Контрагента:\n"
               f"Заказ={lot}, Номенклатура={spc}, Дата={dt}.\n"
               f"Данные сохранены не будут.")
        try:
            log_action("SET_ORDER_FAIL", _C._active_archive_id,
                       _C._active_archive_mid or 0,
                       f"Заказ={lot}; Spc={spc}; Дата={dt}; "
                       f"Причина=Нет Договора и Контрагента",
                       "Admin")
        except Exception as e:
            print(f"[Protocol] log_action SET_ORDER_FAIL error: {e}")
        _show_warning("Заказ", msg)
        return

    num_count = 0
    nums_sample = ""
    try:
        df_chk = get_archive_protocol_data(_C._active_archive_id)
        if df_chk is not None and not df_chk.empty and 'N' in df_chk.columns:
            nums_all = [str(x) for x in df_chk['N'].dropna().tolist()]
            num_count = len(nums_all)
            nums_sample = ','.join(nums_all[:50])
            if num_count > 50:
                nums_sample += "..."
    except Exception as e:
        print(f"[Protocol] get num_count error: {e}")

    try:
        save_order_info(_C._active_archive_id, lot, dogovor, customer)
        try:
            log_action(
                "SET_ORDER", _C._active_archive_id,
                _C._active_archive_mid or 0,
                f"Заказ={lot}; Spc={spc}; Дата={dt}; "
                f"Договор={dogovor}; Контрагент={customer}; "
                f"Номеров в протоколе={num_count}"
                + (f"; Номера=[{nums_sample}]" if nums_sample else ""),
                "Admin")
        except Exception as e:
            print(f"[Protocol] log_action SET_ORDER error: {e}")
    except Exception as e:
        print(f"[Protocol] save_order_info error: {e}")
        try:
            log_action("SET_ORDER_FAIL", _C._active_archive_id,
                       _C._active_archive_mid or 0,
                       f"Заказ={lot}; Spc={spc}; Дата={dt}; "
                       f"Ошибка сохранения: {e}",
                       "Admin")
        except Exception:
            pass
        _show_warning("Ошибка сохранения",
                      f"Не удалось сохранить данные заказа:\n{e}")
        return

    _pm_arch_status(f"Заказ сохранён: {lot} / {spc} / {dt}")

    if dpg.does_item_exist(_C.PM_ORDER_DIALOG):
        dpg.delete_item(_C.PM_ORDER_DIALOG)

    _show_info(
        "Заказ",
        f"Сохранено в psi_measure_protokol_id:\n\n"
        f"Номер заказа:  {lot}\n"
        f"Номенклатура:  {spc}\n"
        f"Дата заказа:   {dt}\n"
        f"Договор:       {dogovor or '-'}\n"
        f"Контрагент:    {customer or '-'}\n"
        f"Номеров в протоколе: {num_count}")


# ============================================================================
# Диалог дат
# ============================================================================
def _open_arch_dates_dialog():
    if not _C._active_archive_id:
        _pm_arch_status("Сначала выберите протокол из списка")
        return
    info = get_protocol_order_info(_C._active_archive_id) or {}
    if dpg.does_item_exist(_C.PM_DATES_DIALOG):
        dpg.delete_item(_C.PM_DATES_DIALOG)
    sw, sh = _layout.screen_size()
    with dpg.window(label="Даты изготовления и перепроверки",
                    tag=_C.PM_DATES_DIALOG, modal=True,
                    width=520, height=270,
                    pos=(max(20, (sw - 520) // 2),
                         max(20, (sh - 270) // 2))):
        dpg.add_text(f"Протокол ID = {_C._active_archive_id} "
                     f"(Measure_ID = {_C._active_archive_mid})",
                     color=(180, 220, 255))
        dpg.add_separator()
        dpg.add_text("Дата изготовления (MakeDate), YYYY-MM-DD:")
        dpg.add_input_text(tag='pm_arch_mk_date_input', width=-1,
                           default_value=str(info.get('MakeDate') or ''))
        dpg.add_text("Дата перепроверки (MakeDate1), YYYY-MM-DD:")
        dpg.add_input_text(tag='pm_arch_mk_date1_input', width=-1,
                           default_value=str(info.get('MakeDate1') or ''))
        dpg.add_spacer(height=8)
        with dpg.group(horizontal=True):
            dpg.add_button(label="Применить", width=150,
                           callback=_save_arch_dates_dialog)
            dpg.add_button(label="Отмена", width=150,
                           callback=lambda: dpg.delete_item(_C.PM_DATES_DIALOG))


def _save_arch_dates_dialog():
    if not _C._active_archive_id:
        return
    if not all(dpg.does_item_exist(t) for t in (
            'pm_arch_mk_date_input', 'pm_arch_mk_date1_input')):
        return
    md  = (dpg.get_value('pm_arch_mk_date_input') or '').strip()
    md1 = (dpg.get_value('pm_arch_mk_date1_input') or '').strip()
    if not md and not md1:
        _show_warning("Даты", "Не введена ни одна дата")
        return

    cnt = 0
    if _C._active_archive_mid:
        df = get_archive_protocol_data(_C._active_archive_id)
        if df is not None and not df.empty:
            nums = [str(x) for x in df['N'].dropna().tolist()]
            try:
                cnt = update_psidata_make_dates(
                    _C._active_archive_mid, nums,
                    make_date=md or None, make_date1=md1 or None)
            except Exception as e:
                _show_warning("Ошибка БД",
                              f"Не удалось обновить psidata:\n{e}")
                return

    try:
        save_make_dates(_C._active_archive_id, md or None, md1 or None)
    except Exception as e:
        print(f"[Protocol] save_make_dates error: {e}")

    try:
        log_action("SET_DATES", _C._active_archive_id,
                   _C._active_archive_mid or 0,
                   f"MakeDate={md}; MakeDate1={md1}; записей={cnt}",
                   "Admin")
    except Exception:
        pass

    _pm_arch_status(f"Даты обновлены. Записей в psidata: {cnt}")

    if dpg.does_item_exist(_C.PM_DATES_DIALOG):
        dpg.delete_item(_C.PM_DATES_DIALOG)

    if cnt == 0:
        _show_info(
            "Даты",
            f"Даты сохранены в заголовок протокола.\n"
            f"Записей psidata не обновлено (в протоколе нет номеров\n"
            f"или Measure_ID не определён).")
    else:
        _show_info("Даты", f"Обновлено записей psidata: {cnt}")


# ============================================================================
# LotRK — с подробным логированием
# ============================================================================
def _on_send_to_lot_rk():
    if dpg.does_item_exist(_C.PM_ORDER_DIALOG):
        dpg.delete_item(_C.PM_ORDER_DIALOG)

    if not _C._active_archive_id:
        _pm_arch_status("Сначала выберите протокол")
        return

    lot = dogovor = customer = ""
    nums_all: list[str] = []
    try:
        info = get_protocol_order_info(_C._active_archive_id) or {}
        lot      = (info.get('LotNumber') or '').strip()
        dogovor  = (info.get('Dogovor')  or '').strip()
        customer = (info.get('Customer') or '').strip()

        df = get_archive_protocol_data(_C._active_archive_id)
        if df is not None and not df.empty and 'N' in df.columns:
            nums_all = [str(x) for x in df['N'].dropna().tolist()]
    except Exception as e:
        print(f"[Protocol] gather LotRK details error: {e}")

    nums_count  = len(nums_all)
    nums_sample = ','.join(nums_all[:50])
    if nums_count > 50:
        nums_sample += "..."

    ok, msg = send_to_lot_rk(_C._active_archive_id)

    if ok:
        try:
            details = (
                f"Заказ={lot}; Договор={dogovor}; Контрагент={customer}; "
                f"Номеров={nums_count}; "
                f"Номера=[{nums_sample}]; "
                f"Результат={msg}"
            )
            log_action("SEND_LOT_RK", _C._active_archive_id,
                       _C._active_archive_mid or 0, details, "Admin")
            log_action("LOT_RK_WRITE", _C._active_archive_id,
                       _C._active_archive_mid or 0,
                       f"Записано в lot_RK: номеров={nums_count}; "
                       f"Заказ={lot}",
                       "Admin")
        except Exception as e:
            print(f"[Protocol] log_action SEND_LOT_RK error: {e}")

        _pm_arch_status(msg)
        _show_info("Отправка в ОТК",
                   f"{msg}\n\nЗаказ: {lot or '-'}\n"
                   f"Отправлено номеров: {nums_count}")
    else:
        try:
            log_action("SEND_LOT_RK_FAIL", _C._active_archive_id,
                       _C._active_archive_mid or 0,
                       f"Заказ={lot}; Номеров={nums_count}; "
                       f"Ошибка={msg}",
                       "Admin")
        except Exception as e:
            print(f"[Protocol] log_action SEND_LOT_RK_FAIL error: {e}")

        _pm_arch_status("Ошибка: " + msg)
        _show_warning("Отправка в ОТК", msg)


# ============================================================================
# Логика вкладки
# ============================================================================
def _refresh_archive_list():
    if not dpg.does_item_exist("pm_archive_list_container"):
        return
    dpg.delete_item("pm_archive_list_container", children_only=True)

    numbers = None
    if dpg.does_item_exist('pm_arch_numbers_input'):
        numbers = parse_numbers_input(
            dpg.get_value('pm_arch_numbers_input') or '')

    msk_partial = None
    if dpg.does_item_exist('pm_arch_search_msk'):
        msk_partial = (dpg.get_value('pm_arch_search_msk') or '').strip() or None

    spc = rtype = date = file = None
    msk_exact = None

    if not (numbers or msk_partial):
        spc = dpg.get_value('pm_arch_spc_combo') or None
        rtype = dpg.get_value('pm_arch_type_combo') or None

        msk_val = dpg.get_value('pm_arch_msk_combo') or ''
        msk_exact = None if msk_val in (ALL_MSK, '') else msk_val

        date_val = dpg.get_value('pm_arch_date_combo') or ''
        date = None if date_val in (_C.ARCH_ALL_DATES, '') else date_val

        file_val = dpg.get_value('pm_arch_file_combo') or ''
        file = None if file_val in (_C.ARCH_ALL_FILES, '') else file_val

    print(f"[Protocol] _refresh_archive_list: "
          f"numbers={numbers} msk_partial={msk_partial} "
          f"spc={spc!r} rtype={rtype!r} msk_exact={msk_exact!r} "
          f"date={date!r} file={file!r}")

    if numbers:
        _pm_arch_status(f'Поиск по {len(numbers)} номерам по всей БД '
                        f'(каскад игнорируется)')
    elif msk_partial:
        _pm_arch_status(f'Поиск МСК по "{msk_partial}" по всей БД')
    else:
        parts = []
        if rtype:     parts.append(f'тип={rtype}')
        if spc:       parts.append(f'spc={spc}')
        if msk_exact: parts.append(f'МСК={msk_exact}')
        if date:      parts.append(f'дата={date}')
        if file:      parts.append(f'файл={file}')
        _pm_arch_status('Поиск: ' + (', '.join(parts) if parts
                                     else 'все протоколы'))

    try:
        dpg.split_frame()
    except Exception:
        pass

    df = search_archived_protocols(
        msk_partial=msk_partial, msk_exact=msk_exact,
        spc=spc, rtype=rtype, date=date, file=file, numbers=numbers,
    )

    if df is None or df.empty:
        _pm_arch_status('Протоколы не найдены')
        dpg.add_text(
            "Протоколы не найдены.\n"
            "Попробуйте выбрать «Все МСК», сбросить фильтры каскада, "
            "или использовать частичный поиск МСК / номеров.",
            parent="pm_archive_list_container",
            color=(200, 150, 150), wrap=1000)
        print("[Protocol] search_archived_protocols: пусто")
        return

    _pm_arch_status(f'Найдено протоколов: {len(df)}')
    print(f"[Protocol] search_archived_protocols: {len(df)} строк")

    with dpg.table(parent="pm_archive_list_container",
                   header_row=True, resizable=True,
                   scrollY=True, height=180,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True):
        dpg.add_table_column(label="Measure_protokol_ID", width_fixed=True,
                             init_width_or_weight=170)
        dpg.add_table_column(label="Протокол N")
        dpg.add_table_column(label="Тип")
        dpg.add_table_column(label="МСК")
        dpg.add_table_column(label="Дата")
        dpg.add_table_column(label="Кол-во")
        dpg.add_table_column(label="Действие")

        for _, row in df.iterrows():
            pid = int(row['Measure_protokol_ID'])
            with dpg.table_row():
                dpg.add_text(str(pid))
                dpg.add_text(str(row.get('ProtokolN', '')))
                dpg.add_text(_screen_safe(str(row.get('PsiType') or 'ОТК')))
                dpg.add_text(_screen_safe(str(row.get('MSK', ''))))
                dpg.add_text(str(row.get('dataR', ''))[:16])
                dpg.add_text(f"{int(row.get('Current_Count') or 0)} / "
                             f"{int(row.get('Total_Count') or 0)}")
                btn = dpg.add_button(label="Загрузить", user_data=pid,
                                     callback=_on_archive_select)
                with dpg.popup(parent=btn,
                               mousebutton=dpg.mvMouseButton_Right):
                    dpg.add_menu_item(
                        label="Удалить протокол",
                        user_data=pid,
                        callback=_on_delete_protocol_by_id)


def _on_reset_archive_search():
    if dpg.does_item_exist('pm_arch_id_input'):
        dpg.set_value('pm_arch_id_input', '')
    if dpg.does_item_exist('pm_arch_numbers_input'):
        dpg.set_value('pm_arch_numbers_input', '')
    if dpg.does_item_exist('pm_arch_search_msk'):
        dpg.set_value('pm_arch_search_msk', '')

    types = []
    _C._arch_suppress = True
    try:
        types = get_protocol_types()
        dpg.configure_item('pm_arch_type_combo', items=types)
        if types:
            dpg.set_value('pm_arch_type_combo', types[0])
        else:
            dpg.configure_item('pm_arch_spc_combo', items=[])
            dpg.set_value('pm_arch_spc_combo', '')
            dpg.configure_item('pm_arch_msk_combo', items=[ALL_MSK])
            dpg.set_value('pm_arch_msk_combo', ALL_MSK)
            dpg.configure_item('pm_arch_date_combo',
                               items=[_C.ARCH_ALL_DATES])
            dpg.set_value('pm_arch_date_combo', _C.ARCH_ALL_DATES)
            dpg.configure_item('pm_arch_file_combo',
                               items=[_C.ARCH_ALL_FILES])
            dpg.set_value('pm_arch_file_combo', _C.ARCH_ALL_FILES)
    finally:
        _C._arch_suppress = False

    if types:
        _on_arch_type_changed()
    _refresh_archive_list()


def _on_archive_load_by_id(sender=None, data=None):
    if not dpg.does_item_exist('pm_arch_id_input'):
        return
    raw = str(dpg.get_value('pm_arch_id_input') or '').strip()
    if not raw.isdigit():
        _pm_arch_status('Введите числовой Measure_protokol_ID')
        return
    pid = int(raw)
    if pid <= 0:
        _pm_arch_status('ID должен быть больше 0')
        return
    _on_archive_select(None, None, pid)


def _on_archive_select(sender, app_data, user_data):
    try:
        protokol_id = int(user_data)
    except (TypeError, ValueError):
        _pm_arch_status('Некорректный Measure_protokol_ID')
        return

    header = get_protocol_by_id(protokol_id)
    if not header:
        _pm_arch_status(f'Протокол ID={protokol_id} не найден в '
                        f'psi_measure_protokol_id')
        return

    _C._active_archive_id = protokol_id

    try:
        _C._active_archive_mid = int(header.get('Measure_ID'))
    except (TypeError, ValueError):
        _C._active_archive_mid = None

    psi_type = header.get('psi_type') or 'ОТК'
    if str(psi_type) not in ('ПСИ', 'ОТК', 'Паспорт', 'ОТКп', 'ОТК_простой', 'ОТК-простой'):
        psi_type = 'ОТК'
    _C._active_archive_psi_type = str(psi_type)

    dpg.set_value(
        "pm_archive_selected_info",
        _screen_safe(f"Measure_protokol_ID={_C._active_archive_id} | "
                     f"Протокол N {header.get('ProtokolN', '?')} | "
                     f"Тип: {_C._active_archive_psi_type} | "
                     f"МСК: {header.get('MSK', '')}")
    )

    if dpg.does_item_exist('pm_arch_id_input'):
        dpg.set_value('pm_arch_id_input', str(_C._active_archive_id))

    df = get_archive_protocol_data(_C._active_archive_id)
    print(f"[Protocol] _on_archive_select: ID={protokol_id}, "
          f"rows={0 if df is None else len(df)}")

    # Popup пересоздаётся внутри; включаем пункты ПОСЛЕ этого
    _pm_fill_archive_data(df, header)

    for tag in ["btn_arch_print", "btn_arch_add", "btn_arch_remove",
                "pm_archive_edit_input",
                "btn_arch_order", "btn_arch_dates", "btn_arch_lotrk"]:
        if dpg.does_item_exist(tag):
            dpg.configure_item(tag, enabled=True)


def _pm_fill_archive_data(df, header=None):
    if dpg.does_item_exist(_C.PM_ARCH_TABLE_CONTAINER):
        for ch in dpg.get_item_children(_C.PM_ARCH_TABLE_CONTAINER, 1) or []:
            dpg.delete_item(ch)

    spc_name = None
    if df is not None and not df.empty and 'Spc' in df.columns:
        uniq = [str(s) for s in df['Spc'].dropna().unique() if s]
        if uniq:
            spc_name = uniq[0]
    if not spc_name and header:
        raw_spc = str(header.get('Spc') or '').strip() or None
        if raw_spc:
            from .Protocol_Data import resolve_spc_name
            spc_name = resolve_spc_name(raw_spc) or raw_spc

    psi_type = _C._active_archive_psi_type or 'ОТК'
    spc_map = (_pm_load_spc_map_for_display(spc_name, psi_type)
               if spc_name else pd.DataFrame())

    if df is None or df.empty:
        dpg.add_text("- в протоколе нет записей -",
                     parent=_C.PM_ARCH_TABLE_CONTAINER,
                     color=(140, 140, 140))
    else:
        display_cols = _build_display_cols(df, spc_map, is_archive=True)
        _render_data_table(df, _C.PM_ARCH_TABLE_CONTAINER,
                           _C.PM_ARCH_TABLE_TAG,
                           spc_map, display_cols, with_checkbox=False)

    _attach_arch_table_popup(enabled=bool(_C._active_archive_id))

    _pm_fill_arch_info(df, header)
    _pm_fill_arch_norms(spc_name, psi_type)


def _on_archive_add():
    if not _C._active_archive_id:
        return
    raw = dpg.get_value("pm_archive_edit_input")
    nums = parse_numbers_input(raw)
    if not nums:
        return

    added = add_numbers_to_protocol(
        _C._active_archive_id, _C._active_archive_mid, nums,
        _C._active_archive_psi_type or 'ОТК')
    if added:
        log_action("ADD_NUMBERS", _C._active_archive_id,
                   _C._active_archive_mid,
                   f"Добавлены: {added}", "Admin")
        _pm_arch_status(f"Добавлено: {len(added)} номеров")
    else:
        _pm_arch_status("Не добавлено ни одного номера (брак или не найдены)")

    if added and _C._active_archive_id and _C._active_archive_mid:
        try:
            info = get_protocol_order_info(_C._active_archive_id) or {}
            md  = info.get('MakeDate')  or None
            md1 = info.get('MakeDate1') or None
            if md or md1:
                update_psidata_make_dates(
                    _C._active_archive_mid, added,
                    make_date=md, make_date1=md1)
        except Exception as e:
            print(f"[Protocol] propagate dates error: {e}")

    _refresh_archive_list()
    _on_archive_select(None, None, _C._active_archive_id)


def _on_archive_remove():
    if not _C._active_archive_id:
        return
    raw = dpg.get_value("pm_archive_edit_input")
    nums = parse_numbers_input(raw)
    if not nums:
        return

    remove_numbers_from_protocol(_C._active_archive_id, nums)
    log_action("REMOVE_NUMBERS", _C._active_archive_id,
               _C._active_archive_mid,
               f"Удалены: {nums}", "Admin")
    _pm_arch_status(f"Удалено: {len(nums)} номеров")

    _refresh_archive_list()
    _on_archive_select(None, None, _C._active_archive_id)


def _on_delete_protocol_by_id(sender, app_data, user_data):
    try:
        pid = int(user_data)
    except (TypeError, ValueError):
        return

    header = get_protocol_by_id(pid)
    try:
        mid = int(header.get('Measure_ID')) if header else None
    except (TypeError, ValueError):
        mid = None

    delete_protocol_completely(pid)
    try:
        log_action("DELETE_PROTOCOL", pid, mid or 0,
                   "Протокол удален", "Admin")
    except Exception:
        pass
    _pm_arch_status(f"Протокол ID={pid} удален")

    was_active = (_C._active_archive_id == pid)
    if was_active:
        _C._active_archive_id = None
        _C._active_archive_mid = None
        _C._active_archive_psi_type = None

        dpg.set_value("pm_archive_selected_info", "-")
        if dpg.does_item_exist('pm_arch_id_input'):
            dpg.set_value('pm_arch_id_input', '')

        if dpg.does_item_exist(_C.PM_ARCH_TABLE_CONTAINER):
            for ch in dpg.get_item_children(_C.PM_ARCH_TABLE_CONTAINER,
                                            1) or []:
                dpg.delete_item(ch)
            dpg.add_text("Выберите протокол из списка выше",
                         parent=_C.PM_ARCH_TABLE_CONTAINER,
                         color=(140, 140, 140))
            _attach_arch_table_popup(enabled=False)

        _pm_fill_arch_info({}, None)
        _pm_fill_arch_norms('', 'ОТК')

    _refresh_archive_list()


def _on_archive_delete():
    if _C._active_archive_id:
        _on_delete_protocol_by_id(None, None, _C._active_archive_id)


def _on_archive_print():
    if not _C._active_archive_id:
        return
    print_archived_protocol(_C._active_archive_id)


def _on_archive_print_passport():
    """Обработчик для печати паспорта из контекстного меню архива."""
    if not _C._active_archive_id:
        return
    print_passport_for_protocol(_C._active_archive_id)