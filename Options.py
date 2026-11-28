import os
from datetime import date
from datetime import datetime
from urllib.parse import urlparse
import serial
import glob

# Параметры подключения
server = 'SQL4\\SQLAPPS'  # Имя сервера и экземпляра
database = 'RqSql'  # Имя базы данных
username = 'msql'  # Логин
password = 'MkndKfEquAqDexj'  # Пароль


def get_connection_string():
    sqlengine = 'mysql+mysqlconnector://xampp:43FPa!29S8HQeAW@MES1:3306/coordinator'
    return sqlengine


def parse_connection_string():
    """Парсит URI подключения и извлекает параметры."""
    try:
        parsed = urlparse(get_connection_string())
        return {
            'user': parsed.username,
            'password': parsed.password,
            'host': parsed.hostname,
            'port': parsed.port,
            'database': parsed.path.lstrip('/')
        }
    except Exception as e:
        print(f"Ошибка парсинга URI: {e}")
        return None


def get_MSSQL_connection_string():
    sqlengine = f"mssql+pyodbc://{username}:{password}@{server}/{database}?driver=ODBC+Driver+17+for+SQL+Server"
    return sqlengine


def get_measure_protokol_path():
    """Возвращает путь к файлам протоколов"""
    # Получаем текущую директорию запуска программы
    current_directory = os.getcwd()

    # Формируем путь к папке "Протоколы"
    protocols_path = os.path.join(current_directory, "Протоколы")

    # Создаем папку, если она не существует
    os.makedirs(protocols_path, exist_ok=True)
    return protocols_path


def get_rt_measure_protokol_path():
    """Возвращает путь к файлам протоколов"""
    # Получаем текущую директорию запуска программы
    current_directory = os.getcwd()

    # Формируем путь к папке "Протоколы"
    protocols_path = os.path.join(current_directory, "Измерения")

    # Создаем папку, если она не существует
    os.makedirs(protocols_path, exist_ok=True)
    return protocols_path


# Возвращает путь к папке с катинками для программы
def get_pict_path():
    """Возвращает путь к файлам протоколов"""
    # Получаем текущую директорию запуска программы
    current_directory = os.getcwd()

    # Формируем путь к папке "Pictures"
    path = os.path.join(current_directory, "Pictures")

    # Создаем папку, если она не существует
    os.makedirs(path, exist_ok=True)
    return path


# Возвращает текущую диекторию запуска программы
def get_system_path():
    return os.getcwd()


def get_current_date() -> str:
    """Возвращает текущую дату в формате 'dd.mm.yyyy'"""
    return date.today().strftime("%d.%m.%Y")


def get_current_datetime() -> str:
    """Возвращает текущую дату и время в формате 'dd.mm.yyyy HH.MM.SS'"""
    return datetime.now().strftime("%d.%m.%Y %H:%M:%S")


def get_current_time() -> str:
    """Возвращает текущую дату и время в формате 'dd.mm.yyyy HH.MM.SS'"""
    return datetime.now().strftime("%H:%M:%S")


# Центрирует заданное окно в контексте
def center_window(dpg, name_window):
    viewport_width = dpg.get_viewport_client_width()
    viewport_height = dpg.get_viewport_client_height()
    window_width = dpg.get_item_width(name_window)
    window_height = dpg.get_item_height(name_window)
    x = (viewport_width - window_width) // 2
    y = (viewport_height - window_height) // 2
    dpg.set_item_pos(name_window, [x, y])


# Возвращает список доступный com портов в системе
def get_available_com_ports():
    """Возвращает список доступных COM-портов."""
    if os.name == 'nt':  # Windows
        ports = ['COM' + str(i + 1) for i in range(256)]
    elif os.name == 'posix':  # Linux/macOS
        ports = glob.glob('/dev/ttyACM*') + glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyS*')
    else:
        raise EnvironmentError('Unsupported operating system')

    available_ports = []
    for port in ports:
        try:
            # Попытка открыть порт (без реального использования) для проверки его доступности.
            with serial.Serial(port):
                available_ports.append(port)
        except serial.SerialException:
            pass  # Порт недоступен
    return available_ports


# Выводит окно с сообщением
def show_message(dpg, header, message):
    with dpg.window(width=300, height=300,
                    label=header,
                    tag=f'Message_windows_{header}'):
        for row in message:
            dpg.add_text(row)
    center_window(dpg, f'Message_windows_{header}')


def show_message_inf(dpg, header, message):
    dpg.delete_item(f'Message_windows_{header}')
    dpg.delete_item(f'Message_windows_text_{header}')
    with dpg.window(width=900, height=150,
                    label=header,
                    tag=f'Message_windows_{header}'):
        dpg.add_input_text(tag=f'Message_windows_text_{header}',
                           multiline=True,
                           readonly=True,
                           width=-1,
                           height=-1,
                           tracked=True,
                           track_offset=1.0
                           )
        temp = ""
        for row in message:
            temp = f'{temp}\n{row}'
        dpg.set_value(f'Message_windows_text_{header}', temp)
        dpg.set_item_height(f'Message_windows_text_{header}', -1)
    center_window(dpg, f'Message_windows_{header}')


# =============================================================================
# Настройки приложения (JSON в директории программы)
# =============================================================================
import json
import sys

APP_SETTINGS_FILENAME = 'app_settings.json'

_DEFAULT_APP_SETTINGS = {
    # True  — быстрый поиск (кэш справочников, score, все кандидаты ≤ ppm)
    # False — классический (SQL на каждый слот, только min ppm, sort по имени)
    'fast_spec_search': True,
}

_app_settings_cache = None


def get_app_directory() -> str:
    """
    Каталог программы (рядом с exe после компиляции).

    PyInstaller / Nuitka: dirname(sys.executable)
    Запуск из исходников: dirname(sys.argv[0]) или cwd.
    """
    if getattr(sys, 'frozen', False):
        return os.path.dirname(os.path.abspath(sys.executable))
    # Nuitka onefile / standalone иногда не ставит frozen
    argv0 = os.path.abspath(sys.argv[0]) if sys.argv and sys.argv[0] else ''
    if argv0 and not argv0.endswith(('.py', '.pyw')):
        return os.path.dirname(argv0)
    if argv0:
        d = os.path.dirname(argv0)
        if d:
            return d
    return os.getcwd()


def get_app_settings_path() -> str:
    return os.path.join(get_app_directory(), APP_SETTINGS_FILENAME)


def _ensure_settings_file() -> dict:
    """Читает JSON; при отсутствии или ошибке создаёт файл с defaults."""
    path = get_app_settings_path()
    if not os.path.isfile(path):
        data = dict(_DEFAULT_APP_SETTINGS)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            print(f'[Settings] создан {path}')
        except Exception as e:
            print(f'[Settings] не удалось создать {path}: {e}')
        return data
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError('settings root is not object')
        # дополняем недостающие ключи
        changed = False
        for k, v in _DEFAULT_APP_SETTINGS.items():
            if k not in data:
                data[k] = v
                changed = True
        if changed:
            save_app_settings(data)
        return data
    except Exception as e:
        print(f'[Settings] ошибка чтения {path}: {e}, пересоздаём')
        data = dict(_DEFAULT_APP_SETTINGS)
        try:
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e2:
            print(f'[Settings] не удалось пересоздать: {e2}')
        return data


def load_app_settings(force: bool = False) -> dict:
    """Загружает настройки (с кэшем в памяти)."""
    global _app_settings_cache
    if _app_settings_cache is not None and not force:
        return _app_settings_cache
    _app_settings_cache = _ensure_settings_file()
    return _app_settings_cache


def save_app_settings(data: dict = None) -> bool:
    """Сохраняет настройки на диск и обновляет кэш."""
    global _app_settings_cache
    if data is None:
        data = _app_settings_cache if _app_settings_cache is not None else dict(_DEFAULT_APP_SETTINGS)
    path = get_app_settings_path()
    try:
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _app_settings_cache = dict(data)
        print(f'[Settings] сохранено → {path}')
        return True
    except Exception as e:
        print(f'[Settings] ошибка записи {path}: {e}')
        return False


def is_fast_spec_search_enabled() -> bool:
    """True = быстрый автоподбор спецификаций (по умолчанию)."""
    return bool(load_app_settings().get('fast_spec_search', True))


def set_fast_spec_search(enabled: bool) -> bool:
    data = load_app_settings()
    data['fast_spec_search'] = bool(enabled)
    return save_app_settings(data)


def create_settings_window(dpg):
    """Окно «Настройки» (меню Файл → Настройки)."""
    tag = 'app_settings_window'
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)

    settings = load_app_settings(force=True)
    fast = bool(settings.get('fast_spec_search', True))

    def _on_save(sender, app_data, user_data):
        val = dpg.get_value('settings_fast_spec_search')
        set_fast_spec_search(bool(val))
        # сброс кэша справочников — следующий поиск подхватит режим
        try:
            from Temperature_Measure.Analyze_Data import clear_spec_cache
            clear_spec_cache()
        except Exception:
            pass
        mode = 'быстрый' if val else 'классический'
        print(f'[Settings] режим поиска спецификаций: {mode}')
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

    def _on_cancel(sender, app_data, user_data):
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

    with dpg.window(
        label='Настройки',
        tag=tag,
        width=480,
        height=220,
        modal=False,
        no_collapse=True,
    ):
        dpg.add_text('Поиск спецификаций')
        dpg.add_separator()
        dpg.add_checkbox(
            label='Быстрый поиск спецификаций',
            tag='settings_fast_spec_search',
            default_value=fast,
        )
        dpg.add_text(
            'Вкл. - кэш справочников, ranking по score, все кандидаты < ppm.\n'
            'Выкл. - классический режим (SQL на каждый слот, только min ppm).',
            wrap=440,
        )
        dpg.add_spacer(height=12)
        with dpg.group(horizontal=True):
            dpg.add_button(label='Сохранить', width=120, callback=_on_save)
            dpg.add_button(label='Отмена', width=120, callback=_on_cancel)
        dpg.add_spacer(height=6)
        dpg.add_text(f'Файл: {get_app_settings_path()}', wrap=440)

    try:
        center_window(dpg, tag)
    except Exception:
        pass
