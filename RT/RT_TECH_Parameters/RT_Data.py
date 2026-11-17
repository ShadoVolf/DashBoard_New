import configparser
from typing import List

import pandas as pd
from sqlalchemy import create_engine

import Options
from Pribory.Network_Analyzer.VNA import VNA


# Получаем состав системы по ид и типу
def get_options_by_id(System_Type, System_ID):
    # Создаем engine
    engine = create_engine(Options.get_connection_string())
    # SQL-запрос для выборки данных
    df = pd.DataFrame()
    query = (f"SELECT * FROM `состав_измерительной_системы` where `System_Name`='{System_Type}' "
             f"and `System_ID`='{System_ID}' order by `ID`")
    try:
        # Извлекаем данные в DataFrame
        df = pd.read_sql(query, engine)
    except Exception as e:
        print(f"Ошибка: {str(e)}")
    finally:
        engine.dispose()
    return df


# Получаем данные конфигурационного файла
def get_system_options():
    # Создаем объект парсера
    path_ = Options.get_system_path()
    parser = configparser.ConfigParser()
    parser.read(path_ + "\\Configuration.con", encoding='utf-8')  # Укажите кодировку, если нужна
    # Получаем данные из секции [System]
    system_data = dict(parser.items('System'))
    return system_data


class RT_DATA:
    # relay_states: List[bool] = [False] * 16
    relay_states = {}
    # Раздельные словари для питания и анализатора
    _power_switch_dict = {}
    _analyzer_switch_dict = {}
    _short_rele_switch_dict = {}
    _multimetr_switch_dict = {}
    _r_magazine_switch_dict = {}
    _r_magazine_value_dict = {}
    # Контроллеры мультиметров
    Voltmetr = None
    Ampermetr = None

    # Текущие полученные значения с мультиметра
    Current_V = None
    Current_V_Status = False
    Current_A = None
    Current_A_Status = False
    Current_P = None
    Current_dA = None
    Current_Rm = {}

    A_history = {}
    dA_history = {}
    last_A_Value = {}
    # Статус анализатора цепей
    vna_id = None
    vna_status = False
    vna_type = None

    # текущее значения ЭМС
    current_magazine_R = None

    # данные измерений
    em_measure_data = {}

    # данные измерений ТЧХ
    temp_measure_data = {}

    TCH_Measure_Data = {}

    '''
    Блок переменных таймеров
    '''
    freq_timer = None
    freq_ppm_timer = None
    freq_r_timer = None

    u_timer = None
    i_timer = None
    power_timer = None

    view_magazine_time_timer = None
    work_timer = None
    work_timer_time = None
    work_status = 'N/A'

    EM_current_time = 0

    tune_full_time = 0

    work_time = 0

    dpg_ref = None

    current_plot_view = 'I(t), мА'
    current_plot_type = 'Время'
    current_tch_row = 0
    current_state_status = 1
    current_state = {}

    process = 'EM'
    process_status_next = False

    series_tags = {}

    # Глобальные переменные для управления состоянием калибровки
    calibration_active = False
    current_channel = 0

    # Словарь номеров
    rt_numbers_dict = {'1': None,
                       '2': None,
                       '3': None,
                       '4': None,
                       '5': None}

    # Данные полные измерений
    rt_measure_full_data = {}
    # Значение текущий линии в таблице результатов
    rt_measure_current_line = 1

    # Устанавливает текущую линию протокола измерений
    @staticmethod
    def set_measure_current_line(value: int):
        RT_DATA.rt_measure_current_line = value

    # Получает текущую линию протокола измерений
    @staticmethod
    def get_measure_current_line() -> int:
        return RT_DATA.rt_measure_current_line

    # Добавляет строчку в данные измерений
    @staticmethod
    def append_rt_data(value: dict):
        if value:
            RT_DATA.rt_measure_full_data[str(RT_DATA.get_measure_current_line())] = value
        else:
            print('Попытка добавить пустые данные')

    # Возвращает данные измерений РТ
    @staticmethod
    def get_rt_measure_full_data():
        return RT_DATA.rt_measure_full_data

    # Удаление всех данных измерений
    @staticmethod
    def clear_rt_measure_full_data():
        RT_DATA.rt_measure_full_data = {}



    @staticmethod
    def a_history_init():
        RT_DATA.A_history = {}
        RT_DATA.dA_history = {}
        RT_DATA.last_A_Value = {}

    @staticmethod
    def get_work_status():
        return RT_DATA.work_status

    @staticmethod
    def set_work_status(value):
        RT_DATA.work_status = value

    # задает словарь номеров рт измерения
    @staticmethod
    def set_rt_numbers(value: dict):
        RT_DATA.rt_numbers_dict = value.copy()

    # Возвращает словарь с номерами резонаторов по каналам
    @staticmethod
    def get_rt_numbers():
        return RT_DATA.rt_numbers_dict

    # Обнуляет состояние статуса результатов измерений
    @staticmethod
    def rt_numbers_init():
        if RT_DATA.rt_numbers_dict:
            for key in RT_DATA.rt_numbers_dict.keys():
                if RT_DATA.rt_numbers_dict[key] is not None:
                    temp_value = RT_DATA.rt_numbers_dict[key]
                    if temp_value['Use']:
                        temp_value['Status'] = 'N/A'

    @staticmethod
    def set_current_state_status(value):
        RT_DATA.current_state_status = value

    @staticmethod
    def get_current_state_status():
        return RT_DATA.current_state_status

    @staticmethod
    def set_current_tch_row(value: int):
        RT_DATA.current_tch_row = value

    @staticmethod
    def get_current_tch_row():
        return RT_DATA.current_tch_row

    @staticmethod
    def set_current_magazine_r(value):
        RT_DATA.current_magazine_R = value

    @staticmethod
    def get_current_magazine_r():
        return RT_DATA.current_magazine_R

    @staticmethod
    def set_work_time(value):
        RT_DATA.work_time = value

    @staticmethod
    def get_work_time():
        return RT_DATA.work_time

    @staticmethod
    def set_tune_time(value):
        RT_DATA.tune_full_time = value

    @staticmethod
    def get_tune_time():
        return RT_DATA.tune_full_time

    @staticmethod
    def set_EM_current_time(value):
        RT_DATA.EM_current_time = value

    @staticmethod
    def get_EM_current_time():
        return RT_DATA.EM_current_time

    @staticmethod
    def set_current_rm(value: dict):
        RT_DATA.Current_Rm = value

    @staticmethod
    def get_current_rm():
        if RT_DATA.Current_Rm:
            return RT_DATA.Current_Rm

    @staticmethod
    def get_process_status():
        return RT_DATA.process_status_next

    @staticmethod
    def set_process_status(value):
        RT_DATA.process_status_next = value

    @staticmethod
    def get_process_type():
        return RT_DATA.process

    @staticmethod
    def set_process_type(value):
        RT_DATA.process = value

    @staticmethod
    def get_current_plot_name():
        return RT_DATA.current_plot_view

    @staticmethod
    def set_current_plot_name(value: str):
        RT_DATA.current_plot_view = value

    @staticmethod
    def get_current_plot_type():
        return RT_DATA.current_plot_type

    @staticmethod
    def set_current_plot_type(value):
        RT_DATA.current_plot_type = value

    # Возвращает список доступных графиков и осей для режима измерения.
    @staticmethod
    def get_plot_names(value: str):
        result = None
        ax = None
        if value == 'Время':
            result = {
                'F(t), Гц': 'series_F',
                'F(t), ppm': 'series_F_ppm',
                'R1(t), Ом': 'series_R',
                'U(t), В': 'series_U',
                'I(t), мА': 'series_I',
                'P(t), мВ': 'series_Power'
            }
            ax = {
                'axis_x': 'Time',
                'F(t), Гц': 'F, Гц',
                'F(t), ppm': 'F, ppm',
                'R1(t), Ом': 'R, Ом',
                'U(t), В': 'U, В',
                'I(t), мА': 'I, мА ',
                'P(t), мВ': 'Мощность, мВ'
            }
        elif value == 'ТЧХ':
            result = {
                'F(R), ppm': 'series_F_ppm',
                'R1(R), Ом': 'series_R',
                'U(R), В': 'series_U',
                'I(R), мА': 'series_I',
                'P(R), мВ': 'series_Power'
            }
            ax = {
                'axis_x': 'R магазина, Ом',
                'F(R), ppm': 'F, ppm',
                'R1(R), Ом': 'R, Ом',
                'U(R), В': 'U, В',
                'I(R), мА': 'I, мА ',
                'P(R), мВ': 'Мощность, мВ'
            }
        return result, ax

    @staticmethod
    def temp_measure_ini():
        RT_DATA.temp_measure_data = {'Time': [],
                                     'Time_All': [],
                                     'R магазина, Ом': [],
                                     'F(R), ppm': [],
                                     'U(R), В': [],
                                     'I(R), мА': [],
                                     'P(R), мВ': [],
                                     'R1(R), Ом': []}

    @staticmethod
    def add_temp_data_value(value: dict):
        numeric_keys = ['R магазина, Ом', 'F(R), ppm', 'U(R), В', 'I(R), мА', 'P(R), мВ', 'R1(R), Ом']
        if len(RT_DATA.temp_measure_data) == 0:
            RT_DATA.temp_measure_ini()
        for key in numeric_keys + ['Time'] + ['Time_All']:
            if key in value:
                # Для времени сохраняем оригинальное значение
                if key == 'Time' or key == 'Time_All':
                    RT_DATA.temp_measure_data[key].append(value[key])
                else:
                    try:
                        # Пытаемся преобразовать в float
                        num_value = float(value[key])
                        RT_DATA.temp_measure_data[key].append(num_value)
                    except (ValueError, TypeError):
                        # В случае ошибки подставляем 0
                        RT_DATA.temp_measure_data[key].append(0.0)
        return 'OK'

    @staticmethod
    def get_temp_data():
        return RT_DATA.temp_measure_data

    @staticmethod
    def em_measure_ini():
        RT_DATA.em_measure_data = {'Time': [],
                                   'Time_All': [],
                                   'R магазина, Ом': [],
                                   'F(t), Гц': [],
                                   'F(t), ppm': [],
                                   'R1(t), Ом': [],
                                   'U(t), В': [],
                                   'I(t), мА': [],
                                   'P(t), мВ': []}

    @staticmethod
    def add_em_data_value(value: dict):
        numeric_keys = ['R магазина, Ом', 'F(t), Гц', 'F(t), ppm', 'R1(t), Ом', 'U(t), В', 'I(t), мА', 'P(t), мВ']
        if len(RT_DATA.em_measure_data) == 0:
            RT_DATA.em_measure_ini()
        for key in numeric_keys + ['Time'] + ['Time_All']:
            if key in value:
                # Для времени сохраняем оригинальное значение
                if key == 'Time' or key == 'Time_All':
                    RT_DATA.em_measure_data[key].append(value[key])
                else:
                    try:
                        # Пытаемся преобразовать в float
                        num_value = float(value[key])
                        RT_DATA.em_measure_data[key].append(num_value)
                    except (ValueError, TypeError):
                        # В случае ошибки подставляем 0
                        RT_DATA.em_measure_data[key].append(0.0)
        return 'OK'

    @staticmethod
    def get_em_data(type_: str):
        return RT_DATA.em_measure_data[type_]

    @staticmethod
    def get_all_em_data():
        return RT_DATA.em_measure_data

    '''
    блок текущее состояние
    '''

    # Возвращает текущий активный канал
    @staticmethod
    def get_current_channel():
        return RT_DATA.current_channel

    # Устанавливает текущий активный канал
    @staticmethod
    def set_current_channel(value):
        RT_DATA.current_channel = value

    '''
    Блок опций для анализатора цепей
    '''

    # Возвращает статус калибровки анализатора цепей
    @staticmethod
    def get_calibration_status():
        return RT_DATA.calibration_active

    # Устанавливает статус калибровки
    @staticmethod
    def set_calibration_status(value):
        RT_DATA.calibration_active = value

    '''
    --------------------------------------------------------------------------------------------------
    '''

    @staticmethod
    def get_relay_states(slave):
        if int(slave) in RT_DATA.relay_states.keys():
            return RT_DATA.relay_states[int(slave)]
        else:
            RT_DATA.relay_states[int(slave)] = [False] * 16
            return RT_DATA.relay_states[int(slave)]

    @staticmethod
    def set_relay_states(slave, value):
        RT_DATA.relay_states[int(slave)] = value

    @staticmethod
    def _load_switch_data(switch_type: str) -> dict:
        """
        Загружает данные MAP из БД для указанного типа (Power/Network_Analyzer)
        и возвращает словарь {Channel: [Module_ID, Rele_ID]}
        """
        system_options = get_system_options()
        engine = create_engine(Options.get_connection_string())

        query = f"""
            SELECT Channel, Module_ID, Rele_ID, Options 
            FROM `измеритель_map` 
            WHERE 
                `System_Name` = '{system_options['тип']}' AND
                `System_ID` = '{system_options['идентификатор']}' AND
                `Type` = '{switch_type}'
            ORDER BY `ID`
        """

        df = pd.read_sql(query, engine)
        return df.set_index('Channel')[['Module_ID', 'Rele_ID', 'Options']].apply(list, axis=1).to_dict()

    @staticmethod
    def _get_switch_dict(switch_type: str) -> dict:
        """
        Возвращает актуальный словарь для указанного типа.
        При необходимости загружает данные из БД.
        """
        target_dict = {
            'Power': RT_DATA._power_switch_dict,
            'Network_Analyzer': RT_DATA._analyzer_switch_dict,
            'Multimetr': RT_DATA._multimetr_switch_dict,
            'Short_rele': RT_DATA._short_rele_switch_dict,
            'R_Magazine': RT_DATA._r_magazine_switch_dict,
            'R_Magazine_Value': RT_DATA._r_magazine_value_dict
        }[switch_type]

        if not target_dict:
            target_dict.update(RT_DATA._load_switch_data(switch_type))
        return target_dict

    @staticmethod
    def get_switch_data(switch_type: str, channel: int) -> list | None:
        """Возвращает данные для переключения указанного канала"""
        channel = int(channel)
        switch_dict = RT_DATA._get_switch_dict(switch_type)
        return switch_dict.get(channel)

    @staticmethod
    def get_switch(switch_type: str) -> dict:
        """Возвращает весь словарь для указанного типа"""
        return RT_DATA._get_switch_dict(switch_type)

    # Удобные методы для быстрого доступа
    @staticmethod
    def get_power_switch_data(channel: int) -> list | None:
        return RT_DATA.get_switch_data('Power', channel)

    @staticmethod
    def get_analyzer_switch_data(channel: int) -> list | None:
        return RT_DATA.get_switch_data('Network_Analyzer', channel)

    @staticmethod
    def get_multimetr_switch_data(channel: int) -> list | None:
        return RT_DATA.get_switch_data('Multimetr', channel)

    @staticmethod
    def get_short_rele_switch_data(channel: int) -> list | None:
        return RT_DATA.get_switch_data('Short_rele', channel)

    @staticmethod
    def get_power_switch() -> dict:
        return RT_DATA.get_switch('Power')

    @staticmethod
    def get_analyzer_switch() -> dict:
        return RT_DATA.get_switch('Network_Analyzer')

    @staticmethod
    def get_multimetr_switch() -> dict:
        return RT_DATA.get_switch('Multimetr')

    @staticmethod
    def get_r_magazine_switch() -> dict:
        return RT_DATA.get_switch('R_Magazine')

    @staticmethod
    def get_r_magazine_switch_data(channel: int) -> list | None:
        return RT_DATA.get_switch_data('R_Magazine', int(channel))

    @staticmethod
    def get_r_magazine_value() -> dict:
        return RT_DATA.get_switch('R_Magazine_Value')

    @staticmethod
    def get_r_magazine_value_data(channel: int) -> list | None:
        return RT_DATA.get_switch_data('R_Magazine_Value', channel)
