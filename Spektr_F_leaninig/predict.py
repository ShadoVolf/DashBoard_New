# -*- coding: utf-8 -*-
"""
Инференс Filtr_Freq (Гц).

Поддерживает два формата моделей:
  * --models <файл.joblib>          — одна глобальная модель (train_model.py → global)
  * --models <каталог с index.json> — модели по спецификациям (train_model.py → per-spc)

Если --models не задан, ищется сначала model_rk731.joblib, потом models_sklearn/index.json.
"""
import argparse, json, os, sys
import numpy as np, pandas as pd
from sqlalchemy import create_engine, text
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
import joblib

DB_URL               = "mysql+mysqlconnector://xampp:43FPa!29S8HQeAW@MES1:3306/coordinator"
DEFAULT_GLOBAL_MODEL = "model_rk731.joblib"
DEFAULT_PER_SPC_DIR  = "models_sklearn"
BASE_FEATS           = ["F", "R", "Q", "C0", "Cq", "L", "Nominal"]
TARGET               = "Filtr_Freq"


def resolve_models_path(user_arg):
    if user_arg:
        if not os.path.exists(user_arg):
            sys.exit(f"[ERROR] Путь не найден: {user_arg}")
        return user_arg
    if os.path.exists(DEFAULT_GLOBAL_MODEL):
        return DEFAULT_GLOBAL_MODEL
    if os.path.exists(os.path.join(DEFAULT_PER_SPC_DIR, "index.json")):
        return DEFAULT_PER_SPC_DIR
    sys.exit(
        f"[ERROR] Нет ни {DEFAULT_GLOBAL_MODEL}, ни {DEFAULT_PER_SPC_DIR}/index.json. "
        f"Сначала train_model.py"
    )


def get_feats(b: dict) -> list:
    if b.get("features"):
        return list(b["features"])
    return list(b["base_features"]) + list(b.get("derived", []))


def load_global(path):
    b = joblib.load(path)
    return {
        "bundle":     b,
        "features":   get_feats(b),
        "spc_like":   b["spc"],
        "fmax_abs":   max(abs(b["filtr_bounds"][0]), abs(b["filtr_bounds"][1])),
    }


def load_per_spc(model_dir: str):
    idx_path = os.path.join(model_dir, "index.json")
    if not os.path.exists(idx_path):
        sys.exit(f"[ERROR] Нет {idx_path}")
    with open(idx_path, encoding="utf-8") as f:
        index = json.load(f)
    # подгружаем bundle-ы
    for spec in index["models"].values():
        spec["_bundle"] = joblib.load(os.path.join(model_dir, spec["dir"], "model.joblib"))
        if not spec.get("features"):
            spec["features"] = get_feats(spec["_bundle"])
    return index


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default=None,
                    help="Файл .joblib (global) или каталог с index.json (per-spc)")
    ap.add_argument("--mode", choices=["validate", "predict"], default="validate")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    models_path = resolve_models_path(args.models)
    is_per_spc  = os.path.isdir(models_path)

    if is_per_spc:
        index      = load_per_spc(models_path)
        spc_like   = index["spc_filter"]
        fmax_abs   = float(index["fmax"])
        mode_label = f"per-spc ({models_path})"
        fallback   = index["models"].get("*")
    else:
        g          = load_global(models_path)
        spc_like   = g["spc_like"]
        fmax_abs   = g["fmax_abs"]
        mode_label = f"global  ({models_path})"
        fallback   = None

    print(f"Модель: {mode_label}")
    print(f"Spc~'{spc_like}'  |{TARGET}|<{fmax_abs:g}")

    engine = create_engine(DB_URL, pool_pre_ping=True)
    cond = f"{TARGET} IS NOT NULL" if args.mode == "validate" else f"{TARGET} IS NULL"
    sel  = f"ID, Spc, {', '.join(BASE_FEATS)}" + (f", {TARGET}" if args.mode == "validate" else "")
    q = text(f"SELECT {sel} FROM psidata WHERE Spc LIKE :spc AND {cond}")
    df = pd.read_sql(q, engine, params={"spc": f"%{spc_like}%"})
    if args.limit:
        df = df.head(args.limit)
    print(f"Строк: {len(df)}")
    if len(df) == 0:
        return

    for c in BASE_FEATS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df["Nominal_Hz"] = df["Nominal"] * 1e6
    df["F_Hz"]       = df["F"] * df["Nominal"]

    df["_pred"] = np.nan

    if is_per_spc:
        models_map = index["models"]
        for spc, sub in df.groupby("Spc"):
            spec = models_map.get(spc) or fallback
            if spec is None:
                print(f"[skip] Spc={spc!r}: нет модели")
                continue
            feats = spec["features"]
            sub_ok = sub.dropna(subset=feats)
            if len(sub_ok) == 0:
                continue
            df.loc[sub_ok.index, "_pred"] = spec["_bundle"]["model"].predict(
                sub_ok[feats].to_numpy(float)
            )
    else:
        feats  = g["features"]
        sub_ok = df.dropna(subset=feats)
        df.loc[sub_ok.index, "_pred"] = g["bundle"]["model"].predict(
            sub_ok[feats].to_numpy(float)
        )

    df = df.dropna(subset=["_pred"]).copy()
    df["Predicted"] = df["_pred"]

    if args.mode == "validate" and TARGET in df:
        y_true = pd.to_numeric(df[TARGET], errors="coerce").to_numpy(float)
        ok = (~np.isnan(y_true)) & (y_true >= -fmax_abs) & (y_true <= fmax_abs)
        if ok.sum() > 1:
            yp = df["Predicted"].to_numpy()[ok]
            print("\n=== Метрики (валидные строки) ===")
            print(f"  n={int(ok.sum())}  "
                  f"RMSE={np.sqrt(mean_squared_error(y_true[ok], yp)):.4g}  "
                  f"MAE={mean_absolute_error(y_true[ok], yp):.4g}  "
                  f"R²={r2_score(y_true[ok], yp):.4f}")
            print("\n=== По Spc ===")
            for spc, sub in df[ok].groupby("Spc"):
                yt  = pd.to_numeric(sub[TARGET], errors="coerce").to_numpy(float)
                ypv = sub["Predicted"].to_numpy()
                m = ~np.isnan(yt)
                if m.sum() < 2:
                    continue
                print(f"  {spc!r:35s} n={int(m.sum()):<6} "
                      f"MAE={mean_absolute_error(yt[m], ypv[m]):.4g}  "
                      f"RMSE={np.sqrt(mean_squared_error(yt[m], ypv[m])):.4g}  "
                      f"R²={r2_score(yt[m], ypv[m]):.4f}")
        df["Error_Hz"] = y_true - df["Predicted"]

    show = ["ID", "Spc"] + BASE_FEATS + \
           (([TARGET, "Error_Hz"] if args.mode == "validate" else []) + ["Predicted"])
    with pd.option_context("display.max_columns", None, "display.width", 260):
        print(df[show].head(20).to_string(index=False))

    out = args.out or f"predictions_{args.mode}.csv"
    df[show].to_csv(out, index=False, encoding="utf-8-sig")
    print(f"\nСохранено: {os.path.abspath(out)}")


if __name__ == "__main__":
    main()