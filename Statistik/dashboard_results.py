"""Сводные таблицы результатов, KDE-графики по МСК, экспорт в Excel."""
from datetime import datetime

import numpy as np
import pandas as pd
import dearpygui.dearpygui as dpg
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, Border, Side

import Statistik.Data
from Statistik.Operations import get_pdf
from Statistik.Operations import add_to_plot
from Statistik.Operations import add_to_plot_msk

from .dashboard_norms import update_spc_norm


def update_result(dpg_):
    if not dpg_.does_item_exist('measure_select'):
        return
    msk_list = Statistik.Data.Data.get_msk_list()
    active_slot_list = Statistik.Data.Data.get_active_data()
    measure_type_list = Statistik.Data.Data.get_measure_type_list()
    measure_field = dpg_.get_value('measure_select')
    clear_dat = (dpg_.get_value('clear_check')
                 if dpg_.does_item_exist('clear_check') else False)

    parent = ('result_table_header'
              if dpg_.does_item_exist('result_table_header')
              else 'result_window')

    if dpg_.does_item_exist('result_table'):
        dpg_.delete_item('result_table')

    with dpg_.table(header_row=True, row_background=True,
                    borders_innerH=True, borders_outerH=True,
                    borders_innerV=True, borders_outerV=True,
                    user_data=dpg_, tag='result_table', parent=parent):
        dpg_.add_table_column(label='##', width_fixed=True,
                              init_width_or_weight=30)
        dpg_.add_table_column(label='Замер')
        dpg_.add_table_column(label='Макс', tag='Max',
                              width_fixed=True, init_width_or_weight=60)
        dpg_.add_table_column(label='Мин', tag='Min',
                              width_fixed=True, init_width_or_weight=60)
        dpg_.add_table_column(label='Среднее', tag='Mean',
                              width_fixed=True, init_width_or_weight=60)
        dpg_.add_table_column(label='Медиана', tag='Median',
                              width_fixed=True, init_width_or_weight=60)
        dpg_.add_table_column(label='СКО', tag='StDev',
                              width_fixed=True, init_width_or_weight=60)
        dpg_.add_table_column(label='Нижняя граница', tag='Lower_bound',
                              width_fixed=True, init_width_or_weight=90)
        dpg_.add_table_column(label='Верхняя граница', tag='Upper_bound',
                              width_fixed=True, init_width_or_weight=110)
        dpg_.add_table_column(label='Количество аномальных',
                              tag='Anomal_count')
        dpg_.add_table_column(label='Выше (ниже) нормы', tag='bad_count')
        dpg_.add_table_column(label='Всего', tag='Count',
                              width_fixed=True, init_width_or_weight=60)
        dpg_.add_table_column(label='Выход годных', tag='out')

    if msk_list and 'Use' in active_slot_list.columns:
        count = 1
        for index, row in active_slot_list.iterrows():
            item_name = 'data' + str(row['Name']) + '_check_box_all'
            if dpg_.does_item_exist(item_name):
                dpg_.set_value(item_name, row['Use'])
            if row['Use']:
                pdf, x, stat = get_pdf(row['Name'], measure_field, clear_dat)
                mes_type_current = measure_type_list[
                    measure_type_list['ID'] == row['Value']]
                if dpg_.does_item_exist('y_axis'):
                    add_to_plot(dpg_, x, pdf, row['Name'])
                with dpg_.table_row(parent='result_table'):
                    dpg_.add_text(str(count))
                    count += 1
                    dpg_.add_text(
                        mes_type_current['Name'].to_string(index=False))
                    for key in stat.keys():
                        dpg_.add_text(f"{stat[key]:.2f}")


def update_msk_result(dpg_):
    if not dpg_.does_item_exist('result_msk_table'):
        return
    if not dpg_.does_item_exist('data_slot_select'):
        return
    if not dpg_.does_item_exist('measure_select'):
        return
    mes_type = dpg_.get_value('data_slot_select')
    mes_list = Statistik.Data.Data.get_measure_type_list()
    active_slot_list = Statistik.Data.Data.get_active_data()
    mes_type_id = mes_list.loc[mes_list['Name'] == mes_type]
    clear_dat = (dpg_.get_value('clear_check')
                 if dpg_.does_item_exist('clear_check') else False)
    dpg_.delete_item('result_msk_table')
    with dpg_.table(header_row=True, row_background=True,
                    borders_innerH=True, borders_outerH=True,
                    borders_innerV=True, borders_outerV=True,
                    user_data=dpg_, tag='result_msk_table',
                    parent='result_msk_window'):
        dpg_.add_table_column(label='N', width_fixed=True,
                              init_width_or_weight=30)
        dpg_.add_table_column(label='МСК')
        dpg_.add_table_column(label='Макс', width_fixed=True,
                              init_width_or_weight=60)
        dpg_.add_table_column(label='Мин', width_fixed=True,
                              init_width_or_weight=60)
        dpg_.add_table_column(label='Среднее', width_fixed=True,
                              init_width_or_weight=60)
        dpg_.add_table_column(label='Медиана', width_fixed=True,
                              init_width_or_weight=60)
        dpg_.add_table_column(label='СКО', width_fixed=True,
                              init_width_or_weight=60)
        dpg_.add_table_column(label='Нижняя граница', width_fixed=True,
                              init_width_or_weight=90)
        dpg_.add_table_column(label='Верхняя граница', width_fixed=True,
                              init_width_or_weight=110)
        dpg_.add_table_column(label='Количество аномальных')
        dpg_.add_table_column(label='Выше (ниже) нормы')
        dpg_.add_table_column(label='Всего', width_fixed=True,
                              init_width_or_weight=60)
        dpg_.add_table_column(label='Выход годных')
    if len(mes_type_id) > 0:
        slot_data = active_slot_list[
            active_slot_list['Value'] == int(mes_type_id['ID'].to_string(index=False))]
        slot = slot_data['Name'].to_string(index=False)
        msk_list = Statistik.Data.Data.get_msk_list()
        count = 1
        for key, values in msk_list.items():
            pdf, x, stat = get_pdf(int(slot),
                                   dpg_.get_value('measure_select'),
                                   clear_dat, key)
            with dpg_.table_row(parent='result_msk_table'):
                dpg_.add_text(str(count))
                count += 1
                dpg_.add_text(key)
                for k in stat.keys():
                    dpg_.add_text(f"{stat[k]:.2f}")


def print_msk_plots(dpg_):
    if not dpg_.does_item_exist('data_slot_select'):
        return
    if not dpg_.does_item_exist('measure_select'):
        return
    mes_type = dpg_.get_value('data_slot_select')
    mes_list = Statistik.Data.Data.get_measure_type_list()
    active_slot_list = Statistik.Data.Data.get_active_data()
    mes_type_id = mes_list.loc[mes_list['Name'] == mes_type]
    if len(mes_type_id) == 0:
        return
    slot_data = active_slot_list[
        active_slot_list['Value'] == int(mes_type_id['ID'].to_string(index=False))]
    slot = slot_data['Name'].to_string(index=False)
    msk_list = Statistik.Data.Data.get_msk_list()
    clear_dat = (dpg_.get_value('clear_check')
                 if dpg_.does_item_exist('clear_check') else False)
    for key, values in msk_list.items():
        pdf, x, stat = get_pdf(int(slot),
                               dpg_.get_value('measure_select'),
                               clear_dat, key)
        add_to_plot_msk(dpg_, x, pdf, slot, key)


def mes_select(sender, data, dpg_):
    if dpg_.does_item_exist('spc_select'):
        update_spc_norm(dpg_)
    if dpg_.does_item_exist('measure_select'):
        update_result(dpg_)
        update_msk_result(dpg_)
    if dpg_.does_item_exist('view_msk_plot'):
        print_msk_plots(dpg_)


def export_xls(sender, data, dpg_):
    if not dpg_.does_item_exist('measure_select'):
        return
    msk_list = Statistik.Data.Data.get_msk_list()
    active_slot_list = Statistik.Data.Data.get_active_data()
    measure_type_list = Statistik.Data.Data.get_measure_type_list()
    measure_field = dpg_.get_value('measure_select')
    clear_dat = (dpg_.get_value('clear_check')
                 if dpg_.does_item_exist('clear_check') else False)
    wb = Workbook()
    ws = wb.active
    header_font = Font(bold=True, size=12)
    cell_alignment = Alignment(horizontal='center', vertical='center')
    border = Border(left=Side(style='thin'), right=Side(style='thin'),
                    top=Side(style='thin'), bottom=Side(style='thin'))
    if msk_list and 'Use' in active_slot_list.columns:
        count = 1
        formatted_data = [[
            'N', 'Параметр', 'Тип измерений', 'Max', 'Min', 'Mean',
            'Median', 'StDev', 'Верхняя граница', 'Нижняя граница',
            'Количество аномальных', 'Брак', 'Выход годных', 'Количество',
        ]]
        formatted_data_msk = [
            'N', 'Параметр', 'Тип измерений', 'MSK', 'Max', 'Min', 'Mean',
            'Median', 'StDev', 'Верхняя граница', 'Нижняя граница',
            'Количество аномальных', 'Брак', 'Выход годных', 'Количество',
        ]
        for index, row in active_slot_list.iterrows():
            mes_type_current = measure_type_list[
                measure_type_list['ID'] == row['Value']]
            if not row['Use']:
                continue
            pdf, x, stat = get_pdf(row['Name'], measure_field, clear_dat)
            formatted_data.append([
                str(count), measure_field,
                mes_type_current['Name'].to_string(index=False),
                f"{stat['Max']:.2f}", f"{stat['Min']:.2f}",
                f"{stat['Mean']:.2f}", f"{stat['Median']:.2f}",
                f"{stat['StDev']:.2f}", f"{stat['Upper_bound']:.2f}",
                f"{stat['Lower_bound']:.2f}", f"{stat['Anomal_count']:.2f}",
                f"{stat['Bad_Count']:.2f}", f"{stat['Out']:.2f}",
                f"{stat['Count']:.2f}",
            ])
            formatted_data.append([])
            formatted_data.append([])
            formatted_data.append(formatted_data_msk)
            count1 = 1
            for key in msk_list.keys():
                pdf, x, stat = get_pdf(row['Name'], measure_field,
                                       clear_dat, key)
                formatted_data.append([
                    str(count1), measure_field,
                    mes_type_current['Name'].to_string(index=False), key,
                    f"{stat['Max']:.2f}", f"{stat['Min']:.2f}",
                    f"{stat['Mean']:.2f}", f"{stat['Median']:.2f}",
                    f"{stat['StDev']:.2f}", f"{stat['Upper_bound']:.2f}",
                    f"{stat['Lower_bound']:.2f}", f"{stat['Anomal_count']:.2f}",
                    f"{stat['Bad_Count']:.2f}", f"{stat['Out']:.2f}",
                    f"{stat['Count']:.2f}",
                ])
                count1 += 1
            count += 1
        for row_apend in formatted_data:
            ws.append(row_apend)
        for cell in ws[1]:
            cell.font = header_font
            cell.alignment = cell_alignment
            cell.border = border
        formatted_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        wb.save(formatted_time + '.xlsx')