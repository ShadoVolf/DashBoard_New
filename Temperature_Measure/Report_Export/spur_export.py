import os
import re

import pandas as pd
import matplotlib.pyplot as plt
from sqlalchemy import create_engine, MetaData, Table
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import numpy as np
import tempfile
import shutil

import Options


def sanitize_filename(filename):
    """Очищает имя файла от недопустимых символов"""
    # Заменяем недопустимые символы на подчеркивание
    invalid_chars = r'[<>:"/\\|?*\x00-\x1f]'
    sanitized = re.sub(invalid_chars, '_', str(filename))
    # Удаляем начальные и конечные пробелы и точки
    sanitized = sanitized.strip('. ')
    # Ограничиваем длину имени файла
    if len(sanitized) > 200:
        sanitized = sanitized[:200]
    return sanitized


def export_spur_data(dpg, measure_id):
    # Подключение к базе данных
    engine_string = Options.get_connection_string()
    engine = create_engine(engine_string)
    metadata = MetaData()
    dpg.configure_item('export_spur_start_button', enabled=False)
    # Отражение таблицы
    spur_table = Table('psidata_spur', metadata, autoload_with=engine)

    # Создание сессии
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Получение всех записей для указанного Measure_ID
        query = session.query(spur_table).filter(spur_table.c.Measure_ID == measure_id)
        df = pd.read_sql(query.statement, session.bind)

        if df.empty:
            print(f"Нет данных для Measure_ID {measure_id}")
            return

        # Получаем MSK для имени файла (берем первое значение)
        msk_value = df['MSK'].iloc[0] if not df['MSK'].isna().all() else f"Measure_{measure_id}"

        # Текущая дата и время для имени файла
        current_time = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Создаем папку для результатов если её нет
        output_dir = Options.get_measure_protokol_path() + "/Нежелательные резонансы"
        os.makedirs(output_dir, exist_ok=True)
        os.makedirs(output_dir + '/XLS', exist_ok=True)
        os.makedirs(output_dir + '/PDF', exist_ok=True)

        # Сортируем данные по номеру резонатора и температуре
        df = df.sort_values(['N', 'Temp'])

        print(f"Найдено {len(df)} записей для Measure_ID {measure_id}")
        # Очищаем значение MSK от недопустимых символов
        msk_value = sanitize_filename(msk_value)
        # Создаем Excel файл с данными из БД

        excel_filename = f"{output_dir}/XLS/{msk_value}_{current_time}.xlsx"

        # Выбираем нужные колонки из БД, включая поле R
        db_columns = ['N', 'Temp', 'R', 'Spur_R_1', 'Spur_F_1', 'Spur_R_2', 'Spur_F_2',
                      'Spur_R_3', 'Spur_F_3', 'Spur_R_4', 'Spur_F_4']

        # Создаем DataFrame с данными из БД
        db_data_df = df[db_columns].copy()

        # Сохраняем данные из БД в Excel с дополнительным форматированием
        save_excel_with_formatting(db_data_df, df, excel_filename)

        print(f"Excel файл создан: {excel_filename}")
        log_text = [f'Создание файла Excel завершено {measure_id}', f'путь {excel_filename}']
        Options.show_message_inf(dpg, 'Экспорт файлов', log_text)
        # Создаем PDF с графиками и таблицей
        pdf_filename = f"{output_dir}/PDF/{msk_value}_{current_time}.pdf"
        create_pdf_with_plots_and_table(df, pdf_filename, db_data_df)

        print(f"PDF файл создан: {pdf_filename}")
        log_text.append(f'Создание файла PDF завершено {measure_id}')
        log_text.append(f'путь {pdf_filename}')
        Options.show_message_inf(dpg, 'Экспорт файлов', log_text)

    except Exception as e:
        print(f"Ошибка: {str(e)}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()


def save_excel_with_formatting(db_data_df, original_df, excel_filename):
    """Сохраняет данные в Excel с форматированием и графиками"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.drawing.image import Image
    import tempfile

    wb = Workbook()
    ws = wb.active
    ws.title = "Данные_резонаторов"

    # Заголовки таблицы
    headers = list(db_data_df.columns)
    for col_idx, header in enumerate(headers, 1):
        ws.cell(row=1, column=col_idx, value=header)
        ws.cell(row=1, column=col_idx).font = Font(bold=True)
        ws.cell(row=1, column=col_idx).alignment = Alignment(horizontal='center')
        # Заливаем заголовки цветом
        ws.cell(row=1, column=col_idx).fill = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")

    # Начальная строка для данных
    current_row = 2

    # Создаем временную папку для графиков
    temp_dir = tempfile.mkdtemp()

    # Получаем уникальные номера резонаторов
    resonators = db_data_df['N'].unique()

    # Проходим по всем резонаторам
    for i, resonator_n in enumerate(resonators):
        # Находим все данные для текущего резонатора
        resonator_data_all = db_data_df[db_data_df['N'] == resonator_n]

        # Получаем первую температуру для этого резонатора для графика
        first_temp_data = original_df[
            (original_df['N'] == resonator_n)
        ].iloc[0]

        plot_data = first_temp_data['Spur_Plot_Data']

        # Создаем график только если есть данные и только для первой температуры
        chart_path = None
        if plot_data is not None:
            # Парсим данные
            data_text = plot_data.decode('cp1251')
            data_lines = data_text.strip().split('\n')

            frequencies = []
            values = []

            for line in data_lines:
                parts = line.split('\t')
                if len(parts) >= 4 and parts[0] == 'RF In/Out':
                    try:
                        frequency = float(parts[2].replace(',', '.'))
                        value = float(parts[3].replace(',', '.'))
                        frequencies.append(frequency)
                        values.append(value)
                    except ValueError:
                        continue

            if frequencies and values:
                # Создаем график
                plt.figure(figsize=(8, 6))
                plt.plot(frequencies, values, 'b-', linewidth=1, marker='o', markersize=2)
                plt.title(f'Резонатор {resonator_n} - RF In/Out(F)\nТемпература: {25}')
                plt.xlabel('Частота, МГц')
                plt.ylabel('Значение, дБ')
                plt.grid(True, alpha=0.3)
                plt.tight_layout()

                # Сохраняем график как временное изображение
                chart_path = os.path.join(temp_dir, f"chart_{resonator_n}.png")
                plt.savefig(chart_path, dpi=100)
                plt.close()

        # Записываем все строки для текущего резонатора
        start_resonator_row = current_row
        for idx, (_, resonator_data) in enumerate(resonator_data_all.iterrows()):
            # Записываем данные резонатора
            for col_idx, col_name in enumerate(headers, 1):
                ws.cell(row=current_row, column=col_idx, value=resonator_data[col_name])

            current_row += 1

        # Вставляем график справа от таблицы (на уровне начала данных резонатора)
        if chart_path:
            img = Image(chart_path)
            # Размещаем график в столбце M (13-й столбец) на уровне начала данных резонатора
            img.anchor = f'M{start_resonator_row}'
            img.width = 400
            img.height = 300
            ws.add_image(img)

        # Добавляем три пустые строки между резонаторами (кроме последнего)
        if i < len(resonators) - 1:
            current_row += 3

    # Настраиваем ширину столбцов с учетом добавленного поля R
    column_widths = {
        'A': 10,  # N
        'B': 10,  # Temp
        'C': 10,  # R (добавленное поле)
        'D': 12,  # Spur_R_1
        'E': 12,  # Spur_F_1
        'F': 12,  # Spur_R_2
        'G': 12,  # Spur_F_2
        'H': 12,  # Spur_R_3
        'I': 12,  # Spur_F_3
        'J': 12,  # Spur_R_4
        'K': 12,  # Spur_F_4
    }

    for col, width in column_widths.items():
        ws.column_dimensions[col].width = width

    # Настраиваем ширину столбца для графиков (теперь столбец M)
    ws.column_dimensions['M'].width = 40

    # Сохраняем файл
    wb.save(excel_filename)

    # Удаляем временную папку
    shutil.rmtree(temp_dir)


def create_pdf_with_plots_and_table(original_df, pdf_filename, db_data_df):
    """Создает PDF файл с графиками и таблицей данных"""
    try:
        from matplotlib.backends.backend_pdf import PdfPages

        with PdfPages(pdf_filename) as pdf:
            # Настройки стиля для графиков
            plt.style.use('default')

            # Получаем уникальные номера резонаторов
            resonators = db_data_df['N'].unique()

            # Для каждого резонатора создаем страницу с таблицей всех температур и графиком
            for resonator_n in resonators:
                # Находим все данные для текущего резонатора
                resonator_data_all = original_df[original_df['N'] == resonator_n]

                # Получаем первую температуру для графика
                first_temp_data = resonator_data_all.iloc[0]
                plot_data = first_temp_data['Spur_Plot_Data']

                # Создаем страницу с таблицей и графиком
                fig = create_resonator_page(resonator_n, resonator_data_all, first_temp_data, plot_data)
                pdf.savefig(fig)
                plt.close()

            # Добавляем страницу с информацией о документе
            fig_info = create_info_page(original_df, len(resonators))
            pdf.savefig(fig_info)
            plt.close()

    except ImportError:
        print("Библиотека matplotlib не установлена. PDF не будет создан.")
        print("Установите: pip install matplotlib")


def create_resonator_page(resonator_n, resonator_data_all, first_temp_data, plot_data):
    """Создает страницу для одного резонатора с таблицей всех температур и графиком"""
    fig = plt.figure(figsize=(14, 10))

    # Общий заголовок
    plt.suptitle(f'Резонатор {resonator_n}', fontsize=16, y=0.95)

    # Создаем подграфики: слева таблица, справа график
    ax_table = plt.subplot2grid((1, 10), (0, 0), colspan=6)
    ax_plot = plt.subplot2grid((1, 10), (0, 6), colspan=4)

    # Таблица с данными всех температур для резонатора
    ax_table.axis('off')

    # Подготовка данных для таблицы с учетом поля R
    table_headers = ['Temp', 'R', 'Spur_R_1', 'Spur_F_1', 'Spur_R_2', 'Spur_F_2',
                     'Spur_R_3', 'Spur_F_3', 'Spur_R_4', 'Spur_F_4']

    table_data = [table_headers]
    for _, row in resonator_data_all.iterrows():
        table_row = [row[col] for col in table_headers]
        table_data.append(table_row)

    # Создаем таблицу
    table = ax_table.table(cellText=table_data,
                           loc='center',
                           cellLoc='center',
                           colWidths=[0.08, 0.08] + [0.084] * 8)  # Настройка ширины столбцов

    # Настраиваем стиль таблицы
    table.auto_set_font_size(False)
    table.set_fontsize(8)
    table.scale(1, 1.2)

    # Выделяем заголовок таблицы
    for i in range(len(table_headers)):
        table[(0, i)].set_facecolor('#DDDDDD')
        table[(0, i)].set_text_props(weight='bold')

    # Заголовок таблицы
    ax_table.set_title('Все температурные зависимости', fontsize=12, pad=20)

    # График (только для первой температуры)
    if plot_data is not None:
        # Парсим данные
        data_text = plot_data.decode('cp1251')
        data_lines = data_text.strip().split('\n')

        frequencies = []
        values = []

        for line in data_lines:
            parts = line.split('\t')
            if len(parts) >= 4 and parts[0] == 'RF In/Out':
                try:
                    frequency = float(parts[2].replace(',', '.'))
                    value = float(parts[3].replace(',', '.'))
                    frequencies.append(frequency)
                    values.append(value)
                except ValueError:
                    continue

        if frequencies and values:
            ax_plot.plot(frequencies, values, 'b-', linewidth=1, marker='o', markersize=2)
            ax_plot.set_title(f'RF In/Out(F)\n(Температура: {first_temp_data["Temp"]})')
            ax_plot.set_xlabel('Частота, МГц')
            ax_plot.set_ylabel('Значение, дБ')
            ax_plot.grid(True, alpha=0.3)
            ax_plot.ticklabel_format(useOffset=False, style='plain')

    plt.tight_layout(rect=[0, 0, 1, 0.93])  # Оставляем место для общего заголовка
    return fig


def create_info_page(df, num_resonators):
    """Создает страницу с информацией о документе"""
    fig, ax = plt.subplots(figsize=(8, 6))
    ax.axis('off')

    info_text = f"Отчет по данным Spur\n\n" \
                f"Measure_ID: {df['Measure_ID'].iloc[0]}\n" \
                f"MSK: {df['MSK'].iloc[0] if not df['MSK'].isna().all() else 'N/A'}\n" \
                f"Количество резонаторов: {num_resonators}\n" \
                f"Общее количество записей: {len(df)}\n" \
                f"Дата создания: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"

    ax.text(0.1, 0.9, info_text, transform=ax.transAxes, fontsize=12, verticalalignment='top')
    return fig


# Пример использования
if __name__ == "__main__":
    measure_id = 24  # Укажите нужный Measure_ID
    export_spur_data(measure_id)