"""
Обучение моделей для Virtual_Measure.

Требует PyTorch:
    pip install torch

Модели сохраняются в ДВУХ местах:
  * файл: models/status_mlp[_<rtype>].npz,
          models/autoenc[_<rtype>].npz,
          models/autoenc_spc_<spec>.npz;
  * таблица БД virtual_nn_models.

При загрузке (Virtual_NN._load_*) приоритет:
  MLP:    rtype-БД → rtype-файл → global-БД → global-файл
  AE:     spec-БД  → spec-файл → rtype-БД → rtype-файл
                    → global-БД → global-файл

CLI:
    # Оба этапа (MLP + AE) глобально; существующие пропускаются:
    python -m Virtual_Measure.train_models

    # Переобучить ТОЛЬКО MLP (AE не трогается):
    python -m Virtual_Measure.train_models --mlp-only --force

    # Переобучить ТОЛЬКО AE:
    python -m Virtual_Measure.train_models --ae-only --force

    # Оба этапа для всех типов из specification:
    python -m Virtual_Measure.train_models --all-rtypes --force

    # Только MLP для конкретного типа:
    python -m Virtual_Measure.train_models --rtype "РК526" --mlp-only --force

    # AE для конкретной спецификации (spec → rtype → global):
    python -m Virtual_Measure.train_models --spc "РК450-10М-144-1" --force

    # AE для всех спецификаций (может занять часы):
    python -m Virtual_Measure.train_models --all-specs

    # Сохранять только в БД (без файлов):
    python -m Virtual_Measure.train_models --no-file

    # Сохранять только в файл (без БД):
    python -m Virtual_Measure.train_models --no-db
"""
import argparse
import io
import os
import random

import numpy as np
import pandas as pd
from sqlalchemy import text

from .Virtual_Data import _engine, _in_spec, _safe_float, _safe_str
from . import Virtual_NN
from .Virtual_NN import (
    MODELS_DIR, STATUS_MLP_PATH, AUTOENC_PATH,
    AE_KEYS, MLP_PARAMS, PARAM_INDEX, N_PARAM_INPUT,
    OUTLIER_ABS_LIMIT, SPEC_PREFIX,
    mlp_path as _mlp_model_path,
    autoenc_path as _ae_model_path,
)


# ============================================================================
# Справочники
# ============================================================================
def list_all_rtypes() -> list:
    """Все типы резонаторов, для которых есть записи в psidata."""
    eng = _engine()
    try:
        df = pd.read_sql(
            "SELECT DISTINCT s.NameR AS rtype "
            "FROM specification s "
            "INNER JOIN psidata p ON p.Spc = s.Name "
            "WHERE s.NameR IS NOT NULL AND s.NameR <> '' "
            "ORDER BY s.NameR", eng)
        return df['rtype'].dropna().astype(str).tolist()
    except Exception as e:
        print(f"[train] list_all_rtypes error: {e}", flush=True)
        return []


def list_all_specs() -> list:
    """Все спецификации, у которых есть записи в psidata."""
    eng = _engine()
    try:
        df = pd.read_sql(
            "SELECT DISTINCT s.Name AS spec "
            "FROM specification s "
            "INNER JOIN psidata p ON p.Spc = s.Name "
            "WHERE s.Name IS NOT NULL AND s.Name <> '' "
            "ORDER BY s.Name", eng)
        return df['spec'].dropna().astype(str).tolist()
    except Exception as e:
        print(f"[train] list_all_specs error: {e}", flush=True)
        return []


# ============================================================================
# Данные для MLP
# ============================================================================
def _iter_params(rtype=None, spec_name=None):
    """Генератор (field, min_v, max_v, vals).

    spec_name задан — только эта спецификация.
    rtype задан     — только спецификации этого типа.
    иначе           — все.
    """
    eng = _engine()
    try:
        if spec_name:
            spcs = pd.read_sql(
                text("SELECT * FROM specification WHERE Name = :n"),
                eng, params={'n': spec_name})
        elif rtype:
            spcs = pd.read_sql(
                text("SELECT * FROM specification WHERE NameR = :t"),
                eng, params={'t': rtype})
        else:
            spcs = pd.read_sql("SELECT * FROM specification", eng)
        spc_map = pd.read_sql(
            "SELECT * FROM spc_map_table ORDER BY ID", eng)
    except Exception as e:
        print(f"[train] DB error: {e}", flush=True)
        return

    for _, spc_row in spcs.iterrows():
        spc_name = _safe_str(spc_row.get('Name'))
        if not spc_name:
            continue
        try:
            df = pd.read_sql(
                text("SELECT * FROM psidata WHERE Spc = :s LIMIT 2000"),
                eng, params={'s': spc_name})
        except Exception:
            continue
        if df.empty:
            continue

        for _, m in spc_map.iterrows():
            use_field = _safe_str(m.get('Use'))
            if not use_field:
                continue
            if _safe_str(spc_row.get(use_field)).lower() not in (
                    'true', '1', 'yes'):
                continue
            param = _safe_str(m.get('Parameter_Name'))
            if not param or param not in df.columns:
                continue
            min_col = _safe_str(m.get('Min'))
            max_col = _safe_str(m.get('Max'))
            min_v = (_safe_float(spc_row.get(min_col))
                     if min_col else None)
            max_v = (_safe_float(spc_row.get(max_col))
                     if max_col else None)
            vals = pd.to_numeric(df[param], errors='coerce').dropna()
            if vals.empty:
                continue
            yield param, min_v, max_v, vals.tolist()


def _brute_force_value(base_v, min_v, max_v, expected, max_attempts=64):
    """Текущая brute-force логика из generate_value — 'учитель'."""
    delta_max = abs(float(base_v)) * 0.5 / 100.0
    if delta_max < 1e-12:
        delta_max = 0.05
    has_min = min_v is not None
    has_max = max_v is not None

    for _ in range(max_attempts):
        cand = base_v + random.uniform(-delta_max, delta_max)
        if _in_spec(cand, min_v, max_v) == expected:
            return cand

    eps = abs(delta_max) * 1e-3 + 1e-12
    if expected:
        lo = base_v - delta_max
        hi = base_v + delta_max
        if has_min:
            lo = max(lo, min_v + eps)
        if has_max:
            hi = min(hi, max_v - eps)
        if lo > hi:
            return base_v
        return random.uniform(lo, hi)
    else:
        if has_min and base_v < min_v:
            hi = min_v - eps
            lo = min(base_v - delta_max, hi - delta_max)
            return random.uniform(lo, hi)
        if has_max and base_v > max_v:
            lo = max_v + eps
            hi = max(base_v + delta_max, lo + delta_max)
            return random.uniform(lo, hi)
    return base_v


def generate_mlp_training_data(target=30000, rtype=None):
    """Собрать (base, min, max, has_min, has_max, expected,
                one_hot(param), delta)."""
    rows = []
    seen = set()
    per_param = {}
    max_per_param = max(500, target // len(MLP_PARAMS))

    label = f"rtype='{rtype}'" if rtype else "глобальная"
    print(f"[train mlp] сбор данных ({label})...", flush=True)

    for field, min_v, max_v, vals in _iter_params(rtype=rtype):
        if field not in PARAM_INDEX:
            continue
        if per_param.get(field, 0) >= max_per_param:
            continue

        sample = random.sample(vals, min(300, len(vals)))
        for base_v in sample:
            if per_param.get(field, 0) >= max_per_param:
                break
            base_v = float(base_v)
            expected = _in_spec(base_v, min_v, max_v)
            key = (field, round(base_v, 4), min_v, max_v, bool(expected))
            if key in seen:
                continue
            seen.add(key)

            best = _brute_force_value(base_v, min_v, max_v, expected)
            delta = float(best) - base_v

            one_hot = [0.0] * N_PARAM_INPUT
            one_hot[PARAM_INDEX[field]] = 1.0

            rows.append(
                [base_v,
                 float(min_v) if min_v is not None else 0.0,
                 float(max_v) if max_v is not None else 0.0,
                 1.0 if min_v is not None else 0.0,
                 1.0 if max_v is not None else 0.0,
                 1.0 if expected else 0.0]
                + one_hot
                + [delta]
            )
            per_param[field] = per_param.get(field, 0) + 1

    if not rows:
        print(f"[train mlp] нет данных для {label}", flush=True)
        return None
    arr = np.array(rows, dtype=np.float64)
    print(f"[train mlp] примеров: {arr.shape[0]}", flush=True)
    print(f"[train mlp] по параметрам: "
          f"{dict(sorted(per_param.items()))}", flush=True)
    return arr


def train_mlp(arr, hidden=128, epochs=200, lr=5e-4, rtype=None):
    """Возвращает (npz_bytes, meta) или None."""
    try:
        import torch
        import torch.nn as nn
        import torch.optim as optim
    except ImportError:
        print("[train] torch не установлен: pip install torch",
              flush=True)
        return None

    n_in = 6 + N_PARAM_INPUT
    X = arr[:, :n_in]
    y = arr[:, n_in:n_in + 1]

    x_mean = X.mean(axis=0)
    x_std = X.std(axis=0)
    x_std[x_std < 1e-9] = 1.0
    y_mean = float(y.mean())
    y_std = float(y.std()) or 1.0

    Xs = (X - x_mean) / x_std
    ys = (y - y_mean) / y_std

    Xt = torch.from_numpy(Xs.astype(np.float32))
    yt = torch.from_numpy(ys.astype(np.float32))

    class MLP(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(n_in, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden), nn.ReLU(),
                nn.Linear(hidden, 1),
            )

        def forward(self, x):
            return self.net(x)

    model = MLP()
    opt = optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    n = Xt.shape[0]
    bs = min(1024, n)
    for epoch in range(epochs):
        idx = torch.randperm(n)
        total = 0.0
        for i in range(0, n, bs):
            batch = idx[i:i + bs]
            opt.zero_grad()
            out = model(Xt[batch])
            loss = loss_fn(out, yt[batch])
            loss.backward()
            opt.step()
            total += float(loss.item()) * len(batch)
        if (epoch + 1) % 25 == 0:
            print(f"[train mlp] epoch {epoch + 1}/{epochs}, "
                  f"loss={total / n:.6f}", flush=True)

    sd = model.state_dict()
    buf = io.BytesIO()
    np.savez(buf,
             W1=sd['net.0.weight'].numpy().T.astype(np.float64),
             b1=sd['net.0.bias'].numpy().astype(np.float64),
             W2=sd['net.2.weight'].numpy().T.astype(np.float64),
             b2=sd['net.2.bias'].numpy().astype(np.float64),
             W3=sd['net.4.weight'].numpy().T.astype(np.float64),
             b3=sd['net.4.bias'].numpy().astype(np.float64),
             x_mean=x_mean, x_std=x_std,
             y_mean=np.array([y_mean]),
             y_std=np.array([y_std]))

    meta = {
        'kind': 'mlp',
        'rtype': rtype or '',
        'hidden': hidden,
        'epochs': epochs,
        'lr': lr,
        'n_samples': int(Xt.shape[0]),
        'loss_final': float(total / n),
    }
    return buf.getvalue(), meta


# ============================================================================
# Данные для AE
# ============================================================================
def generate_ae_training_data(max_total=50000, per_spc_max=3000,
                              rtype=None, spec_name=None):
    """Сэмплировать реальные записи [F, R, C0, Cq, Q, L].

    spec_name задан — только эта спецификация (AE для одной spec).
    rtype задан     — все спецификации этого типа.
    иначе           — глобальная выборка.
    """
    eng = _engine()
    try:
        if spec_name:
            spcs = pd.read_sql(
                text("SELECT s.Name AS Spc, COUNT(*) AS cnt "
                     "FROM psidata p "
                     "INNER JOIN specification s ON s.Name = p.Spc "
                     "WHERE s.Name = :n "
                     "GROUP BY s.Name"),
                eng, params={'n': spec_name})
            per_spc = max_total
        elif rtype:
            spcs = pd.read_sql(
                text("SELECT s.Name AS Spc, COUNT(*) AS cnt "
                     "FROM psidata p "
                     "INNER JOIN specification s ON s.Name = p.Spc "
                     "WHERE s.NameR = :t "
                     "GROUP BY s.Name"),
                eng, params={'t': rtype})
            n_spc = max(1, len(spcs))
            per_spc = max(200, min(per_spc_max,
                                    int(max_total / n_spc)))
        else:
            spcs = pd.read_sql(
                "SELECT Spc, COUNT(*) AS cnt FROM psidata "
                "WHERE Spc IS NOT NULL GROUP BY Spc", eng)
            n_spc = max(1, len(spcs))
            per_spc = max(200, min(per_spc_max,
                                    int(max_total / n_spc)))
    except Exception as e:
        print(f"[train ae] DB error: {e}", flush=True)
        return None

    if spcs.empty:
        print("[train ae] нет спецификаций", flush=True)
        return None

    if spec_name:
        label = f"spec='{spec_name}'"
    elif rtype:
        label = f"rtype='{rtype}'"
    else:
        label = "глобальная"

    print(f"[train ae] {label}: спецификаций {len(spcs)}, "
          f"по {per_spc} записей", flush=True)

    chunks = []
    n_dropped = 0
    for _, row in spcs.iterrows():
        spc = _safe_str(row['Spc'])
        if not spc:
            continue
        cols = ", ".join(f"`{k}`" for k in AE_KEYS)
        try:
            df = pd.read_sql(
                text(f"SELECT {cols} FROM psidata WHERE Spc = :s "
                     f"ORDER BY RAND() LIMIT {per_spc}"),
                eng, params={'s': spc})
        except Exception:
            continue
        if df.empty:
            continue
        for k in AE_KEYS:
            df[k] = pd.to_numeric(df[k], errors='coerce')
        df = df.dropna()

        before = len(df)
        for k in AE_KEYS:
            df = df[df[k].abs() < OUTLIER_ABS_LIMIT]
        n_dropped += (before - len(df))

        if not df.empty:
            chunks.append(df[AE_KEYS].values)

    if not chunks:
        print("[train ae] нет валидных данных", flush=True)
        return None

    arr = np.vstack(chunks)
    if arr.shape[0] > max_total:
        idx = np.random.choice(arr.shape[0], max_total, replace=False)
        arr = arr[idx]

    print(f"[train ae] отброшено выбросов: {n_dropped}", flush=True)
    print(f"[train ae] сэмплировано: {arr.shape[0]} записей",
          flush=True)
    return arr


def train_autoenc(X, hidden=12, epochs=300, lr=5e-4, rtype=None):
    """Возвращает (npz_bytes, meta) или None."""
    try:
        import torch
        import torch.nn as nn
        import torch.optim as optim
    except ImportError:
        print("[train] torch не установлен", flush=True)
        return None

    mask = np.ones(X.shape[0], dtype=bool)
    for i in range(X.shape[1]):
        mask &= np.abs(X[:, i]) < OUTLIER_ABS_LIMIT
    if not mask.all():
        print(f"[train ae] выбросов: {(~mask).sum()}, отбрасываю",
              flush=True)
        X = X[mask]
    if X.shape[0] < 100:
        print("[train ae] слишком мало данных после фильтра",
              flush=True)
        return None

    x_mean = X.mean(axis=0)
    x_raw_std = X.std(axis=0)
    print("[train ae] статистика по полям:", flush=True)
    for i, k in enumerate(AE_KEYS):
        print(f"  {k}: mean={x_mean[i]:.4g}, "
              f"std={x_raw_std[i]:.4g}", flush=True)

    min_std = 1e-3 * np.maximum(np.abs(x_mean), 1.0)
    x_std = np.maximum(x_raw_std, min_std)

    for i, k in enumerate(AE_KEYS):
        if x_raw_std[i] < min_std[i]:
            print(f"[train ae] WARN: {k} std={x_raw_std[i]:.4g} "
                  f"слишком мал, использую {x_std[i]:.4g}",
                  flush=True)

    Xs = (X - x_mean) / x_std
    Xt = torch.from_numpy(Xs.astype(np.float32))
    d = Xt.shape[1]

    class AE(nn.Module):
        def __init__(self):
            super().__init__()
            self.enc = nn.Sequential(
                nn.Linear(d, 48), nn.ReLU(),
                nn.Linear(48, 24), nn.ReLU(),
                nn.Linear(24, hidden),
            )
            self.dec = nn.Sequential(
                nn.Linear(hidden, 24), nn.ReLU(),
                nn.Linear(24, 48), nn.ReLU(),
                nn.Linear(48, d),
            )

        def forward(self, x):
            return self.dec(self.enc(x))

    model = AE()
    opt = optim.Adam(model.parameters(), lr=lr)
    loss_fn = nn.MSELoss()

    n = Xt.shape[0]
    bs = min(512, n)
    for epoch in range(epochs):
        idx = torch.randperm(n)
        total = 0.0
        for i in range(0, n, bs):
            batch = idx[i:i + bs]
            opt.zero_grad()
            out = model(Xt[batch])
            loss = loss_fn(out, Xt[batch])
            loss.backward()
            opt.step()
            total += float(loss.item()) * len(batch)
        if (epoch + 1) % 50 == 0:
            print(f"[train ae] epoch {epoch + 1}/{epochs}, "
                  f"loss={total / n:.6f}", flush=True)

    with torch.no_grad():
        recon = model(Xt)
        diff = (Xt - recon).numpy()
    rmse = np.sqrt(np.mean(diff ** 2, axis=1))
    denom = np.sqrt(np.mean(Xs ** 2, axis=1)) + 1e-9
    scores = rmse / denom

    threshold = float(np.percentile(scores, 99.5))
    print(f"[train ae] score: mean={scores.mean():.3f}, "
          f"p95={np.percentile(scores, 95):.3f}, "
          f"p99.5={threshold:.3f}, max={scores.max():.3f}",
          flush=True)
    print(f"[train ae] xs range: [{Xs.min():.2f}, {Xs.max():.2f}]",
          flush=True)

    sd = model.state_dict()
    buf = io.BytesIO()
    np.savez(buf,
             W1=sd['enc.0.weight'].numpy().T.astype(np.float64),
             b1=sd['enc.0.bias'].numpy().astype(np.float64),
             W2=sd['enc.2.weight'].numpy().T.astype(np.float64),
             b2=sd['enc.2.bias'].numpy().astype(np.float64),
             W3=sd['enc.4.weight'].numpy().T.astype(np.float64),
             b3=sd['enc.4.bias'].numpy().astype(np.float64),
             W4=sd['dec.0.weight'].numpy().T.astype(np.float64),
             b4=sd['dec.0.bias'].numpy().astype(np.float64),
             W5=sd['dec.2.weight'].numpy().T.astype(np.float64),
             b5=sd['dec.2.bias'].numpy().astype(np.float64),
             W6=sd['dec.4.weight'].numpy().T.astype(np.float64),
             b6=sd['dec.4.bias'].numpy().astype(np.float64),
             x_mean=x_mean, x_std=x_std,
             threshold=np.array([threshold]))

    meta = {
        'kind': 'ae',
        'rtype': rtype or '',
        'hidden': hidden,
        'epochs': epochs,
        'lr': lr,
        'n_samples': int(Xt.shape[0]),
        'threshold': threshold,
        'loss_final': float(total / n),
    }
    return buf.getvalue(), meta


# ============================================================================
# Сохранение (файл + БД)
# ============================================================================
def _save_model(kind, rtype, npz_bytes, meta,
                save_to_file, save_to_db, spc=None):
    """
    kind: 'mlp' | 'ae'
    spc:  если задан — сохраняем как spec-уровень AE
          (models/autoenc_spc_<spec>.npz и Rtype='spec::<spec>').
    """
    if spc:
        label = f"spec='{spc}'"
        file_path = _ae_model_path(spc=spc)
        db_tag = f"{SPEC_PREFIX}{spc}"
    else:
        label = f"rtype='{rtype}'" if rtype else "глобальная"
        if kind == 'mlp':
            file_path = _mlp_model_path(rtype)
        else:
            file_path = _ae_model_path(rtype)
        db_tag = rtype or ''

    saved_any = False

    if save_to_file:
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, 'wb') as f:
                f.write(npz_bytes)
            print(f"[train {kind}] файл: {file_path} "
                  f"({len(npz_bytes)} байт)", flush=True)
            saved_any = True
        except Exception as e:
            print(f"[train {kind}] файл: ошибка {e}", flush=True)

    if save_to_db:
        ok = Virtual_NN.save_model_to_db(kind, db_tag, npz_bytes, meta)
        if ok:
            print(f"[train {kind}] БД: virtual_nn_models ({label}, "
                  f"{len(npz_bytes)} байт)", flush=True)
            saved_any = True
        else:
            print(f"[train {kind}] БД: ошибка сохранения", flush=True)

    return saved_any


# ============================================================================
# Один rtype (или глобальный)
# ============================================================================
def train_for_rtype(rtype, do_mlp, do_ae, force_mlp, force_ae,
                     save_to_file=True, save_to_db=True):
    label = f"rtype='{rtype}'" if rtype else "глобальная"
    print(f"\n========== {label} ==========", flush=True)

    # ---------- MLP ----------
    if do_mlp:
        exists_file = os.path.exists(_mlp_model_path(rtype))
        exists_db = (save_to_db
                     and Virtual_NN.db_model_exists('mlp', rtype))

        if (exists_file or exists_db) and not force_mlp:
            where = []
            if exists_file:
                where.append('файл')
            if exists_db:
                where.append('БД')
            print(f"[train mlp] уже существует ({'+'.join(where)}), "
                  f"пропуск (--force / --force-mlp)", flush=True)
        else:
            arr = generate_mlp_training_data(target=30000, rtype=rtype)
            if arr is None or arr.shape[0] < 50:
                n = 0 if arr is None else arr.shape[0]
                print(f"[train mlp] мало данных ({n}), пропуск",
                      flush=True)
            else:
                result = train_mlp(arr, rtype=rtype)
                if result is None:
                    print("[train mlp] не удалось обучить",
                          flush=True)
                else:
                    npz_bytes, meta = result
                    _save_model('mlp', rtype, npz_bytes, meta,
                                save_to_file, save_to_db)

    # ---------- AE ----------
    if do_ae:
        exists_file = os.path.exists(_ae_model_path(rtype))
        exists_db = (save_to_db
                     and Virtual_NN.db_model_exists('ae', rtype))

        if (exists_file or exists_db) and not force_ae:
            where = []
            if exists_file:
                where.append('файл')
            if exists_db:
                where.append('БД')
            print(f"[train ae] уже существует ({'+'.join(where)}), "
                  f"пропуск (--force / --force-ae)", flush=True)
        else:
            arr = generate_ae_training_data(
                max_total=50000, rtype=rtype)
            if arr is None or arr.shape[0] < 100:
                n = 0 if arr is None else arr.shape[0]
                print(f"[train ae] мало данных ({n}), пропуск",
                      flush=True)
            else:
                result = train_autoenc(arr, rtype=rtype)
                if result is None:
                    print("[train ae] не удалось обучить", flush=True)
                else:
                    npz_bytes, meta = result
                    _save_model('ae', rtype, npz_bytes, meta,
                                save_to_file, save_to_db)


# ============================================================================
# Одна спецификация (AE-only)
# ============================================================================
def train_for_spec(spc_name, force_ae, save_to_file=True,
                    save_to_db=True):
    """
    Обучить AE для конкретной спецификации.
    MLP на spec-уровне не поддерживается (не запрошено).
    """
    label = f"spec='{spc_name}'"
    print(f"\n========== {label} ==========", flush=True)

    exists_file = os.path.exists(_ae_model_path(spc=spc_name))
    exists_db = (save_to_db
                 and Virtual_NN.db_model_exists(
                     'ae', f"{SPEC_PREFIX}{spc_name}"))

    if (exists_file or exists_db) and not force_ae:
        where = []
        if exists_file:
            where.append('файл')
        if exists_db:
            where.append('БД')
        print(f"[train ae] уже существует ({'+'.join(where)}), "
              f"пропуск (--force / --force-ae)", flush=True)
        return

    arr = generate_ae_training_data(
        max_total=50000, rtype=None, spec_name=spc_name)
    if arr is None or arr.shape[0] < 100:
        n = 0 if arr is None else arr.shape[0]
        print(f"[train ae] мало данных ({n} < 100), пропуск",
              flush=True)
        return

    result = train_autoenc(arr, rtype=None)
    if result is None:
        print("[train ae] не удалось обучить", flush=True)
        return

    npz_bytes, meta = result
    meta['spec'] = spc_name
    meta['level'] = 'spc'
    _save_model('ae', None, npz_bytes, meta,
                save_to_file, save_to_db, spc=spc_name)


# ============================================================================
# CLI
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Обучение моделей Virtual_Measure")
    parser.add_argument("--force", action="store_true",
                        help="перезаписать все существующие модели")
    parser.add_argument("--force-mlp", action="store_true",
                        help="перезаписать только MLP")
    parser.add_argument("--force-ae", action="store_true",
                        help="перезаписать только AE")
    parser.add_argument("--mlp-only", action="store_true",
                        help="запустить только Stage 1")
    parser.add_argument("--ae-only", action="store_true",
                        help="запустить только Stage 2")
    parser.add_argument("--skip-mlp", action="store_true",
                        help="пропустить MLP")
    parser.add_argument("--skip-ae", action="store_true",
                        help="пропустить AE")
    parser.add_argument("--rtype", default=None,
                        help="обучать для конкретного типа резонатора")
    parser.add_argument("--spc", default=None,
                        help="обучать AE для конкретной спецификации "
                             "(MLP на spec-уровне не поддерживается)")
    parser.add_argument("--all-rtypes", action="store_true",
                        help="обучать для всех типов из specification")
    parser.add_argument("--all-specs", action="store_true",
                        help="обучать AE для всех спецификаций "
                             "(может занять часы)")
    parser.add_argument("--no-db", action="store_true",
                        help="не сохранять в БД")
    parser.add_argument("--no-file", action="store_true",
                        help="не сохранять в файлы")
    args = parser.parse_args()

    save_to_file = not args.no_file
    save_to_db   = not args.no_db
    if not save_to_file and not save_to_db:
        print("[train] некуда сохранять (--no-file и --no-db)",
              flush=True)
        return

    force_mlp = args.force or args.force_mlp
    force_ae  = args.force or args.force_ae

    # --- spec-режимы (AE-only) ---
    if args.all_specs:
        if args.mlp_only:
            print("[train] --all-specs: MLP на spec-уровне "
                  "не поддерживается, игнорирую --mlp-only",
                  flush=True)
        specs = list_all_specs()
        if not specs:
            print("[train] --all-specs: спецификаций не найдено",
                  flush=True)
            return
        print(f"[train] --all-specs: {len(specs)} спецификаций. "
              f"На каждую ~30–120 сек. Можно прервать Ctrl+C.",
              flush=True)
        for i, spc in enumerate(specs, 1):
            print(f"\n--- {i}/{len(specs)} ---", flush=True)
            try:
                train_for_spec(spc, force_ae,
                               save_to_file, save_to_db)
            except KeyboardInterrupt:
                print("[train] прервано пользователем", flush=True)
                Virtual_NN.reload_models()
                return
            except Exception as e:
                print(f"[train] spec '{spc}' error: {e}",
                      flush=True)
                continue
        Virtual_NN.reload_models()
        return

    if args.spc:
        train_for_spec(args.spc, force_ae,
                       save_to_file, save_to_db)
        Virtual_NN.reload_models()
        return

    # --- rtype / глобальный режим ---
    do_mlp = not args.ae_only and not args.skip_mlp
    do_ae  = not args.mlp_only and not args.skip_ae

    if not do_mlp and not do_ae:
        print("[train] нечего обучать (все этапы отключены)",
              flush=True)
        return

    targets = []
    if save_to_file:
        targets.append('файл')
    if save_to_db:
        targets.append('БД')
    print(f"[train] этапы: MLP={'да' if do_mlp else 'нет'}, "
          f"AE={'да' if do_ae else 'нет'}, "
          f"сохранение: {', '.join(targets)}", flush=True)

    if args.all_rtypes:
        rtypes = list_all_rtypes()
        if not rtypes:
            print("[train] --all-rtypes: типы не найдены",
                  flush=True)
            return
        print(f"[train] --all-rtypes: {len(rtypes)} типов",
              flush=True)
        for rt in rtypes:
            train_for_rtype(rt, do_mlp, do_ae, force_mlp, force_ae,
                            save_to_file, save_to_db)
    elif args.rtype:
        train_for_rtype(args.rtype, do_mlp, do_ae, force_mlp, force_ae,
                        save_to_file, save_to_db)
    else:
        train_for_rtype(None, do_mlp, do_ae, force_mlp, force_ae,
                        save_to_file, save_to_db)

    Virtual_NN.reload_models()


if __name__ == '__main__':
    main()