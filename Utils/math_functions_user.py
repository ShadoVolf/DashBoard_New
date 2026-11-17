from datetime import datetime


# Функция преобразование строки в число с проверкой является ли строка числом если нет то выводи 0.0
def safe_float(s):
    s = str(s).strip()
    if s.replace('.', '', 1).replace('-', '', 1).isdigit():
        return float(s)
    return 0.0


# Возвращает текущее время
def get_current_time():
    now = datetime.now()
    return now.strftime('%H:%M:%S')
