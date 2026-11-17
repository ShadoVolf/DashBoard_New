import numpy as np
import pandas as pd
import matplotlib
from openpyxl.chart import Reference
from openpyxl.chart.series import Series
from tabulate import tabulate

import Options

# Устанавливаем не-GUI бэкенд перед импортом pyplot
matplotlib.use('Agg')  # Важно: ДО импорта plt
import matplotlib.pyplot as plt
import io
import os
from datetime import datetime
from scipy.signal import savgol_filter
from openpyxl import Workbook
from openpyxl.drawing.image import Image
from openpyxl.chart import ScatterChart, Reference
from openpyxl.styles import Font, Alignment, PatternFill

def save_resonator_data_to_excel_smart(data_dict):
    """
    Сохраняет данные резонатора в Excel файл с учетом разных длин массивов
    и исключением пустых ключей. Использует не-GUI бэкенд для matplotlib.
    """

    # Создаем папки если их нет
    base_dir = Options.get_rt_measure_protokol_path()
    measurements_dir = os.path.join(base_dir, "Измеритель_РТ")
    os.makedirs(measurements_dir, exist_ok=True)

    # Генерируем имя файла с текущей датой и временем
    current_time = datetime.now()
    time_str = current_time.strftime("%Y-%m-%d_%H-%M-%S")
    readable_time = current_time.strftime("%d.%m.%Y %H:%M:%S")
    filename = f"Измерение_резонатора_{time_str}.xlsx"
    full_path = os.path.join(measurements_dir, filename)

    # Обрабатываем данные: удаляем пустые ключи и обрезаем до минимальной длины
    processed_data = {}

    # Удаляем пустые ключи
    non_empty_keys = {key: value for key, value in data_dict.items()
                      if len(value) > 0 and key != 'Time'}

    if not non_empty_keys:
        raise ValueError("Нет данных для сохранения (все массивы пустые)")

    # Находим минимальную длину среди всех непустых массивов
    min_length = min(len(arr) for arr in non_empty_keys.values())

    # Обрезаем все массивы до минимальной длины
    if 'Time' in data_dict and len(data_dict['Time']) > 0:
        processed_data['Time'] = data_dict['Time'][:min_length]
    else:
        # Если время не предоставлено, создаем искусственный массив времени
        processed_data['Time'] = [i * 0.1 for i in range(min_length)]

    for key, value in non_empty_keys.items():
        processed_data[key] = value[:min_length]

    # Создаем DataFrame из обработанных данных
    df = pd.DataFrame(processed_data)

    # Создаем Excel workbook
    workbook = Workbook()

    # Создаем информационный лист
    info_sheet = workbook.active
    info_sheet.title = "Информация"

    # Добавляем информацию об измерении
    info_sheet['A1'] = "Измерение резонатора"
    info_sheet['A1'].font = Font(size=14, bold=True)

    info_data = [
        ("Дата и время сохранения:", readable_time),
        ("Количество точек:", min_length),
        ("Длительность измерения (сек):", f"{processed_data['Time'][-1]:.2f}"),
        ("", ""),
        ("Параметры (обрезано до минимальной длины):", ""),
    ]

    for i, (param, value) in enumerate(info_data, 2):
        info_sheet[f'A{i}'] = param
        info_sheet[f'B{i}'] = value
        if "Параметры" in param:
            info_sheet[f'A{i}'].font = Font(bold=True)

    # Добавляем список параметров
    param_start_row = 7
    for i, key in enumerate(processed_data.keys()):
        info_sheet[f'A{param_start_row + i}'] = key
        info_sheet[f'B{param_start_row + i}'] = f"Записей: {len(processed_data[key])}"

    # Добавляем информацию об исключенных пустых ключах
    empty_keys = [key for key in data_dict.keys() if len(data_dict.get(key, [])) == 0]
    if empty_keys:
        info_sheet[f'A{param_start_row + len(processed_data) + 2}'] = "Исключенные пустые параметры:"
        info_sheet[f'A{param_start_row + len(processed_data) + 2}'].font = Font(bold=True, color="FF0000")

        for i, empty_key in enumerate(empty_keys):
            info_sheet[f'A{param_start_row + len(processed_data) + 3 + i}'] = empty_key
            info_sheet[f'A{param_start_row + len(processed_data) + 3 + i}'].font = Font(color="FF0000")

    # Создаем лист с данными
    data_sheet = workbook.create_sheet("Данные")

    # Записываем заголовки
    for col_num, column_title in enumerate(df.columns, 1):
        cell = data_sheet.cell(row=1, column=col_num, value=column_title)
        cell.font = Font(bold=True)

    # Записываем данные
    for row_num, row_data in enumerate(df.values, 2):
        for col_num, value in enumerate(row_data, 1):
            data_sheet.cell(row=row_num, column=col_num, value=value)

    # Создаем графики для каждого столбца (кроме времени)
    time_data = processed_data['Time']
    columns_to_plot = [col for col in processed_data.keys() if col != 'Time']

    for column in columns_to_plot:
        try:
            # Создаем график с использованием не-GUI бэкенда
            plt.figure(figsize=(12, 6))
            plt.plot(time_data, processed_data[column], 'b-', linewidth=1, alpha=0.7)
            plt.xlabel('Time (секунды)')
            plt.ylabel(column)
            plt.title(f'{column} от времени\n{readable_time}\n(обрезка до {min_length} точек)')
            plt.grid(True, alpha=0.3)

            # Сохраняем график в буфер
            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', dpi=100, bbox_inches='tight')
            plt.close()

            # Создаем новый лист для графика
            img_buffer.seek(0)
            img = Image(img_buffer)

            sheet_name = f'График {column}'[:31]
            worksheet = workbook.create_sheet(title=sheet_name)
            worksheet.add_image(img, 'A1')

        except Exception as e:
            print(f"Ошибка при создании графика для {column}: {e}")
            continue

    # Автоматически подгоняем ширину столбцов
    for sheet in workbook.sheetnames:
        ws = workbook[sheet]
        if sheet == "Данные":
            for column_cells in ws.columns:
                length = max(len(str(cell.value)) for cell in column_cells)
                ws.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 50)

    # Сохраняем workbook
    workbook.save(full_path)

    return full_path


def analyze_data_structure(data_dict):
    """Анализирует структуру данных и выводит информацию о длинах массивов"""
    print("=== АНАЛИЗ СТРУКТУРЫ ДАННЫХ ===")
    for key, value in data_dict.items():
        print(f"{key}: {len(value)} записей")

    non_empty_keys = {key: value for key, value in data_dict.items()
                      if len(value) > 0 and key != 'Time'}

    if non_empty_keys:
        min_length = min(len(arr) for arr in non_empty_keys.values())
        print(f"\nМинимальная длина непустых массивов: {min_length}")
        print(f"Будут сохранены массивы длиной: {min_length}")

    empty_keys = [key for key in data_dict.keys() if len(data_dict.get(key, [])) == 0]
    if empty_keys:
        print(f"\nПустые массивы (исключены): {empty_keys}")

    print("=" * 40)


# Упрощенная версия без анализа (для использования в потоках)
def save_resonator_data_simple(data_dict):
    """
    Упрощенная версия для использования в потоках
    """
    try:
        return save_resonator_data_to_excel_smart(data_dict)
    except Exception as e:
        print(f"Ошибка сохранения: {e}")
        return None


def print_outliers_statistics(statistics):
    """
    Выводит статистику выбросов в виде красивой таблицы в консоль
    """

    # Создаем данные для таблицы
    table_data = []

    for param, stats in statistics.items():
        row = [
            param,
            stats['method'],
            f"{stats['outliers_count']}",
            f"{stats['outliers_percent']:.2f}%",
            f"{float(stats['q1']):.4f}" if stats['q1'] != 0 else "0",
            f"{float(stats['q3']):.4f}" if stats['q3'] != 0 else "0",
            f"{float(stats['iqr']):.4f}" if stats['iqr'] != 0 else "0",
            f"{float(stats['lower_bound']):.4f}" if stats['lower_bound'] != 0 else "0",
            f"{float(stats['upper_bound']):.4f}" if stats['upper_bound'] != 0 else "0"
        ]
        table_data.append(row)

    # Заголовки таблицы
    headers = [
        'Параметр',
        'Метод',
        'Выбросы',
        'Выбросы %',
        'Q1',
        'Q3',
        'IQR',
        'Нижняя граница',
        'Верхняя граница'
    ]

    # Выводим таблицу
    print("\n" + "=" * 120)
    print("СТАТИСТИКА ФИЛЬТРАЦИИ ВЫБРОСОВ")
    print("=" * 120)
    print(tabulate(table_data, headers=headers, tablefmt='grid', stralign='center'))

    # Добавляем сводную статистику
    total_outliers = sum(stats['outliers_count'] for stats in statistics.values())
    total_params = len(statistics)
    params_with_outliers = sum(1 for stats in statistics.values() if stats['outliers_count'] > 0)

    print(f"\n📊 СВОДНАЯ СТАТИСТИКА:")
    print(f"   Всего параметров: {total_params}")
    print(f"   Параметров с выбросами: {params_with_outliers}")
    print(f"   Общее количество выбросов: {total_outliers}")

    # Находим параметры с наибольшим количеством выбросов
    if params_with_outliers > 0:
        max_outliers_param = max(statistics.items(), key=lambda x: x[1]['outliers_count'])
        print(f"   Наибольшее количество выбросов: {max_outliers_param[1]['outliers_count']} "
              f"({max_outliers_param[1]['outliers_percent']:.2f}%) в параметре '{max_outliers_param[0]}'")


def print_outliers_statistics_simple(statistics):
    """
    Упрощенная версия вывода статистики (только основные колонки)
    """

    table_data = []

    for param, stats in statistics.items():
        # Подсветка строк с выбросами
        if stats['outliers_count'] > 0:
            param_display = f"⚠ {param}"
        else:
            param_display = f"✓ {param}"

        row = [
            param_display,
            stats['method'],
            f"{stats['outliers_count']}",
            f"{stats['outliers_percent']:.2f}%",
            f"{float(stats['iqr']):.4f}" if stats['iqr'] != 0 else "0"
        ]
        table_data.append(row)

    headers = ['Параметр', 'Метод', 'Выбросы', 'Выбросы %', 'IQR']

    print("\n" + "=" * 80)
    print("СТАТИСТИКА ВЫБРОСОВ (IQR МЕТОД)")
    print("=" * 80)
    print(tabulate(table_data, headers=headers, tablefmt='simple_grid', stralign='center'))


def print_detailed_outlier_analysis(statistics):
    """
    Детальный анализ выбросов с дополнительной информацией
    """

    print("\n" + "🔍 ДЕТАЛЬНЫЙ АНАЛИЗ ВЫБРОСОВ")
    print("=" * 100)

    for param, stats in statistics.items():
        print(f"\n📈 ПАРАМЕТР: {param}")
        print(f"   Метод: {stats['method']}")
        print(f"   Порог: {stats['threshold']}")

        if stats['outliers_count'] > 0:
            print(f"   ❌ Выбросы: {stats['outliers_count']} ({stats['outliers_percent']:.2f}%)")
            print(f"   📊 Статистика:")
            print(f"      - Q1 (25%): {float(stats['q1']):.4f}")
            print(f"      - Q3 (75%): {float(stats['q3']):.4f}")
            print(f"      - IQR: {float(stats['iqr']):.4f}")
            print(
                f"      - Диапазон нормальных значений: [{float(stats['lower_bound']):.4f}, {float(stats['upper_bound']):.4f}]")
        else:
            print(f"   ✅ Выбросы не обнаружены")
            print(f"   📊 Статистика:")
            print(f"      - Q1 (25%): {float(stats['q1']):.4f}")
            print(f"      - Q3 (75%): {float(stats['q3']):.4f}")
            print(f"      - IQR: {float(stats['iqr']):.4f}")


def save_temperature_dependence_to_excel(data_dict):
    """
    Сохраняет данные температурной зависимости резонатора в Excel файл
    с графиками и аппроксимацией для F(R)
    """

    try:
        # Создаем папки если их нет
        base_dir = os.path.dirname(os.path.abspath(__file__))
        measurements_dir = os.path.join(base_dir, "Измерения", "Измеритель_РТ")
        os.makedirs(measurements_dir, exist_ok=True)

        # Генерируем имя файла с текущей датой и временем
        current_time = datetime.now()
        time_str = current_time.strftime("%Y-%m-%d_%H-%M-%S")
        readable_time = current_time.strftime("%d.%m.%Y %H:%M:%S")
        filename = f"Температурная_зависимость_{time_str}.xlsx"
        full_path = os.path.join(measurements_dir, filename)

        # Обрабатываем данные: удаляем пустые ключи и обрезаем до минимальной длины
        processed_data = {}

        # Определяем ключи для обработки (исключаем Time_All и пустые массивы)
        keys_to_process = ['R магазина, Ом', 'F(R), ppm', 'U(R), В', 'I(R), мА', 'P(R), мВ']
        non_empty_keys = {}

        for key in keys_to_process:
            if key in data_dict and data_dict[key] and len(data_dict[key]) > 0:
                # Преобразуем все значения в float
                try:
                    processed_data[key] = [float(x) for x in data_dict[key]]
                    non_empty_keys[key] = processed_data[key]
                except (ValueError, TypeError) as e:
                    print(f"Ошибка преобразования данных для {key}: {e}")
                    continue

        if not non_empty_keys:
            raise ValueError("Нет данных для сохранения (все массивы пустые или невалидные)")

        # Находим минимальную длину среди всех непустых массивов
        min_length = min(len(arr) for arr in non_empty_keys.values())

        # Обрезаем все массивы до минимальной длины
        for key in list(processed_data.keys()):
            processed_data[key] = processed_data[key][:min_length]

        # Проверяем, что есть данные для R магазина и F(R)
        if 'R магазина, Ом' not in processed_data or 'F(R), ppm' not in processed_data:
            raise ValueError("Отсутствуют данные R магазина или F(R) для анализа")

        # Создаем Excel workbook
        workbook = Workbook()

        # Удаляем стандартный лист
        if workbook.sheetnames:
            workbook.remove(workbook.active)

        # Лист с информацией
        info_sheet = workbook.create_sheet("Информация")

        # Заполняем информационный лист
        info_sheet['A1'] = "Температурная зависимость резонатора"
        info_sheet['A1'].font = Font(size=14, bold=True)

        info_data = [
            ("Дата и время:", readable_time),
            ("Количество точек измерения:", min_length),
            ("Диапазон R магазина:",
             f"{min(processed_data['R магазина, Ом']):.1f} - {max(processed_data['R магазина, Ом']):.1f} Ом"),
            ("", ""),
            ("Измеряемые параметры:", ""),
        ]

        for i, (param, value) in enumerate(info_data, 2):
            info_sheet[f'A{i}'] = param
            info_sheet[f'B{i}'] = value
            if "Измеряемые параметры:" in param:
                info_sheet[f'A{i}'].font = Font(bold=True)

        # Добавляем список параметров
        param_start_row = 7
        for i, key in enumerate(processed_data.keys()):
            info_sheet[f'A{param_start_row + i}'] = key
            info_sheet[f'B{param_start_row + i}'] = f"Записей: {len(processed_data[key])}"

        # Лист с данными
        data_sheet = workbook.create_sheet("Данные")

        # Создаем DataFrame для удобства
        df_data = []
        for i in range(min_length):
            row = {
                'R магазина, Ом': processed_data['R магазина, Ом'][i],
                'F(R), ppm': processed_data['F(R), ppm'][i],
            }
            if 'U(R), В' in processed_data:
                row['U(R), В'] = processed_data['U(R), В'][i]
            if 'I(R), мА' in processed_data:
                row['I(R), мА'] = processed_data['I(R), мА'][i]
            if 'P(R), мВ' in processed_data:
                row['P(R), мВ'] = processed_data['P(R), мВ'][i]
            df_data.append(row)

        df = pd.DataFrame(df_data)

        # Записываем заголовки
        for col_num, column_title in enumerate(df.columns, 1):
            cell = data_sheet.cell(row=1, column=col_num, value=column_title)
            cell.font = Font(bold=True)
            cell.fill = PatternFill(start_color="4CAF50", end_color="4CAF50", fill_type="solid")

        # Записываем данные
        for row_num, row_data in enumerate(df.values, 2):
            for col_num, value in enumerate(row_data, 1):
                data_sheet.cell(row=row_num, column=col_num, value=value)

        # Подгоняем ширину столбцов
        for column_cells in data_sheet.columns:
            length = max(len(str(cell.value)) for cell in column_cells)
            data_sheet.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 20)

        # График F(R) с аппроксимацией
        R_data = processed_data['R магазина, Ом']
        F_data = processed_data['F(R), ppm']

        # Создаем лист для графика F(R)
        fr_sheet = workbook.create_sheet("График F(R)")

        # Выполняем аппроксимацию с обработкой ошибок
        approximation_info = "Аппроксимация не выполнена"
        R_extremum = None
        F_extremum = None

        try:
            # Преобразуем данные в numpy arrays
            R_array = np.array(R_data, dtype=float)
            F_array = np.array(F_data, dtype=float)

            # Проверяем, что у нас достаточно точек для аппроксимации
            if len(R_array) < 3:
                approximation_info = "Недостаточно точек для аппроксимации (нужно минимум 3)"
            else:
                # Аппроксимация полиномом
                coeffs = np.polyfit(R_array, F_array, 2)
                poly_func = np.poly1d(coeffs)

                # Создаем плотную сетку для гладкой кривой
                R_fine = np.linspace(min(R_array), max(R_array), 100)
                F_fine = poly_func(R_fine)

                # Находим экстремум
                a, b, c = coeffs
                if abs(a) > 1e-10:  # Проверяем, что a не слишком близко к нулю
                    R_extremum = -b / (2 * a)
                    F_extremum = poly_func(R_extremum)
                    extremum_type = "минимум" if a > 0 else "максимум"

                    approximation_info = (f"Аппроксимация: {coeffs[0]:.6f}·R² + {coeffs[1]:.6f}·R + {coeffs[2]:.6f}\n"
                                          f"Экстремум: {extremum_type} при R = {R_extremum:.1f} Ом\n"
                                          f"Значение F: {F_extremum:.3f} ppm")
                else:
                    approximation_info = "Коэффициент a слишком мал для определения экстремума"

        except Exception as e:
            print(f"Ошибка аппроксимации F(R): {e}")
            approximation_info = f"Ошибка аппроксимации: {str(e)}"

        # Создаем график с помощью matplotlib
        plt.figure(figsize=(10, 6))
        plt.plot(R_data, F_data, 'bo-', linewidth=2, markersize=6, label='Измеренные данные')

        try:
            if R_extremum is not None and F_extremum is not None:
                # Снова вычисляем аппроксимацию для matplotlib графика
                R_array = np.array(R_data, dtype=float)
                F_array = np.array(F_data, dtype=float)

                if len(R_array) >= 3:
                    coeffs = np.polyfit(R_array, F_array, 2)
                    poly_func = np.poly1d(coeffs)
                    R_fine = np.linspace(min(R_array), max(R_array), 100)
                    F_fine = poly_func(R_fine)

                    plt.plot(R_fine, F_fine, 'r-', linewidth=2, label='Аппроксимация (полином 2-й степени)')
                    plt.plot(R_extremum, F_extremum, 'ro', markersize=10,
                             label=f'Экстремум: R={R_extremum:.1f} Ом, F={F_extremum:.3f} ppm')
        except Exception as e:
            print(f"Ошибка при построении графика matplotlib: {e}")

        plt.xlabel('R магазина, Ом')
        plt.ylabel('F(R), ppm')
        plt.title('Зависимость частоты от сопротивления магазина')
        plt.grid(True, alpha=0.3)
        plt.legend()

        # Сохраняем график как изображение
        img_buffer = io.BytesIO()
        plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
        plt.close()

        # Вставляем изображение в Excel
        img_buffer.seek(0)
        img = Image(img_buffer)
        img.anchor = 'A1'
        fr_sheet.add_image(img)

        # Добавляем информацию об аппроксимации
        fr_sheet['A30'] = "Информация об аппроксимации:"
        fr_sheet['A30'].font = Font(bold=True)
        fr_sheet['A31'] = approximation_info

        # График I(R)
        if 'I(R), мА' in processed_data:
            ir_sheet = workbook.create_sheet("График I(R)")

            plt.figure(figsize=(10, 6))
            plt.plot(R_data, processed_data['I(R), мА'], 'g^-', linewidth=2, markersize=6)
            plt.xlabel('R магазина, Ом')
            plt.ylabel('I(R), мА')
            plt.title('Зависимость тока от сопротивления магазина')
            plt.grid(True, alpha=0.3)

            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
            plt.close()

            img_buffer.seek(0)
            img = Image(img_buffer)
            img.anchor = 'A1'
            ir_sheet.add_image(img)

        # График U(R)
        if 'U(R), В' in processed_data:
            ur_sheet = workbook.create_sheet("График U(R)")

            plt.figure(figsize=(10, 6))
            plt.plot(R_data, processed_data['U(R), В'], 'ms-', linewidth=2, markersize=6)
            plt.xlabel('R магазина, Ом')
            plt.ylabel('U(R), В')
            plt.title('Зависимость напряжения от сопротивления магазина')
            plt.grid(True, alpha=0.3)

            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
            plt.close()

            img_buffer.seek(0)
            img = Image(img_buffer)
            img.anchor = 'A1'
            ur_sheet.add_image(img)

        # График P(R)
        if 'P(R), мВ' in processed_data:
            pr_sheet = workbook.create_sheet("График P(R)")

            plt.figure(figsize=(10, 6))
            plt.plot(R_data, processed_data['P(R), мВ'], 'cd-', linewidth=2, markersize=6)
            plt.xlabel('R магазина, Ом')
            plt.ylabel('P(R), мВ')
            plt.title('Зависимость мощности от сопротивления магазина')
            plt.grid(True, alpha=0.3)

            img_buffer = io.BytesIO()
            plt.savefig(img_buffer, format='png', dpi=150, bbox_inches='tight')
            plt.close()

            img_buffer.seek(0)
            img = Image(img_buffer)
            img.anchor = 'A1'
            pr_sheet.add_image(img)

        # Лист со статистикой
        stats_sheet = workbook.create_sheet("Статистика")

        stats_sheet['A1'] = "Статистика измерений"
        stats_sheet['A1'].font = Font(size=14, bold=True)

        # Заголовки статистики
        stats_sheet['A3'] = "Параметр"
        stats_sheet['B3'] = "Минимум"
        stats_sheet['C3'] = "Максимум"
        stats_sheet['D3'] = "Среднее"
        stats_sheet['E3'] = "Станд. отклонение"

        for cell in stats_sheet['A3:E3']:
            cell[0].font = Font(bold=True)
            cell[0].fill = PatternFill(start_color="E0E0E0", end_color="E0E0E0", fill_type="solid")

        # Статистика для каждого параметра
        row = 4
        for param in processed_data.keys():
            try:
                data_array = np.array(processed_data[param], dtype=float)
                stats_sheet[f'A{row}'] = param
                stats_sheet[f'B{row}'] = float(np.min(data_array))
                stats_sheet[f'C{row}'] = float(np.max(data_array))
                stats_sheet[f'D{row}'] = float(np.mean(data_array))
                stats_sheet[f'E{row}'] = float(np.std(data_array))
                row += 1
            except Exception as e:
                print(f"Ошибка при расчете статистики для {param}: {e}")
                stats_sheet[f'A{row}'] = param
                stats_sheet[f'B{row}'] = "Ошибка"
                stats_sheet[f'C{row}'] = "Ошибка"
                stats_sheet[f'D{row}'] = "Ошибка"
                stats_sheet[f'E{row}'] = "Ошибка"
                row += 1

        # Подгоняем ширину столбцов для статистики
        for column_cells in stats_sheet.columns:
            length = max(len(str(cell.value)) for cell in column_cells)
            stats_sheet.column_dimensions[column_cells[0].column_letter].width = min(length + 2, 20)

        # Сохраняем workbook
        workbook.save(full_path)

        return full_path
    except Exception as e:
        print(f"Критическая ошибка при создании Excel файла: {e}")
        raise


def open_excel_file(file_path):
    """
    Автоматически открывает Excel файл
    """
    try:
        import subprocess
        import sys
        if sys.platform.startswith('win'):
            os.startfile(file_path)
        elif sys.platform.startswith('darwin'):
            subprocess.run(['open', file_path], check=True)
        else:
            subprocess.run(['xdg-open', file_path], check=True)
        print(f"✓ Excel файл открыт: {file_path}")
    except Exception as e:
        print(f"⚠ Не удалось автоматически открыть Excel: {e}")
        print(f"Файл сохранен по пути: {file_path}")

# Упрощенная версия для использования в потоках
def save_temperature_dependence_to_excel_simple(data_dict):
    """
    Упрощенная версия для использования в потоках
    """
    try:
        file_path = save_temperature_dependence_to_excel(data_dict)
        open_excel_file(file_path)
        return file_path
    except Exception as e:
        print(f"Ошибка при создании Excel файла температурной зависимости: {e}")
        return None

# Пример использования
if __name__ == "__main__":
    # Тестовые данные
    test_data = {
        'Time': [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        'R магазина, Ом': [],
        'F(t), Гц': [9999985.093, 9999985.093, 9999985.093, 9999985.093],
        'F(t), ppm': [-1.491, -1.491, -1.491],
        'R1(t), Ом': [68.5, 68.5, 68.5, 68.5, 68.5],
        'U(t), В': [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
    }

    # Анализируем структуру
    analyze_data_structure(test_data)

    # Сохраняем данные
    saved_file_path = save_resonator_data_simple(test_data)
    if saved_file_path:
        print(f"✓ Данные успешно сохранены в файл: {saved_file_path}")
    else:
        print("✗ Не удалось сохранить данные")
    test_data = {
        'Time': [4.512966871261597, 100.17101526260376, 131.77341151237488, 200.5, 250.8],
        'Time_All': [4.512966871261597, 105.1848452091217, 237.45969343185425, 437.9, 688.7],
        'R магазина, Ом': [8900.0, 8600.0, 8300.0, 8000.0, 7700.0],
        'F(R), ppm': [-1.232, -1.353, -1.247, -1.189, -1.275],
        'U(R), В': [0.007, 3.122, 3.396, 3.521, 3.678],
        'I(R), мА': [0.01, 24.27, 23.36, 22.45, 21.89],
        'P(R), мВ': [0.0, 75.7, 79.3, 79.0, 80.5],
        'R1(R), Ом': []
    }

    print("Создание Excel отчета температурной зависимости...")

    # Сохраняем в Excel
    saved_file_path = save_temperature_dependence_to_excel_simple(test_data)
    if saved_file_path:
        print(f"✓ Excel отчет успешно создан: {saved_file_path}")
    else:
        print("✗ Не удалось создать Excel отчет")

