"""
Нейросетевые модели для генерации и валидации виртуальных замеров.

Stage 1: MLP-подбор значения с сохранением статуса.
Stage 2: Autoencoder-валидация реалистичности.

Порядок поиска MLP:
  1) rtype-специфичная (БД, затем файл);
  2) глобальная (БД, затем файл).

Порядок поиска AE:
  1) spec-специфичная;
  2) rtype-специфичная;
  3) глобальная.
Для каждой ступени сначала БД, затем файл.

В собранном exe (PyInstaller) файлы моделей не поставляются:
модели читаются ТОЛЬКО из таблицы virtual_nn_models
(флаг MODELS_FROM_DB_ONLY = True при sys.frozen).

Инференс — чистый numpy. Обучение — train_models.py (torch).
"""
import io
import os
import re
import sys

import numpy as np


MODELS_DIR       = os.path.join(os.path.dirname(__file__), 'models')
STATUS_MLP_PATH  = os.path.join(MODELS_DIR, 'status_mlp.npz')
AUTOENC_PATH     = os.path.join(MODELS_DIR, 'autoenc.npz')

_TABLE_NAME = 'virtual_nn_models'

# В собранном exe файлы .npz не поставляются — модели берутся только
# из таблицы virtual_nn_models. В dev-режиме файлы доступны для
# отладки. Можно принудительно включить через переменную окружения
# VIRTUAL_NN_DB_ONLY=1 (например, для тестов паритета dev/prod).
_IS_FROZEN          = bool(getattr(sys, 'frozen', False))
_ENV_DB_ONLY        = os.environ.get('VIRTUAL_NN_DB_ONLY', '').strip()
MODELS_FROM_DB_ONLY = _IS_FROZEN or _ENV_DB_ONLY in ('1', 'true', 'yes')

_mlp_cache     = {}
_autoenc_cache = {}

_engine_singleton = None
_table_ready      = False


# ============================================================================
# Порядок параметров
# ============================================================================
MLP_PARAMS = [
    'F', 'R', 'C0', 'Cq', 'L', 'Q', 'FT',
    'Fmax', 'Fmin', 'Fmaxm', 'Fptp', 'Fptp_2',
    'Slope', 'Mono', 'Rmax', 'Rmin',
    'Rsp1', 'Rsp2', 'Rsp3', 'RcRb',
    'C0_C1', 'C1_2C0', 'old1', 'old2', 'old3',
]
PARAM_INDEX   = {p: i for i, p in enumerate(MLP_PARAMS)}
N_PARAM_INPUT = len(MLP_PARAMS)

AE_KEYS = ['F', 'R', 'C0', 'Cq', 'Q', 'L']

OUTLIER_ABS_LIMIT   = 1e15
OUTLIER_SIGMA_LIMIT = 50.0

SPEC_PREFIX = 'spec::'


def _relu(x):
    return np.maximum(0.0, x)


def _safe_filename(name):
    if not name:
        return ''
    return re.sub(r'[^\w\-.]', '_', str(name))


# ============================================================================
# Пути к файлам
# ============================================================================
def mlp_path(rtype=None):
    if rtype:
        return os.path.join(MODELS_DIR,
                            f'status_mlp_{_safe_filename(rtype)}.npz')
    return STATUS_MLP_PATH


def autoenc_path(rtype=None, spc=None):
    if spc:
        return os.path.join(MODELS_DIR,
                            f'autoenc_spc_{_safe_filename(spc)}.npz')
    if rtype:
        return os.path.join(MODELS_DIR,
                            f'autoenc_{_safe_filename(rtype)}.npz')
    return AUTOENC_PATH


def autoenc_spec_db_tag(spc):
    if not spc:
        return None
    return f"{SPEC_PREFIX}{spc}"


def models_dir() -> str:
    return MODELS_DIR


# ============================================================================
# БД
# ============================================================================
def _get_engine():
    global _engine_singleton
    if _engine_singleton is not None:
        return _engine_singleton
    try:
        from Options import get_connection_string
        from sqlalchemy import create_engine
        _engine_singleton = create_engine(
            str(get_connection_string()),
            pool_pre_ping=True, future=True)
        return _engine_singleton
    except Exception as e:
        print(f"[Virtual_NN] _get_engine error: {e}", flush=True)
        _engine_singleton = False
        return None


def _ensure_models_table(engine) -> bool:
    global _table_ready
    if _table_ready:
        return True
    if engine is None:
        return False
    try:
        from sqlalchemy import text
        ddl = (
            "CREATE TABLE IF NOT EXISTS `virtual_nn_models` ("
            "`ID` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
            "`Kind` VARCHAR(8) NOT NULL,"
            "`Rtype` VARCHAR(255) NOT NULL DEFAULT '',"
            "`Data` LONGBLOB NOT NULL,"
            "`Meta` VARCHAR(1024) DEFAULT NULL,"
            "`TrainedAt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "`Size` INT UNSIGNED DEFAULT 0,"
            "PRIMARY KEY (`ID`),"
            "UNIQUE KEY `uq_kind_rtype` (`Kind`, `Rtype`)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        with engine.begin() as conn:
            conn.execute(text(ddl))
        _table_ready = True
        return True
    except Exception as e:
        print(f"[Virtual_NN] ensure_models_table error: {e}",
              flush=True)
        return False


def db_model_exists(kind: str, tag=None) -> bool:
    from sqlalchemy import text
    eng = _get_engine()
    if eng is None or not _ensure_models_table(eng):
        return False
    try:
        sql = text(
            "SELECT 1 FROM virtual_nn_models "
            "WHERE Kind = :k AND Rtype = :r LIMIT 1"
        )
        with eng.connect() as conn:
            row = conn.execute(sql, {
                'k': kind, 'r': tag or ''
            }).fetchone()
        return row is not None
    except Exception as e:
        print(f"[Virtual_NN] db_model_exists error: {e}", flush=True)
        return False


def load_model_bytes_from_db(kind: str, tag=None):
    from sqlalchemy import text
    eng = _get_engine()
    if eng is None or not _ensure_models_table(eng):
        return None
    try:
        sql = text(
            "SELECT Data FROM virtual_nn_models "
            "WHERE Kind = :k AND Rtype = :r LIMIT 1"
        )
        with eng.connect() as conn:
            row = conn.execute(sql, {
                'k': kind, 'r': tag or ''
            }).fetchone()
        if not row or not row[0]:
            return None
        return bytes(row[0])
    except Exception as e:
        print(f"[Virtual_NN] load_from_db error: {e}", flush=True)
        return None


def save_model_to_db(kind: str, tag, npz_bytes: bytes,
                     meta: dict = None) -> bool:
    from sqlalchemy import text
    import json

    eng = _get_engine()
    if eng is None:
        print("[Virtual_NN] save_to_db: engine недоступен", flush=True)
        return False
    if not _ensure_models_table(eng):
        return False

    try:
        meta_str = None
        if meta:
            try:
                meta_str = json.dumps(meta, ensure_ascii=False)[:1024]
            except Exception:
                meta_str = None

        sql = text(
            "INSERT INTO virtual_nn_models "
            "(Kind, Rtype, Data, Meta, Size) "
            "VALUES (:k, :r, :d, :m, :s) "
            "ON DUPLICATE KEY UPDATE "
            "Data=VALUES(Data), Meta=VALUES(Meta), "
            "Size=VALUES(Size), TrainedAt=CURRENT_TIMESTAMP"
        )
        with eng.begin() as conn:
            conn.execute(sql, {
                'k': kind,
                'r': tag or '',
                'd': npz_bytes,
                'm': meta_str,
                's': len(npz_bytes),
            })
        return True
    except Exception as e:
        print(f"[Virtual_NN] save_to_db error: {e}", flush=True)
        return False


# ============================================================================
# Парсеры npz
# ============================================================================
def _parse_mlp_npz(npz):
    return {
        'W1': npz['W1'], 'b1': npz['b1'],
        'W2': npz['W2'], 'b2': npz['b2'],
        'W3': npz['W3'], 'b3': npz['b3'],
        'x_mean': npz['x_mean'], 'x_std': npz['x_std'],
        'y_mean': npz['y_mean'], 'y_std': npz['y_std'],
    }


def _parse_autoenc_npz(npz):
    return {
        'W1': npz['W1'], 'b1': npz['b1'],
        'W2': npz['W2'], 'b2': npz['b2'],
        'W3': npz['W3'], 'b3': npz['b3'],
        'W4': npz['W4'], 'b4': npz['b4'],
        'W5': npz['W5'], 'b5': npz['b5'],
        'W6': npz['W6'], 'b6': npz['b6'],
        'x_mean': npz['x_mean'], 'x_std': npz['x_std'],
        'threshold': float(npz['threshold'][0])
                        if 'threshold' in npz else 0.5,
    }


def _load_mlp_from_bytes(data):
    with np.load(io.BytesIO(data)) as npz:
        return _parse_mlp_npz(npz)


def _load_autoenc_from_bytes(data):
    with np.load(io.BytesIO(data)) as npz:
        return _parse_autoenc_npz(npz)


def _load_mlp_from_file(path):
    with np.load(path) as npz:
        return _parse_mlp_npz(npz)


def _load_autoenc_from_file(path):
    with np.load(path) as npz:
        return _parse_autoenc_npz(npz)


# ============================================================================
# MLP: rtype → global (БД, при необходимости — файл)
# ============================================================================
def _load_mlp(rtype=None):
    key = rtype if rtype else '__global__'
    if key in _mlp_cache:
        return _mlp_cache[key] if _mlp_cache[key] is not False else None

    # ---- rtype-уровень ----
    if rtype:
        try:
            data = load_model_bytes_from_db('mlp', rtype)
            if data:
                m = _load_mlp_from_bytes(data)
                _mlp_cache[key] = m
                print(f"[Virtual_NN] MLP (БД, rtype='{rtype}')",
                      flush=True)
                return m
        except Exception as e:
            print(f"[Virtual_NN] load mlp(БД, {rtype}): {e}",
                  flush=True)
        if not MODELS_FROM_DB_ONLY:
            p = mlp_path(rtype)
            if os.path.exists(p):
                try:
                    m = _load_mlp_from_file(p)
                    _mlp_cache[key] = m
                    print(f"[Virtual_NN] MLP (файл, rtype='{rtype}')",
                          flush=True)
                    return m
                except Exception as e:
                    print(f"[Virtual_NN] load mlp(файл, {rtype}): {e}",
                          flush=True)

    # ---- глобальный уровень ----
    try:
        data = load_model_bytes_from_db('mlp', None)
        if data:
            m = _load_mlp_from_bytes(data)
            _mlp_cache[key] = m
            print("[Virtual_NN] MLP (БД, глобальная)", flush=True)
            return m
    except Exception as e:
        print(f"[Virtual_NN] load mlp(БД, global): {e}", flush=True)

    if not MODELS_FROM_DB_ONLY and os.path.exists(STATUS_MLP_PATH):
        try:
            m = _load_mlp_from_file(STATUS_MLP_PATH)
            _mlp_cache[key] = m
            print("[Virtual_NN] MLP (файл, глобальная)", flush=True)
            return m
        except Exception as e:
            print(f"[Virtual_NN] load mlp(файл, global): {e}",
                  flush=True)

    _mlp_cache[key] = False
    return None


# ============================================================================
# AE: spec → rtype → global (БД, при необходимости — файл)
# ============================================================================
def _load_autoenc(rtype=None, spc=None):
    if spc:
        key = f"{SPEC_PREFIX}{spc}"
    elif rtype:
        key = rtype
    else:
        key = '__global__'

    if key in _autoenc_cache:
        return _autoenc_cache[key] if _autoenc_cache[key] is not False \
                else None

    # ---- spec-уровень ----
    if spc:
        tag = autoenc_spec_db_tag(spc)
        try:
            data = load_model_bytes_from_db('ae', tag)
            if data:
                m = _load_autoenc_from_bytes(data)
                _autoenc_cache[key] = m
                print(f"[Virtual_NN] Autoencoder "
                      f"(БД, spc='{spc}', "
                      f"threshold={m['threshold']:.4f})", flush=True)
                return m
        except Exception as e:
            print(f"[Virtual_NN] load ae(БД, spc='{spc}'): {e}",
                  flush=True)
        if not MODELS_FROM_DB_ONLY:
            p = autoenc_path(spc=spc)
            if os.path.exists(p):
                try:
                    m = _load_autoenc_from_file(p)
                    _autoenc_cache[key] = m
                    print(f"[Virtual_NN] Autoencoder "
                          f"(файл, spc='{spc}', "
                          f"threshold={m['threshold']:.4f})",
                          flush=True)
                    return m
                except Exception as e:
                    print(f"[Virtual_NN] load ae(файл, spc='{spc}'): "
                          f"{e}", flush=True)

    # ---- rtype-уровень ----
    if rtype:
        try:
            data = load_model_bytes_from_db('ae', rtype)
            if data:
                m = _load_autoenc_from_bytes(data)
                _autoenc_cache[key] = m
                print(f"[Virtual_NN] Autoencoder "
                      f"(БД, rtype='{rtype}', "
                      f"threshold={m['threshold']:.4f})", flush=True)
                return m
        except Exception as e:
            print(f"[Virtual_NN] load ae(БД, {rtype}): {e}",
                  flush=True)
        if not MODELS_FROM_DB_ONLY:
            p = autoenc_path(rtype=rtype)
            if os.path.exists(p):
                try:
                    m = _load_autoenc_from_file(p)
                    _autoenc_cache[key] = m
                    print(f"[Virtual_NN] Autoencoder "
                          f"(файл, rtype='{rtype}', "
                          f"threshold={m['threshold']:.4f})",
                          flush=True)
                    return m
                except Exception as e:
                    print(f"[Virtual_NN] load ae(файл, {rtype}): {e}",
                          flush=True)

    # ---- глобальный уровень ----
    try:
        data = load_model_bytes_from_db('ae', None)
        if data:
            m = _load_autoenc_from_bytes(data)
            _autoenc_cache[key] = m
            print(f"[Virtual_NN] Autoencoder "
                  f"(БД, глобальная, "
                  f"threshold={m['threshold']:.4f})", flush=True)
            return m
    except Exception as e:
        print(f"[Virtual_NN] load ae(БД, global): {e}", flush=True)

    if not MODELS_FROM_DB_ONLY and os.path.exists(AUTOENC_PATH):
        try:
            m = _load_autoenc_from_file(AUTOENC_PATH)
            _autoenc_cache[key] = m
            print(f"[Virtual_NN] Autoencoder "
                  f"(файл, глобальная, "
                  f"threshold={m['threshold']:.4f})", flush=True)
            return m
        except Exception as e:
            print(f"[Virtual_NN] load ae(файл, global): {e}",
                  flush=True)

    _autoenc_cache[key] = False
    return None


def reload_models():
    global _mlp_cache, _autoenc_cache, _engine_singleton, _table_ready
    _mlp_cache = {}
    _autoenc_cache = {}
    _engine_singleton = None
    _table_ready = False


# ============================================================================
# Доступность и информация
# ============================================================================
def is_mlp_available(rtype=None) -> bool:
    key = rtype if rtype else '__global__'
    if key in _mlp_cache:
        return _mlp_cache[key] is not False
    return _load_mlp(rtype) is not None


def is_autoenc_available(rtype=None, spc=None) -> bool:
    if spc:
        key = f"{SPEC_PREFIX}{spc}"
    elif rtype:
        key = rtype
    else:
        key = '__global__'
    if key in _autoenc_cache:
        return _autoenc_cache[key] is not False
    return _load_autoenc(rtype=rtype, spc=spc) is not None


def get_mlp_info(rtype=None) -> dict | None:
    if rtype and db_model_exists('mlp', rtype):
        return {'rtype': rtype, 'source': 'db_rtype', 'path': None}
    if not MODELS_FROM_DB_ONLY and rtype:
        p = mlp_path(rtype)
        if os.path.exists(p):
            return {'rtype': rtype, 'source': 'file_rtype', 'path': p}
    if db_model_exists('mlp', None):
        return {'rtype': None, 'source': 'db_global', 'path': None}
    if not MODELS_FROM_DB_ONLY and os.path.exists(STATUS_MLP_PATH):
        return {'rtype': None, 'source': 'file_global',
                'path': STATUS_MLP_PATH}
    return None


def get_autoenc_info(rtype=None, spc=None) -> dict | None:
    if spc:
        tag = autoenc_spec_db_tag(spc)
        if db_model_exists('ae', tag):
            return {'spc': spc, 'rtype': None,
                    'source': 'db_spc', 'path': None}
        if not MODELS_FROM_DB_ONLY:
            p = autoenc_path(spc=spc)
            if os.path.exists(p):
                return {'spc': spc, 'rtype': None,
                        'source': 'file_spc', 'path': p}
    if rtype:
        if db_model_exists('ae', rtype):
            return {'spc': None, 'rtype': rtype,
                    'source': 'db_rtype', 'path': None}
        if not MODELS_FROM_DB_ONLY:
            p = autoenc_path(rtype=rtype)
            if os.path.exists(p):
                return {'spc': None, 'rtype': rtype,
                        'source': 'file_rtype', 'path': p}
    if db_model_exists('ae', None):
        return {'spc': None, 'rtype': None,
                'source': 'db_global', 'path': None}
    if not MODELS_FROM_DB_ONLY and os.path.exists(AUTOENC_PATH):
        return {'spc': None, 'rtype': None,
                'source': 'file_global', 'path': AUTOENC_PATH}
    return None


def list_available_models() -> dict:
    result = {'global': {'mlp': False, 'ae': False}}

    if not MODELS_FROM_DB_ONLY:
        if os.path.exists(STATUS_MLP_PATH):
            result['global']['mlp'] = True
        if os.path.exists(AUTOENC_PATH):
            result['global']['ae'] = True
        if os.path.isdir(MODELS_DIR):
            for fname in os.listdir(MODELS_DIR):
                if (fname.startswith('status_mlp_')
                        and fname.endswith('.npz')):
                    rt = fname[len('status_mlp_'):-len('.npz')]
                    result.setdefault(rt, {'mlp': False, 'ae': False})
                    result[rt]['mlp'] = True
                elif (fname.startswith('autoenc_spc_')
                        and fname.endswith('.npz')):
                    sp = fname[len('autoenc_spc_'):-len('.npz')]
                    key = f"{SPEC_PREFIX}{sp}"
                    result.setdefault(key, {'mlp': False, 'ae': False})
                    result[key]['ae'] = True
                elif (fname.startswith('autoenc_')
                        and fname.endswith('.npz')):
                    rt = fname[len('autoenc_'):-len('.npz')]
                    result.setdefault(rt, {'mlp': False, 'ae': False})
                    result[rt]['ae'] = True

    from sqlalchemy import text
    eng = _get_engine()
    if eng is not None and _ensure_models_table(eng):
        try:
            with eng.connect() as conn:
                rows = conn.execute(text(
                    "SELECT Kind, Rtype FROM virtual_nn_models"
                )).fetchall()
            for kind, rt in rows:
                key = rt if rt else 'global'
                result.setdefault(key, {'mlp': False, 'ae': False})
                if kind == 'mlp':
                    result[key]['mlp'] = True
                elif kind == 'ae':
                    result[key]['ae'] = True
        except Exception as e:
            print(f"[Virtual_NN] list DB error: {e}", flush=True)

    return result


# ============================================================================
# Stage 1: MLP
# ============================================================================
def predict_new_value(base_value, min_v, max_v, has_min, has_max,
                      expected_in_spec, param_name=None, rtype=None):
    m = _load_mlp(rtype)
    if not m:
        return None
    try:
        one_hot = np.zeros(N_PARAM_INPUT, dtype=np.float64)
        if param_name in PARAM_INDEX:
            one_hot[PARAM_INDEX[param_name]] = 1.0

        x = np.concatenate([
            np.array([
                float(base_value or 0.0),
                float(min_v) if min_v is not None else 0.0,
                float(max_v) if max_v is not None else 0.0,
                1.0 if has_min else 0.0,
                1.0 if has_max else 0.0,
                1.0 if expected_in_spec else 0.0,
            ], dtype=np.float64),
            one_hot,
        ])

        xs = (x - m['x_mean']) / m['x_std']
        h1 = _relu(xs @ m['W1'] + m['b1'])
        h2 = _relu(h1 @ m['W2'] + m['b2'])
        y  = h2 @ m['W3'] + m['b3']
        delta = float(y[0] * m['y_std'] + m['y_mean'])
        return float(base_value + delta)
    except Exception as e:
        print(f"[Virtual_NN] mlp predict error: {e}", flush=True)
        return None


# ============================================================================
# Stage 2: Autoencoder
# ============================================================================
def autoenc_score(values_dict, keys=None, rtype=None, spc=None,
                  diagnostic=False, threshold_override=None):
    """
    Reconstruction error по вектору параметров.

    rtype, spc — уровни поиска модели (spec → rtype → global).
    threshold_override — порог из настроек. Если задан, используется
                        вместо обученного p99.5.
    diagnostic=True: при score > threshold вывести в консоль топ-3
                     параметра по вкладу.

    Возвращает (score, is_anom, threshold, per_feature):
        per_feature[k] = {
            'contrib':      float,   # вклад в общий score
            'contrib_frac': float,   # доля вклада (0..1)
            'residual_z':   float,   # невязка в сигмах x_std
            'x':            float,
            'recon':        float,
        }
    или (None, False, None, {}) при недоступности/выбросе/ошибке.
    """
    if keys is None:
        keys = AE_KEYS
    m = _load_autoenc(rtype=rtype, spc=spc)
    if not m:
        return None, False, None, {}
    try:
        arr = []
        for k in keys:
            v = values_dict.get(k)
            try:
                fv = float(v) if v is not None else 0.0
            except (TypeError, ValueError):
                fv = 0.0
            if (not np.isfinite(fv)) or (abs(fv) > OUTLIER_ABS_LIMIT):
                print(f"[Virtual_NN] AE: пропуск {k}={fv:.4g} "
                      f"(выброс)", flush=True)
                return None, False, None, {}
            arr.append(fv)

        x = np.array(arr, dtype=np.float64)
        xs = (x - m['x_mean']) / m['x_std']

        max_abs_xs = float(np.max(np.abs(xs)))
        if max_abs_xs > OUTLIER_SIGMA_LIMIT:
            print(f"[Virtual_NN] AE: пропуск записи "
                  f"(max|xs|={max_abs_xs:.1f})", flush=True)
            return None, False, None, {}

        h1 = _relu(xs @ m['W1'] + m['b1'])
        h2 = _relu(h1 @ m['W2'] + m['b2'])
        h3 = h2 @ m['W3'] + m['b3']
        d1 = _relu(h3 @ m['W4'] + m['b4'])
        d2 = _relu(d1 @ m['W5'] + m['b5'])
        y  = d2 @ m['W6'] + m['b6']

        recon = y * m['x_std'] + m['x_mean']
        diff = x - recon

        rmse = float(np.sqrt(np.mean(diff ** 2)))
        denom = float(np.sqrt(np.mean(x ** 2))) + 1e-9
        score = rmse / denom

        if threshold_override is not None:
            try:
                threshold = float(threshold_override)
                if threshold <= 0:
                    threshold = m.get('threshold', 0.5)
            except (TypeError, ValueError):
                threshold = m.get('threshold', 0.5)
        else:
            threshold = m.get('threshold', 0.5)

        is_anom = score > threshold

        per_feature = {}
        contribs = []
        for i in range(len(keys)):
            c = float((diff[i] ** 2) / (m['x_std'][i] ** 2 + 1e-30))
            contribs.append(c)
        total_contrib = float(sum(contribs)) + 1e-30
        for i, k in enumerate(keys):
            residual_z = float(abs(diff[i]) / (m['x_std'][i] + 1e-30))
            per_feature[k] = {
                'contrib':      contribs[i],
                'contrib_frac': contribs[i] / total_contrib,
                'residual_z':   residual_z,
                'x':            float(x[i]),
                'recon':        float(recon[i]),
            }

        if diagnostic and is_anom:
            top = sorted(per_feature.items(),
                         key=lambda kv: kv[1]['contrib'],
                         reverse=True)[:3]
            parts = []
            for k, info in top:
                if info['contrib'] < 1e-4:
                    continue
                parts.append(
                    f"{k}: x={info['x']:.4g} "
                    f"recon={info['recon']:.4g} "
                    f"|rz|={info['residual_z']:.2f}σ "
                    f"frac={info['contrib_frac']:.2f}")
            if parts:
                print(f"[Virtual_NN] AE anomaly "
                      f"(score={score:.2f} > {threshold:.2f}): "
                      + " | ".join(parts), flush=True)

        return score, is_anom, threshold, per_feature
    except Exception as e:
        print(f"[Virtual_NN] autoenc error: {e}", flush=True)
        return None, False, None, {}