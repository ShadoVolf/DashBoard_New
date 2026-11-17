"""Загрузка/сохранение пула и пар в БД."""
import pandas as pd
from sqlalchemy import create_engine, text, bindparam

from Options import get_connection_string
from .Pairs_DDL import (
    POOL_TABLE, PAIRS_TABLE, ensure_pairs_tables, log_operation,
)


def _engine():
    return create_engine(str(get_connection_string()))


# ----------------------------------------------------------------------------
# Поиск полей F и R в psidata
# ----------------------------------------------------------------------------
def _find_f_r_columns(df: pd.DataFrame) -> tuple[str | None, str | None]:
    """Найти колонки F и R в DataFrame из psidata."""
    if df is None or df.empty:
        return None, None
    f_col = next((c for c in ('F', 'f', 'F_meas', 'F0') if c in df.columns),
                 None)
    r_col = next((c for c in ('R', 'r', 'R_meas', 'R0') if c in df.columns),
                 None)
    if f_col and r_col:
        return f_col, r_col
    # Fallback через карту Field'ов
    try:
        from Archive_View.Archive_Data import get_psidata_field_map
        fmap = get_psidata_field_map()           # {Parameter: Field}
        for param, field in fmap.items():
            pu = str(param).upper()
            if f_col is None and pu in ('F0', 'F') and field in df.columns:
                f_col = field
            if r_col is None and pu in ('R0', 'R') and field in df.columns:
                r_col = field
    except Exception:
        pass
    return f_col or 'F', r_col or 'R'


# ----------------------------------------------------------------------------
# Пул
# ----------------------------------------------------------------------------
def add_measurement_to_pool(measure_id: int,
                            user: str | None = None) -> int:
    """
    Добавить ВСЕ резонаторы из замера measure_id в пул.
    Идемпотентно: старые записи этого measure_id удаляются.

    Возвращает число добавленных строк.
    """
    engine = _engine()
    ensure_pairs_tables(engine)

    try:
        df = pd.read_sql(
            text("SELECT Measure_ID, Spc, MSK, N, Position, F, R "
                 "FROM psidata WHERE Measure_ID = :m"),
            engine, params={'m': int(measure_id)},
        )
    except Exception as e:
        print(f"[Pairs] add_measurement_to_pool SQL error: {e}")
        return 0

    if df.empty:
        return 0

    f_col, r_col = _find_f_r_columns(df)

    def _safe_str(v):
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        s = str(v).strip()
        return s if s and s.lower() not in ('none', 'nan') else None

    def _safe_float(v):
        if v is None:
            return None
        try:
            if pd.isna(v):
                return None
        except (TypeError, ValueError):
            pass
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    rows = []
    for _, r in df.iterrows():
        n_str = _safe_str(r.get('N'))
        if not n_str:
            continue
        n_str = n_str.upper()
        rows.append({
            'mid': int(r['Measure_ID']),
            'spc': _safe_str(r.get('Spc')),
            'msk': _safe_str(r.get('MSK')),
            'n':   n_str,
            # position теперь строка: 'B33', 'A1', ...
            'pos': _safe_str(r.get('Position')),
            'f':   _safe_float(r.get(f_col)) if f_col else None,
            'r':   _safe_float(r.get(r_col)) if r_col else None,
        })

    if not rows:
        return 0

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM `{POOL_TABLE}` WHERE measure_id = :m"),
            {'m': int(measure_id)},
        )
        conn.execute(
            text(f"INSERT INTO `{POOL_TABLE}` "
                 f"(measure_id, spc, msk, n_normalized, position, "
                 f" f_value, r_value) "
                 f"VALUES (:mid, :spc, :msk, :n, :pos, :f, :r)"),
            rows,
        )

    log_operation('pool_add',
                  f'measure_id={measure_id}, rows={len(rows)}', user)
    return len(rows)

def add_measurement_to_pool_1(measure_id: int,
                            user: str | None = None) -> int:
    """
    Добавить ВСЕ резонаторы из замера measure_id в пул.
    Идемпотентно: старые записи этого measure_id удаляются.

    Возвращает число добавленных строк.
    """
    engine = _engine()
    ensure_pairs_tables(engine)

    try:
        df = pd.read_sql(
            text("SELECT Measure_ID, Spc, MSK, N, Position, F, R "
                 "FROM psidata WHERE Measure_ID = :m"),
            engine, params={'m': int(measure_id)},
        )
    except Exception as e:
        print(f"[Pairs] add_measurement_to_pool SQL error: {e}")
        return 0

    if df.empty:
        return 0

    f_col, r_col = _find_f_r_columns(df)

    rows = []
    for _, r in df.iterrows():
        n_raw = r.get('N')
        n_str = (str(n_raw).strip().upper()
                 if pd.notna(n_raw) else None)
        if not n_str:
            continue
        rows.append({
            'mid': int(r['Measure_ID']),
            'spc': str(r['Spc']) if pd.notna(r.get('Spc')) else None,
            'msk': str(r['MSK']) if pd.notna(r.get('MSK')) else None,
            'n':   n_str,
            'pos': int(r['Position']) if pd.notna(r.get('Position')) else None,
            'f':   float(r[f_col]) if f_col and pd.notna(r.get(f_col)) else None,
            'r':   float(r[r_col]) if r_col and pd.notna(r.get(r_col)) else None,
        })

    if not rows:
        return 0

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM `{POOL_TABLE}` WHERE measure_id = :m"),
            {'m': int(measure_id)},
        )
        conn.execute(
            text(f"INSERT INTO `{POOL_TABLE}` "
                 f"(measure_id, spc, msk, n_normalized, position, "
                 f" f_value, r_value) "
                 f"VALUES (:mid, :spc, :msk, :n, :pos, :f, :r)"),
            rows,
        )

    log_operation('pool_add',
                  f'measure_id={measure_id}, rows={len(rows)}', user)
    return len(rows)


def remove_from_pool(ids: list[int], user: str | None = None) -> int:
    if not ids:
        return 0
    engine = _engine()
    ensure_pairs_tables(engine)
    sql = text(f"DELETE FROM `{POOL_TABLE}` WHERE id IN :ids"
               ).bindparams(bindparam("ids", expanding=True))
    with engine.begin() as conn:
        res = conn.execute(sql, {'ids': [int(i) for i in ids]})
    log_operation('pool_remove', f'ids={ids}', user)
    return res.rowcount or 0


def clear_pool(user: str | None = None) -> int:
    """Удаляет только свободные записи (использованные — сохраняются)."""
    engine = _engine()
    ensure_pairs_tables(engine)
    with engine.begin() as conn:
        res = conn.execute(
            text(f"DELETE FROM `{POOL_TABLE}` WHERE status = 'free'")
        )
    log_operation('pool_clear', f'removed={res.rowcount}', user)
    return res.rowcount or 0


def load_pool() -> pd.DataFrame:
    engine = _engine()
    ensure_pairs_tables(engine)
    try:
        return pd.read_sql(
            text(f"SELECT * FROM `{POOL_TABLE}` "
                 f"ORDER BY spc, msk, n_normalized"),
            engine,
        )
    except Exception as e:
        print(f"[Pairs] load_pool error: {e}")
        return pd.DataFrame()


# ----------------------------------------------------------------------------
# Сохранение пар
# ----------------------------------------------------------------------------
def save_pairs_to_db(pairs_df: pd.DataFrame,
                     user: str | None = None) -> int:
    """
    Сохранить выбранные пары и пометить использованные записи пула.
    Возвращает число сохранённых пар.
    """
    if pairs_df is None or pairs_df.empty:
        return 0

    engine = _engine()
    ensure_pairs_tables(engine)

    saved = 0
    with engine.begin() as conn:
        for _, r in pairs_df.iterrows():
            res = conn.execute(
                text(f"INSERT INTO `{PAIRS_TABLE}` "
                     f"(measure_id_1, measure_id_2, n_1, n_2, "
                     f" spc_1, spc_2, msk_1, msk_2, "
                     f" f_1, f_2, r_1, r_2, "
                     f" delta_f, delta_r, created_by, notes) "
                     f"VALUES (:m1, :m2, :n1, :n2, "
                     f"        :s1, :s2, :k1, :k2, "
                     f"        :f1, :f2, :r1, :r2, "
                     f"        :df, :dr, :usr, :notes)"),
                {
                    'm1': int(r['measure_id_1']),
                    'm2': int(r['measure_id_2']),
                    'n1': r.get('n_1'),
                    'n2': r.get('n_2'),
                    's1': r.get('spc_1'),
                    's2': r.get('spc_2'),
                    'k1': r.get('msk_1'),
                    'k2': r.get('msk_2'),
                    'f1': _f(r.get('f_1')),
                    'f2': _f(r.get('f_2')),
                    'r1': _f(r.get('r_1')),
                    'r2': _f(r.get('r_2')),
                    'df': _f(r.get('delta_f')),
                    'dr': _f(r.get('delta_r')),
                    'usr': user,
                    'notes': r.get('notes'),
                },
            )
            pair_id = res.lastrowid
            p1 = r.get('pool_id_1')
            p2 = r.get('pool_id_2')
            if p1 and p2:
                conn.execute(
                    text(f"UPDATE `{POOL_TABLE}` "
                         f"SET status = 'used', pair_id = :pid "
                         f"WHERE id IN (:i1, :i2)"),
                    {'pid': pair_id, 'i1': int(p1), 'i2': int(p2)},
                )
            saved += 1

    log_operation('pairs_save', f'saved={saved}', user)
    return saved


def _f(v):
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


# ----------------------------------------------------------------------------
# Очистка "used" в пуле (для повторного использования)
# ----------------------------------------------------------------------------
def reset_used_in_pool(user: str | None = None) -> int:
    engine = _engine()
    ensure_pairs_tables(engine)
    with engine.begin() as conn:
        res = conn.execute(
            text(f"UPDATE `{POOL_TABLE}` "
                 f"SET status='free', pair_id=NULL WHERE status='used'"))
    log_operation('pool_reset_used', f'reset={res.rowcount}', user)
    return res.rowcount or 0

def load_pairs_from_db(limit=None, date_from=None, date_to=None):
    """
    Загрузить сохранённые пары из таблицы resonator_pairs.

    Параметры:
      limit      : int | None  — сколько последних записей вернуть;
      date_from  : str | None  — начальная дата 'YYYY-MM-DD' или
                                  'YYYY-MM-DD HH:MM:SS';
      date_to    : str | None  — конечная дата.

    Если для даты указан только день (10 символов), для date_from
    автоматически добавляется '00:00:00', для date_to — '23:59:59'.
    """
    engine = _engine()
    ensure_pairs_tables(engine)

    conds, params = [], {}

    if date_from:
        df_str = str(date_from).strip()
        if len(df_str) == 10:
            df_str = df_str + ' 00:00:00'
        conds.append("created_at >= :dt_from")
        params['dt_from'] = df_str

    if date_to:
        dt_str = str(date_to).strip()
        if len(dt_str) == 10:
            dt_str = dt_str + ' 23:59:59'
        conds.append("created_at <= :dt_to")
        params['dt_to'] = dt_str

    where = " AND ".join(conds) if conds else "1=1"
    limit_sql = f"LIMIT {int(limit)}" if limit else ""

    sql = text(
        f"SELECT id, measure_id_1, measure_id_2, n_1, n_2, "
        f"       spc_1, spc_2, msk_1, msk_2, "
        f"       f_1, f_2, r_1, r_2, delta_f, delta_r, "
        f"       created_at, created_by, notes "
        f"FROM `{PAIRS_TABLE}` "
        f"WHERE {where} "
        f"ORDER BY id DESC {limit_sql}"
    )
    try:
        df = pd.read_sql(sql, engine, params=params)
    except Exception as e:
        print(f"[Pairs] load_pairs_from_db error: {e}")
        return pd.DataFrame()

    if df.empty:
        return df

    # signed_delta_f = F1 - F2 (для совместимости с UI)
    if 'f_1' in df.columns and 'f_2' in df.columns:
        try:
            df['signed_delta_f'] = (
                pd.to_numeric(df['f_1'], errors='coerce')
                - pd.to_numeric(df['f_2'], errors='coerce')
            )
        except Exception:
            df['signed_delta_f'] = None

    return df