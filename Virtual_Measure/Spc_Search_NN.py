"""
Нейросетевой подбор спецификаций под измерительный файл и тип резонатора.

Модели сохраняются в таблицу virtual_nn_models — так же, как mlp/ae в
Virtual_Measure (Virtual_NN.py) и toc_if в TempOutlier_Correction
(learning.py):
  * Kind  = 'spcnn';
  * Rtype = ''          — глобальная модель (любой тип резонатора);
  * Rtype = '<NameR>'   — отдельная модель под тип резонатора.

Архитектура — ансамбль из нескольких небольших MLP-классификаторов
(n_in → hidden → hidden2 → 1). Признаковое описание пары
«измерительный файл ↔ спецификация» строит build_feature_vector
(feature version хранится в Meta). Выход каждого члена ансамбля —
sigmoid-вероятность пригодности спецификации; итоговый скор — среднее
по ансамблю.

Приоритет поиска модели (как у остальных kind):
  1) БД: Rtype-специфичная → глобальная;
  2) файлы (только НЕ в замороженном exe, см. Virtual_NN.MODELS_FROM_DB_ONLY):
     models/spcnn_<rtype>.npz → models/spcnn.npz.

Инференс — чистый numpy (torch не нужен в рантайме приложения).
Обучение — автономный скрипт train_spc_models.py:
    python -m Virtual_Measure.train_spc_models --all-rtypes --force
"""

import io
import os
import re

import numpy as np

from . import Virtual_NN

# Kind в virtual_nn_models (до 8 символов, рядом с mlp / ae / toc_if)
KIND_SPCNN = 'spcnn'

MODELS_DIR = os.path.join(os.path.dirname(__file__), 'models')

# ---------------------------------------------------------------------------
# Признаки. ВНИМАНИЕ: определяет совместимость обученных моделей.
# Любое изменение состава/порядка требует инкремента FEATURE_VERSION
# и переобучения (--force).
# ---------------------------------------------------------------------------
FEATURE_VERSION = 1

FEATURES = [
    # ---- номинал -----------------------------------------------------------
    'freq_ppm',          # |Δf|/REF_F * 1e6 / 100, с обрезкой сверху (50)
    'freq_exact',        # номинал совпадает «начисто» (±2 ppm)
    'freq_ok',           # номинал в допуске (±100 ppm)
    # ---- режим нагрузки ----------------------------------------------------
    'load_type_exact',   # LoadType спецификации == CL_Metod файла
    'load_type_compat',  # LoadType в списке совместимых (LOAD_TYPE_COMBINATIONS)
    'cl_required',       # спецификация предполагает нагрузку (LoadType != SERIES)
    'load_value_diff',   # относительное расхождение CL, 0 если CL не задан
    'load_value_ok',     # CL совпадает (≤5%) либо не задан
    # ---- температурный профиль --------------------------------------------
    'temp_iou',          # пересечение точек (IoU, ±0.5 °C)
    'temp_covered',      # профиль полностью покрыт измерением
    'temp_in_range',     # диапазон профиля вложен в диапазон файла
    # ---- дополнительные ----------------------------------------------------
    'spec_multy',        # мульти-спецификация
    'spec_nominal_log',  # log10(номинал, Гц) — масштаб спецификации
    'linked_nom',        # спецификация связана с номенклатурой контекста
]
N_FEATURES = len(FEATURES)

# Должно совпадать с Temperature_Measure.spc_matching
TEMP_EPS = 0.5
FREQ_TOL_PPM = 100.0
FREQ_EPS_PPM = 2.0

_ens_cache = {}
_matching_mod = None


def _safe_filename(name):
    if not name:
        return ''
    return re.sub(r'[^\w\-.]', '_', str(name))


def _to_float(v, default=0.0):
    try:
        out = float(str(v).strip())
    except (TypeError, ValueError):
        return default
    return out if np.isfinite(out) else default


def _cl_value_f(v):
    """'32' | '32(30)' | 32.0 → float (берём первое число)."""
    s = str(v).strip() if v is not None else ''
    if not s:
        return 0.0
    head = re.split(r'[^0-9.]+', s)[0]
    return _to_float(head, 0.0)


def _matching():
    """Общие функции сопоставления (Temperature_Measure.spc_matching)."""
    global _matching_mod
    if _matching_mod is None:
        from Temperature_Measure import spc_matching as M
        _matching_mod = M
    return _matching_mod


# ============================================================================
# Признаки совместимости «файл ↔ спецификация»
# ============================================================================
def build_feature_vector(ctx: dict, spec: dict) -> np.ndarray:
    """
    ctx  — контекст измерительного файла:
           ref_hz     — номинал в Гц (Target_Hz);
           cl_metod   — CL_Metod ('EQREACT'/'NUMERICAL'/'PHYSICAL'/'SERIES');
           cl_value   — значение CL ('32', '32(30)', 0);
           temps      — список температур файла;
           linked     — коллекция имён/ID спецификаций, связанных с
                        номенклатурой (не обязательно).
    spec — данные спецификации:
           name, id, nominal (МГц), load_type, load_value, multy,
           profile_temps.
    """
    M = _matching()

    ref_hz = abs(_to_float(ctx.get('ref_hz'), 0.0))
    if ref_hz <= 0:
        ref_hz = 1.0
    cl_metod = M.normalize_load_type(ctx.get('cl_metod'))
    cl_value = _cl_value_f(ctx.get('cl_value'))
    data_temps = M.parse_temp_list(ctx.get('temps'))
    linked = ctx.get('linked') or ()

    # ---- номинал ----
    spec_nominal_hz = _to_float(spec.get('nominal')) * 1e6
    d_ppm = M.freq_diff_ppm(spec_nominal_hz, ref_hz)
    if d_ppm is None:
        d_ppm = 1e9
    freq_ppm = min(d_ppm / 100.0, 50.0)
    freq_exact = 1.0 if d_ppm < FREQ_EPS_PPM else 0.0
    freq_ok = 1.0 if d_ppm < FREQ_TOL_PPM else 0.0

    # ---- режим нагрузки (ёмкостный фильтр убран: только тип и мягкое
    #      расхождение значения) ----
    load_type = M.normalize_load_type(spec.get('load_type'))
    lt_exact = 1.0 if load_type == cl_metod else 0.0
    lt_compat = 1.0 if M.load_types_compatible(cl_metod, load_type) else 0.0
    cl_required = 0.0 if load_type == 'SERIES' else 1.0
    spec_cl = _to_float(spec.get('load_value'))
    if cl_value > 0:
        lv_diff = min(abs(spec_cl - cl_value) / max(1.0, cl_value), 2.0)
        lv_ok = 1.0 if lv_diff <= 0.05 else 0.0
    else:
        lv_diff, lv_ok = 0.0, 1.0

    # ---- температурный профиль ----
    spec_temps = M.parse_temp_list(spec.get('profile_temps'))
    if spec_temps and data_temps:
        t_iou = M.temps_iou(data_temps, spec_temps)
        t_cov = 1.0 if M.temps_covered(spec_temps, data_temps) else 0.0
        t_range = 1.0 if (min(spec_temps) >= min(data_temps) - TEMP_EPS and
                          max(spec_temps) <= max(data_temps) + TEMP_EPS) \
            else 0.0
    else:
        t_iou = t_cov = t_range = 0.0

    # ---- дополнительные ----
    is_multy = 1.0 if str(spec.get('multy', 0)) in ('1', 'True', 'true') \
        else 0.0
    spec_nominal_log = float(np.log10(max(spec_nominal_hz, 1.0)))
    is_linked = 1.0 if (spec.get('name') in linked or
                        spec.get('id') in linked) else 0.0

    return np.array([
        freq_ppm, freq_exact, freq_ok,
        lt_exact, lt_compat,
        cl_required, lv_diff, lv_ok,
        t_iou, t_cov, t_range,
        is_multy, spec_nominal_log, is_linked,
    ], dtype=np.float64)


# ============================================================================
# Загрузка / сохранение модели (КИНД 'spcnn')
# ============================================================================
def spcnn_path(rtype=None):
    if rtype:
        return os.path.join(MODELS_DIR, f'spcnn_{_safe_filename(rtype)}.npz')
    return os.path.join(MODELS_DIR, 'spcnn.npz')


def _parse_ensemble_npz(npz):
    m = {
        'W1': np.asarray(npz['W1'], dtype=np.float64),
        'b1': np.asarray(npz['b1'], dtype=np.float64),
        'W2': np.asarray(npz['W2'], dtype=np.float64),
        'b2': np.asarray(npz['b2'], dtype=np.float64),
        'W3': np.asarray(npz['W3'], dtype=np.float64),
        'b3': np.asarray(npz['b3'], dtype=np.float64),
        'x_mean': np.asarray(npz['x_mean'], dtype=np.float64),
        'x_std': np.asarray(npz['x_std'], dtype=np.float64),
    }
    m['n_members'] = int(m['W1'].shape[0])
    return m


def _load_ensemble_bytes(data):
    with np.load(io.BytesIO(data)) as npz:
        return _parse_ensemble_npz(npz)


def _load_ensemble_file(path):
    with np.load(path) as npz:
        return _parse_ensemble_npz(npz)


def _load_ensemble(rtype=None):
    """
    Приоритет: БД (rtype → global) → файл (rtype → global, только dev).
    Возвращает dict модели или None (кэшируется).
    """
    key = rtype if rtype else '__global__'
    if key in _ens_cache:
        return _ens_cache[key] if _ens_cache[key] is not False else None

    # ---- БД, уровень rtype ----
    if rtype:
        try:
            data = Virtual_NN.load_model_bytes_from_db(KIND_SPCNN, rtype)
            if data:
                m = _load_ensemble_bytes(data)
                _ens_cache[key] = m
                print(f"[Spc_Search_NN] модель (БД, rtype='{rtype}', "
                      f"членов ансамбля {m['n_members']})", flush=True)
                return m
        except Exception as e:
            print(f"[Spc_Search_NN] load (БД, {rtype}): {e}", flush=True)

    # ---- БД, глобальная ----
    try:
        data = Virtual_NN.load_model_bytes_from_db(KIND_SPCNN, None)
        if data:
            m = _load_ensemble_bytes(data)
            _ens_cache[key] = m
            print(f"[Spc_Search_NN] модель (БД, глобальная, "
                  f"членов ансамбля {m['n_members']})", flush=True)
            return m
    except Exception as e:
        print(f"[Spc_Search_NN] load (БД, global): {e}", flush=True)

    # ---- файлы (только dev-режим / отладка) ----
    if not Virtual_NN.MODELS_FROM_DB_ONLY:
        paths = [spcnn_path(rtype)] if rtype else []
        paths.append(spcnn_path(None))
        for p in paths:
            if os.path.exists(p):
                try:
                    m = _load_ensemble_file(p)
                    _ens_cache[key] = m
                    print(f"[Spc_Search_NN] модель (файл {p})", flush=True)
                    return m
                except Exception as e:
                    print(f"[Spc_Search_NN] load (файл {p}): {e}", flush=True)

    _ens_cache[key] = False
    return None


def spcnn_available(rtype=None) -> bool:
    return _load_ensemble(rtype) is not None


def get_spcnn_info(rtype=None):
    if rtype and Virtual_NN.db_model_exists(KIND_SPCNN, rtype):
        return {'rtype': rtype, 'source': 'db_rtype'}
    if Virtual_NN.db_model_exists(KIND_SPCNN, None):
        return {'rtype': None, 'source': 'db_global'}
    if not Virtual_NN.MODELS_FROM_DB_ONLY:
        if os.path.exists(spcnn_path(rtype)):
            return {'rtype': rtype, 'source': 'file_rtype',
                    'path': spcnn_path(rtype)}
        if os.path.exists(spcnn_path(None)):
            return {'rtype': None, 'source': 'file_global',
                    'path': spcnn_path(None)}
    return None


def save_spcnn(npz_bytes: bytes, rtype=None, meta: dict = None,
               save_to_db=True, save_to_file=True) -> bool:
    """
    Сохранить обученный ансамбль (вызывается из train_spc_models.py):
      * БД — virtual_nn_models, Kind='spcnn', Rtype=rtype/'' (upsert);
      * файл — models/spcnn[_<rtype>].npz (для отладки в dev-режиме).
    """
    saved_any = False
    label = f"rtype='{rtype}'" if rtype else 'глобальная'
    if save_to_db:
        ok = Virtual_NN.save_model_to_db(KIND_SPCNN, rtype or '',
                                         npz_bytes, meta)
        if ok:
            print(f"[train spcnn] БД: virtual_nn_models ({label}, "
                  f"{len(npz_bytes)} байт)", flush=True)
            saved_any = True
        else:
            print("[train spcnn] БД: ошибка сохранения", flush=True)
    if save_to_file:
        try:
            path = spcnn_path(rtype)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'wb') as f:
                f.write(npz_bytes)
            print(f"[train spcnn] файл: {path} ({len(npz_bytes)} байт)",
                  flush=True)
            saved_any = True
        except Exception as e:
            print(f"[train spcnn] файл: ошибка {e}", flush=True)
    return saved_any


def reload_models():
    _ens_cache.clear()
    Virtual_NN.reload_models()


# ============================================================================
# Инференс (чистый numpy)
# ============================================================================
def _relu(x):
    return np.maximum(0.0, x)


def _sigmoid(z):
    return 1.0 / (1.0 + np.exp(-np.clip(z, -30.0, 30.0)))


def _predict_probs(m, X):
    """X: (n, N_FEATURES) → вероятности (n,) — среднее по ансамблю."""
    xs = (X - m['x_mean']) / m['x_std']
    probs = []
    for e in range(m['n_members']):
        h1 = _relu(xs @ m['W1'][e] + m['b1'][e])
        h2 = _relu(h1 @ m['W2'][e] + m['b2'][e])
        z = h2 @ m['W3'][e] + m['b3'][e]
        probs.append(_sigmoid(z[:, 0]))
    return np.mean(probs, axis=0)


def score_candidates(ctx: dict, candidates, rtype=None):
    """
    Вероятности пригодности для списка спецификаций.
    :param candidates: список dict (или один dict) с полями спецификации
    :return: np.ndarray (n,) вероятностей или None, если модель недоступна
    """
    try:
        if isinstance(candidates, dict):
            candidates = [candidates]
        if not candidates:
            return None
        m = _load_ensemble(rtype)
        if not m:
            return None
        X = np.vstack([build_feature_vector(ctx, c) for c in candidates])
        return _predict_probs(m, X)
    except Exception as e:
        print(f"[Spc_Search_NN] score error: {e}", flush=True)
        return None


def rank_spec_candidates(ctx: dict, candidates, rtype=None):
    """
    Кандидаты, отсортированные по убыванию вероятности пригодности.
    :return: список [(spec_dict, prob)] или [] если модель недоступна.
    """
    probs = score_candidates(ctx, candidates, rtype=rtype)
    if probs is None or len(candidates) == 0:
        return []
    pairs = sorted(zip(list(candidates), probs),
                   key=lambda cp: float(cp[1]), reverse=True)
    return [(c, float(p)) for c, p in pairs]


def list_available_models() -> list:
    """Список записей kind='spcnn' в virtual_nn_models."""
    eng = Virtual_NN._get_engine()
    if eng is None or not Virtual_NN._ensure_models_table(eng):
        return []
    try:
        from sqlalchemy import text
        with eng.connect() as conn:
            rows = conn.execute(text(
                "SELECT Kind, Rtype, Size, TrainedAt, Meta "
                "FROM virtual_nn_models WHERE Kind = :k "
                "ORDER BY TrainedAt DESC"
            ), {'k': KIND_SPCNN}).mappings().fetchall()
        import json
        out = []
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r['Meta'] or '{}')
            except Exception:
                pass
            out.append({
                'kind': r['Kind'],
                'rtype': r['Rtype'] or '',
                'size': r['Size'],
                'trained_at': str(r['TrainedAt']),
                'feature_version': meta.get('feature_version'),
                'n_members': meta.get('n_members'),
            })
        return out
    except Exception as e:
        print(f"[Spc_Search_NN] list_available_models: {e}", flush=True)
        return []
