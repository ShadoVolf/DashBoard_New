def convert_to_flat_array(loaded_data):
    """Преобразует данные в плоский массив [real1, imag1, real2, imag2, ...]"""
    # Если данные уже в правильном формате
    if isinstance(loaded_data, (list, tuple)) and all(isinstance(x, (float, int)) for x in loaded_data):
        return list(loaded_data)

    # Если данные представлены как список комплексных чисел
    if isinstance(loaded_data, (list, tuple)) and all(isinstance(x, complex) for x in loaded_data):
        flat_data = []
        for comp in loaded_data:
            flat_data.append(comp.real)
            flat_data.append(comp.imag)
        return flat_data

    # Если данные в другом формате
    raise ValueError("Неподдерживаемый формат данных")


def parse_cal_filename(filename):
    # Удаляем расширение файла
    base_name = filename.rsplit('.', 1)[0]

    # Разделяем базовое имя на части
    parts = base_name.split('_')

    if len(parts) < 4:
        raise ValueError("Неверный формат имени файла. Ожидается: канал_нач_частота_кон_частота_точки")

    try:
        # Первый элемент - номер канала
        channel = int(parts[0])

        # Последний элемент - число точек
        points = int(parts[-1])

        # Средние части - частоты (объединяем части, которые могли разделиться из-за точек)
        freq_parts = parts[1:-1]
        freq_str = '_'.join(freq_parts)
        frequencies = freq_str.split('_') if '_' in freq_str else [freq_str]

        if len(frequencies) != 2:
            raise ValueError("Не удалось извлечь начальную и конечную частоты")

        start_freq = float(frequencies[0]) * 1e6  # МГц -> Гц
        end_freq = float(frequencies[1]) * 1e6  # МГц -> Гц

    except (ValueError, TypeError) as e:
        raise ValueError(f"Ошибка обработки данных: {e}") from e

    return channel, start_freq, end_freq, points


# Функция для построения текстового графика с пропуском точек с одинаковым Y
def plot_text_graph(x_data, y_data, title, width=50, height=20):
    if len(x_data) == 0 or len(y_data) == 0:
        print("Нет данных для построения графика")
        return

    # Находим минимальные и максимальные значения
    x_min = min(x_data)
    x_max = max(x_data)
    y_min = min(y_data)
    y_max = max(y_data)

    # Добавляем небольшой отступ для лучшего отображения
    y_range = y_max - y_min
    y_padding = y_range * 0.1  # 10% от диапазона
    y_min_display = y_min - y_padding
    y_max_display = y_max + y_padding

    # Масштабируем данные для отображения
    scaled_x = []
    scaled_y = []

    for x in x_data:
        # Нормализуем x от 0 до 1, затем масштабируем до ширины графика
        norm_x = (x - x_min) / (x_max - x_min) if x_max != x_min else 0.5
        scaled_x.append(norm_x * (width - 1))

    for y in y_data:
        # Нормализуем y от 0 до 1, затем масштабируем до высоты графика
        norm_y = (y - y_min_display) / (y_max_display - y_min_display)
        scaled_y.append(norm_y * (height - 1))

    # Создаем поле для графика
    grid = [[' ' for _ in range(width)] for _ in range(height)]

    # Заполняем поле точками данных, пропуская точки с одинаковым Y
    prev_y = None
    for x, y in zip(scaled_x, scaled_y):
        x_pos = round(x)
        y_pos = round(y)

        # Пропускаем точку, если Y совпадает с предыдущей
        if prev_y is not None and y_pos == prev_y:
            continue

        if 0 <= y_pos < height and 0 <= x_pos < width:
            grid[height - 1 - y_pos][x_pos] = '*'
            prev_y = y_pos

    # Добавляем оси
    for i in range(height):
        grid[i][0] = '|'
    for j in range(width):
        grid[height - 1][j] = '-'
    grid[height - 1][0] = '|'

    # Добавляем метки для осей с одним знаком после запятой
    x_labels = [
        f"{x_min:.1e}",
        f"{(x_min + x_max) / 2:.1e}",
        f"{x_max:.1e}"
    ]
    y_labels = [
        f"{y_max_display:.1f}",
        f"{(y_min_display + y_max_display) / 2:.1f}",
        f"{y_min_display:.1f}"
    ]

    # Выводим график
    print(f"\n{title}")
    print(f"X (частота, Гц): {x_min:.1e} - {x_max:.1e}")
    print(f"Y: {y_min:.1f} - {y_max:.1f}")
    print()

    # Выводим график с метками осей Y
    for i, row in enumerate(grid):
        if i == 0:
            label = y_labels[0]
        elif i == height // 2:
            label = y_labels[1]
        elif i == height - 1:
            label = y_labels[2]
        else:
            label = " "

        print(f"{label:>8} {''.join(row)}")

    # Выводим метки оси X
    x_label_positions = [0, width // 2, width - 1]
    x_label_line = " " * 9
    for i in range(width):
        if i in x_label_positions:
            idx = x_label_positions.index(i)
            label = x_labels[idx]
            x_label_line += label
            i += len(label) - 1
        else:
            x_label_line += " "

    print(x_label_line)


def format_float(value):
    # Определяем знак числа
    sign = '+' if value >= 0 else '-'
    abs_value = abs(value)

    # Разделяем на целую и дробную части
    int_part = int(abs_value)
    frac_part = abs_value - int_part

    # Преобразуем части в строки
    int_str = str(int_part)
    frac_str = f"{frac_part:.10f}"[2:].rstrip('0')

    # Считаем общее количество цифр
    total_digits = len(int_str) + len(frac_str)

    # Определяем, сколько цифр нужно добавить или убрать
    digits_needed = 5 - total_digits - 1  # -1 для знака

    if digits_needed > 0:
        # Добавляем нули в дробную часть
        frac_str = frac_str.ljust(len(frac_str) + digits_needed, '0')
    elif digits_needed < 0:
        # Округляем число до нужного количества цифр
        new_frac_len = len(frac_str) + digits_needed
        if new_frac_len > 0:
            # Округляем дробную часть
            rounding_factor = 10 ** new_frac_len
            frac_part = round(frac_part * rounding_factor) / rounding_factor
            frac_str = f"{frac_part:.10f}"[2:new_frac_len + 2]
        else:
            # Округляем целую часть
            rounding_factor = 10 ** abs(digits_needed)
            int_part = round(int_part / rounding_factor) * rounding_factor
            int_str = str(int_part)
            frac_str = ""

    # Форматируем результат
    result = sign + int_str
    if frac_str:
        result += '.' + frac_str

    return result