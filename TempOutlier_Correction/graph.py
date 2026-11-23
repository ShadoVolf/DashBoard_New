"""Графики ТЧХ: несколько кривых + corrected, увеличение, колесо мыши."""

from __future__ import annotations

from typing import Dict, List

import dearpygui.dearpygui as dpg
import numpy as np
import pandas as pd

from .constants import (
    BIG_CONTAINER,
    BIG_WIN_TAG,
    COLOR_CORRECTED,
    PLOT_TAG,
    PLOT_TAG_BIG,
    SERIES_COLORS,
    X_AXIS_TAG,
    X_AXIS_TAG_BIG,
    Y_AXIS_TAG,
    Y_AXIS_TAG_BIG,
    OUTLIER_MARKER,
)

_theme_cache: dict = {}


def _line_theme(color: tuple):
    key = ("line", color)
    if key in _theme_cache:
        return _theme_cache[key]
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvLineSeries):
            dpg.add_theme_color(
                dpg.mvPlotCol_Line, color, category=dpg.mvThemeCat_Plots
            )
            try:
                dpg.add_theme_style(
                    dpg.mvPlotStyleVar_LineWeight,
                    1.8,
                    category=dpg.mvThemeCat_Plots,
                )
            except Exception:
                pass
    _theme_cache[key] = th
    return th


def _series_xy(df: pd.DataFrame, param: str):
    if (
        df is None
        or df.empty
        or "Temp" not in df.columns
        or param not in df.columns
    ):
        return [], []
    sub = df.sort_values("Temp")
    xs, ys = [], []
    for _, row in sub.iterrows():
        try:
            t = float(row["Temp"])
            v = float(row[param])
        except (TypeError, ValueError):
            continue
        if not np.isfinite(t) or not np.isfinite(v) or v == OUTLIER_MARKER:
            continue
        xs.append(t)
        ys.append(v)
    return xs, ys


def render_curves(
    parent: str | int,
    curves: Dict[str, pd.DataFrame],
    param: str = "F",
    height: int = 360,
    plot_tag: str = PLOT_TAG,
    x_tag: str = X_AXIS_TAG,
    y_tag: str = Y_AXIS_TAG,
    title: str = "",
) -> None:
    if dpg.does_item_exist(parent):
        try:
            dpg.delete_item(parent, children_only=True)
        except Exception:
            pass
    if dpg.does_item_exist(plot_tag):
        try:
            dpg.delete_item(plot_tag)
        except Exception:
            pass

    with dpg.plot(
        label=title or param,
        parent=parent,
        height=height,
        width=-1,
        tag=plot_tag,
        anti_aliased=True,
    ):
        dpg.add_plot_legend(location=dpg.mvPlot_Location_NorthEast)
        dpg.add_plot_axis(dpg.mvXAxis, label="T, °C", tag=x_tag)
        with dpg.plot_axis(dpg.mvYAxis, label=param, tag=y_tag):
            all_x: List[float] = []
            all_y: List[float] = []
            i = 0
            for label, df in curves.items():
                xs, ys = _series_xy(df, param)
                if not xs:
                    continue
                all_x.extend(xs)
                all_y.extend(ys)
                if str(label).lower().startswith("corr"):
                    color = COLOR_CORRECTED
                else:
                    color = SERIES_COLORS[i % len(SERIES_COLORS)]
                    i += 1
                series_tag = dpg.add_line_series(
                    xs, ys, label=str(label), parent=y_tag
                )
                try:
                    dpg.bind_item_theme(series_tag, _line_theme(color))
                except Exception:
                    pass
                dpg.add_scatter_series(xs, ys, label=None, parent=y_tag)

            if all_x:
                pad = max(1.0, (max(all_x) - min(all_x)) * 0.05)
                try:
                    dpg.set_axis_limits(
                        x_tag, min(all_x) - pad, max(all_x) + pad
                    )
                except Exception:
                    pass
            if all_y:
                pad = (
                    max(0.1, (max(all_y) - min(all_y)) * 0.08)
                    if max(all_y) != min(all_y)
                    else 1.0
                )
                try:
                    dpg.set_axis_limits(
                        y_tag, min(all_y) - pad, max(all_y) + pad
                    )
                except Exception:
                    pass


def open_enlarged_graph(
    curves: Dict[str, pd.DataFrame],
    param: str,
    number: str,
    on_wheel=None,
) -> None:
    try:
        sw = dpg.get_viewport_client_width() or dpg.get_viewport_width() or 1280
        sh = dpg.get_viewport_client_height() or dpg.get_viewport_height() or 800
    except Exception:
        sw, sh = 1280, 800

    w = max(720, int(sw * 0.75))
    h = max(520, int(sh * 0.75))
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)

    if dpg.does_item_exist(BIG_WIN_TAG):
        dpg.delete_item(BIG_WIN_TAG)

    with dpg.window(
        label=f"ТЧХ — N {number} / {param}",
        tag=BIG_WIN_TAG,
        width=w,
        height=h,
        pos=(x, y),
        modal=False,
        no_collapse=True,
    ):
        dpg.add_text(
            "Колесо мыши — смена номера резонатора.  "
            "Жёлтая кривая — скорректированная.",
            color=(150, 200, 255),
        )
        with dpg.child_window(tag=BIG_CONTAINER, height=-1, border=False):
            pass

    plot_h = max(420, h - 70)
    render_curves(
        BIG_CONTAINER,
        curves,
        param=param,
        height=plot_h,
        plot_tag=PLOT_TAG_BIG,
        x_tag=X_AXIS_TAG_BIG,
        y_tag=Y_AXIS_TAG_BIG,
        title=f"N {number}",
    )

    if on_wheel is not None:
        handler_tag = "toc_big_wheel_handler"
        if dpg.does_item_exist(handler_tag):
            try:
                dpg.delete_item(handler_tag)
            except Exception:
                pass
        with dpg.handler_registry(tag=handler_tag):
            dpg.add_mouse_wheel_handler(callback=on_wheel)
