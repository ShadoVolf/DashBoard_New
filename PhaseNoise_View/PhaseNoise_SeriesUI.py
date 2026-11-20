"""Выбор кривых ФШ: MeasureID+N, галочки, перерисовка."""

from __future__ import annotations

import logging
import dearpygui.dearpygui as dpg
import pandas as pd

from .PhaseNoise_Constants import (
    GRAPH_CONTAINER, TABLE_CONTAINER, STATUS_TEXT_TAG,
)
from .PhaseNoise_Graph import (
    render_graph, series_key, list_series_from_points,
)

log = logging.getLogger("PhaseNoise.SeriesUI")

_last_points: pd.DataFrame | None = None
_last_meas: pd.DataFrame | None = None
_last_norms: list = []
_last_operators: dict = {}
_series_selected: dict[str, bool] = {}


def store_load(points, meas, norms, operators, series):
    global _last_points, _last_meas, _last_norms, _last_operators, _series_selected
    _last_meas = meas
    _last_norms = norms or []
    _last_points = points
    _last_operators = operators or {}
    _series_selected = {series_key(mid, n): True for mid, n in series}


def selected_keys() -> set[str]:
    return {k for k, v in _series_selected.items() if v}


def redraw_graph():
    global _last_points, _last_meas, _last_norms, _last_operators
    if _last_points is None or _last_points.empty:
        if dpg.does_item_exist(GRAPH_CONTAINER):
            dpg.delete_item(GRAPH_CONTAINER, children_only=True)
            dpg.add_text("(нет точек для графика)", parent=GRAPH_CONTAINER,
                         color=(140, 140, 140))
        return
    render_graph(
        GRAPH_CONTAINER,
        _last_points,
        _last_meas if _last_meas is not None else pd.DataFrame(),
        _last_norms or [],
        _last_operators,
        group_mode=dpg.get_value("pn_group_mode") or "msk",
        height=260,
        selected_keys=selected_keys(),
    )


def on_series_check(sender, app_data, user_data):
    key = user_data
    if not key:
        return
    _series_selected[key] = bool(app_data)
    redraw_graph()
    n_sel = sum(1 for v in _series_selected.values() if v)
    n_all = len(_series_selected)
    if dpg.does_item_exist(STATUS_TEXT_TAG):
        dpg.set_value(
            STATUS_TEXT_TAG,
            f"На графике: {n_sel}/{n_all} кривых (MeasureID+N)",
        )


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
        dpg.add_button(label="Все", width=70,
                       callback=lambda: on_select_all(True))
        dpg.add_button(label="Снять все", width=90,
                       callback=lambda: on_select_all(False))
        dpg.add_text(f"  кривых: {len(series)}", color=(150, 200, 255))

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
        dpg.add_table_column(label="✓", width_fixed=True, init_width_or_weight=36)
        dpg.add_table_column(label="MeasureID", width_fixed=True,
                             init_width_or_weight=90)
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
