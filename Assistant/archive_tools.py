"""Инструменты ассистента для модуля Архив.

Соглашения:
  * Каждый tool возвращает dict. Ошибка — {'error': str, 'hint': str|None}.
  * Загрузка данных выставляет user_data окна архива и обновляет таблицу UI.
  * Печать / экспорт работают с текущей выборкой или загружают данные по параметрам.
"""
from __future__ import annotations

import os
import traceback
from datetime import datetime
from typing import Any, Optional

import pandas as pd
import dearpygui.dearpygui as dpg

from Archive_View.Archive_Constants import (
    WINDOW_TAG, ALL_MSK, MODE_ONLY_NUM, MODE_FULL_MSK,
)
from Archive_View.Archive_Data import (
    search_archive_msk,
    load_archive_data,
    load_archive_by_numbers,
    find_measure_ids_by_numbers,
    get_archive_msk_list,
    get_archive_specs_by_type,
    get_archive_types,
    parse_numbers_input,
    load_spc_map_for_archive,
    build_archive_print_data,
    get_headers_dict,
)
from .launcher import launch_module, is_module_running


def _log(dpg_, text, color=None):
    try:
        from Statistik.dashboard_llm import _append_assistant_log
        _append_assistant_log(dpg_, text, color=color)
    except Exception:
        print(f'[Assistant.archive] {text}')


def _norm(v):
    if v is None:
        return None
    s = str(v).strip()
    return None if s in (ALL_MSK, '', 'None') else s


def _as_numbers(v):
    if v is None:
        return []
    if isinstance(v, str):
        return parse_numbers_input(v) or []
    if not isinstance(v, list):
        return []
    flat = []
    for x in v:
        if isinstance(x, str):
            flat.extend(parse_numbers_input(x) or [x])
        else:
            flat.append(str(x).strip().upper())
    return [n for n in flat if n]


def _ensure_archive_open(dpg_):
    if is_module_running('archive'):
        return {'status': 'already_running'}
    res = launch_module('archive', dpg_)
    return res


def _set_ui_selection(msk=None, spc=None, measure_id=None, numbers=None):
    """Мягко выставить комбо/поля архива (если окно открыто)."""
    try:
        if spc and dpg.does_item_exist('archive_spc_combo'):
            # по возможности подтянуть тип
            for t in get_archive_types():
                specs = get_archive_specs_by_type(t)
                if spc in specs:
                    if dpg.does_item_exist('archive_type_combo'):
                        dpg.set_value('archive_type_combo', t)
                        dpg.configure_item('archive_spc_combo', items=specs)
                    break
            dpg.set_value('archive_spc_combo', spc)
        if msk and dpg.does_item_exist('archive_msk_combo'):
            items = dpg.get_item_configuration('archive_msk_combo').get('items') or []
            if msk not in items:
                items = list(items) + [msk]
                dpg.configure_item('archive_msk_combo', items=items)
            dpg.set_value('archive_msk_combo', msk)
        if measure_id is not None and dpg.does_item_exist('archive_measure_id_input'):
            dpg.set_value('archive_measure_id_input', str(measure_id))
        if numbers is not None and dpg.does_item_exist('archive_numbers_input'):
            dpg.set_value('archive_numbers_input', ', '.join(numbers))
    except Exception as e:
        print(f'[archive_tools] _set_ui_selection: {e}')


def _fill_ui_from_df(df: Optional[pd.DataFrame], status: str = ''):
    if not dpg.does_item_exist(WINDOW_TAG):
        return
    try:
        from Archive_View.Archive_UI import (
            _fill_table, _fill_info, _fill_norms,
            _resolve_display_spc, _apply_psi_type_from_df,
        )
        dpg.set_item_user_data(WINDOW_TAG, df)
        _apply_psi_type_from_df(df)
        _fill_table(df)
        _fill_info(df)
        spc_for_norms = _resolve_display_spc(df)
        _fill_norms(spc_for_norms)
        if status and dpg.does_item_exist('archive_status_text'):
            dpg.set_value('archive_status_text', status)
    except Exception as e:
        print(f'[archive_tools] _fill_ui_from_df: {e}')
        traceback.print_exc()


def _summary_from_df(df: Optional[pd.DataFrame]) -> dict:
    if df is None or df.empty:
        return {
            'rows': 0,
            'measure_ids': 0,
            'measure_id_list': [],
            'msks': [],
            'msk_count': 0,
            'spc': None,
            'sample_numbers': [],
        }
    mids = (
        sorted(int(x) for x in df['Measure_ID'].dropna().unique())
        if 'Measure_ID' in df.columns else []
    )
    msks = (
        sorted(str(x) for x in df['MSK'].dropna().unique())
        if 'MSK' in df.columns else []
    )
    spc = None
    if 'Spc' in df.columns:
        uniq = [str(s) for s in df['Spc'].dropna().unique() if s]
        if len(uniq) == 1:
            spc = uniq[0]
        elif uniq:
            spc = f'{uniq[0]} (+{len(uniq) - 1})'
    return {
        'rows': len(df),
        'measure_ids': len(mids),
        'measure_id_list': mids[:30],
        'msks': msks[:50],
        'msk_count': len(msks),
        'spc': spc,
        'sample_numbers': (
            [str(n) for n in df['N'].dropna().head(10)]
            if 'N' in df.columns else []
        ),
    }


# =========================================================================
# Tools
# =========================================================================

def _tool_open_archive(params, dpg_):
    res = _ensure_archive_open(dpg_)
    msk = _norm(params.get('msk'))
    spc = _norm(params.get('spc'))
    measure_id = params.get('measure_id')
    numbers = _as_numbers(params.get('numbers'))

    if res.get('status') == 'error':
        return res

    if msk or spc or measure_id or numbers:
        load_res = _tool_load_archive({
            'msk': msk, 'spc': spc,
            'measure_id': measure_id, 'numbers': numbers,
        }, dpg_)
        return {
            'status': res.get('status', 'launched'),
            'loaded': load_res,
        }
    return {
        'status': res.get('status', 'launched'),
        'note': 'Модуль архива открыт. Укажите МСК, номера или ID замера для загрузки.',
    }


def _tool_search_msk(params, dpg_):
    partial = _norm(params.get('partial') or params.get('msk'))
    measure_id = params.get('measure_id')
    numbers = _as_numbers(params.get('numbers'))

    if measure_id is not None:
        try:
            mid = int(measure_id)
        except (TypeError, ValueError):
            return {'error': f'measure_id должен быть int, получено {measure_id!r}'}
        df = load_archive_data(measure_id=mid, only_good=False)
        if df is None or df.empty:
            return {'count': 0, 'msks': [], 'note': f'Замер ID {mid} не найден'}
        msks = (
            sorted(str(x) for x in df['MSK'].dropna().unique())
            if 'MSK' in df.columns else []
        )
        _ensure_archive_open(dpg_)
        _fill_ui_from_df(df, f'Поиск по ID {mid}: {len(df)} строк, МСК: {", ".join(msks[:10])}')
        return {
            'count': len(msks),
            'msks': msks,
            'rows': len(df),
            'measure_id': mid,
            'summary': _summary_from_df(df),
        }

    if numbers:
        return _tool_list_msk_by_numbers({'numbers': numbers}, dpg_)

    if not partial:
        return {
            'error': 'Нужна часть номера МСК, ID замера или номера',
            'hint': 'Пример: «найди мск 456» или «архив id замера 12345»',
        }

    matches = search_archive_msk(partial)
    _ensure_archive_open(dpg_)
    try:
        from Archive_View.Archive_Search import _display_msk_search_results
        _display_msk_search_results(matches, partial)
    except Exception:
        # fallback: только статус
        if dpg.does_item_exist('archive_status_text'):
            dpg.set_value(
                'archive_status_text',
                f'Поиск МСК по "{partial}": найдено {len(matches)}',
            )

    return {
        'count': len(matches),
        'partial': partial,
        'msks': list(matches)[:100],
        'note': (
            f'Найдено {len(matches)} МСК по подстроке «{partial}». '
            'Выберите МСК в комбо или загрузите: «загрузи архив МСК …»'
            if matches else f'По «{partial}» ничего не найдено'
        ),
    }


def _tool_list_msk_by_numbers(params, dpg_):
    numbers = _as_numbers(params.get('numbers'))
    if not numbers:
        return {'error': 'Нужен список или интервал номеров',
                'hint': 'Пример: «все мск для номеров JN4450-JN4460»'}

    mids = find_measure_ids_by_numbers(numbers, only_good=False)
    if not mids:
        return {
            'count': 0, 'msks': [], 'measure_ids': [],
            'note': f'По номерам ({len(numbers)} шт.) замеры не найдены',
        }

    df = load_archive_by_numbers(numbers, MODE_ONLY_NUM, only_good=False,
                                 found_mids=mids)
    msks = (
        sorted(str(x) for x in df['MSK'].dropna().unique())
        if df is not None and not df.empty and 'MSK' in df.columns else []
    )
    _ensure_archive_open(dpg_)
    status = (
        f'Номера: {len(numbers)} | замеров: {len(mids)} | '
        f'МСК: {len(msks)} | строк: {0 if df is None else len(df)}'
    )
    _fill_ui_from_df(df, status)
    _set_ui_selection(numbers=numbers)

    return {
        'count': len(msks),
        'msks': msks,
        'measure_ids': list(mids)[:50],
        'numbers_count': len(numbers),
        'rows': 0 if df is None else len(df),
        'summary': _summary_from_df(df),
        'note': status,
    }


def _tool_list_last_msk(params, dpg_):
    spc = _norm(params.get('spc'))
    last_n = params.get('last_n') or 10
    try:
        last_n = int(last_n)
    except (TypeError, ValueError):
        last_n = 10
    last_n = max(1, min(last_n, 500))

    date_from = _norm(params.get('date_from'))
    date_to = _norm(params.get('date_to'))

    msks = get_archive_msk_list(spc)
    if not msks:
        return {
            'count': 0, 'msks': [],
            'note': f'МСК для спецификации {spc!r} не найдены' if spc
                    else 'Список МСК пуст',
        }

    # Сортировка по «свежести»: пытаемся взять max(Date) / max(Measure_ID)
    # через лёгкий запрос; при ошибке — хвост списка как есть.
    ranked = []
    try:
        from sqlalchemy import create_engine, text
        from Options import get_connection_string
        from Archive_View.Archive_Data import _main
        engine = create_engine(str(get_connection_string()))
        table = _main()
        cond = ['MSK IS NOT NULL']
        p: dict[str, Any] = {}
        if spc:
            cond.append('Spc = :spc')
            p['spc'] = spc
        if date_from:
            cond.append('Date >= :dfrom')
            p['dfrom'] = date_from
        if date_to:
            cond.append('Date <= :dto')
            p['dto'] = date_to
        where = ' AND '.join(cond)
        sql = text(
            f'SELECT MSK, MAX(Date) AS last_date, MAX(Measure_ID) AS last_mid '
            f'FROM `{table}` WHERE {where} '
            f'GROUP BY MSK ORDER BY last_date DESC, last_mid DESC '
            f'LIMIT :lim'
        )
        p['lim'] = last_n
        df_rank = pd.read_sql(sql, engine, params=p)
        ranked = [
            {
                'msk': str(r['MSK']),
                'last_date': str(r['last_date'] or '')[:16],
                'last_measure_id': int(r['last_mid'] or 0),
            }
            for _, r in df_rank.iterrows()
        ]
    except Exception as e:
        print(f'[archive_tools] list_last_msk rank: {e}')
        ranked = [{'msk': m, 'last_date': '', 'last_measure_id': 0}
                  for m in msks[-last_n:]]

    _ensure_archive_open(dpg_)
    if dpg.does_item_exist('archive_status_text'):
        dpg.set_value(
            'archive_status_text',
            f'Последние {len(ranked)} МСК'
            + (f' для {spc}' if spc else '')
            + (f' за {date_from}…{date_to or "…"}' if date_from else ''),
        )

    return {
        'count': len(ranked),
        'spc': spc,
        'last_n': last_n,
        'msks': [r['msk'] for r in ranked],
        'details': ranked,
        'date_from': date_from,
        'date_to': date_to,
    }


def _tool_load_archive(params, dpg_):
    msk = _norm(params.get('msk'))
    spc = _norm(params.get('spc'))
    measure_id = params.get('measure_id')
    numbers = _as_numbers(params.get('numbers'))
    date = _norm(params.get('date'))
    only_good = bool(params.get('only_good', False))
    mode_full = bool(params.get('mode_full_msk', False))
    mode = MODE_FULL_MSK if mode_full else MODE_ONLY_NUM

    if measure_id is not None:
        try:
            measure_id = int(measure_id)
        except (TypeError, ValueError):
            return {'error': f'measure_id должен быть int, получено {measure_id!r}'}

    if not any((msk, spc, measure_id, numbers)):
        return {
            'error': 'Нужна МСК, спецификация, ID замера или номера',
            'hint': 'Пример: «загрузи архив МСК 456»',
        }

    _ensure_archive_open(dpg_)
    _set_ui_selection(msk=msk, spc=spc, measure_id=measure_id, numbers=numbers)

    try:
        if numbers:
            mids = find_measure_ids_by_numbers(numbers, only_good=False)
            df = load_archive_by_numbers(
                numbers, mode, only_good=False, found_mids=mids or None,
            )
        elif measure_id:
            df = load_archive_data(measure_id=measure_id, only_good=False)
        else:
            df = load_archive_data(
                msk=msk, spc=spc, date=date, only_good=False,
            )

        if only_good and df is not None and not df.empty:
            try:
                from Archive_View.Archive_Helpers import _filter_good_only
                df = _filter_good_only(df, spc or '')
            except Exception as e:
                print(f'[archive_tools] only_good: {e}')

        summary = _summary_from_df(df)
        status = (
            f'Загружено: {summary["rows"]} строк | '
            f'Measure_ID: {summary["measure_ids"]} | '
            f'МСК: {summary["msk_count"]} | Spc: {summary["spc"] or "-"}'
        )
        _fill_ui_from_df(df, status)

        if df is None or df.empty:
            return {
                'count': 0, 'rows': 0,
                'note': 'Данные не найдены по заданным фильтрам',
                'filters': {
                    'msk': msk, 'spc': spc, 'measure_id': measure_id,
                    'numbers': numbers[:20] if numbers else None, 'date': date,
                },
            }

        return {
            'count': summary['rows'],
            'rows': summary['rows'],
            'summary': summary,
            'note': status,
        }
    except Exception as e:
        traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}


def _tool_print_archive_protocols(params, dpg_):
    """Печать протоколов измерений для текущей выборки или по параметрам."""
    msk = _norm(params.get('msk'))
    spc = _norm(params.get('spc'))
    numbers = _as_numbers(params.get('numbers'))
    measure_id = params.get('measure_id')
    last_n = params.get('last_n')

    _ensure_archive_open(dpg_)

    # Если заданы фильтры — сначала загружаем
    if msk or numbers or measure_id or (spc and last_n):
        if spc and last_n and not msk and not numbers and not measure_id:
            listed = _tool_list_last_msk(
                {'spc': spc, 'last_n': last_n}, dpg_,
            )
            msk_list = listed.get('msks') or []
            if not msk_list:
                return listed
            frames = []
            for m in msk_list:
                sub = load_archive_data(msk=m, spc=spc, only_good=False)
                if sub is not None and not sub.empty:
                    frames.append(sub)
            df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            _fill_ui_from_df(df, f'Для печати: {len(msk_list)} МСК, {len(df)} строк')
        else:
            load_res = _tool_load_archive({
                'msk': msk, 'spc': spc, 'numbers': numbers,
                'measure_id': measure_id,
            }, dpg_)
            if load_res.get('error') or load_res.get('rows', 0) == 0:
                return load_res

    if not dpg.does_item_exist(WINDOW_TAG):
        return {'error': 'Окно архива не открыто'}

    df = dpg.get_item_user_data(WINDOW_TAG)
    if df is None or (hasattr(df, 'empty') and df.empty):
        return {
            'error': 'Нет данных для печати',
            'hint': 'Сначала загрузите: «загрузи архив МСК 456»',
        }

    try:
        from Archive_View.Archive_Print import print_archive_protocol
        print_archive_protocol()
        summary = _summary_from_df(df)
        return {
            'action': 'printed',
            'summary': summary,
            'note': (
                f'Печать протоколов: {summary["measure_ids"]} замер(ов), '
                f'{summary["rows"]} строк'
            ),
        }
    except Exception as e:
        traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}


def _tool_export_archive_xls(params, dpg_):
    """Экспорт в XLS: текущая выборка или по фильтрам / последним МСК / периоду."""
    msk = _norm(params.get('msk'))
    spc = _norm(params.get('spc'))
    numbers = _as_numbers(params.get('numbers'))
    measure_id = params.get('measure_id')
    last_n = params.get('last_n')
    date = _norm(params.get('date'))
    date_from = _norm(params.get('date_from'))
    date_to = _norm(params.get('date_to'))

    _ensure_archive_open(dpg_)

    need_load = bool(msk or numbers or measure_id or spc or date_from or last_n)
    if need_load:
        if last_n and spc and not msk and not numbers:
            listed = _tool_list_last_msk({
                'spc': spc, 'last_n': last_n,
                'date_from': date_from, 'date_to': date_to,
            }, dpg_)
            msk_list = listed.get('msks') or []
            if not msk_list:
                return listed
            frames = []
            for m in msk_list:
                sub = load_archive_data(
                    msk=m, spc=spc, only_good=False,
                )
                if sub is not None and not sub.empty:
                    if date_from or date_to:
                        if 'Date' in sub.columns:
                            if date_from:
                                sub = sub[sub['Date'].astype(str) >= date_from]
                            if date_to:
                                sub = sub[sub['Date'].astype(str) <= date_to]
                    if not sub.empty:
                        frames.append(sub)
            df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            _fill_ui_from_df(
                df,
                f'Экспорт: {len(msk_list)} МСК, {len(df)} строк',
            )
        elif date_from and spc and not msk:
            # все МСК спецификации за период
            msk_list = get_archive_msk_list(spc)
            frames = []
            for m in msk_list:
                sub = load_archive_data(msk=m, spc=spc, only_good=False)
                if sub is None or sub.empty or 'Date' not in sub.columns:
                    continue
                if date_from:
                    sub = sub[sub['Date'].astype(str) >= date_from]
                if date_to:
                    sub = sub[sub['Date'].astype(str) <= date_to]
                if not sub.empty:
                    frames.append(sub)
            df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
            _fill_ui_from_df(df, f'Экспорт за период: {len(df)} строк')
        else:
            load_res = _tool_load_archive({
                'msk': msk, 'spc': spc, 'numbers': numbers,
                'measure_id': measure_id, 'date': date,
            }, dpg_)
            if load_res.get('error'):
                return load_res
            if load_res.get('rows', 0) == 0:
                return load_res

    if not dpg.does_item_exist(WINDOW_TAG):
        return {'error': 'Окно архива не открыто'}

    df = dpg.get_item_user_data(WINDOW_TAG)
    if df is None or (hasattr(df, 'empty') and df.empty):
        return {
            'error': 'Нет данных для экспорта',
            'hint': 'Сначала загрузите данные или укажите МСК/номера/спецификацию',
        }

    try:
        from Archive_View.Archive_Export import export_archive_to_excel
        export_archive_to_excel()
        summary = _summary_from_df(df)
        # путь из статуса, если успели записать
        path_hint = ''
        if dpg.does_item_exist('archive_status_text'):
            path_hint = dpg.get_value('archive_status_text') or ''
        return {
            'action': 'exported',
            'summary': summary,
            'note': path_hint or (
                f'Excel: {summary["rows"]} строк, '
                f'{summary["measure_ids"]} замер(ов)'
            ),
        }
    except Exception as e:
        traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}


# =========================================================================
# Dispatch / format
# =========================================================================

_TOOLS = {
    'open_archive': _tool_open_archive,
    'search_msk': _tool_search_msk,
    'list_msk_by_numbers': _tool_list_msk_by_numbers,
    'list_last_msk': _tool_list_last_msk,
    'load_archive': _tool_load_archive,
    'print_archive_protocols': _tool_print_archive_protocols,
    'export_archive_xls': _tool_export_archive_xls,
}


def execute(name: str, params: dict, dpg_) -> dict:
    fn = _TOOLS.get(name)
    if not fn:
        return {'error': f'Неизвестный инструмент архива: {name}'}
    try:
        return fn(params or {}, dpg_)
    except Exception as e:
        traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}


def format_result(name: str, res: dict) -> str:
    if not isinstance(res, dict):
        return f'[Archive] {res}'
    if res.get('error'):
        hint = res.get('hint')
        msg = f"[ERR] Архив / {name}: {res['error']}"
        if hint:
            msg += f'\n  → {hint}'
        return msg

    if name == 'open_archive':
        st = res.get('status', '')
        loaded = res.get('loaded')
        if loaded and not loaded.get('error'):
            return (
                f"[OK] Архив открыт ({st}). "
                f"{loaded.get('note') or format_result('load_archive', loaded)}"
            )
        return f"[OK] Архив: {st}. {res.get('note') or ''}".strip()

    if name == 'search_msk':
        msks = res.get('msks') or []
        head = ', '.join(msks[:15])
        more = f' … (+{len(msks) - 15})' if len(msks) > 15 else ''
        return (
            f"[OK] Поиск МСК «{res.get('partial') or ''}»: "
            f"{res.get('count', 0)} шт.\n  {head}{more}\n  {res.get('note') or ''}"
        ).strip()

    if name == 'list_msk_by_numbers':
        msks = res.get('msks') or []
        head = ', '.join(msks[:20])
        return (
            f"[OK] МСК по номерам: {res.get('count', 0)}\n"
            f"  {head}\n  {res.get('note') or ''}"
        ).strip()

    if name == 'list_last_msk':
        lines = []
        for d in (res.get('details') or [])[:20]:
            lines.append(
                f"  {d.get('msk')}  date={d.get('last_date') or '-'}  "
                f"mid={d.get('last_measure_id') or '-'}"
            )
        return (
            f"[OK] Последние {res.get('count', 0)} МСК"
            + (f" для {res.get('spc')}" if res.get('spc') else '')
            + ':\n' + '\n'.join(lines)
        )

    if name == 'load_archive':
        s = res.get('summary') or {}
        return (
            f"[OK] Загрузка архива: {res.get('rows', 0)} строк | "
            f"Measure_ID: {s.get('measure_ids', 0)} | "
            f"МСК: {s.get('msk_count', 0)}\n"
            f"  МСК: {', '.join((s.get('msks') or [])[:10])}\n"
            f"  {res.get('note') or ''}"
        ).strip()

    if name in ('print_archive_protocols', 'export_archive_xls'):
        return f"[OK] {res.get('note') or res.get('action') or name}"

    return f"[OK] Архив / {name}: {res.get('note') or res}"
