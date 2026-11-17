"""Журнал операций над таблицами архива/временной с возможностью отката."""
import json
import os
import traceback
from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, text

import Options

LOG_TABLE = 'psidata_actions_log'

ACTION_ARCHIVE   = 'archive'    # main → archive
ACTION_OVERWRITE = 'overwrite'  # temp → main
ACTION_RESTORE   = 'restore'


def _engine():
    return create_engine(str(Options.get_connection_string()))


def get_operator() -> str:
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
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{LOG_TABLE}` (
                `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `action` VARCHAR(32) NOT NULL,
                `source_table` VARCHAR(64) NOT NULL,
                `target_table` VARCHAR(64) NOT NULL,
                `temp_source` VARCHAR(64) DEFAULT NULL,
                `temp_target` VARCHAR(64) DEFAULT NULL,
                `msk` VARCHAR(50) DEFAULT NULL,
                `measure_id` INT DEFAULT NULL,
                `measure_id_from` INT DEFAULT NULL,
                `measure_id_to` INT DEFAULT NULL,
                `n_number` VARCHAR(64) DEFAULT NULL,
                `n_from` VARCHAR(64) DEFAULT NULL,
                `n_to` VARCHAR(64) DEFAULT NULL,
                `rows_main` INT NOT NULL DEFAULT 0,
                `rows_temp` INT NOT NULL DEFAULT 0,
                `target_main_id_start` BIGINT UNSIGNED DEFAULT NULL,
                `target_main_id_end`   BIGINT UNSIGNED DEFAULT NULL,
                `target_temp_id_start` BIGINT UNSIGNED DEFAULT NULL,
                `target_temp_id_end`   BIGINT UNSIGNED DEFAULT NULL,
                `operator` VARCHAR(128) DEFAULT NULL,
                `action_date` DATETIME NOT NULL,
                `status` VARCHAR(32) NOT NULL DEFAULT 'pending',
                `restored` TINYINT NOT NULL DEFAULT 0,
                `restored_at` DATETIME DEFAULT NULL,
                `restored_by` VARCHAR(128) DEFAULT NULL,
                `row_data` LONGTEXT,
                `temp_data` LONGTEXT,
                `notes` TEXT,
                PRIMARY KEY (`id`),
                KEY `idx_msk` (`msk`),
                KEY `idx_mid` (`measure_id`),
                KEY `idx_restored` (`restored`),
                KEY `idx_action` (`action`),
                KEY `idx_date` (`action_date`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """))


def _json_safe(records):
    out = []
    for rec in records:
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
        out.append(clean)
    return out

def _count_rows(v) -> int:
    """Кол-во записей: список → len, число → int, None → 0."""
    if v is None:
        return 0
    if isinstance(v, (list, tuple)):
        return len(v)
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def insert_log(action, source_table, target_table, *, msk=None,
               measure_id=None, measure_id_from=None, measure_id_to=None,
               n_number=None, n_from=None, n_to=None,
               rows_main=None, rows_temp=None,
               target_main_ids=None, target_temp_ids=None,
               temp_source=None, temp_target=None,
               status='pending', notes='') -> int:
    ensure_log_table()
    engine = _engine()
    row_json = (json.dumps(_json_safe(rows_main), ensure_ascii=False,
                           default=str) if rows_main is not None else None)
    temp_json = (json.dumps(_json_safe(rows_temp), ensure_ascii=False,
                            default=str) if rows_temp is not None else None)
    tm_start, tm_end = (target_main_ids or (None, None))
    tt_start, tt_end = (target_temp_ids or (None, None))

    # <-- ИСПРАВЛЕНИЕ: rows_main/rows_temp — списки записей, а не числа
    rows_main_count = _count_rows(rows_main)
    rows_temp_count = _count_rows(rows_temp)

    with engine.begin() as conn:
        res = conn.execute(text(f"""
            INSERT INTO `{LOG_TABLE}` (
                action, source_table, target_table, temp_source, temp_target,
                msk, measure_id, measure_id_from, measure_id_to,
                n_number, n_from, n_to,
                rows_main, rows_temp,
                target_main_id_start, target_main_id_end,
                target_temp_id_start, target_temp_id_end,
                operator, action_date, status, row_data, temp_data, notes
            ) VALUES (
                :action, :src, :tgt, :tsrc, :ttgt,
                :msk, :mid, :mfrom, :mto,
                :n, :nfrom, :nto,
                :rmain, :rtemp,
                :tm_s, :tm_e, :tt_s, :tt_e,
                :op, :dt, :status, :rdata, :tdata, :notes
            )
        """), {
            'action': action, 'src': source_table, 'tgt': target_table,
            'tsrc': temp_source, 'ttgt': temp_target,
            'msk': msk, 'mid': measure_id,
            'mfrom': measure_id_from, 'mto': measure_id_to,
            'n': n_number, 'nfrom': n_from, 'nto': n_to,
            'rmain': rows_main_count,
            'rtemp': rows_temp_count,
            'tm_s': tm_start, 'tm_e': tm_end,
            'tt_s': tt_start, 'tt_e': tt_end,
            'op': get_operator(), 'dt': datetime.now(),
            'status': status, 'rdata': row_json, 'tdata': temp_json,
            'notes': notes or '',
        })
        return int(res.lastrowid)

def insert_log_1(action, source_table, target_table, *, msk=None,
               measure_id=None, measure_id_from=None, measure_id_to=None,
               n_number=None, n_from=None, n_to=None,
               rows_main=None, rows_temp=None,
               target_main_ids=None, target_temp_ids=None,
               temp_source=None, temp_target=None,
               status='pending', notes='') -> int:
    ensure_log_table()
    engine = _engine()
    row_json = (json.dumps(_json_safe(rows_main), ensure_ascii=False,
                           default=str) if rows_main is not None else None)
    temp_json = (json.dumps(_json_safe(rows_temp), ensure_ascii=False,
                            default=str) if rows_temp is not None else None)
    tm_start, tm_end = (target_main_ids or (None, None))
    tt_start, tt_end = (target_temp_ids or (None, None))

    with engine.begin() as conn:
        res = conn.execute(text(f"""
            INSERT INTO `{LOG_TABLE}` (
                action, source_table, target_table, temp_source, temp_target,
                msk, measure_id, measure_id_from, measure_id_to,
                n_number, n_from, n_to,
                rows_main, rows_temp,
                target_main_id_start, target_main_id_end,
                target_temp_id_start, target_temp_id_end,
                operator, action_date, status, row_data, temp_data, notes
            ) VALUES (
                :action, :src, :tgt, :tsrc, :ttgt,
                :msk, :mid, :mfrom, :mto,
                :n, :nfrom, :nto,
                :rmain, :rtemp,
                :tm_s, :tm_e, :tt_s, :tt_e,
                :op, :dt, :status, :rdata, :tdata, :notes
            )
        """), {
            'action': action, 'src': source_table, 'tgt': target_table,
            'tsrc': temp_source, 'ttgt': temp_target,
            'msk': msk, 'mid': measure_id,
            'mfrom': measure_id_from, 'mto': measure_id_to,
            'n': n_number, 'nfrom': n_from, 'nto': n_to,
            'rmain': int(rows_main) if rows_main is not None else 0,
            'rtemp': int(rows_temp) if rows_temp is not None else 0,
            'tm_s': tm_start, 'tm_e': tm_end,
            'tt_s': tt_start, 'tt_e': tt_end,
            'op': get_operator(), 'dt': datetime.now(),
            'status': status, 'rdata': row_json, 'tdata': temp_json,
            'notes': notes or '',
        })
        return int(res.lastrowid)


def update_status(log_id: int, status: str, notes: str | None = None):
    ensure_log_table()
    engine = _engine()
    with engine.begin() as conn:
        if notes is None:
            conn.execute(text(
                f"UPDATE `{LOG_TABLE}` SET status = :s WHERE id = :i"),
                {'s': status, 'i': int(log_id)})
        else:
            conn.execute(text(
                f"UPDATE `{LOG_TABLE}` SET status = :s, notes = :n "
                f"WHERE id = :i"),
                {'s': status, 'n': notes, 'i': int(log_id)})


def mark_restored(log_id: int, by: str | None = None):
    ensure_log_table()
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(text(f"""
            UPDATE `{LOG_TABLE}`
            SET restored = 1, restored_at = :dt, restored_by = :by,
                status = 'restored'
            WHERE id = :i
        """), {'dt': datetime.now(), 'by': by or get_operator(),
               'i': int(log_id)})


def read_log(measure_id=None, msk=None, only_active=True,
             actions=None, limit=500) -> pd.DataFrame:
    ensure_log_table()
    engine = _engine()
    cond, params = [], {}
    if measure_id:
        cond.append("measure_id = :mid")
        params['mid'] = int(measure_id)
    if msk:
        cond.append("msk LIKE :msk")
        params['msk'] = f"%{msk}%"
    if only_active:
        cond.append("restored = 0")
    if actions:
        ph = ', '.join([f':a{i}' for i in range(len(actions))])
        cond.append(f"action IN ({ph})")
        for i, a in enumerate(actions):
            params[f'a{i}'] = a
    where = " AND ".join(cond) if cond else "1=1"
    sql = text(f"""
        SELECT id, action, source_table, target_table, msk, measure_id,
               measure_id_from, measure_id_to, rows_main, rows_temp,
               operator, action_date, status, restored,
               restored_at, restored_by, notes
        FROM `{LOG_TABLE}` WHERE {where}
        ORDER BY action_date DESC, id DESC LIMIT {int(limit)}
    """)
    return pd.read_sql(sql, engine, params=params)


def get_log_entry(log_id: int) -> dict | None:
    ensure_log_table()
    engine = _engine()
    with engine.connect() as conn:
        row = conn.execute(text(
            f"SELECT * FROM `{LOG_TABLE}` WHERE id = :i"),
            {'i': int(log_id)}).fetchone()
    return dict(row._mapping) if row else None