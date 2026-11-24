# -*- coding: utf-8 -*-
"""
TensorFlow/Keras: единый интерактив, авто-подбор через KFold-grid.
Auto-stop: OFF (фиксированное TF_EPOCHS), прогресс через TFProgress callback.
"""
import os, sys, time, itertools
import numpy as np, pandas as pd
from sklearn.model_selection import train_test_split, KFold
from sklearn.preprocessing import RobustScaler, StandardScaler
from sklearn.metrics import mean_absolute_error
import joblib
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers
from training_common import (
    TARGET, FILTR_MIN, FILTR_MAX, MIN_PER_SPC, MIN_TRAIN, TEST_SIZE, RANDOM_STATE,
    get_engine, load_raw, clean_data, get_features, interactive_setup,
    print_diag, report_predictions, safe_name, save_index,
)

OUT_DIR        = "models_tf"
TF_EPOCHS      = 400           # финальное обучение
TF_EPOCHS_CV   = 150           # для авто-поиска
TF_BATCH       = 256
PROGRESS_EVERY = 20

# --- сетка для авто-поиска ---
TF_CONFIGS = [
    {"hidden": (128, 64, 32), "lr": 1e-3, "batch": 256},
    {"hidden": (256, 128, 64), "lr": 1e-3, "batch": 256},
    {"hidden": (128, 128, 64, 32), "lr": 5e-4, "batch": 256},
    {"hidden": (256, 128, 64), "lr": 5e-4, "batch": 128},
]
DEFAULT_CFG = {"hidden": (128, 64, 32), "lr": 1e-3, "batch": TF_BATCH}


# ---------------- модель ----------------

class TFProgress(keras.callbacks.Callback):
    """Печать прогресса без остановки."""
    def __init__(self, every=PROGRESS_EVERY):
        super().__init__()
        self.every = every
        self.t0 = None

    def on_train_begin(self, logs=None):
        self.t0 = time.time()
        print(f"  [TF] старт: epochs={self.params.get('epochs')}, "
              f"batch={self.params.get('batch_size')}")

    def on_epoch_end(self, epoch, logs=None):
        logs = logs or {}
        n = self.params.get("epochs", 0)
        if not (epoch == 0 or (epoch + 1) % self.every == 0 or (epoch + 1) == n):
            return
        el = time.time() - self.t0
        eta = el / (epoch + 1) * (n - epoch - 1)
        print(f"  [TF] epoch {epoch+1:>4}/{n}  "
              f"loss={logs.get('loss', float('nan')):.4g}  "
              f"val_loss={logs.get('val_loss', float('nan')):.4g}  "
              f"mae={logs.get('mae', float('nan')):.4g}  "
              f"val_mae={logs.get('val_mae', float('nan')):.4g}  "
              f"{el:6.1f}s  ETA {eta:6.1f}s")


def build_model(n_in, hidden, lr):
    inp = keras.Input(shape=(n_in,))
    x = inp
    for h in hidden:
        x = layers.Dense(h, activation="relu")(x)
    out = layers.Dense(1)(x)
    m = keras.Model(inp, out)
    m.compile(optimizer=keras.optimizers.Adam(lr), loss="mse", metrics=["mae"])
    return m


def fit_tf(Xtr, ytr, Xval, yval, cfg, epochs=TF_EPOCHS, verbose_progress=True):
    sx = RobustScaler().fit(Xtr)
    sy = StandardScaler().fit(ytr.reshape(-1, 1))
    m = build_model(Xtr.shape[1], cfg["hidden"], cfg["lr"])
    callbacks = [TFProgress()] if verbose_progress else []
    m.fit(
        sx.transform(Xtr), sy.transform(ytr.reshape(-1, 1)).ravel(),
        validation_data=(sx.transform(Xval), sy.transform(yval.reshape(-1, 1)).ravel()),
        epochs=epochs, batch_size=cfg["batch"], verbose=0, callbacks=callbacks,
    )
    return {"model": m, "scaler_x": sx, "scaler_y": sy, "backend": "tensorflow"}


def predict(b, X):
    ys = b["model"].predict(b["scaler_x"].transform(X), verbose=0).ravel()
    return b["scaler_y"].inverse_transform(ys.reshape(-1, 1)).ravel()


# ---------------- авто-поиск ----------------

def auto_search_tf(Xtr, ytr, n_splits=3):
    print(f"\n  [auto TF] KFold({n_splits}) по {len(TF_CONFIGS)} конфигам, "
          f"по {TF_EPOCHS_CV} эпох на фолд")
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE)
    results = []
    for i, cfg in enumerate(TF_CONFIGS, 1):
        fold_mae = []
        for j, (tr, va) in enumerate(kf.split(Xtr), 1):
            b = fit_tf(Xtr[tr], ytr[tr], Xtr[va], ytr[va], cfg,
                       epochs=TF_EPOCHS_CV, verbose_progress=False)
            p = predict(b, Xtr[va])
            fold_mae.append(mean_absolute_error(ytr[va], p))
        mean = float(np.mean(fold_mae))
        print(f"  [auto TF] cfg {i}/{len(TF_CONFIGS)}  "
              f"hidden={cfg['hidden']}  lr={cfg['lr']}  batch={cfg['batch']}  "
              f"→ CV MAE = {mean:.4g}")
        results.append((mean, cfg))
    results.sort(key=lambda x: x[0])
    print(f"  [auto TF] best CV MAE = {results[0][0]:.4g}, cfg = {results[0][1]}")
    return results[0][1]


# ---------------- обучение группы ----------------

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

    # для авто-поиска — подвыборка
    if auto_search_on and len(Xtr) > 15000:
        rs = np.random.RandomState(RANDOM_STATE)
        sel = rs.choice(len(Xtr), 15000, replace=False)
        Xsr, ysr = Xtr[sel], ytr[sel]
        print(f"  [auto] подвыборка для поиска: {len(Xsr)}")
    else:
        Xsr, ysr = Xtr, ytr

    cfg = auto_search_tf(Xsr, ysr) if auto_search_on else DEFAULT_CFG

    print(f"\n  [TF] финальный fit: cfg={cfg}, epochs={TF_EPOCHS}")
    t0 = time.time()
    b = fit_tf(Xtr, ytr, Xte, yte, cfg, epochs=TF_EPOCHS, verbose_progress=True)
    print(f"  [TF] готово за {time.time()-t0:.1f}s")

    print("\n=== Метрики (delta = y - pred) ===")
    res = {
        "train": report_predictions("TF-train", ytr, predict(b, Xtr)),
        "test":  report_predictions("TF-test",  yte, predict(b, Xte)),
    }

    d = os.path.join(out_dir, tag)
    os.makedirs(d, exist_ok=True)
    b["model"].save(os.path.join(d, "model.keras"))
    joblib.dump({k: v for k, v in b.items() if k != "model"},
                os.path.join(d, "bundle.pkl"))
    print(f"Сохранено: {d}")

    return {"dir": tag, "n_train": int(len(Xtr)), "n_test": int(len(Xte)),
            "features": list(feats), "metrics": res, "cfg": cfg}


# ---------------- main ----------------

def main():
    print(f"=== TensorFlow {tf.__version__} | auto-stop: OFF ===")
    engine = get_engine()
    df_raw = load_raw(engine)
    print(f"Загружено: {len(df_raw)}")
    print_diag(df_raw)

    setup = interactive_setup()
    if setup["diagnose_only"]:
        return

    df = clean_data(df_raw, fmax=setup["fmax"])
    if len(df) < 2 * MIN_TRAIN:
        sys.exit(f"[ERROR] мало данных: {len(df)}")

    scope, feats = setup["scope"], get_features(setup["scope"])
    print(f"\n=== Режим: {scope}  fmax={setup['fmax']:g}  "
          f"features={feats}  auto_search={setup['auto_search']} ===")

    os.makedirs(OUT_DIR, exist_ok=True)
    index = {
        "scope": scope, "spc_filter": "РК731", "fmax": setup["fmax"],
        "target": TARGET, "features": feats, "backend": "tensorflow",
        "auto_stop": False, "epochs": TF_EPOCHS, "models": {},
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

    save_index(os.path.join(OUT_DIR, "index.json"), index)


if __name__ == "__main__":
    main()