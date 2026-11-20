"""Экспорт протокола и графиков ФШ в PDF.

Шрифты - как в Temperature_Measure/Report.py (Arial/Courier из fonts/).
Файлы: Протоколы/ФШ/<MeasureID>_<дата>_<время>.pdf
Графики: по одному на резонатор (N), по 6 на страницу.
"""

from __future__ import annotations

from datetime import datetime
from io import BytesIO
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from .PhaseNoise_Data import (
    build_norms, ensure_norms, get_operator_fname, load_phaze_noise_data,
    load_specification,
)
from .PhaseNoise_Graph import build_graph
from .PhaseNoise_Helpers import collect_norm_points, _fmt_hz

_ROOT = Path(__file__).resolve().parents[1]
_FONTS_DIR = _ROOT / "fonts"
_OUT_DIR = _ROOT / "Протоколы" / "ФШ"

_FONT_REG = False


def _register_fonts() -> str:
    """Регистрация шрифтов как в Temperature_Measure/Report.py."""
    global _FONT_REG
    if not _FONT_REG:
        # Report.py:
        #   pdfmetrics.registerFont(TTFont('Courier', 'fonts\\couriercyrillic.ttf'))
        #   pdfmetrics.registerFont(TTFont('Arial', 'fonts\\ArialRegular.ttf'))
        arial_path = "fonts\\ArialRegular.ttf"
        courier_path = "fonts\\couriercyrillic.ttf"
        arial_abs = _FONTS_DIR / "ArialRegular.ttf"
        courier_abs = _FONTS_DIR / "couriercyrillic.ttf"
        try:
            try:
                pdfmetrics.registerFont(TTFont("Arial", arial_path))
            except Exception:
                if arial_abs.is_file():
                    pdfmetrics.registerFont(TTFont("Arial", str(arial_abs)))
                else:
                    raise
            try:
                pdfmetrics.registerFont(TTFont("Courier", courier_path))
            except Exception:
                if courier_abs.is_file():
                    pdfmetrics.registerFont(TTFont("Courier", str(courier_abs)))
            _FONT_REG = True
        except Exception as e:
            print(f"[PhaseNoise] font register: {e}")
            # если Report уже зарегистрировал Arial - ок
            _FONT_REG = True
    return "Arial"


def _ensure_out_dir() -> Path:
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    return _OUT_DIR


def _make_filename(measurements: pd.DataFrame) -> str:
    mid = ""
    if measurements is not None and not measurements.empty:
        v = measurements.iloc[0].get("MeasureID")
        if v is not None and not (isinstance(v, float) and pd.isna(v)):
            mid = str(int(v)) if str(v).replace(".", "", 1).isdigit() else str(v)
        if not mid:
            v = measurements.iloc[0].get("MSK")
            mid = str(v or "FS").replace(" ", "")
    if not mid:
        mid = "FS"
    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return f"{mid}_{ts}.pdf"


def _f(v) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "---"
    try:
        return f"{float(v):0.2f}"
    except (TypeError, ValueError):
        return "---"


def export_to_pdf(
    measurements: pd.DataFrame,
    spc: str,
    norms: list[dict] | None = None,
    mode: str = "both",
    group_mode: str = "msk",
    filepath: str | None = None,
) -> str:
    if norms is None:
        norms = build_norms(load_specification(spc) or {})
    norms = ensure_norms(norms)

    font = _register_fonts()
    out_dir = _ensure_out_dir()
    if not filepath:
        filepath = str(out_dir / _make_filename(measurements))
    else:
        p = Path(filepath)
        if not p.is_absolute() and str(p.parent) in (".", ""):
            filepath = str(out_dir / p.name)

    styles = _styles(font)
    flow = []

    if mode in ("protocol", "both"):
        flow += _build_protocol(measurements, spc, norms, styles, font)
        if mode == "both":
            flow.append(PageBreak())

    if mode in ("graphs", "both"):
        flow += _build_graphs_pages(measurements, norms, group_mode, styles)

    if not flow:
        flow.append(Paragraph("Нет данных для протокола", styles["body"]))

    doc = SimpleDocTemplate(
        filepath,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm,
    )
    doc.build(flow)
    print(f"[PhaseNoise] PDF сохранён: {filepath}")
    return filepath


def _styles(font: str) -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "pn_title", parent=base["Title"], fontName=font,
            fontSize=14, leading=18, alignment=TA_CENTER, spaceAfter=6,
        ),
        "body": ParagraphStyle(
            "pn_body", parent=base["Normal"], fontName=font,
            fontSize=9, leading=12, alignment=TA_LEFT,
        ),
        "h2": ParagraphStyle(
            "pn_h2", parent=base["Heading2"], fontName=font,
            fontSize=11, leading=14, spaceBefore=4, spaceAfter=4,
        ),
        "small": ParagraphStyle(
            "pn_small", parent=base["Normal"], fontName=font,
            fontSize=7, leading=9, alignment=TA_CENTER,
        ),
    }


def _build_protocol(measurements, spc, norms, styles, font) -> list:
    flow = []
    flow.append(Paragraph("Протокол контроля измерений ФШ", styles["title"]))
    flow.append(Spacer(1, 3 * mm))

    if measurements is None or measurements.empty:
        flow.append(Paragraph("Нет измерений", styles["body"]))
        return flow

    first = measurements.iloc[0]
    msk = first.get("MSK", "")
    date_ = first.get("_Date_", "") or first.get("Date", "")
    mid = first.get("MeasureID", "")
    printed = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    flow.append(Paragraph(f"<b>МСК:</b> {msk}", styles["body"]))
    flow.append(Paragraph(f"<b>MeasureID:</b> {mid}", styles["body"]))
    flow.append(Paragraph(f"<b>Спецификация:</b> {spc}", styles["body"]))
    flow.append(Paragraph(f"<b>Дата измерения:</b> {date_}", styles["body"]))
    flow.append(Paragraph(f"<b>Печать:</b> {printed}", styles["body"]))
    flow.append(Spacer(1, 4 * mm))

    header = ["N", "MeasureID"]
    for nm in norms:
        header.append(_fmt_hz(nm["offset"]))
        header.append(f"Ст.{nm['num']}")
    header.append("Итог")

    data = [header]
    for _, m in measurements.iterrows():
        mr = m.to_dict()
        pts = collect_norm_points(mr, norms)
        by_num = {p["num"]: p for p in pts}
        row = [str(mr.get("N", "") or ""), str(mr.get("MeasureID", "") or "")]
        bad = False
        for nm in norms:
            p = by_num.get(nm["num"], {})
            row.append(_f(p.get("value")))
            st = p.get("status") or "н/д"
            row.append(st)
            if st == "Брак":
                bad = True
        if any(by_num.get(nm["num"], {}).get("value") is not None for nm in norms):
            row.append("Брак" if bad else "Годен")
        else:
            row.append("---")
        data.append(row)

    col_w = [18 * mm, 22 * mm]
    rest = max(12 * mm, (260 * mm - sum(col_w)) / max(1, len(header) - 2))
    col_w += [rest] * (len(header) - 2)

    t = Table(data, repeatRows=1, colWidths=col_w[: len(header)])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.Color(0.85, 0.85, 0.85)),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.black),
        ("FONTNAME", (0, 0), (-1, -1), font),
        ("FONTSIZE", (0, 0), (-1, -1), 7),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    flow.append(t)

    flow.append(Spacer(1, 6 * mm))
    operator = first.get("Operator", "")
    fname = get_operator_fname(operator) or operator
    flow.append(Paragraph(f"Выполнил(а): {fname}", styles["body"]))
    return flow


def _build_graphs_pages(measurements, norms, group_mode, styles) -> list:
    flow = []
    if measurements is None or measurements.empty:
        return flow

    flow.append(Paragraph("Графики PN (по одному на резонатор)", styles["h2"]))

    nums = []
    seen = set()
    for _, m in measurements.iterrows():
        n = str(m.get("N") or "").strip()
        if not n or n.upper() in seen:
            continue
        seen.add(n.upper())
        nums.append(n)

    images = []
    for n in nums:
        sub_meas = measurements[
            measurements["N"].astype(str).str.strip().str.upper() == n.upper()
        ]
        mids = []
        for _, m in sub_meas.iterrows():
            mid = m.get("MeasureID")
            if mid is None or (isinstance(mid, float) and pd.isna(mid)):
                continue
            try:
                mids.append(int(mid))
            except (TypeError, ValueError):
                continue
        mids = sorted(set(mids))
        if not mids:
            continue

        points = load_phaze_noise_data(measure_ids=mids)
        if points.empty:
            continue

        operators = {}
        for _, m in sub_meas.iterrows():
            if "ID" in m and pd.notna(m.get("ID")):
                try:
                    operators[int(m["ID"])] = get_operator_fname(m.get("Operator") or "")
                except (TypeError, ValueError):
                    pass

        try:
            fig = build_graph(
                points, sub_meas, norms, operators,
                group_mode="resonator_single",
                number_filter=n,
            )
            buf = BytesIO()
            fig.savefig(buf, format="png", dpi=120, bbox_inches="tight",
                        facecolor=fig.get_facecolor())
            buf.seek(0)
            import matplotlib.pyplot as plt
            plt.close(fig)
            images.append((n, buf))
        except Exception as e:
            print(f"[PhaseNoise] graph for N={n}: {e}")

    if not images:
        flow.append(Paragraph("Нет данных для графиков", styles["body"]))
        return flow

    page_w = landscape(A4)[0] - 20 * mm
    page_h = landscape(A4)[1] - 30 * mm
    cell_w = page_w / 2 - 4 * mm
    cell_h = page_h / 3 - 6 * mm

    for page_start in range(0, len(images), 6):
        chunk = images[page_start: page_start + 6]
        rows = []
        row = []
        for n, buf in chunk:
            img = Image(buf, width=cell_w, height=cell_h, kind="proportional")
            cell = [Paragraph(f"N {n}", styles["small"]), img]
            row.append(cell)
            if len(row) == 2:
                rows.append(row)
                row = []
        if row:
            while len(row) < 2:
                row.append([Paragraph("", styles["small"])])
            rows.append(row)

        table_data = []
        for r in rows:
            table_data.append([
                Table([[c[0]], [c[1]]], colWidths=[cell_w]) for c in r
            ])

        t = Table(table_data, colWidths=[page_w / 2, page_w / 2])
        t.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        flow.append(t)
        if page_start + 6 < len(images):
            flow.append(PageBreak())

    return flow
