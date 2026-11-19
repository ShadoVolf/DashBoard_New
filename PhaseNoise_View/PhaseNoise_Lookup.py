"""
Справочник номеров резонаторов и МСК для ускорения поиска в ФШ.

Таблица phaze_noise_resonator_lookup:
    id            BIGINT PK
    measure_id    INTEGER
    n_normalized  CHAR(20)   UPPER(TRIM(N))
    msk           VARCHAR(64)

Индексы:
    UNIQUE (measure_id, n_normalized)
    KEY (n_normalized)
    KEY (msk)
    KEY (measure_id)

Метаданные в phaze_noise_resonator_lookup_meta — инкрементальная синхронизация.
"""

from datetime import datetime
import logging

import pandas as pd
from sqlalchemy import create_engine, text, bindparam

from Options import get_connection_string

log = logging.getLogger("PhaseNoise.Lookup")

LOOKUP_TABLE = "phaze_noise_resonator_lookup"
META_TABLE = "phaze_noise_resonator_lookup_meta"


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
                `msk` VARCHAR(64) DEFAULT NULL,
                PRIMARY KEY (`id`),
                UNIQUE KEY `uk_mid_n` (`measure_id`, `n_normalized`),
                KEY `idx_n` (`n_normalized`),
                KEY `idx_msk` (`msk`),
                KEY `idx_mid` (`measure_id`)
            ) ENGINE=InnoDB
              DEFAULT CHARSET=cp1251
              COLLATE=cp1251_general_ci
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{META_TABLE}` (
                `id` TINYINT NOT NULL DEFAULT 1,
                `last_sync` DATETIME DEFAULT NULL,
                `last_phaze_max_id` BIGINT UNSIGNED DEFAULT 0,
                `row_count` BIGINT UNSIGNED DEFAULT 0,
                PRIMARY KEY (`id`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8
        """))


def _read_meta(engine):
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
    """INSERT IGNORE ... SELECT по диапазону ID из phaze_noise."""
    for start in range(start_id, end_id + 1, chunk_size):
        end = min(start + chunk_size, end_id + 1)
        with engine.begin() as conn:
            conn.execute(text(f"""
                INSERT IGNORE INTO `{LOOKUP_TABLE}`
                    (measure_id, n_normalized, msk)
                SELECT DISTINCT MeasureID, UPPER(TRIM(N)), MSK
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
    """Полная пересборка справочника."""
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
    """Синхронизация справочника с phaze_noise."""
    if full_rebuild:
        res = fill_lookup_table(chunk_size, progress_callback)
        return {"inserted": res["inserted"],
                "total": res["total"],
                "mode": "full"}

    engine = _engine()
    ensure_lookup_table(engine)
    meta = _read_meta(engine)
    last_id = meta["last_max_id"]

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
    """Статус актуальности справочника."""
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

    is_empty = lookup_count == 0
    is_actual = (not is_empty) and new_rows == 0

    return {
        "lookup_count": int(lookup_count),
        "phaze_max_id": current_max,
        "last_sync_max_id": meta["last_max_id"],
        "last_sync": meta["last_sync"],
        "new_phaze_rows": new_rows,
        "is_empty": is_empty,
        "is_actual": is_actual,
        "needs_full_rebuild": is_empty,
        "needs_incremental": (not is_empty) and new_rows > 0,
    }


# =============================================================================
# Поиск
# =============================================================================

def find_in_lookup(numbers, engine=None):
    """
    Поиск в справочнике по списку номеров (уже нормализованных UPPER).
    Возвращает (found_numbers_set, found_mids_set, pairs_list).
    """
    engine = engine or _engine()
    ensure_lookup_table(engine)

    numbers_list = [str(n).strip().upper() for n in numbers if n]
    if not numbers_list:
        return set(), set(), []

    try:
        sql = text(
            f"SELECT n_normalized, measure_id, msk "
            f"FROM `{LOOKUP_TABLE}` "
            f"WHERE n_normalized IN :nums"
        ).bindparams(bindparam("nums", expanding=True))
        df = pd.read_sql(sql, engine, params={"nums": numbers_list})
    except Exception as e:
        log.error(f"lookup query error: {e}")
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


def find_msk_by_partial(query: str, limit: int = 200, engine=None) -> list[str]:
    """Поиск МСК по части строки (из справочника, быстро)."""
    engine = engine or _engine()
    ensure_lookup_table(engine)
    q = (query or "").strip()
    if not q:
        return []
    try:
        df = pd.read_sql(text(f"""
            SELECT DISTINCT msk
            FROM `{LOOKUP_TABLE}`
            WHERE msk IS NOT NULL AND msk LIKE :q
            ORDER BY msk
            LIMIT :lim
        """), engine, params={"q": f"%{q}%", "lim": limit})
        return df["msk"].dropna().astype(str).tolist()
    except Exception as e:
        log.error(f"find_msk_by_partial error: {e}")
        return []


def add_pairs_to_lookup(pairs, engine=None):
    """Добавить пары (measure_id, n_normalized, msk) — INSERT IGNORE."""
    if not pairs:
        return 0
    engine = engine or _engine()
    ensure_lookup_table(engine)

    clean = set()
    for item in pairs:
        if len(item) == 2:
            mid, n = item
            msk = ""
        else:
            mid, n, msk = item
        try:
            mid_int = int(mid)
        except (TypeError, ValueError):
            continue
        n_str = str(n).strip().upper()
        msk_str = str(msk or "").strip()
        if n_str and mid_int:
            clean.add((mid_int, n_str, msk_str))

    if not clean:
        return 0

    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT IGNORE INTO `{LOOKUP_TABLE}` "
                 f"(measure_id, n_normalized, msk) VALUES (:mid, :n, :msk)"),
            [{"mid": mid, "n": n, "msk": msk} for mid, n, msk in clean]
        )
    return len(clean)


# =============================================================================
# UI-диалоги
# =============================================================================

def _s(v) -> str:
    if v is None:
        return ""
    try:
        import pandas as pd
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v)


class LookupDialog:
    """Универсальный диалог выбора."""

    def __init__(self, *, title: str, tag_prefix: str,
                 query_fn, format_fn, on_select,
                 width: int = 1000, height: int = 600):
        self.title = title
        self.tag_win = f"{tag_prefix}_win"
        self.tag_search = f"{tag_prefix}_search"
        self.tag_list = f"{tag_prefix}_list"
        self.query_fn = query_fn
        self.format_fn = format_fn
        self.on_select = on_select
        self.width = width
        self.height = height
        log.info(f"LookupDialog init: {title}")
        self._build()
        self._reload()

    def _build(self):
        import dearpygui.dearpygui as dpg
        if dpg.does_item_exist(self.tag_win):
            dpg.delete_item(self.tag_win)
        with dpg.window(label=self.title, tag=self.tag_win,
                        width=self.width, height=self.height,
                        pos=(80, 80)):
            dpg.add_text("Фильтр (МСК / N / Spc / ID):")
            dpg.add_input_text(tag=self.tag_search, width=-1,
                               callback=self._on_search)
            dpg.add_listbox([], tag=self.tag_list,
                            width=-1, height=-80, num_items=25)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Выбрать", callback=self._on_pick,
                               width=110)
                dpg.add_button(label="Обновить", callback=self._on_search,
                               width=110)
                dpg.add_button(label="Отмена", callback=self._on_cancel,
                               width=110)

    def _on_search(self, *args):
        self._reload()

    def _reload(self):
        import dearpygui.dearpygui as dpg
        q = (dpg.get_value(self.tag_search) or "").strip()
        log.info(f"Lookup reload: query={q!r}")
        try:
            df = self.query_fn(q)
        except Exception as e:
            log.exception(f"Lookup query error: {e}")
            df = None
        if df is None or df.empty:
            log.warning(f"Lookup {self.title}: пустой результат")
            items = ["(нет данных)"]
        else:
            items = [self.format_fn(r) for _, r in df.iterrows()]
            log.info(f"Lookup {self.title}: {len(items)} строк")
        dpg.configure_item(self.tag_list, items=items,
                           default_value=items[0])

    def _on_pick(self, *args):
        import dearpygui.dearpygui as dpg
        sel = dpg.get_value(self.tag_list)
        log.info(f"Lookup pick: {sel!r}")
        if not sel or sel == "(нет данных)":
            return
        try:
            self.on_select(sel)
        except Exception as e:
            log.exception(f"on_select error: {e}")
        try:
            dpg.delete_item(self.tag_win)
        except Exception:
            pass

    def _on_cancel(self, *args):
        import dearpygui.dearpygui as dpg
        log.info(f"Lookup cancel: {self.title}")
        try:
            dpg.delete_item(self.tag_win)
        except Exception:
            pass


def open_msk_lookup(on_select):
    from .PhaseNoise_Data import load_msk_lookup

    def fmt(r):
        return (f"{_s(r.get('MSK'))} | N={_s(r.get('N_list'))} | "
                f"Spc={_s(r.get('Spc_list'))} | "
                f"{_s(r.get('last_date'))} | cnt={_s(r.get('cnt'))}")

    def cb(sel):
        msk = sel.split(" | ")[0].strip()
        on_select(msk)

    LookupDialog(title="Справочник МСК", tag_prefix="pn_lookup_msk",
                 query_fn=load_msk_lookup, format_fn=fmt, on_select=cb)


def open_measure_id_lookup(on_select):
    from .PhaseNoise_Data import load_measure_id_lookup

    def fmt(r):
        return (f"{_s(r.get('MeasureID'))} | MSK={_s(r.get('MSK_list'))} | "
                f"N={_s(r.get('N_list'))} | "
                f"Spc={_s(r.get('Spc_list'))} | "
                f"{_s(r.get('last_date'))} | cnt={_s(r.get('cnt'))}")

    def cb(sel):
        mid = sel.split(" | ")[0].strip()
        on_select(int(mid))

    LookupDialog(title="Справочник MeasureID", tag_prefix="pn_lookup_mid",
                 query_fn=load_measure_id_lookup, format_fn=fmt, on_select=cb)


def open_resonator_lookup(on_select):
    from .PhaseNoise_Data import load_resonator_lookup

    def fmt(r):
        return (f"{_s(r.get('N'))} | MSK={_s(r.get('MSK_list'))} | "
                f"{_s(r.get('last_date'))} | cnt={_s(r.get('cnt'))}")

    def cb(sel):
        n = sel.split(" | ")[0].strip()
        on_select(n)

    LookupDialog(title="Справочник номеров резонаторов",
                 tag_prefix="pn_lookup_n",
                 query_fn=load_resonator_lookup,
                 format_fn=fmt, on_select=cb)
