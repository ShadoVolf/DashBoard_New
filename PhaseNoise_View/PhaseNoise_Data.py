"""SQL-слой ФШ. Каскад МСК/номеров - через справочник."""

import logging
import re
import pandas as pd
from sqlalchemy import create_engine, text
from Options import get_connection_string
from .PhaseNoise_Constants import NORM_DEFS
from .PhaseNoise_Norms import DEFAULT_OFFSETS, ensure_norms  # noqa: F401
from .PhaseNoise_Filter import apply_curve_filter, FILTER_NONE

log = logging.getLogger("PhaseNoise.Data")
_engine_cache = None

from .PhaseNoise_Constants import NORM_DEFS, OFFSET_TO_FIELD

# Куда в psidata пишем значения по порядку отстроек
PSIDATA_TARGET_FIELDS = ["Shum", "Shum_1", "Shum_2", "Shum_3", "Shum_4"]

def _get_offset_value(
    n_row,
    data_n: pd.DataFrame,
    offset: float,
    prefer_curve: bool = False,
) -> float | None:
    """
    Значение PN на отстройке `offset` для конкретного номера N.

    1) Если prefer_curve=False: сначала берём стандартную колонку из phaze_noise
       (Shum1/Shum3/Shum10/…), иначе ближайшую точку в phaze_noise_data.
    2) Если prefer_curve=True (сохранение обработанных данных): сначала берём
       ближайшую точку из отфильтрованного спектра phaze_noise_data, иначе откат
       на колонку phaze_noise.
    """
    def _from_raw_cols() -> float | None:
        for std_off, col in OFFSET_TO_FIELD.items():
            if abs(std_off - float(offset)) < 1e-6:
                v = n_row.get(col)
                if v is not None and not pd.isna(v):
                    return float(v)
                break
        return None

    def _from_curve() -> float | None:
        if data_n is None or data_n.empty:
            return None
        try:
            freqs = data_n["Freq"].astype(float).values
        except Exception:
            return None
        if len(freqs) == 0:
            return None
        diffs = pd.Series(freqs).sub(float(offset)).abs()
        idx = int(diffs.idxmin())
        try:
            return float(data_n.iloc[idx]["PN"])
        except Exception:
            return None

    if prefer_curve:
        val = _from_curve()
        return val if val is not None else _from_raw_cols()

    val = _from_raw_cols()
    return val if val is not None else _from_curve()

def _get_offset_value_1(n_row, data_n: pd.DataFrame, offset: float) -> float | None:
    """
    Значение PN на отстройке `offset` для конкретного номера N.

    1) Если offset — «стандартный» (есть в OFFSET_TO_FIELD) — берём
       напрямую из phaze_noise (колонки Shum1/Shum3/Shum10/…).
    2) Иначе (или если колонка пуста) — ищем в phaze_noise_data по Freq
       ближайшую к `offset` (например, 30 Гц: 29.98 и 30.05 → 29.98).
    """
    # 1. Стандартная колонка phaze_noise
    for std_off, col in OFFSET_TO_FIELD.items():
        if abs(std_off - float(offset)) < 1e-6:
            v = n_row.get(col)
            if v is not None and not pd.isna(v):
                return float(v)
            break
    # 2. Ближайший Freq из phaze_noise_data
    if data_n is None or data_n.empty:
        return None
    try:
        freqs = data_n["Freq"].astype(float).values
    except Exception:
        return None
    if len(freqs) == 0:
        return None
    diffs = pd.Series(freqs).sub(float(offset)).abs()
    idx = int(diffs.idxmin())
    try:
        return float(data_n.iloc[idx]["PN"])
    except Exception:
        return None

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
    """Поиск МСК по подстроке.

    1) справочник phaze_noise_resonator_lookup (быстро)
    2) если пусто — основная таблица phaze_noise
    """
    q = (query or "").strip()
    if not q:
        return []
    limit = max(1, int(limit))
    pat = f"%{q}%"

    found: list[str] = []
    try:
        from .PhaseNoise_Lookup import find_msk_by_partial
        found = find_msk_by_partial(q, spc=spc, limit=limit) or []
        found = [str(x).strip() for x in found if str(x).strip()]
        if found:
            log.info(f"msk_partial '{q}': {len(found)} hits (lookup)")
            return found[:limit]
    except Exception as e:
        log.warning(f"lookup partial MSK failed: {e}")

    def _from_phaze(with_spc: bool) -> list[str]:
        cond = ["`Delete` = 0", "MSK IS NOT NULL", "TRIM(MSK) <> ''", "MSK LIKE :q"]
        params: dict = {"q": pat}
        if with_spc and spc:
            cond.append("Spc = :s")
            params["s"] = spc
        df = _q(
            f"SELECT DISTINCT MSK FROM `phaze_noise` "
            f"WHERE {' AND '.join(cond)} ORDER BY MSK LIMIT {limit}",
            params,
            label=f"msk_partial_phaze[{q}|spc={spc if with_spc else None}]",
        )
        if df.empty or "MSK" not in df.columns:
            return []
        return (
            df["MSK"].dropna().astype(str).str.strip()
            .replace("", pd.NA).dropna().unique().tolist()
        )

    found = _from_phaze(with_spc=True)
    if not found and spc:
        log.info("msk_partial: lookup+spc пусто, phaze без Spc")
        found = _from_phaze(with_spc=False)

    log.info(f"msk_partial '{q}': {len(found)} hits (phaze_noise)")
    return found[:limit]


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
def save_psidata_for_measure(
    measure_id: int,
    psi_id: int | None = None,
    filter_mode: str = FILTER_NONE,
) -> tuple[int, int]:
    """
    Для КАЖДОГО номера N в замере MeasureID пишет отдельную строку в psidata.
    Если filter_mode != FILTER_NONE, перед извлечением значений на отстройках
    применяет выбранный фильтр к кривой `phaze_noise_data`.
    """
    if not measure_id:
        log.error("save_psidata_for_measure: measure_id не задан")
        return 0, 0

    # 1. PSI_ID (если не задан из UI)
    if psi_id is None:
        df_link = _q(
            "SELECT PSI_ID FROM `phaze_noise_id` WHERE ID = :mid LIMIT 1",
            {"mid": measure_id},
            label="psi_id_by_measure",
        )
        if df_link.empty or pd.isna(df_link.iloc[0]["PSI_ID"]):
            log.error(
                "Не найден PSI_ID для MeasureID=%s в phaze_noise_id (колонка ID)",
                measure_id,
            )
            return 0, 0
        psi_id = int(df_link.iloc[0]["PSI_ID"])

    # 2. Строки phaze_noise и точки phaze_noise_data
    df_n = load_phaze_noise(measure_id=measure_id)
    if df_n.empty:
        log.warning("Нет строк phaze_noise для MeasureID=%s", measure_id)
        return 0, 0
    df_data = load_phaze_noise_data(measure_id=measure_id)

    use_filtered = bool(filter_mode and filter_mode != FILTER_NONE)
    if use_filtered and not df_data.empty:
        df_data = apply_curve_filter(df_data, filter_mode)

    # 3. Список отстроек
    offset_list: list[float] | None = None
    spc_name = None
    if "Spc" in df_n.columns:
        spc_vals = [v for v in df_n["Spc"].dropna().unique() if str(v).strip()]
        if spc_vals:
            spc_name = str(spc_vals[0])
    if spc_name:
        spec_row = load_specification(spc_name)
        norms = build_norms(spec_row) if spec_row else []
        if norms:
            offset_list = sorted({
                float(n["offset"]) for n in norms if n.get("offset") is not None
            })
    if not offset_list:
        offset_list = sorted(float(k) for k in OFFSET_TO_FIELD.keys())

    log.info(
        "psidata: MeasureID=%s PSI_ID=%s filter=%s offsets=%s",
        measure_id, psi_id, filter_mode, offset_list,
    )

    # 4. По одной строке на уникальный N
    if "N" not in df_n.columns:
        log.error("В выборке phaze_noise нет колонки N")
        return 0, 0
    df_n = df_n.drop_duplicates(subset=["N"], keep="first")

    saved = 0
    skipped = 0

    for _, n_row in df_n.iterrows():
        n_raw = n_row.get("N")
        if n_raw is None or pd.isna(n_raw):
            skipped += 1
            continue
        n_num = str(n_raw).strip()
        if not n_num:
            skipped += 1
            continue

        msk = n_row.get("MSK")
        spc = n_row.get("Spc")

        if not df_data.empty and "N" in df_data.columns:
            data_n = df_data[df_data["N"].astype(str).str.strip() == n_num]
        else:
            data_n = pd.DataFrame()

        target_values: dict[str, float] = {}
        for off in offset_list:
            if len(target_values) >= len(PSIDATA_TARGET_FIELDS):
                break
            val = _get_offset_value(n_row, data_n, off, prefer_curve=use_filtered)
            if val is None:
                continue
            target_values[PSIDATA_TARGET_FIELDS[len(target_values)]] = val

        if not target_values:
            log.info("psidata: N=%s нет данных ни по одной отстройке", n_num)
            skipped += 1
            continue

        # UPSERT по (Measure_ID, N)
        try:
            with _engine().begin() as conn:
                row_id = conn.execute(
                    text(
                        "SELECT ID FROM `psidata` "
                        "WHERE `Measure_ID` = :mid AND `N` = :n LIMIT 1"
                    ),
                    {"mid": psi_id, "n": n_num},
                ).scalar()

                payload: dict = dict(target_values)
                if msk is not None and not pd.isna(msk):
                    payload["MSK"] = str(msk)
                if spc is not None and not pd.isna(spc):
                    payload["Spc"] = str(spc)

                if row_id is not None:
                    set_clause = ", ".join(f"`{k}` = :{k}" for k in payload)
                    conn.execute(
                        text(
                            f"UPDATE `psidata` SET {set_clause} "
                            f"WHERE `ID` = :row_id"
                        ),
                        {"row_id": int(row_id), **payload},
                    )
                    log.info("psidata: UPDATE ID=%s N=%s", row_id, n_num)
                else:
                    payload["Measure_ID"] = psi_id
                    payload["N"] = n_num
                    cols = list(payload.keys())
                    sql = (
                        f"INSERT INTO `psidata` "
                        f"({', '.join(f'`{c}`' for c in cols)}) "
                        f"VALUES ({', '.join(':' + c for c in cols)})"
                    )
                    conn.execute(text(sql), payload)
                    log.info("psidata: INSERT N=%s", n_num)
            saved += 1
        except Exception as e:
            log.error("psidata: ошибка для N=%s: %s", n_num, e)
            skipped += 1

    log.info(
        "psidata: MeasureID=%s сохранено=%s пропущено=%s",
        measure_id, saved, skipped,
    )
    return saved, skipped

# PhaseNoise_Data.py  (добавить в конец файла)
def save_psidata_for_measure_1(measure_id: int, psi_id: int | None = None) -> tuple[int, int]:
    """
    Для КАЖДОГО номера N в замере MeasureID пишет отдельную строку в psidata.

    Связь в БД:
      phaze_noise.MeasureID  ==  phaze_noise_id.ID
      phaze_noise_id.PSI_ID  —> psidata.Measure_ID

    Отстройки:
      - если спецификация замера задаёт нормы — берём их отстройки
        (по возрастанию);
      - иначе — стандартный набор (sorted(OFFSET_TO_FIELD.keys())),
        проходим по нему и оставляем те отстройки, для которых есть данные.
    Для каждой отстройки значение берётся по правилам _get_offset_value
    и пишется в Shum / Shum_1 / Shum_2 / Shum_3 / Shum_4 ПОСЛЕДОВАТЕЛЬНО:
    нет данных для отстройки — пропускаем, поле не занимаем.

    Идентификация строки в psidata: (Measure_ID, N) — повторный вызов
    обновляет существующие строки, дублей не создаёт.

    Возвращает (сохранено, пропущено).
    """
    if not measure_id:
        log.error("save_psidata_for_measure: measure_id не задан")
        return 0, 0

    # 1. PSI_ID (если не задан из UI)
    if psi_id is None:
        df_link = _q(
            "SELECT PSI_ID FROM `phaze_noise_id` WHERE ID = :mid LIMIT 1",
            {"mid": measure_id},
            label="psi_id_by_measure",
        )
        if df_link.empty or pd.isna(df_link.iloc[0]["PSI_ID"]):
            log.error(
                "Не найден PSI_ID для MeasureID=%s в phaze_noise_id (колонка ID)",
                measure_id,
            )
            return 0, 0
        psi_id = int(df_link.iloc[0]["PSI_ID"])

    # 2. Строки phaze_noise (по номеру N) и точки phaze_noise_data
    df_n = load_phaze_noise(measure_id=measure_id)
    if df_n.empty:
        log.warning("Нет строк phaze_noise для MeasureID=%s", measure_id)
        return 0, 0
    df_data = load_phaze_noise_data(measure_id=measure_id)

    # 3. Список отстроек
    offset_list: list[float] | None = None
    spc_name = None
    if "Spc" in df_n.columns:
        spc_vals = [v for v in df_n["Spc"].dropna().unique() if str(v).strip()]
        if spc_vals:
            spc_name = str(spc_vals[0])
    if spc_name:
        spec_row = load_specification(spc_name)
        norms = build_norms(spec_row) if spec_row else []
        if norms:
            offset_list = sorted({
                float(n["offset"]) for n in norms if n.get("offset") is not None
            })
    if not offset_list:
        # Стандартный набор из констант
        offset_list = sorted(float(k) for k in OFFSET_TO_FIELD.keys())

    log.info(
        "psidata: MeasureID=%s PSI_ID=%s offsets=%s",
        measure_id, psi_id, offset_list,
    )

    # 4. По одной строке на уникальный N
    if "N" not in df_n.columns:
        log.error("В выборке phaze_noise нет колонки N")
        return 0, 0
    df_n = df_n.drop_duplicates(subset=["N"], keep="first")

    saved = 0
    skipped = 0

    for _, n_row in df_n.iterrows():
        n_raw = n_row.get("N")
        if n_raw is None or pd.isna(n_raw):
            skipped += 1
            continue
        n_num = str(n_raw).strip()
        if not n_num:
            skipped += 1
            continue

        msk = n_row.get("MSK")
        spc = n_row.get("Spc")

        # Данные phaze_noise_data только для этого N
        if not df_data.empty and "N" in df_data.columns:
            data_n = df_data[df_data["N"].astype(str).str.strip() == n_num]
        else:
            data_n = pd.DataFrame()

        # Собираем значения по отстройкам (макс. 5)
        target_values: dict[str, float] = {}
        for off in offset_list:
            if len(target_values) >= len(PSIDATA_TARGET_FIELDS):
                break
            val = _get_offset_value(n_row, data_n, off)
            if val is None:
                continue
            target_values[PSIDATA_TARGET_FIELDS[len(target_values)]] = val

        if not target_values:
            log.info("psidata: N=%s нет данных ни по одной отстройке", n_num)
            skipped += 1
            continue

        # UPSERT по (Measure_ID, N)
        try:
            with _engine().begin() as conn:
                row_id = conn.execute(
                    text(
                        "SELECT ID FROM `psidata` "
                        "WHERE `Measure_ID` = :mid AND `N` = :n LIMIT 1"
                    ),
                    {"mid": psi_id, "n": n_num},
                ).scalar()

                payload: dict = dict(target_values)
                if msk is not None and not pd.isna(msk):
                    payload["MSK"] = str(msk)
                if spc is not None and not pd.isna(spc):
                    payload["Spc"] = str(spc)

                if row_id is not None:
                    set_clause = ", ".join(f"`{k}` = :{k}" for k in payload)
                    conn.execute(
                        text(
                            f"UPDATE `psidata` SET {set_clause} "
                            f"WHERE `ID` = :row_id"
                        ),
                        {"row_id": int(row_id), **payload},
                    )
                    log.info("psidata: UPDATE ID=%s N=%s", row_id, n_num)
                else:
                    payload["Measure_ID"] = psi_id
                    payload["N"] = n_num
                    cols = list(payload.keys())
                    sql = (
                        f"INSERT INTO `psidata` "
                        f"({', '.join(f'`{c}`' for c in cols)}) "
                        f"VALUES ({', '.join(':' + c for c in cols)})"
                    )
                    conn.execute(text(sql), payload)
                    log.info("psidata: INSERT N=%s", n_num)
            saved += 1
        except Exception as e:
            log.error("psidata: ошибка для N=%s: %s", n_num, e)
            skipped += 1

    log.info(
        "psidata: MeasureID=%s сохранено=%s пропущено=%s",
        measure_id, saved, skipped,
    )
    return saved, skipped
