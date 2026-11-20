"""Построение графика ФШ нативным dpg.plot.

X = log10(отстройка, Гц), по умолчанию 1 Гц … 100 кГц.
Y = PN, дБ/Гц.
Кривая = пара (MeasureID, N) из phaze_noise_data.
"""

from __future__ import annotations

import math
from typing import Any

import dearpygui.dearpygui as dpg
import pandas as pd

from .PhaseNoise_Constants import STATUS_FAIL, NORM_COLORS_RGBA
from .PhaseNoise_Helpers import collect_norm_points

PLOT_TAG = "pn_dpg_plot"
X_AXIS_TAG = "pn_dpg_x"
Y_AXIS_TAG = "pn_dpg_y"

DEFAULT_X_MIN_HZ = 1.0
DEFAULT_X_MAX_HZ = 100_000.0

SERIES_COLORS = [
    (255, 85, 85, 255),
    (85, 170, 255, 255),
    (85, 255, 170, 255),
    (255, 200, 85, 255),
    (200, 85, 255, 255),
    (255, 85, 200, 255),
    (170, 255, 85, 255),
    (85, 255, 255, 255),
    (255, 140, 80, 255),
    (140, 140, 255, 255),
]


def series_key(mid, n) -> str:
    try:
        mid_i = int(mid)
    except (TypeError, ValueError):
        mid_i = 0
    return f"{mid_i}|{str(n or '').strip().upper()}"


def parse_series_key(key: str) -> tuple[int, str]:
    mid_s, _, n = str(key).partition("|")
    try:
        mid = int(mid_s)
    except ValueError:
        mid = 0
    return mid, n


def _safe_log10(v: float) -> float | None:
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    if fv <= 0 or math.isnan(fv) or math.isinf(fv):
        return None
    return math.log10(fv)


def _meas_meta(measurements: pd.DataFrame) -> dict:
    meta: dict = {}
    if measurements is None or measurements.empty:
        return meta
    for _, row in measurements.iterrows():
        mid = row.get("MeasureID")
        n = row.get("N")
        if mid is None or (isinstance(mid, float) and pd.isna(mid)):
            continue
        k = series_key(mid, n)
        meta[k] = row.to_dict()
        try:
            meta.setdefault(int(mid), row.to_dict())
        except (TypeError, ValueError):
            pass
    return meta


def list_series_from_points(points: pd.DataFrame) -> list[tuple[int, str]]:
    if points is None or points.empty:
        return []
    df = points.dropna(subset=["MeasureID"]).copy()
    if "N" not in df.columns:
        df["N"] = ""
    df["N"] = df["N"].fillna("").astype(str).str.strip()
    pairs = (
        df.groupby(["MeasureID", "N"], dropna=False)
        .size()
        .reset_index()[["MeasureID", "N"]]
    )
    out = []
    for _, r in pairs.iterrows():
        try:
            mid = int(r["MeasureID"])
        except (TypeError, ValueError):
            continue
        out.append((mid, str(r["N"])))
    out.sort(key=lambda x: (x[1], x[0]))
    return out


def unique_numbers_from_points(points: pd.DataFrame) -> list[str]:
    if points is None or points.empty or "N" not in points.columns:
        return []
    nums = (
        points["N"].dropna().astype(str).str.strip()
        .replace("", pd.NA).dropna().unique().tolist()
    )
    return sorted(set(nums), key=lambda s: s.upper())


def render_graph(
    parent: int | str,
    graph_df: pd.DataFrame,
    measurements: pd.DataFrame,
    norms: list[dict],
    operator_names: dict[int, str] | None = None,
    group_mode: str = "msk",
    height: int = 320,
    selected_keys: set[str] | None = None,
    number_filter: str | None = None,
    x_min_hz: float = DEFAULT_X_MIN_HZ,
    x_max_hz: float = DEFAULT_X_MAX_HZ,
) -> None:
    operator_names = operator_names or {}
    meta = _meas_meta(measurements)

    if dpg.does_item_exist(parent):
        dpg.delete_item(parent, children_only=True)

    with dpg.plot(
        label="PN (отстройка)",
        parent=parent,
        height=height,
        width=-1,
        tag=PLOT_TAG,
        anti_aliased=True,
        no_menus=False,
    ):
        dpg.add_plot_legend(location=dpg.mvPlot_Location_NorthEast)
        dpg.add_plot_axis(
            dpg.mvXAxis,
            label="Отстройка, log10(Гц)",
            tag=X_AXIS_TAG,
        )
        with dpg.plot_axis(dpg.mvYAxis, label="PN, дБ/Гц", tag=Y_AXIS_TAG):
            if graph_df is None or graph_df.empty:
                _apply_x_limits(x_min_hz, x_max_hz)
                return

            pairs = list_series_from_points(graph_df)
            if number_filter:
                nf = str(number_filter).strip().upper()
                pairs = [
                    (mid, n) for mid, n in pairs
                    if str(n).strip().upper() == nf
                ]
            if selected_keys is not None:
                pairs = [
                    (mid, n) for mid, n in pairs
                    if series_key(mid, n) in selected_keys
                ]

            all_ys: list[float] = []
            for i, (mid, n) in enumerate(pairs):
                sub = graph_df[
                    (graph_df["MeasureID"] == mid)
                    & (graph_df["N"].astype(str).str.strip().str.upper()
                       == str(n).strip().upper())
                ].sort_values("Freq")

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
                all_ys.extend(ys)

                m = meta.get(series_key(mid, n)) or meta.get(mid) or {}
                msk = m.get("MSK", "")
                label = f"№ {n or m.get('N', '')} / ID {mid}"
                if msk:
                    label = f"МСК {msk} · {label}"

                color = SERIES_COLORS[i % len(SERIES_COLORS)]
                dpg.add_line_series(xs, ys, label=label, parent=Y_AXIS_TAG)
                try:
                    dpg.bind_item_theme(dpg.last_item(), _line_theme(color))
                except Exception:
                    pass
                dpg.add_scatter_series(xs, ys, label=None, parent=Y_AXIS_TAG)

                pts = collect_norm_points(m, norms) if m else []
                for np_ in pts:
                    if np_["value"] is None:
                        continue
                    lx = _safe_log10(np_["offset"])
                    if lx is None:
                        continue
                    color_n = NORM_COLORS_RGBA[
                        (np_["num"] - 1) % len(NORM_COLORS_RGBA)
                    ]
                    tag = f"pn_norm_{mid}_{n}_{np_['num']}"
                    if dpg.does_item_exist(tag):
                        dpg.delete_item(tag)
                    dpg.add_scatter_series(
                        [lx], [float(np_["value"])],
                        label=np_["marker_text"] if len(pairs) == 1 else None,
                        parent=Y_AXIS_TAG,
                        tag=tag,
                    )
                    try:
                        dpg.bind_item_theme(tag, _scatter_theme(color_n))
                    except Exception:
                        pass
                    all_ys.append(float(np_["value"]))

            _apply_x_limits(x_min_hz, x_max_hz)
            if all_ys:
                ymin = min(all_ys)
                ymax = max(all_ys)
                if math.isfinite(ymin) and math.isfinite(ymax):
                    pad = max(2.0, (ymax - ymin) * 0.08) if ymax > ymin else 5.0
                    try:
                        dpg.set_axis_limits(Y_AXIS_TAG, ymin - pad, ymax + pad)
                    except Exception:
                        pass


def _apply_x_limits(x_min_hz: float, x_max_hz: float) -> None:
    lo = _safe_log10(x_min_hz)
    hi = _safe_log10(x_max_hz)
    if lo is None or hi is None or not dpg.does_item_exist(X_AXIS_TAG):
        return
    try:
        dpg.set_axis_limits(X_AXIS_TAG, lo, hi)
    except Exception:
        pass


_theme_cache: dict[tuple, Any] = {}


def _line_theme(color: tuple[int, int, int, int]):
    key = ("line", color)
    if key in _theme_cache:
        return _theme_cache[key]
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvLineSeries):
            dpg.add_theme_color(
                dpg.mvPlotCol_Line, color, category=dpg.mvThemeCat_Plots
            )
    _theme_cache[key] = th
    return th


def _scatter_theme(color: tuple[int, int, int, int]):
    key = ("sc", color)
    if key in _theme_cache:
        return _theme_cache[key]
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvScatterSeries):
            dpg.add_theme_color(
                dpg.mvPlotCol_MarkerFill, color, category=dpg.mvThemeCat_Plots
            )
            dpg.add_theme_color(
                dpg.mvPlotCol_MarkerOutline, color, category=dpg.mvThemeCat_Plots
            )
    _theme_cache[key] = th
    return th


def build_graph(
    graph_df,
    measurements,
    norms: list[dict],
    operator_names: dict[int, str] | None = None,
    group_mode: str = "msk",
    selected_keys: set[str] | None = None,
    number_filter: str | None = None,
):
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
        for spine in ax.spines.values():
            spine.set_color("#555555")
        ax.grid(True, which="both", color=grid_c, alpha=0.6, linewidth=0.5)

    operator_names = operator_names or {}
    meta = _meas_meta(measurements)
    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    _apply_dark(ax, fig)

    if graph_df is not None and not graph_df.empty:
        pairs = list_series_from_points(graph_df)
        if number_filter:
            nf = str(number_filter).strip().upper()
            pairs = [(m, n) for m, n in pairs if str(n).strip().upper() == nf]
        if selected_keys is not None:
            pairs = [
                (mid, n) for mid, n in pairs
                if series_key(mid, n) in selected_keys
            ]
        colors = [
            "#ff5555", "#55aaff", "#55ffaa", "#ffc855", "#c855ff",
            "#ff55c8", "#aaff55", "#55ffff",
        ]
        for i, (mid, n) in enumerate(pairs):
            sub = graph_df[
                (graph_df["MeasureID"] == mid)
                & (graph_df["N"].astype(str).str.strip().str.upper()
                   == str(n).strip().upper())
            ].sort_values("Freq")
            if sub.empty:
                continue
            c = colors[i % len(colors)]
            ax.plot(sub["Freq"], sub["PN"], color=c, linewidth=LINE_W,
                    alpha=0.9, label=f"№ {n} / ID {mid}", zorder=3)
            ax.scatter(sub["Freq"], sub["PN"], s=MARKER_S, color=c,
                       linewidths=0, zorder=4)
            m = meta.get(series_key(mid, n)) or meta.get(mid) or {}
            for np_ in collect_norm_points(m, norms):
                if np_["value"] is None:
                    continue
                color = NORM_COLORS[(np_["num"] - 1) % len(NORM_COLORS)]
                marker = "o" if np_["status"] != SF else "x"
                ax.scatter([np_["offset"]], [np_["value"]],
                           color=color, marker=marker, s=NORM_S, zorder=5)

    ax.set_xscale("log")
    ax.set_xlim(DEFAULT_X_MIN_HZ, DEFAULT_X_MAX_HZ)
    ax.set_xlabel("Отстройка, Гц", fontsize=8)
    ax.set_ylabel("PN, дБ/Гц", fontsize=8)
    if ax.get_legend_handles_labels()[0]:
        ax.legend(fontsize=7, loc="best",
                  facecolor="#2a2a2a", edgecolor="#555555",
                  labelcolor="#d0d0d0")
    fig.tight_layout(pad=0.4)
    return fig


def fig_to_png_bytes(fig) -> bytes:
    from io import BytesIO
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    return buf.read()
