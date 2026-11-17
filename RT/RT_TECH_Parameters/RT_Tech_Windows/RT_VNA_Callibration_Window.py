import mysql.connector
import pandas as pd
from sqlalchemy import text, create_engine

from Options import center_window, get_connection_string, parse_connection_string
from Pribory.Network_Analyzer.VNA import VNA
from Pribory.Network_Analyzer.VNA_Calibration_Message_Window import show_calibration_dialog
from Pribory.Network_Analyzer.VNA_Data import VNA_DATA
from Pribory.Network_Analyzer.Vna_Options import generate_filter_values, convert_to_hz, int_to_freq_str, parse_freq_band
from RT.RT_TECH_Parameters.RT_Data import RT_DATA
from RT.RT_TECH_Parameters.switch_use import get_analyzer_channels, analyzer_on, analyzer_all_off


# Создает окно управления калибровкой анализатора цепей
def create_vna_call_window(sender, data, dpg):
    dpg.delete_item('vna_cal_table_view')
    dpg.delete_item('progress_bar_theme')
    dpg.delete_item('RT_VNA_Call_Window')
    data_cal = get_calibration_data()
    print(data_cal)
    freq_band = data_cal['calibration_freq'].iloc[0]
    call_span = data_cal['calibration_span'].iloc[0]
    call_n = data_cal['N'].iloc[0]
    call_power = data_cal['Power_R'].iloc[0]
    filtr_str = int_to_freq_str(data_cal['Filtr'].iloc[0])
    print('Freq_band', freq_band)
    ch_list, freq_view_band = view_callibration_data()
    with dpg.window(
            label="Калибровка векторного анализатора цепей",
            width=890,
            height=390,
            tag='RT_VNA_Call_Window',
            modal=False,
            no_close=False
    ):
        '''
        # Создаем тему для стилизации
        with dpg.theme(tag='progress_bar_theme'):
            with dpg.theme_component(dpg.mvProgressBar):
                dpg.add_theme_color(dpg.mvThemeCol_PlotHistogram, (56, 189, 113))
                dpg.add_theme_style(dpg.mvPlotStyleVar_PlotPadding, 0, 0)
        '''
        # Основная группа с отступами
        with dpg.group(horizontal=False, width=850):
            dpg.add_spacer(height=5)
            dpg.add_text("Параметры калибровки", color=(220, 220, 220))

            # Контейнер для параметров
            with dpg.group(width=850):
                # Создаем столбцы: 400px для меток, 400px для элементов управления
                with dpg.table(header_row=False, row_background=True,
                               borders_innerH=True, borders_outerH=True, borders_innerV=True,
                               borders_outerV=True, width=850, tag='vna_cal_table_view'):
                    dpg.add_table_column(width_fixed=True, width=400)
                    dpg.add_table_column(width_fixed=True, width=350)
                    dpg.add_table_column(width_fixed=True, width=120)

                    # Диапазон частот
                    with dpg.table_row():
                        dpg.add_text("Диапазон частот калибровки:")
                        dpg.add_input_text(default_value=freq_band, tag="freq_range")
                        dpg.add_text('МГц', tag="freq_range_units")

                    # Полоса калибровки
                    with dpg.table_row():
                        dpg.add_text("Полоса калибровки:")
                        dpg.add_input_text(default_value=call_span, tag="cal_bandwidth")
                        dpg.add_text('МГц', tag="cal_bandwidth_units")

                    # Количество точек
                    with dpg.table_row():
                        dpg.add_text("Количество точек в полосе калибровки:")
                        dpg.add_input_text(default_value=call_n, tag="points_count")
                    # Мощность
                    with dpg.table_row():
                        dpg.add_text("Мощность калибровки, мкВт, (R)")
                        dpg.add_input_text(default_value=call_power, tag="power_r_value")

                    # Фильтр ПЧ
                    with dpg.table_row():
                        dpg.add_text("Фильтр ПЧ:")
                        dpg.add_combo(tag="if_filter", items=generate_filter_values(), default_value=filtr_str,
                                      width=380)
                        dpg.add_button(label='Сохранить', width=120, callback=save_cal_parameters, user_data=dpg)
                    with dpg.table_row():
                        dpg.add_text("Загрузка калибровки:")
                    with dpg.table_row():
                        dpg.add_text("Диапазон калибровки")
                        dpg.add_text(freq_view_band, tag='cal_freq_')
                    with dpg.table_row():
                        dpg.add_text("Канал")
                        if len(ch_list) > 0:
                            dpg.add_combo(tag="ch_cal_sel", items=ch_list, default_value=ch_list[0],
                                          width=380)
                        else:
                            dpg.add_combo(tag="ch_cal_sel", items=[], default_value='',
                                          width=380)
                    with dpg.table_row():
                        dpg.add_text("Номинал:")
                        dpg.add_input_text(default_value='10', tag="cal_freq_value_test")
                        dpg.add_button(label="Загрузить", callback=load_calibration,
                                       user_data=dpg, width=120)
            # Кнопка калибровки
            dpg.add_spacer(height=10)
            dpg.add_button(label="Начать калибровку", width=150, height=30, callback=start_calibration,
                           user_data=dpg, tag='cal_start_button')
            # Прогресс-бар с зеленым стилем
            dpg.add_spacer(height=15)
            with dpg.group(horizontal=True):
                progress_bar = dpg.add_progress_bar(
                    tag="calibration_progress",
                    default_value=0.0,
                    width=500
                )

            # Статус калибровки
            dpg.add_spacer(height=5)
            dpg.add_text("Статус: Ожидание начала", tag="progress_status", color=(100, 255, 100))

        # Применяем тему к прогресс-бару
        dpg.bind_item_theme(progress_bar, 'progress_bar_theme')
    if len(data_cal) > 0:
        dpg.set_value('progress_status', 'Статус: Параметры загружены')
    center_window(dpg, 'RT_VNA_Call_Window')


# Загружает данные калибровки в анализатор цепей
def load_calibration(sender, data, dpg):
    print('Begin Load calibration')
    vna = VNA(vna_type=VNA_DATA.get_vna_type())
    nominal_str = dpg.get_value('cal_freq_value_test')
    channel_str = dpg.get_value('ch_cal_sel')
    vna.load_call_short(float(nominal_str), int(channel_str))


# Находит все имеющиеся фалы калибровки и выводит список каналов, а также диапазон калибровки
def view_callibration_data():
    vna = VNA(vna_type=VNA_DATA.get_vna_type())
    return vna.find_calibration_data()


# Получает данные калибровки из БД
def get_calibration_data():
    """
    Извлекает данные из таблицы tr1300_id для текущего значения TR1300_ID.

    Источник TR1300_ID: RT_DATA.get_vna_id()

    Возвращает:
    - pd.DataFrame: DataFrame с колонками calibration_freq, calibration_span, N, Filtr.
    """
    tr1300_id = VNA_DATA.get_vna_id()

    if not tr1300_id:
        print("TR1300_ID не задан. Прерываем выполнение.")
        return pd.DataFrame()

    connection_string = get_connection_string()
    engine = create_engine(connection_string)

    query = text("""
        SELECT 
            calibration_freq, 
            calibration_span, 
            N, 
            Filtr, Power_R 
        FROM tr1300_id
        WHERE TR1300_ID = :tr_id
    """)

    try:
        with engine.connect() as connection:
            df = pd.read_sql(query, connection, params={"tr_id": tr1300_id})
        return df
    except Exception as e:
        print(f"Ошибка при выполнении запроса к БД: {e}")
        return pd.DataFrame()
    finally:
        engine.dispose()


# Сохранения параметров калибровки
def save_cal_parameters(sender, data, dpg):
    # Получаем данные из интерфейса
    par = get_cal_parameters(dpg)
    # Получаем номер анализатора цепей
    tr1300_id = VNA_DATA.get_vna_id()
    conn = None
    cursor = None
    try:
        params = parse_connection_string()
        conn = mysql.connector.connect(**params)
        cursor = conn.cursor()

        # SQL-запрос для вставки данных
        query = """
            UPDATE tr1300_id
            SET
                calibration_freq = %s,
                calibration_span = %s,
                N = %s,
                Filtr = %s,
                Power_R = %s
            WHERE TR1300_ID = %s;
        """
        values = (par['Freq_Band_str'], par['Cal_band'], par['Points'], par['Filtr_PH'], par['Power'], tr1300_id)
        cursor.execute(query, values)  # Добавлен параметр values
        dpg.set_value('progress_status', 'Статус: Параметры сохранены')
        conn.commit()
    finally:
        # Корректное закрытие ресурсов
        if cursor is not None:
            cursor.close()
        if conn is not None and conn.is_connected():
            conn.close()


# Получает данные калибровки из интерфейса
def get_cal_parameters(dpg):
    # Получаем данные из интерфейса
    freq_range = dpg.get_value("freq_range")
    cal_bandwidth = dpg.get_value("cal_bandwidth")
    points_count = dpg.get_value("points_count")
    filter_str = dpg.get_value("if_filter")
    power_str = dpg.get_value("power_r_value")
    # Преобразуем значение фильтра в строку
    filter_hz = convert_to_hz(filter_str)
    freq_range_dict = parse_freq_band(freq_range)
    parameters = {'Freq_Band': freq_range_dict,
                  'Freq_Band_str': freq_range,
                  'Cal_band': cal_bandwidth,
                  'Points': points_count,
                  'Filtr_PH': filter_hz,
                  'Power': power_str}
    return parameters


# Функция запуска калибровки
def start_calibration(sender, data, dpg):
    RT_DATA.set_current_channel(1)
    RT_DATA.set_calibration_status(True)
    dpg.configure_item("cal_start_button", enabled=False)
    run_calibration(dpg, 'continue')


# Функция выполнения калибровки
def run_calibration(dpg, status):
    current_channel = RT_DATA.get_current_channel()
    ch_count = get_analyzer_channels()
    # Проверяем, завершена ли калибровка всех каналов

    if status == 'continue':
        # Выполняем калибровку текущего канала
        dpg.set_value("progress_status", f"Калибровка канала {current_channel}...")
        params = get_cal_parameters(dpg)
        analyzer_all_off()
        vna = VNA(vna_type=VNA_DATA.get_vna_type())
        channel_select(dpg)
        vna.perform_calibration(dpg, params['Freq_Band'], 'calibration_progress',
                                'progress_status',
                                bandwidth=params['Cal_band'], n_points=params['Points'],
                                filtr=params['Filtr_PH'], power=params['Power'], channel_name=current_channel)
    if current_channel >= ch_count:
        finish_calibration(dpg)
        return
    # Показываем диалог подтверждения
    show_calibration_dialog(current_channel, ch_count, on_choice_made, dpg)


# Функция окончания калибровки
def finish_calibration(dpg):
    RT_DATA.set_calibration_status(False)
    dpg.configure_item("cal_start_button", enabled=True)
    RT_DATA.set_current_channel(0)
    channel_select(dpg)
    dpg.set_value("progress_status", "Калибровка всех каналов завершена!")



# Функция выбора реакции на продолжение калибровки
def on_choice_made(choice, dpg):
    """
        Обрабатывает выбор пользователя в процессе калибровки каналов анализатора.

        В зависимости от выбора пользователя (продолжить, пропустить, отменить)
        выполняет соответствующие действия с текущим каналом и обновляет
        статус калибровки в интерфейсе.

        Args:
            choice (str): Выбор пользователя - "continue", "skip" или "cancel"
            dpg: Объект Dear PyGui для управления элементами интерфейса

        Returns:
            None
        """
    current_channel = RT_DATA.get_current_channel()
    ch_count = get_analyzer_channels()
    if choice == "continue":
        # Выполняем калибровку текущего канала
        dpg.set_value("progress_status", f"Канал {current_channel + 1} откалиброван.")
        RT_DATA.set_current_channel(current_channel + 1)
        run_calibration(dpg, choice)
    elif choice == "skip":
        # Пропускаем текущий канал
        dpg.set_value("progress_status", f"Канал {current_channel + 1} пропущен.")
        print(f"Канал {current_channel + 1} пропущен.")
        RT_DATA.set_current_channel(current_channel + 1)
        run_calibration(dpg, choice)
    elif choice == "cancel":
        # Отменяем калибровку
        RT_DATA.set_calibration_status(False)
        dpg.configure_item("cal_start_button", enabled=True)
        dpg.set_value("progress_status", "Калибровка прервана.")
        print('Калибровка прервана.')
        RT_DATA.set_current_channel(0)
        channel_select(dpg)


# Включает выбранный канал анализатора
def channel_select(dpg):
    """
        Обновляет интерфейс выбора каналов анализатора сети.

        Функция определяет текущий активный канал, обновляет состояние кнопок,
        ползунков и цветовую индикацию для всех доступных каналов анализатора.

        Args:
            dpg: Объект Dear PyGui для управления элементами интерфейса

        Returns:
            None
        """
    current_channel = RT_DATA.get_current_channel()
    ch_count = get_analyzer_channels()
    if current_channel != 0:
        result = analyzer_on(current_channel)
    else:
        result = 'ERROR'

    slot = 0
    for i in range(1, ch_count + 1):
        is_current = int(dpg.get_value(f'Channel_select_{i}')) == current_channel
        button_id = f"Network_Analyzer_{i}_button"
        slider_id = f'slider_{i - 1}'
        bg_id = f'bg_{i - 1}'

        # Установка значений и цветов
        value = 1 if is_current else 0
        dpg.configure_item(slider_id, default_value=value)

        # Расчет цвета
        color = [0, 0, 0, 128] if value == 0 else [
            int((1 - (value - 1) / 9.0) * 255),
            int(((value - 1) / 9.0) * 255),
            0,
            128
        ]
        dpg.configure_item(bg_id, color=color, fill=color)

        # Обновление кнопки
        if is_current:
            button_text = 'Анализатор(Выкл)' if dpg.get_item_label(
                button_id) == 'Анализатор(Вкл)' else 'Анализатор(Выкл)'
            dpg.configure_item(button_id, label=button_text)
            slot = i
        else:
            dpg.configure_item(button_id, label='Анализатор(Вкл)')
            dpg.bind_item_theme(button_id, 'Use_button_theme_rt_1')

    # Установка темы для активного слота
    if 'slot' in locals() and slot != 0:
        theme = 'Use_button_theme_rt_3' if result == 'OK' else 'Use_button_theme_rt_2'
        dpg.bind_item_theme(f"Network_Analyzer_{slot}_button", theme)
