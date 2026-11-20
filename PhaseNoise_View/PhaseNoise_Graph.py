"""Построение графика ФШ нативным dpg.plot (лог по X)."""

from __future__ import annotations

import math
from typing import Any

import dearpygui.dearpygui as dpg
import pandas as pd

from .PhaseNoise_Constants import (
    GRAPH_CONTAINER, STATUS_FAIL, NORM_COLORS_RGBA,
)
from .PhaseNoise_Helpers import collect_norm_points

PLOT_TAG = "pn_dpg_plot"
X_AXIS_TAG = "pn_dpg_x"
Y_AXIS_TAG = "pn_dpg_y"

# запас цветов линий серий
SERIES_COLORS = [
    (255, 85, 85, 255),
    (85, 170, 255, 255),
    (85, 255, 170, 255),
    (255, 200, 85, 255),
    (200, 85, 255, 255),
    (255, 85, 200, 255),
    (170, 255, 85, 255),
    (85, 255, 255, 255),
]


def _safe_log10(v: float) -> float | None:
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    if fv <= 0 or math.isnan(fv) or math.isinf(fv):
        return None
    return math.log10(fv)


def render_graph(
    parent: int | str,
    graph_df: pd.DataFrame,
    measurements: pd.DataFrame,
    norms: list[dict],
    operator_names: dict[int, str] | None = None,
    group_mode: str = "msk",
    height: int = 260,
) -> None:
    """
    Рисует стандартный dpg.plot в parent (обычно GRAPH_CONTAINER).
    X — log10(Freq), подписи оси остаются в Гц через кастомные тики не делаем
    (dpg не даёт полноценный log-axis без тиков вручную), поэтому
    ось X подписана как log10(Hz).
    """
    operator_names = operator_names or {}
    meta = measurements.set_index("ID").to_dict("index") if (
        measurements is not None and not measurements.empty and "ID" in measurements.columns
    ) else {}
    # fallback: индекс по MeasureID если нет ID
    if not meta and measurements is not None and not measurements.empty:
        if "MeasureID" in measurements.columns:
            meta = measurements.drop_duplicates("MeasureID").set_index("MeasureID").to_dict("index")

    # очистка контейнера
    if dpg.does_item_exist(parent):
        dpg.delete_item(parent, children_only=True)

    with dpg.plot(
        label="PN(Freq)",
        parent=parent,
        height=height,
        width=-1,
        tag=PLOT_TAG,
        anti_aliased=True,
        no_menus=False,
    ):
        dpg.add_plot_legend(location=dpg.mvPlot_Location_NorthEast)
        dpg.add_plot_axis(dpg.mvXAxis, label="log10(Freq, Hz)", tag=X_AXIS_TAG)
        with dpg.plot_axis(dpg.mvYAxis, label="dB/Hz", tag=Y_AXIS_TAG):
            if graph_df is None or graph_df.empty:
                return

            # серии по MeasureID
            ids = list(graph_df["MeasureID"].dropna().unique())
            for i, mid in enumerate(ids):
                sub = graph_df[graph_df["MeasureID"] == mid].sort_values("Freq")
                xs, ys = [], []
                for _, row in sub.iterrows():
                    lx = _safe_log10(row.get("Freq"))
                    try:
                        yv = float(row.get("PN"))
                    except (TypeError, ValueError):
                        continue
                    if lx is None or math.isnan(yv):
                        continue
                    xs.append(lx)
                    ys.append(yv)
                if not xs:
                    continue

                m = meta.get(mid, {}) or {}
                label = f"МСК {m.get('MSK', '')} / № {m.get('N', '')}".strip(" /№")
                if not label or label == "МСК  / №":
                    label = f"ID {mid}"
                color = SERIES_COLORS[i % len(SERIES_COLORS)]
                dpg.add_line_series(xs, ys, label=label, parent=Y_AXIS_TAG)
                # цвет линии
                try:
                    series_id = dpg.last_item()
                    dpg.bind_item_theme(series_id, _line_theme(color))
                except Exception:
                    pass
                dpg.add_scatter_series(xs, ys, label=None, parent=Y_AXIS_TAG)

            # точки норм (маркеры)
            # берём первую строку meta / measurements для отображения норм
            # если multi — накладываем нормы для каждого mid
            for i, mid in enumerate(ids):
                m = meta.get(mid, {}) or {}
                if not m and measurements is not None and not measurements.empty:
                    # попытка найти строку по MeasureID
                    rows = measurements[measurements.get("MeasureID", pd.Series(dtype=object)) == mid]
                    if not rows.empty:
                        m = rows.iloc[0].to_dict()
                pts = collect_norm_points(m, norms)
                for np_ in pts:
                    if np_["value"] is None:
                        continue
                    lx = _safe_log10(np_["offset"])
                    if lx is None:
                        continue
                    color = NORM_COLORS_RGBA[(np_["num"] - 1) % len(NORM_COLORS_RGBA)]
                    marker = "x" if np_["status"] == STATUS_FAIL else "o"
                    # scatter одной точки
                    tag = f"pn_norm_{mid}_{np_['num']}"
                    if dpg.does_item_exist(tag):
                        dpg.delete_item(tag)
                    dpg.add_scatter_series(
                        [lx], [float(np_["value"])],
                        label=np_["marker_text"] if len(ids) == 1 else None,
                        parent=Y_AXIS_TAG,
                        tag=tag,
                    )
                    try:
                        dpg.bind_item_theme(tag, _scatter_theme(color))
                    except Exception:
                        pass


_theme_cache: dict[tuple, Any] = {}


def _line_theme(color: tuple[int, int, int, int]):
    key = ("line", color)
    if key in _theme_cache:
        return _theme_cache[key]
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvLineSeries):
            dpg.add_theme_color(dpg.mvPlotCol_Line, color, category=dpg.mvThemeCat_Plots)
    _theme_cache[key] = th
    return th


def _scatter_theme(color: tuple[int, int, int, int]):
    key = ("sc", color)
    if key in _theme_cache:
        return _theme_cache[key]
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvScatterSeries):
            dpg.add_theme_color(dpg.mvPlotCol_MarkerFill, color, category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_MarkerOutline, color, category=dpg.mvThemeCat_Plots)
    _theme_cache[key] = th
    return th


# ---------------------------------------------------------------------------
# Совместимость со старым API (matplotlib) — для PDF/экспорта
# ---------------------------------------------------------------------------
def build_graph(
    graph_df,
    measurements,
    norms: list[dict],
    operator_names: dict[int, str] | None = None,
    group_mode: str = "msk",
):
    """
    Оставлено для PhaseNoise_Export (PDF).
    Использует matplotlib только при экспорте, UI больше не зависит от него.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from .PhaseNoise_Constants import NORM_COLORS, STATUS_FAIL as SF

    FIG_W, FIG_H = 5.2, 3.4
    LINE_W, MARKER_S, NORM_S = 0.8, 6, 28

    def _apply_dark(ax, fig):
        bg, fg, grid_c = "#1e1e1e", "#d0d0d0", "#404040"
        fig.patch.set_facecolor(bg)
        ax.set_facecolor(bg)
        ax.tick_params(colors=fg, labelsize=8)
        ax.xaxis.label.set_color(fg)
        ax.yaxis.label.set_color(fg)
        ax.title.set_color(fg)
        for spine in ax.spines.values():
            spine.set_color("#555555")
        ax.grid(True, which="both", color=grid_c, alpha=0.6, linewidth=0.5)

    def _draw_series(ax, sub, meas_row, norms_, operator_name, multi: bool):
        label = (
            f"МСК {meas_row.get('MSK', '')} / № {meas_row.get('N', '')}"
            if multi else None
        )
        if not sub.empty:
            ordered = sub.sort_values("Freq")
            ax.plot(ordered["Freq"], ordered["PN"],
                    color="#ff5555", linewidth=LINE_W, alpha=0.9,
                    label=label, zorder=3)
            ax.scatter(ordered["Freq"], ordered["PN"],
                       s=MARKER_S, color="#ff7777", linewidths=0, zorder=4)
        for np_ in collect_norm_points(meas_row, norms_):
            if np_["value"] is None:
                continue
            color = NORM_COLORS[(np_["num"] - 1) % len(NORM_COLORS)]
            marker = "o" if np_["status"] != SF else "x"
            ax.scatter([np_["offset"]], [np_["value"]],
                       color=color, marker=marker, s=NORM_S, zorder=5,
                       label=None if multi else np_["marker_text"])
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=7, loc="best",
                      facecolor="#2a2a2a", edgecolor="#555555",
                      labelcolor="#d0d0d0")

    operator_names = operator_names or {}
    meta = {}
    if measurements is not None and not measurements.empty:
        if "ID" in measurements.columns:
            meta = measurements.set_index("ID").to_dict("index")
        elif "MeasureID" in measurements.columns:
            meta = measurements.drop_duplicates("MeasureID").set_index(
                "MeasureID").to_dict("index")

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    _apply_dark(ax, fig)
    if graph_df is not None and not graph_df.empty:
        for mid, sub in graph_df.groupby("MeasureID"):
            m = meta.get(mid, {})
            _draw_series(ax, sub, m, norms, operator_names.get(mid, ""), multi=True)
    ax.set_xscale("log")
    ax.set_xlabel("Frequency, Hz", fontsize=8)
    ax.set_ylabel("dB/Hz", fontsize=8)
    fig.tight_layout(pad=0.4)
    return fig


def fig_to_png_bytes(fig) -> bytes:
    from io import BytesIO
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    return buf.read()
