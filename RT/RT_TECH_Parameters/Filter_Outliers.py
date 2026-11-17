import numpy as np
import pandas as pd
from scipy import stats
import matplotlib

matplotlib.use('Agg')
import matplotlib.pyplot as plt
from datetime import datetime


def filter_resonator_outliers(data_dict, method='iqr', threshold=3.0, window_size=5,
                              show_plots=False, save_plots=False):
    """
    Фильтрует выбросы в данных резонатора различными методами

    Args:
        data_dict (dict): Словарь с данными измерений
        method (str): Метод фильтрации ('iqr', 'zscore', 'mad', 'savitzky_golay')
        threshold (float): Порог для определения выбросов
        window_size (int): Размер окна для скользящих методов
        show_plots (bool): Показать графики до/после фильтрации
        save_plots (bool): Сохранить графики в файл

    Returns:
        dict: Отфильтрованные данные
        dict: Статистика фильтрации
    """

    # Обрабатываем данные: удаляем пустые ключи и обрезаем до минимальной длины
    processed_data = {}

    # Удаляем пустые ключи
    non_empty_keys = {key: value for key, value in data_dict.items()
                      if len(value) > 0 and key != 'Time'}

    if not non_empty_keys:
        raise ValueError("Нет данных для фильтрации (все массивы пустые)")

    # Находим минимальную длину среди всех непустых массивов
    min_length = min(len(arr) for arr in non_empty_keys.values())

    # Обрезаем все массивы до минимальной длины
    if 'Time' in data_dict and len(data_dict['Time']) > 0:
        processed_data['Time'] = data_dict['Time'][:min_length]
    else:
        processed_data['Time'] = [i * 0.1 for i in range(min_length)]

    for key, value in non_empty_keys.items():
        processed_data[key] = value[:min_length]

    # Применяем фильтрацию
    filtered_data = {'Time': processed_data['Time']}
    statistics = {}

    for key in non_empty_keys.keys():
        original_data = processed_data[key]

        if method == 'iqr':
            filtered, stats_info = _filter_iqr(original_data, threshold)
        elif method == 'zscore':
            filtered, stats_info = _filter_zscore(original_data, threshold)
        elif method == 'mad':
            filtered, stats_info = _filter_mad(original_data, threshold)
        elif method == 'savitzky_golay':
            filtered, stats_info = _filter_savitzky_golay(original_data, window_size)
        else:
            raise ValueError(f"Неизвестный метод фильтрации: {method}")

        filtered_data[key] = filtered
        statistics[key] = stats_info

        # Визуализация результатов
        if show_plots or save_plots:
            _plot_filtering_results(processed_data['Time'], original_data, filtered,
                                    key, method, stats_info, show_plots, save_plots)

    return filtered_data, statistics


def _filter_iqr(data, threshold=1.5):
    """Фильтрация по межквартильному размаху (IQR)"""
    q1 = np.percentile(data, 25)
    q3 = np.percentile(data, 75)
    iqr = q3 - q1
    lower_bound = q1 - threshold * iqr
    upper_bound = q3 + threshold * iqr

    # Находим выбросы
    outliers_mask = (data < lower_bound) | (data > upper_bound)
    filtered_data = np.where(outliers_mask, np.nan, data)

    # Интерполируем пропущенные значения
    filtered_data = _interpolate_nans(filtered_data)

    stats_info = {
        'method': 'IQR',
        'threshold': threshold,
        'q1': q1,
        'q3': q3,
        'iqr': iqr,
        'lower_bound': lower_bound,
        'upper_bound': upper_bound,
        'outliers_count': np.sum(outliers_mask),
        'outliers_percent': (np.sum(outliers_mask) / len(data)) * 100
    }

    return filtered_data.tolist(), stats_info


def _filter_zscore(data, threshold=3.0):
    """Фильтрация по Z-score"""
    z_scores = np.abs(stats.zscore(data))
    outliers_mask = z_scores > threshold

    filtered_data = np.where(outliers_mask, np.nan, data)
    filtered_data = _interpolate_nans(filtered_data)

    stats_info = {
        'method': 'Z-score',
        'threshold': threshold,
        'mean': np.mean(data),
        'std': np.std(data),
        'max_zscore': np.max(z_scores),
        'outliers_count': np.sum(outliers_mask),
        'outliers_percent': (np.sum(outliers_mask) / len(data)) * 100
    }

    return filtered_data.tolist(), stats_info


def _filter_mad(data, threshold=3.0):
    """Фильтрация по медианному абсолютному отклонению (MAD)"""
    median = np.median(data)
    mad = np.median(np.abs(data - median))

    # Масштабируем MAD для нормального распределения
    mad_z_scores = 0.6745 * (data - median) / mad
    outliers_mask = np.abs(mad_z_scores) > threshold

    filtered_data = np.where(outliers_mask, np.nan, data)
    filtered_data = _interpolate_nans(filtered_data)

    stats_info = {
        'method': 'MAD',
        'threshold': threshold,
        'median': median,
        'mad': mad,
        'max_mad_score': np.max(np.abs(mad_z_scores)),
        'outliers_count': np.sum(outliers_mask),
        'outliers_percent': (np.sum(outliers_mask) / len(data)) * 100
    }

    return filtered_data.tolist(), stats_info


def _filter_savitzky_golay(data, window_size=5):
    """Фильтрация методом Савицкого-Голея"""
    from scipy.signal import savgol_filter

    # Убедимся, что window_size нечетное и меньше длины данных
    window_size = min(window_size, len(data) - 1) if len(data) % 2 == 0 else min(window_size, len(data))
    if window_size % 2 == 0:
        window_size -= 1
    if window_size < 3:
        window_size = 3

    try:
        smoothed = savgol_filter(data, window_size, 2)
        residuals = data - smoothed
        std_residuals = np.std(residuals)

        # Определяем выбросы как точки с большими невязками
        outliers_mask = np.abs(residuals) > 2 * std_residuals

        # Заменяем выбросы сглаженными значениями
        filtered_data = np.where(outliers_mask, smoothed, data)

        stats_info = {
            'method': 'Savitzky-Golay',
            'window_size': window_size,
            'std_residuals': std_residuals,
            'outliers_count': np.sum(outliers_mask),
            'outliers_percent': (np.sum(outliers_mask) / len(data)) * 100
        }

        return filtered_data.tolist(), stats_info
    except Exception as e:
        print(f"Ошибка в Savitzky-Golay фильтре: {e}")
        return data, {'method': 'Savitzky-Golay (failed)', 'error': str(e)}


def _interpolate_nans(data):
    """Интерполирует NaN значения в массиве"""
    df = pd.Series(data)
    return df.interpolate(method='linear', limit_direction='both').values


def _plot_filtering_results(time, original, filtered, parameter, method, stats, show_plots, save_plots):
    """Создает графики до и после фильтрации"""
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8))

    # График исходных данных
    ax1.plot(time, original, 'b-', linewidth=1, alpha=0.7, label='Исходные данные')
    ax1.set_title(f'{parameter} - До фильтрации ({method})', fontsize=14)
    ax1.set_ylabel(parameter)
    ax1.grid(True, alpha=0.3)
    ax1.legend()

    # График после фильтрации
    ax2.plot(time, filtered, 'g-', linewidth=1, alpha=0.7, label='После фильтрации')
    ax2.set_title(f'{parameter} - После фильтрации ({method})', fontsize=14)
    ax2.set_xlabel('Время (секунды)')
    ax2.set_ylabel(parameter)
    ax2.grid(True, alpha=0.3)
    ax2.legend()

    # Добавляем статистику
    stats_text = (f"Метод: {stats['method']}\n"
                  f"Выбросов: {stats.get('outliers_count', 'N/A')} "
                  f"({stats.get('outliers_percent', 'N/A'):.1f}%)\n")

    if 'mean' in stats:
        stats_text += f"Среднее: {stats['mean']:.4f}\n"
    if 'std' in stats:
        stats_text += f"Стд: {stats['std']:.4f}\n"
    if 'threshold' in stats:
        stats_text += f"Порог: {stats['threshold']}"

    fig.text(0.02, 0.02, stats_text, fontsize=10,
             bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.8))

    plt.tight_layout()

    if save_plots:
        current_time = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        filename = f"фильтрация_{parameter}_{method}_{current_time}.png"
        plt.savefig(filename, dpi=150, bbox_inches='tight')
        print(f"График сохранен: {filename}")

    if show_plots:
        plt.show()
    else:
        plt.close()


def print_filtering_statistics(statistics):
    """Выводит статистику фильтрации в удобном формате"""
    print("\n" + "=" * 60)
    print("СТАТИСТИКА ФИЛЬТРАЦИИ ВЫБРОСОВ")
    print("=" * 60)

    total_outliers = 0
    total_points = 0

    for param, stats in statistics.items():
        outliers = stats.get('outliers_count', 0)
        percent = stats.get('outliers_percent', 0)
        method = stats.get('method', 'Unknown')

        print(f"\n📊 {param}:")
        print(f"   Метод: {method}")
        print(f"   Выбросов: {outliers} ({percent:.1f}%)")

        if 'threshold' in stats:
            print(f"   Порог: {stats['threshold']}")
        if 'mean' in stats:
            print(f"   Среднее: {stats['mean']:.6f}")
        if 'std' in stats:
            print(f"   Стд. отклонение: {stats['std']:.6f}")

        total_outliers += outliers

    print("\n" + "=" * 60)
    print(f"📈 ИТОГО: Обнаружено {total_outliers} выбросов")
    print("=" * 60)


# Функция для быстрой фильтрации (упрощенный интерфейс)
def quick_filter_outliers(data_dict, method='iqr'):
    """
    Быстрая фильтрация выбросов с параметрами по умолчанию
    """
    return filter_resonator_outliers(data_dict, method=method, show_plots=False, save_plots=False)


# Пример использования
if __name__ == "__main__":
    # Создаем тестовые данные с выбросами
    np.random.seed(42)
    time_data = np.linspace(0, 10, 100)

    # Нормальные данные с шумом
    clean_data = 10 + np.sin(time_data) + 0.1 * np.random.normal(size=len(time_data))

    # Добавляем выбросы
    test_data = clean_data.copy()
    outlier_indices = [10, 25, 50, 75, 90]
    test_data[outlier_indices] = [15, 5, 20, 3, 18]  # Явные выбросы

    test_dict = {
        'Time': time_data.tolist(),
        'F(t), Гц': test_data.tolist(),
        'R1(t), Ом': (68.5 + 0.1 * np.random.normal(size=len(time_data))).tolist(),
        'U(t), В': (5.0 + 0.05 * np.random.normal(size=len(time_data))).tolist(),
    }

    print("Тестирование фильтрации выбросов...")

    # Тестируем разные методы
    methods = ['iqr', 'zscore', 'mad', 'savitzky_golay']

    for method in methods:
        print(f"\n🔧 Тестирование метода: {method.upper()}")
        try:
            filtered_data, stats = filter_resonator_outliers(
                test_dict,
                method=method,
                show_plots=False,
                save_plots=True
            )

            print_filtering_statistics(stats)

        except Exception as e:
            print(f"❌ Ошибка при использовании метода {method}: {e}")