"""Синхронизация структуры psidata/psidatatemp с их аналогами."""
from sqlalchemy import create_engine, text

import Options

PAIRS = [
    ('psidata',     'psidata_temporary'),
    ('psidata',     'psidata_archive'),
    ('psidatatemp', 'psidatatemp_temporary'),
    ('psidatatemp', 'psidatatemp_archive'),
]


def _engine():
    return create_engine(str(Options.get_connection_string()))


def _get_columns(engine, table: str) -> dict:
    sql = text("""
        SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE, COLUMN_DEFAULT,
               EXTRA, COLUMN_COMMENT, CHARACTER_SET_NAME, COLLATION_NAME
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t
        ORDER BY ORDINAL_POSITION
    """)
    with engine.connect() as conn:
        rows = conn.execute(sql, {'t': table}).fetchall()
    return {r[0]: {
        'type': r[1], 'nullable': r[2] == 'YES', 'default': r[3],
        'extra': r[4] or '', 'comment': r[5] or '',
        'charset': r[6], 'collation': r[7],
    } for r in rows}

def _column_def(name, meta, after):
    parts = [f"`{name}`", meta['type']]
    if meta['charset'] and meta['collation']:
        parts.append(f"CHARACTER SET {meta['charset']}")
        parts.append(f"COLLATE {meta['collation']}")
    parts.append("NULL" if meta['nullable'] else "NOT NULL")

    d = meta['default']
    if d is not None:
        ds = str(d).strip()
        upper = ds.upper()
        if upper.startswith('CURRENT_TIMESTAMP'):
            # выражение — без кавычек
            parts.append(f"DEFAULT {ds}")
        elif upper == 'NULL':
            # строка 'NULL' от mysql.connector = отсутствие дефолта;
            # для nullable-колонки явный DEFAULT NULL не нужен
            pass
        elif isinstance(d, (int, float)):
            parts.append(f"DEFAULT {d}")
        else:
            escaped = ds.replace("'", "''")
            parts.append(f"DEFAULT '{escaped}'")

    if meta['extra']:
        parts.append(meta['extra'])
    if meta['comment']:
        cmt = meta['comment'].replace("'", "''")
        parts.append(f"COMMENT '{cmt}'")
    if after:
        parts.append(f"AFTER `{after}`")
    return ' '.join(parts)

def _column_def_1(name, meta, after):
    parts = [f"`{name}`", meta['type']]
    if meta['charset'] and meta['collation']:
        parts.append(f"CHARACTER SET {meta['charset']}")
        parts.append(f"COLLATE {meta['collation']}")
    parts.append("NULL" if meta['nullable'] else "NOT NULL")
    if meta['default'] is not None:
        d = meta['default']
        if str(d).upper() == 'CURRENT_TIMESTAMP':
            parts.append("DEFAULT CURRENT_TIMESTAMP")
        else:
            parts.append(f"DEFAULT '{d}'")
    if meta['extra']:
        parts.append(meta['extra'])
    if meta['comment']:
        parts.append(f"COMMENT '{meta['comment']}'")
    if after:
        parts.append(f"AFTER `{after}`")
    return ' '.join(parts)


def sync_table_structure() -> list[str]:
    engine = _engine()
    report = []
    for ref, tgt in PAIRS:
        try:
            ref_cols = _get_columns(engine, ref)
            tgt_cols = _get_columns(engine, tgt)
        except Exception as e:
            report.append(f"[{tgt}] ошибка чтения: {e}")
            continue
        if not ref_cols:
            report.append(f"[{tgt}] эталонная {ref} не найдена")
            continue
        missing = [c for c in ref_cols if c not in tgt_cols]
        if not missing:
            report.append(f"[{tgt}] OK")
            continue
        ordered = list(ref_cols.keys())
        for col in missing:
            idx = ordered.index(col)
            after = ordered[idx - 1] if idx > 0 else None
            ddl = _column_def(col, ref_cols[col], after)
            try:
                with engine.begin() as conn:
                    conn.execute(text(
                        f"ALTER TABLE `{tgt}` ADD COLUMN {ddl}"))
                report.append(f"[{tgt}] + {col}")
            except Exception as e:
                report.append(f"[{tgt}] ! {col}: {e}")
    return report


def check_structure() -> dict:
    engine = _engine()
    out = {}
    for ref, tgt in PAIRS:
        try:
            r = set(_get_columns(engine, ref))
            t = set(_get_columns(engine, tgt))
        except Exception:
            continue
        miss = sorted(r - t)
        if miss:
            out[tgt] = {'ref': ref, 'missing': miss}
    return out