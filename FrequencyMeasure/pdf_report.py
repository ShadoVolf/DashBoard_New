import os
import datetime
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib import colors
from reportlab.lib.units import mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (SimpleDocTemplate, Table, TableStyle,
                                Paragraph, Spacer, Image)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont


def _register_font(font_path):
    candidates = [font_path,
                  'C:/Windows/Fonts/DejaVuSans.ttf',
                  'C:/Windows/Fonts/arial.ttf',
                  '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf']
    for p in candidates:
        if p and os.path.exists(p):
            try:
                pdfmetrics.registerFont(TTFont('RusFont', p))
                return 'RusFont'
            except Exception:
                continue
    return 'Helvetica'


def _styled_table(data, col_widths):
    t = Table(data, colWidths=col_widths, repeatRows=1)
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'RusFont'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4472C4')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1),
         [colors.white, colors.HexColor('#EEEEEE')]),
    ]))
    return t


def export_summary_pdf(path, mcu_number, nominal_khz, summary_rows, font_path):
    """
    summary_rows: список словарей с полями
      {'mcu','resonator','max_ppm','min_ppm','monotonicity_ppm','cycles_count'}
    """
    _register_font(font_path)
    doc = SimpleDocTemplate(path, pagesize=landscape(A4),
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle('title', parent=styles['Title'],
                                 fontName='RusFont', fontSize=16)
    h_style = ParagraphStyle('h', parent=styles['Normal'],
                             fontName='RusFont', fontSize=11)

    story = [
        Paragraph("Протокол измерений частоты кварцевых резонаторов",
                  title_style),
        Spacer(1, 6*mm),
        Paragraph(f"МСК: <b>{mcu_number}</b>", h_style),
        Paragraph(f"Номинал: <b>{nominal_khz:.6f} кГц</b>", h_style),
        Paragraph(f"Дата: {datetime.datetime.now():%Y-%m-%d %H:%M:%S}",
                  h_style),
        Spacer(1, 6*mm),
    ]

    header = ['No', 'МСК', 'No резонатора',
              'Макс, ppm', 'Мин, ppm', 'Монот., ppm',
              'Выброс, ppm', 'Статус']
    data = [header]
    for i, row in enumerate(summary_rows, 1):
        mo = row.get('max_outlier_ppm', 0.0) or 0.0
        out_txt = f"{mo:.3f}" if mo > 0 else '-'
        data.append([
            str(i),
            row['mcu'],
            row['resonator'],
            f"{row['max_ppm']:+.3f}" if row['max_ppm'] is not None else '-',
            f"{row['min_ppm']:+.3f}" if row['min_ppm'] is not None else '-',
            f"{row['monotonicity_ppm']:.3f}" if row['monotonicity_ppm'] is not None else '-',
            out_txt,
            row.get('status', '-'),
        ])
    col_w = [12*mm, 28*mm, 32*mm, 32*mm, 32*mm, 34*mm, 34*mm, 24*mm]
    story.append(_styled_table(data, col_w))
    doc.build(story)
    return path


def export_graphs_pdf(path, measurements, font_path):
    """
    measurements: список словарей:
      {'mcu', 'resonator', 'cycle', 'nominal_khz', 't': [...], 'f_ppm': [...]}
    Графики строятся в ppm относительно номинала.
    """
    _register_font(font_path)
    doc = SimpleDocTemplate(path, pagesize=A4,
                            leftMargin=15*mm, rightMargin=15*mm,
                            topMargin=15*mm, bottomMargin=15*mm)
    styles = getSampleStyleSheet()
    h_style = ParagraphStyle('h', parent=styles['Heading2'],
                             fontName='RusFont', fontSize=12)
    title_style = ParagraphStyle('t', parent=styles['Title'],
                                 fontName='RusFont', fontSize=15)
    story = [
        Paragraph("Графики отклонений частоты (ppm)", title_style),
        Spacer(1, 5*mm),
    ]
    img_dir = os.path.join(os.path.dirname(path), '_tmp_imgs')
    os.makedirs(img_dir, exist_ok=True)

    for i, m in enumerate(measurements, 1):
        title = (f"{m['mcu']}  |  Резонатор {m['resonator']}  |  "
                 f"{m['cycle']}  |  ном. {m['nominal_khz']:.6f} кГц  |  "
                 f"точек: {len(m['t'])}")
        story.append(Paragraph(f"{i}. {title}", h_style))
        fig, ax = plt.subplots(figsize=(7.5, 3.5))
        ax.plot(m['t'], m['f_ppm'], '-', linewidth=0.8, color='#1f77b4')
        ax.axhline(0, color='grey', linewidth=0.5, linestyle='--')
        ax.set_xlabel('Время, с')
        ax.set_ylabel('Отклонение, ppm')
        ax.grid(True, alpha=0.3)
        ax.set_title(title, fontsize=8)
        png = os.path.join(img_dir, f'graph_{i}.png')
        fig.tight_layout()
        fig.savefig(png, dpi=110)
        plt.close(fig)
        story.append(Image(png, width=170*mm, height=80*mm))
        story.append(Spacer(1, 4*mm))

    doc.build(story)
    return path