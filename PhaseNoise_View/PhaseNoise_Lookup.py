"""
Справочник номеров резонаторов и МСК для ускорения поиска в ФШ.

Таблица phaze_noise_resonator_lookup:
    measure_id, n_normalized, msk, spc
"""

from datetime import datetime
import logging

import pandas as pd
from sqlalchemy import create_engine, text, bindparam
from sqlalchemy.engine import Engine

from Options import get_connection_string

log = logging.getLogger("PhaseNoise.Lookup")

LOOKUP_TABLE = "phaze_noise_resonator_lookup"
META_TABLE = "phaze_noise_resonator_lookup_meta"

_engine_cache: Engine | None = None

# Флаги схемы: таблица есть / колонка spc есть
_schema_ok: bool = False
_has_spc_column: bool = False


def _engine() -> Engine:
    """
    mysql-connector-python (mysql+mysqlconnector://) не принимает
    read_timeout / write_timeout.
    Поддерживается connection_timeout (сек).
    """
    global _engine_cache
    if _engine_cache is None:
        _engine_cache = create_engine(
            str(get_connection_string()),
            connect_args={
                "connection_timeout": 10,
            },
            pool_pre_ping=True,
            pool_size=5,
            max_overflow=2,
        )
    return _engine_cache


def _column_exists(conn, table: str, column: str) -> bool:
    n = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.columns "
        "WHERE table_schema = DATABASE() "
        "  AND table_name = :t AND column_name = :c"
    ), {"t": table, "c": column}).scalar() or 0
    return bool(n)


def _table_exists(conn, table: str) -> bool:
    n = conn.execute(text(
        "SELECT COUNT(*) FROM information_schema.tables "
        "WHERE table_schema = DATABASE() AND table_name = :t"
    ), {"t": table}).scalar() or 0
    return bool(n)


def ensure_lookup_table(engine=None):
    """
    Создаёт таблицы lookup/meta при отсутствии.
    Добавляет колонку spc, если таблица старая (без spc).
    Идемпотентно; после успеха кэширует _schema_ok.
    """
    global _schema_ok, _has_spc_column
    if _schema_ok and _has_spc_column:
        return

    engine = engine or _engine()

    with engine.connect() as conn:
        exists = _table_exists(conn, LOOKUP_TABLE)
        meta_exists = _table_exists(conn, META_TABLE)
        col_exists = _column_exists(conn, LOOKUP_TABLE, "spc") if exists else False

    if exists and meta_exists and col_exists:
        _schema_ok = True
        _has_spc_column = True
        return

    log.info(
        "ensure_lookup_table: migrate "
        f"exists={exists} meta={meta_exists} spc_col={col_exists}"
    )

    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{LOOKUP_TABLE}` (
                `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `measure_id` INTEGER(11) NOT NULL,
                `n_normalized` CHAR(20) NOT NULL,
                `msk` VARCHAR(64) DEFAULT NULL,
                `spc` VARCHAR(128) DEFAULT NULL,
                PRIMARY KEY (`id`),
                UNIQUE KEY `uk_mid_n` (`measure_id`, `n_normalized`),
                KEY `idx_n` (`n_normalized`),
                KEY `idx_msk` (`msk`),
                KEY `idx_spc` (`spc`),
                KEY `idx_mid` (`measure_id`)
            ) ENGINE=InnoDB
              DEFAULT CHARSET=cp1251
              COLLATE=cp1251_general_ci
        """))

        # Старая таблица без spc — ALTER (CREATE IF NOT EXISTS колонку не добавит)
        if exists and not col_exists:
            # индекс мог отсутствовать — добавляем колонку, индекс отдельно
            try:
                conn.execute(text(
                    f"ALTER TABLE `{LOOKUP_TABLE}` "
                    f"ADD COLUMN `spc` VARCHAR(128) DEFAULT NULL AFTER `msk`"
                ))
                log.info("ensure_lookup_table: added column spc")
            except Exception as e:
                # уже есть / гонка
                log.warning(f"ensure_lookup_table ADD COLUMN spc: {e}")
            try:
                conn.execute(text(
                    f"ALTER TABLE `{LOOKUP_TABLE}` ADD KEY `idx_spc` (`spc`)"
                ))
            except Exception as e:
                log.debug(f"ensure_lookup_table ADD KEY idx_spc: {e}")

        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{META_TABLE}` (
                `id` TINYINT NOT NULL DEFAULT 1,
                `last_sync` DATETIME DEFAULT NULL,
                `last_phaze_max_id` BIGINT UNSIGNED DEFAULT 0,
                `row_count` BIGINT UNSIGNED DEFAULT 0,
                PRIMARY KEY (`id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8
        """))

    # перепроверка
    with engine.connect() as conn:
        _has_spc_column = _column_exists(conn, LOOKUP_TABLE, "spc")
        _schema_ok = (
            _table_exists(conn, LOOKUP_TABLE)
            and _table_exists(conn, META_TABLE)
            and _has_spc_column
        )

    if not _has_spc_column:
        log.error("ensure_lookup_table: колонка spc всё ещё отсутствует")
    else:
        log.info("ensure_lookup_table: schema OK (spc present)")


def is_lookup_empty(engine=None):
    """НЕ создаёт таблицу. Если её нет — считаем пустой."""
    engine = engine or _engine()
    try:
        with engine.connect() as conn:
            cnt = conn.execute(
                text(f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}`")
            ).scalar()
        return not cnt
    except Exception as e:
        log.debug(f"is_lookup_empty: {e}")
        return True


def _read_meta(engine):
    ensure_lookup_table(engine)
    with engine.connect() as conn:
        row = conn.execute(text(
            f"SELECT last_sync, last_phaze_max_id, row_count "
            f"FROM `{META_TABLE}` WHERE id = 1"
        )).fetchone()
    if not row:
        return {"last_sync": None, "last_max_id": 0, "row_count": 0}
    return {
        "last_sync": row[0],
        "last_max_id": int(row[1] or 0),
        "row_count": int(row[2] or 0),
    }


def _write_meta(engine, last_max_id, row_count):
    ensure_lookup_table(engine)
    with engine.begin() as conn:
        conn.execute(text(f"""
            INSERT INTO `{META_TABLE}`
                (id, last_sync, last_phaze_max_id, row_count)
            VALUES (1, :dt, :mid, :cnt)
            ON DUPLICATE KEY UPDATE
                last_sync = VALUES(last_sync),
                last_phaze_max_id = VALUES(last_phaze_max_id),
                row_count = VALUES(row_count)
        """), {
            "dt": datetime.now(),
            "mid": int(last_max_id or 0),
            "cnt": int(row_count or 0),
        })


def _scan_range(engine, start_id, end_id, chunk_size, progress_callback,
                progress_base, progress_total):
    for start in range(start_id, end_id + 1, chunk_size):
        end = min(start + chunk_size, end_id + 1)
        with engine.begin() as conn:
            conn.execute(text(f"""
                INSERT IGNORE INTO `{LOOKUP_TABLE}`
                    (measure_id, n_normalized, msk, spc)
                SELECT DISTINCT MeasureID, UPPER(TRIM(N)), MSK, Spc
                FROM `phaze_noise`
                WHERE ID >= :s AND ID < :e
                  AND `Delete` = 0
                  AND MeasureID IS NOT NULL
                  AND N IS NOT NULL
                  AND TRIM(N) <> ''
            """), {"s": start, "e": end})
        if progress_callback:
            progress_callback(end - progress_base, progress_total)


def fill_lookup_table(chunk_size=50_000, progress_callback=None):
    engine = _engine()
    ensure_lookup_table(engine)

    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE `{LOOKUP_TABLE}`"))

    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT MIN(ID), MAX(ID) FROM `phaze_noise` "
            "WHERE `Delete` = 0 AND MeasureID IS NOT NULL AND N IS NOT NULL"
        )).fetchone()
        min_id, max_id = int(r[0] or 0), int(r[1] or 0)

    if max_id <= min_id:
        _write_meta(engine, 0, 0)
        return {"inserted": 0, "total": 0}

    total_range = max_id - min_id + 1
    _scan_range(engine, min_id, max_id, chunk_size,
                progress_callback, min_id, total_range)

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}`")
        ).scalar()
    _write_meta(engine, max_id, total)
    log.info(f"fill_lookup_table: {total} rows")
    return {"inserted": int(total), "total": int(total)}


def sync_lookup_table(full_rebuild=False, chunk_size=50_000,
                      progress_callback=None):
    engine = _engine()
    ensure_lookup_table(engine)

    if full_rebuild:
        res = fill_lookup_table(chunk_size, progress_callback)
        return {"inserted": res["inserted"],
                "total": res["total"],
                "mode": "full"}

    meta = _read_meta(engine)
    last_id = meta["last_max_id"]

    # после ALTER spc у старых строк NULL → нужна полная пересборка
    try:
        with engine.connect() as conn:
            null_spc = conn.execute(text(
                f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}` "
                f"WHERE spc IS NULL OR TRIM(spc) = ''"
            )).scalar() or 0
            total_rows = conn.execute(text(
                f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}`"
            )).scalar() or 0
        if total_rows and null_spc > total_rows * 0.5:
            log.info(
                f"lookup: {null_spc}/{total_rows} rows without spc — full rebuild"
            )
            res = fill_lookup_table(chunk_size, progress_callback)
            return {"inserted": res["inserted"],
                    "total": res["total"],
                    "mode": "full"}
    except Exception as e:
        log.warning(f"spc check: {e}")

    with engine.connect() as conn:
        r = conn.execute(text(
            "SELECT MIN(ID), MAX(ID) FROM `phaze_noise` "
            "WHERE ID > :last "
            "  AND `Delete` = 0 "
            "  AND MeasureID IS NOT NULL "
            "  AND N IS NOT NULL"
        ), {"last": last_id}).fetchone()
        min_id, max_id = r[0], r[1]

    if min_id is None or max_id is None or int(max_id) <= last_id:
        with engine.connect() as conn:
            total = conn.execute(
                text(f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}`")
            ).scalar()
        _write_meta(engine, max(last_id, int(max_id or last_id)), total)
        return {"inserted": 0, "total": int(total),
                "mode": "incremental"}

    min_id, max_id = int(min_id), int(max_id)
    _scan_range(engine, min_id, max_id, chunk_size,
                progress_callback, min_id, max_id - min_id + 1)

    with engine.connect() as conn:
        total = conn.execute(
            text(f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}`")
        ).scalar()
    _write_meta(engine, max_id, total)

    inserted = int(total) - meta["row_count"]
    log.info(f"sync_lookup_table incremental: +{max(0, inserted)}, total={total}")
    return {"inserted": max(0, inserted),
            "total": int(total),
            "mode": "incremental"}


def check_lookup_actual():
    engine = _engine()
    ensure_lookup_table(engine)

    meta = _read_meta(engine)

    with engine.connect() as conn:
        lookup_count = conn.execute(
            text(f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}`")
        ).scalar() or 0

        r = conn.execute(text(
            "SELECT COALESCE(MAX(ID), 0) FROM `phaze_noise` WHERE `Delete` = 0"
        )).fetchone()
        current_max = int(r[0] or 0)

        r2 = conn.execute(text(
            "SELECT COUNT(*) FROM `phaze_noise` "
            "WHERE ID > :last AND `Delete` = 0"
        ), {"last": meta["last_max_id"]}).fetchone()
        new_rows = int(r2[0] or 0)

        # доля строк без spc — сигнал, что нужна пересборка
        null_spc = 0
        if _has_spc_column and lookup_count:
            try:
                null_spc = conn.execute(text(
                    f"SELECT COUNT(*) FROM `{LOOKUP_TABLE}` "
                    f"WHERE spc IS NULL OR TRIM(spc) = ''"
                )).scalar() or 0
            except Exception:
                null_spc = lookup_count

    is_empty = lookup_count == 0
    needs_spc_fill = (not is_empty) and null_spc > lookup_count * 0.5
    is_actual = (not is_empty) and new_rows == 0 and not needs_spc_fill

    return {
        "lookup_count": int(lookup_count),
        "phaze_max_id": current_max,
        "last_sync_max_id": meta["last_max_id"],
        "last_sync": meta["last_sync"],
        "new_phaze_rows": new_rows,
        "null_spc_rows": int(null_spc),
        "is_empty": is_empty,
        "is_actual": is_actual,
        "needs_full_rebuild": is_empty or needs_spc_fill,
        "needs_incremental": (not is_empty) and new_rows > 0 and not needs_spc_fill,
    }


# =============================================================================
# Быстрые запросы из справочника
# =============================================================================

def _spc_ready() -> bool:
    """Перед запросами с WHERE spc — убедиться, что колонка есть."""
    ensure_lookup_table()
    return _has_spc_column


def lookup_msk_by_spc(spc: str) -> list[str]:
    if not spc:
        return []
    if not _spc_ready():
        log.debug("lookup_msk_by_spc: нет колонки spc")
        return []
    engine = _engine()
    try:
        df = pd.read_sql(text(f"""
            SELECT DISTINCT msk FROM `{LOOKUP_TABLE}`
            WHERE spc = :s AND msk IS NOT NULL AND TRIM(msk) <> ''
            ORDER BY msk
        """), engine, params={"s": spc})
        return df["msk"].dropna().astype(str).tolist()
    except Exception as e:
        log.debug(f"lookup_msk_by_spc: {e}")
        return []


def lookup_mids_by_spc(spc: str) -> list[int]:
    if not spc:
        return []
    if not _spc_ready():
        log.debug("lookup_mids_by_spc: нет колонки spc")
        return []
    engine = _engine()
    try:
        df = pd.read_sql(text(f"""
            SELECT DISTINCT measure_id FROM `{LOOKUP_TABLE}`
            WHERE spc = :s AND measure_id IS NOT NULL
            ORDER BY measure_id
        """), engine, params={"s": spc})
        return df["measure_id"].dropna().astype(int).tolist()
    except Exception as e:
        log.debug(f"lookup_mids_by_spc: {e}")
        return []


def lookup_mids_by_msk(msk: str) -> list[int]:
    if not msk:
        return []
    ensure_lookup_table()
    engine = _engine()
    try:
        df = pd.read_sql(text(f"""
            SELECT DISTINCT measure_id FROM `{LOOKUP_TABLE}`
            WHERE msk = :m AND measure_id IS NOT NULL
            ORDER BY measure_id
        """), engine, params={"m": msk})
        return df["measure_id"].dropna().astype(int).tolist()
    except Exception as e:
        log.debug(f"lookup_mids_by_msk: {e}")
        return []


def lookup_numbers(msk: str | None = None, measure_id: int | None = None,
                   spc: str | None = None) -> list[str]:
    ensure_lookup_table()
    if spc and not _has_spc_column:
        log.debug("lookup_numbers: нет колонки spc — пропуск фильтра")
        return []

    engine = _engine()
    cond = ["n_normalized IS NOT NULL"]
    params = {}
    if measure_id:
        cond.append("measure_id = :mid")
        params["mid"] = int(measure_id)
    elif msk:
        cond.append("msk = :msk")
        params["msk"] = msk
    if spc:
        cond.append("spc = :spc")
        params["spc"] = spc
    try:
        df = pd.read_sql(text(f"""
            SELECT DISTINCT n_normalized AS N FROM `{LOOKUP_TABLE}`
            WHERE {' AND '.join(cond)}
            ORDER BY n_normalized
        """), engine, params=params)
        return df["N"].dropna().astype(str).tolist()
    except Exception as e:
        log.debug(f"lookup_numbers: {e}")
        return []


def find_in_lookup(numbers, engine=None):
    engine = engine or _engine()
    ensure_lookup_table(engine)

    numbers_list = [str(n).strip().upper() for n in numbers if n]
    if not numbers_list:
        return set(), set(), []

    # SELECT spc только если колонка есть
    cols = "n_normalized, measure_id, msk"
    if _has_spc_column:
        cols += ", spc"

    try:
        sql = text(
            f"SELECT {cols} FROM `{LOOKUP_TABLE}` "
            f"WHERE n_normalized IN :nums"
        ).bindparams(bindparam("nums", expanding=True))
        df = pd.read_sql(sql, engine, params={"nums": numbers_list})
    except Exception as e:
        log.debug(f"lookup query error: {e}")
        return set(), set(), []

    if df.empty:
        return set(), set(), []

    found_nums = set(df["n_normalized"].astype(str).str.upper())
    found_mids = set(int(x) for x in df["measure_id"].unique())
    pairs = [
        (int(r["measure_id"]), str(r["n_normalized"]).strip().upper(),
         str(r["msk"] or ""))
        for _, r in df.iterrows()
    ]
    return found_nums, found_mids, pairs


def find_msk_by_partial(query: str, spc: str | None = None,
                       limit: int = 200, engine=None) -> list[str]:
    """Поиск МСК по части — только справочник."""
    engine = engine or _engine()
    ensure_lookup_table(engine)

    q = (query or "").strip()
    if not q:
        return []
    try:
        if spc and _has_spc_column:
            df = pd.read_sql(text(f"""
                SELECT DISTINCT msk FROM `{LOOKUP_TABLE}`
                WHERE msk IS NOT NULL AND msk LIKE :q AND spc = :spc
                ORDER BY msk LIMIT :lim
            """), engine, params={"q": f"%{q}%", "spc": spc, "lim": limit})
        else:
            df = pd.read_sql(text(f"""
                SELECT DISTINCT msk FROM `{LOOKUP_TABLE}`
                WHERE msk IS NOT NULL AND msk LIKE :q
                ORDER BY msk LIMIT :lim
            """), engine, params={"q": f"%{q}%", "lim": limit})
        return df["msk"].dropna().astype(str).tolist()
    except Exception as e:
        log.debug(f"find_msk_by_partial error: {e}")
        return []


def add_pairs_to_lookup(pairs, engine=None):
    if not pairs:
        return 0
    engine = engine or _engine()
    ensure_lookup_table(engine)

    clean = set()
    for item in pairs:
        if len(item) >= 4:
            mid, n, msk, spc = item[0], item[1], item[2], item[3]
        elif len(item) == 3:
            mid, n, msk = item
            spc = ""
        else:
            mid, n = item
            msk, spc = "", ""
        try:
            mid_int = int(mid)
        except (TypeError, ValueError):
            continue
        n_str = str(n).strip().upper()
        if n_str and mid_int:
            clean.add((mid_int, n_str, str(msk or "").strip(),
                       str(spc or "").strip()))

    if not clean:
        return 0

    with engine.begin() as conn:
        if _has_spc_column:
            conn.execute(
                text(f"INSERT IGNORE INTO `{LOOKUP_TABLE}` "
                     f"(measure_id, n_normalized, msk, spc) "
                     f"VALUES (:mid, :n, :msk, :spc)"),
                [{"mid": a, "n": b, "msk": c, "spc": d}
                 for a, b, c, d in clean]
            )
        else:
            conn.execute(
                text(f"INSERT IGNORE INTO `{LOOKUP_TABLE}` "
                     f"(measure_id, n_normalized, msk) "
                     f"VALUES (:mid, :n, :msk)"),
                [{"mid": a, "n": b, "msk": c}
                 for a, b, c, _d in clean]
            )
    return len(clean)
