import os
import json
import sys
from urllib.parse import urlparse, unquote


# Целевая папка для PDF-протоколов и графиков модуля измерения
# частоты. Относительный путь резолвится от текущей рабочей
# директории (корень проекта, где лежит main.py).
DEFAULT_PDF_OUTPUT_DIR = "Измерения/Измерения_частоты_стекло"


def _app_dir():
    """Каталог приложения: рядом с .exe (PyInstaller) или рядом с .py."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


APP_DIR = _app_dir()
CONFIG_PATH = os.path.join(APP_DIR, 'config.json')


def _db_from_options():
    """Взять параметры БД из общего модуля Options - тот же XAMPP/MySQL,
    что использует редактор спецификаций и остальной проект.

    Возвращает dict {'url', 'host', 'user', 'password', 'database'} или None.
    """
    try:
        from Options import get_connection_string
        url = get_connection_string()
        if not url:
            return None
        p = urlparse(url)
        return {
            'url': url,
            'host': p.hostname or 'MES1',
            'user': unquote(p.username) if p.username else 'xampp',
            'password': unquote(p.password) if p.password else '',
            'database': (p.path or '/coordinator').lstrip('/'),
        }
    except Exception as e:
        print(f"[config] Options недоступен, использую фолбэк: {e}")
        return None


_DB_DEFAULT = _db_from_options() or {
    'url': 'mysql+mysqlconnector://xampp:43FPa!29S8HQeAW@MES1:3306/coordinator',
    'host': 'MES1',
    'user': 'xampp',
    'password': '43FPa!29S8HQeAW',
    'database': 'coordinator',
}


DEFAULT_ACCEPTANCE = {
    'max_ppm': 100.0,
    'min_ppm': -100.0,
    'max_monotonicity_ppm': 50.0,
    'outlier_threshold_ppm': 20.0,
}

DEFAULT_CONFIG = {
    'device': {
        'resource': 'auto',
        'baudrate': 9600,
        'gate_time': 0.1,
        'timeout_ms': 5000,
        'poll_interval': 0.05,
    },
    'measurement': {
        'epsilon': 2.0,
        'epsilon_window': 15,
        'min_duration': 10.0,
        'max_duration': 3600.0,
        'min_frequency': 1000.0,
        'signal_stable_time': 0.5,
    },
    'acceptance': dict(DEFAULT_ACCEPTANCE),
    'database': dict(_DB_DEFAULT),
    'pdf': {
        'output_dir': DEFAULT_PDF_OUTPUT_DIR,
        'font_path': 'C:/Windows/Fonts/DejaVuSans.ttf',
    },
}


def _resolve_path(p):
    """Резолв пути для PDF-файлов.

    * Абсолютный путь возвращается как есть.
    * Относительный резолвится от текущей рабочей директории
      (корень проекта, где запускается main.py).
    * Пустое значение - используем папку по умолчанию
      (Измерения/Измерения_частоты_стекло в корне проекта).
    """
    if not p:
        p = DEFAULT_PDF_OUTPUT_DIR
    if os.path.isabs(p):
        return p
    return os.path.join(os.getcwd(), p)


def _sync_database_section(cfg):
    """Синхронизировать cfg['database'] с Options.
    Правим, только если пароль/хост/юзер пустые, чтобы не затирать
    ручные изменения пользователя.
    """
    db_opt = _db_from_options()
    if not db_opt:
        return False

    changed = False
    db = cfg.setdefault('database', {})
    if not isinstance(db, dict):
        cfg['database'] = dict(db_opt)
        return True

    if not db.get('password') or not db.get('host') or not db.get('user'):
        for k in ('url', 'host', 'user', 'password', 'database'):
            if db_opt.get(k) and db.get(k) != db_opt[k]:
                db[k] = db_opt[k]
                changed = True
    return changed


def _migrate_pdf_output_dir(cfg):
    """Перевести старый pdf.output_dir ('reports' или пустое) на новую папку.

    Не трогаем значение, если пользователь явно указал свой путь
    (не 'reports' и не пустое).
    """
    pdf = cfg.get('pdf')
    if not isinstance(pdf, dict):
        cfg['pdf'] = dict(DEFAULT_CONFIG['pdf'])
        return True

    cur = (pdf.get('output_dir') or '').strip()
    if cur in ('', 'reports'):
        pdf['output_dir'] = DEFAULT_PDF_OUTPUT_DIR
        return True
    return False


def load_config():
    if not os.path.exists(CONFIG_PATH):
        print(f'[config] {CONFIG_PATH} не найден - создаю дефолт')
        save_config(DEFAULT_CONFIG)
        return json.loads(json.dumps(DEFAULT_CONFIG))

    with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        cfg = json.load(f)

    for key, default_val in DEFAULT_CONFIG.items():
        if key not in cfg:
            cfg[key] = default_val
        elif isinstance(default_val, dict):
            for k, v in default_val.items():
                cfg[key].setdefault(k, v)

    migrated = False

    # Досыпаем пароль из Options, если в старом config.json он пустой
    if _sync_database_section(cfg):
        migrated = True
        print('[config] database.* синхронизирован с Options')

    # Обновляем старый путь 'reports' на новую папку
    if _migrate_pdf_output_dir(cfg):
        migrated = True
        print(f'[config] pdf.output_dir -> {DEFAULT_PDF_OUTPUT_DIR}')

    if migrated:
        save_config(cfg)

    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
    print(f'[config] сохранён: {CONFIG_PATH}')