"""Построение графика ФШ — тёмная тема, тонкие линии, размер под панель."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from .PhaseNoise_Constants import NORM_COLORS, STATUS_FAIL
from .PhaseNoise_Helpers import collect_norm_points

# размер под правую панель (~400px ширины)
FIG_W = 5.2
FIG_H = 3.4
LINE_W = 0.8
MARKER_S = 6
NORM_S = 28


def _apply_dark(ax, fig):
    bg = "#1e1e1e"
    fg = "#d0d0d0"
    grid_c = "#404040"
    fig.patch.set_facecolor(bg)
    ax.set_facecolor(bg)
    ax.tick_params(colors=fg, labelsize=8)
    ax.xaxis.label.set_color(fg)
    ax.yaxis.label.set_color(fg)
    ax.title.set_color(fg)
    for spine in ax.spines.values():
        spine.set_color("#555555")
    ax.grid(True, which="both", color=grid_c, alpha=0.6, linewidth=0.5)


def build_graph(
    graph_df,
    measurements,
    norms: list[dict],
    operator_names: dict[int, str] | None = None,
    group_mode: str = "msk",
) -> plt.Figure:
    operator_names = operator_names or {}
    meta = measurements.set_index("ID").to_dict("index") if not measurements.empty else {}

    if group_mode == "resonator_multi" and not graph_df.empty:
        ids = list(graph_df["MeasureID"].dropna().unique())
        n = max(1, len(ids))
        fig, axes = plt.subplots(
            nrows=n, ncols=1,
            figsize=(FIG_W, max(2.2, 1.8 * n)),
            sharex=True,
        )
        if n == 1:
            axes = [axes]
        for ax, mid in zip(axes, ids):
            _apply_dark(ax, fig)
            _draw_one(ax, graph_df[graph_df["MeasureID"] == mid],
                      meta.get(mid, {}), norms, operator_names.get(mid, ""))
        axes[-1].set_xlabel("Frequency, Hz", fontsize=8)
        fig.tight_layout(pad=0.4)
        return fig

    fig, ax = plt.subplots(figsize=(FIG_W, FIG_H))
    _apply_dark(ax, fig)
    if not graph_df.empty:
        for mid, sub in graph_df.groupby("MeasureID"):
            m = meta.get(mid, {})
            _draw_series(ax, sub, m, norms, operator_names.get(mid, ""),
                         multi=True)
    ax.set_xscale("log")
    ax.set_xlabel("Frequency, Hz", fontsize=8)
    ax.set_ylabel("dB/Hz", fontsize=8)
    fig.tight_layout(pad=0.4)
    return fig


def _draw_one(ax, sub, m, norms, operator_name):
    _draw_series(ax, sub, m, norms, operator_name, multi=False)
    ax.set_xscale("log")
    ax.set_ylabel("dB/Hz", fontsize=8)


def _draw_series(ax, sub, meas_row, norms, operator_name, multi: bool):
    label = (f"МСК {meas_row.get('MSK', '')} / № {meas_row.get('N', '')}"
             if multi else None)

    # тонкая линия + мелкие маркеры
    if not sub.empty:
        ordered = sub.sort_values("Freq")
        ax.plot(ordered["Freq"], ordered["PN"],
                color="#ff5555", linewidth=LINE_W, alpha=0.9,
                label=label, zorder=3)
        ax.scatter(ordered["Freq"], ordered["PN"],
                   s=MARKER_S, color="#ff7777", linewidths=0, zorder=4)

    norm_points = collect_norm_points(meas_row, norms)
    for np_ in norm_points:
        if np_["value"] is None:
            continue
        color = NORM_COLORS[(np_["num"] - 1) % len(NORM_COLORS)]
        marker = "o" if np_["status"] != STATUS_FAIL else "x"
        ax.scatter([np_["offset"]], [np_["value"]],
                   color=color, marker=marker, s=NORM_S, zorder=5,
                   label=None if multi else np_["marker_text"])

    if not multi:
        title = f"№ {meas_row.get('N', '')}"
        ax.set_title(title, fontsize=9, loc="left", color="#d0d0d0")
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=7, loc="best",
                      facecolor="#2a2a2a", edgecolor="#555555",
                      labelcolor="#d0d0d0")
    else:
        if ax.get_legend_handles_labels()[0]:
            ax.legend(fontsize=7, loc="best",
                      facecolor="#2a2a2a", edgecolor="#555555",
                      labelcolor="#d0d0d0")


def fig_to_png_bytes(fig) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=110, bbox_inches="tight",
                facecolor=fig.get_facecolor())
    buf.seek(0)
    return buf.read()
