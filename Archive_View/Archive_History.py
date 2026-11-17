"""Режим «История по номеру»: группировка по N в таблице, единый протокол, экспорт."""
import os
import traceback
from datetime import datetime

import pandas as pd
import dearpygui.dearpygui as dpg

import Options
from Temperature_Measure.Report import create_protocol, open_pdf
from .Archive_Constants import WINDOW_TAG, _view_state
from .Archive_Data import (
    find_measure_ids_by_numbers, load_archive_by_numbers,
    load_specification, load_spc_map_for_archive,
    build_archive_print_data, build_archive_status_df,
    build_view_data_from_archive, get_headers_dict, get_round_dict,
    get_archive_statistics,
)
from .Archive_Print import _stat_rounding_ctx
from .Archive_UI import (_fill_table, _fill_info, _fill_norms,
                         _resolve_display_spc, _apply_psi_type_from_df)
from .Archive_Helpers import _filter_good_only, \
    _current_psi_type, _load_spc_map_for_display

def _number_col(df) -> str | None:
    if df is None or df.empty:
        return None
    if 'N' in df.columns:
        return 'N'
    if 'Numbers' in df.columns:
        return 'Numbers'
    return None


def _df_numbers(df) -> list[str]:
    col = _number_col(df)
    if not col:
        return []
    seen, out = set(), []
    for v in df[col].dropna():
        s = str(v).strip().upper()
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def _sort_by_number_and_date(df: pd.DataFrame) -> pd.DataFrame:
    n_col = _number_col(df)
    sort_cols = [n_col] if n_col else []
    for c in ('Date', 'Time', 'Measure_ID', 'Position'):
        if c in df.columns:
            sort_cols.append(c)
    if sort_cols:
        return df.sort_values(by=sort_cols, kind='stable').reset_index(drop=True)
    return df.reset_index(drop=True)


# ------------------------------------------------------------ загрузка
def load_history_for_current_view():
    df = dpg.get_item_user_data(WINDOW_TAG)
    if df is None or df.empty:
        dpg.set_value('archive_status_text',
                      'Нет данных — сначала загрузите замер')
        return

    numbers = _df_numbers(df)
    if not numbers:
        dpg.set_value('archive_status_text',
                      'В текущей выборке нет номеров резонаторов')
        return

    only_good = dpg.get_value('archive_only_good_check')
    dpg.set_value('archive_status_text',
                  f'Загрузка истории по {len(numbers)} номерам...')
    try:
        dpg.split_frame()
    except Exception:
        pass

    try:
        mids = find_measure_ids_by_numbers(numbers, only_good=False)
        if not mids:
            dpg.set_value('archive_status_text',
                          'Замеры с этими номерами не найдены')
            return

        history = load_archive_by_numbers(
            numbers, mode='Только номер', only_good=False, found_mids=mids)
        if history is None or history.empty:
            dpg.set_value('archive_status_text', 'История пуста')
            return

        history = _sort_by_number_and_date(history)

        if only_good:
            fallback_spc = dpg.get_value('archive_spc_combo') or ''
            n_before = len(history)
            history = _filter_good_only(history, fallback_spc)
            print(f"[Archive] history only_good: {n_before} → {len(history)}")

        _view_state['mode'] = 'history'
        _view_state['target_numbers'] = numbers

        dpg.set_item_user_data(WINDOW_TAG, history)

        from .Archive_UI import (_fill_table, _fill_info, _fill_norms,
                                 _resolve_display_spc)
        _apply_psi_type_from_df(history)
        _fill_table(history)
        _fill_info(history)

        spc_for_norms = _resolve_display_spc(history)
        _fill_norms(spc_for_norms)

        if history.empty:
            dpg.set_value('archive_status_text',
                          'История: годных записей нет')
            return

        n_mids = (history['Measure_ID'].nunique()
                  if 'Measure_ID' in history.columns else 0)
        n_groups = (history[_number_col(history)].nunique()
                    if _number_col(history) else 0)
        dpg.set_value(
            'archive_status_text',
            f'История: номеров {n_groups} | замеров: {n_mids} | '
            f'записей: {len(history)}')

    except Exception as e:
        print(f"[Archive] Ошибка загрузки истории: {e}")
        traceback.print_exc()
        dpg.set_value('archive_status_text', f'Ошибка истории: {e}')


# ------------------------------------------------------------- протокол
def print_history_grouped_protocol():
    """Один PDF: данные сгруппированы по номерам резонатора."""
    try:
        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для печати истории")
            dpg.set_value('archive_status_text', 'Нет данных для печати')
            return

        spc_name = dpg.get_value('archive_spc_combo') or ''
        if 'Spc' in df.columns:
            uniq = df['Spc'].dropna().unique()
            if len(uniq) >= 1 and uniq[0]:
                spc_name = uniq[0]
        if not spc_name:
            print("[Archive] Не определена спецификация")
            return

        spc_df = load_specification(spc_name)
        if spc_df.empty:
            print(f"[Archive] Спецификация {spc_name!r} не найдена")
            return
        spc_row = spc_df.iloc[0]

        # ▼ Тип протокола: ПСИ (без техзапаса) / ОТК (с техзапасом).
        #   Локальный импорт — не плодим цикл Archive_UI ⇄ Archive_History.
        psi_type = _current_psi_type()
        spc_map = _load_spc_map_for_display(spc_name, psi_type)
        if spc_map.empty:
            print(f"[Archive] Нет норм для {spc_name!r} (тип {psi_type})")
            return

        df_sorted = _sort_by_number_and_date(df)
        n_key = _number_col(df_sorted)
        n_key_data = 'Numbers'  # в data_df всегда Numbers

        # Базовые таблицы
        data_df = build_archive_print_data(df_sorted, spc_map)
        status_df = build_archive_status_df(df_sorted, spc_map)
        headers = get_headers_dict(spc_map)

        # --- Обогащение data_df: Дата / Время ---
        extra = [(src, lbl) for src, lbl in
                 (('Date', 'Дата'), ('Time', 'Время'))
                 if src in df_sorted.columns]
        if extra:
            data_df = data_df.copy()
            for src, lbl in extra:
                data_df[src] = df_sorted[src].values
                headers[src] = lbl
            base = [c for c in ('Positions', 'Numbers') if c in data_df.columns]
            ext  = [src for src, _ in extra]
            tail = [c for c in ('Status', 'Status2') if c in data_df.columns]
            params = [c for c in data_df.columns
                      if c not in base + ext + tail]
            data_df = data_df[base + ext + params + tail]

        # --- Строки-разделители по номерам ---
        new_data, new_status = [], []
        prev_n = None

        for i in range(len(df_sorted)):
            current_n = ''
            if n_key:
                current_n = str(df_sorted.iloc[i].get(n_key, '') or '').strip().upper()

            if current_n and current_n != prev_n:
                # Заголовок группы
                sep_d = {c: '' for c in data_df.columns}
                if n_key_data in sep_d:
                    sep_d[n_key_data] = f'▼ {current_n}'
                new_data.append(sep_d)

                sep_s = {}
                for c in status_df.columns:
                    if c.endswith('_status') or c == 'Status':
                        sep_s[c] = True
                    elif c == 'Status2':
                        sep_s[c] = 'Good'
                    else:
                        sep_s[c] = ''
                new_status.append(sep_s)

                prev_n = current_n

            new_data.append(data_df.iloc[i].to_dict())
            new_status.append(status_df.iloc[i].to_dict())

        final_data = pd.DataFrame(new_data)
        final_status = pd.DataFrame(new_status)

        # --- view_data для «Истории» ---
        view_data = build_view_data_from_archive(
            df_sorted, spc_row, psi_type=psi_type)          # ← psi_type
        n_groups = df_sorted[n_key].dropna().nunique() if n_key else 0
        n_mids = (df_sorted['Measure_ID'].nunique()
                  if 'Measure_ID' in df_sorted.columns else 0)
        view_data['MSK'] = f'История: {n_groups} номеров / {n_mids} замеров'
        view_data['Full_Msk'] = view_data['MSK']
        view_data['FileName'] = ''

        stats_df = get_archive_statistics(df_sorted, spc_map)
        round_map = get_round_dict(spc_map)

        filename = f"history_{datetime.now():%Y%m%d_%H%M%S}.pdf"
        # measure_id=0 — синтетический; view_data уже содержит всю шапку.
        with _stat_rounding_ctx(round_map):
            path = create_protocol(final_data, final_status, headers, spc_map,
                                   view_data, stats_df, 0, filename)
        open_pdf(path)
        print(f"[Archive] Протокол истории создан: {path}")
        dpg.set_value('archive_status_text',
                      f'Протокол ({psi_type}): {os.path.basename(path)}')

    except Exception as e:
        print(f"[Archive] Ошибка печати истории: {e}")
        traceback.print_exc()
        dpg.set_value('archive_status_text', f'Ошибка печати: {e}')

def print_history_grouped_protocol_1():
    """Один PDF: данные сгруппированы по номерам резонатора."""
    try:
        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для печати истории")
            dpg.set_value('archive_status_text', 'Нет данных для печати')
            return

        spc_name = dpg.get_value('archive_spc_combo') or ''
        if 'Spc' in df.columns:
            uniq = df['Spc'].dropna().unique()
            if len(uniq) >= 1 and uniq[0]:
                spc_name = uniq[0]
        if not spc_name:
            print("[Archive] Не определена спецификация")
            return

        spc_df = load_specification(spc_name)
        if spc_df.empty:
            print(f"[Archive] Спецификация {spc_name!r} не найдена")
            return
        spc_row = spc_df.iloc[0]
        spc_map = load_spc_map_for_archive(spc_name)
        if spc_map.empty:
            print(f"[Archive] Нет норм для {spc_name!r}")
            return

        df_sorted = _sort_by_number_and_date(df)
        n_key = _number_col(df_sorted)
        n_key_data = 'Numbers'  # в data_df всегда Numbers

        # Базовые таблицы
        data_df = build_archive_print_data(df_sorted, spc_map)
        status_df = build_archive_status_df(df_sorted, spc_map)
        headers = get_headers_dict(spc_map)

        # --- Обогащение data_df: Дата / Время ---
        extra = [(src, lbl) for src, lbl in
                 (('Date', 'Дата'), ('Time', 'Время'))
                 if src in df_sorted.columns]
        if extra:
            data_df = data_df.copy()
            for src, lbl in extra:
                data_df[src] = df_sorted[src].values
                headers[src] = lbl
            base = [c for c in ('Positions', 'Numbers') if c in data_df.columns]
            ext  = [src for src, _ in extra]
            tail = [c for c in ('Status', 'Status2') if c in data_df.columns]
            params = [c for c in data_df.columns
                      if c not in base + ext + tail]
            data_df = data_df[base + ext + params + tail]

        # --- Строки-разделители по номерам ---
        new_data, new_status = [], []
        prev_n = None

        for i in range(len(df_sorted)):
            current_n = ''
            if n_key:
                current_n = str(df_sorted.iloc[i].get(n_key, '') or '').strip().upper()

            if current_n and current_n != prev_n:
                # Заголовок группы
                sep_d = {c: '' for c in data_df.columns}
                if n_key_data in sep_d:
                    sep_d[n_key_data] = f'▼ {current_n}'
                new_data.append(sep_d)

                sep_s = {}
                for c in status_df.columns:
                    if c.endswith('_status') or c == 'Status':
                        sep_s[c] = True
                    elif c == 'Status2':
                        sep_s[c] = 'Good'
                    else:
                        sep_s[c] = ''
                new_status.append(sep_s)

                prev_n = current_n

            new_data.append(data_df.iloc[i].to_dict())
            new_status.append(status_df.iloc[i].to_dict())

        final_data = pd.DataFrame(new_data)
        final_status = pd.DataFrame(new_status)

        # --- view_data для «Истории» ---
        view_data = build_view_data_from_archive(df_sorted, spc_row)
        n_groups = df_sorted[n_key].dropna().nunique() if n_key else 0
        n_mids = (df_sorted['Measure_ID'].nunique()
                  if 'Measure_ID' in df_sorted.columns else 0)
        view_data['MSK'] = f'История: {n_groups} номеров / {n_mids} замеров'
        view_data['Full_Msk'] = view_data['MSK']
        view_data['FileName'] = ''

        stats_df = get_archive_statistics(df_sorted, spc_map)
        round_map = get_round_dict(spc_map)

        filename = f"history_{datetime.now():%Y%m%d_%H%M%S}.pdf"
        # measure_id=0 — синтетический; view_data уже содержит всю шапку.
        with _stat_rounding_ctx(round_map):
            path = create_protocol(final_data, final_status, headers, spc_map,
                                   view_data, stats_df, 0, filename)
        open_pdf(path)
        print(f"[Archive] Протокол истории создан: {path}")
        dpg.set_value('archive_status_text', f'Протокол: {os.path.basename(path)}')

    except Exception as e:
        print(f"[Archive] Ошибка печати истории: {e}")
        traceback.print_exc()
        dpg.set_value('archive_status_text', f'Ошибка печати: {e}')


# ------------------------------------------------------------- экспорт
def export_history_to_excel():
    """Экспорт истории в Excel: N, Дата, Время, МСК, Файл, ID + параметры."""
    try:
        from openpyxl import Workbook
        # ▼ Тип протокола и карта норм — по выбору пользователя (ПСИ / ОТК).
        from .Archive_UI import _current_psi_type, _load_spc_map_for_display

        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для экспорта истории")
            return

        spc_name = dpg.get_value('archive_spc_combo') or ''
        if 'Spc' in df.columns:
            uniq = df['Spc'].dropna().unique()
            if len(uniq) == 1 and uniq[0]:
                spc_name = uniq[0]

        psi_type = _current_psi_type()
        spc_map = (_load_spc_map_for_display(spc_name, psi_type)
                   if spc_name else pd.DataFrame())
        data_df = build_archive_print_data(df, spc_map)
        if 'Status2' in data_df.columns:
            data_df = data_df.drop(columns=['Status2'])
        headers = get_headers_dict(spc_map)

        df_r = df.reset_index(drop=True)
        data_r = data_df.reset_index(drop=True)

        extras = []
        for src, label in [
            ('N', 'N'), ('Date', 'Дата'), ('Time', 'Время'),
            ('MSK', 'МСК'), ('File', 'Файл'), ('Measure_ID', 'ID замера'),
        ]:
            if src in df_r.columns:
                extras.append((label, df_r[src].tolist()))

        filename = f"history_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        filepath = os.path.join(Options.get_measure_protokol_path(), filename)

        wb = Workbook()
        ws = wb.active
        ws.title = "History"

        # ▼ В шапку добавляем тип, чтобы при просмотре файла было видно,
        #   по каким нормам (ПСИ / ОТК) считался столбец «Статус».
        all_headers = (['Тип'] + [label for label, _ in extras]
                       + [headers.get(c, c) for c in data_r.columns])
        for j, h in enumerate(all_headers, 1):
            ws.cell(1, j, h)

        for i in range(len(df_r)):
            c = 1
            ws.cell(i + 2, c, psi_type)          # ← «ОТК» / «ПСИ»
            c += 1
            for _, vals in extras:
                v = vals[i] if i < len(vals) else ''
                if pd.isna(v):
                    v = ''
                ws.cell(i + 2, c, v)
                c += 1
            for col in data_r.columns:
                v = (data_r.iloc[i].get(col, '') if i < len(data_r) else '')
                if pd.isna(v):
                    v = ''
                ws.cell(i + 2, c, v)
                c += 1

        wb.save(filepath)
        print(f"[Archive] История сохранена в Excel ({psi_type}): {filepath}")
        dpg.set_value('archive_status_text',
                      f'Excel ({psi_type}): {os.path.basename(filepath)}')
    except Exception as e:
        print(f"[Archive] Ошибка экспорта истории: {e}")
        traceback.print_exc()

def export_history_to_excel_1():
    """Экспорт истории в Excel: N, Дата, Время, МСК, Файл, ID + параметры."""
    try:
        from openpyxl import Workbook

        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для экспорта истории")
            return

        spc_name = dpg.get_value('archive_spc_combo') or ''
        if 'Spc' in df.columns:
            uniq = df['Spc'].dropna().unique()
            if len(uniq) == 1 and uniq[0]:
                spc_name = uniq[0]

        spc_map = (load_spc_map_for_archive(spc_name)
                   if spc_name else pd.DataFrame())
        data_df = build_archive_print_data(df, spc_map)
        if 'Status2' in data_df.columns:
            data_df = data_df.drop(columns=['Status2'])
        headers = get_headers_dict(spc_map)

        df_r = df.reset_index(drop=True)
        data_r = data_df.reset_index(drop=True)

        extras = []
        for src, label in [
            ('N', 'N'), ('Date', 'Дата'), ('Time', 'Время'),
            ('MSK', 'МСК'), ('File', 'Файл'), ('Measure_ID', 'ID замера'),
        ]:
            if src in df_r.columns:
                extras.append((label, df_r[src].tolist()))

        filename = f"history_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        filepath = os.path.join(Options.get_measure_protokol_path(), filename)

        wb = Workbook()
        ws = wb.active
        ws.title = "History"

        all_headers = ([label for label, _ in extras]
                       + [headers.get(c, c) for c in data_r.columns])
        for j, h in enumerate(all_headers, 1):
            ws.cell(1, j, h)

        for i in range(len(df_r)):
            c = 1
            for _, vals in extras:
                v = vals[i] if i < len(vals) else ''
                if pd.isna(v):
                    v = ''
                ws.cell(i + 2, c, v)
                c += 1
            for col in data_r.columns:
                v = (data_r.iloc[i].get(col, '') if i < len(data_r) else '')
                if pd.isna(v):
                    v = ''
                ws.cell(i + 2, c, v)
                c += 1

        wb.save(filepath)
        print(f"[Archive] История сохранена в Excel: {filepath}")
        dpg.set_value('archive_status_text',
                      f'Excel: {os.path.basename(filepath)}')
    except Exception as e:
        print(f"[Archive] Ошибка экспорта истории: {e}")
        traceback.print_exc()