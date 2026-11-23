# -*- coding: utf-8 -*-
"""
Предсказание Filtr_Freq по сохранённым моделям (TF / PyTorch, global / per-spc).
Подтягивает модель по Spc из index.json.
"""
import argparse, json, os, sys
import numpy as np, pandas as pd
from sqlalchemy import create_engine, text
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import joblib

DB_URL     = "mysql+mysqlconnector://xampp:43FPa!29S8HQeAW@MES1:3306/coordinator"
BASE_FEATS = ["F", "R", "Q", "C0", "Cq", "L", "Nominal"]
DERIVED    = ["Nominal_Hz", "F_Hz"]
FEATURES   = BASE_FEATS + DERIVED
TARGET     = "Filtr_Freq"


# ---------------- Бэкенды ----------------

def _predict_tf(model_dir, X):
    from tensorflow import keras
    b = joblib.load(os.path.join(model_dir, "bundle.pkl"))
    m = keras.models.load_model(os.path.join(model_dir, "model.keras"))
    ys = m.predict(b["scaler_x"].transform(X), verbose=0).ravel()
    return b["scaler_y"].inverse_transform(ys.reshape(-1, 1)).ravel()


def _predict_torch(model_dir, X):
    import torch, torch.nn as nn
    b = joblib.load(os.path.join(model_dir, "bundle.pkl"))
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
    m = MLP(b["n_in"])
    m.load_state_dict(torch.load(os.path.join(model_dir, "model.pt"), map_location="cpu"))
    m.eval()
    with torch.no_grad():
        ys = m(torch.tensor(b["scaler_x"].transform(X), dtype=torch.float32)).numpy()
    return b["scaler_y"].inverse_transform(ys.reshape(-1, 1)).ravel()


def predict_dir(model_dir, X, backend):
    return _predict_tf(model_dir, X) if backend == "tensorflow" else _predict_torch(model_dir, X)


# ---------------- main ----------------

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True,
                    help="Каталог с index.json и моделями: models_tf/ или models_torch/")
    ap.add_argument("--mode", choices=["validate", "predict"], default="validate")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    idx_path = os.path.join(args.models, "index.json")
    if not os.path.exists(idx_path):
        sys.exit(f"[ERROR] нет {idx_path}. Сначала запустите train_model_tf.py / _torch.py")
    with open(idx_path, encoding="utf-8") as f:
        index = json.load(f)

    scope, backend = index["scope"], index["backend"]
    spc_filter = index["spc_filter"]
    fmin, fmax = -index["fmax"], index["fmax"]
    print(f"Модели: {args.models}  scope={scope}  backend={backend}")
    print(f"Spc~'{spc_filter}'  |{TARGET}|<{fmax:g}")

    engine = create_engine(DB_URL, pool_pre_ping=True)
    cond = f"{TARGET} IS NOT NULL" if args.mode == "validate" else f"{TARGET} IS NULL"
    sel = f"ID, Spc, {', '.join(BASE_FEATS)}" + \
          (f", {TARGET}" if args.mode == "validate" else "")
    q = text(f"SELECT {sel} FROM psidata WHERE Spc LIKE :spc AND {cond}")
    df = pd.read_sql(q, engine, params={"spc": f"%{spc_filter}%"})
    if args.limit:
        df = df.head(args.limit)
    print(f"Строк: {len(df)}")
    if len(df) == 0:
        return

    for c in BASE_FEATS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Nominal_Hz"] = df["Nominal"] * 1e6
    df["F_Hz"]       = df["F"] * df["Nominal"]
    df = df.dropna(subset=FEATURES).copy()

    models_map = index["models"]
    fallback = models_map.get("*")

    df["_pred"] = np.nan
    for spc, sub in df.groupby("Spc"):
        if scope == "per-spc":
            spec = models_map.get(spc) or fallback
            if spec is None:
                print(f"[skip] Spc={spc!r}: нет модели")
                continue
        else:
            spec = fallback
            if spec is None:
                continue
        d = os.path.join(args.models, spec["dir"])
        df.loc[sub.index, "_pred"] = predict_dir(d, sub[FEATURES].to_numpy(float), backend)
    df = df.dropna(subset=["_pred"]).copy()
    df["Predicted"] = df["_pred"]

    if args.mode == "validate" and TARGET in df:
        y_true = pd.to_numeric(df[TARGET], errors="coerce").to_numpy(float)
        ok = (~np.isnan(y_true)) & (y_true >= fmin) & (y_true <= fmax)
        if ok.sum() > 1:
            yp = df["Predicted"].to_numpy()[ok]
            print("\n=== Метрики (валидные строки) ===")
            print(f"  n={int(ok.sum())}  "
                  f"RMSE={np.sqrt(mean_squared_error(y_true[ok], yp)):.4g}  "
                  f"MAE={mean_absolute_error(y_true[ok], yp):.4g}  "
                  f"R²={r2_score(y_true[ok], yp):.4f}")
            print("\n=== По Spc ===")
            for spc, sub in df[ok].groupby("Spc"):
                yt = pd.to_numeric(sub[TARGET], errors="coerce").to_numpy(float)
                ypv = sub["Predicted"].to_numpy()
                m = ~np.isnan(yt)
                if m.sum() < 2: continue
                print(f"  {spc!r:35s} n={int(m.sum()):<6} "
                      f"MAE={mean_absolute_error(yt[m], ypv[m]):.4g}  "
                      f"RMSE={np.sqrt(mean_squared_error(yt[m], ypv[m])):.4g}  "
                      f"R²={r2_score(yt[m], ypv[m]):.4f}")
        df["Error_Hz"] = y_true - df["Predicted"]

    show = (["ID", "Spc"] + BASE_FEATS +
            (([TARGET, "Error_Hz"] if args.mode == "validate" else []) + ["Predicted"]))
    with pd.option_context("display.max_columns", None, "display.width", 260):
        print(df[show].head(20).to_string(index=False))

    out = args.out or f"predictions_{args.mode}.csv"
    df[show].to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\nСохранено: {os.path.abspath(out)}")


if __name__ == "__main__":
    main()