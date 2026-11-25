# -*- coding: utf-8 -*-
"""
sklearn Ridge + MLP + HGB.
- Модели масштабируются от n_train (не overfit-ят на 100-200 точках).
- Сравнение моделей через K-fold CV на train (стабильно даже при test=30).
- Лучшая модель выбирается по CV MAE, метрики train/test считаются отдельно.
- Метрики пишутся в БД (model_metrics) через make_metrics_row.
"""
import os, sys, time
import numpy as np, pandas as pd
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.linear_model import Ridge
from sklearn.metrics import mean_absolute_error
from sklearn.model_selection import (
    train_test_split, KFold, RandomizedSearchCV,
)
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler, StandardScaler
import joblib

from training_common import (
    TARGET, FILTR_MIN, FILTR_MAX, MIN_PER_SPC, MIN_TRAIN, TEST_SIZE, RANDOM_STATE,
    get_engine, load_raw, clean_data, get_features, interactive_setup,
    print_diag, report_predictions, safe_name, save_index,
    save_model_metrics, make_metrics_row,
)

OUT_DIR   = "models_sklearn"
BACKEND   = "sklearn"
CV_FOLDS  = 5           # K-fold для сравнения моделей на train
CV_ENABLE = True        # можно выключить для скорости


# ---------------------------------------------------------------- сложность

def _size(n_train):
    """Категория размера выборки → настройки моделей."""
    if n_train < 200:  return "xs"
    if n_train < 1000: return "sm"
    if n_train < 5000: return "md"
    return "lg"


# ---------------------------------------------------------------- модели

def make_mlp(n_train, verbose=False, **kw):
    sz = _size(n_train)
    hidden = {"xs": (32, 16), "sm": (64, 32),
              "md": (128, 64, 32), "lg": (128, 64, 32)}[sz]
    alpha  = {"xs": 1e-2, "sm": 1e-3, "md": 1e-3, "lg": 1e-3}[sz]
    early  = sz in ("xs", "sm")     # для малых n — обязательный early stop

    p = dict(
        hidden_layer_sizes=hidden,
        activation="relu", solver="adam",
        alpha=alpha, learning_rate_init=1e-3,
        max_iter=2000,
        early_stopping=early,
        n_iter_no_change=20,
        validation_fraction=0.2,
        random_state=RANDOM_STATE, verbose=verbose,
    )
    p.update(kw)
    return TransformedTargetRegressor(
        regressor=Pipeline([
            ("scaler", RobustScaler()),
            ("mlp", MLPRegressor(**p)),
        ]),
        transformer=StandardScaler(),
    )


def make_hgb(n_train, verbose=0, **kw):
    sz = _size(n_train)
    p = dict(
        max_iter          = {"xs": 200, "sm": 500,
                             "md": 1000, "lg": 1000}[sz],
        max_leaf_nodes    = {"xs": 15,  "sm": 31,
                             "md": 63,   "lg": 63}[sz],
        learning_rate     = 0.05,
        l2_regularization = {"xs": 1e-1, "sm": 1e-2,
                             "md": 1e-3, "lg": 1e-3}[sz],
        early_stopping=False,
        verbose=verbose,
        random_state=RANDOM_STATE,
    )
    p.update(kw)
    return TransformedTargetRegressor(
        regressor=HistGradientBoostingRegressor(**p),
        transformer=StandardScaler(),
    )


def make_ridge(n_train, **kw):
    return TransformedTargetRegressor(
        regressor=Pipeline([
            ("scaler", RobustScaler()),
            ("ridge", Ridge(alpha=1.0)),
        ]),
        transformer=StandardScaler(),
    )


# ---------------------------------------------------------------- search

MLP_SPACE = {
    "regressor__mlp__hidden_layer_sizes": [(64, 32), (128, 64), (128, 64, 32)],
    "regressor__mlp__alpha": [1e-4, 1e-3, 1e-2],
    "regressor__mlp__learning_rate_init": [1e-3, 5e-4],
}
HGB_SPACE = {
    "regressor__max_iter": [200, 500],
    "regressor__learning_rate": [0.03, 0.05, 0.1],
    "regressor__max_leaf_nodes": [15, 31, 63],
    "regressor__l2_regularization": [1e-3, 1e-2, 1e-1],
}


def auto_search(base, space, X, y, tag, n_iter=10):
    print(f"\n  [auto {tag}] RandomizedSearchCV: n_iter={n_iter}, cv=3")
    cv = KFold(n_splits=3, shuffle=True, random_state=RANDOM_STATE)
    search = RandomizedSearchCV(
        base, space, n_iter=n_iter, cv=cv,
        scoring="neg_mean_absolute_error",
        random_state=RANDOM_STATE, n_jobs=1, verbose=2,
    )
    search.fit(X, y)
    print(f"  [auto {tag}] CV MAE = {-search.best_score_:.4g}")
    print(f"  [auto {tag}] best params = {search.best_params_}")
    return search.best_estimator_


# ---------------------------------------------------------------- CV

def cv_compare(factories, X, y, n_splits=CV_FOLDS):
    """
    factories: dict name -> callable() -> estimator
    Возвращает dict name -> (mean_mae, std_mae, list_per_fold)
    """
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE)
    out = {}
    for name, fac in factories.items():
        maes = []
        for tr, va in kf.split(X):
            m = fac(); m.fit(X[tr], y[tr])
            maes.append(float(mean_absolute_error(y[va], m.predict(X[va]))))
        out[name] = (float(np.mean(maes)), float(np.std(maes)), maes)
    return out


# ---------------------------------------------------------------- обучение

def train_group(sub, feats, out_dir, tag, auto_search_on, fmax):
    print(f"\n=== {tag} (n={len(sub)}, features={feats}) ===")
    if len(sub) < MIN_TRAIN:
        print(f"[skip] мало данных: {len(sub)} < {MIN_TRAIN}")
        return None

    idx_tr, idx_te = train_test_split(sub.index, test_size=TEST_SIZE,
                                      random_state=RANDOM_STATE)
    Xtr = sub.loc[idx_tr, feats].to_numpy(float)
    Xte = sub.loc[idx_te, feats].to_numpy(float)
    ytr = sub.loc[idx_tr, TARGET].to_numpy(float)
    yte = sub.loc[idx_te, TARGET].to_numpy(float)

    # --- бейзлайны ---
    print("Baselines:")
    report_predictions("mean",   yte, np.full_like(yte, ytr.mean()))
    report_predictions("median", yte, np.full_like(yte, np.median(ytr)))
    report_predictions("zero",   yte, np.zeros_like(yte))

    # --- CV-сравнение на train ---
    if CV_ENABLE:
        print(f"\n=== CV({CV_FOLDS}) на train (n={len(Xtr)}) ===")
        factories = {
            "ridge": lambda: make_ridge(len(Xtr)),
            "mlp":   lambda: make_mlp(len(Xtr)),
            "hgb":   lambda: make_hgb(len(Xtr)),
        }
        cv = cv_compare(factories, Xtr, ytr)
        for nm, (m, s, _) in cv.items():
            print(f"  {nm:<8} CV MAE = {m:9.4g} ± {s:6.3g}")
        chosen = min(cv, key=lambda k: cv[k][0])
        print(f"  [cv best] {chosen.upper()}  CV MAE={cv[chosen][0]:.4g}")
    else:
        cv = None
        # без CV — по одному holdout на train (быстро, но шумно)
        inner_tr, inner_va = train_test_split(
            np.arange(len(Xtr)), test_size=0.2, random_state=RANDOM_STATE)
        maes = {}
        for nm, fac in (("ridge", lambda: make_ridge(len(Xtr))),
                        ("mlp",   lambda: make_mlp(len(Xtr))),
                        ("hgb",   lambda: make_hgb(len(Xtr)))):
            m = fac(); m.fit(Xtr[inner_tr], ytr[inner_tr])
            maes[nm] = float(mean_absolute_error(
                ytr[inner_va], m.predict(Xtr[inner_va])))
        chosen = min(maes, key=maes.get)

    # --- финальный fit лучшей модели ---
    if chosen == "ridge":
        model = make_ridge(len(Xtr))
        if auto_search_on:
            print("  [auto] Ridge — гиперпараметров нет, пропускаю search")
        print(f"\n  Финальный fit RIDGE на train (n={len(Xtr)})...")
        t0 = time.time(); model.fit(Xtr, ytr); print(f"  готово за {time.time()-t0:.1f}s")

    elif chosen == "mlp":
        model = make_mlp(len(Xtr), verbose=not auto_search_on)
        if auto_search_on and len(Xtr) >= 200:
            model = auto_search(model, MLP_SPACE, Xtr, ytr, "MLP")
        print(f"\n  Финальный fit MLP на train (n={len(Xtr)})...")
        t0 = time.time(); model.fit(Xtr, ytr); print(f"  готово за {time.time()-t0:.1f}s")

    else:  # hgb
        model = make_hgb(len(Xtr), verbose=1 if not auto_search_on else 0)
        if auto_search_on and len(Xtr) >= 200:
            model = auto_search(model, HGB_SPACE, Xtr, ytr, "HGB")
        print(f"\n  Финальный fit HGB на train (n={len(Xtr)})...")
        t0 = time.time(); model.fit(Xtr, ytr); print(f"  готово за {time.time()-t0:.1f}s")

    # --- метрики train/test ---
    print(f"\n=== Метрики (delta = y - pred), chosen={chosen.upper()} ===")
    m_train = report_predictions(f"{chosen}-train", ytr, model.predict(Xtr))
    m_test  = report_predictions(f"{chosen}-test",  yte, model.predict(Xte))

    metrics = {
        chosen: {"train": m_train, "test": m_test},
    }
    if cv is not None:
        metrics["_cv"] = {
            nm: {"mae_mean": v[0], "mae_std": v[1]} for nm, v in cv.items()
        }

    # --- сохранение на диск ---
    d = os.path.join(out_dir, tag)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "model.joblib")
    joblib.dump({
        "model":        model,
        "name":         chosen,
        "features":     list(feats),
        "target":       TARGET,
        "metrics":      metrics,
        "filtr_bounds": (FILTR_MIN, FILTR_MAX),
    }, path)
    print(f"Сохранено: {path}")

    return {
        "dir":      tag,
        "n_train":  int(len(Xtr)),
        "n_test":   int(len(Xte)),
        "features": list(feats),
        "metrics":  metrics,
        "best":     chosen,
        "fmax":     float(fmax),
    }


# ---------------------------------------------------------------- main

def main():
    print("=== sklearn | Ridge / MLP / HGB | CV-based model selection ===")
    engine = get_engine()
    df_raw = load_raw(engine)
    print(f"Загружено: {len(df_raw)}")
    print_diag(df_raw)

    setup = interactive_setup()
    if setup["diagnose_only"]:
        return

    df = clean_data(df_raw, fmax=setup["fmax"])
    if len(df) < 2 * MIN_TRAIN:
        sys.exit(f"[ERROR] мало данных: {len(df)} < {2*MIN_TRAIN}")

    scope, feats = setup["scope"], get_features(setup["scope"])
    print(f"\n=== Режим: {scope}  fmax={setup['fmax']:g}  "
          f"features={feats}  auto_search={setup['auto_search']}  "
          f"cv={'on' if CV_ENABLE else 'off'} ===")

    os.makedirs(OUT_DIR, exist_ok=True)
    index = {
        "scope": scope, "spc_filter": "РК731", "fmax": setup["fmax"],
        "target": TARGET, "features": feats, "backend": BACKEND,
        "auto_stop": False, "cv_folds": CV_FOLDS, "models": {},
    }
    all_rows = []

    if scope.startswith("global"):
        spec = train_group(df, feats, OUT_DIR, "global",
                           setup["auto_search"], setup["fmax"])
        if spec:
            index["models"]["*"] = spec
            all_rows.append(make_metrics_row(
                spec, "*", scope, df, setup["fmax"], BACKEND))
    else:
        counts = df.groupby("Spc").size().sort_values(ascending=False)
        total, skipped = len(counts), []
        for i, (spc, n) in enumerate(counts.items(), 1):
            print(f"\n[{i}/{total}] Spc={spc!r}  n={n}")
            if n < MIN_PER_SPC:
                skipped.append((spc, n)); continue
            sub = df[df["Spc"] == spc]
            spec = train_group(sub, feats, OUT_DIR,
                               "spc_" + safe_name(spc),
                               setup["auto_search"], setup["fmax"])
            if spec is None:
                skipped.append((spc, n)); continue
            index["models"][spc] = spec
            all_rows.append(make_metrics_row(
                spec, spc, scope, sub, setup["fmax"], BACKEND))

        if skipped:
            print(f"\nПропущено Spc: {len(skipped)}")
            for spc, n in skipped:
                print(f"  {spc!r:40s} n={n}")

    save_index(os.path.join(OUT_DIR, "index.json"), index)

    print(f"\n=== Сохранение метрик в БД ({len(all_rows)} строк) ===")
    save_model_metrics(engine, all_rows)


if __name__ == "__main__":
    main()