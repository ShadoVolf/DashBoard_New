import math
from functools import reduce
from math import sqrt

import numpy as np
import numpy.exceptions
import pandas as pd
from sqlalchemy import create_engine
from tabulate import tabulate

from Options import get_connection_string
from Temperature_Measure.Control_RK import find_temperature_correction, \
    find_temperature_correction_network, calculate_corrections, calculate_temperature_correction, \
    calculate_rq_corrections
from Temperature_Measure.measure_data_class import MEASURE_DATA


# Параметры, которые зависят от температурного профиля.
# В режиме одной точки они не вычисляются и не проверяются по спецификации.

def _spc_flag(row, name, default=False):
    """Безопасно читает булевый флаг спецификации (колонка может отсутствовать)."""
    try:
        if name not in row.index:
            return default
        v = row[name]
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return default
        if isinstance(v, (bool, int, float)):
            return bool(v)
        s = str(v).strip().lower()
        return s in ("1", "true", "t", "yes", "y", "да")
    except Exception:
        return default


TEMP_DEPENDENT_PARAMS = {
    'Fmin', 'Fmax', 'F_min_int', 'F_max_int', 'Fptp', 'Fptp/2',
    'ABS(Fmax, Fmin)',
    'Rmin', 'Rmax', 'Rmax-Rmin',
    'Rmax/R_center', 'R_center/Rmin', 'Rmax/Rmin',
    '(Rmax-R25)/R25*100%', '(Rmin-R25)/R25*100%',
    'Rc_Rbmax',
    'extr_1', 'extr_2', 'TurnOver_1', 'Mono', 'MonoT', 'Slope',
    'A0', 'A1', 'A2', 'A3', 'A4', 'A5',
    'Ft', 'Ft1', 'Ft2', 'Ft3', 'Ft4',
}


# конвертация единиц по приставкам
def convert_units(series, prefix):
    """Конвертирует значения в базовые единицы с преобразованием типов"""
    if series.dtype == 'object':
        series = series.str.replace(',', '.', regex=False)

    series = pd.to_numeric(series, errors='coerce')

    if prefix in MEASURE_DATA.UNIT_PREFIXES:
        return series * MEASURE_DATA.UNIT_PREFIXES[prefix]

    return series


def get_file_data():
    engine = create_engine(str(get_connection_string()))
    file_data = MEASURE_DATA.get_data()
    machine_type = file_data['Machine_Type']
    archive_suffix = '_archive' if file_data['Archive'] != 0 else ''

    table_config = {
        'KH7700': {
            'main_table': f'KH7700{archive_suffix}',
            'order': 'ID'
        },
        'Transat': {
            'main_table': f'Transat{archive_suffix}' if not archive_suffix else 'TTS100_archive',
            'order': 'ID'
        },
        'Saunders': {
            'main_table': f'Crystal Data{archive_suffix}',
            'setup_table': f'Setup Data{archive_suffix}',
            'order': 'nDataID'
        },
        'ТЧХ2200': {
            'main_table': 'tch2200_measurement_data',
            'order': 'TimeStamp'
        }
    }

    config = table_config.get(machine_type)
    df_data = pd.DataFrame()
    df_data1 = pd.DataFrame()

    if not config:
        return df_data, df_data1

    try:
        main_table = config['main_table']
        order_column = config['order']
        sql = f"SELECT * FROM `{main_table}` WHERE File_ID='{file_data['File_ID']}' ORDER BY `{order_column}`"
        df_data = pd.read_sql(sql, engine)

        if machine_type == 'Saunders':
            setup_table = config['setup_table']
            sql1 = f"SELECT * FROM `{setup_table}` WHERE File_ID='{file_data['File_ID']}' ORDER BY `{order_column}`"
            df_data1 = pd.read_sql(sql1, engine)

    except KeyError as e:
        print(f"Missing table configuration: {e}")

    return df_data, df_data1


# Загрузка данных измерений
def new_data_compile():
    engine = create_engine(str(get_connection_string()))
    sql = "SELECT * FROM `ms_table_headers` ORDER BY `ID`"
    df_config = pd.read_sql(sql, engine)

    machine_type_id = str(MEASURE_DATA.get_data_inf('Machine_Type_ID'))
    print('ID установки', machine_type_id)

    config_filtered = df_config[
        (df_config['Machine_Type'] == int(machine_type_id)) &
        (df_config['Use'] == 1)
        ]

    df_data, df_data1 = get_file_data()

    if not df_data1.empty:
        if 'nDataID' in df_data1.columns:
            merged_df = pd.merge(
                df_data,
                df_data1,
                on='nDataID',
                how='left',
                suffixes=('', '_right')
            )
            merged_df = merged_df[[col for col in merged_df.columns if not col.endswith('_right')]]
        else:
            merged_df = df_data.copy()
    else:
        merged_df = df_data.copy()

    merged_df.columns = merged_df.columns.str.lower()

    needed_cols = [name.lower() for name in config_filtered['Name']]

    missing_cols = set(needed_cols) - set(merged_df.columns)
    if missing_cols:
        print(f"ВНИМАНИЕ: отсутствуют колонки: {missing_cols}")
        needed_cols = [col for col in needed_cols if col in merged_df.columns]

    output_df = merged_df[needed_cols].copy()

    rename_map = dict(zip(needed_cols, config_filtered['Out_Fields'].values))
    output_df.rename(columns=rename_map, inplace=True)

    for out_col in output_df.columns:
        config_row = config_filtered[config_filtered['Out_Fields'] == out_col]
        if not config_row.empty and not pd.isna(config_row['Name_Units'].iloc[0]):
            prefix = config_row['Name_Units'].iloc[0].strip()
            output_df[out_col] = convert_units(output_df[out_col], prefix)

    return output_df


# Выбирает данные для требуемого слота
def normalize_position(pos):
    """Удаляет ведущие нули из позиции (A001 -> A1)"""
    import re
    match = re.match(r'^([A-Za-z]+)(\d+)$', str(pos))
    if match:
        return match.group(1) + str(int(match.group(2)))
    return pos


def filtr_by_slot(slot, data):
    machine_type_str = MEASURE_DATA.get_data_inf('Machine_Type_ID')

    if machine_type_str == 22:  # KH7700
        data = add_kh7700_slot_by_positions(slot, data)
    elif machine_type_str == 26:  # ТЧХ2200
        data['Positions_norm'] = data['Positions'].apply(normalize_position)

        config_row = MEASURE_DATA.get_setupnum_data(slot)
        if config_row is not None and 'Position' in config_row:
            positions = config_row['Position']
            if positions:
                data = data[data['Positions_norm'].isin(positions)].copy()
        data = data.drop(columns=['Positions_norm'])
    else:
        data = data[data['SETUPNUM'] == int(slot)].copy()
        if machine_type_str == 2:  # Transat
            data.loc[:, 'ring'] = data['RINGID'].map({0: 'L', 1: 'U'}).copy()
            data['Positions'] = data['ring'] + data['RINGPOS'].astype(str)
            data = data.drop(['ring', 'RINGID', 'RINGPOS'], axis=1)

    data['Positions'] = data['Positions'].apply(normalize_position)

    data = add_position_index(data)
    return data


# обновляем датафрейм новой строкой если он существует, если нет — создаёт заново
def update_or_create_dataframe(existing_df, new_row):
    if not isinstance(new_row, pd.DataFrame):
        new_df = pd.DataFrame([new_row])
    else:
        new_df = new_row

    if not isinstance(existing_df, pd.DataFrame) or existing_df.empty:
        return new_df

    if set(existing_df.columns) == set(new_df.columns):
        return pd.concat([existing_df, new_df], ignore_index=True)

    print("Ошибка: несовпадение структуры данных")
    return existing_df


# Загружает список выбранных спецификаций
def load_spc_data(slot):
    engine = create_engine(str(get_connection_string()))
    spc_df = MEASURE_DATA.get_spc_sel_list(slot)
    spc_result = pd.DataFrame()
    for index, row in spc_df.iterrows():
        sql = "Select * from `specification` where `ID`='" + str(row['ID']) + "'"
        spc_data_df = pd.read_sql(sql, engine)
        spc_data_df['LoadType'] = spc_data_df['LoadType'].replace({
            'Series': 'SERIES',
            'EqReact': 'EQREACT',
            'Physical': 'PHYSICAL',
            'Saunders (FR+FL)': 'EQREACT',
            'Saunders(FR)': 'SERIES',
            'Saunders(FL)': 'PHYSICAL',
            '0': 'SERIES'
        })
        spc_result = update_or_create_dataframe(spc_result, spc_data_df)
    return spc_result


# Загружает список температур
def load_profile_data(spc_df):
    engine = create_engine(str(get_connection_string()))
    sql = "Select * from `temperatureprofile` where `Name`='" + spc_df['Profile'] + "'"
    df_temp = pd.read_sql(sql, engine)

    temp_str = df_temp['Temperatures'].iloc[0]
    temp_list_db = list(map(float, temp_str.split()))
    return temp_list_db


# добавляет номера по номеру партии в выходные таблицы
def add_numbers(result_df, data_temp, slot):
    numbers = MEASURE_DATA.get_numbers_list(slot)
    data_temp = data_temp.merge(
        numbers[['Positions', 'Numbers']],
        on='Positions',
        how='left'
    )
    result_df = result_df.merge(
        numbers[['Positions', 'Numbers']],
        on='Positions',
        how='left'
    )
    return result_df, data_temp


# модифицирует нормы спецификации на величину допуска
def create_spc_map_otk(spc_map, row):
    engine = create_engine(str(get_connection_string()))
    sql = "Select * from `spc_dopusk_map_table` order by `ID`"
    dopusk_map = pd.read_sql(sql, engine)
    dopusk_map.drop('ID', axis=1)
    dopusk_df = dopusk_map.apply(
        lambda dop_row: pd.Series({
            'Parameter': dop_row['Parameter'],
            'Dopusk_units': row[dop_row['Dopusk_units']],
            'Dopusk_%': row[dop_row['Dopusk_%']]
        }),
        axis=1
    )

    merged_df = spc_map.merge(dopusk_df, on='Parameter', how='left')

    def apply_tolerance(row):
        max_val = row['Max']
        min_val = row['Min']
        units = row['Dopusk_units']
        percent = row['Dopusk_%']

        use_units = False
        use_percent = False

        if pd.notna(units) and units > 0:
            use_units = True
        if pd.notna(percent) and percent > 0:
            use_percent = True

        if use_units and use_percent:
            use_percent = False

        if pd.notna(max_val):
            if use_units:
                max_val -= units
            elif use_percent:
                max_val *= (1 - percent / 100)  # Max уменьшается к нулю
            row['Max'] = np.round(max_val, 3)

        if pd.notna(min_val):
            if use_units:
                min_val += units
            elif use_percent:
                # Сжимаем |Min| к нулю:
                #   для отрицательного  (−50)  → −47.5
                #   для положительного  (+5)   → +5.25
                min_val += abs(min_val) * percent / 100
            row['Min'] = np.round(min_val, 3)

        return row

    result_df = merged_df.apply(apply_tolerance, axis=1)

    result_df = result_df[['Parameter', 'Max', 'Min', 'Code']]
    print('Спецификация ОТК на изделие')
    print(tabulate(
        result_df,
        headers='keys',
        tablefmt='grid',
        showindex=False,
        missingval='—'
    ))
    return result_df


# загружает MAP для таблицы спецификаций
# Параметры фазовых шумов (Shum…Shum4). Есть в spc_map_table для
# спецификаций/отчётов, но не измеряются в Temperature_Measure и
# отсутствуют в psidata_map_table — при разбраковке их нужно игнорировать.
PHASE_NOISE_PARAMS = {
    'Shum', 'Shum1', 'Shum2', 'Shum3', 'Shum4',
}


def load_spc_map(row):
    """Загружает активные параметры спецификации из spc_map_table.

    Параметры фазовых шумов (Shum…Shum4) исключаются: они не участвуют
    в обработке Temperature_Measure и не маппятся в psidata.
    Доступ к колонкам Use/Max/Min — безопасный (нет KeyError, если
    колонки ещё нет в specification).
    """
    engine = create_engine(str(get_connection_string()))

    sql = "Select * from `spc_map_table` order by `ID`"
    spc_map = pd.read_sql(sql, engine)

    def _is_enabled(x):
        use_col = x.get('Use')
        if not use_col or use_col not in row.index:
            return False
        try:
            return row[use_col] == 1
        except Exception:
            return False

    filtered_spc = spc_map[spc_map.apply(_is_enabled, axis=1)].copy()

    # Не использовать фазовые шумы в модуле температурных измерений
    before = len(filtered_spc)
    filtered_spc = filtered_spc[
        ~filtered_spc['Parameter_Name'].isin(PHASE_NOISE_PARAMS)
        & ~filtered_spc['Parameter_Name'].astype(str).str.startswith('Shum')
    ]
    excluded = before - len(filtered_spc)
    if excluded:
        print(f'Исключены параметры фазовых шумов (Shum*) из разбраковки ТИ: {excluded}')

    def _bound(col_name):
        if not col_name or col_name not in row.index:
            return None
        v = row[col_name]
        if v is None or v == 'no':
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    if filtered_spc.empty:
        result_df = pd.DataFrame(columns=['Parameter', 'Max', 'Min', 'Code'])
    else:
        result_df = filtered_spc.apply(
            lambda spc_row: pd.Series({
                'Parameter': spc_row['Parameter_Name'],
                'Max': _bound(spc_row['Max']),
                'Min': _bound(spc_row['Min']),
                'Code': str(int(spc_row['Code'])) if pd.notna(spc_row['Code']) else '',
            }),
            axis=1
        )

    print('Спецификация ПСИ на изделие')
    print(tabulate(
        result_df,
        headers='keys',
        tablefmt='grid',
        showindex=False,
        missingval='—'
    ))
    return result_df


def get_available_parameters(spc_data, data_columns):
    spc_params = spc_data.set_index('Parameter')
    available_params = spc_params.index.intersection(data_columns).tolist()
    missing_params = spc_params.index.difference(data_columns).tolist()

    if missing_params:
        print(f"ВНИМАНИЕ: Не найдены данные для параметров: {missing_params}")

    if not available_params:
        raise ValueError("Ни один параметр из spc_data не найден в data.columns")

    return spc_params.loc[available_params]


def process_min_max(spc_params):
    spc_params['Min'] = pd.to_numeric(spc_params['Min'], errors='coerce')
    spc_params['Max'] = pd.to_numeric(spc_params['Max'], errors='coerce')
    spc_params['Code'] = spc_params['Code'].astype('Int64')
    spc_params['Min'] = spc_params['Min'].fillna(-np.inf).astype(float)
    spc_params['Max'] = spc_params['Max'].fillna(np.inf).astype(float)
    return spc_params


def create_validity_mask(data, spc_params, params):
    mask = data[params].ge(spc_params['Min'], axis=1) & data[params].le(spc_params['Max'], axis=1)
    return mask


def generate_error_codes(error_mask, code_values):
    error_mask = error_mask.astype(int)
    error_codes = error_mask.mul(code_values, axis=1).replace(0, np.nan)
    return error_codes.apply(
        lambda row: list(set(row.dropna().astype(int))),
        axis=1
    )


def calculate_anomalies(data, params, use=True):
    anomaly_masks = {}
    print(data.columns)
    print(data[['Numbers', 'Fs', 'R', 'C0']])
    print(use)
    for param in params:
        mean_val = data[param].mean()
        std_val = data[param].std()
        max_val = data[param].max()
        min_val = data[param].min()
        if use:
            lower = mean_val - 5 * std_val
            upper = mean_val + 5 * std_val
        else:
            lower = min_val - 30 * std_val
            upper = max_val + 30 * std_val

        anomaly_mask = (
                (data[param] < lower) |
                (data[param] > upper) |
                data[param].isna()
        )
        if param in ['R', 'C0']:
            anomaly_mask = anomaly_mask | (data[param] == 0)

        anomaly_masks[param] = anomaly_mask
    print(pd.DataFrame(anomaly_masks))
    return pd.DataFrame(anomaly_masks)


def prepare_result_df(data, mask, anomaly_masks, error_mask, code_values, params):
    result_df = data.copy()

    status_columns = [f"{col}_status" for col in params]
    result_df[status_columns] = mask.astype(bool)

    anomal_columns = [f"{col}_anomal_status" for col in params]
    result_df[anomal_columns] = anomaly_masks.astype(bool)

    result_df['Status'] = (~error_mask).all(axis=1)
    result_df['Anomal_Status'] = anomaly_masks.any(axis=1)

    error_codes = generate_error_codes(error_mask, code_values)
    result_df['Error_Code'] = error_codes

    keep_columns = (
            ['SETUPNUM', 'Positions', 'Position_index', 'Numbers',
             'Status', 'Error_Code', 'Anomal_Status']
            + status_columns
            + anomal_columns
    )

    return result_df[keep_columns]


def prepare_result_df2(data, params):
    selected_columns = ['SETUPNUM', 'Positions', 'Position_index', 'Numbers'] + params
    return data[selected_columns].copy()


def prepare_anomal_df(data, anomaly_masks, params):
    anomaly_df = data.copy()
    for param in params:
        col_name = f"{param}_anomal_status"
        anomaly_df[col_name] = anomaly_masks[param]
    anomaly_df['Anomal_Status'] = anomaly_df[[col for col in anomaly_df if '_anomal_status' in col]].any(axis=1)
    selected_cols = ['SETUPNUM', 'Positions', 'Position_index', 'Numbers'] + params + list(anomaly_masks.columns) + [
        'Anomal_Status']
    return anomaly_df[selected_cols]


def calculate_statistics(data, result_df, spc_params, params):
    stats = []

    numeric_cols = data.columns.difference(
        ['Positions', 'Numbers', 'SETUPNUM', 'Position_index', 'Temp_status', 'KO_F', 'KO_S_Numbers', 'Status2'])
    print('calculate_statistics')
    print(data.columns)
    print(numeric_cols)
    debug_file = 'debug_data_before_mask.csv'
    data[numeric_cols].to_csv(debug_file, index=True)
    print(f"[DEBUG] Данные (до замены >=10000 на NaN) сохранены в {debug_file}")
    data[numeric_cols] = data[numeric_cols].apply(pd.to_numeric, errors='coerce')
    data[numeric_cols] = data[numeric_cols].mask(abs(data[numeric_cols]) >= 10000, np.nan)

    for param in params:
        status_col = f'{param}_status'

        if status_col not in result_df.columns:
            raise ValueError(f"Статусный столбец '{status_col}' не найден в result_df")

        valid_mask = result_df[status_col] == True

        param_values = data[param]
        valid_values = param_values[valid_mask]

        defect_count = len(param_values) - len(valid_values)
        valid_count = len(valid_values)

        max_val = valid_values.max() if not valid_values.empty else np.nan
        min_val = valid_values.min() if not valid_values.empty else np.nan
        avg_val = valid_values.mean() if not valid_values.empty else np.nan
        std_val = valid_values.std() if not valid_values.empty else np.nan

        stats.append({
            'Parameter': param,
            'Брак': defect_count,
            'Годные': valid_count,
            'Макс': max_val,
            'Мин': min_val,
            'Среднее': avg_val,
            'СтОткл': std_val
        })

    return pd.DataFrame(stats)


def add_total_status(stats_df, total_valid, total_defect):
    total_row = {
        'Parameter': 'Общий статус',
        'Брак': total_defect,
        'Годные': total_valid,
        'Макс': np.nan,
        'Мин': np.nan,
        'Среднее': np.nan,
        'СтОткл': np.nan
    }
    return pd.concat([stats_df, pd.DataFrame([total_row])], ignore_index=True)


def print_results(result_df, result_df2, stats_df, result_anomal):
    print("\nДатафрейм с параметрами:")
    print(tabulate(result_df2, headers='keys', tablefmt='grid', showindex=False, missingval='—'))

    print("\nСтатистика по параметрам:")
    print(tabulate(
        stats_df,
        headers='keys',
        tablefmt='grid',
        showindex=False,
        missingval='—',
        floatfmt=('.0f', '.0f', '.1f', '.1f', '.1f', '.2f')
    ))


def set_specification_to_data(spc_data, data, anomal_use=True):
    spc_params = get_available_parameters(spc_data, data.columns)

    params = spc_params.index.tolist()
    spc_params = process_min_max(spc_params)
    mask = create_validity_mask(data, spc_params, params)

    modify_rsp_mask_based_on_spfr(mask, data, spc_params, params)

    mask = exclude_spfr_from_rejection(mask, params)

    anomaly_masks = calculate_anomalies(data, params, use=anomal_use)
    error_mask = (~mask) | anomaly_masks
    code_values = spc_params['Code'].reindex(params).astype(int)
    result_df = prepare_result_df(
        data=data,
        mask=mask,
        anomaly_masks=anomaly_masks,
        error_mask=error_mask,
        code_values=code_values,
        params=params
    )

    result_df2 = prepare_result_df2(data, params)
    result_df2['Anomal_Status'] = result_df['Anomal_Status']

    result_anomal = prepare_anomal_df(data, anomaly_masks, params)

    result_df = add_anomal_to_status(result_df)
    valid_data = data[result_df['Anomal_Status'] == False]
    valid_norm_data = valid_data[result_df['Status']]
    stats_df = calculate_statistics(data, result_df, spc_params, params)
    total_valid = len(valid_norm_data)
    total_defect = len(data) - total_valid
    stats_df = add_total_status(stats_df, total_valid, total_defect)
    result_df2 = clear_anomal_data(result_df2, stats_df)

    result_df, result_df2 = update_statuses_based_on_nan(result_df, result_df2, params)

    print_results(result_df, result_df2, stats_df, result_anomal)
    return result_df, result_df2, stats_df, result_anomal


def modify_rsp_mask_based_on_spfr(mask, data, spc_params, params):
    rsp_params = [p for p in params if p.startswith('Rsp')]

    for rsp_param in rsp_params:
        rsp_index = rsp_param[3:]
        spfr_param = f"SPFR_{rsp_index}"

        if spfr_param in params:
            print(f"Применение специальной логики для {rsp_param} на основе {spfr_param}")
            spfr_in_spec = mask[spfr_param]
            mask[rsp_param] = (~spfr_in_spec) | mask[rsp_param]
        else:
            print(f"SPFR параметр {spfr_param} не найден, применяется стандартная проверка для {rsp_param}")


def exclude_spfr_from_rejection(mask, params):
    spfr_params = [p for p in params if p.startswith('SPFR_')]
    for spfr_param in spfr_params:
        mask[spfr_param] = True
        print(f"Параметр {spfr_param} исключен из браковки изделия")
    return mask


def update_statuses_based_on_nan(result_df, data_df, param_columns):
    result_df = result_df.copy()
    data_df = data_df.copy()
    nan_mask = data_df[param_columns].isna().any(axis=1)

    data_df.loc[nan_mask, 'Anomal_Status'] = True

    keys = ['SETUPNUM', 'Positions', 'Position_index', 'Numbers']
    result_df['temp_key'] = result_df[keys].apply(tuple, axis=1)
    data_df['temp_key'] = data_df[keys].apply(tuple, axis=1)

    nan_keys = set(data_df.loc[nan_mask, 'temp_key'])

    result_nan_mask = result_df['temp_key'].isin(nan_keys)

    result_df.loc[result_nan_mask, 'Status'] = False
    result_df.loc[result_nan_mask, 'Status2'] = 'Bad'
    result_df.loc[result_nan_mask, 'Anomal_Status'] = True

    for param in param_columns:
        param_nan_mask = data_df[param].isna()
        param_nan_keys = set(data_df.loc[param_nan_mask, 'temp_key'])

        param_result_mask = result_df['temp_key'].isin(param_nan_keys)

        result_df.loc[param_result_mask, f'{param}_status'] = False
        result_df.loc[param_result_mask, f'{param}_anomal_status'] = True

    result_df.drop(columns=['temp_key'], inplace=True)
    data_df.drop(columns=['temp_key'], inplace=True)

    return result_df, data_df


def add_anomal_to_status(df):
    ignored_columns = {
        'SETUPNUM', 'Positions', 'Position_index',
        'Numbers', 'Status', 'Error_Code', 'Anomal_Status'
    }

    status_columns = [
        col for col in df.columns
        if (
                col.endswith('_status')
                and not col.endswith('_anomal_status')
                and col not in ignored_columns
        )
    ]
    df['Status2'] = 'Good'
    for status_col in status_columns:
        anomal_col = status_col.replace('_status', '_anomal_status')

        if anomal_col in df.columns:
            df.loc[df[anomal_col], status_col] = False
            df.loc[df[anomal_col], 'Status2'] = 'Bad'
    return df


def clear_anomal_data(data_df, stats_df):
    serve_columns = ['Numbers', 'Positions', 'Status', 'Status2']

    thresholds = {}
    for _, row in stats_df.iterrows():
        param = row['Parameter']
        mean = row['Среднее']
        std = row['СтОткл']
        lower = mean - 40 * std
        upper = mean + 40 * std
        thresholds[param] = (lower, upper)
    for col in data_df.columns:
        if col in thresholds:
            lower, upper = thresholds[col]
            mask = (data_df[col] < lower) | (data_df[col] > upper)
            data_df.loc[mask, col] = np.nan
    return data_df


# Функция собирает базовые температуры со спецификации
def get_spc_base_temps(spc):
    base_params = {
        't_nastr': 'Tnastr',
        'polinom_n': 'polinom',
        'load_type': 'LoadType',
        'fl_num': 'FL_Num',
        't_nakl': 'Tnakl',
        'temp_tch_a': 'TCH_Temp_A',
        'temp_tch_b': 'TCH_Temp_B'
    }

    base_dict = {key: spc[value] for key, value in base_params.items()}

    ft_fields = [
        ('FTx', 'FTxt', 'FTt'),
        ('Ft1', 'Ft1t', 'FT1t'),
        ('Ft2', 'Ft2t', 'FT2t'),
        ('Ft3', 'Ft3t', 'FT3t'),
        ('Ft4', 'Ft4t', 'FT4t')
    ]

    ft_dict = {}
    for condition_key, temp_key, result_key in ft_fields:
        if spc[condition_key] == 1:
            ft_dict[result_key] = spc[temp_key]
        else:
            ft_dict[result_key] = base_dict['t_nastr']

    result = {**base_dict, **ft_dict}
    return result


def check_and_add_columns(df, columns=None, fill_value=pd.NA, verbose=True):
    if columns is None:
        columns = ['Ft', 'Ft1', 'Ft2', 'Ft3', 'Ft4']

    result_df = df.copy()

    added_columns = []
    for col in columns:
        if col not in result_df.columns:
            result_df[col] = fill_value
            added_columns.append(col)

    if verbose and added_columns:
        print(f"Добавлены колонки: {', '.join(added_columns)}")

    return result_df


# Обработка данных
def process_measure(slot):
    measure_slot_index = 0
    data = new_data_compile()
    machine_type_str = MEASURE_DATA.get_data_inf('Machine_Type_ID')
    data = filtr_by_slot(slot, data)
    print('data filtr', len(data))
    if machine_type_str == 1:
        data = convert_freq_w2200(data, slot)

    # --- Определение режима «одна точка» на уровне файла ---
    if 'Temps' in data.columns:
        measured_temps_all = pd.Series(data['Temps']).dropna().unique()
        single_point = len(measured_temps_all) < 2
    else:
        measured_temps_all = []
        single_point = False

    if single_point:
        print(f"РЕЖИМ ОДНОЙ ТОЧКИ: T={list(measured_temps_all)}. "
              f"Температурные параметры спецификации не рассчитываются.")

    # загружаем полные данные спецификации
    spc_data_df = load_spc_data(slot)
    anomal_use = spc_data_df['Anomal'].iloc[0]

    data_temp = pd.DataFrame()
    print("Spc_data", spc_data_df)
    for index, row in spc_data_df.iterrows():
        temp_list_db = load_profile_data(row)

        if row['Multy'] == 1:
            file_configure_data = MEASURE_DATA.get_setupnum_data(slot)
            row['Nominal'] = file_configure_data['Номинал'] / 1E6
        print('температурный профиль', temp_list_db)

        data_temp = data[data['Temps'].isin(temp_list_db)].copy()

        # --- Дедупликация дублей (Positions, Temps) ---
        # На Saunders/ТЧХ и др. после merge Crystal Data + Setup Data
        # может приходить по несколько записей на одну (позицию, температуру).
        # Агрегируем: числовые — среднее, служебные/строковые — first.
        if not data_temp.empty:
            n_before = len(data_temp)
            n_unique = data_temp.drop_duplicates(
                subset=['Positions', 'Temps']
            ).shape[0]
            if n_before > n_unique:
                print(f"Обнаружено дублей (Positions, Temps): "
                      f"{n_before - n_unique} из {n_before} — агрегируем по среднему.")
                group_cols = ['Positions', 'Temps']
                agg_dict = {}
                for col in data_temp.columns:
                    if col in group_cols:
                        continue
                    if col in ('SETUPNUM', 'Position_index'):
                        agg_dict[col] = 'first'
                    elif pd.api.types.is_numeric_dtype(data_temp[col]):
                        agg_dict[col] = 'mean'
                    else:
                        agg_dict[col] = 'first'
                data_temp = data_temp.groupby(
                    group_cols, as_index=False, dropna=False
                ).agg(agg_dict)
                print(f"После агрегации: {len(data_temp)} строк "
                      f"(позиций: {data_temp['Positions'].nunique()}).")

        if data_temp.empty:
            print(f"ВНИМАНИЕ: нет данных для профиля {temp_list_db}")
            continue

        temps_dict = get_spc_base_temps(spc=row)

        if (temps_dict['temp_tch_a'] is None
                or temps_dict['temp_tch_b'] is None
                or temps_dict['temp_tch_a'] >= temps_dict['temp_tch_b']):
            t_lo, t_hi = min(temp_list_db), max(temp_list_db)
            print(
                f"ВНИМАНИЕ: TCH_Temp_A={temps_dict['temp_tch_a']!r}, "
                f"TCH_Temp_B={temps_dict['temp_tch_b']!r} — интервал ТЧХ "
                f"некорректен, используется полный профиль {t_lo}...{t_hi}"
            )
            temps_dict['temp_tch_a'] = t_lo
            temps_dict['temp_tch_b'] = t_hi

        data_temp = convert_units_(data_temp, row)
        data_temp = add_f_25(data_temp, temps_dict['polinom_n'],
                             temps_dict['t_nastr'], temps_dict['load_type'])

        amp_flags = [
            int(row.get('Spur_F_1_AMP_Unit', 0) or 0),
            int(row.get('Spur_F_2_AMP_Unit', 0) or 0),
            int(row.get('Spur_F_3_AMP_Unit', 0) or 0),
        ]
        print('AMP Flags', amp_flags)
        data_temp = add_spur(data_temp, amp_flags=amp_flags)
        data_temp = add_temp_status(data_temp)

        # === Одна точка: не применяем коррекции и интерполяцию ===
        if single_point:
            data_temp = data_temp.copy()
            data_temp['f_interp'] = data_temp['F_']
            data_temp['delta_f'] = 0.0
            data_temp['KO'] = 0
        elif len(MEASURE_DATA.get_control_data_T()) > 0 and row['TCH_correction']:
            print('Расчет ТЧХ с коррекцией температурных точек тип Т')
            temp_correction, numbers = find_temperature_correction(temps_dict['t_nastr'])
            data_temp = data_temp.groupby('Positions', group_keys=False).apply(
                lambda g: interpolate_group_REF(g, temps_dict['polinom_n'], temp_correction)
            )
            data_temp['KO'] = 1
            data_temp['KO_S_Numbers'] = " ".join(map(str, numbers))
            if row['F_correction']:
                data_temp = calculate_temperature_correction(data_temp, temp_correction).copy()

        elif len(MEASURE_DATA.get_control_data_RK()) > 0 and row['TCH_correction']:
            print('Расчет ТЧХ с коррекцией температурных точек тип RK')
            temp_correction, numbers = find_temperature_correction_network(temps_dict['t_nastr'])
            data_temp = data_temp.groupby('Positions', group_keys=False).apply(
                lambda g: interpolate_group_REF(g, temps_dict['polinom_n'], temp_correction)
            )
            data_temp['KO'] = 1
            data_temp['KO_S_Numbers'] = " ".join(map(str, numbers))
        else:
            data_temp = data_temp.groupby('Positions', group_keys=False).apply(
                lambda g: interpolate_group(g, temps_dict['polinom_n'])
            )
            data_temp['KO'] = 0

        result_df = data_temp[data_temp['Temps'] == temps_dict['t_nastr']].copy()
        result_df, data_temp = add_numbers(result_df, data_temp, slot)

        if temps_dict['t_nakl'] == 0:
            temps_dict['t_nakl'] = temps_dict['t_nastr']

        metrics_df = data_temp.groupby('Positions').apply(
            lambda g: calculate_metrics(g, temps_dict['polinom_n'], temps_dict['temp_tch_a'],
                                        temps_dict['temp_tch_b'], temps_dict['t_nakl'])
        ).reset_index()
        result_df = result_df.merge(metrics_df, on='Positions', how='left')

        data_test = add_ft_to_data(data_temp,
                                   t1=temps_dict['FT1t'],
                                   t2=temps_dict['FT2t'],
                                   t3=temps_dict['FT3t'],
                                   t4=temps_dict['FT4t'],
                                   t=temps_dict['FTt'])
        if data_test is not None and not data_test.empty:
            result_df = result_df.merge(data_test, on='Positions', how='left')

        if not single_point and len(MEASURE_DATA.get_control_data_RK()) > 0 and row['F_correction']:
            result_df, numbers = calculate_corrections(result_df)
            if 'KO_S_Numbers' not in result_df.columns:
                result_df['KO_S_Numbers'] = " ".join(map(str, numbers))
            result_df['KO_F'] = 1
        elif not single_point and len(MEASURE_DATA.get_control_data_T()) > 0 and row['F_correction']:
            result_df['KO_F'] = 1
        else:
            result_df['KO_F'] = 0


        # Коррекция R и Q по контрольным образцам типа RK
        if not single_point and len(MEASURE_DATA.get_control_data_RK()) > 0:
            do_r = _spc_flag(row, 'R_correction')
            do_q = _spc_flag(row, 'Q_correction')
            if do_r or do_q:
                print(f'Коррекция R/Q по контрольным RK: R={do_r}, Q={do_q}')
                result_df, _ = calculate_rq_corrections(result_df, correct_r=do_r, correct_q=do_q)
        result_df = add_additional_columns(result_df, temps_dict['load_type'], temps_dict['fl_num'],
                                           row['F_correction'], row['TCH_Approx_Type'])
        result_df = check_and_add_columns(result_df, fill_value=0)

        print_result_to_console(result_df, temps_dict)

        # загружаем спецификацию для разбраковки
        map_spc = load_spc_map(row)

        # === В режиме одной точки исключаем температурные параметры из проверки ===
        if single_point:
            map_spc_check = map_spc[~map_spc['Parameter'].isin(TEMP_DEPENDENT_PARAMS)].copy()
            excluded = sorted(set(map_spc['Parameter']) & TEMP_DEPENDENT_PARAMS)
            if excluded:
                print(f"Исключены из проверки ПСИ (одна точка): {excluded}")
        else:
            map_spc_check = map_spc

        # Производим разбраковку изделий ПСИ
        psi_data_df_status, psi_data_df, psi_stat_df, psi_stat_df_anomal = set_specification_to_data(
            map_spc_check, result_df, anomal_use)
        print(data_temp.columns)

        # Добавляем допуски к спецификации если они есть
        map_spc_otk = create_spc_map_otk(map_spc, row)

        if single_point:
            map_spc_otk_check = map_spc_otk[
                ~map_spc_otk['Parameter'].isin(TEMP_DEPENDENT_PARAMS)
            ].copy()
        else:
            map_spc_otk_check = map_spc_otk

        # Проверяем наличие тех запасов
        otk_use = compare_dataframes(map_spc_check, map_spc_otk_check)
        if not otk_use:
            otk_data_df_status, otk_data_df, otk_stat_df, otk_stat_df_anomal = set_specification_to_data(
                map_spc_otk_check, result_df, anomal_use)
        else:
            otk_data_df_status = pd.DataFrame()
            otk_data_df = pd.DataFrame()
            otk_stat_df = pd.DataFrame()

        # Получаем текущее количество сохранённых слотов измерений
        measure_slot_index = len(MEASURE_DATA.measure_data)
        measure_inf = {'Slot': measure_slot_index + 1,
                       'File_Slot': slot,
                       'Spc': row,
                       'Profile': temp_list_db,
                       'Data_Temp': data_temp,
                       'Result': result_df,
                       'Psi_Data': psi_data_df,
                       'Psi_Data_Status': psi_data_df_status,
                       'Psi_Stat': psi_stat_df,
                       'OTK_Data': otk_data_df,
                       'OTK_Data_Status': otk_data_df_status,
                       'OTK_Stat': otk_stat_df,
                       'Spc_Map': map_spc_check,
                       'Spc_Map_OTK': map_spc_otk_check
                       }

        MEASURE_DATA.measure_data[str(measure_slot_index + 1)] = measure_inf

        msk = MEASURE_DATA.get_msk(slot)
        if msk == 'K.O.' and not single_point:
            MEASURE_DATA.set_control_data(slot, value=measure_inf)
            if len(MEASURE_DATA.get_control_data_T()) > 0:
                print('Таблица коррекции температуры (датчик тип Т)')
                temp_correction, numbers = find_temperature_correction(temps_dict['t_nastr'])

            elif len(MEASURE_DATA.get_control_data_RK()) > 0:
                print('Таблица коррекции температуры (датчик тип RK)')
                temp_correction, numbers = find_temperature_correction_network(temps_dict['t_nastr'])
                result_df, numbers = calculate_corrections(result_df)
                # Коррекция R и Q по контрольным образцам типа RK
                if len(MEASURE_DATA.get_control_data_RK()) > 0:
                    do_r = _spc_flag(row, 'R_correction')
                    do_q = _spc_flag(row, 'Q_correction')
                    if do_r or do_q:
                        print(f'Коррекция R/Q по контрольным RK (K.O.): R={do_r}, Q={do_q}')
                        result_df, _ = calculate_rq_corrections(result_df, correct_r=do_r, correct_q=do_q)


    return measure_slot_index + 1

def process_measure_1(slot):
    measure_slot_index = 0
    data = new_data_compile()
    machine_type_str = MEASURE_DATA.get_data_inf('Machine_Type_ID')
    data = filtr_by_slot(slot, data)
    print('data filtr', len(data))
    if machine_type_str == 1:
        data = convert_freq_w2200(data, slot)

    # --- Определение режима «одна точка» на уровне файла ---
    if 'Temps' in data.columns:
        measured_temps_all = pd.Series(data['Temps']).dropna().unique()
        single_point = len(measured_temps_all) < 2
    else:
        measured_temps_all = []
        single_point = False

    if single_point:
        print(f"РЕЖИМ ОДНОЙ ТОЧКИ: T={list(measured_temps_all)}. "
              f"Температурные параметры спецификации не рассчитываются.")

    # загружаем полные данные спецификации
    spc_data_df = load_spc_data(slot)
    anomal_use = spc_data_df['Anomal'].iloc[0]

    data_temp = pd.DataFrame()
    print("Spc_data", spc_data_df)
    for index, row in spc_data_df.iterrows():
        temp_list_db = load_profile_data(row)

        if row['Multy'] == 1:
            file_configure_data = MEASURE_DATA.get_setupnum_data(slot)
            row['Nominal'] = file_configure_data['Номинал'] / 1E6
        print('температурный профиль', temp_list_db)

        data_temp = data[data['Temps'].isin(temp_list_db)].copy()
        if data_temp.empty:
            print(f"ВНИМАНИЕ: нет данных для профиля {temp_list_db}")
            continue

        temps_dict = get_spc_base_temps(spc=row)

        if (temps_dict['temp_tch_a'] is None
                or temps_dict['temp_tch_b'] is None
                or temps_dict['temp_tch_a'] >= temps_dict['temp_tch_b']):
            t_lo, t_hi = min(temp_list_db), max(temp_list_db)
            print(
                f"ВНИМАНИЕ: TCH_Temp_A={temps_dict['temp_tch_a']!r}, "
                f"TCH_Temp_B={temps_dict['temp_tch_b']!r} — интервал ТЧХ "
                f"некорректен, используется полный профиль {t_lo}...{t_hi}"
            )
            temps_dict['temp_tch_a'] = t_lo
            temps_dict['temp_tch_b'] = t_hi

        data_temp = convert_units_(data_temp, row)
        data_temp = add_f_25(data_temp, temps_dict['polinom_n'], temps_dict['t_nastr'], temps_dict['load_type'])

        amp_flags = [
            int(row.get('Spur_F_1_AMP_Unit', 0) or 0),
            int(row.get('Spur_F_2_AMP_Unit', 0) or 0),
            int(row.get('Spur_F_3_AMP_Unit', 0) or 0),
        ]
        print('AMP Flags', amp_flags)
        data_temp = add_spur(data_temp, amp_flags=amp_flags)
        data_temp = add_temp_status(data_temp)

        # === Одна точка: не применяем коррекции и интерполяцию ===
        if single_point:
            data_temp = data_temp.copy()
            data_temp['f_interp'] = data_temp['F_']
            data_temp['delta_f'] = 0.0
            data_temp['KO'] = 0
        elif len(MEASURE_DATA.get_control_data_T()) > 0 and row['TCH_correction']:
            print('Расчет ТЧХ с коррекцией температурных точек тип Т')
            temp_correction, numbers = find_temperature_correction(temps_dict['t_nastr'])
            data_temp = data_temp.groupby('Positions', group_keys=False).apply(
                lambda g: interpolate_group_REF(g, temps_dict['polinom_n'], temp_correction)
            )
            data_temp['KO'] = 1
            data_temp['KO_S_Numbers'] = " ".join(map(str, numbers))
            if row['F_correction']:
                data_temp = calculate_temperature_correction(data_temp, temp_correction).copy()

        elif len(MEASURE_DATA.get_control_data_RK()) > 0 and row['TCH_correction']:
            print('Расчет ТЧХ с коррекцией температурных точек тип RK')
            temp_correction, numbers = find_temperature_correction_network(temps_dict['t_nastr'])
            data_temp = data_temp.groupby('Positions', group_keys=False).apply(
                lambda g: interpolate_group_REF(g, temps_dict['polinom_n'], temp_correction)
            )
            data_temp['KO'] = 1
            data_temp['KO_S_Numbers'] = " ".join(map(str, numbers))
        else:
            data_temp = data_temp.groupby('Positions', group_keys=False).apply(
                lambda g: interpolate_group(g, temps_dict['polinom_n'])
            )
            data_temp['KO'] = 0

        result_df = data_temp[data_temp['Temps'] == temps_dict['t_nastr']].copy()
        result_df, data_temp = add_numbers(result_df, data_temp, slot)

        if temps_dict['t_nakl'] == 0:
            temps_dict['t_nakl'] = temps_dict['t_nastr']

        metrics_df = data_temp.groupby('Positions').apply(
            lambda g: calculate_metrics(g, temps_dict['polinom_n'], temps_dict['temp_tch_a'],
                                        temps_dict['temp_tch_b'], temps_dict['t_nakl'])
        ).reset_index()
        result_df = result_df.merge(metrics_df, on='Positions', how='left')

        data_test = add_ft_to_data(data_temp,
                                   t1=temps_dict['FT1t'],
                                   t2=temps_dict['FT2t'],
                                   t3=temps_dict['FT3t'],
                                   t4=temps_dict['FT4t'],
                                   t=temps_dict['FTt'])
        if data_test is not None and not data_test.empty:
            result_df = result_df.merge(data_test, on='Positions', how='left')

        if not single_point and len(MEASURE_DATA.get_control_data_RK()) > 0 and row['F_correction']:
            result_df, numbers = calculate_corrections(result_df)
            if 'KO_S_Numbers' not in result_df.columns:
                result_df['KO_S_Numbers'] = " ".join(map(str, numbers))
            result_df['KO_F'] = 1
        elif not single_point and len(MEASURE_DATA.get_control_data_T()) > 0 and row['F_correction']:
            result_df['KO_F'] = 1
        else:
            result_df['KO_F'] = 0


        # Коррекция R и Q по контрольным образцам типа RK
        if not single_point and len(MEASURE_DATA.get_control_data_RK()) > 0:
            do_r = _spc_flag(row, 'R_correction')
            do_q = _spc_flag(row, 'Q_correction')
            if do_r or do_q:
                print(f'Коррекция R/Q по контрольным RK: R={do_r}, Q={do_q}')
                result_df, _ = calculate_rq_corrections(result_df, correct_r=do_r, correct_q=do_q)
        result_df = add_additional_columns(result_df, temps_dict['load_type'], temps_dict['fl_num'],
                                           row['F_correction'], row['TCH_Approx_Type'])
        result_df = check_and_add_columns(result_df, fill_value=0)

        print_result_to_console(result_df, temps_dict)

        # загружаем спецификацию для разбраковки
        map_spc = load_spc_map(row)

        # === В режиме одной точки исключаем температурные параметры из проверки ===
        if single_point:
            map_spc_check = map_spc[~map_spc['Parameter'].isin(TEMP_DEPENDENT_PARAMS)].copy()
            excluded = sorted(set(map_spc['Parameter']) & TEMP_DEPENDENT_PARAMS)
            if excluded:
                print(f"Исключены из проверки ПСИ (одна точка): {excluded}")
        else:
            map_spc_check = map_spc

        # Производим разбраковку изделий ПСИ
        psi_data_df_status, psi_data_df, psi_stat_df, psi_stat_df_anomal = set_specification_to_data(
            map_spc_check, result_df, anomal_use)
        print(data_temp.columns)

        # Добавляем допуски к спецификации если они есть
        map_spc_otk = create_spc_map_otk(map_spc, row)

        if single_point:
            map_spc_otk_check = map_spc_otk[
                ~map_spc_otk['Parameter'].isin(TEMP_DEPENDENT_PARAMS)
            ].copy()
        else:
            map_spc_otk_check = map_spc_otk

        # Проверяем наличие тех запасов
        otk_use = compare_dataframes(map_spc_check, map_spc_otk_check)
        if not otk_use:
            otk_data_df_status, otk_data_df, otk_stat_df, otk_stat_df_anomal = set_specification_to_data(
                map_spc_otk_check, result_df, anomal_use)
        else:
            otk_data_df_status = pd.DataFrame()
            otk_data_df = pd.DataFrame()
            otk_stat_df = pd.DataFrame()

        # Получаем текущее количество сохранённых слотов измерений
        measure_slot_index = len(MEASURE_DATA.measure_data)
        measure_inf = {'Slot': measure_slot_index + 1,
                       'File_Slot': slot,
                       'Spc': row,
                       'Profile': temp_list_db,
                       'Data_Temp': data_temp,
                       'Result': result_df,
                       'Psi_Data': psi_data_df,
                       'Psi_Data_Status': psi_data_df_status,
                       'Psi_Stat': psi_stat_df,
                       'OTK_Data': otk_data_df,
                       'OTK_Data_Status': otk_data_df_status,
                       'OTK_Stat': otk_stat_df,
                       'Spc_Map': map_spc_check,
                       'Spc_Map_OTK': map_spc_otk_check
                       }

        MEASURE_DATA.measure_data[str(measure_slot_index + 1)] = measure_inf

        msk = MEASURE_DATA.get_msk(slot)
        if msk == 'K.O.' and not single_point:
            MEASURE_DATA.set_control_data(slot, value=measure_inf)
            if len(MEASURE_DATA.get_control_data_T()) > 0:
                print('Таблица коррекции температуры (датчик тип Т)')
                temp_correction, numbers = find_temperature_correction(temps_dict['t_nastr'])

            elif len(MEASURE_DATA.get_control_data_RK()) > 0:
                print('Таблица коррекции температуры (датчик тип RK)')
                temp_correction, numbers = find_temperature_correction_network(temps_dict['t_nastr'])
                result_df, numbers = calculate_corrections(result_df)
                # Коррекция R и Q по контрольным образцам типа RK
                if len(MEASURE_DATA.get_control_data_RK()) > 0:
                    do_r = _spc_flag(row, 'R_correction')
                    do_q = _spc_flag(row, 'Q_correction')
                    if do_r or do_q:
                        print(f'Коррекция R/Q по контрольным RK (K.O.): R={do_r}, Q={do_q}')
                        result_df, _ = calculate_rq_corrections(result_df, correct_r=do_r, correct_q=do_q)


    return measure_slot_index + 1


def print_result_to_console(result_df: pd.DataFrame, temps_dict):
    print('Динамические параметры на температуре настройки T = ', temps_dict['t_nastr'])
    table = tabulate(
        result_df[['Positions', 'Numbers', 'Fs_ppm', 'Fl_ppm', 'FL_Num', 'C0', 'C1', 'L', 'R',
                   'Q', 'F', 'F_corr']],
        headers='keys', tablefmt='grid', showindex=False)
    print(table)
    print(f"Частота в интервале температур {temps_dict['temp_tch_a']}...{temps_dict['temp_tch_b']}")
    table = tabulate(
        result_df[['Positions', 'Numbers', 'Fmin', 'Fmax', 'F_min_int', 'F_max_int', 'Fptp', 'Fptp/2',
                   'f_center', 'ABS(Fmax, Fmin)', 'Ft', 'Ft1', 'Ft2', 'Ft3', 'Ft4']],
        headers='keys', tablefmt='grid', showindex=False)
    print(table)
    print(f"Сопротивление в интервале температур {temps_dict['temp_tch_a']}...{temps_dict['temp_tch_b']}")
    table = tabulate(
        result_df[['Positions', 'Numbers', 'Rmin', 'Rmax', 'Rc_Rbmax', 'Rmax-Rmin', 'Rmax/R_center',
                   'R_center/Rmin', 'Rmax/Rmin', '(Rmax-R25)/R25*100%', '(Rmin-R25)/R25*100%', 'R_center']],
        headers='keys', tablefmt='grid', showindex=False)
    print(table)
    print("Нежелательные резонансы")
    table = tabulate(
        result_df[['Positions', 'Numbers', 'Rb', 'Rc_Rb', 'Spur', 'Rsp0', 'SPUR_0', 'SPFR_0',
                   'Rsp1', 'SPUR_1', 'SPFR_1', 'Rsp2', 'SPUR_2', 'SPFR_2']],
        headers='keys', tablefmt='grid', showindex=False)
    print(table)
    print("Анализ ТЧХ")
    table = tabulate(
        result_df[['Positions', 'Numbers', 'extr_1', 'extr_2', 'TurnOver_1', 'Mono',
                   'MonoT', 'Slope', 'A0', 'A1', 'A2', 'A3', 'A4', 'A5']],
        headers='keys', tablefmt='grid', showindex=False)
    print(table)
    print("Дополнительные данные")
    table = tabulate(
        result_df[['Positions', 'Numbers', 'C0_C1', 'C1_2C0', 'F0-FL']],
        headers='keys', tablefmt='grid', showindex=False)
    print(table)


# Сравнивает две спецификации, если они полностью совпадают выдаёт True/иначе False
def compare_dataframes(df1: pd.DataFrame, df2: pd.DataFrame) -> bool:
    if set(df1['Parameter']) != set(df2['Parameter']):
        return False

    df1_unique = df1.drop_duplicates(subset=['Parameter'])
    df2_unique = df2.drop_duplicates(subset=['Parameter'])

    merged = df1_unique.merge(
        df2_unique,
        on='Parameter',
        suffixes=('_1', '_2')
    )

    max_eq = (merged['Max_1'].isna() & merged['Max_2'].isna()) | (merged['Max_1'] == merged['Max_2'])
    min_eq = (merged['Min_1'].isna() & merged['Min_2'].isna()) | (merged['Min_1'] == merged['Min_2'])

    return (max_eq & min_eq).all()


def add_spur(data: pd.DataFrame, amp_flags=None) -> pd.DataFrame:
    if amp_flags is None:
        amp_flags = [0, 0, 0]

    if 'SPUR_0' in data.columns:
        if 'Rb' not in data.columns:
            data['Rb'] = data['SPUR_0']
            data['Rc_Rb'] = np.where(
                data['Rb'] > 0,
                data['R_center'] / data['Rb'],
                0.0
            )
        else:
            data['Rc_Rb'] = 1 / data['SPUR_0']

        for i in range(3):
            spur_col = f"SPUR_{i}"
            rsp_col = f"Rsp{i}"
            spfr_col = f"SPFR_{i}"

            if spur_col in data.columns:
                data[rsp_col] = 0.0

                valid_mask = (
                        data[spur_col].notna() & (data[spur_col] > 0) &
                        data['R_center'].notna() & (data['R_center'] > 0)
                )

                if amp_flags[i] == 1:
                    r_center = data.loc[valid_mask, 'R_center']
                    spur = data.loc[valid_mask, spur_col]
                    ratio = (r_center / (r_center + 12.5)) / (spur / (spur + 12.5))
                    data.loc[valid_mask, rsp_col] = -20 * np.log10(ratio)
                else:
                    data.loc[valid_mask, rsp_col] = -20 * np.log10(
                        data.loc[valid_mask, 'R_center'] /
                        data.loc[valid_mask, spur_col]
                    )

                invalid_mask = ~valid_mask
                data.loc[invalid_mask, spur_col] = 0.0

                if spfr_col not in data.columns:
                    data[spfr_col] = np.nan
                data.loc[invalid_mask, spfr_col] = 0.0

            else:
                data[spur_col] = 0.0
                data[rsp_col] = 0.0
                data[spfr_col] = 0.0

    else:
        data['SPUR_0'] = 0.0
        data['Rb'] = 0.0
        data['Rc_Rb'] = 0.0
        for i in range(3):
            data[f"SPUR_{i}"] = 0.0
            data[f"Rsp{i}"] = 0.0
            data[f"SPFR_{i}"] = 0.0

    return data


# Конвертирует единицы колонок C0 - пФ, C1 - фФ, Q - x1000, L - mH;
# добавляет колонки Fs_ppm, Fl_ppm, FL_Num
def convert_units_(data: pd.DataFrame, spc_row) -> pd.DataFrame:
    nominal = float(spc_row['Nominal']) * 1e6

    for col in ['Fs', 'Fl']:
        if col in data.columns:
            data[f'{col}_ppm'] = ((data[col] - nominal) / nominal) * 1e6

    load_value = float(spc_row['Loadvalue'])
    if load_value > 0:
        load_value *= 1e-12

    if all(col in data.columns for col in ['Fs', 'C1', 'C0']):
        fl_num = data['Fs'] * np.sqrt(1 + data['C1'] / (data['C0'] + load_value))
        data['FL_Num'] = ((fl_num - nominal) / nominal) * 1e6

    spfr_cols = ['SPFR_0', 'SPFR_1', 'SPFR_2', 'SPFR_3']
    existing_spfr_cols = [col for col in spfr_cols if col in data.columns]

    if existing_spfr_cols:
        for col in existing_spfr_cols:
            mask = data[col] > 0
            mask_high = mask & (data[col] > 5000)
            mask_low = mask & (data[col] <= 5000)

            if mask_high.any():
                data.loc[mask_high, col] = (data.loc[mask_high, col] - nominal) / 1000
            if mask_low.any():
                data.loc[mask_low, col] = (data.loc[mask_low, col] * 1e6 - nominal) / 1000

    unit_conversions = {
        'C0': 1e12,
        'C1': 1e15,
        'L': 1e3,
        'Q': 1e-3
    }

    for col, factor in unit_conversions.items():
        if col in data.columns:
            data[col] = data[col] * factor

    return data


# добавляет колонку для сортировки по позициям
def add_position_index(df):
    df = df.copy()

    extracted = df['Positions'].str.extract(r'^([A-Za-z]+)(\d+)$')
    letters = extracted[0]
    numbers = extracted[1]

    letter_code = letters.apply(
        lambda s: ord(s.upper()[0]) - ord('A') + 1 if pd.notna(s) else 0
    )

    number_code = numbers.str.lstrip('0').fillna('0').astype(int)

    df.loc[:, 'Position_index'] = letter_code * 10000 + number_code
    return df


# Добавляет колонку SETUPNUM и фильтрует по выбранным позициям для kh7700
def add_kh7700_slot_by_positions(slot, data):
    data_inf = MEASURE_DATA.get_setupnum_data(slot)
    position = data_inf['Position']
    data = data[data['Positions'].isin(position)]
    data['SETUPNUM'] = slot
    return data


# для W2200 конвертируем значение колонок Fs Fl из относительных единиц в абсолютные в формате Гц
def convert_freq_w2200(data, slot):
    engine = create_engine(get_connection_string())

    file_id = MEASURE_DATA.get_data()['File_ID']
    query = (f"SELECT fReferenceFrequency FROM `setup file headers` WHERE File_ID='{file_id}' and "
             f" `nSetupFileIndex`='{str(slot)}'")
    nominal = pd.read_sql(query, engine).iat[0, 0]
    delta = nominal / 1e6
    for col in ['Fs', 'Fl']:
        data[col] = nominal + data[col] * delta
    return data


# Добавляет колонку Temp_status в температурную таблицу
def add_temp_status(data):
    mask = (
            data['Fs'].notna() &
            (data['Fs'] > 0) &
            (data['Fs'] < 1e10) &
            (data['R'] > 0) &
            (data['R'] < 1e3)
    )

    data['Temp_status'] = 'Bad'
    data.loc[mask, 'Temp_status'] = 'Pass'

    return data


# Выполняет аппроксимацию по заданной колонке
def interpolate_group(group, degree=3):
    """
    Полиномиальная аппроксимация F_(Temps) внутри одной позиции.

    Защищённые случаи (возвращают F_ как есть, delta_f=0):
      * одна точка измерения;
      * все температуры одинаковые;
      * есть NaN/Inf в F_;
      * std(Temps) == 0;
      * polyfit выбросил ошибку (RankWarning / LinAlgError / ValueError).
    """
    x = group['Temps'].values.astype(float)
    y = group['F_'].values.astype(float)

    n_points = len(x)
    finite_temps = x[np.isfinite(x)]
    unique_temps = np.unique(finite_temps)

    def _passthrough(g):
        g = g.copy()
        g['f_interp'] = g['F_']
        g['delta_f'] = 0.0
        return g

    # Вырожденные случаи: одна точка / одинаковые температуры / NaN в F_
    if (n_points < 2
            or len(unique_temps) < 2
            or np.any(~np.isfinite(y))):
        return _passthrough(group)

    if n_points < degree + 1:
        degree_use = max(1, n_points - 1)
        print(f"Warning: Not enough points ({n_points}) for degree {degree}. "
              f"Using degree {degree_use}.")
        degree = degree_use

    x_mean = np.nanmean(x)
    x_std = np.nanstd(x)
    if x_std == 0 or not np.isfinite(x_std):
        return _passthrough(group)

    x_scaled = (x - x_mean) / x_std

    try:
        coefficients = np.polyfit(x_scaled, y, degree)
    except (np.linalg.LinAlgError, ValueError) as e:
        print(f"interpolate_group: polyfit failed ({e}); using F_ as-is.")
        return _passthrough(group)

    y_interp = np.polyval(coefficients, x_scaled)

    group = group.copy()
    group['f_interp'] = y_interp
    group['delta_f'] = group['f_interp'] - group['F_']
    return group


# Выполняет аппроксимацию по заданной колонке для случая с коррекцией ТЧХ
def interpolate_group_REF(group, degree=3, correction=pd.DataFrame()):
    if not correction.empty:
        group = pd.merge(
            group,
            correction[['Temp', 'T_REF']],
            left_on='Temps',
            right_on='Temp',
            how='left'
        ).drop(columns=['Temp'])

    def _passthrough(g):
        g = g.copy()
        g['f_interp'] = g['F_']
        g['delta_f'] = 0.0
        return g

    x = group['T_REF'].values.astype(float)
    y = group['F_'].values.astype(float)

    finite_x = x[np.isfinite(x)]
    unique_x = np.unique(finite_x)
    if (len(x) < 2
            or len(unique_x) < 2
            or np.any(~np.isfinite(y))):
        return _passthrough(group)

    degree_use = degree
    if len(x) < degree + 1:
        degree_use = max(1, len(x) - 1)

    try:
        coefficients = np.polyfit(x, y, degree_use)
    except (np.linalg.LinAlgError, ValueError) as e:
        print(f"interpolate_group_REF: polyfit failed ({e}); using F_ as-is.")
        return _passthrough(group)

    y_interp = np.polyval(coefficients, x)

    group = group.copy()
    group['f_interp'] = y_interp
    group['delta_f'] = group['f_interp'] - group['F_']
    return group


def add_additional_columns(data: pd.DataFrame, Loadtype, fl_num, correction=False,
                           tch_approx_type='Измерения') -> pd.DataFrame:
    print('LoadType', Loadtype)
    if Loadtype == 'SERIES':
        if tch_approx_type == 'Измерения':
            if correction:
                if 'Fs_ppm_corr' in data.columns:
                    data['F'] = data['Fs_ppm_corr'].copy()
                else:
                    data['F'] = data['Fs_ppm'].copy()
            else:
                data['F'] = data['Fs_ppm'].copy()

        else:
            if correction:
                if 'f_center_cor' in data.columns:
                    data['F'] = data['f_center_cor'].copy()
                else:
