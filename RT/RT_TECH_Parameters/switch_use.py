import pandas as pd

from Pribory.R_Magazine.Decade_Programmable_Board import SDPRB
from Pribory.Switchbox.R4D3B16 import RelayController
from RT.RT_TECH_Parameters import RT_Data
from RT.RT_TECH_Parameters.RT_Data import get_system_options, get_options_by_id


# Тестирует все
def test_switch(data):
    result = []
    for index, row in data.iterrows():
        if row['Name'] == 'R4D3B16':
            controller = RelayController(port=row['Port'], slave_id=int(row['Address']), simulation_mode=row['Emulate'])
            if not row['Emulate']:
                controller.reset_port()
            result_str = controller.switch_test()
            controller.disconnect()
            result.append(result_str)
            data.loc[index, 'Status'] = result_str
    return data


# Возвращает словарь с состояниями реле для всех функций
def get_rele_state():
    power = {}
    analyzer = {}
    multimetr = {}
    r_magazine = {}
    channel_map = RT_Data.RT_DATA.get_power_switch().copy()
    # print(channel_map)
    if 0 in channel_map.keys():
        del (channel_map[0])
    for key in channel_map:
        data = RT_Data.RT_DATA.get_power_switch_data(key)
        port, address, name, emulate = get_options(data[0])
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        power[key] = rele_state[int(data[1]) - 1]
        controller.disconnect()
    channel_map = RT_Data.RT_DATA.get_analyzer_switch().copy()
    for key in channel_map:
        data = RT_Data.RT_DATA.get_analyzer_switch_data(key)
        port, address, name, emulate = get_options(data[0])
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        analyzer[key] = rele_state[int(data[1]) - 1]
        controller.disconnect()
    channel_map = RT_Data.RT_DATA.get_multimetr_switch().copy()
    del (channel_map[0])
    for key in channel_map:
        data = RT_Data.RT_DATA.get_multimetr_switch_data(key)
        port, address, name, emulate = get_options(data[0])
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        multimetr[key] = rele_state[int(data[1]) - 1]
        controller.disconnect()
    channel_map = RT_Data.RT_DATA.get_r_magazine_switch().copy()
    for key in channel_map:
        data = RT_Data.RT_DATA.get_r_magazine_switch_data(key)
        port, address, name, emulate = get_options(data[0])
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        r_magazine[key] = rele_state[int(data[1]) - 1]
        controller.disconnect()

    return power, analyzer, multimetr, r_magazine


# Возвращает порт и адрес для коммутатора по протоколу RS485
def get_options(Map_ID):
    # Создаем engine
    system_options = get_system_options()
    options = get_options_by_id(system_options['тип'], system_options['идентификатор'])
    options_map = options[options['System_Map_ID'] == Map_ID]
    _port = options_map['Port'].iloc[0]
    _address = options_map['Address'].iloc[0]
    _name = options_map['Name'].iloc[0]
    _emulate = options_map['Emulate'].iloc[0]
    return _port, _address, _name, _emulate


# Устанавливает заданное сопротивление на канал
def set_resistance(rr):
    map_data = RT_Data.RT_DATA.get_r_magazine_value_data(0)
    map_ = RT_Data.RT_DATA.get_r_magazine_value()
    port, address, name, emulate = get_options(map_data[0])
    r_m = SDPRB('R4D3B16', port=port, slave_id=int(address), simulation_mode=emulate, map_data=map_)
    result = r_m.set_resistance_on_device(rr)
    RT_Data.RT_DATA.current_magazine_R = result[0]
    print('Выполнено', result[0])
    return result[0]


# Выключаем магазин сопротивлений
def off_resistance():
    map_data = RT_Data.RT_DATA.get_r_magazine_value_data(0)
    map_ = RT_Data.RT_DATA.get_r_magazine_value()
    port, address, name, emulate = get_options(map_data[0])
    r_m = SDPRB('R4D3B16', port=port, slave_id=int(address), simulation_mode=emulate, map_data=map_)
    return r_m.magazine_off()


def get_resistance():
    map_data = RT_Data.RT_DATA.get_r_magazine_value_data(0)
    map_ = RT_Data.RT_DATA.get_r_magazine_value()
    port, address, name, emulate = get_options(map_data[0])
    r_m = SDPRB('R4D3B16', port=port, slave_id=int(address), simulation_mode=emulate, map_data=map_)
    return r_m.get_current_resistance()


# Возвращает состояние подключения мультиметра и short реле
def get_multy_state(channel):
    result = {}
    data_m = RT_Data.RT_DATA.get_multimetr_switch_data(channel)
    port, address, name, emulate = get_options(data_m[0])
    if name == 'R4D3B16':
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        controller.disconnect()
        result['Multimetr'] = rele_state[int(data_m[1]) - 1]
    data = RT_Data.RT_DATA.get_short_rele_switch_data(channel)
    port, address, name, emulate = get_options(data[0])
    if name == 'R4D3B16':
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        controller.disconnect()
        result['Short_rele'] = rele_state[int(data[1]) - 1]
    # Если подключен мультиметр и short реле -> short реле отключаем
    if result['Multimetr'] and not result['Short_rele']:
        data = RT_Data.RT_DATA.get_short_rele_switch_data(channel)
        port, address, name, emulate = get_options(data[0])
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        controller.set_single_relay(int(data[1]), True)
        rele_state, status = controller.get_relays()
        result['Short_rele'] = rele_state[int(data[1]) - 1]
        controller.disconnect()
    elif not result['Multimetr'] and result['Short_rele']:
        data = RT_Data.RT_DATA.get_short_rele_switch_data(channel)
        port, address, name, emulate = get_options(data[0])
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        controller.set_single_relay(int(data[1]), False)
        rele_state, status = controller.get_relays()
        result['Short_rele'] = rele_state[int(data[1]) - 1]
        controller.disconnect()

    return result


# отключает линии подачи сигнала на резонатор
def set_multi_off(channel):
    data_m = RT_Data.RT_DATA.get_multimetr_switch_data(channel)
    port, address, name, emulate = get_options(data_m[0])
    result = None
    if name == 'R4D3B16':
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if rele_state[int(data_m[1]) - 1]:
            result = controller.set_single_relay(int(data_m[1]), False)
        controller.disconnect()
        data = RT_Data.RT_DATA.get_short_rele_switch_data(channel)
        port, address, name, emulate = get_options(data[0])
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if rele_state[int(data[1]) - 1]:
            result = controller.set_single_relay(int(data[1]), False)
        controller.disconnect()
    return result


# Включает питание на заданном канале
def power_on(channel):
    # Получаем состояние линии подключения
    line = get_multy_state(channel)
    # Получаем MAP
    data = RT_Data.RT_DATA.get_power_switch_data(channel)
    data_0 = RT_Data.RT_DATA.get_power_switch_data(0)
    # Получаем параметры соединения
    port, address, name, emulate = get_options(data[0])
    if name == 'R4D3B16':
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if not rele_state[int(data[1]) - 1]:
            # Проверяем есть ли реле на минусовом контакте если есть и они выключено -> включаем
            if data_0 is not None:
                if not rele_state[int(data_0[1]) - 1]:
                    controller.set_single_relay(int(data_0[1]), True)
            result = controller.set_single_relay(int(data[1]), True)
        else:
            result = 'OK'
        controller.disconnect()
        return result
    return 'ERROR'


# Выключает питание на канале
def power_off(channel):
    set_multi_off(channel)
    # Получаем MAP
    data = RT_Data.RT_DATA.get_power_switch_data(channel)
    # Получаем параметры соединения
    port, address, name, emulate = get_options(data[0])
    if name == 'R4D3B16':
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if rele_state[int(data[1]) - 1]:
            result = controller.set_single_relay(int(data[1]), False)
        else:
            result = 'OK'
        data_0 = RT_Data.RT_DATA.get_power_switch_data(0)
        if data_0 is not None:
            rele_state, status = controller.get_relays()
            if check_only_one_true(rele_state, int(data_0[1]) - 1):
                result = controller.set_single_relay(int(data_0[1]), False)
        controller.disconnect()
        return result
    return 'ERROR'


# Включает анализатор на канал
def analyzer_on(channel):
    analyzer_all_off()
    data = RT_Data.RT_DATA.get_analyzer_switch_data(channel)
    # Получаем параметры соединения
    port, address, name, emulate = get_options(data[0])
    if name == 'R4D3B16':
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if not rele_state[int(data[1]) - 1]:
            result = controller.set_single_relay(int(data[1]), True)
        else:
            result = 'OK'
        controller.disconnect()
        return result
    return 'ERROR'


# Выключает анализатор на этот канал
def analyzer_off(channel):
    # Получаем MAP
    data = RT_Data.RT_DATA.get_analyzer_switch_data(channel)
    # Получаем параметры соединения
    port, address, name, emulate = get_options(data[0])
    if name == 'R4D3B16':
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if rele_state[int(data[1]) - 1]:
            result = controller.set_single_relay(int(data[1]), False)
        else:
            result = 'OK'
        controller.disconnect()
        return result
    return 'ERROR'


# Отключает все каналы анализатора
def analyzer_all_off():
    # Получаем MAP
    data_state = RT_Data.RT_DATA.get_analyzer_switch().copy()
    # Получаем параметры соединения
    result = None
    for key in data_state:
        data = RT_Data.RT_DATA.get_analyzer_switch_data(key)
        port, address, name, emulate = get_options(data[0])
        if name == 'R4D3B16':
            controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
            rele_state, status = controller.get_relays()
            if rele_state[int(data[1]) - 1]:
                result = controller.set_single_relay(int(data[1]), False)
            else:
                result = 'OK'
            controller.disconnect()
    return result


# Возвращает количество каналов для анализатора цепей
def get_analyzer_channels():
    # Получаем MAP
    data_state = RT_Data.RT_DATA.get_analyzer_switch().copy()
    dict_len = len(data_state)
    return dict_len


# Включает мультиметр на канал
def multimetr_on(channel):
    multimetr_all_off()
    data = RT_Data.RT_DATA.get_multimetr_switch_data(channel)
    # Получаем параметры соединения
    port, address, name, emulate = get_options(data[0])
    if name == 'R4D3B16':
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if not rele_state[int(data[1]) - 1]:
            result = controller.set_single_relay(int(data[1]), True)
        else:
            result = 'OK'
        controller.disconnect()
        data = RT_Data.RT_DATA.get_short_rele_switch_data(channel)
        port, address, name, emulate = get_options(data[0])
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if not rele_state[int(data[1]) - 1]:
            result = controller.set_single_relay(int(data[1]), True)
        else:
            result = 'OK'
        controller.disconnect()
        return result
    return 'ERROR'


# Выключает мультиметр на этот канал
def multimetr_off(channel):
    # Получаем MAP
    data = RT_Data.RT_DATA.get_multimetr_switch_data(channel)
    # Получаем параметры соединения
    result1 = 'NA'
    result1 = 'NA'
    port, address, name, emulate = get_options(data[0])
    if name == 'R4D3B16':
        data = RT_Data.RT_DATA.get_short_rele_switch_data(channel)
        port, address, name, emulate = get_options(data[0])
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if rele_state[int(data[1]) - 1]:
            result1 = controller.set_single_relay(int(data[1]), False)
        else:
            result1 = 'OK'
        controller.disconnect()
        data = RT_Data.RT_DATA.get_multimetr_switch_data(channel)
        # Получаем параметры соединения
        port, address, name, emulate = get_options(data[0])
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if rele_state[int(data[1]) - 1]:
            result = controller.set_single_relay(int(data[1]), False)
        else:
            result = 'OK'
        controller.disconnect()
        return result
    return 'ERROR'


# Отключает все каналы мультиметра
def multimetr_all_off():
    # Получаем MAP
    data_state = RT_Data.RT_DATA.get_multimetr_switch().copy()
    # Получаем параметры соединения
    result = None
    for key in data_state:
        data = RT_Data.RT_DATA.get_multimetr_switch_data(channel=key)
        port, address, name, emulate = get_options(data[0])
        if name == 'R4D3B16':
            controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
            rele_state, status = controller.get_relays()
            controller.disconnect()
            if rele_state[int(data[1]) - 1]:
                data = RT_Data.RT_DATA.get_short_rele_switch_data(channel=key)
                port, address, name, emulate = get_options(data[0])
                controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
                rele_state, status = controller.get_relays()
                if rele_state[int(data[1]) - 1]:
                    result = controller.set_single_relay(int(data[1]), False)
                else:
                    result = 'OK'
                controller.disconnect()
            data = RT_Data.RT_DATA.get_multimetr_switch_data(channel=key)
            port, address, name, emulate = get_options(data[0])
            controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
            rele_state, status = controller.get_relays()
            if rele_state[int(data[1]) - 1]:
                result = controller.set_single_relay(int(data[1]), False)
            else:
                result = 'OK'
            controller.disconnect()
    return result


# Проверяет что все значения массива кроме текущего False
def check_only_one_true(data, target_index):
    series = pd.Series(data)
    # Проверяем, что элемент по target_index равен True
    if not series.iloc[target_index]:
        return False
    # Удаляем элемент и проверяем, что остальные суммируются в 0 (т.е. все False)
    remaining = series.drop(target_index)
    return remaining.sum() == 0


# Подключает магазин сопротивлений к указанному каналу
def r_magazine_on(channel):
    # Получаем данные реле для переключения
    data = RT_Data.RT_DATA.get_r_magazine_switch_data(int(channel))
    # Получаем параметры соединения
    port, address, name, emulate = get_options(data[0])
    if name == 'R4D3B16':
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if not rele_state[int(data[1]) - 1]:
            result = controller.set_single_relay(int(data[1]), True)
        else:
            result = 'OK'
        controller.disconnect()
        return result
    return 'ERROR'


# Отключает магазин сопротивлений указанного канала
def r_magazine_off(channel):
    # Получаем данные реле для переключения
    data = RT_Data.RT_DATA.get_r_magazine_switch_data(int(channel))
    # Получаем параметры соединения
    port, address, name, emulate = get_options(data[0])
    if name == 'R4D3B16':
        controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
        rele_state, status = controller.get_relays()
        if rele_state[int(data[1]) - 1]:
            result = controller.set_single_relay(int(data[1]), False)
        else:
            result = 'OK'
        controller.disconnect()
        return result
    return 'ERROR'


# Отключает все каналы от магазина сопротивлений
def r_magazine_all_off():
    data_map = RT_Data.RT_DATA.get_r_magazine_switch()
    # Получаем параметры соединения
    result = None
    for key in data_map:
        data = RT_Data.RT_DATA.get_r_magazine_switch_data(key)

        port, address, name, emulate = get_options(data[0])
        if name == 'R4D3B16':
            controller = RelayController(port=port, slave_id=int(address), simulation_mode=emulate)
            rele_state, status = controller.get_relays()
            if rele_state[int(data[1]) - 1]:
                result = controller.set_single_relay(int(data[1]), False)
            else:
                result = 'OK'
            controller.disconnect()
    return result
