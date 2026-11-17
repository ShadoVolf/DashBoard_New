import pandas as pd
from sqlalchemy import create_engine, text
import numpy as np
from tabulate import tabulate
import sys
import time
import json
from collections import defaultdict
import Options
from Temperature_Measure import Make_Measure

# ===== Логирование =====
import logging

# Настраиваем базовую конфигурацию: все сообщения уровня INFO и выше пишутся в файл,
# а в консоль дублируются только WARNING и выше (устанавливаем уровень для StreamHandler)
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler('app.log', encoding='utf-8')
    ]
)

# Устанавливаем для консольного обработчика уровень WARNING, чтобы INFO не выводились в консоль
for handler in logging.root.handlers:
    if isinstance(handler, logging.StreamHandler) and handler.stream == sys.stdout:
        handler.setLevel(logging.WARNING)
# =======================


def load_spc_map(row):
    engine = create_engine(str(Options.get_connection_string()))
    sql = "SELECT * FROM `spc_map_table` ORDER BY `ID`"
    spc_map = pd.read_sql(sql, engine)
    filtered_spc = spc_map[spc_map.apply(lambda x: row[x['Use']] == 1, axis=1)]

    result_df = filtered_spc.apply(
        lambda spc_row: pd.Series({
            'Parameter': spc_row['Parameter_Name'],
            'Max': float(row[spc_row['Max']]) if row[spc_row['Max']] != 'no' else None,
            'Min': float(row[spc_row['Min']]) if row[spc_row['Min']] != 'no' else None,
            'Code': str(int(spc_row['Code']))
        }),
        axis=1
    )

    logging.info('Спецификация ПСИ загружена')
    # Вывод таблицы только в лог-файл
    logging.info("\nСпецификация ПСИ на изделие:\n" + tabulate(
        result_df,
        headers='keys',
        tablefmt='grid',
        showindex=False,
        missingval='—'
    ))
    df = result_df[~result_df['Parameter'].isin(['Rsp0', 'Rsp1', 'Rsp2'])]
    return df


def get_available_parameters(spc_data, data_columns):
    spc_params = spc_data.set_index('Parameter')
    available_params = spc_params.index.intersection(data_columns).tolist()
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
            ['Positions',  'Numbers',
             'Status', 'Error_Code', 'Anomal_Status']
            + status_columns
            + anomal_columns
    )

    return result_df[keep_columns]


def prepare_result_df2(data, params):
    selected_columns = ['Positions',  'Numbers'] + params
    return data[selected_columns].copy()


def prepare_anomal_df(data, anomaly_masks, params):
    anomaly_df = data.copy()
    for param in params:
        col_name = f"{param}_anomal_status"
        anomaly_df[col_name] = anomaly_masks[param]
    anomaly_df['Anomal_Status'] = anomaly_df[[col for col in anomaly_df if '_anomal_status' in col]].any(axis=1)
    selected_cols = ['Positions',  'Numbers'] + params + list(anomaly_masks.columns) + [
        'Anomal_Status']
    return anomaly_df[selected_cols]


def add_anomal_to_status(df):
    ignored_columns = {
        'Positions',
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


def calculate_statistics(data, result_df, spc_params, params):
    stats = []
    numeric_cols = data.columns.difference(
        ['Positions', 'Numbers',  'Temp_status', 'KO_F', 'KO_S_Numbers', 'Status2'])

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


def update_statuses_based_on_nan(result_df, data_df, param_columns):
    result_df = result_df.copy()
    data_df = data_df.copy()
    nan_mask = data_df[param_columns].isna().any(axis=1)

    data_df.loc[nan_mask, 'Anomal_Status'] = True

    keys = ['Positions',  'Numbers']
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


def calculate_anomalies(data, params, use=True):
    anomaly_masks = {}
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
    return pd.DataFrame(anomaly_masks)


def print_results(result_df, result_df2, stats_df, result_anomal):
    logging.info("Результаты обработки:")
    logging.info(f"Всего изделий: {len(result_df)}")
    logging.info(f"Годных: {result_df['Status'].sum()}")
    logging.info(f"Бракованных: {len(result_df) - result_df['Status'].sum()}")


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
    if 'Status' in data.columns:
        n_mask = data['Status'] == 'Незамер.'
        if n_mask.any():
            logging.warning(f"Найдено {n_mask.sum()} изделий с пометкой 'Незамер', они будут помечены как брак")
            result_df.loc[n_mask, 'Status'] = False
            result_df.loc[n_mask, 'Status2'] = 'Bad'
            result_df.loc[n_mask, 'Anomal_Status'] = True
            result_df2.loc[n_mask, 'Anomal_Status'] = True

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
            logging.info(f"Применение специальной логики для {rsp_param} на основе {spfr_param}")
            spfr_in_spec = mask[spfr_param]
            mask[rsp_param] = (~spfr_in_spec) | mask[rsp_param]
        else:
            logging.info(f"SPFR параметр {spfr_param} не найден, применяется стандартная проверка для {rsp_param}")


def exclude_spfr_from_rejection(mask, params):
    spfr_params = [p for p in params if p.startswith('SPFR_')]

    for spfr_param in spfr_params:
        mask[spfr_param] = True
        logging.info(f"Параметр {spfr_param} исключен из браковки изделия")

    return mask


def create_spc_map_otk(spc_map, row):
    engine = create_engine(str(Options.get_connection_string()))
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

        # Применение допуска к Max (всегда сужаем)
        if pd.notna(max_val):
            if use_units:
                max_val -= units
            elif use_percent:
                max_val *= (1 - percent / 100)   # для любого знака
            row['Max'] = np.round(max_val, 3)

        # Применение допуска к Min (сужаем с учётом знака)
        if pd.notna(min_val):
            if use_units:
                min_val += units
            elif use_percent:
                if min_val > 0:
                    min_val *= (1 + percent / 100)
                elif min_val < 0:
                    min_val *= (1 - percent / 100)
                # если min_val == 0, оставляем 0
            row['Min'] = np.round(min_val, 3)

        return row

    result_df = merged_df.apply(apply_tolerance, axis=1)
    result_df = result_df[['Parameter', 'Max', 'Min', 'Code']]

    logging.info('Спецификация ОТК загружена')
    # Вывод таблицы только в лог-файл
    logging.info("\nСпецификация ОТК на изделие:\n" + tabulate(
        result_df,
        headers='keys',
        tablefmt='grid',
        showindex=False,
        missingval='—'
    ))
    return result_df


def create_new_measure_id(engine, source_measure_ids=None, msk=None, program_type=None, operator=None):
    try:
        with engine.connect() as conn:
            if source_measure_ids and len(source_measure_ids) > 0:
                source_sql = f"SELECT * FROM psi_measure_id WHERE MeasureID = {source_measure_ids[0]}"
                source_data = pd.read_sql(source_sql, conn)

                if not source_data.empty:
                    source_row = source_data.iloc[0]
                    insert_sql = text("""
                        INSERT INTO psi_measure_id 
                        (MSK, ProtokolN, File, Program_Type, File_ID, Operator)
                        VALUES (:msk, :protokoln, :file, :program_type, :file_id, :operator)
                    """)
                    result = conn.execute(insert_sql, {
                        'msk': msk if msk is not None else source_row['MSK'],
                        'protokoln': source_row['ProtokolN'],
                        'file': source_row['File'],
                        'program_type': program_type if program_type is not None else source_row['Program_Type'],
                        'file_id': str(source_row['File_ID']),
                        'operator': operator if operator is not None else source_row['Operator']
                    })
                else:
                    insert_sql = text("""
                        INSERT INTO psi_measure_id 
                        (MSK, Program_Type, Operator) 
                        VALUES (:msk, :program_type, :operator)
                    """)
                    result = conn.execute(insert_sql, {
                        'msk': msk,
                        'program_type': program_type,
                        'operator': operator
                    })
            else:
                insert_sql = text("""
                    INSERT INTO psi_measure_id 
                    (MSK, Program_Type, Operator) 
                    VALUES (:msk, :program_type, :operator)
                """)
                result = conn.execute(insert_sql, {
                    'msk': msk,
                    'program_type': program_type,
                    'operator': operator
                })

            new_measure_id = result.lastrowid
            conn.commit()

            logging.info(f" Создан новый замер с Measure_ID: {new_measure_id}")
            if msk:
                logging.info(f"   MSK: {msk}")
            if program_type:
                logging.info(f"   Program_Type: {program_type}")
            if operator:
                logging.info(f"   Operator: {operator}")
            return new_measure_id

    except Exception as e:
        logging.exception(f" Ошибка при создании нового Measure_ID: {e}")
        return None

def copy_psi_data(engine, source_measure_ids, valid_numbers, new_measure_id,
                  new_msk=None, new_operator=None, program_type=None,
                  psi_type='ОТК'):
    """Копирует годные строки из исходных замеров в новый Measure_ID.

    psi_type — 'ПСИ' / 'ОТК': явно перезаписывается в psidata.psi_type
    для всех скопированных строк (иначе унаследуется от источников).
    Если колонки psi_type в psidata нет — тихо пропускаем
    (обратная совместимость со старой схемой).
    """
    try:
        total_copied = 0
        psi_type = psi_type if psi_type in ('ПСИ', 'ОТК') else 'ОТК'

        # ----------------------- данные машины -----------------------
        machine_data = None
        if program_type:
            try:
                machine_sql = (
                    f"SELECT * FROM machines WHERE Name = '{program_type}'"
                )
                machine_data = pd.read_sql(machine_sql, engine)
                if not machine_data.empty:
                    machine_data = machine_data.iloc[0]
                    logging.info(f"   Данные машины загружены: {program_type}")
                else:
                    logging.warning(
                        f"   Внимание: машина '{program_type}' "
                        f"не найдена в таблице machines"
                    )
                    machine_data = None
            except Exception as e:
                logging.exception(
                    f"   Ошибка при загрузке данных машины: {e}"
                )
                machine_data = None

        # ------------------------- WHERE по (mid, N) -------------------------
        conditions = []
        params = {}
        param_counter = 0

        for measure_id in source_measure_ids:
            numbers_for_measure = valid_numbers[
                valid_numbers['Measure_ID'] == measure_id
            ]['Numbers'].tolist()
            if numbers_for_measure:
                number_conditions = []
                for number in numbers_for_measure:
                    param_name = f"num_{param_counter}"
                    number_conditions.append(
                        f"(Measure_ID = {measure_id} AND N = :{param_name})"
                    )
                    params[param_name] = number
                    param_counter += 1
                conditions.append(" OR ".join(number_conditions))

        if not conditions:
            logging.info(" Нет данных для копирования в psidata")
            return 0

        where_clause = " WHERE " + " OR ".join(conditions)

        with engine.connect() as conn:
            # ------------------- схема psidata -------------------
            columns_query = """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = 'psidata'
                AND TABLE_SCHEMA = DATABASE()
                AND COLUMN_NAME != 'ID'
                ORDER BY ORDINAL_POSITION
            """
            columns_df = pd.read_sql(columns_query, conn)
            columns = columns_df['COLUMN_NAME'].tolist()

            has_files_multy = 'files_multy' in columns
            has_psi_type = 'psi_type' in columns

            # ------------------- выборка источника -------------------
            select_sql = text(f"SELECT * FROM psidata {where_clause}")
            source_data = pd.read_sql(select_sql, conn, params=params)

            if source_data.empty:
                logging.info(" Нет данных для копирования в psidata")
                return 0

            if 'ID' in source_data.columns:
                source_data = source_data.drop('ID', axis=1)

            # --------------- files_multy по номерам ---------------
            files_by_number = defaultdict(list)
            for _, row in source_data.iterrows():
                number = row['N']
                file_info = []
                if 'File' in row and pd.notna(row['File']):
                    file_info.append(row['File'])
                if 'File_ID' in row and pd.notna(row['File_ID']):
                    file_info.append(row['File_ID'])
                if file_info:
                    files_by_number[number].append(file_info)

            # ------------------ Measure_ID / MSK / Operator ------------------
            source_data['Measure_ID'] = new_measure_id

            # ▼ NEW: единый тип протокола для всех строк нового замера.
            #   Перезаписываем независимо от режима «Изменить/Не изменять
            #   данные»: psi_type — метаданные нового протокола, а не
            #   изменяемые данные источника. Без этой строки значение
            #   унаследуется от исходных замеров (могут быть смешанные).
            if has_psi_type:
                source_data['psi_type'] = psi_type
                logging.info(
                    f" Установлен psi_type = {psi_type!r} "
                    f"для {len(source_data)} записей в psidata"
                )
            else:
                logging.warning(
                    " Внимание: в psidata нет колонки 'psi_type' — "
                    "тип протокола не записан"
                )

            if new_msk is not None:
                source_data['MSK'] = new_msk
                logging.info(
                    f" Обновлен MSK на {new_msk} для "
                    f"{len(source_data)} записей в psidata"
                )

            if new_operator is not None:
                source_data['Operator'] = new_operator
                logging.info(
                    f" Обновлен Operator на {new_operator} для "
                    f"{len(source_data)} записей в psidata"
                )

            # -------------------- данные машины --------------------
            if machine_data is not None:
                if ('Serial_N' in machine_data
                        and pd.notna(machine_data['Serial_N'])):
                    source_data['Machine_Serial'] = machine_data['Serial_N']
                    logging.info(
                        f" Обновлен Machine_Serial на "
                        f"{machine_data['Serial_N']}"
                    )

                if ('Call_Date' in machine_data
                        and pd.notna(machine_data['Call_Date'])):
                    source_data['Machine_Call_Date'] = machine_data['Call_Date']
                    logging.info(
                        f" Обновлен Machine_Call_Date на "
                        f"{machine_data['Call_Date']}"
                    )

                if ('M_Type' in machine_data
                        and pd.notna(machine_data['M_Type'])):
                    source_data['M_Type'] = machine_data['M_Type']
                    logging.info(
                        f" Обновлен M_Type на {machine_data['M_Type']}"
                    )

                if ('Type' in machine_data
                        and pd.notna(machine_data['Type'])):
                    if machine_data['Type'] == 'Transat':
                        source_data['MachineType'] = 'CNA-300'
                        logging.info(
                            " Обновлен MachineType на CNA-300 (Transat)"
                        )
                    else:
                        source_data['MachineType'] = machine_data['Type']
                        logging.info(
                            f" Обновлен MachineType на {machine_data['Type']}"
                        )

            # ------------------- files_multy -------------------
            if has_files_multy:
                source_data['files_multy'] = source_data['N'].apply(
                    lambda x: json.dumps(files_by_number.get(x, []))
                )
                logging.info(
                    " Добавлено поле files_multy с объединенными файлами"
                )
            else:
                logging.warning(
                    " Внимание: поле files_multy не найдено в таблице psidata"
                )

            # ------------------- запись -------------------
            source_data[columns].to_sql(
                'psidata', conn, if_exists='append',
                index=False, method='multi',
            )
            total_copied = len(source_data)

            conn.commit()
            logging.info(
                f" Скопировано {total_copied} записей в psidata "
                f"(psi_type = {psi_type!r})"
            )

        return total_copied

    except Exception as e:
        logging.exception(f" Ошибка при копировании данных в psidata: {e}")
        return 0

def copy_psi_data_1(engine, source_measure_ids, valid_numbers, new_measure_id, new_msk=None, new_operator=None,
                  program_type=None):
    try:
        total_copied = 0

        machine_data = None
        if program_type:
            try:
                machine_sql = f"SELECT * FROM machines WHERE Name = '{program_type}'"
                machine_data = pd.read_sql(machine_sql, engine)
                if not machine_data.empty:
                    machine_data = machine_data.iloc[0]
                    logging.info(f"   Данные машины загружены: {program_type}")
                else:
                    logging.warning(f"   Внимание: машина '{program_type}' не найдена в таблице machines")
                    machine_data = None
            except Exception as e:
                logging.exception(f"   Ошибка при загрузке данных машины: {e}")
                machine_data = None

        conditions = []
        params = {}
        param_counter = 0

        for measure_id in source_measure_ids:
            numbers_for_measure = valid_numbers[valid_numbers['Measure_ID'] == measure_id]['Numbers'].tolist()
            if numbers_for_measure:
                number_conditions = []
                for number in numbers_for_measure:
                    param_name = f"num_{param_counter}"
                    number_conditions.append(f"(Measure_ID = {measure_id} AND N = :{param_name})")
                    params[param_name] = number
                    param_counter += 1
                conditions.append(" OR ".join(number_conditions))

        if not conditions:
            logging.info(" Нет данных для копирования в psidata")
            return 0

        where_clause = " WHERE " + " OR ".join(conditions)

        with engine.connect() as conn:
            columns_query = """
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'psidata' 
                AND TABLE_SCHEMA = DATABASE()
                AND COLUMN_NAME != 'ID'
                ORDER BY ORDINAL_POSITION
            """
            columns_df = pd.read_sql(columns_query, conn)
            columns = columns_df['COLUMN_NAME'].tolist()

            has_files_multy = 'files_multy' in columns

            select_sql = text(f"SELECT * FROM psidata {where_clause}")
            source_data = pd.read_sql(select_sql, conn, params=params)

            if source_data.empty:
                logging.info(" Нет данных для копирования в psidata")
                return 0

            if 'ID' in source_data.columns:
                source_data = source_data.drop('ID', axis=1)

            files_by_number = defaultdict(list)
            for _, row in source_data.iterrows():
                number = row['N']
                file_info = []
                if 'File' in row and pd.notna(row['File']):
                    file_info.append(row['File'])
                if 'File_ID' in row and pd.notna(row['File_ID']):
                    file_info.append(row['File_ID'])
                if file_info:
                    files_by_number[number].append(file_info)

            source_data['Measure_ID'] = new_measure_id

            if new_msk is not None:
                source_data['MSK'] = new_msk
                logging.info(f" Обновлен MSK на {new_msk} для {len(source_data)} записей в psidata")

            if new_operator is not None:
                source_data['Operator'] = new_operator
                logging.info(f" Обновлен Operator на {new_operator} для {len(source_data)} записей в psidata")

            if machine_data is not None:
                if 'Serial_N' in machine_data and pd.notna(machine_data['Serial_N']):
                    source_data['Machine_Serial'] = machine_data['Serial_N']
                    logging.info(f" Обновлен Machine_Serial на {machine_data['Serial_N']}")

                if 'Call_Date' in machine_data and pd.notna(machine_data['Call_Date']):
                    source_data['Machine_Call_Date'] = machine_data['Call_Date']
                    logging.info(f" Обновлен Machine_Call_Date на {machine_data['Call_Date']}")

                if 'M_Type' in machine_data and pd.notna(machine_data['M_Type']):
                    source_data['M_Type'] = machine_data['M_Type']
                    logging.info(f" Обновлен M_Type на {machine_data['M_Type']}")

                if 'Type' in machine_data and pd.notna(machine_data['Type']):
                    if machine_data['Type'] == 'Transat':
                        source_data['MachineType'] = 'CNA-300'
                        logging.info(" Обновлен MachineType на CNA-300 (Transat)")
                    else:
                        source_data['MachineType'] = machine_data['Type']
                        logging.info(f" Обновлен MachineType на {machine_data['Type']}")

            if has_files_multy:
                source_data['files_multy'] = source_data['N'].apply(
                    lambda x: json.dumps(files_by_number.get(x, []))
                )
                logging.info(" Добавлено поле files_multy с объединенными файлами")
            else:
                logging.warning(" Внимание: поле files_multy не найдено в таблице psidata")

            source_data[columns].to_sql('psidata', conn, if_exists='append', index=False, method='multi')
            total_copied = len(source_data)

            conn.commit()
            logging.info(f" Скопировано {total_copied} записей в psidata")

        return total_copied

    except Exception as e:
        logging.exception(f" Ошибка при копировании данных в psidata: {e}")
        return 0


def copy_psi_data1(engine, source_measure_ids, valid_numbers, new_measure_id, new_msk=None, new_operator=None, program_type=None):
    try:
        total_copied = 0

        machine_data = None
        if program_type:
            try:
                machine_sql = f"SELECT * FROM machines WHERE Name = '{program_type}'"
                machine_data = pd.read_sql(machine_sql, engine)
                if not machine_data.empty:
                    machine_data = machine_data.iloc[0]
                    logging.info(f"   Данные машины загружены: {program_type}")
                else:
                    logging.warning(f"   Внимание: машина '{program_type}' не найдена в таблице machines")
                    machine_data = None
            except Exception as e:
                logging.exception(f"   Ошибка при загрузке данных машины: {e}")
                machine_data = None

        conditions = []
        params = {}
        param_counter = 0

        for measure_id in source_measure_ids:
            numbers_for_measure = valid_numbers[valid_numbers['Measure_ID'] == measure_id]['Numbers'].tolist()
            if numbers_for_measure:
                number_conditions = []
                for number in numbers_for_measure:
                    param_name = f"num_{param_counter}"
                    number_conditions.append(f"(Measure_ID = {measure_id} AND N = :{param_name})")
                    params[param_name] = number
                    param_counter += 1
                conditions.append(" OR ".join(number_conditions))

        if not conditions:
            logging.info(" Нет данных для копирования в psidata")
            return 0

        where_clause = " WHERE " + " OR ".join(conditions)

        with engine.connect() as conn:
            columns_query = """
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'psidata' 
                AND TABLE_SCHEMA = DATABASE()
                AND COLUMN_NAME != 'ID'
                ORDER BY ORDINAL_POSITION
            """
            columns_df = pd.read_sql(columns_query, conn)
            columns = columns_df['COLUMN_NAME'].tolist()

            select_sql = text(f"SELECT * FROM psidata {where_clause}")
            source_data = pd.read_sql(select_sql, conn, params=params)

            if source_data.empty:
                logging.info(" Нет данных для копирования в psidata")
                return 0

            if 'ID' in source_data.columns:
                source_data = source_data.drop('ID', axis=1)

            source_data['Measure_ID'] = new_measure_id

            if new_msk is not None:
                source_data['MSK'] = new_msk
                logging.info(f" Обновлен MSK на {new_msk} для {len(source_data)} записей в psidata")

            if new_operator is not None:
                source_data['Operator'] = new_operator
                logging.info(f" Обновлен Operator на {new_operator} для {len(source_data)} записей в psidata")

            if machine_data is not None:
                if 'Serial_N' in machine_data and pd.notna(machine_data['Serial_N']):
                    source_data['Machine_Serial'] = machine_data['Serial_N']
                    logging.info(f" Обновлен Machine_Serial на {machine_data['Serial_N']}")

                if 'Call_Date' in machine_data and pd.notna(machine_data['Call_Date']):
                    source_data['Machine_Call_Date'] = machine_data['Call_Date']
                    logging.info(f" Обновлен Machine_Call_Date на {machine_data['Call_Date']}")

                if 'M_Type' in machine_data and pd.notna(machine_data['M_Type']):
                    source_data['M_Type'] = machine_data['M_Type']
                    logging.info(f" Обновлен M_Type на {machine_data['M_Type']}")

                if 'Type' in machine_data and pd.notna(machine_data['Type']):
                    if machine_data['Type'] == 'Transat':
                        source_data['MachineType'] = 'CNA-300'
                        logging.info(" Обновлен MachineType на CNA-300 (Transat)")
                    else:
                        source_data['MachineType'] = machine_data['Type']
                        logging.info(f" Обновлен MachineType на {machine_data['Type']}")

            source_data[columns].to_sql('psidata', conn, if_exists='append', index=False, method='multi')
            total_copied = len(source_data)

            conn.commit()
            logging.info(f" Скопировано {total_copied} записей в psidata")

        return total_copied

    except Exception as e:
        logging.exception(f" Ошибка при копировании данных в psidata: {e}")
        return 0


def copy_psidatatemp_data(engine, source_measure_ids, valid_numbers, new_measure_id, new_msk=None, new_operator=None):
    try:
        total_copied = 0

        conditions = []
        params = {}
        param_counter = 0

        for measure_id in source_measure_ids:
            numbers_for_measure = valid_numbers[valid_numbers['Measure_ID'] == measure_id]['Numbers'].tolist()
            if numbers_for_measure:
                number_conditions = []
                for number in numbers_for_measure:
                    param_name = f"num_{param_counter}"
                    number_conditions.append(f"(Measure_ID = {measure_id} AND N = :{param_name})")
                    params[param_name] = number
                    param_counter += 1
                conditions.append(" OR ".join(number_conditions))

        if not conditions:
            logging.info(" Нет данных для копирования в psidatatemp")
            return 0

        where_clause = " WHERE " + " OR ".join(conditions)

        with engine.connect() as conn:
            columns_query = """
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'psidatatemp' 
                AND TABLE_SCHEMA = DATABASE()
                AND COLUMN_NAME != 'RecordId'
                ORDER BY ORDINAL_POSITION
            """
            columns_df = pd.read_sql(columns_query, conn)
            columns = columns_df['COLUMN_NAME'].tolist()

            if 'Operator' in columns:
                columns.remove('Operator')

            select_sql = text(f"SELECT * FROM psidatatemp {where_clause}")
            source_data = pd.read_sql(select_sql, conn, params=params)

            if source_data.empty:
                logging.info("✓ Нет данных для копирования в psidatatemp")
                return 0

            if 'RecordId' in source_data.columns:
                source_data = source_data.drop('RecordId', axis=1)

            if 'Operator' in source_data.columns:
                source_data = source_data.drop('Operator', axis=1)

            source_data['Measure_ID'] = new_measure_id

            if new_msk is not None:
                source_data['MSK'] = new_msk
                logging.info(f" Обновлен MSK на {new_msk} для {len(source_data)} записей в psidatatemp")

            source_data[columns].to_sql('psidatatemp', conn, if_exists='append', index=False, method='multi')
            total_copied = len(source_data)

            conn.commit()
            logging.info(f" Скопировано {total_copied} записей в psidatatemp")

        return total_copied

    except Exception as e:
        logging.exception(f" Ошибка при копировании данных в psidatatemp: {e}")
        return 0

def copy_rejected_data(engine, measure_ids, rejected_numbers, new_measure_id,
                       new_msk=None, new_operator=None, program_type=None,
                       psi_type='ОТК'):
    """Копирует бракованные строки в новый Measure_ID (psidata + psidatatemp).

    psi_type — 'ПСИ' / 'ОТК': явно перезаписывается в psidata.psi_type
    для каждой скопированной строки (иначе унаследуется от источника).
    Если колонки psi_type нет — тихо пропускаем.
    """
    try:
        total_psi_copied = 0
        total_temp_copied = 0
        psi_type = psi_type if psi_type in ('ПСИ', 'ОТК') else 'ОТК'

        # ----------------------- данные машины -----------------------
        machine_data = None
        if program_type:
            try:
                machine_sql = (
                    f"SELECT * FROM machines WHERE Name = '{program_type}'"
                )
                machine_data = pd.read_sql(machine_sql, engine)
                if not machine_data.empty:
                    machine_data = machine_data.iloc[0]
                    logging.info(
                        f"   Данные машины загружены для бракованных "
                        f"изделий: {program_type}"
                    )
                else:
                    logging.warning(
                        f"   Внимание: машина '{program_type}' "
                        f"не найдена в таблице machines для бракованных "
                        f"изделий"
                    )
                    machine_data = None
            except Exception as e:
                logging.exception(
                    f"   Ошибка при загрузке данных машины для бракованных "
                    f"изделий: {e}"
                )
                machine_data = None

        # --------------- схема psidata + files_multy ---------------
        with engine.connect() as conn:
            columns_query = """
                SELECT COLUMN_NAME
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_NAME = 'psidata'
                AND TABLE_SCHEMA = DATABASE()
                AND COLUMN_NAME != 'ID'
                ORDER BY ORDINAL_POSITION
            """
            columns_df = pd.read_sql(columns_query, conn)
            columns = columns_df['COLUMN_NAME'].tolist()
            has_files_multy = 'files_multy' in columns
            has_psi_type = 'psi_type' in columns

        # --------------- File / File_ID по номерам ---------------
        files_by_number = defaultdict(list)
        for measure_id in measure_ids:
            try:
                with engine.connect() as conn:
                    psi_sql = (
                        f"SELECT N, File, File_ID FROM psidata "
                        f"WHERE Measure_ID = {measure_id}"
                    )
                    psi_files_data = pd.read_sql(psi_sql, conn)

                    for _, row in psi_files_data.iterrows():
                        number = row['N']
                        file_info = []
                        if pd.notna(row['File']):
                            file_info.append(row['File'])
                        if pd.notna(row['File_ID']):
                            file_info.append(row['File_ID'])
                        if file_info:
                            files_by_number[number].append(file_info)
            except Exception as e:
                logging.exception(
                    f"   Ошибка при получении файлов из "
                    f"Measure_ID {measure_id}: {e}"
                )
                continue

        rejected_numbers_list = list(rejected_numbers)

        for i, number in enumerate(rejected_numbers_list):
            show_progress(
                i + 1, len(rejected_numbers_list),
                f"Копирование бракованных изделий",
            )

            for measure_id in measure_ids:
                try:
                    with engine.connect() as conn:
                        # ------------------ psidata ------------------
                        psi_sql = (
                            f"SELECT * FROM psidata "
                            f"WHERE Measure_ID = {measure_id} "
                            f"AND N = '{number}' LIMIT 1"
                        )
                        psi_data = pd.read_sql(psi_sql, conn)

                        if not psi_data.empty:
                            if 'ID' in psi_data.columns:
                                psi_data = psi_data.drop('ID', axis=1)

                            psi_data['Measure_ID'] = new_measure_id

                            # ▼ NEW: перезапись типа протокола
                            if has_psi_type and 'psi_type' in psi_data.columns:
                                psi_data['psi_type'] = psi_type

                            if new_msk is not None:
                                psi_data['MSK'] = new_msk

                            if new_operator is not None:
                                psi_data['Operator'] = new_operator

                            if machine_data is not None:
                                if ('Serial_N' in machine_data
                                        and pd.notna(machine_data['Serial_N'])):
                                    psi_data['Machine_Serial'] = (
                                        machine_data['Serial_N']
                                    )

                                if ('Call_Date' in machine_data
                                        and pd.notna(
                                            machine_data['Call_Date']
                                        )):
                                    psi_data['Machine_Call_Date'] = (
                                        machine_data['Call_Date']
                                    )

                                if ('M_Type' in machine_data
                                        and pd.notna(machine_data['M_Type'])):
                                    psi_data['M_Type'] = (
                                        machine_data['M_Type']
                                    )

                                if ('Type' in machine_data
                                        and pd.notna(machine_data['Type'])):
                                    if machine_data['Type'] == 'Transat':
                                        psi_data['MachineType'] = 'CNA-300'
                                    else:
                                        psi_data['MachineType'] = (
                                            machine_data['Type']
                                        )

                            if has_files_multy and number in files_by_number:
                                psi_data['files_multy'] = json.dumps(
                                    files_by_number[number]
                                )

                            psi_data[columns].to_sql(
                                'psidata', conn, if_exists='append',
                                index=False,
                            )
                            total_psi_copied += 1

                            # ---------------- psidatatemp ----------------
                            temp_sql = (
                                f"SELECT * FROM psidatatemp "
                                f"WHERE Measure_ID = {measure_id} "
                                f"AND N = '{number}'"
                            )
                            temp_data = pd.read_sql(temp_sql, conn)

                            if not temp_data.empty:
                                if 'RecordId' in temp_data.columns:
                                    temp_data = temp_data.drop(
                                        'RecordId', axis=1
                                    )
                                if 'Operator' in temp_data.columns:
                                    temp_data = temp_data.drop(
                                        'Operator', axis=1
                                    )

                                temp_data['Measure_ID'] = new_measure_id

                                if new_msk is not None:
                                    temp_data['MSK'] = new_msk

                                # psidatatemp — своя схема, psi_type
                                # там обычно нет; перезаписываем только
                                # если колонка реально существует.
                                if 'psi_type' in temp_data.columns:
                                    temp_data['psi_type'] = psi_type

                                temp_data.to_sql(
                                    'psidatatemp', conn,
                                    if_exists='append', index=False,
                                )
                                total_temp_copied += len(temp_data)

                            break  # строка скопирована — к следующему номеру

                except Exception as e:
                    logging.exception(
                        f"✗ Ошибка при копировании бракованного "
                        f"номера {number}: {e}"
                    )
                    continue

        logging.info(
            f"\n Скопировано {total_psi_copied} бракованных записей "
            f"в psidata (psi_type = {psi_type!r})"
        )
        logging.info(
            f" Скопировано {total_temp_copied} бракованных записей "
            f"в psidatatemp"
        )

        return total_psi_copied, total_temp_copied

    except Exception as e:
        logging.exception(f"✗ Ошибка при копировании бракованных данных: {e}")
        return 0, 0

def copy_rejected_data_1(engine, measure_ids, rejected_numbers, new_measure_id, new_msk=None, new_operator=None,
                       program_type=None):
    try:
        total_psi_copied = 0
        total_temp_copied = 0

        machine_data = None
        if program_type:
            try:
                machine_sql = f"SELECT * FROM machines WHERE Name = '{program_type}'"
                machine_data = pd.read_sql(machine_sql, engine)
                if not machine_data.empty:
                    machine_data = machine_data.iloc[0]
                    logging.info(f"   Данные машины загружены для бракованных изделий: {program_type}")
                else:
                    logging.warning(f"   Внимание: машина '{program_type}' не найдена в таблице machines для бракованных изделий")
                    machine_data = None
            except Exception as e:
                logging.exception(f"   Ошибка при загрузке данных машины для бракованных изделий: {e}")
                machine_data = None

        with engine.connect() as conn:
            columns_query = """
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_NAME = 'psidata' 
                AND TABLE_SCHEMA = DATABASE()
                AND COLUMN_NAME != 'ID'
                ORDER BY ORDINAL_POSITION
            """
            columns_df = pd.read_sql(columns_query, conn)
            columns = columns_df['COLUMN_NAME'].tolist()
            has_files_multy = 'files_multy' in columns

        files_by_number = defaultdict(list)
        for measure_id in measure_ids:
            try:
                with engine.connect() as conn:
                    psi_sql = f"SELECT N, File, File_ID FROM psidata WHERE Measure_ID = {measure_id}"
                    psi_files_data = pd.read_sql(psi_sql, conn)

                    for _, row in psi_files_data.iterrows():
                        number = row['N']
                        file_info = []
                        if pd.notna(row['File']):
                            file_info.append(row['File'])
                        if pd.notna(row['File_ID']):
                            file_info.append(row['File_ID'])
                        if file_info:
                            files_by_number[number].append(file_info)
            except Exception as e:
                logging.exception(f"   Ошибка при получении файлов из Measure_ID {measure_id}: {e}")
                continue

        rejected_numbers_list = list(rejected_numbers)

        for i, number in enumerate(rejected_numbers_list):
            show_progress(i + 1, len(rejected_numbers_list), f"Копирование бракованных изделий")

            for measure_id in measure_ids:
                try:
                    with engine.connect() as conn:
                        psi_sql = f"SELECT * FROM psidata WHERE Measure_ID = {measure_id} AND N = '{number}' LIMIT 1"
                        psi_data = pd.read_sql(psi_sql, conn)

                        if not psi_data.empty:
                            if 'ID' in psi_data.columns:
                                psi_data = psi_data.drop('ID', axis=1)

                            psi_data['Measure_ID'] = new_measure_id

                            if new_msk is not None:
                                psi_data['MSK'] = new_msk

                            if new_operator is not None:
                                psi_data['Operator'] = new_operator

                            if machine_data is not None:
                                if 'Serial_N' in machine_data and pd.notna(machine_data['Serial_N']):
                                    psi_data['Machine_Serial'] = machine_data['Serial_N']

                                if 'Call_Date' in machine_data and pd.notna(machine_data['Call_Date']):
                                    psi_data['Machine_Call_Date'] = machine_data['Call_Date']

                                if 'M_Type' in machine_data and pd.notna(machine_data['M_Type']):
                                    psi_data['M_Type'] = machine_data['M_Type']

                                if 'Type' in machine_data and pd.notna(machine_data['Type']):
                                    if machine_data['Type'] == 'Transat':
                                        psi_data['MachineType'] = 'CNA-300'
                                    else:
                                        psi_data['MachineType'] = machine_data['Type']

                            if has_files_multy and number in files_by_number:
                                psi_data['files_multy'] = json.dumps(files_by_number[number])

                            psi_data[columns].to_sql('psidata', conn, if_exists='append', index=False)
                            total_psi_copied += 1

                            temp_sql = f"SELECT * FROM psidatatemp WHERE Measure_ID = {measure_id} AND N = '{number}'"
                            temp_data = pd.read_sql(temp_sql, conn)

                            if not temp_data.empty:
                                if 'RecordId' in temp_data.columns:
                                    temp_data = temp_data.drop('RecordId', axis=1)

                                if 'Operator' in temp_data.columns:
                                    temp_data = temp_data.drop('Operator', axis=1)

                                temp_data['Measure_ID'] = new_measure_id

                                if new_msk is not None:
                                    temp_data['MSK'] = new_msk

                                temp_data.to_sql('psidatatemp', conn, if_exists='append', index=False)
                                total_temp_copied += len(temp_data)

                            break

                except Exception as e:
                    logging.exception(f"✗ Ошибка при копировании бракованного номера {number}: {e}")
                    continue

        logging.info(f"\n Скопировано {total_psi_copied} бракованных записей в psidata")
        logging.info(f" Скопировано {total_temp_copied} бракованных записей в psidatatemp")

        return total_psi_copied, total_temp_copied

    except Exception as e:
        logging.exception(f"✗ Ошибка при копировании бракованных данных: {e}")
        return 0, 0


def copy_rejected_data_1(engine, measure_ids, rejected_numbers, new_measure_id, new_msk=None, new_operator=None, program_type=None):
    try:
        total_psi_copied = 0
        total_temp_copied = 0

        machine_data = None
        if program_type:
            try:
                machine_sql = f"SELECT * FROM machines WHERE Name = '{program_type}'"
                machine_data = pd.read_sql(machine_sql, engine)
                if not machine_data.empty:
                    machine_data = machine_data.iloc[0]
                    logging.info(f"   Данные машины загружены для бракованных изделий: {program_type}")
                else:
                    logging.warning(f"   Внимание: машина '{program_type}' не найдена в таблице machines для бракованных изделий")
                    machine_data = None
            except Exception as e:
                logging.exception(f"   Ошибка при загрузке данных машины для бракованных изделий: {e}")
                machine_data = None

        rejected_numbers_list = list(rejected_numbers)

        for i, number in enumerate(rejected_numbers_list):
            show_progress(i + 1, len(rejected_numbers_list), f"Копирование бракованных изделий")

            for measure_id in measure_ids:
                try:
                    with engine.connect() as conn:
                        psi_sql = f"SELECT * FROM psidata WHERE Measure_ID = {measure_id} AND N = '{number}' LIMIT 1"
                        psi_data = pd.read_sql(psi_sql, conn)

                        if not psi_data.empty:
                            if 'ID' in psi_data.columns:
                                psi_data = psi_data.drop('ID', axis=1)

                            psi_data['Measure_ID'] = new_measure_id

                            if new_msk is not None:
                                psi_data['MSK'] = new_msk

                            if new_operator is not None:
                                psi_data['Operator'] = new_operator

                            if machine_data is not None:
                                if 'Serial_N' in machine_data and pd.notna(machine_data['Serial_N']):
                                    psi_data['Machine_Serial'] = machine_data['Serial_N']

                                if 'Call_Date' in machine_data and pd.notna(machine_data['Call_Date']):
                                    psi_data['Machine_Call_Date'] = machine_data['Call_Date']

                                if 'M_Type' in machine_data and pd.notna(machine_data['M_Type']):
                                    psi_data['M_Type'] = machine_data['M_Type']

                                if 'Type' in machine_data and pd.notna(machine_data['Type']):
                                    if machine_data['Type'] == 'Transat':
                                        psi_data['MachineType'] = 'CNA-300'
                                    else:
                                        psi_data['MachineType'] = machine_data['Type']

                            psi_data.to_sql('psidata', conn, if_exists='append', index=False)
                            total_psi_copied += 1

                            temp_sql = f"SELECT * FROM psidatatemp WHERE Measure_ID = {measure_id} AND N = '{number}'"
                            temp_data = pd.read_sql(temp_sql, conn)

                            if not temp_data.empty:
                                if 'RecordId' in temp_data.columns:
                                    temp_data = temp_data.drop('RecordId', axis=1)

                                if 'Operator' in temp_data.columns:
                                    temp_data = temp_data.drop('Operator', axis=1)

                                temp_data['Measure_ID'] = new_measure_id

                                if new_msk is not None:
                                    temp_data['MSK'] = new_msk

                                temp_data.to_sql('psidatatemp', conn, if_exists='append', index=False)
                                total_temp_copied += len(temp_data)

                            break

                except Exception as e:
                    logging.exception(f"✗ Ошибка при копировании бракованного номера {number}: {e}")
                    continue

        logging.info(f"\n Скопировано {total_psi_copied} бракованных записей в psidata")
        logging.info(f" Скопировано {total_temp_copied} бракованных записей в psidatatemp")

        return total_psi_copied, total_temp_copied

    except Exception as e:
        logging.exception(f"✗ Ошибка при копировании бракованных данных: {e}")
        return 0, 0


def get_table_counts(engine, measure_id):
    try:
        with engine.connect() as conn:
            psi_count_sql = text("SELECT COUNT(*) as count FROM psidata WHERE Measure_ID = :measure_id")
            psi_result = conn.execute(psi_count_sql, {'measure_id': measure_id})
            psi_count = psi_result.fetchone()[0]

            temp_count_sql = text("SELECT COUNT(*) as count FROM psidatatemp WHERE Measure_ID = :measure_id")
            temp_result = conn.execute(temp_count_sql, {'measure_id': measure_id})
            temp_count = temp_result.fetchone()[0]

            return psi_count, temp_count

    except Exception as e:
        logging.exception(f" Ошибка при получении счетчиков: {e}")
        return 0, 0


def show_progress(current, total, prefix="", length=50):
    percent = current / total
    filled_length = int(length * percent)
    bar = "█" * filled_length + "─" * (length - filled_length)
    sys.stdout.write(f"\r{prefix} |{bar}| {current}/{total} ({percent:.1%})")
    sys.stdout.flush()

    if current == total:
        print()


def get_all_numbers_from_measure_ids(engine, measure_ids):
    all_numbers = set()

    for measure_id in measure_ids:
        try:
            with engine.connect() as conn:
                sql = text("SELECT DISTINCT N FROM psidata WHERE Measure_ID = :measure_id")
                result = conn.execute(sql, {'measure_id': measure_id})
                numbers = [row[0] for row in result]
                all_numbers.update(numbers)
        except Exception as e:
            logging.exception(f"✗ Ошибка при получении номеров из Measure_ID {measure_id}: {e}")

    return all_numbers


def get_rejected_numbers(engine, measure_ids, valid_numbers_df):
    all_numbers = get_all_numbers_from_measure_ids(engine, measure_ids)

    logging.info(f'Valid Numbers: {valid_numbers_df}')
    logging.info(f'All Numbers: {all_numbers}')

    valid_numbers_set = set(valid_numbers_df['Numbers'].unique())
    rejected_numbers = all_numbers - valid_numbers_set

    logging.info(f"   Статистика по номерам:")
    logging.info(f"   Всего номеров в исходных замерах: {len(all_numbers)}")
    logging.info(f"   Годных номеров: {len(valid_numbers_set)}")
    logging.info(f"   Бракованных номеров: {len(rejected_numbers)}")

    return rejected_numbers


# ===== Функция для получения детальной информации о браке =====
def get_failed_details(full_df):
    """
    Из объединённого датафрейма (со статусами, значениями и нормами)
    возвращает словарь {номер: [{'Параметр':, 'Значение':, 'Min':, 'Max':}, ...]}
    """
    failed_items = {}
    # Определяем все колонки со статусами (не аномальные)
    status_cols = [col for col in full_df.columns if col.endswith('_status') and not col.endswith('_anomal_status')]
    param_names = [col.replace('_status', '') for col in status_cols]

    for _, row in full_df.iterrows():
        number = row['Numbers']
        if row['Status'] == False:  # брак
            params_info = []
            for param in param_names:
                status_col = f"{param}_status"
                if row[status_col] == False:
                    # Получаем значение параметра (из колонки с именем параметра)
                    value = row[param] if param in row else None
                    # Нормы хранятся в колонках param_Min и param_Max (добавляем при объединении)
                    min_col = f"{param}_Min"
                    max_col = f"{param}_Max"
                    min_val = row[min_col] if min_col in row else None
                    max_val = row[max_col] if max_col in row else None
                    params_info.append({
                        'Параметр': param,
                        'Значение': value,
                        'Min': min_val,
                        'Max': max_val
                    })
            if params_info:
                failed_items[number] = params_info
    return failed_items
# ==================================================


def process_measure_ids_with_copy(measure_ids, msk=None, program_type=None, operator=None, psi_type='ОТК'):
    """Основная функция для обработки списка Measure_ID с копированием в новый замер"""
    engine = create_engine(str(Options.get_connection_string()))

    psi_type = psi_type if psi_type in ('ПСИ', 'ОТК') else 'ОТК'
    logging.info(f"   Тип протокола (psi_type): {psi_type}")

    psi_map_sql = "SELECT * FROM psidata_map_table"
    psi_map = pd.read_sql(psi_map_sql, engine)

    column_mapping = dict(zip(psi_map['Field'], psi_map['Parameter']))

    all_results = []          # для годных изделий (используется позже)
    all_valid_numbers = []    # для годных номеров с Measure_ID
    all_merged_dfs = []       # объединённые датафреймы (статусы + значения + нормы)

    logging.info(" Начало обработки Measure_ID...")
    logging.info(f" Параметры обновления:")
    logging.info(f"   MSK: {msk}")
    logging.info(f"   Program_Type: {program_type}")
    logging.info(f"   Operator: {operator}")

    if program_type:
        try:
            machine_sql = f"SELECT * FROM machines WHERE Name = '{program_type}'"
            machine_data = pd.read_sql(machine_sql, engine)
            if not machine_data.empty:
                machine_data = machine_data.iloc[0]
                logging.info(f"   Данные машины '{program_type}':")
                logging.info(f"     Serial_N: {machine_data.get('Serial_N', 'не указан')}")
                logging.info(f"     Call_Date: {machine_data.get('Call_Date', 'не указана')}")
                logging.info(f"     M_Type: {machine_data.get('M_Type', 'не указан')}")
                logging.info(f"     Type: {machine_data.get('Type', 'не указан')}")
                if machine_data.get('Type') == 'Transat':
                    logging.info(f"     MachineType будет установлен как: CNA-300")
            else:
                logging.warning(f"   Внимание: машина '{program_type}' не найдена в таблице machines")
        except Exception as e:
            logging.exception(f"   Ошибка при получении данных машины: {e}")

    for i, measure_id in enumerate(measure_ids):
        logging.info(f"\n Обработка Measure_ID: {measure_id} ({i + 1}/{len(measure_ids)})")

        show_progress(0, 1, f"Загрузка данных для Measure_ID {measure_id}")

        psi_sql = f"SELECT * FROM psidata WHERE Measure_ID = {measure_id}"
        psi_data = pd.read_sql(psi_sql, engine)

        if psi_data.empty:
            logging.warning(f" Данные для Measure_ID {measure_id} не найдены")
            continue

        psi_data_renamed = psi_data.rename(columns=column_mapping)

        show_progress(0.3, 1, f"Обработка спецификаций для Measure_ID {measure_id}")

        unique_spc = psi_data_renamed['Spc'].unique()

        for spc_name in unique_spc:
            logging.info(f"    Обработка спецификации: {spc_name}")

            spec_sql = f"SELECT * FROM specification WHERE Name = '{spc_name}'"
            spec_data = pd.read_sql(spec_sql, engine)

            if spec_data.empty:
                logging.warning(f"   Спецификация {spc_name} не найдена")
                continue

            spc_mapped = load_spc_map(spec_data.iloc[0])
            map_spc_otk = create_spc_map_otk(spc_mapped, spec_data.iloc[0])

            spc_psi_data = psi_data_renamed[psi_data_renamed['Spc'] == spc_name]

            result_df, result_df2, stats_df, result_anomal = set_specification_to_data(
                map_spc_otk, spc_psi_data
            )

            # Добавляем Measure_ID к результатам
            result_df['Measure_ID'] = measure_id
            result_df2['Measure_ID'] = measure_id

            # --- Объединяем result_df (статусы) и result_df2 (значения) ---
            merged = pd.merge(result_df, result_df2, on=['Numbers', 'Positions', 'Measure_ID'], suffixes=('', '_val'))
            # Добавляем нормы из map_spc_otk
            norms = map_spc_otk.set_index('Parameter')[['Min', 'Max']]
            for param in norms.index:
                merged[f"{param}_Min"] = norms.loc[param, 'Min']
                merged[f"{param}_Max"] = norms.loc[param, 'Max']

            all_merged_dfs.append(merged)

            # Сохраняем только годные изделия
            valid_items = result_df[result_df['Status'] == True][['Numbers', 'Measure_ID', 'Status']]
            all_results.append(valid_items)
            all_valid_numbers.extend(valid_items[['Numbers', 'Measure_ID']].to_dict('records'))

        show_progress(1, 1, f"Завершено для Measure_ID {measure_id}")

    # Объединяем годные результаты
    if all_results:
        final_result = pd.concat(all_results, ignore_index=True)
        valid_numbers_df = pd.DataFrame(all_valid_numbers)
    else:
        final_result = pd.DataFrame(columns=['Numbers', 'Measure_ID', 'Status'])
        valid_numbers_df = pd.DataFrame(columns=['Numbers', 'Measure_ID'])

    # ===== ВЫВОД ДЕТАЛЬНОГО ОТЧЁТА ПО БРАКУ (ТОЛЬКО В ЛОГ-ФАЙЛ) =====
    if all_merged_dfs:
        combined = pd.concat(all_merged_dfs, ignore_index=True)
        failed_details = get_failed_details(combined)
        if failed_details:
            logging.info("=== Детальная информация по бракованным изделиям ===")
            for number, params in failed_details.items():
                logging.info(f"Номер {number}:")
                for p in params:
                    norm_str = f"{p['Min']} .. {p['Max']}" if p['Min'] is not None and p['Max'] is not None else "норма не задана"
                    logging.info(f"  {p['Параметр']} = {p['Значение']} (норма: {norm_str})")
        else:
            logging.info("Бракованных изделий не найдено.")

    # ===== ПРОВЕРКА НАЛИЧИЯ ГОДНЫХ (вывод в консоль через print) =====
    if final_result.empty:
        print("Нет годных изделий. Дальнейшие операции (создание нового замера, копирование) не производятся.")
        return None, 0, 0

    logging.info(f"\n Обработка завершена. Найдено {len(final_result)} годных изделий")

    # Создаём новый замер и копируем данные (только если есть годные)
    logging.info("\n Создание нового замера...")

    new_measure_id = create_new_measure_id(engine, measure_ids, msk, program_type, operator)

    if new_measure_id:
        logging.info("\n Копирование данных в новый замер...")

        psi_count = copy_psi_data(
            engine, measure_ids, valid_numbers_df, new_measure_id,
            msk, operator, program_type, psi_type,  # ← +psi_type
        )
        temp_count = copy_psidatatemp_data(engine, measure_ids, valid_numbers_df, new_measure_id, msk)

        rejected_numbers = get_rejected_numbers(engine, measure_ids, valid_numbers_df)
        if rejected_numbers:
            logging.info("\n Копирование бракованных изделий...")
            rejected_psi_count, rejected_temp_count = copy_rejected_data(
                engine, measure_ids, rejected_numbers, new_measure_id,
                msk, operator, program_type, psi_type,  # ← +psi_type
            )
        else:
            rejected_psi_count, rejected_temp_count = 0, 0

        final_psi_count, final_temp_count = get_table_counts(engine, new_measure_id)

        logging.info(f"\n  Новый замер успешно создан!")
        logging.info(f"    Тип протокола: {psi_type}")  # ← NEW в итоговом логе
        logging.info(f"    Measure_ID: {new_measure_id}")
        if msk:
            logging.info(f"    MSK: {msk}")
        if program_type:
            logging.info(f"    Program_Type: {program_type}")
            try:
                machine_sql = f"SELECT * FROM machines WHERE Name = '{program_type}'"
                machine_data = pd.read_sql(machine_sql, engine)
                if not machine_data.empty:
                    machine_data = machine_data.iloc[0]
                    logging.info(f"    Примененные данные машины:")
                    logging.info(f"      Serial_N: {machine_data.get('Serial_N', 'не указан')}")
                    logging.info(f"      Call_Date: {machine_data.get('Call_Date', 'не указана')}")
                    logging.info(f"      M_Type: {machine_data.get('M_Type', 'не указан')}")
                    machine_type = machine_data.get('Type', 'не указан')
                    if machine_type == 'Transat':
                        logging.info(f"      MachineType: CNA-300 (Transat)")
                    else:
                        logging.info(f"      MachineType: {machine_type}")
            except:
                pass
        if operator:
            logging.info(f"    Operator: {operator}")
        logging.info(f"    Записей в psidata: {final_psi_count}")
        logging.info(f"    Записей в psidatatemp: {final_temp_count}")
        logging.info(f"    Годных изделий: {psi_count}")
        logging.info(f"    Бракованных изделий: {rejected_psi_count}")

        logging.info(f"\n Уникальные изделия в новом замере:")

        with engine.connect() as conn:
            unique_numbers_sql = text("SELECT DISTINCT N FROM psidata WHERE Measure_ID = :measure_id ORDER BY N")
            result = conn.execute(unique_numbers_sql, {'measure_id': new_measure_id})
            unique_numbers = [row[0] for row in result]

            for idx, number in enumerate(unique_numbers):
                logging.info(f"   {idx + 1:3d}. {number}")

        return new_measure_id, final_psi_count, final_temp_count

    return None, 0, 0


# ============================================================================
#   Поиск замеров по номеру резонатора / частичному МСК (основной замер)
# ============================================================================

def _safe_sql_str(s) -> str:
    """Экранирование одинарных кавычек для подстановки в SQL."""
    return str(s).replace("'", "''")


def _get_archive_lookup_module():
    """Archive_Lookup из любого из двух возможных пакетов."""
    try:
        from Archive_View import Archive_Lookup
        return Archive_Lookup
    except ImportError:
        pass
    try:
        from Temperature_Measure.Archive import Archive_Lookup
        return Archive_Lookup
    except ImportError:
        pass
    logging.info("[search] Archive_Lookup недоступен — "
                 "поиск пойдёт напрямую по psidata")
    return None


def _get_search_archive_msk():
    """search_archive_msk из любого из двух возможных пакетов."""
    for mod_path in (
        'Temperature_Measure.Archive.Archive_Data',
        'Archive_View.Archive_Data',
    ):
        try:
            mod = __import__(mod_path, fromlist=['search_archive_msk'])
            return getattr(mod, 'search_archive_msk', None)
        except (ImportError, AttributeError):
            continue
    return None


def _get_engine(engine=None):
    """Вернуть переданный engine или создать из Options."""
    if engine is not None:
        return engine
    return create_engine(str(Options.get_connection_string()))


# ---------------------------------------------------------------------------
#                       Поиск МСК по подстроке
# ---------------------------------------------------------------------------
def search_msk_by_partial(partial, limit: int = 200, engine=None) -> list:
    """Поиск МСК по частичному совпадению.

    Сначала пробует `search_archive_msk` из архивного модуля (если
    доступен), затем — прямой SQL-запрос к `psidata`. Возвращает
    список строк, отсортированный по МСК.
    """
    if not partial or not str(partial).strip():
        return []
    partial_s = str(partial).strip()
    limit = int(limit)

    # 1) архивный справочник
    search_fn = _get_search_archive_msk()
    if search_fn is not None:
        try:
            matches = search_fn(partial_s)
            if matches:
                return list(matches)[:limit]
        except Exception as e:
            logging.warning(f"[search_msk_by_partial] archive error: {e}")

    # 2) fallback — прямой SQL по psidata
    eng = _get_engine(engine)
    safe = _safe_sql_str(partial_s)
    sql = (
        f"SELECT DISTINCT Msk FROM psidata "
        f"WHERE Msk LIKE '%{safe}%' "
        f"  AND Msk IS NOT NULL AND Msk <> '' "
        f"ORDER BY Msk LIMIT {limit}"
    )
    logging.info(f"[search_msk_by_partial] SQL: {sql}")
    try:
        df = pd.read_sql(sql, eng)
        return df['Msk'].dropna().astype(str).tolist()
    except Exception as e:
        logging.exception(f"[search_msk_by_partial] SQL error: {e}")
        return []


# ---------------------------------------------------------------------------
#              Поиск Measure_ID по частичному МСК (основной замер)
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
#              Поиск Measure_ID по частичному МСК (основной замер)
# ---------------------------------------------------------------------------
def search_measure_ids_by_msk_partial(partial_msk, limit: int = 200,
                                       engine=None) -> pd.DataFrame:
    """Замеры для МСК, найденного поиском (как в модуле Архив).

    Ключевое отличие от поиска по подстроке: здесь МСК уже выбран
    оператором из combo, поэтому фильтр — ТОЧНОЕ совпадение
    `MSK = :msk` (как `load_measure_ids_by_msk` в Archive_Data),
    а не `LIKE '%…%'`.

    Возвращает DataFrame:
        Measure_ID, Sample_N, MSK, Spc, Date, N_Count
    Отсортировано по Measure_ID DESC (свежие сверху).
    """
    if not partial_msk or not str(partial_msk).strip():
        return pd.DataFrame()

    eng = _get_engine(engine)
    msk = str(partial_msk).strip()
    safe = _safe_sql_str(msk)
    limit = int(limit)

    sql = (
        "SELECT Measure_ID, MIN(N) AS Sample_N, MIN(MSK) AS MSK, "
        "MIN(Spc) AS Spc, MIN(Date) AS Date, COUNT(*) AS N_Count "
        "FROM psidata "
        f"WHERE MSK = '{safe}' "
        "  AND Measure_ID IS NOT NULL "
        "  AND MSK IS NOT NULL "
        "GROUP BY Measure_ID "
        "ORDER BY Measure_ID DESC "
        f"LIMIT {limit}"
    )
    logging.info(f"[search_measure_ids_by_msk_partial] SQL: {sql}")
    try:
        return pd.read_sql(sql, eng)
    except Exception as e:
        logging.exception(
            f"[search_measure_ids_by_msk_partial] SQL error: {e}")
        return pd.DataFrame()

def search_measure_ids_by_msk_partial_1(partial_msk, limit: int = 200,
                                       engine=None) -> pd.DataFrame:
    """Поиск замеров по частичному МСК.

    Возвращает DataFrame:
        Measure_ID, MSK, Spc, Date, N_Count
    Отсортировано по Measure_ID DESC (свежие сверху).
    """
    if not partial_msk or not str(partial_msk).strip():
        return pd.DataFrame()

    eng = _get_engine(engine)
    safe = _safe_sql_str(str(partial_msk).strip())
    limit = int(limit)
    sql = (
        "SELECT Measure_ID, MIN(MSK) AS MSK, MIN(Spc) AS Spc, "
        "MIN(Date) AS Date, COUNT(*) AS N_Count "
        "FROM psidata "
        f"WHERE MSK LIKE '%{safe}%' "
        "  AND Measure_ID IS NOT NULL "
        "  AND MSK IS NOT NULL "
        "GROUP BY Measure_ID "
        "ORDER BY Measure_ID DESC "
        f"LIMIT {limit}"
    )
    logging.info(f"[search_measure_ids_by_msk_partial] SQL: {sql}")
    try:
        return pd.read_sql(sql, eng)
    except Exception as e:
        logging.exception(
            f"[search_measure_ids_by_msk_partial] SQL error: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
#           Поиск Measure_ID по подстроке номера резонатора (N)
# ---------------------------------------------------------------------------
def search_measure_ids_by_number_partial(partial, limit: int = 500,
                                          engine=None) -> pd.DataFrame:
    """Поиск основных замеров по подстроке номера резонатора.

    Использует `Archive_Lookup` (если доступен) + fallback на
    `psidata.N LIKE '%partial%'` + self-heal справочника — точно так
    же, как в модуле старения `aging_logic`.

    Возвращает DataFrame:
        Measure_ID, Sample_N, MSK, Date, Numbers_Count
    Отсортировано по Measure_ID DESC (свежие сверху).
    """
    if partial is None or not str(partial).strip():
        return pd.DataFrame()

    eng = _get_engine(engine)
    limit = int(limit)

    partial_s = str(partial).strip()
    upper = partial_s.upper()
    safe_upper = _safe_sql_str(upper)
    safe_like = _safe_sql_str(f'%{partial_s}%')

    Lookup = _get_archive_lookup_module()
    mids_from_lookup = set()
    lookup_ok = False

    # ---------------------------------------------------------- 1) lookup
    if Lookup is not None:
        try:
            Lookup.ensure_lookup_table(eng)
            sql_lk = (
                f"SELECT DISTINCT measure_id "
                f"FROM `{Lookup.LOOKUP_TABLE}` "
                f"WHERE n_normalized LIKE '%{safe_upper}%' "
                f"LIMIT {limit}"
            )
            logging.info(f"[search_by_number] lookup SQL: {sql_lk}")
            df_lk = pd.read_sql(sql_lk, eng)
            mids_from_lookup = {
                int(x) for x in df_lk['measure_id'].dropna().unique()
            }
            lookup_ok = True
            logging.info(f"[search_by_number] lookup: "
                         f"{len(mids_from_lookup)} ids")
        except Exception as e:
            logging.warning(f"[search_by_number] lookup error: {e}")

    # --------------------------- 2) решаем, нужен ли fallback
    lookup_empty = len(mids_from_lookup) == 0
    lookup_truncated = len(mids_from_lookup) >= limit
    need_fallback = (not lookup_ok) or lookup_empty or lookup_truncated

    mids_from_fallback = set()
    fallback_pairs = []

    if need_fallback:
        reason = (
            'lookup unavailable' if not lookup_ok
            else 'lookup empty' if lookup_empty
            else f'lookup truncated ({len(mids_from_lookup)}={limit})'
        )
        logging.info(f"[search_by_number] fallback REQUIRED ({reason})")
        try:
            sql_fb = (
                "SELECT Measure_ID, UPPER(TRIM(N)) AS N_norm "
                "FROM psidata "
                f"WHERE N LIKE '{safe_like}' "
                "  AND Measure_ID IS NOT NULL "
                "  AND N IS NOT NULL "
                "  AND TRIM(N) <> '' "
                "LIMIT 20000"
            )
            logging.info(f"[search_by_number] fallback SQL: {sql_fb}")
            df_fb = pd.read_sql(sql_fb, eng)
            for _, r in df_fb.iterrows():
                try:
                    mid = int(r['Measure_ID'])
                except (TypeError, ValueError):
                    continue
                n_norm = str(r.get('N_norm') or '').strip().upper()
                if not n_norm:
                    continue
                mids_from_fallback.add(mid)
                fallback_pairs.append((mid, n_norm))
            logging.info(f"[search_by_number] fallback: "
                         f"{len(mids_from_fallback)} ids")
        except Exception as e:
            logging.exception(f"[search_by_number] fallback error: {e}")

        # self-heal
        if Lookup is not None and lookup_ok and fallback_pairs:
            missing = [(m, n) for m, n in fallback_pairs
                       if m not in mids_from_lookup]
            if missing:
                try:
                    added = Lookup.add_pairs_to_lookup(missing, engine=eng)
                    logging.info(f"[search_by_number] self-heal: "
                                 f"+{added} pairs")
                except Exception as e:
                    logging.warning(f"[search_by_number] self-heal error: {e}")

    all_mids = mids_from_lookup | mids_from_fallback
    if not all_mids:
        return pd.DataFrame()

    # --------------------------------- 3) детали по measure_ids
    from sqlalchemy import bindparam, text as sqltext
    mids_list = sorted(all_mids)[:limit]
    stmt = sqltext(
        "SELECT Measure_ID, MIN(N) AS Sample_N, MIN(MSK) AS MSK, "
        "MIN(Date) AS Date, COUNT(*) AS Numbers_Count "
        "FROM psidata "
        "WHERE Measure_ID IN :mids "
        f"  AND N LIKE '{safe_like}' "
        "GROUP BY Measure_ID "
        "ORDER BY Measure_ID DESC"
    ).bindparams(bindparam("mids", expanding=True))

    try:
        return pd.read_sql(stmt, eng, params={'mids': mids_list})
    except Exception as e:
        logging.exception(f"[search_by_number] details error: {e}")
        return pd.DataFrame()


# ---------------------------------------------------------------------------
#             Сводка по выбранному основному замеру (для UI)
# ---------------------------------------------------------------------------
def get_measure_summary(measure_id, engine=None) -> dict:
    """Краткая информация о замере — для панели «Основной замер».

    Возвращает dict:
        measure_id, msk, spc, date, file, n_count,
        program_type, operator, protocol_n
    Пустой dict, если Measure_ID некорректен.
    """
    try:
        mid = int(str(measure_id).strip())
    except (TypeError, ValueError):
        return {}

    eng = _get_engine(engine)
    info = {'measure_id': mid}

    try:
        sql = (
            "SELECT MIN(MSK) AS MSK, MIN(Spc) AS Spc, "
            "MIN(Date) AS Date, MIN(File) AS File, "
            "COUNT(*) AS N_Count "
            f"FROM psidata WHERE Measure_ID = {mid}"
        )
        df = pd.read_sql(sql, eng)
        if not df.empty and int(df.iloc[0].get('N_Count') or 0) > 0:
            r = df.iloc[0]
            info.update({
                'msk': r['MSK'],
                'spc': r['Spc'],
                'date': r['Date'],
                'file': r['File'],
                'n_count': int(r['N_Count']),
            })
    except Exception as e:
        logging.warning(f"[get_measure_summary] psidata: {e}")

    try:
        sql2 = (
            "SELECT Program_Type, Operator, ProtokolN "
            f"FROM psi_measure_id WHERE MeasureID = {mid}"
        )
        df2 = pd.read_sql(sql2, eng)
        if not df2.empty:
            r = df2.iloc[0]
            info['program_type'] = r.get('Program_Type')
            info['operator'] = r.get('Operator')
            info['protocol_n'] = r.get('ProtokolN')
    except Exception as e:
        logging.warning(f"[get_measure_summary] psi_measure_id: {e}")

    return info


def format_measure_combo_label(row) -> str:
    """Строка для combo-выбора замера из результата поиска.

    Пример: "253799 | N=SU8525 | 456 | СПЕКТР-1 | 2023-06-30 | N=12"
    """
    def _s(key):
        v = row.get(key) if hasattr(row, 'get') else None
        if v is None:
            return ''
        try:
            if pd.isna(v):
                return ''
        except (TypeError, ValueError):
            pass
        return str(v).strip()

    try:
        mid = str(int(row['Measure_ID']))
    except (KeyError, TypeError, ValueError):
        return str(row)

    parts = [mid]
    for key, prefix in (
        ('Sample_N', 'N='),
        ('MSK', ''),
        ('Spc', ''),
        ('Date', ''),
    ):
        val = _s(key)
        if val:
            parts.append(f"{prefix}{val}")
    for key in ('Numbers_Count', 'N_Count'):
        cnt = row.get(key) if hasattr(row, 'get') else None
        if cnt is not None and pd.notna(cnt):
            try:
                parts.append(f"N={int(cnt)}")
                break
            except (TypeError, ValueError):
                pass
    return " | ".join(parts)


if __name__ == "__main__":
    measure_ids = [253799, 253216]

    start_time = time.time()

    new_measure_id, psi_count, temp_count = process_measure_ids_with_copy(measure_ids)

    end_time = time.time()
    execution_time = end_time - start_time

    logging.info(f"\n️ Общее время выполнения: {execution_time:.2f} секунд")

    if new_measure_id:
        logging.info(f"\n Готово! Новый замер {new_measure_id} создан успешно.")
    else:
        logging.error(f"\n Создание нового замера не удалось.")