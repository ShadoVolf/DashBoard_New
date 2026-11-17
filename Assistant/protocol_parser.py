"""Детерминированный разбор NL-запросов к модулю Протоколы.

Возвращает dict {'intent':..., 'params': {...}} либо None.
LLM не задействован — покрывает 95 % типовых формулировок.
"""
import re

from Archive_View.Archive_Data import parse_numbers_input

_NUM_PATTERN = re.compile(r'[A-ZА-Я]{1,4}\d+[A-ZА-Я]?'
                          r'(?:\s*[-,]\s*[A-ZА-Я]{0,4}\d+[A-ZА-Я]?)*',
                          re.IGNORECASE)
_MSK_PATTERN = re.compile(
    r'(?:мск|msk|мк)[\s:№#]*([A-Za-zА-Яа-я0-9\-]+(?:\s*[A-Za-zА-Яа-я0-9\-]+)?)',
    re.IGNORECASE)
_MEASURE_ID_PATTERN = re.compile(
    r'(?:id[\s\-]?замер\w*|замер\w*\s*(?:id|№)?|measure[_\s]?id)'
    r'[\s:=#]*(\d+)', re.IGNORECASE)
_PROTOKOL_ID_PATTERN = re.compile(
    r'(?:протокол\w*[\s№#]*(?:id\s*)?|id\s*протокол\w*[\s:№#]*)'
    r'(\d+)', re.IGNORECASE)
_ORDER_LOT_PATTERN = re.compile(
    r'заказ\w*[\s:№#]*([A-Za-zА-Яа-я0-9\-/]+)', re.IGNORECASE)
_DATE_PATTERN = re.compile(r'(\d{4}-\d{2}-\d{2})')

def parse(q: str):
    if not q or not q.strip():
        return None
    text = q.strip()
    low = text.lower()

    psi_type = ('ПСИ' if 'пси' in low
                else 'ОТК' if ('отк' in low or 'предъяв' in low)
                else 'ОТК')

    # -------- OPEN --------
    if re.search(r'(?:открой|открыть|запусти|запустить)\s+(?:модуль\s+)?'
                 r'протокол', low):
        msk = _extract_msk(text)
        return {'intent': 'open_protocols', 'params': {'msk': msk}}

    # -------- CREATE --------
    if re.search(r'(?:созда|сдела|сформир|выпусти|напечата\w*\s+протокол)', low):
        msk = _extract_msk(text)
        numbers = _extract_numbers(text, exclude=False)
        exclude = _extract_numbers(text, exclude=True)
        order = _extract_order(text, exclude_from_lot=numbers)
        max_count = _extract_max_count(text)
        params = {'msk_or_spec': msk, 'numbers': numbers or None,
                  'exclude_numbers': exclude or None,
                  'psi_type': psi_type, 'order': order,
                  'max_count': max_count}
        if not (params['msk_or_spec'] or params['numbers']):
            return None
        return {'intent': 'create_protocols', 'params': params}

    # -------- SEND_TO_OTK --------
    if re.search(r'(?:отправ|передай|передать)\w*\s+(?:в\s+)?отк', low):
        pid = _extract_protokol_id(text) or _extract_bare_id(text)
        if not pid:
            return None
        return {'intent': 'send_to_otk', 'params': {'protokol_id': pid}}

    # -------- PRINT --------
    if re.search(r'(?:напечатай|распечатай|печать|принт|pdf|в\s+pdf)', low):
        pid = (_extract_protokol_id(text)
               or _extract_any_id(text)
               or _extract_bare_id(text))
        if not pid:
            return None
        return {'intent': 'print_protocol', 'params': {'protokol_id': pid}}

    # -------- ADD_ORDER (раньше ADD_NUMBERS, но не мешает «добавь номер») --------
    if (re.search(r'заказ', low)
            and re.search(r'(?:добав|внеси|постав|прикреп|сохран|'
                          r'зада|установ)', low)
            and not re.search(r'(?:добав|внеси|включи)\w*\s+номер', low)):
        pid = _extract_protokol_id(text)
        order = _extract_order(text)
        return {'intent': 'add_order',
                'params': {'protokol_id': pid, 'order': order}}

    # -------- DELETE --------
    if re.search(r'(?:удали|удалить|убери|сними|снять)\w*\s+номер', low):
        pid = _extract_protokol_id(text)
        msk = _extract_msk(text)
        numbers = _extract_numbers(text, exclude=False)
        if not numbers:
            return None
        if not (pid or msk):
            return None
        return {'intent': 'delete_numbers',
                'params': {'protokol_id': pid, 'msk': msk,
                           'numbers': numbers}}

    # -------- ADD_NUMBERS --------
    if re.search(r'(?:добав|внеси|включи)\w*\s+номер', low):
        pid = _extract_protokol_id(text)
        numbers = _extract_numbers(text, exclude=False)
        if not (pid and numbers):
            return None
        return {'intent': 'add_numbers',
                'params': {'protokol_id': pid, 'numbers': numbers}}

    # -------- SEARCH (явные глаголы) --------
    if re.search(r'(?:найди|найти|покажи|показать|поищи|список|'
                 r'перечисли|вывести|выведи|list)\w*.*протокол', low):
        msk = _extract_msk(text)
        measure_id = _extract_measure_id(text)
        numbers = _extract_numbers(text, exclude=False)
        pid = _extract_protokol_id(text)
        psitype = _extract_psi_type(low)
        if pid and not (msk or measure_id or numbers):
            return {'intent': 'get_protocol_info',
                    'params': {'protokol_id': pid}}
        return {'intent': 'search_protocols',
                'params': {'msk': msk, 'measure_id': measure_id,
                           'numbers': numbers or None,
                           'psi_type': psitype}}

    # -------- GENERIC: любое упоминание «протокол(ы)» --------
    if 'протокол' in low:
        msk = _extract_msk(text)
        measure_id = _extract_measure_id(text)
        numbers = _extract_numbers(text, exclude=False)
        pid = _extract_protokol_id(text)
        psitype = _extract_psi_type(low)
        if pid and not (msk or measure_id or numbers):
            return {'intent': 'get_protocol_info',
                    'params': {'protokol_id': pid}}
        return {'intent': 'search_protocols',
                'params': {'msk': msk, 'measure_id': measure_id,
                           'numbers': numbers or None,
                           'psi_type': psitype}}

    # -------- BARE ID: одиночное число (после списка или промпта) --------
    stripped = text.strip()
    if re.fullmatch(r'\d{3,}', stripped):
        return {'intent': 'get_protocol_info',
                'params': {'protokol_id': int(stripped)}}

    return None

def _extract_any_id(text):
    """ID по префиксу: 'ID 312494', '№312494', 'no.312494', 'номер 312494'."""
    m = re.search(r'(?:id|№|no\.?|номер)\s*[:=#]?\s*(\d{2,})',
                  text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_bare_id(text, exclude=None):
    """Одиночное число 4+ цифр, не часть МСК (826-130 не матчится)."""
    for m in re.finditer(r'(?<![\d\-])(\d{4,})(?![\d\-])', text):
        val = int(m.group(1))
        if exclude is not None and val == exclude:
            continue
        return val
    return None


def _extract_max_count(text):
    """'не более 20', 'макс 20', 'первые 20', 'ограничить 20 шт'."""
    m = re.search(
        r'(?:не\s+более|макс\w*|максимум|первые|огранич\w*)\s+'
        r'(\d+)\s*(?:шт|штук|номер\w*|резонатор\w*)?',
        text, re.IGNORECASE)
    return int(m.group(1)) if m else None

def _extract_psi_type(low: str):
    """'ПСИ' / 'ОТК' / None из запроса."""
    if re.search(r'\bпси\b', low):
        return 'ПСИ'
    if re.search(r'\bотк\b|предъяв', low):
        return 'ОТК'
    return None
# ---------- extractors ----------
def _extract_msk(text):
    m = _MSK_PATTERN.search(text)
    if not m:
        return None
    val = m.group(1).strip()
    # отсекаем хвостовые служебные слова
    val = re.split(r'\s+(?:с|номерами|номер|исключая|заказ|от)\b',
                   val, flags=re.IGNORECASE)[0]
    return val.strip() or None


def _extract_measure_id(text):
    m = _MEASURE_ID_PATTERN.search(text)
    return int(m.group(1)) if m else None


def _extract_protokol_id(text):
    m = _PROTOKOL_ID_PATTERN.search(text)
    return int(m.group(1)) if m else None


def _extract_numbers(text, exclude=False):
    if exclude:
        seg = re.search(
            r'(?:исключ\w*|без|кроме|за\s+исключением)\s+([^\n.;]+)',
            text, re.IGNORECASE)
        if not seg:
            return []
        body = seg.group(1)
    else:
        seg = re.search(
            r'(?:номер\w*|номерами|с\s+номерами|диапазон\w*)\s*[:\-]?\s*'
            r'([^\n.;]+)', text, re.IGNORECASE)
        if not seg:
            return []
        body = seg.group(1)

    matches = _NUM_PATTERN.findall(body)
    if not matches:
        # fallback: числа через запятую/пробел
        plain = re.findall(r'[\dA-Za-zА-Яа-я\-]{2,}', body)
        matches = [p for p in plain
                   if any(c.isdigit() for c in p) and len(p) >= 3]
    out = []
    for m in matches:
        try:
            expanded = parse_numbers_input(m)
            out.extend(expanded or [m])
        except Exception:
            out.append(m)
    return out


_PREPOSITIONS = frozenset((
    'в', 'во', 'к', 'ко', 'от', 'на', 'до', 'из', 'по', 'и',
    'протокол', 'протоколу', 'протокола', 'протоколе',
    'заказ', 'заказа', 'заказу', 'заказе',
    'номер', 'номера', 'номеру',
))


def _normalize_date(d):
    """YYYY-MM-DD из любого поддерживаемого формата."""
    if not d:
        return None
    s = str(d).strip()
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', s):
        return s
    m = re.fullmatch(r'(\d{2})[.\-/](\d{2})[.\-/](\d{4})', s)
    if m:
        return f'{m.group(3)}-{m.group(2)}-{m.group(1)}'
    return s


def _extract_order(text, exclude_from_lot=None):
    """Извлечь lot/date заказа.

    Требует: lot содержит хотя бы одну цифру, не является предлогом,
    не совпадает с protokol_id, не является датой, не совпадает с
    номером резонатора из exclude_from_lot.

    Возвращает dict {'lot': str|None, 'date': str|None} либо None,
    если в тексте нет слова «заказ». Пустой lot/date не роняет
    парсер — tool _tool_add_order вернёт осмысленный hint.
    """
    if not text or not re.search(r'заказ', text, re.IGNORECASE):
        return None

    exclude_set = set()
    if exclude_from_lot:
        exclude_set = {str(x).strip().upper() for x in exclude_from_lot}

    # --- Дата ---
    date = None
    for pat in (
        r'\b(\d{4}-\d{2}-\d{2})\b',
        r'\b(\d{2}\.\d{2}\.\d{4})\b',
        r'\b(\d{2}[-/]\d{2}[-/]\d{4})\b',
    ):
        dm = re.search(pat, text)
        if dm:
            date = _normalize_date(dm.group(1))
            break

    # --- protokol_id, чтобы не спутать с lot ---
    pid = _extract_protokol_id(text)

    # --- Слова после «заказ» ---
    m = re.search(r'заказ\w*', text, re.IGNORECASE)
    if not m:
        return None
    tail = text[m.end():]

    lot = None
    for w in re.findall(r'[^\s,.;:()]+', tail):
        w_strip = w.strip('.,;:()"\'')
        w_low = w_strip.lower()
        if not w_strip:
            continue
        if w_low in _PREPOSITIONS:
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

def _extract_any_id(text):
    """ID по явному префиксу: 'ID 312628', '№312628', 'no.312628'."""
    m = re.search(r'(?:id|№|no\.?|номер)\s*[:=#]?\s*(\d{2,})',
                  text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def _extract_bare_id(text, exclude=None):
    """Отдельно стоящее число 4+ цифр, не часть МСК (826-130 не матчится)."""
    for m in re.finditer(r'(?<![\d\-])(\d{4,})(?![\d\-])', text):
        val = int(m.group(1))
        if exclude is not None and val == exclude:
            continue
        return val
    return None


def _extract_max_count(text):
    """'не более 20', 'макс 20', 'первые 20', 'ограничить 20 шт'."""
    m = re.search(
        r'(?:не\s+более|макс\w*|максимум|первые|огранич\w*)\s+'
        r'(\d+)\s*(?:шт|штук|номер\w*|резонатор\w*)?',
        text, re.IGNORECASE)
    return int(m.group(1)) if m else None