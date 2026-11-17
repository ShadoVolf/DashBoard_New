"""Импорт готовых пар резонаторов из Excel в БД.

Имитирует результат работы модуля формирования пар:
  * берёт резонаторы ТОЛЬКО из пула `resonator_pairs_pool`;
  * пишет пары в `resonator_pairs`;
  * по умолчанию физически УДАЛЯЕТ использованные pool-записи
    (флаг `--keep` → `status='used'` для аудита);
  * каждую пропущенную строку логирует в консоль и в БД
    (`resonator_pairs_log`, операция `pairs_import_skip`).

Заголовки столбцов в Excel (`220`, `222`) трактуются как ПОДСКАЗКИ
для спецификации (`РК507-98,415М-220`), НЕ как Measure_ID.

Поиск резонатора: точное совпадение `UPPER(TRIM(n_normalized))` +
`UPPER(TRIM(spc))`; при неудаче — fallback без spc с предупреждением.

Использование:
    python -m Resonator_Pairs.Pairs_Import файл.xlsx
    python -m Resonator_Pairs.Pairs_Import файл.xlsx --dry-run
    python -m Resonator_Pairs.Pairs_Import файл.xlsx --keep
    python -m Resonator_Pairs.Pairs_Import файл.xlsx --verbose
    python -m Resonator_Pairs.Pairs_Import файл.xlsx \\
        --spc-1 "РК507-98,415М-220" --spc-2 "РК507-98,415М-222"
"""
import argparse
import json
import os
import re
import sys

import pandas as pd
from sqlalchemy import create_engine, text

try:
    from .Pairs_DDL import (
        ensure_pairs_tables, log_operation, PAIRS_TABLE, POOL_TABLE,
    )
except ImportError:
    _here = os.path.dirname(os.path.abspath(__file__))
    _root = os.path.dirname(_here)
    if _root not in sys.path:
        sys.path.insert(0, _root)
    from Resonator_Pairs.Pairs_DDL import (
        ensure_pairs_tables, log_operation, PAIRS_TABLE, POOL_TABLE,
    )

from Options import get_connection_string


# =============================================================================
# Утилиты
# =============================================================================
def _engine():
    return create_engine(str(get_connection_string()))


def _safe_float(v):
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def _is_resonator(v) -> bool:
    if v is None:
        return False
    try:
        if pd.isna(v):
            return False
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    if not s or s.lower() in ('none', 'nan'):
        return False
    if re.match(r'^\d{4}[-./]\d{1,2}[-./]\d{1,2}', s):
        return False
    if re.match(r'^\d{1,2}:\d{2}', s):
        return False
    return bool(re.match(r'^[A-Za-zА-Яа-я0-9]{2,}$', s))


def _ppm_delta(f1, f2):
    if f1 is None or f2 is None:
        return None
    try:
        f1, f2 = float(f1), float(f2)
    except (TypeError, ValueError):
        return None
    if pd.isna(f1) or pd.isna(f2):
        return None
    mean = (f1 + f2) / 2.0
    if mean == 0:
        return None
    return abs(f1 - f2) / abs(mean) * 1e6


def _ohm_delta(r1, r2):
    if r1 is None or r2 is None:
        return None
    try:
        r1, r2 = float(r1), float(r2)
    except (TypeError, ValueError):
        return None
    if pd.isna(r1) or pd.isna(r2):
        return None
    return abs(r1 - r2)


# =============================================================================
# Прогресс (не затирает обычный вывод)
# =============================================================================
class _Progress:
    def __init__(self, total, desc="Import"):
        self.total = max(1, total)
        self.desc = desc
        self._active = False
        try:
            from tqdm import tqdm
            self._tqdm = tqdm(total=total, desc=desc, unit="pair")
            self._active = True
        except ImportError:
            self._tqdm = None

    def update(self, i, extra=""):
        if self._tqdm is not None:
            self._tqdm.update(1)
            if extra:
                self._tqdm.set_postfix_str(extra)
            return
        pct = 100.0 * i / self.total
        filled = int(30 * i / self.total)
        bar = "#" * filled + "-" * (30 - filled)
        line = f"\r  [{bar}] {i:4d}/{self.total} ({pct:3.0f}%) {extra}"
        sys.stdout.write(line.ljust(120))
        sys.stdout.flush()

    def clear_line(self):
        if self._tqdm is None and self._active:
            sys.stdout.write("\r" + " " * 120 + "\r")
            sys.stdout.flush()

    def close(self):
        if self._tqdm is not None:
            self._tqdm.close()
        else:
            if self._active:
                sys.stdout.write("\n")
                sys.stdout.flush()
        self._active = False


# =============================================================================
# Разрешение подсказки Spc
# =============================================================================
def _resolve_spc_from_hint(engine, hint):
    if hint is None:
        return None
    hint = str(hint).strip()
    if not hint:
        return None

    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                "SELECT DISTINCT Spc FROM psidata WHERE Spc = :s LIMIT 1"
            ), {'s': hint}).fetchone()
        if row:
            return str(row[0])
    except Exception:
        pass

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT DISTINCT Spc FROM psidata WHERE Spc LIKE :pat"
            ), {'pat': f'%{hint}%'}).fetchall()
    except Exception as e:
        print(f"\n[Import] spc resolve error: {e}")
        return None

    specs = [str(r[0]) for r in rows if r and r[0]]
    if not specs:
        return None
    if len(specs) == 1:
        return specs[0]

    narrowed = [s for s in specs
                if s.endswith(f'-{hint}') or s.endswith(hint)]
    if len(narrowed) == 1:
        return narrowed[0]

    print(f"\n[Import] WARN: hint '{hint}' matches multiple Spc: {specs}")
    print(f"[Import] WARN: используем {specs[0]!r} "
          f"(укажите --spc-1/--spc-2 для точного выбора)")
    return specs[0]


# =============================================================================
# Поиск резонатора в пуле
# =============================================================================
def _pool_lookup(engine, n_norm, spc_filter, exclude_ids,
                 only_free=True):
    """Один запрос к пулу. Возвращает dict или None."""
    conds = ["UPPER(TRIM(n_normalized)) = :n"]
    params = {'n': n_norm.upper().strip()}

    if spc_filter:
        conds.append("UPPER(TRIM(spc)) = UPPER(TRIM(:s))")
        params['s'] = spc_filter.strip()

    if only_free:
        conds.append("status = 'free'")

    if exclude_ids:
        placeholders = ",".join(f":e{i}" for i in range(len(exclude_ids)))
        conds.append(f"id NOT IN ({placeholders})")
        for i, eid in enumerate(exclude_ids):
            params[f'e{i}'] = int(eid)

    sql = text(
        f"SELECT id, measure_id, spc, msk, n_normalized, "
        f"       f_value, r_value, status "
        f"FROM `{POOL_TABLE}` "
        f"WHERE " + " AND ".join(conds) + " "
        f"ORDER BY measure_id DESC LIMIT 1"
    )
    try:
        with engine.connect() as conn:
            row = conn.execute(sql, params).fetchone()
    except Exception as e:
        print(f"\n[Import] pool SQL error: {e}")
        return None

    if not row:
        return None
    return {
        'pool_id': int(row[0]),
        'measure_id': int(row[1]),
        'spc': str(row[2]) if row[2] else None,
        'msk': str(row[3]) if row[3] else None,
        'n': str(row[4]),
        'f': _safe_float(row[5]),
        'r': _safe_float(row[6]),
        'status': str(row[7]) if row[7] else 'free',
    }


def _find_resonator(engine, n, spc_filter, exclude_ids, verbose=False):
    """
    Возвращает (result_dict | None, reason | None).
    Стратегии:
      1. строгое совпадение spc;
      2. без spc (fallback, с предупреждением);
      3. если найден только в 'used' — reason='already used';
      4. иначе — reason='not in pool'.
    """
    n_norm = str(n).strip().upper()

    # 1) strict spc
    if spc_filter:
        r = _pool_lookup(engine, n_norm, spc_filter, exclude_ids)
        if r:
            return r, None

    # 2) без spc
    r = _pool_lookup(engine, n_norm, None, exclude_ids)
    if r:
        if verbose and spc_filter and r.get('spc') and r['spc'] != spc_filter:
            print(f"\n  WARN: {n_norm} найден без spc-match "
                  f"(pool.spc={r['spc']!r}, ожидалось {spc_filter!r})")
        return r, None

    # 3) exists but used?
    r_used = _pool_lookup(engine, n_norm, spc_filter, exclude_ids,
                          only_free=False)
    if r_used:
        return None, f"already used (pool_id={r_used['pool_id']})"

    return None, "not in pool"


# =============================================================================
# Логирование skips в БД
# =============================================================================
def _log_skips(engine, import_tag, skips, user=None):
    if not skips:
        return
    # Один batch-лог с JSON-списком — не засоряем таблицу
    payload = json.dumps(
        [{'row': s['row'],
          'n_1': s.get('n_1'),
          'n_2': s.get('n_2'),
          'reason': s['reason']} for s in skips],
        ensure_ascii=False,
    )
    log_operation(
        'pairs_import_skip',
        f'import={import_tag}, count={len(skips)}, rows={payload}',
        user,
    )


# =============================================================================
# Импорт
# =============================================================================
def import_pairs_from_excel(file_path,
                            spc_1=None, spc_2=None,
                            allow_psidata=False,
                            keep_in_pool=False,
                            dry_run=False,
                            verbose=False,
                            skip_rows=None, sheet=0,
                            user=None):
    print(f"[Import] File: {file_path}")
    skip_rows = set(skip_rows or [])

    try:
        df = pd.read_excel(file_path, header=None, sheet_name=sheet)
    except Exception as e:
        print(f"[Import] ERROR read excel: {e}")
        return 0

    print(f"[Import] Shape: {df.shape}")

    engine = _engine()
    ensure_pairs_tables(engine)

    # --- заголовки → Spc hints ---
    if spc_1 is None:
        try:
            raw = df.iloc[0, 1]
            if raw is not None and not pd.isna(raw):
                spc_1 = str(raw).strip() or None
        except Exception:
            pass
    if spc_2 is None:
        try:
            raw = df.iloc[0, 2]
            if raw is not None and not pd.isna(raw):
                spc_2 = str(raw).strip() or None
        except Exception:
            pass

    if spc_1:
        spc_1 = _resolve_spc_from_hint(engine, spc_1)
    if spc_2:
        spc_2 = _resolve_spc_from_hint(engine, spc_2)

    import_tag = pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')

    print(f"[Import] Spc 1 (col B): {spc_1 or '—'}")
    print(f"[Import] Spc 2 (col C): {spc_2 or '—'}")
    print(f"[Import] Source:  {'pool + psidata' if allow_psidata else 'pool only'}")
    print(f"[Import] On save: {'KEEP as used' if keep_in_pool else 'DELETE from pool'}")
    print(f"[Import] Mode:    {'DRY RUN' if dry_run else 'SAVE'}")
    print(f"[Import] Tag:     {import_tag}")

    if spc_1 is None and spc_2 is None:
        print("[Import] WARN: обе спецификации не заданы — поиск без фильтра")

    # --- предварительный сбор строк ---
    rows_to_process = []
    for idx in range(1, len(df)):
        row_num = idx + 1
        if row_num in skip_rows:
            continue
        try:
            n1 = df.iloc[idx, 1]
            n2 = df.iloc[idx, 2]
        except IndexError:
            continue
        if not _is_resonator(n1) or not _is_resonator(n2):
            continue
        rows_to_process.append(
            (row_num, str(n1).strip(), str(n2).strip()))

    total = len(rows_to_process)
    print(f"[Import] Rows to process: {total}\n")
    if total == 0:
        return 0

    # --- проход 1: сбор пар ---
    pairs = []
    skips = []
    used_pids = set()

    prog = _Progress(total, "Search")
    for i, (row_num, n1_s, n2_s) in enumerate(rows_to_process, 1):
        prog.update(i, f"row {row_num}")

        r1, reason1 = _find_resonator(
            engine, n1_s, spc_1, used_pids, verbose=verbose)
        if r1 and r1.get('pool_id'):
            used_pids.add(r1['pool_id'])

        r2, reason2 = _find_resonator(
            engine, n2_s, spc_2, used_pids, verbose=verbose)
        if r2 and r2.get('pool_id'):
            used_pids.add(r2['pool_id'])

        if not r1 or not r2:
            reasons = []
            if not r1:
                reasons.append(f'B="{n1_s}": {reason1}')
            if not r2:
                reasons.append(f'C="{n2_s}": {reason2}')
            skips.append({
                'row': row_num, 'n_1': n1_s, 'n_2': n2_s,
                'reason': '; '.join(reasons),
            })
            if verbose:
                prog.clear_line()
                print(f"  SKIP row {row_num}: {n1_s}/{n2_s} — "
                      f"{'; '.join(reasons)}")
            continue

        # контроль spc (мягкий — с предупреждением, если не совпал)
        if spc_1 and r1.get('spc') and r1['spc'] != spc_1 and verbose:
            prog.clear_line()
            print(f"  WARN row {row_num}: B spc={r1['spc']!r} != {spc_1!r}")
        if spc_2 and r2.get('spc') and r2['spc'] != spc_2 and verbose:
            prog.clear_line()
            print(f"  WARN row {row_num}: C spc={r2['spc']!r} != {spc_2!r}")

        pairs.append({
            'row': row_num,
            'r1': r1,
            'r2': r2,
            'delta_f': _ppm_delta(r1.get('f'), r2.get('f')),
            'delta_r': _ohm_delta(r1.get('r'), r2.get('r')),
        })
    prog.close()

    print(f"\n[Import] Valid pairs: {len(pairs)} | Skipped: {len(skips)}")
    if skips and not verbose:
        for s in skips[:15]:
            print(f"  row {s['row']}: {s['reason']}")
        if len(skips) > 15:
            print(f"  ... и ещё {len(skips) - 15} "
                  f"(полный список — в БД, operation=pairs_import_skip)")

    # --- лог skips в БД (всегда, даже в dry-run) ---
    _log_skips(engine, import_tag, skips, user)

    if dry_run:
        print("[Import] DRY RUN — pairs not written")
        return 0

    if not pairs:
        print("[Import] Nothing to save")
        return 0

    # --- проход 2: запись в БД ---
    saved = 0
    failed = []

    prog = _Progress(len(pairs), "Save")
    for i, p in enumerate(pairs, 1):
        prog.update(i, f"row {p['row']}")
        r1, r2 = p['r1'], p['r2']
        try:
            with engine.begin() as conn:
                res = conn.execute(
                    text(f"INSERT INTO `{PAIRS_TABLE}` "
                         f"(measure_id_1, measure_id_2, n_1, n_2, "
                         f" spc_1, spc_2, msk_1, msk_2, "
                         f" f_1, f_2, r_1, r_2, "
                         f" delta_f, delta_r, created_by, notes) "
                         f"VALUES (:m1, :m2, :n1, :n2, "
                         f"        :s1, :s2, :k1, :k2, "
                         f"        :f1, :f2, :r1, :r2, "
                         f"        :df, :dr, :usr, :notes)"),
                    {
                        'm1': r1['measure_id'], 'm2': r2['measure_id'],
                        'n1': r1['n'],          'n2': r2['n'],
                        's1': r1.get('spc'),    's2': r2.get('spc'),
                        'k1': r1.get('msk'),    'k2': r2.get('msk'),
                        'f1': r1.get('f'),      'f2': r2.get('f'),
                        'r1': r1.get('r'),      'r2': r2.get('r'),
                        'df': p['delta_f'],     'dr': p['delta_r'],
                        'usr': user,
                        'notes': f'import={import_tag} '
                                 f'row={p["row"]}',
                    },
                )
                pair_id = res.lastrowid

                for pid in (r1.get('pool_id'), r2.get('pool_id')):
                    if not pid:
                        continue
                    if keep_in_pool:
                        conn.execute(
                            text(f"UPDATE `{POOL_TABLE}` "
                                 f"SET status='used', pair_id=:pid "
                                 f"WHERE id=:id"),
                            {'pid': pair_id, 'id': pid},
                        )
                    else:
                        conn.execute(
                            text(f"DELETE FROM `{POOL_TABLE}` "
                                 f"WHERE id=:id"),
                            {'id': pid},
                        )
                saved += 1
        except Exception as e:
            failed.append({
                'row': p['row'], 'n_1': r1['n'], 'n_2': r2['n'],
                'error': str(e),
            })
            if verbose:
                prog.clear_line()
                print(f"  FAIL row {p['row']}: {e}")
    prog.close()

    print(f"\n[Import] Saved pairs: {saved}")
    if failed:
        print(f"[Import] FAILED rows: {len(failed)}")
        for f in failed[:15]:
            print(f"  row {f['row']}: {f['error']}")
        # лог ошибок в БД
        log_operation(
            'pairs_import_fail',
            f'import={import_tag}, count={len(failed)}, '
            f'details={json.dumps(failed, ensure_ascii=False)}',
            user,
        )

    log_operation(
        'pairs_import_done',
        f'import={import_tag}, saved={saved}, skipped={len(skips)}, '
        f'failed={len(failed)}, spc1={spc_1}, spc2={spc_2}, '
        f'keep={keep_in_pool}',
        user,
    )

    try:
        with engine.connect() as conn:
            cnt = conn.execute(text(
                f"SELECT COUNT(*) FROM `{PAIRS_TABLE}`"
            )).scalar()
            pool_left = conn.execute(text(
                f"SELECT COUNT(*) FROM `{POOL_TABLE}` "
                f"WHERE status='free'"
            )).scalar()
        print(f"[Import] Pairs table total: {cnt}")
        print(f"[Import] Pool 'free' left: {pool_left}")
    except Exception:
        pass

    return saved


# =============================================================================
# CLI
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description='Импорт пар резонаторов из Excel в БД '
                    '(резонаторы берутся из пула).')
    parser.add_argument('file', help='Путь к Excel-файлу')
    parser.add_argument('--spc-1', type=str, default=None,
                        help='Spc для столбца B (точное имя или подстрока)')
    parser.add_argument('--spc-2', type=str, default=None,
                        help='Spc для столбца C')
    parser.add_argument('--sheet', type=int, default=0)
    parser.add_argument('--skip-rows', type=str, default='',
                        help='Пропустить строки (1-based, через запятую)')
    parser.add_argument('--allow-psidata', action='store_true',
                        help='Искать и в psidata, если нет в пуле')
    parser.add_argument('--keep', action='store_true', dest='keep_in_pool',
                        help='Не удалять pool-записи, ставить status="used"')
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--verbose', action='store_true')
    parser.add_argument('--user', type=str, default=None)
    args = parser.parse_args()

    skip = []
    if args.skip_rows:
        for x in args.skip_rows.split(','):
            x = x.strip()
            if x.isdigit():
                skip.append(int(x))

    import_pairs_from_excel(
        args.file,
        spc_1=args.spc_1,
        spc_2=args.spc_2,
        allow_psidata=args.allow_psidata,
        keep_in_pool=args.keep_in_pool,
        dry_run=args.dry_run,
        verbose=args.verbose,
        skip_rows=skip,
        sheet=args.sheet,
        user=args.user,
    )


if __name__ == '__main__':
    main()