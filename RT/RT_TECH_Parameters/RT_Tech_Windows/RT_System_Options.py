import pandas as pd
from sqlalchemy import create_engine, text
import configparser

from tabulate import tabulate

import Options
from RT.RT_TECH_Parameters.Multimetr_use import Multimetr_test
from RT.RT_TECH_Parameters.RT_Data import get_system_options, get_options_by_id
from RT.RT_TECH_Parameters.VNA_use import vna_test
from RT.RT_TECH_Parameters.switch_use import test_switch


def create_options_rt_window(sender, data, dpg):
    dpg.delete_item('RT_Options_Window')
    with dpg.window(label="Настройки", width=900, height=300, tag='RT_Options_Window'):
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
                            tag=f"rt_port_combo_{index}"
                        )
                    if item['Protokol'] in ['RS485', 'RS232']:
                        if item['Port'] in ports:
                            dpg.bind_item_theme(f"rt_port_combo_{index}", 'rt_port_combo_green')
                        else:
                            dpg.bind_item_theme(f"rt_port_combo_{index}", 'rt_port_combo_red')
                    # Поле ввода для адреса
                    with dpg.table_cell():
                        dpg.add_input_text(
                            default_value=item['Address'],
                            width=100,
                            tag=f"rt_address_combo_{index}"
                        )

                    dpg.add_text(item['SerialN'])
                    dpg.add_text('----', tag=f'rt_status_pribor_{index}')
        with dpg.group(horizontal=True, horizontal_spacing=280, width=300):
            dpg.add_button(label='Проверить', callback=test_all, user_data=dpg)
            dpg.add_button(label='Сохранить', callback=save_callback, user_data=dpg)
    Options.center_window(dpg, 'RT_Options_Window')


# Тестирует состояния приборов установки
def test_all(sender, data, dpg):
    system_id = get_system_options()
    df = get_options_by_id(system_id['тип'], system_id['идентификатор']).copy()
    df = test_switch(df)
    df = Multimetr_test(df)
    df = vna_test(df)
    print(tabulate(df, headers='keys', tablefmt='grid', showindex=False, missingval='—'))
    for index, row in df.iterrows():
        dpg.configure_item(f'rt_status_pribor_{index}', default_value=row['Status'])
        if row['Status'] == 'OK':
            dpg.configure_item(f'rt_status_pribor_{index}', color=[0, 255, 0, 128])
        else:
            dpg.configure_item(f'rt_status_pribor_{index}', color=[255, 0, 0, 128])

# Добавляет темы для комбо
def add_theme(dpg):
    # Создаем темы для цветовой индикации
    dpg.delete_item('rt_port_combo_green')
    dpg.delete_item('rt_port_combo_red')
    dpg.delete_item('rt_button_theme_rt_regime')
    with dpg.theme(tag='rt_port_combo_green'):
        with dpg.theme_component(dpg.mvCombo):
            dpg.add_theme_color(dpg.mvThemeCol_Text, (0, 255, 0, 255), category=dpg.mvThemeCat_Core
                                )

    with dpg.theme(tag='rt_port_combo_red'):
        with dpg.theme_component(dpg.mvCombo):
            dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 0, 0, 255), category=dpg.mvThemeCat_Core
                                )
    with dpg.theme(tag='rt_button_theme_rt_regime'):
        # Добавляем компонент для кнопок (mvButton)
        with dpg.theme_component(dpg.mvButton):
            # Устанавливаем цвет фона кнопки
            dpg.add_theme_color(dpg.mvThemeCol_Button, (255, 0, 0, 100),
                                )  # Красный
            # Цвет при наведении
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (255, 0, 0, 120),
                                )  # Желтый
            # Цвет при нажатии
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (255, 0, 0, 150))
            # Настройка закругления углов (радиус 5px)
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 20)


# Сохраняет данные настройек портов в БД
def save_to_database(data):
    system_options = get_system_options()
    try:
        # Создаем подключение
        engine = create_engine(Options.get_connection_string())
        # Создаем DataFrame
        df = pd.DataFrame(data)

        with engine.connect() as conn:
            # Удаляем старые записи
            delete_query = text("""
                DELETE FROM состав_измерительной_системы 
                WHERE System_Name = :name AND System_ID = :id
            """)
            conn.execute(delete_query, {'name': system_options['тип'],
                                        'id': system_options['идентификатор']})
            conn.commit()

        df.to_sql(
            name='состав_измерительной_системы',
            con=engine,
            if_exists='append',
            index=False
        )

        return True
    except Exception as e:
        print(f"Ошибка сохранения: {e}")
        return False


def save_callback(sender, data, dpg):
    # Обновляем данные из интерфейса
    system_id = get_system_options()
    df = get_options_by_id(system_id['тип'], system_id['идентификатор']).copy()
    for index, row in df.iterrows():
        # Получаем новые значения из GUI
        df.loc[index, 'Port'] = dpg.get_value(f"rt_port_combo_{index}")
        df.loc[index, 'Address'] = dpg.get_value(f"rt_address_combo_{index}")
    # Сохраняем в БД
    if save_to_database(df):
        Options.show_message(dpg, "Настройки", ["Данные успешно сохранены!"])
    else:
        Options.show_message(dpg, "Настройки", ["Ошибка сохранения!"])
