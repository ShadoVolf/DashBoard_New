"""
Logika korrekcii vybrosov TCH (F, R) po neskolkim zameram.

F: zapolnenie prorezhin i sglazhivanie - polinom 3 poryadka.
R: consensus + regressiya stepeni 2 (kak ran'she, rabotaet horosho).
IsolationForest: skor po ostatku ot poly3, kraevye tochki ne pomechayutsya
tol'ko po IF (chtoby ne bylo bol'shih oshibok na krayah).
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from .constants import MAD_K, OUTLIER_MARKER, OUTLIER_PARAMS

from . import learning as toc_learning

ProgressCb = Optional[Callable[[float, str], None]]

_ABS_FLOOR = {
    "F": 2.0,
    "R": 0.5,
    "FL": 2.0,
    "Q": 50.0,
}

# stepen' polinoma dlya zapolneniya / sglazhivaniya
_POLY_DEGREE = {
    "F": 3,
    "R": 2,
    "FL": 3,
    "Q": 2,
}


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
    arr = np.asarray(
        [v for v in values if v is not None and v != OUTLIER_MARKER], dtype=float
    )
    if arr.size == 0:
        return 0.0, 0.0, None
    med = float(np.median(arr))
    if arr.size < 3:
        return med, 0.0, None
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
    """Zapolnenie plohih tochek polinomom zadannoj stepeni (dlya F - 3)."""
    out = values.astype(float).copy()
    good = ~bad_mask & np.isfinite(values) & (values != OUTLIER_MARKER)
    n_good = int(good.sum())
    if n_good < max(2, degree + 1):
        for i in np.where(bad_mask)[0]:
            neigh = []
            for j in range(max(0, i - 2), min(len(values), i + 3)):
                if j == i:
                    continue
                if np.isfinite(values[j]) and values[j] != OUTLIER_MARKER:
                    neigh.append(float(values[j]))
            if neigh:
                out[i] = float(np.median(neigh))
        return out
    deg = min(degree, n_good - 1)
    coeffs = np.polyfit(temps[good], values[good], deg)
    for i in np.where(bad_mask)[0]:
        out[i] = float(np.polyval(coeffs, temps[i]))
    return out


def smooth_curve_poly(
    temps: np.ndarray,
    values: np.ndarray,
    degree: int = 3,
    protect_mask: Optional[np.ndarray] = None,
    max_delta: Optional[float] = None,
) -> np.ndarray:
    """
    Sglazhivanie krivoj polinomom. Tochki s protect_mask=True
    ne dvigaem sil'nee max_delta (sohranyaem consensus).
    """
    out = values.astype(float).copy()
    finite = np.isfinite(out) & (out != OUTLIER_MARKER)
    if int(finite.sum()) < max(2, degree + 1):
        return out
    deg = min(degree, int(finite.sum()) - 1)
    coeffs = np.polyfit(temps[finite], out[finite], deg)
    approx = np.polyval(coeffs, temps)
    for i in range(len(out)):
        if not np.isfinite(temps[i]):
            continue
        if not finite[i]:
            out[i] = float(approx[i])
            continue
        if protect_mask is not None and protect_mask[i]:
            if max_delta is not None and abs(approx[i] - out[i]) > max_delta:
                # ne lomayem horoshuyu tochu
                continue
            # legkoe podtyagivanie
            out[i] = float(0.7 * out[i] + 0.3 * approx[i])
        else:
            out[i] = float(approx[i])
    return out


def _series_for_number(
    temps_df: pd.DataFrame, mid: int, number: str
) -> pd.DataFrame:
    if temps_df is None or temps_df.empty:
        return pd.DataFrame()
    sub = temps_df[
        (temps_df["Measure_ID"] == mid)
        & (temps_df["N"].astype(str).str.strip().str.upper() == str(number).upper())
    ].copy()
    if sub.empty:
        return sub
    return sub.sort_values("Temp").reset_index(drop=True)


def _within_curve_bad_mask(temps: np.ndarray, values: np.ndarray) -> np.ndarray:
    n = len(values)
    bad = np.zeros(n, dtype=bool)
    clean = []
    for i, v in enumerate(values):
        if not np.isfinite(v) or v == OUTLIER_MARKER:
            bad[i] = True
        else:
            clean.append(float(v))
    if len(clean) >= 3:
        med, _, thr = _mad_threshold(clean)
        if thr is not None:
            for i, v in enumerate(values):
                if bad[i]:
                    continue
                if abs(float(v) - med) > thr:
                    bad[i] = True
    for i in range(n):
        if bad[i] or not np.isfinite(values[i]):
            continue
        neigh = []
        for j in (i - 1, i + 1):
            if 0 <= j < n and not bad[j] and np.isfinite(values[j]) and values[j] != OUTLIER_MARKER:
                neigh.append(float(values[j]))
        if len(neigh) == 2:
            pred = 0.5 * (neigh[0] + neigh[1])
            spread = abs(neigh[0] - neigh[1]) + 1e-9
            if abs(float(values[i]) - pred) > max(3.0 * spread, abs(pred) * 0.02 + 1e-6):
                bad[i] = True
    return bad


def _cross_is_bad(
    v: Optional[float],
    peers: List[Optional[float]],
    param: str,
) -> bool:
    if v is None or (isinstance(v, float) and not np.isfinite(v)):
        return True
    if v == OUTLIER_MARKER:
        return True
    peer_vals = [
        float(x) for x in peers
        if x is not None and x != OUTLIER_MARKER and np.isfinite(float(x))
    ]
    if len(peer_vals) < 2:
        return False
    med, _, thr = _mad_threshold(peer_vals)
    floor = _ABS_FLOOR.get(param, 1.0)
    if thr is None:
        others = [x for x in peer_vals if abs(x - float(v)) > 1e-15]
        if not others:
            return False
        omed = float(np.median(others))
        rel = abs(omed) * 0.03 + floor
        return abs(float(v) - omed) > rel
    thr_use = max(thr, floor)
    if abs(float(v) - med) > thr_use:
        return True
    others = [x for x in peer_vals if abs(x - float(v)) > 1e-15]
    if others:
        omed = float(np.median(others))
        if abs(float(v) - omed) > thr_use:
            return True
    return False


def _align_grid(
    series_by_mid: Dict[int, pd.DataFrame],
    param: str,
    temp_tol: float = 0.51,
    extra_bad: Optional[Dict[int, set]] = None,
) -> Tuple[List[float], Dict[int, List[Optional[float]]], Dict[int, List[bool]]]:
    all_t: List[float] = []
    for df in series_by_mid.values():
        if df is None or df.empty or "Temp" not in df.columns:
            continue
        for t in df["Temp"].dropna():
            tv = _safe_float(t)
            if tv is not None:
                all_t.append(round(tv, 2))
    if not all_t:
        return [], {}, {}

    grid = sorted(set(all_t))
    aligned: Dict[int, List[Optional[float]]] = {}
    within_bad: Dict[int, List[bool]] = {}

    for mid, df in series_by_mid.items():
        if df is None or df.empty or param not in df.columns:
            aligned[mid] = [None] * len(grid)
            within_bad[mid] = [True] * len(grid)
            continue
        temps = np.asarray([_safe_float(t) or np.nan for t in df["Temp"]], dtype=float)
        values = np.asarray(
            [_safe_float(v) if _safe_float(v) is not None else np.nan for v in df[param]],
            dtype=float,
        )
        values_for_mask = values.copy()
        values_for_mask[~np.isfinite(values_for_mask)] = OUTLIER_MARKER
        wbad = _within_curve_bad_mask(temps, values_for_mask)

        vals: List[Optional[float]] = []
        wflags: List[bool] = []
        used = set()
        for t_ref in grid:
            best = None
            best_d = temp_tol + 1
            best_i = None
            for idx in range(len(df)):
                if idx in used:
                    continue
                tv = temps[idx]
                if not np.isfinite(tv):
                    continue
                d = abs(float(tv) - t_ref)
                if d < best_d:
                    best_d = d
                    vv = values[idx]
                    best = float(vv) if np.isfinite(vv) else None
                    best_i = idx
            if best_i is not None and best_d <= temp_tol:
                used.add(best_i)
                # tocki "sboya stenda" udalayutsya so vseh krivyh zamera
                eb = (extra_bad or {}).get(mid) or set()
                if eb and round(float(temps[best_i]), 2) in eb:
                    vals.append(None)
                    wflags.append(True)
                else:
                    vals.append(best)
                    wflags.append(bool(wbad[best_i]))
            else:
                vals.append(None)
                wflags.append(True)
        aligned[mid] = vals
        within_bad[mid] = wflags
    return grid, aligned, within_bad


def _nn_outlier_scores(
    grid: List[float],
    aligned: Dict[int, List[Optional[float]]],
    nn_options: Optional[Dict[str, bool]],
    param: str = "F",
) -> Dict[int, List[float]]:
    """
    IsolationForest po ostatku ot poly-fit (ne po syrym index,value).
    Kraevye 15% tochek NE pomechayutsya tol'ko po IF.
    """
    scores = {m: [0.0] * len(grid) for m in aligned}
    if not nn_options:
        return scores
    use_if = nn_options.get("use_isolation_forest") or nn_options.get("use_autoencoder")
    if not use_if or not grid:
        return scores

    # trained model from active learning if available
    model = None
    try:
        from . import learning as toc_learning
        model = toc_learning.get_trained_model(param)
    except Exception:
        model = None

    try:
        from sklearn.ensemble import IsolationForest  # type: ignore
    except Exception:
        return scores

    n = len(grid)
    edge = max(1, int(0.15 * n))  # kraevye zony
    deg = _POLY_DEGREE.get(param, 2)

    for mid, vals in aligned.items():
        xs, ys, idxs = [], [], []
        for i, v in enumerate(vals):
            if v is not None and v != OUTLIER_MARKER and np.isfinite(float(v)):
                xs.append(float(grid[i]))
                ys.append(float(v))
                idxs.append(i)
        if len(xs) < 6:
            continue
        t_arr = np.asarray(xs, dtype=float)
        v_arr = np.asarray(ys, dtype=float)
        try:
            d = min(deg, len(xs) - 1)
            coeffs = np.polyfit(t_arr, v_arr, d)
            resid = v_arr - np.polyval(coeffs, t_arr)
            # features: residual, normalized position
            t_norm = (t_arr - t_arr.min()) / (t_arr.max() - t_arr.min() + 1e-9)
            feat = np.column_stack([resid, t_norm])
            if model is not None:
                pred = model.predict(feat)
            else:
                clf = IsolationForest(
                    contamination=min(0.1, max(0.05, 2.0 / len(xs))),
                    random_state=42,
                    n_estimators=100,
                )
                pred = clf.fit_predict(feat)
            for k, i in enumerate(idxs):
                # ne trogaem kraevye tol'ko po IF
                if i < edge or i >= n - edge:
                    continue
                if pred[k] < 0:
                    scores[mid][i] = 1.0
        except Exception:
            continue
    return scores


def build_corrected_curve_for_number(
    temps_df: pd.DataFrame,
    selected_mids: Sequence[int],
    number: str,
    params: Sequence[str] = OUTLIER_PARAMS,
    prefer_mid: Optional[int] = None,
    degree: int = 2,
    nn_options: Optional[Dict[str, bool]] = None,
    extra_bad: Optional[Dict[str, Dict[int, set]]] = None,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]], int]:
    mids = [int(m) for m in selected_mids]
    series_by_mid: Dict[int, pd.DataFrame] = {}
    for mid in mids:
        s = _series_for_number(temps_df, mid, number)
        if not s.empty:
            series_by_mid[mid] = s
    if not series_by_mid:
        return pd.DataFrame(), [], (prefer_mid or (mids[0] if mids else 0))

    bad_counts: Dict[int, int] = {m: 0 for m in series_by_mid}
    aligned_all: Dict[str, Any] = {}

    for param in params:
        eb_mid = (extra_bad or {}).get(param, {})
        grid, aligned, within_bad = _align_grid(
            series_by_mid, param, extra_bad=eb_mid or None
        )
        nn_scores = _nn_outlier_scores(grid, aligned, nn_options, param=param)
        aligned_all[param] = (grid, aligned, within_bad, nn_scores)
        for mid in series_by_mid:
            for i, v in enumerate(aligned.get(mid, [])):
                peers = [aligned[m][i] for m in aligned]
                local = within_bad.get(mid, [False] * len(grid))[i] if i < len(within_bad.get(mid, [])) else False
                cross = _cross_is_bad(v, peers, param)
                nn = (nn_scores.get(mid) or [0.0])[i] >= 0.5 if i < len(nn_scores.get(mid) or []) else False
                if local or cross or nn or v is None:
                    bad_counts[mid] = bad_counts.get(mid, 0) + 1

    # Если пользователь явно указал основной замер и по нему есть данные — берём его.
    # Иначе: меньше «плохих» точек, при равенстве — prefer_mid, затем меньший MID.
    if prefer_mid is not None and int(prefer_mid) in series_by_mid:
        base_mid = int(prefer_mid)
    else:
        ordered = sorted(
            series_by_mid.keys(),
            key=lambda m: (bad_counts.get(m, 10**9), 0 if m == prefer_mid else 1, m),
        )
        base_mid = ordered[0]

    all_grid: List[float] = []
    for param in params:
        g = aligned_all.get(param, ([], {}, {}, {}))[0]
        all_grid.extend(g)
    out_grid = sorted(set(all_grid)) if all_grid else []
    if not out_grid:
        base_df = series_by_mid[base_mid].copy()
        base_df["Measure_ID"] = base_mid
        base_df["N"] = str(number).upper()
        return base_df, [], base_mid

    rows: List[Dict[str, Any]] = []
    for t in out_grid:
        rows.append({"Temp": t, "N": str(number).upper(), "Measure_ID": base_mid})
    out_df = pd.DataFrame(rows)
    base_src = series_by_mid[base_mid]
    extra_cols = [
        c for c in base_src.columns
        if c not in ("Temp", "N", "Measure_ID") and c not in params
    ]
    for c in extra_cols:
        out_df[c] = np.nan

    # Parametry na odnoj temperature (ne OUTLIER_PARAMS F/R):
    # 1) s zamera gde znachenie v norme specifikacii (esli limity est)
    # 2) inache s osnovnogo
    # 3) inache s lyubogo drugogo gde est konechnoe znachenie
    if extra_cols and out_grid:
        from .data import value_in_spec

        limits_map = getattr(
            build_corrected_curve_for_number, "_spec_limits", None
        ) or {}
        rows_by_mid_t: Dict[int, Dict[float, Any]] = {}
        for mid, src in series_by_mid.items():
            if "Temp" not in src.columns:
                continue
            bucket: Dict[float, Any] = {}
            for _, row in src.iterrows():
                try:
                    bucket[round(float(row["Temp"]), 4)] = row
                except (TypeError, ValueError):
                    continue
            rows_by_mid_t[mid] = bucket

        for i, t in enumerate(out_grid):
            key = round(float(t), 4)
            for c in extra_cols:
                val = None
                lim = limits_map.get(c) or limits_map.get(str(c).upper())
                if lim:
                    for mid, bucket in rows_by_mid_t.items():
                        row = bucket.get(key)
                        if row is None or c not in row.index:
                            continue
                        try:
                            v = float(row[c])
                        except (TypeError, ValueError):
                            continue
                        if (
                            np.isfinite(v)
                            and v != OUTLIER_MARKER
                            and value_in_spec(v, lim)
                        ):
                            val = v
                            break
                if val is None:
                    row = rows_by_mid_t.get(base_mid, {}).get(key)
                    if row is not None and c in row.index:
                        try:
                            v = float(row[c])
                            if np.isfinite(v) and v != OUTLIER_MARKER:
                                val = v
                        except (TypeError, ValueError):
                            pass
                if val is None:
                    for mid, bucket in rows_by_mid_t.items():
                        if mid == base_mid:
                            continue
                        row = bucket.get(key)
                        if row is None or c not in row.index:
                            continue
                        try:
                            v = float(row[c])
                            if np.isfinite(v) and v != OUTLIER_MARKER:
                                val = v
                                break
                        except (TypeError, ValueError):
                            continue
                if val is not None:
                    out_df.at[i, c] = val

    corrections: List[Dict[str, Any]] = []

    for param in params:
        grid, aligned, within_bad, nn_scores = aligned_all.get(
            param, ([], {}, {}, {})
        )
        if not grid:
            continue
        g_index = {t: i for i, t in enumerate(grid)}
        corr_vals: List[float] = []
        bad_flags: List[bool] = []
        protect: List[bool] = []
        methods: List[str] = []

        deg = _POLY_DEGREE.get(param, degree)

        for t_ref in out_grid:
            if t_ref not in g_index:
                corr_vals.append(np.nan)
                bad_flags.append(True)
                protect.append(False)
                methods.append("missing")
                continue
            i = g_index[t_ref]
            peers = [aligned[m][i] for m in aligned]
            good: List[float] = []
            for mid in aligned:
                v = aligned[mid][i]
                if v is None or v == OUTLIER_MARKER or not np.isfinite(float(v)):
                    continue
                local = within_bad.get(mid, [False] * len(grid))[i]
                cross = _cross_is_bad(v, peers, param)
                nn = False
                if nn_scores.get(mid) and i < len(nn_scores[mid]):
                    nn = nn_scores[mid][i] >= 0.5
                if not local and not cross and not nn:
                    good.append(float(v))

            base_v = aligned.get(base_mid, [None] * len(grid))[i] if base_mid in aligned else None

            if good:
                new_v = float(np.median(good))
                method = "cross_consensus"
                if (
                    base_v is not None
                    and base_v != OUTLIER_MARKER
                    and np.isfinite(float(base_v))
                    and not _cross_is_bad(base_v, peers, param)
                    and not (within_bad.get(base_mid, [False] * len(grid))[i] if base_mid in within_bad else False)
                    and abs(float(base_v) - new_v) <= _ABS_FLOOR.get(param, 1.0) * 0.25
                ):
                    new_v = float(base_v)
                    method = "base_keep"
                corr_vals.append(new_v)
                bad_flags.append(False)
                protect.append(True)
                methods.append(method)
                if base_v is None or abs(float(base_v) - new_v) > 1e-12:
                    corrections.append({
                        "mid": base_mid,
                        "number": number,
                        "param": param,
                        "temp": t_ref,
                        "old": base_v,
                        "new": new_v,
                        "reason": method,
                        "n_good": len(good),
                        "n_peers": len([p for p in peers if p is not None]),
                    })
            else:
                corr_vals.append(
                    float(base_v) if base_v is not None and np.isfinite(float(base_v)) else np.nan
                )
                bad_flags.append(True)
                protect.append(False)
                methods.append("need_regression")

        temps_arr = np.asarray(out_grid, dtype=float)
        vals_arr = np.asarray(corr_vals, dtype=float)
        bad_mask = np.asarray(bad_flags, dtype=bool) | ~np.isfinite(vals_arr)
        protect_mask = np.asarray(protect, dtype=bool)

        if bad_mask.any():
            # TCN/seq2seq vosstanovlenie probelov vmesto poly-zapolneniya;
            # bez modeli - interpolyaciya zamenyaet regression_replace.
            use_tcn = bool(nn_options and nn_options.get("use_tcn_restore"))
            fixed = None
            reason = f"poly{deg}_fill"
            if use_tcn:
                try:
                    fixed = toc_learning.tcn_restore_curve(
                        vals_arr, bad_mask, param=param
                    )
                    if fixed is not None:
                        reason = "tcn_restore"
                except Exception as e:
                    print(f"[TOC] tcn_restore failed: {e}", flush=True)
                    fixed = None
            if fixed is None:
                fixed = regression_replace(temps_arr, vals_arr, bad_mask, degree=deg)
                reason = f"poly{deg}_fill"
            for i in np.where(bad_mask)[0]:
                if not np.isfinite(float(fixed[i])):
                    continue
                corrections.append({
                    "mid": base_mid,
                    "number": number,
                    "param": param,
                    "temp": float(out_grid[i]),
                    "old": float(vals_arr[i]) if np.isfinite(vals_arr[i]) else None,
                    "new": float(fixed[i]),
                    "reason": reason,
                })
                corr_vals[i] = float(fixed[i])
                methods[i] = reason
            vals_arr = np.asarray(corr_vals, dtype=float)

        # Sglazhivanie dlya F (poly3) - vsya krivaya
        if param == "F" and len(corr_vals) >= 5:
            smoothed = smooth_curve_poly(
                temps_arr,
                np.asarray(corr_vals, dtype=float),
                degree=3,
                protect_mask=protect_mask,
                max_delta=_ABS_FLOOR.get("F", 2.0) * 2,
            )
            for i in range(len(corr_vals)):
                if abs(smoothed[i] - corr_vals[i]) > 1e-9:
                    corrections.append({
                        "mid": base_mid,
                        "number": number,
                        "param": param,
                        "temp": float(out_grid[i]),
                        "old": float(corr_vals[i]),
                        "new": float(smoothed[i]),
                        "reason": "poly3_smooth",
                    })
                    methods[i] = methods[i] + "+poly3_smooth"
                    corr_vals[i] = float(smoothed[i])

        out_df[param] = [float(v) for v in corr_vals]
        out_df[f"{param}_method"] = methods

    return out_df, corrections, base_mid


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
            sub = df[df["N"].astype(str).str.strip().str.upper() == n].sort_values("Temp")
            if param not in sub.columns:
                continue
            vals = [_safe_float(v) for v in sub[param].tolist()]
            arr = np.asarray([v if v is not None else OUTLIER_MARKER for v in vals], dtype=float)
            temps = np.asarray([_safe_float(t) or np.nan for t in sub["Temp"]], dtype=float)
            wbad = _within_curve_bad_mask(temps, arr)
            bad_temps = set()
            for k, row in enumerate(sub.itertuples(index=False)):
                tv = _safe_float(getattr(row, "Temp", None))
                if tv is None:
                    continue
                if wbad[k]:
                    bad_temps.add(round(tv, 2))
            per_n_bad[str(n)] = bad_temps
        all_temps: Dict[float, int] = {}
        for s in per_n_bad.values():
            for t in s:
                all_temps[t] = all_temps.get(t, 0) + 1
        for t, cnt in all_temps.items():
            if cnt / n_total >= min_fraction:
                failures.append({
                    "mid": measure_id,
                    "param": param,
                    "temp": t,
                    "affected": cnt,
                    "total": n_total,
                    "reason": "global_temp_failure",
                })
    return failures


def classify_temp_failures(
    temps_df: pd.DataFrame,
    measure_id: int,
    params: Sequence[str] = OUTLIER_PARAMS,
    min_fraction: float = 0.7,
    sign_fraction: float = 0.8,
    min_noise_numbers: int = 3,
) -> List[Dict[str, Any]]:
    """
    Klassifikaciya sboev po patternu vseh N na odnoj T:
      - "stand" (sboy stenda): na temperature T zametnoe otklonenie Odnogo
        napravleniya vosproizvoditsya u >= min_fraction vseh N - takie T
        udalayutsya so VSEH krivyh zamera i vosstanavlivayutsya model'yu;
      - "noise" (shum): razbroshennye plohie tochki po mnogim N bez obshej T;
      - "single" (edinichnyj rezonator): vybrosy lokalizovany v odnom N.
    """
    if temps_df is None or temps_df.empty:
        return []
    df = temps_df[temps_df["Measure_ID"] == measure_id].copy()
    if df.empty:
        return []
    numbers = sorted(
        df["N"].astype(str).str.strip().str.upper().unique().tolist()
    )
    n_total = len(numbers)
    if n_total < 3:
        return []
    result: List[Dict[str, Any]] = []

    for param in params:
        if param not in df.columns:
            continue
        scatter: Dict[str, set] = {}
        bad_gate: Dict[float, Dict[str, bool]] = {}
        sign_gate: Dict[float, Dict[str, float]] = {}
        for n in numbers:
            sub = (
                df[df["N"].astype(str).str.strip().str.upper() == str(n)]
                .sort_values("Temp")
            )
            pts = [
                (_safe_float(t), _safe_float(v))
                for t, v in zip(sub["Temp"].tolist(), sub[param].tolist())
            ]
            pts = [
                (t, v) for t, v in pts
                if t is not None and v is not None
                and np.isfinite(t) and np.isfinite(v)
            ]
            if len(pts) < 3:
                continue
            temps_arr = np.asarray([p[0] for p in pts], dtype=float)
            vals_arr = np.asarray([p[1] for p in pts], dtype=float)
            mine = set()
            # svoi vybrosy: MAD + sosednij test (kak _within_curve_bad_mask)
            mask_in = np.where(np.isfinite(vals_arr), vals_arr, OUTLIER_MARKER)
            wbad = _within_curve_bad_mask(temps_arr, mask_in)
            for i, wb in enumerate(wbad):
                if wb:
                    mine.add(round(float(temps_arr[i]), 2))
            if mine:
                scatter.setdefault(str(n), set()).update(mine)
            # otkloneniya ot sosedej - potencialnyj "stand"
            for i in range(1, len(pts) - 1):
                pred = 0.5 * (vals_arr[i - 1] + vals_arr[i + 1])
                if not np.isfinite(pred):
                    continue
                spread = abs(vals_arr[i - 1] - vals_arr[i + 1])
                r = float(vals_arr[i] - pred)
                t_r = round(float(temps_arr[i]), 2)
                bad_gate.setdefault(t_r, {})[str(n)] = abs(r) > max(
                    3.0 * spread, abs(pred) * 0.02 + 1e-6
                )
                sign_gate.setdefault(t_r, {})[str(n)] = 1.0 if r >= 0 else -1.0

        stand: set = set()
        for t_r, bgate in bad_gate.items():
            bad_ns = [k for k, ok in bgate.items() if ok]
            need = max(2, int(round(min_fraction * n_total)))
            if len(bad_ns) < need:
                continue
            sgn = sign_gate.get(t_r, {})
            pos = sum(1 for k in bad_ns if sgn.get(k, 0.0) > 0)
            neg = len(bad_ns) - pos
            dominant = max(pos, neg)
            if len(bad_ns) and (dominant / len(bad_ns)) >= sign_fraction:
                stand.add(t_r)
                result.append({
                    "mid": measure_id,
                    "param": param,
                    "temp": float(t_r),
                    "class": "stand",
                    "affected": len(bad_ns),
                    "total": n_total,
                    "reason": "global_temp_failure",
                })

        all_scatter = {
            n: (s - stand) for n, s in scatter.items() if (s - stand)
        }
        if len(all_scatter) >= min_noise_numbers:
            total_bad = sum(len(s) for s in all_scatter.values())
            result.append({
                "mid": measure_id,
                "param": param,
                "class": "noise",
                "affected": len(all_scatter),
                "total": n_total,
                "bad_points": total_bad,
                "reason": "noise_pattern",
            })
        elif len(all_scatter) == 1:
            for n, s in all_scatter.items():
                for t_r in sorted(s):
                    result.append({
                        "mid": measure_id,
                        "param": param,
                        "number": n,
                        "temp": float(t_r),
                        "class": "single",
                        "reason": "single_resonator",
                    })
    return result


def build_corrected_temps(
    temps_df: pd.DataFrame,
    selected_mids: Sequence[int],
    params: Sequence[str] = OUTLIER_PARAMS,
    prefer_mid: Optional[int] = None,
    progress: ProgressCb = None,
    nn_options: Optional[Dict[str, bool]] = None,
    spec_limits: Optional[Dict[str, Dict[str, Optional[float]]]] = None,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]], Dict[str, Any]]:
    selected_mids = list(selected_mids)
    if not selected_mids:
        return pd.DataFrame(), [], {}
    # limits for extra-col pick (Q, C0, Cq, L, ...)
    build_corrected_curve_for_number._spec_limits = dict(spec_limits or {})  # type: ignore[attr-defined]

    def _p(pct: float, msg: str) -> None:
        if progress:
            try:
                progress(pct, msg)
            except Exception:
                pass

    _p(2, "Подготовка...")
    numbers = (
        temps_df[temps_df["Measure_ID"].isin(selected_mids)]["N"]
        .astype(str)
        .str.strip()
        .str.upper()
        .unique()
        .tolist()
        if temps_df is not None and not temps_df.empty
        else []
    )
    numbers = sorted({n for n in numbers if n})

    all_corr: List[Dict[str, Any]] = []
    parts: List[pd.DataFrame] = []
    report: Dict[str, Any] = {"per_number": {}, "global": [], "base_mid": None}
    base_votes: List[int] = []

    # klassifikaciya sboev: stand-temperatury udalayutsya so vseh krivyh zamera
    extra_bad: Dict[str, Dict[int, set]] = {}
    if nn_options and nn_options.get("use_failure_classifier"):
        for mid in selected_mids:
            entries = classify_temp_failures(temps_df, mid, params=params)
            report["global"].extend(entries)
            for e in entries:
                if e.get("class") == "stand":
                    extra_bad.setdefault(e["param"], {}).setdefault(
                        int(mid), set()
                    ).add(round(float(e["temp"]), 2))
    else:
        for mid in selected_mids:
            gfs = detect_global_temp_failures(temps_df, mid, params=params)
            report["global"].extend(gfs)

    n_total = max(len(numbers), 1)
    for k, n in enumerate(numbers):
        _p(5 + 90 * k / n_total, f"N {n} ({k+1}/{n_total})")
        part, corr, base_mid = build_corrected_curve_for_number(
            temps_df,
            selected_mids,
            n,
            params=params,
            prefer_mid=prefer_mid,
            nn_options=nn_options,
            extra_bad=extra_bad or None,
        )
        if not part.empty:
            parts.append(part)
        all_corr.extend(corr)
        base_votes.append(base_mid)
        report["per_number"][n] = {
            "corrections": len(corr),
            "base_mid": base_mid,
        }

    if parts:
        corrected = pd.concat(parts, ignore_index=True)
    else:
        corrected = pd.DataFrame()

    if base_votes:
        report["base_mid"] = max(set(base_votes), key=base_votes.count)
    else:
        report["base_mid"] = prefer_mid or selected_mids[0]
    report["n_corrections"] = len(all_corr)
    report["nn_options"] = dict(nn_options or {})
    report["corrections"] = all_corr
    _p(100, "Готово")
    return corrected, all_corr, report
