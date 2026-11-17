"""Логика совмещения протоколов измерений.

Все функции находятся в одном модуле, чтобы избежать циклических
импортов и ошибок NameError / Unresolved reference при вызове
create_new_protocol из save_merged_protocol.
"""
import pandas as pd
from sqlalchemy import text

from .db import (
    execute_query,
    execute_many_updates,   # реэкспорт для обратной совместимости
    insert_and_get_id,
    get_engine,
)


# ============================================================================
#                     1. Загрузка справочных данных
# ============================================================================

def load_resonator_types() -> list[str]:
    """Список типов резонаторов."""
    df = execute_query("SELECT `Type` FROM ResonatorType")
    return df['Type'].tolist()


def load_specifications(resonator_type: str) -> list[str]:
    """Список спецификаций для заданного типа резонатора."""
    if not resonator_type:
        return []
    # Параметризация вручную (execute_query принимает готовый SQL)
    safe = str(resonator_type).replace("'", "''")
    query = (
        f"SELECT `Name` FROM specification "
        f"WHERE NameR = '{safe}' ORDER BY `Name`"
    )
    df = execute_query(query)
    return df['Name'].tolist()


def load_msk_from_psidata(spc: str) -> list[str]:
    """Список МСК, встречающихся в psidata для спецификации."""
    if not spc:
        return []
    safe = str(spc).replace("'", "''")
    query = (
        f"SELECT DISTINCT Msk FROM psidata "
        f"WHERE Spc = '{safe}' ORDER BY Msk"
    )
    df = execute_query(query)
    return df['Msk'].tolist()


def load_measure_ids_from_psidata(spc: str, msk: str = None) -> list:
    """Список Measure_ID из psidata по спецификации и (опц.) МСК."""
    if not spc:
        return []
    safe_spc = str(spc).replace("'", "''")
    where = f"Spc = '{safe_spc}'"
    if msk:
        safe_msk = str(msk).replace("'", "''")
        where += f" AND Msk = '{safe_msk}'"
    query = (
        f"SELECT DISTINCT Measure_ID FROM psidata "
        f"WHERE {where} ORDER BY Measure_ID"
    )
    df = execute_query(query)
    return df['Measure_ID'].tolist()

def load_measure_ids_from_old(
    spc: str = None,
    msk: str = None,
    old_id: str = None,
) -> list:
    """Уникальные MeasureID из old по одному или нескольким фильтрам."""
    conditions = []
    if spc:
        conditions.append(f"Spc = '{str(spc).replace(chr(39), chr(39) * 2)}'")
    if msk:
        conditions.append(f"Msk = '{str(msk).replace(chr(39), chr(39) * 2)}'")
    if old_id:
        conditions.append(f"Old_ID = '{str(old_id).replace(chr(39), chr(39) * 2)}'")
    if not conditions:
        return []
    query = (
        "SELECT DISTINCT MeasureID FROM old "
        f"WHERE {' AND '.join(conditions)} ORDER BY MeasureID"
    )
    try:
        df = execute_query(query)
        return df['MeasureID'].dropna().tolist()
    except Exception as e:
        print(f"[load_measure_ids_from_old] error: {e}")
        return []


def load_old_ids_from_old(
    spc: str = None,
    msk: str = None,
    measure_id: str = None,
) -> list:
    """Уникальные Old_ID из old по одному или нескольким фильтрам."""
    conditions = []
    if spc:
        conditions.append(f"Spc = '{str(spc).replace(chr(39), chr(39) * 2)}'")
    if msk:
        conditions.append(f"Msk = '{str(msk).replace(chr(39), chr(39) * 2)}'")
    if measure_id:
        conditions.append(
            f"MeasureID = '{str(measure_id).replace(chr(39), chr(39) * 2)}'"
        )
    if not conditions:
        return []
    query = (
        "SELECT DISTINCT Old_ID FROM old "
        f"WHERE {' AND '.join(conditions)} ORDER BY Old_ID"
    )
    try:
        df = execute_query(query)
        return df['Old_ID'].dropna().tolist()
    except Exception as e:
        print(f"[load_old_ids_from_old] error: {e}")
        return []

def load_old_meta_by_measure_id(measure_id) -> dict:
    """Из old по MeasureID: возвращает первую пару {msk, old_id}."""
    if not measure_id:
        return {}
    safe = str(measure_id).replace("'", "''")
    query = (
        f"SELECT Msk, Old_ID FROM old WHERE MeasureID = '{safe}' LIMIT 1"
    )
    try:
        df = execute_query(query)
        if df.empty:
            return {}
        row = df.iloc[0]
        return {"msk": row.get("Msk"), "old_id": row.get("Old_ID")}
    except Exception as e:
        print(f"[load_old_meta_by_measure_id] error: {e}")
        return {}

def load_old_meta_by_old_id(old_id) -> dict:
    """Из old по Old_ID: возвращает первую пару {msk, measure_id}."""
    if not old_id:
        return {}
    safe = str(old_id).replace("'", "''")
    query = (
        f"SELECT Msk, MeasureID FROM old WHERE Old_ID = '{safe}' LIMIT 1"
    )
    try:
        df = execute_query(query)
        if df.empty:
            return {}
        row = df.iloc[0]
        return {"msk": row.get("Msk"), "measure_id": row.get("MeasureID")}
    except Exception as e:
        print(f"[load_old_meta_by_old_id] error: {e}")
        return {}



def load_msk_from_old(spc: str = None) -> list[str]:
    """Уникальные Msk из таблицы old (опц. — по Spc)."""
    conditions = []
    if spc:
        conditions.append(f"Spc = '{str(spc).replace(chr(39), chr(39) * 2)}'")
    if not conditions:
        return []
    query = (
        "SELECT DISTINCT Msk FROM old "
        f"WHERE {' AND '.join(conditions)} ORDER BY Msk"
    )
    try:
        df = execute_query(query)
        return df['Msk'].dropna().tolist()
    except Exception as e:
        print(f"[load_msk_from_old] error: {e}")
        return []



def load_main_data(
    spc: str,
    msk: str = None,
    measure_id: str = None,
) -> pd.DataFrame:
    """Данные основного замера из psidata."""
    if not spc:
        return pd.DataFrame()
    conditions = [f"Spc = '{str(spc).replace(chr(39), chr(39) * 2)}'"]
    if msk:
        conditions.append(f"Msk = '{str(msk).replace(chr(39), chr(39) * 2)}'")
    if measure_id:
        conditions.append(
            f"Measure_ID = '{str(measure_id).replace(chr(39), chr(39) * 2)}'"
        )
    where = " AND ".join(conditions)
    query = f"SELECT * FROM psidata WHERE {where} ORDER BY N"
    return execute_query(query)


def load_secondary_data(
    spc: str,
    msk: str = None,
    measure_id: str = None,
) -> pd.DataFrame:
    """Данные дополнительного замера (тот же psidata)."""
    return load_main_data(spc, msk, measure_id)

def load_old_data(
    msk: str = None,
    measure_id: str = None,
    old_id: str = None,
) -> pd.DataFrame:
    """Данные старения из таблицы old."""
    conditions = []
    if msk:
        conditions.append(f"Msk = '{str(msk).replace(chr(39), chr(39) * 2)}'")
    if measure_id:
        conditions.append(
            f"MeasureID = '{str(measure_id).replace(chr(39), chr(39) * 2)}'"
        )
    if old_id:
        conditions.append(
            f"Old_ID = '{str(old_id).replace(chr(39), chr(39) * 2)}'"
        )

    if not conditions:
        print("[load_old_data] все фильтры пусты — пустой df "
              "(не тянуть всю таблицу old)")
        return pd.DataFrame()

    where = " AND ".join(conditions)
    query = f"SELECT * FROM old WHERE {where} ORDER BY N"
    print(f"[load_old_data] SQL: {query}")

    try:
        df = execute_query(query)
    except Exception as e:
        print(f"[load_old_data] SQL error: {e}")
        return pd.DataFrame()

    print(f"[load_old_data] результат: {len(df)} строк, "
          f"колонки: {df.columns.tolist() if not df.empty else '—'}")
    return df


# ============================================================================
#                          2. Функции слияния
# ============================================================================
def merge_psidata(
    main_df: pd.DataFrame,
    secondary_df: pd.DataFrame,
    add_spur: bool = False,
    only_spur: bool = False,
) -> pd.DataFrame:
    """Сливает дополнительный замер в основной по колонке N.

    Параметры:
    ----------
    add_spur : bool
        Добавить колонки Spur / Rsp1-Rsp3 / FSpur1-FSpur3
        в дополнение к F, R, C0, Cq, L, Q.
    only_spur : bool
        Если True — переносятся ТОЛЬКО spur-колонки.
        F, R, C0, Cq, L, Q остаются из основного замера.
        Имеет приоритет над add_spur.
    """
    if secondary_df is None or secondary_df.empty:
        return main_df

    spur_cols = [
        'Spur', 'Rsp1', 'Rsp2', 'Rsp3',
        'FSpur1', 'FSpur2', 'FSpur3',
    ]

    if only_spur:
        value_cols = spur_cols
    else:
        value_cols = ['F', 'R', 'C0', 'Cq', 'L', 'Q']
        if add_spur:
            value_cols.extend(spur_cols)

    sec_value_cols = [c for c in value_cols if c in secondary_df.columns]
    if not sec_value_cols:
        return main_df

    print(f"[merge_psidata] перенос колонок: {sec_value_cols} "
          f"(only_spur={only_spur}, add_spur={add_spur})")

    sec_subset = secondary_df[['N'] + sec_value_cols].copy()
    sec_subset = sec_subset.rename(
        columns={c: f"{c}_new" for c in sec_value_cols}
    )

    main_value_cols = [c for c in sec_value_cols if c in main_df.columns]
    main_subset = main_df[['N'] + main_value_cols].copy()

    merged = main_subset.merge(sec_subset, on='N', how='left')

    for col in sec_value_cols:
        new_col = f"{col}_new"
        if new_col not in merged.columns:
            continue
        if col in main_df.columns:
            main_df[col] = merged[new_col].combine_first(main_df[col])
        else:
            main_df[col] = merged[new_col]

    return main_df



def merge_old(
    main_df: pd.DataFrame,
    old_df: pd.DataFrame,
    aging_type: int,
) -> pd.DataFrame:
    """Добавляет колонку Old из old{1|2|3}."""
    if old_df is None or old_df.empty:
        print("[merge_old] old_df пуст — пропуск")
        return main_df

    if 'N' not in old_df.columns:
        print(f"[merge_old] в old_df нет колонки N. "
              f"Колонки: {old_df.columns.tolist()}")
        return main_df

    # Ищем колонку old{aging_type} без учёта регистра:
    # в базе встречается Old1 / OLD1 / old1
    target = f'old{aging_type}'.lower()
    old_col = None
    for c in old_df.columns:
        if str(c).lower() == target:
            old_col = c
            break

    if old_col is None:
        print(f"[merge_old] не найдена колонка {target!r}. "
              f"Колонки old_df: {old_df.columns.tolist()}")
        return main_df

    print(f"[merge_old] использую колонку {old_col!r}")

    old_subset = old_df[['N', old_col]].copy()
    old_subset = old_subset.rename(columns={old_col: '_old_val'})

    merged = main_df[['N']].merge(old_subset, on='N', how='left')

    if 'Old' in main_df.columns:
        main_df['Old'] = merged['_old_val'].combine_first(main_df['Old'])
    else:
        main_df['Old'] = merged['_old_val']

    filled = int(main_df['Old'].notna().sum())
    print(f"[merge_old] заполнено Old: {filled} из {len(main_df)}")

    return main_df

# ============================================================================
#                       3. Создание нового протокола
# ============================================================================
import math
import numpy as np


def _safe_db_value(v):
    """Приводит значение к виду, который mysql-connector отправит
    как NULL, а не как литерал nan/inf/NaT.

    Ключевой момент: numpy-типы конвертируем в native Python —
    mysql-connector иначе может форматировать nan как SQL-идентификатор.
    """
    if v is None:
        return None

    # numpy floating / native float
    if isinstance(v, (float, np.floating)):
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv

    # numpy integer / native int / bool
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)

    # pandas Timestamp / NaT и прочее
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass

    return v

def load_psidata_by_measure_id(measure_id) -> pd.DataFrame:
    """Загрузить psidata только по Measure_ID.

    Используется как fallback, когда фильтр по Spc/Msk даёт пусто
    (несовпадение по регистру, пробелам или символам).
    """
    if measure_id is None or measure_id == "":
        return pd.DataFrame()

    # combo может вернуть tuple (label, value) — берём value
    if isinstance(measure_id, (tuple, list)) and len(measure_id) >= 2:
        measure_id = measure_id[1]

    try:
        mid_int = int(str(measure_id).strip())
    except (TypeError, ValueError):
        print(f"[load_psidata_by_measure_id] "
              f"не удалось привести к int: {measure_id!r}")
        return pd.DataFrame()

    query = (
        f"SELECT * FROM psidata WHERE Measure_ID = {mid_int} "
        f"ORDER BY N"
    )
    try:
        return execute_query(query)
    except Exception as e:
        print(f"[load_psidata_by_measure_id] SQL error: {e}")
        return pd.DataFrame()
def reserve_measure_id(
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
    notes: str = None,
) -> int:
    """INSERT в psi_measure_id → новый MeasureID.

    Пишет только заголовок протокола. Ничего в psidata не пишет.
    MSK может быть пустым — колонка nullable, ограничение по MSK
    проверяется на уровне save_merged_protocol.
    """
    if not protocol_number:
        raise ValueError("Не задан номер протокола")

    if notes is not None:
        notes = str(notes).strip() or None
        if notes and len(notes) > 200:
            print(f"[reserve_measure_id] Notes > 200 симв., обрезано")
            notes = notes[:200]

    insert_sql = """
        INSERT INTO psi_measure_id
            (MSK, ProtokolN, File, Program_Type, Operator,
             archive_flag, Notes)
        VALUES
            (:msk, :protocol_number, :file_name, :program_type,
             :operator, 0, :notes)
    """
    params = {
        'msk': msk or None,
        'protocol_number': protocol_number,
        'file_name': file_name,
        'program_type': program_type,
        'operator': operator_name,
        'notes': notes,
    }
    new_id = insert_and_get_id(insert_sql, params)
    if not new_id:
        raise RuntimeError(
            "Не удалось получить новый MeasureID из psi_measure_id"
        )
    print(f"[reserve_measure_id] MeasureID = {new_id}, "
          f"ProtokolN = {protocol_number!r}, notes = {notes!r}")
    return new_id


def save_merged_rows(
    merged_df: pd.DataFrame,
    measure_id: int,
    psi_type: str = 'ОТК',
    source_measure_id: int = None,
) -> int:
    """INSERT строк merged_df в psidata с заданным Measure_ID.

    Если задан source_measure_id — дополнительно копирует в psidatatemp
    строки температур из указанного замера-источника (основного).
    Совмещение меняет только psidata; температуры берутся без изменений.

    psi_measure_id не трогает — заголовок должен быть создан заранее
    через reserve_measure_id().
    """
    if merged_df is None or merged_df.empty:
        raise ValueError("merged_df пуст — сохранять нечего")
    if 'N' not in merged_df.columns:
        raise ValueError("В merged_df нет обязательной колонки 'N'")
    if not measure_id:
        raise ValueError("Не передан Measure_ID")

    mid = int(measure_id)
    psi_type = psi_type if psi_type in ('ПСИ', 'ОТК') else 'ОТК'

    engine = get_engine()

    df_copy = merged_df.copy()
    for pk in ('id', 'ID'):
        if pk in df_copy.columns:
            df_copy = df_copy.drop(columns=[pk])
    if 'Measure_ID' in df_copy.columns:
        df_copy = df_copy.drop(columns=['Measure_ID'])
    df_copy.insert(0, 'Measure_ID', mid)

    with engine.connect() as conn:
        result = conn.execute(text("DESCRIBE psidata"))
        target_columns = [row[0] for row in result]
        try:
            pk_rows = list(conn.execute(text(
                "SHOW KEYS FROM psidata WHERE Key_name = 'PRIMARY'")))
            pk_columns = {r[4] for r in pk_rows}
        except Exception:
            pk_columns = set()

    for pk in pk_columns:
        if pk in target_columns:
            target_columns.remove(pk)

    if 'psi_type' in target_columns:
        df_copy['psi_type'] = psi_type
        print(f"[save_merged_rows] psidata.psi_type = {psi_type!r} "
              f"(для {len(df_copy)} строк)")
    else:
        print("[save_merged_rows] В psidata нет колонки 'psi_type' — "
              "пропуск")

    cols_to_insert = [c for c in target_columns if c in df_copy.columns]
    if not cols_to_insert:
        raise RuntimeError(
            "Нет подходящих столбцов для вставки в psidata. "
            f"В df: {list(df_copy.columns)}; "
            f"в таблице: {target_columns}"
        )

    columns_sql = ','.join(f"`{c}`" for c in cols_to_insert)
    placeholders = ','.join(['%s'] * len(cols_to_insert))
    bulk_insert_sql = (
        f"INSERT INTO psidata ({columns_sql}) "
        f"VALUES ({placeholders})"
    )

    df_to_insert = df_copy[cols_to_insert]
    records = []
    nan_cells = 0
    for row in df_to_insert.itertuples(index=False, name=None):
        cleaned = []
        for v in row:
            cv = _safe_db_value(v)
            if cv is None and v is not None:
                nan_cells += 1
            cleaned.append(cv)
        records.append(tuple(cleaned))

    if nan_cells:
        print(f"[save_merged_rows] Заменено NaN/Inf на NULL: {nan_cells}")

    print(f"[save_merged_rows] Вставка {len(records)} строк в psidata "
          f"(MeasureID = {mid})...")

    with engine.begin() as conn:
        conn.exec_driver_sql(bulk_insert_sql, records)

    print(f"[save_merged_rows] УСПЕХ: MeasureID = {mid}, "
          f"строк = {len(records)}, psi_type = {psi_type!r}")

    # ▼ Копируем температуры основного замера в psidatatemp
    if source_measure_id:
        try:
            _copy_temperatures(engine, source_measure_id, mid)
        except Exception as e:
            print(f"[save_merged_rows] ПРЕДУПРЕЖДЕНИЕ: температуры "
                  f"не скопированы: {e}")

    return mid

def save_merged_rows_1(
    merged_df: pd.DataFrame,
    measure_id: int,
    psi_type: str = 'ОТК',
) -> int:
    """INSERT строк merged_df в psidata с заданным Measure_ID.

    psi_measure_id не трогает — заголовок должен быть создан заранее
    через reserve_measure_id().
    """
    if merged_df is None or merged_df.empty:
        raise ValueError("merged_df пуст — сохранять нечего")
    if 'N' not in merged_df.columns:
        raise ValueError("В merged_df нет обязательной колонки 'N'")
    if not measure_id:
        raise ValueError("Не передан Measure_ID")

    mid = int(measure_id)
    psi_type = psi_type if psi_type in ('ПСИ', 'ОТК') else 'ОТК'

    engine = get_engine()

    df_copy = merged_df.copy()
    for pk in ('id', 'ID'):
        if pk in df_copy.columns:
            df_copy = df_copy.drop(columns=[pk])
    if 'Measure_ID' in df_copy.columns:
        df_copy = df_copy.drop(columns=['Measure_ID'])
    df_copy.insert(0, 'Measure_ID', mid)

    with engine.connect() as conn:
        result = conn.execute(text("DESCRIBE psidata"))
        target_columns = [row[0] for row in result]
        try:
            pk_rows = list(conn.execute(text(
                "SHOW KEYS FROM psidata WHERE Key_name = 'PRIMARY'")))
            pk_columns = {r[4] for r in pk_rows}
        except Exception:
            pk_columns = set()

    for pk in pk_columns:
        if pk in target_columns:
            target_columns.remove(pk)

    if 'psi_type' in target_columns:
        df_copy['psi_type'] = psi_type
        print(f"[save_merged_rows] psidata.psi_type = {psi_type!r} "
              f"(для {len(df_copy)} строк)")
    else:
        print("[save_merged_rows] В psidata нет колонки 'psi_type' — "
              "пропуск")

    cols_to_insert = [c for c in target_columns if c in df_copy.columns]
    if not cols_to_insert:
        raise RuntimeError(
            "Нет подходящих столбцов для вставки в psidata. "
            f"В df: {list(df_copy.columns)}; "
            f"в таблице: {target_columns}"
        )

    columns_sql = ','.join(f"`{c}`" for c in cols_to_insert)
    placeholders = ','.join(['%s'] * len(cols_to_insert))
    bulk_insert_sql = (
        f"INSERT INTO psidata ({columns_sql}) "
        f"VALUES ({placeholders})"
    )

    df_to_insert = df_copy[cols_to_insert]
    records = []
    nan_cells = 0
    for row in df_to_insert.itertuples(index=False, name=None):
        cleaned = []
        for v in row:
            cv = _safe_db_value(v)
            if cv is None and v is not None:
                nan_cells += 1
            cleaned.append(cv)
        records.append(tuple(cleaned))

    if nan_cells:
        print(f"[save_merged_rows] Заменено NaN/Inf на NULL: {nan_cells}")

    print(f"[save_merged_rows] Вставка {len(records)} строк в psidata "
          f"(MeasureID = {mid})...")

    with engine.begin() as conn:
        conn.exec_driver_sql(bulk_insert_sql, records)

    print(f"[save_merged_rows] УСПЕХ: MeasureID = {mid}, "
          f"строк = {len(records)}, psi_type = {psi_type!r}")
    return mid
def create_new_protocol(
    merged_df: pd.DataFrame,
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
    psi_type: str = 'ОТК',
    notes: str = None,
    measure_id: int = None,
    source_measure_id: int = None,
) -> int:
    """Создаёт протокол: заголовок (если не передан Measure_ID) + строки.

    * Если measure_id задан — используется он, psi_measure_id не пишется
      (GUI уже создал заголовок при объединении).
    * Если measure_id=None — резервируется новый MeasureID
      (backward-compat / «атомарное» сохранение).
    * Если source_measure_id задан — в psidatatemp копируются температуры
      из этого замера (основного, без изменений).
    """
    if measure_id is not None:
        mid = int(measure_id)
        print(f"[create_new_protocol] Используем готовый MeasureID = {mid}")
    else:
        mid = reserve_measure_id(
            msk=msk,
            protocol_number=protocol_number,
            program_type=program_type,
            operator_name=operator_name,
            file_name=file_name,
            notes=notes,
        )
    save_merged_rows(
        merged_df, mid, psi_type,
        source_measure_id=source_measure_id,
    )
    return mid

def create_new_protocol_7(
    merged_df: pd.DataFrame,
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
    psi_type: str = 'ОТК',
    notes: str = None,
    measure_id: int = None,
    source_measure_id: int = None,
) -> int:
    """Создаёт протокол: заголовок (если не передан Measure_ID) + строки.

    * Если measure_id задан — используется он, psi_measure_id не пишется
      (GUI уже создал заголовок при объединении).
    * Если measure_id=None — резервируется новый MeasureID
      (backward-compat / «атомарное» сохранение).
    * Если source_measure_id задан — в psidatatemp копируются температуры
      из этого замера (основного, без изменений).
    """
    if measure_id is not None:
        mid = int(measure_id)
        print(f"[create_new_protocol] Используем готовый MeasureID = {mid}")
    else:
        mid = reserve_measure_id(
            msk=msk,
            protocol_number=protocol_number,
            program_type=program_type,
            operator_name=operator_name,
            file_name=file_name,
            notes=notes,
        )
    save_merged_rows(
        merged_df, mid, psi_type,
        source_measure_id=source_measure_id,
    )
    return mid

def create_new_protocol_1(
    merged_df: pd.DataFrame,
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
    psi_type: str = 'ОТК',
    notes: str = None,
    measure_id: int = None,
) -> int:
    """Создаёт протокол: заголовок (если не передан Measure_ID) + строки.

    * Если measure_id задан — используется он, psi_measure_id не пишется
      (GUI уже создал заголовок при объединении).
    * Если measure_id=None — резервируется новый MeasureID
      (backward-compat / «атомарное» сохранение).
    """
    if measure_id is not None:
        mid = int(measure_id)
        print(f"[create_new_protocol] Используем готовый MeasureID = {mid}")
    else:
        mid = reserve_measure_id(
            msk=msk,
            protocol_number=protocol_number,
            program_type=program_type,
            operator_name=operator_name,
            file_name=file_name,
            notes=notes,
        )
    save_merged_rows(merged_df, mid, psi_type)
    return mid

def save_merged_protocol(
    merged_df: pd.DataFrame,
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
    psi_type: str = 'ОТК',
    notes: str = None,
    measure_id: int = None,
    source_measure_id: int = None,
) -> int:
    """Полный путь: валидация + (reserve) + save rows. Backward-compat."""
    if merged_df is None or merged_df.empty:
        raise ValueError("Нет данных для сохранения: merged_df пуст")
    if 'N' not in merged_df.columns:
        raise ValueError(
            "В merged_df отсутствует обязательная колонка 'N'"
        )
    if not msk:
        raise ValueError("Не задан MSK")
    if not protocol_number:
        raise ValueError("Не задан номер протокола")

    return create_new_protocol(
        merged_df=merged_df,
        msk=msk,
        protocol_number=protocol_number,
        program_type=program_type,
        operator_name=operator_name,
        file_name=file_name,
        psi_type=psi_type,
        notes=notes,
        measure_id=measure_id,
        source_measure_id=source_measure_id,
    )

def save_merged_protocol_1(
    merged_df: pd.DataFrame,
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
    psi_type: str = 'ОТК',
    notes: str = None,
    measure_id: int = None,
) -> int:
    """Полный путь: валидация + (reserve) + save rows. Backward-compat."""
    if merged_df is None or merged_df.empty:
        raise ValueError("Нет данных для сохранения: merged_df пуст")
    if 'N' not in merged_df.columns:
        raise ValueError(
            "В merged_df отсутствует обязательная колонка 'N'"
        )
    if not msk:
        raise ValueError("Не задан MSK")
    if not protocol_number:
        raise ValueError("Не задан номер протокола")

    return create_new_protocol(
        merged_df=merged_df,
        msk=msk,
        protocol_number=protocol_number,
        program_type=program_type,
        operator_name=operator_name,
        file_name=file_name,
        psi_type=psi_type,
        notes=notes,
        measure_id=measure_id,
    )

def create_new_protocol_4(
    merged_df: pd.DataFrame,
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
    psi_type: str = 'ОТК',
    notes: str = None,
) -> int:
    """Создаёт новый протокол (psi_measure_id + psidata).

    * Регистрирует замер в psi_measure_id (MSK, ProtokolN, File,
      Program_Type, Operator, Notes, archive_flag=0).
    * Копирует все строки merged_df в psidata, подменяя Measure_ID
      на новый; в psi_type пишет переданный тип протокола.
    * notes — свободный текст (например «Совмещение (1: ..., 2: ...)»),
      попадает в psi_measure_id.Notes.

    Возвращает новый MeasureID.
    """
    print("[create_new_protocol] Начало создания протокола")
    print(f"[create_new_protocol] psi_type={psi_type!r}, "
          f"notes={notes!r}")

    if merged_df is None or merged_df.empty:
        print("[create_new_protocol] ОТМЕНА: merged_df пуст")
        raise ValueError("merged_df пуст — сохранять нечего")

    if 'N' not in merged_df.columns:
        print("[create_new_protocol] ОТМЕНА: нет колонки 'N'")
        raise ValueError("В merged_df нет обязательной колонки 'N'")

    psi_type = psi_type if psi_type in ('ПСИ', 'ОТК') else 'ОТК'

    # Notes — VARCHAR(200), аккуратно ограничим длину
    if notes is not None:
        notes = str(notes).strip() or None
        if notes and len(notes) > 200:
            print(f"[create_new_protocol] Notes > 200 симв., "
                  f"обрезано до 200")
            notes = notes[:200]

    engine = get_engine()

    # --- 1. Регистрируем замер в psi_measure_id ---
    print(f"[create_new_protocol] INSERT в psi_measure_id: "
          f"MSK={msk!r}, ProtokolN={protocol_number!r}, "
          f"File={file_name!r}, Program_Type={program_type!r}, "
          f"Operator={operator_name!r}, Notes={notes!r}")

    insert_measure_sql = """
        INSERT INTO psi_measure_id
            (MSK, ProtokolN, File, Program_Type, Operator,
             archive_flag, Notes)
        VALUES
            (:msk, :protocol_number, :file_name, :program_type,
             :operator, 0, :notes)
    """
    params = {
        'msk': msk,
        'protocol_number': protocol_number,
        'file_name': file_name,
        'program_type': program_type,
        'operator': operator_name,
        'notes': notes,
    }
    new_measure_id = insert_and_get_id(insert_measure_sql, params)
    if not new_measure_id:
        print("[create_new_protocol] ОШИБКА: "
              "insert_and_get_id() вернул пустой MeasureID")
        raise RuntimeError(
            "Не удалось получить новый MeasureID из psi_measure_id"
        )
    print(f"[create_new_protocol] Зарегистрирован MeasureID = "
          f"{new_measure_id}")

    # --- 2. Готовим данные для psidata ---
    df_copy = merged_df.copy()

    for pk in ('id', 'ID'):
        if pk in df_copy.columns:
            df_copy = df_copy.drop(columns=[pk])

    if 'Measure_ID' in df_copy.columns:
        df_copy = df_copy.drop(columns=['Measure_ID'])

    df_copy.insert(0, 'Measure_ID', new_measure_id)

    # --- 3. Схема psidata ---
    print("[create_new_protocol] Получение схемы psidata...")
    with engine.connect() as conn:
        result = conn.execute(text("DESCRIBE psidata"))
        target_columns = [row[0] for row in result]

        try:
            pk_rows = list(conn.execute(text(
                "SHOW KEYS FROM psidata WHERE Key_name = 'PRIMARY'")))
            pk_columns = {r[4] for r in pk_rows}
        except Exception:
            pk_columns = set()

    for pk in pk_columns:
        if pk in target_columns:
            target_columns.remove(pk)

    print(f"[create_new_protocol] В таблице psidata колонок: "
          f"{len(target_columns)}; PK исключён: {sorted(pk_columns)}")

    if 'psi_type' in target_columns:
        df_copy['psi_type'] = psi_type
        print(f"[create_new_protocol] psidata.psi_type = {psi_type!r} "
              f"(для {len(df_copy)} строк)")
    else:
        print("[create_new_protocol] В psidata нет колонки 'psi_type' — "
              "пропуск (нормально для старой схемы)")

    cols_to_insert = [c for c in target_columns if c in df_copy.columns]
    if not cols_to_insert:
        print("[create_new_protocol] ОШИБКА: нет подходящих столбцов.")
        raise RuntimeError(
            "Нет подходящих столбцов для вставки в psidata. "
            f"Столбцы в df: {list(df_copy.columns)}; "
            f"в таблице: {target_columns}"
        )
    print(f"[create_new_protocol] Колонок к вставке: "
          f"{len(cols_to_insert)}")

    # --- 4. Массовая вставка ---
    columns_sql = ','.join(f"`{c}`" for c in cols_to_insert)
    placeholders = ','.join(['%s'] * len(cols_to_insert))
    bulk_insert_sql = (
        f"INSERT INTO psidata ({columns_sql}) "
        f"VALUES ({placeholders})"
    )

    df_to_insert = df_copy[cols_to_insert]
    records = []
    nan_cells = 0
    for row in df_to_insert.itertuples(index=False, name=None):
        cleaned = []
        for v in row:
            cv = _safe_db_value(v)
            if cv is None and v is not None:
                nan_cells += 1
            cleaned.append(cv)
        records.append(tuple(cleaned))

    if nan_cells:
        print(f"[create_new_protocol] Заменено NaN/Inf на NULL: "
              f"{nan_cells} значений")

    print(f"[create_new_protocol] Подготовлено записей: {len(records)}")
    print("[create_new_protocol] Выполнение массовой вставки в psidata...")

    with engine.begin() as conn:
        conn.exec_driver_sql(bulk_insert_sql, records)

    print(f"[create_new_protocol] УСПЕХ: вставлено {len(records)} "
          f"строк, MeasureID = {new_measure_id}, "
          f"psi_type = {psi_type!r}, notes = {notes!r}")
    return new_measure_id


def save_merged_protocol_4(
    merged_df: pd.DataFrame,
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
    psi_type: str = 'ОТК',
    notes: str = None,
) -> int:
    """Валидирует и сохраняет результат слияния в БД.

    * psi_type — 'ПСИ' / 'ОТК', пишется в psidata.psi_type.
    * notes    — отметка о совмещении, пишется в psi_measure_id.Notes.
    """
    print("[save_merged_protocol] Валидация входных данных...")

    if merged_df is None or merged_df.empty:
        raise ValueError("Нет данных для сохранения: merged_df пуст")

    if 'N' not in merged_df.columns:
        raise ValueError(
            "В merged_df отсутствует обязательная колонка 'N'"
        )

    if not msk:
        raise ValueError("Не задан MSK")

    if not protocol_number:
        raise ValueError("Не задан номер протокола")

    psi_type = psi_type if psi_type in ('ПСИ', 'ОТК') else 'ОТК'

    print(f"[save_merged_protocol] Проверки пройдены, "
          f"передаю в create_new_protocol(): "
          f"строк={len(merged_df)}, MSK={msk!r}, "
          f"протокол={protocol_number!r}, "
          f"psi_type={psi_type!r}, notes={notes!r}")

    return create_new_protocol(
        merged_df=merged_df,
        msk=msk,
        protocol_number=protocol_number,
        program_type=program_type,
        operator_name=operator_name,
        file_name=file_name,
        psi_type=psi_type,
        notes=notes,
    )

def create_new_protocol_6(
    merged_df: pd.DataFrame,
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
    psi_type: str = 'ОТК',
) -> int:
    """Создаёт новый протокол (psi_measure_id + psidata).

    1. Вставляет запись в psi_measure_id и получает новый MeasureID.
    2. Копирует все строки merged_df в psidata, заменяя Measure_ID
       на новый; в колонку psi_type пишет переданный тип протокола
       ('ПСИ' / 'ОТК'), если такая колонка есть в psidata.

    Возвращает новый MeasureID.
    """
    print("[create_new_protocol] Начало создания протокола")
    print(f"[create_new_protocol] psi_type={psi_type!r}")

    if merged_df is None or merged_df.empty:
        print("[create_new_protocol] ОТМЕНА: merged_df пуст")
        raise ValueError("merged_df пуст — сохранять нечего")

    if 'N' not in merged_df.columns:
        print("[create_new_protocol] ОТМЕНА: нет колонки 'N'")
        raise ValueError("В merged_df нет обязательной колонки 'N'")

    # Нормализуем тип протокола — единственная точка валидации
    psi_type = psi_type if psi_type in ('ПСИ', 'ОТК') else 'ОТК'

    engine = get_engine()

    # --- 1. Регистрируем замер в psi_measure_id ---
    print(f"[create_new_protocol] INSERT в psi_measure_id: "
          f"MSK={msk!r}, ProtokolN={protocol_number!r}, "
          f"File={file_name!r}, Program_Type={program_type!r}, "
          f"Operator={operator_name!r}")

    insert_measure_sql = """
        INSERT INTO psi_measure_id
            (MSK, ProtokolN, File, Program_Type, Operator, archive_flag)
        VALUES
            (:msk, :protocol_number, :file_name, :program_type,
             :operator, 0)
    """
    params = {
        'msk': msk,
        'protocol_number': protocol_number,
        'file_name': file_name,
        'program_type': program_type,
        'operator': operator_name,
    }
    new_measure_id = insert_and_get_id(insert_measure_sql, params)
    if not new_measure_id:
        print("[create_new_protocol] ОШИБКА: "
              "insert_and_get_id() вернул пустой MeasureID")
        raise RuntimeError(
            "Не удалось получить новый MeasureID из psi_measure_id"
        )
    print(f"[create_new_protocol] Зарегистрирован MeasureID = "
          f"{new_measure_id}")

    # --- 2. Готовим данные для psidata ---
    df_copy = merged_df.copy()

    # PK psidata генерируется СУБД — из источника переносить нельзя.
    for pk in ('id', 'ID'):
        if pk in df_copy.columns:
            df_copy = df_copy.drop(columns=[pk])

    if 'Measure_ID' in df_copy.columns:
        df_copy = df_copy.drop(columns=['Measure_ID'])

    df_copy.insert(0, 'Measure_ID', new_measure_id)

    # --- 3. Схема psidata ---
    print("[create_new_protocol] Получение схемы psidata...")
    with engine.connect() as conn:
        result = conn.execute(text("DESCRIBE psidata"))
        target_columns = [row[0] for row in result]

        try:
            pk_rows = list(conn.execute(text(
                "SHOW KEYS FROM psidata WHERE Key_name = 'PRIMARY'")))
            pk_columns = {r[4] for r in pk_rows}
        except Exception:
            pk_columns = set()

    for pk in pk_columns:
        if pk in target_columns:
            target_columns.remove(pk)

    print(f"[create_new_protocol] В таблице psidata колонок: "
          f"{len(target_columns)}; PK исключён: {sorted(pk_columns)}")

    # ▼ NEW: единый psi_type для всех строк нового замера.
    #   * Если psidata.psi_type существует — пишем туда выбранный тип.
    #   * Если нет — молча пропускаем (обратная совместимость со схемой
    #     без этой колонки).
    if 'psi_type' in target_columns:
        df_copy['psi_type'] = psi_type
        print(f"[create_new_protocol] psidata.psi_type = {psi_type!r} "
              f"(для {len(df_copy)} строк)")
    else:
        print("[create_new_protocol] В psidata нет колонки 'psi_type' — "
              "пропуск (нормально для старой схемы)")

    cols_to_insert = [c for c in target_columns if c in df_copy.columns]
    if not cols_to_insert:
        print("[create_new_protocol] ОШИБКА: нет подходящих столбцов. "
              f"В df: {list(df_copy.columns)}; "
              f"в таблице: {target_columns}")
        raise RuntimeError(
            "Нет подходящих столбцов для вставки в psidata. "
            f"Столбцы в df: {list(df_copy.columns)}; "
            f"в таблице: {target_columns}"
        )
    print(f"[create_new_protocol] Колонок к вставке: "
          f"{len(cols_to_insert)}")
    print(f"[create_new_protocol]   {cols_to_insert}")

    # --- 4. Массовая вставка позиционными параметрами ---
    #
    # В psidata есть колонки с дефисом (F0-Fl, Rmax-Rmin, MSK-M),
    # поэтому именованные параметры SQLAlchemy не годятся. Используем
    # %s и передаём кортежи значений.
    #
    # Ключевая защита: NaN/Inf/NaT конвертируем в None ещё ДО того,
    # как они попадут в mysql-connector. Иначе драйвер подставит
    # в SQL литерал nan → MySQL сочтёт его именем колонки.
    columns_sql = ','.join(f"`{c}`" for c in cols_to_insert)
    placeholders = ','.join(['%s'] * len(cols_to_insert))
    bulk_insert_sql = (
        f"INSERT INTO psidata ({columns_sql}) "
        f"VALUES ({placeholders})"
    )

    df_to_insert = df_copy[cols_to_insert]
    records = []
    nan_cells = 0
    for row in df_to_insert.itertuples(index=False, name=None):
        cleaned = []
        for v in row:
            cv = _safe_db_value(v)
            if cv is None and v is not None:
                nan_cells += 1
            cleaned.append(cv)
        records.append(tuple(cleaned))

    if nan_cells:
        print(f"[create_new_protocol] Заменено NaN/Inf на NULL: "
              f"{nan_cells} значений")

    print(f"[create_new_protocol] Подготовлено записей: {len(records)}")
    print("[create_new_protocol] Выполнение массовой вставки в psidata...")

    with engine.begin() as conn:
        conn.exec_driver_sql(bulk_insert_sql, records)

    print(f"[create_new_protocol] УСПЕХ: вставлено {len(records)} "
          f"строк, MeasureID = {new_measure_id}, psi_type = {psi_type!r}")
    return new_measure_id

def create_new_protocol_2(
    merged_df: pd.DataFrame,
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
) -> int:
    """Создаёт новый протокол (psi_measure_id + psidata).

    1. Вставляет запись в psi_measure_id и получает новый MeasureID.
    2. Копирует все строки merged_df в psidata, заменяя Measure_ID
       на новый.

    Возвращает новый MeasureID.
    """
    print("[create_new_protocol] Начало создания протокола")

    if merged_df is None or merged_df.empty:
        print("[create_new_protocol] ОТМЕНА: merged_df пуст")
        raise ValueError("merged_df пуст — сохранять нечего")

    if 'N' not in merged_df.columns:
        print("[create_new_protocol] ОТМЕНА: нет колонки 'N'")
        raise ValueError("В merged_df нет обязательной колонки 'N'")

    engine = get_engine()

    # --- 1. Регистрируем замер в psi_measure_id ---
    print(f"[create_new_protocol] INSERT в psi_measure_id: "
          f"MSK={msk!r}, ProtokolN={protocol_number!r}, "
          f"File={file_name!r}, Program_Type={program_type!r}, "
          f"Operator={operator_name!r}")

    insert_measure_sql = """
        INSERT INTO psi_measure_id
            (MSK, ProtokolN, File, Program_Type, Operator, archive_flag)
        VALUES
            (:msk, :protocol_number, :file_name, :program_type,
             :operator, 0)
    """
    params = {
        'msk': msk,
        'protocol_number': protocol_number,
        'file_name': file_name,
        'program_type': program_type,
        'operator': operator_name,
    }
    new_measure_id = insert_and_get_id(insert_measure_sql, params)
    if not new_measure_id:
        print("[create_new_protocol] ОШИБКА: "
              "insert_and_get_id() вернул пустой MeasureID")
        raise RuntimeError(
            "Не удалось получить новый MeasureID из psi_measure_id"
        )
    print(f"[create_new_protocol] Зарегистрирован MeasureID = "
          f"{new_measure_id}")

    # --- 2. Готовим данные для psidata ---
    df_copy = merged_df.copy()

    # PK psidata генерируется СУБД — из источника переносить нельзя.
    for pk in ('id', 'ID'):
        if pk in df_copy.columns:
            df_copy = df_copy.drop(columns=[pk])

    if 'Measure_ID' in df_copy.columns:
        df_copy = df_copy.drop(columns=['Measure_ID'])

    df_copy.insert(0, 'Measure_ID', new_measure_id)

    # --- 3. Схема psidata ---
    print("[create_new_protocol] Получение схемы psidata...")
    with engine.connect() as conn:
        result = conn.execute(text("DESCRIBE psidata"))
        target_columns = [row[0] for row in result]

        try:
            pk_rows = list(conn.execute(text(
                "SHOW KEYS FROM psidata WHERE Key_name = 'PRIMARY'")))
            pk_columns = {r[4] for r in pk_rows}
        except Exception:
            pk_columns = set()

    for pk in pk_columns:
        if pk in target_columns:
            target_columns.remove(pk)

    print(f"[create_new_protocol] В таблице psidata колонок: "
          f"{len(target_columns)}; PK исключён: {sorted(pk_columns)}")

    cols_to_insert = [c for c in target_columns if c in df_copy.columns]
    if not cols_to_insert:
        print("[create_new_protocol] ОШИБКА: нет подходящих столбцов. "
              f"В df: {list(df_copy.columns)}; "
              f"в таблице: {target_columns}")
        raise RuntimeError(
            "Нет подходящих столбцов для вставки в psidata. "
            f"Столбцы в df: {list(df_copy.columns)}; "
            f"в таблице: {target_columns}"
        )
    print(f"[create_new_protocol] Колонок к вставке: "
          f"{len(cols_to_insert)}")
    print(f"[create_new_protocol]   {cols_to_insert}")

    # --- 4. Массовая вставка позиционными параметрами ---
    #
    # В psidata есть колонки с дефисом (F0-Fl, Rmax-Rmin, MSK-M),
    # поэтому именованные параметры SQLAlchemy не годятся. Используем
    # %s и передаём кортежи значений.
    #
    # Ключевая защита: NaN/Inf/NaT конвертируем в None ещё ДО того,
    # как они попадут в mysql-connector. Иначе драйвер подставит
    # в SQL литерал nan → MySQL сочтёт его именем колонки.
    columns_sql = ','.join(f"`{c}`" for c in cols_to_insert)
    placeholders = ','.join(['%s'] * len(cols_to_insert))
    bulk_insert_sql = (
        f"INSERT INTO psidata ({columns_sql}) "
        f"VALUES ({placeholders})"
    )

    df_to_insert = df_copy[cols_to_insert]
    records = []
    nan_cells = 0
    for row in df_to_insert.itertuples(index=False, name=None):
        cleaned = []
        for v in row:
            cv = _safe_db_value(v)
            if cv is None and v is not None:
                nan_cells += 1
            cleaned.append(cv)
        records.append(tuple(cleaned))

    if nan_cells:
        print(f"[create_new_protocol] Заменено NaN/Inf на NULL: "
              f"{nan_cells} значений")

    print(f"[create_new_protocol] Подготовлено записей: {len(records)}")
    print("[create_new_protocol] Выполнение массовой вставки в psidata...")

    with engine.begin() as conn:
        conn.exec_driver_sql(bulk_insert_sql, records)

    print(f"[create_new_protocol] УСПЕХ: вставлено {len(records)} "
          f"строк, MeasureID = {new_measure_id}")
    return new_measure_id



# ============================================================================
#                  4. Хелперы и обёртки для GUI
# ============================================================================

def get_merged_preview(
    merged_df: pd.DataFrame,
    max_rows: int = 500,
) -> pd.DataFrame:
    """Возвращает компактный DataFrame для предпросмотра."""
    if merged_df is None or merged_df.empty:
        return pd.DataFrame()

    priority = ['N', 'Spc', 'Msk', 'F', 'R', 'C0', 'Cq', 'L', 'Q', 'Old']
    cols = [c for c in priority if c in merged_df.columns]
    rest = [
        c for c in merged_df.columns
        if c not in cols and c not in ('Measure_ID', 'id')
    ]
    df = merged_df[cols + rest].copy()
    return df.head(max_rows) if len(df) > max_rows else df


def calculate_merge_statistics(
    main_df: pd.DataFrame,
    secondary_df: pd.DataFrame = None,
    old_df: pd.DataFrame = None,
    merged_df: pd.DataFrame = None,
) -> dict:
    """Сводная статистика слияния для отображения в UI."""
    stats = {
        'main_rows': len(main_df) if main_df is not None else 0,
        'secondary_rows': len(secondary_df) if secondary_df is not None else 0,
        'old_rows': len(old_df) if old_df is not None else 0,
        'merged_rows': len(merged_df) if merged_df is not None else 0,
        'columns': len(merged_df.columns) if merged_df is not None else 0,
    }

    if (
        secondary_df is not None
        and not secondary_df.empty
        and merged_df is not None
        and 'N' in merged_df.columns
        and 'N' in secondary_df.columns
    ):
        stats['matched_secondary'] = int(
            merged_df['N'].isin(secondary_df['N']).sum()
        )

    if (
        old_df is not None
        and not old_df.empty
        and merged_df is not None
        and 'Old' in merged_df.columns
    ):
        stats['old_filled'] = int(merged_df['Old'].notna().sum())

    return stats


def protocol_number_exists(protocol_number: str) -> bool:
    """Мягкая проверка: есть ли уже такой ProtokolN в psi_measure_id."""
    if not protocol_number:
        return False
    try:
        safe = str(protocol_number).replace("'", "''")
        df = execute_query(
            f"SELECT MeasureID FROM psi_measure_id "
            f"WHERE ProtokolN = '{safe}' LIMIT 1"
        )
        return not df.empty
    except Exception:
        # Если таблица/поле отсутствует — не падаем, считаем, что нет
        return False

def save_merged_protocol_2(
    merged_df: pd.DataFrame,
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
    psi_type: str = 'ОТК',
) -> int:
    """Валидирует и сохраняет результат слияния в БД.

    psi_type — тип протокола ('ПСИ' / 'ОТК'). Передаётся в
    create_new_protocol() и пишется в psidata.psi_type.
    Любое другое значение приводится к 'ОТК'.
    """
    print("[save_merged_protocol] Валидация входных данных...")

    if merged_df is None or merged_df.empty:
        print("[save_merged_protocol] ОТМЕНА: merged_df пуст")
        raise ValueError("Нет данных для сохранения: merged_df пуст")

    if 'N' not in merged_df.columns:
        print("[save_merged_protocol] ОТМЕНА: нет колонки 'N'")
        raise ValueError(
            "В merged_df отсутствует обязательная колонка 'N'"
        )

    if not msk:
        print("[save_merged_protocol] ОТМЕНА: не задан MSK")
        raise ValueError("Не задан MSK")

    if not protocol_number:
        print("[save_merged_protocol] ОТМЕНА: не задан номер протокола")
        raise ValueError("Не задан номер протокола")

    psi_type = psi_type if psi_type in ('ПСИ', 'ОТК') else 'ОТК'

    print(f"[save_merged_protocol] Проверки пройдены, "
          f"передаю в create_new_protocol(): "
          f"строк={len(merged_df)}, MSK={msk!r}, "
          f"протокол={protocol_number!r}, psi_type={psi_type!r}")

    return create_new_protocol(
        merged_df=merged_df,
        msk=msk,
        protocol_number=protocol_number,
        program_type=program_type,
        operator_name=operator_name,
        file_name=file_name,
        psi_type=psi_type,
    )

def save_merged_protocol_1(
    merged_df: pd.DataFrame,
    msk: str,
    protocol_number: str,
    program_type: str = None,
    operator_name: str = None,
    file_name: str = None,
) -> int:
    """Валидирует и сохраняет результат слияния в БД."""
    print("[save_merged_protocol] Валидация входных данных...")

    if merged_df is None or merged_df.empty:
        print("[save_merged_protocol] ОТМЕНА: merged_df пуст")
        raise ValueError("Нет данных для сохранения: merged_df пуст")

    if 'N' not in merged_df.columns:
        print("[save_merged_protocol] ОТМЕНА: нет колонки 'N'")
        raise ValueError(
            "В merged_df отсутствует обязательная колонка 'N'"
        )

    if not msk:
        print("[save_merged_protocol] ОТМЕНА: не задан MSK")
        raise ValueError("Не задан MSK")

    if not protocol_number:
        print("[save_merged_protocol] ОТМЕНА: не задан номер протокола")
        raise ValueError("Не задан номер протокола")

    print(f"[save_merged_protocol] Проверки пройдены, "
          f"передаю в create_new_protocol(): "
          f"строк={len(merged_df)}, MSK={msk!r}, "
          f"протокол={protocol_number!r}")

    return create_new_protocol(
        merged_df=merged_df,
        msk=msk,
        protocol_number=protocol_number,
        program_type=program_type,
        operator_name=operator_name,
        file_name=file_name,
    )

# ============================================================================
#      Поиск замеров по номеру резонатора / частичному МСК
# ============================================================================

def _safe_sql_str(s) -> str:
    """Экранирование строки для подстановки в SQL (одинарные кавычки)."""
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
    return None


def _get_search_archive_msk():
    """search_archive_msk из любого из двух возможных пакетов."""
    for mod_path in (
        'Temperature_Measure.Archive.Archive_Data',
        'Archive_View.Archive_Data',
    ):
        try:
            mod = __import__(mod_path, fromlist=['search_archive_msk'])
            return getattr(mod, 'search_archive_msk')
        except (ImportError, AttributeError):
            continue
    return None


def search_msk_by_partial(partial: str, limit: int = 200) -> list[str]:
    """Поиск МСК по частичному совпадению.

    Сначала пробует архивный `search_archive_msk` (если доступен),
    затем — прямой запрос к psidata. Возвращает список строк.
    """
    if not partial or not str(partial).strip():
        return []
    partial_s = str(partial).strip()

    search_fn = _get_search_archive_msk()
    if search_fn is not None:
        try:
            matches = search_fn(partial_s)
            if matches:
                return list(matches)[:int(limit)]
        except Exception as e:
            print(f"[search_msk_by_partial] archive error: {e}")

    safe = _safe_sql_str(partial_s)
    query = (
        f"SELECT DISTINCT Msk FROM psidata "
        f"WHERE Msk LIKE '%{safe}%' "
        f"  AND Msk IS NOT NULL AND Msk <> '' "
        f"ORDER BY Msk LIMIT {int(limit)}"
    )
    try:
        df = execute_query(query)
        return df['Msk'].dropna().astype(str).tolist()
    except Exception as e:
        print(f"[search_msk_by_partial] SQL error: {e}")
        return []

def search_measure_ids_by_msk_partial(
    partial_msk: str, limit: int = 200,
) -> pd.DataFrame:
    """Замеры для МСК, найденного поиском (как в модуле Архив).

    Ключевое отличие от поиска по части: здесь МСК уже выбран
    оператором из combo, поэтому фильтр — ТОЧНОЕ совпадение
    `MSK = :msk` (как `load_measure_ids_by_msk` в Archive_Data),
    а не `LIKE '%…%'`.

    Возвращает DataFrame:
        Measure_ID, Sample_N, MSK, Spc, Date, N_Count
    Отсортировано по Measure_ID DESC (свежие сверху).
    """
    if not partial_msk or not str(partial_msk).strip():
        return pd.DataFrame()

    msk = str(partial_msk).strip()
    safe_msk = _safe_sql_str(msk)

    # 1) Сами Measure_ID — точное совпадение, как в Архиве.
    #    Используем ту же форму SQL, что load_measure_ids_by_msk,
    #    но сразу с добором MIN(Spc/Date/N) для combo-лейбла.
    query = (
        "SELECT Measure_ID, MIN(N) AS Sample_N, MIN(MSK) AS MSK, "
        "MIN(Spc) AS Spc, MIN(Date) AS Date, COUNT(*) AS N_Count "
        "FROM psidata "
        f"WHERE MSK = '{safe_msk}' "
        "  AND Measure_ID IS NOT NULL "
        "GROUP BY Measure_ID "
        "ORDER BY Measure_ID DESC "
        f"LIMIT {int(limit)}"
    )
    print(f"[search_by_msk] SQL: {query}")
    try:
        return execute_query(query)
    except Exception as e:
        print(f"[search_measure_ids_by_msk_partial] error: {e}")
        return pd.DataFrame()

def search_measure_ids_by_msk_partial_1(
    partial_msk: str, limit: int = 200,
) -> pd.DataFrame:
    """Поиск замеров по частичному МСК (по всем спецификациям).

    Возвращает DataFrame: Measure_ID, MSK, Spc, Date, N_Count
    Отсортировано по Measure_ID DESC (свежие сверху).
    """
    if not partial_msk or not str(partial_msk).strip():
        return pd.DataFrame()
    safe = _safe_sql_str(str(partial_msk).strip())
    query = (
        "SELECT Measure_ID, MIN(MSK) AS MSK, MIN(Spc) AS Spc, "
        "MIN(Date) AS Date, COUNT(*) AS N_Count "
        "FROM psidata "
        f"WHERE MSK LIKE '%{safe}%' "
        "  AND Measure_ID IS NOT NULL "
        "  AND MSK IS NOT NULL "
        "GROUP BY Measure_ID "
        "ORDER BY Measure_ID DESC "
        f"LIMIT {int(limit)}"
    )
    print(f"[search_by_msk_partial] SQL: {query}")
    try:
        return execute_query(query)
    except Exception as e:
        print(f"[search_measure_ids_by_msk_partial] error: {e}")
        return pd.DataFrame()

def _copy_temperatures(
    engine,
    source_measure_id: int,
    target_measure_id: int,
) -> int:
    """Копирует строки psidatatemp из source_measure_id в target_measure_id.

    Используется при сохранении совмещённого протокола: температуры
    берутся из основного замера без изменений (совмещение затрагивает
    только psidata).

    Возвращает количество вставленных строк (0, если копировать нечего).
    """
    if not source_measure_id or not target_measure_id:
        return 0
    try:
        src_mid = int(source_measure_id)
        tgt_mid = int(target_measure_id)
    except (TypeError, ValueError):
        return 0
    if src_mid == tgt_mid:
        return 0

    # --- схема psidatatemp ---
    with engine.connect() as conn:
        result = conn.execute(text("DESCRIBE psidatatemp"))
        all_columns = [row[0] for row in result]
        if not all_columns:
            print("[_copy_temperatures] psidatatemp недоступна")
            return 0
        try:
            pk_rows = list(conn.execute(text(
                "SHOW KEYS FROM psidatatemp WHERE Key_name = 'PRIMARY'")))
            pk_columns = {r[4] for r in pk_rows}
        except Exception:
            pk_columns = set()

    cols_to_insert = [
        c for c in all_columns
        if c not in pk_columns and c != 'Measure_ID'
    ]
    if not cols_to_insert:
        return 0

    columns_sql = ', '.join(f"`{c}`" for c in cols_to_insert)

    # --- читаем исходные температуры ---
    try:
        df_temp = pd.read_sql(
            text(f"SELECT {columns_sql} FROM psidatatemp "
                 f"WHERE Measure_ID = :src"),
            engine, params={'src': src_mid},
        )
    except Exception as e:
        print(f"[_copy_temperatures] read error: {e}")
        return 0

    if df_temp.empty:
        print(f"[_copy_temperatures] нет температур для "
              f"Measure_ID={src_mid} — пропуск")
        return 0

    # --- вставляем с новым Measure_ID ---
    placeholders = ', '.join(f':p{i}' for i in range(len(cols_to_insert)))
    insert_sql = (
        f"INSERT INTO psidatatemp (`Measure_ID`, {columns_sql}) "
        f"VALUES (:tgt, {placeholders})"
    )

    inserted = 0
    with engine.begin() as conn:
        for _, row in df_temp.iterrows():
            params = {'tgt': tgt_mid}
            for i, col in enumerate(cols_to_insert):
                params[f'p{i}'] = _safe_db_value(row.get(col))
            conn.execute(text(insert_sql), params)
            inserted += 1

    print(f"[_copy_temperatures] скопировано {inserted} строк "
          f"psidatatemp: Measure_ID {src_mid} -> {tgt_mid}")
    return inserted

def search_measure_ids_by_number_partial(
    partial, limit: int = 500,
) -> pd.DataFrame:
    """Поиск замеров по подстроке номера резонатора.

    Делегирует в aging_logic.search_measure_ids_by_number_partial
    (там уже реализован lookup + fallback + self-heal). Если модуль
    недоступен — локальная упрощённая реализация через psidata.
    """
    if partial is None or not str(partial).strip():
        return pd.DataFrame()

    try:
        from Temperature_Measure.Spektr_OLD.aging_logic import (
            search_measure_ids_by_number_partial as _impl,
        )
        return _impl(partial, limit=limit)
    except ImportError:
        pass

    # --- fallback: прямой запрос к psidata ---
    pattern = f'%{str(partial).strip()}%'
    safe = _safe_sql_str(pattern)
    sql = (
        "SELECT Measure_ID, MIN(N) AS Sample_N, MIN(MSK) AS MSK, "
        "MIN(Date) AS Date, COUNT(*) AS Numbers_Count "
        "FROM psidata "
        f"WHERE N LIKE '{safe}' "
        "  AND Measure_ID IS NOT NULL "
        "  AND N IS NOT NULL "
        "GROUP BY Measure_ID "
        "ORDER BY Measure_ID DESC "
        f"LIMIT {int(limit)}"
    )
    print(f"[search_by_number] SQL: {sql}")
    try:
        return execute_query(sql)
    except Exception as e:
        print(f"[search_measure_ids_by_number_partial] error: {e}")
        return pd.DataFrame()

# ============================================================================
#      Хелперы для combo-поиска (используются в sort_gui.py)
# ============================================================================

def get_measure_summary(measure_id, engine=None) -> dict:
    """Сводка по Measure_ID.

    Возвращает dict: measure_id, msk, spc, date, file, n_count,
    program_type, operator, protocol_n. Пустой dict, если ID некорректен.
    """
    try:
        mid = int(str(measure_id).strip())
    except (TypeError, ValueError):
        return {}
    info = {'measure_id': mid}

    try:
        df = execute_query(
            f"SELECT MIN(MSK) AS MSK, MIN(Spc) AS Spc, "
            f"MIN(Date) AS Date, MIN(File) AS File, "
            f"COUNT(*) AS N_Count "
            f"FROM psidata WHERE Measure_ID = {mid}"
        )
        if not df.empty and int(df.iloc[0].get('N_Count') or 0) > 0:
            r = df.iloc[0]
            info.update({
                'msk': r['MSK'], 'spc': r['Spc'],
                'date': r['Date'], 'file': r['File'],
                'n_count': int(r['N_Count']),
            })
    except Exception as e:
        print(f"[get_measure_summary] psidata: {e}")

    try:
        df2 = execute_query(
            f"SELECT Program_Type, Operator, ProtokolN "
            f"FROM psi_measure_id WHERE MeasureID = {mid}"
        )
        if not df2.empty:
            r = df2.iloc[0]
            info['program_type'] = r.get('Program_Type')
            info['operator'] = r.get('Operator')
            info['protocol_n'] = r.get('ProtokolN')
    except Exception as e:
        print(f"[get_measure_summary] psi_measure_id: {e}")

    return info


def format_measure_combo_label(row) -> str:
    """Строка для combo.

    Пример: '253799 | N=SU8525 | 456 | СПЕКТР-1 | 2023-06-30 | N=12'
    Учитывает колонки обоих поисков (N_Count и Numbers_Count).
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
    for key, prefix in (('Sample_N', 'N='), ('MSK', ''),
                        ('Spc', ''), ('Date', '')):
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

def get_next_protocol_number() -> str:
    """Возвращает следующий стандартный (числовой) номер протокола.

    Смотрит в psi_measure_id.ProtokolN, оставляя только записи,
    состоящие из цифр (чтобы не спотыкаться о старые 'AVT-...').
    Если таблица/поле недоступны — отдаёт '1'.
    """
    try:
        df = execute_query(
            "SELECT MAX(CAST(ProtokolN AS UNSIGNED)) AS mx "
            "FROM psi_measure_id "
            "WHERE ProtokolN REGEXP '^[0-9]+$'"
        )
        if not df.empty:
            mx = df.iloc[0].get('mx')
            if mx is not None and not pd.isna(mx):
                return str(int(mx) + 1)
    except Exception as e:
        print(f"[get_next_protocol_number] error: {e}")
    return "1"

def find_secondary_measure_candidates(
    main_measure_id, limit: int = 200,
) -> pd.DataFrame:
    """Найти замеры, где встречаются номера резонаторов основного замера.

    Возвращает DataFrame:
        Measure_ID, Sample_N, MSK, Spc, Date, Numbers_Count
    Сортировка: сначала замеры с максимальным числом совпавших
    резонаторов, затем — по Measure_ID DESC (свежие сверху).
    Сам основной замер из результатов исключается.
    """
    if main_measure_id is None or main_measure_id == "":
        return pd.DataFrame()
    try:
        mid = int(str(main_measure_id).strip())
    except (TypeError, ValueError):
        return pd.DataFrame()

    # --- 1. Собираем все N из основного замера ---
    try:
        df_n = execute_query(
            f"SELECT DISTINCT N FROM psidata "
            f"WHERE Measure_ID = {mid} "
            f"  AND N IS NOT NULL AND TRIM(N) <> ''"
        )
    except Exception as e:
        print(f"[find_secondary] error loading N: {e}")
        return pd.DataFrame()

    if df_n.empty:
        print(f"[find_secondary] у Measure_ID={mid} нет номеров резонаторов")
        return pd.DataFrame()

    n_values = [str(x).strip() for x in df_n['N'].dropna().tolist()]
    n_values = [n for n in n_values if n]
    if not n_values:
        return pd.DataFrame()

    # --- 2. IN-список N (экранируем) ---
    safe_ns = ", ".join(
        "'" + str(n).replace("'", "''") + "'" for n in n_values
    )

    # --- 3. Ищем замеры, где есть эти N, исключая сам основной ---
    sql = (
        "SELECT Measure_ID, MIN(N) AS Sample_N, MIN(MSK) AS MSK, "
        "MIN(Spc) AS Spc, MIN(Date) AS Date, "
        "COUNT(DISTINCT N) AS Numbers_Count "
        "FROM psidata "
        f"WHERE N IN ({safe_ns}) "
        f"  AND Measure_ID <> {mid} "
        "  AND Measure_ID IS NOT NULL "
        "GROUP BY Measure_ID "
        "ORDER BY Numbers_Count DESC, Measure_ID DESC "
        f"LIMIT {int(limit)}"
    )
    print(f"[find_secondary] N={len(n_values)}, SQL: {sql[:200]}...")
    try:
        df = execute_query(sql)
        print(f"[find_secondary] найдено {len(df)} замеров-кандидатов")
        return df
    except Exception as e:
        print(f"[find_secondary] SQL error: {e}")
        return pd.DataFrame()

def load_measure_psi_type(measure_id) -> str:
    """Тип протокола из psidata.psi_type ('ПСИ' / 'ОТК').

    Возвращает 'ОТК' по умолчанию, если:
      * Measure_ID не задан/некорректен;
      * в psidata нет колонки psi_type;
      * значение не равно 'ПСИ' или 'ОТК'.
    """
    if measure_id is None or measure_id == "":
        return 'ОТК'
    try:
        mid = int(str(measure_id).strip())
    except (TypeError, ValueError):
        return 'ОТК'

    try:
        df = execute_query(
            f"SELECT psi_type FROM psidata "
            f"WHERE Measure_ID = {mid} AND psi_type IS NOT NULL "
            f"LIMIT 1"
        )
        if not df.empty:
            v = df.iloc[0].get('psi_type')
            if v in ('ПСИ', 'ОТК'):
                return v
    except Exception as e:
        # Если колонки psi_type нет — это не ошибка, тихо откатываемся
        print(f"[load_measure_psi_type] fallback -> ОТК: {e}")
    return 'ОТК'