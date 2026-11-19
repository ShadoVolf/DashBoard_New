"""Детерминированный разбор NL-запросов: спецификации и температурные интервалы.

Возвращает dict {'intent': ..., 'params': {...}} либо None.

Примеры запросов:
  «создай спецификацию РК508 на основе РК507 с параметрами R, C0, Fmax»
  «сделай новую спецификацию NEW на базе OLD добавь монотонность max 3»
  «создай интервал -10...+50 step 5(28, 43) для спецификации РК507-98.415М-220»
  «температурный интервал от -10 до +50 шагом 5 с точками 28, 43 для XXX»
  «список спецификаций» / «параметры спецификации XXX» /
  «какие параметры есть в spc_map»
"""
from __future__ import annotations

import re
from typing import Optional

from .spec_tools import parse_interval_text

_CREATE_SPEC_RE = re.compile(
    r'(?:созда|сдела|сформир|добав|зарегистр)\w*\s+'
    r'(?:(?:новую|следующ\w+|друг\w+)\s+)?'
    r'(?:спецификац\w*|спек\w*|spc|spec)\b',
    re.IGNORECASE,
)
_INTERVAL_KW_RE = re.compile(r'интервал', re.IGNORECASE)
_TEMP_KW_RE = re.compile(r'температур\w*', re.IGNORECASE)

_SPC_WORD_RE = re.compile(
    r'(?:спецификац\w*|спек\w*|spc|spec|баз\w*|основ\w*)'
    r'[\s:№#]*'
    r'([A-Za-zА-Яа-я0-9]+(?:[-–—][A-Za-zА-Яа-я0-9.,]+)*)',
    re.IGNORECASE,
)
# Голый код спеки вида РК507-98.415М-220 / RK507-98,415M-220
_SPC_BARE_RE = re.compile(
    r'(?<![A-Za-zА-Яа-я0-9])'
    r'([A-Za-zА-Яа-я]{1,4}\d{2,4}[-–—]\d{1,4}[.,]\d{1,4}[A-Za-zА-Яа-я]?'
    r'(?:[-–—]\d{1,6})?)'
    r'(?![A-Za-zА-Яа-я0-9])',
)
_BASE_RE = re.compile(
    r'(?:на\s+основ\w+|на\s+баз\w+|по\s+образц\w+|коп\w+|из|от)\s+'
    r'([A-Za-zА-Яа-я0-9]+(?:[-–—][A-Za-zА-Яа-я0-9.,]+)*)',
    re.IGNORECASE,
)
_WITH_PARAMS_RE = re.compile(
    r'(?:с\s+параметр\w*|параметр\w*|добав\w*|включ\w*|и)\s*[:\-]?\s*'
    r'(.+)$',
    re.IGNORECASE,
)
_LIST_SPECS_RE = re.compile(
    r'(?:список|покажи|показать|какие)\s+.*спецификац|спецификац\w*\s+список',
    re.IGNORECASE,
)
_GET_PARAMS_RE = re.compile(
    r'(?:параметр\w*|норм\w*)\s+(?:спецификац\w*|спек\w*|spc|spec)',
    re.IGNORECASE,
)
_SPC_MAP_LIST_RE = re.compile(
    r'(?:какие\s+)?(?:параметр\w*|обозначени\w*)[^.?]*'
    r'(?:spc[_\s]?map|справочник|все\s+параметр)',
    re.IGNORECASE,
)


def _clean_token(s: str) -> str:
    return (s or '').strip().strip('.,;:!?').strip()


def _extract_spc_codes(text: str) -> list[str]:
    """Все «голые» коды спецификаций вида РК507-98.415М-220."""
    return [m.group(1) for m in _SPC_BARE_RE.finditer(text)]


def _extract_base(text: str) -> Optional[str]:
    m = _BASE_RE.search(text)
    if m:
        return _clean_token(m.group(1))
    return None


def _extract_new_name(text: str, base: Optional[str],
                      spc_codes: list[str]) -> Optional[str]:
    """Имя новой спецификации: после глагола «создай спецификацию X …»."""
    m = re.search(
        r'(?:созда|сдела|сформир|добав)\w*\s+(?:новую\s+)?'
        r'(?:спецификац\w*|спек\w*|spc|spec)\s+'
        r'([A-Za-zА-Яа-я0-9_]+(?:[-–—][A-Za-zА-Яа-я0-9.,_]+)*)',
        text, re.IGNORECASE)
    if m:
        name = _clean_token(m.group(1))
        # не путать с предлогами
        if name.lower() not in ('на', 'из', 'от', 'для', 'с', 'по', 'new'):
            return name
        return name or None
    # «спецификацию X создай»
    m2 = _SPC_WORD_RE.search(text)
    if m2:
        cand = _clean_token(m2.group(1))
        if base and cand.casefold() == base.casefold():
            return None
        return cand
    return None


def _split_param_tokens(seg: str) -> list[str]:
    """Разбить хвост «R, C0, Fmax max 30 min 10» на токены параметров."""
    seg = seg.strip().strip('.;:')
    if not seg:
        return []
    parts = re.split(r',|;|\s+и\s+', seg)
    out = []
    for p in parts:
        p = p.strip()
        if p:
            out.append(p)
    return out


def _extract_params(text: str, consumed: list[str]) -> list[str]:
    """Список новых параметров из хвоста запроса.

    Из текста вырезаются уже использованные фрагменты (имя, база,
    интервал), затем ищется сегмент «с параметрами ...» / «добавь ...».
    """
    t = text
    for c in consumed:
        if c:
            t = t.replace(c, ' ')
    m = _WITH_PARAMS_RE.search(t)
    if not m:
        return []
    seg = m.group(1)
    # обрываем на упоминании интервала
    seg = re.split(r'(?:интервал|температур)', seg, flags=re.IGNORECASE)[0]
    tokens = _split_param_tokens(seg)
    cleaned = []
    for tok in tokens:
        tok = tok.strip()
        if not tok or tok.lower() in ('параметр', 'параметры', 'параметрами',
                                      'новый', 'новые', 'добавь', 'включи',
                                      'максимум', 'минимум'):
            continue
        cleaned.append(tok)
    return cleaned


def _extract_wait(text: str) -> Optional[float]:
    m = re.search(r'(?:выдержк\w*|wait|время)\D{0,10}(\d+(?:[.,]\d+)?)',
                  text, re.IGNORECASE)
    if m:
        try:
            return float(m.group(1).replace(',', '.'))
        except ValueError:
            return None
    return None


def parse(q: str) -> Optional[dict]:
    if not q or not q.strip():
        return None
    text = q.strip()
    low = text.lower()

    # протоколы — не наш домен
    if 'протокол' in low:
        return None

    interval = parse_interval_text(text)
    want_interval_kw = bool(_INTERVAL_KW_RE.search(low))
    want_temp_kw = bool(_TEMP_KW_RE.search(low))

    # ---- создание интервала (для существующей спецификации) ----
    if interval and (want_interval_kw or want_temp_kw):
        codes = _extract_spc_codes(text)
        spc = None
        m = re.search(r'(?:для|спецификац\w*|спек\w*|spc|spec)'
                      r'[\s:№#]*([A-Za-zА-Яа-я0-9]+(?:[-–—]'
                      r'[A-Za-zА-Яа-я0-9.,]+)*)', text, re.IGNORECASE)
        if m:
            spc = _clean_token(m.group(1))
        if not spc and codes:
            spc = codes[-1]
        wait = _extract_wait(text)
        if wait is not None:
            interval['wait'] = wait
        return {
            'intent': 'create_temp_interval',
            'params': {'spc': spc, 'interval': interval},
        }

    # ---- создание спецификации (+опционально интервал) ----
    if _CREATE_SPEC_RE.search(text):
        base = _extract_base(text)
        codes = _extract_spc_codes(text)
        if not base and codes:
            # первая «голая» спека считается базой, если она не новое имя
            base = codes[0]
        name = _extract_new_name(text, base, codes)
        if name and base and name.casefold() == base.casefold():
            # одно и то же — ищем другое вхождение
            alt = [c for c in codes if c.casefold() != name.casefold()]
            base = alt[0] if alt else base
        params_list = _extract_params(text, consumed=[n for n in
                                                      (name, base) if n])
        wait = _extract_wait(text)
        if interval and wait is not None:
            interval['wait'] = wait
        params = {
            'name': name,
            'base': base,
            'new_params': params_list,
        }
        if interval:
            params['interval'] = interval
        if wait is not None:
            params['wait'] = wait
        return {'intent': 'create_spec', 'params': params}

    # ---- справочные запросы ----
    if _SPC_MAP_LIST_RE.search(text):
        return {'intent': 'list_spc_params', 'params': {}}

    if _GET_PARAMS_RE.search(text):
        codes = _extract_spc_codes(text)
        spc = codes[0] if codes else None
        if not spc:
            m = _SPC_WORD_RE.search(text)
            spc = _clean_token(m.group(1)) if m else None
        return {'intent': 'get_spec_params', 'params': {'spc': spc}}

    if _LIST_SPECS_RE.search(text) and 'спецификац' in low:
        return {'intent': 'list_specs', 'params': {'search': ''}}

    # голый интервал без ключевого слова, но со словом «шаг/step» и «для спеки»
    if interval and re.search(r'(?:шаг|step)', low):
        codes = _extract_spc_codes(text)
        return {
            'intent': 'create_temp_interval',
            'params': {'spc': codes[-1] if codes else None,
                       'interval': interval},
        }

    return None
