"""Обработчик NL-запросов: pending → launch → protocol/graph → LLM(stats).

Приоритет:
  1. Активный pending.
  2. Явные launch-команды.
  3. Сильный protocol-контекст («протокол») → protocol_parser.
  4. Graph-парсер (игнорирует «протокол»).
  5. Protocol-парсер (слабые формы).
  6. Fallback-подсказки / LLM-статистика.
"""
import re

import dearpygui.dearpygui as dpg

from .context import (get_ctx, set_pending, clear_pending,
                      peek_pending, is_no)
from .launcher import (
    is_statistics_running, launch_statistics,
    is_protocol_running,   launch_protocol,
    is_graph_running,      launch_graph,
)
from . import protocol_parser
from . import protocol_tools
from . import graph_parser
from . import graph_tools


_STATS_LAUNCH_KW = (
    'запусти стат', 'запустить стат', 'открой стат', 'открыть стат',
    'включи стат', 'включить стат', 'запусти модуль стат',
    'открой модуль стат', 'launch stat', 'start stat', 'open stat',
)
_PROTO_LAUNCH_KW = (
    'запусти протокол', 'открой протокол', 'открыть протокол',
    'запусти модуль протокол', 'открой модуль протокол',
    'открыть протоколы',
)
_GRAPH_LAUNCH_KW = (
    'запусти график', 'открой график', 'открыть график',
    'запусти модуль график', 'открой модуль график',
    'открыть графики', 'запустить графики', 'open graph', 'launch graph',
)
_STATS_QUERY_KW = (
    'стат', 'stat', 'мск', 'msk', 'слот', 'slot',
    'fr', 'fs', 'fl', 'c0', 'c1', 'l1',
    'годн', 'брак', 'норм', 'процент',
    'загрузи', 'загрузить', 'спецификац', 'list_msks', 'list_slots',
    'list_specs', 'get_stat', 'get_norms', 'drop_anomal',
)


def _log(dpg_, text, color=(150, 255, 150)):
    try:
        from Statistik.dashboard_llm import _append_assistant_log
        _append_assistant_log(dpg_, text, color=color)
    except Exception:
        print(f'[Assistant] {text}')


def _is_any(q, kws):
    q = (q or '').lower()
    return any(k in q for k in kws)


def _ensure_module_opened(dpg_, key):
    if key == 'stats':
        if is_statistics_running():
            return
        res = launch_statistics(dpg_)
        if res.get('status') == 'launched':
            _log(dpg_, 'Открываю окна модуля статистики...')
        elif res.get('status') == 'error':
            _log(dpg_, f'Не удалось открыть статистику: {res.get("error")}',
                 color=(255, 150, 150))
        return
    if key == 'protocol':
        if is_protocol_running():
            return
        res = launch_protocol(dpg_)
        if res.get('status') == 'launched':
            _log(dpg_, 'Открываю модуль протоколов...')
        elif res.get('status') == 'error':
            _log(dpg_, f'Не удалось открыть протоколы: {res.get("error")}',
                 color=(255, 150, 150))
        return
    if key == 'graph':
        if is_graph_running():
            return
        res = launch_graph(dpg_)
        if res.get('status') == 'launched':
            _log(dpg_, 'Открываю модуль графиков...')
        elif res.get('status') == 'error':
            _log(dpg_, f'Не удалось открыть графики: {res.get("error")}',
                 color=(255, 150, 150))


def _apply_soft_msk(name, params):
    """п.1 protocol_tools_CHANGES: msk → msk_partial, если не exact-only."""
    params = dict(params or {})
    if name in ('search_protocols', 'latest_protocol'):
        if (params.get('msk')
                and not params.get('msk_partial')
                and not params.get('msk_exact_only')):
            params['msk_partial'] = params['msk']
            params['msk'] = None
    return params


def _exec_tool(name, params, dpg_):
    params = _apply_soft_msk(name, params)
    res = protocol_tools.execute(name, params, dpg_)
    if isinstance(res, dict) and res.get('action') == 'dry_run':
        set_pending('confirm_' + name.split('_')[0], {
            'tool': name,
            'params': params,
        })
        _log(dpg_, protocol_tools.format_result(name, res),
             color=(255, 220, 150))
        return
    _log(dpg_, protocol_tools.format_result(name, res),
         color=(255, 150, 150) if isinstance(res, dict) and res.get('error')
         else (150, 255, 150))


def _exec_graph_tool(name, params, dpg_):
    res = graph_tools.execute(name, params, dpg_)
    _log(dpg_, graph_tools.format_result(name, res),
         color=(255, 150, 150) if isinstance(res, dict) and res.get('error')
         else (150, 255, 150))


def _clear_input(dpg_):
    try:
        if dpg_.does_item_exist('assistant_input'):
            dpg_.set_value('assistant_input', '')
            try:
                dpg_.focus_item('assistant_input')
            except Exception:
                pass
    except Exception:
        pass


def run_nl_query(sender, data, dpg_):
    try:
        return run_nl_query_impl(sender, data, dpg_)
    finally:
        _clear_input(dpg_)


def run_nl_query_impl(sender, data, dpg_):
    try:
        q = (dpg_.get_value('assistant_input') or '').strip()
    except Exception:
        q = ''
    if not q:
        return

    q_low = q.lower()

    # -------- 1. Pending --------
    pending = peek_pending()
    if pending:
        if pending['kind'].startswith('confirm') and not (is_no(q)
                or q_low in ('да', 'yes', 'нет', 'no', 'ok',
                             'подтверждаю', 'применить',
                             'отмена', 'cancel', 'стоп')):
            clear_pending()
            _log(dpg_, '[CANCEL] Предыдущая операция отменена (новый запрос).',
                 color=(255, 220, 150))
        else:
            res = protocol_tools.handle_pending_reply(q, dpg_)
            if res is not None:
                _log(dpg_, protocol_tools.format_result('pending', res),
                     color=(255, 150, 150) if res.get('error')
                     else (150, 255, 150))
                return

    # -------- 2. Explicit launch --------
    if _is_any(q, _GRAPH_LAUNCH_KW) and 'протокол' not in q_low:
        gparsed = graph_parser.parse(q)
        if gparsed:
            _exec_graph_tool(gparsed['intent'], gparsed['params'], dpg_)
            return
        if is_graph_running():
            _log(dpg_, 'Модуль графиков уже открыт.')
        else:
            res = launch_graph(dpg_)
            _log(dpg_, f"Графики: {res.get('status')}",
                 color=(255, 150, 150) if res.get('status') == 'error'
                 else (150, 255, 150))
        return

    if _is_any(q, _PROTO_LAUNCH_KW):
        if 'мск' in q_low or 'msk' in q_low:
            parsed = protocol_parser.parse(q)
            if parsed and parsed['intent'] == 'open_protocols':
                _exec_tool('open_protocols', parsed['params'], dpg_)
                return
        if is_protocol_running():
            _log(dpg_, 'Модуль протоколов уже открыт.')
        else:
            res = launch_protocol(dpg_)
            _log(dpg_, f"Протоколы: {res.get('status')}",
                 color=(255, 150, 150) if res.get('status') == 'error'
                 else (150, 255, 150))
        return

    if _is_any(q, _STATS_LAUNCH_KW):
        if is_statistics_running():
            _log(dpg_, 'Модуль статистики уже запущен.')
        else:
            res = launch_statistics(dpg_)
            if res.get('status') == 'launched':
                _log(dpg_, 'Модуль статистики запущен.')
            elif res.get('status') == 'error':
                _log(dpg_, f"Ошибка: {res.get('error')}",
                     color=(255, 150, 150))
        return

    # -------- 3. Strong protocol context first --------
    if 'протокол' in q_low:
        parsed = protocol_parser.parse(q)
        if parsed:
            _exec_tool(parsed['intent'], parsed['params'], dpg_)
            return

    # -------- 4. Graph parse --------
    gparsed = graph_parser.parse(q)
    if gparsed:
        _exec_graph_tool(gparsed['intent'], gparsed['params'], dpg_)
        return

    # -------- 5. Protocol weak forms --------
    parsed = protocol_parser.parse(q)
    if parsed:
        _exec_tool(parsed['intent'], parsed['params'], dpg_)
        return

    # -------- 6. Fallback hints --------
    has_stats = _is_any(q, _STATS_QUERY_KW)
    has_graph = any(k in q_low for k in (
        'граф', 'график', 'plot', 'тчх', 'плотн', 'распредел',
    ))
    has_protocol_weak = (
            'заказ' in q_low
            or re.search(r'\bотк\b|\bпси\b', q_low) is not None
            or re.search(r'id\s*замер', q_low) is not None
            or re.search(r'(?:удали|убери|сними)\w*\s+номер', q_low) is not None
            or re.search(r'(?:отправ\w*|передай\w*)\s+(?:в\s+)?отк', q_low) is not None
    )

    if has_graph and not has_stats:
        _log(dpg_,
             'Не удалось разобрать запрос к графикам. Примеры:\n'
             '  «открой графики МСК 456»\n'
             '  «графики номеров JN4450-JN4460 параметр F»\n'
             '  «все графики МСК 456 на одном поле»\n'
             '  «плотность распределения МСК 456»\n'
             '  «pdf графики номеров JN4450-JN4500»',
             color=(255, 220, 150))
        return

    if ('протокол' in q_low or has_protocol_weak) and not has_stats:
        _log(dpg_,
             'Не удалось разобрать запрос к протоколам. Примеры:\n'
             '  «протокол ID 42» / «напечатай протокол 312494»\n'
             '  «найди протоколы МСК 456»\n'
             '  «последний протокол МСК 456»\n'
             '  «создай протокол МСК 456 номера JN4450-JN4460»\n'
             '  «отправь в ОТК ID 312494»',
             color=(255, 220, 150))
        return

    # -------- 7. Stats (LLM) --------
    if has_stats:
        _ensure_module_opened(dpg_, 'stats')

    from Statistik.dashboard_llm import run_nl_query as _orig
    return _orig(sender, data, dpg_)


def check_llm(sender, data, dpg_):
    from Statistik.dashboard_llm import check_llm as _f
    return _f(sender, data, dpg_)


def clear_assistant_log(sender, data, dpg_):
    from Statistik.dashboard_llm import clear_assistant_log as _f
    return _f(sender, data, dpg_)


def run_llm_report(sender, data, dpg_):
    from Statistik.dashboard_llm import run_llm_report as _f
    return _f(sender, data, dpg_)


def stop_llm_report(sender, data, dpg_):
    from Statistik.dashboard_llm import stop_llm_report as _f
    return _f(sender, data, dpg_)
