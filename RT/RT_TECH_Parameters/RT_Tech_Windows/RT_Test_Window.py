import pandas as pd
from tabulate import tabulate

import Options
from Pribory.Network_Analyzer.OBZOR_304 import start_vna
from RT.RT_TECH_Parameters.Multimetr_use import Multimetr_test
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_System_Options import get_system_options, get_options_by_id, add_theme
from RT.RT_TECH_Parameters.VNA_use import vna_test
from RT.RT_TECH_Parameters.switch_use import test_switch, get_rele_state

from colorama import Fore, Back, Style, init
from tabulate import tabulate

# Инициализация colorama для цветного вывода в Windows
init(autoreset=True)
def create_start_test_rt_window(dpg):
    dpg.delete_item('RT_start_test_Window')
    with dpg.window(label="Тестирование приборов", width=900, height=300, tag='RT_start_test_Window',
                    modal=True,
                    no_close=False):
        dpg.add_text("Установка")
        system_op = get_system_options()
        with dpg.group(horizontal=True, horizontal_spacing=25, width=150):
            dpg.add_text(f"Тип  {system_op['тип']}")
            dpg.add_text(f"Идентификатор  {system_op['идентификатор']}")
        dpg.add_separator()
        dpg.add_separator()
        dpg.add_text("Состав установки")
        system_id = get_system_options()
        df = get_options_by_id(system_id['тип'], system_id['идентификатор'])
        print(tabulate(df, headers='keys', tablefmt='grid', showindex=False, missingval='—'))
        ports = Options.get_available_com_ports()
        print('Доступные COM порты', ports)
        add_theme(dpg)
        # Создаем таблицу с границами и фиксированными столбцами
        with dpg.table(
                header_row=True,
                borders_innerH=True,
                borders_outerH=True,
                borders_innerV=True,
                borders_outerV=True
        ):
            # Создаем колонки таблицы
            dpg.add_table_column(label="Тип")
            dpg.add_table_column(label="Название")
            dpg.add_table_column(label="Протокол")
            dpg.add_table_column(label="Порт")
            dpg.add_table_column(label="Адрес")
            dpg.add_table_column(label="Серийный номер")
            dpg.add_table_column(label="Статус")

            # Добавляем строки с данными
            for index, item in df.iterrows():
                with dpg.table_row():
                    dpg.add_text(item['Type'])
                    dpg.add_text(item['Name'])
                    dpg.add_text(item['Protokol'])

                    # Выпадающий список для портов
                    # Ячейка с комбо-боксом и цветовой индикацией
                    with dpg.table_cell():
                        dpg.add_combo(
                            items=ports,
                            default_value=item['Port'],
                            width=100,
                            tag=f"rt_test_port_combo_{index}"
                        )
                    if item['Protokol'] in ['RS485', 'RS232']:
                        if item['Port'] in ports:
                            dpg.bind_item_theme(f"rt_test_port_combo_{index}", 'rt_port_combo_green')
                        else:
                            dpg.bind_item_theme(f"rt_test_port_combo_{index}", 'rt_port_combo_red')
                    # Поле ввода для адреса
                    with dpg.table_cell():
                        dpg.add_input_text(
                            default_value=item['Address'],
                            width=100,
                            tag=f"rt_test_address_combo_{index}"
                        )

                    dpg.add_text(item['SerialN'])
                    dpg.add_text('----', tag=f'rt_test_status_pribor_{index}')
    Options.center_window(dpg, 'RT_start_test_Window')
    test_all(dpg)
    dpg.add_button(label='Закрыть', tag='test_close_button_rt', parent='RT_start_test_Window', callback=close,
                   user_data=dpg)
    dpg.bind_item_theme('test_close_button_rt', 'rt_button_theme_rt_regime')


def close(sender, data, dpg):
    dpg.delete_item('RT_start_test_Window')


# Тестирование всех подключенных систем установки
def test_all(dpg):
    system_id = get_system_options()
    df = get_options_by_id(system_id['тип'], system_id['идентификатор']).copy()
    df = test_switch(df)
    df = Multimetr_test(df)
    df = vna_test(df)
    print(tabulate(df, headers='keys', tablefmt='grid', showindex=False, missingval='—'))

    for index, row in df.iterrows():
        dpg.configure_item(f'rt_test_status_pribor_{index}', default_value=row['Status'])
        if row['Status'] == 'OK':
            dpg.configure_item(f'rt_test_status_pribor_{index}', color=[0, 255, 0, 128])
        else:
            dpg.configure_item(f'rt_test_status_pribor_{index}', color=[255, 0, 0, 128])

    power_state, analyzer_state, multimetr_state, r_magazine_state = get_rele_state()

    # Создаем DataFrame для состояний реле
    relay_data = []

    # Добавляем состояния питания
    for key, state in power_state.items():
        relay_data.append({
            'Тип устройства': 'Питание',
            'Идентификатор': key,
            'Состояние': 'ВКЛЮЧЕНО' if state else 'ВЫКЛЮЧЕНО'
        })

    # Добавляем состояния анализатора
    for key, state in analyzer_state.items():
        relay_data.append({
            'Тип устройства': 'Анализатор цепей',
            'Идентификатор': key,
            'Состояние': 'ВКЛЮЧЕНО' if state else 'ВЫКЛЮЧЕНО'
        })

    # Добавляем состояния мультиметра
    for key, state in multimetr_state.items():
        relay_data.append({
            'Тип устройства': 'Мультиметр',
            'Идентификатор': key,
            'Состояние': 'ВКЛЮЧЕНО' if state else 'ВЫКЛЮЧЕНО'
        })

    # Добавляем состояния электронного магазина
    for key, state in r_magazine_state.items():
        relay_data.append({
            'Тип устройства': 'Электронный магазин',
            'Идентификатор': key,
            'Состояние': 'ВКЛЮЧЕНО' if state else 'ВЫКЛЮЧЕНО'
        })

    # Создаем DataFrame
    relay_df = pd.DataFrame(relay_data)

    # Выводим таблицу
    print("\nСОСТОЯНИЕ РЕЛЕ:")
    print(tabulate(relay_df, headers='keys', tablefmt='grid', showindex=False))

    # Обновление кнопок в GUI (оригинальный код)
    for key in power_state:
        if power_state[key]:
            dpg.configure_item(f"Power_{key}_button", label='Отключить')
            dpg.bind_item_theme(f"Power_{key}_button", 'Use_button_theme_rt_3')
        else:
            dpg.configure_item(f"Power_{key}_button", label='Вкл')
            dpg.bind_item_theme(f"Power_{key}_button", 'Use_button_theme_rt')

    for key in analyzer_state:
        if analyzer_state[key]:
            dpg.configure_item(f"Network_Analyzer_{key}_button", label='Анализатор(Выкл)')
            dpg.bind_item_theme(f"Network_Analyzer_{key}_button", 'Use_button_theme_rt_3')
        else:
            dpg.configure_item(f"Network_Analyzer_{key}_button", label='Анализатор(Вкл)')
            dpg.bind_item_theme(f"Network_Analyzer_{key}_button", 'Use_button_theme_rt_1')

    for key in multimetr_state:
        if multimetr_state[key]:
            dpg.configure_item(f"V_{key}_button", label='Мультиметр(Выкл)')
            dpg.bind_item_theme(f"V_{key}_button", 'Use_button_theme_rt_3')
        else:
            dpg.configure_item(f"V_{key}_button", label='Мультиметр(Вкл)')
            dpg.bind_item_theme(f"V_{key}_button", 'Use_button_theme_rt_1')