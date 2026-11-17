from typing import Optional

from Options import get_connection_string
from Pribory.Network_Analyzer import VNA_Data
from RT.RT_TECH_Parameters import RT_Data
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Specification_Window import create_spc_rt_window
from Statistik.Operations import get_resonator_types, get_resonator_nominals_list, get_resonator_nom_list
from Temperature_Measure.Load_Data import get_msk_by_id, get_nom_id_by_name
import pandas as pd
from sqlalchemy import create_engine, text


def create_nom_rt_window(dpg):
    with dpg.window(label="Выбор номенклатуры", width=400, height=300, pos=(20, 0), tag='Nomenklatura'):
        dpg.add_text("Номенклатура")
        resonator_types = get_resonator_types()
        dpg.add_combo(resonator_types, label='Тип резонатора', user_data=dpg, callback=get_res_nom,
                      tag='rt_measure_type_select')
        resonator_nominals = get_resonator_nominals_list()
        dpg.add_combo(resonator_nominals, label='Номинал', user_data=dpg, callback=get_res_nom1,
                      tag='rt_measure_nominal_select')
        dpg.add_combo(label='Спецификация', user_data=dpg, tag='rt_measure_spc_select',
                      callback=lambda: search_vna_spc(dpg, 'Измеритель РТ'))
        dpg.add_input_text(label='Код МСК', tag='RT_measure_select_msk', user_data=dpg, callback=msk_select_callback)
        dpg.add_spacer(height=20)
        dpg.add_text('Измерительная спецификация')
        dpg.add_combo(user_data=dpg, tag='measure_spc_select', callback=measure_spc_select)
        dpg.add_spacer(height=30)
        dpg.add_button(label='Новая', width=100, height=30)


# Загрузка номенклатуры по названию или коду мск
def msk_select_callback(sender, data, dpg):
    code = '-' not in data
    msk, spc_nom, nominal, type_rq = get_msk_by_id(data, code)
    dpg.configure_item('rt_measure_type_select', default_value=type_rq)
    dpg.configure_item('rt_measure_nominal_select', default_value=nominal)
    dpg.configure_item('rt_measure_spc_select', default_value=spc_nom)


def search_vna_spc(dpg, measure_system: str):
    """
    Ищет записи в таблице vna_spc по заданным условиям.

    :param dpg:
    :param measure_system: Требуемая измерительная система
    :return: DataFrame с результатами запроса
    """
    connection_string = get_connection_string()
    engine = create_engine(connection_string)
    vna_type = VNA_Data.VNA_DATA.get_vna_type()
    code = get_nom_id_by_name(dpg.get_value('rt_measure_spc_select'))

    query = text("""
           SELECT * 
           FROM vna_spc 
           WHERE (Nomenklatura_ID LIKE :code_pattern1 
                  OR Nomenklatura_ID LIKE :code_pattern2
                  OR Nomenklatura_ID LIKE :code_pattern3
                  OR Nomenklatura_ID = :code
                  OR Nomenklatura_ID LIKE '% 0 %'
                  OR Nomenklatura_ID = '0')
             AND (VNA = :vna_type OR VNA = 'Все')
             AND Measure_system = :measure_system
       """)

    params = {
        'code_pattern1': f'{code} %',
        'code_pattern2': f'% {code} %',
        'code_pattern3': f'% {code}',
        'code': f'{code}',
        'vna_type': vna_type,
        'measure_system': measure_system
    }
    # Выполняем запрос и получаем результат в виде DataFrame
    result_df = pd.read_sql_query(query, engine, params=params)
    res_list = result_df['Name'].tolist()
    if len(res_list) > 0:
        dpg.configure_item('measure_spc_select', items=res_list, default_value=res_list[0])
        spc_id = get_id_by_name_vna_spc(res_list[0])
        create_spc_rt_window(dpg, spc_id)


# Обратный вызов для выбора измерительной спецификации
def measure_spc_select(sender, data, dpg):
    spc_id = get_id_by_name_vna_spc(data)
    create_spc_rt_window(dpg, spc_id)


# Функция выбора номинала резонатора
def get_res_nom1(sender, data, dpg):
    tt = dpg.get_value('rt_measure_type_select')
    if tt is not None:
        nom_list = get_resonator_nom_list(resonator_type=tt, resonator_nominal=data)
    else:
        nom_list = get_resonator_nom_list(resonator_nominal=data)
    if len(nom_list) > 0:
        dpg.configure_item('rt_measure_spc_select', items=nom_list, default_value=nom_list[0])


# Обратный вызов выбора типа резонатора
def get_res_nom(sender, data, dpg):
    res_list = get_resonator_nominals_list(data)
    if len(res_list) > 0:
        dpg.configure_item('rt_measure_nominal_select', items=res_list, default_value=res_list[0])
        nom_list = get_resonator_nom_list(resonator_type=data, resonator_nominal=res_list[0])
        if len(nom_list) > 0:
            dpg.configure_item('rt_measure_spc_select', items=nom_list, default_value=nom_list[0])


def get_id_by_name_vna_spc(name: str) -> Optional[int]:
    """
    Получает ID записи по значению Name из таблицы vna_spc.

    Параметры:
    name - значение Name для поиска

    Возвращает:
    ID записи или None, если запись не найдена
    """
    connection_string = get_connection_string()
    engine = create_engine(connection_string)
    # SQL-запрос для поиска ID по имени
    query = text("""
        SELECT ID 
        FROM vna_spc 
        WHERE Name = :name
    """)

    # Параметры запроса
    params = {'name': name}

    try:
        # Выполняем запрос и получаем результат
        result_df = pd.read_sql_query(query, engine, params=params)

        # Проверяем, найдена ли запись
        if not result_df.empty:
            return result_df['ID'].iloc[0]  # Возвращаем первый найденный ID
        else:
            return None  # Запись не найдена

    except Exception as e:
        print(f"Ошибка при выполнении запроса: {e}")
        return None
