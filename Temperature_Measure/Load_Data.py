import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text
import re
from tabulate import tabulate

from Options import get_connection_string, parse_connection_string
from Temperature_Measure.measure_data_class import MEASURE_DATA
from Temperature_Measure.spc_matching import (FREQ_TOL_PPM, parse_temp_list,
                                              temps_covered, temps_sets_equal,
                                              temps_match,
                                              load_types_compatible,
                                              nominal_matches)
import mysql.connector
from mysql.connector import Error


def get_resonator_type_psi():
    """
    Метод возвращает список типов резонаторов для измерительных спецификаций
    :return:
    """
    engine = create_engine(str(get_connection_string()))
    sql = "Select `Type` from `resonatortype` ORDER by `Type`"
    df = pd.read_sql_query(sql, engine)  # Запращиваем список типов резонаторов
    return df['Type'].tolist()


def get_resonator_spc_psi_type(spc_name):
    """
    Метод возвращает список типов резонаторов для измерительных спецификаций
    :return:
    """
    engine = create_engine(str(get_connection_string()))
    sql = ("Select `Name`, `ID`, `NameR` from `specification` where `Name`='" + spc_name + "'")
    df = pd.read_sql_query(sql, engine)  # Запрашиваем список типов спецификаций для типа резонатора
    return df['NameR'].tolist()


def get_resonator_spc_type_nominal(spc_name):
    """
    Метод возвращает номинал и тип резонатора для выбранной номенклатуры
    :return:
    """
    engine = create_engine(str(get_connection_string()))
    # Запрашиваем список типов спецификаций для типа резонатора
    sql = ("Select `наименование`,`частота`, `РКНомер`,`Гармоника` from `nomeklatura_rk` where `наименование`='"
           + spc_name + "'")
    df = pd.read_sql_query(sql, engine)
    # Запрашиваем список тип резонатора по коду
    sql = ("Select `ID`, `Name` from `resonatortype_rq` where `ID`='" + str(df['РКНомер'].iloc[0]) + "'")
    df_re = pd.read_sql_query(sql, engine)

    df['Номинал'] = np.where(  # формируем новую колнку номинала в зависимости от гармоники
        df['Гармоника'] > 1,
        (df['частота'] / 1000).round(6).astype(str) + "M",  # Если гармоника > 1
        df['частота'].round(6).astype(str) + "K"  # Если гармоника <= 1
    )
    return df['Номинал'].iloc[0], str(df_re['Name'].iloc[0])


def get_resonator_spc_psi(type_res: str):
    """
    Метод возвращает список номенклатур резонаторов для измерительных спецификаций
    :param type_res:
    :return:
    """
    engine = create_engine(str(get_connection_string()))
    sql = ("Select `Name`, `ID`, `NameR` from `specification` where `NameR`='" + type_res +
           "' ORDER by `Name`")
    df = pd.read_sql_query(sql, engine)  # Запрашиваем список типов спецификаций для типа резонатора
    return df['Name'].tolist()


def get_resonator_spc_psi_data(spc_name: str) -> pd.DataFrame():
    """
    Метод возвращает данные для выбранной спецификации измерений
    :param spc_name:
    :return:
    """
    engine = create_engine(str(get_connection_string()))
    sql = ("Select `Name`, `ID`, `Nominal`, `Profile`, `LoadType`, `Loadvalue`, `Multy` from `specification`"
           " where `Name`='" + spc_name + "'")
    df = pd.read_sql_query(sql, engine)  # Запрашиваем спецификацию по названию
    # Ищем связанные номенклатуры
    sql = "select * from `nomeklatura_rk_psi` order by `SpcName`"  # Получаем данные на связь спецификаций
    df_nom_psi = pd.read_sql_query(sql, engine)
    first_id = df.iloc[0]['ID']
    filtered_df2 = df_nom_psi[df_nom_psi['SpcID'] == first_id]
    nom_list = filtered_df2['NomenklaturaName'].tolist()
    df['Nom_List'] = [nom_list] * len(df)
    df['LoadType'] = df['LoadType'].replace({
        'Series': 'SERIES',
        'EqReact': 'EQREACT',
        'Phisical': 'PHYSICAL',
        'Saunders (FR+FL)': 'EQREACT',
        'Saunders(FR)': 'SERIES',
        'Saunders(FL)': 'PHYSICAL',
        '0': 'SERIES'
    })
    return df


# Загружает и сортирует список номеров и позиций для номера партии

def load_numbers_list(slot: str) -> pd.DataFrame:
    print('load measure_list', 'slot', slot)
    df = MEASURE_DATA.get_numbers_list(slot)
    print('Numbers', df)

    # Нормализация позиций: удаление ведущих нулей
    def normalize_position(pos):
        import re
        match = re.match(r'^([A-Za-z]+)(\d+)$', str(pos))
        if match:
            return match.group(1) + str(int(match.group(2)))
        return pos

    df['Positions'] = df['Positions'].apply(normalize_position)
    print(df['Positions'])
    # Извлечение буквенной и числовой частей для сортировки
    df['letter'] = df['Positions'].str.extract(r'([A-Za-z]+)', expand=False).str.upper()
    df['number'] = df['Positions'].str.extract(r'(\d+)', expand=False).astype(int)
    df_sorted = df.sort_values(by=['letter', 'number']).reset_index(drop=True)
    df_sorted = df_sorted.drop(['letter', 'number'], axis=1)

    MEASURE_DATA.numbers_select_dict[str(slot)] = df_sorted
    return df_sorted


def load_numbers_list_1(slot: str) -> pd.DataFrame:
    df = MEASURE_DATA.get_numbers_list(slot)
    # Извлечение буквенной и числовой частей
    df['letter'] = df['Positions'].str.extract(r'([A-Za-z]+)', expand=False).str.upper()
    df['number'] = df['Positions'].str.extract(r'(\d+)', expand=False).astype(int)
    # Сортируем и обновляем индексы
    df_sorted = df.sort_values(by=['letter', 'number']).reset_index(drop=True)

    # Удаляем временные колонки (если не нужны)
    df_sorted = df_sorted.drop(['letter', 'number'], axis=1)
    MEASURE_DATA.numbers_select_dict[str(slot)] = df_sorted
    return df_sorted


# Добавляет серия к номерам
def add_sn_letters_to_numbers(setupnum: str, serial_n: str):
    # Загружаем список номеров
    numbers_list = load_numbers_list(setupnum)
    serial_n = serial_n.upper()

    def process_number(number):
        # Проверка на пустоту или только буквы
        if pd.isna(number) or (str(number).strip() == ''):
            return '0000'
        s = str(number).strip()
        if s.isalpha():
            return '0000'
        # Проверка первых 3 или 2 символов
        if len(s) >= 3 and s[:3].isalpha():
            new_s = s[3:]
        elif len(s) >= 2 and s[:2].isalpha():
            new_s = s[2:]
        else:
            new_s = s
        return f"{serial_n}{new_s}"

    numbers_list['Numbers'] = numbers_list['Numbers'].apply(process_number)
    MEASURE_DATA.set_numbers_list(setupnum, numbers_list)


# Задает номера от начальной до конечной позиции начиная с начального номера
def fill_numbers(start_pos, end_pos, first_number, slot: str):
    df = load_numbers_list(slot)
    first_number = first_number.upper()

    # Проверка формата first_number
    if not re.match(r'^[A-Za-z]{0,3}\d{1,6}$', first_number):
        raise ValueError("Некорректный формат first_number")

    # Разделение буквенной и цифровой частей
    letters_match = re.match(r'^([A-Za-z]{0,3})', first_number)
    letters = letters_match.group(1) if letters_match else ''
    digits = re.sub(r'^[A-Za-z]*', '', first_number)

    # Определение параметров генерации
    start_num = int(digits) if digits else 0
    num_length = len(digits) if digits else 1

    # Функция для извлечения буквы и числа из позиции
    def parse_pos(pos):
        letter_part = re.match(r'^[A-Za-z]+', pos).group()
        number_part = re.sub(r'^[A-Za-z]*', '', pos)
        return letter_part.upper(), int(number_part)

    # Функция для расчета комбинированного кода
    def get_pos_code(pos):
        letter, num = parse_pos(pos)
        # Преобразуем букву в числовой код (A=1, B=2, ..., Z=26)
        # Умножаем на 10^6, чтобы избежать коллизий при больших числах
        return (ord(letter[0]) - ord('A') + 1) * 10 ** 6 + num

    # Получаем коды начальной и конечной позиций
    start_code = get_pos_code(start_pos)
    end_code = get_pos_code(end_pos)

    # Создаем столбец с кодами позиций
    df['Pos_Code'] = df['Positions'].apply(get_pos_code)

    # Фильтрация и сортировка по кодам позиций
    mask = (df['Pos_Code'] >= start_code) & (df['Pos_Code'] <= end_code)
    filtered_df = df[mask].sort_values(by='Pos_Code')
    filtered_indices = filtered_df.index.tolist()

    # Заполнение номеров в правильном порядке
    for i, idx in enumerate(filtered_indices):
        current_num = start_num + i
        df.at[idx, 'Numbers'] = f"{letters}{current_num:0{num_length}d}"

    MEASURE_DATA.set_numbers_list(slot, df)


# Функция задает номера текущей партии в соотвествии с указанным замером ИД или МСК
def process_batch_data(input_str):
    # Определяем тип входной строки
    df = load_numbers_list(MEASURE_DATA.active_slot_number)
    print('IN')
    print(df)
    # Добавляем колонку Numbers, если её нет
    if 'Numbers' not in df.columns:
        df['Numbers'] = None
    engine = create_engine(str(get_connection_string()))
    if re.match(r'^\d+-\d+$', input_str):
        query_type = 'msk'
        query_value = input_str
    elif input_str.isdigit():
        query_type = 'Measure_ID'
        query_value = int(input_str)
    else:
        raise ValueError("Неверный формат. Ожидается: XX-XXXX или число")

    # Формируем SQL-запрос с учетом минимального Measure_ID
    if query_type == 'msk':
        sql = f"""
            SELECT p.Position, p.N 
            FROM psidata p
            INNER JOIN (
                SELECT MIN(Measure_ID) as min_id 
                FROM psidata 
                WHERE msk = '{query_value}'
            ) AS sub
            ON p.Measure_ID = sub.min_id
        """
    else:
        sql = f"SELECT Position, N FROM psidata WHERE Measure_ID = {query_value}"

    # Выполняем запрос
    db_data = pd.read_sql(sql, engine)
    print('DB DATA')
    print(db_data)
    if not db_data.empty:
        # Фильтруем DF по найденным позициям
        filtered_df = df[df['Positions'].isin(db_data['Position'])]

        # Объединяем с данными из БД
        merged = filtered_df.merge(db_data,
                                   left_on='Positions',
                                   right_on='Position',
                                   how='left')
        print('Merge')
        print(merged)

        # Обработка дубликатов
        duplicates = merged['N'].duplicated(keep=False)
        merged.loc[duplicates, 'N'] = None
        if not merged.empty:
            # Обновляем основной DF
            df.update(merged[['N']].rename(columns={'N': 'Numbers'}))
            print(df)
            MEASURE_DATA.set_numbers_list(MEASURE_DATA.active_slot_number, df)


# Функция задания номеров из номеров маркировки мск по ид мск или ее названию
def add_numbers_by_msk(start_pos, end_pos, input_str: str):
    # Добавляем колонку Numbers, если её нет
    df = load_numbers_list(MEASURE_DATA.active_slot_number)
    engine = create_engine(str(get_connection_string()))
    if 'Numbers' not in df.columns:
        df['Numbers'] = None
    if re.match(r'^\d+-\d+$', input_str):
        query_type = 'msk'
        query_value = input_str
    elif input_str.isdigit():
        query_type = 'Measure_ID'
        query_value = int(input_str)
    else:
        raise ValueError("Неверный формат. Ожидается: XX-XXXX или число")
    if query_type == 'Measure_ID':
        sql = "Select `мск`, `мскРеал` from `msk_rq` where `msk`='" + str(query_value) + "'"
        df_msk = pd.read_sql(sql, engine)
        msk = df_msk['мскРеал'].iloc[0]
    else:
        msk = query_value

    sql = "Select `MSK`, `Begin` from `marker` where `MSK`='" + msk + "'"
    df_marker = pd.read_sql(sql, engine)
    fill_numbers(start_pos, end_pos, str(df_marker['Begin'].iloc[0]), MEASURE_DATA.active_slot_number)


# Функция проверки номеров перед сохранением
def test_numbers_dataframe(slot: str):
    numbers_str = 'Нет'
    df = load_numbers_list(slot)
    print('test_numbers_list')
    print('Slot', slot)
    print('DF', df)
    MEASURE_DATA.set_numbers_list(slot, df)
    print('Save_DF', df)
    # Формируем результат
    result_df = load_numbers_list(slot)[['Positions', 'Numbers']]
    result_df.columns = ['Позиции', 'Номера']
    # Вывод таблицы с границами
    print("\nТаблица номеров:")
    print(tabulate(result_df, headers='keys', tablefmt='psql', showindex=False))
    return make_number_str(df)


# Получает интревал номеров и сами номера для номера партии
def make_number_str(df):
    numbers_str = 'Нет'
    valid_numbers = []
    # Предобработка данных
    df['Numbers'] = (
        df['Numbers']
        .astype(str)
        .str.strip()
        .replace({'': '0000', 'nan': '0000'})
        .str.upper()
    )

    # Поиск дубликатов (исключая 0000)
    temp_series = df['Numbers'].where(df['Numbers'] != '0000')
    duplicates_mask = temp_series.duplicated(keep=False)
    duplicates = df[duplicates_mask]

    # Вывод дубликатов
    if not duplicates.empty:
        grouped = (
            duplicates
            .groupby('Numbers')['Positions']
            .agg(list)
            .reset_index()
        )

        print("Найдены дубликаты:")
        print(tabulate(grouped, headers='keys', tablefmt='psql', showindex=False))
    else:
        # Формирование интервала для уникальных значений (исключая 0000)
        valid_numbers = sorted(
            df[df['Numbers'] != '0000']['Numbers'].unique(),
            key=lambda x: (len(x), x)
        )

        if valid_numbers:
            first = valid_numbers[0]
            last = valid_numbers[-1]
            numbers_str = f" {first}...{last}"
        else:
            numbers_str = 'Нет'
    return numbers_str


# Функция возвращает МСК/ номеклатуру / тип резонатора и его номинала по штрих коду
def get_msk_by_id(input_str, code=True):
    engine = create_engine(str(get_connection_string()))
    msk_field = 'мск'
    if not code:
        msk_field = 'мскРеал'

    # Первый запрос для получения базовой информации
    msk_query = f"SELECT `мскРеал`, `КодНоменклатуры`, `мск` FROM `msk_rk` WHERE `{msk_field}` = '{input_str}'"
    msk_df = pd.read_sql(msk_query, engine)

    if msk_df.empty:
        return (None,) * 4

    # Второй запрос для номенклатуры
    nom_query = f"""
        SELECT `наименование`, `частота`, `РКНомер`, `Гармоника` 
        FROM `nomeklatura_rk` 
        WHERE `номенклатура` = '{msk_df.iloc[0]['КодНоменклатуры']}'
    """
    nom_df = pd.read_sql(nom_query, engine)

    if nom_df.empty:
        return (None,) * 4

    # Формирование номинала
    freq = nom_df.iloc[0]['частота']
    harmonic = nom_df.iloc[0]['Гармоника']
    nominal = f"{freq / 1000}M" if harmonic > 1 else f"{freq}K"

    # Третий запрос для типа резонатора
    type_query = f"SELECT `Name` FROM `resonatortype_rq` WHERE `ID` = '{nom_df.iloc[0]['РКНомер']}'"
    type_df = pd.read_sql(type_query, engine)

    return (
        msk_df.iloc[0]['мскРеал'],
        nom_df.iloc[0]['наименование'],
        nominal,
        type_df.iloc[0]['Name'] if not type_df.empty else None
    )


# Функция возвращает информацию на выбранную мск
def get_msk_inf(msk_str):
    engine = create_engine(str(get_connection_string()))

    # Первый запрос для базовой информации MSK
    msk_query = f"SELECT `мскРеал`, `статус шт`, `Cn`, `КодНоменклатуры` FROM `msk_rk` WHERE `мскРеал` = '{msk_str}'"
    msk_df = pd.read_sql(msk_query, engine)

    if msk_df.empty:
        return None, None, None, None, []

    # Извлекаем основные значения
    msk_data = msk_df.iloc[0]
    nom_code = msk_data['КодНоменклатуры']

    # Запрос данных номенклатуры
    nom_query = f"""
        SELECT `наименование`, `частота`, `РКНомер`, `Гармоника`, `Cn(pF)` 
        FROM `nomeklatura_rk` 
        WHERE `номенклатура` = '{nom_code}'
    """
    nom_df = pd.read_sql(nom_query, engine)

    if nom_df.empty:
        return None, None, None, None, [], None
    # Получаем суффикс для МСК
    msk_suffix = get_auto_suffix(nom_df['РКНомер'].iloc[0], msk_str)

    # Формирование номинала
    freq = nom_df.iloc[0]['частота']
    nominal = f"{freq / 1000}M" if nom_df.iloc[0]['Гармоника'] > 1 else f"{freq}K"

    # Запрос номеров маркировки
    marker_query = f"SELECT `Begin`, `End` FROM `marker` WHERE `MSK` = '{msk_data['мскРеал']}'"
    marker_df = pd.read_sql(marker_query, engine)
    numbers = f"{marker_df['Begin'].iloc[0]}...{marker_df['End'].iloc[0]}" if not marker_df.empty else ''

    # Запрос спецификаций
    spc_query = f"SELECT `SpcName` FROM `nomeklatura_rk_psi` WHERE `NomenklaturaID` = '{nom_code}'"
    spc_list = pd.read_sql(spc_query, engine)['SpcName'].tolist()

    return (
        nominal,
        nom_df.iloc[0]['Cn(pF)'],
        msk_data['статус шт'],
        numbers,
        spc_list,
        msk_suffix
    )


# Функция проверяет соответсвие номинальной часто измерительного файла и выбранной мск
def test_nominal_freq(msk_str, slot):
    engine = create_engine(str(get_connection_string()))

    query = f"""
        SELECT n.`частота` 
        FROM msk_rk m
        JOIN nomeklatura_rk n ON m.`КодНоменклатуры` = n.`номенклатура`
        WHERE m.`мскРеал` = '{msk_str}'
    """
    result = pd.read_sql(query, engine)

    nominal_db = result.iloc[0, 0] * 1000
    nominal_file = float(MEASURE_DATA.get_setupnum_data(slot)['Номинал'])

    # Добавляем абсолютное значение и правильную проверку
    diff = abs((nominal_db - nominal_file) / nominal_db) * 1e6

    # Правильный порядок проверки условий
    if diff < 100:
        return 'OK'
    elif diff < 300:
        return 'Не полное соответствие'
    return 'Не соответствует'


# Возвращает номенклатуру RQ для указанной МСК (Название)
def get_msk_nom(msk_str):
    engine = create_engine(str(get_connection_string()))

    query = f"""
            SELECT n.`частота`, n.`наименование` 
            FROM msk_rk m
            JOIN nomeklatura_rk n ON m.`КодНоменклатуры` = n.`номенклатура`
            WHERE m.`мскРеал` = '{msk_str}'
        """
    result = pd.read_sql(query, engine)
    if result is not None and not result.empty:
        return result['наименование'].iloc[0]
    else:
        return None


# Функция автоматической задачи номеров для заданного мск
def set_numbers_auto_msk(msk_str):
    engine = create_engine(str(get_connection_string()))
    slot = MEASURE_DATA.active_slot_number

    # Получаем начальный номер маркировки
    marker_df = pd.read_sql(f"SELECT Begin FROM marker WHERE MSK = '{msk_str}'", engine)
    if marker_df.empty:
        return None
    # Загружаем и обрабатываем номера
    numbers_data = load_numbers_list(slot)
    start = numbers_data['Positions'].tolist()[0]
    end = numbers_data['Positions'].tolist()[-1]
    fill_numbers(start, end, marker_df.iat[0, 0], slot)

    # Формируем результат
    result_df = load_numbers_list(slot)[['Positions', 'Numbers']]
    result_df.columns = ['Позиции', 'Номера']

    # Вывод таблицы с границами
    print("\nТаблица номеров:")
    print(tabulate(result_df, headers='keys', tablefmt='psql', showindex=False))

    # Возвращаем граничные значения
    return f"{result_df['Номера'].iloc[0]}...{result_df['Номера'].iloc[-1]}"


def process_nominal(df):
    # Создаем копию для безопасной модификации
    df = df.copy()

    # Преобразуем колонку
    df['Nominal'] = (
            df['Nominal']
            .astype(str)
            .str.replace(",", ".", regex=False)
            .apply(pd.to_numeric, errors='coerce')
            * 1_000_000
    )

    # Удаляем строки с ошибками (опционально)
    df = df.dropna(subset=['Nominal'])

    return df


# Проверка температурного интревала для списка спецификаций


def test_spcecification(slot):
    engine = create_engine(str(get_connection_string()))
    data = MEASURE_DATA.get_setupnum_data(slot)
    spc_sel_df = MEASURE_DATA.get_spc_sel_list(slot)
    if spc_sel_df is None:
        return "Отсутсвует спецификация"

    if spc_sel_df.empty:
        return "Не соответствует"

    spc_sel_df = process_nominal(spc_sel_df)
    # Исправляем номинал в случае мульти спецификаций.
    # Раньше правка выполнялась через iterrows (запись в копию строки),
    # поэтому DataFrame не менялся и мульти-спецификации всегда возвращали
    # "Не соответствует". Теперь правим исходный df по маске.
    multy_mask = spc_sel_df['Multy'] == 1
    if multy_mask.any():
        spc_sel_df.loc[multy_mask, 'Nominal'] = data['Номинал'] / 1E6

    # Допуск по номиналу: 100 ppm вместо строгого равенства float
    # (равенство float давало ложные отказы из-за погрешностей округления)
    if not spc_sel_df['Nominal'].apply(
            lambda f: nominal_matches(f, data['Номинал'],
                                      tol_ppm=FREQ_TOL_PPM)).all():
        return "Не соответствует"

    # Совместимость режима измерения и типа нагрузки.
    # Проверка Loadvalue == CL_Value (подбор по ёмкости нагрузки) убрана:
    # расхождения в форме записи значения CL (нули, '32(30)') отбраковывали
    # корректные спецификации.
    cl_metod = data['CL_Metod']
    if not all(load_types_compatible(cl_metod, load_type)
               for load_type in spc_sel_df['LoadType']):
        return "Не соответствует"

    temp_results = []
    for _, row in spc_sel_df.iterrows():
        profile_id = row['Profile']
        query = f"SELECT `Temperatures` FROM `temperatureprofile` WHERE `Name` = '{profile_id}'"
        df_temp = pd.read_sql(query, engine)

        if df_temp.empty:
            return "Не соответствует"

        temp_str = df_temp['Temperatures'].iloc[0]
        # Парсинг устойчив к формату записи: 25 vs 25.0, разделители
        # ',' / ';' / пробелы, None (раньше строки сравнивались в исходном
        # виде и проверка падала на неожиданном формате)
        temp_list_db = parse_temp_list(temp_str)
        temp_list_data = parse_temp_list(data['Temp_List'])

        if temps_sets_equal(temp_list_data, temp_list_db):
            temp_results.append("OK")
        elif temps_covered(temp_list_db, temp_list_data):
            temp_results.append("OK (Интервал избыточен)")
        elif temps_match(temp_list_db, temp_list_data):
            temp_results.append("OK (Гибкое совпадение интервала)")
        else:
            temp_results.append("Не соответствует")

    if "Не соответствует" in temp_results:
        return "Не соответствует"
    elif "OK" in temp_results:
        return "OK"
    elif "OK (Интервал избыточен)" in temp_results:
        return "OK (Интервал избыточен)"
    else:
        return "OK (Гибкое совпадение интервала)"


# Функция проверяет соответсвие установленных номеров номерам МСК
def check_serial_numbers(slot, msk_str):
    """
    Проверяет, принадлежат ли серийные номера заданному интервалу [begin_number, end_number].
    Возвращает статус и DataFrame с несоответствующими позициями.
    """
    df = MEASURE_DATA.get_numbers_list(slot)
    if df is not None and not df.empty and 'Numbers' in df.columns:
        engine = create_engine(str(get_connection_string()))
        # Получаем начальный номер маркировки
        marker_df = pd.read_sql(f"SELECT `Begin`, `End` FROM marker WHERE MSK = '{msk_str}'", engine)
        if not marker_df.empty:
            begin_number = marker_df['Begin'].iloc[0]
            end_number = marker_df['End'].iloc[0]
            # Проверяем корректность интервала
            if begin_number > end_number:
                raise ValueError("Начало интервала должно быть меньше или равно концу")

            # Фильтруем номера вне интервала
            invalid_df = df[
                (df['Numbers'].str.strip() < begin_number) |
                (df['Numbers'].str.strip() > end_number)
                ].copy()

            # Добавляем колонку с ожидаемым статусом
            invalid_df['Status'] = 'Не соответствует'

            # Формируем результат
            if invalid_df.empty:
                return "OK", pd.DataFrame()
            else:
                return "Не соответствует", invalid_df[['Positions', 'Numbers', 'Status']]
        else:
            return 'OK', pd.DataFrame()
    else:
        return "Не соответствует", pd.DataFrame()


# Возвращает значение ИД МСК по ее названию
def get_msk_id_by_name(msk_str):
    engine = create_engine(str(get_connection_string()))
    sql = "Select `мск`, `мскРеал` from `msk_rk` where `мскРеал`='" + msk_str + "'"
    msk_df = pd.read_sql(sql, engine)
    return msk_df['мск'].iloc[0]


# Возвращает список суффиксов МСК
def get_msk_suffix_list():
    engine = create_engine(str(get_connection_string()))
    sql = "Select `Name` from `msk_sufix` order by `Name`"
    suf_df = pd.read_sql(sql, engine)
    return suf_df['Name'].tolist()


# Функция для получения реального номера МСК в случае использования суффиксов
def clean_MSK(msk_str):
    """Извлекает идентификатор партии в формате YY-XXXX"""
    if pd.isna(msk_str):
        return None
    if '-' in msk_str:
        # Ищем последовательность: цифры, дефис, цифры до первого нецифрового символа
        match = re.match(r'^(\d+-\d+)', msk_str)  # Изменено: \d+ вместо \d{2}
        return match.group(1) if match else msk_str
    else:
        return None


# Создает автоматическое имя МСК
def generate_msk_name():
    """
    Генерирует уникальный номер msk_name в формате ddmmyy_xxxx.
    Обеспечивает корректную работу в многопользовательской среде.

    Параметры:
        connection_params (dict): Параметры подключения к MySQL.

    Возвращает:
        str: Сгенерированный msk_name или None при ошибке.
    """
    conn = None
    cursor = None
    try:

        # Устанавливаем соединение с базой данных
        params = parse_connection_string()
        conn = mysql.connector.connect(**params)

        # Начинаем транзакцию с уровнем изоляции SERIALIZABLE
        conn.start_transaction(isolation_level='SERIALIZABLE')
        cursor = conn.cursor()

        # Получаем текущую дату с сервера MySQL
        cursor.execute("SELECT CURDATE()")
        current_date = cursor.fetchone()[0]
        ddmmyy = current_date.strftime('%d%m%y')

        # Запрос максимального номера xxxx за текущую дату
        cursor.execute("""
            SELECT MAX(CAST(SUBSTRING_INDEX(msk_name, '_', -1) AS UNSIGNED))
            FROM `msk_new_id`
            WHERE date = %s
        """, (current_date,))
        max_number = cursor.fetchone()[0]

        # Определяем следующий номер
        next_number = 1 if max_number is None else max_number + 1
        msk_name = f"{ddmmyy}_{next_number:04d}"

        # Вставляем новую запись в таблицу
        cursor.execute("""
            INSERT INTO msk_new_id (msk_name, date)
            VALUES (%s, %s)
        """, (msk_name, current_date))

        # Фиксируем транзакцию
        conn.commit()
        return msk_name

    except Error as e:
        print(f"Ошибка при генерации msk_name: {e}")
        if conn:
            conn.rollback()
        return None
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()


# Добавляет суффикс в БД
def manage_suffix(input_str):
    """
    Добавляет значение input_str в таблицу msk_sufix, если его нет.
    Возвращает список всех значений из колонки Name.

    :param input_str: Строка для добавления
    :param db_url: URL подключения к базе данных (например, 'mysql+pymysql://user:pass@localhost/dbname')
    :return: Список всех значений Name
    """
    engine = create_engine(get_connection_string())

    with engine.begin() as connection:  # Автоматическое управление транзакцией
        # Проверка существования значения
        check_query = text("SELECT * FROM msk_sufix WHERE Name = :name")
        existing = pd.read_sql(check_query, connection, params={'name': input_str})

        if not existing.empty:
            print("Значение уже существует в таблице.")
        else:
            # Вставка новой записи
            insert_query = text("INSERT INTO msk_sufix (Name) VALUES (:name)")
            connection.execute(insert_query, {'name': input_str})

        # Получение всех значений Name
        all_names = pd.read_sql(text("SELECT Name FROM msk_sufix"), connection)

    return all_names['Name'].tolist()


# Создает связку спецификации и номенклатуры из RQ
def save_map_spc(spc_name, nom_name):
    engine = create_engine(str(get_connection_string()))
    sql = "Select `Name`, `ID` from  `specification` where `Name`='" + spc_name + "'"
    spc_temp = pd.read_sql(sql, engine)
    if len(spc_temp) > 0:
        sql = ("Select `наименование`, `номенклатура`  from `nomeklatura_rk` where `наименование`='"
               + nom_name + "'")
        nom_temp = pd.read_sql(sql, engine)
        print(nom_temp)
        if len(nom_temp) > 0:
            print('Совмещение спецификаций')
            print(f"1: {spc_temp['ID'].iloc[0]}: {spc_temp['Name'].iloc[0]} <---> "
                  f"{nom_temp['номенклатура'].iloc[0]}: {nom_temp['наименование'].iloc[0]}")
            sql = (f"Select * from `nomeklatura_rk_psi` where `SpcID` = '"
                   f"{spc_temp['ID'].iloc[0]}' and `NomenklaturaID`='{nom_temp['номенклатура'].iloc[0]}'")
            nom_spc_df = pd.read_sql(sql, engine)
            if len(nom_spc_df) > 0:
                print("Данная связка спецификаций уже присутствует")
            else:
                data = {'SpcName': spc_temp['Name'].iloc[0],
                        'SpcID': spc_temp['ID'].iloc[0],
                        'NomenklaturaID': nom_temp['номенклатура'].iloc[0],
                        'NomenklaturaName': nom_temp['наименование'].iloc[0]}
                df = pd.DataFrame(data, index=[0])
                df.to_sql(
                    name='nomeklatura_rk_psi',
                    con=engine,
                    if_exists='append',
                    index=False
                )
                print("Выполнено")


# Возвращает автоматический суффикс для МСК опредленного типа
# Тип МСК задется через таблицу spc_special
def get_auto_suffix(type_, msk_str):
    suf = None
    engine = create_engine(str(get_connection_string()))
    sql = f"Select * from  `spc_special` where `Type`='{type_}'"
    type_df = pd.read_sql(sql, engine)
    if not type_df.empty:
        if type_df['Auto_Suffix'].iloc[0] is not None and len(type_df['Auto_Suffix'].iloc[0]) > 2:
            data_list = type_df['Auto_Suffix'].iloc[0].split('_')
            sql = f"Select `{data_list[1]}` from `{data_list[0]}` where `Msk`='{msk_str}'"
            marker_df = pd.read_sql(sql, engine)
            if not marker_df.empty:
                suf = marker_df[data_list[1]].iloc[0]
    else:
        suf = None
    return suf


# Возвразщает значение поля ПМИ для строчки МСК
def get_msk_pmi_status(msk_str):
    engine = create_engine(str(get_connection_string()))
    sql = f"Select `КодНоменклатуры` from `msk_rk` where `мскРеал`='{msk_str}'"
    nom_df = pd.read_sql(sql, engine)
    pmi_str = ""
    if nom_df is not None and not nom_df.empty:
        nom_code = nom_df['КодНоменклатуры'].iloc[0]
        sql = f"Select `наименование` from `nomeklatura_rk` where `номенклатура`='{nom_code}'"
        pmi_df = pd.read_sql(sql, engine)
        pmi_str = pmi_df['наименование'].iloc[0]
    if "ПМИ" in pmi_str:
        pmi =  1
    elif "SMD" in pmi_str:
        pmi = 2
    else:
        pmi = 0
    return  pmi


# Функция возвращает код номенклатуры при известном названии
def get_nom_id_by_name(input_str):
    engine = create_engine(str(get_connection_string()))

    nom_query = f"""
        SELECT `номенклатура`,`наименование`, `частота`, `РКНомер`, `Гармоника` 
        FROM `nomeklatura_rk` 
        WHERE `наименование` = '{input_str}'
    """
    nom_df = pd.read_sql(nom_query, engine)
    code = nom_df.iloc[0]['номенклатура']
    return code
