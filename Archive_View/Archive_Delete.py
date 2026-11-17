"""Удаление номеров резонаторов из замера с журналированием и восстановлением.

Схема psidata_deleted_resonators_log:
    id, measure_id, msk, n_number, operator, deleted_at,
    restored(0/1), restored_at, restored_by,
    row_data — JSON со списком полных исходных строк psidata.
"""
import json
import os
import traceback
from datetime import datetime

import pandas as pd
import dearpygui.dearpygui as dpg
from sqlalchemy import create_engine, text, bindparam

import Options
from .Archive_Constants import WINDOW_TAG
from .Archive_Data import parse_numbers_input


LOG_TABLE = 'psidata_deleted_resonators_log'
LOG_WINDOW_TAG = 'archive_delete_log_window'
DELETE_DIALOG_TAG = 'archive_delete_dialog'
LOG_TABLE_GROUP = 'archive_log_table_group'


def _engine():
    return create_engine(str(Options.get_connection_string()))


def _get_operator() -> str:
    """Имя оператора для журнала.

    Пытается взять из Options (get_operator / operator / ...), иначе —
    системный логин, иначе 'unknown'.
    """
    for name in ('get_operator', 'get_operator_name', 'get_user'):
        fn = getattr(Options, name, None)
        if callable(fn):
            try:
                v = fn()
                if v:
                    return str(v)
            except Exception:
                pass
    for attr in ('operator', 'Operator', 'user_name', 'OPERATOR'):
        v = getattr(Options, attr, None)
        if v:
            return str(v)
    try:
        return os.getlogin()
    except Exception:
        return 'unknown'


def ensure_log_table():
    """Создаёт таблицу журнала, если её нет."""
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{LOG_TABLE}` (
                `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `measure_id` INT NOT NULL,
                `msk` VARCHAR(64) DEFAULT NULL,
                `n_number` VARCHAR(64) NOT NULL,
                `operator` VARCHAR(128) DEFAULT NULL,
                `deleted_at` DATETIME NOT NULL,
                `restored` TINYINT NOT NULL DEFAULT 0,
                `restored_at` DATETIME DEFAULT NULL,
                `restored_by` VARCHAR(128) DEFAULT NULL,
                `row_data` LONGTEXT,
                PRIMARY KEY (`id`),
                KEY `idx_mid` (`measure_id`),
                KEY `idx_n` (`n_number`),
                KEY `idx_restored` (`restored`),
                KEY `idx_deleted_at` (`deleted_at`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))


def _to_clean_record(rec: dict) -> dict:
    """Убирает NaN/Timestamp/None из записи для JSON."""
    clean = {}
    for k, v in rec.items():
        if v is None:
            clean[k] = None
            continue
        try:
            if pd.isna(v):
                clean[k] = None
                continue
        except (TypeError, ValueError):
            pass
        if isinstance(v, (pd.Timestamp, datetime)):
            clean[k] = (v.isoformat(sep=' ') if hasattr(v, 'isoformat')
                        else str(v))
        else:
            clean[k] = v
    return clean


# ===========================================================================
# Удаление
# ===========================================================================

def delete_resonators(measure_id: int, numbers: list[str]) -> dict:
    """Удаляет номера резонаторов из замера с логированием.

    Возвращает {'ok', 'deleted_rows', 'logged_numbers',
                'measure_id', 'numbers'} либо {'ok': False, 'error': ...}.
    """
    if not measure_id or not numbers:
        return {'ok': False, 'error': 'Не указан Measure_ID или номера'}

    numbers_norm = [str(n).strip().upper() for n in numbers if str(n).strip()]
    if not numbers_norm:
        return {'ok': False, 'error': 'Список номеров пуст'}

    ensure_log_table()
    engine = _engine()
    operator = _get_operator()

    # 1) Читаем строки, которые собираемся удалить
    try:
        sql = text(
            "SELECT * FROM psidata "
            "WHERE Measure_ID = :mid AND UPPER(TRIM(N)) IN :nums"
        ).bindparams(bindparam("nums", expanding=True))
        df = pd.read_sql(sql, engine,
                         params={'mid': int(measure_id), 'nums': numbers_norm})
    except Exception as e:
        traceback.print_exc()
        return {'ok': False, 'error': f'Ошибка чтения: {e}'}

    if df is None or df.empty:
        return {'ok': False, 'error': 'Нет строк для удаления'}

    msk_val = None
    if 'MSK' in df.columns:
        uniq = [str(x) for x in df['MSK'].dropna().unique() if str(x).strip()]
        if uniq:
            msk_val = uniq[0]

    logged = 0
    deleted = 0
    try:
        with engine.begin() as conn:
            # 2) Логируем по каждому N
            n_series = df['N'].astype(str).str.strip().str.upper()
            for n_val, group in df.groupby(n_series):
                records = [_to_clean_record(r) for r in
                           group.to_dict('records')]
                row_json = json.dumps(records, ensure_ascii=False,
                                      default=str)
                conn.execute(text(f"""
                    INSERT INTO `{LOG_TABLE}`
                    (measure_id, msk, n_number, operator, deleted_at, row_data)
                    VALUES (:mid, :msk, :n, :op, :dt, :data)
                """), {
                    'mid': int(measure_id),
                    'msk': msk_val,
                    'n': str(n_val),
                    'op': operator,
                    'dt': datetime.now(),
                    'data': row_json,
                })
                logged += 1

            # 3) Удаляем из psidata
            del_sql = text(
                "DELETE FROM psidata "
                "WHERE Measure_ID = :mid AND UPPER(TRIM(N)) IN :nums"
            ).bindparams(bindparam("nums", expanding=True))
            res = conn.execute(del_sql,
                               {'mid': int(measure_id),
                                'nums': numbers_norm})
            deleted = int(res.rowcount or 0)
    except Exception as e:
        traceback.print_exc()
        return {'ok': False, 'error': f'Ошибка удаления: {e}'}

    return {
        'ok': True,
        'deleted_rows': deleted,
        'logged_numbers': logged,
        'measure_id': int(measure_id),
        'numbers': numbers_norm,
    }


# ===========================================================================
# Восстановление
# ===========================================================================

def restore_log_entry(log_id: int) -> dict:
    """Восстанавливает удалённые строки по записи журнала."""
    if log_id is None:
        return {'ok': False, 'error': 'Не указан ID записи журнала'}
    try:
        log_id = int(log_id)
    except (TypeError, ValueError):
        return {'ok': False, 'error': f'Некорректный ID записи: {log_id!r}'}
    ensure_log_table()
    engine = _engine()
    operator = _get_operator()

    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                f"SELECT measure_id, n_number, restored, row_data "
                f"FROM `{LOG_TABLE}` WHERE id = :id"
            ), {'id': int(log_id)}).fetchone()
    except Exception as e:
        traceback.print_exc()
        return {'ok': False, 'error': f'Ошибка чтения журнала: {e}'}

    if not row:
        return {'ok': False, 'error': f'Запись id={log_id} не найдена'}
    if row[2]:
        return {'ok': False, 'error': 'Эта запись уже восстановлена'}

    try:
        records = json.loads(row[3] or '[]')
    except Exception as e:
        return {'ok': False, 'error': f'Ошибка разбора JSON: {e}'}

    if not records:
        return {'ok': False, 'error': 'Пустые данные для восстановления'}

    measure_id = int(row[0])
    n_number = str(row[1])

    restored = 0
    try:
        with engine.begin() as conn:
            for rec in records:
                # id не восстанавливаем (автоинкремент), остальные — как были
                cols = [c for c in rec.keys() if c != 'id']
                if not cols:
                    continue
                col_list = ', '.join([f'`{c}`' for c in cols])
                placeholders = ', '.join([f':p{i}' for i in range(len(cols))])
                params = {f'p{i}': rec[c] for i, c in enumerate(cols)}
                conn.execute(text(
                    f"INSERT INTO psidata ({col_list}) "
                    f"VALUES ({placeholders})"
                ), params)
                restored += 1

            conn.execute(text(f"""
                UPDATE `{LOG_TABLE}`
                SET restored = 1, restored_at = :dt, restored_by = :op
                WHERE id = :id
            """), {'dt': datetime.now(), 'op': operator, 'id': int(log_id)})
    except Exception as e:
        traceback.print_exc()
        return {'ok': False, 'error': f'Ошибка восстановления: {e}'}

    return {
        'ok': True,
        'measure_id': measure_id,
        'n_number': n_number,
        'rows_restored': restored,
    }


# ===========================================================================
# UI: диалог удаления
# ===========================================================================

def _current_measure_id():
    """Measure_ID из текущего контекста (input → единственная в выборке)."""
    if dpg.does_item_exist('archive_measure_id_input'):
        v = dpg.get_value('archive_measure_id_input')
        try:
            mid = int(str(v).strip())
            if mid > 0:
                return mid
        except (TypeError, ValueError):
            pass

    df = dpg.get_item_user_data(WINDOW_TAG)
    if df is not None and not df.empty and 'Measure_ID' in df.columns:
        uniq = df['Measure_ID'].dropna().unique()
        if len(uniq) == 1:
            try:
                return int(uniq[0])
            except (TypeError, ValueError):
                pass
    return None


def _current_msk():
    df = dpg.get_item_user_data(WINDOW_TAG)
    if df is not None and not df.empty and 'MSK' in df.columns:
        uniq = [str(x) for x in df['MSK'].dropna().unique() if str(x).strip()]
        if len(uniq) == 1:
            return uniq[0]
    return ''


def open_delete_dialog():
    """Модальный диалог удаления номеров."""
    if dpg.does_item_exist(DELETE_DIALOG_TAG):
        dpg.delete_item(DELETE_DIALOG_TAG)

    mid = _current_measure_id()
    msk = _current_msk()

    with dpg.window(label='Удаление номеров резонаторов',
                    tag=DELETE_DIALOG_TAG, modal=True,
                    width=520, height=360, no_collapse=True):
        dpg.add_text(f'Оператор: {_get_operator()}', color=(150, 200, 255))
        dpg.add_separator()
        if mid:
            dpg.add_text(f'Measure_ID: {mid}')
        else:
            dpg.add_text('Measure_ID не определён — введите вручную',
                         color=(255, 180, 100))
        dpg.add_input_int(label='Measure_ID', tag='archive_delete_mid',
                          default_value=mid or 0, width=150)
        if msk:
            dpg.add_text(f'МСК: {msk}')
        dpg.add_separator()
        dpg.add_text('Номера для удаления '
                     '(одиночный / список / диапазон):')
        dpg.add_input_text(
            tag='archive_delete_numbers', width=-1,
            hint="JN4450  |  JN4450,JN4451  |  JN4450-JN4460")
        dpg.add_spacer(height=8)
        dpg.add_text('', tag='archive_delete_status',
                     color=(255, 180, 100), wrap=500)
        dpg.add_spacer(height=10)
        with dpg.group(horizontal=True):
            dpg.add_button(label='Удалить', width=130,
                           callback=lambda s, a: _on_confirm_delete())
            dpg.add_button(label='Отмена', width=130,
                           callback=lambda s, a: dpg.delete_item(
                               DELETE_DIALOG_TAG))


def _on_confirm_delete():
    try:
        mid = int(dpg.get_value('archive_delete_mid'))
    except (TypeError, ValueError):
        dpg.set_value('archive_delete_status', 'Некорректный Measure_ID')
        return
    if mid <= 0:
        dpg.set_value('archive_delete_status', 'Measure_ID должен быть > 0')
        return

    raw = dpg.get_value('archive_delete_numbers') or ''
    nums = parse_numbers_input(raw)
    if not nums:
        dpg.set_value('archive_delete_status',
                      'Введите номера для удаления')
        return

    res = delete_resonators(mid, nums)
    if not res['ok']:
        dpg.set_value('archive_delete_status',
                      f"Ошибка: {res.get('error', '?')}")
        return

    dpg.set_value(
        'archive_delete_status',
        f"Удалено строк: {res['deleted_rows']}, "
        f"записей в журнале: {res['logged_numbers']}")

    _refresh_main_view()
    if dpg.does_item_exist(LOG_WINDOW_TAG):
        _refresh_log_table()


# ===========================================================================
# UI: журнал удалений
# ===========================================================================

def open_log_window():
    """Открывает окно журнала удалений / восстановления."""
    if dpg.does_item_exist(LOG_WINDOW_TAG):
        dpg.delete_item(LOG_WINDOW_TAG)

    ensure_log_table()
    prefill_mid = _current_measure_id()

    with dpg.window(label='Журнал удалений резонаторов',
                    tag=LOG_WINDOW_TAG, width=1100, height=650):
        with dpg.group(horizontal=True):
            dpg.add_text('Measure_ID:')
            dpg.add_input_text(
                tag='archive_log_filter_mid', width=100,
                default_value=str(prefill_mid) if prefill_mid else '')
            dpg.add_text('N:')
            dpg.add_input_text(tag='archive_log_filter_n', width=150)
            dpg.add_checkbox(label='Только не восстановленные',
                             tag='archive_log_filter_active',
                             default_value=True)
            dpg.add_button(label='Применить',
                           callback=lambda s, a: _refresh_log_table())
            dpg.add_button(label='Обновить',
                           callback=lambda s, a: _refresh_log_table())
        dpg.add_separator()
        dpg.add_text('', tag='archive_log_status', color=(150, 200, 255))
        dpg.add_separator()
        with dpg.group(tag=LOG_TABLE_GROUP):
            pass

    _refresh_log_table()


def _read_log_entries(measure_id=None, n_filter=None,
                      only_active=True, limit=500):
    ensure_log_table()
    engine = _engine()
    cond, params = [], {}
    if measure_id:
        cond.append("measure_id = :mid")
        params['mid'] = int(measure_id)
    if n_filter:
        cond.append("n_number LIKE :npat")
        params['npat'] = f"%{n_filter}%"
    if only_active:
        cond.append("restored = 0")
    where = " AND ".join(cond) if cond else "1=1"
    sql = text(
        f"SELECT id, measure_id, msk, n_number, operator, deleted_at, "
        f"restored, restored_at, restored_by "
        f"FROM `{LOG_TABLE}` WHERE {where} "
        f"ORDER BY deleted_at DESC, id DESC LIMIT {int(limit)}"
    )
    try:
        return pd.read_sql(sql, engine, params=params)
    except Exception as e:
        print(f"[Archive] log read error: {e}")
        return pd.DataFrame()


def _refresh_log_table():
    if not dpg.does_item_exist(LOG_TABLE_GROUP):
        return
    for ch in dpg.get_item_children(LOG_TABLE_GROUP, 1) or []:
        dpg.delete_item(ch)

    mid_str = (dpg.get_value('archive_log_filter_mid')
               if dpg.does_item_exist('archive_log_filter_mid') else '')
    try:
        mid = int(str(mid_str).strip()) if str(mid_str).strip() else None
    except ValueError:
        mid = None

    n_filter = (dpg.get_value('archive_log_filter_n')
                if dpg.does_item_exist('archive_log_filter_n') else '')
    n_filter = str(n_filter).strip() or None

    only_active = (dpg.get_value('archive_log_filter_active')
                   if dpg.does_item_exist('archive_log_filter_active')
                   else True)

    df = _read_log_entries(mid, n_filter, only_active)

    if dpg.does_item_exist('archive_log_status'):
        dpg.set_value('archive_log_status',
                      f'Записей: {len(df)}' if not df.empty else 'Записей нет')

    if df.empty:
        return

    with dpg.table(parent=LOG_TABLE_GROUP,
                   header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True,
                   resizable=True, scrollY=True, height=500,
                   policy=dpg.mvTable_SizingFixedFit):
        dpg.add_table_column(label='ID', width_fixed=True,
                             init_width_or_weight=60)
        dpg.add_table_column(label='Дата', width_fixed=True,
                             init_width_or_weight=140)
        dpg.add_table_column(label='Оператор', width_fixed=True,
                             init_width_or_weight=120)
        dpg.add_table_column(label='МСК', width_fixed=True,
                             init_width_or_weight=120)
        dpg.add_table_column(label='Measure_ID', width_fixed=True,
                             init_width_or_weight=90)
        dpg.add_table_column(label='N', width_fixed=True,
                             init_width_or_weight=100)
        dpg.add_table_column(label='Статус', width_fixed=True,
                             init_width_or_weight=110)
        dpg.add_table_column(label='Действие', width_fixed=True,
                             init_width_or_weight=140)

        for _, r in df.iterrows():
            with dpg.table_row():
                dpg.add_text(str(int(r['id'])))
                dt_val = r['deleted_at']
                dt_str = (dt_val.strftime('%Y-%m-%d %H:%M:%S')
                          if pd.notna(dt_val) and hasattr(dt_val, 'strftime')
                          else (str(dt_val) if pd.notna(dt_val) else ''))
                dpg.add_text(dt_str)
                dpg.add_text(str(r['operator'] or ''))
                dpg.add_text(str(r['msk'] or ''))
                mid_v = r['measure_id']
                dpg.add_text(str(int(mid_v)) if pd.notna(mid_v) else '')
                dpg.add_text(str(r['n_number'] or ''))
                if r['restored']:
                    dpg.add_text('восстановлен', color=(140, 220, 140))
                else:
                    dpg.add_text('удалён', color=(255, 180, 100))
                if not r['restored']:
                    lid = int(r['id'])
                    dpg.add_button(
                        label='Восстановить',
                        callback=_on_restore,
                        user_data=lid)
                else:
                    dpg.add_text('')

def _on_restore(sender=None, app_data=None, user_data=None):
    log_id = user_data
    if log_id is None:
        dpg.set_value('archive_log_status',
                      'Не указан ID записи журнала')
        return
    res = restore_log_entry(log_id)
    if not res['ok']:
        dpg.set_value('archive_log_status',
                      f"Ошибка восстановления: {res.get('error', '?')}")
        return
    dpg.set_value(
        'archive_log_status',
        f"Восстановлено: N={res['n_number']}, "
        f"строк: {res['rows_restored']}")
    _refresh_log_table()
    _refresh_main_view()


# ===========================================================================
# Вспомогательные
# ===========================================================================

def _refresh_main_view():
    try:
        from .Archive_Cascade import reload_archive_data
        reload_archive_data()
    except Exception as e:
        print(f"[Archive] Не удалось обновить основное окно: {e}")


def _on_open_delete_dialog(sender=None, data=None):
    open_delete_dialog()


def _on_open_log_window(sender=None, data=None):
    open_log_window()