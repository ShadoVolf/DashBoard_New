import re

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

from Options import get_connection_string
from datetime import datetime
from tabulate import tabulate

from Temperature_Measure.measure_data_class import MEASURE_DATA
from Temperature_Measure.spc_matching import (parse_temp_list, temps_match,
                                              load_types_compatible,
                                              nominal_matches, nominal_exact)


def load_measure_file_data(file_inf: str):
    """
    Метод загружает данные файла по полученной строке из списка выбора и
    сохраняет их в переменную measure_file в виде словаря в классе MEASURE_DATA
    :param file_inf:
    """
    engine = create_engine(str(get_connection_string()))
    file_inf_arrray = file_inf.split()  # Разбиваем строку на слова
    file_id = str(file_inf_arrray[0])  # Идентификатор файла
    file_name = str(file_inf_arrray[1])  # Имя файла
    sql = ("Select `Name`,`Machine_Type`, `Archive`, `Size` from `files` where `ID`='" + file_id +
           "'")
    df = pd.read_sql_query(sql, engine)  # Запращиваем данные файла
    machine = str(df['Machine_Type'].iloc[0])  # Индекс измерительной установки
    sql1 = ("Select `Serial_N`, `Type`, `PoverKa`, `Call_Date`, `M_Type` from `machines` where `ID`='" + machine + "'")
    df1 = pd.read_sql_query(sql1, engine)  # Запращиваем данные на установку
    machine_type = str(df1['Type'].iloc[0])
    machine_serial = str(df1['Serial_N'].iloc[0])
    machine_poverka = df1['PoverKa'].iloc[0]
    machine_poverka_date = str(df1['Call_Date'].iloc[0])
    # Преобразуем строку в объект datetime
    date_format = "%d.%m.%Y"
    date = datetime.strptime(machine_poverka_date, date_format)
    # Добавляем один год к дате
    # Важно: простое добавление 365 дней не учитывает високосные годы
    # Поэтому добавляем 1 год через замену года
    new_date = date.replace(year=date.year + 1)
    # Получаем текущую дату
    current_date = datetime.now()
    # Рассчитываем разницу в днях
    difference = new_date - current_date
    sql2 = ("Select `Archive` from `saunders` where `File_ID`='" + file_id + "'")
    df2 = pd.read_sql_query(sql2, engine)  # Запращиваем данные файла

    # Сохранеям информацию по файлу
    MEASURE_DATA.measure_file['FileName'] = file_name
    MEASURE_DATA.measure_file['File_ID'] = file_id
    MEASURE_DATA.measure_file['Machine_Serial'] = machine_serial
    MEASURE_DATA.measure_file['Machine_Type'] = machine_type
    MEASURE_DATA.measure_file['Machine_Type_ID'] = df1['M_Type'].iloc[0]
    MEASURE_DATA.measure_file['Machine_ID'] = machine
    MEASURE_DATA.measure_file['Archive'] = df2['Archive'].iloc[0]
    MEASURE_DATA.measure_file['Size'] = df['Size'].iloc[0]
    MEASURE_DATA.measure_file['Poverka'] = machine_poverka
    MEASURE_DATA.measure_file['Poverka_Date'] = machine_poverka_date
    MEASURE_DATA.measure_file['Poverka_Actual'] = difference
    return file_name, machine_serial, machine_type, machine_poverka, difference, df2['Archive'].iloc[0], file_id


def get_file_inf_KH7700(file_id: str, Archive):
    """
    Метод производит анализ файла из установки KH7700 и выводит полученную информацию

    :param Archive:
    :param file_id:
    """
    engine = create_engine(str(get_connection_string()))
    if Archive == 0:
        sql = ("Select  `ID`, `FileName`, `FileSize`, `File_ID`, `XTALROW`, `Temp`, "
               "`FS`, `FL` from `kh7700` where `File_ID` = '" + file_id + "' order by `ID`")
    else:
        sql = ("Select  `ID`, `FileName`, `FileSize`, `File_ID`, `XTALROW`, `Temp`, "
               "`FS`, `FL` from `kh7700_archive` where `File_ID` = '" + file_id + "' order by `ID`")
    df = pd.read_sql_query(sql, engine)  # Запращиваем данные файла
    if not df.empty:
        # Получение уникальных значений из колонки Temp
        unique_temps = df['Temp'].unique().tolist()
        # Получение уникальных значений из колонки XTALROW
        unique_xtalrows = df['XTALROW'].unique().tolist()
        # Преобразуем в цифровые значения убрая ошибочные символы
        unique_temps = sorted(unique_temps)  # Сортируем по возрастанию
        # Формируем температурный интервал
        result_string, result_step = analyse_temp(unique_temps)
        if result_step is not None:
            print('Температурный интревал', result_string, 'Шаг', result_step)
        else:
            print('Температурный интревал', result_string)
        # Формируем список позиций
        # print('Разбиение на позиции:')
        df_pos = analyse_positions_kh7700(unique_xtalrows)
        # print('Найдено интервалов', df_pos.shape[0])
        df_data = analyse_data_test(df, df_pos, 'KH7700')
        print('Анализ данных...')
        df_data['Temp'] = result_string
        df_data['Temp_Step'] = result_step
        df_data['Temp_List'] = [unique_temps] * len(df_data)
        df_data['Position_Count'] = df_data['Position'].apply(lambda x: len(x) if isinstance(x, list) else 0)
        selected_columns = ['Position_str', 'Номинал', 'Selected_Temp', 'Temp', 'CL_Metod', 'CL_Value']
        print(tabulate(df_data[selected_columns], headers=selected_columns, tablefmt='grid', showindex=False))
        # Сохраняем конфигурацию файла
        MEASURE_DATA.measure_file['Status'] = 'Load'
        MEASURE_DATA.measure_file['Configuration'] = df_data
        return df_data


def get_file_inf_TCH2200(file_id: str, archive):
    """
    Метод производит анализ файла из установки ТЧХ2200 и выводит полученную информацию.
    Параметр archive не используется, но сохранён для совместимости.
    """
    engine = create_engine(str(get_connection_string()))
    file_name = MEASURE_DATA.measure_file['FileName']

    # Извлекаем msk_name и RunId из имени файла (формат: "msk_name_RunId.db")
    base = file_name.replace('.db', '')
    parts = base.split('_')
    if len(parts) < 2:
        print(f"Ошибка: не удалось разобрать имя файла {file_name}")
        return pd.DataFrame()

    RunId = parts[-1]
    msk_name = '_'.join(parts[:-1])

    # SQL-запрос напрямую к tch2200_measurement_data, без JOIN
    sql = """
        SELECT
            `Position`,
            `TemperatureSetPoint` AS Temp,
            `ActualFR` AS Fs,
            `ActualFL` AS Fl,
            `RR` AS R,
            `C0`,
            `C1`,
            `Q`,
            `L`,
            `batch_id` AS SETUPNUM,
            `Mode`,
            `PL`,
            `ReferenceFrequency`,
            `ReferenceCL`
        FROM `tch2200_measurement_data`
        WHERE `msk_name` = %s AND `RunId` = %s
    """
    df = pd.read_sql(sql, engine, params=(msk_name, RunId))
    df['SETUPNUM'] = 1
    if df.empty:
        print("Данные не найдены")
        return df

    # Удаляем строки с отсутствующей позицией
    df = df.dropna(subset=['Position'])
    print(df.head(30))
    # Анализ температур
    unique_temps = df['Temp'].unique().tolist()
    temp_str, temp_step = analyse_temp(unique_temps)
    print('Температурный интервал', temp_str, 'Шаг', temp_step)

    # Анализ позиций и разбиение на интервалы по партиям (SETUPNUM)
    df_pos = analyse_positions_TCH2200(df)
    print('Найдено интервалов:', df_pos.shape[0])
    print(df_pos)

    # Получение усреднённых данных по каждой партии
    df_data = get_avg_data(df, df_pos, 'ТЧХ2200')

    # Добавляем служебные колонки (температурный интервал)
    df_data['Temp'] = temp_str
    df_data['Temp_Step'] = temp_step
    df_data['Temp_List'] = [unique_temps] * len(df_data)

    # Вычисляем целевую частоту и номинал
    df_data = set_target_freq(df_data, 'ТЧХ2200')
    df_data = get_nominal(df_data, 'ТЧХ2200')

    # ВОССТАНАВЛИВАЕМ температурные колонки (get_nominal их удаляет)
    df_data['Temp'] = temp_str
    df_data['Temp_Step'] = temp_step
    df_data['Temp_List'] = [unique_temps] * len(df_data)

    df_data['Position_Count'] = df_data['Position'].apply(lambda x: len(x) if isinstance(x, list) else 0)

    # Вывод в консоль
    selected_columns = ['Position_str', 'Номинал', 'Selected_Temp', 'Temp', 'CL_Metod', 'CL_Value']
    print(tabulate(df_data[selected_columns], headers=selected_columns, tablefmt='grid', showindex=False))

    # Сохраняем конфигурацию файла
    MEASURE_DATA.measure_file['Status'] = 'Load'
    MEASURE_DATA.measure_file['Configuration'] = df_data
    return df_data


def analyse_positions_TCH2200(df: pd.DataFrame):
    # Убираем группировку по SETUPNUM, работаем со всеми позициями сразу
    unique_pos = df['Position'].unique()
    groups = {}
    for item in unique_pos:
        item = str(item)
        match = re.match(r"^([A-Za-z]+)(\d+)$", item, re.IGNORECASE)
        if match:
            letter = match.group(1).upper()
            number = int(match.group(2))
            groups.setdefault(letter, []).append(number)

    interval_strings = []
    all_positions_norm = []
    for letter in sorted(groups.keys()):
        numbers = sorted(groups[letter])
        if not numbers:
            continue

        start = numbers[0]
        prev = start
        intervals = []
        for num in numbers[1:]:
            if num != prev + 1:
                intervals.append((start, prev))
                start = num
            prev = num
        intervals.append((start, prev))

        for start_n, end_n in intervals:
            if start_n == end_n:
                pos_str = f"{letter}{start_n:03d}"
            else:
                pos_str = f"{letter}{start_n:03d}-{letter}{end_n:03d}"
            interval_strings.append(pos_str)

            for i in range(start_n, end_n + 1):
                all_positions_norm.append(f"{letter}{i}")

    position_str = ', '.join(interval_strings)
    result = [{
        'SETUPNUM': 1,
        'Position_str': position_str,
        'Position': all_positions_norm
    }]
    return pd.DataFrame(result)


def get_file_inf_TTS100(file_id: str, archive):
    """
    Метод производит анализ файла из установки TTS-100 и выводит полученную информацию
    :param file_id:
    :param archive:
    :return:
    """
    df_data = []
    engine = create_engine(str(get_connection_string()))
    if archive == 0:
        sql = ("Select  `SETUPNUM`, `RINGID`, `RINGPOS`, `SETPOINT`, `F0_MHZ`, "
               "`FL_MHZ`, `CLSTATUS`,`TCL_PF`,`ACL_PF`, `CHAMBER`, `FileName`, `Size`, "
               "`File_ID`  from `transat` where `File_ID` = '"
               + file_id + "' order by `ID`")
    else:
        sql = ("Select  `SETUPNUM`, `RINGID`, `RINGPOS`, `SETPOINT`, `F0_MHZ`, "
               "`FL_MHZ`, `CLSTATUS`,`TCL_PF`,`ACL_PF` , `CHAMBER`, `FileName`, `Size`, `File_ID` "
               " from `tts100_archive` where "
               "`File_ID` = '" + file_id + "' order by `ID`")
    df = pd.read_sql_query(sql, engine)  # Запращиваем данные файла
    if not df.empty:
        # Получение уникальных значений из колонки Temp
        unique_temps = df['SETPOINT'].unique().tolist()
        temp_str, temp_step = analyse_temp(unique_temps)
        print('Температуры', temp_str, 'Шаг', temp_step)
        pos, df_with_pos = analyse_positions_tts100(df)
        # print('Найдено интервалов', pos.shape[0])
        # print('Интервал')
        # print(pos)
        print('Анализ данных...')
        df_data = analyse_data_test(df_with_pos, pos, 'Transat')

        df_data['Temp'] = temp_str
        df_data['Temp_Step'] = temp_step
        df_data['Temp_List'] = [unique_temps] * len(df_data)
        df_data['Position_Count'] = df_data['Position'].apply(lambda x: len(x) if isinstance(x, list) else 0)
        selected_columns = ['Position_str', 'Номинал', 'Selected_Temp', 'Temp', 'CL_Metod', 'CL_Value']
        print(tabulate(df_data[selected_columns], headers=selected_columns, tablefmt='grid', showindex=False))
        # Сохраняем конфигурацию файла
        MEASURE_DATA.measure_file['Status'] = 'Load'
        MEASURE_DATA.measure_file['Configuration'] = df_data
    return df_data


def get_file_inf_W2200(file_id: str, archive):
    df_data = []
    engine = create_engine(str(get_connection_string()))
    if archive == 0:
        sql = ("Select  `nSetupFileIndex`, `strCrystalID`, `fSetTemperature`, "
               " `Name`, `Size`, `File_ID`, `fFrequencyPPM`  from `crystal data` where `File_ID` = '"
               + file_id + "' order by `strCrystalID`")
    else:
        sql = ("Select  `nSetupFileIndex`, `strCrystalID`, `fSetTemperature`, "
               " `Name`, `Size`, `File_ID`, `fFrequencyPPM`  from `crystal data_archive` where `File_ID` = '"
               + file_id + "' order by `strCrystalID`")
    df = pd.read_sql_query(sql, engine)  # Запращиваем данные файла
    if not df.empty:
        # Получение уникальных значений из колонки Temp
        unique_temps = df['fSetTemperature'].unique().tolist()
        temp_str, temp_step = analyse_temp(unique_temps)
        print('Температуры', temp_str, 'Шаг', temp_step)
        pos, data = analyse_positions_W2200(df)
        pos_print = pos[['SETUPNUM', 'Position_str']]
        print('Найдены интервалы позиций')
        print(pos_print)
        df_data = analyse_data_W2200(data, pos, 'Saunders', file_id, archive)
        df_data['Temp'] = temp_str
        df_data['Temp_Step'] = temp_step
        df_data['Temp_List'] = [unique_temps] * len(df_data)
        df_data['Position_Count'] = df_data['Position'].apply(lambda x: len(x) if isinstance(x, list) else 0)
        selected_columns = ['Position_str', 'Номинал', 'Selected_Temp', 'Temp', 'CL_Metod', 'CL_Value']
        print(tabulate(df_data[selected_columns], headers=selected_columns, tablefmt='grid', showindex=False))
        # Сохраняем конфигурацию файла
        MEASURE_DATA.measure_file['Status'] = 'Load'
        MEASURE_DATA.measure_file['Configuration'] = df_data
    return df_data


def analyse_temp(unique_temps):
    """
    Метод формирует строчку температурного интревала для заданного файла
    :param unique_temps:  Список температур
    :return: Строка интревала,  Шаг
    """
    unique_temps = sorted(unique_temps)  # Сортируем по возрастанию
    if len(unique_temps) > 1:
        a = unique_temps[0]  # Первое число
        b = unique_temps[-1]  # Последнее число
        result_string = f"{a}...{b}"  # Температурный интервал
        step = unique_temps[1] - unique_temps[0]  # Шаг между первыми двумя элементами
        is_uniform_step = all(
            abs((unique_temps[i + 1] - unique_temps[i]) - step) < 1e-6  # Проверка на равномерность шага
            for i in range(len(unique_temps) - 1))
        if is_uniform_step:
            result_step = step
        else:
            result_step = None
    else:
        result_string = unique_temps[0]
        result_step = None
    return result_string, result_step


def analyse_positions_kh7700(unique_xtalrows):
    """
    Метод анализирует позиции в файле и разбивает их на интревалы по имеющимся пропускам позиций
    :param unique_xtalrows: {} Список уникальных позиций файла
    :return: DataFrame (index, Position_str, Positions)
    """
    # Группируем элементы по букве и извлекаем числа
    groups = {}
    for item in unique_xtalrows:
        item = str(item)  # На случай, если элементы не строковые
        match = re.match(r"^([A-Za-z]+)(\d+)$", item, re.IGNORECASE)
        if match:
            letter = match.group(1).upper()
            number = int(match.group(2))
            if letter not in groups:
                groups[letter] = []
            groups[letter].append(number)

    # Сортируем группы по алфавиту и числа внутри групп
    sorted_letters = sorted(groups.keys())
    data = []
    for letter in sorted_letters:
        numbers = sorted(groups[letter])
        if not numbers:
            continue

        # Формируем интервалы
        intervals = []
        start = numbers[0]
        prev = start

        for num in numbers[1:]:
            if num != prev + 1:
                intervals.append((start, prev))
                start = num
            prev = num
        intervals.append((start, prev))  # Добавляем последний интервал

        # Создаем записи для DataFrame
        for interval in intervals:
            start, end = interval
            # Формируем строку интервала
            if start == end:
                position_str = f"{letter}{start}"
            else:
                position_str = f"{letter}{start}-{letter}{end}"

            # Формируем список всех позиций в интервале
            positions = [f"{letter}{i}" for i in range(start, end + 1)]

            data.append({"Position_str": position_str, "Position": positions})

    # Создаем DataFrame
    df = pd.DataFrame(data)
    return df


def analyse_data_test(df_main: pd.DataFrame, df_intervals: pd.DataFrame, machine_type: str):
    """Обрабатывает данные, добавляя номинальные значения."""
    result_df = get_avg_data_tts100_kh7700(df_main, df_intervals, machine_type)
    # Добавление номиналов (логика функции get_nominal не показана)
    nom = get_nominal(result_df, machine_type)
    return nom


def get_avg_data_tts100_kh7700(df_main: pd.DataFrame, df_intervals: pd.DataFrame, machine_type: str,
                               file_id='') -> pd.DataFrame:
    """Основная функция с исправленной обработкой температур"""
    global filtered
    machine_config = {
        'KH7700': {
            'position_col': 'XTALROW',
            'fs_col': 'FS',
            'fl_col': 'FL',
            'temp_col': 'Temp',
            'filter_cond': lambda df: df['FS'] != 0
        },
        'Transat': {
            'position_col': 'position',
            'fs_col': 'F0_MHZ',
            'fl_col': 'FL_MHZ',
            'temp_col': 'SETPOINT',  # Исправлено: SETPOINT вместо SETPOINT
            'filter_cond': lambda df, sn: (df['F0_MHZ'] != 0) & (df['SETUPNUM'] == sn)
        }
    }

    results = []
    config = machine_config.get(machine_type, {})

    for _, row in df_intervals.iterrows():
        # Фильтрация основных данных
        position_filter = df_main[config['position_col']].isin(row['Position'])

        # Тип-специфичная фильтрация
        if machine_type == 'KH7700':
            filtered = df_main[position_filter & config['filter_cond'](df_main)]
        elif machine_type == 'Transat':
            setupnum = row['SETUPNUM']
            filtered = df_main[position_filter & config['filter_cond'](df_main, setupnum)]

        if filtered.empty:
            continue

        # Получение температур с обработкой NaN
        temps = filtered[config['temp_col']].dropna().values
        target_temp = get_target_temp(temps)

        if target_temp is None:
            continue  # Пропускаем интервалы без валидных температур

        # Фильтрация по целевой температуре
        temp_filtered = filtered[filtered[config['temp_col']] == target_temp]

        if temp_filtered.empty:
            continue

        # Усреднение и сохранение результатов
        results.append({
            'SETUPNUM': row.get('SETUPNUM', 0),
            'FS': temp_filtered[config['fs_col']].mean(),
            'FL': temp_filtered[config['fl_col']].mean(),
            'CL': get_cl_status(temp_filtered, machine_type)[0],
            'CL_Metod': get_cl_status(temp_filtered, machine_type)[1],
            'CL_Value': get_cl_status(temp_filtered, machine_type)[2],
            'Position_str': row['Position_str'],
            'Position': row['Position'],
            'Selected_Temp': target_temp
        })

    return pd.DataFrame(results)


def get_avg_data(df_main: pd.DataFrame, df_intervals: pd.DataFrame, machine_type: str, file_id='', archive=0) \
        -> pd.DataFrame:
    """
    Метод получает датафрейм с усредненными значениями номинальных частот по позициям в каждой партии
    :param archive:
    :param file_id: ИД файла опционально только для W2200
    :param df_main:  Основные данные
    :param df_intervals:  Выбранные интервалы позиций по партиям
    :param machine_type: Тип установки Transat/KH7700/W2200/TCH2200
    :return:
    """
    # Шаг 1: Фильтрация и усреднение данных
    results = []
    result_df = pd.DataFrame()

    if machine_type == 'KH7700':
        count = 1
        for _, row in df_intervals.iterrows():
            # Выбираем позиции интервала и фильтруем данные
            filtered = df_main[
                df_main['XTALROW'].isin(row['Position']) &
                (df_main['FS'] != 0)
                ]
            if filtered.empty:
                continue
            # Усредняем Fs и FL
            avg_data = filtered[['FS', 'FL']].mean().to_dict()
            avg_data['Position_str'] = row['Position_str']
            avg_data['Temps'] = filtered['Temp'].tolist()
            avg_data['Position'] = row['Position']
            clstatus, cl_metod, cl_value = get_cl_status(df_main=filtered, machine_type='KH7700')
            avg_data['CL'] = clstatus
            avg_data['CL_Metod'] = cl_metod
            avg_data['CL_Value'] = cl_value
            avg_data['SETUPNUM'] = count
            count = count + 1
            results.append(avg_data)
            result_df = pd.DataFrame(results)

    elif machine_type == 'Transat':
        for _, row in df_intervals.iterrows():
            # Выбираем позиции интервала и фильтруем данные
            filtered = df_main[
                df_main['position'].isin(row['Position']) &
                (df_main['F0_MHZ'] != 0) &
                (df_main['SETUPNUM'] == row['SETUPNUM'])
                ]
            if filtered.empty:
                continue
            # Усредняем Fs и FL
            avg_data = filtered[['F0_MHZ', 'FL_MHZ']].mean().to_dict()
            avg_data['Position_str'] = row['Position_str']
            avg_data['Temps'] = filtered['SETPOINT'].tolist()
            avg_data['Position'] = row['Position']
            clstatus, cl_metod, cl_value = get_cl_status(df_main=filtered, machine_type='Transat')
            avg_data['CL'] = clstatus
            avg_data['CL_Metod'] = cl_metod
            avg_data['CL_Value'] = cl_value
            avg_data['SETUPNUM'] = row['SETUPNUM']
            results.append(avg_data)
            result_df = pd.DataFrame(results)

    elif machine_type == 'Saunders':
        engine = create_engine(str(get_connection_string()))
        # Запрашиваем данные частот из таблицы setup data
        if archive == 1:
            sql = ("select `nSetupFileIndex`, `strCrystalID`, `fSetTemperature`, `fValue1` "
                   "from `setup data_archive` where `File_ID`='" + str(file_id) + "' order by `nSetupFileIndex`")
        else:
            sql = ("select `nSetupFileIndex`, `strCrystalID`, `fSetTemperature`, `fValue1` "
                   "from `setup data` where `File_ID`='" + str(file_id) + "' order by `nSetupFileIndex`")
        df_setupdata = pd.read_sql_query(sql, engine)
        # Запрашиваем данные частот из таблицы setup file headers
        if archive == 1:
            sql = ("select `nSetupFileIndex`, `fReferenceFrequency`, `strLoadType` from `setup file headers_archive`"
                   " where `File_ID`='" + str(file_id) + "' order by `nSetupFileIndex`")
        else:
            sql = ("select `nSetupFileIndex`, `fReferenceFrequency`, `strLoadType` from `setup file headers`"
                   " where `File_ID`='" + str(file_id) + "' order by `nSetupFileIndex`")
        df_headers = pd.read_sql_query(sql, engine)
        # Объединение Crystal Data и Setup Data
        merged_step1 = pd.merge(
            df_main,
            df_setupdata,
            on=['nSetupFileIndex', 'strCrystalID', 'fSetTemperature'],
            how='inner'
        )

        # Добавляем strLoadType из df_headers
        merged_step2 = pd.merge(
            merged_step1,
            df_headers[['nSetupFileIndex', 'strLoadType', 'fReferenceFrequency']],  # Берём только нужные колонки
            on='nSetupFileIndex',
            how='left'
        )
        # Объединение с setup_positions по SETUPNUM
        merged_all = pd.merge(
            merged_step2,
            df_intervals,
            left_on='nSetupFileIndex',
            right_on='SETUPNUM',
            how='inner'
        )
        # Получаем список температур
        temp_list = merged_all['fSetTemperature'].unique().tolist()
        # Получаем референсную температуру
        target_temp = get_target_temp_w2200(temp_list)

        # Очистка от некорректных значений в колонках fValue1 и fFrequencyPPM
        merged_all['fValue1'] = pd.to_numeric(merged_all['fValue1'], errors='coerce')
        merged_all['fFrequencyPPM'] = pd.to_numeric(merged_all['fFrequencyPPM'], errors='coerce')
        # Удаление строк с NaN в колонках fValue1 и fFrequencyPPM
        merged_all = merged_all.dropna(subset=['fValue1', 'fFrequencyPPM'])

        # Фильтрация:
        # 1. Удаление строк с fFrequencyPPM == 1E30
        # 2. Оставляем только строки с целевой температурой (fSetTemperature == целевое значение для партии)
        filtered = merged_all[
            (merged_all['fFrequencyPPM'] != 1e30) &
            (merged_all['fSetTemperature'] == target_temp)
            ]
        # Группировка и агрегация только по SETUPNUM
        grouped = filtered.groupby('SETUPNUM').agg({
            'fFrequencyPPM': 'mean',  # Усреднение FS
            'fValue1': 'mean',  # Усреднение FL
            'strLoadType': 'first',  # Первый тип нагрузки
            'fSetTemperature': lambda x: list(x.unique()),
            'fReferenceFrequency': 'first'  # Первый номинал
        }).reset_index()
        # Добавление Position и Position_str из setup_positions
        output_df = pd.merge(
            grouped,
            df_intervals[['SETUPNUM', 'Position', 'Position_str']],
            on='SETUPNUM',
            how='left'
        )
        # Переименование колонок
        output_df.rename(columns={
            'fFrequencyPPM': 'FS',
            'fValue1': 'FL',
            'fSetTemperature': 'Temps',
            'fReferenceFrequency': 'Target_Hz'
        }, inplace=True)
        # Добавление колонок
        output_df['CL_Metod'] = output_df.apply(determine_cl_metod, axis=1)
        output_df['CL_Value'] = 0
        output_df['CL'] = output_df['CL_Metod'].ne('SERIES').astype(int)

        # Формирование финального датафрейма
        result_df = output_df[[
            'SETUPNUM', 'FS', 'FL', 'CL_Metod', 'CL_Value', 'CL',
            'Position', 'Position_str', 'Temps', 'Target_Hz'
        ]]

    # ========== НОВАЯ ВЕТКА ДЛЯ ТЧХ2200 ==========
    elif machine_type == 'ТЧХ2200':
        # Приводим SETUPNUM к целому числу
        df_main['SETUPNUM'] = df_main['SETUPNUM'].astype(int)
        df_main['SETUPNUM'] = 1

        # Функция для удаления ведущих нулей из позиции (например, A001 -> A1)
        def normalize_position(pos):
            import re
            match = re.match(r'^([A-Za-z]+)(\d+)$', pos)
            if match:
                letter = match.group(1)
                number = int(match.group(2))  # int автоматически убирает ведущие нули
                return f"{letter}{number}"
            return pos

        df_main['Position_norm'] = df_main['Position'].apply(normalize_position)

        results = []
        for _, row in df_intervals.iterrows():
            # Фильтруем по SETUPNUM и нормализованным позициям
            filtered = df_main[
                (df_main['SETUPNUM'] == row['SETUPNUM']) &
                (df_main['Position_norm'].isin(row['Position']))
                ]
            if filtered.empty:
                continue

            # Усредняем необходимые параметры
            avg_data = filtered[['Fs', 'Fl', 'R', 'C0', 'C1', 'Q', 'L']].mean().to_dict()
            avg_data['Position_str'] = row['Position_str']
            avg_data['Position'] = row['Position']  # список позиций без ведущих нулей
            avg_data['SETUPNUM'] = row['SETUPNUM']
            avg_data['Temps'] = filtered['Temp'].unique().tolist()
            target_temp = get_target_temp(np.array(avg_data['Temps']))
            avg_data['Selected_Temp'] = target_temp
            avg_data['Mode'] = filtered['Mode'].iloc[0] if 'Mode' in filtered.columns else 0
            avg_data['PL'] = filtered['PL'].iloc[0] if 'PL' in filtered.columns else 0
            ref_cl = filtered['ReferenceCL'].iloc[0] if 'ReferenceCL' in filtered.columns else 0
            avg_data['ReferenceCL'] = ref_cl
            clstatus, cl_metod, cl_value = get_cl_status(filtered, machine_type, avg_data)
            avg_data['CL'] = clstatus
            avg_data['CL_Metod'] = cl_metod
            avg_data['CL_Value'] = cl_value

            results.append(avg_data)

        if results:
            result_df = pd.DataFrame(results)
            result_df.rename(columns={'Fs': 'FS', 'Fl': 'FL'}, inplace=True)
        else:
            result_df = pd.DataFrame()

    return result_df


def get_target_temp_w2200(temps):
    """Определяет целевую температуру на основе списка температур.
    :param temps:
    :return:
    """
    if not temps:
        return None
    if 25 in temps:
        return 25
    sorted_temps = sorted(temps)
    mid = (sorted_temps[0] + sorted_temps[-1]) / 2
    return min(sorted_temps, key=lambda x: abs(x - mid))


def get_target_temp(temps: np.ndarray) -> float | None:
    """
    Определяет целевую температуру на основе массива температур.
    Возвращает None, если данных недостаточно.
    """
    # Удаление NaN и проверка на пустоту
    valid_temps = temps[~np.isnan(temps)]
    if valid_temps.size == 0:
        return None

    # Проверка наличия 25°C
    if 25 in valid_temps:
        return 25.0

    # Определение середины диапазона
    sorted_temps = np.sort(valid_temps)
    mid = (sorted_temps[0] + sorted_temps[-1]) / 2
    return sorted_temps[np.abs(sorted_temps - mid).argmin()]


# Функция для определения CL_Metod
def determine_cl_metod(row):
    load_type = row['strLoadType']
    fs = row['FS']
    fl = row['FL']
    diff = abs(fs - fl)
    if load_type == 'Measured FL':
        return 'EQREACT' if diff > 1 else 'SERIES'
    elif load_type == 'Calculated FL':
        return 'NUMERICAL' if diff > 1 else 'SERIES'
    elif load_type == 'Physical FL':
        return 'PHYSICAL'
    return 'Unknown'


def get_cl_status(df_main: pd.DataFrame, machine_type: str, extra_data: dict = None):
    """
    Метод добавляет в строку датафрейм колонки содержащие тип измерения в зависимости от емкости
    :param df_main:
    :param machine_type:
    :param extra_data: дополнительные данные для определения режима (используется для TCH2200)
    :return:
    """
    clstatus = 0
    clmetod = ''
    cl_value = '0'

    if machine_type == 'KH7700':
        if df_main['FL'].mean() > 0:
            clstatus = 1
            clmetod = 'EQREACT'
        else:
            clstatus = 0
            clmetod = 'SERIES'
        cl_value = '0'

    elif machine_type == 'Transat':
        if df_main['CLSTATUS'].iloc[0] == 0:
            clstatus = 0
            clmetod = 'SERIES'
            cl_value = '0'
        elif df_main['CLSTATUS'].iloc[0] == 1:
            clstatus = 1
            clmetod = 'PHYSICAL'
            cl_value = f"{float(df_main['TCL_PF'].iloc[0]):.0f}" + '(' + f"{float(df_main['ACL_PF'].iloc[0]):.0f}" + ')'
        elif df_main['CLSTATUS'].iloc[0] == 2:
            clstatus = 1
            clmetod = 'NUMERICAL'
            cl_value = '0'
        elif df_main['CLSTATUS'].iloc[0] == 3:
            clstatus = 1
            clmetod = 'EQREACT'
            cl_value = f"{float(df_main['TCL_PF'].iloc[0]):.0f}"
        else:
            clstatus = 0
            clmetod = 'ERROR'
            cl_value = '0'

    # ========== НОВАЯ ВЕТКА ДЛЯ ТЧХ2200 ==========
    elif machine_type in ('ТЧХ2200', 'TCH2200'):
        if extra_data is not None:
            mode = extra_data.get('Mode', 0)
            pl = extra_data.get('PL', 0)
            ref_cl = extra_data.get('RefCL', 0)
        else:
            mode = df_main['Mode'].iloc[0] if 'Mode' in df_main.columns else 0
            pl = df_main['PL'].iloc[0] if 'PL' in df_main.columns else 0
            ref_cl = df_main['RefCL'].iloc[0] if 'RefCL' in df_main.columns else 0

        # Приведение к числам
        try:
            mode = float(mode)
            pl = float(pl)
            ref_cl = float(ref_cl)
        except (ValueError, TypeError):
            mode = 0
            pl = 0
            ref_cl = 0

        if mode == 1:  # SERIES
            clstatus = 0
            clmetod = 'SERIES'
            cl_value = '0'
        elif mode == 2:  # EQREACT
            clstatus = 1
            clmetod = 'EQREACT'
            cl_value = f"{ref_cl:.1f}" if ref_cl != 0 else '0'
        elif mode == 3 and pl > 0:  # PHYSICAL
            clstatus = 1
            clmetod = 'PHYSICAL'
            cl_value = f"{pl:.1f}"
        else:
            clstatus = 0
            clmetod = 'SERIES'
            cl_value = '0'

    return clstatus, clmetod, cl_value


def analyse_data(df_main: pd.DataFrame, df_intervals: pd.DataFrame, machine_type: str, file_id=''):
    """
    Метод получает среднюю частоту Fs/FL для данной партии на температуре 25 либо на середине
    рабочего интревала температур.
    :param file_id:
    :param machine_type: Тип установки
    :param df_main: Таблица KH7700
    :param df_intervals:  Список интревалов позиций метод analyse_positions_kh7700
    :return: DataFrame
    """
    fs = 'FS'
    fl = 'FL'
    result_df = get_avg_data(df_main, df_intervals, machine_type=machine_type,
                             file_id=file_id)  # Получаем усредененные данные
    # Шаг 2: Обработка температур
    final_data = []
    for _, row in result_df.iterrows():
        temps = row['Temps']
        target_temp = None

        # Проверка наличия 25
        if 25 in temps:
            target_temp = 25
        else:
            if len(temps) == 1:
                target_temp = temps[0]
            else:
                mid = (min(temps) + max(temps)) / 2
                closest = min(temps, key=lambda x: abs(x - mid))
                target_temp = closest
        if machine_type == 'KH7700':
            fs = 'FS'
            fl = 'FL'
        elif machine_type == 'Transat':
            fs = 'F0_MHZ'
            fl = 'FL_MHZ'
        final_data.append({
            'Position_str': row['Position_str'],
            'FS': row[fs],
            'FL': row[fl],
            'Selected_Temp': target_temp,
            'Position': row['Position'],
            'CL': row['CL'],
            'CL_Metod': row['CL_Metod'],
            'CL_Value': row['CL_Value'],
            'SETUPNUM': row['SETUPNUM'],
        })
    final_df = pd.DataFrame(final_data)
    nom = get_nominal(final_df, machine_type)  # Добавляем номинальные частоты
    return nom


def analyse_data_W2200(df_main: pd.DataFrame, df_intervals: pd.DataFrame, machine_type: str, file_id='', archive=0):
    """
    Метод получает среднюю частоту Fs/FL для данной партии на температуре 25 либо на середине
    рабочего интревала температур.
    :param archive:
    :param file_id:
    :param machine_type: Тип установки
    :param df_main: Таблица KH7700
    :param df_intervals:  Список интревалов позиций метод analyse_positions_kh7700
    :return: DataFrame
    """
    fs = 'FS'
    fl = 'FL'
    result_df = get_avg_data(df_main, df_intervals, machine_type=machine_type,
                             file_id=file_id, archive=archive)  # Получаем усредененные данные
    final_data = []

    for _, row in result_df.iterrows():
        temps_list = row['Temps']
        target_temp = get_target_temp_w2200(temps_list)
        final_data.append({
            'Position_str': row['Position_str'],
            'FS': row[fs],
            'FL': row[fl],
            'Selected_Temp': target_temp,
            'Position': row['Position'],
            'CL': row['CL'],
            'CL_Metod': row['CL_Metod'],
            'CL_Value': row['CL_Value'],
            'SETUPNUM': row['SETUPNUM'],
            'Target_Hz': row['Target_Hz']
        })
    final_df = pd.DataFrame(final_data)
    nom = get_nominal(final_df, machine_type)  # Добавляем номинальные частоты
    return nom


# Функция для поиска ближайших спецификаций
def find_closest_specs(row, df_nom: pd.DataFrame):
    """
    Метод находит ближайший номинал для заданных изделий и создает для них список спецификаций
    :param row:
    :param df_nom:
    :return:
    """
    target = row['Target_Hz']
    nominal_freq = 0
    specs = []
    specs_id = []
    spc_id_list = []
    spc_name_list = []
    # Вычисляем разницу в ppm (частей на миллион)
    df_nom['F_diff_ppm'] = np.abs((df_nom['частота'] - target) / target * 1e6)
    print("find_closest")

    # Находим минимальную разницу
    min_diff_ppm = df_nom['F_diff_ppm'].min()
    df_spc_id = pd.DataFrame()
    # Если минимальная разница > 100 ppm, берем FL_Hz (если > 0), иначе Fs_Hz
    print('Row', row)
    print('Target', target)
    print('Min', min_diff_ppm)
    if min_diff_ppm > 100:
        nominal_freq = target
        nominal_freq = round(nominal_freq)  # Округляем до Гц
        specs = []  # Нет подходящих спецификаций
        specs_id = []  # Нет подходящих спецификаций
        print('Номинал не найден')
    else:

        # Фильтруем все спецификации с минимальной разницей
        candidates = df_nom[df_nom['F_diff_ppm'] == min_diff_ppm]
        print('Find_closest', 'Candidates', candidates)
        # Подбор по ёмкости нагрузки убран: сравнение значений CL между
        # файлом и спецификацией отбраковывало корректные номенклатуры.
        if not candidates.empty:
            nominal_freq = round(candidates['частота'].iloc[0])  # Округляем до Гц
            specs = candidates['наименование'].tolist()  # Список спецификаций
            specs_id = candidates['номенклатура'].tolist()  # Список спецификаций ID
            df_spc_id = get_psi_specification(specs_id)

            if not df_spc_id.empty:
                spc_id_list = df_spc_id['SpcID'].tolist()
                spc_name_list = df_spc_id['SpcName'].tolist()

        else:
            nominal_freq = target
            nominal_freq = round(nominal_freq)  # Округляем до Гц

    return pd.Series([nominal_freq, specs, specs_id, spc_id_list, spc_name_list])


# Получает список мульти спецификаций для данного температурного интервала
def get_multy_spec(row):
    result = []
    # Получаем текущий списка температур
    temp_list = row['Temp_List']
    engine = create_engine(str(get_connection_string()))
    sql = "Select * from spc_special"
    # Получаем список возможных спецификаций
    spc_df = pd.read_sql(sql, engine)
    # Гибкое сопоставление: устойчиво к формату записи (25 vs 25.0,
    # разделители, покрытие, вложенность диапазонов, IoU)
    data_temps = parse_temp_list(temp_list)
    for index, spc_ in spc_df.iterrows():
        db_temps = parse_temp_list(spc_['Temps'])  # список температур
        if temps_match(db_temps, data_temps):
            result.append(spc_['Multy_Spc_Name'])
    return result


# Проверяет соответствие температурного интервала спецификации и измерительного файла
def test_temp_interval_points(data, spc_list):
    if not spc_list:
        return []

    engine = create_engine(str(get_connection_string()))

    # Формируем плейсхолдеры для IN-условия
    placeholders = ','.join(['%s'] * len(spc_list))
    spc_query = f"""
        SELECT s.`Name`, s.`Profile`, tp.`Temperatures`
        FROM `specification` s
        LEFT JOIN `temperatureprofile` tp 
        ON s.`Profile` = tp.`Name`
        WHERE s.`Name` IN ({placeholders})
    """

    try:
        # Преобразуем список в кортеж для параметров
        spc_df = pd.read_sql(spc_query, engine, params=tuple(spc_list))
    except Exception as e:
        print(f"Database error: {e}")
        return []

    if spc_df.empty:
        return []

    data_temps = parse_temp_list(data['Temp_List'])

    def check_temps(temp_str):
        # Гибкое сопоставление профилей: точное совпадение (±0.5 °C),
        # покрытие профиля измерением, вложенность диапазонов или
        # большое пересечение. Некорректный формат больше не роняет
        # сравнение строк температур.
        return temps_match(temp_str, data_temps)

    spc_df['Temps_test'] = spc_df['Temperatures'].apply(check_temps)

    return spc_df[spc_df['Temps_test']]['Name'].tolist()


# ============================================================================
# Подбор спецификаций под тип резонатора (гибкий + нейросетевой)
# ============================================================================

SPEC_FIELDS_SQL = """
    SELECT s.`Name`, s.`ID`, s.`Nominal`, s.`LoadType`, s.`Loadvalue`,
           s.`Multy`, s.`NameR`, s.`Profile`,
           tp.`Temperatures` AS ProfileTemps
    FROM `specification` s
    LEFT JOIN `temperatureprofile` tp
    ON s.`Profile` = tp.`Name`
"""


def _series_get(row, key):
    try:
        return row.get(key)
    except Exception:
        return None


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [v for v in value if v is not None and str(v) != 'nan']
    try:
        if pd.isna(value):
            return []
    except (TypeError, ValueError):
        pass
    return [value]


def _to_float(value, default=0.0):
    try:
        return float(str(value).strip().replace(',', '.'))
    except (TypeError, ValueError):
        return default


def _spec_row_to_dict(spec_row) -> dict:
    """Строка specification → словарь признаков спецификации."""
    try:
        multy = int(float(spec_row.get('Multy', 0) or 0)) != 0
    except (TypeError, ValueError):
        multy = str(spec_row.get('Multy', 0)).strip() in ('True', 'true')
    profile_temps = spec_row.get('ProfileTemps')
    return {
        'name': str(spec_row.get('Name') or ''),
        'id': str(spec_row.get('ID') or ''),
        'nominal': _to_float(spec_row.get('Nominal')),   # МГц
        'load_type': str(spec_row.get('LoadType') or ''),
        'load_value': _to_float(spec_row.get('Loadvalue')),
        'multy': multy,
        'rtype': str(spec_row.get('NameR') or ''),
        'profile_temps': None if profile_temps is None else str(profile_temps),
    }


def _row_to_ctx(row) -> dict:
    """
    Строка конфигурации файла → контекст признаков подбора
    (см. Virtual_Measure.Spc_Search_NN.build_feature_vector).
    """
    temps = parse_temp_list(_series_get(row, 'Temp_List'))
    ref_hz = _to_float(_series_get(row, 'Target_Hz'))
    if ref_hz <= 0:
        # Target_Hz отбрасывается при формировании итогового датафрейма,
        # номинал из get_nominal уже в Гц
        ref_hz = _to_float(_series_get(row, 'Номинал'))
    cl_metod = str(_series_get(row, 'CL_Metod') or 'SERIES')
    linked = set()
    for key in ('Spec_list', 'SpcName', 'Specs_ID', 'SpcID'):
        linked.update(str(v) for v in _as_list(_series_get(row, key)))
    return {
        'ref_hz': ref_hz,
        'cl_metod': cl_metod,
        'cl_value': _series_get(row, 'CL_Value'),
        'temps': temps,
        'linked': linked,
    }


def _rule_score(ctx: dict, spec: dict) -> float:
    """Правило совместимости (резерв при недоступной модели NN)."""
    score = 0.0
    cl_metod = str(ctx.get('cl_metod') or '')
    cl_value = _to_float(ctx.get('cl_value'))
    if spec['load_type'] == cl_metod:
        score += 2.0
    elif load_types_compatible(cl_metod, spec['load_type']):
        score += 1.0
    spec_hz = spec['nominal'] * 1e6
    if nominal_exact(spec_hz, ctx.get('ref_hz')):
        score += 2.0
    elif nominal_matches(spec_hz, ctx.get('ref_hz')):
        score += 1.0
    if ctx.get('cl_value') and cl_value > 0:
        if abs(spec['load_value'] - cl_value) / max(1.0, cl_value) <= 0.05:
            score += 0.5
    linked = ctx.get('linked') or ()
    if spec['name'] in linked or spec['id'] in linked:
        score += 1.0
    return score


def _rank_spec_dicts(ctx: dict, candidates, rtype=None):
    """
    Кандидаты (словари спецификаций) → [(имя, оценка)] по убыванию.
    Сначала ансамбль NN (Spc_Search_NN, kind='spcnn'), при недоступности
    модели — корпусное правило _rule_score.
    """
    if not candidates:
        return []
    try:
        from Virtual_Measure import Spc_Search_NN
        rtype = rtype or ctx.get('rtype')
        ranked = Spc_Search_NN.rank_spec_candidates(ctx, candidates,
                                                    rtype=rtype)
        if ranked:
            return [(d['name'], p) for d, p in ranked]
    except Exception as e:
        print(f"rank_spec_candidates (NN): {e}", flush=True)
    print("Модель spcnn недоступна, подбор по правилу совместимости",
          flush=True)
    scored = [(d, _rule_score(ctx, d)) for d in candidates]
    scored.sort(key=lambda dp: dp[1], reverse=True)
    return [(d['name'], s) for d, s in scored]


def _load_spec_fields(spc_names):
    """Загружает поля спецификаций (нагрузка, номинал, профиль) по именам."""
    if not spc_names:
        return pd.DataFrame()
    engine = create_engine(str(get_connection_string()))
    placeholders = ','.join(['%s'] * len(spc_names))
    sql = SPEC_FIELDS_SQL + f" WHERE s.`Name` IN ({placeholders})"
    try:
        return pd.read_sql(sql, engine, params=tuple(spc_names))
    except Exception as e:
        print(f"_load_spec_fields: {e}", flush=True)
        return pd.DataFrame()


def rank_spec_candidates(ctx: dict, spc_names, rtype=None):
    """
    Ранжирует спецификации по именам для контекста измерительного файла.
    Кандидаты сначала пропускаются через гибкую проверку температурного
    профиля (temps_match); фильтра по ёмкости нагрузки нет.
    """
    if not spc_names:
        return []
    spec_df = _load_spec_fields(list(spc_names))
    if spec_df.empty:
        return []
    data_temps = parse_temp_list(ctx.get('temps'))
    candidates = []
    for _, spec_row in spec_df.iterrows():
        d = _spec_row_to_dict(spec_row)
        if not temps_match(parse_temp_list(d.get('profile_temps')),
                           data_temps):
            continue
        candidates.append(d)
    return _rank_spec_dicts(ctx, candidates, rtype=rtype)


def find_spc_for_resonator(rtype, ctx=None, row=None, use_nn=True):
    """
    Надёжный подбор спецификаций под тип резонатора (NameR):
      1) берутся ВСЕ спецификации заданного типа из specification;
      2) гибкий фильтр по температурному профилю файла;
      3) ранжирование ансамблем NN (kind='spcnn'), резерв — правило
         совместимости (_rule_score).
    :param rtype: тип резонатора (specification.NameR)
    :param ctx: контекст из _row_to_ctx (или row из конфигурации файла)
    :param row: строка конфигурации файла (если ctx не задан)
    :param use_nn: использовать нейросетевое ранжирование
    :return: [(имя спецификации, оценка)] по убыванию оценки
    """
    if ctx is None and row is not None:
        ctx = _row_to_ctx(row)
    if not ctx:
        return []
    engine = create_engine(str(get_connection_string()))
    if rtype:
        sql = SPEC_FIELDS_SQL + " WHERE s.`NameR` = %s AND s.`Name` <> ''"
        params = (rtype,)
    else:
        sql = (SPEC_FIELDS_SQL +
               " WHERE s.`NameR` IS NOT NULL AND s.`NameR` <> '' "
               "AND s.`Name` <> ''")
        params = None
    try:
        spec_df = pd.read_sql(sql, engine, params=params)
    except Exception as e:
        print(f"find_spc_for_resonator: {e}", flush=True)
        return []
    if spec_df.empty:
        return []
    data_temps = parse_temp_list(ctx.get('temps'))
    candidates = []
    for _, spec_row in spec_df.iterrows():
        d = _spec_row_to_dict(spec_row)
        if not temps_match(parse_temp_list(d.get('profile_temps')),
                           data_temps):
            continue
        candidates.append(d)
    if not use_nn:
        scored = [(d, _rule_score(ctx, d)) for d in candidates]
        scored.sort(key=lambda dp: dp[1], reverse=True)
        return [(d['name'], s) for d, s in scored]
    return _rank_spec_dicts(ctx, candidates, rtype=rtype)


def build_spc_candidate_list(row):
    """
    Формирует итоговый список спецификаций (SpcName) для строки
    конфигурации файла:
      * базовые кандидаты find_closest_specs (Spec_list) и привязки PSI
        (SpcID / Specs_ID → nomeklatura_rk_psi);
      * мульти-спецификации spc_special (гибкое совпадение интервала);
      * гибкая проверка температурного профиля (temps_match);
      * ранжирование нейросетью Spc_Search_NN (kind='spcnn'), резерв —
        правило совместимости (_rule_score).
    """
    names = []
    for key in ('Spec_list', 'SpcName'):
        for v in _as_list(_series_get(row, key)):
            v = str(v)
            if v and v not in names:
                names.append(v)
    ids = []
    for key in ('Specs_ID', 'SpcID'):
        ids.extend(_as_list(_series_get(row, key)))
    if ids:
        try:
            df_psi = get_psi_specification(ids)
            for v in df_psi['SpcName'].tolist():
                v = str(v)
                if v and v not in names:
                    names.append(v)
        except Exception as e:
            print(f"build_spc_candidate_list (psi): {e}", flush=True)
    try:
        for v in get_multy_spec(row):
            v = str(v)
            if v and v not in names:
                names.append(v)
    except Exception as e:
        print(f"build_spc_candidate_list (multy): {e}", flush=True)

    ctx = _row_to_ctx(row)
    if not ctx or not names:
        return names
    try:
        ranked = rank_spec_candidates(ctx, names)
        if ranked:
            return [name for name, _score in ranked]
    except Exception as e:
        print(f"build_spc_candidate_list (rank): {e}", flush=True)
    return names


def get_psi_specification(spc_id):
    """
    Метод подбирает доступные варианты спецификаций для списка номенклатур основываясь на таблицк nomeklatura_psi_rk
    :param spc_id: Список ИД номенклатур
    :return:
    """
    sql = "select * from `nomeklatura_rk_psi` order by `SpcName`"  # Получаем данные на связь спецификаций
    engine = create_engine(str(get_connection_string()))
    df_nom_psi = pd.read_sql_query(sql, engine)
    df_nom_psi_filtr = df_nom_psi[df_nom_psi['NomenklaturaID'].isin(spc_id)][['SpcID', 'SpcName']]
    return df_nom_psi_filtr


def get_nominal(df_data: pd.DataFrame, machine_type: str):
    """
    Метод получает номинальную частоту изделий из базы спецификаций если ближайшего номинала не найдено
    берется частота изделий с нагрузкой или без округленная до Гц
    :param machine_type:  Тип установки Transat/KH7700/W2200
    :param df_data:
    :return:
    """
    if not df_data.empty:
        engine = create_engine(str(get_connection_string()))
        sql = ("select distinct `частота`, `Cn(pF)`, `наименование`, `номенклатура` from `nomeklatura_rk` order by "
               "`наименование`")
        df = pd.read_sql_query(sql, engine)  # Запращиваем данные частот из таблицы nomeklatura_rk
        df_main = df.dropna().loc[df['частота'] != 0]  # Очистка
        # Переводим номинальную частоту в Гц
        df_main['частота'] = df_main['частота'] * 1000
        # Определяем целевую частоту для каждой строки result_df
        df_data = set_target_freq(df_data, machine_type)
        # Применяем функцию к каждой строке result_df
        df_data[['Номинал', 'Spec_list', 'Specs_ID', 'SpcID', 'SpcName']] = df_data.apply(find_closest_specs, axis=1,
                                                                                          df_nom=df_main)
        # Формируем итоговый датафрейм
        output_df = df_data[['Position_str', 'Номинал', 'Spec_list', 'Selected_Temp', 'Position', 'Specs_ID', 'SpcID',
                             'SpcName', 'CL', 'CL_Metod', 'CL_Value', 'SETUPNUM']]
    else:
        columns = [
            'Position_str', 'Номинал', 'Spec_list', 'Selected_Temp', 'Position',
            'Specs_ID', 'SpcID', 'SpcName', 'CL', 'CL_Metod', 'CL_Value', 'SETUPNUM'
        ]

        output_df = pd.DataFrame(columns=columns)
    print('get nominal')
    print(output_df)
    return output_df


def create_ranges(sorted_list):
    """
Вспомогальная функция для создание интревалов analyse_positions_tts100
    :param sorted_list:
    :return:
    """
    if not sorted_list:
        return []
    ranges = []
    start = end = sorted_list[0]
    for num in sorted_list[1:]:
        if num == end + 1:
            end = num
        else:
            ranges.append((start, end))
            start = end = num
    ranges.append((start, end))
    return ranges


# Форматирование интервалов в строки
def format_ranges(ranges, ring):
    """
    Вспомогальная функция для создание интревалов analyse_positions_tts100
    :param ranges:
    :param ring:
    :return:
    """
    formatted = []
    for start, end in ranges:
        if start == end:
            formatted.append(f"{ring}{start}")
        else:
            formatted.append(f"{ring}{start}-{ring}{end}")
    return formatted


def analyse_positions_tts100(df: pd.DataFrame):
    """
    Метод для анализа разбияния на интревалы установки TTS-100
    :param df:
    :return:
    """
    # Преобразование ringid в L и U
    df['ring'] = df['RINGID'].map({0: 'L', 1: 'U'})
    # Создание колонки с позицией
    df['position'] = df['ring'] + df['RINGPOS'].astype(str)
    # unique_df = df['position'].unique().tolist()
    # Группировка и создание интервалов
    grouped = df.groupby(['SETUPNUM', 'ring'])['RINGPOS'].apply(lambda x: sorted(x.unique())).reset_index()
    grouped['ranges'] = grouped['RINGPOS'].apply(create_ranges)
    grouped['formatted'] = grouped.apply(lambda row: format_ranges(row['ranges'], row['ring']), axis=1)
    # Создание колонки Position_str
    position_str_df = grouped.groupby('SETUPNUM')['formatted'].agg(
        lambda x: ', '.join([item for sublist in x for item in sublist])).reset_index()
    position_str_df.columns = ['SETUPNUM', 'Position_str']
    # Создание колонки Position с уникальными значениями
    df_sorted = df.sort_values(['SETUPNUM', 'ring', 'RINGPOS'])
    position_list_df = df_sorted.groupby('SETUPNUM')['position'].agg(
        lambda x: x.unique().tolist()
    ).reset_index()
    position_list_df.columns = ['SETUPNUM', 'Position']

    # Объединение результатов
    result_df = pd.merge(position_str_df, position_list_df, on='SETUPNUM')
    return result_df, df


def analyse_positions_W2200(df: pd.DataFrame):
    # Извлекаем компоненты идентификатора
    df[['circle', 'number']] = df['strCrystalID'].str.extract(r'([A-D])(\d+)', expand=True)
    df['number'] = df['number'].astype(int)

    result = []
    for (setup, circle), group in df.groupby(['nSetupFileIndex', 'circle']):
        numbers = group['number'].sort_values().unique()
        if not numbers.size:
            continue

        # Находим границы интервалов
        breaks = np.where(np.diff(numbers) > 1)[0] + 1
        intervals = np.split(numbers, breaks)

        for interval in intervals:
            start, end = interval[0], interval[-1]
            position_str = f"{circle}{start:03d}-{circle}{end:03d}"

            # Уникальные позиции в интервале
            mask = group['number'].between(start, end)
            positions = group.loc[mask, 'strCrystalID'].unique().tolist()

            result.append({
                'SETUPNUM': setup,
                'Position_str': position_str,
                'Position': positions
            })

    # Создаем и сортируем DataFrame
    result_df = pd.DataFrame(result)
    result_df = result_df.sort_values(by=['SETUPNUM', 'Position_str'])

    # Агрегируем результаты
    final_df = result_df.groupby('SETUPNUM', as_index=False).agg({
        'Position_str': ', '.join,
        'Position': lambda x: list(set().union(*x))  # Уникальные позиции для всего сетапа
    })

    return final_df, df


def set_target_freq(df_data: pd.DataFrame, machine_Type: str) -> pd.DataFrame:
    """
    Метод добавляет в текущие датафрейм колонку с целевой частотой Target_Hz
    в зависимости о типа установки
    :rtype: object
    """
    if machine_Type == 'Transat':
        df_data['Target_Hz'] = np.where(
            df_data['CL'] == 0,
            df_data['FS'] * 1e6,  # Переводим мегагерцы в герцы
            df_data['FL'] * 1e6  # Переводим мегагерцы в герцы
        )
    elif machine_Type == 'KH7700':
        df_data['Target_Hz'] = np.where(
            df_data['FL'] == 0,
            df_data['FS'],
            df_data['FL']
        )
    elif machine_Type == 'ТЧХ2200':
        df_data['Target_Hz'] = np.where(
            df_data['FL'] == 0,
            df_data['FS'],
            df_data['FL']
        )
    return df_data
