"""Детерминированный парсер NL-команд для модуля Графики.

Рассчитан на gamma-12b в режиме без размышлений:
короткие чёткие паттерны, без неоднозначных эвристик.
"""
from __future__ import annotations

import re
from typing import Optional


# ---------------------------------------------------------------------------
# Извлечение сущностей
# ---------------------------------------------------------------------------
_MSK_RE = re.compile(
    r'(?:мск|msk)\s*[№#]?\s*([A-Za-zА-Яа-я0-9_\-/.]+)',
    re.IGNORECASE,
)
_NUMBERS_RANGE_RE = re.compile(
    r'(?:номера?|numbers?)\s*'
    r'([A-Za-z]*\d+[A-Za-z]*)\s*[-–—]\s*([A-Za-z]*\d+[A-Za-z]*)',
    re.IGNORECASE,
)
_NUMBERS_LIST_RE = re.compile(
    r'(?:номера?|numbers?)\s+([A-Za-z0-9_,;\s\-–—]+)',
    re.IGNORECASE,
)
_SINGLE_NUM_RE = re.compile(
    r'\b((?:JN|jn)?\d{3,6}[A-Za-z]?)\b',
)
_PARAM_RE = re.compile(
    r'(?:параметр|param(?:eter)?)\s*[:=]?\s*'
    r'(F\s*с\s*нагрузкой|F\s*без(?:\s*нагрузки)?|FL?|R|Q|C0|Cq|L|Rb|Rc/?Rb|'
    r'монотонность|добротность|сопротивление|частота)',
    re.IGNORECASE,
)
_PARAM_SHORT_RE = re.compile(
    r'\b(FL?|C0|Cq|Rc/?Rb|Mono|Q|R|L|Rb)\b',
)


def _extract_msk(q: str) -> Optional[str]:
    m = _MSK_RE.search(q)
    return m.group(1).strip() if m else None


def _extract_param(q: str) -> Optional[str]:
    m = _PARAM_RE.search(q)
    if m:
        return m.group(1).strip()
    m = _PARAM_SHORT_RE.search(q)
    if m:
        return m.group(1).strip()
    return None


def _extract_numbers(q: str) -> list:
    m = _NUMBERS_RANGE_RE.search(q)
    if m:
        a, b = m.group(1), m.group(2)
        # раскрытие диапазона, если числовой
        try:
            from Archive_View.Archive_Data import parse_numbers_input
            return parse_numbers_input(f'{a}-{b}') or [a, b]
        except Exception:
            return [a, b]

    m = _NUMBERS_LIST_RE.search(q)
    if m:
        chunk = m.group(1)
        try:
            from Archive_View.Archive_Data import parse_numbers_input
            nums = parse_numbers_input(chunk)
            if nums:
                return nums
        except Exception:
            pass
        return [x.strip() for x in re.split(r'[,;\s]+', chunk) if x.strip()]

    # одиночные JN-номера
    found = _SINGLE_NUM_RE.findall(q)
    return found


# ---------------------------------------------------------------------------
# Интенты
# ---------------------------------------------------------------------------
def parse(q: str) -> Optional[dict]:
    """Вернуть {'intent': str, 'params': dict} или None."""
    if not q or not q.strip():
        return None
    ql = q.lower().strip()

    # Быстрый отсев: нет графиковых ключевых слов
    graph_kw = ('граф', 'график', 'plot', 'chart', 'тчх', 'крив',
                'плотн', 'распредел', 'kde', 'гистограм')
    if not any(k in ql for k in graph_kw):
        # «напечатай МСК 456» без слова график — не наш
        if not (('печат' in ql or 'pdf' in ql or 'принт' in ql)
                and ('мск' in ql or 'msk' in ql or 'номер' in ql)):
            return None

    msk = _extract_msk(q)
    numbers = _extract_numbers(q)
    param = _extract_param(q)
    want_print = any(k in ql for k in (
        'печат', 'распечат', 'напечат', 'pdf', 'принт', 'print', 'экспорт',
    ))
    want_density = any(k in ql for k in (
        'плотн', 'распредел', 'kde', 'гистограм', 'density',
    ))
    want_all = any(k in ql for k in (
        'все на одном', 'на одном поле', 'на одном графике',
        'all on one', 'вместе', 'одном окне',
    ))

    params = {}
    if msk:
        params['msk'] = msk
    if numbers:
        params['numbers'] = numbers
    if param:
        params['param'] = param
    if want_print:
        params['print'] = True

    # ---- приоритет интентов ----
    if want_density:
        if not msk and not numbers:
            return None
        return {'intent': 'density', 'params': params}

    if want_all and msk:
        return {'intent': 'all_on_one', 'params': params}

    if want_print and numbers and not msk:
        return {'intent': 'pdf_numbers', 'params': params}

    if want_print and msk:
        return {'intent': 'print_graphs_msk', 'params': params}

    if numbers and not msk:
        return {'intent': 'open_graphs_numbers', 'params': params}

    if msk:
        return {'intent': 'open_graphs_msk', 'params': params}

    # «открой графики» без МСК/номеров — просто открыть модуль
    if any(k in ql for k in ('открой график', 'открыть график', 'запусти график',
                             'открой модуль график', 'open graph')):
        return {'intent': 'open_graphs_msk', 'params': params}

    return None
