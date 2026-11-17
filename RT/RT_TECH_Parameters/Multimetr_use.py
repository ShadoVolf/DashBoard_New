from Pribory.Multimetr.VoltmeterController import VoltmeterController_Multy
from RT.RT_TECH_Parameters.RT_Data import RT_DATA
from Utils.Thread_timer import Timer_D
from Utils.math_functions_user import safe_float


def Multimetr_test1(data):
    for index, row in data.iterrows():
        if row['Name'] == '34401A':
            print('Port', row['Port'])
            '''
            RT_DATA.Voltmetr = VoltmeterController(port=row['Port'], multy_type=row['Address'],
                                                   emulate=row['Emulate'])
                                                   
            '''
            RT_DATA.Voltmetr = VoltmeterController_Multy(device_name=row['Name'], device_params={
                'port': row['Port']},
                                                         measurement_type=row['Address'], emulate=row['Emulate'])
            result_str, serial = RT_DATA.Voltmetr.test()
            serial_str = str(serial).split(',')
            data.loc[index, 'Status'] = result_str
            data.loc[index, 'SerialN'] = serial_str[3]
        if row['Name'] == 'DM858':
            RT_DATA.Voltmetr = VoltmeterController_Multy(device_name=row['Name'], device_params={
                'port': row['Port']},
                                                         measurement_type=row['Address'], emulate=row['Emulate'])
            result_str, serial = RT_DATA.Voltmetr.test()
            serial_str = str(serial).split(',')
            data.loc[index, 'Status'] = result_str
            data.loc[index, 'SerialN'] = serial_str[2]

    return data


def Multimetr_test(data):
    for index, row in data.iterrows():
        if row['Name'] in ['34401A', 'DM858']:
            # Определяем индекс для серийного номера
            serial_index = 3 if row['Name'] == '34401A' else 2

            RT_DATA.Voltmetr = VoltmeterController_Multy(
                device_name=row['Name'],
                device_params={'port': row['Port']},
                measurement_type=row['Address'],
                emulate=row['Emulate']
            )

            result_str, serial = RT_DATA.Voltmetr.test()
            serial_str = str(serial).split(',')

            data.loc[index, 'Status'] = result_str
            data.loc[index, 'SerialN'] = serial_str[serial_index]

    return data


# Возвращает результат измерения мощности на резонаторе
def get_power():
    v_str = RT_DATA.Current_V
    a_str = RT_DATA.Current_A
    if v_str is not None:
        v = safe_float(v_str)
        if a_str is not None:
            a = safe_float(a_str) / 1E3
            power = (a * v) * 1E3
            if power > 5000:
                return 'N/A'
            else:
                return f"{power:.1f}"
    return 0


# запуск остановка таймеров для чтения данных мультиметра
def control_ui_timer(value):
    timers = (RT_DATA.u_timer, RT_DATA.i_timer, RT_DATA.power_timer)
    for timer in timers:
        if timer is not None:
            if value == 'Start':
                timer.start()
            elif value == 'Stop':
                timer.stop()


# инициализация таймера мультиметра
def ui_timer_init(dpg):
    if RT_DATA.u_timer is None:
        RT_DATA.u_timer = Timer_D(dpg, value_func=RT_DATA.Voltmetr.serial_worker)
    if RT_DATA.i_timer is None:
        RT_DATA.i_timer = Timer_D(dpg, value_func=RT_DATA.Ampermetr.serial_worker,
                                  display='current_val',
                                  data='A')
    if RT_DATA.power_timer is None:
        RT_DATA.power_timer = Timer_D(dpg, value_func=get_power, display='power_val', data='P')
