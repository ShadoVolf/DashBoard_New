import os
import platform
import subprocess
from reportlab.lib.pagesizes import landscape, A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Table, TableStyle, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.units import mm
import qrcode
import io
import pandas as pd
from reportlab.pdfbase import pdfmetrics
import datetime
from datetime import datetime

from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
import re
import sys

from tabulate import tabulate


import Options

pdfmetrics.registerFont(TTFont('Courier', 'fonts\\couriercyrillic.ttf'))
pdfmetrics.registerFont(TTFont('Arial', 'fonts\\ArialRegular.ttf'))


def generate_filename(measure_id, extension="pdf", print_version=False):
    """
    Генерирует имя файла с временной меткой

    :param measure_id: Идентификатор измерения
    :param extension: Расширение файла (по умолчанию 'txt')
    :param print_version: Флаг версии для печати (добавляет суффикс '_print')
    :return: Строка вида 'ID_YYYY-MM-DD_HH-MM-SS[_print].ext'
    """
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = "_print" if print_version else ""
    return f"{measure_id}_{timestamp}{suffix}.{extension}"


# открывает созданный Pdf документ
def open_pdf(filename):
    """Открывает PDF-файл в программе просмотра по умолчанию"""
    try:
        if platform.system() == 'Darwin':  # macOS
            subprocess.run(['open', filename])
        elif platform.system() == 'Windows':  # Windows
            os.startfile(filename)
        else:  # Linux/UNIX
            subprocess.run(['xdg-open', filename])
    except Exception as e:
        print(f"Ошибка при открытии файла: {e}")


def create_protocol(data_df, status_df, headers, spc_map, view_data, stats_df, measure_id, filename="protocol.pdf"):
    """Main function to create measurement protocol"""
    data_df = data_df.drop('Status2', axis=1)
    print('Протокол для печати')
    table = tabulate(
        data_df,
        headers='keys', tablefmt='grid', showindex=False)
    print(table)
    path = Options.get_measure_protokol_path()
    filename = path + "\\" + filename
    # Setup document and basic elements
    doc, elements = setup_document(filename)

    # Create header section
    elements.append(create_header(view_data, measure_id, doc.width))
    elements.append(Spacer(1, 5 * mm))

    # Add protocol title
    elements.append(create_protocol_title(measure_id, view_data['Protokol_Type']))

    # Prepare data for main table
    spc_dict = process_spc_map(spc_map)
    table_data = prepare_table_data(data_df, headers, spc_dict, stats_df)

    # Create and style main table
    main_table = build_main_table(data_df, table_data, doc.width)
    apply_table_styles(main_table, data_df, status_df, spc_dict)

    elements.append(main_table)

    # Функция для добавления колонтитулов
    def add_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont('Arial', 8)
        page_num = canvas.getPageNumber()
        text = f"Страница {page_num}"
        text2 = f"Исполнитель   {view_data['Operator']}"
        canvas.drawString(doc.width - 20 * mm, 10 * mm, text)
        canvas.drawString(doc.width - 170 * mm, 10 * mm, text2)
        canvas.restoreState()

    # Настройка документа
    doc = SimpleDocTemplate(
        filename,
        pagesize=A4,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=15 * mm  # Увеличен для размещения номера
    )

    doc.build(elements, onFirstPage=add_footer, onLaterPages=add_footer)
    return filename


# Basic document setup
def setup_document(filename):
    """Initialize PDF document template"""
    return SimpleDocTemplate(
        filename,
        pagesize=A4,
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=10 * mm
    ), []


# Header section
def create_header(view_data, measure_id, page_width):
    """Create header with left-aligned content and QR in top-right corner"""
    qr_image = generate_qr_code(measure_id)
    header_table = format_header_content(view_data)

    # Основная таблица с контейнером для данных и QR
    main_table = Table(
        [
            [
                header_table,  # Основные данные слева
                Image(qr_image, width=10 * mm, height=10 * mm)  # QR-код справа
            ]
        ],
        colWidths=[page_width * 0.95, page_width * 0.05]
    )

    main_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),  # Выравнивание данных влево
        ('ALIGN', (1, 0), (1, 0), 'RIGHT'),  # Выравнивание QR вправо
        ('LEFTPADDING', (0, 0), (0, 0), 0),  # Убираем отступы слева
        ('RIGHTPADDING', (1, 0), (1, 0), 0),  # Убираем отступы справа
    ]))

    return main_table


def generate_qr_code(measure_id):
    """Generate QR code image"""
    qr = qrcode.make(str(measure_id))
    buffer = io.BytesIO()
    qr.save(buffer, format='PNG')
    buffer.seek(0)
    return buffer


def format_header_content(view_data):
    """Format header content with left-aligned labels and right-aligned values"""
    spc_name = view_data['Spc_Text']
    if view_data['PMI'] == 1:
        spc_name = "ПМИ " + spc_name
    elif view_data['PMI'] == 2:
        spc_name = 'SMD ' + spc_name
    corr_type_str = ''
    if view_data.get('F_correction'):
        corr_type_str = corr_type_str + ' Точность настройки'
    if view_data.get('TCH_correction'):
        corr_type_str = corr_type_str + '  ТЧХ'
    if view_data.get('R_correction'):
        corr_type_str = corr_type_str + '  R'
    if view_data.get('Q_correction'):
        corr_type_str = corr_type_str + '  Q'
    if corr_type_str == '':
        corr_type_str = 'Нет'
    data = [
        ["Протокол измерений резонаторов   ", spc_name],
        ["Дата выполнения", pd.Timestamp.now().strftime('%d.%m.%Y')],
        ["MCK", view_data['MSK']],
        ["Номинал", f"{view_data['Nominal']} МГц"],
        ["Позиции", view_data['Position_str']],
        ["Температурный профиль", f"{view_data['Profile']} ({view_data['Temp']})"],
        ["Тип ТЧХ", f"{view_data['TCH_Type']}"],
        ["Коррекция", f"{corr_type_str}"],
        ["Файл", f"{view_data['FileName']} ({view_data['File_ID']})"],
        ["Режим измерений", get_load_type_string(view_data)],
        ["Установка", view_data['Machine_Type']],
        ["Серийный номер", f"N{view_data['Machine_Serial']}"],
        [get_poverka_string(view_data), ""]  # Занимает всю ширину
    ]

    table = Table(data, colWidths=[250, None])  # Ширина колонки меток
    table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Courier'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('LEADING', (0, 0), (-1, -1), 12),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),  # Метки слева
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),  # Значения справа
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('SPAN', (-2, -1), (-1, -1)),  # Объединяем последнюю строку
        ('LINEBELOW', (-2, -1), (-1, -1), 0.5, colors.lightgrey),
    ]))

    return table


def get_load_type_string(view_data):
    """Format load type information"""
    out_str = ''
    if view_data['LoadType'] == 'EQREACT':
        out_str = f"{view_data['LoadType']}{'(по формуле)' if view_data['Virtual'] == 1 else ''}"
    else:
        out_str = view_data['LoadType']
    if view_data['LoadType'] != 'SERIES':
        out_str = out_str + '  Нагрузочная емкость ' + str(view_data['LoadValue']) + ' пФ'
    return out_str


def get_poverka_string(view_data):
    """Format calibration/verification information with right alignment"""
    label = 'Дата поверки' if view_data['Poverka'] == 1 else 'Дата калибровки'
    return f"{label}: {view_data['Poverka_Date']}".rjust(40)  # Выравнивание пробелами


# Title section
def create_protocol_title(measure_id, protokol_type):
    """Create main protocol title"""
    return Paragraph(
        f"Протокол измерений {protokol_type}  № {measure_id}",
        get_protocol_title_style()
    )


# Table preparation
def process_spc_map(spc_map):
    """Process SPC specifications to dictionary"""
    return spc_map.set_index('Parameter')[['Max', 'Min']].to_dict('index')


def prepare_table_data(data_df, headers, spc_dict, stats_df):
    """Prepare complete dataset for the main table"""
    header_rows, max_row, min_row = create_table_headers(data_df, headers, spc_dict)
    stat_rows = prepare_statistics_rows(data_df, stats_df)
    return [header_rows, max_row, min_row] + stat_rows + data_df.values.tolist()


def create_table_headers(data_df, headers, spc_dict):
    """Create table header rows with specifications"""
    header_row = []
    max_row = []
    min_row = []

    for col in data_df.columns:
        # Main header
        header_row.append(Paragraph(headers.get(col, col), get_table_header_style()))

        # Specifications
        if col in spc_dict:
            max_text = format_spec('Макс', spc_dict[col]['Max'])
            min_text = format_spec('Мин', spc_dict[col]['Min'])
        else:
            max_text = min_text = ''

        max_row.append(Paragraph(max_text, get_norm_style()))
        min_row.append(Paragraph(min_text, get_norm_style()))

    return header_row, max_row, min_row


def format_spec(label, value):
    """Format specification value"""
    return f"<b>{label}:</b> {value:.2f}" if pd.notna(value) else ""


def prepare_statistics_rows(data_df, stats_df):
    """Prepare statistics rows for the table"""
    stat_metrics = ['Брак', 'Годные', 'Макс', 'Мин', 'Среднее', 'СтОткл']
    rows = []

    for metric in stat_metrics:
        row = [Paragraph(metric, get_stats_label_style())]
        for col in data_df.columns:
            if col == 'Positions':
                continue

            cell_content = get_stat_cell_content(col, metric, stats_df, data_df)
            row.append(Paragraph(cell_content, get_stats_data_style()))
        rows.append(row)

    return rows


def get_stat_cell_content(col, metric, stats_df, data_df):
    """Get formatted content for statistics cell"""
    if col == 'Status':
        return format_status_stat(metric, stats_df)
    if col == 'Numbers':
        return '-'
    return format_parameter_stat(col, metric, stats_df)


def format_status_stat(metric, stats_df):
    """Format statistics for Status column"""
    total_stats = stats_df[stats_df['Parameter'] == 'Общий статус'].iloc[0]
    if metric in ['Брак', 'Годные']:
        return f"{int(total_stats[metric])}" if pd.notna(total_stats[metric]) else '-'
    return '-'


def format_parameter_stat(col, metric, stats_df):
    """Format statistics for parameter columns"""
    param_stats = stats_df[stats_df['Parameter'] == col]
    if param_stats.empty:
        return '-'

    value = param_stats[metric].values[0]
    if pd.isna(value):
        return '-'

    if metric in ['Брак', 'Годные']:
        return f"{int(value)}"
    return f"{value:.2f}"


# Table construction
def build_main_table(data_df, table_data, page_width):
    """Build main table with configured parameters"""
    num_cols = len(data_df.columns)
    return Table(
        table_data,
        colWidths=[page_width * 0.95 / num_cols] * num_cols,
        repeatRows=9  # 3 header rows + 6 statistics rows
    )


# Style application
def apply_table_styles(table, data_df, status_df, spc_dict):
    """Apply all styles and highlighting to the table"""
    base_styles = [
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DDDDDD')),
        ('BACKGROUND', (0, 1), (-1, 2), colors.HexColor('#E8E8E8')),
        ('BACKGROUND', (0, 3), (-1, 8), colors.HexColor('#F5F5F5')),
        ('FONTSIZE', (0, 0), (-1, 0), 6),
        ('FONTSIZE', (0, 1), (-1, 2), 6),
        ('FONTSIZE', (0, 3), (-1, 8), 6),
        ('FONTSIZE', (0, 9), (-1, -1), 9),
        ('LEADING', (0, 0), (-1, -1), 9),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2)
    ]

    # Add merged cells for columns without specs
    for col_idx, col in enumerate(data_df.columns):
        if col not in spc_dict:
            base_styles.append(('SPAN', (col_idx, 0), (col_idx, 2)))

    # Add highlighting
    highlight_styles = get_highlight_styles(data_df, status_df)
    table.setStyle(TableStyle(base_styles + highlight_styles))

def _status_is_bad(value):
    """
    Интерпретирует значение статуса как признак брака.

    Понимает bool, 0/1, 'Годен'/'Брак', 'Good'/'Bad', 'True'/'False',
    '1'/'0', 'Да'/'Нет'. None/NaN/пустая строка/неизвестное значение
    возвращают None (статус неизвестен — строка не подсвечивается).
    """
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value == 0
    s = str(value).strip().casefold()
    if s in ('', 'nan', 'none'):
        return None
    if s in ('годен', 'good', 'true', '1', 'да', 'ok', 'ok.'):
        return False
    if s in ('брак', 'bad', 'false', '0', 'нет', 'fail', 'failed'):
        return True
    return None


def _key_normalize(value):
    """
    Нормализует ключ сопоставления: '5' / 5 / 5.0 / '05' / ' 5 ' -> '5'.
    Для нечисловых значений — строка с обрезанными пробелами, casefold.
    None/NaN/пустая строка -> None.
    """
    if value is None:
        return None
    if isinstance(value, float) and pd.isna(value):
        return None
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, (int, float)):
        f = float(value)
        return str(int(f)) if f.is_integer() else repr(f)
    s = str(value).strip()
    if not s:
        return None
    t = s.replace(',', '.')
    if t.replace('.', '', 1).isdigit():
        f = float(t)
        return str(int(f)) if f.is_integer() else repr(f)
    return s.casefold()


def get_highlight_styles(data_df, status_df, data_offset=9):
    """
    Цветовая разметка брака в печатном протоколе.

      * строка со статусом 'Брак'          — светло-жёлтая (#FFFACD) целиком;
      * ячейки Позиция / Номер / Статус    — оранжевые (#FF9933);
      * отбракованные параметры            — оранжевые (#FF9933);
      * строки 'Годен' и статусы-заглушки  — без заливки.

    В отличие от прежней версии статус сопоставляется по паре
    (Позиция, Номер), а при отсутствии номера или пары — по позиции.
    Ранее сравнение шло только по позиции, и при повторяющихся позициях
    (несколько настроек, история, ВСЕ МСК в архиве) бракованная строка
    могла получить статус чужой строки и остаться без заливки.

    Приоритет статуса: собственное значение data_df['Status'] печатаемой
    строки ('Брак'/'Годен'), затем — any-bad по подобранным строкам
    status_df (общий статус = AND статусов параметров).
    """
    styles = []
    try:
        status_col_idx   = data_df.columns.get_loc('Status')
        number_col_idx   = data_df.columns.get_loc('Numbers')
        position_col_idx = data_df.columns.get_loc('Positions')
    except KeyError as e:
        raise ValueError(f"Missing required column: {e}")

    ROW_BAD     = colors.HexColor('#FFFACD')   # светло-жёлтый
    SERVICE_BAD = colors.HexColor('#FF9933')   # тёмный оранжевый
    PARAM_BAD   = colors.HexColor('#FF9933')   # тёмный оранжевый

    last_col_idx = len(data_df.columns) - 1

    if status_df is None or len(status_df) == 0:
        return styles
    status_df = status_df.reset_index(drop=True)

    # Индексы поиска в status_df: по позиции и по паре (позиция, номер).
    pos_rows = {}
    pair_rows = {}
    has_numbers = 'Numbers' in status_df.columns
    for i, row in status_df.iterrows():
        pk = _key_normalize(row.get('Positions'))
        if pk is None:
            continue
        pos_rows.setdefault(pk, []).append(i)
        if has_numbers:
            nk = _key_normalize(row.get('Numbers'))
            if nk is not None:
                pair_rows.setdefault((pk, nk), []).append(i)

    for row_idx in range(len(data_df)):
        data_row = data_df.iloc[row_idx]
        pk = _key_normalize(data_row['Positions'])
        if pk is None:
            continue
        cand = []
        if has_numbers:
            nk = _key_normalize(data_row['Numbers'])
            if nk is not None:
                cand = pair_rows.get((pk, nk), [])
        if not cand:
            cand = pos_rows.get(pk, [])
        if not cand:
            continue

        # Приоритет — собственный статус печатаемой строки.
        row_is_bad = _status_is_bad(data_row['Status'])
        if row_is_bad is None:
            any_bad = False
            for i in cand:
                sb = _status_is_bad(status_df.at[i, 'Status'])
                if sb is None:
                    continue
                any_bad = any_bad or sb
            row_is_bad = any_bad
        if row_is_bad is not True:
            continue

        y = row_idx + data_offset

        # 1. Вся строка — светло-жёлтая
        styles.append(
            ('BACKGROUND', (0, y), (last_col_idx, y), ROW_BAD))
        # 2. Служебные ячейки — тёмный оранжевый
        for idx in (position_col_idx, number_col_idx, status_col_idx):
            styles.append(
                ('BACKGROUND', (idx, y), (idx, y), SERVICE_BAD))

        # 3. Забракованные параметры — тёмный оранжевый
        for i in cand:
            for param in data_df.columns:
                if param in ('Positions', 'Numbers', 'Status', 'Status2'):
                    continue
                status_key = f'{param}_status'
                if status_key not in status_df.columns:
                    continue
                if _status_is_bad(status_df.at[i, status_key]) is True:
                    param_idx = data_df.columns.get_loc(param)
                    styles.append(
                        ('BACKGROUND', (param_idx, y),
                         (param_idx, y), PARAM_BAD))
    return styles


def get_test_data_cell_style():
    """
    Стиль ячейки данных тестового протокола.
    ВАЖНО: без backColor — иначе Paragraph перекроет
    ('BACKGROUND', ...) из TableStyle, и подсветка брака
    (жёлтая строка / оранжевые параметры) будет невидима.
    """
    return ParagraphStyle(
        'TestDataCellStyle',
        fontName='Arial',
        fontSize=8,
        leading=9,
        alignment=TA_CENTER,
        textColor=colors.black,
        wordWrap='CJK',
    )


# ============================================================================
# ТЕСТОВЫЙ ПРОТОКОЛ: нормы внизу каждой страницы + статистика в конце
# ============================================================================

def _fmt_num(v):
    """Короткое числовое представление для таблицы тестового протокола."""
    if v is None:
        return ''
    if isinstance(v, float):
        if pd.isna(v):
            return ''
        return f"{v:.6g}"
    return str(v)

def _fmt_num_cell(v, decimals=3):
    """Форматирует значение с фиксированным числом знаков после запятой."""
    if v is None:
        return ''
    try:
        if pd.isna(v):
            return ''
    except (TypeError, ValueError):
        pass
    if isinstance(v, (int, float)):
        try:
            return f"{float(v):.{int(decimals)}f}"
        except (TypeError, ValueError):
            return str(v)
    return str(v)


_COL_LABELS = {
    'Positions': 'Позиции',
    'Numbers':   'Номер',
    'Status':    'Статус',
}


def _col_label(col):
    return _COL_LABELS.get(col, col)


def _build_norms_flowable(spc_map, page_width, font_size=6):
    """
    Компактная таблица норм для подвала КАЖДОЙ страницы.

    Колонок — 1, 2 или 3 (по количеству параметров), чтобы уложиться
    в ~60 мм по высоте.
    """
    entries = []
    for _, row in spc_map.iterrows():
        label = (row.get('Note_mini')
                 or row.get('Note')
                 or str(row['Parameter']))
        mx = row['Max']
        mn = row['Min']
        mx_s = f"{mx:.4g}" if mx is not None and not pd.isna(mx) else '—'
        mn_s = f"{mn:.4g}" if mn is not None and not pd.isna(mn) else '—'
        entries.append([str(label), mx_s, mn_s])

    n = len(entries)
    if n == 0:
        return None

    if n <= 10:
        n_cols = 1
    elif n <= 24:
        n_cols = 2
    else:
        n_cols = 3

    per_col = (n + n_cols - 1) // n_cols
    cols_entries = []
    for i in range(n_cols):
        chunk = entries[i * per_col:(i + 1) * per_col]
        while len(chunk) < per_col:
            chunk.append(['', '', ''])
        cols_entries.append(chunk)

    header = []
    for _ in range(n_cols):
        header.extend(['Параметр', 'Макс', 'Мин'])
    data = [header]
    for row_idx in range(per_col):
        row = []
        for i in range(n_cols):
            row.extend(cols_entries[i][row_idx])
        data.append(row)

    # Ширины: (label | max | min) * n_cols
    col_widths = []
    slice_w = page_width / n_cols
    for _ in range(n_cols):
        col_widths.extend([slice_w * 0.55, slice_w * 0.225, slice_w * 0.225])

    t = Table(data, colWidths=col_widths)
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('FONTSIZE', (0, 0), (-1, -1), font_size),
        ('LEADING', (0, 0), (-1, -1), font_size + 1),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DDDDDD')),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))
    return t


def _build_stats_flowable(stats_df, headers, page_width, round_map=None):
    """
    Таблица статистики для КОНЦА протокола:
      * шапка: Параметр | Брак | Годные | Макс | Мин | Среднее | СтОткл
      * по каждой колонке спецификации
      * в конце — блок «Общий статус: Годен N / Брак M»
    """
    round_map = round_map or {}

    def _dec(param):
        try:
            return int(round_map.get(param, 2))
        except (TypeError, ValueError):
            return 2

    def _fv(v, param):
        if v is None or pd.isna(v):
            return '-'
        try:
            return f"{float(v):.{_dec(param)}f}"
        except (TypeError, ValueError):
            return str(v)

    # Общий статус
    n_good = n_bad = 0
    total_row = stats_df[stats_df['Parameter'] == 'Общий статус']
    if not total_row.empty:
        tr = total_row.iloc[0]
        n_good = int(tr['Годные']) if pd.notna(tr['Годные']) else 0
        n_bad = int(tr['Брак']) if pd.notna(tr['Брак']) else 0

    data = [['Параметр', 'Брак', 'Годные',
             'Макс', 'Мин', 'Среднее', 'СтОткл']]

    for _, row in stats_df.iterrows():
        param = row['Parameter']
        if param == 'Общий статус':
            continue
        label = headers.get(param, param) if headers else param
        data.append([
            str(label),
            f"{int(row['Брак'])}" if pd.notna(row['Брак']) else '-',
            f"{int(row['Годные'])}" if pd.notna(row['Годные']) else '-',
            _fv(row['Макс'], param),
            _fv(row['Мин'], param),
            _fv(row['Среднее'], param),
            _fv(row['СтОткл'], param),
        ])

    data.append(['', '', '', '', '', '', ''])
    data.append(['ИТОГО ПО ПАРТИИ', '', '', '', '', '', ''])
    data.append(['   Годен', '', str(n_good), '', '', '', ''])
    data.append(['   Брак',  '', str(n_bad),  '', '', '', ''])

    col_w = page_width / 7.0
    t = Table(data, colWidths=[
        col_w * 1.8, col_w * 0.8, col_w * 0.8,
        col_w * 1.0, col_w * 1.0, col_w * 1.0, col_w * 1.0,
    ])
    t.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('FONTSIZE', (0, 0), (-1, -1), 8),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DDDDDD')),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        # Жирный итоговый блок
        ('FONTNAME', (0, len(data) - 4), (-1, -1), 'Arial'),
        ('BACKGROUND', (0, len(data) - 4), (-1, len(data) - 4),
         colors.HexColor('#E8E8E8')),
        ('BACKGROUND', (0, len(data) - 3), (-1, len(data) - 3),
         colors.HexColor('#F0F0F0')),
    ]))
    return t
def create_test_protocol(data_df, status_df, headers, spc_map,
                          view_data, stats_df, measure_id,
                          filename="protocol_test.pdf"):
    data_df = data_df.drop('Status2', axis=1, errors='ignore')

    path = Options.get_measure_protokol_path()
    filename = path + "\\" + filename

    # round_map из spc_map
    round_map = {}
    if spc_map is not None and not spc_map.empty:
        for _, r in spc_map.iterrows():
            rv = r.get('Round')
            if pd.notna(rv):
                try:
                    round_map[str(r['Parameter'])] = int(rv)
                except (TypeError, ValueError):
                    pass

    doc = SimpleDocTemplate(
        filename, pagesize=A4,
        leftMargin=10 * mm, rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=72 * mm,
    )

    elements = []

    # --- Шапка ---
    elements.append(create_header(view_data, measure_id, doc.width))
    elements.append(Spacer(1, 5 * mm))
    elements.append(create_protocol_title(
        measure_id, view_data['Protokol_Type']))

    # --- Основная таблица данных ---
    num_cols = len(data_df.columns)
    col_width = doc.width / num_cols

    header_row = []
    for col in data_df.columns:
        label = _col_label(col) if col in _COL_LABELS \
                else headers.get(col, col)
        header_row.append(Paragraph(label, get_table_header_style()))

    data_rows = []
    for _, row in data_df.iterrows():
        r = []
        for col in data_df.columns:
            if col in ('Positions', 'Numbers', 'Status'):
                r.append(Paragraph(_fmt_num_cell(row[col], 0),
                                    get_test_data_cell_style()))
            else:
                decimals = round_map.get(col, 3)
                r.append(Paragraph(_fmt_num_cell(row[col], decimals),
                                    get_test_data_cell_style()))
        data_rows.append(r)

    main_table = Table(
        [header_row] + data_rows,
        colWidths=[col_width] * num_cols,
        repeatRows=1,
    )
    base_styles = [
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#DDDDDD')),
        ('FONTSIZE', (0, 0), (-1, 0), 7),
        ('FONTSIZE', (0, 1), (-1, -1), 8),
        ('LEADING', (0, 0), (-1, -1), 9),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]
    try:
        highlight_styles = get_highlight_styles(
            data_df, status_df, data_offset=1)
    except Exception as e:
        print(f"[test_protocol] highlight skip: {e}")
        highlight_styles = []
    main_table.setStyle(TableStyle(base_styles + highlight_styles))
    elements.append(main_table)

    # --- Подвал (нормы + статистика), повторяется на каждой стр. ---
    footer_table, total_good, total_bad = _build_combined_footer_table(
        data_df, spc_map, stats_df, doc.width,
        round_map=round_map, font_size=9.6)

    def add_page_footer(canvas, doc_):
        canvas.saveState()

        if footer_table is not None:
            try:
                footer_table.wrapOn(canvas, doc_.width, 150 * mm)
                footer_table.drawOn(canvas, doc_.leftMargin, 12 * mm)
            except Exception as e:
                print(f"[test_protocol] footer draw skip: {e}")

            canvas.setFont('Arial', 9.6)
            canvas.setFillColor(colors.black)
            canvas.drawString(
                doc_.leftMargin, 8 * mm,
                f"ИТОГО по протоколу: "
                f"Годных {total_good}, Брак {total_bad}, "
                f"Всего {total_good + total_bad}")

        canvas.setFont('Arial', 7)
        canvas.drawString(
            doc_.leftMargin, 4 * mm,
            f"Исполнитель: {view_data.get('Operator', '')}")
        canvas.drawRightString(
            doc_.leftMargin + doc_.width, 4 * mm,
            f"Страница {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(elements,
              onFirstPage=add_page_footer,
              onLaterPages=add_page_footer)
    return filename




def get_highlight_styles_test(data_df, status_df):
    """
    Устаревшая обёртка: вся логика живёт в get_highlight_styles.
    Смещение 9 соответствует старому поведению (row_idx + 9).
    """
    return get_highlight_styles(data_df, status_df, data_offset=9)



def get_protocol_title_style():
    """Style for protocol title"""
    return ParagraphStyle(
        'ProtocolTitleStyle',
        fontName='Arial',
        fontSize=12,
        leading=14,
        alignment=1,
        spaceAfter=5 * mm
    )


def get_table_header_style():
    """Style for table column headers"""
    return ParagraphStyle(
        'TableHeaderStyle',
        fontName='Arial',
        fontSize=6,
        leading=9,
        alignment=1,
        wordWrap='CJK'
    )


def get_norm_style():
    """Style for specification limits"""
    return ParagraphStyle(
        'NormStyle',
        fontName='Arial',
        fontSize=8,
        leading=8,
        alignment=1,
        textColor=colors.black,
        backColor=colors.HexColor('#F5F5F5'),
        borderWidth=0.5,
        borderColor=colors.gray,
        borderPadding=(2, 2, 2)
    )


def get_stats_label_style():
    """Style for statistics labels"""
    return ParagraphStyle(
        'StatsLabelStyle',
        fontName='Arial',
        fontSize=8,
        leading=9,
        alignment=1,
        textColor=colors.black,
        backColor=colors.HexColor('#E8E8E8'),
        borderWidth=0.5,
        borderColor=colors.gray,
        borderPadding=(2, 2, 2)
    )


def get_stats_data_style():
    """Style for statistics data cells"""
    return ParagraphStyle(
        'StatsDataStyle',
        fontName='Arial',
        fontSize=8,
        leading=9,
        alignment=1,
        textColor=colors.black,
        backColor=colors.HexColor('#F5F5F5'),
        borderWidth=0.5,
        borderColor=colors.gray,
        borderPadding = (2, 2, 2)
    )


def get_measurement_print_header_style():
    style = getSampleStyleSheet()['Normal']
    style.fontName = 'Courier'
    style.fontSize = 9
    style.leading = 10
    return style


# Функция создания таблицы для распечатки
def create_measurements_table(df, page_width, num_columns=4, approx=False):
    """
        Создает многостолбцовую таблицу измерений для PDF-отчета.

        Функция группирует данные из DataFrame по позициям и номерам, формируя
        отформатированные блоки с заголовками и таблицами значений. Готовые блоки
        распределяются по колонкам на странице.

        Параметры:
        ----------
        df : pandas.DataFrame
            Датафрейм с данными, содержащий следующие столбцы:
            - Positions: идентификатор позиции
            - Numbers: номер образца
            - f_center: значение точности (ppm)
            - Temps: температура (°C)
            - F_: значение F (ppm)
            - R: сопротивление (Ом)

        page_width : float
            Ширина страницы в единицах ReportLab (обычно мм*inch)

        num_columns : int, optional
            Количество колонок на странице (по умолчанию 2)

        Возвращает:
        ----------
        reportlab.platypus.Table
            Таблица, готовая для добавления в PDF-документ

        Зависимости:
        ------------
        - reportlab.lib.styles.ParagraphStyle
        - reportlab.platypus.Table/TableStyle
        - reportlab.lib.units.mm
        - reportlab.lib.colors

        Примечания:
        -----------
        1. Требуется предварительное определение стиля get_measurement_header_style
        2. Элементы группируются по ('Positions', 'Numbers')
        3. В заголовке группы отображается среднее значение f_center
        4. Для незаполненных ячеек в последней строке добавляются пустые блоки
        5. Ширина колонок таблиц рассчитывается пропорционально:
           - Температура: 30%
           - F: 35%
           - R: 35%
        """
    # Группируем данные по позициям и номерам
    df = df.sort_values(by=['Numbers','Temps'], ascending=True).copy()
    grouped = df.groupby(['Numbers', 'Positions',])

    # Создаем список элементов для размещения
    elements = []
    for (num, pos), group in grouped:
        # Формируем заголовок группы
        f_center = group['f_center'].values[0]
        header_text = f"Позиция: {pos}, Номер: {num}, Точность: {f_center:.3f} ppm"
        header = Paragraph(header_text, get_measurement_print_header_style())

        # Формируем таблицу данных
        data = [["Темп., °C", "F, ppm", "R, Ом"]]
        for _, row in group.iterrows():
            if approx:
                data.append([
                    f"{row['Temps']:.0f}",
                    f"{row['f_interp']:.2f}",
                    f"{row['R']:.1f}"
                ])
            else:
                data.append([
                    f"{row['Temps']:.0f}",
                    f"{row['F_']:.2f}",
                    f"{row['R']:.1f}"
                ])

        # Создаем таблицу
        table_width = (page_width - 20 * mm) / num_columns
        col_widths = [table_width * 0.3, table_width * 0.35, table_width * 0.35]
        table = Table(data, colWidths=col_widths)
        table.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (-1, -1), 'Courier'),
            ('FONTSIZE', (0, 0), (-1, -1), 7),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ('BACKGROUND', (0, 0), (-1, 0), colors.lightblue),
            ('LEFTPADDING', (0, 0), (-1, -1), 3),
            ('RIGHTPADDING', (0, 0), (-1, -1), 3),
            ('TOPPADDING', (0, 0), (-1, -1), 0),  # 3. Убираем вертикальные отступы
            ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ]))

        # Объединяем заголовок и таблицу в один элемент
        block = [
            header,
            Spacer(1, 6),
            table
        ]
        elements.append(block)

    # Формируем финальную таблицу размещения
    main_data = []
    current_row = []
    for element in elements:
        current_row.append(element)
        if len(current_row) == num_columns:
            main_data.append(current_row)
            current_row = []

    # Добавляем незаполненные ячейки для последней строки
    if current_row:
        while len(current_row) < num_columns:
            current_row.append('')
        main_data.append(current_row)

    # Создаем таблицу размещения
    col_widths = [(page_width - 20 * mm) / num_columns] * num_columns
    main_table = Table(main_data, colWidths=col_widths)
    main_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 0),  # 6. Убираем вертикальные отступы
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    return main_table


# Создания протокола распечатки
def generate_pdf(measure_id, view_data, df, filename, num_columns=4):
    """
        Генерирует PDF-протокол с измерениями и метаданными

        Структура документа:
        1. Заголовок протокола
        2. Блок с метаданными и QR-кодом
        3. Таблица измерений с группировкой по позициям

        Параметры:
        ----------
        measure_id : str
            Уникальный идентификатор измерения
        view_data : dict
            Словарь с метаданными для отображения:
            - "operator": имя оператора
            - "equipment": название оборудования
            - "comment": комментарий
            - "qr_data": данные для QR-кода
        df : pandas.DataFrame
            Таблица с измерениями, содержащая колонки:
            - Positions, Numbers (для группировки)
            - Temps, F_, R (данные измерений)
            - f_center (точность)
        filename : str
            Базовое имя файла (будет дополнено временной меткой)
        num_columns : int, optional
            Количество колонок в таблице измерений (по умолчанию 2)

        Возвращает:
        ----------
        str
            Полный путь к сохраненному файлу

        Зависимости:
        ------------
        - reportlab.lib.pagesizes.A4
        - reportlab.platypus.SimpleDocTemplate
        - Вспомогательные функции:
            * create_protocol_title()
            * create_header()
            * create_measurements_table()
        - Класс Options с методом get_measure_protokol_path()

        Примечания:
        -----------
        1. Файл сохраняется в каталог, возвращаемый Options.get_measure_protokol_path()
        2. Имя файла формируется по шаблону: {measure_id}_YYYY-MM-DD_HH-MM-SS.pdf
        3. Таблица измерений автоматически разбивается на колонки
        4. Требует предварительной настройки стилей для заголовков
        """
    filename = Options.get_measure_protokol_path() + "\\" + filename
    doc = SimpleDocTemplate(filename, pagesize=A4)
    story = []

    # Добавляем основной заголовок
    title = create_protocol_title(measure_id, "резонаторов")
    story.append(title)
    story.append(Spacer(1, 12))

    # Добавляем заголовок с данными и QR
    header = create_header(view_data, measure_id, A4[0])
    story.append(header)
    story.append(Spacer(1, 24))
    if view_data['TCH_Type'] == 'Аппроксимация':
        approx = True
    else:
        approx = False
    # Добавляем таблицу с измерениями
    measurements_table = create_measurements_table(df, A4[0], num_columns, approx)
    story.append(measurements_table)

    doc.build(story)
    return filename

def _build_norms_footer_table(data_df, spc_map, page_width,
                               font_size=10):
    """
    Горизонтальная таблица норм для подвала каждой страницы.

    * Колонки и ширины — ровно как у main_table
      (тот же порядок data_df.columns, page_width / n_cols);
    * Значения норм — БЕЗ префиксов «Макс:»/«Мин:», bold, font_size
      (по умолчанию 10 = 2× от прежних 5);
    * Метки «Макс» / «Мин» вынесены в первую не-параметрическую
      колонку (обычно «Позиции»): верхняя ячейка — «Макс»,
      нижняя — «Мин»;
    * Остальные не-параметрические колонки (Numbers, Status)
      SPAN'ятся по вертикали и остаются пустыми.
    """
    if data_df is None or data_df.empty:
        return None
    if spc_map is None or spc_map.empty:
        return None

    spc_dict = {}
    for _, row in spc_map.iterrows():
        spc_dict[str(row['Parameter'])] = {
            'Max': row['Max'],
            'Min': row['Min'],
        }

    columns = list(data_df.columns)
    num_cols = len(columns)
    if num_cols == 0:
        return None

    col_w = page_width / num_cols

    norm_style = ParagraphStyle(
        'TestNormStyle',
        fontName='Arial',
        fontSize=font_size,
        leading=font_size + 2,
        alignment=TA_CENTER,
        wordWrap='CJK',
    )
    label_style = ParagraphStyle(
        'TestNormLabelStyle',
        fontName='Arial',
        fontSize=font_size,
        leading=font_size + 2,
        alignment=TA_CENTER,
        wordWrap='CJK',
    )

    # Индексы колонок-параметров и не-параметров
    param_indices = []
    non_param_indices = []
    for idx, col in enumerate(columns):
        if col in spc_dict:
            param_indices.append(idx)
        else:
            non_param_indices.append(idx)

    # Первая не-параметрическая колонка получает метки Макс/Мин.
    # Это обычно «Позиции» — самая левая колонка таблицы данных.
    label_col_idx = non_param_indices[0] if non_param_indices else None

    max_row = []
    min_row = []

    for idx, col in enumerate(columns):
        if col in spc_dict:
            mx = spc_dict[col]['Max']
            mn = spc_dict[col]['Min']
            mx_s = (f"{mx:.4g}"
                    if mx is not None and not pd.isna(mx) else '')
            mn_s = (f"{mn:.4g}"
                    if mn is not None and not pd.isna(mn) else '')
            max_row.append(Paragraph(f"<b>{mx_s}</b>", norm_style))
            min_row.append(Paragraph(f"<b>{mn_s}</b>", norm_style))
        elif idx == label_col_idx:
            max_row.append(Paragraph("<b>Макс</b>", label_style))
            min_row.append(Paragraph("<b>Мин</b>", label_style))
        else:
            max_row.append('')
            min_row.append('')

    table = Table([max_row, min_row],
                  colWidths=[col_w] * num_cols)

    styles = [
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('FONTSIZE', (0, 0), (-1, -1), font_size),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BACKGROUND', (0, 0), (-1, -1),
         colors.HexColor('#F5F5F5')),
        ('LEFTPADDING', (0, 0), (-1, -1), 3),
        ('RIGHTPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
    ]

    # Остальные не-параметры SPAN'ятся вертикально
    for idx in non_param_indices:
        if idx == label_col_idx:
            continue
        styles.append(('SPAN', (idx, 0), (idx, 1)))

    table.setStyle(TableStyle(styles))
    return table



def create_calibration_protocol(result, numbers, Type_str, filename_prefix="temperature_calibration"):
    """
    Создает PDF-протокол коррекции температуры согласно требованиям ГОСТ РФ.

    Функция генерирует официальный протокол калибровки температурных датчиков
    с таблицей данных и соответствующим оформлением. После создания файла
    автоматически открывает его в программе для просмотра PDF.

    Parameters
    ----------
    result : pandas.DataFrame
        DataFrame с данными калибровки, содержащий колонки:
        - 'Temp': измеренная температура
        - 'T_REF': эталонное значение температуры
        - 'DELTA_T': разница между измеренным и эталонным значением
    numbers : list or str
        Список номеров контрольных образцов или строка с перечислением номеров
        (например, ['AP5517', 'AP5527'] или "AP5517, AP5527")
    Type_str : str
        Строка с описанием типа датчика (например, "Тип RK")
    filename_prefix : str, optional
        Префикс для имени файла (по умолчанию "temperature_calibration")

    Returns
    -------
    None
        Функция не возвращает значений, но создает PDF-файл и открывает его.

    Raises
    ------
    FileNotFoundError
        Если не удается найти или создать указанный файл
    Exception
        При возникновении других ошибок в процессе создания PDF

    Examples
    --------
    >>> import pandas as pd
    >>> data = pd.DataFrame({
    ...     'Temp': [-60, -55],
    ...     'T_REF': [-63.0723, -58.085],
    ...     'DELTA_T': [-3.07227, -3.085]
    ... })
    >>> numbers = ['AP5517', 'AP5527']
    >>> create_calibration_protocol(data, numbers, "Тип RK")

    Notes
    -----
    Для корректной работы необходимо установить следующие библиотеки:
    - reportlab
    - pandas

    Функция использует шрифт Arial для соответствия требованиям ГОСТ РФ.
    Все числовые значения округляются до одного знака после запятой.
    Имя файла содержит текущую дату и время.
    """
    try:
        # Преобразование номеров образцов в строку с разделителем-запятой
        if isinstance(numbers, list):
            numbers_str = ', '.join(numbers)
        else:
            numbers_str = str(numbers)

        # Округление числовых значений до одного знака после запятой
        result_rounded = result.copy()
        for col in ['Temp', 'T_REF', 'DELTA_T']:
            if col in result_rounded.columns:
                result_rounded[col] = result_rounded[col].round(1)

        # Создание имени файла с текущей датой и временем
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename_prefix}_{current_time}.pdf"
        path = Options.get_measure_protokol_path()
        filename = path + "\\Correction\\" + filename
        # Создание PDF-документа
        doc = SimpleDocTemplate(filename, pagesize=A4)
        styles = getSampleStyleSheet()

        # Создание стилей с использованием Arial
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontName='Arial',
            fontSize=14,
            alignment=TA_CENTER,
            spaceAfter=30
        )

        info_style = ParagraphStyle(
            'CustomInfo',
            parent=styles['Normal'],
            fontName='Arial',
            fontSize=12,
            alignment=TA_LEFT,
            spaceAfter=12
        )

        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontName='Arial',
            fontSize=10,
            alignment=TA_LEFT
        )

        story = []

        # Добавление заголовка
        title = Paragraph("Данные коррекции температуры в температурной камере по контрольным образцам", title_style)
        story.append(title)

        # Добавление информации об образцах и типе датчика
        samples_info = Paragraph(f"Номера контрольных образцов: {numbers_str}", info_style)
        sensor_info = Paragraph(f"Тип датчика: {Type_str}", info_style)
        story.append(samples_info)
        story.append(sensor_info)
        story.append(Spacer(1, 20))

        # Подготовка данных таблицы
        df = result_rounded[['Temp', 'T_REF', 'DELTA_T']].copy()
        df.columns = ['Температура, °C', 'Эталонное значение, °C', 'Коррекция, °C']
        data = [df.columns.tolist()] + df.values.tolist()

        # Создание таблицы
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Arial'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTNAME', (0, 1), (-1, -1), 'Arial'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(table)
        story.append(Spacer(1, 30))

        # Добавление подписей
        signatures = [
            Paragraph("Исполнитель: _________________ / ФИО /", normal_style),
            Spacer(1, 20),
            Paragraph("Дата: _________________", normal_style)
        ]
        story.extend(signatures)

        # Генерация PDF
        doc.build(story)

        # Открытие файла
        if os.name == 'nt':  # Для Windows
            os.startfile(filename)
        else:  # Для MacOS и Linux
            subprocess.call(['open', filename] if sys.platform == 'darwin' else ['xdg-open', filename])

        print(f"Протокол успешно создан и сохранен как {filename}")

    except FileNotFoundError as e:
        print(f"Ошибка: не удается создать или найти файл {filename}")
        raise e
    except Exception as e:
        print(f"Произошла ошибка при создании протокола: {str(e)}")
        raise e


def create_accuracy_correction_protocol(data, filename_prefix="accuracy_correction"):
    """
    Создает PDF-протокол коррекции точности настройки согласно требованиям ГОСТ РФ.

    Функция генерирует официальный протокол коррекции точности настройки
    с таблицей данных и соответствующим оформлением. После создания файла
    автоматически открывает его в программе для просмотра PDF.

    Parameters
    ----------
    data : pandas.DataFrame
        DataFrame с данными коррекции точности настройки, содержащий колонки:
        - 'Numbers': номера образцов
        - 'delta_Fs': коррекция Fs
        - 'delta_FL': коррекция FL
        - 'delta_FL_Num': численная коррекция FL
        - 'delta_Fint': коррекция Fint
    filename_prefix : str, optional
        Префикс для имени файла (по умолчанию "accuracy_correction")

    Returns
    -------
    None
        Функция не возвращает значений, но создает PDF-файл и открывает его.

    Raises
    ------
    FileNotFoundError
        Если не удается найти или создать указанный файл
    Exception
        При возникновении других ошибок в процессе создания PDF
    """
    try:
        # Округление числовых значений до одного знака после запятой
        data_rounded = data.copy()
        for col in ['delta_Fs', 'delta_FL', 'delta_FL_Num', 'delta_Fint']:
            if col in data_rounded.columns:
                data_rounded[col] = data_rounded[col].round(1)

        # Создание имени файла с текущей датой и временем
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename_prefix}_{current_time}.pdf"
        path = Options.get_measure_protokol_path()
        filename = path + "\\Correction\\" + filename
        # Создание PDF-документа
        doc = SimpleDocTemplate(filename, pagesize=A4)
        styles = getSampleStyleSheet()

        # Создание стилей с использованием Arial
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontName='Arial',
            fontSize=14,
            alignment=TA_CENTER,
            spaceAfter=30
        )

        info_style = ParagraphStyle(
            'CustomInfo',
            parent=styles['Normal'],
            fontName='Arial',
            fontSize=12,
            alignment=TA_LEFT,
            spaceAfter=12
        )

        normal_style = ParagraphStyle(
            'CustomNormal',
            parent=styles['Normal'],
            fontName='Arial',
            fontSize=10,
            alignment=TA_LEFT
        )

        story = []

        # Добавление заголовка
        title = Paragraph("Протокол коррекции измерения точности настройки", title_style)
        story.append(title)
        story.append(Spacer(1, 20))

        # Подготовка данных таблицы
        df = data_rounded[['Numbers', 'delta_Fs', 'delta_FL', 'delta_FL_Num', 'delta_Fint']].copy()
        df.columns = ['№ образца', 'ΔFs, Гц', 'ΔFL, Гц', 'ΔFL (числ.), Гц', 'ΔFint, Гц']
        data_table = [df.columns.tolist()] + df.values.tolist()

        # Создание таблицы
        table = Table(data_table, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Arial'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('FONTNAME', (0, 1), (-1, -1), 'Arial'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('GRID', (0, 0), (-1, -1), 1, colors.black)
        ]))
        story.append(table)
        story.append(Spacer(1, 30))

        # Добавление подписей
        signatures = [
            Paragraph("Исполнитель: _________________ / ФИО /", normal_style),
            Spacer(1, 20),
            Paragraph("Дата: _________________", normal_style)
        ]
        story.extend(signatures)

        # Генерация PDF
        doc.build(story)

        # Открытие файла
        if os.name == 'nt':  # Для Windows
            os.startfile(filename)
        else:  # Для MacOS и Linux
            subprocess.call(['open', filename] if sys.platform == 'darwin' else ['xdg-open', filename])

        print(f"Протокол успешно создан и сохранен как {filename}")

    except FileNotFoundError as e:
        print(f"Ошибка: не удается создать или найти файл {filename}")
        raise e
    except Exception as e:
        print(f"Произошла ошибка при создании протокола: {str(e)}")
        raise e

from reportlab.platypus import Flowable
from reportlab.pdfbase.pdfmetrics import stringWidth


# ============================================================================
# ПРЕДЪЯВИТЕЛЬСКИЙ ПРОТОКОЛ (по образцу FastReport TfrxReport)
# ============================================================================

# ============================================================================
# Хелперы для предъявительского протокола
# ============================================================================

def _fnum(v, d=4):
    """Компактное числовое представление."""
    if v is None:
        return '—'
    try:
        if pd.isna(v):
            return '—'
    except (TypeError, ValueError):
        pass
    if isinstance(v, float):
        return f"{v:.{d}g}"
    return str(v)


class _RotatedText(Flowable):
    """Текст, повёрнутый на 90° — для вертикальных заголовков."""
    def __init__(self, text, width, height, font='Arial', size=7,
                 bold=False):
        Flowable.__init__(self)
        self.text = text
        self.width = width
        self.height = height
        self.font = font
        self.size = size
        self.bold = bold

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.translate(self.width, 0)
        c.rotate(90)
        c.setFont(self.font, self.size)
        tw = c.stringWidth(self.text, self.font, self.size)
        x = max(0, (self.height - tw) / 2)
        y = (self.width - self.size) / 2 + 2
        if self.bold:
            c.drawString(x, y, self.text)
            c.drawString(x + 0.3, y, self.text)
        else:
            c.drawString(x, y, self.text)
        c.restoreState()


# ============================================================================
# Предъявительский протокол
# ============================================================================
# ============================================================================
# Каждый pn ссылается на:
#   'field'    — колонка в psidata / в data_df (значение измерения);
#   'norm_max' / 'norm_min' — поле в specification с базовой (ТУ) нормой;
#   'tol'      — поле с допуском (технологический запас);
#   'tol_abs'  — True: допуск в абсолютных ед-цах, False: в %;
#   'suffix'   — единицы измерения для заголовка.
#
# Порядок в _TU_ORDER = порядок колонок в печатном протоколе:
#   1. F       — Допуск на точность настройки, Гц
#   2. R       — Динамическое сопротивление, Ом
#   3. Fmaxm   — Относительное отклонение частоты, 10E-6
#   4. Cq      — Динамическая ёмкость, фФ
#   5. Q       — Добротность, x1000
#   6. C0      — Статическая ёмкость, пФ
#   7. Rsp1    — Ослабление нежелательных резонансов, дБ
