"""
Настройки модуля виртуальных замеров.

Хранятся в JSON-файле:
  * frozen (PyInstaller): рядом с .exe — "директория программы";
  * dev: рядом с модулем;
  * если папка программы read-only: %APPDATA%/Virtual_Measure.

При отсутствии файла используются значения по умолчанию, файл
создаётся при первом сохранении. При первом запуске выполняется
миграция из старого места (dev-каталог / _MEIPASS), если файл там
присутствует.
"""
import json
import os
import shutil
import sys


APP_NAME = "Virtual_Measure"


DEFAULT_SETTINGS = {
    "variance": {
        "max_delta_percent":  0.5,
        "max_delta_absolute": 0.05,
        "use_absolute":       False,
        "preserve_status":    True,
        "max_attempts":       64,
    },
    "stats": {
        "histogram_bins": 20,
        "last_param":     "",
    },
    "last_used": {
        "rtype":      "",
        "spc":        "",
        "msk":        "",
        "measure_id": "",
        "only_good":  False,
        "machine_type": "",
        "machine_sn":   "",
    },
    "nn": {
        "mlp_enabled":        False,
        "autoenc_enabled":    False,
        "autoenc_threshold":  0.27,
        "autoenc_block":      False,
    },
}


# ============================================================================
# Определение пути к конфигу
# ============================================================================
def _is_frozen() -> bool:
    return bool(getattr(sys, 'frozen', False))


def _dir_is_writable(path: str) -> bool:
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, '.vm_write_probe')
        with open(probe, 'w', encoding='utf-8') as f:
            f.write('x')
        os.remove(probe)
        return True
    except Exception:
        return False


def _appdata_dir() -> str:
    base = os.environ.get('APPDATA') or os.environ.get('LOCALAPPDATA')
    if not base:
        base = os.path.expanduser('~')
    return os.path.join(base, APP_NAME)


def _program_dir() -> str:
    """Директория программы: рядом с exe (frozen) или с модулем (dev)."""
    if _is_frozen():
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


def _resolve_config_path() -> str:
    primary = _program_dir()
    if _dir_is_writable(primary):
        return os.path.join(primary, 'virtual_settings.json')

    fallback = _appdata_dir()
    try:
        os.makedirs(fallback, exist_ok=True)
    except Exception as e:
        print(f"[Virtual] settings: не удалось создать {fallback}: {e}",
              flush=True)
    return os.path.join(fallback, 'virtual_settings.json')


CONFIG_PATH = _resolve_config_path()


# ============================================================================
# Миграция из старого места (однократно, если в новом месте файла нет)
# ============================================================================
def _migrate_legacy():
    if os.path.exists(CONFIG_PATH):
        return

    candidates = []

    # 1. Рядом с exe (если exe лежит в dev-папке проекта и там уже был
    #    сохранён файл — этот случай покрыт самим CONFIG_PATH).
    # 2. Внутри _MEIPASS — если разработчик упаковал дефолтный
    #    virtual_settings.json через datas.
    if _is_frozen():
        meipass = getattr(sys, '_MEIPASS', None)
        if meipass:
            candidates.append(os.path.join(meipass, 'virtual_settings.json'))
            candidates.append(os.path.join(
                meipass, 'Virtual_Measure', 'virtual_settings.json'))
        # 3. Рядом с исходным exe (на случай переноса в другую папку)
        exe_dir = os.path.dirname(os.path.abspath(sys.executable))
        candidates.append(os.path.join(exe_dir, 'virtual_settings.json'))
    else:
        # dev: рядом с модулем
        candidates.append(os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            'virtual_settings.json'))

    dst_abs = os.path.abspath(CONFIG_PATH)
    for src in candidates:
        try:
            src_abs = os.path.abspath(src)
        except Exception:
            continue
        if src_abs == dst_abs:
            continue
        if not os.path.exists(src):
            continue
        try:
            shutil.copy2(src, CONFIG_PATH)
            print(f"[Virtual] settings migrated: {src_abs} -> {dst_abs}",
                  flush=True)
            return
        except Exception as e:
            print(f"[Virtual] settings migration error "
                  f"({src_abs}): {e}", flush=True)


_migrate_legacy()


# ============================================================================
# Публичное API
# ============================================================================
def load_settings() -> dict:
    if not os.path.exists(CONFIG_PATH):
        return _deep_copy(DEFAULT_SETTINGS)
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        merged = _deep_copy(DEFAULT_SETTINGS)
        _deep_merge(merged, data)
        return merged
    except Exception as e:
        print(f"[Virtual] settings load error ({CONFIG_PATH}): {e}",
              flush=True)
        return _deep_copy(DEFAULT_SETTINGS)


def save_settings(settings: dict):
    try:
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        # Атомарная запись: temp -> rename
        tmp_path = CONFIG_PATH + '.tmp'
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(settings, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, CONFIG_PATH)
        print(f"[Virtual] settings saved: {CONFIG_PATH}", flush=True)
    except Exception as e:
        print(f"[Virtual] settings save error ({CONFIG_PATH}): {e}",
              flush=True)


def config_path() -> str:
    """Для диагностики: показать актуальный путь к конфигу."""
    return CONFIG_PATH


def _deep_copy(d):
    return json.loads(json.dumps(d))


def _deep_merge(target, source):
    for k, v in source.items():
        if (k in target
                and isinstance(target[k], dict)
                and isinstance(v, dict)):
            _deep_merge(target[k], v)
        else:
            target[k] = v