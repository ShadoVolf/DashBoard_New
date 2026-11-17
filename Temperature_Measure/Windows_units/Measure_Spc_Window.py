import locale

import pandas as pd
from tabulate import tabulate

from Temperature_Measure import _layout
from Statistik.Operations import (
    get_resonator_types, get_resonator_nominals_list, get_resonator_nom_list,
)
from Temperature_Measure.Load_Data import (
    get_resonator_type_psi, get_resonator_spc_psi, get_resonator_spc_psi_data,
    get_resonator_spc_type_nominal, get_resonator_spc_psi_type, save_map_spc,
)
from Temperature_Measure.Make_Measure import load_spc_data
from Temperature_Measure.measure_data_class import MEASURE_DATA


def add_local_spc_to_list(sender, data, dpg):
    result = str(sender).split('_')
    slot = result[2]
    spc_name = dpg.get_value('spc_' + str(slot) + 'select')
    result = get_resonator_spc_psi_data(spc_name)
    if not result.empty:
        MEASURE_DATA.add_spc_to_list(slot, result)
    spc_df = MEASURE_DATA.get_spc_sel_list(slot)
    if spc_df is not None and not spc_df.empty:
        spc_sel_list = spc_df['Name'].tolist()
        dpg.configure_item('spc_' + str(slot) + 'select',
                           items=spc_sel_list, default_value=spc_sel_list[0])
    print_spc_str(slot)


def print_spc_str(slot):
    result_all = MEASURE_DATA.get_spc_sel_list(setupnum=slot)
    data = MEASURE_DATA.get_setupnum_data(slot)
    if result_all is not None:
        if not result_all.empty:
            mask = result_all['Multy'] == 1
            result_all.loc[mask, 'Nominal'] = data['Номинал'] / 1e6
            print('Выбранные спецификации')
            selected_columns = ['Nominal', 'Profile', 'LoadType',
                                'Loadvalue', 'Name']
            print(tabulate(result_all[selected_columns],
                           headers=selected_columns, tablefmt='grid',
                           showindex=False))
    else:
        print("Спецификации отсутствуют")
    return result_all


def create_set_specification_windows(sender, dpg):
    """Создаёт окно выбора спецификаций с адаптивным размером."""
    result = str(sender).split('_')
    setupnum = result[2]
    data_row = MEASURE_DATA.get_setupnum_data(setupnum=setupnum)
    MEASURE_DATA.active_slot_number = setupnum
    r_type = get_resonator_type_psi()
    rk_types_ = get_resonator_types()
    spc_sel_df = MEASURE_DATA.get_spc_sel_list(setupnum)

    pos, size = _layout.dialog_rect(fraction_w=0.65, fraction_h=0.6,
                                    min_w=820, min_h=440,
                                    max_w=1200, max_h=800)

    with dpg.window(label="Выбор спецификаций",
                    width=size[0], height=size[1], pos=pos,
                    tag='spc_select_window'):
        dpg.add_text("Параметры измерительного файла")
        with dpg.group(height=40, horizontal=True):
            with dpg.table(
                    header_row=True,
                    borders_innerH=True,
                    borders_outerH=True,
                    borders_innerV=True,
                    borders_outerV=True,
                    resizable=True,
                    policy=dpg.mvTable_SizingFixedFit,
                    scrollY=False,
                    scrollX=False,
                    no_host_extendX=True,
                    height=40,
            ):
                dpg.add_table_column(label="Позиции", width=180)
                dpg.add_table_column(label="Номинал, Гц", width=100)
                dpg.add_table_column(label="Температуры", width=150)
                dpg.add_table_column(label="Режим измерения", width=150)
                dpg.add_table_column(label="Нагрузка. пФ", width=100)
                with dpg.table_row():
                    dpg.add_text(data_row['Position_str'])
                    dpg.add_text(data_row['Номинал'])
                    dpg.add_text(data_row['Temp'])
                    dpg.add_text(data_row['CL_Metod'])
                    dpg.add_text(data_row['CL_Value'])
            dpg.add_radio_button(('Все', 'Выбранные'),
                                 tag='radio_group_select_load',
                                 callback=radio_spc_callback, user_data=dpg)

        dpg.add_separator()
        dpg.add_text("Выбор типа резонатора")
        dpg.add_combo(r_type, user_data=dpg, callback=get_spc_callback,
                      tag='spc_resonator_type_select', default_value=r_type[0])
        dpg.add_text("Выбор спецификации")

        dpg.add_combo([], user_data=dpg, callback=get_spc_sel_callback,
                      tag='spc_resonator_select', default_value='Нет')
        get_spc_callback('', '', dpg)
        with dpg.group(horizontal=True):
            dpg.add_button(label='Добавить', tag='add_spc_button_tolist',
                           callback=add_to_spc_list, user_data=dpg)
            dpg.add_button(label='Очистить', tag='clear_spc_button_tolist',
                           user_data=dpg, callback=clear_spc_list)
        dpg.add_separator()
        dpg.add_separator()
        dpg.add_text("Выбор номенклатуры")
        dpg.add_combo(rk_types_, user_data=dpg,
                      callback=get_nominal_spc_callback,
                      tag='nom_type_resonator_select',
                      default_value=rk_types_[0], label='Тип')
        dpg.add_combo([], user_data=dpg, callback=get_nom_spc_callback,
                      tag='nom_nominal_resonator_select',
                      default_value='', label='Номинал')
        get_nominal_spc_callback('', '', dpg)
        dpg.add_combo([], user_data=dpg, callback=get_nom_callback,
                      tag='nom_resonator_select', default_value='Нет',
                      label='Номенклатура')
        get_nom_spc_callback('', '', dpg)
        dpg.add_button(label='Сохранить', tag='add_nom_button_to_spc',
                       callback=save_spc_nom_map, user_data=dpg)
        dpg.add_separator()
        dpg.add_separator()
        with dpg.table(
                header_row=True,
                borders_innerH=True,
                borders_outerH=True,
                borders_innerV=True,
                borders_outerV=True,
                resizable=True,
                policy=dpg.mvTable_SizingFixedFit,
                scrollY=False,
                scrollX=False,
                no_host_extendX=True,
                tag='spc_select_table_view',
        ):
            dpg.add_table_column(label='Номинал, Гц', width_fixed=True,
                                 init_width_or_weight=100)
            dpg.add_table_column(label="Температуры", width_fixed=True,
                                 init_width_or_weight=120)
            dpg.add_table_column(label="Режим измерения", width_fixed=True,
                                 init_width_or_weight=150)
            dpg.add_table_column(label="Нагрузка, пФ", width_fixed=True,
                                 init_width_or_weight=120)
            dpg.add_table_column(label="Спецификация", width_fixed=True,
                                 init_width_or_weight=250)
            dpg.add_table_column(label="Номенклатура", width_fixed=True,
                                 init_width_or_weight=250)
            count = 1
            if spc_sel_df is not None:
                for index, row in spc_sel_df.iterrows():
                    formatted_value = locale.format_string(
                        "%.0f", float(row['Nominal']) * 1E6, grouping=True)

                    with dpg.table_row(parent='spc_select_table_view'):
                        dpg.add_text(formatted_value)
                        dpg.add_text(row['Profile'])
                        dpg.add_text(row['LoadType'])
                        dpg.add_text(row['Loadvalue'])
                        dpg.add_text(row['Name'])
                        if row['Nom_List'] is not None and len(row['Nom_List']) > 0:
                            dpg.add_combo(
                                row['Nom_List'], user_data=dpg,
                                tag='spc_sel_nom_resonator_select_' + str(count),
                                width=250,
                                default_value=row['Nom_List'][0],
                            )
                        else:
                            dpg.add_combo(
                                [], user_data=dpg,
                                tag='spc_sel_nom_resonator_select_' + str(count),
                                width=250,
                            )
                        count = count + 1

    _layout.center_on_screen('spc_select_window')


def save_spc_nom_map(sender, data, dpg):
    spc_name = dpg.get_value('spc_resonator_select')
    nom_name = dpg.get_value('nom_resonator_select')
    save_map_spc(spc_name, nom_name)


def get_spc_sel_callback(sender, data, dpg):
    sel = dpg.get_value('radio_group_select_load')
    if sel == 'Выбранные':
        data_row = MEASURE_DATA.get_setupnum_data(
            setupnum=MEASURE_DATA.active_slot_number)
        if len(data_row['SpcName']) > 0:
            spc_name = dpg.get_value('spc_resonator_select')
            type_name = get_resonator_spc_psi_type(spc_name)
            r_type = get_resonator_type_psi()
            dpg.configure_item('spc_resonator_type_select', items=r_type,
                               default_value=type_name[0])


def get_nom_spc_callback(sender, data, dpg):
    if sender == 'nom_nominal_resonator_select_msk':
        type_select = 'nom_type_resonator_select_msk'
        nom_select = 'nom_nominal_resonator_select_msk'
        spc_data = 'nom_resonator_select_msk'
    elif sender == 'nom_nominal_resonator_select':
        type_select = 'nom_type_resonator_select'
        nom_select = 'nom_nominal_resonator_select'
        spc_data = 'nom_resonator_select'
    else:
        type_select = 'nom_type_resonator_select'
        nom_select = 'nom_nominal_resonator_select'
        spc_data = 'nom_resonator_select'

    if len(dpg.get_value(nom_select)) > 1:
        spc_list = get_resonator_nom_list(dpg.get_value(type_select),
                                          dpg.get_value(nom_select))
    else:
        spc_list = get_resonator_nom_list(dpg.get_value(type_select))

    if len(spc_list) > 0:
        dpg.configure_item(spc_data, items=spc_list,
                           default_value=spc_list[0])


def get_nom_callback(sender, data, dpg):
    sel = dpg.get_value('radio_group_select_load')
    if sel == 'Выбранные':
        data_row = MEASURE_DATA.get_setupnum_data(
            setupnum=MEASURE_DATA.active_slot_number)
        if len(data_row['Spec_list']) > 0:
            spc_name = dpg.get_value('nom_resonator_select')
            nominal, rk_type = get_resonator_spc_type_nominal(spc_name)
            rk_types_ = get_resonator_types()
            dpg.configure_item('nom_type_resonator_select', items=rk_types_,
                               default_value=rk_type)
            nom_list = get_resonator_nominals_list(
                dpg.get_value('nom_type_resonator_select'))
            dpg.configure_item('nom_nominal_resonator_select',
                               items=nom_list, default_value=nominal)


def radio_spc_callback(sender, data, dpg):
    if data == 'Выбранные':
        data_row = MEASURE_DATA.get_setupnum_data(
            setupnum=MEASURE_DATA.active_slot_number)
        if len(data_row['SpcName']) > 0:
            dpg.configure_item('spc_resonator_type_select', callback='')
            dpg.configure_item('spc_resonator_select',
                               items=data_row['SpcName'],
                               default_value=data_row['SpcName'][0])
            type_name = get_resonator_spc_psi_type(data_row['SpcName'][0])
            r_type = get_resonator_type_psi()
            dpg.configure_item('spc_resonator_type_select', items=r_type,
                               default_value=type_name[0])
        if len(data_row['Spec_list']) > 0:
            dpg.configure_item('nom_type_resonator_select', callback='')
            dpg.configure_item('nom_nominal_resonator_select', callback='')
            dpg.configure_item('nom_resonator_select',
                               items=data_row['Spec_list'],
                               default_value=data_row['Spec_list'][0])
            nominal, rk_type = get_resonator_spc_type_nominal(
                data_row['Spec_list'][0])
            rk_types_ = get_resonator_types()
            dpg.configure_item('nom_type_resonator_select', items=rk_types_,
                               default_value=rk_type)
            nom_list = get_resonator_nominals_list(
                dpg.get_value('nom_type_resonator_select'))
            dpg.configure_item('nom_nominal_resonator_select',
                               items=nom_list, default_value=nominal)
    else:
        dpg.configure_item('nom_type_resonator_select',
                           callback=get_nominal_spc_callback)
        dpg.configure_item('nom_nominal_resonator_select',
                           callback=get_nom_spc_callback)
        dpg.configure_item('spc_resonator_type_select',
                           callback=get_spc_callback)

        if dpg.get_value('spc_resonator_type_select') != 'Все':
            get_spc_callback(sender, data, dpg)
            get_nominal_spc_callback(sender, data, dpg)
            get_nom_spc_callback(sender, data, dpg)


def get_nominal_spc_callback(sender, data, dpg):
    if sender == 'nom_type_resonator_select_msk':
        type_select = 'nom_type_resonator_select_msk'
        nom_data = 'nom_nominal_resonator_select_msk'
    elif sender == 'nom_type_resonator_select':
        type_select = 'nom_type_resonator_select'
        nom_data = 'nom_nominal_resonator_select'
    else:
        type_select = 'nom_type_resonator_select'
        nom_data = 'nom_nominal_resonator_select'
    nom_list = get_resonator_nominals_list(dpg.get_value(type_select))
    if len(nom_list) > 0:
        dpg.configure_item(nom_data, items=nom_list,
                           default_value=nom_list[0])


def update_spc_select_table(dpg):
    result_all = print_spc_str(MEASURE_DATA.active_slot_number)
    if dpg.does_item_exist('spc_select_table_view'):
        dpg.delete_item('spc_select_table_view')
    with dpg.table(
            header_row=True,
            borders_innerH=True,
            borders_outerH=True,
            borders_innerV=True,
            borders_outerV=True,
            resizable=True,
            policy=dpg.mvTable_SizingFixedFit,
            scrollY=False,
            scrollX=False,
            no_host_extendX=True,
            tag='spc_select_table_view',
            parent='spc_select_window',
    ):
        dpg.add_table_column(label='Номинал, Гц', width_fixed=True,
                             init_width_or_weight=100)
        dpg.add_table_column(label="Температуры", width_fixed=True,
                             init_width_or_weight=120)
        dpg.add_table_column(label="Режим измерения", width_fixed=True,
                             init_width_or_weight=150)
        dpg.add_table_column(label="Нагрузка, пФ", width_fixed=True,
                             init_width_or_weight=120)
        dpg.add_table_column(label="Спецификация", width_fixed=True,
                             init_width_or_weight=250)
        dpg.add_table_column(label="Номенклатура", width_fixed=True,
                             init_width_or_weight=250)
        count = 1
    if result_all is not None:
        for index, row in result_all.iterrows():
            formatted_value = locale.format_string(
                "%.0f", float(row['Nominal']) * 1E6, grouping=True)

            with dpg.table_row(parent='spc_select_table_view'):
                dpg.add_text(formatted_value)
                dpg.add_text(row['Profile'])
                dpg.add_text(row['LoadType'])
                dpg.add_text(row['Loadvalue'])
                dpg.add_text(row['Name'])
                if row['Nom_List'] is not None and len(row['Nom_List']) > 0:
                    dpg.add_combo(
                        row['Nom_List'], user_data=dpg,
                        tag='spc_sel_nom_resonator_select_' + str(count),
                        width=250, default_value=row['Nom_List'][0],
                    )
                else:
                    dpg.add_combo(
                        [], user_data=dpg,
                        tag='spc_sel_nom_resonator_select_' + str(count),
                        width=250,
                    )
                count = count + 1


def add_to_spc_list(sender, data, dpg):
    spc_name = dpg.get_value('spc_resonator_select')
    slot = MEASURE_DATA.active_slot_number
    result = get_resonator_spc_psi_data(spc_name)
    if not result.empty:
        MEASURE_DATA.add_spc_to_list(MEASURE_DATA.active_slot_number, result)
        update_spc_select_table(dpg)
    spc_df = MEASURE_DATA.get_spc_sel_list(slot)
    if not spc_df.empty:
        spc_sel_list = spc_df['Name'].tolist()
        dpg.configure_item('spc_' + str(slot) + 'select',
                           items=spc_sel_list, default_value=spc_sel_list[0])


def get_spc_callback(sender, data, dpg):
    spc_list = get_resonator_spc_psi(
        dpg.get_value('spc_resonator_type_select'))
    if len(spc_list) > 0:
        dpg.configure_item('spc_resonator_select', items=spc_list,
                           default_value=spc_list[0])


def clear_spc_list(sender, data, dpg):
    slot = MEASURE_DATA.active_slot_number
    MEASURE_DATA.delete_spc_slot(slot)
    dpg.configure_item('spc_' + str(slot) + 'select', items=[],
                       default_value='Нет')
    update_spc_select_table(dpg)