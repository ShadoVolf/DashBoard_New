import pandas as pd
import matplotlib
from scipy.signal import savgol_filter

import Options

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np
import os
from datetime import datetime
import subprocess
import sys


def save_resonator_data_to_pdf(data_dict):
    """
    Сохраняет данные резонатора в PDF файл с графиками и автоматически открывает его
    """

    # Создаем папки если их нет
    base_dir = Options.get_rt_measure_protokol_path()
    measurements_dir = os.path.join(base_dir, "Измеритель_РТ")
    os.makedirs(measurements_dir, exist_ok=True)

    # Генерируем имя файла с текущей датой и временем
    current_time = datetime.now()
    time_str = current_time.strftime("%Y-%m-%d_%H-%M-%S")
    readable_time = current_time.strftime("%d.%m.%Y %H:%M:%S")
    filename = f"Измерение_резонатора_{time_str}.pdf"
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

    # Создаем списки для статистики
    empty_keys = [key for key in data_dict.keys() if len(data_dict.get(key, [])) == 0]

    # Создаем PDF файл
    with PdfPages(full_path) as pdf:
        # Первая страница - информационная
        fig_info = plt.figure(figsize=(11.69, 8.27))  # A4 landscape
        fig_info.suptitle('Измерение параметров резонатора', fontsize=16, fontweight='bold')

        # Добавляем информацию
        info_text = [
            f"Дата и время: {readable_time}",
            f"Количество точек измерения: {min_length}",
            f"Длительность измерения: {processed_data['Time'][-1]:.2f} сек",
            "",
            "Сохраненные параметры:",
        ]

        # Добавляем информацию о параметрах
        for key in processed_data.keys():
            if key != 'Time':
                info_text.append(f"  • {key}: {len(processed_data[key])} записей")

        if empty_keys:
            info_text.extend([
                "",
                "Исключенные пустые параметры:",
            ])
            for key in empty_keys:
                info_text.append(f"  • {key}")

        info_text.extend([
            "",
            "Обработка данных:",
            f"  • Все массивы обрезаны до {min_length} точек (минимальная длина)",
            "  • Пустые массивы исключены из отчета"
        ])

        # Создаем текстовое поле
        plt.figtext(0.05, 0.9, '\n'.join(info_text), fontsize=10,
                    verticalalignment='top', fontfamily='DejaVu Sans')
        plt.axis('off')

        pdf.savefig(fig_info, bbox_inches='tight')
        plt.close(fig_info)

        # Создаем графики для каждого параметра
        time_data = processed_data['Time']
        columns_to_plot = [col for col in processed_data.keys() if col != 'Time']

        # Создаем отдельный график для каждого параметра (по одному на страницу)
        for i, column in enumerate(columns_to_plot):
            fig, ax = plt.subplots(figsize=(11.69, 8.27))

            # Рисуем основной график
            ax.plot(time_data, processed_data[column], 'b-', linewidth=2, alpha=0.8)
            ax.set_xlabel('Время (секунды)', fontsize=12)
            ax.set_ylabel(column, fontsize=12)
            ax.set_title(f'{column} от времени', fontsize=14, fontweight='bold')
            ax.grid(True, alpha=0.3)

            # Добавляем статистику
            data_array = processed_data[column]
            data_min = min(data_array)
            data_max = max(data_array)
            data_mean = np.mean(data_array)
            data_std = np.std(data_array)

            stats_text = (f'Минимум: {data_min:.6f}\n'
                          f'Максимум: {data_max:.6f}\n'
                          f'Среднее: {data_mean:.6f}\n'
                          f'Станд. отклонение: {data_std:.6f}\n'
                          f'Количество точек: {len(data_array)}')

            # Добавляем статистику в текстовое поле
            ax.text(0.02, 0.98, stats_text, transform=ax.transAxes, fontsize=10,
                    verticalalignment='top', bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

            plt.tight_layout()
            pdf.savefig(fig, bbox_inches='tight')
            plt.close(fig)

        # Добавляем страницу с таблицей статистики
        fig_stats = plt.figure(figsize=(11.69, 8.27))
        fig_stats.suptitle('Сводная статистика измерений', fontsize=16, fontweight='bold')

        # Создаем данные для таблицы
        table_data = []
        headers = ['Параметр', 'Минимум', 'Максимум', 'Среднее', 'Станд. отклонение']

        for column in columns_to_plot:
            data_array = processed_data[column]
            table_data.append([
                column,
                f"{min(data_array):.6f}",
                f"{max(data_array):.6f}",
                f"{np.mean(data_array):.6f}",
                f"{np.std(data_array):.6f}"
            ])

        # Создаем таблицу
        ax_table = plt.subplot(111)
        ax_table.axis('tight')
        ax_table.axis('off')

        table = ax_table.table(cellText=table_data,
                               colLabels=headers,
                               cellLoc='center',
                               loc='center',
                               bbox=[0.1, 0.2, 0.8, 0.6])

        table.auto_set_font_size(False)
        table.set_fontsize(10)
        table.scale(1.2, 1.8)

        # Стилизуем заголовки
        for i in range(len(headers)):
            table[(0, i)].set_facecolor('#4CAF50')
            table[(0, i)].set_text_props(weight='bold', color='white')

        # Добавляем информацию об обработке данных
        processing_info = (f"Отчет сгенерирован: {readable_time}\n"
                           f"Всего параметров: {len(columns_to_plot)}\n"
                           f"Точек измерения: {min_length}\n"
                           f"Исключено пустых параметров: {len(empty_keys)}")

        plt.figtext(0.1, 0.05, processing_info, fontsize=10,
                    bbox=dict(boxstyle='round', facecolor='lightgray', alpha=0.5))

        pdf.savefig(fig_stats, bbox_inches='tight')
        plt.close(fig_stats)

        # Добавляем метаданные
        pdf_metadata = pdf.infodict()
        pdf_metadata['Title'] = f'Измерение резонатора {readable_time}'
        pdf_metadata['Author'] = 'Измеритель РТ'
        pdf_metadata['Subject'] = 'Параметры резонатора'
        pdf_metadata['Keywords'] = 'резонатор, измерения, параметры'
        pdf_metadata['CreationDate'] = current_time

    # Автоматически открываем PDF файл
    open_pdf_file(full_path)

    return full_path


def open_pdf_file(file_path):
    """
    Автоматически открывает PDF файл в зависимости от операционной системы
    """
    try:
        if sys.platform.startswith('win'):
            # Windows
            os.startfile(file_path)
        elif sys.platform.startswith('darwin'):
            # macOS
            subprocess.run(['open', file_path], check=True)
        else:
            # Linux
            subprocess.run(['xdg-open', file_path], check=True)
        print(f"✓ PDF файл открыт: {file_path}")
    except Exception as e:
        print(f"⚠ Не удалось автоматически открыть PDF: {e}")
        print(f"Файл сохранен по пути: {file_path}")


def analyze_data_for_pdf(data_dict):
    """Анализирует структуру данных для PDF отчета"""
    print("=== ПОДГОТОВКА PDF ОТЧЕТА ===")

    non_empty_keys = {key: value for key, value in data_dict.items()
                      if len(value) > 0 and key != 'Time'}

    if non_empty_keys:
        min_length = min(len(arr) for arr in non_empty_keys.values())
        print(f"✓ Будет создано {len(non_empty_keys)} графиков")
        print(f"✓ Длина массивов после обрезки: {min_length}")

    empty_keys = [key for key in data_dict.keys() if len(data_dict.get(key, [])) == 0]
    if empty_keys:
        print(f"⚠ Исключено пустых параметров: {len(empty_keys)}")

    print("=" * 40)


# Упрощенная версия для использования в потоках
def save_resonator_data_to_pdf_simple(data_dict):
    """
    Упрощенная версия для использования в потоках
    """
    try:
        return save_resonator_data_to_pdf(data_dict)
    except Exception as e:
        print(f"Ошибка при создании PDF: {e}")
        return None


def save_temperature_dependence_to_pdf1(data_dict):
    """
    Сохраняет данные температурной зависимости резонатора в PDF файл
    с аппроксимацией и поиском экстремума для F(R)
    """

    # Создаем папки если их нет
    base_dir = os.path.dirname(os.path.abspath(__file__))
    measurements_dir = os.path.join(base_dir, "Измерения", "Измеритель_РТ")
    os.makedirs(measurements_dir, exist_ok=True)

    # Генерируем имя файла с текущей датой и временем
    current_time = datetime.now()
    time_str = current_time.strftime("%Y-%m-%d_%H-%M-%S")
    readable_time = current_time.strftime("%d.%m.%Y %H:%M:%S")
    filename = f"Температурная_зависимость_{time_str}.pdf"
    full_path = os.path.join(measurements_dir, filename)

    # Обрабатываем данные: удаляем пустые ключи и обрезаем до минимальной длины
    processed_data = {}

    # Определяем ключи для обработки (исключаем Time_All и пустые массивы)
    keys_to_process = ['R магазина, Ом', 'F(R), ppm', 'U(R), В', 'I(R), мА', 'P(R), мВ']
    non_empty_keys = {key: data_dict[key] for key in keys_to_process
                      if key in data_dict and len(data_dict[key]) > 0}

    if not non_empty_keys:
        raise ValueError("Нет данных для сохранения (все массивы пустые)")

    # Находим минимальную длину среди всех непустых массивов
    min_length = min(len(arr) for arr in non_empty_keys.values())

    # Обрезаем все массивы до минимальной длины
    for key in keys_to_process:
        if key in data_dict and len(data_dict[key]) > 0:
            processed_data[key] = data_dict[key][:min_length]

    # Проверяем, что есть данные для R магазина и F(R)
    if 'R магазина, Ом' not in processed_data or 'F(R), ppm' not in processed_data:
        raise ValueError("Отсутствуют данные R магазина или F(R) для анализа")

    # Создаем PDF файл
    with PdfPages(full_path) as pdf:
        # Первая страница - информационная
        fig_info = plt.figure(figsize=(11.69, 8.27))
        fig_info.suptitle('Температурная зависимость резонатора', fontsize=16, fontweight='bold')

        # Добавляем информацию
        info_text = [
            f"Дата и время: {readable_time}",
            f"Количество точек измерения: {min_length}",
            f"Диапазон R магазина: {min(processed_data['R магазина, Ом']):.1f} - {max(processed_data['R магазина, Ом']):.1f} Ом",
            "",
            "Измеряемые параметры:",
        ]

        for key in processed_data.keys():
            info_text.append(f"  • {key}: {len(processed_data[key])} записей")

        # Добавляем информацию о времени измерений
        if 'Time' in data_dict and len(data_dict['Time']) > 0:
            info_text.extend([
                "",
                "Время измерений:",
                f"  • Общая длительность: {max(data_dict['Time']):.1f} сек",
                f"  • Время на точку: {np.mean(np.diff(data_dict['Time'][:min_length])):.1f} сек"
            ])

        # Создаем текстовое поле
        plt.figtext(0.05, 0.9, '\n'.join(info_text), fontsize=10,
                    verticalalignment='top', fontfamily='DejaVu Sans')
        plt.axis('off')

        pdf.savefig(fig_info, bbox_inches='tight')
        plt.close(fig_info)

        # График F(R) с аппроксимацией и экстремумом
        fig_fr = plt.figure(figsize=(11.69, 8.27))
        ax1 = plt.subplot(111)

        R_data = processed_data['R магазина, Ом']
        F_data = processed_data['F(R), ppm']

        # Строим исходные данные
        ax1.plot(R_data, F_data, 'bo-', linewidth=2, markersize=6, label='Измеренные данные')

        # Аппроксимация полиномом 2-й степени
        try:
            # Фильтруем данные для лучшей аппроксимации
            if len(R_data) >= 5:
                F_smooth = savgol_filter(F_data, min(5, len(F_data)), 2)
            else:
                F_smooth = F_data

            # Аппроксимация полиномом
            coeffs = np.polyfit(R_data, F_smooth, 2)
            poly_func = np.poly1d(coeffs)

            # Создаем плотную сетку для гладкой кривой
            R_fine = np.linspace(min(R_data), max(R_data), 100)
            F_fine = poly_func(R_fine)

            # Строим аппроксимацию
            ax1.plot(R_fine, F_fine, 'r-', linewidth=2, label='Аппроксимация (полином 2-й степени)')

            # Находим экстремум (вершину параболы)
            # Для ax² + bx + c экстремум в x = -b/(2a)
            a, b, c = coeffs
            R_extremum = -b / (2 * a)
            F_extremum = poly_func(R_extremum)

            # Определяем тип экстремума
            extremum_type = "минимум" if a > 0 else "максимум"

            # Отмечаем экстремум на графике
            ax1.plot(R_extremum, F_extremum, 'ro', markersize=10,
                     label=f'{extremum_type.capitalize()}: R={R_extremum:.1f} Ом, F={F_extremum:.3f} ppm')

            # Добавляем информацию об аппроксимации
            approx_info = (f"Аппроксимация: {coeffs[0]:.6f}·R² + {coeffs[1]:.6f}·R + {coeffs[2]:.6f}\n"
                           f"Экстремум: {extremum_type} при R = {R_extremum:.1f} Ом\n"
                           f"Значение F: {F_extremum:.3f} ppm")

            ax1.text(0.02, 0.98, approx_info, transform=ax1.transAxes, fontsize=10,
                     verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))

        except Exception as e:
            print(f"Ошибка аппроксимации F(R): {e}")
            ax1.text(0.02, 0.98, "Аппроксимация не удалась", transform=ax1.transAxes, fontsize=10,
                     verticalalignment='top', bbox=dict(boxstyle='round', facecolor='red', alpha=0.8))

        ax1.set_xlabel('R магазина, Ом', fontsize=12)
        ax1.set_ylabel('F(R), ppm', fontsize=12)
        ax1.set_title('Зависимость частоты от сопротивления магазина', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.legend()

        plt.tight_layout()
        pdf.savefig(fig_fr, bbox_inches='tight')
        plt.close(fig_fr)

        # График I(R)
        if 'I(R), мА' in processed_data:
            fig_ir = plt.figure(figsize=(11.69, 8.27))
            ax2 = plt.subplot(111)

            I_data = processed_data['I(R), мА']
            ax2.plot(R_data, I_data, 'g^-', linewidth=2, markersize=6)
            ax2.set_xlabel('R магазина, Ом', fontsize=12)
            ax2.set_ylabel('I(R), мА', fontsize=12)
            ax2.set_title('Зависимость тока от сопротивления магазина', fontsize=14, fontweight='bold')
            ax2.grid(True, alpha=0.3)

            # Добавляем статистику
            stats_text = (f"Мин: {min(I_data):.2f} мА\n"
                          f"Макс: {max(I_data):.2f} мА\n"
                          f"Среднее: {np.mean(I_data):.2f} мА")

            ax2.text(0.02, 0.98, stats_text, transform=ax2.transAxes, fontsize=10,
                     verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))

            plt.tight_layout()
            pdf.savefig(fig_ir, bbox_inches='tight')
            plt.close(fig_ir)

        # График U(R)
        if 'U(R), В' in processed_data:
            fig_ur = plt.figure(figsize=(11.69, 8.27))
            ax3 = plt.subplot(111)

            U_data = processed_data['U(R), В']
            ax3.plot(R_data, U_data, 'ms-', linewidth=2, markersize=6)
            ax3.set_xlabel('R магазина, Ом', fontsize=12)
            ax3.set_ylabel('U(R), В', fontsize=12)
            ax3.set_title('Зависимость напряжения от сопротивления магазина', fontsize=14, fontweight='bold')
            ax3.grid(True, alpha=0.3)

            # Добавляем статистику
            stats_text = (f"Мин: {min(U_data):.3f} В\n"
                          f"Макс: {max(U_data):.3f} В\n"
                          f"Среднее: {np.mean(U_data):.3f} В")

            ax3.text(0.02, 0.98, stats_text, transform=ax3.transAxes, fontsize=10,
                     verticalalignment='top', bbox=dict(boxstyle='round', facecolor='violet', alpha=0.8))

            plt.tight_layout()
            pdf.savefig(fig_ur, bbox_inches='tight')
            plt.close(fig_ur)

        # График P(R)
        if 'P(R), мВ' in processed_data:
            fig_pr = plt.figure(figsize=(11.69, 8.27))
            ax4 = plt.subplot(111)

            P_data = processed_data['P(R), мВ']
            ax4.plot(R_data, P_data, 'cd-', linewidth=2, markersize=6)
            ax4.set_xlabel('R магазина, Ом', fontsize=12)
            ax4.set_ylabel('P(R), мВ', fontsize=12)
            ax4.set_title('Зависимость мощности от сопротивления магазина', fontsize=14, fontweight='bold')
            ax4.grid(True, alpha=0.3)

            # Добавляем статистику
            stats_text = (f"Мин: {min(P_data):.1f} мВ\n"
                          f"Макс: {max(P_data):.1f} мВ\n"
                          f"Среднее: {np.mean(P_data):.1f} мВ")

            ax4.text(0.02, 0.98, stats_text, transform=ax4.transAxes, fontsize=10,
                     verticalalignment='top', bbox=dict(boxstyle='round', facecolor='cyan', alpha=0.8))

            plt.tight_layout()
            pdf.savefig(fig_pr, bbox_inches='tight')
            plt.close(fig_pr)

        # Страница со сводной таблицей
        fig_table = plt.figure(figsize=(11.69, 8.27))
        fig_table.suptitle('Сводные данные измерений', fontsize=16, fontweight='bold')

        # Создаем данные для таблицы
        table_data = []
        headers = ['R магазина, Ом', 'F(R), ppm', 'U(R), В', 'I(R), мА', 'P(R), мВ']

        for i in range(min_length):
            row = [
                f"{R_data[i]:.1f}",
                f"{F_data[i]:.3f}",
                f"{processed_data.get('U(R), В', [0])[i]:.3f}" if 'U(R), В' in processed_data else "N/A",
                f"{processed_data.get('I(R), мА', [0])[i]:.2f}" if 'I(R), мА' in processed_data else "N/A",
                f"{processed_data.get('P(R), мВ', [0])[i]:.1f}" if 'P(R), мВ' in processed_data else "N/A"
            ]
            table_data.append(row)

        # Создаем таблицу
        ax_table = plt.subplot(111)
        ax_table.axis('tight')
        ax_table.axis('off')

        table = ax_table.table(cellText=table_data,
                               colLabels=headers,
                               cellLoc='center',
                               loc='center',
                               bbox=[0.1, 0.3, 0.8, 0.6])

        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1.2, 1.5)

        # Стилизуем заголовки
        for i in range(len(headers)):
            table[(0, i)].set_facecolor('#4CAF50')
            table[(0, i)].set_text_props(weight='bold', color='white')

        pdf.savefig(fig_table, bbox_inches='tight')
        plt.close(fig_table)

        # Добавляем метаданные
        pdf_metadata = pdf.infodict()
        pdf_metadata['Title'] = f'Температурная зависимость резонатора {readable_time}'
        pdf_metadata['Author'] = 'Измеритель РТ'
        pdf_metadata['Subject'] = 'Температурная зависимость параметров резонатора'
        pdf_metadata['Keywords'] = 'резонатор, температурная зависимость, измерения'
        pdf_metadata['CreationDate'] = current_time

    # Автоматически открываем PDF файл
    open_pdf_file(full_path)

    return full_path


def save_temperature_dependence_to_pdf(data_dict):
    """
    Сохраняет данные температурной зависимости резонатора в PDF файл
    с аппроксимацией полиномом 3-го порядка и сплайном, поиском двух экстремумов для F(R)
    """

    # Создаем папки если их нет
    base_dir = os.path.dirname(os.path.abspath(__file__))
    measurements_dir = os.path.join(base_dir, "Измерения", "Измеритель_РТ")
    os.makedirs(measurements_dir, exist_ok=True)

    # Генерируем имя файла с текущей датой и временем
    current_time = datetime.now()
    time_str = current_time.strftime("%Y-%m-%d_%H-%M-%S")
    readable_time = current_time.strftime("%d.%m.%Y %H:%M:%S")
    filename = f"Температурная_зависимость_{time_str}.pdf"
    full_path = os.path.join(measurements_dir, filename)

    # Обрабатываем данные: удаляем пустые ключи и обрезаем до минимальной длины
    processed_data = {}

    # Определяем ключи для обработки (исключаем Time_All и пустые массивы)
    keys_to_process = ['R магазина, Ом', 'F(R), ppm', 'U(R), В', 'I(R), мА', 'P(R), мВ']
    non_empty_keys = {key: data_dict[key] for key in keys_to_process
                      if key in data_dict and len(data_dict[key]) > 0}

    if not non_empty_keys:
        raise ValueError("Нет данных для сохранения (все массивы пустые)")

    # Находим минимальную длину среди всех непустых массивов
    min_length = min(len(arr) for arr in non_empty_keys.values())

    # Обрезаем все массивы до минимальной длины
    for key in keys_to_process:
        if key in data_dict and len(data_dict[key]) > 0:
            processed_data[key] = data_dict[key][:min_length]

    # Проверяем, что есть данные для R магазина и F(R)
    if 'R магазина, Ом' not in processed_data or 'F(R), ppm' not in processed_data:
        raise ValueError("Отсутствуют данные R магазина или F(R) для анализа")

    # Создаем PDF файл
    with PdfPages(full_path) as pdf:
        # Первая страница - информационная
        fig_info = plt.figure(figsize=(11.69, 8.27))
        fig_info.suptitle('Температурная зависимость резонатора', fontsize=16, fontweight='bold')

        # Добавляем информацию
        info_text = [
            f"Дата и время: {readable_time}",
            f"Количество точек измерения: {min_length}",
            f"Диапазон R магазина: {min(processed_data['R магазина, Ом']):.1f} - {max(processed_data['R магазина, Ом']):.1f} Ом",
            "",
            "Измеряемые параметры:",
        ]

        for key in processed_data.keys():
            info_text.append(f"  • {key}: {len(processed_data[key])} записей")

        # Добавляем информацию о времени измерений
        if 'Time' in data_dict and len(data_dict['Time']) > 0:
            info_text.extend([
                "",
                "Время измерений:",
                f"  • Общая длительность: {max(data_dict['Time']):.1f} сек",
                f"  • Время на точку: {np.mean(np.diff(data_dict['Time'][:min_length])):.1f} сек"
            ])

        # Создаем текстовое поле
        plt.figtext(0.05, 0.9, '\n'.join(info_text), fontsize=10,
                    verticalalignment='top', fontfamily='DejaVu Sans')
        plt.axis('off')

        pdf.savefig(fig_info, bbox_inches='tight')
        plt.close(fig_info)

        # График F(R) с аппроксимацией полиномом 3-го порядка и сплайном
        fig_fr = plt.figure(figsize=(11.69, 8.27))
        ax1 = plt.subplot(111)

        R_data = processed_data['R магазина, Ом']
        F_data = processed_data['F(R), ppm']

        # Строим исходные данные
        ax1.plot(R_data, F_data, 'bo-', linewidth=2, markersize=6, label='Измеренные данные')

        # Аппроксимация полиномом 3-й степени
        try:
            # Аппроксимация полиномом 3-й степени
            coeffs_3 = np.polyfit(R_data, F_data, 3)
            poly_func_3 = np.poly1d(coeffs_3)

            # Создаем плотную сетку для гладкой кривой
            R_fine = np.linspace(min(R_data), max(R_data), 500)
            F_fine_3 = poly_func_3(R_fine)

            # Строим аппроксимацию полиномом 3-й степени
            ax1.plot(R_fine, F_fine_3, 'r-', linewidth=2,
                     label='Аппроксимация (полином 3-й степени)')

            # Находим экстремумы полинома 3-й степени
            # Производная: 3*coeffs_3[0]*x^2 + 2*coeffs_3[1]*x + coeffs_3[2]
            derivative_coeffs = [3 * coeffs_3[0], 2 * coeffs_3[1], coeffs_3[2]]
            roots = np.roots(derivative_coeffs)

            # Фильтруем действительные корни в пределах диапазона данных
            real_roots = []
            for root in roots:
                if np.isreal(root) and min(R_data) <= root.real <= max(R_data):
                    real_roots.append(root.real)

            # Сортируем корни
            real_roots.sort()
            extremums_poly = []

            for root in real_roots:
                F_val = poly_func_3(root)
                # Определяем тип экстремума по второй производной
                second_derivative = 6 * coeffs_3[0] * root + 2 * coeffs_3[1]
                extremum_type = "минимум" if second_derivative > 0 else "максимум"
                extremums_poly.append((root, F_val, extremum_type))

            # Отмечаем экстремумы на графике
            colors = ['red', 'orange']
            for i, (R_ext, F_ext, ext_type) in enumerate(extremums_poly):
                if i < 2:  # Ограничиваемся первыми двумя экстремумами
                    ax1.plot(R_ext, F_ext, 'o', markersize=10, color=colors[i],
                             label=f'{ext_type.capitalize()} (полином): R={R_ext:.1f} Ом, F={F_ext:.3f} ppm')

        except Exception as e:
            print(f"Ошибка аппроксимации полиномом 3-й степени: {e}")

        # Аппроксимация сплайном с сшивкой по первой и второй производной
        try:
            from scipy.interpolate import CubicSpline

            # Создаем сплайн с естественными граничными условиями (вторая производная = 0 на концах)
            # Это обеспечивает сшивку по первой и второй производной
            spline = CubicSpline(R_data, F_data, bc_type='natural')

            # Вычисляем сплайн на плотной сетке
            F_fine_spline = spline(R_fine)

            # Строим аппроксимацию сплайном
            ax1.plot(R_fine, F_fine_spline, 'g--', linewidth=2,
                     label='Аппроксимация (сплайн)')

            # Находим экстремумы сплайна численно
            # Вычисляем первую производную сплайна
            spline_derivative = spline.derivative()
            der_values = spline_derivative(R_fine)

            # Ищем смену знака производной для нахождения экстремумов
            extremums_spline = []
            for i in range(1, len(der_values)):
                if der_values[i - 1] * der_values[i] <= 0:  # Смена знака
                    # Уточняем положение экстремума методом деления отрезка
                    left = R_fine[i - 1]
                    right = R_fine[i]

                    # Ищем корень производной (экстремум функции)
                    tolerance = 1e-6
                    while right - left > tolerance:
                        mid = (left + right) / 2
                        if spline_derivative(left) * spline_derivative(mid) <= 0:
                            right = mid
                        else:
                            left = mid

                    R_ext = (left + right) / 2
                    F_ext = spline(R_ext)

                    # Определяем тип экстремума по второй производной
                    second_der = spline_derivative.derivative()(R_ext)
                    extremum_type = "минимум" if second_der > 0 else "максимум"

                    extremums_spline.append((R_ext, F_ext, extremum_type))

            # Убираем дубликаты (слишком близкие экстремумы)
            unique_extremums = []
            for ext in extremums_spline:
                is_unique = True
                for existing in unique_extremums:
                    if abs(ext[0] - existing[0]) < (max(R_data) - min(R_data)) * 0.05:
                        is_unique = False
                        break
                if is_unique:
                    unique_extremums.append(ext)

            # Сортируем по R
            unique_extremums.sort(key=lambda x: x[0])

            # Отмечаем экстремумы сплайна на графике
            colors_spline = ['darkgreen', 'lime']
            for i, (R_ext, F_ext, ext_type) in enumerate(unique_extremums):
                if i < 2:  # Ограничиваемся первыми двумя экстремумами
                    ax1.plot(R_ext, F_ext, 's', markersize=8, color=colors_spline[i],
                             label=f'{ext_type.capitalize()} (сплайн): R={R_ext:.1f} Ом, F={F_ext:.3f} ppm')

        except Exception as e:
            print(f"Ошибка аппроксимации сплайном: {e}")

        # Добавляем информацию об аппроксимациях
        approx_info = []
        if 'coeffs_3' in locals():
            approx_info.append(
                f"Полином 3-й степени: {coeffs_3[0]:.6f}·R³ + {coeffs_3[1]:.6f}·R² + {coeffs_3[2]:.6f}·R + {coeffs_3[3]:.6f}")

        if 'extremums_poly' in locals() and extremums_poly:
            approx_info.append("Экстремумы (полином):")
            for R_ext, F_ext, ext_type in extremums_poly[:2]:  # Показываем только первые два
                approx_info.append(f"  {ext_type}: R={R_ext:.1f} Ом, F={F_ext:.3f} ppm")

        if 'unique_extremums' in locals() and unique_extremums:
            approx_info.append("Экстремумы (сплайн):")
            for R_ext, F_ext, ext_type in unique_extremums[:2]:  # Показываем только первые два
                approx_info.append(f"  {ext_type}: R={R_ext:.1f} Ом, F={F_ext:.3f} ppm")

        if approx_info:
            ax1.text(0.02, 0.98, '\n'.join(approx_info), transform=ax1.transAxes, fontsize=9,
                     verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightblue', alpha=0.8))

        ax1.set_xlabel('R магазина, Ом', fontsize=12)
        ax1.set_ylabel('F(R), ppm', fontsize=12)
        ax1.set_title('Зависимость частоты от сопротивления магазина', fontsize=14, fontweight='bold')
        ax1.grid(True, alpha=0.3)
        ax1.legend(loc='best')

        plt.tight_layout()
        pdf.savefig(fig_fr, bbox_inches='tight')
        plt.close(fig_fr)

        # Остальные графики (I(R), U(R), P(R)) остаются без изменений
        # График I(R)
        if 'I(R), мА' in processed_data:
            fig_ir = plt.figure(figsize=(11.69, 8.27))
            ax2 = plt.subplot(111)

            I_data = processed_data['I(R), мА']
            ax2.plot(R_data, I_data, 'g^-', linewidth=2, markersize=6)
            ax2.set_xlabel('R магазина, Ом', fontsize=12)
            ax2.set_ylabel('I(R), мА', fontsize=12)
            ax2.set_title('Зависимость тока от сопротивления магазина', fontsize=14, fontweight='bold')
            ax2.grid(True, alpha=0.3)

            # Добавляем статистику
            stats_text = (f"Мин: {min(I_data):.2f} мА\n"
                          f"Макс: {max(I_data):.2f} мА\n"
                          f"Среднее: {np.mean(I_data):.2f} мА")

            ax2.text(0.02, 0.98, stats_text, transform=ax2.transAxes, fontsize=10,
                     verticalalignment='top', bbox=dict(boxstyle='round', facecolor='lightgreen', alpha=0.8))

            plt.tight_layout()
            pdf.savefig(fig_ir, bbox_inches='tight')
            plt.close(fig_ir)

        # График U(R)
        if 'U(R), В' in processed_data:
            fig_ur = plt.figure(figsize=(11.69, 8.27))
            ax3 = plt.subplot(111)

            U_data = processed_data['U(R), В']
            ax3.plot(R_data, U_data, 'ms-', linewidth=2, markersize=6)
            ax3.set_xlabel('R магазина, Ом', fontsize=12)
            ax3.set_ylabel('U(R), В', fontsize=12)
            ax3.set_title('Зависимость напряжения от сопротивления магазина', fontsize=14, fontweight='bold')
            ax3.grid(True, alpha=0.3)

            # Добавляем статистику
            stats_text = (f"Мин: {min(U_data):.3f} В\n"
                          f"Макс: {max(U_data):.3f} В\n"
                          f"Среднее: {np.mean(U_data):.3f} В")

            ax3.text(0.02, 0.98, stats_text, transform=ax3.transAxes, fontsize=10,
                     verticalalignment='top', bbox=dict(boxstyle='round', facecolor='violet', alpha=0.8))

            plt.tight_layout()
            pdf.savefig(fig_ur, bbox_inches='tight')
            plt.close(fig_ur)

        # График P(R)
        if 'P(R), мВ' in processed_data:
            fig_pr = plt.figure(figsize=(11.69, 8.27))
            ax4 = plt.subplot(111)

            P_data = processed_data['P(R), мВ']
            ax4.plot(R_data, P_data, 'cd-', linewidth=2, markersize=6)
            ax4.set_xlabel('R магазина, Ом', fontsize=12)
            ax4.set_ylabel('P(R), мВ', fontsize=12)
            ax4.set_title('Зависимость мощности от сопротивления магазина', fontsize=14, fontweight='bold')
            ax4.grid(True, alpha=0.3)

            # Добавляем статистику
            stats_text = (f"Мин: {min(P_data):.1f} мВ\n"
                          f"Макс: {max(P_data):.1f} мВ\n"
                          f"Среднее: {np.mean(P_data):.1f} мВ")

            ax4.text(0.02, 0.98, stats_text, transform=ax4.transAxes, fontsize=10,
                     verticalalignment='top', bbox=dict(boxstyle='round', facecolor='cyan', alpha=0.8))

            plt.tight_layout()
            pdf.savefig(fig_pr, bbox_inches='tight')
            plt.close(fig_pr)

        # Страница со сводной таблицей (без изменений)
        fig_table = plt.figure(figsize=(11.69, 8.27))
        fig_table.suptitle('Сводные данные измерений', fontsize=16, fontweight='bold')

        # Создаем данные для таблицы
        table_data = []
        headers = ['R магазина, Ом', 'F(R), ppm', 'U(R), В', 'I(R), мА', 'P(R), мВ']

        for i in range(min_length):
            row = [
                f"{R_data[i]:.1f}",
                f"{F_data[i]:.3f}",
                f"{processed_data.get('U(R), В', [0])[i]:.3f}" if 'U(R), В' in processed_data else "N/A",
                f"{processed_data.get('I(R), мА', [0])[i]:.2f}" if 'I(R), мА' in processed_data else "N/A",
                f"{processed_data.get('P(R), мВ', [0])[i]:.1f}" if 'P(R), мВ' in processed_data else "N/A"
            ]
            table_data.append(row)

        # Создаем таблицу
        ax_table = plt.subplot(111)
        ax_table.axis('tight')
        ax_table.axis('off')

        table = ax_table.table(cellText=table_data,
                               colLabels=headers,
                               cellLoc='center',
                               loc='center',
                               bbox=[0.1, 0.3, 0.8, 0.6])

        table.auto_set_font_size(False)
        table.set_fontsize(8)
        table.scale(1.2, 1.5)

        # Стилизуем заголовки
        for i in range(len(headers)):
            table[(0, i)].set_facecolor('#4CAF50')
            table[(0, i)].set_text_props(weight='bold', color='white')

        pdf.savefig(fig_table, bbox_inches='tight')
        plt.close(fig_table)

        # Добавляем метаданные
        pdf_metadata = pdf.infodict()
        pdf_metadata['Title'] = f'Температурная зависимость резонатора {readable_time}'
        pdf_metadata['Author'] = 'Измеритель РТ'
        pdf_metadata['Subject'] = 'Температурная зависимость параметров резонатора'
        pdf_metadata['Keywords'] = 'резонатор, температурная зависимость, измерения'
        pdf_metadata['CreationDate'] = current_time

    # Автоматически открываем PDF файл
    open_pdf_file(full_path)

    return full_path

# Упрощенная версия для использования в потоках
def save_temperature_dependence_simple(data_dict):
    """
    Упрощенная версия для использования в потоках
    """
    try:
        return save_temperature_dependence_to_pdf(data_dict)
    except Exception as e:
        print(f"Ошибка при создании PDF температурной зависимости: {e}")
        return None


# Пример использования
if __name__ == "__main__":
    # Тестовые данные
    test_data = {
        'Time': [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        'R магазина, Ом': [],
        'F(t), Гц': [9999985.093, 9999984.5, 9999983.8, 9999983.2, 9999982.9],
        'F(t), ppm': [-1.491, -1.5, -1.52, -1.55, -1.57],
        'R1(t), Ом': [68.5, 68.6, 68.7, 68.8, 68.9],
        'U(t), В': [0.0, 0.1, 0.2, 0.3, 0.4],
    }

    # Анализируем структуру
    analyze_data_for_pdf(test_data)

    # Сохраняем в PDF
    saved_file_path = save_resonator_data_to_pdf_simple(test_data)
    if saved_file_path:
        print(f"✓ PDF отчет успешно создан: {saved_file_path}")
    else:
        print("✗ Не удалось создать PDF отчет")

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

    print("Создание PDF отчета температурной зависимости...")

    # Сохраняем в PDF
    saved_file_path = save_temperature_dependence_simple(test_data)
    if saved_file_path:
        print(f"✓ PDF отчет успешно создан: {saved_file_path}")
    else:
        print("✗ Не удалось создать PDF отчет")