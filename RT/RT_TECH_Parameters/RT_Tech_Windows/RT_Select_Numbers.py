from RT.RT_TECH_Parameters.RT_Data import RT_DATA


def create_numbers_rt_window(dpg):
    with dpg.window(label="Номера", width=400, height=300, pos=(20, 325), tag='RT_Numbers_Select_window'):
        with dpg.group(height=40, width=150, horizontal=True):
            with dpg.group(height=40, width=150, horizontal=False):
                dpg.add_text("Штрих код МСК")
                dpg.add_input_text(tag='rt_bar_code_text', decimal=True, width=150, callback='',
                                   user_data=dpg)
            with dpg.group(height=40, width=150, horizontal=False):
                dpg.add_text("МСК")
                dpg.add_input_text(tag='rt_msk_name_text', width=150, callback='',
                                   user_data=dpg)
        dpg.add_separator()
        dpg.add_separator()
        with dpg.table(header_row=True):
            dpg.add_table_column(label="N", width_fixed=True, init_width_or_weight=20)
            dpg.add_table_column(label="Номер", width_fixed=True, init_width_or_weight=90)
            dpg.add_table_column(label="ON", width_fixed=True, init_width_or_weight=30)

            for i in range(1, 6):
                with dpg.table_row():
                    dpg.add_text(str(i), tag=f'rt_numbers_n_{str(i)}')
                    dpg.add_input_text(tag=f'rt_numbers_serial_{str(i)}', callback=next_field_callback, user_data=dpg,
                                       on_enter=True)
                    dpg.add_checkbox(tag=f'rt_numbers_on_{str(i)}', callback=set_number_callback, user_data=dpg)


# Функция установки номеров резонатор
def set_number_callback(sender, data, dpg):
    result_dict = {}
    for i in range(1, 6):
        N = dpg.get_value(f'rt_numbers_serial_{str(i)}')
        N_Status = dpg.get_value(f'rt_numbers_on_{str(i)}')
        result_dict[f'{i}'] = {'Serial': N,
                               'Use': N_Status,
                               'Status': 'NA'}
        if N_Status:
            dpg.set_value(f"number_{str(i - 1)}", f"Номер: {N}")
    RT_DATA.set_rt_numbers(result_dict)


# Функция переключения фокуса
def next_field_callback(sender, data, dpg):
    index = int(sender.split('_')[-1])
    if index < 5:
        index = index + 1
    else:
        index = 1
    if dpg.does_item_exist(f'rt_numbers_serial_{str(index)}'):
        dpg.focus_item(f'rt_numbers_serial_{str(index)}')

