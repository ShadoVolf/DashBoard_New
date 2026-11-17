import time

from Options import get_current_time
from Pribory.Network_Analyzer import VNA_Data
from Pribory.Network_Analyzer.VNA import VNA
from RT.RT_TECH_Parameters.Multimetr_use import control_ui_timer, ui_timer_init
from RT.RT_TECH_Parameters.RT_Data import RT_DATA
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Control_Manual import set_button
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Freq_Window import measure, update_measure_value
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_View_Status import set_lamp_state
from RT.RT_TECH_Parameters.switch_use import multimetr_on, power_on, multimetr_all_off, power_off, analyzer_on
from Utils.Thread_timer_work import Timer_Work
from Utils.math_functions_user import safe_float


def create_control_panel_rt_manual__regime_window(dpg):
    with dpg.window(label="Панель управления", width=525, height=190, pos=(1350, 895),
                    tag='result_RT_manual_control_regime_Panel'):
        with dpg.theme(tag='Use_button_theme_rt_regime'):
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
        with dpg.theme(tag='Use_button_theme_rt_regime_1'):
            with dpg.theme_component(dpg.mvButton):
                # Устанавливаем цвет фона кнопки
                dpg.add_theme_color(dpg.mvThemeCol_Button, (135, 206, 250, 80),
                                    )  # Красный
                # Цвет при наведении
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (135, 206, 250, 120),
                                    )  # Желтый
                # Цвет при нажатии
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (135, 206, 250, 150))
                # Настройка закругления углов (радиус 5px)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 20)
        with dpg.theme(tag='Use_button_theme_green_regime_1'):
            with dpg.theme_component(dpg.mvButton):
                # Основной цвет кнопки (светло-зеленый)
                dpg.add_theme_color(dpg.mvThemeCol_Button, (144, 238, 144, 80))
                # Цвет при наведении (более насыщенный)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (144, 238, 144, 120))
                # Цвет при нажатии (самый насыщенный)
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (144, 238, 144, 150))
                # Закругление углов (радиус 20px)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 20)

        dpg.add_combo(label='Режим работы',
                      items=['Измерение', 'Измерение с нагревом', 'Выход на режим', 'Поиск экстремума'],
                      default_value='Нет')
        dpg.add_separator()
        dpg.add_separator()

        dpg.add_text("Статус измерения:")
        dpg.add_text('Остановка')
        dpg.add_spacer(height=50)
        with dpg.group(horizontal=True, horizontal_spacing=70, width=150):
            dpg.add_text('Запуск измерения')
            btn = dpg.add_button(label='Старт', tag=f"Start_button", callback=start_measure,
                                 user_data=dpg)
            timer_display = dpg.add_text("00:00", tag='timer_work_view')
            # Инициализируем контроллер
            # timer = Timer_Controller(dpg, btn, timer_display)
            dpg.bind_item_theme('Start_button', 'Use_button_theme_green_regime_1')


# Выполнение нагрева
def start_hit(dpg):
    # Получаем данные по номерам резонаторов
    data = RT_DATA.get_rt_numbers()
    # Получаем номер текущего канала
    channel = RT_DATA.get_current_channel() + 1
    if channel <= 5:
        RT_DATA.set_current_channel(channel)
        # Получаем данные текущего номера
        row_dict = data[str(int(channel))]
        if row_dict is not None:
            Serial_N = row_dict['Serial']
            use = row_dict['Use']
            # Если номер активен
            if use:
                print('Включение канала ', channel)
                # Запускаем таймеры
                # ui_timer_init(dpg)
                # Подключаем мультиметр на текущий канал
                result = multimetr_on(channel=channel)
                # Пауза для стабилизации после переключения
                time.sleep(2)
                if result == 'OK':
                    # Начинаем запись напряжения на нагревателе
                    # control_ui_timer('Start')
                    # Включаем питание элемента
                    res_power = power_on(channel=channel)
                    row_dict['Status'] = 'Прогрев'
                    if res_power == 'OK':
                        print("Подключен канал ", channel, "Резонатор № ", Serial_N, 'Время запуска ',
                              get_current_time())
                        # Нажимаем кнопки
                        set_button(dpg, lamp_state=False)
                        # Зажигаем индикатор прогрева
                        set_lamp_state(channel, 1, dpg)
                        # пауза стабилизации значений
                        time.sleep(10)
                        print('Ожидание выхода на режим...')
                        while safe_float(RT_DATA.Current_A) >= 60:
                            time.sleep(1)
                        # Отключаем показ значений
                        # control_ui_timer('Stop')
                        # Устанавливаем статус нагрева резонатора на 2
                        set_lamp_state(channel, 2, dpg)
                        data[channel] = row_dict
                        RT_DATA.set_rt_numbers(data)
                        set_button(dpg, lamp_state=False)
    else:
        RT_DATA.set_current_channel(0)
        RT_DATA.set_work_status('Нагрев')


# Функция запуска процесса измерений
def start_measure(sender, data, dpg):
    RT_DATA.dpg_ref = dpg
    channel = RT_DATA.set_current_channel(0)
    work_status = False
    RT_DATA.a_history_init()
    if not hasattr(RT_DATA, 'current_state'):
        RT_DATA.current_state = {}
    if dpg.get_item_label(f"Start_button") == 'Старт':
        work_status = True
        dpg.configure_item(f"Start_button", label='Стоп')
    else:
        work_status = False
        dpg.configure_item(f"Start_button", label='Старт')
    if work_status:
        # обновляем статус измерения позиций
        RT_DATA.rt_numbers_init()
        # инициализируем таймер процесса
        RT_DATA.work_timer = Timer_Work(dpg, value_func=work_process,
                                        display_time='timer_work_view',
                                        sleep_time=0.5,
                                        time_storage_var='Work_time')
        RT_DATA.work_timer_time = Timer_Work(dpg, value_func=work_process_time,
                                             display_time='timer_work_view',
                                             sleep_time=0.3,
                                             time_storage_var='Work_time')
        # Инициализируем таймер мультиметра
        ui_timer_init(dpg)
        # Запускаем сканирование данных для мультиметра
        control_ui_timer('Start')
        time.sleep(5)
        # Запускаем процесс измерений
        RT_DATA.work_timer.start()
        RT_DATA.work_timer_time.start()
    else:
        # Останавливаем процесс измерения
        stop_work(dpg, but=False)


# Остановка процесса измерения
def stop_work(dpg, but=True):
    # Останавливаем таймер процесса
    RT_DATA.work_timer_time.stop()
    RT_DATA.work_timer.stop()
    time.sleep(5)
    # Останавливаем таймеры опроса мультиметра
    control_ui_timer('Stop')
    time.sleep(2)
    # Выключаем мультиметр
    multimetr_all_off()
    if but:
        print('Остановлено', get_current_time())
    else:
        print("Завершено", get_current_time())
    # Возвращаем кнопку в исходное состояние
    dpg.configure_item(f"Start_button", label='Старт')
    # Отключаем питание
    data = RT_DATA.get_rt_numbers()
    for key in data.keys():
        temp_value = data[key]
        if len(temp_value) > 0:
            if temp_value['Use']:
                power_off(int(key))
                set_lamp_state(int(key), 0, dpg)
                print('отключено питание канал', key)
    # Устанавливаем корректное состояние кнопок ручного контроля
    RT_DATA.set_work_status('N/A')
    RT_DATA.work_timer_time.stop()
    set_button(dpg, lamp_state=False)


# Функция выполнения процесса измерения
def work_process():
    # Получаем текущий контекст графики
    dpg = RT_DATA.dpg_ref
    # Если статус измерения не установлен ставим его в 'Включение'
    if RT_DATA.get_work_status() == 'N/A':
        RT_DATA.set_work_status('Включение')

    if RT_DATA.get_work_status() == 'Включение':
        start_hit(dpg)
    elif RT_DATA.get_work_status() == 'Нагрев':
        hit_measure(dpg)
    elif RT_DATA.get_work_status() == 'Измерение':
        measure_parameters(dpg)
    else:
        stop_work(dpg, but=False)
        return "Завершено"


# Функция регистрация времени процесса измерений
def work_process_time():
    dpg = RT_DATA.dpg_ref
    # Выводим время работы на панель
    mins, secs = divmod(RT_DATA.get_work_time(), 60)
    hours, mins = divmod(mins, 60)
    timer_str = f"{int(mins):02d}:{int(secs):02d}"
    dpg.set_value('timer_work_view', timer_str)


# Функция обеспечивающая прогрев резонаторов
def hit_measure(dpg):
    # Получаем данные по номерам резонаторов
    data = RT_DATA.get_rt_numbers()
    # Получаем номер текущего канала
    channel = RT_DATA.get_current_channel() + 1
    if channel <= 5:
        RT_DATA.set_current_channel(channel)
        # Получаем данные текущего номера
        row_dict = data[str(int(channel))]
        use = row_dict['Use']
        if use:
            result = multimetr_on(channel=channel)
            set_button(dpg, lamp_state=False)
            time.sleep(10)
            print('Чтение данных, канал', channel)
            print(RT_DATA.A_history)
            if channel in RT_DATA.A_history.keys() and len(RT_DATA.A_history[channel]) >= 1:
                print(RT_DATA.Current_A, RT_DATA.last_A_Value[channel])
                da = safe_float(RT_DATA.Current_A) - safe_float(RT_DATA.last_A_Value[channel])
                if channel not in RT_DATA.dA_history.keys():
                    RT_DATA.dA_history[channel] = []
                    RT_DATA.dA_history[channel].append(da)
                    RT_DATA.A_history[channel].append(RT_DATA.Current_A)
                    RT_DATA.last_A_Value[channel] = RT_DATA.Current_A
                    states = [
                        (0.5, 10), (1, 9), (2, 8), (3, 7), (5, 6),
                        (7, 5), (8, 4), (10, 3), (20, 2)
                    ]

                    target_state_by_current = 1  # значение по умолчанию (самый низкий уровень)
                    for threshold, state in states:
                        if da < threshold:
                            target_state_by_current = state
                            break
                    print('Текущая разница тока', da)
                    print('Состояние', target_state_by_current)
                    set_lamp_state(channel, target_state_by_current, dpg)
                    if target_state_by_current >= 10:
                        row_dict['Status'] = 'Измерение'
                    finish = all(
                        'Status' in row_dict and row_dict['Status'] in ['NA', 'Измерение']
                        for row_dict in data.values()
                    )
                    print('Finish', finish)
                    if finish:
                        RT_DATA.set_work_status('Измерение')
                        RT_DATA.set_current_channel(0)
            else:
                print('Подготовка данных', channel)
                RT_DATA.last_A_Value[channel] = RT_DATA.Current_A
                if channel not in RT_DATA.A_history.keys():
                    RT_DATA.A_history[channel] = []
                RT_DATA.A_history[channel].append(RT_DATA.Current_A)
    else:
        RT_DATA.set_current_channel(0)


# Функция выполняющая измерения резонаторов
def measure_parameters(dpg):
    # Получаем данные по номерам резонаторов
    data = RT_DATA.get_rt_numbers()
    # Получаем номер текущего канала
    channel = RT_DATA.get_current_channel() + 1
    if channel <= 5:
        RT_DATA.set_current_channel(channel)
        # Получаем данные текущего номера
        row_dict = data[str(int(channel))]
        if row_dict is not None:
            Serial_N = row_dict['Serial']
            use = row_dict['Use']
            # Если номер активен
            if use:
                print('Подключаем канал №', channel)
                # Подключаем мультиметр
                result = multimetr_on(channel=channel)
                time.sleep(2)
                set_button(dpg, lamp_state=False)
                result = analyzer_on(channel=RT_DATA.get_current_channel())
                time.sleep(5)
                if result == 'OK':
                    vna = VNA(vna_type=VNA_Data.VNA_DATA.get_vna_type(), channel=channel)
                    vna.measure(int(channel))
                    data_out = VNA_Data.VNA_DATA.get_measure_data()
                    out = {'Freq': format(data_out['Freq'], '.3f'),
                           'F_ppm': format(data_out['F_ppm'], '.3f'),
                           'R': format(data_out['R'], '.1f'),
                           'C0': format(data_out['C0'] * 1E+12, '.3f'),
                           'C1': format(data_out['C1'] * 1E+15, '.3f'),
                           'L1': format(data_out['L1'] * 1E+3, '.3f'),
                           'Q': format(data_out['Q'] * 1E+3, '.1f'),
                           'U': RT_DATA.Current_V,
                           'I': RT_DATA.Current_A,
                           'P': RT_DATA.Current_P}
                    update_measure_value(dpg)
                    row_dict['Result'] = out
                    row_dict['Status'] = 'Завершено'
                    data[channel] = row_dict
                    RT_DATA.set_rt_numbers(data)
                else:
                    print('Не включился канал подключения анализатора', RT_DATA.get_current_channel())
    else:
        RT_DATA.set_current_channel(0)
        print(RT_DATA.get_rt_numbers())
        RT_DATA.set_work_status('Завершено')
