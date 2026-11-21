"""
Логика обнаружения и коррекции выбросов.

Сценарии:
1) По каждому номеру резонатора N: сравниваем кривые F/R нескольких замеров
   на одинаковых температурах. Если точка — выброс только на одном замере
   (есть «хорошие» соседи на той же T) — заменяем медианой/регрессией.
2) Глобальная корреляция: если на одной температуре у ВСЕХ номеров одного
   замера единичный сбой (выброс), точка считается системным сбоем замера
   и заменяется регрессией по соседним температурам.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .constants import MAD_K, MEASURABLE_COLS, OUTLIER_MARKER, OUTLIER_PARAMS


def _safe_float(v) -> Optional[float]:
    if v is None or (isinstance(v, float) and (np.isnan(v) or np.isinf(v))):
        return None
    try:
        fv = float(v)
        if np.isnan(fv) or np.isinf(fv):
            return None
        return fv
    except (TypeError, ValueError):
        return None


def _mad_threshold(values: Sequence[float]) -> Tuple[float, float, Optional[float]]:
    """median, robust_sigma, threshold (or None if too few points)."""
    arr = np.asarray(
        [v for v in values if v is not None and v != OUTLIER_MARKER], dtype=float
    )
    if arr.size < 3:
        return float(np.median(arr)) if arr.size else 0.0, 0.0, None
    med = float(np.median(arr))
    mad = float(np.median(np.abs(arr - med)))
    sigma = 1.4826 * mad
    thr = MAD_K * sigma if sigma > 0 else None
    return med, sigma, thr


def is_outlier_value(value: float, median: float, threshold: Optional[float]) -> bool:
    if value == OUTLIER_MARKER:
        return True
    if threshold is None:
        return False
    return abs(value - median) > threshold


def regression_replace(
    temps: np.ndarray,
    values: np.ndarray,
    bad_mask: np.ndarray,
    degree: int = 2,
) -> np.ndarray:
    """Замена плохих точек полиномиальной регрессией по хорошим."""
    out = values.astype(float).copy()
    good = ~bad_mask & np.isfinite(values) & (values != OUTLIER_MARKER)
    if good.sum() < max(2, degree + 1):
        for i in np.where(bad_mask)[0]:
            neigh = []
            for j in range(max(0, i - 2), min(len(values), i + 3)):
                if j == i:
                    continue
                if good[j] or (np.isfinite(values[j]) and values[j] != OUTLIER_MARKER):
                    neigh.append(values[j])
            if neigh:
                out[i] = float(np.median(neigh))
        return out

    deg = min(degree, int(good.sum()) - 1)
    coeffs = np.polyfit(temps[good], values[good], deg)
    for i in np.where(bad_mask)[0]:
        out[i] = float(np.polyval(coeffs, temps[i]))
    return out


def _align_by_temp(
    series_list: List[pd.DataFrame],
    param: str,
    temp_tol: float = 0.51,
) -> Dict[float, List[Optional[float]]]:
    if not series_list:
        return {}
    ref = series_list[0]
    if ref.empty or "Temp" not in ref.columns:
        return {}
    ref_temps = sorted(
        {
            round(float(t), 2)
            for t in ref["Temp"].dropna()
            if _safe_float(t) is not None
        }
    )
    result: Dict[float, List[Optional[float]]] = {t: [] for t in ref_temps}
    for df in series_list:
        used = set()
        for t_ref in ref_temps:
            best = None
            best_d = temp_tol + 1
            for idx, row in df.iterrows():
                if idx in used:
                    continue
                tv = _safe_float(row.get("Temp"))
                if tv is None:
                    continue
                d = abs(tv - t_ref)
                if d < best_d:
                    best_d = d
                    best = (idx, _safe_float(row.get(param)))
            if best is not None and best_d <= temp_tol:
                used.add(best[0])
                result[t_ref].append(best[1])
            else:
                result[t_ref].append(None)
    return result


def detect_cross_measure_outliers(
    temps_by_mid: Dict[int, pd.DataFrame],
    number: str,
    params: Sequence[str] = OUTLIER_PARAMS,
) -> Dict[str, Any]:
    mids = list(temps_by_mid.keys())
    if len(mids) < 2:
        return {"outliers": [], "masks": {}}

    series = []
    mid_order = []
    for mid in mids:
        df = temps_by_mid[mid]
        if df is None or df.empty:
            continue
        sub = df[
            df["N"].astype(str).str.strip().str.upper() == str(number).upper()
        ].copy()
        if sub.empty:
            continue
        sub = sub.sort_values("Temp")
        series.append(sub)
        mid_order.append(mid)

    if len(series) < 2:
        return {"outliers": [], "masks": {}}

    outliers: List[Dict[str, Any]] = []
    masks: Dict[int, Dict[str, np.ndarray]] = {mid: {} for mid in mid_order}

    for param in params:
        aligned = _align_by_temp(series, param)
        for t_ref, vals in aligned.items():
            good_vals = [v for v in vals if v is not None and v != OUTLIER_MARKER]
            if len(good_vals) < 2:
                continue
            med, _, thr = _mad_threshold(good_vals)
            for i, v in enumerate(vals):
                if v is None:
                    continue
                mid = mid_order[i]
                is_bad = is_outlier_value(v, med, thr)
                others = [
                    x
                    for j, x in enumerate(vals)
                    if j != i and x is not None and x != OUTLIER_MARKER
                ]
                if others and thr is not None:
                    other_med = float(np.median(others))
                    if abs(v - other_med) > thr and abs(v - other_med) > abs(
                        med - other_med
                    ) * 0.5:
                        is_bad = True
                if v == OUTLIER_MARKER:
                    is_bad = True
                if is_bad:
                    outliers.append(
                        {
                            "mid": mid,
                            "param": param,
                            "temp": t_ref,
                            "old": v,
                            "reason": "cross_measure",
                            "number": number,
                        }
                    )

        for i, mid in enumerate(mid_order):
            df = series[i]
            mask = np.zeros(len(df), dtype=bool)
            for k, row in enumerate(df.itertuples(index=False)):
                tv = _safe_float(getattr(row, "Temp", None))
                if tv is None:
                    continue
                t_key = (
                    min(aligned.keys(), key=lambda x: abs(x - tv)) if aligned else None
                )
                if t_key is None or abs(t_key - tv) > 0.51:
                    continue
                vals = aligned[t_key]
                v = vals[i] if i < len(vals) else None
                if v is None:
                    continue
                good_vals = [x for x in vals if x is not None and x != OUTLIER_MARKER]
                med, _, thr = _mad_threshold(good_vals)
                if is_outlier_value(v, med, thr) or v == OUTLIER_MARKER:
                    others = [
                        x for j, x in enumerate(vals) if j != i and x is not None
                    ]
                    if len(others) >= 1 or v == OUTLIER_MARKER:
                        mask[k] = True
            masks[mid][param] = mask

    return {
        "outliers": outliers,
        "masks": masks,
        "mid_order": mid_order,
        "series": series,
    }


def detect_global_temp_failures(
    temps_df: pd.DataFrame,
    measure_id: int,
    params: Sequence[str] = OUTLIER_PARAMS,
    min_fraction: float = 0.7,
) -> List[Dict[str, Any]]:
    if temps_df is None or temps_df.empty:
        return []
    df = temps_df[temps_df["Measure_ID"] == measure_id].copy()
    if df.empty:
        return []

    numbers = df["N"].astype(str).str.strip().str.upper().unique()
    n_total = len(numbers)
    if n_total < 3:
        return []

    failures: List[Dict[str, Any]] = []
    for param in params:
        per_n_bad: Dict[str, set] = {}
        for n in numbers:
            sub = df[
                df["N"].astype(str).str.strip().str.upper() == n
            ].sort_values("Temp")
            vals = (
                [_safe_float(v) for v in sub[param].tolist()]
                if param in sub.columns
                else []
            )
            clean = [v for v in vals if v is not None and v != OUTLIER_MARKER]
            med, _, thr = _mad_threshold(clean)
            bad_temps = set()
            for _, row in sub.iterrows():
                tv = _safe_float(row.get("Temp"))
                vv = _safe_float(row.get(param))
                if tv is None or vv is None:
                    continue
                if is_outlier_value(vv, med, thr):
                    bad_temps.add(round(tv, 2))
            per_n_bad[str(n)] = bad_temps

        all_temps: Dict[float, int] = {}
        for bad_set in per_n_bad.values():
            for t in bad_set:
                all_temps[t] = all_temps.get(t, 0) + 1

        for t, cnt in all_temps.items():
            if cnt / n_total >= min_fraction:
                failures.append(
                    {
                        "mid": measure_id,
                        "param": param,
                        "temp": t,
                        "affected": cnt,
                        "total": n_total,
                        "reason": "global_temp_failure",
                    }
                )
    return failures


def apply_corrections(
    temps_df: pd.DataFrame,
    measure_id: int,
    number: str,
    param_masks: Dict[str, np.ndarray],
    global_failures: Optional[List[Dict[str, Any]]] = None,
    params: Sequence[str] = OUTLIER_PARAMS,
    degree: int = 2,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    df = temps_df[
        (temps_df["Measure_ID"] == measure_id)
        & (temps_df["N"].astype(str).str.strip().str.upper() == str(number).upper())
    ].sort_values("Temp").copy()

    if df.empty:
        return df, []

    corrections: List[Dict[str, Any]] = []
    global_failures = global_failures or []
    temps = df["Temp"].astype(float).values

    for param in params:
        if param not in df.columns:
            continue
        values = df[param].astype(float).values.copy()
        bad = np.zeros(len(df), dtype=bool)

        mask = param_masks.get(param)
        if mask is not None and len(mask) == len(df):
            bad |= mask

        for gf in global_failures:
            if gf.get("mid") != measure_id or gf.get("param") != param:
                continue
            t_bad = float(gf["temp"])
            for i, t in enumerate(temps):
                if abs(t - t_bad) <= 0.51:
                    bad[i] = True

        if not bad.any():
            continue

        new_vals = regression_replace(temps, values, bad, degree=degree)
        for i in np.where(bad)[0]:
            old = float(values[i])
            new = float(new_vals[i])
            if abs(old - new) < 1e-12:
                continue
            corrections.append(
                {
                    "mid": measure_id,
                    "number": number,
                    "param": param,
                    "temp": float(temps[i]),
                    "old": old,
                    "new": new,
                    "reason": "regression",
                }
            )
            df.iloc[i, df.columns.get_loc(param)] = new

    return df, corrections


def build_corrected_temps(
    temps_df: pd.DataFrame,
    selected_mids: Sequence[int],
    params: Sequence[str] = OUTLIER_PARAMS,
    prefer_mid: Optional[int] = None,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]], Dict[str, Any]]:
    selected_mids = list(selected_mids)
    if not selected_mids:
        return pd.DataFrame(), [], {}

    base_mid = prefer_mid if prefer_mid in selected_mids else selected_mids[0]
    all_corr: List[Dict[str, Any]] = []
    report: Dict[str, Any] = {"per_number": {}, "global": []}

    global_by_mid: Dict[int, List[Dict[str, Any]]] = {}
    for mid in selected_mids:
        gfs = detect_global_temp_failures(temps_df, mid, params=params)
        global_by_mid[mid] = gfs
        report["global"].extend(gfs)

    numbers = (
        temps_df[temps_df["Measure_ID"].isin(selected_mids)]["N"]
        .astype(str)
        .str.strip()
        .str.upper()
        .unique()
        .tolist()
    )

    corrected_parts: List[pd.DataFrame] = []

    for n in sorted(set(numbers)):
        if not n:
            continue
        temps_by_mid = {
            mid: temps_df[
                (temps_df["Measure_ID"] == mid)
                & (temps_df["N"].astype(str).str.strip().str.upper() == n)
            ]
            for mid in selected_mids
        }
        det = detect_cross_measure_outliers(temps_by_mid, n, params=params)
        masks = det.get("masks") or {}

        param_masks = masks.get(base_mid, {})
        part, corr = apply_corrections(
            temps_df,
            base_mid,
            n,
            param_masks,
            global_failures=global_by_mid.get(base_mid, []),
            params=params,
        )
        if not part.empty:
            corrected_parts.append(part)
        all_corr.extend(corr)
        report["per_number"][n] = {
            "outliers_found": len(det.get("outliers") or []),
            "corrections": len(corr),
        }

        for mid in selected_mids:
            if mid == base_mid:
                continue
            pm = masks.get(mid, {})
            _, corr_o = apply_corrections(
                temps_df,
                mid,
                n,
                pm,
                global_failures=global_by_mid.get(mid, []),
                params=params,
            )
            all_corr.extend([{**c, "display_only": True} for c in corr_o])

    if corrected_parts:
        corrected = pd.concat(corrected_parts, ignore_index=True)
    else:
        corrected = temps_df[temps_df["Measure_ID"] == base_mid].copy()

    report["base_mid"] = base_mid
    report["n_corrections"] = len([c for c in all_corr if not c.get("display_only")])
    return corrected, all_corr, report
