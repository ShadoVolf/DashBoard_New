"""Детерминированный разбор NL-запросов к модулю Архив.

Возвращает dict {'intent': ..., 'params': {...}} либо None.
LLM не задействован — покрывает типовые формулировки.
"""
from __future__ import annotations

import re
from typing import Optional

from Archive_View.Archive_Data import parse_numbers_input

_MSK_PATTERN = re.compile(
    r'(?:мск|msk|мк)[\s:№#]*([A-Za-zА-Яа-я0-9\-]+(?:\s*[A-Za-zА-Яа-я0-9\-]+)?)',
    re.IGNORECASE,
)
_MEASURE_ID_PATTERN = re.compile(
    r'(?:id[\s\-]?замер\w*|замер\w*\s*(?:id|№)?|measure[_\s]?id)'
    r'[\s:=#]*(\d+)', re.IGNORECASE,
)
_SPC_PATTERN = re.compile(
    r'(?:спецификац\w*|спек\w*|spc|spec)[\s:№#]*'
    r'([A-Za-zА-Яа-я0-9\-_.,/]+(?:\s*[A-Za-zА-Яа-я0-9\-_.,/]+)*)',
    re.IGNORECASE,
)
# Голый код спеки вида РК507-98.415М-220 / RK507-98,415M-220
_SPC_BARE_PATTERN = re.compile(
    r'(?<![A-Za-zА-Яа-я0-9])'
    r'([A-Za-zА-Яа-я]{1,4}\d{2,4}[-–—]\d{1,4}[.,]\d{1,4}[A-Za-zА-Яа-я]?'
    r'(?:[-–—]\d{1,6})?)'
    r'(?![A-Za-zА-Яа-я0-9])',
)
_DATE_PATTERN = re.compile(
    r'\b(\d{4}-\d{2}-\d{2}|\d{2}[.\-/]\d{2}[.\-/]\d{4})\b',
)
_NUM_PATTERN = re.compile(
    r'[A-ZА-Я]{1,4}\d+[A-ZА-Я]?'
    r'(?:\s*[-,]\s*[A-ZА-Я]{0,4}\d+[A-ZА-Я]?)*',
    re.IGNORECASE,
)
_LAST_N_RE = re.compile(
    r'(?:последн(?:ие|их|ий)|last)\s+(\d{1,4})\s*'
    r'(?:мск|msk|номер\w*|numbers?|шт\.?)?',
    re.IGNORECASE,
)
_PERIOD_RE = re.compile(
    r'(?:за\s+период|период|с\s+)(\d{4}-\d{2}-\d{2}|\d{2}[.\-/]\d{2}[.\-/]\d{4})'
    r'(?:\s*(?:по|до|-|–|—)\s*(\d{4}-\d{2}-\d{2}|\d{2}[.\-/]\d{2}[.\-/]\d{4}))?',
    re.IGNORECASE,
)


def parse(q: str) -> Optional[dict]:
    if not q or not q.strip():
        return None
    text = q.strip()
    low = text.lower()

    # Не перехватывать протоколы / графики / статистику без архивного контекста
    if 'протокол' in low and 'архив' not in low and not _has_archive_kw(low):
        return None
    if any(k in low for k in ('граф', 'график', 'plot', 'тчх', 'плотн')) and 'архив' not in low:
        return None

    # ---- запуск модуля ----
    if re.search(
        r'(?:открой|открыть|запусти|запустить)\s+(?:модуль\s+)?'
        r'(?:архив|archive)', low
    ):
        msk = _extract_msk(text)
        spc = _extract_spc(text)
        measure_id = _extract_measure_id(text)
        numbers = _extract_numbers(text)
        return {
            'intent': 'open_archive',
            'params': {
                'msk': msk,
                'spc': spc,
                'measure_id': measure_id,
                'numbers': numbers or None,
            },
        }

    has_arch = _has_archive_kw(low)
    has_export = any(k in low for k in ('экспорт', 'excel', 'xls', 'xlsx', 'в excel', 'в xls'))
    has_print = any(k in low for k in (
        'напечат', 'распечат', 'печат', 'pdf', 'принт', 'print',
    ))
    has_search = any(k in low for k in (
        'найди', 'найти', 'покажи', 'показать', 'поищи', 'список',
        'перечисли', 'вывести', 'выведи', 'list', 'поиск',
    ))
    has_load = any(k in low for k in (
        'загрузи', 'загрузить', 'открой данные', 'подгрузи', 'load',
    ))
    has_last = bool(re.search(r'последн', low))

    msk = _extract_msk(text)
    spc = _extract_spc(text)
    measure_id = _extract_measure_id(text)
    numbers = _extract_numbers(text)
    last_n = _extract_last_n(text)
    date = _extract_date(text)
    date_from, date_to = _extract_period(text)

    # ---- экспорт в Excel ----
    if has_export and (has_arch or msk or spc or numbers or last_n or date_from):
        params = {
            'msk': msk,
            'spc': spc,
            'numbers': numbers or None,
            'measure_id': measure_id,
            'last_n': last_n,
            'date': date,
            'date_from': date_from,
            'date_to': date_to,
        }
        return {'intent': 'export_archive_xls', 'params': params}

    # ---- печать протоколов измерений из архива ----
    if has_print and (has_arch or (msk or numbers) and 'протокол' not in low):
        # «напечатай архив МСК 456» / «pdf архив номера JN4450-JN4460»
        if has_arch or re.search(r'(?:архив|измерительн\w*\s+протокол)', low):
            params = {
                'msk': msk,
                'spc': spc,
                'numbers': numbers or None,
                'measure_id': measure_id,
                'last_n': last_n,
            }
            return {'intent': 'print_archive_protocols', 'params': params}

    # ---- последние N МСК по спецификации ----
    # «последние 10 мск для спецификации РК507-98.415М-220»
    # «последние 5 мск РК507-98,415М-220»
    if has_last and (
        spc
        or (has_arch and re.search(r'мск|msk', low))
        or (re.search(r'мск|msk', low) and (spc or _SPC_BARE_PATTERN.search(text)))
    ):
        if not spc:
            m_bare = _SPC_BARE_PATTERN.search(text)
            if m_bare:
                spc = m_bare.group(1).strip()
        params = {
            'spc': spc,
            'last_n': last_n or 10,
            'date_from': date_from,
            'date_to': date_to,
        }
        return {'intent': 'list_last_msk', 'params': params}

    # ---- все МСК для списка/интервала номеров ----
    if numbers and re.search(r'(?:все\s+)?мск|msk', low) and (
        has_search or has_arch or 'для' in low or 'по номер' in low
    ):
        return {
            'intent': 'list_msk_by_numbers',
            'params': {'numbers': numbers},
        }

    # ---- поиск МСК по части номера ----
    if has_search and re.search(r'мск|msk', low) and (has_arch or 'по' in low):
        partial = msk
        if not partial:
            # «найди мск 456» / «поиск мск по 25-24»
            m = re.search(
                r'(?:мск|msk)[\s:№#]*(?:по\s+)?([A-Za-zА-Яа-я0-9\-]+)',
                text, re.I,
            )
            if m:
                partial = m.group(1).strip()
        if partial or measure_id or numbers:
            return {
                'intent': 'search_msk',
                'params': {
                    'partial': partial,
                    'measure_id': measure_id,
                    'numbers': numbers or None,
                },
            }

    # ---- загрузка данных в архив ----
    if has_load or (has_arch and (msk or measure_id or numbers or spc)):
        if not (msk or measure_id or numbers or spc):
            if has_load and has_arch:
                return {'intent': 'open_archive', 'params': {}}
            return None
        params = {
            'msk': msk,
            'spc': spc,
            'measure_id': measure_id,
            'numbers': numbers or None,
            'date': date,
            'only_good': bool(re.search(r'только\s+годн|only\s+good', low)),
            'mode_full_msk': bool(re.search(
                r'вся\s+мск|full\s+msk|все\s+номера\s+мск', low
            )),
        }
        return {'intent': 'load_archive', 'params': params}

    # ---- общий поиск / список при наличии архивного контекста ----
    if has_arch and (has_search or msk or numbers or measure_id):
        if numbers and not msk and not measure_id:
            return {
                'intent': 'list_msk_by_numbers',
                'params': {'numbers': numbers},
            }
        return {
            'intent': 'search_msk',
            'params': {
                'partial': msk,
                'measure_id': measure_id,
                'numbers': numbers or None,
            },
        }

    # Явная команда без деталей
    if re.search(r'\bархив\b|\barchive\b', low) and not any(
        k in low for k in ('стат', 'протокол', 'граф', 'график')
    ):
        return {'intent': 'open_archive', 'params': {}}

    return None


def _has_archive_kw(low: str) -> bool:
    return any(k in low for k in (
        'архив', 'archive', 'просмотр архив', 'модуль архив',
    ))


def _extract_msk(text: str) -> Optional[str]:
    m = _MSK_PATTERN.search(text)
    if not m:
        return None
    val = m.group(1).strip()
    val = re.split(
        r'\s+(?:с|номерами|номера|номер|исключая|заказ|от|по|за|параметр|'
        r'спецификац|спек)\b',
        val, flags=re.IGNORECASE,
    )[0]
    return val.strip() or None


def _extract_spc(text: str) -> Optional[str]:
    m = _SPC_PATTERN.search(text)
    if m:
        val = m.group(1).strip()
        # обрезать хвост «МСК …» / «последние …»
        val = re.split(
            r'\s+(?:мск|msk|номер|последн|за\s+период)\b',
            val, flags=re.IGNORECASE,
        )[0]
        val = val.strip(' .,;:')
        if val:
            return val
    m = _SPC_BARE_PATTERN.search(text)
    if m:
        return m.group(1).strip()
    return None


def _extract_measure_id(text: str) -> Optional[int]:
    m = _MEASURE_ID_PATTERN.search(text)
    return int(m.group(1)) if m else None


def _extract_date(text: str) -> Optional[str]:
    m = _DATE_PATTERN.search(text)
    return _normalize_date(m.group(1)) if m else None


def _extract_period(text: str):
    m = _PERIOD_RE.search(text)
    if not m:
        return None, None
    d1 = _normalize_date(m.group(1))
    d2 = _normalize_date(m.group(2)) if m.group(2) else None
    return d1, d2


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


def _extract_last_n(text: str) -> Optional[int]:
    m = _LAST_N_RE.search(text)
    if not m:
        return None
    try:
        n = int(m.group(1))
        return n if 0 < n <= 5000 else None
    except ValueError:
        return None


def _extract_numbers(text: str):
    seg = re.search(
        r'(?:номер\w*|номерами|с\s+номерами|диапазон\w*|'
        r'интервал\w*)\s*[:\-]?\s*([^\n.;]+)',
        text, re.IGNORECASE,
    )
    body = seg.group(1) if seg else text
    matches = _NUM_PATTERN.findall(body)
    if not matches:
        # диапазон JN4450-JN4460 без слова «номера»
        m = re.search(
            r'\b((?:JN)?\d{3,6}[A-Za-z]?)\s*[-–—]\s*((?:JN)?\d{3,6}[A-Za-z]?)\b',
            text, re.I,
        )
        if m:
            try:
                return parse_numbers_input(f'{m.group(1)}-{m.group(2)}') or []
            except Exception:
                return [m.group(1), m.group(2)]
        plain = re.findall(r'[\dA-Za-zА-Яа-я\-]{3,}', body)
        matches = [
            p for p in plain
            if any(c.isdigit() for c in p) and len(p) >= 3
            and not re.fullmatch(r'\d{4}-\d{2}-\d{2}', p)
        ]
    out = []
    for m in matches:
        try:
            expanded = parse_numbers_input(m)
            out.extend(expanded or [m])
        except Exception:
            out.append(m)
    # убрать чистые 4+ цифры, если это похоже на ID замера/протокол
    cleaned = []
    for x in out:
        s = str(x).strip().upper()
        if re.fullmatch(r'\d{5,}', s) and 'номер' not in text.lower():
            continue
        cleaned.append(s)
    return cleaned or None
