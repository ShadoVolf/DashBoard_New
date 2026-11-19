"""Детерминированный разбор NL: спецификации, модификация, интервалы.

Примеры:
  «создай спецификацию РК507-98.440М-240 на основе РК507-98.415М-220»
  «создай спецификацию NEW на базе OLD, точность настройки =+/- 20»
  «измени в спецификации РК507-98.415М-220 точность настройки =+/- 7,
   сопротивление до 120»
  «установи в РК507-98.415М-220 R max 30 min 10»
  «создай температурный интервал от -30 до +60 шагом 5 с точками 23,28»
"""
from __future__ import annotations

import re
from typing import Optional

from .spec_tools import parse_interval_text, parse_norm_assignment

_CREATE_SPEC_RE = re.compile(
    r'(?:созда|сдела|сформир|зарегистр)\w*\s+'
    r'(?:(?:новую|следующ\w+|друг\w+)\s+)?'
    r'(?:спецификац\w*|спек\w*|spc|spec)\b',
    re.IGNORECASE,
)
_MODIFY_SPEC_RE = re.compile(
    r'(?:измен|постав|установи|поправ|задай|обнов|прав)\w*\s+'
    r'(?:в\s+)?'
    r'(?:спецификац\w*|спек\w*|spc|spec)?',
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
_SPC_BARE_RE = re.compile(
    r'(?<![A-Za-zА-Яа-я0-9])'
    r'([A-Za-zА-Яа-я]{1,4}\d{2,4}[-–—]\d{1,4}[.,]\d{1,4}[A-Za-zА-Яа-я]?'
    r'(?:[-–—]\d{1,6})?)'
    r'(?![A-Za-zА-Яа-я0-9])',
)
_BASE_RE = re.compile(
    r'(?:на\s+основ\w+|на\s+баз\w+|по\s+образц\w+|коп\w+)\s+'
    r'([A-Za-zА-Яа-я0-9]+(?:[-–—][A-Za-zА-Яа-я0-9.,]+)*)',
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
    return [m.group(1) for m in _SPC_BARE_RE.finditer(text)]


def _extract_base(text: str) -> Optional[str]:
    m = _BASE_RE.search(text)
    if m:
        return _clean_token(m.group(1))
    return None


def _extract_new_name(text: str, base: Optional[str],
                      spc_codes: list[str]) -> Optional[str]:
    m = re.search(
        r'(?:созда|сдела|сформир|зарегистр)\w*\s+(?:новую\s+)?'
        r'(?:спецификац\w*|спек\w*|spc|spec)\s+'
        r'([A-Za-zА-Яа-я0-9_]+(?:[-–—][A-Za-zА-Яа-я0-9.,_]+)*)',
        text, re.IGNORECASE)
    if m:
        name = _clean_token(m.group(1))
        if name.lower() not in ('на', 'из', 'от', 'для', 'с', 'по', 'new',
                                'базе', 'основе'):
            return name
    for c in spc_codes:
        if base and c.casefold() == base.casefold():
            continue
        return c
    return None


def _split_change_tokens(seg: str) -> list[str]:
    seg = (seg or '').strip().strip('.;:')
    if not seg:
        return []
    parts = re.split(r'\s*,\s*|\s*;\s*|\s+и\s+', seg)
    return [p.strip() for p in parts if p.strip()]


def _extract_changes_tail(text: str, spc: Optional[str]) -> list[str]:
    t = text
    if spc:
        t = re.sub(re.escape(spc), ' ', t, count=1, flags=re.IGNORECASE)
    t = re.sub(
        r'(?:измен|постав|установи|поправ|задай|обнов|прав)\w*',
        ' ', t, flags=re.IGNORECASE)
    t = re.sub(
        r'(?:в\s+)?(?:спецификац\w*|спек\w*|spc|spec)',
        ' ', t, flags=re.IGNORECASE)
    t = re.sub(r'\s+', ' ', t).strip(' :,-')
    return _split_change_tokens(t)


def _extract_create_param_tokens(text: str, consumed: list[str]) -> list[str]:
    t = text
    for c in consumed:
        if c:
            t = t.replace(c, ' ')
    m = re.search(
        r'(?:с\s+параметр\w*|параметр\w*|добав\w*|включ\w*|постав\w*|'
        r'установи\w*|точность|сопротивление|r\b|c0|c1|q\b|допуск)'
        r'[\s:]*(.+)$',
        t, re.IGNORECASE)
    if not m:
        if re.search(r'\+/-|±|max|min|до\s+\d', t, re.I):
            t2 = re.sub(
                r'(?:созда|сдела|сформир|зарегистр)\w*.*?'
                r'(?:спецификац\w*|спек\w*)\s+\S+',
                ' ', t, flags=re.I)
            t2 = re.sub(
                r'(?:на\s+основ\w+|на\s+баз\w+)\s+\S+',
                ' ', t2, flags=re.I)
            return _split_change_tokens(t2)
        return []
    seg = m.group(0)
    seg = re.split(r'(?:интервал|температур)', seg, flags=re.IGNORECASE)[0]
    return _split_change_tokens(seg)


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

    if 'протокол' in low:
        return None

    if re.search(r'(?:удал|сотр)\w+\s+.*спецификац', low):
        return None

    interval = parse_interval_text(text)
    want_interval_kw = bool(_INTERVAL_KW_RE.search(low))
    want_temp_kw = bool(_TEMP_KW_RE.search(low))

    if interval and (want_interval_kw or want_temp_kw):
        codes = _extract_spc_codes(text)
        spc = None
        m = re.search(
            r'(?:для|спецификац\w*|спек\w*|spc|spec)'
            r'[\s:№#]*([A-Za-zА-Яа-я0-9]+(?:[-–—][A-Za-zА-Яа-я0-9.,]+)*)',
            text, re.IGNORECASE)
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

    if _CREATE_SPEC_RE.search(text):
        base = _extract_base(text)
        codes = _extract_spc_codes(text)
        name = _extract_new_name(text, base, codes)
        if not base and codes:
            if name and len(codes) >= 2:
                for c in codes:
                    if c.casefold() != name.casefold():
                        base = c
                        break
            elif not name and codes:
                base = codes[0]
        if name and base and name.casefold() == base.casefold():
            alt = [c for c in codes if c.casefold() != name.casefold()]
            base = alt[0] if alt else None

        tokens = _extract_create_param_tokens(
            text, consumed=[n for n in (name, base) if n])
        new_params: list = []
        for tok in tokens:
            parsed = parse_norm_assignment(tok)
            if parsed.get('param'):
                if (parsed.get('min') is not None
                        or parsed.get('max') is not None
                        or parsed.get('pm') is not None):
                    new_params.append(parsed)
                else:
                    new_params.append(parsed['param'])
            elif tok:
                new_params.append(tok)

        wait = _extract_wait(text)
        if interval and wait is not None:
            interval['wait'] = wait
        params: dict = {
            'name': name,
            'base': base,
            'new_params': new_params,
        }
        if interval:
            params['interval'] = interval
        if wait is not None:
            params['wait'] = wait
        return {'intent': 'create_spec', 'params': params}

    if _MODIFY_SPEC_RE.search(text) and (
            'спецификац' in low or 'спек' in low or _extract_spc_codes(text)
    ):
        codes = _extract_spc_codes(text)
        spc = codes[0] if codes else None
        if not spc:
            m = _SPC_WORD_RE.search(text)
            if m:
                spc = _clean_token(m.group(1))
        changes_raw = _extract_changes_tail(text, spc)
        changes = []
        for tok in changes_raw:
            parsed = parse_norm_assignment(tok)
            if parsed.get('param'):
                changes.append(parsed)
            elif tok:
                changes.append(tok)
        return {
            'intent': 'modify_spec',
            'params': {'spc': spc, 'changes': changes},
        }

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

    if interval and re.search(r'(?:шаг|step)', low):
        codes = _extract_spc_codes(text)
        return {
            'intent': 'create_temp_interval',
            'params': {
                'spc': codes[-1] if codes else None,
                'interval': interval,
            },
        }

    return None
