"""Assistant — LLM-ассистент с поддержкой модулей Статистика, Протоколы, Графики и Архив.

Публичный API:
    create_assistant_window, show_assistant_window,
    run_nl_query, check_llm, clear_assistant_log,
    run_llm_report, stop_llm_report,
    launch_statistics, is_statistics_running,
    launch_protocol,   is_protocol_running,
    launch_graph,      is_graph_running,
    launch_archive,    is_archive_running,
    launch_module,     is_module_running,   # key='stats'|'protocol'|'graph'|'archive'

Импорты ленивые (PEP 562): тяжёлые модули (controller, window, launcher)
подгружаются только при первом обращении к их атрибутам. Это позволяет
тестам импортировать парсеры (graph_parser, protocol_parser, archive_parser)
без побочных эффектов и без запуска GUI/БД-цепочек.
"""
from __future__ import annotations
from . import window  # noqa: F401  — якорь для PyInstaller
from importlib import import_module

# Публичные имена → модуль, где они определены.
_ATTR_TO_MODULE = {
    # constants
    'USER_WINDOW_H': '.constants',
    'MARGIN':         '.constants',
    'WIDTH_FRAC':     '.constants',
    'HEIGHT_FRAC':    '.constants',
    'MIN_WIDTH':      '.constants',
    # launcher
    'is_statistics_running': '.launcher',
    'launch_statistics':     '.launcher',
    'is_protocol_running':   '.launcher',
    'launch_protocol':       '.launcher',
    'is_graph_running':      '.launcher',
    'launch_graph':          '.launcher',
    'is_archive_running':    '.launcher',
    'launch_archive':        '.launcher',
    'launch_module':         '.launcher',
    'is_module_running':     '.launcher',
    # window
    'create_assistant_window': '.window',
    'show_assistant_window':   '.window',
    # controller
    'run_nl_query':        '.controller',
    'check_llm':           '.controller',
    'clear_assistant_log': '.controller',
    'run_llm_report':      '.controller',
    'stop_llm_report':     '.controller',
}

# Подмодули, доступные как Assistant.<name> без импорта в __init__.
_SUBMODULES = frozenset({
    'constants', 'launcher', 'window', 'controller',
    'graph_parser', 'protocol_parser', 'protocol_tools',
    'archive_parser', 'archive_tools',
})

__all__ = list(_ATTR_TO_MODULE)


def __getattr__(name: str):
    mod_path = _ATTR_TO_MODULE.get(name)
    if mod_path is not None:
        value = getattr(import_module(mod_path, __name__), name)
        globals()[name] = value
        return value

    if name in _SUBMODULES:
        mod = import_module(f'.{name}', __name__)
        globals()[name] = mod
        return mod

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__():
    return sorted(
        set(globals())
        | set(_ATTR_TO_MODULE)
        | set(_SUBMODULES)
    )
