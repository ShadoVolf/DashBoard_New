"""Вкладка «Создание протокола» (каскад + печать + даты)."""
import pandas as pd
import dearpygui.dearpygui as dpg
from collections import defaultdict

from Temperature_Measure import _layout
from Archive_View.Archive_Data import (
    get_archive_types, get_archive_specs_by_type, get_archive_msk_list,
    get_archive_dates_list, get_archive_files_list, load_archive_data,
    load_measure_ids_by_msk, load_archive_by_measure_id, parse_numbers_input,
    find_measure_ids_by_numbers, load_archive_by_numbers,
    rename_fields_to_parameters, log_missing_params,
    search_archive_msk,
)
from Archive_View.Archive_Helpers import _filter_good_only
from Archive_View.Archive_Constants import ALL_MSK, MODE_ONLY_NUM, MODE_FULL_MSK

from . import Protocol_Constants as _C
from .Protocol_Common import (
    _pm_status, _show_warning, _show_info,
    _pm_fill_norms, _pm_fill_info, _pm_current_psi_type,
    _pm_load_spc_map_for_display, _pm_resolve_display_spc,
    _build_display_cols, _render_data_table,
)
from .Protocol_Data import update_psidata_make_dates
from .Protocol_Print import print_custom_protocol


# ============================================================================
# Bootstrap
# ============================================================================
def _pm_bootstrap():
    from .Protocol_Common import clear_presentation_params_cache
    clear_presentation_params_cache()

    try:
        types = get_archive_types()
        dpg.configure_item('pm_type_combo', items=types)
        if types:
            dpg.set_value('pm_type_combo', types[0])
            _pm_on_type_changed()
    except Exception as e:
        print(f"[Protocol] Ошибка инициализации: {e}")


# ============================================================================
# Каскад
# ============================================================================
def _pm_on_type_changed(sender=None, data=None):
    if _C._suppress_cascade:
        return
    rtype = dpg.get_value('pm_type_combo')
    specs = get_archive_specs_by_type(rtype) if rtype else []
    dpg.configure_item('pm_spc_combo', items=specs)
    dpg.set_value('pm_spc_combo', specs[0] if specs else '')
    _pm_on_spc_changed()


def _pm_on_spc_changed(sender=None, data=None):
    if _C._suppress_cascade:
        return
    spc = dpg.get_value('pm_spc_combo')
    msks = get_archive_msk_list(spc if spc else None)
    items = [ALL_MSK] + msks
    dpg.configure_item('pm_msk_combo', items=items)
    dpg.set_value('pm_msk_combo', msks[0] if msks else ALL_MSK)
    _pm_on_msk_changed()
    _pm_fill_norms(spc)


def _pm_on_msk_changed(sender=None, data=None):
    if _C._suppress_cascade:
        return
    if dpg.does_item_exist('pm_measure_id_input'):
        dpg.set_value('pm_measure_id_input', '')

    msk_val = dpg.get_value('pm_msk_combo')
    if msk_val == ALL_MSK:
        for tag in ('pm_date_combo', 'pm_file_combo', 'pm_measure_id_combo'):
            dpg.configure_item(tag, items=[])
            dpg.set_value(tag, '')
        return

    msk = msk_val or None
    spc = dpg.get_value('pm_spc_combo')

    dates = get_archive_dates_list(msk, spc if spc else None)
    dpg.configure_item('pm_date_combo', items=dates)
    dpg.set_value('pm_date_combo', dates[0] if dates else '')

    mids = load_measure_ids_by_msk(msk) if msk else []
    dpg.configure_item('pm_measure_id_combo', items=mids)
    dpg.set_value('pm_measure_id_combo', mids[0] if mids else '')

    _pm_on_date_changed()


def _pm_on_date_changed(sender=None, data=None):
    if _C._suppress_cascade:
        return
    msk_val = dpg.get_value('pm_msk_combo')
    if msk_val == ALL_MSK:
        return
    msk = msk_val or None
    spc = dpg.get_value('pm_spc_combo')
    date = dpg.get_value('pm_date_combo')
    files = get_archive_files_list(msk, spc if spc else None,
                                   date if date else None)
    dpg.configure_item('pm_file_combo', items=files)
    dpg.set_value('pm_file_combo', files[0] if files else '')


def _pm_on_measure_id_pick(sender=None, data=None):
    mid = dpg.get_value('pm_measure_id_combo')
    if not mid:
        return
    dpg.set_value('pm_measure_id_input', str(mid))
    _pm_on_measure_id_enter()


def _pm_on_measure_id_enter(sender=None, data=None):
    raw = dpg.get_value('pm_measure_id_input')
    if raw is None:
        return
    raw_str = str(raw).strip()
    if not raw_str.isdigit():
        return
    mid = int(raw_str)
    if mid <= 0:
        return

    info = load_archive_by_measure_id(mid)
    if info is None:
        _pm_status(f'ID {mid} не найден в psidata')
        return

    _C._suppress_cascade = True
    try:
        if info['rtype']:
            dpg.set_value('pm_type_combo', info['rtype'])
            dpg.configure_item('pm_spc_combo',
                               items=get_archive_specs_by_type(info['rtype']))
        if info['spc']:
            dpg.set_value('pm_spc_combo', info['spc'])
        if info['msk']:
            msks = get_archive_msk_list(info['spc'])
            dpg.configure_item('pm_msk_combo', items=[ALL_MSK] + msks)
            dpg.set_value('pm_msk_combo', info['msk'])
        mids = load_measure_ids_by_msk(info['msk']) if info['msk'] else []
        dpg.configure_item('pm_measure_id_combo', items=mids)
        dpg.set_value('pm_measure_id_combo', mid if mid in mids else '')
        dpg.set_value('pm_measure_id_input', str(mid))
    finally:
        _C._suppress_cascade = False

    _pm_on_date_changed()
    if dpg.does_item_exist('pm_numbers_input'):
        dpg.set_value('pm_numbers_input', '')
    _pm_reload_data()


# ============================================================================
# Поиск МСК
# ============================================================================
def _pm_on_msk_search(sender=None, data=None):
    if not dpg.does_item_exist('pm_msk_search_input'):
        return
    partial = (dpg.get_value('pm_msk_search_input') or '').strip()
    if not partial:
        _pm_status('Введите часть номера МСК')
        return

    _pm_status(f'Поиск МСК по "{partial}"...')
    try:
        dpg.split_frame()
    except Exception:
        pass

    matches = search_archive_msk(partial)
    items = [ALL_MSK] + list(matches) if matches else [ALL_MSK]
    dpg.configure_item('pm_msk_combo', items=items)
    dpg.set_value('pm_msk_combo', matches[0] if matches else ALL_MSK)
    _pm_on_msk_changed()

    if matches:
        _pm_status(f'Поиск МСК по "{partial}": найдено {len(matches)}')
    else:
        _pm_status(f'Поиск МСК по "{partial}": ничего не найдено')


def _pm_on_clear_msk_search(sender=None, data=None):
    if dpg.does_item_exist('pm_msk_search_input'):
        dpg.set_value('pm_msk_search_input', '')
    _pm_on_spc_changed()


def _pm_on_clear_numbers(sender=None, data=None):
    if dpg.does_item_exist('pm_numbers_input'):
        dpg.set_value('pm_numbers_input', '')
    _pm_reload_data()


# ============================================================================
# Загрузка данных
# ============================================================================
def _pm_reload_data():
    only_good = dpg.get_value('pm_only_good_check')

    numbers_filter = None
    if dpg.does_item_exist('pm_numbers_input'):
        numbers_filter = parse_numbers_input(
            dpg.get_value('pm_numbers_input') or '')

    mid_str = dpg.get_value('pm_measure_id_input')
    measure_id = None
    if mid_str is not None:
        ms = str(mid_str).strip()
        if ms.isdigit() and int(ms) > 0:
            measure_id = int(ms)

    if numbers_filter:
        if measure_id and dpg.does_item_exist('pm_measure_id_input'):
            dpg.set_value('pm_measure_id_input', '')
        mode = (dpg.get_value('pm_search_mode')
                if dpg.does_item_exist('pm_search_mode')
                else MODE_ONLY_NUM)
        _pm_status('Поиск по номерам...')
        try:
            dpg.split_frame()
        except Exception:
            pass

        mids = find_measure_ids_by_numbers(numbers_filter, only_good=False)
        if not mids:
            _pm_set_data(pd.DataFrame())
            _pm_status(f'По номерам ({len(numbers_filter)}): ничего не найдено')
            return

        df = load_archive_by_numbers(numbers_filter, mode,
                                     only_good=False, found_mids=mids)
        if only_good and df is not None and not df.empty:
            n_before = len(df)
            df = _filter_good_only(df, dpg.get_value('pm_spc_combo') or '')
            print(f"[Protocol] only_good: {n_before} -> {len(df)}")
        _pm_set_data(df)
        if df is None or df.empty:
            _pm_status(f'По номерам ({len(numbers_filter)}): пусто')
        else:
            n_mids = (df['Measure_ID'].nunique()
                      if 'Measure_ID' in df.columns else 0)
            mode_str = 'вся МСК' if mode == MODE_FULL_MSK else 'только номер'
            _pm_status(f'По номерам ({len(numbers_filter)}) | '
                       f'записей: {len(df)} | замеров: {n_mids} | '
                       f'режим: {mode_str}')
        return

    msk_val = dpg.get_value('pm_msk_combo') or None
    msk = None if msk_val == ALL_MSK else msk_val
    spc = dpg.get_value('pm_spc_combo') or None
    date = dpg.get_value('pm_date_combo') or None
    file = dpg.get_value('pm_file_combo') or None

    _pm_status('Загрузка...')
    try:
        dpg.split_frame()
    except Exception:
        pass

    if measure_id:
        df = load_archive_data(measure_id=measure_id, only_good=False)
    else:
        df = load_archive_data(msk=msk, spc=spc, date=date, file=file,
                               measure_id=None, only_good=False)

    if only_good and df is not None and not df.empty:
        n_before = len(df)
        df = _filter_good_only(df, spc or '')
        print(f"[Protocol] only_good: {n_before} -> {len(df)}")

    _pm_set_data(df)

    if df is None or df.empty:
        _pm_status('Данные не найдены')
    else:
        n_mid = df['Measure_ID'].nunique() if 'Measure_ID' in df.columns else 0
        _pm_status(f'Загружено: {len(df)} строк | Measure_ID: {n_mid} | '
                   f'Spc: {_pm_resolve_display_spc(df) or "-"}')


def _pm_set_data(df):
    _C._loaded_df = df
    _C._selected_numbers = {}
    _pm_fill_table(df)
    _pm_fill_info(df)
    _pm_fill_norms(_pm_resolve_display_spc(df))


def _pm_fill_table(df):
    if dpg.does_item_exist(_C.PM_TABLE_CONTAINER):
        for ch in dpg.get_item_children(_C.PM_TABLE_CONTAINER, 1) or []:
            dpg.delete_item(ch)

    if df is None or df.empty:
        dpg.add_text("- нет данных -", parent=_C.PM_TABLE_CONTAINER,
                     color=(140, 140, 140))
        return

    spc_name = _pm_resolve_display_spc(df)
    spc_map = (_pm_load_spc_map_for_display(spc_name, _pm_current_psi_type())
               if spc_name else pd.DataFrame())

    if not spc_map.empty:
        log_missing_params(rename_fields_to_parameters(df), spc_map,
                           context=f"pm_fill_table spc={spc_name}")

    display_cols = _build_display_cols(df, spc_map, is_archive=False)
    _render_data_table(df, _C.PM_TABLE_CONTAINER, _C.PM_TABLE_TAG,
                       spc_map, display_cols, with_checkbox=True)


def _pm_on_psi_type_changed(sender=None, data=None):
    if _C._loaded_df is not None and not _C._loaded_df.empty:
        _pm_fill_table(_C._loaded_df)
    _pm_fill_norms(dpg.get_value('pm_spc_combo') or '')


# ============================================================================
# Выбор / печать
# ============================================================================
def _pm_select_all(sender=None, data=None):
    for pos_idx in _C._selected_numbers:
        tag = f'pm_sel_{pos_idx}'
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, True)


def _pm_clear_selection(sender=None, data=None):
    for pos_idx in _C._selected_numbers:
        tag = f'pm_sel_{pos_idx}'
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, False)


def _on_print_click(psi_type: str):
    if _C._loaded_df is None or _C._loaded_df.empty:
        _pm_status("Данные не загружены")
        return

    by_mid = defaultdict(list)
    for pos_idx, (mid, n) in _C._selected_numbers.items():
        tag = f'pm_sel_{pos_idx}'
        if dpg.does_item_exist(tag) and dpg.get_value(tag):
            if mid is not None and n != '':
                by_mid[mid].append(n)

    if not by_mid:
        _pm_status("Не выбрано ни одного номера")
        return

    total = sum(len(v) for v in by_mid.values())
    _pm_status(f"Генерация {psi_type}: {total} номеров "
               f"в {len(by_mid)} замерах...")
    try:
        dpg.split_frame()
    except Exception:
        pass

    spc_name = dpg.get_value('pm_spc_combo') or None
    for mid, nums in by_mid.items():
        try:
            print_custom_protocol(mid, nums, psi_type, spc_name=spc_name)
        except Exception as e:
            print(f"[Protocol] Ошибка печати ID={mid}: {e}")


# ============================================================================
# Установка дат для выбранных номеров
# ============================================================================
def _open_create_dates_dialog():
    by_mid = defaultdict(list)
    for pos_idx, (mid, n) in _C._selected_numbers.items():
        tag = f'pm_sel_{pos_idx}'
        if dpg.does_item_exist(tag) and dpg.get_value(tag):
            if mid is not None and n != '':
                by_mid[mid].append(str(n))
    if not by_mid:
        _pm_status("Не отмечено ни одного номера")
        return

    if dpg.does_item_exist(_C.PM_CREATE_DATES_DLG):
        dpg.delete_item(_C.PM_CREATE_DATES_DLG)

    sw, sh = _layout.screen_size()
    with dpg.window(label="Установить даты для отмеченных номеров",
                    tag=_C.PM_CREATE_DATES_DLG, modal=True,
                    width=520, height=250,
                    pos=(max(20, (sw - 520) // 2),
                         max(20, (sh - 250) // 2))):
        dpg.add_text(f"Будет обновлено замеров: {len(by_mid)}, "
                     f"номеров: {sum(len(v) for v in by_mid.values())}",
                     color=(180, 220, 255))
        dpg.add_separator()
        dpg.add_text("Дата изготовления (MakeDate), YYYY-MM-DD:")
        dpg.add_input_text(tag='pm_cr_mk_date_input', width=-1)
        dpg.add_text("Дата перепроверки (MakeDate1), YYYY-MM-DD:")
        dpg.add_input_text(tag='pm_cr_mk_date1_input', width=-1)
        dpg.add_spacer(height=8)
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="Применить", width=150,
                callback=lambda: _save_create_dates(by_mid))
            dpg.add_button(
                label="Отмена", width=150,
                callback=lambda: dpg.delete_item(_C.PM_CREATE_DATES_DLG))


def _save_create_dates(by_mid: dict):
    md  = (dpg.get_value('pm_cr_mk_date_input') or '').strip()
    md1 = (dpg.get_value('pm_cr_mk_date1_input') or '').strip()
    if not md and not md1:
        _show_warning("Даты", "Не введена ни одна дата")
        return
    total = 0
    for mid, nums in by_mid.items():
        try:
            total += update_psidata_make_dates(
                int(mid), nums,
                make_date=md or None,
                make_date1=md1 or None)
        except Exception as e:
            _show_warning("Ошибка БД", f"Measure_ID={mid}:\n{e}")
            return
    _pm_status(f"Даты обновлены для {total} номеров")
    dpg.delete_item(_C.PM_CREATE_DATES_DLG)
    _show_info("Даты", f"Обновлено записей psidata: {total}")


# ============================================================================
# Построение вкладки
# ============================================================================
def _build_create_tab():
    with dpg.group(horizontal=True):
        with dpg.group(width=160):
            dpg.add_text("Тип резонатора")
            dpg.add_combo([], tag='pm_type_combo', width=160,
                          callback=_pm_on_type_changed)
        with dpg.group(width=200):
            dpg.add_text("Спецификация")
            dpg.add_combo([], tag='pm_spc_combo', width=200,
                          callback=_pm_on_spc_changed)
        with dpg.group(width=160):
            dpg.add_text("МСК")
            dpg.add_combo([], tag='pm_msk_combo', width=160,
                          callback=_pm_on_msk_changed)
        with dpg.group(width=140):
            dpg.add_text("Дата")
            dpg.add_combo([], tag='pm_date_combo', width=140,
                          callback=_pm_on_date_changed)
        with dpg.group(width=180):
            dpg.add_text("Файл")
            dpg.add_combo([], tag='pm_file_combo', width=180)

    with dpg.group(horizontal=True):
        with dpg.group(width=320):
            dpg.add_text("Поиск МСК по части номера")
            dpg.add_input_text(tag='pm_msk_search_input', width=320,
                               hint="456  |  25-2456", on_enter=True,
                               callback=lambda s, a: _pm_on_msk_search())
        with dpg.group(width=120):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Найти МСК', width=120,
                           callback=lambda s, a: _pm_on_msk_search())
        with dpg.group(width=120):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Очистить МСК', width=120,
                           callback=_pm_on_clear_msk_search)

    with dpg.group(horizontal=True):
        with dpg.group(width=150):
            dpg.add_text("ID замера (Enter)")
            dpg.add_input_text(tag='pm_measure_id_input', width=150,
                               decimal=True, on_enter=True,
                               callback=_pm_on_measure_id_enter)
        with dpg.group(width=160):
            dpg.add_text("Список ID")
            dpg.add_combo([], tag='pm_measure_id_combo', width=160,
                          callback=_pm_on_measure_id_pick)
        with dpg.group(width=150):
            dpg.add_spacer(height=18)
            dpg.add_checkbox(label="Только годные",
                             tag='pm_only_good_check')
        with dpg.group(width=130):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Загрузить', width=130,
                           callback=lambda s, a: _pm_reload_data())

    with dpg.group(horizontal=True):
        with dpg.group(width=420):
            dpg.add_text("Номера (одиночный / список / диапазон)")
            dpg.add_input_text(
                tag='pm_numbers_input', width=420,
                hint="JN4450  |  JN4450,JN4451  |  JN4450-JN4460",
                on_enter=True,
                callback=lambda s, a: _pm_reload_data())
        with dpg.group(width=230):
            dpg.add_text("Режим поиска по номерам")
            dpg.add_radio_button(
                [MODE_ONLY_NUM, MODE_FULL_MSK],
                tag='pm_search_mode',
                horizontal=True, default_value=MODE_ONLY_NUM)
        with dpg.group(width=140):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Очистить', width=140,
                           callback=_pm_on_clear_numbers)

    dpg.add_separator()
    dpg.add_text("", tag=_C.PM_STATUS_TAG, color=(100, 255, 100))
    dpg.add_separator()

    with dpg.child_window(tag='pm_main_area', width=-1, height=-70,
                          border=False):
        with dpg.group(horizontal=True):
            with dpg.child_window(tag='pm_table_child', width=-360,
                                  height=-1, border=False):
                with dpg.group(tag=_C.PM_TABLE_CONTAINER):
                    dpg.add_text("- нажмите <Загрузить> для поиска -",
                                 color=(140, 140, 140))
            with dpg.child_window(width=340, height=-1, border=True):
                _build_pm_info_panel()

    with dpg.group(horizontal=True):
        dpg.add_button(label="Печать ПСИ", width=150, height=42,
                       callback=lambda: _on_print_click("ПСИ"))
        dpg.add_button(label="Печать Предъявительский (ОТК)",
                       width=230, height=42,
                       callback=lambda: _on_print_click("ОТК"))
        dpg.add_button(label="Печать простой ОТК",
                       width=180, height=42,
                       callback=lambda: _on_print_click("ОТКп"))
        dpg.add_button(
            label="Печать паспорта",
            width=180,
            height=42,
            callback=lambda: _on_print_passport_click("ПСИ")  # для паспорта всегда ПСИ
        )
        dpg.add_spacer(width=12)
        dpg.add_button(label="Выбрать все", width=120, height=42,
                       callback=_pm_select_all)
        dpg.add_button(label="Снять все", width=120, height=42,
                       callback=_pm_clear_selection)
        dpg.add_button(label="Установить даты (выбранные)",
                       width=220, height=42,
                       callback=_open_create_dates_dialog)


def _on_print_passport_click(psi_type: str):
    if _C._loaded_df is None or _C._loaded_df.empty:
        _pm_status("Данные не загружены")
        return
    # Для паспорта всегда используем нормы ПСИ
    psi_type = "ПСИ"
    by_mid = defaultdict(list)
    for pos_idx, (mid, n) in _C._selected_numbers.items():
        tag = f'pm_sel_{pos_idx}'
        if dpg.does_item_exist(tag) and dpg.get_value(tag):
            by_mid[mid].append(n)
    if not by_mid:
        _pm_status("Не выбрано ни одного номера")
        return
    for mid, nums in by_mid.items():
        try:
            from .Protocol_Passport import print_passport_for_protocol
            print_passport_for_protocol(mid)
        except Exception as e:
            print(f"[Protocol] Ошибка печати паспорта ID={mid}: {e}")

def _build_pm_info_panel():
    dpg.add_text("Информация о записи", color=(180, 220, 255))
    dpg.add_separator()

    def info_row(label, tag):
        with dpg.group(horizontal=True):
            dpg.add_text(f"{label}:", color=(150, 200, 255))
            dpg.add_text("", tag=tag)

    info_row("МСК", 'pm_info_msk')
    info_row("Файл", 'pm_info_file')
    info_row("Спецификация", 'pm_info_spc')
    info_row("Дата", 'pm_info_date')
    info_row("Время", 'pm_info_time')
    info_row("ID замера", 'pm_info_measure_id')
    info_row("Записей", 'pm_info_count')

    dpg.add_separator()
    dpg.add_text("Параметры спецификации", color=(180, 220, 255))
    with dpg.group(horizontal=True):
        dpg.add_text("Тип протокола:", color=(150, 200, 255))
        dpg.add_combo(['ПСИ', 'ОТК'],
                      tag='pm_psi_type_combo', width=120,
                      default_value='ОТК',
                      callback=_pm_on_psi_type_changed)
    with dpg.group(tag=_C.PM_NORMS_GROUP):
        dpg.add_text("- спецификация не выбрана -",
                     tag='pm_norms_hint', color=(140, 140, 140))