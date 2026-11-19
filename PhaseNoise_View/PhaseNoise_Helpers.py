"""Статусы, сводные таблицы, сбор точек норм."""

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
            f">{nm['num']} {_fmt_hz(nm['offset'])}   "
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


def _fmt_hz(hz: int) -> str:
    if hz >= 1_000_000:
        return f"{hz // 1_000_000}МГц"
    if hz >= 1000:
        return f"{hz // 1000}кГц"
    return f"{hz}Гц"