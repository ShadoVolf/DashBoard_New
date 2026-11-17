from Pribory.Multimetr.VoltmeterController import VoltmeterController_Multy
from Pribory.Network_Analyzer import VNA_Data
from Pribory.Network_Analyzer.VNA import VNA
from RT.RT_TECH_Parameters.Multimetr_use import Multimetr_test, get_power
from RT.RT_TECH_Parameters.RT_Data import RT_DATA, get_system_options, get_options_by_id
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Freq_Window import update_measure_value, update_f_ppm_value, \
    update_R_value
from RT.RT_TECH_Parameters.switch_use import power_on, power_off, analyzer_off, analyzer_on, get_rele_state, \
    multimetr_on, multimetr_off
from Utils.Thread_timer import Timer_D


def create_control_panel_rt_manual_window(dpg):
    system_id = get_system_options()
    df = get_options_by_id(system_id['тип'], system_id['идентификатор']).copy()
    for index, row in df.iterrows():
        if row['Type'] == 'Мультиметр':
            if row['Address'] == 'VOLT':
                # RT_DATA.Voltmetr = VoltmeterController(port=row['Port'], multy_type='VOLT', emulate=row['Emulate'])
                RT_DATA.Voltmetr = VoltmeterController_Multy(device_name=row['Name'], device_params={
                    'port': row['Port']},
                                                             measurement_type=row['Address'], emulate=row['Emulate'])
            elif row['Address'] == 'AMP':
                # RT_DATA.Ampermetr = VoltmeterController(port=row['Port'], multy_type='AMP', emulate=row['Emulate'])
                RT_DATA.Ampermetr = VoltmeterController_Multy(device_name=row['Name'], device_params={
                    'port': row['Port']},
                                                              measurement_type=row['Address'], emulate=row['Emulate'])
    # Активируем таймеры для мультиметров
    tt_V = Timer_D(dpg, value_func=RT_DATA.Voltmetr.serial_worker)
    tt_A = Timer_D(dpg, value_func=RT_DATA.Ampermetr.serial_worker, display='current_val',
                   data='A')
    tt_P = Timer_D(dpg, value_func=get_power, display='power_val', data='P')
    # Активируем таймеры для анализатора цепей
    with dpg.window(label="Панель управления", width=870, height=190, pos=(450, 895), tag='result_RT_manual_Panel'):
        '''
        with dpg.theme(tag='Use_button_theme_rt'):
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
        with dpg.theme(tag='Use_button_theme_rt_1'):
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
        with dpg.theme(tag='Use_button_theme_rt_2'):
            with dpg.theme_component(dpg.mvButton):
                # Устанавливаем цвет фона кнопки
                dpg.add_theme_color(dpg.mvThemeCol_Button, (204, 153, 255, 80),
                                    )  # Красный
                # Цвет при наведении
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (204, 153, 255, 120),
                                    )  # Желтый
                # Цвет при нажатии
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (204, 153, 255, 150))
                # Настройка закругления углов (радиус 5px)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 20)
        with dpg.theme(tag='Use_button_theme_rt_3'):
            with dpg.theme_component(dpg.mvButton):
                # Устанавливаем цвет фона кнопки
                dpg.add_theme_color(dpg.mvThemeCol_Button, (127, 255, 212, 80),
                                    )  # Красный
                # Цвет при наведении
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (127, 255, 212, 120),
                                    )  # Желтый
                # Цвет при нажатии
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (127, 255, 212, 150))
                # Настройка закругления углов (радиус 5px)
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 20)
        '''
        with dpg.group(horizontal=True, horizontal_spacing=25, width=150):
            for j in range(1, 6):
                with dpg.group(width=150):
                    dpg.add_text('Канал')
                    dpg.add_combo(items=[str(i) for i in range(1, 6)], default_value=str(j),
                                  tag=f'Channel_select_{j}')
                    dpg.add_spacer(height=5)
                    dpg.add_button(label='Вкл', tag=f"Power_{j}_button",
                                   callback=set_power,
                                   user_data=dpg)
                    dpg.bind_item_theme(f"Power_{j}_button", 'Use_button_theme_rt')
                    dpg.add_separator()
                    dpg.add_button(label='Мультиметр(Вкл)', tag=f"V_{j}_button",
                                   user_data=dpg,
                                   callback=set_multimetr)
                    dpg.bind_item_theme(f"V_{j}_button", 'Use_button_theme_rt_1')
                    dpg.set_item_user_data(f"V_{j}_button", [dpg, tt_V, tt_A, tt_P])
                    dpg.add_button(label='Анализатор(Вкл)', tag=f"Network_Analyzer_{j}_button",
                                   user_data=dpg,
                                   callback=set_analazer)
                    dpg.bind_item_theme(f"Network_Analyzer_{j}_button", 'Use_button_theme_rt_1')


# Обратный вызов для кнопки включения питания канала
def set_power(sender, data, dpg):
    result = str(sender).split('_')  # Получаем таг и разделяем его выделяя номер партии
    slot = result[1]
    chanel = dpg.get_value(f'Channel_select_{slot}')
    button_text = dpg.get_item_label(sender)
    if button_text == 'Вкл':
        result = power_on(chanel)
        dpg.configure_item(f'slider_{int(slot) - 1}', default_value=1)
        # Обновление цвета
        dpg.configure_item(f'bg_{int(slot) - 1}', color=get_res_state_color(1), fill=get_res_state_color(1))
        dpg.configure_item(sender, label='Отключить')
        if result == 'OK':
            RT_DATA.set_current_channel(chanel)
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_3')
        else:
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_2')
    else:
        result = power_off(chanel)
        # Обновление цвета
        dpg.configure_item(f'slider_{int(slot) - 1}', default_value=0)
        dpg.configure_item(f'bg_{int(slot) - 1}', color=get_res_state_color(0), fill=get_res_state_color(0))
        if result == 'OK':
            dpg.bind_item_theme(sender, 'Use_button_theme_rt')
        else:
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_2')
        dpg.configure_item(sender, label='Вкл')


# Получает цвет для состояния резонатора
def get_res_state_color(value: int):
    if value == 0:
        color = [0, 0, 0, 128]
    else:
        ratio = (value - 1) / 9.0
        color = [
            int((1 - ratio) * 255),
            int(ratio * 255),
            0,
            128
        ]
    return color


# Обратный вызов для кнопки подключения анализатора цепей
def set_analazer(sender, data, user_data):
    dpg = user_data
    result = str(sender).split('_')  # Получаем таг и разделяем его выделяя номер партии
    slot = result[2]
    chanel = dpg.get_value(f'Channel_select_{slot}')
    button_text = dpg.get_item_label(sender)
    if button_text == 'Анализатор(Вкл)':
        result = analyzer_on(chanel)
        dpg.configure_item(sender, label='Анализатор(Выкл)')

        if result == 'OK':
            RT_DATA.set_current_channel(chanel)
            vna = VNA(vna_type=VNA_Data.VNA_DATA.get_vna_type())
            RT_DATA.freq_timer = Timer_D(dpg, value_func=vna.Scan, display='freq_val', data='F', sleep_time=0.1)
            RT_DATA.freq_ppm_timer = Timer_D(dpg, value_func=update_f_ppm_value, display='freq_ppm_val', data='F_ppm',
                                             sleep_time=0.1)
            RT_DATA.freq_r_timer = Timer_D(dpg, value_func=update_R_value, display='R_val', data='R', sleep_time=0.1)
            vna.set_channel(int(chanel))
            RT_DATA.freq_timer.start()
            RT_DATA.freq_ppm_timer.start()
            RT_DATA.freq_r_timer.start()
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_3')
        else:
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_2')
    else:
        if RT_DATA.freq_timer is not None:
            RT_DATA.freq_timer.stop()
            RT_DATA.freq_ppm_timer.stop()
            RT_DATA.freq_r_timer.stop()
        result = analyzer_off(chanel)

        if result == 'OK':
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_1')
        else:
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_2')
        dpg.configure_item(sender, label='Анализатор(Вкл)')
    set_button(dpg)


# обратный вызов для кнопки включения мультиметра
def set_multimetr(sender, data, user_data):
    '''
    RT_DATA.Voltmetr_timer = Timer_Controller_(dpg, display_tag='voltage_val', button_tag=f"V_{j}_button",
                                           value_func=RT_DATA.Voltmetr.serial_worker,
                                           label_start='Мультиметр(Вкл)',
                                           label_stop='Мультиметр(Выкл)')
    '''
    [dpg, tt, tt_A, tt_P] = user_data
    result = str(sender).split('_')  # Получаем таг и разделяем его выделяя номер партии
    slot = result[1]
    chanel = dpg.get_value(f'Channel_select_{slot}')
    button_text = dpg.get_item_label(sender)
    if button_text == 'Мультиметр(Вкл)':
        result = multimetr_on(channel=chanel)
        tt.start()
        tt_A.start()
        tt_P.start()
        dpg.configure_item(sender, label='Мультиметр(Выкл)')
        if result == 'OK':
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_3')
        else:
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_2')
    else:

        tt.stop()
        tt_A.stop()
        tt_P.stop()
        RT_DATA.Voltmetr.end_measure()
        result = multimetr_off(chanel)
        if result == 'OK':
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_1')
        else:
            dpg.bind_item_theme(sender, 'Use_button_theme_rt_2')
        dpg.configure_item(sender, label='Мультиметр(Вкл)')
    set_button(dpg)


# Устанавливает сотояние кнопок после подключения анализатора
def set_button(dpg, lamp_state=True):
    power_state, analyzer_state, multimetr_state, r_magazine = get_rele_state()
    for key in analyzer_state:
        if analyzer_state[key]:
            dpg.configure_item(f"Network_Analyzer_{key}_button", label='Анализатор(Выкл)')
            dpg.bind_item_theme(f"Network_Analyzer_{key}_button", 'Use_button_theme_rt_3')
        else:
            dpg.configure_item(f"Network_Analyzer_{key}_button", label='Анализатор(Вкл)')
            dpg.bind_item_theme(f"Network_Analyzer_{key}_button", 'Use_button_theme_rt_1')
    for key_1 in multimetr_state:
        if multimetr_state[key_1]:
            dpg.configure_item(f"V_{key_1}_button", label='Мультиметр(Выкл)')
            dpg.bind_item_theme(f"V_{key_1}_button", 'Use_button_theme_rt_3')
        else:
            dpg.configure_item(f"V_{key_1}_button", label='Мультиметр(Вкл)')
            dpg.bind_item_theme(f"V_{key_1}_button", 'Use_button_theme_rt_1')
    for key_2 in power_state:
        if power_state[key_2]:
            dpg.configure_item(f"Power_{key_2}_button", label='Отключить')
            dpg.bind_item_theme(f"Power_{key_2}_button", 'Use_button_theme_rt_3')
            if lamp_state:
                dpg.configure_item(f'bg_{int(key_2) - 1}', color=get_res_state_color(1), fill=get_res_state_color(1))
        else:
            dpg.configure_item(f"Power_{key_2}_button", label='Вкл')
            dpg.bind_item_theme(f"Power_{key_2}_button", 'Use_button_theme_rt')
            if lamp_state:
                dpg.configure_item(f'bg_{int(key_2) - 1}', color=get_res_state_color(0), fill=get_res_state_color(0))
