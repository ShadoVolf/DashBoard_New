"""Инструменты ассистента для модуля Протоколы.

Соглашения:
  * Каждый tool возвращает dict. Ошибка — {'error': str, 'hint': str|None}.
  * Мутации: dry_run (confirm=False) → preview; confirm=True → apply.
    Исключение — delete с явным protokol_id: применяется сразу (по ТЗ).
  * Все mutation-tools после успеха вызывают _invalidate_caches() и
    _refresh_protocol_ui(), чтобы UI не показывал устаревшие нормы.
  * log_action вызывается с actor='Assistant' и исходным текстом запроса.
"""
from __future__ import annotations

import re
import time

from Archive_View.Archive_Constants import ALL_MSK, MODE_ONLY_NUM
from Archive_View.Archive_Data import (
    load_archive_data, load_archive_by_numbers,
    get_archive_types, get_archive_specs_by_type, get_archive_msk_list,
    parse_numbers_input,
)
from Protocol_Manager.Protocol_Data import (
    search_archived_protocols, get_protocol_by_id, get_archive_protocol_data,
    get_protocol_order_info, get_lot_details,
    add_numbers_to_protocol, remove_numbers_from_protocol,
    save_order_info, save_make_dates, update_psidata_make_dates,
    send_to_lot_rk, log_action, _engine,
)
from Protocol_Manager.Protocol_Create_Tab import print_custom_protocol
from Protocol_Manager.Protocol_Print import print_archived_protocol
from Protocol_Manager.Protocol_Common import (
    _pm_load_spc_map_for_display, clear_presentation_params_cache,
)
from Protocol_Manager.Protocol_Constants import ARCH_ALL_DATES, ARCH_ALL_FILES
from .context import get_ctx, set_pending, peek_pending, pop_pending, is_yes, is_no
from .launcher import launch_protocol


# =========================================================================
# Логирование
# =========================================================================
def _log(dpg_, text, color=None):
    try:
        from Statistik.dashboard_llm import _append_assistant_log
        _append_assistant_log(dpg_, text, color=color)
    except Exception:
        print(f'[Assistant.protocol] {text}')


# =========================================================================
# Вспомогательные
# =========================================================================
_SENTINELS = frozenset((ALL_MSK, ARCH_ALL_DATES, ARCH_ALL_FILES, '', None))


def _norm(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s in _SENTINELS else s


def _invalidate_caches():
    try:
        clear_presentation_params_cache()
    except Exception:
        pass


def _refresh_protocol_ui(dpg_, protokol_id=None):
    """Перерисовать список/текущий протокол после мутации."""
    try:
        from Protocol_Manager.Protocol_Archive_Tab import (
            _refresh_archive_list, _on_archive_select,
        )
        if dpg_.does_item_exist('pm_archive_list_container'):
            _refresh_archive_list()
        if protokol_id and dpg_.does_item_exist('pm_archive_selected_info'):
            _on_archive_select(None, None, int(protokol_id))
    except Exception as e:
        print(f'[_refresh_protocol_ui] {e}')


def _as_int(v, name):
    if isinstance(v, bool):
        return {'error': f'{name} должен быть целым числом, не bool'}
    try:
        return int(v)
    except (TypeError, ValueError):
        return {'error': f'{name} должен быть целым числом, получено {v!r}',
                'hint': 'Возьмите ID из search_protocols'}


def _as_numbers(v):
    if v is None:
        return []
    if isinstance(v, str):
        return parse_numbers_input(v)
    if not isinstance(v, list):
        return {'error': f'numbers должен быть list[str], получено {type(v).__name__}',
                'hint': 'Один номер — списком из одного: ["JN4450"]'}
    flat = []
    for x in v:
        if isinstance(x, str):
            flat.extend(parse_numbers_input(x) or [x])
        else:
            flat.append(str(x))
    return flat


def _count_remaining(protokol_id):
    df = get_archive_protocol_data(protokol_id)
    return 0 if df is None else len(df)

def _int_or(v, default=0):
    """int(v) с защитой от None/NaN/str-мусора."""
    if v is None:
        return default
    try:
        if v != v:   # NaN: NaN != NaN всегда True
            return default
    except Exception:
        pass
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _tool_search_protocols(params, ctx, dpg_):
    mid = params.get('measure_id')
    if mid is not None:
        try:
            mid = int(mid)
        except (TypeError, ValueError):
            return {'error': f'measure_id должен быть int, получено {mid!r}'}

    numbers = _as_numbers(params.get('numbers'))
    if isinstance(numbers, dict):
        return numbers

    psi_type = _norm(params.get('psi_type'))
    if psi_type not in (None, 'ПСИ', 'ОТК'):
        return {'error': f"psi_type должен быть 'ПСИ' или 'ОТК', "
                         f"получено {psi_type!r}"}

    # ---- загрузка ----
    if mid is not None:
        df = _search_by_measure_id(mid)
        if isinstance(df, dict):          # ошибка БД внутри хелпера
            return df
        if psi_type and df is not None and not df.empty \
                and 'PsiType' in df.columns:
            df = df[df['PsiType'] == psi_type]
    else:
        df = search_archived_protocols(
            msk_partial=_norm(params.get('msk_partial')),
            msk_exact=_norm(params.get('msk')),
            spc=_norm(params.get('spc')),
            rtype=_norm(params.get('rtype')),
            date=_norm(params.get('date')),
            file=_norm(params.get('file')),
            numbers=numbers or None,
            psi_type=psi_type,
            limit=int(params.get('limit', 200)),
        )

    if isinstance(df, dict):
        return df
    if df is None or df.empty:
        extra = f' (тип {psi_type})' if psi_type else ''
        return {'count': 0, 'protocols': [],
                'note': (f'Ничего не найдено{extra}. '
                         f'Попробуйте снять фильтры или '
                         f'использовать msk_partial вместо msk.')}

    ctx['last_search_df'] = df
    if len(df) == 1:
        ctx['last_protokol_id'] = _int_or(
            df.iloc[0].get('Measure_protokol_ID'), 0)

    # ---- безопасный маппинг строк ----
    protocols = []
    for _, r in df.head(200).iterrows():
        protocols.append({
            'id': _int_or(r.get('Measure_protokol_ID'), 0),
            'protokol_n': str(r.get('ProtokolN') or ''),
            'msk': str(r.get('MSK') or ''),
            'spc': str(r.get('Spc') or ''),
            'date': str(r.get('dataR') or '')[:16],
            'measure_id': _int_or(r.get('Measure_ID'), 0),
            'type': str(r.get('PsiType') or 'ОТК'),
            'count_items': _int_or(r.get('Current_Count'), 0),
            'total_items': _int_or(r.get('Total_Count'), 0),
            'rows': (f"{_int_or(r.get('Current_Count'), 0)}/"
                     f"{_int_or(r.get('Total_Count'), 0)}"),
        })

    return {
        'count':    len(df),
        'psi_type': psi_type,
        'protocols': protocols,
    }
# =========================================================================
# Загрузка psidata
# =========================================================================
def _load_source_df(msk_or_spec, numbers=None):
    """DataFrame с колонками N, Measure_ID, Spc для MSK/спеки/номеров."""
    if msk_or_spec:
        df = load_archive_data(msk=msk_or_spec, only_good=False)
        if df is not None and not df.empty:
            return df
        # Попытка как спецификация
        try:
            for t in get_archive_types():
                if msk_or_spec in get_archive_specs_by_type(t):
                    frames = []
                    for m in get_archive_msk_list(msk_or_spec):
                        sub = load_archive_data(msk=m, spc=msk_or_spec,
                                                 only_good=False)
                        if sub is not None and not sub.empty:
                            frames.append(sub)
                    if frames:
                        import pandas as pd
                        return pd.concat(frames, ignore_index=True)
        except Exception:
            pass
    if numbers:
        df = load_archive_by_numbers(numbers, MODE_ONLY_NUM, only_good=False)
        if df is not None and not df.empty:
            return df
    return {'error': f'Не удалось загрузить psidata для {msk_or_spec!r}',
            'hint': 'Проверьте имя МСК (list_msks) или номера'}


def _find_new_protocol_id(measure_id, numbers, spc_name):
    """ID только что созданного протокола: самый свежий с такими номерами."""
    try:
        df = search_archived_protocols(numbers=numbers, spc=spc_name, limit=10)
        if df is None or df.empty:
            return None
        if 'Measure_ID' in df.columns:
            df = df[df['Measure_ID'] == measure_id]
        if df.empty:
            return None
        return int(df.iloc[0]['Measure_protokol_ID'])
    except Exception as e:
        print(f'[_find_new_protocol_id] {e}')
        return None


def _apply_order_data(protokol_id, order, spc_fallback=None):
    """Сохранить заказ в протокол (lot + date → dogovor, customer)."""
    lot  = (order or {}).get('lot')
    date = (order or {}).get('date')
    if not lot or not date:
        return {'error': 'order требует lot и date'}

    header = get_protocol_by_id(protokol_id) or {}
    spc = (header.get('Spc') or spc_fallback or '').strip()

    details = get_lot_details(lot, spc, date)
    if not details:
        return {'error': (f'Заказ не найден в заказы1С_новые: '
                          f'lot={lot}, spc={spc!r}, date={date}'),
                'hint': 'Проверьте номер заказа и дату'}

    dogovor  = (details.get('dogovor')  or '').strip()
    customer = (details.get('customer') or '').strip()
    if not dogovor and not customer:
        return {'error': 'У заказа нет ни договора, ни контрагента'}

    save_order_info(protokol_id, lot, dogovor, customer)
    log_action('SET_ORDER', protokol_id, header.get('Measure_ID') or 0,
               f'Assistant: lot={lot}, date={date}, dogovor={dogovor}',
               'Assistant')
    return {'lot': lot, 'date': date, 'dogovor': dogovor,
            'customer': customer}


# =========================================================================
# CREATE
# =========================================================================
def _tool_create_protocols(params, ctx, dpg_):
    msk_or_spec = (_norm(params.get('msk_or_spec'))
                   or _norm(params.get('msk'))
                   or _norm(params.get('spc')))
    numbers_in  = _as_numbers(params.get('numbers'))
    numbers_ex  = _as_numbers(params.get('exclude_numbers')
                              or params.get('exclude')) or []
    psi_type    = params.get('psi_type') or 'ОТК'
    order       = params.get('order')
    confirm     = bool(params.get('confirm', False))

    max_count = params.get('max_count')
    try:
        max_count = int(max_count) if max_count else None
        if max_count is not None and max_count <= 0:
            max_count = None
    except (TypeError, ValueError):
        max_count = None

    selected_mids = params.get('selected_measure_ids')
    if selected_mids is not None:
        try:
            selected_mids = {int(x) for x in selected_mids}
        except (TypeError, ValueError):
            return {'error': 'selected_measure_ids должен быть списком int'}

    if isinstance(numbers_in, dict):
        return numbers_in
    if isinstance(numbers_ex, dict):
        return numbers_ex

    if psi_type not in ('ПСИ', 'ОТК'):
        return {'error': f'psi_type должен быть ПСИ или ОТК, получено {psi_type!r}'}
    if not msk_or_spec and not numbers_in:
        return {'error': 'Нужна МСК/спецификация или номера',
                'hint': 'Пример: {"msk_or_spec": "456", "numbers": ["JN4450"]}'}

    df = _load_source_df(msk_or_spec, numbers_in)
    if isinstance(df, dict):
        return df
    if df.empty:
        return {'error': 'Нет данных для заданных фильтров'}

    if numbers_in:
        keep = set(n.upper() for n in numbers_in)
        df = df[df['N'].astype(str).str.upper().isin(keep)]
    if numbers_ex:
        drop = set(n.upper() for n in numbers_ex)
        df = df[~df['N'].astype(str).str.upper().isin(drop)]

    if df.empty:
        return {'error': 'После фильтрации не осталось номеров'}

    if 'Measure_ID' not in df.columns:
        return {'error': 'В данных нет Measure_ID'}

    groups = {}
    truncated_info = []
    for mid, sub in df.groupby('Measure_ID'):
        nums = [str(n) for n in sub['N'].dropna()]
        if max_count and len(nums) > max_count:
            truncated_info.append({'measure_id': int(mid),
                                   'kept': max_count,
                                   'total': len(nums)})
            nums = nums[:max_count]
        if nums:
            groups[int(mid)] = nums

    if selected_mids is not None:
        groups = {mid: nums for mid, nums in groups.items()
                  if mid in selected_mids}
        if not groups:
            return {'error': 'Из выбранных замеров ничего не осталось'}

    spc_name = None
    if 'Spc' in df.columns:
        uniq = [str(s) for s in df['Spc'].dropna().unique() if s]
        if len(uniq) == 1:
            spc_name = uniq[0]

    # ---- PREVIEW ----
    if not confirm:
        candidates = []
        for mid, nums in groups.items():
            sub = df[df['Measure_ID'] == mid]
            msk_val = ''
            if 'MSK' in sub.columns and not sub.empty:
                try:
                    msk_val = str(sub['MSK'].iloc[0])
                except Exception:
                    pass
            candidates.append({
                'measure_id':    int(mid),
                'msk':           msk_val,
                'numbers_count': len(nums),
                'sample':        nums[:5],
            })

        if len(groups) > 1:
            set_pending('await_create_choice', {
                'action': 'create_protocols',
                'params': {
                    'msk_or_spec': msk_or_spec,
                    'numbers': numbers_in,
                    'exclude_numbers': numbers_ex,
                    'psi_type': psi_type,
                    'order': order,
                    'max_count': max_count,
                },
                'candidates': candidates,
            })
            return {
                'action': 'await_create_choice',
                'psi_type': psi_type,
                'total_protocols': len(groups),
                'total_numbers': sum(len(v) for v in groups.values()),
                'candidates': candidates,
                'truncated': truncated_info or None,
            }

        return {
            'action': 'dry_run',
            'msk_or_spec': msk_or_spec,
            'psi_type': psi_type,
            'protocols_count': len(groups),
            'numbers_total': sum(len(v) for v in groups.values()),
            'protocols': candidates,
            'order': order,
            'truncated': truncated_info or None,
            'note': 'Это preview. Для создания повтори с confirm=true.',
        }

    # ---- APPLY ----
    created = []
    for mid, nums in groups.items():
        try:
            _log(dpg_, f'Создаю {psi_type} для Measure_ID={mid} '
                       f'({len(nums)} номеров)...')
            print_custom_protocol(mid, nums, psi_type, spc_name=spc_name)
            pid = _find_new_protocol_id(mid, nums, spc_name)
            rec = {'measure_id': mid, 'numbers_count': len(nums),
                   'protokol_id': pid}
            if order and pid:
                rec['order'] = _apply_order_data(pid, order, spc_name)
            created.append(rec)
        except Exception as e:
            created.append({'measure_id': mid,
                            'error': f'{type(e).__name__}: {e}'})

    _invalidate_caches()
    _refresh_protocol_ui(dpg_)
    return {'action': 'created', 'psi_type': psi_type, 'protocols': created}



# =========================================================================
# SEARCH
# =========================================================================
def _search_by_measure_id(measure_id, limit=50):
    """search_archived_protocols не умеет measure_id — прямой запрос."""
    from sqlalchemy import text
    import pandas as pd
    try:
        from Protocol_Manager.Protocol_Data import _has_psi_type_column
        _has = _has_psi_type_column
    except Exception:
        _has = lambda e: False
    engine = _engine()
    psi_expr = ("COALESCE(p.psi_type, 'ОТК')" if _has(engine) else "'ОТК'")
    sql = text(f"""
        SELECT p.Measure_protokol_ID, p.ProtokolN, p.MSK, p.Spc,
               p.dataR, p.Count AS Total_Count,
               {psi_expr} AS PsiType, p.Measure_ID,
               (SELECT COUNT(*) FROM psi_protokol_archive a2
                WHERE a2.Measure_Protokol_ID = p.Measure_protokol_ID)
                 AS Current_Count
        FROM psi_measure_protokol_id p
        WHERE p.Measure_ID = :mid
        ORDER BY p.dataR DESC, p.Measure_protokol_ID DESC
        LIMIT :lim
    """)
    try:
        return pd.read_sql(sql, engine,
                           params={'mid': int(measure_id), 'lim': limit})
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}




# =========================================================================
# DELETE (мутация, без confirm для явного ID — по ТЗ)
# =========================================================================
def _do_delete_by_id(protokol_id, numbers, dpg_):
    header = get_protocol_by_id(protokol_id)
    if not header:
        return {'error': f'Протокол {protokol_id} не найден'}
    try:
        remove_numbers_from_protocol(protokol_id, numbers)
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}
    log_action('REMOVE_NUMBERS', protokol_id,
               header.get('Measure_ID') or 0,
               f'Assistant: удалил {numbers}', 'Assistant')
    _invalidate_caches()
    _refresh_protocol_ui(dpg_, protokol_id)
    return {'action': 'removed',
            'protokol_id': protokol_id,
            'removed': numbers,
            'remaining': _count_remaining(protokol_id)}


def _tool_delete_numbers(params, ctx, dpg_):
    numbers = _as_numbers(params.get('numbers'))
    if isinstance(numbers, dict):
        return numbers
    if not numbers:
        return {'error': 'numbers обязательны',
                'hint': 'Например: {"protokol_id": 42, "numbers": ["JN4450"]}'}

    pid = params.get('protokol_id')
    if pid is not None:
        pid = _as_int(pid, 'protokol_id')
        if isinstance(pid, dict):
            return pid
        # По ТЗ: явный ID → сразу выполняем
        return _do_delete_by_id(pid, numbers, dpg_)

    msk = _norm(params.get('msk'))
    if not msk:
        return {'error': 'Укажите protokol_id или msk'}

    df = search_archived_protocols(msk_exact=msk, limit=100)
    if df is None or df.empty:
        return {'error': f'Нет протоколов на МСК {msk}'}

    # Оставляем только протоколы, где реально есть эти номера
    candidates = []
    for _, row in df.iterrows():
        cpid = int(row['Measure_protokol_ID'])
        cdf = get_archive_protocol_data(cpid)
        if cdf is None or cdf.empty or 'N' not in cdf.columns:
            continue
        existing = set(str(x) for x in cdf['N'].dropna())
        matched = [n for n in numbers if n in existing]
        if matched:
            candidates.append({
                'protokol_id': cpid,
                'protokol_n': str(row.get('ProtokolN', '')),
                'date':       str(row.get('dataR', ''))[:16],
                'msk':        str(row.get('MSK', '')),
                'matched':    matched,
                'total_rows': len(existing),
            })

    if not candidates:
        return {'error': f'Ни в одном протоколе на МСК {msk} '
                          f'не найдены номера {numbers}'}
    if len(candidates) == 1:
        return _do_delete_by_id(candidates[0]['protokol_id'],
                                candidates[0]['matched'], dpg_)

    set_pending('await_protokol_id', {
        'action': 'delete_numbers',
        'msk': msk,
        'numbers': numbers,
        'candidates': candidates,
    })
    return {
        'action': 'await_choice',
        'msk': msk,
        'candidates': candidates,
        'hint': 'Ответьте ID протокола (например: 42) или его '
                'номером в списке (1..N)',
    }


# =========================================================================
# ADD_NUMBERS
# =========================================================================
def _tool_add_numbers(params, ctx, dpg_):
    pid = _as_int(params.get('protokol_id'), 'protokol_id')
    if isinstance(pid, dict):
        return pid
    numbers = _as_numbers(params.get('numbers'))
    if isinstance(numbers, dict):
        return numbers
    if not numbers:
        return {'error': 'numbers обязательны'}

    header = get_protocol_by_id(pid)
    if not header:
        return {'error': f'Протокол {pid} не найден'}

    df = get_archive_protocol_data(pid)
    existing = set()
    if df is not None and not df.empty and 'N' in df.columns:
        existing = {str(x).strip().upper() for x in df['N'].dropna()}
    to_add = [n for n in numbers if n.upper() not in existing]
    skipped = [n for n in numbers if n.upper() in existing]

    if not params.get('confirm', False):
        return {'action': 'dry_run',
                'protokol_id': pid,
                'protokol_n': header.get('ProtokolN'),
                'msk': header.get('MSK'),
                'would_add': to_add,
                'skipped_existing': skipped,
                'note': 'Повторите с confirm=true'}

    if not to_add:
        return {'action': 'noop', 'protokol_id': pid,
                'skipped': skipped,
                'note': 'Все номера уже в протоколе'}

    added = add_numbers_to_protocol(
        pid, header.get('Measure_ID'), to_add,
        header.get('psi_type') or 'ОТК')
    log_action('ADD_NUMBERS', pid, header.get('Measure_ID') or 0,
               f'Assistant: добавил {added}; пропущено {skipped}',
               'Assistant')

    # Пробрасываем даты изготовления, если они уже заданы
    try:
        info = get_protocol_order_info(pid) or {}
        md, md1 = info.get('MakeDate'), info.get('MakeDate1')
        if (md or md1) and header.get('Measure_ID'):
            update_psidata_make_dates(header.get('Measure_ID'), added,
                                      make_date=md, make_date1=md1)
    except Exception:
        pass

    _invalidate_caches()
    _refresh_protocol_ui(dpg_, pid)
    return {'action': 'added', 'protokol_id': pid,
            'added': added, 'skipped': skipped,
            'total_after': _count_remaining(pid)}


# =========================================================================
# ADD_ORDER
# =========================================================================
def _tool_add_order(params, ctx, dpg_):
    pid = params.get('protokol_id') or ctx.get('last_protokol_id')
    if pid is None:
        return {'error': 'protokol_id не задан и последний протокол '
                         'не выбран',
                'hint': 'Сначала откройте протокол: '
                        '"протокол ID 42" или "найди протоколы на МСК 456", '
                        'затем "добавь заказ 12345 от 2025-01-15"'}
    pid = _as_int(pid, 'protokol_id')
    if isinstance(pid, dict):
        return pid

    header = get_protocol_by_id(pid)
    if not header:
        return {'error': f'Протокол {pid} не найден'}

    order = params.get('order') or {}
    lot  = (order.get('lot')  or params.get('lot')  or '').strip()
    date = (order.get('date') or params.get('date') or '').strip()

    missing = []
    if not lot:
        missing.append('номер заказа (lot)')
    if not date:
        missing.append('дата заказа YYYY-MM-DD (date)')
    if missing:
        return {'error': 'Не указаны: ' + ', '.join(missing),
                'hint': (f'Протокол {pid} выбран. Укажите данные заказа: '
                         f'"добавь заказ <номер> от YYYY-MM-DD"')}

    spc = (header.get('Spc') or '').strip()

    details = get_lot_details(lot, spc, date)
    if not details:
        return {'error': (f'Заказ не найден: lot={lot}, '
                          f'spc={spc!r}, date={date}'),
                'hint': 'Проверьте номер и дату заказа'}

    if not params.get('confirm', False):
        return {'action': 'dry_run',
                'protokol_id': pid,
                'protokol_n': header.get('ProtokolN'),
                'msk': header.get('MSK'),
                'would_set': {
                    'lot': lot, 'date': date,
                    'dogovor':  details.get('dogovor'),
                    'customer': details.get('customer'),
                    'remainder': details.get('remainder'),
                },
                'note': 'Повторите с confirm=true'}

    res = _apply_order_data(pid, {'lot': lot, 'date': date}, spc)
    if 'error' in res:
        return res
    _refresh_protocol_ui(dpg_, pid)
    return {'action': 'order_saved', 'protokol_id': pid, **res}


# =========================================================================
# SEND_TO_OTK
# =========================================================================
def _tool_send_to_otk(params, ctx, dpg_):
    pid = params.get('protokol_id') or ctx.get('last_protokol_id')
    if pid is None:
        return {'error': 'protokol_id не задан'}
    pid = _as_int(pid, 'protokol_id')
    if isinstance(pid, dict):
        return pid

    header = get_protocol_by_id(pid)
    if not header:
        return {'error': f'Протокол {pid} не найден'}

    info = get_protocol_order_info(pid) or {}
    if not (info.get('LotNumber') or '').strip():
        return {'error': f'У протокола {pid} нет данных заказа',
                'hint': 'Сначала add_order (номер заказа + дата)'}

    if not params.get('confirm', False):
        return {'action': 'dry_run',
                'protokol_id': pid,
                'protokol_n': header.get('ProtokolN'),
                'msk': header.get('MSK'),
                'order_lot': info.get('LotNumber'),
                'numbers_count': _count_remaining(pid),
                'note': 'Повторите с confirm=true. '
                        'Отправка в ОТК НЕ ОТКАТЫВАЕТСЯ.'}

    ok, msg = send_to_lot_rk(pid)
    if ok:
        log_action('SEND_LOT_RK', pid,
                   header.get('Measure_ID') or 0,
                   f'Assistant: {msg}', 'Assistant')
        _refresh_protocol_ui(dpg_, pid)
        return {'action': 'sent', 'protokol_id': pid, 'message': msg}
    log_action('SEND_LOT_RK_FAIL', pid,
               header.get('Measure_ID') or 0,
               f'Assistant: {msg}', 'Assistant')
    return {'error': msg}


# =========================================================================
# PRINT
# =========================================================================
def _tool_print_protocol(params, ctx, dpg_):
    pid = params.get('protokol_id') or ctx.get('last_protokol_id')
    if pid is None:
        return {'error': 'protokol_id не задан'}
    pid = _as_int(pid, 'protokol_id')
    if isinstance(pid, dict):
        return pid
    if not get_protocol_by_id(pid):
        return {'error': f'Протокол {pid} не найден'}
    try:
        print_archived_protocol(pid)
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}
    return {'action': 'printed', 'protokol_id': pid,
            'note': 'PDF сохранён в папке «Отчеты»'}


# =========================================================================
# OPEN_PROTOCOLS
# =========================================================================
def _tool_open_protocols(params, ctx, dpg_):
    msk = _norm(params.get('msk'))
    res = launch_protocol(dpg_)
    if res.get('status') == 'error':
        return res

    if not msk:
        return {'action': 'opened'}

    try:
        if dpg_.does_item_exist('pm_arch_id_input'):
            dpg_.set_value('pm_arch_id_input', '')
        if dpg_.does_item_exist('pm_arch_search_msk'):
            dpg_.set_value('pm_arch_search_msk', msk)
        if dpg_.does_item_exist('pm_arch_numbers_input'):
            dpg_.set_value('pm_arch_numbers_input', '')
        from Protocol_Manager.Protocol_Archive_Tab import _refresh_archive_list
        _refresh_archive_list()
        ctx['last_msk'] = msk
    except Exception as e:
        return {'action': 'opened',
                'warning': f'Модуль открыт, но фильтр МСК '
                           f'применить не удалось: {e}'}
    return {'action': 'opened', 'msk': msk}


# =========================================================================
# GET_PROTOCOL_INFO
# =========================================================================
def _tool_get_protocol_info(params, ctx, dpg_):
    pid = params.get('protokol_id') or ctx.get('last_protokol_id')
    if pid is None:
        return {'error': 'protokol_id не задан'}
    pid = _as_int(pid, 'protokol_id')
    if isinstance(pid, dict):
        return pid
    header = get_protocol_by_id(pid)
    if not header:
        return {'error': f'Протокол {pid} не найден'}
    ctx['last_protokol_id'] = pid        # <-- сохраняем для следующих операций
    order = get_protocol_order_info(pid) or {}
    df = get_archive_protocol_data(pid)
    return {
        'id': pid,
        'protokol_n': header.get('ProtokolN'),
        'msk': header.get('MSK'),
        'spc': header.get('Spc'),
        'psi_type': header.get('psi_type') or 'ОТК',
        'date': str(header.get('dataR') or '')[:16],
        'measure_id': header.get('Measure_ID'),
        'rows': 0 if df is None else len(df),
        'order': {k: order.get(k) for k in
                  ('LotNumber', 'Dogovor', 'Customer', 'MakeDate', 'MakeDate1')
                  if order.get(k)},
    }


# =========================================================================
# Dispatcher + pending handler
# =========================================================================
_TOOLS = {
    'create_protocols': _tool_create_protocols,
    'search_protocols': _tool_search_protocols,
    'delete_numbers':   _tool_delete_numbers,
    'add_numbers':      _tool_add_numbers,
    'add_order':        _tool_add_order,
    'send_to_otk':      _tool_send_to_otk,
    'print_protocol':   _tool_print_protocol,
    'open_protocols':   _tool_open_protocols,
    'get_protocol_info': _tool_get_protocol_info,
}


def execute(name, params, dpg_):
    fn = _TOOLS.get(name)
    if not fn:
        return {'error': f'unknown tool: {name}'}
    try:
        return fn(params or {}, get_ctx(), dpg_)
    except Exception as e:
        import traceback; traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}

# =========================================================================
# Форматирование результата для лога ассистента
# =========================================================================
# Все маркеры — ASCII, чтобы не зависеть от глифов в шрифте DearPyGui.
#    [OK]       — успех
#    [ERR]      — ошибка
#    [!]        — предупреждение
#    [?]        — запрос уточнения
#    [INFO]     — нейтральная информация
#    [PREVIEW]  — ожидание подтверждения (dry_run)
#    [CANCEL]   — операция отменена
# =========================================================================
def _format_search_result(res):
    """Заголовок с количеством + список протоколов.

    Формат строки:
      ID <id> | <дата> | <штук> шт | МСК <msk> | <ПСИ|ОТК>
    Показываем первые 50 — дальше "... показаны первые 50 из N".
    """
    count     = res.get('count', 0)
    protocols = res.get('protocols') or []
    psi       = res.get('psi_type')

    head = f'[INFO] Найдено протоколов: {count}'
    if psi:
        head += f' ({psi})'
    if not protocols:
        note = res.get('note')
        return head + (f'\n  {note}' if note else '')

    lines = [head, '']
    shown = protocols[:50]
    for p in shown:
        pid   = p.get('id', 0)
        date  = p.get('date') or '-'
        items = p.get('count_items')
        if items is None:
            # fallback для старых результатов без count_items
            items = p.get('rows', '').split('/')[0] or 0
        msk   = p.get('msk') or ''
        ptype = p.get('type') or 'ОТК'

        line = f'  ID {pid} | {date} | {items} шт'
        if msk:
            line += f' | МСК {msk}'
        line += f' | {ptype}'
        lines.append(line)

    if len(protocols) > len(shown):
        lines.append(
            f'  ... показаны первые {len(shown)} из {len(protocols)}, '
            f'уточните фильтры (МСК / дата / тип)'
        )
    return '\n'.join(lines)
def format_result(name, res):
    """Человекочитаемая строка для лога ассистента (без спецсимволов).

    name='pending' — ответ после handle_pending_reply (см. controller).
    """
    if not isinstance(res, dict):
        return str(res)
    if res.get('error'):
        return f'[ERR] {res["error"]}'

    # ---- поиск протоколов: заголовок + построчный список ----
    if name == 'search_protocols' or (
            'count' in res and 'protocols' in res and 'action' not in res):
        return _format_search_result(res)

    action = res.get('action')

    if action == 'dry_run':
        return '[PREVIEW] ' + _preview_str(name, res)

    if action == 'await_create_choice':
        cands = res.get('candidates') or []
        head = (f'[?] Найдено замеров: {len(cands)}, будет создано '
                f'протоколов {res.get("psi_type")} на '
                f'{res.get("total_numbers")} номеров:')
        lines = [head]
        for i, c in enumerate(cands, 1):
            msk = c.get('msk') or '?'
            lines.append(
                f'  {i}) ID замера {c["measure_id"]} | МСК {msk} | '
                f'{c["numbers_count"]} шт'
            )
        trunc = res.get('truncated') or []
        if trunc:
            parts = [f"ID {t['measure_id']} ({t['kept']}/{t['total']})"
                     for t in trunc]
            lines.append('[!] Обрезано по max_count: ' + ', '.join(parts))
        lines.append('Ответьте "все" или номера через запятую '
                     '(1,3,5 — индексы / ID через запятую — замеры).')
        return '\n'.join(lines)

    if action == 'await_choice':
        cands = res.get('candidates') or []
        lines = [f'[?] Найдено {len(cands)} протоколов:']
        for i, c in enumerate(cands, 1):
            lines.append(
                f'  {i}) ID {c["protokol_id"]} | '
                f'{c["date"]} | МСК {c["msk"]} | '
                f'совпало {len(c["matched"])} из {c["total_rows"]}'
            )
        lines.append('Ответьте ID протокола или номером из списка.')
        return '\n'.join(lines)

    if action == 'created':
        prots = res.get('protocols') or []
        n = len(prots)
        ok = sum(1 for p in prots if not p.get('error'))
        lines = [f'[OK] Создано протоколов: {ok}/{n} '
                 f'({res.get("psi_type")})']
        for p in prots:
            if p.get('error'):
                lines.append(
                    f'  ID замера {p.get("measure_id")}: [ERR] {p["error"]}'
                )
            else:
                lines.append(
                    f'  ID замера {p.get("measure_id")} -> '
                    f'протокол {p.get("protokol_id") or "?"} '
                    f'({p.get("numbers_count")} шт)'
                )
                if p.get('order') and not p['order'].get('error'):
                    o = p['order']
                    lines.append(
                        f'    заказ {o.get("lot")} / {o.get("date")} '
                        f'-> {o.get("dogovor") or "-"}'
                    )
        return '\n'.join(lines)

    if action == 'removed':
        return (f'[OK] Удалено {len(res.get("removed") or [])} номеров '
                f'из протокола {res.get("protokol_id")} '
                f'(осталось: {res.get("remaining")})')

    if action == 'added':
        return (f'[OK] Добавлено {len(res.get("added") or [])} номеров '
                f'в протокол {res.get("protokol_id")} '
                f'(пропущено {len(res.get("skipped") or [])})')

    if action == 'order_saved':
        return (f'[OK] Заказ сохранён в протокол {res.get("protokol_id")}: '
                f'{res.get("lot")} / {res.get("date")}')

    if action == 'sent':
        return f'[OK] Отправлено в ОТК: {res.get("message")}'

    if action == 'printed':
        return (f'[OK] PDF сформирован (ID {res.get("protokol_id")}), '
                f'папка "Отчеты"')

    if action == 'opened':
        extra = f', МСК {res["msk"]}' if res.get('msk') else ''
        warn  = f' [!] {res["warning"]}' if res.get('warning') else ''
        return f'[OK] Модуль протоколов открыт{extra}{warn}'

    if action == 'cancelled':
        return '[CANCEL] Операция отменена.'

    if action == 'noop':
        return '[INFO] Все номера уже в протоколе.'

    # get_protocol_info
    if 'id' in res and 'protokol_n' in res:
        lines = [f'[INFO] Протокол ID {res.get("id")} '
                 f'({res.get("psi_type") or "ОТК"})',
                 f'  N: {res.get("protokol_n") or "-"} | '
                 f'МСК {res.get("msk") or "-"} | '
                 f'Spc {res.get("spc") or "-"}',
                 f'  Дата: {res.get("date") or "-"} | '
                 f'ID замера: {res.get("measure_id") or "-"} | '
                 f'Записей: {res.get("rows", 0)}']
        order = res.get('order') or {}
        if order:
            parts = [f'{k}={v}' for k, v in order.items()]
            lines.append('  Заказ: ' + ', '.join(parts))
        else:
            lines.append('  Заказ: не задан')
        return '\n'.join(lines)

    if 'count' in res:
        return f'[INFO] Найдено протоколов: {res["count"]}'

    return str(res)[:300]

def _preview_str(name, res):
    """Текст dry_run-предпросмотра (без спецсимволов)."""
    if name == 'create_protocols':
        prots = res.get('protocols') or []
        lines = [f'создам {res.get("protocols_count", len(prots))} '
                 f'протоколов {res.get("psi_type")} на '
                 f'{res.get("numbers_total", 0)} номеров:']
        for c in prots:
            msk = c.get('msk') or '?'
            lines.append(
                f'  ID замера {c["measure_id"]} | МСК {msk} | '
                f'{c["numbers_count"]} шт'
                + (f' | пример: {", ".join(c["sample"])}'
                   if c.get('sample') else '')
            )
        trunc = res.get('truncated') or []
        if trunc:
            parts = [f"ID {t['measure_id']} ({t['kept']}/{t['total']})"
                     for t in trunc]
            lines.append('[!] Обрезано по max_count: ' + ', '.join(parts))
        lines.append('Ответьте "да" или "нет".')
        return '\n'.join(lines)

    if name == 'add_numbers':
        return (f'добавлю {len(res.get("would_add") or [])} номеров '
                f'в протокол {res.get("protokol_id")} '
                f'(пропущу {len(res.get("skipped_existing") or [])}). '
                f'Ответьте "да" или "нет".')

    if name == 'add_order':
        w = res.get('would_set') or {}
        return (f'сохраню заказ {w.get("lot")} / {w.get("date")} '
                f'в протокол {res.get("protokol_id")} '
                f'(договор {w.get("dogovor") or "-"}, '
                f'контрагент {w.get("customer") or "-"}). '
                f'Ответьте "да" или "нет".')

    if name == 'send_to_otk':
        return (f'отправлю протокол {res.get("protokol_id")} '
                f'({res.get("numbers_count")} номеров) в ОТК. '
                f'НЕОБРАТИМО. Ответьте "да" или "нет".')

    return 'подтвердите операцию ("да" / "нет")'


def handle_pending_reply(reply, dpg_):
    """Обработать ответ пользователя, если есть активный pending.

    Типы pending:
      confirm_create / confirm_add_numbers / confirm_add_order /
      confirm_send          — «да» / «нет»
      await_protokol_id     — числовой ответ: ID протокола или номер 1..N
      await_create_choice   — «все» или список: 1,3,5 / ID,ID,ID

    Возвращает dict-результат или None, если pending нет/истёк.
    """
    pending = peek_pending()
    if not pending:
        return None

    kind    = pending['kind']
    payload = pending['payload']
    reply   = (reply or '').strip()
    reply_low = reply.lower()

    # ---- подтверждения (да/нет) ----
    if kind in ('confirm_create', 'confirm_add_numbers',
                'confirm_add_order', 'confirm_send'):
        if is_yes(reply):
            pop_pending()
            p = dict(payload['params'])
            p['confirm'] = True
            return execute(payload['tool'], p, dpg_)
        if is_no(reply):
            pop_pending()
            return {'action': 'cancelled'}
        return {'error': 'Ответьте "да" или "нет" '
                         '(или введите новый запрос для отмены)'}

    # ---- выбор замеров для создания протоколов ----
    if kind == 'await_create_choice':
        if reply_low in ('нет', 'no', 'отмена', 'cancel', 'стоп',
                         'не надо'):
            pop_pending()
            return {'action': 'cancelled'}

        candidates = payload['candidates']

        if reply_low in ('все', 'all', '*', 'да', 'yes', 'ok',
                         'создавай', 'выполняй'):
            selected_mids = [c['measure_id'] for c in candidates]
        else:
            targets = set()
            for tok in re.split(r'[,\s]+', reply_low):
                tok = tok.strip()
                if not tok:
                    continue
                if '-' in tok and tok.count('-') == 1:
                    a, b = tok.split('-', 1)
                    try:
                        for i in range(int(a), int(b) + 1):
                            targets.add(i)
                    except (ValueError, TypeError):
                        pass
                elif tok.isdigit():
                    targets.add(int(tok))

            selected_mids = []
            for i, c in enumerate(candidates, 1):
                if i in targets or c['measure_id'] in targets:
                    selected_mids.append(c['measure_id'])

        if not selected_mids:
            return {'error':
                    'Не удалось распознать выбор. Ответьте "все" '
                    'или номера через запятую (1,3,5 или ID через запятую)'}

        pop_pending()
        params = dict(payload['params'])
        params['confirm'] = True
        params['selected_measure_ids'] = selected_mids
        return execute('create_protocols', params, dpg_)

    # ---- выбор протокола для удаления ----
    if kind == 'await_protokol_id':
        m = re.match(r'^\s*(\d+)\s*$', reply)
        if not m:
            return {'error': 'Ответьте числом — ID протокола или номер '
                             'из списка'}
        val = int(m.group(1))
        candidates = payload['candidates']
        for c in candidates:
            if c['protokol_id'] == val:
                pop_pending()
                return _do_delete_by_id(c['protokol_id'],
                                        c['matched'], dpg_)
        if 1 <= val <= len(candidates):
            c = candidates[val - 1]
            pop_pending()
            return _do_delete_by_id(c['protokol_id'],
                                    c['matched'], dpg_)
        return {'error': f'{val} нет в списке — укажите ID или номер 1..N'}

    return {'error': f'Неизвестное pending-состояние: {kind}'}


def _tool_search_protocols(params, ctx, dpg_):
    mid = params.get('measure_id')
    if mid is not None:
        try:
            mid = int(mid)
        except (TypeError, ValueError):
            return {'error': f'measure_id должен быть int'}

    numbers = _as_numbers(params.get('numbers'))
    if isinstance(numbers, dict):
        return numbers

    psi_type = _norm(params.get('psi_type'))

    if mid is not None:
        df = _search_by_measure_id(mid)
        if isinstance(df, dict):
            return df
        if psi_type and not df.empty and 'PsiType' in df.columns:
            df = df[df['PsiType'] == psi_type]
    else:
        df = search_archived_protocols(
            msk_partial=_norm(params.get('msk_partial')),
            msk_exact=_norm(params.get('msk')),
            spc=_norm(params.get('spc')),
            rtype=_norm(params.get('rtype')),
            date=_norm(params.get('date')),
            file=_norm(params.get('file')),
            numbers=numbers or None,
            psi_type=psi_type,
            limit=int(params.get('limit', 200)),
        )
    if isinstance(df, dict):
        return df
    if df is None or df.empty:
        extra = f' (тип {psi_type})' if psi_type else ''
        return {'count': 0, 'protocols': [],
                'note': f'Ничего не найдено{extra}. '
                        f'Попробуйте снять фильтры или '
                        f'использовать msk_partial вместо msk.'}

    ctx['last_search_df'] = df
    if len(df) == 1:
        ctx['last_protokol_id'] = int(df.iloc[0]['Measure_protokol_ID'])

    return {
        'count': len(df),
        'psi_type': psi_type,
        'protocols': [
            {'id': int(r['Measure_protokol_ID']),
             'protokol_n': str(r.get('ProtokolN', '')),
             'msk': str(r.get('MSK', '')),
             'spc': str(r.get('Spc', '')),
             'date': str(r.get('dataR', ''))[:16],
             'measure_id': int(r.get('Measure_ID') or 0),
             'type': str(r.get('PsiType') or 'ОТК'),
             'rows': f"{int(r.get('Current_Count') or 0)}/"
                     f"{int(r.get('Total_Count') or 0)}"}
            for _, r in df.head(200).iterrows()
        ],
    }