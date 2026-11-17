import numpy as np

from Pribory.Network_Analyzer import VNA_Data
from Pribory.Network_Analyzer.VNA import VNA
from Pribory.Network_Analyzer.VNA_Utils import format_float
from Pribory.Network_Analyzer.Vna_Options import create_vna_options_window
from RT.RT_TECH_Parameters import RT_Data
from RT.RT_TECH_Parameters.RT_Data import RT_DATA
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_VNA_Callibration_Window import create_vna_call_window
from RT.RT_TECH_Parameters.switch_use import analyzer_all_off, analyzer_on
from Utils.Thread_timer import Timer_D


def create_rt_measure_freq_window(dpg):
    # Главное окно
    with dpg.window(tag="RT_Measurements_freq", width=525, height=520, pos=(1350, 365),
                    label='Результаты измерения параметров'):
        with dpg.child_window(width=500, height=150, tag="freq_panel"):
            dpg.add_text("Частота (Гц):", indent=20, tag='freq_value')
            dpg.add_text("0.000000", tag="freq_val", indent=20)
            with dpg.popup('freq_val', min_size=[120, 30]):
                dpg.add_selectable(label="Калибровка VNA", callback=create_vna_call_window,
                                   user_data=dpg,
                                   tag='vna_menu_pop_1')
                dpg.add_selectable(label="Настройки VNA", callback=create_vna_options_window,
                                   user_data=dpg,
                                   tag='vna_menu_pop_2')
                dpg.add_selectable(label="Измерение", callback=measure,
                                   user_data=dpg,
                                   tag='vna_menu_pop_3')
        with dpg.group(horizontal=True, horizontal_spacing=10):
            with dpg.child_window(width=245, height=150, tag="freq_ppm_panel"):
                dpg.add_text("Точность настройки (ppm):", indent=20)
                dpg.add_text("0.000", tag="freq_ppm_val", indent=20)

            with dpg.child_window(width=245, height=150, tag="R_panel"):
                dpg.add_text("Динамическое сопротивление:", indent=20)
                dpg.add_text("0.0", tag="R_val", indent=20)
            # Добавляем таблицу
        with dpg.child_window(width=500, height=170, tag="table_container_rt_measure"):  # Контейнер для таблицы
            dpg.add_table(tag="parameters_table_rt",
                          header_row=True,
                          borders_innerH=True,
                          borders_outerH=True,
                          row_background=True,
                          policy=dpg.mvTable_SizingStretchProp)
            dpg.add_table_column(label="Параметр", parent="parameters_table_rt")
            dpg.add_table_column(label="Значение", parent="parameters_table_rt")

        with dpg.table_row(parent="parameters_table_rt"):
            dpg.add_text("Точность настройки, ppm")
            dpg.add_text("0.000", tag="ppm_table_val")

        with dpg.table_row(parent="parameters_table_rt"):
            dpg.add_text("Динамическое сопротивление, Ом")
            dpg.add_text("0.0", tag="dynamic_resistance_val")

        with dpg.table_row(parent="parameters_table_rt"):
            dpg.add_text("Статическая емкость, пФ")
            dpg.add_text("0.0", tag="static_capacitance_val")

        with dpg.table_row(parent="parameters_table_rt"):
            dpg.add_text("Добротность, х1000")
            dpg.add_text("0.0", tag="Q_factor_val")

        with dpg.table_row(parent="parameters_table_rt"):
            dpg.add_text("Динамическая емкость, фФ")
            dpg.add_text("0.0", tag="dynamic_capacitance_val")

        with dpg.table_row(parent="parameters_table_rt"):
            dpg.add_text("Динамическая индуктивность, мГн")
            dpg.add_text("0.0", tag="dynamic_inductance_val")

    # Темы с подсветкой и стилями
    with dpg.theme(tag="freq_theme"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (204, 153, 255, 80))  # Yellow background
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 12)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 20, 20)
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, (204, 153, 255))

    with dpg.theme(tag="freq_ppm_theme"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (135, 206, 250, 80))  # Blue background
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 12)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 20, 20)
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, (135, 206, 250))

    with dpg.theme(tag="R_theme"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (144, 238, 144, 80))  # Orange background
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 12)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 20, 20)
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, (173, 255, 47))

    # Применяем темы к панелям
    dpg.bind_item_theme("freq_panel", "freq_theme")
    dpg.bind_item_theme("freq_ppm_panel", "freq_ppm_theme")
    dpg.bind_item_theme("R_panel", "R_theme")

    # Привязываем шрифты к тексту
    dpg.bind_item_font("freq_val", 'large_font')
    dpg.bind_item_font("freq_ppm_val", 'large_font')
    dpg.bind_item_font("R_val", 'large_font')


def measure(sender, data, dpg):
    print('Подключаем канал №', RT_DATA.get_current_channel())
    result = analyzer_on(channel=RT_DATA.get_current_channel())
    print(result)
    if result == 'OK':
        vna = VNA(vna_type=VNA_Data.VNA_DATA.get_vna_type(), channel=RT_DATA.get_current_channel())
        vna.measure(int(RT_DATA.get_current_channel()))
        update_measure_value(dpg)
    else:
        print('Не включился канал подключения анализатора',RT_DATA.get_current_channel())


def update_f_ppm_value():
    data = VNA_Data.VNA_DATA.get_measure_data_scan()
    if 'F_ppm' in data.keys():
        if data['F_ppm'] is not None:
            if ['F_ppm'] != np.nan:
                return format_float(data['F_ppm'])
            else:
                return 'NA'
        else:
            return 'NA'
    else:
        return 'NA'
def update_R_value():
    data = VNA_Data.VNA_DATA.get_measure_data_scan()
    if 'R' in data.keys():
        return format(data['R'], '.1f')
    else:
        return 'NA'

def update_measure_value(dpg):
    data = VNA_Data.VNA_DATA.get_measure_data()
    result = format(data['Freq'], '.3f')
    dpg.set_value('freq_val', result)
    dpg.set_value('static_capacitance_val', format(data['C0'] * 1E+12, '.3f'))
    dpg.set_value('R_val', format(data['R'], '.1f'))
    dpg.set_value('dynamic_resistance_val', format(data['R'], '.1f'))
    dpg.set_value('dynamic_capacitance_val', format(data['C1'] * 1E+15, '.3f'))
    dpg.set_value('dynamic_inductance_val', format(data['L1'] * 1E+3, '.3f'))
    dpg.set_value('Q_factor_val', format(data['Q'] * 1E+3, '.1f'))
    spc = VNA_Data.VNA_DATA.get_current_measure_spc()
    #F_ppm = ((data['Freq'] - float(spc['Nominal'])) / float(spc['Nominal'])) * 1E+6
    dpg.set_value('freq_ppm_val', format_float(data['F_ppm']))
    dpg.set_value('ppm_table_val', format(data['F_ppm'], '.3f'))

    #data['F_ppm'] = F_ppm
    print_parameters_table(data)


def print_parameters_table(data):
    """
    Выводит таблицу параметров с преобразованием единиц и округлением до 2 знаков
    """
    # Преобразование значений согласно требованиям с округлением до 2 знаков
    formatted_data = {
        'Freq': (round(data['Freq'], 3), 'Гц'),
        'F_ppm': (round(data['F_ppm'], 3), 'ppm'),
        'R': (round(data['R'], 1), 'Ом'),
        'C1': (round(data['C1'] * 1e15, 3), 'фФ'),  # Переводим в фемтофарады
        'C0': (round(data['C0'] * 1e12, 3), 'пФ'),  # Переводим в пикофарады
        'Q': (round(data['Q'] / 1000, 1), 'x1000'),  # Делим на 1000
        'L1': (round(data['L1'] * 1000, 3), 'мГн'),
        'Phi': (round(data['Phi'], 3), 'град')

    }
    print("Результаты измерения")
    # Вывод таблицы
    print("параметр | значение   | Единицы")
    print("-----------------------------")
    for param, (value, unit) in formatted_data.items():
        print(f"{param:<8} | {value:>9.3f} | {unit}")

    # Дополнительные параметры (не в таблице) с округлением
    print(f"\nER = {round(data['ER'], 3)} Гц")
