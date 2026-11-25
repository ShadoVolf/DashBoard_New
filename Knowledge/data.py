# -*- coding: utf-8 -*-
"""
Загрузка данных для модуля Knowledge.
Каскад Type -> Spec -> MSK -> Date/File/Measure_ID - по образцу Archive_View / TOC.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from sqlalchemy import create_engine, text

from Options import get_connection_string

from .constants import ALL_MSK, REF_F_COL, TARGET_COL

_engine = None


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_connection_string(), pool_pre_ping=True)
    return _engine


def _main() -> str:
    return "psidata"


# ---------------------------------------------------------------------------
# Каскад (переиспользуем логику Archive, если доступна)
# ---------------------------------------------------------------------------

def get_types() -> List[str]:
    try:
        from Archive_View.Archive_Data import get_archive_types
        return list(get_archive_types() or [])
    except Exception:
        pass
    eng = _get_engine()
    try:
        q = text(f"""
            SELECT DISTINCT Type FROM (
                SELECT COALESCE(psi_type, '') AS Type FROM `{_main()}`
                WHERE COALESCE(psi_type, '') <> ''
            ) t ORDER BY Type
        """)
        df = pd.read_sql(q, eng)
        return [str(x) for x in df["Type"].tolist() if str(x).strip()]
    except Exception:
        return []


def get_specs_by_type(rtype: Optional[str] = None) -> List[str]:
    try:
        from Archive_View.Archive_Data import get_archive_specs_by_type
        if rtype:
            return list(get_archive_specs_by_type(rtype) or [])
    except Exception:
        pass
    eng = _get_engine()
    try:
        if rtype:
            q = text(f"""
                SELECT DISTINCT Spc FROM `{_main()}`
                WHERE Spc IS NOT NULL AND Spc <> ''
                  AND (psi_type = :t OR :t = '')
                ORDER BY Spc
            """)
            df = pd.read_sql(q, eng, params={"t": rtype or ""})
        else:
            q = text(f"""
                SELECT DISTINCT Spc FROM `{_main()}`
                WHERE Spc IS NOT NULL AND Spc <> ''
                ORDER BY Spc
            """)
            df = pd.read_sql(q, eng)
        return [str(x) for x in df["Spc"].tolist() if str(x).strip()]
    except Exception:
        return []


def get_msk_list(spc: Optional[str] = None) -> List[str]:
    try:
        from Archive_View.Archive_Data import get_archive_msk_list
        return list(get_archive_msk_list(spc if spc else None) or [])
    except Exception:
        pass
    eng = _get_engine()
    try:
        if spc:
            q = text(f"""
                SELECT DISTINCT MSK FROM `{_main()}`
                WHERE MSK IS NOT NULL AND MSK <> '' AND Spc = :spc
                ORDER BY MSK
            """)
            df = pd.read_sql(q, eng, params={"spc": spc})
        else:
            q = text(f"""
                SELECT DISTINCT MSK FROM `{_main()}`
                WHERE MSK IS NOT NULL AND MSK <> ''
                ORDER BY MSK
            """)
            df = pd.read_sql(q, eng)
        return [str(x) for x in df["MSK"].tolist() if str(x).strip()]
    except Exception:
        return []


def get_dates_list(msk: Optional[str] = None, spc: Optional[str] = None) -> List[str]:
    try:
        from Archive_View.Archive_Data import get_archive_dates_list
        return list(get_archive_dates_list(msk, spc) or [])
    except Exception:
        pass
    eng = _get_engine()
    try:
        conds = ["Date IS NOT NULL"]
        params: Dict[str, Any] = {}
        if msk and msk != ALL_MSK:
            conds.append("MSK = :msk")
            params["msk"] = msk
        if spc:
            conds.append("Spc = :spc")
            params["spc"] = spc
        where = " AND ".join(conds)
        q = text(f"""
            SELECT DISTINCT DATE_FORMAT(Date, '%Y-%m-%d') AS d
            FROM `{_main()}` WHERE {where}
            ORDER BY d DESC
        """)
        df = pd.read_sql(q, eng, params=params)
        return [str(x) for x in df["d"].tolist() if str(x).strip()]
    except Exception:
        return []


def get_files_list(
    msk: Optional[str] = None,
    spc: Optional[str] = None,
    date: Optional[str] = None,
) -> List[str]:
    try:
        from Archive_View.Archive_Data import get_archive_files_list
        return list(get_archive_files_list(msk, spc, date) or [])
    except Exception:
        pass
    return []


def list_measure_ids(
    msk: Optional[str] = None,
    spc: Optional[str] = None,
    date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Список Measure_ID с метаданными."""
    try:
        from Archive_View.Archive_Data import load_measure_ids_by_msk
        if msk and msk != ALL_MSK:
            mids = load_measure_ids_by_msk(msk) or []
            # load_measure_ids_by_msk может вернуть list[str] или list[dict]
            out = []
            for m in mids:
                if isinstance(m, dict):
                    out.append(m)
                else:
                    out.append({"Measure_ID": int(m) if str(m).isdigit() else m, "MSK": msk})
            return out
    except Exception:
        pass

    eng = _get_engine()
    conds = ["Measure_ID IS NOT NULL"]
    params: Dict[str, Any] = {}
    if msk and msk != ALL_MSK:
        conds.append("MSK = :msk")
        params["msk"] = msk
    if spc:
        conds.append("Spc = :spc")
        params["spc"] = spc
    if date:
        conds.append("DATE(Date) = :dt")
        params["dt"] = date
    where = " AND ".join(conds)
    try:
        q = text(f"""
            SELECT Measure_ID, MSK, Spc,
                   DATE_FORMAT(MIN(Date), '%Y-%m-%d') AS Date,
                   COUNT(*) AS n_count
            FROM `{_main()}`
            WHERE {where}
            GROUP BY Measure_ID, MSK, Spc
            ORDER BY Measure_ID DESC
            LIMIT 500
        """)
        df = pd.read_sql(q, eng, params=params)
        return df.to_dict(orient="records")
    except Exception as e:
        print(f"[Knowledge/data] list_measure_ids: {e}")
        return []


def parse_numbers_input(s: str) -> List[str]:
    try:
        from Archive_View.Archive_Data import parse_numbers_input as _p
        return list(_p(s) or [])
    except Exception:
        pass
    if not s or not str(s).strip():
        return []
    parts = []
    for chunk in str(s).replace(";", ",").replace(" ", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "-" in chunk and chunk.replace("-", "").isdigit():
            a, b = chunk.split("-", 1)
            try:
                lo, hi = int(a), int(b)
                if lo > hi:
                    lo, hi = hi, lo
                parts.extend(str(i) for i in range(lo, hi + 1))
            except ValueError:
                parts.append(chunk)
        else:
            parts.append(chunk)
    return parts


def load_psi_by_measure_id(measure_id: int) -> pd.DataFrame:
    """Все строки psidata для Measure_ID."""
    eng = _get_engine()
    q = text(f"SELECT * FROM `{_main()}` WHERE Measure_ID = :mid")
    df = pd.read_sql(q, eng, params={"mid": int(measure_id)})
    return df


def load_psi_by_msk_numbers(
    msk: str,
    numbers: Sequence[str],
    spc: Optional[str] = None,
) -> pd.DataFrame:
    """Строки по МСК и списку номеров."""
    if not numbers:
        return pd.DataFrame()
    eng = _get_engine()
    nums = [str(n).strip() for n in numbers if str(n).strip()]
    # Number может быть int/str
    placeholders = ", ".join(f":n{i}" for i in range(len(nums)))
    params: Dict[str, Any] = {f"n{i}": n for i, n in enumerate(nums)}
    params["msk"] = msk
    cond = f"MSK = :msk AND CAST(Number AS CHAR) IN ({placeholders})"
    if spc:
        cond += " AND Spc = :spc"
        params["spc"] = spc
    q = text(f"SELECT * FROM `{_main()}` WHERE {cond}")
    return pd.read_sql(q, eng, params=params)


def load_psi_filtered(
    measure_id: Optional[int] = None,
    msk: Optional[str] = None,
    spc: Optional[str] = None,
    numbers: Optional[Sequence[str]] = None,
    date: Optional[str] = None,
) -> pd.DataFrame:
    """Универсальная загрузка с приоритетом: numbers > Measure_ID > msk/spc/date."""
    if numbers and msk and msk != ALL_MSK:
        return load_psi_by_msk_numbers(msk, numbers, spc)
    if measure_id is not None and int(measure_id) > 0:
        return load_psi_by_measure_id(int(measure_id))
    eng = _get_engine()
    conds = ["1=1"]
    params: Dict[str, Any] = {}
    if msk and msk != ALL_MSK:
        conds.append("MSK = :msk")
        params["msk"] = msk
    if spc:
        conds.append("Spc = :spc")
        params["spc"] = spc
    if date:
        conds.append("DATE(Date) = :dt")
        params["dt"] = date
    where = " AND ".join(conds)
    q = text(f"SELECT * FROM `{_main()}` WHERE {where} LIMIT 5000")
    return pd.read_sql(q, eng, params=params)


def resolve_ref_f_mhz(row: pd.Series) -> Optional[float]:
    """Ref_f (Гц) -> МГц; fallback на Nominal если есть."""
    for col in (REF_F_COL, "Ref_F", "ref_f", "REF_F"):
        if col in row.index and pd.notna(row[col]):
            try:
                v = float(row[col])
                if v > 1000:  # похоже на Гц
                    return v / 1e6
                return v  # уже МГц
            except (TypeError, ValueError):
                pass
    for col in ("Nominal", "nominal", "Nom"):
        if col in row.index and pd.notna(row[col]):
            try:
                return float(row[col])
            except (TypeError, ValueError):
                pass
    return None


def spc_contains_rk731(spc: Any) -> bool:
    if spc is None or (isinstance(spc, float) and pd.isna(spc)):
        return False
    return "РК731" in str(spc) or "RK731" in str(spc).upper()


def update_filtr_freq(
    measure_id: int,
    predictions: Dict[Any, float],
    id_col: str = "ID",
) -> int:
    """
    Записать Filtr_Freq в psidata.
    predictions: {ID или Number -> value}.
    Возвращает число обновлённых строк.
    """
    if not predictions:
        return 0
    eng = _get_engine()
    updated = 0
    with eng.begin() as conn:
        # Определяем, есть ли колонка
        cols = pd.read_sql(text(f"SHOW COLUMNS FROM `{_main()}`"), conn)
        col_names = set(cols["Field"].astype(str).str.lower())
        target = TARGET_COL
        if target.lower() not in col_names:
            # пробуем filtr_freq
            if "filtr_freq" in col_names:
                target = "filtr_freq"
            else:
                raise RuntimeError(
                    f"Колонка {TARGET_COL} отсутствует в {_main()}. "
                    "Добавьте её перед сохранением."
                )

        for key, val in predictions.items():
            if val is None or (isinstance(val, float) and pd.isna(val)):
                continue
            # key = ID строки
            try:
                kid = int(key)
            except (TypeError, ValueError):
                continue
            r = conn.execute(
                text(
                    f"UPDATE `{_main()}` SET `{target}` = :v "
                    f"WHERE Measure_ID = :mid AND ID = :id"
                ),
                {"v": float(val), "mid": int(measure_id), "id": kid},
            )
            updated += r.rowcount or 0
    return updated


def export_predictions_csv(df: pd.DataFrame, path: str) -> str:
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path
