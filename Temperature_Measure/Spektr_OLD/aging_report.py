"""PDF-протокол старения (аналог frxReport1 в SpektrOLD) с QR-кодом."""
import io
import os
import platform
import subprocess
from datetime import datetime

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image,
)

import Options

try:
    import qrcode
    HAS_QRCODE = True
except ImportError:
    HAS_QRCODE = False
    print('[aging_report] Модуль qrcode не установлен — '
          'QR-код не будет нарисован. pip install qrcode[pil]')


# ---------------------------------------------------------------------------
#                              QR helper
# ---------------------------------------------------------------------------
def _make_qr(data_str: str, size_mm: float = 24):
    """Возвращает reportlab.Image с QR-кодом или None."""
    if not HAS_QRCODE:
        return None
    try:
        qr = qrcode.make(str(data_str))
        buf = io.BytesIO()
        qr.save(buf, format='PNG')
        buf.seek(0)
        return Image(buf, width=size_mm * mm, height=size_mm * mm)
    except Exception as e:
        print(f'[aging_report] _make_qr error: {e}')
        return None


def build_qr_payload(old_id, meta: dict) -> str:
    """Единый формат полезной нагрузки QR.

    Пример: AGING:42116|M1:230630|M2:231987
    — при сканировании легко распарсить: old_id, Measure_ID первого
    замера и Measure_ID второго (или AUTO).
    """
    mid_1 = meta.get('Measure_ID') or '?'
    mid_2 = meta.get('MeasureID') or '?'
    return f'AGING:{old_id}|M1:{mid_1}|M2:{mid_2}'


# ---------------------------------------------------------------------------
#                        Основная функция протокола
# ---------------------------------------------------------------------------
def create_aging_report(old_id, data_df: pd.DataFrame, meta: dict,
                        norms: dict, stats: dict,
                        filename: str = None) -> str:
    if filename is None:
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"aging_{old_id}_{ts}.pdf"

    path = os.path.join(Options.get_measure_protokol_path(), filename)

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        'AgingTitle', parent=styles['Heading1'],
        fontName='Arial', fontSize=14, alignment=TA_CENTER, spaceAfter=2,
    )
    sub_style = ParagraphStyle(
        'AgingSub', parent=styles['Normal'],
        fontName='Arial', fontSize=11, alignment=TA_CENTER, spaceAfter=4,
    )
    info_style = ParagraphStyle(
        'AgingInfo', parent=styles['Normal'],
        fontName='Arial', fontSize=9, alignment=TA_LEFT, leading=11,
    )
    qr_caption_style = ParagraphStyle(
        'AgingQRCaption', parent=styles['Normal'],
        fontName='Courier', fontSize=7, alignment=TA_CENTER,
        textColor=colors.HexColor('#555555'),
    )

    story = []

    # -----------------------------------------------------------------
    # 1. Шапка: заголовок + QR справа
    # -----------------------------------------------------------------
    qr_payload = build_qr_payload(old_id, meta)
    qr_img = _make_qr(qr_payload, size_mm=24)

    title_block = [
        Paragraph('Уход частоты (старение)', title_style),
        Paragraph(f'Спецификация: <b>{_str(meta.get("Spc"))}</b>',
                  sub_style),
    ]

    usable_w = A4[0] - 20 * mm  # 20mm = left + right margins

    if qr_img is not None:
        qr_block = [
            qr_img,
            Paragraph(f'old_id: {old_id}', qr_caption_style),
        ]
        header_tbl = Table(
            [[title_block, qr_block]],
            colWidths=[usable_w - 32 * mm, 32 * mm],
        )
        header_tbl.setStyle(TableStyle([
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),
            ('ALIGN', (0, 0), (0, 0), 'CENTER'),
            ('ALIGN', (1, 0), (1, 0), 'RIGHT'),
            ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ('RIGHTPADDING', (0, 0), (-1, -1), 0),
            ('TOPPADDING', (0, 0), (-1, -1), 0),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))
        story.append(header_tbl)
    else:
        story.extend(title_block)

    story.append(Spacer(1, 4 * mm))

    # -----------------------------------------------------------------
    # 2. Информационный блок (текстовые метаданные)
    # -----------------------------------------------------------------
    mid_1 = meta.get('Measure_ID')
    # при автопоиске MeasureID в old — разные для разных N
    unique_ids_2 = []
    if 'MeasureID' in data_df.columns:
        unique_ids_2 = (data_df['MeasureID']
                        .dropna().unique().tolist())
    if len(unique_ids_2) == 0:
        mid2_str = '-'
    elif len(unique_ids_2) == 1:
        mid2_str = str(int(unique_ids_2[0]))
    else:
        mid2_str = f'{len(unique_ids_2)} (автопоиск)'

    info_rows = [
        ['МСК', _str(meta.get('MSK'))],
        ['ID старения', _str(old_id)],
        ['Код замера 1', _str(mid_1)],
        ['Код замера 2', mid2_str],
        ['Файл 1', _str(meta.get('File_1'))],
        ['Файл 2', _str(meta.get('File_2'))],
        ['QR-код', qr_payload],
    ]
    info_tbl = Table(info_rows, colWidths=[45 * mm, 135 * mm])
    info_tbl.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        # моно-шрифт для строки QR
        ('FONTNAME', (1, 6), (1, 6), 'Courier'),
        ('FONTSIZE', (1, 6), (1, 6), 8),
    ]))
    story.append(info_tbl)
    story.append(Spacer(1, 5 * mm))

    # -----------------------------------------------------------------
    # 3. Основная таблица результатов
    # -----------------------------------------------------------------
    rows = [['Номер', 'F2-F1, ppm', 'R2-R1, Ом', 'Статус']]
    for _, r in data_df.iterrows():
        rows.append([
            _str(r.get('N')),
            _fmt(r.get('old1')),
            _fmt(r.get('old2')),
            _str(r.get('Status')),
        ])

    tbl = Table(rows, colWidths=[40 * mm, 45 * mm, 45 * mm, 50 * mm],
                repeatRows=1)
    tbl_style = [
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DDDDDD')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]
    for idx, (_, r) in enumerate(data_df.iterrows(), start=1):
        if r.get('Status') == 'Брак':
            tbl_style.append(('BACKGROUND', (0, idx), (-1, idx),
                              colors.HexColor('#FFCC99')))
    tbl.setStyle(TableStyle(tbl_style))
    story.append(tbl)
    story.append(Spacer(1, 6 * mm))

    # -----------------------------------------------------------------
    # 4. Статистика
    # -----------------------------------------------------------------
    f_vals = pd.to_numeric(data_df['old1'], errors='coerce').dropna()
    r_vals = pd.to_numeric(data_df['old2'], errors='coerce').dropna()
    f_bad = int((data_df['Status'] == 'Брак').sum())
    f_good = int((data_df['Status'] == 'Годен').sum())

    def _norm_str(lo, hi):
        if lo is None and hi is None:
            return '-'
        return f'{_fmt(lo, "-")} … {_fmt(hi, "-")}'

    stat_rows = [
        ['', 'F2-F1, ppm', 'R2-R1, Ом'],
        ['Норма',
         _norm_str(norms.get('old1min'), norms.get('old1max')),
         _norm_str(norms.get('old2min'), norms.get('Old2Max'))],
        ['Макс', _fmt(f_vals.max() if len(f_vals) else None),
         _fmt(r_vals.max() if len(r_vals) else None)],
        ['Мин', _fmt(f_vals.min() if len(f_vals) else None),
         _fmt(r_vals.min() if len(r_vals) else None)],
        ['Среднее', _fmt(f_vals.mean() if len(f_vals) else None),
         _fmt(r_vals.mean() if len(r_vals) else None)],
        ['Годных', str(f_good), ''],
        ['Брак', str(f_bad), ''],
        ['Всего', str(stats.get('total', len(data_df))), ''],
    ]
    stat_tbl = Table(stat_rows, colWidths=[45 * mm, 55 * mm, 55 * mm])
    stat_tbl.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DDDDDD')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#F5F5F5')),
    ]))
    story.append(stat_tbl)
    story.append(Spacer(1, 8 * mm))

    story.append(Paragraph(
        'Оператор: ______________________   Дата: ____________',
        info_style,
    ))

    # -----------------------------------------------------------------
    # 5. Футер (на каждой странице): old_id, QR-payload, страница
    # -----------------------------------------------------------------
    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont('Courier', 7)
        canvas.setFillColor(colors.HexColor('#555555'))
        canvas.drawString(doc_.leftMargin, 9 * mm,
                          f'ID старения: {old_id}')
        canvas.drawString(doc_.leftMargin, 6 * mm,
                          f'QR: {qr_payload}')
        canvas.setFont('Arial', 7)
        canvas.drawRightString(doc_.leftMargin + doc_.width, 9 * mm,
                               f'Страница {canvas.getPageNumber()}')
        canvas.restoreState()

    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=10 * mm, bottomMargin=18 * mm,
    )
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return path


# ---------------------------------------------------------------------------
#                            Открытие PDF
# ---------------------------------------------------------------------------
def open_pdf(path: str):
    try:
        if platform.system() == 'Windows':
            os.startfile(path)
        elif platform.system() == 'Darwin':
            subprocess.run(['open', path])
        else:
            subprocess.run(['xdg-open', path])
    except Exception as e:
        print(f'[aging_report.open_pdf] {e}')


# ---------------------------------------------------------------------------
#                              Утилиты
# ---------------------------------------------------------------------------
def _fmt(v, default='-'):
    if v is None:
        return default
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)
    if pd.isna(f):
        return default
    return f'{f:.2f}'


def _str(v):
    if v is None:
        return '-'
    try:
        if pd.isna(v):
            return '-'
    except (TypeError, ValueError):
        pass
    return str(v)