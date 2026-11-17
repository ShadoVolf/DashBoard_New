"""Управление слотами измерений: чекбоксы, combo, перерисовка таблиц."""
import dearpygui.dearpygui as dpg

import Statistik.Data
from Statistik.Operations import (
    get_measure_type,
    update_plot_seris,
    get_msk_plating_count,
    get_msk_psi_count,
    get_msk_psi_spc,
)

from .dashboard_helpers import _get_single_selected_msk
from .dashboard_results import update_result, update_msk_result, print_msk_plots


def set_slot_data(sender, data, dpg_):
    data_types = Statistik.Data.Data.get_measure_type_list()
    active_slot_list = Statistik.Data.Data.get_active_data()
    for index, row in active_slot_list.iterrows():
        if str(sender).count(str(row['Name'])):
            temp = data_types[data_types['Name'] == data]
            active_slot_list.loc[
                active_slot_list['Name'] == row['Name'], 'Value'] = int(
                temp['ID'].to_string(index=False))
    Statistik.Data.Data.set_active_data(active_slot_list)
    repaint_signal_window(None, None, dpg_)
    repaint_action_window(None, None, dpg_)


def add_del_slot(sender, data, dpg_):
    if sender == 'add_data_slot':
        df = Statistik.Data.Data.get_active_data()
        count = df['Name'].max() + 1
        data_types = get_measure_type()
        mes_names = Statistik.Data.Data.get_measure_type_list()
        unique1 = [x for x in mes_names['ID'].tolist()
                   if x not in df['Value'].tolist()]
        unique2 = [x for x in df['Value'].tolist()
                   if x not in mes_names['ID'].tolist()]
        intersect = list(filter(lambda x: x != 0, unique1 + unique2))
        if intersect:
            mes_names = mes_names[mes_names['ID'] == intersect[0]]
            data_def_value = mes_names['Name'].to_string(index=False)
            data_def_index = intersect[0]
        else:
            data_def_value = mes_names[mes_names['ID'] == 6].to_string(index=False)
            data_def_index = 6
        dpg_.add_combo(data_types, parent='Select_Measure_Type',
                       tag='combo' + str(count) + "_Select",
                       default_value=data_def_value,
                       label='Данные ' + str(count),
                       callback=set_slot_data, user_data=dpg_)
        new_row = {'Name': count, 'Value': data_def_index}
        df.loc[len(df)] = new_row
        Statistik.Data.Data.set_active_data(df)
    if sender == 'del_data_slot':
        df = Statistik.Data.Data.get_active_data()
        max_index = df['Name'].idxmax()
        count = df['Name'][max_index]
        df.drop(max_index, inplace=True)
        Statistik.Data.Data.set_active_data(df)
        if dpg_.does_item_exist('combo' + str(count) + "_Select"):
            dpg_.delete_item('combo' + str(count) + "_Select")
    repaint_signal_window(None, None, dpg_)
    repaint_action_window(None, None, dpg_)
    update_slot_use_data(None, None, dpg_)


def repaint_signal_window(sender, data, dpg_):
    data_types = Statistik.Data.Data.get_measure_type_list()
    active_slot_list = Statistik.Data.Data.get_active_data()
    if dpg_.does_item_exist('signal_table'):
        dpg_.delete_item('signal_table')
    if not dpg_.does_item_exist('view_msk'):
        return
    with dpg_.table(header_row=False, tag='signal_table', parent='view_msk'):
        dpg_.add_table_column(width_fixed=True, init_width_or_weight=200)
        dpg_.add_table_column(width_fixed=True, init_width_or_weight=220)
        dpg_.add_table_column(width_fixed=True, init_width_or_weight=100)
        for index, row in active_slot_list.iterrows():
            with dpg_.table_row():
                tag_str = 'data' + str(row['Name']) + '_check_box'
                tag_str1 = 'combo' + str(row['Name']) + '_check_box'
                tag_str2 = 'text' + str(row['Name']) + '_check_box'
                data_types_temp = data_types[data_types['ID'] == row['Value']]
                dpg_.add_checkbox(
                    label=data_types_temp['Name'].to_string(index=False),
                    default_value=False, tag=tag_str)
                dpg_.add_combo(tag=tag_str1, callback=set_id_count,
                               user_data=dpg_,
                               default_value=data_types.loc[5, 'Name'])
                dpg_.add_text("0 шт.", tag=tag_str2)


def repaint_action_window(sender, data, dpg_):
    data_types = Statistik.Data.Data.get_measure_type_list()
    active_slot_list = Statistik.Data.Data.get_active_data()
    if not dpg_.does_item_exist('actions'):
        return
    if dpg_.does_item_exist('signal_all_table'):
        dpg_.delete_item('signal_all_table')
    with dpg_.table(header_row=False, tag='signal_all_table',
                    parent='actions'):
        dpg_.add_table_column(width_fixed=True, init_width_or_weight=200)
        dpg_.add_table_column(width_fixed=True, init_width_or_weight=220)
        dpg_.add_table_column(width_fixed=True, init_width_or_weight=100)
        for index, row in active_slot_list.iterrows():
            with dpg_.table_row():
                tag_str = 'data' + str(row['Name']) + '_check_box_all'
                tag_str2 = 'text' + str(row['Name']) + '_check_box_all'
                data_types_temp = data_types[data_types['ID'] == row['Value']]
                if 'Use' in active_slot_list.columns:
                    dpg_.add_checkbox(
                        label=data_types_temp['Name'].to_string(index=False),
                        default_value=bool(row['Use']), tag=tag_str,
                        callback=update_slot_use_data, user_data=dpg_)
                else:
                    dpg_.add_checkbox(
                        label=data_types_temp['Name'].to_string(index=False),
                        default_value=False, tag=tag_str,
                        callback=update_slot_use_data, user_data=dpg_)
                if 'Count' in active_slot_list.columns:
                    dpg_.add_text(str(row['Count']) + " шт.", tag=tag_str2)
                    if int(row['Count']) == 0:
                        dpg_.set_value(tag_str, False)
                        active_slot_list.loc[
                            active_slot_list['Name'] == row['Name'], 'Use'] = False
                else:
                    dpg_.add_text("0 шт.", tag=tag_str2)
                    dpg_.set_value(tag_str, False)
                    active_slot_list.loc[
                        active_slot_list['Name'] == row['Name'], 'Use'] = False
        Statistik.Data.Data.set_active_data(active_slot_list)
        update_plot_seris(dpg_)


def set_id_count(sender, data, dpg_):
    msk = _get_single_selected_msk(dpg_)
    if not msk:
        return
    data_types = Statistik.Data.Data.get_measure_type_list()
    active_slot_list = Statistik.Data.Data.get_active_data()
    measure_type = 0
    slot_name = 0
    for item in dpg_.get_all_items():
        alias = dpg_.get_item_alias(item)
        if alias == 'id_info':
            dpg_.delete_item(alias)
    for index, row in active_slot_list.iterrows():
        if str(sender).count(str(row['Name'])):
            temp = data_types[data_types['ID'] == row['Value']]
            measure_type = temp['ID'].to_string(index=False)
            slot_name = row['Name']
    if slot_name == 0:
        return
    if int(measure_type) != 6:
        count = (get_msk_plating_count(msk=msk, measure_type=measure_type)
                 if data == 'все'
                 else get_msk_plating_count(msk=msk, measure_id=data))
    else:
        if data == 'все':
            count = get_msk_psi_count(msk)
        else:
            count = get_msk_psi_count(msk, data)
            df = get_msk_psi_spc(measure_id=data)
            with dpg_.group(horizontal=True, parent='view_msk',
                            tag='id_info'):
                dpg_.add_text('Спецификация')
                dpg_.add_text(df['spc'].to_string(index=False))
                dpg_.add_text('Дата измерения')
                dpg_.add_text(df['Date'].to_string(index=False))
                dpg_.add_text('МСК')
                dpg_.add_text(df['MSK'].to_string(index=False))
    dpg_.set_value('text' + str(slot_name) + '_check_box', str(count))


def update_slot_use_data(sender, data, dpg_):
    active_slots_list = Statistik.Data.Data.get_active_data()
    for index, row in active_slots_list.iterrows():
        item_name = 'data' + str(row['Name']) + '_check_box_all'
        item_name1 = 'text' + str(row['Name']) + '_check_box_all'
        if 'Use' in active_slots_list.columns:
            if dpg_.does_item_exist(item_name):
                active_slots_list.loc[
                    active_slots_list['Name'] == row['Name'], 'Use'] = dpg_.get_value(item_name)
            if 'Count' in active_slots_list.columns and row['Use']:
                if dpg_.does_item_exist(item_name1):
                    dpg_.set_value(item_name1, str(row['Count']) + " шт.")
    Statistik.Data.Data.set_active_data(active_slots_list)
    update_plot_seris(dpg_)
    update_result(dpg_)


def without_cap_changed(sender, app_data, user_data):
    dpg_ = user_data
    Statistik.Data.Data.set_without_cap_mode(bool(app_data))
    try:
        update_result(dpg_)
    except Exception as e:
        print(f'[without_cap] update_result: {e}')
    try:
        update_msk_result(dpg_)
    except Exception as e:
        print(f'[without_cap] update_msk_result: {e}')
    try:
        if dpg_.does_item_exist('view_msk_plot'):
            print_msk_plots(dpg_)
    except Exception as e:
        print(f'[without_cap] print_msk_plots: {e}')

def clear_all_data(sender, data, dpg_):
    Statistik.Data.Data.clear_all_data()
    # clear_all_data обнуляет msk_list и data_full — пометить
    # как «требующие перезагрузки». При следующем NL-запросе
    # _reload_current_msks сразу вернётся (msk_list пуст),
    # но флаг сбросится — состояние согласовано.
    Statistik.Data.Data.dirty = True

    repaint_action_window(None, None, dpg_)
    update_slot_use_data(None, None, dpg_)
    active_slot_list = Statistik.Data.Data.get_active_data()
    for index, row in active_slot_list.iterrows():
        active_slot_list.loc[
            active_slot_list['Name'] == row['Name'], 'Use'] = False
    Statistik.Data.Data.set_active_data(active_slot_list)
    update_plot_seris(dpg_)

def clear_all_data_1(sender, data, dpg_):
    Statistik.Data.Data.clear_all_data()
    repaint_action_window(None, None, dpg_)
    update_slot_use_data(None, None, dpg_)
    active_slot_list = Statistik.Data.Data.get_active_data()
    for index, row in active_slot_list.iterrows():
        active_slot_list.loc[
            active_slot_list['Name'] == row['Name'], 'Use'] = False
    Statistik.Data.Data.set_active_data(active_slot_list)
    update_plot_seris(dpg_)