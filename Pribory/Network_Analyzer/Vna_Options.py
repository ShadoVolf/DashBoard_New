from Options import center_window
import re


def create_vna_options_window(sender, data, dpg):
    with dpg.window(label="Настройки векторного анализатора цепей", width=900, height=300, tag='RT_VNA_Options_Window',
                    modal=True,
                    no_close=False):
        dpg.add_text("Установка")

    center_window(dpg, 'RT_VNA_Options_Window')


# Формирует список для значений фильтра ПЧ
def generate_filter_values() -> list:
    """
    Генерирует отсортированный список строковых значений частот для фильтра ПЧ анализатора цепей.

    Значения формируются по правилу:
    - Базовые множители: 1, 3, 5, 7
    - Умножаются на 10^i, где i ∈ [0, 4]
    - Диапазон: от 1 Гц до 10 кГц
    - Единицы измерения: 'Гц' для значений < 1000, 'кГц' для кратных 1000

    Returns:
        list: Отсортированный список строковых значений с единицами измерения.

    Examples:
        >>> generate_filter_values()
        ['1 Гц', '3 Гц', '5 Гц', '7 Гц', '10 Гц', '30 Гц', '50 Гц', '70 Гц', '100 Гц',
         '300 Гц', '500 Гц', '700 Гц', '1 кГц', '3 кГц', '5 кГц', '7 кГц', '10 кГц']
    """
    values = []
    for i in range(5):  # степени 10 от 0 до 4 (10^0 до 10^4)
        multiplier = 10 ** i
        for base in [1, 3, 5, 7]:
            val = base * multiplier
            if val > 10000:
                continue
            if val >= 1000 and val % 1000 == 0:
                values.append(f"{val // 1000} кГц")
            else:
                values.append(f"{val} Гц")

    # Сортировка значений по числовому представлению в Гц
    def sort_key(s):
        return convert_to_hz(s)

    return sorted(values, key=sort_key)


# Преобразует значения из строки фильтра ПЧ в значение типа int
def convert_to_hz(s: str) -> int:
    """
    Преобразует строковое значение частоты в целое число, соответствующее частоте в герцах.

    Поддерживаемые форматы:
    - '1 Гц', '3 кГц', '10кГц' и т.д.
    - Регистр и лишние пробелы в строке игнорируются.

    Args:
        s (str): Входная строка с частотой и единицей измерения.

    Returns:
        int: Частота в герцах.

    Raises:
        ValueError: Если формат строки некорректен.

    Examples:
        >>> convert_to_hz('3 кГц')
        3000
        >>> convert_to_hz('700 Гц')
        700
        >>> convert_to_hz('invalid')
        ValueError: Неверный формат строки: 'invalid'
    """
    s = s.strip()
    match = re.match(r'^(\d+)\s*(к\s*гц|гц)$', s, re.IGNORECASE)
    if not match:
        raise ValueError(f"Неверный формат строки: '{s}'")
    number = int(match.group(1))
    unit = match.group(2).lower().replace(' ', '')
    if unit.startswith('к'):
        return number * 1000
    else:
        return number


# Преобразует фильтр в формате int в строку.
def int_to_freq_str(freq: int) -> str:
    """
    Преобразует целочисленное значение частоты в строку с единицами измерения.

    Поддерживаемые форматы:
    - Если значение кратно 1000: '3 кГц', '10 кГц'
    - Иначе: '700 Гц', '1500 Гц'

    Args:
        freq (int): Частота в герцах (положительное число).

    Returns:
        str: Строковое представление частоты с единицами измерения.

    Raises:
        ValueError: Если значение меньше или равно нулю.

    Examples:
        >>> int_to_freq_str(3000)
        '3 кГц'
        >>> int_to_freq_str(700)
        '700 Гц'
        >>> int_to_freq_str(0)
        ValueError: Частота должна быть положительным числом
    """
    if freq < 1:
        raise ValueError("Частота должна быть положительным числом")
    if freq % 1000 == 0:
        return f"{freq // 1000} кГц"
    else:
        return f"{freq} Гц"


# Преобразовываем строку диапазонов в параметры
def parse_freq_band(range_str):
    ranges = range_str.split(',')
    result = {}
    for i, r in enumerate(ranges, start=1):
        r_clean = r.strip()
        parts = r_clean.split('...')

        if len(parts) != 2:
            raise ValueError(f"Неправильный формат диапазона: '{r_clean}'")

        try:
            # Парсим значения
            start_val = int(parts[0])
            end_val = int(parts[1])

            # Корректируем границы
            start_val = max(1, start_val)  # Нижняя граница = 1
            end_val = min(250, end_val)  # Верхняя граница = 250

            # Если после корректировки начало > конца - меняем местами
            if start_val > end_val:
                start_val, end_val = end_val, start_val

        except ValueError:
            raise ValueError(f"Невозможно преобразовать в числа: '{r_clean}'")

        result[i] = {'start': start_val, 'end': end_val}

    return result


# Преобразует мощность
def read_power_data(value):
    try:
        # Разделяем строку и преобразуем в числа
        P_diss_microW, R_res = map(float, map(str.strip, value.split(',')))
        return P_diss_microW * 1e-6, R_res  # Конвертация мкВт → Вт
    except (ValueError, IndexError):
        return None, None
