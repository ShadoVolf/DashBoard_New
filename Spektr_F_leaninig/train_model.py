# -*- coding: utf-8 -*-
"""
Предсказание Filtr_Freq (Гц) — это МАЛОЕ отклонение настройки, а не абсолют.
Учим цель напрямую.

Управление — ТОЛЬКО через вопросы в консоли:
  * Только диагностика или обучение
  * Одна общая модель (global) ИЛИ отдельная модель на каждую Spc (per-spc)

Для per-spc из списка признаков исключаются Nominal и Nominal_Hz
(они постоянны внутри одной спецификации и не несут информации).
"""
import json, os, re, sys
import numpy as np, pandas as pd
from sqlalchemy import create_engine, text
from sklearn.compose import TransformedTargetRegressor
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import train_test_split
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import RobustScaler, StandardScaler
import joblib

DB_URL       = "mysql+mysqlconnector://xampp:43FPa!29S8HQeAW@MES1:3306/coordinator"
SPC_FILTER   = "РК731"
BASE_FEATS   = ["F", "R", "Q", "C0", "Cq", "L", "Nominal"]
DERIVED      = ["Nominal_Hz", "F_Hz"]
TARGET       = "Filtr_Freq"
MODEL_PATH   = "model_rk731.joblib"     # глобальная модель
OUT_DIR      = "models_sklearn"         # каталог per-spc моделей
RANDOM_STATE = 42
FILTR_MIN, FILTR_MAX = -500.0, 500.0
MIN_PER_SPC  = 100


def safe_name(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_") or "empty"


# ---------------- интерактив ----------------

def prompt_yn(label: str) -> bool:
    while True:
        s = input(f"{label} (д/н): ").strip().lower()
        if s in ("д", "да", "y", "yes", ""):
            return True
        if s in ("н", "нет", "n", "no"):
            return False
        print("  Введите 'д' или 'н'.")


def prompt_choice(label: str, choices: list) -> str:
    print(f"\n{label}")
    for i, c in enumerate(choices, 1):
        print(f"  {i}) {c}")
    while True:
        s = input("Выбор: ").strip()
        if s.isdigit() and 1 <= int(s) <= len(choices):
            return choices[int(s) - 1]
        print(f"  Введите число 1..{len(choices)}.")


# ---------------- данные ----------------

def load_data(engine):
    q = text(f"""
        SELECT ID, Spc, {', '.join(BASE_FEATS)}, {TARGET}
        FROM psidata
        WHERE Spc LIKE :spc AND {TARGET} IS NOT NULL
    """)
    return pd.read_sql(q, engine, params={"spc": f"%{SPC_FILTER}%"})


def diagnose(df):
    y = pd.to_numeric(df[TARGET], errors="coerce").dropna()
    print("\n=== ДИАГНОСТИКА Filtr_Freq ===")
    print(f"Всего: {len(df)}   числовых: {len(y)}")
    print(f"min={y.min():.6g}   max={y.max():.6g}")
    print("Перцентили:")
    for p in [0, .1, 1, 5, 10, 25, 50, 75, 90, 95, 99, 99.9, 100]:
        print(f"  {p:5.1f}% = {y.quantile(p/100):.6g}")
    print(f"== 0:       {int((y == 0).sum())}")
    print(f"== 1e30:    {int((y > 1e20).sum())}")
    print(f"|y| > 2000: {int((y.abs() > 2000).sum())}")

    fhz = pd.to_numeric(df["F"], errors="coerce") * pd.to_numeric(df["Nominal"], errors="coerce")
    mask = fhz.notna() & y.notna() & y.abs().between(0, 2000)
    if mask.sum() > 10:
        err = y[mask] - fhz[mask]
        print(f"\nBaseline Filtr_Freq ≈ F×Nominal (n={int(mask.sum())}):")
        print(f"  MAE  = {err.abs().mean():.4g} Гц")
        print(f"  corr = {y[mask].corr(fhz[mask]):.4f}")

    print("\nГруппы Spc:")
    for spc, n in df.groupby("Spc").size().sort_values(ascending=False).items():
        print(f"  {spc!r:40s} n={n}")


def clean(df):
    for c in BASE_FEATS + [TARGET]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=BASE_FEATS + [TARGET]).copy()
    df = df[(df["Nominal"] > 50) & (df["Nominal"] < 70)]
    df = df[df["F"].abs() < 50]
    df = df[(df["R"] > 0) & (df["Q"] > 0) & (df["L"] > 0)]
    n_before = len(df)
    df = df[df[TARGET].between(FILTR_MIN, FILTR_MAX)].copy()
    print(f"Отсечено по границам [{FILTR_MIN}, {FILTR_MAX}]: {n_before - len(df)}")
    df["Nominal_Hz"] = df["Nominal"] * 1e6
    df["F_Hz"]       = df["F"] * df["Nominal"]
    return df


# ---------------- модели ----------------

def make_mlp():
    inner = Pipeline([
        ("scaler", RobustScaler()),
        ("mlp", MLPRegressor(
            hidden_layer_sizes=(256, 128, 64, 64, 32),
            activation="relu", solver="adam",
            alpha=1e-3, learning_rate_init=1e-3,
            max_iter=3000, early_stopping=True,
            n_iter_no_change=500, validation_fraction=0.15,
            random_state=RANDOM_STATE, verbose=False,
        )),
    ])
    return TransformedTargetRegressor(regressor=inner, transformer=StandardScaler())


def make_hgb():
    return TransformedTargetRegressor(
        regressor=HistGradientBoostingRegressor(
            max_iter=1800, learning_rate=0.05, l2_regularization=1e-3,
            early_stopping=False, n_iter_no_change=500,
            random_state=RANDOM_STATE,
        ),
        transformer=StandardScaler(),
    )


def report(name, yt, yp):
    rmse = float(np.sqrt(mean_squared_error(yt, yp)))
    mae  = float(mean_absolute_error(yt, yp))
    r2   = float(r2_score(yt, yp)) if np.std(yt) > 0 else float("nan")
    print(f"  {name:<10} RMSE={rmse:10.4g} Гц  MAE={mae:10.4g} Гц  R²={r2:8.4f}")
    return {"rmse": rmse, "mae": mae, "r2": r2}


def train_one(sub: pd.DataFrame, feats: list) -> dict:
    """Обучает MLP и HGB, выбирает лучший по test MAE, возвращает bundle."""
    idx_tr, idx_te = train_test_split(sub.index, test_size=0.2, random_state=RANDOM_STATE)
    Xtr = sub.loc[idx_tr, feats].to_numpy(float)
    Xte = sub.loc[idx_te, feats].to_numpy(float)
    ytr = sub.loc[idx_tr, TARGET].to_numpy(float)
    yte = sub.loc[idx_te, TARGET].to_numpy(float)

    print("\n=== Baselines (test) ===")
    report("mean", yte, np.full_like(yte, ytr.mean()))
    if "F_Hz" in sub.columns:
        report("F_Hz", yte, sub.loc[idx_te, "F_Hz"].to_numpy(float))

    models = {"MLP": make_mlp(), "HGB": make_hgb()}
    results = {}
    for name, m in models.items():
        print(f"\n>>> Обучение {name} на {len(Xtr)} строках, {len(feats)} признаках")
        m.fit(Xtr, ytr)
        print(f"  {name}:")
        tr = report("train", ytr, m.predict(Xtr))
        te = report("test",  yte, m.predict(Xte))
        results[name] = {"train": tr, "test": te}

    best = min(results, key=lambda k: results[k]["test"]["mae"])
    print(f"\nЛучшая модель: {best} (test MAE = {results[best]['test']['mae']:.4g} Гц)")

    base_used    = [c for c in BASE_FEATS if c in feats]
    derived_used = [c for c in DERIVED    if c in feats]
    return {
        "model":         models[best],
        "name":          best,
        "features":      list(feats),
        "base_features": base_used,
        "derived":       derived_used,
        "target":        TARGET,
        "target_mode":   "raw",
        "spc":           None,           # заполним отдельно
        "n_train":       int(len(Xtr)),
        "n_test":        int(len(Xte)),
        "metrics":       results,
        "filtr_bounds":  (FILTR_MIN, FILTR_MAX),
    }


# ---------------- сценарии ----------------

def train_global(df: pd.DataFrame):
    feats = BASE_FEATS + DERIVED
    print(f"\n=== Глобальная модель: признаки {feats} ===")
    bundle = train_one(df, feats)
    bundle["spc"] = SPC_FILTER
    joblib.dump(bundle, MODEL_PATH)
    print(f"\nСохранено: {os.path.abspath(MODEL_PATH)}")


def train_per_spc(df: pd.DataFrame):
    # для per-spc убираем Nominal и Nominal_Hz — они константны внутри Spc
    feats = [c for c in BASE_FEATS if c != "Nominal"] + \
            [c for c in DERIVED    if c != "Nominal_Hz"]
    print(f"\n=== Модели по спецификациям: признаки {feats} ===")

    os.makedirs(OUT_DIR, exist_ok=True)
    index = {
        "scope":      "per-spc",
        "spc_filter": SPC_FILTER,
        "fmax":       max(abs(FILTR_MIN), abs(FILTR_MAX)),
        "target":     TARGET,
        "features":   feats,
        "backend":    "sklearn",
        "models":     {},
    }

    trained, skipped = [], []
    for spc, sub in df.groupby("Spc"):
        if len(sub) < MIN_PER_SPC:
            print(f"\n[skip] Spc={spc!r}: n={len(sub)} < {MIN_PER_SPC}")
            skipped.append(spc)
            continue
        print(f"\n=== Spc={spc!r}  (n={len(sub)}) ===")
        bundle = train_one(sub, feats)
        bundle["spc"] = spc

        tag = "spc_" + safe_name(spc)
        d = os.path.join(OUT_DIR, tag)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, "model.joblib")
        joblib.dump(bundle, path)

        index["models"][spc] = {
            "dir":      tag,
            "n_train":  bundle["n_train"],
            "n_test":   bundle["n_test"],
            "features": feats,
            "name":     bundle["name"],
            "metrics":  bundle["metrics"],
        }
        trained.append(spc)
        print(f"  → {path}")

    idx_path = os.path.join(OUT_DIR, "index.json")
    with open(idx_path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)

    print(f"\nОбучено Spc: {len(trained)}")
    if skipped:
        print(f"Пропущено (мало данных): {len(skipped)} → {skipped}")
    print(f"Индекс: {os.path.abspath(idx_path)}")


# ---------------- main ----------------

def main():
    print(f"=== Загрузка из {DB_URL.split('@')[-1]} ===")
    engine = create_engine(DB_URL, pool_pre_ping=True)
    df = load_data(engine)
    print(f"Загружено: {len(df)}")

    diagnose(df)

    if prompt_yn("\nТолько диагностика, без обучения?"):
        return

    scope = prompt_choice(
        "Что обучать?",
        ["global  — одна общая модель на все Spc",
         "per-spc — отдельная модель для каждой Spc"],
    )

    print("\n=== Чистка ===")
    df = clean(df)
    print(f"После чистки: n={len(df)}  "
          f"Filtr_Freq: min={df[TARGET].min():.4g}  max={df[TARGET].max():.4g}  "
          f"std={df[TARGET].std():.4g} Гц")
    if len(df) < 100:
        sys.exit("[ERROR] Слишком мало валидных данных")

    if scope.startswith("global"):
        train_global(df)
    else:
        train_per_spc(df)


if __name__ == "__main__":
    main()