"""Запуск модулей (статистика, протоколы, графики) в том же процессе.

Backward-compat: is_statistics_running/launch_statistics сохранены.
"""
import importlib
import dearpygui.dearpygui as dpg

_MODULES = {
    'stats': {
        'tags':    ('result_table', 'nom_window', 'msk_window'),
        'factory': ('Statistik.DashBoard', 'create_main_windows'),
        'label':   'модуль статистики (DashBoard)',
    },
    'protocol': {
        'tags':    ('protocol_manager_window',),
        'factory': ('Protocol_Manager.Protocol_Tab',
                    'create_protocol_window'),
        'label':   'модуль протоколов',
    },
    'graph': {
        'tags':    ('resonator_graph_window', 'resonator_graph_controls'),
        'factory': ('ResonatorGraph.ui', 'create_graph_window'),
        'label':   'модуль графиков (ResonatorGraph)',
    },
}
_LAUNCHED: dict[str, bool] = {}


def is_module_running(key: str) -> bool:
    if _LAUNCHED.get(key):
        return True
    spec = _MODULES.get(key) or {}
    for tag in spec.get('tags', ()):
        try:
            if dpg.does_item_exist(tag):
                return True
        except Exception:
            pass
    return False


def launch_module(key: str, dpg_=None) -> dict:
    """Возвращает {'status': 'launched'|'already_running'|'error', ...}."""
    if key not in _MODULES:
        return {'status': 'error', 'error': f'unknown module {key!r}'}
    if is_module_running(key):
        return {'status': 'already_running'}
    spec = _MODULES[key]
    try:
        mod_name, fn_name = spec['factory']
        mod = importlib.import_module(mod_name)
        getattr(mod, fn_name)()
        _LAUNCHED[key] = True
        return {'status': 'launched', 'label': spec['label']}
    except Exception as e:
        import traceback; traceback.print_exc()
        return {'status': 'error', 'error': f'{type(e).__name__}: {e}'}


# ---- backward compat ----
def is_statistics_running() -> bool:
    return is_module_running('stats')


def launch_statistics(dpg_=None) -> dict:
    return launch_module('stats', dpg_)


def is_protocol_running() -> bool:
    return is_module_running('protocol')


def launch_protocol(dpg_=None) -> dict:
    return launch_module('protocol', dpg_)


def is_graph_running() -> bool:
    return is_module_running('graph')


def launch_graph(dpg_=None) -> dict:
    return launch_module('graph', dpg_)
