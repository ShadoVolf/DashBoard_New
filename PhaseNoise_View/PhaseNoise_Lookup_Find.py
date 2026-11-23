"""Поиск МСК по части номера в справочнике."""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text

log = logging.getLogger("PhaseNoise.Lookup")


def find_msk_by_partial(query: str, spc: str | None = None,
                       limit: int = 200, engine=None) -> list[str]:
    """Поиск МСК по части в справочнике phaze_noise_resonator_lookup."""
    from .PhaseNoise_Lookup import (
        LOOKUP_TABLE, _engine, ensure_lookup_table, _has_spc_column,
    )

    engine = engine or _engine()
    ensure_lookup_table(engine)

    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, int(limit))
    pat = f"%{q}%"

    def _query(with_spc: bool):
        # LIMIT вшит в SQL: mysql.connector часто ломает LIMIT :lim
        if with_spc and spc and _has_spc_column:
            sql = f"""
                SELECT DISTINCT msk FROM `{LOOKUP_TABLE}`
                WHERE msk IS NOT NULL AND TRIM(msk) <> ''
                  AND msk LIKE :q AND spc = :spc
                ORDER BY msk LIMIT {limit}
            """
            params = {"q": pat, "spc": spc}
        else:
            sql = f"""
                SELECT DISTINCT msk FROM `{LOOKUP_TABLE}`
                WHERE msk IS NOT NULL AND TRIM(msk) <> ''
                  AND msk LIKE :q
                ORDER BY msk LIMIT {limit}
            """
            params = {"q": pat}
        return pd.read_sql(text(sql), engine, params=params)

    try:
        df = _query(with_spc=True)
        if (df is None or df.empty) and spc:
            log.debug(f"find_msk_by_partial: по spc={spc!r} пусто, без фильтра")
            df = _query(with_spc=False)
        if df is None or df.empty or "msk" not in df.columns:
            return []
        return (
            df["msk"].dropna().astype(str).str.strip()
            .replace("", pd.NA).dropna().unique().tolist()
        )
    except Exception as e:
        log.warning(f"find_msk_by_partial error: {e}")
        return []
