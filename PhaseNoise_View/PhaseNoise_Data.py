"""SQL-слой ФШ. Каскад МСК/номеров - через справочник."""

import logging
import re
import pandas as pd
from sqlalchemy import create_engine, text
from Options import get_connection_string
from .PhaseNoise_Constants import NORM_DEFS
from .PhaseNoise_Norms import DEFAULT_OFFSETS, ensure_norms  # noqa: F401

log = logging.getLogger("PhaseNoise.Data")
_engine_cache = None


def _engine():
    global _engine_cache
    if _engine_cache is None:
        log.info("Creating DB engine")
        _engine_cache = create_engine(str(get_connection_string()))
    return _engine_cache


def _q(sql_str: str, params: dict | None = None, label: str = "") -> pd.DataFrame:
    log.debug(f"SQL[{label}]: {sql_str} | params={params}")
    try:
        df = pd.read_sql(text(sql_str), _engine(), params=params or {})
        log.debug(f"SQL[{label}] -> {len(df)} rows")
        return df
    except Exception as e:
        log.error(f"SQL[{label}] ERROR: {e}")
        log.error(f"SQL was: {sql_str}")
        return pd.DataFrame()


def get_resonator_types() -> list[str]:
    df = _q(
        "SELECT DISTINCT NameR FROM `specification` "
        "WHERE NameR IS NOT NULL AND TRIM(NameR) <> '' ORDER BY NameR",
        label="resonator_types")
    if df.empty:
        log.warning("Список NameR пуст - каскад по типу будет неактивен")
        return []
    out = []
    for v in df["NameR"].tolist():
        s = str(v).strip()
        if s and s not in ('\"\"', "''"):
            out.append(s)
    log.info(f"Resonator types({len(out)}): {out[:8]}")
    return out


def get_spc_by_type(res_type: str) -> list[str]:
    if not res_type:
        return []
    df = _q("SELECT Name FROM `specification` WHERE NameR = :t ORDER BY Name",
            {"t": res_type}, label=f"spc_for_type[{res_type}]")
    if df.empty:
        log.warning(f"Нет спецификаций для типа {res_type!r}")
        return []
    return df["Name"].dropna().astype(str).tolist()


def get_msk_by_spc(spc: str) -> list[str]:
    if not spc:
        return []
    try:
        from .PhaseNoise_Lookup import lookup_msk_by_spc, is_lookup_empty
        if not is_lookup_empty():
            found = lookup_msk_by_spc(spc)
            if found:
                return found
    except Exception as e:
        log.warning(f"lookup msk_by_spc failed: {e}")
    df = _q(
        "SELECT DISTINCT MSK FROM `phaze_noise` "
        "WHERE Spc = :s AND `Delete` = 0 AND MSK IS NOT NULL ORDER BY MSK",
        {"s": spc}, label=f"msk_for_spc[{spc}]")
    if df.empty:
        return []
    return df["MSK"].dropna().astype(str).tolist()


def get_measure_ids_by_spc(spc: str) -> list[int]:
    if not spc:
        return []
    try:
        from .PhaseNoise_Lookup import lookup_mids_by_spc, is_lookup_empty
        if not is_lookup_empty():
            found = lookup_mids_by_spc(spc)
            if found:
                return found
    except Exception as e:
        log.warning(f"lookup mids_by_spc failed: {e}")
    df = _q(
        "SELECT DISTINCT MeasureID FROM `phaze_noise` "
        "WHERE Spc = :s AND `Delete` = 0 AND MeasureID IS NOT NULL ORDER BY MeasureID",
        {"s": spc}, label=f"mid_for_spc[{spc}]")
    if df.empty:
        return []
    return df["MeasureID"].dropna().astype(int).tolist()


def get_measure_ids_by_msk(msk: str) -> list[int]:
    if not msk:
        return []
    try:
        from .PhaseNoise_Lookup import lookup_mids_by_msk, is_lookup_empty
        if not is_lookup_empty():
            found = lookup_mids_by_msk(msk)
            if found:
                return found
    except Exception as e:
        log.warning(f"lookup mids_by_msk failed: {e}")
    df = _q(
        "SELECT DISTINCT MeasureID FROM `phaze_noise` "
        "WHERE MSK = :m AND `Delete` = 0 AND MeasureID IS NOT NULL ORDER BY MeasureID",
        {"m": msk}, label=f"mid_for_msk[{msk}]")
    if df.empty:
        return []
    return df["MeasureID"].dropna().astype(int).tolist()


def get_numbers(msk: str | None, measure_id: int | None, spc: str | None) -> list[str]:
    try:
        from .PhaseNoise_Lookup import lookup_numbers, is_lookup_empty
        if not is_lookup_empty():
            found = lookup_numbers(msk=msk, measure_id=measure_id, spc=spc)
            if found:
                return found
    except Exception as e:
        log.warning(f"lookup numbers failed: {e}")
    cond = ["`Delete` = 0", "N IS NOT NULL"]
    params: dict = {}
    if spc:
        cond.append("Spc = :s")
        params["s"] = spc
    if measure_id:
        cond.append("MeasureID = :mid")
        params["mid"] = measure_id
    elif msk:
        cond.append("MSK = :msk")
        params["msk"] = msk
    df = _q(
        f"SELECT DISTINCT N FROM `phaze_noise` WHERE {' AND '.join(cond)} ORDER BY N",
        params, label="numbers")
    if df.empty:
        return []
    return df["N"].dropna().astype(str).tolist()


def search_msk_partial(query: str, spc: str | None = None, limit: int = 200) -> list[str]:
    q = (query or "").strip()
    if not q:
        return []
    try:
        from .PhaseNoise_Lookup import find_msk_by_partial
        found = find_msk_by_partial(q, spc=spc, limit=limit)
        if found:
            return found[:limit]
    except Exception as e:
        log.warning(f"lookup partial MSK failed: {e}")
    cond = ["`Delete` = 0", "MSK IS NOT NULL", "MSK LIKE :q"]
    params = {"q": f"%{q}%"}
    if spc:
        cond.append("Spc = :s")
        params["s"] = spc
    df = _q(
        f"SELECT DISTINCT MSK FROM `phaze_noise` WHERE {' AND '.join(cond)} "
        f"ORDER BY MSK LIMIT {int(limit)}",
        params, label="msk_partial_fallback")
    if df.empty:
        return []
    return df["MSK"].dropna().astype(str).tolist()


def parse_numbers_input(raw: str) -> list[str]:
    if not raw or not str(raw).strip():
        return []
    text = str(raw).strip().upper().replace(";", ",").replace(" ", "")
    parts = [p for p in text.split(",") if p]
    result = []
    for p in parts:
        if "-" in p and not p.startswith("-"):
            a, _, b = p.partition("-")
            a, b = a.strip(), b.strip()
            if a and b:
                m_a = re.match(r"^([A-Z]*)(\d+)$", a)
                m_b = re.match(r"^([A-Z]*)(\d+)$", b)
                if m_a and m_b and m_a.group(1) == m_b.group(1):
                    prefix = m_a.group(1)
                    n1, n2 = int(m_a.group(2)), int(m_b.group(2))
                    if n1 > n2:
                        n1, n2 = n2, n1
                    for i in range(n1, n2 + 1):
                        result.append(f"{prefix}{i}")
                    continue
        result.append(p)
    seen, out = set(), []
    for n in result:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def load_phaze_noise(msk: str | None = None, measure_id: int | None = None,
                     n: str | None = None,
                     numbers: list[str] | None = None) -> pd.DataFrame:
    if numbers:
        try:
            from .PhaseNoise_Lookup import find_in_lookup
            _, mids, _ = find_in_lookup(numbers)
            if mids:
                ids = sorted(mids)
                placeholders = ",".join(str(i) for i in ids)
                return _q(
                    f"SELECT * FROM `phaze_noise` WHERE `Delete` = 0 "
                    f"AND MeasureID IN ({placeholders}) ORDER BY `_Date_`, `_Time_`",
                    label="load_by_numbers_lookup")
        except Exception as e:
            log.warning(f"lookup numbers failed, fallback: {e}")
        nums = [str(x).strip().upper() for x in numbers if x]
        if not nums:
            return pd.DataFrame()
        in_list = ",".join(f"'{n.replace(chr(39), '')}'" for n in nums)
        return _q(
            f"SELECT * FROM `phaze_noise` WHERE `Delete` = 0 "
            f"AND UPPER(TRIM(N)) IN ({in_list}) ORDER BY `_Date_`, `_Time_`",
            label="load_by_numbers")
    cond, params = ["`Delete` = 0"], {}
    if measure_id:
        cond.append("MeasureID = :mid")
        params["mid"] = measure_id
    elif msk:
        cond.append("MSK = :msk")
        params["msk"] = msk
    if n:
        cond.append("N = :n")
        params["n"] = n
    if len(cond) == 1:
        log.warning("load_phaze_noise: пустой фильтр - не запускаем")
        return pd.DataFrame()
    return _q(
        f"SELECT * FROM `phaze_noise` WHERE {' AND '.join(cond)} "
        "ORDER BY `_Date_`, `_Time_`", params, label="load_phaze_noise")


def load_phaze_noise_data(msk: str | None = None, measure_id: int | None = None,
                          n: str | None = None,
                          measure_ids: list[int] | None = None,
                          pairs: list[tuple] | None = None) -> pd.DataFrame:
    if pairs:
        clean = []
        for item in pairs:
            try:
                mid = int(item[0])
                nn = str(item[1]).strip()
            except (TypeError, ValueError, IndexError):
                continue
            if nn:
                clean.append((mid, nn))
        if not clean:
            return pd.DataFrame()
        parts = []
        for mid, nn in clean:
            safe_n = nn.replace("\\", "\\\\").replace("'", "''")
            parts.append(f"({mid}, '{safe_n}')")
        in_list = ",".join(parts)
        return _q(
            f"SELECT MeasureID, N, Freq, PN FROM `phaze_noise_data` "
            f"WHERE (MeasureID, N) IN ({in_list}) ORDER BY MeasureID, N, ID",
            label="load_data_by_pairs")
    if measure_ids:
        ids = [int(x) for x in measure_ids if x]
        if not ids:
            return pd.DataFrame()
        placeholders = ",".join(str(i) for i in ids)
        return _q(
            f"SELECT MeasureID, N, Freq, PN FROM `phaze_noise_data` "
            f"WHERE MeasureID IN ({placeholders}) ORDER BY MeasureID, N, ID",
            label="load_data_by_ids")
    cond, params = [], {}
    if measure_id:
        cond.append("MeasureID = :mid")
        params["mid"] = measure_id
    elif msk:
        cond.append("Msk = :msk")
        params["msk"] = msk
    if n:
        cond.append("N = :n")
        params["n"] = n
    if not cond:
        return pd.DataFrame()
    return _q(
        f"SELECT MeasureID, N, Freq, PN FROM `phaze_noise_data` "
        f"WHERE {' AND '.join(cond)} ORDER BY MeasureID, N, ID",
        params, label="load_phaze_noise_data")


def load_specification(spc: str) -> dict | None:
    if not spc:
        return None
    df = _q("SELECT * FROM `specification` WHERE Name = :n LIMIT 1",
            {"n": spc}, label=f"spec[{spc}]")
    return None if df.empty else df.iloc[0].to_dict()


def get_operator_fname(login: str) -> str:
    if not login:
        return ""
    df = _q("SELECT Fname FROM `пользователи` WHERE PH_Login = :l LIMIT 1",
            {"l": login}, label="operator")
    return "" if df.empty else str(df.iloc[0]["Fname"] or "")


def build_norms(spec_row: dict | None) -> list[dict]:
    if not spec_row:
        return []
    out = []
    for flag_f, min_f, max_f, ot_f, num in NORM_DEFS:
        if not _is_true(spec_row.get(flag_f)):
            continue
        raw_ot = spec_row.get(ot_f)
        if raw_ot is None or pd.isna(raw_ot):
            continue
        try:
            offset = int(float(raw_ot))
        except Exception:
            continue
        out.append({
            "num": num, "offset": offset,
            "min": _parse_num(spec_row.get(min_f)),
            "max": _parse_num(spec_row.get(max_f)),
            "flag_field": flag_f,
        })
    log.info(f"Norms active: {[(n['num'], n['offset']) for n in out]}")
    return out


def _parse_num(v):
    if v is None or pd.isna(v):
        return None
    s = str(v).strip().lower()
    if s in ("no", "", "nan"):
        return None
    try:
        return float(s.replace(",", "."))
    except Exception:
        return None


def _is_true(v) -> bool:
    if v is None or pd.isna(v):
        return False
    return str(v).lower() in ("1", "true", "да")


def load_msk_lookup(query: str = "") -> pd.DataFrame:
    where = ["`Delete` = 0", "MSK IS NOT NULL"]
    params = {}
    if query:
        where.append("(MSK LIKE :q OR N LIKE :q OR Spc LIKE :q)")
        params["q"] = f"%{query}%"
    return _q(
        "SELECT MSK, GROUP_CONCAT(DISTINCT N) AS N_list, "
        "GROUP_CONCAT(DISTINCT Spc) AS Spc_list, "
        "MAX(_Date_) AS last_date, COUNT(*) AS cnt "
        f"FROM `phaze_noise` WHERE {' AND '.join(where)} "
        "GROUP BY MSK ORDER BY MSK LIMIT 5000",
        params, label="lookup_msk")


def load_resonator_lookup(query: str = "") -> pd.DataFrame:
    where = ["`Delete` = 0", "N IS NOT NULL"]
    params = {}
    if query:
        where.append("(N LIKE :q OR MSK LIKE :q OR Spc LIKE :q)")
        params["q"] = f"%{query}%"
    return _q(
        "SELECT N, GROUP_CONCAT(DISTINCT MSK) AS MSK_list, "
        "MAX(_Date_) AS last_date, COUNT(*) AS cnt "
        f"FROM `phaze_noise` WHERE {' AND '.join(where)} "
        "GROUP BY N ORDER BY N LIMIT 5000",
        params, label="lookup_resonator")


def load_measure_id_lookup(query: str = "") -> pd.DataFrame:
    where = ["`Delete` = 0", "MeasureID IS NOT NULL"]
    params = {}
    if query:
        where.append("(CAST(MeasureID AS CHAR) LIKE :q "
                     "OR MSK LIKE :q OR N LIKE :q OR Spc LIKE :q)")
        params["q"] = f"%{query}%"
    return _q(
        "SELECT MeasureID, GROUP_CONCAT(DISTINCT MSK) AS MSK_list, "
        "GROUP_CONCAT(DISTINCT N) AS N_list, "
        "GROUP_CONCAT(DISTINCT Spc) AS Spc_list, "
        "MAX(_Date_) AS last_date, COUNT(*) AS cnt "
        f"FROM `phaze_noise` WHERE {' AND '.join(where)} "
        "GROUP BY MeasureID ORDER BY MeasureID DESC LIMIT 5000",
        params, label="lookup_mid")
