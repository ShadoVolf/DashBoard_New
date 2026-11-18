"""Детерминированный разбор NL-запросов к модулю Протоколы.

Возвращает dict {'intent':..., 'params': {...}} либо None.
LLM не задействован — покрывает типовые формулировки для gamma-12b.
"""
from __future__ import annotations

import re
from typing import Optional

from Archive_View.Archive_Data import parse_numbers_input

_NUM_PATTERN = re.compile(
    r'[A-ZА-Я]{1,4}\d+[A-ZА-Я]?'
    r'(?:\s*[-,]\s*[A-ZА-Я]{0,4}\d+[A-ZА-Я]?)*',
    re.IGNORECASE,
)
_MSK_PATTERN = re.compile(
    r'(?:мск|msk|мк)[\s:№#]*([A-Za-zА-Яа-я0-9\-]+(?:\s*[A-Za-zА-Яа-я0-9\-]+)?)',
    re.IGNORECASE,
)
_MEASURE_ID_PATTERN = re.compile(
    r'(?:id[\s\-]?замер\w*|замер\w*\s*(?:id|№)?|measure[_\s]?id)'
    r'[\s:=#]*(\d+)', re.IGNORECASE,
)
_PROTOKOL_ID_PATTERN = re.compile(
    r'(?:протокол\w*[\s№#]*(?:id\s*)?|id\s*протокол\w*[\s:№#]*)'
    r'(\d+)', re.IGNORECASE,
)
_DATE_PATTERN = re.compile(
    r'\b(\d{4}-\d{2}-\d{2}|\d{2}[.\-/]\d{2}[.\-/]\d{4})\b',
)

_PREPOSITIONS = frozenset((
    'в', 'во', 'к', 'ко', 'от', 'на', 'до', 'из', 'по', 'и',
    'протокол', 'протоколу', 'протокола', 'протоколе', 'протоколы',
    'заказ', 'заказа', 'заказу', 'заказе',
    'номер', 'номера', 'номеру',
))


def parse(q: str):
    if not q or not q.strip():
        return None
    text = q.strip()
    low = text.lower()

    if re.search(r'(?:открой|открыть|запусти|запустить)\s+(?:модуль\s+)?'
                 r'протокол', low):
        msk = _extract_msk(text)
        return {'intent': 'open_protocols', 'params': {'msk': msk}}

    if (re.search(r'(?:созда|сдела|сформир|выпусти)\w*\s+протокол', low)
            or re.search(r'напечата\w*\s+протокол\w*\s+(?:на|для|мск|msk)', low)):
        msk = _extract_msk(text)
        numbers = _extract_numbers(text, exclude=False)
        if not numbers:
            numbers = _extract_numbers_loose(text)
        exclude = _extract_numbers(text, exclude=True)
        order = _extract_order(text, exclude_from_lot=numbers)
        max_count = _extract_max_count(text)
        psi_type = _extract_psi_type(low)
        params = {
            'msk_or_spec': msk,
            'numbers': numbers or None,
            'exclude_numbers': exclude or None,
            'psi_type': psi_type or 'ОТК',
            'psi_type_explicit': psi_type is not None,
            'order': order,
            'max_count': max_count,
        }
        if not (params['msk_or_spec'] or params['numbers']):
            return None
        return {'intent': 'create_protocols', 'params': params}

    if re.search(r'(?:отправ|передай|передать)\w*\s+(?:в\s+)?отк', low):
        pid = _extract_protokol_id(text) or _extract_bare_id(text)
        if not pid:
            return None
        return {'intent': 'send_to_otk', 'params': {'protokol_id': pid}}

    if re.search(r'(?:напечатай|распечатай|печать|принт|pdf|в\s+pdf)', low):
        if any(k in low for k in ('граф', 'график', 'plot', 'тчх', 'плотн')):
            return None
        if 'протокол' not in low and not _extract_protokol_id(text):
            pid_try = _extract_any_id(text) or _extract_bare_id(text)
            if not pid_try or re.search(r'\b(?:мск|msk)\b', low):
                return None
        pid = (_extract_protokol_id(text)
               or _extract_any_id(text)
               or _extract_bare_id(text))
        if not pid:
            return None
        return {'intent': 'print_protocol', 'params': {'protokol_id': pid}}

    if (re.search(r'заказ', low)
            and re.search(r'(?:добав|внеси|постав|прикреп|сохран|'
                          r'зада|установ)', low)
            and not re.search(r'(?:добав|внеси|включи)\w*\s+номер', low)):
        pid = _extract_protokol_id(text)
        order = _extract_order(text)
        return {'intent': 'add_order',
                'params': {'protokol_id': pid, 'order': order}}

    if re.search(r'(?:удали|удалить|убери|сними|снять)\w*\s+номер', low):
        pid = _extract_protokol_id(text)
        msk = _extract_msk(text)
        numbers = _extract_numbers(text, exclude=False) or _extract_numbers_loose(text)
        if not numbers or not (pid or msk):
            return None
        return {'intent': 'delete_numbers',
                'params': {'protokol_id': pid, 'msk': msk, 'numbers': numbers}}

    if re.search(r'(?:добав|внеси|включи)\w*\s+номер', low):
        pid = _extract_protokol_id(text)
        numbers = _extract_numbers(text, exclude=False) or _extract_numbers_loose(text)
        if not (pid and numbers):
            return None
        return {'intent': 'add_numbers',
                'params': {'protokol_id': pid, 'numbers': numbers}}

    if re.search(r'(?:последн\w*\s+протокол|latest\s+protocol)', low):
        msk = _extract_msk(text)
        psitype = _extract_psi_type(low)
        params = {'latest': True, 'limit': 1}
        if msk:
            params['msk'] = msk
        if psitype:
            params['psi_type'] = psitype
        return {'intent': 'latest_protocol', 'params': params}

    if re.search(r'(?:найди|найти|покажи|показать|поищи|список|'
                 r'перечисли|вывести|выведи|list)\w*.*протокол', low):
        return _search_or_info(text, low)

    if 'протокол' in low:
        msk = _extract_msk(text)
        measure_id = _extract_measure_id(text)
        numbers = _extract_numbers(text, exclude=False)
        pid = _extract_protokol_id(text)
        date = _extract_date(text)
        if not any((msk, measure_id, numbers, pid, date, _extract_psi_type(low))):
            if re.search(r'(?:все|список|list)', low):
                return {'intent': 'search_protocols', 'params': {'limit': 50}}
            return {'intent': 'open_protocols', 'params': {}}
        return _search_or_info(text, low)

    stripped = text.strip()
    if re.fullmatch(r'\d{3,}', stripped):
        return {'intent': 'get_protocol_info',
                'params': {'protokol_id': int(stripped)}}
    return None


def _search_or_info(text: str, low: str) -> dict:
    msk = _extract_msk(text)
    measure_id = _extract_measure_id(text)
    numbers = _extract_numbers(text, exclude=False) or _extract_numbers_loose(text)
    pid = _extract_protokol_id(text)
    psitype = _extract_psi_type(low)
    date = _extract_date(text)
    latest = bool(re.search(r'последн', low))
    if pid and not (msk or measure_id or numbers):
        return {'intent': 'get_protocol_info', 'params': {'protokol_id': pid}}
    params = {'msk': msk, 'measure_id': measure_id, 'numbers': numbers or None,
              'psi_type': psitype, 'date': date}
    if latest:
        params['latest'] = True
        params['limit'] = 1
        return {'intent': 'latest_protocol', 'params': params}
    return {'intent': 'search_protocols', 'params': params}


def _extract_msk(text) -> Optional[str]:
    m = _MSK_PATTERN.search(text)
    if not m:
        return None
    val = m.group(1).strip()
    val = re.split(
        r'\s+(?:с|номерами|номера|номер|исключая|заказ|от|по|за|параметр)\b',
        val, flags=re.IGNORECASE)[0]
    val = re.sub(r'\s+номер\w*.*$', '', val, flags=re.IGNORECASE).strip()
    return val.strip() or None


def _extract_measure_id(text) -> Optional[int]:
    m = _MEASURE_ID_PATTERN.search(text)
    return int(m.group(1)) if m else None


def _extract_protokol_id(text) -> Optional[int]:
    m = _PROTOKOL_ID_PATTERN.search(text)
    return int(m.group(1)) if m else None


def _extract_any_id(text) -> Optional[int]:
    m = re.search(r'(?:id|№|no\.?)\s*[:=#]?\s*(\d{2,})', text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_bare_id(text, exclude=None) -> Optional[int]:
    for m in re.finditer(r'(?<![\d\-])(\d{4,})(?![\d\-])', text):
        val = int(m.group(1))
        if exclude is not None and val == exclude:
            continue
        return val
    return None


def _extract_max_count(text) -> Optional[int]:
    m = re.search(
        r'(?:не\s+более|макс\w*|максимум|первые|огранич\w*)\s+'
        r'(\d+)\s*(?:шт|штук|номер\w*|резонатор\w*)?',
        text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_psi_type(low: str) -> Optional[str]:
    if re.search(r'\bпси\b', low):
        return 'ПСИ'
    if re.search(r'\bотк\b|предъяв', low):
        return 'ОТК'
    return None


def _extract_date(text) -> Optional[str]:
    m = _DATE_PATTERN.search(text)
    return _normalize_date(m.group(1)) if m else None


def _normalize_date(d) -> Optional[str]:
    if not d:
        return None
    s = str(d).strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        return s
    m = re.fullmatch(r'(\d{2})[.\-/](\d{2})[.\-/](\d{4})', s)
    if m:
        return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
    return s


def _extract_numbers(text, exclude=False):
    if exclude:
        seg = re.search(r'(?:исключ\w*|без|кроме|за\s+исключением)\s+([^\n.;]+)',
                        text, re.IGNORECASE)
        if not seg:
            return []
        body = seg.group(1)
    else:
        seg = re.search(
            r'(?:номер\w*|номерами|с\s+номерами|диапазон\w*)\s*[:\-]?\s*([^\n.;]+)',
            text, re.IGNORECASE)
        if not seg:
            return []
        body = seg.group(1)
    matches = _NUM_PATTERN.findall(body)
    if not matches:
        plain = re.findall(r'[\dA-Za-zА-Яа-я\-]{2,}', body)
        matches = [p for p in plain if any(c.isdigit() for c in p) and len(p) >= 3]
    out = []
    for m in matches:
        try:
            expanded = parse_numbers_input(m)
            out.extend(expanded or [m])
        except Exception:
            out.append(m)
    return out


def _extract_numbers_loose(text):
    if _extract_protokol_id(text) and not re.search(r'JN\d', text, re.I):
        return []
    found = []
    for m in _NUM_PATTERN.finditer(text):
        chunk = m.group(0)
        if re.fullmatch(r'\d{4,}', chunk) and 'протокол' in text.lower():
            continue
        try:
            expanded = parse_numbers_input(chunk)
            found.extend(expanded or [chunk])
        except Exception:
            found.append(chunk)
    if not found:
        m = re.search(
            r'\b((?:JN)?\d{3,6}[A-Za-z]?)\s*[-–—]\s*((?:JN)?\d{3,6}[A-Za-z]?)\b',
            text, re.I)
        if m:
            try:
                found = parse_numbers_input(f'{m.group(1)}-{m.group(2)}') or []
            except Exception:
                found = [m.group(1), m.group(2)]
    return found


def _extract_order(text, exclude_from_lot=None):
    if not text or not re.search(r'заказ', text, re.IGNORECASE):
        return None
    exclude_set = {str(x).strip().upper() for x in (exclude_from_lot or [])}
    date = _extract_date(text)
    pid = _extract_protokol_id(text)
    m = re.search(r'заказ\w*', text, re.IGNORECASE)
    if not m:
        return None
    tail = text[m.end():]
    lot = None
    for w in re.findall(r'[^\s,.;:()]+', tail):
        w_strip = w.strip('.,;:()"\'')
        w_low = w_strip.lower()
        if not w_strip or w_low in _PREPOSITIONS:
            continue
        if not any(ch.isdigit() for ch in w_strip):
            continue
        if re.fullmatch(r'\d{4}-\d{2}-\d{2}', w_strip):
            continue
        if re.fullmatch(r'\d{2}[.\-/]\d{2}[.\-/]\d{4}', w_strip):
            continue
        if pid is not None and w_strip.isdigit() and int(w_strip) == pid:
            continue
        if w_strip.upper() in exclude_set:
            continue
        lot = w_strip
        break
    return {'lot': lot, 'date': date}
