"""Инструменты ассистента: спецификации и температурные интервалы.

Возможности:
  * list_specs / get_spec_params
  * create_spec — на основе + параметры
  * modify_spec — изменить нормы/допуски
  * create_temp_interval

Мутации через SpecEditorController (specification_log).
Удаление через ассистента запрещено.
"""
from __future__ import annotations

import re
from typing import Optional

from .context import get_ctx, set_pending, peek_pending, pop_pending, is_yes, is_no


def _fetch_spc_map() -> list[dict]:
    try:
        from ResonatorGraph import db
        rows = db.fetchall("SELECT * FROM `spc_map_table` ORDER BY `ID`")
        if rows:
            return [dict(r) for r in rows]
    except Exception as e:
        print(f'[spec_tools] spc_map_table: {e}')
    from .spc_map_fallback import get_spc_map_rows
    return get_spc_map_rows()


def _norm_key(s) -> str:
    t = str(s or '').strip().lower().replace('ё', 'е').replace(',', '.')
    return re.sub(r'\s+', '', t)


def find_param(query: str, spc_map: Optional[list] = None) -> Optional[dict]:
    qk = _norm_key(query)
    if not qk:
        return None
    spc_map = spc_map if spc_map is not None else _fetch_spc_map()
    fields = ('Parameter_Name', 'Use', 'Note_mini', 'Note', 'Max', 'Min')
    for row in spc_map:
        for f in fields:
            if _norm_key(row.get(f)) == qk:
                return row
    for row in spc_map:
        for v in row.values():
            if isinstance(v, str) and _norm_key(v) == qk:
                return row
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
        return sorted(uniq.values(), key=lambda r: len(str(r.get('Parameter_Name'))))[0]
    return None


def param_columns(row_map: dict) -> dict:
    return {
        'use_col': (row_map.get('Use') or '').strip(),
        'max_col': (row_map.get('Max') or '').strip(),
        'min_col': (row_map.get('Min') or '').strip(),
        'param': (row_map.get('Parameter_Name') or '').strip(),
        'note': (row_map.get('Note') or '').strip(),
        'note_mini': (row_map.get('Note_mini') or '').strip(),
    }


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


_PARAM_ALIASES = {
    'точностьнастройки': 'F', 'точность': 'F', 'fnastr': 'F',
    'сопротивление': 'R', 'добротность': 'Q',
    'статическаяемкость': 'C0', 'динамическаяемкость': 'C1',
    'наклон': 'Slope', 'монотонность': 'Mono',
}


def _resolve_alias(query: str) -> str:
    qk = _norm_key(query)
    if qk in _PARAM_ALIASES:
        return _PARAM_ALIASES[qk]
    for alias, canon in _PARAM_ALIASES.items():
        if alias in qk or qk in alias:
            return canon
    return query


def parse_norm_assignment(text: str) -> dict:
    raw = (text or '').strip()
    out = {'param': None, 'min': None, 'max': None, 'pm': None, 't': None, 'raw': raw}
    if not raw:
        return out
    t = raw.replace('±', '+/-').replace('–', '-').replace('—', '-')
    t = re.sub(r'\s+', ' ', t).strip()
    m_pm = re.search(rf'(?:=)?\s*\+/-\s*(?P<pm>{_NUM_RE})', t, re.I)
    if m_pm:
        pm = _to_float(m_pm.group('pm'))
        if pm is not None:
            pm = abs(pm)
            out['pm'], out['min'], out['max'] = pm, -pm, pm
            t = (t[:m_pm.start()] + ' ' + t[m_pm.end():]).strip()
    m_range = re.search(
        rf'(?:от\s*)?(?P<a>{_NUM_RE})\s*(?:до|по|\.\.\.?|-)\s*(?P<b>{_NUM_RE})',
        t, re.I)
    if m_range and out['pm'] is None:
        a, b = _to_float(m_range.group('a')), _to_float(m_range.group('b'))
        if a is not None and b is not None:
            out['min'], out['max'] = min(a, b), max(a, b)
            t = (t[:m_range.start()] + ' ' + t[m_range.end():]).strip()
    mmx = re.search(rf'(?:max|макс\w*)\s*[:=]?\s*(?P<v>{_NUM_RE})', t, re.I)
    mnm = re.search(rf'(?:min|мин\w*)\s*[:=]?\s*(?P<v>{_NUM_RE})', t, re.I)
    if mmx:
        out['max'] = _to_float(mmx.group('v'))
        t = re.sub(rf'(?:max|макс\w*)\s*[:=]?\s*{_NUM_RE}', ' ', t, flags=re.I)
    if mnm:
        out['min'] = _to_float(mnm.group('v'))
        t = re.sub(rf'(?:min|мин\w*)\s*[:=]?\s*{_NUM_RE}', ' ', t, flags=re.I)
    m_to = re.search(rf'(?:до|не\s+более|<=|≤)\s*(?P<v>{_NUM_RE})', t, re.I)
    if m_to and out['max'] is None:
        out['max'] = _to_float(m_to.group('v'))
        t = (t[:m_to.start()] + ' ' + t[m_to.end():]).strip()
    t = re.sub(r'[:=]+', ' ', t)
    t = re.sub(
        r'\b(?:установи|поставь|задай|измен\w*|норм\w*|параметр\w*|значение)\b',
        ' ', t, flags=re.I)
    t = re.sub(r'\s+', ' ', t).strip(' ,;')
    if t:
        out['param'] = t
    return out


def parse_interval_text(text: str) -> Optional[dict]:
    if not text:
        return None
    t = text.replace('…', '...').replace('–', '-').replace('—', '-')
    t = t.replace('+', ' +')
    t = re.sub(r'\s+', ' ', t).strip()
    m = re.search(
        rf'(?P<a>{_NUM_RE})\s*(?:\.\.\.+|\.\.|до|по|-)\s*(?P<b>{_NUM_RE})',
        t, re.I)
    if not m:
        return None
    a, b = _to_float(m.group('a')), _to_float(m.group('b'))
    if a is None or b is None:
        return None
    step = None
    ms = re.search(rf'(?:шаг\w*|step)[\s:=]*(?P<s>{_NUM_RE})', t, re.I)
    if ms:
        step = _to_float(ms.group('s'))
    extra = []
    me = re.search(r'\(([^)]*)\)', t)
    if me:
        for tok in re.split(r'[,;]+', me.group(1)):
            v = _to_float(tok)
            if v is not None:
                extra.append(v)
    if not extra:
        me2 = re.search(
            rf'(?:точк\w*|point\w*)\s*(?::=|\bс\b)?\s*((?:{_NUM_RE}\s*[,;]?\s*)+)',
            t, re.I)
        if me2:
            for tok in re.split(r'[,;]+', me2.group(1)):
                v = _to_float(tok)
                if v is not None:
                    extra.append(v)
    if step is None and not extra:
        return None
    return {'a': a, 'b': b, 'step': step, 'extra': extra}


def build_temperature_points(a, b, step=None, extra=None):
    lo, hi = (a, b) if a <= b else (b, a)
    pts = []
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


def format_interval_name(a, b, step, extra):
    def _fmt(x):
        x = float(x)
        s = f'{int(x)}' if x.is_integer() else f'{x:g}'
        return f'+{s}' if x > 0 else s
    name = f'{_fmt(a)}...{_fmt(b)}'
    if step:
        s = float(step)
        name += f' step {int(s) if s.is_integer() else s:g}'
    if extra:
        parts = [f'{int(float(x))}' if float(x).is_integer() else f'{float(x):g}' for x in extra]
        name += '(' + ', '.join(parts) + ')'
    return name


_ctrl_singleton = None


def _get_controller():
    global _ctrl_singleton
    if _ctrl_singleton is None:
        from SpecEditor.logic import SpecEditorController
        _ctrl_singleton = SpecEditorController()
    return _ctrl_singleton


def _normalize_spec_token(s: str) -> str:
    t = (s or '').strip()
    trans = str.maketrans({'М': 'M', 'м': 'M', 'К': 'K', 'к': 'K', ',': '.', '–': '-', '—': '-'})
    return t.translate(trans)


def _resolve_base_spec(name_or_code: str) -> dict:
    raw = (name_or_code or '').strip()
    if not raw:
        return {'spc': None, 'candidates': [], 'error': 'Пустое имя'}
    norm = _normalize_spec_token(raw)
    from .archive_tools import resolve_spec_name
    res = {'spc': None, 'candidates': [], 'error': f'Не найдена {raw!r}'}
    for candidate in (raw, norm):
        r = resolve_spec_name(candidate)
        if r.get('spc'):
            return {'spc': r['spc'], 'candidates': [], 'error': None}
        res = r
    try:
        ctrl = _get_controller()
        target = _norm_key(norm)
        hits = []
        for s in ctrl.list_specs():
            name = str(s.get('Name') or '')
            if _norm_key(_normalize_spec_token(name)) == target:
                return {'spc': name, 'candidates': [], 'error': None}
            if target and target in _norm_key(_normalize_spec_token(name)):
                hits.append(name)
        if len(hits) == 1:
            return {'spc': hits[0], 'candidates': [], 'error': None}
        if hits:
            return {'spc': None, 'candidates': hits[:15], 'error': f'Неоднозначно {raw!r}'}
    except Exception as e:
        print(f'[spec_tools] resolve fallback: {e}')
    return res


def _tool_list_specs(params, dpg_):
    search = (params or {}).get('search') or ''
    ctrl = _get_controller()
    try:
        specs = ctrl.list_specs(search)
    except Exception as e:
        return {'error': f'Список: {e}'}
    return {'count': len(specs), 'specs': [{'name': s.get('Name'), 'type': s.get('NameR'),
              'nominal': s.get('Nominal'), 'profile': s.get('Profile')} for s in specs[:200]]}


def _tool_list_spc_params(params, dpg_):
    return {'count': len(_fetch_spc_map()), 'params': [param_columns(r) for r in _fetch_spc_map()]}


def _tool_get_spec_params(params, dpg_):
    name = (params or {}).get('spc') or (params or {}).get('name')
    if not name:
        return {'error': 'Укажите спецификацию'}
    resolved = _resolve_base_spec(name)
    spc = resolved.get('spc')
    if not spc:
        return {'error': resolved.get('error') or 'не найдена', 'candidates': resolved.get('candidates') or []}
    ctrl = _get_controller()
    try:
        row = ctrl.load_spec(spc)
    except Exception as e:
        return {'error': str(e)}
    return {'spc': spc, 'count': len(ctrl.get_spc_map_for_row(row)), 'norms': ctrl.get_spc_map_for_row(row)}


def _apply_param_item(item, all_cols, spc_map):
    if isinstance(item, dict) and item.get('param'):
        parsed = item
    else:
        parsed = parse_norm_assignment(str(item))
    q = parsed.get('param') or ''
    mn, mx, pm = parsed.get('min'), parsed.get('max'), parsed.get('pm')
    if pm is not None and mn is None and mx is None:
        mn, mx = -abs(pm), abs(pm)
    if not q:
        return {}, None, 'пустой параметр'
    canon = _resolve_alias(q)
    row_map = find_param(canon, spc_map) or find_param(q, spc_map)
    if not row_map:
        return {}, None, f'не найден {q!r}'
    c = param_columns(row_map)
    upd = {}
    info = {'param': c['param'], 'note': c['note'] or c['note_mini'], 'min': mn, 'max': mx, 'pm': pm,
            'use_col': c['use_col'], 'max_col': c['max_col'], 'min_col': c['min_col']}
    if c['use_col'] and c['use_col'] in all_cols:
        upd[c['use_col']] = 1
    if c['max_col'] and c['max_col'] in all_cols and mx is not None:
        upd[c['max_col']] = mx
    if c['min_col'] and c['min_col'] in all_cols and mn is not None:
        upd[c['min_col']] = mn
    if pm is not None and c['param'] in ('F', 'f_corr') and 'DopuskF' in all_cols:
        upd['DopuskF'] = abs(pm)
        info['dopusk'] = abs(pm)
    return upd, info, None


def _tool_create_spec(params, dpg_):
    params = dict(params or {})
    name = _normalize_spec_token((params.get('name') or '').strip())
    base = (params.get('base') or '').strip()
    new_params = params.get('new_params') or []
    interval = params.get('interval')
    wait = _to_float(params.get('wait')) or 0.0
    confirm = bool(params.get('confirm'))
    if not name:
        return {'error': 'Нужно имя новой спецификации'}
    ctrl = _get_controller()
    try:
        all_cols = set(ctrl.columns())
    except Exception as e:
        return {'error': f'БД: {e}'}
    if any(str(s.get('Name')).casefold() == name.casefold() for s in ctrl.list_specs()):
        return {'error': f'«{name}» уже существует'}
    base_resolved = None
    if base:
        resolved = _resolve_base_spec(base)
        base_resolved = resolved.get('spc')
        if not base_resolved:
            return {'error': resolved.get('error') or f'База {base!r} не найдена',
                    'candidates': resolved.get('candidates') or []}
    spc_map = _fetch_spc_map()
    updates, added, errors = {}, [], []
    for item in new_params:
        upd, info, err = _apply_param_item(item, all_cols, spc_map)
        if err:
            errors.append(err)
            continue
        updates.update(upd)
        if info:
            added.append(info)
    if errors:
        return {'error': '; '.join(errors)}
    interval_info = None
    if interval:
        a, b = _to_float(interval.get('a')), _to_float(interval.get('b'))
        step = _to_float(interval.get('step'))
        extra = [x for x in (_to_float(x) for x in (interval.get('extra') or [])) if x is not None]
        if a is None or b is None or (step is None and not extra):
            return {'error': 'Неполный интервал'}
        points = build_temperature_points(a, b, step, extra)
        it_name = (interval.get('name') or format_interval_name(a, b, step, extra)).strip()
        interval_info = {'name': it_name, 'points': points, 'wait': wait}
        updates['Profile'] = interval.get('profile_name') or it_name
        if 'IntervalName' in all_cols:
            updates['IntervalName'] = it_name
    if not confirm:
        return {'action': 'dry_run', 'name': name, 'base': base_resolved,
                'added_params': added, 'updates': dict(updates), 'interval': interval_info,
                'note': 'Preview. Ответьте «да».'}
    try:
        ctrl.create_spec(name, base_from=base_resolved)
        if updates:
            ctrl.save_spec(name, updates)
    except Exception as e:
        return {'error': f'Создание: {e}'}
    result = {'action': 'created_spec', 'name': name, 'base': base_resolved, 'added_params': added}
    if interval_info:
        ir = _apply_interval_to_spec({'spc': name, 'interval': interval_info, 'confirm': True}, dpg_)
        result['interval'] = ir.get('interval') or ir
    return result


def _tool_modify_spec(params, dpg_):
    params = dict(params or {})
    spc_raw = (params.get('spc') or params.get('name') or '').strip()
    changes = params.get('changes') or []
    confirm = bool(params.get('confirm'))
    if not spc_raw:
        return {'error': 'Укажите спецификацию',
                'hint': '«измени в спецификации NAME точность настройки =+/- 7»'}
    if not changes:
        return {'error': 'Не указаны изменения'}
    resolved = _resolve_base_spec(spc_raw)
    spc = resolved.get('spc')
    if not spc:
        return {'error': resolved.get('error') or f'Не найдена {spc_raw!r}',
                'candidates': resolved.get('candidates') or []}
    ctrl = _get_controller()
    try:
        all_cols = set(ctrl.columns())
        ctrl.load_spec(spc)
    except Exception as e:
        return {'error': f'Не открыть {spc!r}: {e}'}
    spc_map = _fetch_spc_map()
    updates, added, errors = {}, [], []
    for item in changes:
        upd, info, err = _apply_param_item(item, all_cols, spc_map)
        if err:
            errors.append(err)
            continue
        updates.update(upd)
        if info:
            added.append(info)
    if errors:
        return {'error': '; '.join(errors)}
    if not updates:
        return {'error': 'Нечего менять'}
    if not confirm:
        return {'action': 'dry_run', 'spc': spc, 'changes': added, 'updates': dict(updates),
                'note': 'Preview. Ответьте «да».'}
    try:
        ctrl.save_spec(spc, updates)
    except Exception as e:
        return {'error': f'Сохранение: {e}'}
    return {'action': 'modified_spec', 'spc': spc, 'changes': added, 'updates': updates}


def _find_profile_by_temperatures(points):
    try:
        from ResonatorGraph import db
        temps_str = ' '.join(str(p) for p in points)
        row = db.fetchone("SELECT `Name` FROM `temperatureprofile` WHERE `Temperatures` = :t LIMIT 1", t=temps_str)
        return row['Name'] if row else None
    except Exception:
        return None


def _apply_interval_to_spec(params, dpg_):
    params = dict(params or {})
    spc_raw = params.get('spc') or params.get('name')
    it = params.get('interval') or {}
    confirm = bool(params.get('confirm'))
    a = _to_float(it.get('a') if it.get('a') is not None else params.get('a'))
    b = _to_float(it.get('b') if it.get('b') is not None else params.get('b'))
    step = _to_float(it.get('step') if it.get('step') is not None else params.get('step'))
    extra_raw = it.get('extra') if it.get('extra') is not None else params.get('extra')
    extra = [x for x in (_to_float(x) for x in (extra_raw or [])) if x is not None]
    if a is None or b is None or (step is None and not extra):
        return {'error': 'Нужны границы и шаг/точки',
                'hint': '«создай температурный интервал от -30 до +60 шагом 5 с точками 23,28»'}
    points = build_temperature_points(a, b, step, extra)
    it_name = (it.get('name') or format_interval_name(a, b, step, extra)).strip()
    wait = _to_float(it.get('wait') if it.get('wait') is not None else params.get('wait')) or 0.0
    profile_name = it.get('profile_name') or params.get('profile_name') or it_name
    spc = None
    if spc_raw:
        resolved = _resolve_base_spec(str(spc_raw))
        spc = resolved.get('spc')
        if not spc:
            return {'error': resolved.get('error') or f'Не найдена {spc_raw!r}',
                    'candidates': resolved.get('candidates') or []}
    existing = _find_profile_by_temperatures(points)
    if not confirm:
        return {'action': 'dry_run', 'spc': spc,
                'interval': {'name': it_name, 'points': points, 'wait': wait, 'profile_name': profile_name},
                'existing_profile': existing, 'note': 'Preview. Ответьте «да».'}
    target, created = existing, False
    if not target:
        try:
            from Temperature_Measure.Temp_profile_data import save_profile
            try:
                save_profile(profile_name, points, wait=wait)
            except TypeError:
                save_profile(profile_name, points)
            target, created = profile_name, True
        except Exception as e:
            return {'error': f'Профиль: {e}'}
    if spc:
        try:
            ctrl = _get_controller()
            cols = set(ctrl.columns())
            upd = {}
            if 'Profile' in cols:
                upd['Profile'] = target
            if 'IntervalName' in cols:
                upd['IntervalName'] = it_name
            if upd:
                ctrl.save_spec(spc, upd)
        except Exception as e:
            return {'error': f'Профиль ок, spec нет: {e}',
                    'interval': {'name': it_name, 'profile': target, 'points_count': len(points)}}
    return {'action': 'interval_created', 'spc': spc,
            'interval': {'name': it_name, 'profile': target, 'created_profile': created,
                         'points': points, 'points_count': len(points), 'wait': wait}}


_TOOLS = {
    'list_specs': _tool_list_specs,
    'list_spc_params': _tool_list_spc_params,
    'get_spec_params': _tool_get_spec_params,
    'create_spec': _tool_create_spec,
    'modify_spec': _tool_modify_spec,
    'create_temp_interval': _apply_interval_to_spec,
}


def execute(name, params, dpg_):
    fn = _TOOLS.get(name)
    if not fn:
        return {'error': f'Неизвестный tool: {name}'}
    try:
        return fn(params or {}, dpg_)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}


def handle_pending_reply(reply, dpg_):
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
    return {'error': 'Ответьте «да» или «нет»'}


def format_result(name, res):
    if not isinstance(res, dict):
        return f'[Spec] {res}'
    if res.get('error'):
        msg = f"[ERR] Спецификации: {res['error']}"
        if res.get('hint'):
            msg += f"\n  → {res['hint']}"
        if res.get('candidates'):
            msg += '\n  Варианты: ' + ', '.join(str(c) for c in res['candidates'][:10])
        return msg
    action = res.get('action')
    if action == 'dry_run':
        if res.get('spc') and 'changes' in res:
            lines = [f"[PREVIEW] Изменю «{res.get('spc')}»:"]
            for p in res.get('changes') or []:
                seg = f"  • {p.get('param') or '?'}"
                if p.get('pm') is not None:
                    seg += f" ±{p['pm']}"
                else:
                    if p.get('min') is not None:
                        seg += f" min={p['min']}"
                    if p.get('max') is not None:
                        seg += f" max={p['max']}"
                lines.append(seg)
            lines.append('Подтвердите: «да» / «нет»')
            return '\n'.join(lines)
        if 'added_params' in res or name == 'create_spec':
            lines = [f"[PREVIEW] Создам «{res.get('name')}»" + (f" на основе «{res.get('base')}»" if res.get('base') else '') + ':']
            for p in res.get('added_params') or []:
                seg = f"  + {p.get('param') or '?'}"
                if p.get('pm') is not None:
                    seg += f" ±{p['pm']}"
                lines.append(seg)
            lines.append('Подтвердите: «да» / «нет»')
            return '\n'.join(lines)
        if res.get('interval'):
            it = res['interval']
            pts = it.get('points') or []
            lines = [f"[PREVIEW] Интервал «{it.get('name')}»: {len(pts)} точек",
                     f"  {pts[:8]}{'…' if len(pts) > 8 else ''}"]
            if res.get('spc'):
                lines.append(f"  для: {res['spc']}")
            lines.append('Подтвердите: «да» / «нет»')
            return '\n'.join(lines)
        return f"[PREVIEW] {res.get('note') or res}"
    if action == 'created_spec':
        return f"[OK] Создана «{res.get('name')}»" + (f" (база: {res['base']})" if res.get('base') else '')
    if action == 'modified_spec':
        return f"[OK] «{res.get('spc')}» изменена ({len(res.get('updates') or {})} полей)"
    if action == 'interval_created':
        it = res.get('interval') or {}
        msg = f"[OK] Интервал «{it.get('name')}»: профиль {it.get('profile')}, точек {it.get('points_count')}"
        if res.get('spc'):
            msg += f", к {res['spc']}"
        return msg
    if action == 'cancelled':
        return '[CANCEL] Отменено'
    if 'specs' in res:
        return f"[OK] Спецификаций: {res.get('count', 0)}"
    if 'norms' in res:
        return f"[OK] {res.get('spc')}: параметров {res.get('count', 0)}"
    return f'[Spec] {res}'
