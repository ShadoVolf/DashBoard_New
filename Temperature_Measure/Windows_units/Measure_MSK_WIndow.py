from tabulate import tabulate

from Temperature_Measure import _layout
from Statistik.Operations import get_resonator_types, get_msk
from Temperature_Measure.Load_Data import (
    get_resonator_spc_psi_data, check_serial_numbers, test_spcecification,
    test_nominal_freq, get_msk_by_id, get_msk_inf, get_msk_id_by_name,
    get_msk_suffix_list, clean_MSK, manage_suffix, save_map_spc, get_msk_nom)
from Temperature_Measure.Windows_units import Measure_Number_Window
from Temperature_Measure.Windows_units.Measure_Spc_Window import (
    get_nominal_spc_callback, get_nom_spc_callback)
from Temperature_Measure.measure_data_class import MEASURE_DATA


def create_set_msk_windows(sender, dpg):
    result = str(sender).split('_')
    setupnum = result[2]
    MEASURE_DATA.active_slot_number = setupnum
    rq_types = get_resonator_types()

    for tag in ('select_msk_view_table', 'msk_table_group',
                'msk_table_numbers_pop', 'select_msk_view_table_spc_list_pop',
                'clear_spc_msk_view_table_pop', 'suffix_add'):
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

    pos, size = _layout.dialog_rect(fraction_w=0.55, fraction_h=0.45,
                                    min_w=700, min_h=380,
                                    max_w=1000, max_h=650)

    with dpg.window(label="Выбор МСК", width=size[0], height=size[1],
                    pos=pos, tag='msk_select_window'):
        dpg.add_text("Выбор МСК")
        with dpg.group(height=40, horizontal=False):
            dpg.add_combo(rq_types, user_data=dpg,
                          callback=get_nominal_spc_callback,
                          tag='nom_type_resonator_select_msk',
                          label='Тип', default_value=rq_types[0])
            dpg.add_combo([], user_data=dpg, callback=get_nom_spc_callback,
                          tag='nom_nominal_resonator_select_msk',
                          label='Номинал')
            dpg.add_combo([], user_data=dpg, callback=get_msk_list_callback,
                          tag='nom_resonator_select_msk',
                          default_value='Нет', label='Номенклатура')
            dpg.add_combo([], user_data=dpg, callback=get_msk_info,
                          tag='msk_resonator_select_msk',
                          default_value='Нет', label='МСК')
        dpg.add_separator()
        dpg.add_separator()
        with dpg.group(height=40, horizontal=True):
            with dpg.group(height=40, width=150, horizontal=False):
                dpg.add_text("Штрих код МСК")
                dpg.add_input_text(tag='bar_code_text', decimal=True,
                                   width=150, callback=bar_code_callback,
                                   user_data=dpg)
            with dpg.group(height=40, width=150, horizontal=False):
                dpg.add_text("МСК")
                dpg.add_input_text(tag='msk_name_text', width=150,
                                   callback=bar_code_callback, user_data=dpg)
            with dpg.group(height=40, width=150, horizontal=False):
                dpg.add_text("Авто_Суффикс")
                dpg.add_text('---', tag='msk_auto_sufix_text')
            with dpg.group(height=40, width=150, horizontal=False):
                dpg.add_text("Суффикс МСК")
                dpg.add_combo(get_msk_suffix_list(), user_data=dpg,
                              tag='suffix_msk', default_value='Нет', width=150)
                with dpg.popup('suffix_msk', min_size=[80, 30]):
                    dpg.add_selectable(label="добавить",
                                       callback=show_msk_sufix_input_window,
                                       user_data=dpg, tag='suffix_add')

        dpg.add_separator()
        dpg.add_separator()
        with dpg.group(height=40, width=250, horizontal=True):
            dpg.add_text("Контроль номинальной частоты")
            dpg.add_text("Нет", tag='nominal_control_text',
                         color=[255, 0, 0])
        with dpg.group(height=40, width=250, horizontal=True):
            dpg.add_text("Контроль заданных спецификаций")
            dpg.add_text("Нет", tag='spc_control_text', color=[255, 0, 0])
        with dpg.group(height=40, width=250, horizontal=True):
            dpg.add_text("Контроль заданных номеров")
            dpg.add_text("Нет", tag='numbers_control_text', color=[255, 0, 0])
        dpg.add_separator()
        dpg.add_separator()
        dpg.add_button(label='Сохранить', user_data=dpg, callback=test_msk_data)
        dpg.add_separator()
        dpg.add_separator()
        with dpg.group(height=40, horizontal=True, tag='msk_table_group'):
            with dpg.table(
                    header_row=True, borders_innerH=True,
                    borders_outerH=True, borders_innerV=True,
                    borders_outerV=True, resizable=True,
                    policy=dpg.mvTable_SizingFixedFit,
                    scrollY=False, scrollX=False,
                    no_host_extendX=True, height=40,
                    tag='select_msk_view_table'):
                dpg.add_table_column(label="Номинал, Гц", width_fixed=True,
                                     init_width_or_weight=120)
                dpg.add_table_column(label="Нагрузка", width_fixed=True,
                                     init_width_or_weight=70)
                dpg.add_table_column(label="Количество", width_fixed=True,
                                     init_width_or_weight=110)
                dpg.add_table_column(label="Номера", width_fixed=True,
                                     init_width_or_weight=150)
                dpg.add_table_column(label="Доступные спецификации",
                                     width_fixed=True,
                                     init_width_or_weight=250)
                msk = MEASURE_DATA.get_msk(setupnum)
                msk = clean_MSK(msk)
                if msk is not None:
                    msk_id = get_msk_id_by_name(msk)
                    dpg.configure_item('bar_code_text', default_value=msk_id)
                    bar_code_callback('', msk_id, dpg)
                    test_msk(dpg)


def rebuild_msk_table(data, dpg):
    nominal, load_value, count, numbers, spc_list, msk_sufix = get_msk_inf(data)
    if msk_sufix is not None:
        dpg.configure_item('msk_auto_sufix_text', default_value=msk_sufix)
    else:
        dpg.configure_item('msk_auto_sufix_text', default_value='---')

    for tag in ('select_msk_view_table', 'msk_table_group',
                'msk_table_numbers_pop', 'select_msk_view_table_spc_list_pop',
                'clear_spc_msk_view_table_pop'):
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

    with dpg.group(height=40, horizontal=True, tag='msk_table_group',
                   parent='msk_select_window'):
        with dpg.table(
                header_row=True, borders_innerH=True,
                borders_outerH=True, borders_innerV=True,
                borders_outerV=True, resizable=True,
                policy=dpg.mvTable_SizingFixedFit,
                scrollY=False, scrollX=False,
                no_host_extendX=True, height=40,
                tag='select_msk_view_table'):
            dpg.add_table_column(label="Номинал, Гц", width_fixed=True,
                                 init_width_or_weight=120)
            dpg.add_table_column(label="Нагрузка", width_fixed=True,
                                 init_width_or_weight=70)
            dpg.add_table_column(label="Количество", width_fixed=True,
                                 init_width_or_weight=110)
            dpg.add_table_column(label="Номера", width_fixed=True,
                                 init_width_or_weight=150)
            dpg.add_table_column(label="Доступные спецификации",
                                 width_fixed=True,
                                 init_width_or_weight=250)
            with dpg.table_row(parent='select_msk_view_table'):
                dpg.add_text(nominal)
                dpg.add_text(load_value)
                dpg.add_text(count)
                dpg.add_text(numbers, tag='msk_table_numbers')
                with dpg.popup('msk_table_numbers', min_size=[80, 30]):
                    dpg.add_selectable(label="Задать",
                                       callback=Measure_Number_Window.add_numbers_by_msk_auto,
                                       user_data=dpg,
                                       tag='msk_table_numbers_pop')
                dpg.add_combo(spc_list, user_data=dpg,
                              tag='select_msk_view_table_spc_list', width=250)
                with dpg.popup('select_msk_view_table_spc_list',
                               min_size=[80, 30]):
                    dpg.add_selectable(label="Добавить",
                                       callback=add_spc_by_msk_auto,
                                       user_data=dpg,
                                       tag='select_msk_view_table_spc_list_pop')
                    dpg.add_selectable(label="Очистить",
                                       callback=clear_spc_list, user_data=dpg,
                                       tag='clear_spc_msk_view_table_pop')
                if len(spc_list) > 0:
                    dpg.configure_item('select_msk_view_table_spc_list',
                                       default_value=spc_list[0])


def get_msk_list_callback(sender, data, dpg):
    ms_list = get_msk(dpg.get_value(sender))
    if not ms_list.empty:
        msk_list = ms_list['мскРеал'].to_list()
        dpg.configure_item('msk_resonator_select_msk', items=msk_list,
                           default_value=msk_list[0])


def bar_code_callback(sender, data, dpg):
    code = True
    if sender == 'msk_name_text':
        code = False
    msk, spc_nom, nominal, type_rq = get_msk_by_id(data, code)
    dpg.configure_item('nom_type_resonator_select_msk', default_value=type_rq)
    dpg.configure_item('nom_nominal_resonator_select_msk',
                       default_value=nominal)
    dpg.configure_item('nom_resonator_select_msk', default_value=spc_nom)
    dpg.configure_item('msk_resonator_select_msk', default_value=msk)
    if msk is not None:
        get_msk_info(sender, msk, dpg)


def get_msk_info(sender, data, dpg):
    rebuild_msk_table(data, dpg)


def test_msk(dpg):
    msk_str = dpg.get_value('msk_resonator_select_msk')
    slot = MEASURE_DATA.active_slot_number
    test_nom_status = test_nominal_freq(msk_str, slot)
    if test_nom_status == 'OK':
        dpg.configure_item('nominal_control_text', default_value=test_nom_status,
                           color=[0, 128, 0])
    elif test_nom_status == 'Не полное соответствие':
        dpg.configure_item('nominal_control_text', default_value=test_nom_status,
                           color=[255, 255, 0])
    else:
        dpg.configure_item('nominal_control_text', default_value=test_nom_status,
                           color=[255, 0, 0])

    test_spc_status = test_spcecification(slot=slot)
    if test_spc_status == 'OK':
        dpg.configure_item('spc_control_text', default_value=test_spc_status,
                           color=[0, 128, 0])
    elif test_spc_status == 'OK (Интервал избыточен)':
        dpg.configure_item('spc_control_text', default_value=test_spc_status,
                           color=[255, 255, 0])
    else:
        dpg.configure_item('spc_control_text', default_value=test_spc_status,
                           color=[255, 0, 0])

    test_numbers_status, result_df_num = check_serial_numbers(slot, msk_str)
    if test_numbers_status == 'OK':
        dpg.configure_item('numbers_control_text',
                           default_value=test_numbers_status, color=[0, 128, 0])
    else:
        dpg.configure_item('numbers_control_text',
                           default_value=test_numbers_status, color=[255, 0, 0])
        print("\nНесоответствующие позиции:")
        print(tabulate(result_df_num, headers='keys', tablefmt='grid',
                       showindex=False))


def test_msk_data(sender, data, dpg):
    msk_str = dpg.get_value('msk_resonator_select_msk')
    msk_suffix = dpg.get_value('suffix_msk')
    msk_str_text = msk_str
    if msk_suffix != 'Нет':
        msk_str_text = msk_str + "_" + msk_suffix
    msk_auto_sufix = dpg.get_value('msk_auto_sufix_text')
    if msk_auto_sufix != '---':
        msk_str_text = msk_str_text + "_(" + msk_auto_sufix + ")"
    slot = MEASURE_DATA.active_slot_number

    spc_list = MEASURE_DATA.get_spc_sel_list(slot)
    if spc_list is not None and len(spc_list) > 0:
        nom = get_msk_nom(msk_str)
        for index, row in spc_list.iterrows():
            save_map_spc(row['Name'], nom)

    test_msk(dpg)
    MEASURE_DATA.add_msk(slot, msk_str_text)
    dpg.configure_item('msk_' + str(slot) + '_select', label=msk_str_text)
    dpg.delete_item('msk_select_window')


def add_spc_by_msk_auto(sender, data, dpg):
    spc_name = dpg.get_value('select_msk_view_table_spc_list')
    if len(spc_name) > 5:
        slot = MEASURE_DATA.active_slot_number
        result = get_resonator_spc_psi_data(spc_name)
        if not result.empty:
            MEASURE_DATA.add_spc_to_list(slot, result)
        spc_df = MEASURE_DATA.get_spc_sel_list(slot)
        if not spc_df.empty:
            spc_sel_list = spc_df['Name'].tolist()
            dpg.configure_item('spc_' + str(slot) + 'select',
                               items=spc_sel_list, default_value=spc_sel_list[0])


def clear_spc_list(sender, data, dpg):
    slot = MEASURE_DATA.active_slot_number
    MEASURE_DATA.delete_spc_slot(slot)
    dpg.configure_item('spc_' + str(slot) + 'select', items=[],
                       default_value='Нет')


def show_msk_sufix_input_window(sender, data, dpg):
    pos, size = _layout.dialog_rect(fraction_w=0.18, fraction_h=0.12,
                                    min_w=280, min_h=140,
                                    max_w=380, max_h=190)
    with dpg.window(label="Добавить новый суффикс",
                    width=size[0], height=size[1], pos=pos,
                    tag='msk_suffix_add_window'):
        dpg.add_input_text(hint="Пример: ВП_ПСИ", decimal=False,
                           callback=add_suffix, tag="msk_sufix_input_text",
                           user_data=dpg, on_enter=True)
        dpg.add_button(label="Сохранить", callback=add_suffix, user_data=dpg)


def add_suffix(sender, data, dpg):
    data = dpg.get_value('msk_sufix_input_text')
    result = manage_suffix(data)
    dpg.configure_item('suffix_msk', items=result)
    dpg.delete_item('msk_suffix_add_window')