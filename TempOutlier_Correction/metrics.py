"""
Пересчёт сводных метрик резонатора по температурной кривой.

Fmax, Fmin, Fptp, Fptp/2, Rmax, Rmin, Rptp,
Mono, Slope, Tmax, Tmin, Turnover.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
import pandas as pd

from .constants import OUTLIER_MARKER


def _clean_series(temps: np.ndarray, values: np.ndarray):
    mask = np.isfinite(temps) & np.isfinite(values) & (values != OUTLIER_MARKER)
    t = temps[mask]
    v = values[mask]
    order = np.argsort(t)
    return t[order], v[order]


def compute_curve_metrics(
    temp_df: pd.DataFrame,
    f_col: str = "F",
    r_col: str = "R",
    mono_degree: int = 3,
) -> Dict[str, Any]:
    """Метрики одной кривой (один N, один Measure_ID)."""
    out: Dict[str, Any] = {
        "Fmax": None,
        "Fmin": None,
        "Fptp": None,
        "Fptp/2": None,
        "Rmax": None,
        "Rmin": None,
        "Rptp": None,
        "Mono": None,
        "Slope": None,
        "Tmax": None,
        "Tmin": None,
        "Turnover": None,
    }
    if temp_df is None or temp_df.empty or "Temp" not in temp_df.columns:
        return out

    t_raw = temp_df["Temp"].astype(float).values

    if f_col in temp_df.columns:
        f_raw = temp_df[f_col].astype(float).values
        t, f = _clean_series(t_raw, f_raw)
        if f.size >= 1:
            out["Fmax"] = float(np.max(f))
            out["Fmin"] = float(np.min(f))
            out["Fptp"] = float(out["Fmax"] - out["Fmin"])
            out["Fptp/2"] = out["Fptp"] / 2.0
            out["Tmax"] = float(t[np.argmax(f)])
            out["Tmin"] = float(t[np.argmin(f)])
            if f.size >= 3:
                deg = min(mono_degree, f.size - 1)
                coeffs = np.polyfit(t, f, deg)
                dcoeffs = np.polyder(coeffs)
                roots = np.roots(dcoeffs)
                real_roots = [
                    float(r.real)
                    for r in roots
                    if abs(r.imag) < 1e-8 and t.min() <= r.real <= t.max()
                ]
                if real_roots:
                    mid = 0.5 * (t.min() + t.max())
                    real_roots.sort(key=lambda x: abs(x - mid))
                    out["Turnover"] = real_roots[0]
                else:
                    if f.size >= 2:
                        slopes = np.diff(f) / np.diff(t)
                        idx = int(np.argmin(np.abs(slopes)))
                        out["Turnover"] = float(0.5 * (t[idx] + t[idx + 1]))

            if f.size >= mono_degree + 1:
                deg = min(mono_degree, f.size - 1)
                coeffs = np.polyfit(t, f, deg)
                approx = np.polyval(coeffs, t)
                delta = approx - f
                if delta.size > 2:
                    delta = delta[1:-1]
                if delta.size:
                    i = int(np.argmax(np.abs(delta)))
                    out["Mono"] = float(delta[i])

            if f.size >= 2:
                out["Slope"] = (
                    float((f[-1] - f[0]) / (t[-1] - t[0])) if t[-1] != t[0] else 0.0
                )

    if r_col in temp_df.columns:
        r_raw = temp_df[r_col].astype(float).values
        t, r = _clean_series(t_raw, r_raw)
        if r.size >= 1:
            out["Rmax"] = float(np.max(r))
            out["Rmin"] = float(np.min(r))
            out["Rptp"] = float(out["Rmax"] - out["Rmin"])

    return out


def build_summary_table(
    psi_df: pd.DataFrame,
    temps_df: pd.DataFrame,
    measure_id: int,
) -> pd.DataFrame:
    if psi_df is None or psi_df.empty:
        return pd.DataFrame()

    sub = psi_df[psi_df["Measure_ID"] == measure_id].copy()
    if sub.empty:
        return pd.DataFrame()

    rows = []
    for _, prow in sub.iterrows():
        n = str(prow.get("N") or "").strip().upper()
        if not n:
            continue
        tsub = temps_df[
            (temps_df["Measure_ID"] == measure_id)
            & (temps_df["N"].astype(str).str.strip().str.upper() == n)
        ]
        m = compute_curve_metrics(tsub)
        row = {"N": n, "Measure_ID": measure_id, "Status": prow.get("Status")}
        row.update(m)
        for col in ("Fmax", "Fmin", "Rmax", "Rmin", "Mono", "Turnover"):
            if col in prow.index and pd.notna(prow.get(col)):
                row.setdefault(f"{col}_psi", prow.get(col))
        rows.append(row)

    return pd.DataFrame(rows)


def apply_metrics_to_psidata(
    psi_df: pd.DataFrame,
    temps_df: pd.DataFrame,
    measure_id: int,
) -> pd.DataFrame:
    out = psi_df[psi_df["Measure_ID"] == measure_id].copy()
    if out.empty:
        return out

    for idx, prow in out.iterrows():
        n = str(prow.get("N") or "").strip().upper()
        tsub = temps_df[
            (temps_df["Measure_ID"] == measure_id)
            & (temps_df["N"].astype(str).str.strip().str.upper() == n)
        ]
        m = compute_curve_metrics(tsub)
        mapping = {
            "Fmax": "Fmax",
            "Fmin": "Fmin",
            "Rmax": "Rmax",
            "Rmin": "Rmin",
            "Mono": "Mono",
            "Turnover": "Turnover",
        }
        extra = {
            "Fptp": m.get("Fptp"),
            "Fptp/2": m.get("Fptp/2"),
            "Rptp": m.get("Rptp"),
            "Slope": m.get("Slope"),
            "Tmax": m.get("Tmax"),
            "Tmin": m.get("Tmin"),
        }
        for src, dst in mapping.items():
            if dst in out.columns and m.get(src) is not None:
                out.at[idx, dst] = m[src]
        for col, val in extra.items():
            if col in out.columns and val is not None:
                out.at[idx, col] = val

    return out
