"""Построение графика ФШ, воспроизводящее оформление C++ Chart1."""

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from io import BytesIO
from .PhaseNoise_Constants import NORM_COLORS, STATUS_FAIL
from .PhaseNoise_Helpers import collect_norm_points


def build_graph(
    graph_df,
    measurements,
    norms: list[dict],
    operator_names: dict[int, str] | None = None,
    group_mode: str = "msk",
) -> plt.Figure:
    """
    graph_df:      DataFrame [MeasureID, N, Freq, PN]
    measurements:  DataFrame заголовков phaze_noise
    norms:         список норм из build_norms()
    operator_names: dict MeasureID -> ФИО оператора
    group_mode:
        "msk"               — все измерения одной МСК на одном графике;
        "resonator_single"  — все измерения одного резонатора на одном графике;
        "resonator_multi"   — отдельный subplot на каждое измерение.
    """
    operator_names = operator_names or {}
    meta = measurements.set_index("ID").to_dict("index") if not measurements.empty else {}

    if group_mode == "resonator_multi" and not graph_df.empty:
        ids = list(graph_df["MeasureID"].dropna().unique())
        fig, axes = plt.subplots(
            nrows=len(ids), ncols=1, figsize=(10, 3 + 2.5 * len(ids)), sharex=True
        )
        if len(ids) == 1:
            axes = [axes]
        for ax, mid in zip(axes, ids):
            _draw_one(ax, graph_df[graph_df["MeasureID"] == mid], meta.get(mid, {}),
                      norms, operator_names.get(mid, ""))
        axes[-1].set_xlabel("Frequency, Hz")
        fig.tight_layout()
        return fig

    fig, ax = plt.subplots(figsize=(11, 6.5))
    if not graph_df.empty:
        for mid, sub in graph_df.groupby("MeasureID"):
            m = meta.get(mid, {})
            _draw_series(ax, sub, m, norms, operator_names.get(mid, ""), multi=True)
    ax.set_xscale("log")
    ax.set_xlabel("Frequency, Hz")
    ax.set_ylabel("dB/Hz")
    ax.grid(True, which="both", alpha=0.3)
    fig.tight_layout()
    return fig


def _draw_one(ax, sub, m, norms, operator_name):
    _draw_series(ax, sub, m, norms, operator_name, multi=False)
    ax.set_xscale("log")
    ax.set_ylabel("dB/Hz")


def _draw_series(ax, sub, meas_row, norms, operator_name, multi: bool):
    """Рисует одну линию измерения (Series2) и точки норм (Series3..)."""
    label = f"МСК {meas_row.get('MSK','')} / № {meas_row.get('N','')}" if multi else None

    # Основная кривая — мелкие точки, как Series2 (PointsSeries, красные)
    if not sub.empty:
        ax.scatter(sub["Freq"], sub["PN"], s=4, color="red",
                   label=label, zorder=3)

    # Точки норм
    norm_points = collect_norm_points(meas_row, norms)
    for np_ in norm_points:
        if np_["value"] is None:
            continue
        color = NORM_COLORS[(np_["num"] - 1) % len(NORM_COLORS)]
        marker = "o" if np_["status"] != STATUS_FAIL else "X"
        ax.scatter([np_["offset"]], [np_["value"]],
                   color=color, marker=marker, s=60, zorder=5,
                   label=None if multi else np_["marker_text"])

    # Заголовки как в Chart1 (Title/SubTitle/Foot/SubFoot)
    title = f"№ {meas_row.get('N','')}"
    subtitle = "   ".join(p["marker_text"] for p in norm_points) if not multi else ""
    if not multi:
        ax.set_title(title, fontsize=11, loc="left")
        if subtitle:
            ax.text(0.5, 1.02, subtitle, transform=ax.transAxes,
                    ha="center", fontsize=9)
        foot = (
            f"Дата {meas_row.get('_Date_','')} {meas_row.get('_Time_','')}   "
            f"Выполнил {operator_name or meas_row.get('Operator','')}   "
            f"Идентификатор замера {meas_row.get('MeasureID','')}"
        )
        subfoot = (
            f"МСК {meas_row.get('MSK','')}   {meas_row.get('Spc','')}   "
            f"ID {meas_row.get('PSI_ID','')}"
        )
        ax.text(0.0, -0.08, foot, transform=ax.transAxes, fontsize=8, color="dimgray")
        ax.text(0.0, -0.13, subfoot, transform=ax.transAxes, fontsize=8, color="dimgray")
        # Нормы в подписи
        norm_lines = [
            f"Норма {p['num']} отстройка {p['offset']}Гц >{p['min']}dB/Hz"
            for p in norm_points if p["min"] is not None
        ]
        for i, line in enumerate(norm_lines):
            ax.text(0.0, -0.18 - 0.045 * i, line, transform=ax.transAxes,
                    fontsize=8, color="dimgray")

    if not multi:
        ax.legend(fontsize=8, loc="best")
    else:
        ax.legend(fontsize=8, loc="best")


def fig_to_png_bytes(fig: plt.Figure) -> bytes:
    buf = BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    buf.seek(0)
    return buf.read()