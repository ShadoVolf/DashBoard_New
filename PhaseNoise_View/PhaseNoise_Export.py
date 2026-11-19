"""Экспорт протокола и графиков ФШ в PDF, близкий к frxReport1 из DFM."""

import pandas as pd
from io import BytesIO
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image,
)
from reportlab.lib.styles import getSampleStyleSheet

from .PhaseNoise_Data import (
    load_phaze_noise_data, build_norms, load_specification, get_operator_fname,
)
from .PhaseNoise_Helpers import collect_norm_points, _fmt_hz
from .PhaseNoise_Graph import build_graph


def export_to_pdf(
    measurements: pd.DataFrame,
    spc: str,
    norms: list[dict] | None = None,
    mode: str = "both",
    group_mode: str = "msk",
    filepath: str = "phase_noise.pdf",
):
    """
    mode: "protocol" | "graphs" | "both".
    Для графиков данные берутся по MeasureID из measurements.
    """
    if norms is None:
        spec_row = load_specification(spc)
        norms = build_norms(spec_row or {})

    styles = getSampleStyleSheet()
    flow = []

    # ---- Протокол ----
    if mode in ("protocol", "both"):
        flow += _build_protocol(measurements, spc, norms, styles)
        flow.append(Spacer(1, 8 * mm))

    # ---- Графики ----
    if mode in ("graphs", "both"):
        ids = measurements["ID"].tolist()
        data_parts = []
        for mid in ids:
            sub = load_phaze_noise_data(None, int(mid), None)
            if not sub.empty:
                data_parts.append(sub)
        import pandas as pd
        graph_df = pd.concat(data_parts, ignore_index=True) if data_parts else pd.DataFrame()

        operator_names = {
            int(m["ID"]): get_operator_fname(m.get("Operator") or "")
            for _, m in measurements.iterrows()
        }
        if not graph_df.empty:
            fig = build_graph(graph_df, measurements, norms, operator_names, group_mode)
            buf = BytesIO()
            fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
            buf.seek(0)
            import matplotlib.pyplot as plt
            plt.close(fig)
            flow.append(Paragraph("Графики PN(Freq)", styles["Heading2"]))
            flow.append(Image(buf, width=250 * mm, height=150 * mm))

    doc = SimpleDocTemplate(filepath, pagesize=landscape(A4),
                            leftMargin=10*mm, rightMargin=10*mm,
                            topMargin=10*mm, bottomMargin=10*mm)
    doc.build(flow)
    print(f"[PhaseNoise] PDF сохранён: {filepath}")


def _build_protocol(measurements: pd.DataFrame, spc: str, norms: list[dict], styles):
    """Шапка + таблица, повторяющая frxReport1 из PhazeNoise.dfm."""
    flow = []
    flow.append(Paragraph("Протокол контроля измерений ФШ.", styles["Title"]))
    flow.append(Spacer(1, 3 * mm))

    first = measurements.iloc[0]
    msk = first.get("MSK", "")
    date_ = first.get("_Date_", "")
    flow.append(Paragraph(f"<b>МСК:</b> {msk}", styles["Normal"]))
    flow.append(Paragraph(f"<b>Спецификация:</b> {spc}", styles["Normal"]))
    flow.append(Paragraph(f"<b>Дата:</b> {date_}", styles["Normal"]))
    flow.append(Spacer(1, 4 * mm))

    # Заголовок таблицы
    header = ["№", "Номер", "Фазовые шумы 1, дБ", "Фазовые шумы 2, дБ",
              "Изменение ФШ, дБ", "Статус"]
    data = [header]
    for i, (_, m) in enumerate(measurements.iterrows(), start=1):
        mr = m.to_dict()
        pts = collect_norm_points(mr, norms)
        vals = {p["num"]: p for p in pts}
        # «ФШ 1» — первая активная норма, «ФШ 2» — вторая; «Изменение» — разница
        first_pt = vals.get(1, {})
        second_pt = vals.get(2, {})
        v1 = first_pt.get("value")
        v2 = second_pt.get("value")
        dev = None
        if v1 is not None and v2 is not None:
            dev = v1 - v2
        # Общий статус — Брак, если хотя бы одна норма не прошла
        bad = any(p.get("status") == "Брак" for p in pts)
        status = "Брак" if bad else "Годен"
        data.append([
            str(i),
            str(mr.get("N", "")),
            _f(v1), _f(v2), _f(dev), status,
        ])

    t = Table(data, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID",       (0, 0), (-1, -1), 0.4, colors.black),
        ("FONTSIZE",   (0, 0), (-1, -1), 8),
        ("ALIGN",      (0, 0), (-1, -1), "CENTER"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
    ]))
    flow.append(t)

    # Подпись
    flow.append(Spacer(1, 6 * mm))
    operator = first.get("Operator", "")
    fname = get_operator_fname(operator) or operator
    flow.append(Paragraph(f"Выполнил(а): {fname}", styles["Normal"]))
    return flow


def _f(v):
    if v is None or pd.isna(v):
        return "-"
    return f"{v:0.2f}"