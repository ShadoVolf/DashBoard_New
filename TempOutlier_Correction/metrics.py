"""
Пересчёт сводных метрик резонатора по температурной кривой.

Fmax, Fmin, Fptp, Fptp/2, Rmax, Rmin, Rptp,
Mono, Slope, Tmax, Tmin, Turnover.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

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

    t_raw = pd.to_numeric(temp_df["Temp"], errors="coerce").values.astype(float)

    if f_col in temp_df.columns:
        f_raw = pd.to_numeric(temp_df[f_col], errors="coerce").values.astype(float)
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
                elif f.size >= 2:
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
        r_raw = pd.to_numeric(temp_df[r_col], errors="coerce").values.astype(float)
        t, r = _clean_series(t_raw, r_raw)
        if r.size >= 1:
            out["Rmax"] = float(np.max(r))
            out["Rmin"] = float(np.min(r))
            out["Rptp"] = float(out["Rmax"] - out["Rmin"])

    return out


def _temps_for_number(
    temps_df: pd.DataFrame,
    number: str,
    measure_id: Optional[int] = None,
) -> pd.DataFrame:
    if temps_df is None or temps_df.empty:
        return pd.DataFrame()
    n = str(number).strip().upper()
    mask = temps_df["N"].astype(str).str.strip().str.upper() == n
    sub = temps_df[mask]
    if measure_id is not None and "Measure_ID" in temps_df.columns:
        by_mid = sub[sub["Measure_ID"] == measure_id]
        if not by_mid.empty:
            return by_mid
    return sub


def build_summary_table(
    psi_df: pd.DataFrame,
    temps_df: pd.DataFrame,
    measure_id: int,
) -> pd.DataFrame:
    """
    Stroim svodnuyu po VSEM nomeram iz temps (corrected) i/ili psi.
    Esli psi po measure_id pustoj - berem nomera iz temps.
    """
    rows = []
    numbers = []
    psi_sub = pd.DataFrame()
    if psi_df is not None and not psi_df.empty and "Measure_ID" in psi_df.columns:
        psi_sub = psi_df[psi_df["Measure_ID"] == measure_id].copy()
        if not psi_sub.empty and "N" in psi_sub.columns:
            numbers = (
                psi_sub["N"].astype(str).str.strip().str.upper().unique().tolist()
            )
    if not numbers and temps_df is not None and not temps_df.empty and "N" in temps_df.columns:
        numbers = (
            temps_df["N"].astype(str).str.strip().str.upper().unique().tolist()
        )
    numbers = sorted({n for n in numbers if n and n != "NAN"})

    psi_by_n = {}
    if not psi_sub.empty and "N" in psi_sub.columns:
        for _, prow in psi_sub.iterrows():
            nn = str(prow.get("N") or "").strip().upper()
            if nn:
                psi_by_n[nn] = prow

    for n in numbers:
        tsub = _temps_for_number(temps_df, n, measure_id)
        m = compute_curve_metrics(tsub)
        prow = psi_by_n.get(n)
        status = prow.get("Status") if prow is not None else None
        row = {"N": n, "Measure_ID": measure_id, "Status": status}
        row.update(m)
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
        tsub = _temps_for_number(temps_df, n, measure_id)
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
