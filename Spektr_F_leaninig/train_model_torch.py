# -*- coding: utf-8 -*-
"""
PyTorch — предсказание Filtr_Freq.
--scope global / per-spc, features для per-spc без Nominal.
"""
import argparse, json, os, re, sys
import numpy as np, pandas as pd
from sqlalchemy import create_engine, text
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import RobustScaler, StandardScaler
import joblib
import torch
import torch.nn as nn
from torch.utils.data import TensorDataset, DataLoader

DB_URL       = "mysql+mysqlconnector://xampp:43FPa!29S8HQeAW@MES1:3306/coordinator"
SPC_FILTER   = "РК731"
RAW_FEATS    = ["F", "R", "Q", "C0", "Cq", "L", "Nominal"]
TARGET       = "Filtr_Freq"
RANDOM_STATE = 42
DEFAULT_FMAX = 500.0
OUT_DIR      = "models_torch"
MIN_PER_SPC  = 100

GLOBAL_FEATS = ["F", "R", "Q", "C0", "Cq", "L", "Nominal",
                "Nominal_Hz", "F_Hz", "F_Hz_over_Q", "F_over_Q",
                "F_times_Cq", "C0_over_Cq", "R_times_C0", "Q_sq",
                "L_over_Cq", "F_over_R"]
PERSPS_FEATS = ["F", "R", "Q", "C0", "Cq", "L",
                "F_over_Q", "F_times_Cq", "C0_over_Cq", "R_times_C0",
                "Q_sq", "L_over_Cq", "F_over_R"]


def safe_name(s): return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_") or "empty"


def load_data(engine):
    q = text(f"SELECT ID, Spc, {', '.join(RAW_FEATS)}, {TARGET} "
             f"FROM psidata WHERE Spc LIKE :spc AND {TARGET} IS NOT NULL")
    return pd.read_sql(q, engine, params={"spc": f"%{SPC_FILTER}%"})


def make_all_features(df):
    df = df.copy(); eps = 1e-12
    df["Nominal_Hz"]  = df["Nominal"] * 1e6
    df["F_Hz"]        = df["F"] * df["Nominal"]
    df["F_over_Q"]    = df["F"] / (df["Q"] + eps)
    df["F_times_Cq"]  = df["F"] * df["Cq"]
    df["F_Hz_over_Q"] = df["F_Hz"] / (df["Q"] + eps)
    df["C0_over_Cq"]  = df["C0"] / (df["Cq"] + eps)
    df["R_times_C0"]  = df["R"] * df["C0"]
    df["Q_sq"]        = df["Q"] ** 2
    df["L_over_Cq"]   = df["L"] / (df["Cq"] + eps)
    df["F_over_R"]    = df["F"] / (df["R"] + eps)
    return df


def clean_and_fe(df, fmax, scope):
    df = df.copy()
    for c in RAW_FEATS + [TARGET]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=RAW_FEATS + [TARGET])
    df = df[(df["Nominal"] > 0) & (df["Nominal"] < 1000)]
    df = df[df["F"].abs() < 1e5]
    df = df[(df["R"] > 0) & (df["Q"] > 0) & (df["L"] > 0)]
    df = df[df[TARGET].abs() < fmax].copy()
    df = make_all_features(df)
    feats = list(GLOBAL_FEATS if scope == "global" else PERSPS_FEATS)
    feats = [c for c in feats if c in df.columns and df[c].std() > 1e-9]
    return df, feats


class MLP(nn.Module):
    def __init__(self, n_in):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(n_in, 128), nn.ReLU(),
            nn.Linear(128, 64),  nn.ReLU(),
            nn.Linear(64, 32),   nn.ReLU(),
            nn.Linear(32, 1),
        )
    def forward(self, x): return self.net(x).squeeze(-1)


def fit_torch(Xtr, ytr, Xval, yval, patience=40, max_epochs=800):
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    sx = RobustScaler().fit(Xtr)
    sy = StandardScaler().fit(ytr.reshape(-1, 1))
    Xtr_t = torch.tensor(sx.transform(Xtr), dtype=torch.float32)
    Xval_t = torch.tensor(sx.transform(Xval), dtype=torch.float32).to(device)
    ytr_t = torch.tensor(sy.transform(ytr.reshape(-1, 1)).ravel(), dtype=torch.float32)
    yval_t = torch.tensor(sy.transform(yval.reshape(-1, 1)).ravel(), dtype=torch.float32).to(device)

    dl = DataLoader(TensorDataset(Xtr_t, ytr_t), batch_size=256, shuffle=True)
    model = MLP(Xtr.shape[1]).to(device)
    opt = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    loss_fn = nn.MSELoss()

    best_val, best_state, counter = float("inf"), None, 0
    for _ in range(max_epochs):
        model.train()
        for xb, yb in dl:
            xb, yb = xb.to(device), yb.to(device)
            opt.zero_grad(); loss = loss_fn(model(xb), yb); loss.backward(); opt.step()
        model.eval()
        with torch.no_grad():
            vl = float(loss_fn(model(Xval_t), yval_t).item())
        if vl < best_val - 1e-6:
            best_val = vl
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            counter = 0
        else:
            counter += 1
            if counter >= patience: break

    return {"state_dict": best_state, "n_in": int(Xtr.shape[1]),
            "scaler_x": sx, "scaler_y": sy, "backend": "pytorch"}


def fit_hgb(Xtr, ytr):
    m = TransformedTargetRegressor(
        regressor=HistGradientBoostingRegressor(
            max_iter=1500, learning_rate=0.03, max_leaf_nodes=63,
            l2_regularization=1e-3, early_stopping=True,
            n_iter_no_change=100, random_state=RANDOM_STATE),
        transformer=StandardScaler())
    m.fit(Xtr, ytr)
    return {"model": m, "backend": "sklearn_hgb"}


def predict(b, X):
    if b["backend"] == "pytorch":
        model = MLP(b["n_in"]); model.load_state_dict(b["state_dict"]); model.eval()
        with torch.no_grad():
            ys = model(torch.tensor(b["scaler_x"].transform(X), dtype=torch.float32)).numpy()
        return b["scaler_y"].inverse_transform(ys.reshape(-1, 1)).ravel()
    return b["model"].predict(X)


def report(yt, yp):
    return {"n": int(len(yt)),
            "rmse": float(np.sqrt(mean_squared_error(yt, yp))),
            "mae":  float(mean_absolute_error(yt, yp)),
            "r2":   float(r2_score(yt, yp)) if np.std(yt) > 0 else float("nan")}


def print_report(name, m):
    print(f"  {name:<8} RMSE={m['rmse']:10.4g}  MAE={m['mae']:10.4g}  R²={m['r2']:.4f}")


def save_torch(b, out_dir, tag):
    d = os.path.join(out_dir, tag); os.makedirs(d, exist_ok=True)
    torch.save(b["state_dict"], os.path.join(d, "model.pt"))
    joblib.dump({k: v for k, v in b.items() if k != "state_dict"},
                os.path.join(d, "bundle.pkl"))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["global", "per-spc"], default="global")
    ap.add_argument("--fmax", type=float, default=DEFAULT_FMAX)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--diagnose-only", action="store_true")
    args = ap.parse_args()

    print(f"=== PyTorch {torch.__version__} CUDA={torch.cuda.is_available()} | "
          f"scope={args.scope} | |Filtr_Freq|<{args.fmax:g}")
    engine = create_engine(DB_URL, pool_pre_ping=True)
    df = load_data(engine)
    print(f"Загружено: {len(df)}")
    os.makedirs(args.out, exist_ok=True)
    index = {"scope": args.scope, "spc_filter": SPC_FILTER, "fmax": args.fmax,
             "target": TARGET, "backend": "pytorch", "models": {}}

    def one_run(sub, tag, key):
        sub, feats = clean_and_fe(sub, args.fmax, args.scope)
        print(f"\n=== {tag} (n={len(sub)}, n_features={len(feats)}) ===")
        if len(feats) == 0:
            print("[skip] нет признаков"); return
        idx_tr, idx_te = train_test_split(sub.index, test_size=0.2, random_state=RANDOM_STATE)
        Xtr = sub.loc[idx_tr, feats].to_numpy(float); Xte = sub.loc[idx_te, feats].to_numpy(float)
        ytr = sub.loc[idx_tr, TARGET].to_numpy(float); yte = sub.loc[idx_te, TARGET].to_numpy(float)

        print("Baselines:")
        print_report("mean", report(yte, np.full_like(yte, ytr.mean())))
        if "F_Hz" in feats:
            print_report("F_Hz", report(yte, sub.loc[idx_te, "F_Hz"].to_numpy(float)))

        b_torch = fit_torch(Xtr, ytr, Xte, yte)
        res = {"torch": {"train": report(ytr, predict(b_torch, Xtr)),
                         "test":  report(yte, predict(b_torch, Xte))}}
        print("Torch:"); print_report("train", res["torch"]["train"]); print_report("test", res["torch"]["test"])

        b_hgb = fit_hgb(Xtr, ytr)
        res["hgb"] = {"train": report(ytr, predict(b_hgb, Xtr)),
                      "test":  report(yte, predict(b_hgb, Xte))}
        print("HGB:"); print_report("train", res["hgb"]["train"]); print_report("test", res["hgb"]["test"])

        best = "hgb" if res["hgb"]["test"]["mae"] < res["torch"]["test"]["mae"] else "torch"
        print(f"Лучший: {best}")

        d = save_torch(b_torch, args.out, tag)
        index["models"][key] = {"dir": os.path.relpath(d, args.out),
                                "n_train": int(len(Xtr)), "n_test": int(len(Xte)),
                                "features": feats, "metrics": res, "best": best}

    if args.diagnose_only:
        d0, _ = clean_and_fe(df, args.fmax, args.scope)
        print("\nГруппы Spc:")
        for spc, n in d0.groupby("Spc").size().sort_values(ascending=False).items():
            print(f"  {spc!r:40s} n={n}")
        return

    if args.scope == "global":
        one_run(df, "global", "*")
    else:
        for spc, sub in df.groupby("Spc"):
            if len(sub) < MIN_PER_SPC:
                print(f"[skip] Spc={spc!r}: n={len(sub)} < {MIN_PER_SPC}")
                continue
            one_run(sub, "spc_" + safe_name(spc), spc)

    with open(os.path.join(args.out, "index.json"), "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"\nИндекс: {os.path.join(args.out, 'index.json')}")


if __name__ == "__main__":
    main()