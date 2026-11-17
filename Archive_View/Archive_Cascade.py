"""Bootstrap, каскад фильтров, Measure_ID, reload — единая точка загрузки."""
import pandas as pd
import dearpygui.dearpygui as dpg

from .Archive_Constants import ALL_MSK, MODE_ONLY_NUM, _progress_state
from .Archive_Data import (
    get_archive_types, get_archive_specs_by_type, get_archive_msk_list,
    get_archive_dates_list, get_archive_files_list, load_archive_data,
    load_measure_ids_by_msk, load_archive_by_measure_id, parse_numbers_input,
)
from .Archive_Helpers import _filter_good_only
from .Archive_Search import _start_numbers_search

from .Archive_UI import (_fill_table, _fill_info, _fill_norms,
                        _resolve_display_spc, _apply_psi_type_from_df)

_suppress_cascade = False


def _bootstrap():
    try:
        from .Archive_TableSync import sync_table_structure
        report = sync_table_structure()
        for line in report:
            if 'OK' not in line:
                print(f"[Archive/TableSync] {line}")
    except Exception as e:
        print(f"[Archive] TableSync недоступен: {e}")
    try:
        types = get_archive_types()
        dpg.configure_item('archive_type_combo', items=types)
        if types:
            dpg.set_value('archive_type_combo', types[0])
            on_type_changed()
    except Exception as e:
        print(f"[Archive] Ошибка инициализации: {e}")


def on_type_changed(sender=None, data=None):
    if _suppress_cascade:
        return
    rtype = dpg.get_value('archive_type_combo')
    specs = get_archive_specs_by_type(rtype) if rtype else []
    dpg.configure_item('archive_spc_combo', items=specs)
    dpg.set_value('archive_spc_combo', specs[0] if specs else '')
    on_spc_changed()


def on_spc_changed(sender=None, data=None):
    if _suppress_cascade:
        return
    spc = dpg.get_value('archive_spc_combo')
    msks = get_archive_msk_list(spc if spc else None)
    items = [ALL_MSK] + msks
    dpg.configure_item('archive_msk_combo', items=items)
    dpg.set_value('archive_msk_combo', msks[0] if msks else ALL_MSK)
    on_msk_changed()
    _fill_norms(spc)


def on_msk_changed(sender=None, data=None):
    if _suppress_cascade:
        return
    # Смена МСК пользователем — сбрасываем Measure_ID,
    # иначе «Загрузить» / Enter уйдёт по старому ID.
    if dpg.does_item_exist('archive_measure_id_input'):
        dpg.set_value('archive_measure_id_input', '')

    msk_val = dpg.get_value('archive_msk_combo')

    if msk_val == ALL_MSK:
        for tag in ('archive_date_combo', 'archive_file_combo',
                    'archive_measure_id_combo'):
            dpg.configure_item(tag, items=[])
            dpg.set_value(tag, '')
        return

    msk = msk_val or None
    spc = dpg.get_value('archive_spc_combo')

    dates = get_archive_dates_list(msk, spc if spc else None)
    dpg.configure_item('archive_date_combo', items=dates)
    dpg.set_value('archive_date_combo', dates[0] if dates else '')

    mids = load_measure_ids_by_msk(msk) if msk else []
    dpg.configure_item('archive_measure_id_combo', items=mids)
    dpg.set_value('archive_measure_id_combo', mids[0] if mids else '')

    on_date_changed()


def on_date_changed(sender=None, data=None):
    if _suppress_cascade:
        return
    msk_val = dpg.get_value('archive_msk_combo')
    if msk_val == ALL_MSK:
        return
    msk = msk_val or None
    spc = dpg.get_value('archive_spc_combo')
    date = dpg.get_value('archive_date_combo')
    files = get_archive_files_list(msk, spc if spc else None,
                                   date if date else None)
    dpg.configure_item('archive_file_combo', items=files)
    dpg.set_value('archive_file_combo', files[0] if files else '')


# -------------------------------------------------------- Measure_ID
def _on_measure_id_pick(sender=None, data=None):
    mid = dpg.get_value('archive_measure_id_combo')
    if not mid:
        return
    dpg.set_value('archive_measure_id_input', str(mid))
    _on_measure_id_enter()

def _on_measure_id_enter(sender=None, data=None):
    global _suppress_cascade
    if _suppress_cascade:
        return
    raw = dpg.get_value('archive_measure_id_input')
    if raw is None:
        return
    raw_str = str(raw).strip()
    if not raw_str or not raw_str.isdigit():
        return
    mid = int(raw_str)
    if mid <= 0:
        return

    info = load_archive_by_measure_id(mid)
    if info is None:
        dpg.set_value('archive_status_text', f'ID {mid} не найден в psidata')
        return

    _suppress_cascade = True
    try:
        if info['rtype']:
            dpg.set_value('archive_type_combo', info['rtype'])
            dpg.configure_item('archive_spc_combo',
                               items=get_archive_specs_by_type(info['rtype']))
        if info['spc']:
            dpg.set_value('archive_spc_combo', info['spc'])
        if info['msk']:
            msks = get_archive_msk_list(info['spc'])
            dpg.configure_item('archive_msk_combo', items=[ALL_MSK] + msks)
            dpg.set_value('archive_msk_combo', info['msk'])
        mids = load_measure_ids_by_msk(info['msk']) if info['msk'] else []
        dpg.configure_item('archive_measure_id_combo', items=mids)
        dpg.set_value('archive_measure_id_combo',
                      mid if mid in mids else '')
        dpg.set_value('archive_measure_id_input', str(mid))
    finally:
        _suppress_cascade = False

    # Обновляем date/file уже ПОСЛЕ снятия suppress
    on_date_changed()

    # Сбрасываем «висящие» номера, чтобы reload пошёл по пути ID
    if dpg.does_item_exist('archive_numbers_input'):
        dpg.set_value('archive_numbers_input', '')

    reload_archive_data()


# ---------------------------------------------------------- очистка
def _on_clear_numbers(sender=None, data=None):
    if dpg.does_item_exist('archive_numbers_input'):
        dpg.set_value('archive_numbers_input', '')
    reload_archive_data()


# ----------------------------------------------------------- загрузка

def reload_archive_data():
    if _progress_state.get('active'):
        dpg.set_value('archive_status_text',
                      'Дождитесь завершения текущего поиска...')
        return

    from .Archive_Constants import _view_state
    _view_state['mode'] = 'normal'
    _view_state['target_numbers'] = []

    only_good = dpg.get_value('archive_only_good_check')

    numbers_filter = None
    if dpg.does_item_exist('archive_numbers_input'):
        numbers_filter = parse_numbers_input(
            dpg.get_value('archive_numbers_input') or '')

    # --- Measure_ID из input ---
    mid_str = dpg.get_value('archive_measure_id_input')
    measure_id = None
    if mid_str is not None:
        ms = str(mid_str).strip()
        if ms.isdigit() and int(ms) > 0:
            measure_id = int(ms)

    # --- Приоритет: numbers > ID ---
    # Введённые номера — это явное действие пользователя,
    # «висящий» Measure_ID из прошлой загрузки не должен его перебивать.
    if numbers_filter:
        # Синхронизируем UI: чистим поле ID, чтобы оно не вводило в
        # заблуждение (иначе следующий «Загрузить» опять уйдёт по ID).
        if measure_id and dpg.does_item_exist('archive_measure_id_input'):
            dpg.set_value('archive_measure_id_input', '')

        mode = (dpg.get_value('archive_search_mode')
                if dpg.does_item_exist('archive_search_mode')
                else MODE_ONLY_NUM)

        msk_v = dpg.get_value('archive_msk_combo') or ''
        spc_v = dpg.get_value('archive_spc_combo') or ''
        date_v = dpg.get_value('archive_date_combo') or ''
        file_v = dpg.get_value('archive_file_combo') or ''
        has_other = ((msk_v and msk_v != ALL_MSK)
                     or spc_v or date_v or file_v)
        if has_other:
            print("[Archive] Поиск по номерам выполняется по всей БД "
                  "(Spc/МСК/Дата/Файл игнорируются)")
            dpg.set_value(
                'archive_status_text',
                'Поиск по номерам по всей БД '
                '(фильтры Spc/МСК/Дата/Файл игнорируются)...')

        _start_numbers_search(numbers_filter, mode, only_good)
        return

    msk_val = dpg.get_value('archive_msk_combo') or None
    msk = None if msk_val == ALL_MSK else msk_val
    spc = dpg.get_value('archive_spc_combo') or None
    date = dpg.get_value('archive_date_combo') or None
    file = dpg.get_value('archive_file_combo') or None

    dpg.set_value('archive_status_text', 'Загрузка...')
    try:
        dpg.split_frame()
    except Exception:
        pass

    # --- Прямая загрузка по ID: игнорируем остальные фильтры ---
    if measure_id:
        df = load_archive_data(measure_id=measure_id, only_good=False)
    else:
        df = load_archive_data(msk=msk, spc=spc, date=date, file=file,
                               measure_id=None, only_good=False)

    if only_good and df is not None and not df.empty:
        n_before = len(df)
        df = _filter_good_only(df, spc or '')
        print(f"[Archive] only_good: {n_before} → {len(df)} строк")

    dpg.set_item_user_data('archive_view_window', df)
    _apply_psi_type_from_df(df)
    _fill_table(df)
    _fill_info(df)

    # Нормы — по фактическому Spc из загруженных данных
    spc_for_norms = _resolve_display_spc(df)
    _fill_norms(spc_for_norms)
    if df is None or df.empty:
        dpg.set_value('archive_status_text', 'Данные не найдены')
    else:
        n_mid = (df['Measure_ID'].nunique()
                 if 'Measure_ID' in df.columns else 0)
        dpg.set_value(
            'archive_status_text',
            f'Загружено: {len(df)} строк | '
            f'Measure_ID: {n_mid} | Spc: {spc_for_norms or "-"}')




