"""Экспорт пар в XLS и PDF + открытие файла в системном приложении."""
import os
import sys
import glob
from datetime import datetime

import pandas as pd

import Options


_COLS_LABELS = {
    'n_1': 'N1', 'spc_1': 'Spc1', 'msk_1': 'MSK1',
    'f_1': 'F1', 'r_1': 'R1',
    'n_2': 'N2', 'spc_2': 'Spc2', 'msk_2': 'MSK2',
    'f_2': 'F2', 'r_2': 'R2',
    'signed_delta_f': 'F1-F2, ppm',
    'dev_from_target': 'dF от цели',
    'delta_f': 'dF, ppm',
    'delta_r': 'dR, Ohm',
    'measure_id_1': 'ID1', 'measure_id_2': 'ID2',
}

_COLS_ORDER = [
    'measure_id_1', 'n_1', 'spc_1', 'msk_1', 'f_1', 'r_1',
    'measure_id_2', 'n_2', 'spc_2', 'msk_2', 'f_2', 'r_2',
    'signed_delta_f', 'dev_from_target', 'delta_r',
]


# =============================================================================
# Шрифт с поддержкой кириллицы (для PDF)
# =============================================================================
_CYR_FONT_NAME = None
_CYR_FONT_BOLD = None
_CYR_FONT_REGISTERED = False


def _find_font_paths():
    """Кандидаты: сначала проектная папка fonts, потом системные."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    candidates = [
        os.path.join(root, 'fonts', 'DejaVuSans.ttf'),
        os.path.join(root, 'fonts', 'arial.ttf'),
        os.path.join(root, 'fonts', 'Arial.ttf'),
        os.path.join(root, 'Pictures', 'Theme_View', 'fonts', 'DejaVuSans.ttf'),
        r'C:\Windows\Fonts\arial.ttf',
        r'C:\Windows\Fonts\Arial.ttf',
        r'C:\Windows\Fonts\DejaVuSans.ttf',
        r'C:\Windows\Fonts\tahoma.ttf',
        r'C:\Windows\Fonts\calibri.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/System/Library/Fonts/Supplemental/Arial.ttf',
    ]
    # matplotlib (там всегда есть DejaVuSans)
    try:
        import matplotlib
        mpl_dir = os.path.dirname(matplotlib.__file__)
        candidates += glob.glob(
            os.path.join(mpl_dir, 'mpl-data', 'fonts', 'ttf', 'DejaVuSans*.ttf'))
    except Exception:
        pass
    # reportlab тоже иногда содержит Vera
    try:
        import reportlab
        rl_dir = os.path.dirname(reportlab.__file__)
        candidates += glob.glob(
            os.path.join(rl_dir, 'fonts', '*.ttf'))
    except Exception:
        pass
    return [p for p in candidates if p and os.path.exists(p)]


def _register_cyrillic_font():
    """Регистрирует TTF-шрифт с кириллицей в reportlab. Возвращает имя."""
    global _CYR_FONT_NAME, _CYR_FONT_BOLD, _CYR_FONT_REGISTERED
    if _CYR_FONT_REGISTERED:
        return _CYR_FONT_NAME or 'Helvetica'

    try:
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        print("[Pairs] reportlab недоступен")
        _CYR_FONT_REGISTERED = True
        return 'Helvetica'

    paths = _find_font_paths()
    if not paths:
        print("[Pairs] WARN: TTF с кириллицей не найден, будет Helvetica")
        _CYR_FONT_REGISTERED = True
        _CYR_FONT_NAME = 'Helvetica'
        _CYR_FONT_BOLD = 'Helvetica-Bold'
        return _CYR_FONT_NAME

    primary = paths[0]
    try:
        pdfmetrics.registerFont(TTFont('CyrFont', primary))
        _CYR_FONT_NAME = 'CyrFont'
    except Exception as e:
        print(f"[Pairs] font register failed ({primary}): {e}")
        _CYR_FONT_NAME = 'Helvetica'

    # bold-версия — рядом с основным
    bold_candidates = []
    for base in (primary,):
        if 'Sans.ttf' in base:
            bold_candidates.append(base.replace('Sans.ttf', 'Sans-Bold.ttf'))
        if 'arial.ttf' in base:
            bold_candidates.append(base.replace('arial.ttf', 'arialbd.ttf'))
        if 'Arial.ttf' in base:
            bold_candidates.append(base.replace('Arial.ttf', 'Arialbd.ttf'))
        if 'tahoma.ttf' in base:
            bold_candidates.append(base.replace('tahoma.ttf', 'tahomabd.ttf'))
        if 'calibri.ttf' in base:
            bold_candidates.append(base.replace('calibri.ttf', 'calibrib.ttf'))

    _CYR_FONT_BOLD = _CYR_FONT_NAME
    for bp in bold_candidates:
        if os.path.exists(bp):
            try:
                pdfmetrics.registerFont(TTFont('CyrFontBold', bp))
                _CYR_FONT_BOLD = 'CyrFontBold'
                break
            except Exception as e:
                print(f"[Pairs] bold font register failed ({bp}): {e}")

    print(f"[Pairs] PDF font: {primary} (bold: {_CYR_FONT_BOLD})")
    _CYR_FONT_REGISTERED = True
    return _CYR_FONT_NAME


# =============================================================================
# XLS
# =============================================================================
def export_pairs_xls(pairs_df: pd.DataFrame,
                     header: dict | None = None) -> str | None:
    try:
        from openpyxl import Workbook
    except ImportError:
        print("[Pairs] openpyxl недоступен")
        return None

    if pairs_df is None or pairs_df.empty:
        return None

    filename = f"pairs_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
    filepath = os.path.join(Options.get_measure_protokol_path(), filename)

    wb = Workbook()
    ws = wb.active
    ws.title = "Пары"

    r = 1
    ws.cell(r, 1, "Протокол формирования пар резонаторов")
    r += 1
    ws.cell(r, 1, f"Дата: {datetime.now():%Y-%m-%d %H:%M}")
    r += 1
    if header:
        for k, v in header.items():
            ws.cell(r, 1, f"{k}: {v}")
            r += 1
    r += 1

    present = [c for c in _COLS_ORDER if c in pairs_df.columns]
    for j, c in enumerate(present, 1):
        ws.cell(r, j, _COLS_LABELS.get(c, c))
    header_row = r
    r += 1

    for _, row in pairs_df.iterrows():
        for j, c in enumerate(present, 1):
            v = row.get(c, '')
            if pd.isna(v):
                v = ''
            ws.cell(r, j, v)
        r += 1

    ws.freeze_panes = ws.cell(header_row + 1, 1)
    wb.save(filepath)
    print(f"[Pairs] XLS: {filepath}")
    return filepath


# =============================================================================
# PDF
# =============================================================================
def export_pairs_pdf(pairs_df: pd.DataFrame,
                     header: dict | None = None) -> str | None:
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.lib import colors
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.platypus import (SimpleDocTemplate, Table,
                                        TableStyle, Paragraph, Spacer)
    except ImportError:
        print("[Pairs] reportlab недоступен")
        return None

    if pairs_df is None or pairs_df.empty:
        return None

    font = _register_cyrillic_font()
    bold = _CYR_FONT_BOLD or font

    filename = f"pairs_{datetime.now():%Y%m%d_%H%M%S}.pdf"
    filepath = os.path.join(Options.get_measure_protokol_path(), filename)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'CyrTitle', parent=styles['Title'], fontName=bold,
        fontSize=14, leading=18,
    )
    normal = ParagraphStyle(
        'CyrNormal', parent=styles['Normal'], fontName=font,
        fontSize=10, leading=13,
    )

    doc = SimpleDocTemplate(filepath, pagesize=landscape(A4),
                            leftMargin=18, rightMargin=18,
                            topMargin=18, bottomMargin=18)
    story = [
        Paragraph("Протокол формирования пар резонаторов", title_style),
        Spacer(1, 8),
        Paragraph(f"Дата: {datetime.now():%Y-%m-%d %H:%M}", normal),
    ]
    if header:
        for k, v in header.items():
            story.append(Paragraph(f"{k}: {v}", normal))
    story.append(Spacer(1, 10))

    present = [c for c in _COLS_ORDER if c in pairs_df.columns]
    data = [[_COLS_LABELS.get(c, c) for c in present]]
    for _, row in pairs_df.iterrows():
        line = []
        for c in present:
            v = row.get(c, '')
            if pd.isna(v):
                v = ''
            elif isinstance(v, float):
                v = f"{v:.4g}"
            line.append(str(v))
        data.append(line)

    tbl = Table(data, repeatRows=1)
    tbl.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#c8dcff')),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.grey),
        ('FONTNAME', (0, 0), (-1, -1), font),
        ('FONTNAME', (0, 0), (-1, 0), bold),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
    ]))
    story.append(tbl)
    doc.build(story)
    print(f"[Pairs] PDF: {filepath}")
    return filepath


# =============================================================================
# Открытие файла в системном приложении
# =============================================================================
def open_file(filepath: str) -> None:
    if not filepath or not os.path.exists(filepath):
        return
    try:
        if os.name == 'nt':
            os.startfile(filepath)  # type: ignore[attr-defined]
        elif sys.platform == 'darwin':
            import subprocess
            subprocess.Popen(['open', filepath])
        else:
            import subprocess
            subprocess.Popen(['xdg-open', filepath])
    except Exception as e:
        print(f"[Pairs] open_file failed: {e}")