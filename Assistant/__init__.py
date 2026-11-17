"""Assistant — LLM-ассистент с поддержкой модулей Статистика и Протоколы.

Публичный API:
    create_assistant_window, show_assistant_window,
    run_nl_query, check_llm, clear_assistant_log,
    run_llm_report, stop_llm_report,
    launch_statistics, is_statistics_running,
    launch_protocol,   is_protocol_running,
"""
from .constants import (
    USER_WINDOW_H, MARGIN, WIDTH_FRAC, HEIGHT_FRAC, MIN_WIDTH,
)
from .launcher import (
    is_statistics_running, launch_statistics,
    is_protocol_running,   launch_protocol,
    launch_module, is_module_running,
)
from .window import create_assistant_window, show_assistant_window
from .controller import (
    run_nl_query, check_llm, clear_assistant_log,
    run_llm_report, stop_llm_report,
)

__all__ = [
    'USER_WINDOW_H', 'MARGIN', 'WIDTH_FRAC', 'HEIGHT_FRAC', 'MIN_WIDTH',
    'is_statistics_running', 'launch_statistics',
    'is_protocol_running',   'launch_protocol',
    'launch_module', 'is_module_running',
    'create_assistant_window', 'show_assistant_window',
    'run_nl_query', 'check_llm', 'clear_assistant_log',
    'run_llm_report', 'stop_llm_report',
]