"""Статусы, сводные таблицы, сбор точек норм, статистика по отстройкам."""

import math
import pandas as pd
from .PhaseNoise_Constants import (
    OFFSET_TO_FIELD, NORM_DEFS, STATUS_OK, STATUS_FAIL,
)


def data_value_at_offset(meas_row: dict, offset: int) -> float | None:
    """Аналог ветвлений if ShOT==1 -> Shum1, ... в PhazeNoise.cpp."""
    field = OFFSET_TO_FIELD.get(offset)
    if not field:
        return None
    v = meas_row.get(field)
    if v is None or pd.isna(v):
        return None
    return float(v)


def calc_status(data: float | None, vmin: float | None, vmax: float | None) -> str:
    """
    Аналог проверки в C++:
        if ShMax!='no' and fabs(data) > ShMax -> Брак
        if ShMin!='no' and fabs(data) < ShMin -> Брак
    """
    if data is None:
        return "-"
    a = abs(data)
    if vmax is not None and a > vmax:
        return STATUS_FAIL
    if vmin is not None and a < vmin:
        return STATUS_FAIL
    return STATUS_OK


def collect_norm_points(meas_row: dict, norms: list[dict]) -> list[dict]:
    """
    Возвращает список точек для наложения на график:
        { "num", "offset", "value", "status", "min", "max", "marker_text" }
    Аналог Series3..Series6 (addXY + подписи SubTitle).
    """
    pts = []
    for nm in norms:
        v = data_value_at_offset(meas_row, nm["offset"])
        st = calc_status(v, nm["min"], nm["max"])
        marker = (
            f"{nm['num']} {_fmt_hz(nm['offset'])}   "
            f"{'—' if v is None else f'{v:0.2f}'}  {st}"
        )
        pts.append({
            "num": nm["num"],
            "offset": nm["offset"],
            "value": v,
            "status": st,
            "min": nm["min"],
            "max": nm["max"],
            "marker_text": marker,
        })
    return pts


def build_summary_table(measurements: pd.DataFrame, norms: list[dict]) -> pd.DataFrame:
    """Сводная таблица по отстройкам для UI/Excel/PDF."""
    rows = []
    for _, m in measurements.iterrows():
        row = {
            "MSK": m.get("MSK"),
            "N": m.get("N"),
            "Spc": m.get("Spc"),
            "Date": m.get("_Date_"),
            "Time": m.get("_Time_"),
            "Operator": m.get("Operator"),
            "MeasureID": m.get("MeasureID"),
        }
        for nm in norms:
            off = nm["offset"]
            v = data_value_at_offset(m.to_dict(), off)
            row[f"{_fmt_hz(off)}"] = v
            row[f"Статус {nm['num']}"] = calc_status(v, nm["min"], nm["max"])
        rows.append(row)
    return pd.DataFrame(rows)


def build_offset_stats(measurements: pd.DataFrame, norms: list[dict]) -> list[dict]:
    """
    Статистика по каждой активной отстройке для загруженной выборки.

    Возвращает список dict:
        num, offset, offset_label, n, mean, std, min, max, median,
        n_good, n_fail, pct_good, cpk, vmin, vmax

    Значения считаются по abs(value), как в calc_status.
    Cpk: при наличии обеих границ — min((USL-μ)/(3σ), (μ-LSL)/(3σ));
         при одной границе — соответствующая сторона; иначе None.
    """
    if measurements is None or measurements.empty or not norms:
        return []

    result = []
    for nm in norms:
        vals_raw = []
        n_good = 0
        n_fail = 0
        for _, m in measurements.iterrows():
            v = data_value_at_offset(m.to_dict(), nm["offset"])
            if v is None:
                continue
            a = abs(v)
            vals_raw.append(a)
            st = calc_status(v, nm["min"], nm["max"])
            if st == STATUS_OK:
                n_good += 1
            elif st == STATUS_FAIL:
                n_fail += 1

        n = len(vals_raw)
        if n == 0:
            result.append({
                "num": nm["num"],
                "offset": nm["offset"],
                "offset_label": _fmt_hz(nm["offset"]),
                "n": 0,
                "mean": None, "std": None, "min": None, "max": None,
                "median": None,
                "n_good": 0, "n_fail": 0, "pct_good": None,
                "cpk": None,
                "vmin": nm["min"], "vmax": nm["max"],
            })
            continue

        s = pd.Series(vals_raw, dtype=float)
        mean = float(s.mean())
        std = float(s.std(ddof=1)) if n >= 2 else 0.0
        vmin = nm["min"]
        vmax = nm["max"]

        cpk = _calc_cpk(mean, std, vmin, vmax)

        result.append({
            "num": nm["num"],
            "offset": nm["offset"],
            "offset_label": _fmt_hz(nm["offset"]),
            "n": n,
            "mean": mean,
            "std": std,
            "min": float(s.min()),
            "max": float(s.max()),
            "median": float(s.median()),
            "n_good": n_good,
            "n_fail": n_fail,
            "pct_good": 100.0 * n_good / n if n else None,
            "cpk": cpk,
            "vmin": vmin,
            "vmax": vmax,
        })
    return result


def overall_yield(measurements: pd.DataFrame, norms: list[dict]) -> dict:
    """
    Общий выход годных: измерение годно, только если все активные нормы OK.
    Возвращает {n_total, n_good, n_fail, pct_good}.
    """
    if measurements is None or measurements.empty:
        return {"n_total": 0, "n_good": 0, "n_fail": 0, "pct_good": None}
    n_total = 0
    n_good = 0
    for _, m in measurements.iterrows():
        pts = collect_norm_points(m.to_dict(), norms)
        if not pts:
            continue
        n_total += 1
        if all(p["status"] == STATUS_OK for p in pts):
            n_good += 1
    n_fail = n_total - n_good
    return {
        "n_total": n_total,
        "n_good": n_good,
        "n_fail": n_fail,
        "pct_good": 100.0 * n_good / n_total if n_total else None,
    }


def _calc_cpk(mean: float, std: float,
              lsl: float | None, usl: float | None) -> float | None:
    """Cpk по abs-значениям. None если σ≈0 или нет границ."""
    if std is None or std < 1e-12:
        return None
    parts = []
    if usl is not None:
        parts.append((usl - mean) / (3.0 * std))
    if lsl is not None:
        parts.append((mean - lsl) / (3.0 * std))
    if not parts:
        return None
    return float(min(parts))


def _fmt_hz(hz: int) -> str:
    if hz >= 1_000_000:
        return f"{hz // 1_000_000}МГц"
    if hz >= 1000:
        return f"{hz // 1000}кГц"
    return f"{hz}Гц"


def _fmt_num(v, digits: int = 2) -> str:
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "—"
    return f"{v:.{digits}f}"
