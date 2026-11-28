import re

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

from Options import get_connection_string, is_fast_spec_search_enabled, is_ai_spec_enabled
from datetime import datetime
from tabulate import tabulate

from Temperature_Measure.measure_data_class import MEASURE_DATA


def load_measure_file_data(file_inf: str):
    """
    Метод загружает данные файла по полученной строке из списка выбора и
    сохраняет их в переменную measure_file в виде словаря в классе MEASURE_DATA
    :param file_inf:
    """
    # Новый файл — сбрасываем кэш справочников (на случай обновления БД)
    clear_spec_cache()
    engine = get_engine()
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
    # SELECT * — полный набор колонок (как Make_Measure.get_file_data / new_data_compile).
    # FS/FL обязательны; R/C0/C1/Q подхватятся в get_avg_data_tts100_kh7700, если есть в таблице.
    if Archive == 0:
        sql = ("SELECT * FROM `kh7700` WHERE `File_ID` = '" + file_id + "' ORDER BY `ID`")
    else:
        sql = ("SELECT * FROM `kh7700_archive` WHERE `File_ID` = '" + file_id + "' ORDER BY `ID`")
    df = pd.read_sql_query(sql, engine)  # Запращиваем данные файла
    # Нормализация имён колонок (регистр) для единого пайплайна
    if not df.empty:
        colmap = {c: c for c in df.columns}
        lower = {c.lower(): c for c in df.columns}
        for want in ('XTALROW', 'Temp', 'FS', 'FL', 'R', 'C0', 'C1', 'Q', 'L', 'RR'):
            if want not in df.columns and want.lower() in lower:
                df.rename(columns={lower[want.lower()]: want}, inplace=True)
        if 'RR' in df.columns and 'R' not in df.columns:
            df.rename(columns={'RR': 'R'}, inplace=True)
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
    # SELECT * — полный набор (как Make_Measure.get_file_data); F0_MHZ/FL_MHZ обязательны,
    # R/C0/C1/Q подхватятся в get_avg_data_tts100_kh7700, если есть в таблице.
    if archive == 0:
        sql = ("SELECT * FROM `transat` WHERE `File_ID` = '" + file_id + "' ORDER BY `ID`")
    else:
        sql = ("SELECT * FROM `tts100_archive` WHERE `File_ID` = '" + file_id + "' ORDER BY `ID`")
    df = pd.read_sql_query(sql, engine)  # Запращиваем данные файла
    if not df.empty:
        # Единые имена колонок (регистр)
        lower = {c.lower(): c for c in df.columns}
        for want in ('SETUPNUM', 'RINGID', 'RINGPOS', 'SETPOINT', 'F0_MHZ', 'FL_MHZ',
                     'R', 'C0', 'C1', 'Q', 'L', 'RR'):
            if want not in df.columns and want.lower() in lower:
                df.rename(columns={lower[want.lower()]: want}, inplace=True)
        if 'RR' in df.columns and 'R' not in df.columns:
            df.rename(columns={'RR': 'R'}, inplace=True)
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
    # SELECT * — полный crystal data (параметры резонатора, если колонки есть)
    if archive == 0:
        sql = ("SELECT * FROM `crystal data` WHERE `File_ID` = '"
               + file_id + "' ORDER BY `strCrystalID`")
    else:
        sql = ("SELECT * FROM `crystal data_archive` WHERE `File_ID` = '"
               + file_id + "' ORDER BY `strCrystalID`")
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
    """
    Единый путь подготовки Configuration для KH7700 и Transat (TTS100):
      сырые данные установки
        → get_avg_data_tts100_kh7700  (средние на Selected_Temp, единые имена FS/FL/R/C0/C1/Q)
        → get_nominal                 (подбор спецификаций; AI-колонки сохраняются)
    Результат — одинаковый формат строк для всех установок.
    """
    result_df = get_avg_data_tts100_kh7700(df_main, df_intervals, machine_type)
    nom = get_nominal(result_df, machine_type)
    return nom


def _resolve_col(df: pd.DataFrame, *candidates) -> str | None:
    """Первое существующее имя колонки из candidates (с учётом регистра)."""
    lower = {c.lower(): c for c in df.columns}
    for name in candidates:
        if name in df.columns:
            return name
        if name.lower() in lower:
            return lower[name.lower()]
    return None


def get_avg_data_tts100_kh7700(df_main: pd.DataFrame, df_intervals: pd.DataFrame, machine_type: str,
                               file_id='') -> pd.DataFrame:
    """
    Единая подготовка средних параметров для KH7700 и Transat (TTS100).

    На выходе одинаковый набор колонок (как у Configuration после get_nominal):
      SETUPNUM, FS, FL, R?, C0?, C1?, Q?, L?,
      CL, CL_Metod, CL_Value, Position_str, Position, Selected_Temp

    Усреднение только на Selected_Temp (25°C или середина диапазона) —
    той же температуре, что используется для номинала.
    """
    global filtered
    machine_config = {
        'KH7700': {
            'position_col': 'XTALROW',
            'fs_candidates': ('FS', 'Fs', 'fs'),
            'fl_candidates': ('FL', 'Fl', 'fl'),
            'temp_col': 'Temp',
            'filter_cond': lambda df, fs: df[fs] != 0 if fs else df.index == df.index
        },
        'Transat': {
            'position_col': 'position',
            'fs_candidates': ('F0_MHZ', 'FS', 'Fs'),
            'fl_candidates': ('FL_MHZ', 'FL', 'Fl'),
            'temp_col': 'SETPOINT',
            'filter_cond': lambda df, fs, sn: (
                (df[fs] != 0) & (df['SETUPNUM'] == sn) if fs else (df['SETUPNUM'] == sn)
            ),
        }
    }

    results = []
    config = machine_config.get(machine_type, {})
    if not config:
        return pd.DataFrame()

    pos_col = _resolve_col(df_main, config['position_col']) or config['position_col']
    temp_col = _resolve_col(df_main, config['temp_col']) or config['temp_col']
    fs_col = _resolve_col(df_main, *config['fs_candidates'])
    fl_col = _resolve_col(df_main, *config['fl_candidates'])

    for _, row in df_intervals.iterrows():
        position_filter = df_main[pos_col].isin(row['Position'])

        if machine_type == 'KH7700':
            extra = config['filter_cond'](df_main, fs_col)
            filtered = df_main[position_filter & extra]
        elif machine_type == 'Transat':
            setupnum = row['SETUPNUM']
            extra = config['filter_cond'](df_main, fs_col, setupnum)
            filtered = df_main[position_filter & extra]
        else:
            filtered = df_main[position_filter]

        if filtered.empty:
            continue

        temps = filtered[temp_col].dropna().values
        target_temp = get_target_temp(np.asarray(temps, dtype=float))
        if target_temp is None:
            continue

        temp_filtered = filtered[filtered[temp_col] == target_temp]
        if temp_filtered.empty:
            temp_filtered = filtered[
                np.isclose(filtered[temp_col].astype(float), float(target_temp), atol=0.51)
            ]
        if temp_filtered.empty:
            continue

        # --- единый формат строки ---
        item = {
            'SETUPNUM': row.get('SETUPNUM', 0),
            'FS': float(temp_filtered[fs_col].mean()) if fs_col else 0.0,
            'FL': float(temp_filtered[fl_col].mean()) if fl_col else 0.0,
            'CL': get_cl_status(temp_filtered, machine_type)[0],
            'CL_Metod': get_cl_status(temp_filtered, machine_type)[1],
            'CL_Value': get_cl_status(temp_filtered, machine_type)[2],
            'Position_str': row['Position_str'],
            'Position': row['Position'],
            'Selected_Temp': target_temp,
        }

        # Доп. параметры резонатора в единых именах (если колонки есть в файле)
        param_aliases = {
            'R': ('R', 'RR', 'Rs', 'Resistance'),
            'C0': ('C0', 'C0_PF', 'C0_pF'),
            'C1': ('C1', 'Cq', 'C1_fF'),
            'Q': ('Q', 'Qfactor'),
            'L': ('L', 'Ls'),
        }
        for out_name, cands in param_aliases.items():
            src = _resolve_col(temp_filtered, *cands)
            if src is not None:
                try:
                    item[out_name] = float(temp_filtered[src].mean())
                except (TypeError, ValueError):
                    pass

        results.append(item)

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
            temps = filtered['Temp'].dropna().unique()
            target_temp = get_target_temp(np.asarray(temps, dtype=float))
            if target_temp is not None:
                temp_filtered = filtered[filtered['Temp'] == target_temp]
                if temp_filtered.empty:
                    temp_filtered = filtered[
                        np.isclose(filtered['Temp'].astype(float), float(target_temp), atol=0.51)
                    ]
                if temp_filtered.empty:
                    temp_filtered = filtered
            else:
                temp_filtered = filtered
            param_cols = [c for c in ('FS', 'FL', 'R', 'C0', 'C1', 'Q', 'L')
                          if c in temp_filtered.columns]
            avg_data = temp_filtered[param_cols].mean(numeric_only=True).to_dict()
            avg_data['Position_str'] = row['Position_str']
            avg_data['Temps'] = list(temps)
            avg_data['Selected_Temp'] = target_temp
            avg_data['Position'] = row['Position']
            clstatus, cl_metod, cl_value = get_cl_status(df_main=temp_filtered, machine_type='KH7700')
            avg_data['CL'] = clstatus
            avg_data['CL_Metod'] = cl_metod
            avg_data['CL_Value'] = cl_value
            avg_data['SETUPNUM'] = count
            count = count + 1
            results.append(avg_data)
            result_df = pd.DataFrame(results)

    elif machine_type == 'Transat':
        for _, row in df_intervals.iterrows():
            filtered = df_main[
                df_main['position'].isin(row['Position']) &
                (df_main['F0_MHZ'] != 0) &
                (df_main['SETUPNUM'] == row['SETUPNUM'])
                ]
            if filtered.empty:
                continue
            temps = filtered['SETPOINT'].dropna().unique()
            target_temp = get_target_temp(np.asarray(temps, dtype=float))
            if target_temp is not None:
                temp_filtered = filtered[filtered['SETPOINT'] == target_temp]
                if temp_filtered.empty:
                    temp_filtered = filtered[
                        np.isclose(filtered['SETPOINT'].astype(float), float(target_temp), atol=0.51)
                    ]
                if temp_filtered.empty:
                    temp_filtered = filtered
            else:
                temp_filtered = filtered
            param_cols = [c for c in ('F0_MHZ', 'FL_MHZ', 'R', 'C0', 'C1', 'Q', 'L', 'RR')
                          if c in temp_filtered.columns]
            avg_data = temp_filtered[param_cols].mean(numeric_only=True).to_dict()
            if 'F0_MHZ' in avg_data:
                avg_data['FS'] = avg_data.pop('F0_MHZ')
            if 'FL_MHZ' in avg_data:
                avg_data['FL'] = avg_data.pop('FL_MHZ')
            if 'RR' in avg_data and 'R' not in avg_data:
                avg_data['R'] = avg_data.pop('RR')
            avg_data['Position_str'] = row['Position_str']
            avg_data['Temps'] = list(temps)
            avg_data['Selected_Temp'] = target_temp
            avg_data['Position'] = row['Position']
            clstatus, cl_metod, cl_value = get_cl_status(df_main=temp_filtered, machine_type='Transat')
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
        # Группировка и агрегация только по SETUPNUM (на target_temp уже отфильтровано)
        agg_spec = {
            'fFrequencyPPM': 'mean',  # FS
            'fValue1': 'mean',        # FL
            'strLoadType': 'first',
            'fSetTemperature': lambda x: list(x.unique()),
            'fReferenceFrequency': 'first',
        }
        # Параметры резонатора — если есть в crystal data / merge
        param_src = {
            'R': ('R', 'RR', 'fResistance', 'Resistance', 'Rs'),
            'C0': ('C0', 'fC0', 'C0_pF'),
            'C1': ('C1', 'Cq', 'fC1'),
            'Q': ('Q', 'fQ', 'Qfactor'),
            'L': ('L', 'fL', 'Ls'),
        }
        resolved = {}
        lower_cols = {c.lower(): c for c in filtered.columns}
        for out_name, cands in param_src.items():
            for cand in cands:
                if cand in filtered.columns:
                    resolved[out_name] = cand
                    break
                if cand.lower() in lower_cols:
                    resolved[out_name] = lower_cols[cand.lower()]
                    break
            if out_name in resolved:
                # numeric mean
                filtered[resolved[out_name]] = pd.to_numeric(
                    filtered[resolved[out_name]], errors='coerce'
                )
                agg_spec[resolved[out_name]] = 'mean'

        grouped = filtered.groupby('SETUPNUM').agg(agg_spec).reset_index()
        output_df = pd.merge(
            grouped,
            df_intervals[['SETUPNUM', 'Position', 'Position_str']],
            on='SETUPNUM',
            how='left'
        )
        rename_cols = {
            'fFrequencyPPM': 'FS',
            'fValue1': 'FL',
            'fSetTemperature': 'Temps',
            'fReferenceFrequency': 'Target_Hz',
        }
        for out_name, src in resolved.items():
            if src in output_df.columns:
                rename_cols[src] = out_name
        output_df.rename(columns=rename_cols, inplace=True)

        output_df['CL_Metod'] = output_df.apply(determine_cl_metod, axis=1)
        output_df['CL_Value'] = 0
        output_df['CL'] = output_df['CL_Metod'].ne('SERIES').astype(int)
        output_df['Selected_Temp'] = target_temp

        keep = [
            'SETUPNUM', 'FS', 'FL', 'CL_Metod', 'CL_Value', 'CL',
            'Position', 'Position_str', 'Temps', 'Target_Hz', 'Selected_Temp',
        ]
        for c in ('R', 'C0', 'C1', 'Q', 'L'):
            if c in output_df.columns:
                keep.append(c)
        result_df = output_df[keep]

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

            # Температуры партии → целевая (25°C или середина диапазона)
            temps = filtered['Temp'].dropna().unique()
            target_temp = get_target_temp(np.asarray(temps, dtype=float))
            if target_temp is None:
                continue

            # Параметры для AI/номинала — только на той же температуре, что и номинал
            temp_filtered = filtered[filtered['Temp'] == target_temp]
            if temp_filtered.empty:
                # допуск на float-сравнение
                temp_filtered = filtered[
                    np.isclose(filtered['Temp'].astype(float), float(target_temp), atol=0.51)
                ]
            if temp_filtered.empty:
                continue

            param_cols = [c for c in ('Fs', 'Fl', 'R', 'C0', 'C1', 'Q', 'L')
                          if c in temp_filtered.columns]
            avg_data = temp_filtered[param_cols].mean(numeric_only=True).to_dict()
            avg_data['Position_str'] = row['Position_str']
            avg_data['Position'] = row['Position']  # список позиций без ведущих нулей
            avg_data['SETUPNUM'] = row['SETUPNUM']
            avg_data['Temps'] = list(temps)
            avg_data['Selected_Temp'] = target_temp
            avg_data['Mode'] = temp_filtered['Mode'].iloc[0] if 'Mode' in temp_filtered.columns else 0
            avg_data['PL'] = temp_filtered['PL'].iloc[0] if 'PL' in temp_filtered.columns else 0
            ref_cl = temp_filtered['ReferenceCL'].iloc[0] if 'ReferenceCL' in temp_filtered.columns else 0
            avg_data['ReferenceCL'] = ref_cl
            clstatus, cl_metod, cl_value = get_cl_status(temp_filtered, machine_type, avg_data)
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
        item = {
            'Position_str': row['Position_str'],
            'FS': row[fs],
            'FL': row[fl],
            'Selected_Temp': target_temp,
            'Position': row['Position'],
            'CL': row['CL'],
            'CL_Metod': row['CL_Metod'],
            'CL_Value': row['CL_Value'],
            'SETUPNUM': row['SETUPNUM'],
        }
        # Параметры резонатора (если уже усреднены в get_avg_data) — для AI-подбора
        for col in ('R', 'C0', 'C1', 'Q', 'L'):
            if col in row.index and pd.notna(row[col]):
                item[col] = row[col]
        final_data.append(item)
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
        item = {
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
        }
        for col in ('R', 'C0', 'C1', 'Q', 'L'):
            if col in row.index and pd.notna(row[col]):
                item[col] = row[col]
        final_data.append(item)
    final_df = pd.DataFrame(final_data)
    nom = get_nominal(final_df, machine_type)  # Добавляем номинальные частоты
    return nom


# =============================================================================
# Автоподбор спецификаций: порог ppm, score, подробный лог отбора/отсева
# =============================================================================

# Порог совпадения номинала по частоте (ppm). Можно переопределить через
# set_ppm_threshold() или переменную окружения SPEC_PPM_THRESHOLD.
PPM_THRESHOLD_DEFAULT = 100.0
_ppm_threshold = PPM_THRESHOLD_DEFAULT

# Веса score (чем больше — тем выше приоритет в combo)
SCORE_BASE = 1000.0
SCORE_CAPACITY_MATCH = 30.0
SCORE_TEMP_EXACT = 50.0
SCORE_TEMP_SUBSET = 20.0


# -----------------------------------------------------------------------------
# Кэш справочников + общий engine (ускорение автоподбора)
# -----------------------------------------------------------------------------
_engine = None

# Сколько строк отсева печатать на одну причину (полный dump — только DEBUG)
SPEC_LOG_REJECT_SAMPLES = 5


def get_engine():
    """Singleton SQLAlchemy engine на процесс."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            str(get_connection_string()),
            pool_pre_ping=True,
            pool_recycle=3600,
        )
    return _engine


class SpecRefCache:
    """
    Кэш справочников на сессию файла.
    Загрузка ленивая, один SQL на таблицу; invalidate() при смене файла.
    """
    __slots__ = (
        'nomeklatura_rk', 'nomeklatura_rk_psi', 'spc_special',
        'spec_profiles',  # name -> (profile_name, temps_list, temps_str)
        '_loaded',
    )

    def __init__(self):
        self.nomeklatura_rk = None
        self.nomeklatura_rk_psi = None
        self.spc_special = None
        self.spec_profiles = {}
        self._loaded = set()

    def clear(self):
        self.nomeklatura_rk = None
        self.nomeklatura_rk_psi = None
        self.spc_special = None
        self.spec_profiles = {}
        self._loaded.clear()
        print('[SpecRefCache] очищен')

    def ensure_nomeklatura_rk(self) -> pd.DataFrame:
        if 'nomeklatura_rk' in self._loaded and self.nomeklatura_rk is not None:
            return self.nomeklatura_rk
        engine = get_engine()
        sql = (
            "SELECT DISTINCT `частота`, `Cn(pF)`, `наименование`, `номенклатура` "
            "FROM `nomeklatura_rk` ORDER BY `наименование`"
        )
        df = pd.read_sql_query(sql, engine)
        df = df.dropna().loc[df['частота'] != 0].copy()
        df['частота'] = df['частота'] * 1000  # кГц/МГц в таблице → Гц
        self.nomeklatura_rk = df
        self._loaded.add('nomeklatura_rk')
        print(f'[SpecRefCache] nomeklatura_rk: {len(df)} строк')
        return df

    def ensure_nomeklatura_rk_psi(self) -> pd.DataFrame:
        if 'nomeklatura_rk_psi' in self._loaded and self.nomeklatura_rk_psi is not None:
            return self.nomeklatura_rk_psi
        engine = get_engine()
        sql = (
            "SELECT `NomenklaturaID`, `SpcID`, `SpcName` "
            "FROM `nomeklatura_rk_psi` ORDER BY `SpcName`"
        )
        try:
            df = pd.read_sql_query(sql, engine)
        except Exception:
            # fallback если имена колонок отличаются
            df = pd.read_sql_query("SELECT * FROM `nomeklatura_rk_psi` ORDER BY `SpcName`", engine)
        self.nomeklatura_rk_psi = df
        self._loaded.add('nomeklatura_rk_psi')
        print(f'[SpecRefCache] nomeklatura_rk_psi: {len(df)} строк')
        return df

    def ensure_spc_special(self) -> pd.DataFrame:
        if 'spc_special' in self._loaded and self.spc_special is not None:
            return self.spc_special
        engine = get_engine()
        df = pd.read_sql_query("SELECT * FROM `spc_special`", engine)
        self.spc_special = df
        self._loaded.add('spc_special')
        print(f'[SpecRefCache] spc_special: {len(df)} строк')
        return df

    def ensure_spec_profiles(self, names) -> dict:
        """
        Подгружает temperatureprofile для списка имён спецификаций.
        Уже известные имена не перечитываются.
        """
        names = [n for n in names if n]
        missing = [n for n in names if n not in self.spec_profiles]
        if not missing:
            return self.spec_profiles

        engine = get_engine()
        placeholders = ','.join(['%s'] * len(missing))
        sql = f"""
            SELECT s.`Name`, s.`Profile`, tp.`Temperatures`
            FROM `specification` s
            LEFT JOIN `temperatureprofile` tp ON s.`Profile` = tp.`Name`
            WHERE s.`Name` IN ({placeholders})
        """
        try:
            df = pd.read_sql(sql, engine, params=tuple(missing))
        except Exception as e:
            print(f'[SpecRefCache] spec_profiles error: {e}')
            for n in missing:
                self.spec_profiles[n] = (None, [], None)
            return self.spec_profiles

        found = set()
        for _, r in df.iterrows():
            tstr = r['Temperatures']
            try:
                pt = list(map(float, str(tstr).split())) if pd.notna(tstr) and tstr else []
            except (ValueError, AttributeError):
                pt = []
            self.spec_profiles[r['Name']] = (r.get('Profile'), pt, tstr)
            found.add(r['Name'])
        for n in missing:
            if n not in found:
                self.spec_profiles[n] = (None, [], None)
        print(f'[SpecRefCache] spec_profiles: +{len(missing)} имён '
              f'(всего {len(self.spec_profiles)})')
        return self.spec_profiles


_spec_cache = SpecRefCache()


def get_spec_cache() -> SpecRefCache:
    return _spec_cache


def clear_spec_cache() -> None:
    """Сбросить кэш (вызывать при смене/перезагрузке файла)."""
    _spec_cache.clear()


def preload_spec_refs() -> None:
    """Прогрев всех справочников одним проходом (опционально)."""
    c = _spec_cache
    c.ensure_nomeklatura_rk()
    c.ensure_nomeklatura_rk_psi()
    c.ensure_spc_special()



def get_ppm_threshold() -> float:
    """Текущий порог совпадения номинала, ppm."""
    import os
    env = os.environ.get('SPEC_PPM_THRESHOLD')
    if env is not None and str(env).strip() != '':
        try:
            return float(env)
        except ValueError:
            pass
    return float(_ppm_threshold)


def set_ppm_threshold(value: float) -> None:
    """Задать порог ppm на время сессии (для тестов и настройки)."""
    global _ppm_threshold
    _ppm_threshold = float(value)


def compute_freq_diff_ppm(freq_hz: float, target_hz: float) -> float:
    """Абсолютная разница частот в ppm."""
    if target_hz is None or target_hz == 0 or (isinstance(target_hz, float) and np.isnan(target_hz)):
        return float('inf')
    return float(np.abs((freq_hz - target_hz) / target_hz * 1e6))


def capacity_matches(cl_metod, fl_value, cn_pf) -> tuple:
    """
    Проверка соответствия нагрузочной ёмкости номенклатуры режиму измерения.
    Возвращает (ok: bool, reason: str|None).
    reason заполнен только при отсеве.
    """
    if cl_metod != 'PHYSICAL':
        return True, None
    try:
        fl = float(fl_value) if fl_value is not None and not (isinstance(fl_value, float) and np.isnan(fl_value)) else 0.0
    except (TypeError, ValueError):
        fl = 0.0
    try:
        cn = float(cn_pf) if cn_pf is not None and not (isinstance(cn_pf, float) and np.isnan(cn_pf)) else 0.0
    except (TypeError, ValueError):
        cn = 0.0

    if fl > 0:
        if cn > 0:
            return True, None
        return False, f'PHYSICAL + FL>0, но Cn(pF)={cn} (нужен Cn>0)'
    # FL == 0 → серия без нагрузки
    if cn == 0:
        return True, None
    return False, f'PHYSICAL + FL==0, но Cn(pF)={cn} (нужен Cn==0)'


def score_nomenclature_candidate(ppm: float, capacity_ok: bool = True) -> float:
    """
    Score номенклатуры на этапе подбора по частоте.
    База: SCORE_BASE - ppm; бонус за совпадение ёмкости.
    """
    score = SCORE_BASE - float(ppm)
    if capacity_ok:
        score += SCORE_CAPACITY_MATCH
    return score


def score_with_temp_match(base_score: float, temp_match: str) -> float:
    """Добавляет бонус за качество совпадения температурного профиля."""
    if temp_match == 'exact':
        return base_score + SCORE_TEMP_EXACT
    if temp_match == 'subset':
        return base_score + SCORE_TEMP_SUBSET
    return base_score


def classify_temp_match(file_temps, profile_temps) -> str:
    """
    'exact' | 'subset' | 'none'
    file_temps / profile_temps — iterable чисел.
    """
    try:
        ft = set(float(x) for x in file_temps)
        pt = set(float(x) for x in profile_temps)
    except (TypeError, ValueError):
        return 'none'
    if not pt:
        return 'none'
    if ft == pt:
        return 'exact'
    if pt.issubset(ft):
        return 'subset'
    return 'none'


def filter_and_rank_nomenclature(df_nom: pd.DataFrame, target_hz: float,
                                 cl_metod, fl_value,
                                 ppm_threshold: float = None) -> tuple:
    """
    Чистая логика этапа 1: отбор номенклатур по ppm и ёмкости + ранжирование.

    Возвращает (accepted, rejected), где каждый элемент — dict:
      accepted: наименование, номенклатура, частота, Cn, ppm, score, capacity_ok
      rejected: те же поля + reason
    """
    if ppm_threshold is None:
        ppm_threshold = get_ppm_threshold()

    work = df_nom.copy()
    if 'F_diff_ppm' not in work.columns:
        work['F_diff_ppm'] = work['частота'].apply(
            lambda f: compute_freq_diff_ppm(f, target_hz)
        )

    accepted = []
    rejected = []

    for _, r in work.iterrows():
        ppm = float(r['F_diff_ppm'])
        name = r.get('наименование', '')
        nom_id = r.get('номенклатура', '')
        freq = r.get('частота')
        cn = r.get('Cn(pF)', 0)

        entry = {
            'наименование': name,
            'номенклатура': nom_id,
            'частота': freq,
            'Cn(pF)': cn,
            'ppm': ppm,
        }

        if ppm > ppm_threshold:
            entry['reason'] = (
                f'Δ{ppm:.3f} ppm > порог {ppm_threshold:g} ppm'
            )
            entry['score'] = None
            rejected.append(entry)
            continue

        ok, reason = capacity_matches(cl_metod, fl_value, cn)
        if not ok:
            entry['reason'] = reason
            entry['score'] = None
            rejected.append(entry)
            continue

        entry['capacity_ok'] = True
        entry['score'] = score_nomenclature_candidate(ppm, capacity_ok=True)
        accepted.append(entry)

    accepted.sort(key=lambda x: (-x['score'], x['ppm'], str(x['наименование'])))
    return accepted, rejected


def _log_block(title: str) -> None:
    line = '=' * 72
    print(line)
    print(f'  {title}')
    print(line)


def log_nomenclature_selection(target_hz, cl_metod, fl_value, ppm_threshold,
                               accepted, rejected) -> None:
    """Лог этапа подбора по номиналу (отсев — сжатый: счётчики + N примеров)."""
    import os
    debug = os.environ.get('DEBUG_SPEC_SELECTION', '').strip() in ('1', 'true', 'yes')
    samples = len(rejected) if debug else SPEC_LOG_REJECT_SAMPLES

    _log_block('АВТОПОДБОР: этап 1 — номинал (частота + ёмкость)')
    print(f'  Target_Hz      : {target_hz}')
    print(f'  CL_Metod       : {cl_metod}')
    print(f'  FL             : {fl_value}')
    print(f'  Порог ppm      : {ppm_threshold:g}')
    print(f'  Кандидатов OK  : {len(accepted)}')
    print(f'  Отсеяно        : {len(rejected)}')
    print('-' * 72)
    if accepted:
        print('  ОТОБРАНЫ (по убыванию score):')
        for i, a in enumerate(accepted, 1):
            print(
                f'    [{i:02d}] score={a["score"]:8.2f}  Δ={a["ppm"]:8.3f} ppm  '
                f'f={a["частота"]}  Cn={a["Cn(pF)"]}  '
                f'{a["наименование"]}  (id={a["номенклатура"]})'
            )
    else:
        print('  ОТОБРАНЫ: (пусто)')
    print('-' * 72)
    if rejected:
        print('  ОТСЕЯНЫ (сжатый лог, DEBUG_SPEC_SELECTION=1 — полный):')
        by_reason = {}
        for r in rejected:
            by_reason.setdefault(r.get('reason', '?'), []).append(r)
        for reason, items in by_reason.items():
            print(f'    ▸ {reason}  ({len(items)} шт.)')
            for r in items[:samples]:
                print(
                    f'        Δ={r["ppm"]:8.3f} ppm  f={r["частота"]}  '
                    f'Cn={r["Cn(pF)"]}  {r["наименование"]}  (id={r["номенклатура"]})'
                )
            if len(items) > samples:
                print(f'        ... ещё {len(items) - samples}')
    else:
        print('  ОТСЕЯНЫ: (нет)')
    print('=' * 72)


def log_temp_filter(file_temps, kept, dropped) -> None:
    """Лог этапа фильтрации по температурному профилю."""
    _log_block('АВТОПОДБОР: этап 2 — температурный профиль')
    print(f'  Температуры файла: {sorted(file_temps) if file_temps is not None else "—"}')
    print(f'  Прошли фильтр    : {len(kept)}')
    print(f'  Отсеяно          : {len(dropped)}')
    print('-' * 72)
    if kept:
        print('  ОТОБРАНЫ:')
        for name, match_kind, profile in kept:
            print(f'    ✓ [{match_kind:6}] {name}  profile={profile}')
    else:
        print('  ОТОБРАНЫ: (пусто)')
    print('-' * 72)
    if dropped:
        print('  ОТСЕЯНЫ:')
        for name, reason, profile in dropped:
            print(f'    ✗ {name}  — {reason}  profile={profile}')
    else:
        print('  ОТСЕЯНЫ: (нет)')
    print('=' * 72)


def log_final_spc_list(spc_list, default_value, multi_added=None) -> None:
    """Лог итогового списка для combo."""
    _log_block('АВТОПОДБОР: итог — список для выбора (combo)')
    if multi_added:
        print(f'  Multi-spec добавлены: {multi_added}')
    if not spc_list or spc_list == ['Нет']:
        print('  Список пуст → «Нет»')
    else:
        for i, name in enumerate(spc_list, 1):
            mark = ' ← default' if name == default_value else ''
            print(f'    [{i:02d}] {name}{mark}')
    print('=' * 72)


# Функция для поиска ближайших спецификаций
def find_closest_specs_fast(row, df_nom: pd.DataFrame):
    """
    Находит номинал и связанные спецификации ПСИ с ранжированием по score.

    Этап 1 (этот метод):
      - все номенклатуры с Δppm ≤ порога (get_ppm_threshold), не только min;
      - фильтр по ёмкости для PHYSICAL;
      - сортировка по score = (1000 - ppm) + бонус за ёмкость;
      - подробный лог принятых и отсеянных.

    Возвращает Series: [Номинал, Spec_list, Specs_ID, SpcID, SpcName]
    """
    target = row['Target_Hz']
    cl_metod = row['CL_Metod'] if 'CL_Metod' in row.index else None
    fl_value = row['FL'] if 'FL' in row.index else 0
    ppm_threshold = get_ppm_threshold()

    work = df_nom.copy()
    work['F_diff_ppm'] = work['частота'].apply(
        lambda f: compute_freq_diff_ppm(f, target)
    )

    accepted, rejected = filter_and_rank_nomenclature(
        work, target, cl_metod, fl_value, ppm_threshold=ppm_threshold
    )
    log_nomenclature_selection(
        target, cl_metod, fl_value, ppm_threshold, accepted, rejected
    )

    specs = []
    specs_id = []
    spc_id_list = []
    spc_name_list = []

    if not accepted:
        nominal_freq = round(float(target)) if target is not None else 0
        print(f'  → Номинал не найден в пределах {ppm_threshold:g} ppm, '
              f'используем Target_Hz={nominal_freq}')
        return pd.Series([nominal_freq, specs, specs_id, spc_id_list, spc_name_list])

    # Номинал — частота лучшего (первого) кандидата
    nominal_freq = round(float(accepted[0]['частота']))
    specs = [a['наименование'] for a in accepted]
    specs_id = [a['номенклатура'] for a in accepted]

    df_spc_id = get_psi_specification_fast(specs_id)
    if not df_spc_id.empty:
        # Порядок номенклатур (лучший score раньше) → связанные SpcName без дублей.
        seen = set()
        ordered_names = []
        ordered_ids = []
        if 'NomenklaturaID' in df_spc_id.columns:
            for nid in specs_id:
                sub = df_spc_id[df_spc_id['NomenklaturaID'] == nid]
                for _, sr in sub.iterrows():
                    nm = sr['SpcName']
                    if nm not in seen:
                        seen.add(nm)
                        ordered_names.append(nm)
                        ordered_ids.append(sr['SpcID'])
        else:
            for _, sr in df_spc_id.iterrows():
                nm = sr['SpcName']
                if nm not in seen:
                    seen.add(nm)
                    ordered_names.append(nm)
                    ordered_ids.append(sr['SpcID'])
        spc_name_list = ordered_names
        spc_id_list = ordered_ids

    print(f'  → Номинал={nominal_freq} Гц, номенклатур={len(specs)}, '
          f'спецификаций ПСИ={len(spc_name_list)}: {spc_name_list}')

    return pd.Series([nominal_freq, specs, specs_id, spc_id_list, spc_name_list])


# Получает список мульти спецификаций для данного температурного интервала
def get_multy_spec_fast(row):
    """Multi-spec из кэша spc_special (без повторного SQL)."""
    result = []
    temp_list = row['Temp_List']
    spc_df = get_spec_cache().ensure_spc_special()
    try:
        str_list1 = [str(int(float(x))) for x in temp_list]
    except (TypeError, ValueError):
        str_list1 = [str(x) for x in temp_list]
    key = tuple(sorted(str_list1))
    for _, spc_ in spc_df.iterrows():
        db_temps = str(spc_['Temps']).split()
        if tuple(sorted(db_temps)) == key:
            result.append(spc_['Multy_Spc_Name'])
    if result:
        print(f'  [multi-spec] для temp={str_list1} найдены: {result}')
    return result


# Проверяет соответствие температурного интервала спецификации и измерительного файла
def test_temp_interval_points_fast(data, spc_list):
    """
    Фильтрует имена спецификаций по температурному профилю.
    Профили читаются из SpecRefCache (SQL только для ещё не кэшированных имён).
    Порядок входного списка сохраняется.
    """
    if not spc_list:
        return []

    file_temps_raw = data['Temp_List'] if hasattr(data, '__getitem__') else []
    try:
        if isinstance(file_temps_raw, (list, tuple, set, np.ndarray)):
            file_temps = [float(x) for x in file_temps_raw]
        else:
            file_temps = list(file_temps_raw)
    except Exception:
        file_temps = list(file_temps_raw) if file_temps_raw is not None else []

    profiles = get_spec_cache().ensure_spec_profiles(spc_list)

    kept = []
    dropped = []
    kept_names = []

    for name in spc_list:
        if name not in profiles:
            dropped.append((name, 'нет в БД specification/profile', None))
            continue
        profile_name, pt, tstr = profiles[name]
        # пустая запись = имя запрошено, но в specification не найдено
        if profile_name is None and not pt and tstr is None:
            dropped.append((name, 'нет в БД specification/profile', None))
            continue
        match = classify_temp_match(file_temps, pt)
        if match in ('exact', 'subset'):
            kept.append((name, match, tstr))
            kept_names.append(name)
        else:
            dropped.append((
                name,
                f'профиль не совпадает (file={sorted(file_temps)}, profile={pt})',
                tstr
            ))

    log_temp_filter(file_temps, kept, dropped)
    return kept_names



def _ai_get_psidata_map() -> dict:
    """Field → Parameter из psidata_map_table (кэш на сессию)."""
    cache = getattr(_ai_get_psidata_map, '_cache', None)
    if cache is not None:
        return cache
    mapping = {}
    try:
        eng = create_engine(str(get_connection_string()), pool_pre_ping=True)
        df = pd.read_sql('SELECT `Field`, `Parameter` FROM `psidata_map_table`', eng)
        mapping = dict(zip(df['Field'].astype(str), df['Parameter'].astype(str)))
        print(f'[SpcAI] psidata_map_table: {len(mapping)} записей', flush=True)
    except Exception as e:
        print(f'[SpcAI] psidata_map_table недоступна: {e}', flush=True)
    _ai_get_psidata_map._cache = mapping
    return mapping


def _ai_to_float(v):
    try:
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _ai_sample_from_row(row) -> dict:
    """
    Собрать признаки для AI-модели из строки слота.

    Источник: усреднённые на Selected_Temp значения из get_avg_data
    (FS/FL/R/C0/C1/Q) + Nominal/Target_Hz.

    Единицы приводятся к виду psidata (как convert_units_ в Make_Measure):
      C0: Ф → пФ (*1e12), если значение похоже на СИ
      C1→Cq: Ф → фФ (*1e15)
      Q:  /1000, если Q очень большое
      F:  из FS; если >1e5 — Гц→МГц (/1e6), иначе как есть
    Имена колонок можно уточнить через psidata_map_table.
    """
    sample = {}
    try:
        if hasattr(row, 'get'):
            def getter(k, default=None):
                try:
                    return row.get(k, default)
                except Exception:
                    return default
            def has(k):
                try:
                    return k in row
                except Exception:
                    return False
        else:
            def getter(k, default=None):
                try:
                    return row[k] if k in row.index else default
                except Exception:
                    return default
            def has(k):
                try:
                    return k in row.index
                except Exception:
                    return False

        # --- Nominal ---
        for src in ('Номинал', 'Nominal', 'Target_Hz'):
            if has(src) or getter(src) is not None:
                v = _ai_to_float(getter(src))
                if v is not None:
                    # Номинал в модели — строковый код около МГц (напр. 58.941176)
                    if v > 1000:  # похоже на Гц
                        sample['Nominal'] = round(v / 1e6, 6)
                    else:
                        sample['Nominal'] = v
                    break

        # --- F из FS / FL / F ---
        f_raw = None
        for src in ('F', 'FS', 'Fs', 'FL', 'Fl'):
            if has(src):
                f_raw = _ai_to_float(getter(src))
                if f_raw is not None:
                    break
        if f_raw is not None:
            # CL_Metod SERIES → FS, иначе FL предпочтительнее уже учтено Target_Hz
            sample['F'] = f_raw / 1e6 if f_raw > 1e5 else f_raw

        # --- R ---
        for src in ('R', 'RR', 'Rs'):
            if has(src):
                rv = _ai_to_float(getter(src))
                if rv is not None:
                    sample['R'] = rv
                    break

        # --- C0 ---
        if has('C0'):
            c0 = _ai_to_float(getter('C0'))
            if c0 is not None:
                # СИ-фарады обычно < 1e-6; в psidata — пФ порядка 0.1..10
                sample['C0'] = c0 * 1e12 if abs(c0) < 1e-6 else c0

        # --- Cq из C1 / Cq ---
        cq = None
        for src in ('Cq', 'C1'):
            if has(src):
                cq = _ai_to_float(getter(src))
                if cq is not None:
                    break
        if cq is not None:
            # СИ → фФ (*1e15); иначе уже в рабочих единицах
            sample['Cq'] = cq * 1e15 if abs(cq) < 1e-9 else cq

        # --- Q ---
        if has('Q'):
            qv = _ai_to_float(getter('Q'))
            if qv is not None:
                sample['Q'] = qv * 1e-3 if qv > 1000 else qv

        # Уточнение имён через psidata_map (Field→Parameter), если в row
        # есть «сырые» Field-имена, которых нет в стандартном наборе.
        try:
            pmap = _ai_get_psidata_map()
            inv = {}
            for field, param in pmap.items():
                inv.setdefault(str(param), []).append(str(field))
            for param in ('F', 'R', 'C0', 'Cq', 'Q', 'C1'):
                if param in sample:
                    continue
                for field in inv.get(param, []):
                    if has(field):
                        vv = _ai_to_float(getter(field))
                        if vv is not None:
                            key = 'Cq' if param in ('Cq', 'C1') else param
                            sample[key] = vv
                            break
        except Exception:
            pass

        if sample:
            print(f'[SpcAI] sample features: {sample}', flush=True)
    except Exception as e:
        print(f'[SpcAI] _ai_sample_from_row: {e}', flush=True)
    return sample


def _apply_ai_to_spc_list(result: list, row) -> list:
    """Если AI включён — переупорядочить список кандидатов."""
    if not is_ai_spec_enabled():
        return result
    try:
        from Temperature_Measure.Models.predict_spc_model import (
            rank_spc_list_with_ai, predict_spc, get_model,
        )
        if get_model() is None:
            return result
        sample = _ai_sample_from_row(row)
        # Если признаков мало — всё равно попробуем (Nominal)
        if not sample:
            return result
        ranked = rank_spc_list_with_ai(result, sample=sample, top_k=5)
        # Режим «только AI»: если fast выключен и классика дала мало —
        # дополнительно подмешаем top предсказания, даже если их не было в кандидатах
        if not is_fast_spec_search_enabled():
            best, top = predict_spc(sample, top_k=3)
            extra = []
            for name, _p in top:
                if name not in ranked and name not in extra:
                    extra.append(name)
            if best and best not in ranked and best not in extra:
                extra.insert(0, best)
            if extra:
                ranked = extra + ranked
                print(f'[SpcAI] добавлены AI-кандидаты вне фильтра: {extra}', flush=True)
        return ranked if ranked else result
    except Exception as e:
        print(f'[SpcAI] _apply_ai_to_spc_list: {e}', flush=True)
        return result


def build_ranked_spc_combo_list(row) -> list:
    """
    Собирает итоговый упорядоченный список спецификаций для combo слота:
      1) SpcName из этапа номинала (уже по score)
      2) фильтр по температуре (порядок сохраняется)
      3) multi-spec в конец
    Пишет итоговый лог. Первый элемент — default.
    """
    spc_list = row.at['SpcName'] if hasattr(row, 'at') else row.get('SpcName', [])
    if spc_list is None:
        spc_list = []
    if isinstance(spc_list, np.ndarray):
        spc_list = spc_list.tolist()
    if not isinstance(spc_list, list):
        spc_list = list(spc_list) if spc_list is not None else []

    filtered = test_temp_interval_points_fast(row, spc_list)
    multi = get_multy_spec_fast(row)
    multi_new = [m for m in multi if m not in filtered]
    result = list(filtered) + multi_new
    if not result:
        result = ['Нет']
    result = _apply_ai_to_spc_list(result, row)
    default = result[0]
    log_final_spc_list(result, default, multi_added=multi_new or None)
    return result


def get_psi_specification_fast(spc_id):
    """
    Спецификации ПСИ для ID номенклатур — фильтр по кэшу (без повторного SQL).
    """
    if not spc_id:
        return pd.DataFrame(columns=['SpcID', 'SpcName', 'NomenklaturaID'])
    df = get_spec_cache().ensure_nomeklatura_rk_psi()
    cols = [c for c in ('SpcID', 'SpcName', 'NomenklaturaID') if c in df.columns]
    id_set = set(spc_id)
    return df[df['NomenklaturaID'].isin(id_set)][cols].copy()


def get_nominal_fast(df_data: pd.DataFrame, machine_type: str):
    """
    Номинал и списки спецификаций по слотам (быстрый режим).
    Справочник nomeklatura_rk берётся из SpecRefCache (1 SQL на сессию).
    """
    if not df_data.empty:
        df_main = get_spec_cache().ensure_nomeklatura_rk()
        # прогрев psi заранее — find_closest_specs не будет ходить в БД по слотам
        get_spec_cache().ensure_nomeklatura_rk_psi()

        df_data = set_target_freq(df_data, machine_type)
        df_data[['Номинал', 'Spec_list', 'Specs_ID', 'SpcID', 'SpcName']] = df_data.apply(
            find_closest_specs_fast, axis=1, df_nom=df_main
        )
        base_cols = [
            'Position_str', 'Номинал', 'Spec_list', 'Selected_Temp', 'Position',
            'Specs_ID', 'SpcID', 'SpcName', 'CL', 'CL_Metod', 'CL_Value', 'SETUPNUM'
        ]
        # Сохраняем измеренные параметры для AI (на Selected_Temp)
        extra = [c for c in (
            'FS', 'FL', 'Target_Hz', 'R', 'C0', 'C1', 'Q', 'L', 'Fs', 'Fl'
        ) if c in df_data.columns]
        output_df = df_data[base_cols + extra].copy()
    else:
        columns = [
            'Position_str', 'Номинал', 'Spec_list', 'Selected_Temp', 'Position',
            'Specs_ID', 'SpcID', 'SpcName', 'CL', 'CL_Metod', 'CL_Value', 'SETUPNUM'
        ]
        output_df = pd.DataFrame(columns=columns)
    print('get nominal')
    print(output_df)
    return output_df


# =============================================================================
# Классический (медленный) режим + маршрутизация по настройке
# =============================================================================

def find_closest_specs_legacy(row, df_nom: pd.DataFrame):
    """
    Классический подбор: только min ppm, порог 100, без ranking по score.
    """
    target = row['Target_Hz']
    nominal_freq = 0
    specs = []
    specs_id = []
    spc_id_list = []
    spc_name_list = []

    work = df_nom.copy()
    work['F_diff_ppm'] = np.abs((work['частота'] - target) / target * 1e6)
    print('find_closest (legacy)')
    min_diff_ppm = work['F_diff_ppm'].min()
    print('Row', row)
    print('Target', target)
    print('Min', min_diff_ppm)

    if min_diff_ppm > 100:
        nominal_freq = round(float(target))
        print('Номинал не найден')
        return pd.Series([nominal_freq, specs, specs_id, spc_id_list, spc_name_list])

    candidates = work[work['F_diff_ppm'] == min_diff_ppm]
    print('Find_closest', 'Candidates', candidates)
    if row.get('CL_Metod') == 'PHYSICAL' or (hasattr(row, 'index') and 'CL_Metod' in row.index and row['CL_Metod'] == 'PHYSICAL'):
        fl = row['FL'] if 'FL' in (row.index if hasattr(row, 'index') else row) else 0
        try:
            fl = float(fl)
        except Exception:
            fl = 0
        if fl > 0:
            candidates = candidates[candidates['Cn(pF)'] > 0]
        else:
            candidates = candidates[candidates['Cn(pF)'] == 0]

    if not candidates.empty:
        nominal_freq = round(float(candidates['частота'].iloc[0]))
        specs = candidates['наименование'].tolist()
        specs_id = candidates['номенклатура'].tolist()
        df_spc_id = get_psi_specification_legacy(specs_id)
        if not df_spc_id.empty:
            spc_id_list = df_spc_id['SpcID'].tolist()
            spc_name_list = df_spc_id['SpcName'].tolist()
    else:
        nominal_freq = round(float(target))

    return pd.Series([nominal_freq, specs, specs_id, spc_id_list, spc_name_list])


def get_psi_specification_legacy(spc_id):
    """Полный SQL nomeklatura_rk_psi на каждый вызов."""
    if not spc_id:
        return pd.DataFrame(columns=['SpcID', 'SpcName', 'NomenklaturaID'])
    engine = create_engine(str(get_connection_string()))
    try:
        sql = (
            "SELECT `NomenklaturaID`, `SpcID`, `SpcName` "
            "FROM `nomeklatura_rk_psi` ORDER BY `SpcName`"
        )
        df = pd.read_sql_query(sql, engine)
    except Exception:
        df = pd.read_sql_query(
            "SELECT * FROM `nomeklatura_rk_psi` ORDER BY `SpcName`", engine
        )
    cols = [c for c in ('SpcID', 'SpcName', 'NomenklaturaID') if c in df.columns]
    return df[df['NomenklaturaID'].isin(spc_id)][cols].copy()


def get_multy_spec_legacy(row):
    result = []
    temp_list = row['Temp_List']
    engine = create_engine(str(get_connection_string()))
    spc_df = pd.read_sql("Select * from spc_special", engine)
    try:
        str_list1 = [str(int(float(x))) for x in temp_list]
    except (TypeError, ValueError):
        str_list1 = [str(x) for x in temp_list]
    for _, spc_ in spc_df.iterrows():
        db_temps = str(spc_['Temps']).split()
        if sorted(str_list1) == sorted(db_temps):
            result.append(spc_['Multy_Spc_Name'])
    return result


def test_temp_interval_points_legacy(data, spc_list):
    if not spc_list:
        return []
    engine = create_engine(str(get_connection_string()))
    placeholders = ','.join(['%s'] * len(spc_list))
    spc_query = f"""
        SELECT s.`Name`, s.`Profile`, tp.`Temperatures`
        FROM `specification` s
        LEFT JOIN `temperatureprofile` tp ON s.`Profile` = tp.`Name`
        WHERE s.`Name` IN ({placeholders})
    """
    try:
        spc_df = pd.read_sql(spc_query, engine, params=tuple(spc_list))
    except Exception as e:
        print(f"Database error in test_temp_interval_points_legacy: {e}")
        return []

    file_temps_raw = data['Temp_List'] if hasattr(data, '__getitem__') else []
    try:
        if isinstance(file_temps_raw, (list, tuple, set, np.ndarray)):
            file_temps = set(float(x) for x in file_temps_raw)
        else:
            file_temps = set(file_temps_raw)
    except Exception:
        file_temps = set(file_temps_raw) if file_temps_raw is not None else set()
    data_len = len(file_temps)

    def check_temps(temp_str):
        if not temp_str:
            return False
        try:
            db_temps = list(map(float, str(temp_str).split()))
            return (
                (set(db_temps) == file_temps and len(db_temps) == data_len)
                or (set(db_temps).issubset(file_temps) and data_len >= len(db_temps))
            )
        except (ValueError, AttributeError):
            return False

    if spc_df.empty:
        return []
    spc_df = spc_df.copy()
    spc_df['Temps_test'] = spc_df['Temperatures'].apply(check_temps)
    return spc_df[spc_df['Temps_test']]['Name'].tolist()


def get_nominal_legacy(df_data: pd.DataFrame, machine_type: str):
    """Классический get_nominal: SQL nomeklatura_rk каждый раз, legacy find_closest."""
    if not df_data.empty:
        engine = create_engine(str(get_connection_string()))
        sql = (
            "select distinct `частота`, `Cn(pF)`, `наименование`, `номенклатура` "
            "from `nomeklatura_rk` order by `наименование`"
        )
        df = pd.read_sql_query(sql, engine)
        df_main = df.dropna().loc[df['частота'] != 0].copy()
        df_main['частота'] = df_main['частота'] * 1000
        df_data = set_target_freq(df_data, machine_type)
        df_data[['Номинал', 'Spec_list', 'Specs_ID', 'SpcID', 'SpcName']] = df_data.apply(
            find_closest_specs_legacy, axis=1, df_nom=df_main
        )
        base_cols = [
            'Position_str', 'Номинал', 'Spec_list', 'Selected_Temp', 'Position',
            'Specs_ID', 'SpcID', 'SpcName', 'CL', 'CL_Metod', 'CL_Value', 'SETUPNUM'
        ]
        extra = [c for c in (
            'FS', 'FL', 'Target_Hz', 'R', 'C0', 'C1', 'Q', 'L', 'Fs', 'Fl'
        ) if c in df_data.columns]
        output_df = df_data[base_cols + extra].copy()
    else:
        columns = [
            'Position_str', 'Номинал', 'Spec_list', 'Selected_Temp', 'Position',
            'Specs_ID', 'SpcID', 'SpcName', 'CL', 'CL_Metod', 'CL_Value', 'SETUPNUM'
        ]
        output_df = pd.DataFrame(columns=columns)
    print('get nominal (legacy)')
    print(output_df)
    return output_df


def find_closest_specs(row, df_nom: pd.DataFrame):
    if is_fast_spec_search_enabled():
        return find_closest_specs_fast(row, df_nom)
    return find_closest_specs_legacy(row, df_nom)


def get_psi_specification(spc_id):
    if is_fast_spec_search_enabled():
        return get_psi_specification_fast(spc_id)
    return get_psi_specification_legacy(spc_id)


def get_multy_spec(row):
    if is_fast_spec_search_enabled():
        return get_multy_spec_fast(row)
    return get_multy_spec_legacy(row)


def test_temp_interval_points(data, spc_list):
    if is_fast_spec_search_enabled():
        return test_temp_interval_points_fast(data, spc_list)
    return test_temp_interval_points_legacy(data, spc_list)


def get_nominal(df_data: pd.DataFrame, machine_type: str):
    if is_fast_spec_search_enabled():
        print('[SpecSearch] режим: быстрый')
        return get_nominal_fast(df_data, machine_type)
    print('[SpecSearch] режим: классический')
    return get_nominal_legacy(df_data, machine_type)


def build_spc_combo_list(row) -> list:
    """
    Список для combo: быстрый (ranking) или классический (temp + multi + sort по имени).
    """
    if is_fast_spec_search_enabled():
        return build_ranked_spc_combo_list(row)

    spc_list = row.at['SpcName'] if hasattr(row, 'at') else row.get('SpcName', [])
    if spc_list is None:
        spc_list = []
    if isinstance(spc_list, np.ndarray):
        spc_list = spc_list.tolist()
    if not isinstance(spc_list, list):
        spc_list = list(spc_list) if spc_list is not None else []

    filtered = test_temp_interval_points_legacy(row, spc_list)
    multi = get_multy_spec_legacy(row)
    for m in multi:
        if m not in filtered:
            filtered.append(m)
    filtered.sort()
    if not filtered:
        filtered = ['Нет']
    filtered = _apply_ai_to_spc_list(filtered, row)
    print(f'[SpecSearch] legacy combo default={filtered[0]!r}, n={len(filtered)}')
    return filtered



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
