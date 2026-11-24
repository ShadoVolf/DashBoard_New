# -*- coding: utf-8 -*-
"""
PyTorch: единый интерактив, авто-подбор через KFold-grid.
Auto-stop: OFF. Прогресс печатается каждые PROGRESS_EVERY эпох.
"""
import os, sys, time
import numpy as np, pandas as pd
from sklearn.model_selection import train_test_split, KFold
from sklearn.preprocessing import RobustScaler, StandardScaler
from sklearn.metrics import mean_absolute_error
import joblib
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader
from training_common import (
    TARGET, FILTR_MIN, FILTR_MAX, MIN_PER_SPC, MIN_TRAIN, TEST_SIZE, RANDOM_STATE,
    get_engine, load_raw, clean_data, get_features, interactive_setup,
    print_diag, report_predictions, safe_name, save_index,
)

OUT_DIR         = "models_torch"
TORCH_EPOCHS    = 400
TORCH_EPOCHS_CV = 150
TORCH_BATCH     = 256
PROGRESS_EVERY  = 20

TORCH_CONFIGS = [
    {"hidden": (128, 64, 32), "lr": 1e-3, "batch": 256, "wd": 1e-4},
    {"hidden": (256, 128, 64), "lr": 1e-3, "batch": 256, "wd": 1e-4},
    {"hidden": (128, 128, 64, 32), "lr": 5e-4, "batch": 256, "wd": 1e-4},
    {"hidden": (256, 128, 64), "lr": 5e-4, "batch": 128, "wd": 1e-3},
]
DEFAULT_CFG = {"hidden": (128, 64, 32), "lr": 1e-3, "batch": TORCH_BATCH, "wd": 1e-4}


class MLP(nn.Module):
    def __init__(self, n_in, hidden):
        super().__init__()
        layers_ = []
        prev = n_in
        for h in hidden:
            layers_ += [nn.Linear(prev, h), nn.ReLU()]
            prev = h
        layers_.append(nn.Linear(prev, 1))
        self.net = nn.Sequential(*layers_)

    def forward(self, x):
        return self.net(x).squeeze(-1)


def fit_torch(Xtr, ytr, Xval, yval, cfg, epochs=TORCH_EPOCHS, verbose_progress=True):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    sx = RobustScaler().fit(Xtr)
    sy = StandardScaler().fit(ytr.reshape(-1, 1))

    Xtr_t  = torch.tensor(sx.transform(Xtr), dtype=torch.float32)
    Xval_t = torch.tensor(sx.transform(Xval), dtype=torch.float32).to(device)
    ytr_t  = torch.tensor(sy.transform(ytr.reshape(-1, 1)).ravel(), dtype=torch.float32)
    yval_t = torch.tensor(sy.transform(yval.reshape(-1, 1)).ravel(), dtype=torch.float32).to(device)

    dl = DataLoader(TensorDataset(Xtr_t, ytr_t), batch_size=cfg["batch"], shuffle=True)
    model = MLP(Xtr.shape[1], cfg["hidden"]).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=cfg["lr"], weight_decay=cfg["wd"])
    loss_fn = nn.MSELoss()

    if verbose_progress:
        print(f"  [Torch] старт: epochs={epochs}, batch={cfg['batch']}, "
              f"hidden={cfg['hidden']}, lr={cfg['lr']}")

    t0 = time.time()
    for ep in range(epochs):
        model.train()
        for xb, yb in dl:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad()
            loss = loss_fn(model(xb), yb)
            loss.backward()
            opt.step()

        if verbose_progress and (ep == 0 or (ep + 1) % PROGRESS_EVERY == 0 or ep + 1 == epochs):
            model.eval()
            with torch.no_grad():
                val_loss = float(loss_fn(model(Xval_t), yval_t).item())
            el = time.time() - t0
            eta = el / (ep + 1) * (epochs - ep - 1)
            print(f"  [Torch] epoch {ep+1:>4}/{epochs}  val_loss={val_loss:.4g}  "
                  f"{el:6.1f}s  ETA {eta:6.1f}s")

    return {"state_dict": model.state_dict(), "n_in": int(Xtr.shape[1]),
            "hidden": cfg["hidden"], "scaler_x": sx, "scaler_y": sy, "backend": "pytorch"}


def predict(b, X):
    model = MLP(b["n_in"], b["hidden"])
    model.load_state_dict(b["state_dict"]); model.eval()
    with torch.no_grad():
        ys = model(torch.tensor(b["scaler_x"].transform(X), dtype=torch.float32)).numpy()
    return b["scaler_y"].inverse_transform(ys.reshape(-1, 1)).ravel()


def auto_search_torch(Xtr, ytr, n_splits=3):
    print(f"\n  [auto Torch] KFold({n_splits}) по {len(TORCH_CONFIGS)} конфигам, "
          f"по {TORCH_EPOCHS_CV} эпох")
    kf = KFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE)
    results = []
    for i, cfg in enumerate(TORCH_CONFIGS, 1):
        fold_mae = []
        for tr, va in kf.split(Xtr):
            b = fit_torch(Xtr[tr], ytr[tr], Xtr[va], ytr[va], cfg,
                          epochs=TORCH_EPOCHS_CV, verbose_progress=False)
            p = predict(b, Xtr[va])
            fold_mae.append(mean_absolute_error(ytr[va], p))
        m = float(np.mean(fold_mae))
        print(f"  [auto Torch] cfg {i}/{len(TORCH_CONFIGS)}  "
              f"hidden={cfg['hidden']}  lr={cfg['lr']}  batch={cfg['batch']}  "
              f"→ CV MAE = {m:.4g}")
        results.append((m, cfg))
    results.sort(key=lambda x: x[0])
    print(f"  [auto Torch] best CV MAE = {results[0][0]:.4g}, cfg = {results[0][1]}")
    return results[0][1]


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

    if auto_search_on and len(Xtr) > 15000:
        rs = np.random.RandomState(RANDOM_STATE)
        sel = rs.choice(len(Xtr), 15000, replace=False)
        Xsr, ysr = Xtr[sel], ytr[sel]
        print(f"  [auto] подвыборка для поиска: {len(Xsr)}")
    else:
        Xsr, ysr = Xtr, ytr

    cfg = auto_search_torch(Xsr, ysr) if auto_search_on else DEFAULT_CFG

    print(f"\n  [Torch] финальный fit: cfg={cfg}, epochs={TORCH_EPOCHS}")
    b = fit_torch(Xtr, ytr, Xte, yte, cfg, epochs=TORCH_EPOCHS, verbose_progress=True)

    print("\n=== Метрики (delta = y - pred) ===")
    res = {
        "train": report_predictions("Torch-train", ytr, predict(b, Xtr)),
        "test":  report_predictions("Torch-test",  yte, predict(b, Xte)),
    }

    d = os.path.join(out_dir, tag)
    os.makedirs(d, exist_ok=True)
    torch.save(b["state_dict"], os.path.join(d, "model.pt"))
    joblib.dump({k: v for k, v in b.items() if k != "state_dict"},
                os.path.join(d, "bundle.pkl"))
    print(f"Сохранено: {d}")

    return {"dir": tag, "n_train": int(len(Xtr)), "n_test": int(len(Xte)),
            "features": list(feats), "metrics": res, "cfg": cfg}


def main():
    print(f"=== PyTorch {torch.__version__} CUDA={torch.cuda.is_available()} | "
          f"auto-stop: OFF ===")
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
        "target": TARGET, "features": feats, "backend": "pytorch",
        "auto_stop": False, "epochs": TORCH_EPOCHS, "models": {},
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