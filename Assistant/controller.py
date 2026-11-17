"""Обработчик NL-запросов: pending → launch → protocol → LLM(stats).

Приоритет:
  1. Активный pending (ждали «да/нет» или ID протокола).
  2. Явные launch-команды ('запусти/открой статистику/протоколы').
  3. Детерминированный protocol-парсер (protocol_parser.parse).
  4. Если распарсили мутацию → выполняем; dry_run → pending.
  5. Иначе — LLM-статистика (старый путь).
"""
import re

import dearpygui.dearpygui as dpg

from .context import (get_ctx, set_pending, clear_pending,
                      peek_pending, is_no)
from .launcher import (
    is_statistics_running, launch_statistics,
    is_protocol_running,   launch_protocol,
)
from . import protocol_parser
from . import protocol_tools


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


def _exec_tool(name, params, dpg_):
    """Выполнить tool с обработкой dry_run → pending."""
    res = protocol_tools.execute(name, params, dpg_)

    # dry_run мутации → ставим pending, ждём подтверждения
    if isinstance(res, dict) and res.get('action') == 'dry_run':
        set_pending('confirm_' + name.split('_')[0], {
            'tool': name,
            'params': params,
        })
        _log(dpg_, protocol_tools.format_result(name, res),
             color=(255, 220, 150))
        return

    # pending await_choice уже установлен внутри tool-а
    _log(dpg_, protocol_tools.format_result(name, res),
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
    """Точка входа. Логика — в run_nl_query_impl."""
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

    # -------- 1. Pending --------
    pending = peek_pending()
    if pending:
        # Ввод нового запроса (не 'да/нет' и не ID) — отменяем pending
        if pending['kind'].startswith('confirm') and not (is_no(q)
                or q.lower() in ('да', 'yes', 'нет', 'no', 'ok',
                                 'подтверждаю', 'применить',
                                 'отмена', 'cancel', 'стоп')):
            clear_pending()
        else:
            res = protocol_tools.handle_pending_reply(q, dpg_)
            if res is not None:
                _log(dpg_, protocol_tools.format_result('pending', res),
                     color=(255, 150, 150) if res.get('error')
                     else (150, 255, 150))
                return

    # -------- 2. Explicit launch --------
    if _is_any(q, _PROTO_LAUNCH_KW):
        # «Открой протоколы на МСК 456» — сразу с фильтром
        if 'мск' in q.lower() or 'msk' in q.lower():
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

    # -------- 3. Deterministic protocol parse --------
    parsed = protocol_parser.parse(q)
    if parsed:
        _exec_tool(parsed['intent'], parsed['params'], dpg_)
        return

    # -------- 4. Protocol fallback: не пускаем в stats-LLM --------
    q_low = q.lower()
    has_stats = _is_any(q, _STATS_QUERY_KW)
    has_protocol = (
            'протокол' in q_low
            or 'заказ' in q_low
            or re.search(r'\bотк\b|\bпси\b', q_low) is not None
            or re.search(r'id\s*замер', q_low) is not None
            or re.search(r'(?:напечатай|распечатай|печать|принт|pdf)',
                         q_low) is not None
            or re.search(r'(?:удали|убери|сними)\w*\s+номер', q_low) is not None
            or re.search(r'(?:отправ\w*|передай\w*)\s+(?:в\s+)?отк',
                         q_low) is not None
            or re.search(r'(?:созда\w*|сдела\w*|сформир\w*)\s+протокол',
                         q_low) is not None
    )

    if has_protocol and not has_stats:
        _log(dpg_,
             'Не удалось разобрать запрос к протоколам. Уточните: '
             '"протокол ID 42", "МСК 456", "ID замера 789", '
             '"номера JN4450-JN4460", "все протоколы ПСИ".',
             color=(255, 220, 150))
        return

    # -------- 5. Stats (LLM) --------
    if has_stats:
        _ensure_module_opened(dpg_, 'stats')

    from Statistik.dashboard_llm import run_nl_query as _orig
    return _orig(sender, data, dpg_)


# ----- re-export -----
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