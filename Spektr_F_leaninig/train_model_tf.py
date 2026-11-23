# -*- coding: utf-8 -*-
"""
TensorFlow/Keras — предсказание Filtr_Freq.
Добавлены: фиче-инжиниринг, HGB-baseline, разбивка метрик по Measure_ID,
           остаточный анализ на батч-эффект.
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
import tensorflow as tf
from tensorflow import keras
from tensorflow.keras import layers

DB_URL       = "mysql+mysqlconnector://xampp:43FPa!29S8HQeAW@MES1:3306/coordinator"
SPC_FILTER   = "РК731"
RAW_FEATS    = ["F", "R", "Q", "C0", "Cq", "L", "Nominal"]
TARGET       = "Filtr_Freq"
RANDOM_STATE = 42
DEFAULT_FMAX = 500.0
OUT_DIR      = "models_tf"
MIN_PER_SPC  = 100

# --- доп. колонки из psidata, если есть в таблице ---
EXTRA_COLS   = ["Fptp", "Fmax", "Fmin", "C0_C1", "Mono", "F0_Fl", "Rmax_Rmin",
                "Fs_ppm", "Fl_ppm", "delta_Fint", "Measure_ID", "PH_ID", "Date"]
# ---------------------------------------------------


def safe_name(s): return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_") or "empty"


def available_cols(engine, table="psidata"):
    q = text(f"SHOW COLUMNS FROM {table}")
    return {r[0] for r in engine.execute(q)}


def load_data(engine):
    cols = available_cols(engine)
    use_extra = [c for c in EXTRA_COLS if c in cols]
    print(f"Доп. признаки из psidata: {use_extra or '—'}")
    all_feats = RAW_FEATS + use_extra
    q = text(f"SELECT ID, Spc, {', '.join(all_feats)}, {TARGET} "
             f"FROM psidata WHERE Spc LIKE :spc AND {TARGET} IS NOT NULL")
    df = pd.read_sql(q, engine, params={"spc": f"%{SPC_FILTER}%"})
    df.attrs["extra_cols_used"] = use_extra
    return df, all_feats


def clean_and_fe(df, feats, fmax):
    df = df.copy()
    for c in feats + [TARGET]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=feats + [TARGET])
    df = df[(df["Nominal"] > 0) & (df["Nominal"] < 1000)]
    df = df[df["F"].abs() < 1e5]
    df = df[(df["R"] > 0) & (df["Q"] > 0) & (df["L"] > 0)]
    df = df[df[TARGET].abs() < fmax].copy()

    # ---------- ФИЧЕ-ИНЖИНИРИНГ ----------
    eps = 1e-12
    df["Nominal_Hz"] = df["Nominal"] * 1e6
    df["F_Hz"]       = df["F"] * df["Nominal"]
    df["F_Hz_over_Q"]     = df["F_Hz"] / (df["Q"] + eps)
    df["F_Hz_times_Cq"]   = df["F_Hz"] * df["Cq"]
    df["C0_over_Cq"]      = df["C0"] / (df["Cq"] + eps)
    df["R_times_C0"]      = df["R"] * df["C0"]
    df["Q_sq"]            = df["Q"] ** 2
    df["sqrt_F_Hz_signed"] = np.sign(df["F_Hz"]) * np.sqrt(np.abs(df["F_Hz"]) + eps)
    df["L_over_Cq"]       = df["L"] / (df["Cq"] + eps)
    df["F_times_Cq"]      = df["F"] * df["Cq"]
    df["F_over_R"]        = df["F"] / (df["R"] + eps)
    # ---------------------------------------

    engineered = ["Nominal_Hz", "F_Hz", "F_Hz_over_Q", "F_Hz_times_Cq",
                  "C0_over_Cq", "R_times_C0", "Q_sq", "sqrt_F_Hz_signed",
                  "L_over_Cq", "F_times_Cq", "F_over_R"]
    return df, feats + engineered


def build_model(n_in):
    inp = keras.Input(shape=(n_in,))
    x = layers.Dense(128, activation="relu")(inp)
    x = layers.Dense(64,  activation="relu")(x)
    x = layers.Dense(32,  activation="relu")(x)
    out = layers.Dense(1)(x)
    m = keras.Model(inp, out)
    m.compile(optimizer=keras.optimizers.Adam(1e-3), loss="mse", metrics=["mae"])
    return m


def fit_tf(Xtr, ytr, Xval, yval, verbose=0):
    sx = RobustScaler().fit(Xtr)
    sy = StandardScaler().fit(ytr.reshape(-1, 1))
    m = build_model(Xtr.shape[1])
    cb = [keras.callbacks.EarlyStopping(
        monitor="val_loss", patience=40, restore_best_weights=True)]
    m.fit(sx.transform(Xtr), sy.transform(ytr.reshape(-1, 1)).ravel(),
          validation_data=(sx.transform(Xval), sy.transform(yval.reshape(-1, 1)).ravel()),
          epochs=800, batch_size=256, verbose=verbose, callbacks=cb)
    return {"model": m, "scaler_x": sx, "scaler_y": sy, "backend": "tensorflow"}


def fit_hgb(Xtr, ytr, Xval, yval):
    m = TransformedTargetRegressor(
        regressor=HistGradientBoostingRegressor(
            max_iter=1500, learning_rate=0.03, max_leaf_nodes=63,
            l2_regularization=1e-3, early_stopping=True,
            n_iter_no_change=40, random_state=RANDOM_STATE),
        transformer=StandardScaler())
    m.fit(Xtr, ytr)
    return {"model": m, "backend": "sklearn_hgb"}


def predict(b, X):
    if b["backend"] == "tensorflow":
        ys = b["model"].predict(b["scaler_x"].transform(X), verbose=0).ravel()
        return b["scaler_y"].inverse_transform(ys.reshape(-1, 1)).ravel()
    return b["model"].predict(X)


def report(name, yt, yp):
    return {"n": int(len(yt)),
            "rmse": float(np.sqrt(mean_squared_error(yt, yp))),
            "mae":  float(mean_absolute_error(yt, yp)),
            "r2":   float(r2_score(yt, yp)) if np.std(yt) > 0 else float("nan")}


def print_report(name, m):
    print(f"  {name:<8} RMSE={m['rmse']:10.4g}  MAE={m['mae']:10.4g}  R²={m['r2']:.4f}")


def save_tf(b, out_dir, tag):
    d = os.path.join(out_dir, tag); os.makedirs(d, exist_ok=True)
    b["model"].save(os.path.join(d, "model.keras"))
    joblib.dump({k: v for k, v in b.items() if k != "model"},
                os.path.join(d, "bundle.pkl"))
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=["global", "per-spc"], default="global")
    ap.add_argument("--fmax", type=float, default=DEFAULT_FMAX)
    ap.add_argument("--out", default=OUT_DIR)
    ap.add_argument("--verbose", type=int, default=0)
    ap.add_argument("--diagnose-only", action="store_true")
    args = ap.parse_args()

    print(f"=== TensorFlow {tf.__version__} | scope={args.scope} | |Filtr_Freq|<{args.fmax:g}")
    engine = create_engine(DB_URL, pool_pre_ping=True)
    df, feats = load_data(engine)
    df, feats = clean_and_fe(df, feats, args.fmax)
    print(f"После чистки и FE: n={len(df)}  n_features={len(feats)}")

    print("\nГруппы Spc:")
    for spc, n in df.groupby("Spc").size().sort_values(ascending=False).items():
        print(f"  {spc!r:40s} n={n}")
    if args.diagnose_only:
        return

    if len(df) < 200:
        sys.exit("[ERROR] мало данных")

    os.makedirs(args.out, exist_ok=True)
    index = {"scope": args.scope, "spc_filter": SPC_FILTER, "fmax": args.fmax,
             "features": feats, "target": TARGET, "backend": "tensorflow", "models": {}}

    def one_run(sub, tag, key):
        print(f"\n=== {tag} (n={len(sub)}) ===")
        # split
        idx_tr, idx_te = train_test_split(sub.index, test_size=0.2, random_state=RANDOM_STATE)
        Xtr, Xte = sub.loc[idx_tr, feats].to_numpy(float), sub.loc[idx_te, feats].to_numpy(float)
        ytr, yte = sub.loc[idx_tr, TARGET].to_numpy(float), sub.loc[idx_te, TARGET].to_numpy(float)

        # baseline
        print("Baselines:")
        print_report("mean", report("mean", yte, np.full_like(yte, ytr.mean())))
        print_report("F_Hz", report("F_Hz", yte, sub.loc[idx_te, "F_Hz"].to_numpy(float)))

        # models
        print("\nModels:")
        res = {}
        b_tf = fit_tf(Xtr, ytr, Xte, yte, args.verbose)
        res["tf"] = {"train": report("train", ytr, predict(b_tf, Xtr)),
                     "test":  report("test",  yte, predict(b_tf, Xte))}
        print_report("TF-train", res["tf"]["train"]); print_report("TF-test", res["tf"]["test"])

        b_hgb = fit_hgb(Xtr, ytr, Xte, yte)
        res["hgb"] = {"train": report("train", ytr, predict(b_hgb, Xtr)),
                      "test":  report("test",  yte, predict(b_hgb, Xte))}
        print_report("HGB-train", res["hgb"]["train"]); print_report("HGB-test", res["hgb"]["test"])

        best = "hgb" if res["hgb"]["test"]["mae"] < res["tf"]["test"]["mae"] else "tf"
        print(f"Лучший: {best}")

        # residual analysis by Measure_ID (если есть)
        if "Measure_ID" in sub.columns:
            pred = predict(b_tf if best == "tf" else b_hgb, Xte)
            te = sub.loc[idx_te, ["Measure_ID", TARGET]].copy()
            te["pred"] = pred
            te["res"] = te[TARGET] - te["pred"]
            print("\nСредний residual по Measure_ID (батч-эффект):")
            for mid, g in te.groupby("Measure_ID"):
                print(f"  Measure_ID={mid}: n={len(g)}  mean_res={g['res'].mean():+.2f}  "
                      f"std={g['res'].std():.2f}")

        # save TF (пользователь просил TF-вариант)
        d = save_tf(b_tf, args.out, tag)
        index["models"][key] = {"dir": os.path.relpath(d, args.out),
                                "n_train": int(len(Xtr)), "n_test": int(len(Xte)),
                                "metrics": res, "best": best,
                                "features": feats}
        print(f"Сохранено: {d}")

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