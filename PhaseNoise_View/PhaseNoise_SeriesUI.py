"""Выбор кривых ФШ: MeasureID+N, галочки, номер графика, колесо мыши."""

from __future__ import annotations

import logging
import dearpygui.dearpygui as dpg
import pandas as pd

from .PhaseNoise_Constants import (
    GRAPH_CONTAINER, TABLE_CONTAINER, STATUS_TEXT_TAG,
)
from .PhaseNoise_Graph import (
    render_graph, series_key, list_series_from_points,
    unique_numbers_from_points, PLOT_TAG,
)

log = logging.getLogger("PhaseNoise.SeriesUI")

_last_points: pd.DataFrame | None = None
_last_meas: pd.DataFrame | None = None
_last_norms: list = []
_last_operators: dict = {}
_series_selected: dict[str, bool] = {}

_numbers: list[str] = []
_current_number: str = ""

_wheel_registered = False
_suppress_number_cb = False


def store_load(points, meas, norms, operators, series, current_number: str | None = None):
    global _last_points, _last_meas, _last_norms, _last_operators
    global _series_selected, _numbers, _current_number

    _last_meas = meas
    _last_norms = norms or []
    _last_points = points
    _last_operators = operators or {}
    _series_selected = {series_key(mid, n): True for mid, n in series}

    nums = unique_numbers_from_points(points) if points is not None and not points.empty else []
    if not nums and meas is not None and not meas.empty and "N" in meas.columns:
        nums = sorted(
            {str(x).strip() for x in meas["N"].dropna().astype(str) if str(x).strip()},
            key=str.upper,
        )
    _numbers = nums

    if current_number and str(current_number).strip() in {n for n in _numbers}:
        _current_number = str(current_number).strip()
    elif current_number:
        cu = str(current_number).strip().upper()
        match = next((n for n in _numbers if n.upper() == cu), None)
        _current_number = match or (_numbers[0] if _numbers else "")
    else:
        _current_number = _numbers[0] if _numbers else ""


def get_numbers() -> list[str]:
    return list(_numbers)


def get_current_number() -> str:
    return _current_number


def selected_keys() -> set[str]:
    return {k for k, v in _series_selected.items() if v}


def set_current_number(number: str, update_combo: bool = True) -> None:
    global _current_number, _suppress_number_cb
    if not number:
        return
    cu = str(number).strip().upper()
    match = next((n for n in _numbers if n.upper() == cu), None)
    if match is None and _numbers:
        return
    _current_number = match or str(number).strip()

    if update_combo and dpg.does_item_exist("pn_number"):
        _suppress_number_cb = True
        try:
            dpg.set_value("pn_number", _current_number)
        finally:
            _suppress_number_cb = False

    redraw_graph()
    n_sel = sum(1 for v in _series_selected.values() if v)
    if dpg.does_item_exist(STATUS_TEXT_TAG):
        dpg.set_value(
            STATUS_TEXT_TAG,
            f"График: N {_current_number} - кривых в выборке "
            f"{n_sel}/{len(_series_selected)} - "
            f"номеров {len(_numbers)} (колесо мыши - смена номера)",
        )


def cycle_number(delta: int) -> None:
    if not _numbers:
        return
    try:
        idx = next(
            i for i, n in enumerate(_numbers)
            if n.upper() == _current_number.upper()
        )
    except StopIteration:
        idx = 0
    if delta > 0:
        idx = (idx - 1) % len(_numbers)
    elif delta < 0:
        idx = (idx + 1) % len(_numbers)
    else:
        return
    set_current_number(_numbers[idx], update_combo=True)


def is_number_cb_suppressed() -> bool:
    return _suppress_number_cb


def redraw_graph():
    global _last_points, _last_meas, _last_norms, _last_operators
    global _current_number
    if _last_points is None or _last_points.empty:
        if dpg.does_item_exist(GRAPH_CONTAINER):
            dpg.delete_item(GRAPH_CONTAINER, children_only=True)
            dpg.add_text("(нет точек для графика)", parent=GRAPH_CONTAINER,
                         color=(140, 140, 140))
        return
    gm = "msk"
    if dpg.does_item_exist("pn_group_mode"):
        gm = dpg.get_value("pn_group_mode") or "msk"
    render_graph(
        GRAPH_CONTAINER,
        _last_points,
        _last_meas if _last_meas is not None else pd.DataFrame(),
        _last_norms or [],
        _last_operators,
        group_mode=gm,
        height=320,
        selected_keys=selected_keys(),
        number_filter=_current_number or None,
    )


def on_series_check(sender, app_data, user_data):
    key = user_data
    if not key:
        return
    _series_selected[key] = bool(app_data)
    redraw_graph()


def on_select_all(select: bool):
    for k in list(_series_selected.keys()):
        _series_selected[k] = select
        tag = f"pn_chk_{k}"
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, select)
    redraw_graph()


def render_series_table(meas: pd.DataFrame, series: list[tuple[int, str]]):
    dpg.delete_item(TABLE_CONTAINER, children_only=True)
    if not series:
        dpg.add_text("Нет кривых (MeasureID+N)", parent=TABLE_CONTAINER,
                     color=(140, 140, 140))
        return

    with dpg.group(parent=TABLE_CONTAINER, horizontal=True):
        dpg.add_button(label="Все", width=70, callback=lambda: on_select_all(True))
        dpg.add_button(label="Снять все", width=90, callback=lambda: on_select_all(False))
        dpg.add_text(
            f"  кривых: {len(series)} - номер графика: {_current_number or '-'}",
            color=(150, 200, 255),
        )

    by_pair: dict[str, dict] = {}
    by_mid: dict[int, dict] = {}
    if meas is not None and not meas.empty:
        for _, row in meas.iterrows():
            mid = row.get("MeasureID")
            n = row.get("N")
            if mid is None or (isinstance(mid, float) and pd.isna(mid)):
                continue
            try:
                mid_i = int(mid)
            except (TypeError, ValueError):
                continue
            d = row.to_dict()
            by_pair[series_key(mid_i, n)] = d
            by_mid[mid_i] = d

    with dpg.table(parent=TABLE_CONTAINER, header_row=True, resizable=True,
                   policy=dpg.mvTable_SizingStretchProp,
                   scrollY=True, height=-1,
                   borders_innerH=True, borders_outerH=True):
        dpg.add_table_column(label="+", width_fixed=True, init_width_or_weight=36)
        dpg.add_table_column(label="MeasureID", width_fixed=True, init_width_or_weight=90)
        dpg.add_table_column(label="N")
        dpg.add_table_column(label="МСК")
        dpg.add_table_column(label="Spc")
        dpg.add_table_column(label="Дата")
        dpg.add_table_column(label="Время")

        for mid, n in series:
            key = series_key(mid, n)
            m = by_pair.get(key) or by_mid.get(mid) or {}
            checked = _series_selected.get(key, True)
            _series_selected[key] = checked
            with dpg.table_row():
                dpg.add_checkbox(
                    default_value=checked,
                    tag=f"pn_chk_{key}",
                    callback=on_series_check,
                    user_data=key,
                )
                dpg.add_text(str(mid))
                dpg.add_text(str(n or m.get("N") or ""))
                dpg.add_text(str(m.get("MSK") or ""))
                dpg.add_text(str(m.get("Spc") or ""))
                dpg.add_text(str(m.get("_Date_") or m.get("Date") or ""))
                dpg.add_text(str(m.get("_Time_") or m.get("Time") or ""))


def _on_plot_wheel(sender, app_data, user_data):
    if not dpg.does_item_exist(PLOT_TAG):
        return
    if not dpg.is_item_hovered(PLOT_TAG):
        return
    if not _numbers:
        return
    delta = int(app_data) if app_data is not None else 0
    cycle_number(delta)


def ensure_wheel_handler():
    global _wheel_registered
    if _wheel_registered:
        return
    try:
        with dpg.handler_registry(tag="pn_wheel_registry"):
            dpg.add_mouse_wheel_handler(callback=_on_plot_wheel)
        _wheel_registered = True
        log.info("PN mouse wheel handler registered")
    except Exception as e:
        try:
            dpg.add_mouse_wheel_handler(callback=_on_plot_wheel,
                                        parent="pn_wheel_registry")
            _wheel_registered = True
        except Exception as e2:
            log.warning(f"wheel handler: {e} / {e2}")
