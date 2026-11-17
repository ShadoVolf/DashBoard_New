"""Экспорт выборки в Excel."""
import os
import traceback
from datetime import datetime

import pandas as pd
import dearpygui.dearpygui as dpg

import Options
from .Archive_Constants import WINDOW_TAG
from .Archive_Data import (
    load_spc_map_for_archive, build_archive_print_data, get_headers_dict,
)
from .Archive_Helpers import _current_psi_type, _load_spc_map_for_display

def export_archive_to_excel():
    try:
        from openpyxl import Workbook
        # ▼ Тип протокола и карта норм — по выбору пользователя (ПСИ / ОТК).
        #   Для ОТК _load_spc_map_for_display подменяет Max/Min на
        #   Max_otk/Min_otk, поэтому в Excel попадают те же нормы,
        #   что уйдут в PDF, и статусы пересчитываются accordingly.
        from .Archive_UI import _current_psi_type, _load_spc_map_for_display

        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для экспорта")
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

        filename = f"archive_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        filepath = os.path.join(Options.get_measure_protokol_path(), filename)

        wb = Workbook()
        ws = wb.active
        ws.title = "Data"
        row0 = df.iloc[0]
        ws.cell(1, 1, f"MSK {row0.get('MSK', '')}")
        ws.cell(1, 2, f"Spc {row0.get('Spc', '')}")
        ws.cell(1, 3, f"File {row0.get('File', '')}")
        ws.cell(1, 4, f"Тип {psi_type}")          # ← тип в шапке листа

        for j, col in enumerate(data_df.columns, 1):
            ws.cell(2, j, headers.get(col, col))

        for i, (_, r) in enumerate(data_df.iterrows(), 3):
            for j, col in enumerate(data_df.columns, 1):
                val = r.get(col, '')
                if pd.isna(val):
                    val = ''
                ws.cell(i, j, val)

        wb.save(filepath)
        print(f"[Archive] Excel сохранён ({psi_type}): {filepath}")
        dpg.set_value('archive_status_text',
                      f'Excel ({psi_type}): {os.path.basename(filepath)}')
    except Exception as e:
        print(f"[Archive] Ошибка экспорта в Excel: {e}")
        traceback.print_exc()

def export_archive_to_excel_1():
    try:
        from openpyxl import Workbook

        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            print("[Archive] Нет данных для экспорта")
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

        filename = f"archive_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        filepath = os.path.join(Options.get_measure_protokol_path(), filename)

        wb = Workbook()
        ws = wb.active
        ws.title = "Data"
        row0 = df.iloc[0]
        ws.cell(1, 1, f"MSK {row0.get('MSK', '')}")
        ws.cell(1, 2, f"Spc {row0.get('Spc', '')}")
        ws.cell(1, 3, f"File {row0.get('File', '')}")

        for j, col in enumerate(data_df.columns, 1):
            ws.cell(2, j, headers.get(col, col))

        for i, (_, r) in enumerate(data_df.iterrows(), 3):
            for j, col in enumerate(data_df.columns, 1):
                val = r.get(col, '')
                if pd.isna(val):
                    val = ''
                ws.cell(i, j, val)

        wb.save(filepath)
        print(f"[Archive] Excel сохранён: {filepath}")
    except Exception as e:
        print(f"[Archive] Ошибка экспорта в Excel: {e}")
        traceback.print_exc()