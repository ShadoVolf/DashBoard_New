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
    if view_data['F_correction']:
        corr_type_str = corr_type_str + ' Точность настройки'
    if view_data['TCH_correction']:
        corr_type_str = corr_type_str + '  ТЧХ'
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

def get_highlight_styles(data_df, status_df, data_offset=9):
    """
    Цветовая разметка брака:

      * Фон всей строки брака       — светло-жёлтый  (#FFFACD);
      * Позиции / Номер / Статус    — тёмный оранжевый (#FF9933);
      * Забракованный параметр      — тёмный оранжевый (#FF9933).

    Тёмный оранжевый «перекрывает» жёлтый только в конкретных
    ячейках, остальная строка остаётся жёлтой.
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

    for row_idx, position in enumerate(data_df['Positions']):
        status_row = status_df[status_df['Positions'] == position]
        if status_row.empty:
            continue

        row_is_bad = not bool(status_row['Status'].values[0])
        y = row_idx + data_offset

        if row_is_bad:
            # 1. Вся строка — светло-жёлтая
            styles.append(
                ('BACKGROUND', (0, y), (last_col_idx, y), ROW_BAD))
            # 2. Служебные — тёмный оранжевый
            for idx in (position_col_idx, number_col_idx, status_col_idx):
                styles.append(
                    ('BACKGROUND', (idx, y), (idx, y), SERVICE_BAD))

        # 3. Забракованные параметры — тёмный оранжевый
        for param in data_df.columns:
            if param in ('Positions', 'Numbers', 'Status', 'Status2'):
                continue
            status_key = f'{param}_status'
            if status_key not in status_row.columns:
                continue
            if not bool(status_row[status_key].values[0]):
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
    """Generate styles for status-based highlighting"""
    styles = []
    try:
        status_col_idx = data_df.columns.get_loc('Status')
        number_col_idx = data_df.columns.get_loc('Numbers')
        position_col_idx = data_df.columns.get_loc('Positions')
    except KeyError as e:
        raise ValueError(f"Missing required column: {e}")

    for row_idx, position in enumerate(data_df['Positions']):
        status_row = status_df[status_df['Positions'] == position]
        if status_row.empty:
            continue

        # Highlight main columns if failed
        if not status_row['Status'].values[0]:
            for col_idx in [status_col_idx, number_col_idx, position_col_idx]:
                styles.append((
                    'BACKGROUND',
                    (col_idx, row_idx + 9),
                    (col_idx, row_idx + 9),
                    colors.orange
                ))

        # Highlight parameter columns
        for param in data_df.columns:
            if param in ['Positions', 'Numbers', 'Status', 'Status2']:
                continue

            if not status_row[f"{param}_status"].values[0]:
                param_idx = data_df.columns.get_loc(param)
                styles.append((
                    'BACKGROUND',
                    (param_idx, row_idx + 9),
                    (param_idx, row_idx + 9),
                    colors.orange
                ))
    return styles



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
# ----------------------------------------------------------------------------
_TU_PARAMS = {
    1: {'field': 'F',     'norm_max': 'Fmax',    'norm_min': 'Fmin',
        'tol': 'DopuskF',  'tol_abs': True,  'suffix': ', Гц (Т=87С)'},
    2: {'field': 'R',     'norm_max': 'Rmax',    'norm_min': 'Rmin',
        'tol': 'DopuskR',  'tol_abs': False, 'suffix': ', Ом (Т=87С)'},
    3: {'field': 'Fmaxm', 'norm_max': 'Fmaxmax', 'norm_min': 'Fmaxmin',
        'tol': 'DopuskFi', 'tol_abs': False, 'suffix': ', 10E-6 (Т=87С)'},
    4: {'field': 'Cq',    'norm_max': 'Cqmax',   'norm_min': 'Cqmin',
        'tol': 'DopuskCq', 'tol_abs': False, 'suffix': ', фФ (Т=87С)'},
    5: {'field': 'Q',     'norm_max': 'Qmax',    'norm_min': 'Qmin',
        'tol': 'DopuskQ',  'tol_abs': False, 'suffix': ', x1000 (Т=87С)'},
    6: {'field': 'C0',    'norm_max': 'C0max',   'norm_min': 'C0min',
        'tol': 'DopuskC0', 'tol_abs': False, 'suffix': ', пФ (Т=87С)'},
    7: {'field': 'Rsp1',  'norm_max': 'Rsp1max', 'norm_min': 'Rsp1min',
        'tol': 'DopuskSR', 'tol_abs': False, 'suffix': ', дБ'},
}
_TU_ORDER = [1, 2, 3, 4, 5, 6, 7]
from reportlab.pdfbase.pdfmetrics import stringWidth


# ============================================================================
# Хелперы
# ============================================================================
def _cs(size=7.5):
    return ParagraphStyle(
        f'TCS{size}', fontName='Arial', fontSize=size,
        leading=size + 2, alignment=TA_CENTER, wordWrap='CJK')


def _tu_s(tu_row, field):
    v = tu_row.get(field)
    if v is None:
        return ''
    try:
        if pd.isna(v):
            return ''
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    return '' if s.lower() in ('none', 'nan', '') else s



def _autosize(text, max_len, sizes=(8.5, 8, 7.5, 7, 6.5, 6, 5.5, 5)):
    """Наименьший шрифт из sizes, при котором text помещается в max_len."""
    for s in sizes:
        if stringWidth(text, 'Arial', s) <= max_len:
            return s
    return sizes[-1]


class _RotText(Flowable):
    """Повёрнутый текст. Автоподбор размера шрифта, при нехватке —
    перенос по словам на несколько вертикальных строк."""
    def __init__(self, text, width, height, bold=False):
        Flowable.__init__(self)
        self.width = width
        self.height = height
        self.bold = bold
        self.lines, self.size = _fit_rotated(text, height - 6)
        self.leading = self.size + 2

    def wrap(self, aw, ah):
        return self.width, self.height

    def draw(self):
        c = self.canv
        c.saveState()
        c.translate(self.width, 0)
        c.rotate(90)
        c.setFont('Arial', self.size)

        total_h = len(self.lines) * self.leading
        y = (self.width - total_h) / 2 + total_h - self.leading

        for line in self.lines:
            tw = stringWidth(line, 'Arial', self.size)
            x = max(2, (self.height - tw) / 2)
            if self.bold:
                c.drawString(x, y, line)
                c.drawString(x + 0.25, y, line)
            else:
                c.drawString(x, y, line)
            y -= self.leading
        c.restoreState()


def _fit_rotated(text, max_len):
    """
    Возвращает (lines, font_size). Сначала пытается вписать одной
    строкой с авторазмером; если не получается — переносит по словам
    шрифтом 6.5.
    """
    # 1 строка
    for s in (8.5, 8, 7.5, 7, 6.5, 6):
        if stringWidth(text, 'Arial', s) <= max_len:
            return [text], s
    # Много строк
    size = 6.5
    words = text.split()
    lines, cur = [], ''
    for w in words:
        test = (cur + ' ' + w).strip()
        if stringWidth(test, 'Arial', size) <= max_len:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [text], size


def _get_norm(df, field, col):
    """Достать значение из spc_map(_otk) по Parameter=field, колонка col."""
    if df is None or df.empty:
        return None
    sub = df[df['Parameter'] == field]
    if sub.empty:
        return None
    return sub.iloc[0].get(col)


def _param_ok(v, pn, spc_row):
    cfg = _TU_PARAMS.get(pn)
    if not cfg:
        return True
    fv = v
    try:
        fv = float(v) if v is not None else None
    except (TypeError, ValueError):
        fv = None
    if fv is None or pd.isna(fv):
        return False
    mx = spc_row.get(cfg['norm_max'])
    mn = spc_row.get(cfg['norm_min'])
    try:
        mx = float(mx) if mx not in (None, 'no', '') else None
    except (TypeError, ValueError):
        mx = None
    try:
        mn = float(mn) if mn not in (None, 'no', '') else None
    except (TypeError, ValueError):
        mn = None
    if mx is not None and fv > mx:
        return False
    if mn is not None and fv < mn:
        return False
    return True


# ============================================================================
# Предъявительский протокол
# ============================================================================
import os  # Убедитесь, что os импортирован в начале файла

import os  # Убедитесь, что os импортирован

import os  # Убедитесь, что os импортирован в начале файла


def create_presentation_protocol(data_df, status_df, view_data, tu_data,
                                 presentation_params, spc_row,
                                 measure_id, filename="presentation.pdf",
                                 measure_protokol_id=None):
    from reportlab.lib.pagesizes import landscape

    page_w, page_h = landscape(A4)
    margin = 12 * mm
    usable_w = page_w - 2 * margin
    n = len(presentation_params)
    if n == 0:
        raise ValueError("Нет параметров для протокола")

    story = []

    # ======================= 1. ШАПКА =======================
    # Логотип
    logo_path = os.path.join('Pictures', 'Morion_Logo.png')
    if os.path.exists(logo_path):
        logo_img = Image(logo_path, width=12 * mm, height=12 * mm)
    else:
        logo_img = Spacer(1, 1)

    logo_p = Paragraph('<b>АО "Морион"</b>',
                       ParagraphStyle('PLogo', fontName='Arial', fontSize=13, leading=15, leftIndent=5))

    left_block = Table([[logo_img, logo_p]], colWidths=[14 * mm, None])
    left_block.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    # Заголовок (по центру)
    title_p = Paragraph("Протокол № ___________________________<br/>от ________________",
                        ParagraphStyle('PHTitle', fontName='Arial', fontSize=11, leading=14, alignment=TA_CENTER))

    # QR-код и ID (справа)
    qr_data = str(measure_protokol_id) if measure_protokol_id else str(measure_id)
    try:
        qr_img = Image(generate_qr_code(qr_data), width=16 * mm, height=16 * mm)
    except Exception:
        qr_img = Spacer(1, 1)

    qr_text = Paragraph(qr_data, ParagraphStyle('QRText', fontName='Arial', fontSize=8, alignment=TA_CENTER))

    qr_block = Table([[qr_img], [qr_text]], colWidths=[18 * mm])
    qr_block.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    top = Table([[left_block, title_p, qr_block]],
                colWidths=[usable_w * 0.33, usable_w * 0.40, usable_w * 0.27])
    top.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(top)
    story.append(Spacer(1, 3 * mm))

    # Текст шапки (без строки с извещением; «на соответствие…» перенесено в первую строку)
    header_text = f"""
    Предъявительских испытаний изделий: <b>{view_data.get('Spc_Text', '—')}</b> на соответствие требованиям технических условий <b>{view_data.get('TU', '—')}</b><br/>
    Договор № ________________________ для организации _______________<br/>
    Кварцевые резонаторы изготовлены в эквиваленте типа <b>{view_data.get('TGK', '—')}</b><br/>
    Внешний вид и маркировка соответствуют ТУ, посторонние частицы отсутствуют.<br/>
    МСК № <b>{view_data.get('MSK', '—')}</b> &nbsp;&nbsp;&nbsp;&nbsp; Дата изготовления <b>{view_data.get('Date', '—')}</b>
    """
    header_style = ParagraphStyle('HeaderText', fontName='Arial', fontSize=9.5, leading=11.5, spaceAfter=3)
    story.append(Paragraph(header_text, header_style))
    story.append(Spacer(1, 2 * mm))

    # ======================= 2. ТАБЛИЦА =======================
    w_num = 45  # Увеличили ширину для текста "Нормы ТУ/ОТК"
    w_res = 55  # Увеличили ширину для текста "не более/не менее"
    w_param = (usable_w - w_num - w_res) / n
    col_widths = [w_num, w_res] + [w_param] * n

    HDR_H = 120
    s_center = _cs(7)
    s_header = _cs(6.5)
    s_header_left = ParagraphStyle('SHL', fontName='Arial', fontSize=6.5, leading=8, alignment=TA_CENTER,
                                   wordWrap='CJK')

    rows = []

    # Row 0
    r0 = [_RotText("№№", w_num, HDR_H, bold=True),
          _RotText("№ резонатора", w_res, HDR_H, bold=True)]
    for p in presentation_params:
        title = (f"{p['name']}, {p['units']}" if p.get('units') else p['name'])
        r0.append(_RotText(title, w_param, HDR_H, bold=True))
    rows.append(r0)

    # Row 1 — Нормы ТУ (не более)
    r1 = [Paragraph("<b>Нормы ТУ</b>", s_header_left),
          Paragraph("<b>не более</b>", s_header_left)]
    for p in presentation_params:
        r1.append(Paragraph(_fnum(p['max_tu']), s_center))
    rows.append(r1)

    # Row 2 — Нормы ТУ (не менее)
    r2 = ["", Paragraph("<b>не менее</b>", s_header_left)]
    for p in presentation_params:
        r2.append(Paragraph(_fnum(p['min_tu']), s_center))
    rows.append(r2)

    # Row 3 — Нормы ОТК (не более)
    r3 = [Paragraph("<b>Нормы ОТК</b>", s_header_left),
          Paragraph("<b>не более</b>", s_header_left)]
    for p in presentation_params:
        r3.append(Paragraph(_fnum(p['max_otk']), s_center))
    rows.append(r3)

    # Row 4 — Нормы ОТК (не менее)
    r4 = ["", Paragraph("<b>не менее</b>", s_header_left)]
    for p in presentation_params:
        r4.append(Paragraph(_fnum(p['min_otk']), s_center))
    rows.append(r4)

    # Row 5 — № п.п. требований ТУ
    tu_name = tu_data.get('tu_name', '') or ''
    label_tu = (f"<b>№ п.п. требований<br/>ТУ {tu_name}</b>" if tu_name else "<b>№ п.п. требований ТУ</b>")
    r5 = [Paragraph(label_tu, s_header_left), Spacer(1, 1)]
    for p in presentation_params:
        r5.append(Paragraph(p['norm_p'] or "—", s_header))
    rows.append(r5)

    # Row 6 — № п.п. методов контроля
    r6 = [Paragraph("<b>№ п.п. методов<br/>контроля</b>", s_header_left), Spacer(1, 1)]
    for p in presentation_params:
        r6.append(Paragraph(p['cntrl'] or "—", s_header))
    rows.append(r6)

    header_rows = len(rows)

    # Данные
    for idx, (_, dr) in enumerate(data_df.iterrows(), 1):
        row = [Paragraph(str(idx), s_center), Paragraph(str(dr.get('Numbers', '')), s_center)]
        for p in presentation_params:
            v = dr.get(p['param']) if p['param'] in data_df.columns else None
            row.append(Paragraph(_fnum(v, 3), s_center))
        rows.append(row)

    table = Table(rows, colWidths=col_widths, repeatRows=header_rows)
    styles = [
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#D9E2F3')),
        ('BACKGROUND', (0, 1), (-1, 6), colors.HexColor('#F2F2F2')),

        # Объединяем ячейки "Нормы ТУ" и "Нормы ОТК" по вертикали (по 2 строки)
        ('SPAN', (0, 1), (0, 2)),
        ('SPAN', (0, 3), (0, 4)),

        # Объединение первых двух колонок для строк 5 и 6
        ('SPAN', (0, 5), (1, 5)),  # № п.п. требований ТУ
        ('SPAN', (0, 6), (1, 6)),  # № п.п. методов контроля
    ]
    table.setStyle(TableStyle(styles))
    story.append(table)
    story.append(Spacer(1, 5 * mm))

    # ======================= 3. ЗАКЛЮЧЕНИЕ =======================
    n_total = len(data_df)
    spc_text = view_data.get('Spc_Text', '')
    tu_text = view_data.get('TU', '')

    concl = ParagraphStyle('PC', fontName='Arial', fontSize=9.5, leading=12, alignment=TA_LEFT)

    # Заголовок ЗАКЛЮЧЕНИЕ
    story.append(Paragraph("ЗАКЛЮЧЕНИЕ",
                           ParagraphStyle('PCTitle', fontName='Arial', fontSize=11, leading=14, alignment=TA_CENTER,
                                          spaceAfter=5, spaceBefore=5)))

    # Логика вывода номеров
    if n_total < 10 and 'Numbers' in data_df.columns:
        nums_str = ", ".join(data_df['Numbers'].astype(str).tolist())
        prefix_text = f"Изделия <b>{spc_text}</b> за № <b>{nums_str}</b>"
    else:
        prefix_text = f"Изделия <b>{spc_text}</b> в количестве <b>{n_total}</b> шт."

    story.append(Paragraph(
        f"{prefix_text} соответствуют требованиям ТУ <b>{tu_text}</b> и могут быть "
        f"предъявлены военному представительству.", concl))

    story.append(Spacer(1, 3 * mm))

    story.append(Paragraph(
        f"Изделия за №№ __________________________________ "
        f"не соответствуют требованиям ТУ <b>{tu_text}</b> "
        f"и подлежат возврату изготовителю.", concl))

    story.append(Spacer(1, 10 * mm))

    # ======================= 4. ПОДПИСИ =======================
    sig_data = [
        [Paragraph("Представитель ОТК", concl), Spacer(1, 1), Spacer(1, 1), Spacer(1, 1)],
        [Spacer(1, 1), Paragraph("______________________", concl), Paragraph("______________________", concl),
         Paragraph("Дата __________", concl)],
        [Spacer(1, 1), Paragraph("<font size=7>подпись</font>", concl),
         Paragraph("<font size=7>инициалы, фамилия</font>", concl), Spacer(1, 1)],
    ]
    sig_tbl = Table(sig_data, colWidths=[usable_w * 0.20, usable_w * 0.25, usable_w * 0.30, usable_w * 0.25])
    sig_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ]))
    story.append(sig_tbl)

    # ======================= 5. BUILD =======================
    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont('Arial', 8)
        canvas.setFillColor(colors.HexColor('#555555'))
        canvas.drawRightString(page_w - margin, 5 * mm, f"Лист {canvas.getPageNumber()}")
        canvas.restoreState()

    path = Options.get_measure_protokol_path() + "\\" + filename
    doc = SimpleDocTemplate(
        path, pagesize=landscape(A4),
        leftMargin=margin, rightMargin=margin,
        topMargin=8 * mm, bottomMargin=10 * mm)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return path


def _build_combined_footer_table(data_df, spc_map, stats_df,
                                  page_width, round_map=None,
                                  font_size=9.6):
    """
    Подвал: нормы + статистика, под своими колонками.

    Служебные колонки:
      * Positions (или первая не-параметрическая) — метки строк
        («Макс ТУ», «Мин ТУ», «Брак», «Годных», «Среднее», «СтОткл»,
         «Факт.Макс», «Факт.Мин»);
      * Numbers — пустые ячейки с сохранёнными границами
        (вертикальный SPAN не применяется);
      * Status — только числа: в «Брак» — количество брака,
        в «Годных» — количество годных (без текстовых меток);
      * прочие не-параметры (если появятся) — вертикальный SPAN.
    """
    round_map = round_map or {}
    if data_df is None or data_df.empty:
        return None, 0, 0

    columns = list(data_df.columns)
    num_cols = len(columns)
    if num_cols == 0:
        return None, 0, 0
    col_w = page_width / num_cols

    # Нормы из spc_map
    spc_dict = {}
    if spc_map is not None and not spc_map.empty:
        for _, r in spc_map.iterrows():
            spc_dict[str(r['Parameter'])] = {
                'Max': r['Max'], 'Min': r['Min'],
            }

    # Индексы: параметры vs не-параметры
    param_indices, non_param_indices = [], []
    for idx, col in enumerate(columns):
        if col in spc_dict:
            param_indices.append(idx)
        else:
            non_param_indices.append(idx)
    label_col_idx = non_param_indices[0] if non_param_indices else None

    # Общий итог по протоколу
    stats_by_param = {}
    total_good = total_bad = 0
    if stats_df is not None and not stats_df.empty:
        for _, r in stats_df.iterrows():
            p = r['Parameter']
            if p == 'Общий статус':
                tg, tb = r['Годные'], r['Брак']
                total_good = int(tg) if pd.notna(tg) else 0
                total_bad  = int(tb) if pd.notna(tb) else 0
            else:
                stats_by_param[p] = r

    # Служебные колонки:
    # Numbers — пустые ячейки (границы сохраняются, SPAN не применяется);
    # Status  — итоговые числа без меток.
    SERVICE_VALUES = {
        'Numbers': {},
        'Status': {
            'stat_bad':  str(total_bad),
            'stat_good': str(total_good),
        },
    }

    cell_style = ParagraphStyle(
        'FCell', fontName='Arial', fontSize=font_size,
        leading=font_size + 1, alignment=TA_CENTER, wordWrap='CJK')
    label_style = ParagraphStyle(
        'FLabel', fontName='Arial', fontSize=font_size,
        leading=font_size + 1, alignment=TA_CENTER, wordWrap='CJK')

    def _fmt_col(v, col):
        """Округление значения по round_map[col]; '—' для None/NaN."""
        if v is None:
            return '—'
        try:
            if pd.isna(v):
                return '—'
        except (TypeError, ValueError):
            pass
        if isinstance(v, (int, float)):
            d = int(round_map.get(col, 3))
            try:
                return f"{float(v):.{d}f}"
            except (TypeError, ValueError):
                return str(v)
        return str(v)

    def _fmt_int(v):
        """Целочисленное форматирование; '—' для None/NaN."""
        if v is None:
            return '—'
        try:
            if pd.isna(v):
                return '—'
        except (TypeError, ValueError):
            pass
        try:
            return f"{int(v)}"
        except (TypeError, ValueError):
            return str(v)

    row_defs = [
        ('Макс ТУ',   'norm_max'),
        ('Мин ТУ',    'norm_min'),
        ('Брак',      'stat_bad'),
        ('Годных',    'stat_good'),
        ('Среднее',   'stat_avg'),
        ('СтОткл',    'stat_std'),
        ('Факт.Макс', 'stat_max'),
        ('Факт.Мин',  'stat_min'),
    ]
    stat_field = {
        'stat_bad':  'Брак',
        'stat_good': 'Годные',
        'stat_avg':  'Среднее',
        'stat_std':  'СтОткл',
        'stat_max':  'Макс',
        'stat_min':  'Мин',
    }

    rows = []
    for label, kind in row_defs:
        row = []
        for idx, col in enumerate(columns):
            # --- Колонка меток (Positions) ---
            if idx == label_col_idx:
                row.append(Paragraph(f"<b>{label}</b>", label_style))
                continue

            # --- Numbers / Status: своя ячейка в каждой строке ---
            if col in SERVICE_VALUES:
                if kind in SERVICE_VALUES[col]:
                    val = SERVICE_VALUES[col][kind]
                    if callable(val):
                        val = val()
                    row.append(Paragraph(str(val), cell_style) if val else '')
                else:
                    row.append('')        # пустая ячейка — граница сохранена
                continue

            # --- Прочие не-параметры (нет в spc_dict) ---
            if col not in spc_dict:
                row.append('')
                continue

            # --- Параметры спецификации ---
            if kind in ('norm_max', 'norm_min'):
                v = spc_dict[col]['Max' if kind == 'norm_max' else 'Min']
                row.append(Paragraph(_fmt_col(v, col), cell_style))
            else:
                fld = stat_field[kind]
                if col in stats_by_param:
                    v = stats_by_param[col].get(fld)
                    if kind in ('stat_bad', 'stat_good'):
                        row.append(Paragraph(_fmt_int(v), cell_style))
                    else:
                        row.append(Paragraph(_fmt_col(v, col), cell_style))
                else:
                    row.append('')
        rows.append(row)

    table = Table(rows, colWidths=[col_w] * num_cols)
    styles = [
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('FONTSIZE', (0, 0), (-1, -1), font_size),
        ('GRID', (0, 0), (-1, -1), 0.3, colors.grey),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('BACKGROUND', (0, 0), (-1, 1), colors.HexColor('#E8E8E8')),
        ('BACKGROUND', (0, 2), (-1, -1), colors.HexColor('#FAFAFA')),
    ]

    # ▼ SPAN — только для «прочих» не-параметров
    # (не Numbers/Status/Positions)
    for idx in non_param_indices:
        if idx == label_col_idx:
            continue
        if columns[idx] in SERVICE_VALUES:
            continue
        styles.append(('SPAN', (idx, 0), (idx, len(rows) - 1)))

    table.setStyle(TableStyle(styles))
    return table, total_good, total_bad


def create_psi_protocol(data_df, status_df, view_data, tu_data,
                        presentation_params, spc_row,
                        measure_id, filename="psi.pdf",
                        measure_protokol_id=None):
    """
    Создает PDF-протокол ПСИ (Приемо-сдаточные испытания) по форме МК.10.602Ф.
    Отличия от предъявительского:
      - Нет логотипа и надписи "АО Морион"
      - Другое заключение (подлежат возврату ОТК)
      - Подпись Представителя ВП
      - Нормы ОТК и ТУ разнесены на 2 строки: «Не более» и «Не менее»
    """
    from reportlab.lib.pagesizes import landscape

    page_w, page_h = landscape(A4)
    margin = 12 * mm
    usable_w = page_w - 2 * margin
    n = len(presentation_params)
    if n == 0:
        raise ValueError("Нет параметров для протокола")

    story = []

    # ======================= 1. КОМПАКТНАЯ ШАПКА =======================

    # Левая часть пустая (логотип убран)
    left_block = Spacer(1, 1)

    # Заголовок (по центру)
    title_p = Paragraph("Протокол № ___________________________<br/>от ________________",
                        ParagraphStyle('PHTitle', fontName='Arial', fontSize=11, leading=14, alignment=TA_CENTER))

    # QR-код и ID (справа)
    qr_data = str(measure_protokol_id) if measure_protokol_id else str(measure_id)
    try:
        qr_img = Image(generate_qr_code(qr_data), width=16 * mm, height=16 * mm)
    except Exception:
        qr_img = Spacer(1, 1)

    qr_text = Paragraph(qr_data, ParagraphStyle('QRText', fontName='Arial', fontSize=8, alignment=TA_CENTER))

    qr_block = Table([[qr_img], [qr_text]], colWidths=[18 * mm])
    qr_block.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
    ]))

    # Собираем верхнюю таблицу: Пусто | Заголовок | QR
    top = Table([[left_block, title_p, qr_block]],
                colWidths=[usable_w * 0.20, usable_w * 0.55, usable_w * 0.25])
    top.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))
    story.append(top)
    story.append(Spacer(1, 3 * mm))


    header_text = f"""
    Приемо-сдаточных испытаний изделий: <b>{view_data.get('Spc_Text', '—')}</b> на соответствие требованиям технических условий <b>{view_data.get('TU', '—')}</b><br/>
    предъявленных извещением № _________ от " _____ " ____________________ 20 ___ г.<br/>
    Договор № ________________________ для организации _______________<br/>
    Кварцевые резонаторы изготовлены в эквиваленте типа <b>{view_data.get('TGK', '—')}</b><br/>
    Внешний вид и маркировка соответствуют ТУ, посторонние частицы отсутствуют.<br/>
    МСК № <b>{view_data.get('MSK', '—')}</b> &nbsp;&nbsp;&nbsp;&nbsp; Дата изготовления <b>{view_data.get('Date', '—')}</b>
    """

    header_style = ParagraphStyle('HeaderText', fontName='Arial', fontSize=9.5, leading=11.5, spaceAfter=3)
    story.append(Paragraph(header_text, header_style))
    story.append(Spacer(1, 2 * mm))

    # ======================= 2. ТАБЛИЦА =======================
    w_num = 45  # Увеличили ширину для текста "Нормы ОТК"
    w_res = 55  # Увеличили ширину для текста "не более/не менее"
    w_param = (usable_w - w_num - w_res) / n
    col_widths = [w_num, w_res] + [w_param] * n

    HDR_H = 120
    s_center = _cs(7)
    s_header = _cs(6.5)
    s_header_left = ParagraphStyle('SHL', fontName='Arial', fontSize=6.5, leading=8, alignment=TA_CENTER,
                                   wordWrap='CJK')

    rows = []

    # Row 0
    r0 = [_RotText("№№", w_num, HDR_H, bold=True),
          _RotText("№ резонатора", w_res, HDR_H, bold=True)]
    for p in presentation_params:
        title = (f"{p['name']}, {p['units']}" if p.get('units') else p['name'])
        r0.append(_RotText(title, w_param, HDR_H, bold=True))
    rows.append(r0)

    # Row 1 — Нормы ОТК (не более)
    r1 = [Paragraph("<b>Нормы ОТК</b>", s_header_left),
          Paragraph("<b>не более</b>", s_header_left)]
    for p in presentation_params:
        r1.append(Paragraph(_fnum(p['max_otk']), s_center))
    rows.append(r1)

    # Row 2 — Нормы ОТК (не менее)
    r2 = ["", Paragraph("<b>не менее</b>", s_header_left)]
    for p in presentation_params:
        r2.append(Paragraph(_fnum(p['min_otk']), s_center))
    rows.append(r2)

    # Row 3 — № п.п. требований ТУ
    tu_name = tu_data.get('tu_name', '') or ''
    label_tu = (f"<b>№ п.п. требований<br/>ТУ {tu_name}</b>" if tu_name else "<b>№ п.п. требований ТУ</b>")
    r3 = [Paragraph(label_tu, s_header_left), Spacer(1, 1)]
    for p in presentation_params:
        r3.append(Paragraph(p['norm_p'] or "—", s_header))
    rows.append(r3)

    # Row 4 — № п.п. методов контроля
    r4 = [Paragraph("<b>№ п.п. методов<br/>контроля</b>", s_header_left), Spacer(1, 1)]
    for p in presentation_params:
        r4.append(Paragraph(p['cntrl'] or "—", s_header))
    rows.append(r4)

    header_rows = len(rows)

    # Данные
    for idx, (_, dr) in enumerate(data_df.iterrows(), 1):
        row = [Paragraph(str(idx), s_center), Paragraph(str(dr.get('Numbers', '')), s_center)]
        for p in presentation_params:
            v = dr.get(p['param']) if p['param'] in data_df.columns else None
            row.append(Paragraph(_fnum(v, 3), s_center))
        rows.append(row)

    table = Table(rows, colWidths=col_widths, repeatRows=header_rows)
    styles = [
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('GRID', (0, 0), (-1, -1), 0.4, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('LEFTPADDING', (0, 0), (-1, -1), 2),
        ('RIGHTPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#D9E2F3')),
        ('BACKGROUND', (0, 1), (-1, 4), colors.HexColor('#F2F2F2')),

        # Объединяем ячейку "Нормы ОТК" по вертикали (по 2 строки)
        ('SPAN', (0, 1), (0, 2)),

        # Объединение первых двух колонок для строк 3 и 4
        ('SPAN', (0, 3), (1, 3)),  # № п.п. требований ТУ
        ('SPAN', (0, 4), (1, 4)),  # № п.п. методов контроля
    ]
    table.setStyle(TableStyle(styles))
    story.append(table)
    story.append(Spacer(1, 5 * mm))

    # ======================= 3. ЗАКЛЮЧЕНИЕ (ПСИ) =======================
    n_total = len(data_df)
    spc_text = view_data.get('Spc_Text', '')
    tu_text = view_data.get('TU', '')

    concl = ParagraphStyle('PC', fontName='Arial', fontSize=9.5, leading=12, alignment=TA_LEFT)

    # Заголовок ЗАКЛЮЧЕНИЕ
    story.append(Paragraph("ЗАКЛЮЧЕНИЕ",
                           ParagraphStyle('PCTitle', fontName='Arial', fontSize=11, leading=14, alignment=TA_CENTER,
                                          spaceAfter=5, spaceBefore=5)))

    # Логика вывода номеров
    if n_total < 10 and 'Numbers' in data_df.columns:
        nums_str = ", ".join(data_df['Numbers'].astype(str).tolist())
        prefix_text = f"Изделия <b>{spc_text}</b> за № <b>{nums_str}</b>"
    else:
        prefix_text = f"Изделия <b>{spc_text}</b> в количестве <b>{n_total}</b> шт."

    story.append(Paragraph(
        f"{prefix_text} соответствуют требованиям ТУ <b>{tu_text}</b> "
        f"приняты и годны для использования по назначению (эксплуатации).", concl))

    story.append(Spacer(1, 3 * mm))

    story.append(Paragraph(
        f"Изделия <b>{spc_text}</b> за № ____________________ "
        f"не соответствуют требованиям ТУ <b>{tu_text}</b> "
        f"и подлежат возврату ОТК.", concl))

    story.append(Spacer(1, 10 * mm))

    # ======================= 4. ПОДПИСИ (ПСИ) =======================
    sig_data = [
        [Paragraph("Представитель ВП", concl), Spacer(1, 1), Spacer(1, 1), Spacer(1, 1)],
        [Spacer(1, 1), Paragraph("______________________", concl), Paragraph("______________________", concl),
         Paragraph("Дата __________", concl)],
        [Spacer(1, 1), Paragraph("<font size=7>подпись</font>", concl),
         Paragraph("<font size=7>инициалы, фамилия</font>", concl), Spacer(1, 1)],
    ]
    sig_tbl = Table(sig_data, colWidths=[usable_w * 0.20, usable_w * 0.25, usable_w * 0.30, usable_w * 0.25])
    sig_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ]))
    story.append(sig_tbl)

    # ======================= 5. BUILD =======================
    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont('Arial', 8)
        canvas.setFillColor(colors.HexColor('#555555'))
        canvas.drawRightString(page_w - margin, 5 * mm, f"Лист {canvas.getPageNumber()}")
        canvas.restoreState()

    path = Options.get_measure_protokol_path() + "\\" + filename
    doc = SimpleDocTemplate(
        path, pagesize=landscape(A4),
        leftMargin=margin, rightMargin=margin,
        topMargin=8 * mm, bottomMargin=10 * mm)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return path

# ============================================================================
# ПАСПОРТ (по форме ТУ)
# ============================================================================
# Паспорт формируется по тем же параметрам, что и протоколы ПСИ/ОТК.
# Всегда выводятся:
#   * Номинальная частота — в единицах спецификации (109,11М → МГц; 20000К → кГц);
#   * Порядок колебаний   — из таблицы спецификаций (Order / Harmonic / ...);
#   * Код частоты ftCode   — если колонка присутствует в спецификации;
#   * Точность настройки   — psidata.F, Гц;
#   * Тип установки (TGK)  — specification.TGK (fallback: view_data.TGK);
#   * Макс. изменение частоты — psidata.Fmaxm, ppm;
#   * Динамическое сопротивление — psidata.R, Ом.
# Дополнительные строки и распиновка настраиваются через параметры
# (в будущем могут храниться в таблице `tu` — см. load_passport_config_from_tu).
# ============================================================================

_FREQ_UNIT_SUFFIXES = [
    ('МГЦ', 'МГц'), ('MHZ', 'МГц'),
    ('КГЦ', 'кГц'), ('KHZ', 'кГц'),
    ('ГЦ', 'Гц'),  ('HZ', 'Гц'),
    ('М', 'МГц'),  ('M', 'МГц'),
    ('К', 'кГц'),  ('K', 'кГц'),
]


def _parse_nominal_frequency(nominal_str):
    """
    Разбирает номинал частоты из view_data['Nominal'].

    Примеры:
        "109,11М"  → (109.11, "МГц")
        "20000К"   → (20000.0, "кГц")
        "32,768К"  → (32.768, "кГц")
        "10МГц"    → (10.0, "МГц")
        "109.11"   → (109.11, "МГц")  — по умолчанию МГц

    Возвращает (значение: float | None, единицы: str).
    """
    if not nominal_str:
        return None, ''

    s = str(nominal_str).strip().replace(',', '.')
    if not s:
        return None, ''

    s_upper = s.upper().replace(' ', '')
    for suffix, units in _FREQ_UNIT_SUFFIXES:
        if s_upper.endswith(suffix):
            value_part = s[:len(s) - len(suffix)].strip()
            try:
                return float(value_part), units
            except ValueError:
                return None, ''

    # Без суффикса — предполагаем МГц (типично для резонаторов)
    try:
        return float(s), 'МГц'
    except ValueError:
        return None, ''


def _get_spec_value(spc_row, *fields):
    """Достаёт первое непустое значение из spc_row по перечню полей."""
    if spc_row is None:
        return None
    for field in fields:
        try:
            v = spc_row.get(field) if hasattr(spc_row, 'get') else None
        except Exception:
            v = None
        if v is None:
            continue
        try:
            if pd.isna(v):
                continue
        except (TypeError, ValueError):
            pass
        s = str(v).strip()
        if s.lower() in ('', 'nan', 'none', 'null', 'no', '—', '-'):
            continue
        return v
    return None


def _get_first_psidata_value(data_df, field):
    """Достаёт первое непустое числовое значение из data_df[field]."""
    if data_df is None or field not in data_df.columns:
        return None
    for v in data_df[field].values:
        if v is None:
            continue
        try:
            if pd.isna(v):
                continue
        except (TypeError, ValueError):
            pass
        try:
            return float(v)
        except (TypeError, ValueError):
            return v
    return None


def load_passport_config_from_tu(tu_row):
    """
    Загружает конфигурацию паспорта из строки таблицы `tu` (опционально).

    Предполагаемые дополнительные колонки в `tu` (JSON-строки):
      * PinoutImages       — список путей к изображениям распиновки;
      * AdditionalLines    — список строк доп. данных;
      * PowerDissipation   — мощность рассеивания (п. 2.1);
      * PassportParams     — список параметров (как presentation_params).

    Если колонки отсутствуют — возвращает пустую конфигурацию.
    """
    import json
    cfg = {
        'pinout_images': None,
        'additional_lines': None,
        'power_dissipation': None,
        'presentation_params': None,
    }
    if tu_row is None:
        return cfg

    mapping = [
        ('pinout_images',     'PinoutImages'),
        ('additional_lines',  'AdditionalLines'),
        ('power_dissipation', 'PowerDissipation'),
        ('presentation_params', 'PassportParams'),
    ]
    for key, field in mapping:
        try:
            raw = tu_row.get(field) if hasattr(tu_row, 'get') else None
        except Exception:
            raw = None
        if raw is None:
            continue
        if isinstance(raw, (list, dict)):
            cfg[key] = raw
        elif isinstance(raw, str) and raw.strip():
            try:
                cfg[key] = json.loads(raw)
            except (ValueError, TypeError):
                cfg[key] = raw
    return cfg


def create_passport_protocol(
    data_df, view_data, tu_data, presentation_params, spc_row,
    measure_id,
    filename="passport.pdf",
    measure_protokol_id=None,
    pinout_images=None,
    additional_lines=None,
    power_dissipation=None,
    power_dissipation_unit='мВт',
):
    """
    Создаёт PDF-паспорт на изделие.

    Параметры
    ---------
    data_df : DataFrame
        Данные измерений (одна строка — одно изделие; для партии берётся
        первая строка по каждому параметру).
    view_data : dict
        Данные об изделии (Spc_Text, TU, Nominal, TGK, MSK, Date, ...).
    tu_data : dict
        Данные ТУ (tu_name и т.п.).
    presentation_params : list
        Список параметров — как в ПСИ/ОТК (dict с 'param', 'name', 'units').
    spc_row : pandas.Series | dict
        Строка спецификации: Order / ftCode / TGK / Power и т.д.
    measure_id : str
        ID измерения.
    filename : str
        Имя PDF-файла.
    measure_protokol_id : int | None
        ID протокола (для QR-кода).
    pinout_images : list[str] | str | None
        Пути к изображениям распиновки. Может быть строкой-каталогом —
        тогда загружаются все картинки из него.
    additional_lines : list[str] | None
        Дополнительные строки (могут меняться для разных изделий).
    power_dissipation : str | float | None
        Мощность рассеивания (п. 2.1). Если None — берётся из spc_row
        (Power / P_max / Pmax / PowerDissipation).
    power_dissipation_unit : str
        Единицы мощности рассеивания (по умолчанию «мВт»).

    Возвращает
    ----------
    str
        Полный путь к сохранённому PDF-файлу.
    """
    page_w, page_h = A4
    margin = 15 * mm
    usable_w = page_w - 2 * margin

    spc_text = view_data.get('Spc_Text', '—')
    tu_text = view_data.get('TU', '—')
    freq_value, freq_units = _parse_nominal_frequency(
        view_data.get('Nominal', ''))

    # ---- разрешение pinout_images ----
    if isinstance(pinout_images, str):
        if os.path.isdir(pinout_images):
            exts = ('.png', '.jpg', '.jpeg', '.gif', '.bmp')
            try:
                pinout_images = sorted([
                    os.path.join(pinout_images, f)
                    for f in os.listdir(pinout_images)
                    if f.lower().endswith(exts)
                ])
            except OSError:
                pinout_images = None
        else:
            pinout_images = [pinout_images]

    # ---- справочные значения из спецификации ----
    order_val = _get_spec_value(
        spc_row, 'Order', 'OscOrder', 'Osc_Order', 'OrderOsc',
        'Harmonic', 'Overtone', 'ПорядокКолебаний', 'НомерГармоники')
    ft_code = _get_spec_value(
        spc_row, 'ftCode', 'FtCode', 'FTCode', 'ft_code',
        'FrequencyCode', 'КодЧастоты')
    tgk_val = (_get_spec_value(spc_row, 'TGK', 'Tgk', 'tgk',
                               'ТипУстановки', 'InstallationType')
               or view_data.get('TGK'))

    # ---- вспомогательные стили ----
    info_style = ParagraphStyle('PInfo', fontName='Arial',
                                fontSize=11, leading=14)
    section_style = ParagraphStyle('PSection', fontName='Arial',
                                   fontSize=11, leading=14,
                                   spaceAfter=3, spaceBefore=2)
    cell_l = ParagraphStyle('PPName', fontName='Arial', fontSize=10,
                            leading=12, alignment=TA_LEFT, wordWrap='CJK')
    cell_r = ParagraphStyle('PPVal', fontName='Arial', fontSize=10,
                            leading=12, alignment=TA_CENTER, wordWrap='CJK')

    story = []

    # ======================= 1. ШАПКА =======================
    logo_path = os.path.join('Pictures', 'Morion_Logo.png')
    if os.path.exists(logo_path):
        logo_img = Image(logo_path, width=15 * mm, height=15 * mm)
    else:
        logo_img = Spacer(1, 1)
    logo_p = Paragraph('<b>АО "Морион"</b>', ParagraphStyle(
        'PLogo', fontName='Arial', fontSize=14, leading=16, leftIndent=5))
    left_block = Table([[logo_img, logo_p]], colWidths=[17 * mm, None])
    left_block.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    qr_data = str(measure_protokol_id) if measure_protokol_id else str(measure_id)
    try:
        qr_img = Image(generate_qr_code(qr_data), width=18 * mm, height=18 * mm)
    except Exception:
        qr_img = Spacer(1, 1)
    qr_text = Paragraph(qr_data, ParagraphStyle(
        'PQRText', fontName='Arial', fontSize=8, alignment=TA_CENTER))
    qr_block = Table([[qr_img], [qr_text]], colWidths=[20 * mm])
    qr_block.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    title_p = Paragraph('<b>ПАСПОРТ</b>', ParagraphStyle(
        'PTitle', fontName='Arial', fontSize=18, leading=22,
        alignment=TA_CENTER))
    top = Table([[left_block, title_p, qr_block]],
                colWidths=[usable_w * 0.30, usable_w * 0.45, usable_w * 0.25])
    top.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, 0), 'LEFT'),
        ('ALIGN', (1, 0), (1, 0), 'CENTER'),
        ('ALIGN', (2, 0), (2, 0), 'RIGHT'),
    ]))
    story.append(top)
    story.append(Spacer(1, 5 * mm))

    # ======================= 2. ОБЩИЕ СВЕДЕНИЯ =======================
    story.append(Paragraph(f"Изделие: <b>{spc_text}</b>", info_style))
    story.append(Paragraph(f"ТУ: <b>{tu_text}</b>", info_style))

    if 'Numbers' in data_df.columns and len(data_df) > 0:
        nums = [str(n) for n in data_df['Numbers'].tolist() if str(n).strip()]
        if nums:
            story.append(Paragraph(
                f"Заводской номер: <b>{', '.join(nums)}</b>", info_style))
    story.append(Spacer(1, 4 * mm))

    # ======================= 3. ОСНОВНЫЕ ТЕХ. ДАННЫЕ =======================
    story.append(Paragraph("<b>1. Основные технические данные</b>",
                           section_style))

    param_rows = []

    # 1) Номинальная частота (в единицах спецификации)
    if freq_value is not None:
        param_rows.append(("Номинальная частота",
                           f"{freq_value:g} {freq_units}"))

    # 2) Порядок колебаний (из спецификации)
    if order_val is not None:
        param_rows.append(("Порядок колебаний", str(order_val)))

    # 3) Код частоты ftCode (если есть)
    if ft_code is not None:
        param_rows.append(("Код частоты", str(ft_code)))

    # 4) Точность настройки F (psidata)
    f_val = _get_first_psidata_value(data_df, 'F')
    if f_val is not None:
        try:
            f_str = f"{float(f_val):.3f} Гц"
        except (TypeError, ValueError):
            f_str = f"{f_val} Гц"
        param_rows.append(("Точность настройки", f_str))

    # 5) Тип установки TGK (спецификация)
    if tgk_val is not None:
        param_rows.append(("Тип установки", str(tgk_val)))

    # 6) Максимальное изменение частоты Fmaxm (psidata)
    fmaxm_val = _get_first_psidata_value(data_df, 'Fmaxm')
    if fmaxm_val is not None:
        try:
            fm_str = f"{float(fmaxm_val):.2f} ppm"
        except (TypeError, ValueError):
            fm_str = f"{fmaxm_val} ppm"
        param_rows.append(("Максимальное изменение частоты", fm_str))

    # 7) Динамическое сопротивление R (psidata)
    r_val = _get_first_psidata_value(data_df, 'R')
    if r_val is not None:
        try:
            r_str = f"{float(r_val):.1f} Ом"
        except (TypeError, ValueError):
            r_str = f"{r_val} Ом"
        param_rows.append(("Динамическое сопротивление", r_str))

    # 8) Дополнительные параметры из presentation_params
    _already = {'F', 'R', 'Fmaxm', 'TGK', 'ftCode', 'Order',
                'OscOrder', 'Osc_Order', 'Harmonic'}
    for p in (presentation_params or []):
        param = p.get('param')
        if not param or param in _already:
            continue
        val = _get_first_psidata_value(data_df, param)
        if val is None:
            continue
        name = p.get('name', param)
        units = p.get('units', '') or ''
        unit_str = f" {units}" if units else ""
        try:
            formatted = f"{float(val):.3f}{unit_str}"
        except (TypeError, ValueError):
            formatted = f"{val}{unit_str}"
        param_rows.append((name, formatted))

    param_data = [
        [Paragraph("<b>Параметр</b>", _cs(10)),
         Paragraph("<b>Значение</b>", _cs(10))]
    ]
    for name, value in param_rows:
        param_data.append([Paragraph(str(name), cell_l),
                           Paragraph(str(value), cell_r)])

    param_table = Table(param_data,
                        colWidths=[usable_w * 0.58, usable_w * 0.42])
    param_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Arial'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (0, 0), (0, -1), 'LEFT'),
        ('ALIGN', (1, 0), (1, -1), 'CENTER'),
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#D9E2F3')),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story.append(param_table)
    story.append(Spacer(1, 4 * mm))

    # ======================= 4. МОЩНОСТЬ РАССЕИВАНИЯ (п. 2.1) ==========
    if power_dissipation is None:
        power_dissipation = _get_spec_value(
            spc_row, 'Power', 'P_max', 'Pmax', 'PowerDissipation',
            'Мощность', 'МощностьРассеивания')
    if power_dissipation is not None:
        story.append(Paragraph(
            f"<b>2.1.</b> Мощность рассеивания, не более: "
            f"<b>{power_dissipation}</b> {power_dissipation_unit}",
            ParagraphStyle('PPower', fontName='Arial',
                           fontSize=10.5, leading=13)))
        story.append(Spacer(1, 4 * mm))

    # ======================= 5. РАСПИНОВКА =======================
    if pinout_images:
        story.append(Paragraph("<b>3. Распиновка</b>", section_style))
        valid_imgs = []
        for img_path in pinout_images:
            if img_path and os.path.exists(img_path):
                try:
                    valid_imgs.append(Image(img_path, width=40 * mm,
                                            height=40 * mm))
                except Exception as e:
                    print(f"[Passport] Не удалось загрузить {img_path}: {e}")
        if valid_imgs:
            n_per_row = min(3, len(valid_imgs))
            img_data, current = [], []
            for img in valid_imgs:
                current.append(img)
                if len(current) == n_per_row:
                    img_data.append(current)
                    current = []
            if current:
                while len(current) < n_per_row:
                    current.append(Spacer(1, 1))
                img_data.append(current)
            img_table = Table(img_data,
                              colWidths=[usable_w / n_per_row] * n_per_row)
            img_table.setStyle(TableStyle([
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('LEFTPADDING', (0, 0), (-1, -1), 2),
                ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                ('TOPPADDING', (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
            ]))
            story.append(img_table)
            story.append(Spacer(1, 4 * mm))

    # ======================= 6. ДОП. СТРОКИ =======================
    if additional_lines:
        add_style = ParagraphStyle('PAddLine', fontName='Arial',
                                   fontSize=10, leading=13)
        for line in additional_lines:
            if line:
                story.append(Paragraph(str(line), add_style))
                story.append(Spacer(1, 1.5 * mm))
        story.append(Spacer(1, 2 * mm))

    # ======================= 7. СВИДЕТЕЛЬСТВО О ПРИЕМКЕ ==========
    story.append(Paragraph("<b>4. Свидетельство о приемке</b>",
                           section_style))
    numbers_text = ""
    if 'Numbers' in data_df.columns and len(data_df) > 0:
        nums = [str(n) for n in data_df['Numbers'].tolist() if str(n).strip()]
        if nums:
            numbers_text = f" за № <b>{', '.join(nums)}</b>"

    story.append(Paragraph(
        f"Изделие <b>{spc_text}</b>{numbers_text} соответствует "
        f"требованиям ТУ <b>{tu_text}</b> и признано годным "
        f"к эксплуатации.",
        ParagraphStyle('PAccept', fontName='Arial',
                       fontSize=10, leading=13)))
    story.append(Spacer(1, 8 * mm))

    # ======================= 8. ПОДПИСИ =======================
    sig_style = ParagraphStyle('PSig', fontName='Arial',
                               fontSize=10, leading=13)
    sig_data = [
        [Paragraph("Начальник ОТК", sig_style),
         Paragraph("______________________", sig_style)],
        [Spacer(1, 1),
         Paragraph("<font size=7>подпись</font>", sig_style)],
        [Paragraph("Дата: ____________", sig_style), Spacer(1, 1)],
    ]
    sig_tbl = Table(sig_data, colWidths=[usable_w * 0.4, usable_w * 0.6])
    sig_tbl.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'BOTTOM'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
    ]))
    story.append(sig_tbl)

    # ======================= 9. BUILD =======================
    def _footer(canvas, doc_):
        canvas.saveState()
        canvas.setFont('Arial', 8)
        canvas.setFillColor(colors.HexColor('#555555'))
        canvas.drawRightString(page_w - margin, 8 * mm,
                               f"Стр. {canvas.getPageNumber()}")
        canvas.restoreState()

    path = Options.get_measure_protokol_path() + "\\" + filename
    doc = SimpleDocTemplate(
        path, pagesize=A4,
        leftMargin=margin, rightMargin=margin,
        topMargin=12 * mm, bottomMargin=15 * mm)
    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    return path