"""
Автономное обучение нейросетей подбора спецификаций (kind='spcnn').

Запуск (требуется PyTorch, уже обученный train_models.py не трогается):
    pip install torch

    # Глобальная модель (все типы резонаторов):
    python -m Virtual_Measure.train_spc_models --force

    # Отдельная модель под тип резонатора:
    python -m Virtual_Measure.train_spc_models --rtype "РК526"

    # Все типы из specification + глобальная:
    python -m Virtual_Measure.train_spc_models --all-rtypes --force

    # Тонкая настройка:
    python -m Virtual_Measure.train_spc_models --all-rtypes \
        --members 5 --epochs 200 --hidden 64 --hidden2 32 --negatives 5

    # Сохранять только в БД (без файлов) / только в файлы:
    python -m Virtual_Measure.train_spc_models --no-file
    python -m Virtual_Measure.train_spc_models --no-db

Данные: psidata (история реальных измерений) + specification +
temperatureprofile + msk_rk + nomeklatura_rk_psi.

Схема разметки (learning-to-rank):
  * положительный пример — пара (контекст измерения, спецификация),
    которая реально была использована (psidata.Spc);
  * отрицательные — конкурирующие спецификации ТОГО ЖЕ типа резонатора
    (NameR), не использованные в этом контексте.
Признаки пары строит Spc_Search_NN.build_feature_vector (единый код
с рантаймом — паритет train/inference гарантирован).

Обученный ансамбль сохраняется:
  * в БД — таблица virtual_nn_models, Kind='spcnn',
    Rtype='<тип>' / '' (глобальная);
  * опционально в файл models/spcnn[_<rtype>].npz (для отладки).
"""

import argparse
import io
import random
from collections import defaultdict

import numpy as np
import pandas as pd
from sqlalchemy import text

from . import Virtual_NN
from . import Spc_Search_NN
from .Spc_Search_NN import (KIND_SPCNN, FEATURE_VERSION, FEATURES,
                            build_feature_vector, save_spcnn)
from .Virtual_Data import _engine, _safe_float, _safe_str


# ============================================================================
# Загрузка данных
# ============================================================================
def list_resonator_types() -> list:
    """Типы резонаторов, по которым есть история измерений в psidata."""
    eng = _engine()
    try:
        df = pd.read_sql(text(
            "SELECT DISTINCT s.`NameR` AS rtype "
            "FROM specification s "
            "INNER JOIN psidata p ON p.`Spc` = s.`Name` "
            "WHERE s.`NameR` IS NOT NULL AND s.`NameR` <> '' "
            "ORDER BY s.`NameR`"), eng)
        return df['rtype'].dropna().astype(str).tolist()
    except Exception as e:
        print(f"[train spcnn] list_resonator_types: {e}", flush=True)
        return []


def load_spec_frame() -> pd.DataFrame:
    """Все спецификации + температурные профили, единым фреймом."""
    eng = _engine()
    sql = text(
        "SELECT s.`Name`, s.`ID`, s.`Nominal`, s.`Profile`, "
        "       s.`LoadType`, s.`Loadvalue`, s.`Multy`, s.`NameR`, "
        "       tp.`Temperatures` AS ProfileTemps "
        "FROM specification s "
        "LEFT JOIN temperatureprofile tp ON tp.`Name` = s.`Profile`"
    )
    df = pd.read_sql(sql, eng)
    df['Nominal'] = pd.to_numeric(df['Nominal'], errors='coerce')
    return df


def _spec_frames(spec_df: pd.DataFrame):
    """Индексы по имени и по типу резонатора."""
    by_name = {}
    by_type = defaultdict(list)
    for _, r in spec_df.iterrows():
        name = _safe_str(r.get('Name'))
        if not name:
            continue
        by_name[name] = r
        rtype = _safe_str(r.get('NameR'))
        if rtype:
            by_type[rtype].append(name)
    return by_name, by_type


def spec_to_dict(r) -> dict:
    return {
        'name': _safe_str(r.get('Name')),
        'id': _safe_str(r.get('ID')),
        'nominal': _safe_float(r.get('Nominal')),
        'load_type': _safe_str(r.get('LoadType')),
        'load_value': _safe_float(r.get('Loadvalue')),
        'multy': 1 if str(r.get('Multy', 0)).strip() in ('1', 'True',
                                                         'true') else 0,
        'rtype': _safe_str(r.get('NameR')),
        'profile_temps': None if r.get('ProfileTemps') is None
        else str(r.get('ProfileTemps')),
    }


def load_contexts(rtype=None, max_rows=300000, max_per_spc=400):
    """
    Уникальные контексты измерений из psidata.

    Контекст: ref_hz, cl_metod, cl_value, temps (по профилю использованной
    спецификации), linked (спецификации, связанные с номенклатурой МСК),
    spc — использованная спецификация (положительный пример).
    """
    eng = _engine()

    where = ("INNER JOIN specification s ON s.`Name` = p.`Spc` "
             "WHERE s.`NameR` = :t " if rtype else "")
    params = {'t': rtype} if rtype else None
    sql = text(
        "SELECT p.`MSK`, p.`Spc`, p.`REF_F`, p.`Measure_Metod`, p.`Cn` "
        f"FROM psidata p {where} "
        "LIMIT :lim"
    )
    if params is None:
        params = {}
    params['lim'] = int(max_rows)
    df = pd.read_sql(sql, eng, params=params)
    if df.empty:
        print("[train spcnn] psidata: данных нет", flush=True)
        return []

    # --- температуры профилей спецификаций ---
    spec_df = load_spec_frame()
    temps_by_spec = {}
    for _, r in spec_df.iterrows():
        name = _safe_str(r.get('Name'))
        temps = _safe_str(r.get('ProfileTemps'))
        if name and temps:
            try:
                from Temperature_Measure.spc_matching import parse_temp_list
                temps_by_spec[name] = parse_temp_list(temps)
            except Exception:
                temps_by_spec[name] = []

    # --- номенклатура МСК → код ---
    code_by_msk = {}
    try:
        msk_df = pd.read_sql(text(
            "SELECT `мскРеал`, `КодНоменклатуры` FROM msk_rk"), eng)
        for _, r in msk_df.iterrows():
            msk = _safe_str(r.get('мскРеал'))
            code = _safe_str(r.get('КодНоменклатуры'))
            if msk and code:
                code_by_msk[msk] = code
    except Exception as e:
        print(f"[train spcnn] msk_rk: {e}", flush=True)

    # --- связи номенклатура → спецификации ---
    links_by_code = defaultdict(set)
    try:
        link_df = pd.read_sql(text(
            "SELECT `NomenklaturaID`, `SpcName` FROM nomeklatura_rk_psi"),
            eng)
        for _, r in link_df.iterrows():
            code = _safe_str(r.get('NomenklaturaID'))
            name = _safe_str(r.get('SpcName'))
            if code and name:
                links_by_code[code].add(name)
    except Exception as e:
        print(f"[train spcnn] nomeklatura_rk_psi: {e}", flush=True)

    # --- дедупликация контекстов ---
    per_spc = defaultdict(int)
    seen = set()
    contexts = []
    for _, r in df.iterrows():
        spc = _safe_str(r.get('Spc'))
        if not spc or per_spc[spc] >= max_per_spc:
            continue
        ref_hz = _safe_float(r.get('REF_F'))
        if ref_hz <= 0:
            continue
        key = (spc, round(ref_hz, 6), _safe_str(r.get('Measure_Metod')),
               _safe_float(r.get('Cn')))
        if key in seen:
            continue
        seen.add(key)
        per_spc[spc] += 1
        nom_code = code_by_msk.get(_safe_str(r.get('MSK')), '')
        contexts.append({
            'spc': spc,
            'ref_hz': ref_hz,
            'cl_metod': _safe_str(r.get('Measure_Metod')) or 'SERIES',
            'cl_value': _safe_float(r.get('Cn')),
            'temps': temps_by_spec.get(spc, []),
            'linked': links_by_code.get(nom_code, set()),
        })
        if len(contexts) >= max_rows:
            break
    print(f"[train spcnn] контекстов собрано: {len(contexts)}",
          flush=True)
    return contexts


# ============================================================================
# Датасет
# ============================================================================
def build_training_set(contexts, spec_df, negatives_per_pos=5, seed=7):
    """
    X (n, N_FEATURES), y (n,) — 1 использованная спецификация,
    0 — конкурирующие спецификации того же типа резонатора.
    """
    from .Spc_Search_NN import N_FEATURES

    by_name, by_type = _spec_frames(spec_df)
    rng = random.Random(seed)
    X, y = [], []
    n_pos = n_neg = 0
    for ctx in contexts:
        pos = ctx['spc']
        pos_row = by_name.get(pos)
        if pos_row is None:
            continue
        pos_dic = spec_to_dict(pos_row)
        X.append(build_feature_vector(ctx, pos_dic))
        y.append(1.0)
        n_pos += 1

        rtype = pos_dic['rtype']
        others = [n for n in by_type.get(rtype, []) if n != pos]
        if not others:
            continue
        if len(others) > negatives_per_pos:
            others = rng.sample(others, negatives_per_pos)
        for n in others:
            X.append(build_feature_vector(ctx, spec_to_dict(by_name[n])))
            y.append(0.0)
            n_neg += 1

    if not X:
        return None, None, (0, 0)
    arr_x = np.vstack(X).astype(np.float64)
    arr_y = np.asarray(y, dtype=np.float64)
    print(f"[train spcnn] примеров: {len(arr_y)} "
          f"(+{n_pos} / -{n_neg})", flush=True)
    return arr_x, arr_y, (n_pos, n_neg)


# ============================================================================
# Обучение ансамбля
# ============================================================================
def train_ensemble(X, y, hidden=48, hidden2=24, n_members=5,
                   epochs=150, lr=1e-3, batch=512, val_frac=0.1,
                   seed=13, rtype=None):
    """Возвращает (npz_bytes, meta) или None."""
    try:
        import torch
        import torch.nn as nn
        import torch.optim as optim
    except ImportError:
        print("[train spcnn] torch не установлен: pip install torch",
              flush=True)
        return None

    from .Spc_Search_NN import N_FEATURES

    if len(y) < 100:
        print(f"[train spcnn] слишком мало примеров ({len(y)})", flush=True)
        return None

    x_mean = X.mean(axis=0)
    x_std = X.std(axis=0)
    x_std[x_std < 1e-9] = 1.0
    Xs = (X - x_mean) / x_std

    # Стратифицированная валидация 10%
    rng = np.random.RandomState(seed)
    val_idx = []
    for cls in (0.0, 1.0):
        cls_idx = np.where(y == cls)[0]
        if len(cls_idx) > 10:
            take = max(5, int(len(cls_idx) * val_frac))
            val_idx.extend(rng.choice(cls_idx, take, replace=False))
    val_mask = np.zeros(len(y), dtype=bool)
    if val_idx:
        val_mask[np.array(val_idx)] = True
    train_mask = ~val_mask if val_idx else np.ones(len(y), dtype=bool)

    Xt = torch.from_numpy(Xs[train_mask].astype(np.float32))
    yt = torch.from_numpy(y[train_mask].astype(np.float32))
    Xv = torch.from_numpy(Xs[val_mask].astype(np.float32)) if val_idx else None
    yv = y[val_mask] if val_idx else None

    pos_weight_val = float((y[train_mask] == 0).sum() /
                           max(1.0, (y[train_mask] == 1).sum()))
    print(f"[train spcnn] pos_weight={pos_weight_val:.2f}", flush=True)

    class SpcNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(N_FEATURES, hidden), nn.ReLU(),
                nn.Linear(hidden, hidden2), nn.ReLU(),
                nn.Linear(hidden2, 1),
            )

        def forward(self, x):
            return self.net(x).squeeze(-1)

    models = []
    val_scores = []
    for e in range(n_members):
        torch.manual_seed(seed + 1000 * (e + 1))
        model = SpcNet()
        opt = optim.Adam(model.parameters(), lr=lr)
        loss_fn = nn.BCEWithLogitsLoss(
            pos_weight=torch.tensor([pos_weight_val]))

        n = Xt.shape[0]
        bs = min(batch, n)
        total = 0.0
        for epoch in range(epochs):
            idx = torch.randperm(n)
            for i in range(0, n, bs):
                b = idx[i:i + bs]
                opt.zero_grad()
                out = model(Xt[b])
                loss = loss_fn(out, yt[b])
                loss.backward()
                opt.step()
                total += float(loss.item()) * len(b)
            if (epoch + 1) % 25 == 0:
                print(f"[train spcnn] member {e + 1}/{n_members} "
                      f"epoch {epoch + 1}/{epochs}, "
                      f"loss={total / n:.5f}", flush=True)
        models.append(model)

        if Xv is not None and len(yv) > 0:
            with torch.no_grad():
                pv = (torch.sigmoid(model(Xv)).numpy() > 0.5)
            acc = float((pv == yv.astype(bool)).mean())
        else:
            acc = float('nan')
        val_scores.append(acc)
        print(f"[train spcnn] member {e + 1}: val accuracy={acc}",
              flush=True)

    sd_all = [m.state_dict() for m in models]
    buf = io.BytesIO()
    np.savez(buf,
             W1=np.stack([sd['net.0.weight'].numpy().T
                          for sd in sd_all]).astype(np.float64),
             b1=np.stack([sd['net.0.bias'].numpy()
                          for sd in sd_all]).astype(np.float64),
             W2=np.stack([sd['net.2.weight'].numpy().T
                          for sd in sd_all]).astype(np.float64),
             b2=np.stack([sd['net.2.bias'].numpy()
                          for sd in sd_all]).astype(np.float64),
             W3=np.stack([sd['net.4.weight'].numpy().T
                          for sd in sd_all]).astype(np.float64),
             b3=np.stack([sd['net.4.bias'].numpy()
                          for sd in sd_all]).astype(np.float64),
             x_mean=x_mean, x_std=x_std)

    valid_acc = [a for a in val_scores if a == a]
    meta = {
        'kind': KIND_SPCNN,
        'rtype': rtype or '',
        'feature_version': FEATURE_VERSION,
        'features': FEATURES,
        'n_members': n_members,
        'hidden': hidden,
        'hidden2': hidden2,
        'epochs': epochs,
        'lr': lr,
        'n_samples': int(len(y)),
        'val_accuracy': (round(float(np.mean(valid_acc)), 4)
                         if valid_acc else None),
    }
    return buf.getvalue(), meta


# ============================================================================
# Обучение для типа резонатора / глобально
# ============================================================================
def train_for_rtype(rtype=None, force=False, save_to_file=True,
                    save_to_db=True, negatives=5, max_rows=300000,
                    epochs=150, hidden=48, hidden2=24, n_members=5):
    label = f"rtype='{rtype}'" if rtype else "глобальная"
    print(f"\n========== spcnn {label} ==========", flush=True)

    if not force and Virtual_NN.db_model_exists(KIND_SPCNN, rtype or ''):
        print("[train spcnn] модель уже существует в БД, "
              "пропуск (--force)", flush=True)
        return

    spec_df = load_spec_frame()
    contexts = load_contexts(rtype=rtype, max_rows=max_rows,
                             max_per_spc=400)
    X, y, _ = build_training_set(contexts, spec_df,
                                 negatives_per_pos=negatives)

    # Для уровня rtype датасет часто мал — добавляем глобальные данные
    if rtype and (X is None or len(y) < 300):
        print("[train spcnn] мало данных по типу — добавляю "
              "глобальную выборку", flush=True)
        g_contexts = load_contexts(rtype=None, max_rows=max_rows,
                                   max_per_spc=200)
        Xg, yg, _ = build_training_set(g_contexts, spec_df,
                                       negatives_per_pos=negatives)
        if Xg is not None:
            X = Xg if X is None else np.vstack([X, Xg])
            y = yg if y is None else np.concatenate([y, yg])

    if X is None or len(y) < 100:
        print("[train spcnn] недостаточно данных, пропуск", flush=True)
        return

    result = train_ensemble(X, y, hidden=hidden, hidden2=hidden2,
                            n_members=n_members, epochs=epochs,
                            rtype=rtype)
    if result is None:
        print("[train spcnn] не удалось обучить", flush=True)
        return
    npz_bytes, meta = result
    save_spcnn(npz_bytes, rtype=rtype, meta=meta,
               save_to_file=save_to_file, save_to_db=save_to_db)


# ============================================================================
# CLI
# ============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Обучение нейросетей подбора спецификаций "
                    "(kind='spcnn', таблица virtual_nn_models)")
    parser.add_argument("--force", action="store_true",
                        help="переобучить существующие модели")
    parser.add_argument("--rtype", default=None,
                        help="тип резонатора (NameR)")
    parser.add_argument("--all-rtypes", action="store_true",
                        help="обучить для всех типов + глобальную")
    parser.add_argument("--negatives", type=int, default=5,
                        help="отрицательных примеров на один "
                             "положительный (по умолчанию 5)")
    parser.add_argument("--max-rows", type=int, default=300000,
                        help="ограничение выборки psidata")
    parser.add_argument("--epochs", type=int, default=150)
    parser.add_argument("--hidden", type=int, default=48)
    parser.add_argument("--hidden2", type=int, default=24)
    parser.add_argument("--members", type=int, default=5,
                        help="размер ансамбля")
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--no-db", action="store_true",
                        help="не сохранять в БД")
    parser.add_argument("--no-file", action="store_true",
                        help="не сохранять в файлы")
    args = parser.parse_args()

    save_to_file = not args.no_file
    save_to_db = not args.no_db
    if not save_to_file and not save_to_db:
        print("[train spcnn] некуда сохранять (--no-file и --no-db)",
              flush=True)
        return

    def run(rtype):
        train_for_rtype(rtype=rtype, force=args.force,
                        save_to_file=save_to_file, save_to_db=save_to_db,
                        negatives=args.negatives, max_rows=args.max_rows,
                        epochs=args.epochs, hidden=args.hidden,
                        hidden2=args.hidden2, n_members=args.members)

    if args.all_rtypes:
        rtypes = list_resonator_types()
        print(f"[train spcnn] типов с историей: {len(rtypes)}", flush=True)
        for rt in rtypes:
            try:
                run(rt)
            except KeyboardInterrupt:
                print("[train spcnn] прервано пользователем", flush=True)
                Spc_Search_NN.reload_models()
                return
            except Exception as e:
                print(f"[train spcnn] rtype '{rt}' error: {e}", flush=True)
                continue
        run(None)          # глобальная модель всегда
    elif args.rtype:
        run(args.rtype)
    else:
        run(None)          # глобальная модель по умолчанию

    Spc_Search_NN.reload_models()
    print("[train spcnn] модели в virtual_nn_models:",
          flush=True)
    for info in Spc_Search_NN.list_available_models():
        print(f"  rtype='{info['rtype']}' size={info['size']} "
              f"trained_at={info['trained_at']}", flush=True)


if __name__ == '__main__':
    main()
