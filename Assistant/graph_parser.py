"""Детерминированный парсер NL-команд для модуля Графики.

Рассчитан на gamma-12b в режиме без размышлений.
"""
from __future__ import annotations

import re
from typing import Optional

_MSK_RE = re.compile(r'(?:мск|msk)\s*[№#]?\s*([A-Za-zА-Яа-я0-9_\-/.]+)', re.I)
_MSK_PAIR_RE = re.compile(
    r'(?:мск|msk)\s*[№#]?\s*([A-Za-zА-Яа-я0-9_\-/.]+)\s*'
    r'(?:и|vs\.?|versus|против|/|,)\s*(?:(?:мск|msk)\s*[№#]?\s*)?'
    r'([A-Za-zА-Яа-я0-9_\-/.]+)', re.I)
_NUMBERS_RANGE_RE = re.compile(
    r'(?:номера?|numbers?)\s*([A-Za-z]*\d+[A-Za-z]*)\s*[-–—]\s*([A-Za-z]*\d+[A-Za-z]*)', re.I)
_NUMBERS_LIST_RE = re.compile(r'(?:номера?|numbers?)\s+([A-Za-z0-9_,;\s\-–—]+)', re.I)
_SINGLE_NUM_RE = re.compile(r'\b((?:JN|jn)?\d{3,6}[A-Za-z]?)\b')
_PARAM_RE = re.compile(
    r'(?:параметр|param(?:eter)?)\s*[:=]?\s*'
    r'(F\s*с\s*нагрузкой|F\s*без(?:\s*нагрузки)?|FL?|R|Q|C0|Cq|L|Rb|Rc/?Rb|'
    r'монотонность|добротность|сопротивление|частота)', re.I)
_PARAM_IMPLICIT_RE = re.compile(
    r'(?:^|[\s,;])(без\s*нагрузки|с\s*нагрузкой|F\s*без(?:\s*нагрузки)?|F\s*с\s*нагрузкой|'
    r'\bFL\b|\bF\b|\bC0\b|\bCq\b|\bRc/?Rb\b|\bMono\b|\bQ\b|\bR\b|\bL\b|\bRb\b|'
    r'монотонность|добротность|сопротивление|частота)(?:$|[\s,;])', re.I)
_PARAM_SHORT_RE = re.compile(r'\b(FL?|C0|Cq|Rc/?Rb|Mono|Q|R|L|Rb)\b')
_MEASURE_ID_RE = re.compile(
    r'(?:id\s*замер(?:а)?|measure[_\s-]?id|замер(?:а)?\s*id|id\s*замера)\s*[:=#№]?\s*(\d+)', re.I)
_MEASURE_ID_SHORT_RE = re.compile(r'(?:^|[\s])id\s*[:=#№]?\s*(\d{3,})', re.I)
_LAST_N_RE = re.compile(r'(?:последн(?:ие|их|ий)|last)\s+(\d{1,4})\s*(?:номер|numbers?|шт\.?)?', re.I)


def _extract_msk(q):
    m = _MSK_RE.search(q)
    return m.group(1).strip() if m else None


def _extract_msk_pair(q):
    m = _MSK_PAIR_RE.search(q)
    if m:
        a, b = m.group(1).strip(), m.group(2).strip()
        if a and b and a != b:
            return a, b
    all_m = _MSK_RE.findall(q)
    if len(all_m) >= 2:
        return all_m[0].strip(), all_m[1].strip()
    return None


def _extract_param(q):
    m = _PARAM_RE.search(q)
    if m:
        return m.group(1).strip()
    m = _PARAM_IMPLICIT_RE.search(q)
    if m:
        return m.group(1).strip()
    m = _PARAM_SHORT_RE.search(q)
    if m:
        return m.group(1).strip()
    ql = q.lower()
    if 'без нагруз' in ql:
        return 'F без нагрузки'
    if 'с нагруз' in ql:
        return 'F с нагрузкой'
    return None


def _extract_measure_id(q):
    m = _MEASURE_ID_RE.search(q)
    if m:
        return m.group(1)
    m = _MEASURE_ID_SHORT_RE.search(q)
    if m:
        return m.group(1)
    return None


def _extract_last_n(q):
    m = _LAST_N_RE.search(q)
    if not m:
        return None
    try:
        n = int(m.group(1))
        return n if 0 < n <= 5000 else None
    except ValueError:
        return None


def _extract_quality(q):
    ql = q.lower()
    if re.search(r'только\s+годн|only\s+good|только\s+норм', ql):
        return 'only_good'
    if re.search(r'только\s+брак|only\s+reject|только\s+негодн', ql):
        return 'only_reject'
    return None


def _extract_numbers(q):
    m = _NUMBERS_RANGE_RE.search(q)
    if m:
        a, b = m.group(1), m.group(2)
        try:
            from Archive_View.Archive_Data import parse_numbers_input
            return parse_numbers_input(f'{a}-{b}') or [a, b]
        except Exception:
            return [a, b]
    m = _NUMBERS_LIST_RE.search(q)
    if m:
        chunk = m.group(1)
        if not re.match(r'последн|last\s+\d', chunk, re.I):
            try:
                from Archive_View.Archive_Data import parse_numbers_input
                nums = parse_numbers_input(chunk)
                if nums:
                    return nums
            except Exception:
                pass
            return [x.strip() for x in re.split(r'[,;\s]+', chunk) if x.strip()]
    return _SINGLE_NUM_RE.findall(q)


def parse(q: str) -> Optional[dict]:
    if not q or not q.strip():
        return None
    ql = q.lower().strip()

    # Протоколы — не наш домен
    if 'протокол' in ql:
        return None

    graph_kw = ('граф', 'график', 'plot', 'chart', 'тчх', 'крив',
                'плотн', 'распредел', 'kde', 'гистограм',
                'сравни', 'сравнить', 'compare', 'отчёт', 'отчет', 'report')
    has_graph_kw = any(k in ql for k in graph_kw)
    has_print_msk = (('печат' in ql or 'pdf' in ql or 'принт' in ql)
                     and ('мск' in ql or 'msk' in ql or 'номер' in ql
                          or 'id замер' in ql or 'measure' in ql))
    if not has_graph_kw and not has_print_msk and not _extract_measure_id(q):
        return None

    msk = _extract_msk(q)
    msk_pair = _extract_msk_pair(q)
    numbers = _extract_numbers(q)
    param = _extract_param(q)
    measure_id = _extract_measure_id(q)
    last_n = _extract_last_n(q)
    quality = _extract_quality(q)

    want_print = any(k in ql for k in ('печат', 'распечат', 'напечат', 'pdf', 'принт', 'print', 'экспорт'))
    want_density = any(k in ql for k in ('плотн', 'распредел', 'kde', 'гистограм', 'density'))
    want_all = any(k in ql for k in ('все на одном', 'на одном поле', 'на одном графике', 'all on one', 'вместе', 'одном окне'))
    want_compare = any(k in ql for k in ('сравни', 'сравнить', 'compare', 'vs', 'versus'))
    want_report = any(k in ql for k in ('отчёт', 'отчет', 'auto report', 'автоотчёт', 'автоотчет', 'полный отчёт', 'полный отчет', 'report'))

    params = {}
    if msk:
        params['msk'] = msk
    if numbers:
        params['numbers'] = numbers
    if param:
        params['param'] = param
    if measure_id:
        params['measure_id'] = measure_id
    if last_n:
        params['last_n'] = last_n
    if quality:
        params['quality'] = quality
    if want_print:
        params['print'] = True
    if msk_pair:
        params['msk_a'], params['msk_b'] = msk_pair[0], msk_pair[1]

    if want_compare and (msk_pair or (msk and 'и' in ql)):
        if msk_pair:
            params['msk_a'], params['msk_b'] = msk_pair
        return {'intent': 'compare_msk', 'params': params}
    if want_report and (msk or measure_id):
        return {'intent': 'auto_report', 'params': params}
    if want_density:
        if not msk and not numbers and not measure_id:
            return None
        return {'intent': 'density', 'params': params}
    if want_all and (msk or measure_id):
        return {'intent': 'all_on_one', 'params': params}
    if want_print and numbers and not msk and not measure_id:
        return {'intent': 'pdf_numbers', 'params': params}
    if want_print and (msk or measure_id):
        return {'intent': 'print_graphs_msk', 'params': params}

    if measure_id and not msk:
        if numbers and all(str(n) == str(measure_id) for n in numbers):
            numbers = []
            params.pop('numbers', None)
        if not numbers:
            return {'intent': 'open_by_measure_id', 'params': params}

    if numbers and not msk:
        return {'intent': 'open_graphs_numbers', 'params': params}
    if msk:
        return {'intent': 'open_graphs_msk', 'params': params}
    if any(k in ql for k in ('открой график', 'открыть график', 'запусти график', 'открой модуль график', 'open graph')):
        return {'intent': 'open_graphs_msk', 'params': params}
    return None
