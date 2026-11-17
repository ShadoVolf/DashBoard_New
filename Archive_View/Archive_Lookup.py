"""
Справочник номеров резонаторов для ускорения поиска Measure_ID.

Таблица psidata_resonator_lookup:
    id            BIGINT PK
    measure_id    INTEGER
    n_normalized  CHAR(20)   UPPER(TRIM(N)) из psidata

Индексы:
    UNIQUE (measure_id, n_normalized)  — для INSERT IGNORE и self-heal
    KEY (n_normalized)                 — основной поиск
    KEY (measure_id)                   — фильтр по годным

Метаданные (last_sync, last_psidata_max_id, row_count) хранятся в
psidata_resonator_lookup_meta — используются для инкрементальной
синхронизации: обрабатываются только новые строки psidata с ID >
last_psidata_max_id.

Полная пересборка нужна только если данные в psidata удаляются/правятся
(что для архивных замеров нетипично). Инкрементальная синхронизация
покрывает штатный сценарий: psidata только пополняется.
"""

from datetime import datetime

import pandas as pd
from sqlalchemy import create_engine, text, bindparam

from Options import get_connection_string


LOOKUP_TABLE = 'psidata_resonator_lookup'
META_TABLE = 'psidata_resonator_lookup_meta'


def _engine():
    return create_engine(str(get_connection_string()))


# =============================================================================
# DDL и метаданные
# =============================================================================

def ensure_lookup_table(engine=None):
    """Создаёт таблицу-справочник и мета-таблицу, если их нет."""
    engine = engine or _engine()
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{LOOKUP_TABLE}` (
                `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `measure_id` INTEGER(11) NOT NULL,
                `n_normalized` CHAR(20) NOT NULL,
                PRIMARY KEY (`id`),
                UNIQUE KEY `uk_mid_n` (`measure_id`, `n_normalized`),
                KEY `idx_n` (`n_normalized`),
                KEY `idx_mid` (`measure_id`)
            ) ENGINE=InnoDB
              DEFAULT CHARSET=cp1251
              COLLATE=cp1251_general_ci
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{META_TABLE}` (
                `id` TINYINT NOT NULL DEFAULT 1,
                `last_sync` DATETIME DEFAULT NULL,
                `last_psidata_max_id` BIGINT UNSIGNED DEFAULT 0,
                `row_count` BIGINT UNSIGNED DEFAULT 0,
                PRIMARY KEY (`id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8
        """))


def _read_meta(engine):
    with engine.connect() as conn:
        row = conn.execute(text(
            f"SELECT last_sync, last_psidata_max_id, row_count "
            f"FROM `{META_TABLE}` WHERE id = 1"
        )).fetchone()
    if not row:
        return {'last_sync': None, 'last_max_id': 0, 'row_count': 0}
    return {
        'last_sync': row[0],
        'last_max_id': int(row[1] or 0),
        'row_count': int(row[2] or 0),
    }


def _write_meta(engine, last_max_id, row_count):
    with engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO `{META_TABLE}`
                (id, last_sync, last_psidata_max_id, row_count)
            VALUES (1, :dt, :mid, :cnt)
            ON DUPLICATE KEY UPDATE
                last_sync = VALUES(last_sync),
                last_psidata_max_id = VALUES(last_psidata_max_id),
                row_count = VALUES(row_count)
        """), {
            'dt': datetime.now(),
            'mid': int(last_max_id or 0),
            'cnt': int(row_count or 0),
        })


# =============================================================================
# Заполнение / синхронизация
# =============================================================================

def is_lookup_empty(engine=None):
    engine = engine or _engine()
    ensure_lookup_table(engine)
    with engine.connect() as conn:
        cnt = conn.execute(
            text(f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}`")
        ).scalar()
    return not cnt


def _scan_range(engine, start_id, end_id, chunk_size, progress_callback,
                progress_base, progress_total):
    """Вспомогательный: INSERT IGNORE ... SELECT по диапазону ID."""
    for start in range(start_id, end_id + 1, chunk_size):
        end = min(start + chunk_size, end_id + 1)
        with engine.begin() as conn:
            conn.execute(text(f"""
                INSERT IGNORE INTO `{LOOKUP_TABLE}` (measure_id, n_normalized)
                SELECT DISTINCT Measure_ID, UPPER(TRIM(N))
                FROM psidata
                WHERE ID >= :s AND ID < :e
                  AND Measure_ID IS NOT NULL
                  AND N IS NOT NULL
                  AND TRIM(N) <> ''
            """), {'s': start, 'e': end})
        if progress_callback:
            progress_callback(end - progress_base, progress_total)


def fill_lookup_table(chunk_size=100_000, progress_callback=None):
    """
    Полная пересборка справочника (TRUNCATE + INSERT по чанкам ID).
    Возвращает {'inserted': int, 'total': int}.
    """
    engine = _engine()
    ensure_lookup_table(engine)

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE `{LOOKUP_TABLE}`"))

    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT MIN(ID), MAX(ID) FROM psidata "
            "WHERE Measure_ID IS NOT NULL AND N IS NOT NULL"
        )).fetchone()
        min_id, max_id = int(r[0] or 0), int(r[1] or 0)

    if max_id <= min_id:
        _write_meta(engine, 0, 0)
        return {'inserted': 0, 'total': 0}

    total_range = max_id - min_id + 1
    _scan_range(engine, min_id, max_id, chunk_size,
                progress_callback, min_id, total_range)

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}`")
        ).scalar()
    _write_meta(engine, max_id, total)
    return {'inserted': int(total), 'total': int(total)}


def sync_lookup_table(full_rebuild=False, chunk_size=100_000,
                      progress_callback=None):
    """
    Синхронизация справочника с psidata.

    full_rebuild=True   — полная пересборка (fill_lookup_table)
    full_rebuild=False  — только новые строки с ID > last_psidata_max_id
    """
    if full_rebuild:
        res = fill_lookup_table(chunk_size, progress_callback)
        return {'inserted': res['inserted'],
                'total': res['total'],
                'mode': 'full'}

    engine = _engine()
    ensure_lookup_table(engine)
    meta = _read_meta(engine)
    last_id = meta['last_max_id']

    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT MIN(ID), MAX(ID) FROM psidata "
            "WHERE ID > :last "
            "  AND Measure_ID IS NOT NULL "
            "  AND N IS NOT NULL"
        ), {'last': last_id}).fetchone()
        min_id, max_id = r[0], r[1]

    if min_id is None or max_id is None or int(max_id) <= last_id:
        with engine.connect() as conn:
            total = conn.execute(
                text(f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}`")
            ).scalar()
        _write_meta(engine, max(last_id, int(max_id or last_id)), total)
        return {'inserted': 0, 'total': int(total),
                'mode': 'incremental'}

    min_id, max_id = int(min_id), int(max_id)
    _scan_range(engine, min_id, max_id, chunk_size,
                progress_callback, min_id, max_id - min_id + 1)

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}`")
        ).scalar()
    _write_meta(engine, max_id, total)

    inserted = int(total) - meta['row_count']
    return {'inserted': max(0, inserted),
            'total': int(total),
            'mode': 'incremental'}


# =============================================================================
# Проверка актуальности
# =============================================================================

def check_lookup_actual():
    """
    Возвращает dict:
        lookup_count           — строк в справочнике
        psidata_max_id         — MAX(ID) psidata сейчас
        last_sync_max_id       — MAX(ID) на момент последней синхронизации
        last_sync              — datetime последней синхронизации
        new_psidata_rows       — сколько новых строк в psidata с прошлой синхр.
        is_empty               — справочник пуст → нужна полная пересборка
        is_actual              — справочник актуален (можно пользоваться)
        needs_full_rebuild     — нужен fill_lookup_table()
        needs_incremental      — нужен sync_lookup_table(full_rebuild=False)
    """
    engine = _engine()
    ensure_lookup_table(engine)
    meta = _read_meta(engine)

    with engine.connect() as conn:
        lookup_count = conn.execute(
            text(f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}`")
        ).scalar() or 0

        r = conn.execute(text(
            "SELECT COALESCE(MAX(ID), 0) FROM psidata"
        )).fetchone()
        current_max = int(r[0] or 0)

        r2 = conn.execute(text(
            "SELECT COUNT(*) FROM psidata WHERE ID > :last"
        ), {'last': meta['last_max_id']}).fetchone()
        new_rows = int(r2[0] or 0)

    is_empty = lookup_count == 0
    is_actual = (not is_empty) and new_rows == 0

    return {
        'lookup_count': int(lookup_count),
        'psidata_max_id': current_max,
        'last_sync_max_id': meta['last_max_id'],
        'last_sync': meta['last_sync'],
        'new_psidata_rows': new_rows,
        'is_empty': is_empty,
        'is_actual': is_actual,
        'needs_full_rebuild': is_empty,
        'needs_incremental': (not is_empty) and new_rows > 0,
    }


# =============================================================================
# Низкоуровневые операции для поиска
# =============================================================================

def find_in_lookup(numbers, engine=None):
    """
    Поиск в справочнике.
    Возвращает (found_numbers_set, found_mids_set, pairs_list).
    """
    engine = engine or _engine()
    ensure_lookup_table(engine)

    numbers_list = [n for n in numbers if n]
    if not numbers_list:
        return set(), set(), []

    try:
        sql = text(
            f"SELECT n_normalized, measure_id "
            f"FROM `{LOOKUP_TABLE}` "
            f"WHERE n_normalized IN :nums"
        ).bindparams(bindparam("nums", expanding=True))
        df = pd.read_sql(sql, engine, params={'nums': numbers_list})
    except Exception as e:
        print(f"[Archive] lookup query error: {e}")
        return set(), set(), []

    if df.empty:
        return set(), set(), []

    found_nums = set(df['n_normalized'].astype(str).str.upper())
    found_mids = set(int(x) for x in df['measure_id'].unique())
    pairs = [(int(r['measure_id']), str(r['n_normalized']).strip().upper())
             for _, r in df.iterrows()]
    return found_nums, found_mids, pairs


def add_pairs_to_lookup(pairs, engine=None):
    """
    Добавить пары (measure_id, n_normalized) — INSERT IGNORE.
    Используется в self-heal после fallback-поиска.
    """
    if not pairs:
        return 0
    engine = engine or _engine()
    ensure_lookup_table(engine)

    clean = set()
    for mid, n in pairs:
        try:
            mid_int = int(mid)
        except (TypeError, ValueError):
            continue
        n_str = str(n).strip().upper()
        if n_str and mid_int:
            clean.add((mid_int, n_str))

    if not clean:
        return 0

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT IGNORE INTO `{LOOKUP_TABLE}` "
                 f"(measure_id, n_normalized) VALUES (:mid, :n)"),
            [{'mid': mid, 'n': n} for mid, n in clean]
        )
    return len(clean)