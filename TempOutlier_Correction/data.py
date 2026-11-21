"""Загрузка и сохранение данных psidata / psidatatemp."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

import pandas as pd
from sqlalchemy import create_engine, text, bindparam

from Options import get_connection_string

from .constants import SOURCES

_engine = None
_source = {
    "main_table": "psidata",
    "temps_table": "psidatatemp",
    "label": "Основная",
}


def _get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(
            str(get_connection_string()),
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def set_source(label: str) -> None:
    for lab, main, temps in SOURCES:
        if lab == label:
            _source["main_table"] = main
            _source["temps_table"] = temps
            _source["label"] = lab
            return


def get_source_label() -> str:
    return _source["label"]


def _main() -> str:
    return _source["main_table"]


def _temps() -> str:
    return _source["temps_table"]


def search_msk(partial: str, limit: int = 50) -> List[str]:
    """LIKE-поиск МСК по части номера."""
    partial = (partial or "").strip()
    if not partial:
        return []
    eng = _get_engine()
    sql = text(
        f"SELECT DISTINCT MSK FROM `{_main()}` "
        f"WHERE MSK LIKE :p ORDER BY MSK LIMIT :lim"
    )
    with eng.connect() as conn:
        rows = conn.execute(sql, {"p": f"%{partial}%", "lim": limit}).fetchall()
    return [str(r[0]) for r in rows if r[0]]


def list_measure_ids_for_msk(msk: str) -> List[Dict[str, Any]]:
    """Список Measure_ID для МСК с метаданными (Date, File, count N)."""
    msk = (msk or "").strip()
    if not msk:
        return []
    eng = _get_engine()
    sql = text(
        f"""
        SELECT Measure_ID,
               MIN(Date) AS Date,
               MIN(File) AS File,
               COUNT(DISTINCT N) AS n_count,
               COUNT(*) AS row_count
        FROM `{_main()}`
        WHERE MSK = :msk AND Measure_ID IS NOT NULL
        GROUP BY Measure_ID
        ORDER BY Measure_ID DESC
        """
    )
    with eng.connect() as conn:
        rows = conn.execute(sql, {"msk": msk}).mappings().fetchall()
    return [dict(r) for r in rows]


def load_psidata(measure_ids: Sequence[int]) -> pd.DataFrame:
    mids = [int(m) for m in measure_ids if m is not None]
    if not mids:
        return pd.DataFrame()
    eng = _get_engine()
    sql = text(
        f"SELECT * FROM `{_main()}` WHERE Measure_ID IN :mids"
    ).bindparams(bindparam("mids", expanding=True))
    return pd.read_sql(sql, eng, params={"mids": mids})


def load_temps(measure_ids: Sequence[int]) -> pd.DataFrame:
    mids = [int(m) for m in measure_ids if m is not None]
    if not mids:
        return pd.DataFrame()
    eng = _get_engine()
    sql = text(
        f"SELECT * FROM `{_temps()}` WHERE Measure_ID IN :mids "
        f"ORDER BY Measure_ID, N, Temp"
    ).bindparams(bindparam("mids", expanding=True))
    return pd.read_sql(sql, eng, params={"mids": mids})


def load_temps_for_number(
    measure_ids: Sequence[int], number: str
) -> pd.DataFrame:
    """Температуры для одного номера N по списку Measure_ID."""
    mids = [int(m) for m in measure_ids if m is not None]
    n = str(number or "").strip().upper()
    if not mids or not n:
        return pd.DataFrame()
    eng = _get_engine()
    sql = text(
        f"SELECT * FROM `{_temps()}` "
        f"WHERE Measure_ID IN :mids AND UPPER(TRIM(N)) = :n "
        f"ORDER BY Measure_ID, Temp"
    ).bindparams(bindparam("mids", expanding=True))
    return pd.read_sql(sql, eng, params={"mids": mids, "n": n})


def unique_numbers(psi_df: pd.DataFrame) -> List[str]:
    if psi_df is None or psi_df.empty or "N" not in psi_df.columns:
        return []
    nums = (
        psi_df["N"]
        .dropna()
        .astype(str)
        .str.strip()
        .str.upper()
        .replace("", pd.NA)
        .dropna()
        .unique()
        .tolist()
    )
    return sorted(set(nums))


def next_measure_id() -> int:
    eng = _get_engine()
    with eng.connect() as conn:
        r = conn.execute(
            text(f"SELECT COALESCE(MAX(Measure_ID), 0) + 1 FROM `{_main()}`")
        ).scalar()
    return int(r or 1)


def save_corrected_measure(
    psi_rows: pd.DataFrame,
    temp_rows: pd.DataFrame,
    msk: str,
    source_mids: Sequence[int],
    login: str = "toc",
) -> int:
    """
    Записать скорректированный замер как новый Measure_ID.
    Возвращает новый Measure_ID.
    """
    if psi_rows is None or psi_rows.empty:
        raise ValueError("Нет строк psidata для сохранения")

    new_mid = next_measure_id()
    eng = _get_engine()

    psi = psi_rows.copy()
    psi["Measure_ID"] = new_mid
    if "MSK" in psi.columns:
        psi["MSK"] = msk
    for col, val in (
        ("File", f"TOC_corr_from_{'_'.join(str(m) for m in source_mids)}"),
        ("Virtual_Data", 1),
    ):
        if col in psi.columns:
            psi[col] = val

    temps = temp_rows.copy() if temp_rows is not None else pd.DataFrame()
    if not temps.empty:
        temps["Measure_ID"] = new_mid
        if "MSK" in temps.columns:
            temps["MSK"] = msk

    for df in (psi, temps):
        for pk in ("ID", "id", "RecordId", "RecordID"):
            if pk in df.columns:
                df.drop(columns=[pk], inplace=True, errors="ignore")

    with eng.begin() as conn:
        psi.to_sql(_main(), con=conn, if_exists="append", index=False, method="multi")
        if not temps.empty:
            temps.to_sql(
                _temps(), con=conn, if_exists="append", index=False, method="multi"
            )
        try:
            conn.execute(
                text(
                    """
                    CREATE TABLE IF NOT EXISTS `temp_outlier_log` (
                        `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                        `MSK` VARCHAR(64),
                        `Source_Measure_IDs` TEXT,
                        `New_Measure_ID` INTEGER,
                        `Login` VARCHAR(64),
                        `Created` DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (`id`)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8
                    """
                )
            )
            conn.execute(
                text(
                    "INSERT INTO `temp_outlier_log` "
                    "(MSK, Source_Measure_IDs, New_Measure_ID, Login) "
                    "VALUES (:m, :s, :n, :l)"
                ),
                {
                    "m": str(msk),
                    "s": ",".join(str(x) for x in source_mids),
                    "n": new_mid,
                    "l": login,
                },
            )
        except Exception as e:
            print(f"[TOC] log write skipped: {e}", flush=True)

    return new_mid
