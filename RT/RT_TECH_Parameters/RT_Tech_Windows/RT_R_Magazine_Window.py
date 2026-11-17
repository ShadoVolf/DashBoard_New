import time

import Options
from Pribory.Network_Analyzer import VNA_Data
from Pribory.Network_Analyzer.VNA import VNA
from Pribory.Network_Analyzer.VNA_Data import VNA_DATA
from Pribory.R_Magazine.Decade_Programmable_Board import SDPRB
from RT.RT_TECH_Parameters import RT_Data
from RT.RT_TECH_Parameters.Export_RT_Data_Excel import analyze_data_structure, save_resonator_data_to_excel_smart, \
    print_outliers_statistics, save_temperature_dependence_to_excel_simple
from RT.RT_TECH_Parameters.Export_RT_Data_PDF import analyze_data_for_pdf, save_resonator_data_to_pdf_simple, \
    save_temperature_dependence_simple
from RT.RT_TECH_Parameters.Filter_Outliers import quick_filter_outliers
from RT.RT_TECH_Parameters.Multimetr_use import get_power
from RT.RT_TECH_Parameters.RT_Data import RT_DATA
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Control_Manual import set_button, get_res_state_color
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Freq_Window import update_f_ppm_value, update_R_value
from RT.RT_TECH_Parameters.switch_use import r_magazine_all_off, r_magazine_on, set_resistance, get_options, \
    get_resistance, multimetr_on, off_resistance, multimetr_all_off, analyzer_on, analyzer_all_off, power_on, power_off
from Utils.Thread_timer import Timer_D
from Utils.Thread_timer_multy import Timer_D_Multy
import pandas as pd
import os

from Utils.math_functions_user import safe_float


def create_rt_r_magazine_window(dpg, channel=1):
    dpg.delete_item('RT_r_magazine_Window')
    RT_DATA.dpg_ref = dpg
    RT_DATA.set_current_channel(channel)
    map_data = RT_Data.RT_DATA.get_r_magazine_value_data(0)
    map_ = RT_Data.RT_DATA.get_r_magazine_value()
    port, address, name, emulate = get_options(map_data[0])
    r_m = SDPRB('R4D3B16', port=port, slave_id=int(address), simulation_mode=emulate, map_data=map_)
    max_board, min_board, step_board = r_m.get_min_max_resistance_and_step()
    current_r = r_m.get_current_resistance()
    with dpg.window(label="Электронный магазин", width=870, height=610, pos=(450, 275), tag='RT_r_magazine_Window',
                    modal=False,
                    no_close=False):
        dpg.add_text(f"Электронный магазин: канал {channel}")
        user_data = [dpg, channel, 'EM']
        with dpg.group(horizontal=True):
            dpg.add_text(f'Диапазон значений [{min_board}...{max_board}] Ом')
            dpg.add_text(f'Шаг {step_board} Ом')
        dpg.add_separator()
        dpg.add_text('Текущее значение')
        with dpg.group(horizontal=True):
            user_data_2 =[dpg, channel]
            dpg.add_input_text(width=200, tag='rt_r_magazine_input_value', default_value=current_r[0])
            dpg.add_button(label='Установить', user_data=user_data_2, callback=set_resistance_value_button,
                           tag='rt_r_magazine_set_button')
            # Добавлен индикатор статуса установки
            dpg.add_text("", tag='rt_r_magazine_set_indicator')
            dpg.add_button(label='Включить', user_data=user_data, callback=r_magazine_on_button,
                           tag='rt_r_magazine_on_button', width=100)
        dpg.add_separator()
        dpg.add_separator()
        with dpg.table(header_row=True, width=870):
            dpg.add_table_column(label="R, Ом", width_fixed=True, init_width_or_weight=70)
            dpg.add_table_column(label="F, Гц", width_fixed=True, init_width_or_weight=150)
            dpg.add_table_column(label="F, ppm", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="U, В", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="I, мА", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="P, мВ", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="Время, c", width_fixed=True, init_width_or_weight=100)
            dpg.add_table_column(label="Общее время, c", width_fixed=True, init_width_or_weight=120)
            with dpg.table_row():
                dpg.add_text('---', tag=f'rt_tune_current_r')
                dpg.add_text('--------', tag=f'rt_tune_current_fhz')
                dpg.add_text('---', tag=f'rt_tune_current_fppm')
                dpg.add_text('---', tag=f'rt_tune_current_u')
                dpg.add_text('---', tag=f'rt_tune_current_i')
                dpg.add_text('---', tag=f'rt_tune_current_p')
                dpg.add_text('---', tag=f'rt_tune_current_time')
                dpg.add_text('---', tag=f'rt_tune_current_time_all')
        dpg.add_separator()
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_text('Настройка')
            dpg.add_input_text(label='Начальное значение, Ом', width=70, default_value=f'{min_board}',
                               tag='rt_tune_begin_value')
            dpg.add_input_text(label='Конечное значение, Ом', width=70, default_value=f'{max_board}',
                               tag='rt_tune_end_value')
            dpg.add_input_text(label='Шаг, Ом', width=70, default_value=f'{step_board}',
                               tag='rt_tune_step_value')
            user_data = [dpg, channel, 'Temp']
            dpg.add_button(label='Включить', height=25, width=100, tag='rt_tune_start_button',
                           callback=start_find_extr, user_data=user_data)
        dpg.add_separator()
        dpg.add_separator()
        # Горизонтальная группа для таблицы и графика
        with dpg.group(horizontal=True):
            # График слева
            with dpg.group(horizontal=False):
                with dpg.plot(label="График I(t), мА", height=300, width=400, tag='em_graph_plot'):
                    # optionally create legend
                    dpg.add_plot_legend()
                    # REQUIRED: create x and y axes
                    # Ось X (время)
                    dpg.add_plot_axis(dpg.mvXAxis, label="Time", tag="x_axis_em")

                    # Ось Y для основных параметров
                    y_axis = dpg.add_plot_axis(dpg.mvYAxis, label="I, ма", tag="y_axis_em")

                    # Создаем серии для каждого параметра

                    dpg.add_line_series([], [], label="U(t), В", parent=y_axis,
                                        tag="series_U")
                with dpg.group(horizontal=True):
                    dpg.add_combo(items=[], tag='rt_em_plot_select_view', width=200, user_data=dpg,
                                  callback=change_plot_view)
                    dpg.add_button(label='Сохранить', width=90, tag='rt_save_em_data_button', user_data=dpg,
                                   callback=save_em_data)
                    dpg.add_button(label='Печать', width=90, tag='rt_print_em_data_button', user_data=dpg,
                                   callback=print_em_data)
                with dpg.group(horizontal=True):
                    dpg.add_text("Режим:")
                    dpg.add_radio_button(
                        items=["Время", "ТЧХ"],
                        default_value="Время",
                        tag="RT_plot_display_mode",
                        callback=set_plot_type,
                        user_data=dpg
                    )

            # Таблица справа
            with dpg.table(header_row=True, width=480, tag='RT_TCH_table_data'):
                dpg.add_table_column(label="N", width_fixed=True, init_width_or_weight=20)
                dpg.add_table_column(label="R, Ом", width_fixed=True, init_width_or_weight=60)
                dpg.add_table_column(label="F, ppm", width_fixed=True, init_width_or_weight=60)
                dpg.add_table_column(label="U, В", width_fixed=True, init_width_or_weight=60)
                dpg.add_table_column(label="I, мА", width_fixed=True, init_width_or_weight=60)
                dpg.add_table_column(label="Время цикла", width_fixed=True, init_width_or_weight=70)
                dpg.add_table_column(label="Время", width_fixed=True, init_width_or_weight=60)
                with dpg.table_row(tag='RT_TCH_1_row_data'):
                    dpg.add_text('0', tag=f'rt_1_tune_current_N')
                    dpg.add_text('---', tag=f'rt_1_tune_current_R')
                    dpg.add_text('---', tag=f'rt_1_tune_current_fppm')
                    dpg.add_text('---', tag=f'rt_1_tune_current_u')
                    dpg.add_text('---', tag=f'rt_1_tune_current_i')
                    dpg.add_text('---', tag=f'rt_1_tune_current_time')
                    dpg.add_text('---', tag=f'rt_1_tune_current_time_all')
    dpg.bind_item_theme("rt_r_magazine_on_button", 'Use_button_theme_rt_1')
    dpg.bind_item_theme('rt_tune_start_button', 'Use_button_theme_rt_1')


def find_nearest_multiple_of_100(num):
    """Находит ближайшее число, кратное 100"""
    remainder = num % 100
    if remainder == 0:
        return num
    elif remainder < 50:
        return num - remainder
    else:
        return num + (100 - remainder)


def start_find_extr(sender, data, user_data):
    (dpg, channel, process) = user_data
    button_text = dpg.get_item_label(sender)

    if button_text == 'Включить':
        items_to_delete = []
        # Проходим по всем элементам интерфейса
        for item in dpg.get_all_items():
            tag = dpg.get_item_alias(item) or str(item)  # Получаем тег элемента
            if 'row' in tag:
                items_to_delete.append(item)
        # Удаляем найденные элементы
        for item in items_to_delete:
            dpg.delete_item(item)
        RT_DATA.set_process_type(process)
        map_data = RT_Data.RT_DATA.get_r_magazine_value_data(0)
        map_ = RT_Data.RT_DATA.get_r_magazine_value()
        port, address, name, emulate = get_options(map_data[0])
        r_m = SDPRB('R4D3B16', port=port, slave_id=int(address), simulation_mode=emulate, map_data=map_)
        max_board, min_board, step_board = r_m.get_min_max_resistance_and_step()

        begin_value = dpg.get_value('rt_tune_begin_value')
        end_value = dpg.get_value('rt_tune_end_value')
        step_value_str = dpg.get_value('rt_tune_step_value')

        current_value = safe_float(begin_value)
        dpg.set_value('rt_r_magazine_input_value', int(current_value))
        channel = RT_DATA.get_current_channel()
        user_data_ = (dpg, channel)
        set_resistance_value_button(None, None, user_data_)
        current_value = safe_float(dpg.get_value('rt_r_magazine_input_value'))
        dpg.set_value('rt_tune_begin_value', current_value)
        begin_value = current_value
        if safe_float(step_value_str) < step_board:
            step_value = step_board
        else:
            step_value = safe_float(step_value_str)

        step_value = find_nearest_multiple_of_100(step_value)
        dpg.set_value('rt_tune_step_value', step_value)

        r_dict = {'Begin': begin_value,
                  'End': safe_float(end_value),
                  'Step': step_value,
                  'Current': current_value}
        RT_DATA.set_current_rm(r_dict)

    r_magazine_on_button(sender, data, user_data)




def update_graph_series(dpg, graph_tag='em_graph_plot', x_axis_tag='x_axis_em',
                        y_axis_tag='y_axis_em', plot_type='R_Magazine'):
    """
    Обновляет метки осей и серии данных на графике

    Args:
        ax_dict: Словарь с метками для осей
        series_dict: Словарь с тегами серий данных
        graph_tag: Тег графика (по умолчанию 'em_graph_plot')
        x_axis_tag: Тег оси X (по умолчанию 'x_axis_em')
        y_axis_tag: Тег оси Y (по умолчанию 'y_axis_em')
        :param dpg:
        :param x_axis_tag:
        :param graph_tag:
        :param y_axis_tag:
        :param plot_type:
    """
    # Проверяем существование графика и осей
    series_dict, ax_dict = RT_DATA.get_plot_names(plot_type)

    if not dpg.does_item_exist(graph_tag):
        print(f"Ошибка: График с тегом '{graph_tag}' не существует")
        return

    if not dpg.does_item_exist(x_axis_tag):
        print(f"Ошибка: Ось X с тегом '{x_axis_tag}' не существует")
        return

    if not dpg.does_item_exist(y_axis_tag):
        print(f"Ошибка: Ось Y с тегом '{y_axis_tag}' не существует")
        return

    # Установка метки для оси X
    if 'axis_x' in ax_dict:
        dpg.set_item_label(x_axis_tag, ax_dict['axis_x'])
    current_plot = RT_DATA.get_current_plot_name()
    # Обработка серий данных
    for series_name, series_tag in series_dict.items():
        # Проверяем, есть ли метка для этой серии в словаре ax
        if series_name not in ax_dict:
            print(f"Предупреждение: Для серии '{series_name}' нет метки в словаре ax")
            continue

        # Проверяем существование серии и удаляем если есть
        if dpg.does_item_exist(series_tag):
            dpg.delete_item(series_tag)
        plot_show = False
        if series_name == current_plot:
            plot_show = True
        # Создаем новую серию данных
        RT_DATA.series_tags[series_name] = dpg.add_line_series(
            x=[],
            y=[],
            label=ax_dict[series_name],
            parent=y_axis_tag,
            tag=series_tag, show=plot_show
        )
        dpg.set_axis_limits_auto(x_axis_tag)

    print("График успешно обновлен")


def set_plot_type(sender, data, user_data):
    dpg = user_data
    plot_select = dpg.get_value('RT_plot_display_mode')
    RT_DATA.set_current_plot_type(plot_select)
    plot_views, axes_names = RT_DATA.get_plot_names(plot_select)
    keys_list = list(plot_views.keys())
    plot_default_view = None
    dpg.configure_item('rt_em_plot_select_view', items=keys_list)

    if plot_select == 'Время':
        plot_default_view = 'I(t), мА'
    elif plot_select == 'ТЧХ':
        plot_default_view = 'F(R), ppm'

    dpg.configure_item('rt_em_plot_select_view', default_value=plot_default_view)
    RT_DATA.current_plot_view = plot_default_view
    update_graph_series(dpg, graph_tag='em_graph_plot', x_axis_tag='x_axis_em',
                        y_axis_tag='y_axis_em', plot_type=plot_select)
    change_plot_view(None, plot_default_view, dpg)
    update_em_graph(dpg)



def update_em_graph(dpg):
    """Обновление графика новыми данными"""
    plot_type = RT_DATA.get_current_plot_type()
    data = None
    times = None
    if plot_type == 'Время':
        if not hasattr(RT_DATA, 'em_measure_data') or not RT_DATA.get_all_em_data():
            return
        data = RT_DATA.get_all_em_data()
        # Проверяем, что есть данные для отображения
        if 'Time' not in data or not data['Time']:
            return

        times = data['Time']

    elif plot_type == 'ТЧХ':
        if not hasattr(RT_DATA, 'temp_measure_data') or not RT_DATA.get_temp_data():
            return
        data = RT_DATA.get_temp_data()
        # Проверяем, что есть данные для отображения
        if 'R магазина, Ом' not in data or not data['R магазина, Ом']:
            return
        times = data['R магазина, Ом']

    # Обновляем каждую серию данных
    for param, tag in RT_DATA.series_tags.items():
        if param in data and len(data[param]) == len(times):
            # Берем только последние N точек для производительности
            max_points = 50000  # Ограничиваем количество точек на графике
            if len(times) > max_points:
                x_data = times[-max_points:]
                y_data = data[param][-max_points:]
            else:
                x_data = times
                y_data = data[param]

            # Обновляем данные серии
            dpg.set_value(tag, [x_data, y_data])
            dpg.fit_axis_data('y_axis_em')
            dpg.fit_axis_data('x_axis_em')


def change_plot_view(sender, data, dpg):
    current_plot_name = RT_DATA.get_current_plot_name()
    current_plot_type = RT_DATA.get_current_plot_type()
    view_select = data
    if data != current_plot_name:
        RT_DATA.set_current_plot_name(data)
        series_dict, ax_dict = RT_DATA.get_plot_names(current_plot_type)
        for series_name, series_tag in series_dict.items():
            # Проверяем, есть ли метка для этой серии в словаре ax
            if series_name not in ax_dict:
                print(f"Предупреждение: Для серии '{series_name}' нет метки в словаре ax")
                continue
            if data == series_name:
                if dpg.does_item_exist(series_tag):
                    dpg.configure_item(series_tag, show=True)
                    dpg.set_item_label('y_axis_em', ax_dict[series_name])
            else:
                if dpg.does_item_exist(series_tag):
                    dpg.configure_item(series_tag, show=False)
        dpg.configure_item('em_graph_plot', label=f'График {data}')
        if 'axis_x' in ax_dict:
            dpg.set_item_label('x_axis_em', ax_dict['axis_x'])

        print('Установлен для отображения график ', data)


def save_em_data(sender, data, dpg):
    result = RT_DATA.get_all_em_data()
    filtered_data, stats = quick_filter_outliers(result, method='iqr')
    print_outliers_statistics(stats)
    analyze_data_structure(filtered_data)
    try:
        saved_file_path = save_resonator_data_to_excel_smart(filtered_data)
        print(f"✓ Данные успешно сохранены в файл: {saved_file_path}")
        print(f"✓ Папка: {os.path.dirname(saved_file_path)}")

        # Показываем информацию о сохраненных данных
        df = pd.DataFrame({key: value[:2] for key, value in filtered_data.items()
                           if len(value) > 0})  # Берем только первые 2 элемента для демонстрации
        print(f"\n✓ Сохранено параметров: {len(df.columns)}")
        print(f"✓ Длина массивов после обрезки: {min(len(arr) for arr in filtered_data.values() if len(arr) > 0)}")

    except Exception as e:
        print(f"✗ Ошибка при сохранении: {e}")

    result_TCH = RT_DATA.get_temp_data()
    saved_file_path = save_temperature_dependence_to_excel_simple(result_TCH)
    if saved_file_path:
        print(f"✓ Excel отчет успешно создан: {saved_file_path}")
    else:
        print("✗ Не удалось создать Excel отчет")


def print_em_data(sender, data, dpg):
    result = RT_DATA.get_all_em_data()
    filtered_data, stats = quick_filter_outliers(result, method='iqr')
    print_outliers_statistics(stats)
    analyze_data_for_pdf(filtered_data)
    # Сохраняем в PDF
    saved_file_path = save_resonator_data_to_pdf_simple(filtered_data)
    if saved_file_path:
        print(f"✓ PDF отчет успешно создан: {saved_file_path}")
    else:
        print("✗ Не удалось создать PDF отчет")

    result_TCH = RT_DATA.get_temp_data()
    if len(result_TCH) > 3:
        saved_file_path = save_temperature_dependence_simple(result_TCH)
        if saved_file_path:
            print(f"✓ PDF отчет успешно создан: {saved_file_path}")
        else:
            print("✗ Не удалось создать PDF отчет")
    else:
        print("Недостаточно данных для сохранения")



def r_magazine_on_button(sender, data, user_data):
    (dpg, channel, process) = user_data
    r_magazine_all_off()
    button_text = dpg.get_item_label(sender)
    time_type_str = 'EM_time'
    if button_text == 'Включить':
        cure_res = get_resistance()[0]
        RT_DATA.set_current_state_status(False)
        print('Включено')
        RT_DATA.em_measure_ini()
        if process == 'Temp':
            RT_DATA.temp_measure_ini()
            time_type_str = 'Full_time'

        plot_views, plot_ax = RT_DATA.get_plot_names('Время')
        keys_list = list(plot_views.keys())
        current_plot = RT_DATA.get_current_plot_name()
        dpg.configure_item('rt_em_plot_select_view', items=keys_list, default_value=current_plot)
        RT_DATA.set_current_plot_type('Время')

        update_graph_series(dpg, graph_tag='em_graph_plot', x_axis_tag='x_axis_em',
                            y_axis_tag='y_axis_em', plot_type='Время')

        print('Магазин сопротивлений установлен на значение ', cure_res)
        if cure_res != 'NA' and cure_res != 0:
            print('Подключения к каналу магазина сопротивлений ', channel)
            print('Результат', r_magazine_on(channel))
            time.sleep(2)
            print('Подключения мультиметра к каналу  ', channel)

        if RT_Data.RT_DATA.u_timer is None:
            RT_Data.RT_DATA.u_timer = Timer_D(dpg, value_func=RT_DATA.Voltmetr.serial_worker)
            RT_Data.RT_DATA.i_timer = Timer_D(dpg, value_func=RT_DATA.Ampermetr.serial_worker, display='current_val',
                                              data='A')
            RT_Data.RT_DATA.power_timer = Timer_D(dpg, value_func=get_power, display='power_val', data='P')

        result = multimetr_on(channel=channel)
        if result == 'OK':
            # Начинаем запись напряжения на нагревателе
            RT_Data.RT_DATA.u_timer.start()
            RT_Data.RT_DATA.i_timer.start()
            RT_Data.RT_DATA.power_timer.start()
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_3')
            dpg.configure_item(sender, label='Выключить')
        print('Подключения анализатора цепей к каналу  ', channel)
        res_an = analyzer_on(channel)
        print('Результат', res_an)
        time.sleep(1)
        if res_an == 'OK':
            RT_DATA.set_current_channel(channel)
            if len(VNA_Data.VNA_DATA.get_current_measure_spc()) > 0:
                vna = VNA(vna_type=VNA_Data.VNA_DATA.get_vna_type())
                RT_DATA.freq_timer = Timer_D(dpg, value_func=vna.Scan, display='freq_val', data='F', sleep_time=0.1)
                RT_DATA.freq_ppm_timer = Timer_D(dpg, value_func=update_f_ppm_value, display='freq_ppm_val',
                                                 data='F_ppm',
                                                 sleep_time=0.1)
                RT_DATA.freq_r_timer = Timer_D(dpg, value_func=update_R_value, display='R_val', data='R',
                                               sleep_time=0.1)
                vna.set_channel(int(channel))
                # запускаем таймер вывода значений
                RT_DATA.freq_timer.start()
                RT_DATA.freq_ppm_timer.start()
                RT_DATA.freq_r_timer.start()

            else:
                print('Не выбрана спецификация')
                dpg.bind_item_theme(sender, 'Use_button_theme_rt_2')
        if RT_DATA.view_magazine_time_timer is None:
            RT_DATA.view_magazine_time_timer = Timer_D_Multy(dpg, value_func=get_values_timer,
                                                             display_time='rt_tune_current_time',
                                                             sleep_time=0.5, time_storage_var=time_type_str)

        while VNA_DATA.current_F is None:
            time.sleep(0.5)
        res_power = power_on(channel)
        if res_power == 'OK':
            RT_DATA.view_magazine_time_timer.start()

    else:
        dpg.configure_item(sender, label='Включить')
        print('Остановка обновления данных')
        if RT_DATA.view_magazine_time_timer is not None:
            RT_DATA.view_magazine_time_timer.stop()

        if RT_Data.RT_DATA.u_timer is not None:
            RT_Data.RT_DATA.u_timer.stop()
        if RT_Data.RT_DATA.i_timer is not None:
            RT_Data.RT_DATA.i_timer.stop()
        if RT_Data.RT_DATA.power_timer is not None:
            RT_Data.RT_DATA.power_timer.stop()

        if RT_DATA.freq_timer is not None:
            RT_DATA.freq_timer.stop()
        if RT_DATA.freq_ppm_timer is not None:
            RT_DATA.freq_ppm_timer.stop()
        if RT_DATA.freq_r_timer is not None:
            RT_DATA.freq_r_timer.stop()

        print('Выключаем анализатор цепей')
        time.sleep(1)
        res_ann = analyzer_all_off()
        print('Результат', res_ann)
        print('Выключаем мультиметр')
        time.sleep(1)
        result = multimetr_all_off()
        print('Результат', result)
        time.sleep(2)
        print('Отключения магазина сопротивлений ', channel)
        print('Результат', r_magazine_all_off())
        time.sleep(2)
        print('Выключаем магазин сопротивлений')
        print('Результат', off_resistance())
        time.sleep(1)
        print('отключаем питание')
        print('Результат', power_off(channel))
        print('Обнуляем текущие данные')
        RT_DATA.Current_A = None
        RT_DATA.Current_dA = None
        RT_DATA.Current_V = None
        RT_DATA.Current_P = None
        VNA_DATA.current_F = None
        VNA_DATA.current_R = None
        VNA_DATA.current_F_ppm = None
        dpg.set_value('freq_val', '0.0000000')
        dpg.set_value('freq_ppm_val', '0.000')
        dpg.set_value('R_val', '00.0')
        dpg.set_value('voltage_val', '0.00')
        dpg.set_value('current_val', '0.00')
        dpg.set_value('power_val', '0.00')
        dpg.bind_item_theme(sender, 'Use_button_theme_rt_1')
        dpg.configure_item(sender, label='Включить')
    set_button(dpg)



def get_values_timer():
    # Проверка и корректировка значений тока
    if float(RT_DATA.Current_A) > 2000:
        RT_DATA.Current_A = 0
    if float(RT_DATA.Current_P) > 20000:
        RT_DATA.Current_P = 0
    channel = RT_DATA.get_current_channel()
    # Устанавливаем новое значение сопротивления магазина если измерения на прошлом завершено
    if RT_DATA.get_process_status():
        u_data = (RT_DATA.dpg_ref, channel)
        r_dict = RT_DATA.get_current_rm()
        value_r = r_dict['Current'] - r_dict['Step']
        # Проверяем условие окончание измерений
        if value_r < r_dict['End']:
            user_data_temp = (RT_DATA.dpg_ref, channel, 'Temp')
            r_magazine_on_button('rt_tune_start_button', None, user_data_temp)
            result = {
                'rt_tune_current_r': 'NA',
                'rt_tune_current_fhz': '0.0000000',
                'rt_tune_current_fppm': 0,
                'rt_tune_current_u': 0,
                'rt_tune_current_i': 0,
                'rt_tune_current_p': 0,
                'rt_tune_current_time_all': '00:00'
            }
            return result
        else:
            RT_DATA.set_current_state_status(1)
            RT_DATA.dpg_ref.set_value('rt_r_magazine_input_value', int(value_r))
            RT_DATA.set_current_magazine_r(int(value_r))
            set_resistance_value_button(None, None, u_data)
            r_dict['Current'] = value_r
            RT_DATA.set_current_rm(r_dict)
            RT_DATA.set_process_status(False)
            RT_DATA.em_measure_ini()
            time.sleep(5)
    mins, secs = divmod(RT_DATA.get_tune_time(), 60)
    hours, mins = divmod(mins, 60)
    timer_str = f"{int(mins):02d}:{int(secs):02d}"
    # Формирование выходных данных
    result = {
        'rt_tune_current_r': RT_DATA.get_current_magazine_r(),
        'rt_tune_current_fhz': VNA_DATA.current_F,
        'rt_tune_current_fppm': VNA_DATA.current_F_ppm,
        'rt_tune_current_u': RT_DATA.Current_V,
        'rt_tune_current_i': RT_DATA.Current_A,
        'rt_tune_current_p': RT_DATA.Current_P,
        'rt_tune_current_time_all': timer_str
    }

    out_data = {
        'Time': RT_DATA.get_EM_current_time(),
        'Time_All': RT_DATA.get_tune_time(),
        'F(t), Гц': VNA_DATA.current_F,
        'F(t), ppm': VNA_DATA.current_F_ppm,
        'R1(t), Ом': VNA_DATA.current_R,
        'U(t), В': RT_DATA.Current_V,
        'I(t), мА': RT_DATA.Current_A,
        'P(t), мВ': RT_DATA.Current_P,
        'R магазина, Ом': RT_DATA.get_current_magazine_r()
    }
    # Получение текущего значения dA
    current_dA = safe_float(RT_DATA.Current_dA)

    channel_key = f"channel_{int(channel)}"

    # Инициализация истории измерений если нужно
    if not hasattr(RT_DATA, 'dA_history'):
        RT_DATA.dA_history = {}

    if not hasattr(RT_DATA, 'state_history'):
        RT_DATA.state_history = {}

    if not hasattr(RT_DATA, 'current_state'):
        RT_DATA.current_state = {}

    if not hasattr(RT_DATA, 'freq_history'):
        RT_DATA.freq_history = {}

    if channel_key not in RT_DATA.dA_history:
        RT_DATA.dA_history[channel_key] = []

    if channel_key not in RT_DATA.state_history:
        RT_DATA.state_history[channel_key] = []

    if channel_key not in RT_DATA.current_state:
        RT_DATA.current_state[channel_key] = 1  # начальное состояние

    if channel_key not in RT_DATA.freq_history:
        RT_DATA.freq_history[channel_key] = []

    # Добавление текущего значения в историю
    # Проверяем наличие нового измерения
    if RT_DATA.Current_A_Status:
        RT_DATA.dA_history[channel_key].append(current_dA)
        RT_DATA.Current_A_Status = False

    # Добавление текущей частоты в историю
    current_freq = safe_float(VNA_DATA.current_F_ppm)
    # Проверяем наличие нового измерения
    if VNA_DATA.current_F_status:
        RT_DATA.freq_history[channel_key].append(current_freq)
        VNA_DATA.current_F_status = False

    # Поддержание размера истории (последние 3 измерения для dA, 10 для частоты)
    if len(RT_DATA.dA_history[channel_key]) > 10:
        RT_DATA.dA_history[channel_key].pop(0)

    if len(RT_DATA.freq_history[channel_key]) > 5:
        RT_DATA.freq_history[channel_key].pop(0)

    # Вычисление среднего значения dA
    if len(RT_DATA.dA_history[channel_key]) > 0:
        avg_dA = sum(RT_DATA.dA_history[channel_key])
    else:
        avg_dA = current_dA

    # Определение состояния по усредненному dA
    states = [
        (0.05, 10), (0.1, 9), (0.3, 8), (0.5, 7), (1, 6),
        (1.5, 5), (2, 4), (4, 3), (10, 2)
    ]

    target_state_by_current = 1  # значение по умолчанию (самый низкий уровень)
    for threshold, state in states:
        if avg_dA < threshold:
            target_state_by_current = state
            break

    # Определение целевого состояния с учетом стабильности частоты
    target_state = target_state_by_current
    if RT_DATA.get_current_state_status() > 7:
        target_state = RT_DATA.get_current_state_status()
    # Для состояний выше 7 учитываем стабильность частоты
    if target_state_by_current > 7 and len(RT_DATA.freq_history[channel_key]) >= 5:
        # Вычисляем изменение частоты (максимальная разница за последние 10 измерений)
        freq_change = max(RT_DATA.freq_history[channel_key]) - min(RT_DATA.freq_history[channel_key])
        # Определяем состояние на основе стабильности частоты
        if round(freq_change, 4) <= 0.002:
            target_state = 10
            RT_DATA.set_current_state_status(10)
        elif round(freq_change, 4) <= 0.005:
            target_state = 9
            RT_DATA.set_current_state_status(9)
        elif round(freq_change, 4) <= 0.01:
            target_state = 8
            RT_DATA.set_current_state_status(8)
        # Если изменение частоты больше порогов, оставляем состояние по току

    # Добавляем новое состояние в историю состояний
    RT_DATA.state_history[channel_key].append(target_state)

    # Поддерживаем размер истории состояний (последние 10 измерений)
    if len(RT_DATA.state_history[channel_key]) > 10:
        RT_DATA.state_history[channel_key].pop(0)

    # Проверяем, было ли состояние стабильным в течение 10 циклов
    if len(RT_DATA.state_history[channel_key]) >= 10 and target_state > 8:
        # Проверяем, все ли последние 50 состояний одинаковы
        if all(state == target_state for state in RT_DATA.state_history[channel_key]):
            # Проверяем, можно ли изменить состояние на соседнее
            current_state = RT_DATA.current_state[channel_key]
            if abs(target_state - current_state) <= 1:
                # Меняем состояние только если оно соседнее
                RT_DATA.current_state[channel_key] = target_state
                color = get_res_state_color(target_state)
                RT_DATA.dpg_ref.configure_item(f'bg_{int(channel) - 1}', color=color, fill=color)
                RT_DATA.dpg_ref.configure_item(f'slider_{int(channel) - 1}', default_value=target_state)
            else:
                # Меняем состояние только на 1 шаг в направлении целевого состояния
                step = 1 if target_state > current_state else -1
                new_state = current_state + step
                RT_DATA.current_state[channel_key] = new_state
                color = get_res_state_color(new_state)
                RT_DATA.dpg_ref.configure_item(f'bg_{int(channel) - 1}', color=color, fill=color)
                RT_DATA.dpg_ref.configure_item(f'slider_{int(channel) - 1}', default_value=new_state)
        else:
            RT_DATA.current_state[channel_key] = target_state
            color = get_res_state_color(target_state)
            RT_DATA.dpg_ref.configure_item(f'bg_{int(channel) - 1}', color=color, fill=color)
            RT_DATA.dpg_ref.configure_item(f'slider_{int(channel) - 1}', default_value=target_state)
    else:
        RT_DATA.current_state[channel_key] = target_state
        color = get_res_state_color(target_state)
        RT_DATA.dpg_ref.configure_item(f'bg_{int(channel) - 1}', color=color, fill=color)
        RT_DATA.dpg_ref.configure_item(f'slider_{int(channel) - 1}', default_value=target_state)
    # Добавление данных и обновление графика
    RT_DATA.add_em_data_value(out_data)
    update_em_graph(RT_DATA.dpg_ref)
    # Если образец полностью нагрелся
    if target_state == 10 and RT_DATA.get_process_type() == 'Temp' and len(RT_DATA.state_history[channel_key]) >= 10:
        out_data_temp = {
            'Time': RT_DATA.get_EM_current_time(),
            'F(R), ppm': VNA_DATA.current_F_ppm,
            'U(R), В': RT_DATA.Current_V,
            'I(R), мА': RT_DATA.Current_A,
            'P(R), мВ': RT_DATA.Current_P,
            'R1(R), Ом': VNA_DATA.current_R,
            'R магазина, Ом': RT_DATA.current_magazine_R,
            'Time_All': RT_DATA.get_tune_time()
        }

        add_table_TCH_row(RT_DATA.dpg_ref, out_data_temp)

        # Обнуляем время для текущего сопротивления
        RT_DATA.add_temp_data_value(out_data_temp)

        RT_DATA.set_process_status(True)
    return result


def add_table_TCH_row(dpg, data):
    row_n = RT_DATA.get_current_tch_row()

    with dpg.table_row(parent='RT_TCH_table_data', tag=f"RT_TCH_{str(data['R магазина, Ом'])}_row_data"):
        dpg.add_text(str(int(row_n)), tag=f"rt_{str(data['R магазина, Ом'])}_tune_current_N")
        dpg.add_text(str(data['R магазина, Ом']), tag=f"rt_{str(data['R магазина, Ом'])}_tune_current_R")
        dpg.add_text(str(data['F(R), ppm']), tag=f"rt_{str(data['R магазина, Ом'])}_tune_current_fppm")
        dpg.add_text(str(data['U(R), В']), tag=f"rt_{str(data['R магазина, Ом'])}_tune_current_u")
        dpg.add_text(str(data['I(R), мА']), tag=f"rt_{str(data['R магазина, Ом'])}_tune_current_i")
        dpg.add_text(get_time_str(data['Time']), tag=f"rt_{str(data['R магазина, Ом'])}_tune_current_time")
        dpg.add_text(get_time_str(data['Time_All']), tag=f"rt_{str(data['R магазина, Ом'])}_tune_current_time_all")
    RT_DATA.set_current_tch_row(row_n + 1)


def get_time_str(value: float):
    mins, secs = divmod(value, 60)
    hours, mins = divmod(mins, 60)
    return f"{int(mins):02d}:{int(secs):02d}"


def set_resistance_value_button(sender, data, user_data):
    """
    Обработчик нажатия кнопки для установки значения сопротивления.

    Функция получает значение из виджета 'rt_r_magazine_input_value', проверяет его на возможность
    преобразования в целое число, и если всё в порядке и `data` не равно 'NA',
    вызывает функцию `set_resistance` с указанным каналом и значением.

    Args:
        user_data (tuple): Кортеж, содержащий (dpg, channel), где:
            - dpg: Объект Dear PyGui.
            - channel: Канал, к которому применяется сопротивление.

    Returns:
        None: Функция ничего не возвращает, но может выводить сообщения об ошибках.
    """
    (dpg, channel) = user_data
    r_value = dpg.get_value('rt_r_magazine_input_value')
    if r_value is not None:
        try:
            r_value = int(str(r_value))
        except ValueError:
            # Обработка случая, когда r_value не может быть преобразовано в int
            print(f"Ошибка: '{r_value}' нельзя преобразовать в целое число.")
            # Устанавливаем индикатор ошибки (крестик)
            dpg.set_value('rt_r_magazine_set_indicator', "NA")
            dpg.set_value('rt_r_magazine_input_value', "NA")
            return 'NA'
        data = dpg.get_value('rt_r_magazine_input_value')
        if data != 'NA':
            result = set_resistance(r_value)
            if result == 'OK':
                c_r = get_resistance()
                dpg.set_value('rt_r_magazine_input_value', c_r[0])
                # Устанавливаем индикатор успеха (галочка)
                dpg.set_value('rt_r_magazine_set_indicator', "OK")
                return c_r[0]
            else:
                return 'NA'

    else:
        print("Ошибка: значение r_value равно None.")
        # Устанавливаем индикатор ошибки (крестик)
        dpg.set_value('rt_r_magazine_set_indicator', "NA")
        return 'NA'
