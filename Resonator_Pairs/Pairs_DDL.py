"""DDL и логирование операций модуля пар."""

from sqlalchemy import create_engine, text

from Options import get_connection_string

POOL_TABLE  = 'resonator_pairs_pool'
PAIRS_TABLE = 'resonator_pairs'
LOG_TABLE   = 'resonator_pairs_log'


def _engine():
    return create_engine(str(get_connection_string()))


def _column_type(conn, table: str, column: str) -> str | None:
    """Вернуть текущий тип колонки в БД (или None, если её нет)."""
    try:
        row = conn.execute(text(
            "SELECT DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "  AND TABLE_NAME = :t AND COLUMN_NAME = :c"
        ), {'t': table, 'c': column}).fetchone()
        return str(row[0]).lower() if row else None
    except Exception:
        return None


def ensure_pairs_tables(engine=None):
    """Создать таблицы модуля, если их нет. Мигрирует position INT->VARCHAR."""
    engine = engine or _engine()
    with engine.begin() as conn:
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{POOL_TABLE}` (
                `id`             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `measure_id`     INT NOT NULL,
                `spc`            VARCHAR(255) DEFAULT NULL,
                `msk`            VARCHAR(255) DEFAULT NULL,
                `n_normalized`   VARCHAR(50)  DEFAULT NULL,
                `position`       VARCHAR(50)  DEFAULT NULL,
                `f_value`        DOUBLE DEFAULT NULL,
                `r_value`        DOUBLE DEFAULT NULL,
                `added_at`       DATETIME DEFAULT CURRENT_TIMESTAMP,
                `status`         ENUM('free','used') NOT NULL DEFAULT 'free',
                `pair_id`        BIGINT UNSIGNED DEFAULT NULL,
                PRIMARY KEY (`id`),
                KEY `idx_measure_id` (`measure_id`),
                KEY `idx_spc`        (`spc`),
                KEY `idx_status`     (`status`),
                KEY `idx_n`          (`n_normalized`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8
        """))

        # --- Миграция: если таблица была создана раньше с position INT ---
        ctype = _column_type(conn, POOL_TABLE, 'position')
        if ctype and 'char' not in ctype and 'text' not in ctype:
            try:
                conn.execute(text(
                    f"ALTER TABLE `{POOL_TABLE}` "
                    f"MODIFY `position` VARCHAR(50) DEFAULT NULL"
                ))
                print(f"[Pairs] migration: {POOL_TABLE}.position "
                      f"{ctype} -> VARCHAR(50)")
            except Exception as e:
                print(f"[Pairs] migration position failed: {e}")

        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{PAIRS_TABLE}` (
                `id`            BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `measure_id_1`  INT NOT NULL,
                `measure_id_2`  INT NOT NULL,
                `n_1`           VARCHAR(50)  DEFAULT NULL,
                `n_2`           VARCHAR(50)  DEFAULT NULL,
                `spc_1`         VARCHAR(255) DEFAULT NULL,
                `spc_2`         VARCHAR(255) DEFAULT NULL,
                `msk_1`         VARCHAR(255) DEFAULT NULL,
                `msk_2`         VARCHAR(255) DEFAULT NULL,
                `f_1`           DOUBLE DEFAULT NULL,
                `f_2`           DOUBLE DEFAULT NULL,
                `r_1`           DOUBLE DEFAULT NULL,
                `r_2`           DOUBLE DEFAULT NULL,
                `delta_f`       DOUBLE DEFAULT NULL,
                `delta_r`       DOUBLE DEFAULT NULL,
                `created_at`    DATETIME DEFAULT CURRENT_TIMESTAMP,
                `created_by`    VARCHAR(100) DEFAULT NULL,
                `notes`         TEXT,
                PRIMARY KEY (`id`),
                KEY `idx_n1_n2`  (`n_1`, `n_2`),
                KEY `idx_created`(`created_at`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8
        """))
        conn.execute(text(f"""
            CREATE TABLE IF NOT EXISTS `{LOG_TABLE}` (
                `id`         BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
                `operation`  VARCHAR(100) NOT NULL,
                `details`    TEXT,
                `created_at` DATETIME DEFAULT CURRENT_TIMESTAMP,
                `created_by` VARCHAR(100) DEFAULT NULL,
                PRIMARY KEY (`id`),
                KEY `idx_created`   (`created_at`),
                KEY `idx_operation` (`operation`)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8
        """))


def log_operation(operation: str, details: str, user: str | None = None,
                  engine=None) -> None:
    """Записать операцию в журнал."""
    engine = engine or _engine()
    ensure_pairs_tables(engine)
    try:
        with engine.begin() as conn:
            conn.execute(
                text(f"INSERT INTO `{LOG_TABLE}` "
                     f"(operation, details, created_by) "
                     f"VALUES (:op, :det, :usr)"),
                {'op': operation, 'det': details, 'usr': user},
            )
    except Exception as e:
        print(f"[Pairs] log error: {e}")