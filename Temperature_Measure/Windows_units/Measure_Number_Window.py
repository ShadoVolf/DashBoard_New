from Temperature_Measure import _layout
from Temperature_Measure import Control_RK
from Temperature_Measure.Control_RK import test_control_numbers_dataframe
from Temperature_Measure.Load_Data import (
    load_numbers_list, set_numbers_auto_msk, test_numbers_dataframe,
    add_numbers_by_msk, process_batch_data, fill_numbers,
    add_sn_letters_to_numbers,
)
from Temperature_Measure.measure_data_class import MEASURE_DATA


def print_key_code(sender, app_data, user_data):
    print("Key pressed:", app_data)
    if app_data == 655:
        print('Sender', sender)
        print('Focus', user_data.get_focused_item())


def create_set_numbers_windows(sender, dpg):
    """Создаёт окно задания номеров с адаптивным размером."""
    result = str(sender).split('_')
    setupnum = result[2]
    MEASURE_DATA.active_slot_number = setupnum
    df_sorted = load_numbers_list(MEASURE_DATA.active_slot_number)
    pos_list = df_sorted['Positions'].to_list()
    MEASURE_DATA.current_focus = None

    if dpg.does_item_exist('Number_handler'):
        dpg.delete_item('Number_handler')
    with dpg.handler_registry(tag='Number_handler'):
        dpg.add_key_press_handler(callback=lambda: handle_enter(dpg), key=525)
        dpg.add_key_press_handler(key=627, callback=lambda: handle_enter(dpg))
        dpg.add_key_press_handler(key=516, callback=lambda: handle_enter(dpg))
        dpg.add_key_press_handler(key=515,
                                  callback=lambda: handle_arrow_up(dpg))

    pos, size = _layout.dialog_rect(fraction_w=0.32, fraction_h=0.82,
                                    min_w=420, min_h=600,
                                    max_w=560, max_h=1050)

    with dpg.window(label="Выбор номеров", width=size[0], height=size[1],
                    pos=pos, tag='numbers_select_window'):
        dpg.add_text("Установка номеров", tag='text_item')
        with dpg.group(parent="numbers_select_window", horizontal=True):
            dpg.add_combo(pos_list, user_data=dpg, default_value=pos_list[0],
                          tag='first_num_select', width=70, label='Начало')
            dpg.add_combo(pos_list, user_data=dpg, default_value=pos_list[-1],
                          tag='end_num_select', width=70, label='Конец')
            dpg.add_input_text(label='Номер', width=80,
                               tag='first_number_text', on_enter=True,
                               callback=add_ser_numbers_callback,
                               user_data=dpg)
            dpg.add_button(label='<<<', width=40,
                           callback=add_ser_numbers_callback, user_data=dpg)
        dpg.add_separator()
        dpg.add_separator()
        with dpg.group(parent="numbers_select_window", horizontal=True):
            dpg.add_input_text(label='Серия', width=80,
                               tag='serial_n_add_text', user_data=dpg,
                               on_enter=True, callback=add_serial_n_callback)
            dpg.add_button(label='<<<', width=40,
                           callback=add_serial_n_callback, user_data=dpg)
        dpg.add_separator()
        dpg.add_separator()
        dpg.add_text("Добавление номеров с предыдущего замера")
        with dpg.group(parent="numbers_select_window", horizontal=True):
            dpg.add_input_text(label='Идентификатор/МСК', width=150,
                               tag='measure_id_str', user_data=dpg,
                               on_enter=True,
                               callback=add_numbers_by_measure_id_callback)
            dpg.add_button(label='<<<', width=40, user_data=dpg,
                           callback=add_numbers_by_measure_id_callback)
        dpg.add_separator()
        dpg.add_separator()
        dpg.add_text("Добавление номеров с МСК")
        with dpg.group(parent="numbers_select_window", horizontal=True):
            dpg.add_input_text(label='МСК', width=150, tag='add_msk_id_str',
                               user_data=dpg, on_enter=True,
                               callback=add_numbers_by_msk_marker)
            dpg.add_button(label='<<<', width=40,
                           callback=add_numbers_by_msk_marker, user_data=dpg)
        dpg.add_separator()
        dpg.add_separator()
        with dpg.group(parent="numbers_select_window", horizontal=True):
            dpg.add_button(label='Сохранить', user_data=dpg,
                           callback=save_numbers_callback)
            dpg.add_button(label='Очистить', user_data=dpg,
                           callback=clear_numbers_callback)
        dpg.add_separator()
        dpg.add_separator()
        msk = dpg.get_item_label('msk_' + str(setupnum) + '_select')
        if msk == 'K.O.':
            rebuild_table_control(dpg)
        else:
            rebuild_table(dpg)


def create_table_common(dpg, parent, df_sorted, column_label, column_width,
                        cell_creator, group_width=220):
    if dpg.does_item_exist("table_container"):
        dpg.delete_item("table_container")
    if dpg.does_item_exist('Number_handler'):
        dpg.delete_item('Number_handler')

    with dpg.handler_registry(tag='Number_handler'):
        dpg.add_key_press_handler(callback=lambda: handle_enter(dpg), key=525)
        dpg.add_key_press_handler(key=627, callback=lambda: handle_enter(dpg))
        dpg.add_key_press_handler(key=516, callback=lambda: handle_enter(dpg))
        dpg.add_key_press_handler(key=515,
                                  callback=lambda: handle_arrow_up(dpg))

    with dpg.group(parent=parent, tag="table_container", horizontal=True,
                   width=group_width):
        with dpg.table(tag="main_table", header_row=True,
                       borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True,
                       scrollX=True, scrollY=True,
                       policy=dpg.mvTable_SizingFixedFit):
            dpg.add_table_column(label="N", width_fixed=True,
                                 init_width_or_weight=30)
            dpg.add_table_column(label="Позиции", width_fixed=True,
                                 init_width_or_weight=70)
            dpg.add_table_column(label=column_label, width_fixed=True,
                                 init_width_or_weight=column_width)

            for count, row_idx in enumerate(df_sorted.index, 1):
                with dpg.table_row():
                    dpg.add_text(str(count))
                    dpg.add_text(str(df_sorted.at[row_idx, 'Positions']))
                    current_row = row_idx
                    cell_item = cell_creator(current_row, df_sorted)
                    if dpg.does_item_exist(f"focus_reg_{row_idx}"):
                        dpg.delete_item(f"focus_reg_{row_idx}")
                    if dpg.does_item_exist(f"focus_reg_handler{row_idx}"):
                        dpg.delete_item(f"focus_reg_handler{row_idx}")

                    with dpg.item_handler_registry(tag=f"focus_reg_{row_idx}"):
                        dpg.add_item_focus_handler(
                            callback=on_cell_focus,
                            user_data=(row_idx, 'Numbers'),
                            tag=f"focus_reg_handler{row_idx}",
                        )

                    dpg.bind_item_handler_registry(
                        cell_item, f"focus_reg_{row_idx}")


def on_cell_focus(sender, app_data, user_data):
    try:
        row_idx, col_name = user_data
        if isinstance(row_idx, int) and col_name == 'Numbers':
            MEASURE_DATA.current_focus = (row_idx, col_name)
        else:
            raise ValueError
    except (TypeError, ValueError):
        print("Ошибка формата фокуса!")
        MEASURE_DATA.current_focus = None


def handle_enter(dpg):
    if MEASURE_DATA.current_focus is None:
        first_tag = "cell_0_Numbers"
        if dpg.does_item_exist(first_tag):
            dpg.focus_item(first_tag)
            MEASURE_DATA.current_focus = (0, 'Numbers')
        return

    row_idx, col_name = MEASURE_DATA.current_focus
    next_row = row_idx + 1
    slot = MEASURE_DATA.active_slot_number
    if next_row < len(MEASURE_DATA.get_numbers_list(slot)):
        next_tag = f"cell_{next_row}_Numbers"
        if dpg.does_item_exist(next_tag):
            dpg.focus_item(next_tag)
            MEASURE_DATA.current_focus = (next_row, 'Numbers')


def create_table_common_control(dpg, parent, df_sorted, column_label,
                                column_width, cell_creator, group_width=220):
    if dpg.does_item_exist("table_container"):
        dpg.delete_item("table_container")
    if dpg.does_item_exist('Number_handler'):
        dpg.delete_item('Number_handler')

    with dpg.group(parent=parent, tag="table_container", horizontal=True,
                   width=group_width):
        with dpg.table(tag="main_table", header_row=True,
                       borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True,
                       scrollX=True, scrollY=True,
                       policy=dpg.mvTable_SizingFixedFit):
            dpg.add_table_column(label="N", width_fixed=True,
                                 init_width_or_weight=30)
            dpg.add_table_column(label="Позиции", width_fixed=True,
                                 init_width_or_weight=70)
            dpg.add_table_column(label=column_label, width_fixed=True,
                                 init_width_or_weight=column_width)

            for count, row_idx in enumerate(df_sorted.index, 1):
                with dpg.table_row():
                    dpg.add_text(str(count))
                    dpg.add_text(df_sorted.at[row_idx, 'Positions'])
                    cell_creator(row_idx, df_sorted)


def rebuild_table(dpg):
    df_sorted = load_numbers_list(MEASURE_DATA.active_slot_number)

    def create_input_cell(row_idx, df):
        value = str(df.at[row_idx, 'Numbers']) if 'Numbers' in df.columns else ''
        tag = f"cell_{row_idx}_Numbers"
        input_item = dpg.add_input_text(
            tag=tag, default_value=value, width=105,
            callback=update_cell, user_data=(row_idx, 'Numbers'),
        )
        if row_idx == 0:
            dpg.focus_item(input_item)
            MEASURE_DATA.current_focus = (0, 'Numbers')
        return input_item

    create_table_common(dpg, "numbers_select_window", df_sorted,
                        "Номера", 80, create_input_cell)


def rebuild_table_control(dpg):
    df_sorted = load_numbers_list(MEASURE_DATA.active_slot_number)
    control_rk_numbers, numbers_df = Control_RK.load_control_rk_numbers(
        MEASURE_DATA.active_slot_number)

    def create_combo_cell(row_idx, df):
        tag = f"cell_{row_idx}_Numbers"
        dpg.add_combo(
            items=control_rk_numbers, tag=tag, width=100,
            user_data=(row_idx, 'Numbers'), callback=update_combo_cell,
        )

    create_table_common_control(dpg, "numbers_select_window", df_sorted,
                                "Номера", 100, create_combo_cell,
                                group_width=225)


def handle_arrow_up(dpg):
    current_focused = MEASURE_DATA.current_focus
    if current_focused is None:
        return
    row_idx, col_name = current_focused
    if col_name != 'Numbers':
        return
    next_row = row_idx - 1
    if next_row >= 0:
        next_tag = f"cell_{next_row}_Numbers"
        if dpg.does_item_exist(next_tag):
            dpg.focus_item(next_tag)
            MEASURE_DATA.current_focus = (next_row, 'Numbers')


def update_cell(sender, app_data, user_data):
    df = MEASURE_DATA.get_numbers_list(MEASURE_DATA.active_slot_number)
    row_idx, col_name = user_data
    if col_name == 'Numbers':
        df.at[row_idx, 'Numbers'] = app_data
        MEASURE_DATA.set_numbers_list(MEASURE_DATA.active_slot_number, df)
    MEASURE_DATA.current_focus = (row_idx, col_name)


def update_combo_cell(sender, app_data, user_data):
    df = MEASURE_DATA.get_numbers_list(MEASURE_DATA.active_slot_number)
    row_idx, col_name = user_data
    if col_name == 'Numbers':
        df.at[row_idx, 'Numbers'] = app_data
        MEASURE_DATA.set_numbers_list(MEASURE_DATA.active_slot_number, df)


def add_serial_n_callback(sender, data, dpg):
    add_sn_letters_to_numbers(MEASURE_DATA.active_slot_number,
                              dpg.get_value('serial_n_add_text'))
    rebuild_table(dpg)


def add_ser_numbers_callback(sender, data, dpg):
    first_pos = dpg.get_value('first_num_select')
    end_pos = dpg.get_value('end_num_select')
    first_number = dpg.get_value('first_number_text')
    fill_numbers(first_pos, end_pos, first_number,
                 MEASURE_DATA.active_slot_number)
    rebuild_table(dpg)


def add_numbers_by_measure_id_callback(sender, data, dpg):
    input_str = dpg.get_value('measure_id_str')
    process_batch_data(input_str)
    rebuild_table(dpg)


def add_numbers_by_msk_marker(sender, data, dpg):
    first_pos = dpg.get_value('first_num_select')
    end_pos = dpg.get_value('end_num_select')
    input_str = dpg.get_value('add_msk_id_str')
    add_numbers_by_msk(first_pos, end_pos, input_str)
    rebuild_table(dpg)


def save_numbers_callback(sender, data, dpg):
    slot = MEASURE_DATA.active_slot_number
    msk_str = MEASURE_DATA.get_msk(slot)
    if msk_str == 'K.O.':
        numbers_res = test_control_numbers_dataframe(slot, dpg)
    else:
        numbers_res = test_numbers_dataframe(slot)
    dpg.configure_item('numbers_' + str(slot) + '_select',
                       label=numbers_res)
    rebuild_table(dpg)
    if numbers_res != 'Нет':
        dpg.delete_item('numbers_select_window')


def clear_numbers_callback(sender, data, dpg):
    MEASURE_DATA.delete_number_slot(MEASURE_DATA.active_slot_number)
    MEASURE_DATA.current_focus = None
    rebuild_table(dpg)


def add_numbers_by_msk_auto(sender, data, dpg):
    msk_str = dpg.get_value('msk_resonator_select_msk')
    number_str = set_numbers_auto_msk(msk_str)
    slot = MEASURE_DATA.active_slot_number
    if number_str is not None:
        dpg.configure_item('numbers_' + str(slot) + '_select',
                           label=number_str)