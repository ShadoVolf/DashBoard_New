"""Логика расчёта старения резонаторов (порт SpektrOLD.cpp).

Ключевые отличия от предыдущей версии:
  * Таблица «шапки» называется psi_measure_old_id (а не old_id).
  * Есть режим auto_search: для каждого N из M_ID_1 автоматически
    ищется «старый» замер без температурных параметров
    (Fptp IS NULL OR Fptp = 0).
  * Все ошибки и SQL-шаги пишутся в консоль через print + traceback.
"""
import math
import traceback

import numpy as np
import pandas as pd
from sqlalchemy import text

from Temperature_Measure.unite_protokol.db import (
    execute_query, get_engine, insert_and_get_id,
)

OLD_ID_TABLE = 'psi_measure_old_id'


# ---------------------------------------------------------------------------
#                      Загрузка исходных данных
# ---------------------------------------------------------------------------
def load_measure_by_id(measure_id) -> pd.DataFrame:
    mid = _as_int(measure_id)
    if mid is None:
        print(f'[aging_logic] load_measure_by_id: invalid id {measure_id!r}')
        return pd.DataFrame()

    sql = (
        "SELECT SQL_NO_CACHE N, MSK, F, R, Measure_ID, File, Spc, "
        "Date, DateR, Fptp, Fmax, Fmin "
        f"FROM psidata WHERE Measure_ID = {mid}"
    )
    print(f'[aging_logic] SQL: {sql}')
    try:
        df = execute_query(sql)
        print(f'[aging_logic] Loaded {len(df)} rows for Measure_ID={mid}')
        return df
    except Exception as e:
        print(f'[aging_logic.load_measure_by_id] SQL error: {e}')
        traceback.print_exc()
        return pd.DataFrame()


def load_spec_old(spc_name) -> dict:
    if not spc_name:
        print('[aging_logic.load_spec_old] spc_name empty')
        return {}
    safe = str(spc_name).replace("'", "''")
    sql = (
        "SELECT Name, old1max, old1min, Old2Max, old2min, "
        "PrintProfile, ID "
        f"FROM specification WHERE Name = '{safe}'"
    )
    print(f'[aging_logic] SQL: {sql}')
    try:
        df = execute_query(sql)
    except Exception as e:
        print(f'[aging_logic.load_spec_old] SQL error: {e}')
        traceback.print_exc()
        return {}
    if df.empty:
        print(f'[aging_logic.load_spec_old] spec not found: {spc_name!r}')
        return {}
    row = df.iloc[0]
    return {
        'Name': row.get('Name'),
        'old1max': _as_float_or_none(row.get('old1max')),
        'old1min': _as_float_or_none(row.get('old1min')),
        'Old2Max': _as_float_or_none(row.get('Old2Max')),
        'old2min': _as_float_or_none(row.get('old2min')),
        'PrintProfile': row.get('PrintProfile'),
        'ID': row.get('ID'),
    }


# ---------------------------------------------------------------------------
#                 Автопоиск «старого» замера для одного N
# ---------------------------------------------------------------------------
def find_old_measurement_for_n(n, spc, measure_id_1):
    """Ищем «второй» замер для одного N.

    «Второй» = следующий по времени замер того же N без темп. параметров.
    Порядок попыток (каждый N):
      1) Measure_ID > M_ID_1, тот же Spc, Fptp=0/NULL   — «второй» замер
      2) Measure_ID > M_ID_1, любой Spc,  Fptp=0/NULL
      3) Measure_ID < M_ID_1, тот же Spc, Fptp=0/NULL   — fallback: «предыдущий»
      4) Measure_ID < M_ID_1, любой Spc,  Fptp=0/NULL
    """

    safe_n = str(n).replace("'", "''")
    safe_spc = str(spc).replace("'", "''")
    mid1 = int(measure_id_1)

    def _fetch(direction: str, same_spc: bool) -> dict | None:
        sign = '>' if direction == 'newer' else '<'
        order = 'ASC' if direction == 'newer' else 'DESC'
        spc_clause = f" AND Spc = '{safe_spc}'" if same_spc else ''
        spc_order = (f"  CASE WHEN Spc = '{safe_spc}' THEN 0 ELSE 1 END ASC,"
                     if not same_spc else '')

        sql = (
            "SELECT Measure_ID, F, R, MSK, File, Date, Spc "
            "FROM psidata "
            f"WHERE N = '{safe_n}' "
            f"  AND Measure_ID {sign} {mid1}"
            f"{spc_clause} "
            "  AND (Fptp IS NULL OR Fptp = 0) "
            f"ORDER BY {spc_order} Measure_ID {order} "
            "LIMIT 1"
        )
        tag = f"{direction}/{'same-spc' if same_spc else 'any-spc'}"
        print(f'[find_old] N={n!r} [{tag}] SQL: {sql}')
        try:
            df = execute_query(sql)
        except Exception as e:
            print(f'[find_old] N={n!r} [{tag}] SQL error: {e}')
            traceback.print_exc()
            return None
        if df.empty:
            return None
        row = df.iloc[0]
        print(f'[find_old] N={n!r} [{tag}] -> '
              f'Measure_ID={row["Measure_ID"]}, '
              f'F={row["F"]}, R={row["R"]}, '
              f'Spc={row["Spc"]!r}, Date={row["Date"]!r}')
        return {
            'Measure_ID_2': row['Measure_ID'],
            'F2': row['F'],
            'R2': row['R'],
            'File_2': row.get('File'),
            'MSK_2': row.get('MSK'),
            'Date_2': row.get('Date'),
            'Spc_2': row.get('Spc'),
        }

    # 1–4: последовательные попытки
    for direction, same_spc in (
        ('newer', True),
        ('newer', False),
        ('older', True),
        ('older', False),
    ):
        found = _fetch(direction, same_spc)
        if found is not None:
            return found

    # Диагностика: что вообще есть для этого N
    print(f'[find_old] N={n!r}: НЕ НАЙДЕН, диагностика:')
    try:
        diag = execute_query(
            "SELECT Measure_ID, Spc, Fptp, Tmax, Tmin, F, R "
            f"FROM psidata WHERE N = '{safe_n}' "
            "ORDER BY Measure_ID DESC LIMIT 10"
        )
        for _, r in diag.iterrows():
            print(f'   Measure_ID={r["Measure_ID"]}, '
                  f'Spc={r.get("Spc")!r}, Fptp={r.get("Fptp")}, '
                  f'Tmax={r.get("Tmax")}, Tmin={r.get("Tmin")}, '
                  f'F={r.get("F")}, R={r.get("R")}')
    except Exception as e:
        print(f'   diagnostic SQL error: {e}')

    return None




def _row_to_old(row):
    return {
        'Measure_ID_2': row['Measure_ID'],
        'F2': row['F'],
        'R2': row['R'],
        'File_2': row.get('File'),
        'MSK_2': row.get('MSK'),
        'Date_2': row.get('Date'),
    }


def _safe_query(sql):
    try:
        return execute_query(sql)
    except Exception as e:
        print(f'[find_old] SQL error: {e}')
        traceback.print_exc()
        return pd.DataFrame()

def find_old_measurements_for_batch(first_df, spc, measure_id_1) -> pd.DataFrame:
    """Пройти по всем N из first_df, вернуть {N, F2, R2, Measure_ID_2, ...}."""
    if first_df.empty:
        return pd.DataFrame()

    rows = []
    for _, first_row in first_df.iterrows():
        n = first_row['N']
        old = find_old_measurement_for_n(n, spc, measure_id_1)
        if old is None:
            rows.append({
                'N': n, 'F2': None, 'R2': None,
                'Measure_ID_2': None, 'File_2': None,
                'MSK_2': None, 'Date_2': None,
            })
        else:
            old['N'] = n
            rows.append(old)

    result = pd.DataFrame(rows)
    found = int(result['Measure_ID_2'].notna().sum())
    print(f'[find_old] Batch: {len(result)} rows, found {found}')
    return result


# ---------------------------------------------------------------------------
#                         Основной расчёт
# ---------------------------------------------------------------------------
def compute_aging(measure_id_1,
                  measure_id_2=None,
                  operator: str = '',
                  auto_search: bool = True) -> dict:
    """Полный расчёт старения.

    Режимы:
      * auto_search=True  — measure_id_2 игнорируется; для каждого N
                            из первого замера ищется «старый» замер
                            без температурных параметров (Fptp/Tmax/Tmin).
      * auto_search=False — оба замера указаны явно, сопоставление
                            по N напрямую.

    В auto_search-режиме, если ни для одного N не найден старый замер
    или все найденные строки имеют пустые F/R, выбрасывается
    ValueError с диагностикой в консоли.

    Возвращает словарь с ключами:
      old_id, spc_name, measure_id_1, measure_id_2, msk,
      file_1, file_2, norms, dyn_norm, data, stats.
    """
    try:
        mid_1 = _as_int(measure_id_1)
        if mid_1 is None:
            raise ValueError(f'Некорректный «Код замера 1»: {measure_id_1!r}')

        # --- 1. Загрузка первого замера ---
        m1 = load_measure_by_id(mid_1)
        if m1.empty:
            raise ValueError(f'В psidata нет данных для Measure_ID={mid_1}')

        msk = str(m1['MSK'].iloc[0]) if 'MSK' in m1.columns else ''
        file_1 = str(m1['File'].iloc[0]) if 'File' in m1.columns else ''
        spc_name = str(m1['Spc'].iloc[0]) if 'Spc' in m1.columns else ''
        print(f'[compute_aging] M_ID_1={mid_1}, MSK={msk!r}, '
              f'Spc={spc_name!r}, File={file_1!r}')

        # --- 2. Нормы из спецификации ---
        norms = load_spec_old(spc_name)
        if not norms:
            raise ValueError(f'Не найдена спецификация {spc_name!r}')
        print(f'[compute_aging] Norms: {norms}')

        # --- 3. Формирование пар (F1/R1 ↔ F2/R2) ---
        if auto_search:
            print('[compute_aging] auto_search=True')
            old_per_n = find_old_measurements_for_batch(m1, spc_name, mid_1)
            if old_per_n.empty:
                raise ValueError(
                    'Автопоиск вернул пустой DataFrame — нет данных')

            found_n = int(old_per_n['Measure_ID_2'].notna().sum())
            print(f'[compute_aging] найдено старых замеров: '
                  f'{found_n} из {len(old_per_n)}')

            if found_n == 0:
                raise ValueError(
                    f'Автопоиск не нашёл ни одного старого замера '
                    f'для N из Measure_ID={mid_1}.\n'
                    f'Проверьте, что для этих резонаторов есть замеры '
                    f'без температурных параметров (Fptp IS NULL/0, '
                    f'Tmax/Tmin IS NULL), и что Measure_ID < {mid_1}.')

            first_slim = m1[['N', 'F', 'R']].copy()
            first_slim.columns = ['N', 'F1', 'R1']
            pairs = first_slim.merge(old_per_n, on='N', how='inner')

            # Отбрасываем N, у которых старый замер не нашёлся
            # (Measure_ID_2 == NaN) или пустые F2/R2
            pairs = pairs.dropna(
                subset=['Measure_ID_2', 'F2', 'R2']
            ).reset_index(drop=True)
            if pairs.empty:
                raise ValueError(
                    'Все найденные старые замеры имеют пустые F/R — '
                    'расчёт невозможен.')

            print(f'[compute_aging] к сравнению допущено: '
                  f'{len(pairs)} пар')
            file_2 = 'AUTO'
            mid_2_used = 'AUTO'

        else:
            mid_2 = _as_int(measure_id_2)
            if mid_2 is None:
                raise ValueError(
                    f'Некорректный «Код замера 2»: {measure_id_2!r}')

            m2 = load_measure_by_id(mid_2)
            if m2.empty:
                raise ValueError(
                    f'В psidata нет данных для Measure_ID={mid_2}')

            file_2 = str(m2['File'].iloc[0]) if 'File' in m2.columns else ''

            a = m1[['N', 'F', 'R']].copy()
            a.columns = ['N', 'F1', 'R1']
            b = m2[['N', 'F', 'R']].copy()
            b.columns = ['N', 'F2', 'R2']
            pairs = b.merge(a, on='N', how='inner')
            if pairs.empty:
                raise ValueError(
                    f'Нет совпадающих N между Measure_ID={mid_1} '
                    f'и Measure_ID={mid_2}')

            pairs['Measure_ID_2'] = mid_2
            pairs['File_2'] = file_2
            pairs['MSK_2'] = None
            pairs['Date_2'] = None
            mid_2_used = str(mid_2)
            print(f'[compute_aging] manual compare: {len(pairs)} matched')

        # --- 4. Расчёт разностей ---
        pairs['diffF'] = pairs['F2'] - pairs['F1']            # знаковая
        pairs['diffR_signed'] = pairs['R2'] - pairs['R1']     # знаковая
        pairs['diffR'] = pairs['diffR_signed'].abs()          # для БД (old2)

        # --- 5. Динамическая норма ---
        dyn_norm = _compute_dynamic_norm(pairs)
        print(f'[compute_aging] dyn norm: '
              f'meanR={dyn_norm["meanR"]}, '
              f'sigma={dyn_norm["sigma"]}, '
              f'[{dyn_norm["lower"]}; {dyn_norm["upper"]}]')

        # --- 6. Статусы ---
        data = _evaluate_status(pairs, norms, dyn_norm)

        # --- 7. Запись в psi_measure_old_id ---
        old_id = _insert_old_id(msk, mid_1, file_1, file_2)
        print(f'[compute_aging] created psi_measure_old_id.ID = {old_id}')

        # --- 8. Запись строк в old ---
        _insert_old_rows(
            old_id=old_id, msk=msk, spc_name=spc_name,
            file_1=file_1, file_2=file_2, measure_id_1=mid_1,
            data=data, operator=operator,
        )

        # --- 9. Счётчики в psi_measure_old_id ---
        total = len(data)
        good = int((data['Status'] == 'Годен').sum())
        bad = total - good
        _update_old_id_counters(old_id, total, bad, good)
        print(f'[compute_aging] DONE: old_id={old_id}, total={total}, '
              f'good={good}, bad={bad}')

        return {
            'old_id': old_id,
            'spc_name': spc_name,
            'measure_id_1': str(mid_1),
            'measure_id_2': mid_2_used,
            'msk': msk,
            'file_1': file_1,
            'file_2': file_2,
            'norms': norms,
            'dyn_norm': dyn_norm,
            'data': data,
            'stats': {'total': total, 'good': good, 'bad': bad},
        }

    except Exception as e:
        print(f'[compute_aging] ERROR: {e}')
        traceback.print_exc()
        raise

def compute_aging_1(measure_id_1,
                  measure_id_2=None,
                  operator: str = '',
                  auto_search: bool = True) -> dict:
    """Полный расчёт старения.

    Если auto_search=True — measure_id_2 игнорируется; для каждого N
    из первого замера ищется «старый» замер без темп. параметров.
    Если auto_search=False — оба замера указаны явно.
    """
    try:
        mid_1 = _as_int(measure_id_1)
        if mid_1 is None:
            raise ValueError(f'Некорректный «Код замера 1»: {measure_id_1!r}')

        m1 = load_measure_by_id(mid_1)
        if m1.empty:
            raise ValueError(f'В psidata нет данных для Measure_ID={mid_1}')

        msk = str(m1['MSK'].iloc[0]) if 'MSK' in m1.columns else ''
        file_1 = str(m1['File'].iloc[0]) if 'File' in m1.columns else ''
        spc_name = str(m1['Spc'].iloc[0]) if 'Spc' in m1.columns else ''
        print(f'[compute_aging] M_ID_1={mid_1}, MSK={msk!r}, '
              f'Spc={spc_name!r}, File={file_1!r}')

        norms = load_spec_old(spc_name)
        if not norms:
            raise ValueError(f'Не найдена спецификация {spc_name!r}')
        print(f'[compute_aging] Norms: {norms}')

        if auto_search:
            print('[compute_aging] auto_search=True')
            old_per_n = find_old_measurements_for_batch(m1, spc_name, mid_1)
            if old_per_n.empty:
                raise ValueError('Не удалось найти старые замеры для N')
            first_slim = m1[['N', 'F', 'R']].copy()
            first_slim.columns = ['N', 'F1', 'R1']
            pairs = first_slim.merge(old_per_n, on='N', how='inner')
            if pairs.empty:
                raise ValueError('Ни один N не имеет старого замера')
            file_2 = 'AUTO'
            mid_2_used = 'AUTO'
        else:
            mid_2 = _as_int(measure_id_2)
            if mid_2 is None:
                raise ValueError(
                    f'Некорректный «Код замера 2»: {measure_id_2!r}')
            m2 = load_measure_by_id(mid_2)
            if m2.empty:
                raise ValueError(f'В psidata нет данных для Measure_ID={mid_2}')
            file_2 = str(m2['File'].iloc[0]) if 'File' in m2.columns else ''
            a = m1[['N', 'F', 'R']].copy()
            a.columns = ['N', 'F1', 'R1']
            b = m2[['N', 'F', 'R']].copy()
            b.columns = ['N', 'F2', 'R2']
            pairs = b.merge(a, on='N', how='inner')
            if pairs.empty:
                raise ValueError('Нет совпадающих N между замерами')
            pairs['Measure_ID_2'] = mid_2
            pairs['File_2'] = file_2
            mid_2_used = str(mid_2)
            print(f'[compute_aging] manual compare: {len(pairs)} matched')

        pairs['diffF'] = pairs['F2'] - pairs['F1']
        pairs['diffR_signed'] = pairs['R2'] - pairs['R1']
        pairs['diffR'] = pairs['diffR_signed'].abs()

        dyn_norm = _compute_dynamic_norm(pairs)
        print(f'[compute_aging] dyn norm: meanR={dyn_norm["meanR"]}, '
              f'sigma={dyn_norm["sigma"]}, '
              f'[{dyn_norm["lower"]}; {dyn_norm["upper"]}]')

        data = _evaluate_status(pairs, norms, dyn_norm)

        old_id = _insert_old_id(msk, mid_1, file_1, file_2)
        print(f'[compute_aging] created psi_measure_old_id.ID = {old_id}')

        _insert_old_rows(
            old_id=old_id, msk=msk, spc_name=spc_name,
            file_1=file_1, file_2=file_2, measure_id_1=mid_1,
            data=data, operator=operator,
        )

        total = len(data)
        good = int((data['Status'] == 'Годен').sum())
        bad = total - good
        _update_old_id_counters(old_id, total, bad, good)
        print(f'[compute_aging] DONE: old_id={old_id}, total={total}, '
              f'good={good}, bad={bad}')

        return {
            'old_id': old_id,
            'spc_name': spc_name,
            'measure_id_1': str(mid_1),
            'measure_id_2': mid_2_used,
            'msk': msk,
            'file_1': file_1,
            'file_2': file_2,
            'norms': norms,
            'dyn_norm': dyn_norm,
            'data': data,
            'stats': {'total': total, 'good': good, 'bad': bad},
        }
    except Exception as e:
        print(f'[compute_aging] ERROR: {e}')
        traceback.print_exc()
        raise


# ---------------------------------------------------------------------------
#                          Вспомогательные
# ---------------------------------------------------------------------------
def _compute_dynamic_norm(df) -> dict:
    if df.empty:
        return {'meanR': None, 'sigma': None, 'lower': None, 'upper': None}
    n = len(df)
    vals = df['diffR_signed'].astype(float)
    mean_r = float(vals.sum()) / n
    if n > 1:
        var = float(((vals - mean_r) ** 2).sum()) / (n - 1)
        sigma = math.sqrt(var) if var > 0 else 0.0
    else:
        sigma = 0.0
    return {
        'meanR': mean_r, 'sigma': sigma,
        'lower': mean_r - 2.0 * sigma,
        'upper': mean_r + 2.0 * sigma,
    }


def _evaluate_status(df, norms, dyn_norm) -> pd.DataFrame:
    out = df.copy()
    f_min, f_max = norms.get('old1min'), norms.get('old1max')
    r_min, r_max = norms.get('old2min'), norms.get('Old2Max')
    dyn_lo, dyn_hi = dyn_norm.get('lower'), dyn_norm.get('upper')

    def _check(row):
        dF = row['diffF']
        dR = row['diffR_signed']
        if f_min is not None and dF < f_min: return 'Брак'
        if f_max is not None and dF > f_max: return 'Брак'
        if r_min is not None and dR < r_min: return 'Брак'
        if r_max is not None and dR > r_max: return 'Брак'
        if dyn_lo is not None and dyn_hi is not None:
            if dR < dyn_lo or dR > dyn_hi: return 'Брак'
        return 'Годен'

    out['Status'] = out.apply(_check, axis=1)
    return out


def _insert_old_id(msk, measure_id_1, file_1, file_2) -> int:
    sql = text(f"""
        INSERT INTO `{OLD_ID_TABLE}`
            (MSK, Measure_ID, File_1, File_2, Psi_Measure_ID)
        VALUES
            (:msk, :measure_id, :file_1, :file_2, :psi_measure_id)
    """)
    params = {
        'msk': msk,
        'measure_id': int(measure_id_1),
        'file_1': (file_1 or '')[:50],
        'file_2': (file_2 or '')[:50],
        'psi_measure_id': int(measure_id_1),
    }
    print(f'[aging] INSERT {OLD_ID_TABLE}: {params}')
    return insert_and_get_id(str(sql), params)


def _insert_old_rows(old_id, msk, spc_name, file_1, file_2,
                     measure_id_1, data: pd.DataFrame, operator: str):
    if data.empty:
        return
    engine = get_engine()
    with engine.connect() as conn:
        result = conn.execute(text("DESCRIBE old"))
        target_cols = {row[0] for row in result}

    records = []
    for _, r in data.iterrows():
        row = {
            'MSK': msk,
            'N': r['N'],
            'Old_ID': old_id,
            'MeasureID': _as_int(r.get('Measure_ID_2')) or measure_id_1,
            'Spc': spc_name,
            'File1': (file_1 or '')[:50],
            'File2': (r.get('File_2') or file_2 or '')[:50],
            'Measure1': r['F1'],
            'Measure2': r['F2'],
            'Measure1_R': r['R1'],
            'Measure2_R': r['R2'],
            'old1': r['diffF'],
            'old2': r['diffR'],
            'Status': r['Status'],
            'Operator': operator,
            'M1': 1,
            'M2': 1,
            'Old1B': 1,
            'Old2B': 1,
        }
        records.append({k: _safe_value(v) for k, v in row.items()
                        if k in target_cols})

    if not records:
        print('[aging] _insert_old_rows: nothing to insert')
        return
    df_insert = pd.DataFrame(records)
    print(f'[aging] INSERT old: {len(df_insert)} rows')
    df_insert.to_sql('old', engine, if_exists='append', index=False)
    print('[aging] old rows inserted')


def _update_old_id_counters(old_id, total, bad, good):
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text(f"""
                UPDATE `{OLD_ID_TABLE}`
                   SET all_counter  = :total,
                       bad_counter  = :bad,
                       good_counter = :good
                 WHERE ID = :old_id
            """),
            {'total': total, 'bad': bad, 'good': good, 'old_id': old_id},
        )
    print(f'[aging] counters updated: id={old_id}, '
          f'all={total}, bad={bad}, good={good}')


# ---------------------------------------------------------------------------
#                    Загрузка для печати
# ---------------------------------------------------------------------------
def load_old_by_id(old_id) -> pd.DataFrame:
    oid = _as_int(old_id)
    if oid is None:
        return pd.DataFrame()
    return execute_query(f"SELECT * FROM old WHERE Old_ID = {oid} ORDER BY N")


def load_old_id_meta(old_id) -> dict:
    oid = _as_int(old_id)
    if oid is None:
        return {}
    df = execute_query(f"SELECT * FROM `{OLD_ID_TABLE}` WHERE ID = {oid}")
    return {} if df.empty else df.iloc[0].to_dict()


# ---------------------------------------------------------------------------
#                    Утилиты
# ---------------------------------------------------------------------------
def _as_int(v):
    if v is None:
        return None
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _as_float_or_none(v):
    if v is None:
        return None
    s = str(v).strip()
    if s == '' or s.lower() in ('no', 'none', 'nan'):
        return None
    try:
        return float(s.replace(',', '.'))
    except (TypeError, ValueError):
        return None


def _safe_value(v):
    if v is None:
        return None
    if isinstance(v, (bool, np.bool_)):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        fv = float(v)
        if math.isnan(fv) or math.isinf(fv):
            return None
        return fv
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v

# ---------------------------------------------------------------------------
#              Поиск Measure_ID по частичному номеру резонатора
# ---------------------------------------------------------------------------
def search_measure_ids_by_number_partial_1(partial: str,
                                          limit: int = 500) -> pd.DataFrame:
    """Поиск Measure_ID по подстроке номера: N LIKE '%partial%'.

    Возвращает DataFrame:
        Measure_ID, Sample_N, MSK, Date, Numbers_Count
    Отсортировано по Measure_ID DESC (свежие сверху).
    """
    if not partial or not str(partial).strip():
        return pd.DataFrame()

    pattern = f'%{str(partial).strip()}%'
    safe = pattern.replace("'", "''")
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
    print(f'[aging_logic.search_by_number] SQL: {sql}')
    try:
        return execute_query(sql)
    except Exception as e:
        print(f'[aging_logic.search_by_number] error: {e}')
        traceback.print_exc()
        return pd.DataFrame()

# ---------------------------------------------------------------------------
#          Поиск Measure_ID по частичному номеру через lookup-таблицу
# ---------------------------------------------------------------------------
def _get_archive_lookup_module():
    """Импорт Archive_Lookup из любого из двух возможных пакетов."""
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
    print('[aging_logic] Archive_Lookup недоступен — '
          'поиск пойдёт напрямую по psidata')
    return None


def _safe_sql_str(s) -> str:
    return str(s).replace("'", "''")
def search_measure_ids_by_number_partial(partial, limit: int = 500) -> pd.DataFrame:
    """Поиск Measure_ID по подстроке номера резонатора.

    Fallback к psidata выполняется ТОЛЬКО если lookup не может
    ответить полностью:
      * lookup пуст (0 результатов) — номер отсутствует в справочнике;
      * lookup достиг limit (возможна усечённая выдача);
      * lookup недоступен (Archive_Lookup не импортировался).

    Если 0 < count < limit — lookup покрывает запрос, fallback
    пропускается (быстрый путь).
    """
    import time

    if partial is None:
        return pd.DataFrame()
    partial_s = str(partial).strip()
    if not partial_s:
        return pd.DataFrame()

    upper = partial_s.upper()
    safe_upper = _safe_sql_str(upper)
    safe_like = _safe_sql_str(f'%{partial_s}%')

    engine = get_engine()
    Lookup = _get_archive_lookup_module()

    # ---------------------------------------------------------- 1) lookup
    t0 = time.time()
    mids_from_lookup: set[int] = set()
    lookup_ok = False
    if Lookup is not None:
        try:
            Lookup.ensure_lookup_table(engine)
            sql = (
                f"SELECT DISTINCT measure_id "
                f"FROM `{Lookup.LOOKUP_TABLE}` "
                f"WHERE n_normalized LIKE '%{safe_upper}%' "
                f"LIMIT {int(limit)}"
            )
            print(f'[aging.search] lookup SQL: {sql}')
            df_lk = pd.read_sql(sql, engine)
            mids_from_lookup = {
                int(x) for x in df_lk['measure_id'].dropna().unique()
            }
            lookup_ok = True
        except Exception as e:
            print(f'[aging.search] lookup error: {e}')
            traceback.print_exc()

    t1 = time.time()
    print(f'[aging.search] lookup: {len(mids_from_lookup)} ids '
          f'in {(t1 - t0) * 1000:.1f} ms')

    # --------------------------------------- 2) решаем, нужен ли fallback
    lookup_truncated = len(mids_from_lookup) >= limit
    lookup_empty = len(mids_from_lookup) == 0
    need_fallback = (
        not lookup_ok       # lookup недоступен
        or lookup_empty     # ничего не нашли в справочнике
        or lookup_truncated  # возможно, усечено лимитом
    )

    mids_from_fallback: set[int] = set()
    fallback_pairs: list[tuple[int, str]] = []

    if need_fallback:
        reason = (
            'lookup unavailable' if not lookup_ok
            else 'lookup empty' if lookup_empty
            else f'lookup truncated ({len(mids_from_lookup)}={limit})'
        )
        print(f'[aging.search] fallback REQUIRED ({reason})')

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
            print(f'[aging.search] fallback SQL: {sql_fb}')
            df_fb = pd.read_sql(sql_fb, engine)
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
        except Exception as e:
            print(f'[aging.search] fallback error: {e}')
            traceback.print_exc()

        t2 = time.time()
        print(f'[aging.search] fallback: {len(mids_from_fallback)} ids '
              f'in {(t2 - t1) * 1000:.1f} ms')

        # self-heal: добавляем в lookup то, чего там не было
        if Lookup is not None and lookup_ok and fallback_pairs:
            missing = [(m, n) for m, n in fallback_pairs
                       if m not in mids_from_lookup]
            if missing:
                try:
                    added = Lookup.add_pairs_to_lookup(
                        missing, engine=engine)
                    print(f'[aging.search] self-heal: +{added} pairs')
                except Exception as e:
                    print(f'[aging.search] self-heal error: {e}')
    else:
        print(f'[aging.search] fallback SKIPPED '
              f'(lookup covers query: {len(mids_from_lookup)} < {limit})')

    all_mids = mids_from_lookup | mids_from_fallback
    if not all_mids:
        return pd.DataFrame()

    # ------------------------------ 3) детали по measure_ids
    from sqlalchemy import bindparam, text as sqltext

    t3 = time.time()
    mids_list = sorted(all_mids)[:int(limit)]
    stmt = sqltext(
        "SELECT Measure_ID, MIN(N) AS Sample_N, "
        "MIN(MSK) AS MSK, MIN(Date) AS Date, "
        "COUNT(*) AS Numbers_Count "
        "FROM psidata "
        "WHERE Measure_ID IN :mids "
        f"  AND N LIKE '{safe_like}' "
        "GROUP BY Measure_ID "
        "ORDER BY Measure_ID DESC"
    ).bindparams(bindparam("mids", expanding=True))

    try:
        df = pd.read_sql(stmt, engine, params={'mids': mids_list})
        t4 = time.time()
        print(f'[aging.search] details: {len(df)} rows '
              f'in {(t4 - t3) * 1000:.1f} ms')
        print(f'[aging.search] TOTAL: {(t4 - t0) * 1000:.1f} ms')
        return df
    except Exception as e:
        print(f'[aging.search] details error: {e}')
        traceback.print_exc()
        return pd.DataFrame()

def search_measure_ids_by_number_partial_2(partial, limit: int = 500) -> pd.DataFrame:
    """Поиск Measure_ID по подстроке номера резонатора.

    Приоритет:
      1) psidata_resonator_lookup — узкая таблица с индексом (быстро);
      2) fallback на psidata.N LIKE '%partial%' — если в lookup пусто,
         найдёт всё, включая строки, которых ещё нет в справочнике;
      3) self-heal: найденные в fallback пары записываются в lookup,
         чтобы следующий поиск шёл через быструю таблицу.

    Возвращает DataFrame:
        Measure_ID, Sample_N, MSK, Date, Numbers_Count
    Отсортировано по Measure_ID DESC (свежие сверху).
    """
    if partial is None:
        return pd.DataFrame()
    partial_s = str(partial).strip()
    if not partial_s:
        return pd.DataFrame()

    upper = partial_s.upper()
    safe_upper = _safe_sql_str(upper)
    safe_like = _safe_sql_str(f'%{partial_s}%')

    engine = get_engine()
    Lookup = _get_archive_lookup_module()

    # ---------------------------------------------------------- 1) lookup
    mids_from_lookup: set[int] = set()
    lookup_ok = False
    if Lookup is not None:
        try:
            Lookup.ensure_lookup_table(engine)
            sql = (
                f"SELECT DISTINCT measure_id "
                f"FROM `{Lookup.LOOKUP_TABLE}` "
                f"WHERE n_normalized LIKE '%{safe_upper}%' "
                f"LIMIT {int(limit)}"
            )
            print(f'[aging.search] lookup SQL: {sql}')
            df_lk = pd.read_sql(sql, engine)
            mids_from_lookup = {
                int(x) for x in df_lk['measure_id'].dropna().unique()
            }
            lookup_ok = True
            print(f'[aging.search] lookup -> '
                  f'{len(mids_from_lookup)} measure_ids')
        except Exception as e:
            print(f'[aging.search] lookup error: {e}')
            traceback.print_exc()

    # ------------------------------------------------ 2) fallback psidata
    mids_from_fallback: set[int] = set()
    fallback_pairs: list[tuple[int, str]] = []
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
        print(f'[aging.search] fallback SQL: {sql_fb}')
        df_fb = pd.read_sql(sql_fb, engine)
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
        print(f'[aging.search] fallback -> '
              f'{len(mids_from_fallback)} measure_ids')
    except Exception as e:
        print(f'[aging.search] fallback error: {e}')
        traceback.print_exc()

    # -------------------------------------------------- 3) self-heal
    if Lookup is not None and lookup_ok and fallback_pairs:
        missing = [(m, n) for m, n in fallback_pairs
                   if m not in mids_from_lookup]
        if missing:
            try:
                added = Lookup.add_pairs_to_lookup(missing, engine=engine)
                print(f'[aging.search] self-heal: +{added} pairs')
            except Exception as e:
                print(f'[aging.search] self-heal error: {e}')

    all_mids = mids_from_lookup | mids_from_fallback
    if not all_mids:
        return pd.DataFrame()

    # ------------------------------ 4) детали по measure_ids
    from sqlalchemy import bindparam, text as sqltext

    mids_list = sorted(all_mids)[:int(limit)]
    stmt = sqltext(
        "SELECT Measure_ID, MIN(N) AS Sample_N, "
        "MIN(MSK) AS MSK, MIN(Date) AS Date, "
        "COUNT(*) AS Numbers_Count "
        "FROM psidata "
        "WHERE Measure_ID IN :mids "
        f"  AND N LIKE '{safe_like}' "
        "GROUP BY Measure_ID "
        "ORDER BY Measure_ID DESC"
    ).bindparams(bindparam("mids", expanding=True))

    try:
        df = pd.read_sql(stmt, engine, params={'mids': mids_list})
        print(f'[aging.search] details: {len(df)} rows')
        return df
    except Exception as e:
        print(f'[aging.search] details error: {e}')
        traceback.print_exc()
        return pd.DataFrame()