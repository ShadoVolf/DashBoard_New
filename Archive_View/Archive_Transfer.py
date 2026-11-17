"""Переносы: temp→main (overwrite), main→archive (with verification),
restore архивирования."""
import json
import traceback

import pandas as pd
from sqlalchemy import create_engine, text

import Options
from .Archive_ActionsLog import (
    insert_log, update_status, mark_restored, get_log_entry,
    ACTION_ARCHIVE, ACTION_OVERWRITE,
)


def _engine():
    return create_engine(str(Options.get_connection_string()))

# Первичные ключи таблиц, чтобы корректно пропускать их при INSERT
_PK = {
    'psidata':                'ID',
    'psidata_archive':        'ID',
    'psidata_temporary':      'ID',
    'psidatatemp':            'RecordId',
    'psidatatemp_archive':    'RecordId',
    'psidatatemp_temporary':  'RecordId',
}


def _pk_of(table: str) -> str:
    return _PK.get(table, 'ID')


def _read_rows(engine, table, *, msk=None, measure_id=None,
               measure_id_from=None, measure_id_to=None,
               n_from=None, n_to=None) -> pd.DataFrame:
    cond, params = [], {}
    if msk:
        cond.append("MSK = :msk"); params['msk'] = msk
    if measure_id:
        cond.append("Measure_ID = :mid"); params['mid'] = int(measure_id)
    if measure_id_from is not None:
        cond.append("Measure_ID >= :mfrom"); params['mfrom'] = int(measure_id_from)
    if measure_id_to is not None:
        cond.append("Measure_ID <= :mto"); params['mto'] = int(measure_id_to)
    if n_from:
        cond.append("N >= :nfrom"); params['nfrom'] = str(n_from).strip().upper()
    if n_to:
        cond.append("N <= :nto");   params['nto']   = str(n_to).strip().upper()
    where = " AND ".join(cond) if cond else "1=1"
    return pd.read_sql(text(f"SELECT * FROM `{table}` WHERE {where}"),
                       engine, params=params)


def _delete_rows(engine, table, **kw) -> int:
    cond, params = [], {}
    if kw.get('msk'):
        cond.append("MSK = :msk"); params['msk'] = kw['msk']
    if kw.get('measure_id'):
        cond.append("Measure_ID = :mid"); params['mid'] = int(kw['measure_id'])
    if kw.get('measure_id_from') is not None:
        cond.append("Measure_ID >= :mfrom"); params['mfrom'] = int(kw['measure_id_from'])
    if kw.get('measure_id_to') is not None:
        cond.append("Measure_ID <= :mto"); params['mto'] = int(kw['measure_id_to'])
    if kw.get('n_from'):
        cond.append("N >= :nfrom"); params['nfrom'] = str(kw['n_from']).strip().upper()
    if kw.get('n_to'):
        cond.append("N <= :nto");   params['nto']   = str(kw['n_to']).strip().upper()
    if not cond:
        return 0
    sql = text(f"DELETE FROM `{table}` WHERE " + " AND ".join(cond))
    with engine.begin() as conn:
        return int(conn.execute(sql, params).rowcount or 0)


def _delete_by_id_range(engine, table, start, end) -> int:
    if start is None or end is None:
        return 0
    pk = _pk_of(table)
    sql = text(f"DELETE FROM `{table}` WHERE `{pk}` BETWEEN :s AND :e")
    with engine.begin() as conn:
        return int(conn.execute(sql, {'s': int(start), 'e': int(end)}).rowcount or 0)


def _insert_rows(engine, table, df, skip_id=False):
    """Возвращает (count, start_id, end_id). skip_id=True — PK-колонка
    (ID / RecordId) из df игнорируется, значение назначается AUTO_INCREMENT."""
    if df is None or df.empty:
        return 0, None, None

    pk = _pk_of(table)
    cols = [c for c in df.columns if not (skip_id and c == pk)]
    if not cols:
        return 0, None, None

    ph = ', '.join([f':p{i}' for i in range(len(cols))])
    cl = ', '.join([f'`{c}`' for c in cols])
    stmt = text(f"INSERT INTO `{table}` ({cl}) VALUES ({ph})")

    inserted = 0
    last_id = None
    with engine.begin() as conn:
        for _, r in df.iterrows():
            params = {}
            for i, c in enumerate(cols):
                v = r.get(c)
                if pd.isna(v):
                    v = None
                params[f'p{i}'] = v
            conn.execute(stmt, params)
            inserted += 1
        if inserted and skip_id:
            last_id = conn.execute(text("SELECT LAST_INSERT_ID()")).scalar()

    if skip_id and inserted and last_id is not None:
        start = int(last_id) - inserted + 1
        return inserted, start, int(last_id)
    return inserted, None, None


# =========================================================================
# Overwrite: temp → main
# =========================================================================
def overwrite_temp_to_main(msk: str, measure_id: int) -> dict:
    if not msk or not measure_id:
        return {'ok': False, 'error': 'Не указаны MSK/Measure_ID'}
    engine = _engine()
    try:
        df_main = _read_rows(engine, 'psidata_temporary',
                             msk=msk, measure_id=measure_id)
        df_temp = _read_rows(engine, 'psidatatemp_temporary',
                             msk=msk, measure_id=measure_id)
        if df_main.empty and df_temp.empty:
            return {'ok': False,
                    'error': 'Во временной таблице нет данных'}

        existing_main = _read_rows(engine, 'psidata',
                                   msk=msk, measure_id=measure_id)
        existing_temp = _read_rows(engine, 'psidatatemp',
                                   msk=msk, measure_id=measure_id)
        exists_in_main = (not existing_main.empty) or (not existing_temp.empty)

        if exists_in_main:
            # В основной уже есть данные этого замера — только чистим временную
            d1 = _delete_rows(engine, 'psidata_temporary',
                              msk=msk, measure_id=measure_id)
            d2 = _delete_rows(engine, 'psidatatemp_temporary',
                              msk=msk, measure_id=measure_id)
            log_id = insert_log(
                ACTION_OVERWRITE,
                'psidata_temporary', 'psidata',
                temp_source='psidatatemp_temporary', temp_target='psidatatemp',
                msk=msk, measure_id=measure_id,
                rows_main=existing_main.to_dict('records')
                          if not existing_main.empty else [],
                rows_temp=existing_temp.to_dict('records')
                          if not existing_temp.empty else [],
                status='completed',
                notes=(f'в основной уже есть данные этого замера '
                       f'(main={len(existing_main)}, '
                       f'temp={len(existing_temp)}); '
                       f'временная очищена без переноса: '
                       f'main {d1}, temp {d2}'))
            return {'ok': True, 'mode': 'skipped_exists',
                    'log_id': log_id,
                    'main_inserted': 0, 'temp_inserted': 0,
                    'deleted_main': d1, 'deleted_temp': d2,
                    'existing_main': len(existing_main),
                    'existing_temp': len(existing_temp)}

        # В основной нет — переносим
        n_main, _, _ = _insert_rows(engine, 'psidata', df_main, skip_id=True)
        n_temp, _, _ = _insert_rows(engine, 'psidatatemp', df_temp, skip_id=True)

        _delete_rows(engine, 'psidata_temporary',
                     msk=msk, measure_id=measure_id)
        _delete_rows(engine, 'psidatatemp_temporary',
                     msk=msk, measure_id=measure_id)

        log_id = insert_log(
            ACTION_OVERWRITE,
            'psidata_temporary', 'psidata',
            temp_source='psidatatemp_temporary', temp_target='psidatatemp',
            msk=msk, measure_id=measure_id,
            rows_main=df_main.to_dict('records'),
            rows_temp=df_temp.to_dict('records'),
            status='completed',
            notes=f'перенесено main={n_main}, temp={n_temp}; '
                  f'временная очищена')

        return {'ok': True, 'mode': 'transferred',
                'log_id': log_id,
                'main_inserted': n_main, 'temp_inserted': n_temp,
                'deleted_main': len(df_main),
                'deleted_temp': len(df_temp),
                'existing_main': 0, 'existing_temp': 0}
    except Exception as e:
        traceback.print_exc()
        return {'ok': False, 'error': str(e)}


def overwrite_temp_to_main_1(msk: str, measure_id: int) -> dict:
    if not msk or not measure_id:
        return {'ok': False, 'error': 'Не указаны MSK/Measure_ID'}
    engine = _engine()
    try:
        df_main = _read_rows(engine, 'psidata_temporary',
                             msk=msk, measure_id=measure_id)
        df_temp = _read_rows(engine, 'psidatatemp_temporary',
                             msk=msk, measure_id=measure_id)
        if df_main.empty and df_temp.empty:
            return {'ok': False,
                    'error': 'Во временной таблице нет данных'}

        existing_main = _read_rows(engine, 'psidata',
                                   msk=msk, measure_id=measure_id)
        existing_temp = _read_rows(engine, 'psidatatemp',
                                   msk=msk, measure_id=measure_id)

        _delete_rows(engine, 'psidata', msk=msk, measure_id=measure_id)
        _delete_rows(engine, 'psidatatemp', msk=msk, measure_id=measure_id)

        n_main, _, _ = _insert_rows(engine, 'psidata', df_main, skip_id=True)
        n_temp, _, _ = _insert_rows(engine, 'psidatatemp', df_temp, skip_id=True)

        _delete_rows(engine, 'psidata_temporary',
                     msk=msk, measure_id=measure_id)
        _delete_rows(engine, 'psidatatemp_temporary',
                     msk=msk, measure_id=measure_id)

        log_id = insert_log(
            ACTION_OVERWRITE,
            'psidata_temporary', 'psidata',
            temp_source='psidatatemp_temporary', temp_target='psidatatemp',
            msk=msk, measure_id=measure_id,
            rows_main=existing_main.to_dict('records') if not existing_main.empty else [],
            rows_temp=existing_temp.to_dict('records') if not existing_temp.empty else [],
            status='completed',
            notes=(f'заменено main={len(existing_main)}, temp={len(existing_temp)}; '
                   f'вставлено main={n_main}, temp={n_temp}'))

        return {'ok': True, 'log_id': log_id,
                'main_inserted': n_main, 'temp_inserted': n_temp,
                'main_replaced': len(existing_main),
                'temp_replaced': len(existing_temp)}
    except Exception as e:
        traceback.print_exc()
        return {'ok': False, 'error': str(e)}


# =========================================================================
# Archive: main → archive (с верификацией)
# =========================================================================

def archive_main_to_archive(msk: str, *,
                            measure_id=None,
                            measure_id_from=None, measure_id_to=None,
                            n_from=None, n_to=None) -> dict:
    if not msk:
        return {'ok': False, 'error': 'Не указан МСК'}
    if measure_id is None and measure_id_from is None and measure_id_to is None:
        return {'ok': False, 'error': 'Укажите Measure_ID или диапазон'}
    if (measure_id_from is not None and measure_id_to is not None
            and int(measure_id_from) > int(measure_id_to)):
        return {'ok': False, 'error': 'Начало диапазона > конца'}

    engine = _engine()
    try:
        kw = dict(msk=msk, measure_id=measure_id,
                  measure_id_from=measure_id_from, measure_id_to=measure_id_to,
                  n_from=n_from, n_to=n_to)
        df_main = _read_rows(engine, 'psidata', **kw)
        df_temp = _read_rows(engine, 'psidatatemp', **kw)
        if df_main.empty and df_temp.empty:
            return {'ok': False, 'error': 'Нет данных для архивирования'}

        n_main, tm_s, tm_e = _insert_rows(engine, 'psidata_archive', df_main,
                                          skip_id=True)
        n_temp, tt_s, tt_e = _insert_rows(engine, 'psidatatemp_archive',
                                          df_temp, skip_id=True)

        if n_main != len(df_main) or n_temp != len(df_temp):
            return {'ok': False, 'error':
                    f'Верификация insert: main {n_main}/{len(df_main)}, '
                    f'temp {n_temp}/{len(df_temp)} — удаление отменено'}

        log_id = insert_log(
            ACTION_ARCHIVE, 'psidata', 'psidata_archive',
            temp_source='psidatatemp', temp_target='psidatatemp_archive',
            msk=msk, measure_id=measure_id,
            measure_id_from=measure_id_from, measure_id_to=measure_id_to,
            n_from=n_from, n_to=n_to,
            rows_main=df_main.to_dict('records'),
            rows_temp=df_temp.to_dict('records'),
            target_main_ids=(tm_s, tm_e),
            target_temp_ids=(tt_s, tt_e),
            status='archived_pending_delete',
            notes='Данные перенесены в архив, удаление из основной ожидает')

        entry = get_log_entry(log_id)
        if not entry or entry.get('status') != 'archived_pending_delete':
            return {'ok': False,
                    'error': 'Журнал отката не подтверждён — удаление отменено',
                    'log_id': log_id}

        del_main = _delete_rows(engine, 'psidata', **kw)
        del_temp = _delete_rows(engine, 'psidatatemp', **kw)

        update_status(log_id, 'completed',
                      notes=(f'Архивировано main={n_main}, temp={n_temp}; '
                             f'удалено main={del_main}, temp={del_temp}'))
        return {'ok': True, 'log_id': log_id,
                'archived_main': n_main, 'archived_temp': n_temp,
                'deleted_main': del_main, 'deleted_temp': del_temp}
    except Exception as e:
        traceback.print_exc()
        return {'ok': False, 'error': str(e)}


# =========================================================================
# Restore архивирования
# =========================================================================

def restore_archive(log_id: int) -> dict:
    entry = get_log_entry(log_id)
    if not entry:
        return {'ok': False, 'error': 'Запись журнала не найдена'}
    if entry['action'] != ACTION_ARCHIVE:
        return {'ok': False, 'error': 'Откат доступен только для archive'}
    if entry['restored']:
        return {'ok': False, 'error': 'Уже восстановлено'}
    if entry['status'] not in ('completed', 'archived_pending_delete'):
        return {'ok': False,
                'error': f"Статус {entry['status']} не допускает откат"}

    try:
        rows_main = json.loads(entry['row_data'] or '[]')
        rows_temp = json.loads(entry['temp_data'] or '[]')
    except Exception as e:
        return {'ok': False, 'error': f'JSON: {e}'}

    engine = _engine()
    try:
        df_main = pd.DataFrame(rows_main)
        df_temp = pd.DataFrame(rows_temp)
        n_main, _, _ = _insert_rows(engine, 'psidata', df_main, skip_id=True)
        n_temp, _, _ = _insert_rows(engine, 'psidatatemp', df_temp, skip_id=True)

        _delete_by_id_range(engine, 'psidata_archive',
                            entry.get('target_main_id_start'),
                            entry.get('target_main_id_end'))
        _delete_by_id_range(engine, 'psidatatemp_archive',
                            entry.get('target_temp_id_start'),
                            entry.get('target_temp_id_end'))

        mark_restored(log_id)
        return {'ok': True, 'log_id': log_id,
                'restored_main': n_main, 'restored_temp': n_temp}
    except Exception as e:
        traceback.print_exc()
        return {'ok': False, 'error': str(e)}


# =========================================================================
# Очистка временных таблиц
# =========================================================================

def _delete_all(engine, table) -> int:
    with engine.begin() as conn:
        return int(conn.execute(text(f"DELETE FROM `{table}`")).rowcount or 0)


def clear_temp_tables() -> dict:
    """Полностью очищает psidata_temporary и psidatatemp_temporary."""
    engine = _engine()
    try:
        with engine.connect() as conn:
            n1 = int(conn.execute(text(
                "SELECT COUNT(*) FROM `psidata_temporary`")).scalar() or 0)
            n2 = int(conn.execute(text(
                "SELECT COUNT(*) FROM `psidatatemp_temporary`")).scalar() or 0)

        d1 = _delete_all(engine, 'psidata_temporary')
        d2 = _delete_all(engine, 'psidatatemp_temporary')

        log_id = insert_log(
            'clear_temp',
            'psidata_temporary', 'psidata_temporary',
            temp_source='psidatatemp_temporary',
            temp_target='psidatatemp_temporary',
            status='completed',
            notes=(f'очищено psidata_temporary {d1} (было {n1}); '
                   f'psidatatemp_temporary {d2} (было {n2})'))

        return {'ok': True, 'log_id': log_id,
                'deleted_main': d1, 'deleted_temp': d2,
                'was_main': n1, 'was_temp': n2}
    except Exception as e:
        traceback.print_exc()
        return {'ok': False, 'error': str(e)}


# =========================================================================
# Структурная синхронизация — обёртка
# =========================================================================

def sync_structures() -> list[str]:
    from .Archive_TableSync import sync_table_structure
    return sync_table_structure()