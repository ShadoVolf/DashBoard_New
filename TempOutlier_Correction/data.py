"""Zagruzka i sohranenie dannyh psidata / psidatatemp."""

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
    "label": "Osnovnaya",
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


# Parametry specifikacii dlya metrik TCH (Tnakl/Tnastr/polinom/TCH_Temp_A/B)
_SPEC_PARAM_COLUMNS = {
    "t_nakl": ("Tnakl", "t_nakl"),
    "t_nastr": ("Tnastr", "t_nastr"),
    "degree": ("polinom", "Polinom"),
    "ta": ("TCH_Temp_A", "TCH_TempA", "Temp_TCH_A"),
    "tb": ("TCH_Temp_B", "TCH_TempB", "Temp_TCH_B"),
}
_SPEC_PARAMS_CACHE: Dict[str, Dict[str, Any]] = {}

def get_spec_params(spc: Optional[str]) -> Dict[str, Any]:
    """Parametry specifikacii dlya metrik TCH (kak get_spc_base_temps v Make_Measure)."""
    empty = {"t_nakl": None, "t_nastr": None, "degree": 3, "ta": None, "tb": None}
    if not spc:
        return dict(empty)
    spc = str(spc).strip()
    if not spc:
        return dict(empty)
    cached = _SPEC_PARAMS_CACHE.get(spc)
    if cached is not None:
        return dict(cached)

    out = dict(empty)
    eng = _get_engine()
    try:
        # ❗ обычные обратные кавычки, БЕЗ слэшей перед ними
        sql = "SELECT * FROM `specification` WHERE Name = :n LIMIT 1"
        row = pd.read_sql(text(sql), eng, params={"n": spc})
        if not row.empty:
            r = row.iloc[0]
            for key, cols in _SPEC_PARAM_COLUMNS.items():
                for c in cols:
                    if c not in row.columns:
                        continue
                    v = r.get(c)
                    if v is None or (isinstance(v, float) and pd.isna(v)):
                        continue
                    if key == "degree":
                        try:
                            out["degree"] = max(
                                1,
                                int(float(str(v).strip().replace(",", ".")))
                            )
                        except (TypeError, ValueError):
                            pass
                    else:
                        try:
                            out[key] = float(str(v).strip().replace(",", "."))
                        except (TypeError, ValueError):
                            pass
                    break
    except Exception as e:
        print(f"[TOC] get_spec_params: {e}", flush=True)

    _SPEC_PARAMS_CACHE[spc] = out
    return dict(out)
def get_spec_params_1(spc: Optional[str]) -> Dict[str, Any]:
    """Parametry specifikacii dlya metrik TCH (kak get_spc_base_temps v Make_Measure)."""
    empty = {"t_nakl": None, "t_nastr": None, "degree": 3, "ta": None, "tb": None}
    if not spc:
        return dict(empty)
    spc = str(spc).strip()
    if not spc:
        return dict(empty)
    cached = _SPEC_PARAMS_CACHE.get(spc)
    if cached is not None:
        return dict(cached)
    out = dict(empty)
    eng = _get_engine()
    try:
        row = pd.read_sql(
            text("SELECT * FROM \`specification\` WHERE Name = :n LIMIT 1"),
            eng,
            params={"n": spc},
        )
        if not row.empty:
            r = row.iloc[0]
            for key, cols in _SPEC_PARAM_COLUMNS.items():
                for c in cols:
                    if c not in row.columns:
                        continue
                    v = r.get(c)
                    if v is None or (isinstance(v, float) and pd.isna(v)):
                        continue
                    if key == "degree":
                        try:
                            out["degree"] = max(1, int(float(str(v).strip().replace(",", "."))))
                        except (TypeError, ValueError):
                            pass
                    else:
                        try:
                            out[key] = float(str(v).strip().replace(",", "."))
                        except (TypeError, ValueError):
                            pass
                    break
    except Exception as e:
        print(f"[TOC] get_spec_params: {e}", flush=True)
    _SPEC_PARAMS_CACHE[spc] = out
    return dict(out)


# ---------------------------------------------------------------------------
# Kaskad: Type -> Spec -> MSK -> Date -> Measure_ID  (kak v Archive)
# ---------------------------------------------------------------------------

def get_types() -> List[str]:
    eng = _get_engine()
    try:
        return (
            pd.read_sql(
                text("SELECT `Type` FROM `resonatortype` ORDER BY `Type`"),
                eng,
            )["Type"]
            .dropna()
            .astype(str)
            .tolist()
        )
    except Exception as e:
        print(f"[TOC] get_types: {e}", flush=True)
        return []


def get_specs_by_type(rtype: str) -> List[str]:
    if not rtype:
        return []
    eng = _get_engine()
    try:
        return (
            pd.read_sql(
                text(
                    "SELECT `Name` FROM `specification` "
                    "WHERE NameR = :t ORDER BY `Name`"
                ),
                eng,
                params={"t": rtype},
            )["Name"]
            .dropna()
            .astype(str)
            .tolist()
        )
    except Exception as e:
        print(f"[TOC] get_specs: {e}", flush=True)
        return []


def get_msk_list(spc: Optional[str] = None) -> List[str]:
    eng = _get_engine()
    table = _main()
    try:
        if spc:
            sql = text(
                f"SELECT DISTINCT MSK FROM `{table}` "
                f"WHERE Spc = :spc AND MSK IS NOT NULL ORDER BY MSK"
            )
            params = {"spc": spc}
        else:
            sql = text(
                f"SELECT DISTINCT MSK FROM `{table}` "
                f"WHERE MSK IS NOT NULL ORDER BY MSK"
            )
            params = {}
        return (
            pd.read_sql(sql, eng, params=params)["MSK"]
            .dropna()
            .astype(str)
            .tolist()
        )
    except Exception as e:
        print(f"[TOC] get_msk_list: {e}", flush=True)
        return []


def get_dates_list(
    msk: Optional[str] = None, spc: Optional[str] = None
) -> List[str]:
    eng = _get_engine()
    table = _main()
    cond, params = [], {}
    if msk:
        cond.append("MSK = :msk")
        params["msk"] = msk
    if spc:
        cond.append("Spc = :spc")
        params["spc"] = spc
    where = " AND ".join(cond) if cond else "1=1"
    sql = text(
        f"SELECT DISTINCT Date FROM `{table}` WHERE {where} "
        f"AND Date IS NOT NULL ORDER BY Date"
    )
    try:
        return (
            pd.read_sql(sql, eng, params=params)["Date"]
            .dropna()
            .astype(str)
            .tolist()
        )
    except Exception as e:
        print(f"[TOC] get_dates: {e}", flush=True)
        return []


def get_files_list(
    msk: Optional[str] = None,
    spc: Optional[str] = None,
    date: Optional[str] = None,
) -> List[str]:
    eng = _get_engine()
    table = _main()
    cond, params = [], {}
    if msk:
        cond.append("MSK = :msk")
        params["msk"] = msk
    if spc:
        cond.append("Spc = :spc")
        params["spc"] = spc
    if date:
        cond.append("Date = :dt")
        params["dt"] = date
    where = " AND ".join(cond) if cond else "1=1"
    sql = text(
        f"SELECT DISTINCT File FROM `{table}` WHERE {where} "
        f"AND File IS NOT NULL ORDER BY File"
    )
    try:
        return (
            pd.read_sql(sql, eng, params=params)["File"]
            .dropna()
            .astype(str)
            .tolist()
        )
    except Exception as e:
        print(f"[TOC] get_files: {e}", flush=True)
        return []


def list_measure_ids(
    msk: Optional[str] = None,
    spc: Optional[str] = None,
    date: Optional[str] = None,
    file: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Spisok Measure_ID s metadannymi. Filtry neobyazatelny."""
    eng = _get_engine()
    table = _main()
    cond, params = ["Measure_ID IS NOT NULL"], {}
    if msk:
        cond.append("MSK = :msk")
        params["msk"] = msk
    if spc:
        cond.append("Spc = :spc")
        params["spc"] = spc
    if date:
        cond.append("Date = :dt")
        params["dt"] = date
    if file:
        cond.append("File = :fl")
        params["fl"] = file
    where = " AND ".join(cond)
    sql = text(
        f"""
        SELECT Measure_ID,
               MIN(MSK)  AS MSK,
               MIN(Spc)  AS Spc,
               MIN(Date) AS Date,
               MIN(File) AS File,
               COUNT(DISTINCT N) AS n_count,
               COUNT(*) AS row_count
        FROM `{table}`
        WHERE {where}
        GROUP BY Measure_ID
        ORDER BY Measure_ID DESC
        """
    )
    try:
        with eng.connect() as conn:
            rows = conn.execute(sql, params).mappings().fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[TOC] list_measure_ids: {e}", flush=True)
        return []


def search_msk(partial: str, limit: int = 80) -> List[str]:
    """LIKE-poisk MSK po chasti nomera (lyubye imena: data, indeks i t.d.)."""
    partial = (partial or "").strip()
    if not partial:
        return []
    eng = _get_engine()
    sql = text(
        f"SELECT DISTINCT MSK FROM `{_main()}` "
        f"WHERE MSK LIKE :p ORDER BY MSK LIMIT :lim"
    )
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                sql, {"p": f"%{partial}%", "lim": int(limit)}
            ).fetchall()
        return [str(r[0]) for r in rows if r[0]]
    except Exception as e:
        print(f"[TOC] search_msk: {e}", flush=True)
        return []


def get_spc_for_msk(msk: str) -> Optional[str]:
    """Первая спецификация, встречающаяся у данного MSK (для каскада после поиска)."""
    msk = (msk or "").strip()
    if not msk:
        return None
    eng = _get_engine()
    sql = text(
        f"SELECT Spc FROM `{_main()}` "
        f"WHERE MSK = :msk AND Spc IS NOT NULL AND Spc != '' "
        f"LIMIT 1"
    )
    try:
        with eng.connect() as conn:
            row = conn.execute(sql, {"msk": msk}).fetchone()
        if row and row[0]:
            return str(row[0]).strip()
    except Exception as e:
        print(f"[TOC] get_spc_for_msk: {e}", flush=True)
    return None


def get_type_for_spc(spc: str) -> Optional[str]:
    """Тип резонатора по имени спецификации (если есть связь)."""
    spc = (spc or "").strip()
    if not spc:
        return None
    eng = _get_engine()
    try:
        # specification.Name + Type / Rtype / TypeName - tipichnye kolonki
        for col in ("Type", "Rtype", "TypeName", "ResonatorType"):
            try:
                sql = text(
                    f"SELECT `{col}` FROM `specification` WHERE Name = :n LIMIT 1"
                )
                with eng.connect() as conn:
                    row = conn.execute(sql, {"n": spc}).fetchone()
                if row and row[0]:
                    return str(row[0]).strip()
            except Exception:
                continue
        # fallback: Type iz psidata po Spc
        sql = text(
            f"SELECT Type FROM `{_main()}` "
            f"WHERE Spc = :spc AND Type IS NOT NULL AND Type != '' LIMIT 1"
        )
        with eng.connect() as conn:
            row = conn.execute(sql, {"spc": spc}).fetchone()
        if row and row[0]:
            return str(row[0]).strip()
    except Exception as e:
        print(f"[TOC] get_type_for_spc: {e}", flush=True)
    return None


# Parametry, po kotorym berem znacheniya s zamera "v norme" (kak Archive)
SPEC_PICK_PARAMS = ("F", "R", "Q", "C0", "Cq", "L")


def _safe_float_spc(v) -> Optional[float]:
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() == "no":
            return None
        try:
            return float(s.replace(",", "."))
        except (ValueError, TypeError):
            return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_specification_row(spc_name: str) -> Optional[Dict[str, Any]]:
    """Stroka specification po Name (kak Archive_View.load_specification)."""
    spc_name = (spc_name or "").strip()
    if not spc_name:
        return None
    eng = _get_engine()
    try:
        df = pd.read_sql(
            text("SELECT * FROM `specification` WHERE Name = :n LIMIT 1"),
            eng,
            params={"n": spc_name},
        )
        if df.empty:
            return None
        return df.iloc[0].to_dict()
    except Exception as e:
        print(f"[TOC] load_specification_row: {e}", flush=True)
        return None


def load_spc_param_limits(
    spc_name: str,
    params: Sequence[str] = SPEC_PICK_PARAMS,
) -> Dict[str, Dict[str, Optional[float]]]:
    """Min/Max dlya parametrov F,R,Q,C0,Cq,L iz specification + spc_map_table.

    Logika Use/Max/Min kak v Archive_View.load_spc_map_for_archive:
    spc_map_table.Use / Max / Min - imena kolonok v specification.
    Esli parametra net v karte ili Use!=1 - ego net v resultate.
    """
    out: Dict[str, Dict[str, Optional[float]]] = {}
    row = load_specification_row(spc_name)
    if not row:
        return out
    eng = _get_engine()
    try:
        spc_map = pd.read_sql(
            text("SELECT * FROM `spc_map_table` ORDER BY ID"), eng
        )
    except Exception as e:
        print(f"[TOC] load_spc_param_limits map: {e}", flush=True)
        return out

    want = {str(p).strip().upper() for p in params}
    # aliasy Parameter_Name -> nash kod
    aliases = {
        "F": "F", "R": "R", "Q": "Q",
        "C0": "C0", "Cq": "Cq", "CQ": "Cq", "L": "L",
    }

    for _, mr in spc_map.iterrows():
        pname = str(mr.get("Parameter_Name") or mr.get("Parameter") or "").strip()
        if not pname:
            continue
        key = aliases.get(pname) or aliases.get(pname.upper())
        if key is None:
            # pryamoe sovpadenie s nashim spiskom
            if pname.upper() in want:
                key = pname.upper() if pname.upper() != "CQ" else "Cq"
            else:
                continue
        if key.upper() not in want and key not in params:
            continue

        use_col = mr.get("Use")
        use_val = 0
        if use_col is not None and str(use_col).strip() not in ("", "nan"):
            # Use - imya kolonki specification ili litera 1
            if str(use_col).strip() in ("1", "0"):
                use_val = int(str(use_col).strip())
            else:
                use_val = int(_safe_float_spc(row.get(str(use_col))) or 0)
        if use_val != 1:
            continue

        max_col = mr.get("Max")
        min_col = mr.get("Min")
        mx = _safe_float_spc(row.get(str(max_col))) if max_col is not None else None
        mn = _safe_float_spc(row.get(str(min_col))) if min_col is not None else None
        # esli Max/Min - literaly chisel v mape
        if mx is None:
            mx = _safe_float_spc(max_col)
        if mn is None:
            mn = _safe_float_spc(min_col)
        if mx is None and mn is None:
            continue
        out[key] = {"min": mn, "max": mx}

    # pryamye kolonki F_min/F_max i t.p. esli map pust
    if not out:
        for p in params:
            mn = _safe_float_spc(row.get(f"{p}_min") or row.get(f"{p}min") or row.get(f"Min_{p}"))
            mx = _safe_float_spc(row.get(f"{p}_max") or row.get(f"{p}max") or row.get(f"Max_{p}"))
            if mn is not None or mx is not None:
                out[p] = {"min": mn, "max": mx}
    return out


def value_in_spec(
    value: Any,
    limits: Optional[Dict[str, Optional[float]]],
) -> bool:
    """True esli value v [min; max] (otsutstvuyushchaya granica - ne proveryaetsya)."""
    if not limits:
        return False
    v = _safe_float_spc(value)
    if v is None:
        return False
    mn = limits.get("min")
    mx = limits.get("max")
    if mn is not None and v < mn:
        return False
    if mx is not None and v > mx:
        return False
    return True


def pick_params_from_measurements(
    psi_df: pd.DataFrame,
    measure_ids: Sequence[int],
    number: str,
    base_mid: int,
    limits: Dict[str, Dict[str, Optional[float]]],
    params: Sequence[str] = SPEC_PICK_PARAMS,
) -> Dict[str, Any]:
    """Dlya kazhdogo parametra: znachenie s zamera, gde ono v norme;
    esli takogo net - s osnovnogo (base_mid).

    Beretsya lyuboj zamer, gde param v [Min;Max]. Neskolko - pervyj podhodyashchij.
    """
    result: Dict[str, Any] = {}
    if psi_df is None or psi_df.empty or not measure_ids:
        return result
    n = str(number or "").strip().upper()
    sub = psi_df.copy()
    if "Measure_ID" in sub.columns:
        sub = sub[sub["Measure_ID"].isin([int(m) for m in measure_ids])]
    if "N" in sub.columns and n:
        sub = sub[sub["N"].astype(str).str.strip().str.upper() == n]
    if sub.empty:
        return result

    by_mid: Dict[int, pd.Series] = {}
    for mid, g in sub.groupby("Measure_ID"):
        by_mid[int(mid)] = g.iloc[0]

    base_row = by_mid.get(int(base_mid))
    for param in params:
        col = None
        for c in sub.columns:
            if str(c).strip() == param or str(c).strip().upper() == param.upper():
                col = c
                break
        if col is None:
            continue
        lim = limits.get(param) or limits.get(param.upper())
        chosen = None
        chosen_mid = None
        if lim:
            for mid, row in by_mid.items():
                val = row.get(col)
                if value_in_spec(val, lim):
                    chosen = val
                    chosen_mid = mid
                    break
        if chosen is None and base_row is not None:
            chosen = base_row.get(col)
            chosen_mid = int(base_mid)
        if chosen is not None:
            result[param] = {
                "value": chosen,
                "mid": chosen_mid,
                "in_spec": bool(lim and value_in_spec(chosen, lim)),
            }
    return result


def apply_in_spec_params_to_psi(
    psi_base: pd.DataFrame,
    psi_all: pd.DataFrame,
    selected_mids: Sequence[int],
    base_mid: int,
    spc_name: Optional[str],
    params: Sequence[str] = SPEC_PICK_PARAMS,
) -> pd.DataFrame:
    """Podstavit v psi_base (stroki osnovnogo zamera) parametry F,R,Q,C0,Cq,L
    s zamera, gde oni v norme (inache ostavit s base).
    """
    if psi_base is None or psi_base.empty:
        return psi_base
    limits = load_spc_param_limits(spc_name or "", params=params) if spc_name else {}
    out = psi_base.copy()
    if "N" not in out.columns:
        return out
    for idx, row in out.iterrows():
        n = str(row.get("N") or "").strip().upper()
        if not n:
            continue
        picked = pick_params_from_measurements(
            psi_all, selected_mids, n, int(base_mid), limits, params=params
        )
        for param, info in picked.items():
            if param in out.columns:
                out.at[idx, param] = info["value"]
            else:
                # popytka case-insensitive
                for c in out.columns:
                    if str(c).strip().upper() == param.upper():
                        out.at[idx, c] = info["value"]
                        break
    return out


def search_measure_id(partial: str, limit: int = 50) -> List[Dict[str, Any]]:
    """Poisk Measure_ID po chasti nomera ili tochnomu ID."""
    partial = (partial or "").strip()
    if not partial:
        return []
    eng = _get_engine()
    table = _main()
    try:
        if partial.isdigit():
            sql = text(
                f"""
                SELECT Measure_ID,
                       MIN(MSK) AS MSK, MIN(Spc) AS Spc, MIN(Date) AS Date,
                       MIN(File) AS File, COUNT(DISTINCT N) AS n_count
                FROM `{table}`
                WHERE Measure_ID = :mid
                GROUP BY Measure_ID
                """
            )
            params = {"mid": int(partial)}
        else:
            sql = text(
                f"""
                SELECT Measure_ID,
                       MIN(MSK) AS MSK, MIN(Spc) AS Spc, MIN(Date) AS Date,
                       MIN(File) AS File, COUNT(DISTINCT N) AS n_count
                FROM `{table}`
                WHERE CAST(Measure_ID AS CHAR) LIKE :p
                   OR MSK LIKE :p
                   OR File LIKE :p
                GROUP BY Measure_ID
                ORDER BY Measure_ID DESC
                LIMIT :lim
                """
            )
            params = {"p": f"%{partial}%", "lim": int(limit)}
        with eng.connect() as conn:
            rows = conn.execute(sql, params).mappings().fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[TOC] search_measure_id: {e}", flush=True)
        return []


def list_measure_ids_for_msk(msk: str) -> List[Dict[str, Any]]:
    return list_measure_ids(msk=msk)


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



def register_measure_id(
    msk: str,
    filename: str,
    file_id: Optional[int] = None,
    login: str = "toc",
    protokol_type: Optional[str] = None,
    program_type: str = "TempOutlier_Correction",
) -> int:
    """Registraciya Measure_ID srazu v tablice psi_measure_id.

    Kak Save_To_mySql.insert_msk_value v Temperature_Measure: dobavlyaetsya
    strochka v psi_measure_id i ID beretsya iz LAST_INSERT_ID(). Eto
    isklyuchaet nalezhenie Measure_ID pri parallel'nom sohranenii
    (v otlichie ot next_measure_id = MAX(Measure_ID)+1).
    Kolonki zapisyvayutsya tolko esli ih real'no est' v tablice.
    """
    eng = _get_engine()
    with eng.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'psi_measure_id'"
            )
        ).fetchall()
        cols = [str(r[0]) for r in rows]
        if not cols:
            raise RuntimeError("Tablica psi_measure_id nedostupna")

        def real_col(name: str) -> Optional[str]:
            for col in cols:
                if col.upper() == name.upper():
                    return col
            return None

        values: Dict[str, Any] = {}
        for name, val in (
            ("MSK", msk),
            ("File", filename),
            ("Program_Type", program_type),
            ("File_ID", file_id),
            ("Operator", login),
            ("ProtokolN", protokol_type),
        ):
            real = real_col(name)
            if real is not None and val is not None:
                values[real] = val
        if not values:
            raise RuntimeError("Net dannyh dlya vstavki v psi_measure_id")
        col_sql = ", ".join(f"`{k}`" for k in values)
        par_sql = ", ".join(f":{k}" for k in values)
        conn.execute(
            text(f"INSERT INTO `psi_measure_id` ({col_sql}) VALUES ({par_sql})"),
            values,
        )
        new_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()
    return int(new_id or 0)


def _table_columns(table: str) -> list:
    """Realnye kolonki tablicy v tekushchej BDs."""
    eng = _get_engine()
    try:
        with eng.connect() as conn:
            rows = conn.execute(
                text(
                    "SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t "
                    "ORDER BY ORDINAL_POSITION"
                ),
                {"t": table},
            ).fetchall()
        return [str(r[0]) for r in rows]
    except Exception as e:
        print(f"[TOC] _table_columns({table}): {e}", flush=True)
        return []


def _align_df_to_table(df: pd.DataFrame, table: str) -> pd.DataFrame:
    """Ostavit tolko kolonki, kotorye est' v tablice. Ubrat F_method i t.p."""
    if df is None or df.empty:
        return df
    cols = _table_columns(table)
    if not cols:
        # fallback: ubrat sluzhebnye
        drop = [c for c in df.columns if str(c).endswith("_method")
                or str(c) in ("ID", "id", "RecordId", "RecordID")]
        out = df.drop(columns=drop, errors="ignore")
        return out
    keep = [c for c in df.columns if c in cols]
    missing = [c for c in cols if c not in df.columns
               and c not in ("ID", "id", "RecordId", "RecordID", "AUTO_INCREMENT")]
    out = df[keep].copy()
    # NaN for optional missing non-PK columns is not added - DB defaults
    print(f"[TOC] align {table}: keep={len(keep)} drop={len(df.columns)-len(keep)}",
          flush=True)
    return out


def _make_toc_filename(base_file: Optional[str], source_mids: Sequence[int] = ()) -> str:
    """Imya fajla: File osnovnogo zamera + ' (TOC)'.
    Esli File pustoj - fallback TOC_corr_from_<mids> (TOC).
    """
    name = (base_file or "").strip()
    if not name:
        mids = "_".join(str(m) for m in (source_mids or [])[:8]) or "corr"
        name = f"TOC_corr_from_{mids}"
    low = name.lower()
    for sfx in (" (toc)", "(toc)", " (TOC)", "(TOC)"):
        if low.endswith(sfx.lower()):
            name = name[: -len(sfx)].rstrip()
            break
    return f"{name} (TOC)"


def save_corrected_measure(
    psi_rows: pd.DataFrame,
    temp_rows: pd.DataFrame,
    msk: str,
    source_mids: Sequence[int],
    login: str = "toc",
    base_file: Optional[str] = None,
) -> int:
    if psi_rows is None or psi_rows.empty:
        raise ValueError("Net strok psidata dlya sohraneniya")

    eng = _get_engine()

    # Imya fajla = File osnovnogo zamera + " (TOC)"
    if not base_file and "File" in psi_rows.columns:
        try:
            vals = psi_rows["File"].dropna().astype(str).str.strip()
            vals = vals[vals != ""]
            if not vals.empty:
                base_file = str(vals.iloc[0])
        except Exception:
            base_file = None
    file_label = _make_toc_filename(base_file, source_mids)

    # Measure_ID registrirovan srazu v psi_measure_id (kak v
    # Temperature_Measure), tak chto nalezhenie ID pri parallel'nom
    # sohranenii isklyucheno. Fallback - staryj MAX(Measure_ID)+1.
    try:
        new_mid = register_measure_id(msk=msk, filename=file_label, login=login)
    except Exception as e:
        print(f"[TOC] psi_measure_id registraciya ne udalas ({e}); "
              f"fallback MAX(Measure_ID)+1", flush=True)
        new_mid = next_measure_id()

    psi = psi_rows.copy()
    psi["Measure_ID"] = new_mid
    if "MSK" in psi.columns:
        psi["MSK"] = msk
    for col, val in (
        ("File", file_label),
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
        # sluzhebnye kolonki korrekcii
        drop_extra = [c for c in df.columns if str(c).endswith("_method")]
        if drop_extra:
            df.drop(columns=drop_extra, inplace=True, errors="ignore")

    psi = _align_df_to_table(psi, _main())
    # priznaki korrekcii: KO / KO_F = 1 (dannye ispravleny modulem korrekcii)
    _ko_cols = {str(c).upper(): c for c in _table_columns(_main())}
    for flg in ("KO", "KO_F"):
        real = _ko_cols.get(flg)
        if real is not None:
            psi[real] = 1
    if not temps.empty:
        temps = _align_df_to_table(temps, _temps())

    with eng.begin() as conn:
        psi.to_sql(
            _main(), con=conn, if_exists="append", index=False,
            method="multi", chunksize=500,
        )
        if not temps.empty:
            temps.to_sql(
                _temps(), con=conn, if_exists="append", index=False,
                method="multi", chunksize=500,
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
