"""Хелперы ФШ: нормы, сводная таблица, статистика."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from .PhaseNoise_Constants import STATUS_FAIL, STATUS_OK, STATUS_NA


def collect_norm_points(meas_row: dict, norms: list[dict]) -> list[dict]:
    """Точки норм для одной строки измерения."""
    out = []
    for nm in norms:
        num = nm["num"]
        field = f"PN{num}" if num > 1 else "PN"
        # в phaze_noise колонки могут быть PN / PN2 / ...
        raw = meas_row.get(field)
        if raw is None or (isinstance(raw, float) and pd.isna(raw)):
            # запасные имена
            raw = meas_row.get(f"ФазовыеШумы{num}") or meas_row.get(f"PN_{num}")
        try:
            val = float(raw) if raw is not None and not (isinstance(raw, float) and pd.isna(raw)) else None
        except (TypeError, ValueError):
            val = None

        status = STATUS_NA
        if val is not None:
            vmin, vmax = nm.get("min"), nm.get("max")
            ok = True
            if vmin is not None and val < vmin:
                ok = False
            if vmax is not None and val > vmax:
                ok = False
            status = STATUS_OK if ok else STATUS_FAIL

        out.append({
            "num": num,
            "offset": nm["offset"],
            "value": val,
            "min": nm.get("min"),
            "max": nm.get("max"),
            "status": status,
            "marker_text": f"N{num} {nm['offset']}Hz",
        })
    return out


def build_summary_table(meas: pd.DataFrame, norms: list[dict]) -> pd.DataFrame:
    rows = []
    for _, m in meas.iterrows():
        d = m.to_dict()
        pts = collect_norm_points(d, norms)
        row = {
            "ID": d.get("ID"),
            "MeasureID": d.get("MeasureID"),
            "MSK": d.get("MSK"),
            "N": d.get("N"),
            "Spc": d.get("Spc"),
            "Date": d.get("_Date_") or d.get("Date"),
            "Time": d.get("_Time_") or d.get("Time"),
        }
        for p in pts:
            row[f"PN{p['num']}"] = p["value"]
            row[f"St{p['num']}"] = p["status"]
        rows.append(row)
    return pd.DataFrame(rows) if rows else pd.DataFrame()


def overall_yield(measurements: pd.DataFrame, norms: list[dict]) -> dict:
    if measurements is None or measurements.empty:
        return {"n_total": 0, "n_good": 0, "n_fail": 0, "pct_good": None}
    n_total = len(measurements)
    n_good = 0
    for _, m in measurements.iterrows():
        pts = collect_norm_points(m.to_dict(), norms)
        if pts and all(p["status"] != STATUS_FAIL for p in pts):
            if any(p["status"] == STATUS_OK for p in pts):
                n_good += 1
            elif all(p["status"] == STATUS_NA for p in pts):
                pass
            else:
                n_good += 1
        elif not pts:
            n_good += 1
    n_fail = n_total - n_good
    pct = 100.0 * n_good / n_total if n_total else None
    return {"n_total": n_total, "n_good": n_good, "n_fail": n_fail, "pct_good": pct}


def build_offset_stats(measurements: pd.DataFrame, norms: list[dict]) -> list[dict]:
    """Статистика по каждой активной отстройке."""
    out = []
    if measurements is None or measurements.empty or not norms:
        return out
    for nm in norms:
        vals = []
        n_ok = 0
        for _, m in measurements.iterrows():
            pts = {p["num"]: p for p in collect_norm_points(m.to_dict(), norms)}
            p = pts.get(nm["num"])
            if not p or p["value"] is None:
                continue
            vals.append(float(p["value"]))
            if p["status"] == STATUS_OK:
                n_ok += 1
        if not vals:
            continue
        s = pd.Series(vals, dtype=float)
        mean = float(s.mean())
        std = float(s.std(ddof=1)) if len(s) > 1 else 0.0
        cpk = _cpk(mean, std, nm.get("min"), nm.get("max"))
        pct_good = 100.0 * n_ok / len(vals) if vals else None
        out.append({
            "offset_label": f"{nm['offset']} Hz",
            "n": len(vals),
            "mean": mean,
            "std": std,
            "min": float(s.min()),
            "max": float(s.max()),
            "median": float(s.median()),
            "pct_good": pct_good,
            "cpk": cpk,
        })
    return out


def _cpk(mean: float, std: float, lsl, usl) -> float | None:
    """Cpk. None если std~0 или нет границ."""
    if std is None or std <= 1e-12 or math.isnan(std):
        return None
    parts = []
    if usl is not None:
        parts.append((float(usl) - mean) / (3.0 * std))
    if lsl is not None:
        parts.append((mean - float(lsl)) / (3.0 * std))
    if not parts:
        return None
    return float(min(parts))


def _fmt_num(v) -> str:
    if v is None or (isinstance(v, float) and (math.isnan(v) or math.isinf(v))):
        return "-"
    try:
        return f"{float(v):.3g}"
    except (TypeError, ValueError):
        return "-"
