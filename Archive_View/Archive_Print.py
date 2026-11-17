"""Печать протоколов (обычный / тестовый / предъявительский) и распечатка температур."""
import traceback
from contextlib import contextmanager

import pandas as pd
import dearpygui.dearpygui as dpg

import Temperature_Measure.Report as _Report
from Temperature_Measure.Report import (
    create_protocol, generate_filename, open_pdf, generate_pdf,
    create_test_protocol, create_presentation_protocol,
)
from .Archive_Constants import WINDOW_TAG, ALL_MSK, MODE_ONLY_NUM
from .Archive_Data import (
    load_specification, load_spc_map_for_archive,
    get_archive_statistics, build_archive_print_data,
    build_archive_status_df, build_view_data_from_archive,
    get_headers_dict, get_round_dict, rename_fields_to_parameters,
    load_archive_temperatures, load_archive_temperatures_by_mids,
    prepare_temperatures_for_pdf, find_measure_ids_by_numbers,
    parse_numbers_input, load_tu_parameters_for_spec,
    build_presentation_params,
)

from Temperature_Measure.Report import open_pdf

from reportlab.lib.pagesizes import A4


# ---- подмена форматирования статистики (round_map из spec) ----
_orig_format_stat = _Report.format_parameter_stat
_round_map_ctx = {'round_map': None}


def _patched_format_parameter_stat(col, metric, stats_df):
    param_stats = stats_df[stats_df['Parameter'] == col]
    if param_stats.empty:
        return '-'
    value = param_stats[metric].values[0]
    if pd.isna(value):
        return '-'
    if metric in ['Брак', 'Годные']:
        return f"{int(value)}"
    decimals = 2
    rm = _round_map_ctx.get('round_map') or {}
    if col in rm:
        try:
            decimals = int(rm[col])
        except (TypeError, ValueError):
            decimals = 2
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


@contextmanager
def _stat_rounding_ctx(round_map):
    _round_map_ctx['round_map'] = round_map or {}
    _Report.format_parameter_stat = _patched_format_parameter_stat
    try:
        yield
    finally:
        _Report.format_parameter_stat = _orig_format_stat
        _round_map_ctx['round_map'] = None


# ============================================================================
# Обычный протокол
# ============================================================================
def print_archive_protocol():
    try:
        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для печати")
            return
        if 'Measure_ID' in df.columns:
            mids = df['Measure_ID'].dropna().unique()
            if len(mids) > 1:
                for mid in sorted(mids):
                    _print_single_protocol(df[df['Measure_ID'] == mid], int(mid))
                return
        try:
            mid = int(df.iloc[0].get('Measure_ID', 0))
        except (TypeError, ValueError):
            mid = 0
        _print_single_protocol(df, mid)
    except Exception as e:
        print(f"[Archive] Ошибка печати: {e}")
        traceback.print_exc()


def print_archive_protocol_selected():
    try:
        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для печати")
            return
        if not dpg.does_item_exist('archive_print_measure_combo'):
            return
        mid_str = dpg.get_value('archive_print_measure_combo')
        if not mid_str:
            print("[Archive] Не выбран Measure_ID для печати")
            return
        try:
            mid = int(mid_str)
        except (TypeError, ValueError):
            return
        if 'Measure_ID' not in df.columns:
            return
        df_mid = df[df['Measure_ID'] == mid]
        if df_mid.empty:
            return
        _print_single_protocol(df_mid, mid)
    except Exception as e:
        print(f"[Archive] Ошибка печати выбранного замера: {e}")
        traceback.print_exc()

def _print_single_protocol(df, measure_id):
    row = df.iloc[0]
    spc_name = (row.get('Spc') or dpg.get_value('archive_spc_combo') or '')
    if not spc_name:
        return
    spc_df = load_specification(spc_name)
    if spc_df.empty:
        return
    spc_row = spc_df.iloc[0]

    from .Archive_UI import _current_psi_type, _load_spc_map_for_display
    psi_type = _current_psi_type()
    spc_map = _load_spc_map_for_display(spc_name, psi_type)
    if spc_map.empty:
        return

    data_df   = build_archive_print_data(df, spc_map)
    status_df = build_archive_status_df(df, spc_map)
    view_data = build_view_data_from_archive(df, spc_row, psi_type=psi_type)
    stats_df  = get_archive_statistics(df, spc_map)
    headers   = get_headers_dict(spc_map)
    round_map = get_round_dict(spc_map)

    if 'MSK' in df.columns:
        uniq = df['MSK'].dropna().unique()
        if len(uniq) > 1:
            view_data['MSK'] = f'{ALL_MSK} ({len(uniq)})'
            view_data['Full_Msk'] = ALL_MSK

    filename = generate_filename(measure_id)
    with _stat_rounding_ctx(round_map):
        path = create_protocol(data_df, status_df, headers, spc_map,
                               view_data, stats_df, measure_id, filename)
    open_pdf(path)
    print(f"[Archive] Протокол создан: {path}")




# ============================================================================
# Тестовый протокол
# ============================================================================
def print_archive_test_protocol():
    try:
        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для тестового протокола")
            return
        if 'Measure_ID' in df.columns:
            mids = df['Measure_ID'].dropna().unique()
            if len(mids) > 1:
                for mid in sorted(mids):
                    _print_single_test_protocol(
                        df[df['Measure_ID'] == mid], int(mid))
                return
        try:
            mid = int(df.iloc[0].get('Measure_ID', 0))
        except (TypeError, ValueError):
            mid = 0
        _print_single_test_protocol(df, mid)
    except Exception as e:
        print(f"[Archive] Ошибка печати тестового протокола: {e}")
        traceback.print_exc()

def _print_single_test_protocol(df, measure_id):
    row = df.iloc[0]
    spc_name = (row.get('Spc') or dpg.get_value('archive_spc_combo') or '')
    if not spc_name:
        return
    spc_df = load_specification(spc_name)
    if spc_df.empty:
        return
    spc_row = spc_df.iloc[0]

    from .Archive_UI import _current_psi_type, _load_spc_map_for_display
    psi_type = _current_psi_type()
    spc_map = _load_spc_map_for_display(spc_name, psi_type)
    if spc_map.empty:
        return

    data_df   = build_archive_print_data(df, spc_map)
    status_df = build_archive_status_df(df, spc_map)
    view_data = build_view_data_from_archive(df, spc_row, psi_type=psi_type)
    stats_df  = get_archive_statistics(df, spc_map)
    headers   = get_headers_dict(spc_map)
    round_map = get_round_dict(spc_map)

    if 'MSK' in df.columns:
        uniq = df['MSK'].dropna().unique()
        if len(uniq) > 1:
            view_data['MSK'] = f'{ALL_MSK} ({len(uniq)})'
            view_data['Full_Msk'] = ALL_MSK

    filename = generate_filename(measure_id).replace('.pdf', '_test.pdf')
    with _stat_rounding_ctx(round_map):
        path = create_test_protocol(data_df, status_df, headers, spc_map,
                                    view_data, stats_df, measure_id, filename)
    open_pdf(path)
    print(f"[Archive] Тестовый протокол создан: {path}")










# ============================================================================
# Распечатка температур
# ============================================================================
def print_archive_temperatures():
    try:
        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для распечатки")
            return

        row = df.iloc[0]
        try:
            measure_id = int(row.get('Measure_ID', 0))
        except (TypeError, ValueError):
            measure_id = 0
        msk = row.get('MSK')

        spc_name = (row.get('Spc') or dpg.get_value('archive_spc_combo') or '')
        if not spc_name:
            return
        spc_df = load_specification(spc_name)
        if spc_df.empty:
            return
        spc_row = spc_df.iloc[0]
        try:
            t_ref = float(spc_row.get('Tnastr', 25) or 25)
        except (TypeError, ValueError):
            t_ref = 25.0

        numbers_filter = None
        if dpg.does_item_exist('archive_numbers_input'):
            numbers_filter = parse_numbers_input(
                dpg.get_value('archive_numbers_input') or '')
        mode = (dpg.get_value('archive_search_mode')
                if dpg.does_item_exist('archive_search_mode')
                else MODE_ONLY_NUM)
        only_good = dpg.get_value('archive_only_good_check')

        mids_from_df = (
            sorted(int(m) for m in df['Measure_ID'].dropna().unique())
            if 'Measure_ID' in df.columns else [])

        if numbers_filter:
            if only_good and mids_from_df:
                mids = mids_from_df
            else:
                mids = find_measure_ids_by_numbers(
                    numbers_filter, only_good=False)
            if not mids:
                print("[Archive] По заданным номерам замеры не найдены")
                return
            temps_df = load_archive_temperatures_by_mids(mids)
        elif len(mids_from_df) > 1:
            temps_df = load_archive_temperatures_by_mids(mids_from_df)
        elif measure_id:
            temps_df = load_archive_temperatures(measure_id=measure_id)
        elif msk:
            temps_df = load_archive_temperatures(msk=msk)
        else:
            temps_df = pd.DataFrame()

        if temps_df.empty:
            print("[Archive] Нет данных температур для распечатки")
            return

        if numbers_filter and mode == MODE_ONLY_NUM:
            col = ('N' if 'N' in temps_df.columns
                   else ('Numbers' if 'Numbers' in temps_df.columns else None))
            if col:
                mask = (temps_df[col].astype(str).str.upper()
                        .str.strip().isin(numbers_filter))
                temps_df = temps_df[mask].reset_index(drop=True)
            if temps_df.empty:
                print("[Archive] Нет температур по заданным номерам")
                return

        if only_good and 'Measure_ID' in df.columns:
            num_col_df = ('N' if 'N' in df.columns
                          else ('Numbers' if 'Numbers' in df.columns else None))
            num_col_t = ('N' if 'N' in temps_df.columns
                         else ('Numbers' if 'Numbers' in temps_df.columns else None))
            if (num_col_df and num_col_t
                    and 'Measure_ID' in temps_df.columns):
                good_pairs = set()
                for mid_d, n_d in zip(df['Measure_ID'], df[num_col_df]):
                    try:
                        good_pairs.add(
                            (int(mid_d), str(n_d).strip().upper()))
                    except (TypeError, ValueError):
                        continue
                keep = []
                for mid_t, n_t in zip(temps_df['Measure_ID'],
                                      temps_df[num_col_t]):
                    try:
                        keep.append(
                            (int(mid_t), str(n_t).strip().upper())
                            in good_pairs)
                    except (TypeError, ValueError):
                        keep.append(False)
                n_before = len(temps_df)
                temps_df = temps_df[keep].reset_index(drop=True)
                print(f"[Archive] only_good (температуры): "
                      f"{n_before} → {len(temps_df)} строк")
                if temps_df.empty:
                    print("[Archive] Нет годных изделий для распечатки")
                    return

        pdf_df = prepare_temperatures_for_pdf(temps_df, t_ref, spc_row)
        if pdf_df.empty:
            print("[Archive] Не удалось подготовить данные температур")
            return

        view_data = build_view_data_from_archive(df, spc_row)
        if 'MSK' in df.columns:
            uniq = df['MSK'].dropna().unique()
            if len(uniq) > 1:
                view_data['MSK'] = f'{ALL_MSK} ({len(uniq)})'
                view_data['Full_Msk'] = ALL_MSK

        filename = generate_filename(measure_id, print_version=True)
        path = generate_pdf(measure_id, view_data, pdf_df,
                            filename, num_columns=4)
        open_pdf(path)
        print(f"[Archive] Распечатка создана: {path}")

    except Exception as e:
        print(f"[Archive] Ошибка распечатки температур: {e}")
        traceback.print_exc()


# ============================================================================
# НОВЫЕ ФУНКЦИИ: Протокол ПСИ, Предъявительский (ОТК) и Этикетка МСК
# ============================================================================

def print_archive_psi_protocol():
    """Протокол ПСИ (Приемо-сдаточные испытания) - форма МК.10.602Ф."""
    try:
        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для протокола ПСИ")
            return
        if 'Measure_ID' in df.columns:
            mids = df['Measure_ID'].dropna().unique()
            if len(mids) > 1:
                for mid in sorted(mids):
                    _print_single_psi_protocol(df[df['Measure_ID'] == mid], int(mid))
                return
        try:
            mid = int(df.iloc[0].get('Measure_ID', 0))
        except (TypeError, ValueError):
            mid = 0
        _print_single_psi_protocol(df, mid)
    except Exception as e:
        print(f"[Archive] Ошибка печати протокола ПСИ: {e}")
        traceback.print_exc()


def _print_single_psi_protocol(df, measure_id):
    print(f"\n{'=' * 70}")
    print(f"[PSI] Печать протокола ПСИ для measure_id={measure_id}")
    print(f"{'=' * 70}")

    row = df.iloc[0]
    spc_name = (row.get('Spc') or dpg.get_value('archive_spc_combo') or '')
    print(f"[PSI] Spc='{spc_name}'")
    if not spc_name:
        return

    spc_df = load_specification(spc_name)
    if spc_df.empty:
        print(f"[PSI] Спецификация не найдена!")
        return
    spc_row = spc_df.iloc[0]

    tu_data = load_tu_parameters_for_spec(spc_name) or {
        'tu_name': '', 'tu_row': {}, 'rtype': ''}
    print(f"[PSI] TU='{tu_data.get('tu_name')}', "
          f"tu_index={tu_data.get('tu_index')}")

    presentation_params = build_presentation_params(spc_name, tu_data)
    if not presentation_params:
        print(f"[PSI] Нет параметров для протокола — выход")
        return

    from .Archive_Data import (
        resolve_param_column, get_next_protocol_number_archive,
        save_protocol_to_db, log_protocol_creation
    )
    from .Archive_UI import _load_spc_map_for_display
    from Temperature_Measure.Report import create_psi_protocol

    # ИСПОЛЬЗУЕМ НОРМЫ ПСИ
    psi_type = 'ПСИ'
    spc_map = _load_spc_map_for_display(spc_name, psi_type)

    mapped = rename_fields_to_parameters(df)

    good_mask = pd.Series(True, index=mapped.index)

    # Фильтрация годных по нормам ПСИ
    for p in presentation_params:
        if not p['has_norm']:
            continue
        col = resolve_param_column(mapped, p['param'])
        if col is None:
            print(f"[PSI] Фильтрация: '{p['param']}' → колонки нет, пропуск")
            continue
        vals = pd.to_numeric(mapped[col], errors='coerce')
        if (p['has_max'] and p['max_otk'] is not None
                and not pd.isna(p['max_otk'])):
            good_mask &= (vals <= float(p['max_otk']))
        if (p['has_min'] and p['min_otk'] is not None
                and not pd.isna(p['min_otk'])):
            good_mask &= (vals >= float(p['min_otk']))
        good_mask &= vals.notna()

    df_good = df[good_mask].copy()
    print(f"[PSI] Годных записей: {len(df_good)} из {len(df)}")
    if df_good.empty:
        print(f"[PSI] Нет годных изделий — выход")
        dpg.set_value('archive_status_text', 'Нет годных изделий для протокола ПСИ')
        return

    # ▼ СОРТИРОВКА: ЧИСЛА КАК ЧИСЛА, СТРОКИ КАК СТРОКИ
    def _sort_key(val):
        if pd.isna(val): return (2, 0)
        s = str(val).strip()
        if not s: return (2, 0)

        if s.isdigit():
            return (0, int(s))
        return (1, s.lower())

    if 'N' in df_good.columns:
        idx_sort = df_good['N'].map(_sort_key).argsort()
        df_good = df_good.iloc[idx_sort].reset_index(drop=True)
    elif 'Numbers' in df_good.columns:
        idx_sort = df_good['Numbers'].map(_sort_key).argsort()
        df_good = df_good.iloc[idx_sort].reset_index(drop=True)

    data_df = build_archive_print_data(df_good, spc_map)
    status_df = build_archive_status_df(df_good, spc_map)
    view_data = build_view_data_from_archive(df_good, spc_row, psi_type=psi_type)

    def _s(v):
        if v is None: return ''
        try:
            if pd.isna(v): return ''
        except (TypeError, ValueError):
            pass
        return str(v)

    view_data['TU'] = _s(spc_row.get('TU'))
    view_data['TGK'] = _s(spc_row.get('TGK'))
    view_data['Spc_Text'] = _s(spc_row.get('Text')) or spc_name
    view_data['Date'] = _s(row.get('Date'))
    view_data['Protokol_Type'] = 'приемо-сдаточных испытаний изделий'

    filename = generate_filename(measure_id).replace('.pdf', '_psi.pdf')

    # 1. Получаем следующий номер протокола
    protokol_n = get_next_protocol_number_archive()
    print(f"[PSI] Новый номер протокола: {protokol_n}")

    # 2. Сохраняем в БД и получаем Measure_protokol_ID
    measure_protokol_id = save_protocol_to_db(
        protokol_n=protokol_n,
        msk=view_data.get('MSK', ''),
        file_name=filename,
        measure_id=measure_id,
        count=len(data_df),
        spc=view_data.get('Spc_Text', '')
    )

    # 3. Вызываем генерацию PDF
    print(f"[PSI] Вызов create_psi_protocol...")
    path = create_psi_protocol(
        data_df=data_df,
        status_df=status_df,
        view_data=view_data,
        tu_data=tu_data,
        presentation_params=presentation_params,
        spc_row=spc_row,
        measure_id=measure_id,
        filename=filename,
        measure_protokol_id=measure_protokol_id
    )

    # 4. Пишем лог в БД
    log_protocol_creation(measure_id=measure_id, protokol_n=protokol_n)

    # 5. Открываем PDF
    open_pdf(path)
    print(f"[PSI] Готово: {path}")
    print(f"{'=' * 70}\n")
def _print_single_psi_protocol_10(df, measure_id):
    row = df.iloc[0]
    spc_name = (row.get('Spc') or dpg.get_value('archive_spc_combo') or '')
    if not spc_name:
        return
    spc_df = load_specification(spc_name)
    if spc_df.empty:
        return
    spc_row = spc_df.iloc[0]

    # ЖЕСТКО ИСПОЛЬЗУЕМ НОРМЫ ПСИ
    from .Archive_UI import _load_spc_map_for_display
    psi_type = 'ПСИ'
    spc_map = _load_spc_map_for_display(spc_name, psi_type)
    if spc_map.empty:
        return

    data_df = build_archive_print_data(df, spc_map)
    status_df = build_archive_status_df(df, spc_map)
    view_data = build_view_data_from_archive(df, spc_row, psi_type=psi_type)
    stats_df = get_archive_statistics(df, spc_map)
    headers = get_headers_dict(spc_map)
    round_map = get_round_dict(spc_map)

    if 'MSK' in df.columns:
        uniq = df['MSK'].dropna().unique()
        if len(uniq) > 1:
            view_data['MSK'] = f'{ALL_MSK} ({len(uniq)})'
            view_data['Full_Msk'] = ALL_MSK

    filename = generate_filename(measure_id).replace('.pdf', '_psi.pdf')
    with _stat_rounding_ctx(round_map):
        path = create_protocol(data_df, status_df, headers, spc_map,
                               view_data, stats_df, measure_id, filename)
    open_pdf(path)
    print(f"[Archive] Протокол ПСИ создан: {path}")


def print_archive_presentation_protocol():
    """Предъявительский протокол (ОТК) - форма МК.10.605Ф."""
    try:
        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для предъявительского протокола")
            return
        if 'Measure_ID' in df.columns:
            mids = df['Measure_ID'].dropna().unique()
            if len(mids) > 1:
                for mid in sorted(mids):
                    _print_single_presentation_protocol(
                        df[df['Measure_ID'] == mid], int(mid))
                return
        try:
            mid = int(df.iloc[0].get('Measure_ID', 0))
        except (TypeError, ValueError):
            mid = 0
        _print_single_presentation_protocol(df, mid)
    except Exception as e:
        print(f"[Archive] Ошибка предъявительского протокола: {e}")
        traceback.print_exc()


def _print_single_presentation_protocol(df, measure_id):
    print(f"\n{'=' * 70}")
    print(f"[Presentation] Печать протокола для measure_id={measure_id}")
    print(f"{'=' * 70}")

    row = df.iloc[0]
    spc_name = (row.get('Spc') or dpg.get_value('archive_spc_combo') or '')
    print(f"[Presentation] Spc='{spc_name}'")
    if not spc_name:
        return

    spc_df = load_specification(spc_name)
    if spc_df.empty:
        print(f"[Presentation] Спецификация не найдена!")
        return
    spc_row = spc_df.iloc[0]

    tu_data = load_tu_parameters_for_spec(spc_name) or {
        'tu_name': '', 'tu_row': {}, 'rtype': ''}
    print(f"[Presentation] TU='{tu_data.get('tu_name')}', "
          f"tu_index={tu_data.get('tu_index')}")

    presentation_params = build_presentation_params(spc_name, tu_data)
    if not presentation_params:
        print(f"[Presentation] Нет presentation_params — выход")
        return

    from .Archive_Data import (
        resolve_param_column, _prepare_spc_map,
        get_next_protocol_number_archive, save_protocol_to_db,
        log_protocol_creation
    )
    from .Archive_UI import _load_spc_map_for_display

    # ЖЕСТКО ИСПОЛЬЗУЕМ НОРМЫ ОТК
    psi_type = 'ОТК'
    spc_map = _load_spc_map_for_display(spc_name, psi_type)

    # ▼ Замена Fmax+Fmin -> ABS(Fmax, Fmin) — ТОЛЬКО для предъявительского
    spc_map = _prepare_spc_map(spc_map)

    mapped = rename_fields_to_parameters(df)

    good_mask = pd.Series(True, index=mapped.index)

    # Фильтрация годных по нормам ОТК
    for p in presentation_params:
        if not p['has_norm']:
            continue
        col = resolve_param_column(mapped, p['param'])
        if col is None:
            print(f"[Presentation] Фильтрация: '{p['param']}' → колонки нет, пропуск")
            continue
        vals = pd.to_numeric(mapped[col], errors='coerce')
        if (p['has_max'] and p['max_otk'] is not None
                and not pd.isna(p['max_otk'])):
            good_mask &= (vals <= float(p['max_otk']))
        if (p['has_min'] and p['min_otk'] is not None
                and not pd.isna(p['min_otk'])):
            good_mask &= (vals >= float(p['min_otk']))
        good_mask &= vals.notna()

    df_good = df[good_mask].copy()
    print(f"[Presentation] Годных записей: {len(df_good)} из {len(df)}")
    if df_good.empty:
        print(f"[Presentation] Нет годных изделий — выход")
        dpg.set_value('archive_status_text', 'Нет годных изделий для протокола')
        return

    # ▼ СОРТИРОВКА: ЧИСЛА КАК ЧИСЛА, СТРОКИ КАК СТРОКИ
    def _sort_key(val):
        if pd.isna(val): return (2, 0)  # Пустые в конец
        s = str(val).strip()
        if not s: return (2, 0)

        if s.isdigit():
            return (0, int(s))  # Если состоит только из цифр -> по числу
        return (1, s.lower())  # Иначе -> по алфавиту (как строку)

    if 'N' in df_good.columns:
        idx_sort = df_good['N'].map(_sort_key).argsort()
        df_good = df_good.iloc[idx_sort].reset_index(drop=True)
    elif 'Numbers' in df_good.columns:
        idx_sort = df_good['Numbers'].map(_sort_key).argsort()
        df_good = df_good.iloc[idx_sort].reset_index(drop=True)

    data_df = build_archive_print_data(df_good, spc_map)
    status_df = build_archive_status_df(df_good, spc_map)
    view_data = build_view_data_from_archive(df_good, spc_row, psi_type=psi_type)

    def _s(v):
        if v is None: return ''
        try:
            if pd.isna(v): return ''
        except (TypeError, ValueError):
            pass
        return str(v)

    view_data['TU'] = _s(spc_row.get('TU'))
    view_data['TGK'] = _s(spc_row.get('TGK'))
    view_data['Spc_Text'] = _s(spc_row.get('Text')) or spc_name
    view_data['Date'] = _s(row.get('Date'))
    view_data['Protokol_Type'] = 'предъявительских испытаний изделий'

    filename = generate_filename(measure_id).replace('.pdf', '_presentation.pdf')

    # 1. Получаем следующий номер протокола (для таблицы)
    protokol_n = get_next_protocol_number_archive()
    print(f"[Presentation] Новый номер протокола: {protokol_n}")

    # 2. Сохраняем в БД и получаем Measure_protokol_ID (для QR-кода)
    measure_protokol_id = save_protocol_to_db(
        protokol_n=protokol_n,
        msk=view_data.get('MSK', ''),
        file_name=filename,
        measure_id=measure_id,
        count=len(data_df),
        spc=view_data.get('Spc_Text', '')
    )

    # 3. Вызываем генерацию PDF, передавая Measure_protokol_ID
    print(f"[Presentation] Вызов create_presentation_protocol...")
    path = create_presentation_protocol(
        data_df=data_df,
        status_df=status_df,
        view_data=view_data,
        tu_data=tu_data,
        presentation_params=presentation_params,
        spc_row=spc_row,
        measure_id=measure_id,
        filename=filename,
        measure_protokol_id=measure_protokol_id
    )

    # 4. Пишем лог в БД
    log_protocol_creation(measure_id=measure_id, protokol_n=protokol_n)

    # 5. Открываем PDF
    open_pdf(path)
    print(f"[Presentation] Готово: {path}")
    print(f"{'=' * 70}\n")




def print_archive_msk_label():
    """Генерация этикетки МСК в верхней части листа A4 (книжная)."""
    import os
    from datetime import datetime
    try:
        from reportlab.pdfgen import canvas
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        import Options
        from Temperature_Measure.Report import open_pdf
        from reportlab.lib.pagesizes import A4

        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для этикетки")
            dpg.set_value('archive_status_text', 'Нет данных для этикетки')
            return

        row = df.iloc[0]
        msk = str(row.get('MSK', ''))
        spc = str(row.get('Spc', ''))
        date_val = str(row.get('Date', ''))
        time_val = str(row.get('Time', ''))
        mid = str(row.get('Measure_ID', ''))
        file_val = str(row.get('File', ''))

        filename = f"label_{msk}_{datetime.now():%Y%m%d_%H%M%S}.pdf"
        filepath = os.path.join(Options.get_measure_protokol_path(), filename)

        # Размер A4 (595.27 x 841.89 points)
        width, height = A4

        c = canvas.Canvas(filepath, pagesize=A4)

        font_name = "Helvetica"
        try:
            font_path = "C:\\Windows\\Fonts\\arial.ttf"
            if os.path.exists(font_path):
                pdfmetrics.registerFont(TTFont('Arial', font_path))
                font_name = 'Arial'
        except Exception:
            pass

        # Блок вверху. Высота A4 = 842. 15% от 842 = ~126 points.
        block_w = 400
        block_h = 115
        x = 40
        y = height - 40 - block_h  # Отступ сверху 40 pt

        # Рамка
        c.setLineWidth(1)
        c.rect(x, y, block_w, block_h)

        c.setFont(font_name, 18)
        c.drawString(x + 15, y + block_h - 25, f"МСК: {msk}")

        c.setFont(font_name, 10)
        c.drawString(x + 15, y + block_h - 50, f"Спецификация: {spc}")
        c.drawString(x + 15, y + block_h - 65, f"Дата/Время: {date_val} {time_val}")
        c.drawString(x + 15, y + block_h - 80, f"ID замера: {mid}")

        if len(file_val) > 35:
            file_val = file_val[:32] + "..."
        c.drawString(x + 15, y + block_h - 95, f"Файл: {file_val}")

        c.showPage()
        c.save()

        open_pdf(filepath)
        print(f"[Archive] Этикетка МСК создана: {filepath}")
        dpg.set_value('archive_status_text', f'Этикетка: {os.path.basename(filepath)}')
    except Exception as e:
        print(f"[Archive] Ошибка печати этикетки МСК: {e}")
        traceback.print_exc()
