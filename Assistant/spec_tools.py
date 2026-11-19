"""Инструменты ассистента: спецификации и температурные интервалы.

Возможности:
  * list_specs / get_spec_params — чтение справочника параметров из
    таблицы ``spc_map_table`` (обозначения параметров: Parameter_Name,
    Use, Max, Min, Note, Note_mini);
  * create_spec  — создание спецификации «на основе» существующей
    (+ новые параметры из spc_map_table: включение флага Use и нормы
    Max/Min/T);
  * create_temp_interval — температурный интервал вида
    «-10...+50 step 5(28, 43)»: точки от A до B с шагом Step и
    дополнительными точками Extra; интервал сохраняется как
    температурный профиль (temperatureprofile/profiledata) и может
    быть привязан к спецификации (поле Profile + IntervalName).

Соглашения как в protocol_tools:
  * каждый tool возвращает dict; ошибка — {'error', 'hint'};
  * мутации без confirm=True возвращают {'action': 'dry_run', ...},
    контроллер ставит pending и ждёт «да»/«нет».
"""
from __future__ import annotations

import re
from typing import Optional

from .context import get_ctx, set_pending, peek_pending, pop_pending, is_yes, is_no


# =========================================================================
# Справочник spc_map_table
# =========================================================================
def _fetch_spc_map() -> list[dict]:
    """Строки spc_map_table; при недоступности БД — локальная копия."""
    try:
        from ResonatorGraph import db
        rows = db.fetchall("SELECT * FROM `spc_map_table` ORDER BY `ID`")
        if rows:
            return [dict(r) for r in rows]
    except Exception as e:
        print(f'[spec_tools] spc_map_table из БД недоступна: {e}')
    from .spc_map_fallback import get_spc_map_rows
    return get_spc_map_rows()


def _norm_key(s) -> str:
    t = str(s or '').strip().lower()
    t = t.replace('ё', 'е').replace(',', '.')
    return re.sub(r'\s+', '', t)


def find_param(query: str, spc_map: Optional[list] = None) -> Optional[dict]:
    """Найти строку spc_map_table по имени/обозначению параметра.

    Понимает 'C0', 'С1' (кириллица), 'Fmax', 'Rmax/Rmin',
    'T экстремум min', 'Наклон', 'Монотонность', 'Spur(F1)' и т.п.
    """
    qk = _norm_key(query)
    if not qk:
        return None
    spc_map = spc_map if spc_map is not None else _fetch_spc_map()

    # 1) точное совпадение по основным полям
    fields = ('Parameter_Name', 'Use', 'Note_mini', 'Note', 'Max', 'Min')
    for row in spc_map:
        for f in fields:
            if _norm_key(row.get(f)) == qk:
                return row
    # 2) точное совпадение по любой текстовой колонке
    for row in spc_map:
        for v in row.values():
            if isinstance(v, str) and _norm_key(v) == qk:
                return row
    # 3) подстрока (короткие имена — только начало строки, чтобы F не ловило Fmax)
    candidates = []
    for row in spc_map:
        for f in fields:
            v = _norm_key(row.get(f))
            if v and (v.startswith(qk) if len(qk) <= 3 else qk in v):
                candidates.append(row)
                break
    uniq = {id(r): r for r in candidates}
    if len(uniq) == 1:
        return next(iter(uniq.values()))
    if uniq:
        # наименьшее имя — самое близкое
        return sorted(uniq.values(),
                      key=lambda r: len(str(r.get('Parameter_Name'))))[0]
    return None


def param_columns(row_map: dict) -> dict:
    """Колонки спецификации для строки spc_map_table."""
    return {
        'use_col': (row_map.get('Use') or '').strip(),
        'max_col': (row_map.get('Max') or '').strip(),
        'min_col': (row_map.get('Min') or '').strip(),
        'param':   (row_map.get('Parameter_Name') or '').strip(),
        'note':    (row_map.get('Note') or '').strip(),
        'note_mini': (row_map.get('Note_mini') or '').strip(),
        'code': row_map.get('Code'),
        'round': row_map.get('Round'),
        'order': row_map.get('Order'),
    }


# =========================================================================
# Вспомогательные: температуры / числа
# =========================================================================
_NUM_RE = r'[-+]?\d+(?:[.,]\d+)?'


def _to_float(v) -> Optional[float]:
    if v is None:
        return None
    if isinstance(v, bool):
        return float(v)
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(',', '.')
    if not s or s.lower() == 'no':
        return None
    try:
        return float(s)
    except ValueError:
        return None


def parse_interval_text(text: str) -> Optional[dict]:
    """Разобрать описание интервала.

    Поддерживаемые формы:
      '-10...+50 step 5(28, 43)'
      'от -10 до +50 шагом 5 с точками 28, 43'
      'с -10 по 50 шаг 5 (28,43)'
      '-40..85 шаг 1'
    Возвращает {'a', 'b', 'step', 'extra': [...]} или None.
    """
    if not text:
        return None
    t = text.replace('…', '...').replace('–', '-').replace('—', '-')
    t = t.replace('+', ' +')  # не склеивать знак с предыдущим токеном
    t = re.sub(r'\s+', ' ', t).strip()

    m = re.search(
        rf'(?P<a>{_NUM_RE})\s*(?:\.\.\.+|\.\.|до|по|-)\s*(?P<b>{_NUM_RE})',
        t, re.IGNORECASE)
    if not m:
        return None
    a = _to_float(m.group('a'))
    b = _to_float(m.group('b'))
    if a is None or b is None:
        return None

    step = None
    ms = re.search(rf'(?:шаг\w*|step)[\s:=]*(?P<s>{_NUM_RE})', t, re.IGNORECASE)
    if ms:
        step = _to_float(ms.group('s'))

    extra: list[float] = []
    me = re.search(r'\(([^)]*)\)', t)
    if me:
        for tok in re.split(r'[,;]+', me.group(1)):
            v = _to_float(tok)
            if v is not None:
                extra.append(v)
    if not extra:
        me2 = re.search(
            rf'(?:точк\w*|point\w*)\s*(?:[:=]|\bс\b)?\s*((?:{_NUM_RE}\s*[,;]?\s*)+)',
            t, re.IGNORECASE)
        if me2:
            for tok in re.split(r'[,;]+', me2.group(1)):
                v = _to_float(tok)
                if v is not None:
                    extra.append(v)

    if step is None and not extra:
        return None
    return {'a': a, 'b': b, 'step': step, 'extra': extra}


def build_temperature_points(a: float, b: float,
                             step: Optional[float] = None,
                             extra: Optional[list] = None) -> list[float]:
    """Точки интервала: a..b с шагом step + дополнительные точки extra.

    Порядок границ не важен: всегда идём от min к max.
    Шаг должен быть > 0. Доп. точки (extra) вставляются в сетку
    и сортируются вместе с ней.
    Пример: a=-30, b=60, step=5, extra=[23, 28]
      → [-30, -25, ..., 20, 23, 25, 28, 30, ..., 60]
    """
    lo, hi = (a, b) if a <= b else (b, a)
    pts: list[float] = []
    if step and step > 0:
        n = int(round((hi - lo) / step))
        pts = [round(lo + i * step, 6) for i in range(n + 1)]
        if abs(pts[-1] - hi) > 1e-9:
            pts.append(round(hi, 6))
    else:
        pts = [round(lo, 6), round(hi, 6)]
    for x in extra or []:
        try:
            v = round(float(x), 6)
        except (TypeError, ValueError):
            continue
        if v not in pts:
            pts.append(v)
    pts = sorted(set(pts))
    return [int(p) if float(p).is_integer() else p for p in pts]


def format_interval_name(a: float, b: float,
                         step: Optional[float], extra: list) -> str:
    """'-10...+50 step 5(28, 43)' — каноническое имя интервала."""
    def _fmt(x):
        x = float(x)
        s = f'{int(x)}' if x.is_integer() else f'{x:g}'
        return f'+{s}' if x > 0 else s
    name = f'{_fmt(a)}...{_fmt(b)}'
    if step:
        s = float(step)
        name += f' step {int(s) if s.is_integer() else s:g}'
    if extra:
        parts = []
        for x in extra:
            x = float(x)
            parts.append(f'{int(x)}' if x.is_integer() else f'{x:g}')
        name += '(' + ', '.join(parts) + ')'
    return name


# =========================================================================
# Доступ к контроллеру спецификаций
# =========================================================================
_ctrl_singleton = None


def _get_controller():
    global _ctrl_singleton
    if _ctrl_singleton is None:
        from SpecEditor.logic import SpecEditorController
        _ctrl_singleton = SpecEditorController()
    return _ctrl_singleton


def _resolve_base_spec(name_or_code: str) -> dict:
    """Каноническое имя спецификации через resolve_spec_name (архив)."""
    from .archive_tools import resolve_spec_name
    res = resolve_spec_name(name_or_code)
    if res.get('spc'):
        return {'spc': res['spc'], 'candidates': [], 'error': None,
                'matched': res.get('matched')}
    return res


# =========================================================================
# Tools
# =========================================================================
def _tool_list_specs(params, dpg_):
    search = (params or {}).get('search') or ''
    ctrl = _get_controller()
    try:
        specs = ctrl.list_specs(search)
    except Exception as e:
        return {'error': f'Не удалось получить список спецификаций: {e}'}
    return {'count': len(specs),
            'specs': [{'name': s.get('Name'), 'type': s.get('NameR'),
                       'nominal': s.get('Nominal'),
                       'profile': s.get('Profile')} for s in specs[:200]]}


def _tool_list_spc_params(params, dpg_):
    spc_map = _fetch_spc_map()
    return {'count': len(spc_map),
            'params': [param_columns(r) for r in spc_map]}


def _tool_get_spec_params(params, dpg_):
    """Какие параметры включены в спецификацию (флаги Use из spc_map_table)."""
    name = (params or {}).get('spc') or (params or {}).get('name')
    if not name:
        return {'error': 'Укажите спецификацию',
                'hint': 'Пример: «параметры спецификации РК507-98.415М-220»'}
    resolved = _resolve_base_spec(name)
    spc = resolved.get('spc')
    if not spc:
        return {'error': resolved.get('error') or f'Спецификация {name!r} не найдена',
                'candidates': resolved.get('candidates') or [],
                'hint': resolved.get('hint')}
    ctrl = _get_controller()
    try:
        row = ctrl.load_spec(spc)
    except Exception as e:
        return {'error': f'Спецификация {spc!r} не найдена: {e}'}
    norms = ctrl.get_spc_map_for_row(row)
    return {'spc': spc, 'count': len(norms), 'norms': norms}


def _tool_create_spec(params, dpg_):
    params = dict(params or {})
    name = (params.get('name') or '').strip()
    base = (params.get('base') or '').strip()
    new_params = params.get('new_params') or []
    interval = params.get('interval')          # dict из parse_interval_text
    wait = _to_float(params.get('wait')) or 0.0
    confirm = bool(params.get('confirm'))

    if not name:
        return {'error': 'Нужно имя новой спецификации',
                'hint': 'Пример: «создай спецификацию NEW на основе OLD с параметрами R, C0»'}

    ctrl = _get_controller()
    try:
        all_cols = set(ctrl.columns())
    except Exception as e:
        return {'error': f'БД спецификаций недоступна: {e}'}

    exists = any(str(s.get('Name')).casefold() == name.casefold()
                 for s in ctrl.list_specs())
    if exists:
        return {'error': f'Спецификация «{name}» уже существует'}

    spc_map = _fetch_spc_map()

    # --- базовая спецификация ---
    base_row: dict = {}
    base_resolved = None
    if base:
        resolved = _resolve_base_spec(base)
        base_resolved = resolved.get('spc')
        if not base_resolved:
            return {'error': resolved.get('error') or f'База {base!r} не найдена',
                    'candidates': resolved.get('candidates') or [],
                    'hint': resolved.get('hint')}
        try:
            base_row = ctrl.load_spec(base_resolved)
        except Exception as e:
            return {'error': f'Не удалось прочитать базу {base_resolved!r}: {e}'}

    # --- новые параметры из spc_map_table ---
    updates: dict = {}
    added = []
    unknown = []
    for item in new_params:
        if isinstance(item, dict):
            q = item.get('param') or item.get('name') or ''
            mn = item.get('min', item.get('mn'))
            mx = item.get('max', item.get('mx'))
            tt = item.get('t', item.get('temp'))
        else:
            # строковый вид: "R 10..30" / "R max 30 min 10" / "C0"
            q, mn, mx = str(item), None, None
            m = re.search(rf'^(.+?)\s*(-?[\d.,]+)\s*(?:\.\.\.|—|-|–)\s*'
                          rf'(-?[\d.,]+)\s*$', q)
            if m:
                q, mn, mx = m.group(1).strip(), m.group(2), m.group(3)
            else:
                mmx = re.search(rf'max\s*[:=]?\s*(-?[\d.,]+)', q, re.I)
                mnm = re.search(rf'min\s*[:=]?\s*(-?[\d.,]+)', q, re.I)
                if mmx:
                    mx = mmx.group(1)
                    q = re.sub(rf'max\s*[:=]?\s*-?[\d.,]+', '', q,
                               flags=re.I).strip()
                if mnm:
                    mn = mnm.group(1)
                    q = re.sub(rf'min\s*[:=]?\s*-?[\d.,]+', '', q,
                               flags=re.I).strip()
            tt = None
        row_map = find_param(q, spc_map)
        if not row_map:
            unknown.append(q)
            continue
        c = param_columns(row_map)
        if c['use_col'] and c['use_col'] in all_cols:
            updates[c['use_col']] = 1
        for col, val in ((c['max_col'], mx), (c['min_col'], mn)):
            fv = _to_float(val)
            if col and col in all_cols and fv is not None:
                updates[col] = fv
        added.append({
            'param': c['param'], 'note': c['note'] or c['note_mini'],
            'use_col': c['use_col'], 'max_col': c['max_col'],
            'min_col': c['min_col'],
            'max': _to_float(mx), 'min': _to_float(mn),
        })

    if unknown:
        return {'error': f'Параметры не найдены в spc_map_table: {", ".join(unknown)}',
                'hint': 'Обозначения параметров — колонки Parameter_Name / Use / '
                        'Note_mini таблицы spc_map_table. Список: «параметры spc»'}

    # --- температурный интервал → профиль ---
    interval_info = None
    if interval:
        a = _to_float(interval.get('a'))
        b = _to_float(interval.get('b'))
        step = _to_float(interval.get('step'))
        extra = [_to_float(x) for x in (interval.get('extra') or [])]
        extra = [x for x in extra if x is not None]
        if a is None or b is None:
            return {'error': 'Неполный температурный интервал: нужны границы'}
        if step is None and not extra:
            return {'error': 'Нужен шаг или дополнительные точки интервала'}
        points = build_temperature_points(a, b, step, extra)
        it_name = (interval.get('name') or
                   format_interval_name(a, b, step, extra)).strip()
        interval_info = {'name': it_name, 'points': points, 'wait': wait}
        prof_name = interval.get('profile_name') or it_name
        updates['Profile'] = prof_name
        if 'IntervalName' in all_cols:
            updates['IntervalName'] = it_name

    summary = {
        'action': 'dry_run',
        'name': name,
        'base': base_resolved,
        'added_params': added,
        'updates': {k: v for k, v in updates.items()},
        'interval': interval_info,
        'note': 'Это preview. Для создания повтори с confirm=true.',
    }
    if not confirm:
        return summary

    # ---- APPLY ----
    try:
        ctrl.create_spec(name, base_from=base_resolved)
        if updates:
            ctrl.save_spec(name, updates)
    except Exception as e:
        return {'error': f'Ошибка создания спецификации: {e}'}

    result = {'action': 'created_spec', 'name': name, 'base': base_resolved,
              'added_params': added}

    if interval_info:
        ir = _apply_interval_to_spec({'spc': name, 'interval': interval_info,
                                      'confirm': True}, dpg_)
        result['interval'] = ir.get('interval') or ir
    return result


def _find_profile_by_temperatures(points: list) -> Optional[str]:
    """Существующий профиль с точно таким же списком температур."""
    try:
        from ResonatorGraph import db
        temps_str = ' '.join(str(p) for p in points)
        row = db.fetchone(
            "SELECT `Name` FROM `temperatureprofile` "
            "WHERE `Temperatures` = :t LIMIT 1", t=temps_str)
        return row['Name'] if row else None
    except Exception:
        return None


def _apply_interval_to_spec(params, dpg_):
    """Создать температурный профиль-интервал; опционально привязать к спецификации.

    Без ``spc`` — просто создаёт профиль в temperatureprofile / profiledata.
    С ``spc`` — ещё и прописывает Profile / IntervalName в спецификации.
    """
    params = dict(params or {})
    spc_raw = params.get('spc') or params.get('name')
    it = params.get('interval') or {}
    confirm = bool(params.get('confirm'))

    # границы можно передать плоско или внутри interval
    a = _to_float(it.get('a') if it.get('a') is not None else params.get('a'))
    b = _to_float(it.get('b') if it.get('b') is not None else params.get('b'))
    step = _to_float(it.get('step') if it.get('step') is not None else params.get('step'))
    extra_raw = it.get('extra') if it.get('extra') is not None else params.get('extra')
    extra = [_to_float(x) for x in (extra_raw or [])]
    extra = [x for x in extra if x is not None]

    if a is None or b is None or (step is None and not extra):
        return {
            'error': 'Нужны границы, шаг (или точки) интервала',
            'hint': 'Формат: «создай температурный интервал от -30 до +60 '
                    'шагом 5 с точками 23,28» или «-10...+50 step 5(28, 43)»',
        }

    points = build_temperature_points(a, b, step, extra)
    it_name = (it.get('name') or format_interval_name(a, b, step, extra)).strip()
    wait = _to_float(
        it.get('wait') if it.get('wait') is not None else params.get('wait')
    ) or 0.0
    profile_name = (it.get('profile_name') or params.get('profile_name')
                    or it_name)

    # --- опциональная привязка к спецификации ---
    spc = None
    if spc_raw:
        resolved = _resolve_base_spec(str(spc_raw))
        spc = resolved.get('spc')
        if not spc:
            return {
                'error': resolved.get('error') or f'Спецификация {spc_raw!r} не найдена',
                'candidates': resolved.get('candidates') or [],
                'hint': resolved.get('hint'),
            }

    existing_profile = _find_profile_by_temperatures(points)

    preview = {
        'action': 'dry_run',
        'spc': spc,
        'interval': {
            'name': it_name,
            'points': points,
            'wait': wait,
            'profile_name': profile_name,
        },
        'existing_profile': existing_profile,
        'note': 'Это preview. Для применения ответьте «да».',
    }
    if not confirm:
        return preview

    # ---- APPLY: создать профиль (если нет такого же) ----
    created_profile = False
    target_profile = existing_profile or profile_name
    if not existing_profile:
        try:
            from PSI_Specification.Temperature_profile.Temp_profile_data import (
                save_profile,
            )
            ok = save_profile(
                profile_name,
                [(p, wait) for p in points],
                code='',
                interval_name=it_name,
            )
            if not ok:
                return {'error': f'Не удалось создать профиль «{profile_name}»'}
            created_profile = True
        except Exception as e:
            return {'error': f'Ошибка создания профиля: {e}'}

    # ---- назначить спецификации (если указана) ----
    if spc:
        try:
            ctrl = _get_controller()
            cols = set(ctrl.columns())
            upd = {}
            if 'Profile' in cols:
                upd['Profile'] = target_profile
            if 'IntervalName' in cols:
                upd['IntervalName'] = it_name
            if upd:
                ctrl.save_spec(spc, upd)
        except Exception as e:
            return {
                'error': f'Профиль создан, но спецификацию не обновил: {e}',
                'interval': {
                    'name': it_name,
                    'profile': target_profile,
                    'points_count': len(points),
                },
            }

    return {
        'action': 'interval_created',
        'spc': spc,
        'interval': {
            'name': it_name,
            'profile': target_profile,
            'created_profile': created_profile,
            'points': points,
            'points_count': len(points),
            'wait': wait,
        },
    }


# =========================================================================
# Реестр / execute / форматирование
# =========================================================================
_TOOLS = {
    'list_specs':       _tool_list_specs,
    'list_spc_params':  _tool_list_spc_params,
    'get_spec_params':  _tool_get_spec_params,
    'create_spec':      _tool_create_spec,
    'create_temp_interval': _apply_interval_to_spec,
}


def execute(name: str, params: dict, dpg_) -> dict:
    fn = _TOOLS.get(name)
    if not fn:
        return {'error': f'Неизвестный инструмент спецификаций: {name}'}
    try:
        return fn(params or {}, dpg_)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}


def _fmt_num(x) -> str:
    v = _to_float(x)
    if v is None:
        return str(x)
    return f'{int(v)}' if float(v).is_integer() else f'{v:g}'


def format_result(name: str, res: dict) -> str:
    if not isinstance(res, dict):
        return f'[Spec] {res}'
    if res.get('error'):
        msg = f"[ERR] Спецификации: {res['error']}"
        if res.get('hint'):
            msg += f'\n  → {res["hint"]}'
        cands = res.get('candidates') or []
        if cands:
            msg += '\n  Варианты: ' + ', '.join(str(c) for c in cands[:10])
        return msg

    action = res.get('action')

    if action == 'dry_run':
        lines = ['[PREVIEW] ']
        if name == 'create_spec' or 'added_params' in res:
            lines[0] = (f'[PREVIEW] Создам спецификацию '
                        f'«{res.get("name")}»'
                        + (f' на основе «{res.get("base")}»'
                           if res.get('base') else ' (пустую)') + ':')
            for p in res.get('added_params') or []:
                seg = f'  + {p["param"]} ({p.get("note") or ""})'
                if p.get('min') is not None or p.get('max') is not None:
                    seg += (f': {_fmt_num(p.get("min"))} … '
                            f'{_fmt_num(p.get("max"))}')
                lines.append(seg)
            it = res.get('interval')
            if it:
                pts = it.get('points') or []
                lines.append(f'  Интервал: {it["name"]} '
                             f'({len(pts)} точек: '
                             f'{pts[0]} … {pts[-1]})'
                             + (f', выдержка {it.get("wait")} мин'
                                if it.get('wait') else ''))
        else:
            it = res.get('interval') or {}
            pts = it.get('points') or []
            spc = res.get('spc')
            head = (f'[PREVIEW] Интервал «{it.get("name")}»'
                    + (f' для спецификации «{spc}»' if spc else '')
                    + ':')
            lines = [
                head,
                f'  Точки ({len(pts)}): '
                + ', '.join(str(p) for p in pts[:40])
                + (' …' if len(pts) > 40 else ''),
            ]
            if res.get('existing_profile'):
                lines.append(f'  Такой профиль уже есть: '
                             f'«{res["existing_profile"]}» — переиспользую.')
            elif it.get('profile_name'):
                lines.append(f'  Создам профиль «{it["profile_name"]}».')
        lines.append('Ответьте «да» или «нет».')
        return '\n'.join(lines)

    if action == 'created_spec':
        lines = [f'[OK] Создана спецификация «{res.get("name")}»'
                 + (f' (копия «{res.get("base")}»)' if res.get('base') else '')]
        for p in res.get('added_params') or []:
            lines.append(f'  + {p["param"]} ({p.get("note") or ""})')
        it = res.get('interval')
        if isinstance(it, dict):
            if it.get('error'):
                lines.append(f'  [!] Интервал: {it["error"]}')
            else:
                ii = it.get('interval') or it
                lines.append(
                    f'  Интервал «{ii.get("name")}»: '
                    f'{ii.get("points_count", len(ii.get("points") or []))} '
                    f'точек, профиль «{ii.get("profile")}»')
        return '\n'.join(lines)

    if action == 'interval_created':
        ii = res.get('interval') or {}
        verb = 'создан' if ii.get('created_profile') else 'использован существующий'
        spc = res.get('spc')
        tail = f' для «{spc}»' if spc else ''
        return (f'[OK] Интервал «{ii.get("name")}»{tail}: '
                f'{ii.get("points_count")} точек, профиль '
                f'«{ii.get("profile")}» ({verb})')

    if name == 'list_specs':
        specs = res.get('specs') or []
        head = ', '.join(str(s.get('name')) for s in specs[:20])
        more = f' … (+{len(specs) - 20})' if len(specs) > 20 else ''
        return f'[OK] Спецификаций: {res.get("count", 0)}\n  {head}{more}'

    if name == 'list_spc_params':
        lines = [f'[INFO] Параметры spc_map_table ({res.get("count", 0)}):']
        for p in res.get('params') or []:
            lines.append(
                f'  {p["param"]:<18} флаг={p["use_col"]:<12} '
                f'max={p["max_col"]:<14} min={p["min_col"]:<14} '
                f'{p["note"]}')
        return '\n'.join(lines)

    if name == 'get_spec_params':
        lines = [f'[INFO] Параметры спецификации «{res.get("spc")}» '
                 f'({res.get("count", 0)}):']
        for nrm in res.get('norms') or []:
            lines.append(
                f'  {nrm.get("Parameter")}: '
                f'min={_fmt_num(nrm.get("Min"))} '
                f'max={_fmt_num(nrm.get("Max"))}')
        return '\n'.join(lines)

    return f'[OK] {name}: {str(res)[:300]}'


# =========================================================================
# Pending-ответы («да»/«нет» для dry_run этих инструментов)
# =========================================================================
def handle_pending_reply(reply: str, dpg_):
    pending = peek_pending()
    if not pending or not str(pending.get('kind', '')).startswith('confirm_spec'):
        return None
    payload = pending['payload']
    tool = payload.get('tool')
    if tool not in _TOOLS:
        return None
    if is_yes(reply):
        pop_pending()
        p = dict(payload.get('params') or {})
        p['confirm'] = True
        return execute(tool, p, dpg_)
    if is_no(reply):
        pop_pending()
        return {'action': 'cancelled'}
    return {'error': 'Ответьте «да» или «нет» '
                     '(или введите новый запрос для отмены)'}
