# -*- coding: utf-8 -*-
"""
sklearn MLP + HGB, единый интерактив, авто-подбор через RandomizedSearchCV.
Auto-stop: OFF. Прогресс: MLP (verbose), HGB (verbose=1), search (verbose=2).
"""
import os, sys, time
import numpy as np, pandas as pd
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.model_selection import train_test_split, KFold, RandomizedSearchCV
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler, StandardScaler
import joblib
from training_common import (
    TARGET, FILTR_MIN, FILTR_MAX, MIN_PER_SPC, MIN_TRAIN, TEST_SIZE, RANDOM_STATE,
    get_engine, load_raw, clean_data, get_features, interactive_setup,
    print_diag, report_predictions, safe_name, save_index,
)

OUT_DIR = "models_sklearn"


def make_mlp(verbose=False, **kw):
    p = dict(
        hidden_layer_sizes=(128, 64, 32),
        activation="relu", solver="adam",
        alpha=1e-3, learning_rate_init=1e-3,
        max_iter=2000,
        early_stopping=False,          # OFF
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


def make_hgb(verbose=0, **kw):
    p = dict(
        max_iter=1000, learning_rate=0.05, max_leaf_nodes=63,
        l2_regularization=1e-3,
        early_stopping=False,          # OFF
        verbose=verbose,
        random_state=RANDOM_STATE,
    )
    p.update(kw)
    return TransformedTargetRegressor(
        regressor=HistGradientBoostingRegressor(**p),
        transformer=StandardScaler(),
    )


MLP_SPACE = {
    "regressor__mlp__hidden_layer_sizes": [(64, 32), (128, 64), (128, 64, 32), (256, 128, 64)],
    "regressor__mlp__alpha": [1e-4, 1e-3, 1e-2],
    "regressor__mlp__learning_rate_init": [1e-3, 5e-4],
}
HGB_SPACE = {
    "regressor__max_iter": [300, 500, 1000],
    "regressor__learning_rate": [0.03, 0.05, 0.1],
    "regressor__max_leaf_nodes": [31, 63, 127],
    "regressor__l2_regularization": [0, 1e-3, 1e-2],
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


def train_group(sub, feats, out_dir, tag, auto_search_on):
    print(f"\n=== {tag} (n={len(sub)}, features={feats}) ===")
    if len(sub) < MIN_TRAIN:
        print(f"[skip] мало данных: {len(sub)} < {MIN_TRAIN}")
        return None

    idx_tr, idx_te = train_test_split(sub.index, test_size=TEST_SIZE, random_state=RANDOM_STATE)
    Xtr = sub.loc[idx_tr, feats].to_numpy(float)
    Xte = sub.loc[idx_te, feats].to_numpy(float)
    ytr = sub.loc[idx_tr, TARGET].to_numpy(float)
    yte = sub.loc[idx_te, TARGET].to_numpy(float)

    print("Baselines:")
    report_predictions("mean", yte, np.full_like(yte, ytr.mean()))

    # подвыборка для авто-поиска (ускорение)
    if auto_search_on and len(Xtr) > 20000:
        rs = np.random.RandomState(RANDOM_STATE)
        sel = rs.choice(len(Xtr), 20000, replace=False)
        Xsr, ysr = Xtr[sel], ytr[sel]
        print(f"  [auto] подвыборка для поиска: {len(Xsr)}")
    else:
        Xsr, ysr = Xtr, ytr

    if auto_search_on:
        mlp = auto_search(make_mlp(), MLP_SPACE, Xsr, ysr, "MLP")
        print(f"\n  Финальный fit MLP на полном train...")
        t0 = time.time(); mlp.fit(Xtr, ytr); print(f"  MLP готово за {time.time()-t0:.1f}s")

        hgb = auto_search(make_hgb(), HGB_SPACE, Xsr, ysr, "HGB")
        print(f"\n  Финальный fit HGB на полном train...")
        t0 = time.time(); hgb.fit(Xtr, ytr); print(f"  HGB готово за {time.time()-t0:.1f}s")
    else:
        print("\n  [MLP] fit (auto-stop OFF, verbose=True)...")
        t0 = time.time()
        mlp = make_mlp(verbose=True); mlp.fit(Xtr, ytr)
        print(f"  [MLP] готово за {time.time()-t0:.1f}s")

        print("\n  [HGB] fit (auto-stop OFF, verbose=1)...")
        t0 = time.time()
        hgb = make_hgb(verbose=1); hgb.fit(Xtr, ytr)
        print(f"  [HGB] готово за {time.time()-t0:.1f}s")

    print("\n=== Метрики (delta = y - pred) ===")
    res = {
        "mlp": {"train": report_predictions("MLP-train", ytr, mlp.predict(Xtr)),
                "test":  report_predictions("MLP-test",  yte, mlp.predict(Xte))},
        "hgb": {"train": report_predictions("HGB-train", ytr, hgb.predict(Xtr)),
                "test":  report_predictions("HGB-test",  yte, hgb.predict(Xte))},
    }
    best = "hgb" if res["hgb"]["test"]["mae"] < res["mlp"]["test"]["mae"] else "mlp"
    best_model = hgb if best == "hgb" else mlp
    print(f"Лучший: {best.upper()}")

    d = os.path.join(out_dir, tag)
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "model.joblib")
    joblib.dump({
        "model":        best_model,
        "name":         best,
        "features":     list(feats),
        "target":       TARGET,
        "metrics":      res,
        "filtr_bounds": (FILTR_MIN, FILTR_MAX),
    }, path)
    print(f"Сохранено: {path}")

    return {"dir": tag, "n_train": int(len(Xtr)), "n_test": int(len(Xte)),
            "features": list(feats), "metrics": res, "best": best}


def main():
    print("=== sklearn | auto-stop: OFF ===")
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
          f"features={feats}  auto_search={setup['auto_search']} ===")

    os.makedirs(OUT_DIR, exist_ok=True)
    index = {
        "scope": scope, "spc_filter": "РК731", "fmax": setup["fmax"],
        "target": TARGET, "features": feats, "backend": "sklearn",
        "auto_stop": False, "models": {},
    }

    if scope.startswith("global"):
        spec = train_group(df, feats, OUT_DIR, "global", setup["auto_search"])
        if spec: index["models"]["*"] = spec
    else:
        counts = df.groupby("Spc").size().sort_values(ascending=False)
        total, skipped = len(counts), []
        for i, (spc, n) in enumerate(counts.items(), 1):
            print(f"\n[{i}/{total}] Spc={spc!r}  n={n}")
            if n < MIN_PER_SPC:
                skipped.append((spc, n)); continue
            sub = df[df["Spc"] == spc]
            spec = train_group(sub, feats, OUT_DIR, "spc_" + safe_name(spc), setup["auto_search"])
            if spec is None:
                skipped.append((spc, n)); continue
            index["models"][spc] = spec

        if skipped:
            print(f"\nПропущено Spc: {len(skipped)}")
            for spc, n in skipped:
                print(f"  {spc!r:40s} n={n}")

    save_index(os.path.join(OUT_DIR, "index.json"), index)


if __name__ == "__main__":
    main()