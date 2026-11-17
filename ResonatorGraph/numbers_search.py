"""Поиск Measure_ID по номерам (с lookup) и по МСК (по подстроке).

Источник данных берётся из constants._source_state (Основная / Временная /
Архивная). Справочник psidata_resonator_lookup индексирует только psidata —
для временной/архивной таблиц выполняется прямой поиск по индексу N.
"""
import re
from typing import Optional

import pandas as pd
from sqlalchemy import create_engine, text, bindparam

from Options import get_connection_string
from .constants import _source_state


_NUM_SPLIT_RE = re.compile(r'[,;\s]+')
_NUM_RANGE_RE = re.compile(r'^([A-Za-z]*)(\d+)\s*-\s*([A-Za-z]*)(\d+)$')

LOOKUP_TABLE = 'psidata_resonator_lookup'


# ---------------------------------------------------------------------------
# Парсер ввода номеров (одиночный / список / диапазон)
# ---------------------------------------------------------------------------
def parse_numbers_input(text) -> Optional[list[str]]:
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None

    result: set[str] = set()
    for part in _NUM_SPLIT_RE.split(text):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            m = _NUM_RANGE_RE.match(part)
            if m:
                pre1, n1, pre2, n2 = m.groups()
                prefix = (pre1 or pre2 or '').upper()
                try:
                    start, end = int(n1), int(n2)
                except ValueError:
                    result.add(part.upper())
                    continue
                if start > end:
                    start, end = end, start
                width = max(len(n1), len(n2))
                if end - start > 10000:
                    end = start + 10000
                for i in range(start, end + 1):
                    result.add(f"{prefix}{i:0{width}d}")
            else:
                result.add(part.upper())
        else:
            result.add(part.upper())

    return sorted(result) if result else None


# ---------------------------------------------------------------------------
# Поиск Measure_ID по номерам
# ---------------------------------------------------------------------------
def _engine():
    return create_engine(str(get_connection_string()))


def find_measure_ids_by_numbers(numbers, only_good: bool = False,
                                engine=None) -> list[int]:
    if not numbers:
        return []
    numbers_set = {str(n).strip().upper() for n in numbers if str(n).strip()}
    if not numbers_set:
        return []

    table = _source_state['main_table']
    engine = engine or _engine()

    # --- Не основная таблица: прямой поиск ------------------------------
    if table != 'psidata':
        cond = ["UPPER(TRIM(N)) IN :nums", "Measure_ID IS NOT NULL"]
        if only_good:
            cond.append("Status2 = 'Good'")
        stmt = (f"SELECT DISTINCT Measure_ID FROM `{table}` "
                f"WHERE " + " AND ".join(cond) + " ORDER BY Measure_ID")
        sql = text(stmt).bindparams(bindparam("nums", expanding=True))
        try:
            df = pd.read_sql(sql, engine,
                             params={'nums': list(numbers_set)})
            return df['Measure_ID'].tolist()
        except Exception as e:
            print(f"[Graphs] Ошибка поиска по {table}: {e}")
            return []

    # --- psidata: lookup + fallback -------------------------------------
    found_nums: set[str] = set()
    found_mids: set[int] = set()

    try:
        sql = text(
            f"SELECT n_normalized, measure_id FROM `{LOOKUP_TABLE}` "
            f"WHERE n_normalized IN :nums"
        ).bindparams(bindparam("nums", expanding=True))
        df = pd.read_sql(sql, engine, params={'nums': list(numbers_set)})
        if not df.empty:
            found_nums = set(df['n_normalized'].astype(str).str.upper())
            found_mids = {int(x) for x in df['measure_id'].unique()}
    except Exception as e:
        print(f"[Graphs] lookup недоступен ({e}), используется fallback")

    missing = numbers_set - found_nums
    if missing:
        try:
            stmt = ("SELECT DISTINCT N, Measure_ID FROM psidata "
                    "WHERE N IN :nums AND Measure_ID IS NOT NULL")
            sql = text(stmt).bindparams(bindparam("nums", expanding=True))
            df = pd.read_sql(sql, engine, params={'nums': list(missing)})
            if not df.empty:
                self_pairs: list[tuple[int, str]] = []
                for _, r in df.iterrows():
                    n_raw, mid_raw = r['N'], r['Measure_ID']
                    if pd.isna(n_raw) or pd.isna(mid_raw):
                        continue
                    n_norm = str(n_raw).strip().upper()
                    mid = int(mid_raw)
                    found_nums.add(n_norm)
                    found_mids.add(mid)
                    self_pairs.append((mid, n_norm))
                if self_pairs:
                    try:
                        with engine.begin() as conn:
                            conn.execute(
                                text(f"INSERT IGNORE INTO `{LOOKUP_TABLE}` "
                                     f"(measure_id, n_normalized) "
                                     f"VALUES (:mid, :n)"),
                                [{'mid': m, 'n': n} for m, n in self_pairs]
                            )
                    except Exception:
                        pass
        except Exception as e:
            print(f"[Graphs] fallback поиск ошибка: {e}")

    if only_good and found_mids:
        try:
            good_mids: set[int] = set()
            mids_list = list(found_mids)
            chunk = 1000
            for i in range(0, len(mids_list), chunk):
                part = mids_list[i:i + chunk]
                sql = text(
                    "SELECT DISTINCT Measure_ID FROM psidata "
                    "WHERE Measure_ID IN :mids AND Status2 = 'Good'"
                ).bindparams(bindparam("mids", expanding=True))
                dfg = pd.read_sql(sql, engine, params={'mids': part})
                good_mids |= {int(x) for x in dfg['Measure_ID'].unique()}
            found_mids = good_mids
        except Exception as e:
            print(f"[Graphs] only_good фильтр ошибка: {e}")

    return sorted(found_mids)


# ---------------------------------------------------------------------------
# Поиск МСК по подстроке в активной таблице
# ---------------------------------------------------------------------------
def search_msk_by_partial(partial: str, engine=None) -> list[str]:
    if not partial:
        return []
    partial = str(partial).strip()
    if not partial:
        return []
    table = _source_state['main_table']
    engine = engine or _engine()
    sql = (f"SELECT DISTINCT MSK FROM `{table}` "
           f"WHERE MSK IS NOT NULL AND MSK LIKE :pat "
           f"ORDER BY MSK")
    try:
        df = pd.read_sql(text(sql), engine, params={'pat': f'%{partial}%'})
        return df['MSK'].dropna().astype(str).tolist()
    except Exception as e:
        print(f"[Graphs] Ошибка поиска МСК: {e}")
        return []