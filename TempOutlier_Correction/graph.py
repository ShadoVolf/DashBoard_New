"""Графики ТЧХ: несколько кривых + corrected, увеличение, колесо мыши."""

from __future__ import annotations

from typing import Callable, Dict, List, Optional

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

# layout tags inside enlarge window
BIG_PLOT_AREA = "toc_big_plot_area"
BIG_EDIT_AREA = "toc_big_edit_area"
BIG_EDIT_TABLE = "toc_big_edit_table"
BIG_HINT = "toc_big_hint"
ONLY_CORR_CHECK_BIG = "toc_only_corr_check_big"


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
    only_corrected: bool = False,
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
        dpg.add_plot_axis(dpg.mvXAxis, label="T, C", tag=x_tag)
        with dpg.plot_axis(dpg.mvYAxis, label=param, tag=y_tag):
            all_x: List[float] = []
            all_y: List[float] = []
            i = 0
            for label, df in curves.items():
                # rejim "Только corrected": izmeritel'nye krivye (i linii,
                # i tochki) voobshche ne risuetsya, chtoby ne meshaali
                # ocenivat' skorrektirovannuyu krivuyu
                if only_corrected and not str(label).lower().startswith("corr"):
                    continue
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
    on_wheel: Optional[Callable] = None,
    on_prev: Optional[Callable] = None,
    on_next: Optional[Callable] = None,
    edit_builder: Optional[Callable] = None,
    plot_height: Optional[int] = None,
    only_corrected: bool = False,
    on_only_corrected: Optional[Callable] = None,
) -> None:
    """
    Bol'shoe okno: grafik + tablitsa pravok operatora snizu.
    Koleso myshi rabotaet, kogda kursor nad etim oknom.
    """
    try:
        sw = dpg.get_viewport_client_width() or dpg.get_viewport_width() or 1280
        sh = dpg.get_viewport_client_height() or dpg.get_viewport_height() or 800
    except Exception:
        sw, sh = 1280, 800

    w = max(900, int(sw * 0.88))
    h = max(640, int(sh * 0.88))
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)

    # save callbacks for live refresh
    if dpg.does_item_exist(BIG_WIN_TAG):
        try:
            dpg.delete_item(BIG_WIN_TAG)
        except Exception:
            pass

    # plot takes ~55% height, edit table the rest
    plot_h = plot_height or max(280, int(h * 0.52))
    edit_h = max(180, h - plot_h - 90)

    with dpg.window(
        label=f"ТЧХ - N {number} / {param}",
        tag=BIG_WIN_TAG,
        width=w,
        height=h,
        pos=(x, y),
        modal=False,
        no_collapse=True,
    ):
        with dpg.group(horizontal=True):
            dpg.add_text(
                "Колесо мыши - смена номера. Желтая - corrected. "
                "Правки в таблице сразу на кривой.",
                color=(150, 200, 255),
            )
            dpg.add_spacer(width=20)
            dpg.add_checkbox(
                label="Только corrected",
                tag=ONLY_CORR_CHECK_BIG,
                default_value=only_corrected,
                callback=on_only_corrected,
            )
            if on_prev:
                dpg.add_button(label="< N", callback=lambda: on_prev(), width=50)
            if on_next:
                dpg.add_button(label="N >", callback=lambda: on_next(), width=50)
        dpg.add_text(f"Номер: {number}   параметр: {param}", tag=BIG_HINT)

        with dpg.child_window(
            tag=BIG_PLOT_AREA, height=plot_h, border=False
        ):
            pass

        dpg.add_separator()
        dpg.add_text("Скорректированные точки (правка оператора)")
        with dpg.child_window(
            tag=BIG_EDIT_AREA, height=edit_h, border=True
        ):
            if edit_builder is not None:
                try:
                    edit_builder(BIG_EDIT_AREA)
                except Exception as e:
                    dpg.add_text(f"Ошибка таблицы: {e}", parent=BIG_EDIT_AREA)
            else:
                dpg.add_text("Нет данных", parent=BIG_EDIT_AREA)

    # alias BIG_CONTAINER for render
    # render into BIG_PLOT_AREA
    render_curves(
        BIG_PLOT_AREA,
        curves,
        param=param,
        height=plot_h - 8,
        plot_tag=PLOT_TAG_BIG,
        x_tag=X_AXIS_TAG_BIG,
        y_tag=Y_AXIS_TAG_BIG,
        title=f"N {number}",
        only_corrected=only_corrected,
    )

    # wheel: only when mouse is over big window
    def _wheel_if_focused(sender=None, app_data=None, user_data=None):
        if on_wheel is None:
            return
        if not dpg.does_item_exist(BIG_WIN_TAG):
            return
        try:
            # focus check: hovered item belongs to big window tree
            hovered = dpg.is_item_hovered(BIG_WIN_TAG)
            if not hovered:
                # also check children plot
                for tag in (BIG_PLOT_AREA, PLOT_TAG_BIG, BIG_EDIT_AREA, BIG_WIN_TAG):
                    if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                        hovered = True
                        break
            if not hovered:
                return
            on_wheel(sender, app_data, "from_big")
        except Exception:
            try:
                on_wheel(sender, app_data, "from_big")
            except Exception:
                pass

    handler_tag = "toc_big_wheel_handler"
    if dpg.does_item_exist(handler_tag):
        try:
            dpg.delete_item(handler_tag)
        except Exception:
            pass
    with dpg.handler_registry(tag=handler_tag):
        dpg.add_mouse_wheel_handler(callback=_wheel_if_focused)

    # store for external refresh
    try:
        dpg.set_item_user_data(BIG_WIN_TAG, {
            "param": param,
            "number": number,
            "on_wheel": on_wheel,
            "edit_builder": edit_builder,
        })
    except Exception:
        pass


def refresh_enlarged_graph(
    curves: Dict[str, pd.DataFrame],
    param: str,
    number: str,
    edit_builder: Optional[Callable] = None,
    only_corrected: bool = False,
) -> None:
    """Obnovit uvelichennyj grafik i tablitsu bez pereotkrytiya okna."""
    if not dpg.does_item_exist(BIG_WIN_TAG):
        return
    try:
        dpg.configure_item(BIG_WIN_TAG, label=f"ТЧХ - N {number} / {param}")
    except Exception:
        pass
    if dpg.does_item_exist(BIG_HINT):
        try:
            dpg.set_value(BIG_HINT, f"Номер: {number}   параметр: {param}")
        except Exception:
            pass
    try:
        if dpg.does_item_exist(ONLY_CORR_CHECK_BIG):
            dpg.set_value(ONLY_CORR_CHECK_BIG, bool(only_corrected))
    except Exception:
        pass

    plot_h = 320
    try:
        h = dpg.get_item_height(BIG_WIN_TAG) or 640
        plot_h = max(260, int(h * 0.52))
    except Exception:
        pass

    if dpg.does_item_exist(BIG_PLOT_AREA):
        render_curves(
            BIG_PLOT_AREA,
            curves,
            param=param,
            height=plot_h - 8,
            plot_tag=PLOT_TAG_BIG,
            x_tag=X_AXIS_TAG_BIG,
            y_tag=Y_AXIS_TAG_BIG,
            title=f"N {number}",
            only_corrected=only_corrected,
        )

    if dpg.does_item_exist(BIG_EDIT_AREA):
        try:
            dpg.delete_item(BIG_EDIT_AREA, children_only=True)
        except Exception:
            pass
        if edit_builder is not None:
            try:
                edit_builder(BIG_EDIT_AREA)
            except Exception as e:
                dpg.add_text(f"Ошибка таблицы: {e}", parent=BIG_EDIT_AREA)
