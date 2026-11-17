import pandas as pd
from sqlalchemy import create_engine
from collections import OrderedDict
from Options import get_connection_string
from Pribory.Network_Analyzer import VNA_Data
from RT.RT_TECH_Parameters import RT_Data


def create_spc_rt_window(dpg, spc_id):
    dpg.delete_item('RT_spc_view_window')
    with dpg.window(label="Спецификация", width=400, height=450, pos=(20, 635), tag='RT_spc_view_window'):
        if spc_id == 0:
            data_dict = {}
        else:
            data_dict = get_vna_spc_data(spc_id)

        with dpg.table(header_row=True):
            dpg.add_table_column(label="Параметр")
            dpg.add_table_column(label="Значение")
            for param, value in data_dict.items():
                with dpg.table_row():
                    dpg.add_text(param)
                    dpg.add_text(value)


def get_vna_spc_data(spc_id):
    """
        Извлекает данные VNA SPC из базы данных и возвращает их в виде упорядоченного словаря.

        Параметры:
            spc_id (int): Идентификатор SPC, для которого запрашиваются данные.

        Возвращает:
            OrderedDict: Словарь с параметрами в порядке, определенном таблицей vna_spc_parameters.
                         Ключи - отображаемые имена параметров (Name_Text),
                         значения - соответствующие значения из vna_spc_data.
                         Параметры, отсутствующие в справочнике vna_spc_parameters,
                         добавляются в конец словаря.

        Пример:
            OrderedDict([('Частота', '1.5 GHz'), ('Мощность', '20 dBm'), ...])
        """
    # Создаем подключение к базе данных
    connection_string = get_connection_string()
    engine = create_engine(connection_string)

    # Получаем данные из vna_spc_data для указанного SPC_ID
    query_data = f"SELECT Parametr, Value FROM vna_spc_data WHERE SPC_ID = {spc_id}"
    df_data = pd.read_sql(query_data, engine)

    # Получаем информацию о параметрах из vna_spc_parameters
    query_params = "SELECT Name, Name_Text FROM vna_spc_parameters ORDER BY ID"
    df_params = pd.read_sql(query_params, engine)
    # Преобразуем DataFrame в словарь
    data_dict = dict(zip(df_data['Parametr'], df_data['Value']))
    VNA_Data.VNA_DATA.set_current_measure_spc(data_dict)
    # Создаем упорядоченный словарь параметров в соответствии с vna_spc_parameters
    ordered_params = OrderedDict()

    for _, row in df_params.iterrows():
        param_name = row['Name']
        if param_name in df_data['Parametr'].values:
            display_name = row['Name_Text']
            value = df_data[df_data['Parametr'] == param_name]['Value'].iloc[0]
            ordered_params[display_name] = value

    # Добавляем параметры, которые есть в данных, но отсутствуют в справочнике
    for _, row in df_data.iterrows():
        param_name = row['Parametr']
        if param_name not in df_params['Name'].values:
            ordered_params[param_name] = row['Value']

    return ordered_params
