import pandas as pd
from sqlalchemy import create_engine

from Options import get_connection_string


def get_machine_types_list():
    """
    Возвращает список установок отсортированный по имени в обратном порядке.
    В список добавляет слово 'Все'
    :return: list
    """
    engine = create_engine(str(get_connection_string()))
    sql = "Select `Name` from `machines` where `Function`='Measure' order by `Name`"
    df_nom = pd.read_sql_query(sql, engine)
    out_list = df_nom['Name'].to_list()
    out_list.append('Все')
    out_list.sort(reverse=True)
    return out_list


def get_files_types_list(machine_type):
    """
    Метод возвращает список файлов в виде строк File_ID, FileName, Date
    :param machine_type:
    :return: str File_ID, FileName, Date
    """
    engine = create_engine(str(get_connection_string()))
    if machine_type == 'Все':
        sql = "Select `File_ID`, `FileName`, `Date`  from `saunders` order by `File_ID` DESC"
    else:
        sql_m = ("Select `IP`, `Type`, `Serial_N` from `machines` where `Name`='"+machine_type+"'")
        df1 = pd.read_sql_query(sql_m, engine)
        print('Выбрана установка типа', df1['Type'].iloc[0], 'Серийный номер', df1['Serial_N'].iloc[0])
        sql = ("Select `File_ID`, `FileName`,  `Date` from `saunders` where `Machine`='" +
               df1['IP'].iloc[0]+"' order by `File_ID` DESC")
    df = pd.read_sql_query(sql, engine)
    # Конвертируем все данные в строки
    df = df.astype(str)

    # Рассчитываем максимальные длины для каждого поля
    max_lengths = {
        'File_ID': df['File_ID'].str.len().max(),
        'FileName': df['FileName'].str.len().max(),
        'Date': df['Date'].str.len().max(),
    }

    # Форматируем строки с выравниванием
    formatted_list = []
    for _, row in df.iterrows():
        line = (f"{row['File_ID']:<{max_lengths['File_ID']}}     "
                f"{row['FileName']:<{max_lengths['FileName']}}   "
                f"({row['Date']}) ")
        formatted_list.append(line)

    return formatted_list
