# -*- coding: utf-8 -*-
"""
Общие утилиты для всех training-скриптов (sklearn / TF / Torch):
единый интерактив, единая очистка, единые метрики на остатках.
"""
import re
import numpy as np, pandas as pd
from sqlalchemy import create_engine, text
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

DB_URL     = "mysql+mysqlconnector://xampp:43FPa!29S8HQeAW@MES1:3306/coordinator"
SPC_FILTER = "РК731"
TARGET     = "Filtr_Freq"

# --- наборы признаков ---
PERSPS_FEATS    = ["F", "R", "Q", "C0", "Cq"]
GLOBAL_NO_NOM   = ["F", "R", "Q", "C0", "Cq"]
GLOBAL_WITH_NOM = ["F", "R", "Q", "C0", "Cq", "Nominal"]

DEFAULT_FMAX         = 500.0
FILTR_MIN, FILTR_MAX = -500.0, 500.0

# --- границы фильтрации (единые для всех) ---
NOMINAL_RANGE = (50.0, 70.0)   # МГц
F_RANGE       = (-50.0, 50.0)  # ppm
IQR_MULT      = 3.0            # мягкое удаление выбросов таргета

# --- пороги обучения ---
MIN_PER_SPC  = 30
MIN_TRAIN    = 20
TEST_SIZE    = 0.2
RANDOM_STATE = 42


# ---------------- интерактив ----------------

def prompt_yn(label, default_yes=False):
    s_default = "д/н" if not default_yes else "Д/н"
    while True:
        s = input(f"{label} ({s_default}): ").strip().lower()
        if s == "":
            return default_yes
        if s in ("д", "да", "y", "yes"):
            return True
        if s in ("н", "нет", "n", "no"):
            return False
        print("  Введите 'д' или 'н'.")


def prompt_choice(label, choices):
    print(f"\n{label}")
    for i, c in enumerate(choices, 1):
        print(f"  {i}) {c}")
    while True:
        s = input("Выбор: ").strip()
        if s.isdigit() and 1 <= int(s) <= len(choices):
            return int(s)
        print(f"  Введите число 1..{len(choices)}.")


def prompt_float(label, default):
    s = input(f"{label} [Enter = {default:g}]: ").strip()
    if not s:
        return float(default)
    try:
        return float(s)
    except ValueError:
        print(f"  Не число, беру {default:g}")
        return float(default)


# ---------------- БД ----------------

def get_engine():
    return create_engine(DB_URL, pool_pre_ping=True)


def load_raw(engine):
    q = text(f"""
        SELECT ID, Spc, F, R, Q, C0, Cq, L, Nominal, {TARGET}
        FROM psidata
        WHERE Spc LIKE :spc AND {TARGET} IS NOT NULL
    """)
    return pd.read_sql(q, engine, params={"spc": f"%{SPC_FILTER}%"})


# ---------------- единая очистка ----------------

def clean_data(df, fmax=DEFAULT_FMAX, verbose=True):
    """Агрессивная фильтрация: dropna → физические границы → IQR."""
    log, n0 = [], len(df)
    df = df.copy()

    num_cols = ["F", "R", "Q", "C0", "Cq", "L", "Nominal", TARGET]
    for c in num_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=num_cols)
    log.append(("dropna ключевых", n0 - len(df)))
    n = len(df)

    df = df[df["Nominal"].between(*NOMINAL_RANGE)]
    log.append((f"Nominal {NOMINAL_RANGE}", n - len(df)))
    n = len(df)

    df = df[df["F"].between(*F_RANGE)]
    log.append((f"F {F_RANGE}", n - len(df)))
    n = len(df)

    pos_mask = (df[["R", "Q", "C0", "Cq", "L"]] > 0).all(axis=1)
    df = df[pos_mask]
    log.append(("R,Q,C0,Cq,L > 0", n - len(df)))
    n = len(df)

    df = df[(df[TARGET] >= FILTR_MIN) & (df[TARGET] <= FILTR_MAX) & (df[TARGET].abs() < fmax)]
    log.append((f"|{TARGET}| < {fmax}", n - len(df)))
    n = len(df)

    if IQR_MULT > 0 and len(df) > 20:
        q1, q3 = df[TARGET].quantile([0.25, 0.75])
        iqr = q3 - q1
        if iqr > 0:
            lo, hi = q1 - IQR_MULT * iqr, q3 + IQR_MULT * iqr
            df = df[df[TARGET].between(lo, hi)]
            log.append((f"IQR {IQR_MULT}×", n - len(df)))

    if verbose:
        print("\n=== Очистка данных ===")
        print(f"  Исходно: {n0}")
        for lbl, k in log:
            if k > 0:
                print(f"  - {lbl:<25} убрано {k}")
        print(f"  Осталось: {len(df)}")
    return df.copy()


# ---------------- признаки ----------------

def get_features(scope):
    if scope == "per-spc":        return list(PERSPS_FEATS)
    if scope == "global_no_nom":  return list(GLOBAL_NO_NOM)
    if scope == "global_with_nom":return list(GLOBAL_WITH_NOM)
    raise ValueError(scope)


# ---------------- интерактивный старт ----------------

def interactive_setup():
    """Общий интерактив — вызывается в каждом train_*.py."""
    if prompt_yn("\nТолько диагностика (без обучения)?", default_yes=False):
        return {"diagnose_only": True}

    idx = prompt_choice(
        "Что обучать?",
        [
            "global без Nominal (F, R, Q, C0, Cq)",
            "global с Nominal  (F, R, Q, C0, Cq, Nominal)",
            "per-spc           (F, R, Q, C0, Cq)",
        ]
    )
    scope = ["global_no_nom", "global_with_nom", "per-spc"][idx - 1]

    fmax = prompt_float(f"|{TARGET}| < fmax", DEFAULT_FMAX)
    auto = prompt_yn("Автоподбор гиперпараметров?", default_yes=False)

    return {"diagnose_only": False, "scope": scope, "fmax": fmax, "auto_search": auto}


# ---------------- диагностика ----------------

def print_diag(df):
    print(f"\n=== Диагностика {TARGET} ===")
    print(f"Всего строк: {len(df)}")
    y = pd.to_numeric(df[TARGET], errors="coerce").dropna()
    print(f"Числовых: {len(y)}")
    if len(y) == 0:
        print("  нет числовых значений!")
        return
    print(f"min={y.min():.6g}  max={y.max():.6g}  std={y.std():.4g}")
    print("Перцентили:")
    for p in [0, .1, 1, 5, 10, 25, 50, 75, 90, 95, 99, 99.9, 100]:
        print(f"  {p:5.1f}% = {y.quantile(p/100):.6g}")
    print(f"==0: {int((y == 0).sum())}  |y|>1e20: {int((y.abs() > 1e20).sum())}")
    print("\nГруппы Spc:")
    for spc, n in df.groupby("Spc").size().sort_values(ascending=False).items():
        print(f"  {spc!r:40s} n={n}")


# ---------------- метрики ----------------

def report_predictions(name, yt, yp, print_row=True):
    """Метрика delta = yt - yp: bias, std, MAE, RMSE, R², p90/p95, доля <10/<50 Гц."""
    err = yt - yp
    r = {
        "n":         int(len(yt)),
        "rmse":      float(np.sqrt(mean_squared_error(yt, yp))),
        "mae":       float(mean_absolute_error(yt, yp)),
        "r2":        float(r2_score(yt, yp)) if np.std(yt) > 0 else float("nan"),
        "bias":      float(err.mean()),
        "std_res":   float(err.std()),
        "max_abs":   float(np.max(np.abs(err))) if len(err) else float("nan"),
        "p90_abs":   float(np.percentile(np.abs(err), 90)) if len(err) else float("nan"),
        "p95_abs":   float(np.percentile(np.abs(err), 95)) if len(err) else float("nan"),
        "frac_10hz": float((np.abs(err) < 10).mean()) if len(err) else float("nan"),
        "frac_50hz": float((np.abs(err) < 50).mean()) if len(err) else float("nan"),
    }
    if print_row:
        print(f"  {name:<12} n={r['n']:<6} "
              f"RMSE={r['rmse']:9.4g}  MAE={r['mae']:9.4g}  R²={r['r2']:7.4f}  "
              f"bias={r['bias']:+8.3g}  "
              f"|e|p90={r['p90_abs']:8.3g}  |e|p95={r['p95_abs']:8.3g}  "
              f"<10Hz={r['frac_10hz']*100:4.0f}%  <50Hz={r['frac_50hz']*100:4.0f}%")
    return r


def safe_name(s):
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", s).strip("_") or "empty"


def save_index(path, index):
    import json, os
    with open(path, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"\nИндекс: {os.path.abspath(path)}")


# ---------------- интерактив: выбор моделей ----------------

def prompt_path(label, default=None):
    d = f" [Enter = {default}]" if default else ""
    s = input(f"{label}{d}: ").strip()
    return s or default


def find_models(search_dir="."):
    """Сканирует каталог: *.joblib (global) и */index.json (per-spc)."""
    import glob, os
    found = []
    for f in sorted(glob.glob(os.path.join(search_dir, "*.joblib"))):
        found.append(("file", os.path.abspath(f)))
    for f in sorted(glob.glob(os.path.join(search_dir, "*/index.json"))):
        found.append(("dir", os.path.abspath(os.path.dirname(f))))
    return found


# ---------------- сравнение моделей ----------------

def per_model_metrics(results, y):
    """
    results: dict name -> {"pred": np.ndarray, "fmax": float}
    y: np.ndarray (validate) или None.
    """
    out = []
    for name, r in results.items():
        pred, fmax = r["pred"], r["fmax"]
        if y is None:
            ok = ~np.isnan(pred)
        else:
            ok = (~np.isnan(y)) & (~np.isnan(pred)) & (np.abs(y) <= fmax)
        n = int(ok.sum())
        item = {"name": name, "n": n}
        if n < 2 or y is None:
            out.append(item); continue
        yt, yp = y[ok], pred[ok]
        err = yt - yp
        item.update({
            "rmse": float(np.sqrt(mean_squared_error(yt, yp))),
            "mae":  float(mean_absolute_error(yt, yp)),
            "r2":   float(r2_score(yt, yp)) if np.std(yt) > 0 else float("nan"),
            "bias": float(err.mean()),
            "p90":  float(np.percentile(np.abs(err), 90)),
            "p95":  float(np.percentile(np.abs(err), 95)),
        })
        out.append(item)
    return out


def print_model_comparison(results, y):
    print("\n" + "=" * 112)
    print("=== Сравнение моделей (delta = y - pred) ===")
    print(f"{'#':<3} {'model':<28} {'n':>7} {'RMSE':>10} {'MAE':>10} {'R²':>8} "
          f"{'bias':>10} {'|e|p90':>10} {'|e|p95':>10}")
    print("-" * 112)
    rows = per_model_metrics(results, y)
    best = None
    for i, m in enumerate(rows, 1):
        if m["n"] < 2 or "mae" not in m:
            print(f"{i:<3} {m['name'][:28]:<28} {m['n']:>7}  (мало данных)")
            continue
        if best is None or m["mae"] < best["mae"]:
            best = m
        print(f"{i:<3} {m['name'][:28]:<28} {m['n']:>7} {m['rmse']:>10.4g} "
              f"{m['mae']:>10.4g} {m['r2']:>8.4f} {m['bias']:>+10.3g} "
              f"{m['p90']:>10.3g} {m['p95']:>10.3g}")
    print("=" * 112)
    if best:
        print(f"[best] {best['name']}  MAE={best['mae']:.4g}  "
              f"RMSE={best['rmse']:.4g}  R²={best['r2']:.4f}")
    return rows


def print_per_spc_comparison(results, dfe, y, spc_col="Spc"):
    if len(results) < 2 or y is None:
        return
    names = list(results.keys())
    spcs = sorted(dfe[spc_col].astype(str).unique())
    if len(spcs) < 2:
        return
    print("\n=== По Spc: MAE каждой модели (меньше = лучше) ===")
    head = f"{'Spc':<22} {'n':>5}  " + "  ".join(f"{n[:16]:>16}" for n in names)
    print(head)
    print("-" * len(head))
    for spc in spcs:
        mask_spc = (dfe[spc_col].astype(str) == spc).to_numpy()
        if mask_spc.sum() < 2:
            continue
        line = f"{spc:<22} {int(mask_spc.sum()):>5}  "
        best = None
        for name in names:
            r = results[name]
            ok = (mask_spc & (~np.isnan(y)) & (~np.isnan(r["pred"]))
                  & (np.abs(y) <= r["fmax"]))
            if ok.sum() < 2:
                line += f"  {'—':>16}"
                continue
            mae = mean_absolute_error(y[ok], r["pred"][ok])
            if best is None or mae < best[0]:
                best = (mae, name)
            line += f"  {mae:>16.4g}"
        if best:
            line += f"  <- {best[1]}"
        print(line)


def save_comparison_csv(results, dfe, y, mode, out_path):
    import os, pandas as pd
    base_cols = [c for c in ["ID", "Spc", "F", "R", "Q", "C0", "Cq", "L", "Nominal"]
                 if c in dfe.columns]
    merged = dfe[base_cols].copy()
    if mode == "validate" and y is not None:
        merged[TARGET] = y
    for name, r in results.items():
        safe = "".join(c if (c.isalnum() or c in "._-") else "_" for c in name) or "model"
        merged[f"pred_{safe}"] = r["pred"]
        if mode == "validate" and y is not None:
            merged[f"err_{safe}"] = y - r["pred"]
    merged.to_csv(out_path, index=False, encoding="utf-8-sig")
    print(f"\nСохранено: {os.path.abspath(out_path)}")
    return merged

def print_coverage(dfe, results, y=None, top=25):
    """
    Покрытие предсказаний по Spc: rows / y_ok / pred_<model> для каждой Spc.
    Работает и для per-spc (skipped_spcs), и для global (n_no_model/no_no_feats).
    """
    if not results:
        return
    names = list(results.keys())

    print("\n=== Покрытие предсказаний по Spc ===")
    head = f"{'Spc':<28} {'rows':>6} {'y_ok':>6}  " + \
           "  ".join(f"{n[:16]:>16}" for n in names)
    print(head)
    print("-" * len(head))

    rows = []
    for spc, sub in dfe.groupby("Spc"):
        idx = sub.index.to_numpy()
        r = {"spc": str(spc), "rows": len(idx), "y_ok": 0, "pred": {}}
        if y is not None:
            ysub = y[idx]
            ok = ~np.isnan(ysub)
            for res in results.values():
                ok &= (np.abs(ysub) <= res["fmax"])
            r["y_ok"] = int(ok.sum())
        for name, res in results.items():
            r["pred"][name] = int((~np.isnan(res["pred"][idx])).sum())
        rows.append(r)

    # сначала проблемные Spc: где меньше всего покрытия
    rows.sort(key=lambda r: (r["rows"] - sum(r["pred"].values()) / max(len(names), 1)),
              reverse=True)

    for r in rows[:top]:
        line = f"{r['spc'][:28]:<28} {r['rows']:>6} {r['y_ok']:>6}  "
        for n in names:
            p = r["pred"][n]
            flag = "" if p == r["rows"] else (" !" if p == 0 else " ~")
            line += f"  {p:>6}/{r['rows']:<6}{flag:<3}"
        print(line)
    if len(rows) > top:
        print(f"  ... и ещё {len(rows) - top} Spc")

    total_rows = sum(r["rows"] for r in rows)
    print(f"\n  Всего Spc: {len(rows)}, строк: {total_rows}")
    for name, res in results.items():
        n_pred = int((~np.isnan(res["pred"])).sum())
        line = f"  {name:<24} pred={n_pred}/{total_rows}  fmax={res['fmax']:g}"
        # per-spc (predict.py) → skipped_spcs; global (predict_multi.py) → n_no_model
        if res.get("n_no_model") is not None:
            line += f"  no_model={res['n_no_model']}  no_feats={res.get('n_no_feats', 0)}"
        elif res.get("skipped_spcs"):
            line += f"  skip Spc={len(res['skipped_spcs'])}"
        print(line)

# ---------------- малые модели: сохранение в БД ----------------

SMALL_METRICS_TABLE = "small_model_metrics"


def ensure_small_metrics_table(engine, table=SMALL_METRICS_TABLE):
    """Создаёт таблицу для метрик малых моделей, если её нет."""
    ddl = text(f"""
        CREATE TABLE IF NOT EXISTS {table} (
            id INT AUTO_INCREMENT PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            nominal DOUBLE NULL,
            spc VARCHAR(255) NULL,
            model_type VARCHAR(64) NULL,
            pct_lt50_train DOUBLE NULL,
            pct_lt50_test DOUBLE NULL,
            n_train INT NULL,
            n_test INT NULL,
            mean_delta DOUBLE NULL
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """)
    with engine.begin() as conn:
        conn.execute(ddl)


def save_small_model_metrics(engine, rows, table=SMALL_METRICS_TABLE):
    """
    rows: список dict'ов, каждый должен содержать ключи:
          nominal, spc, model_type, pct_lt50_train, pct_lt50_test,
          n_train, n_test, mean_delta
    """
    if not rows:
        print("  [db] нет строк для записи")
        return
    ensure_small_metrics_table(engine, table)
    df = pd.DataFrame(rows)
    keep = ("nominal", "spc", "model_type", "pct_lt50_train", "pct_lt50_test",
            "n_train", "n_test", "mean_delta")
    df = df[[c for c in keep if c in df.columns]]
    df.to_sql(table, engine, if_exists="append", index=False)
    print(f"  [db] записано в {table}: {len(df)} строк")

    # ---------------- метрики моделей: сохранение в БД ----------------


MODEL_METRICS_TABLE = "model_metrics"


def ensure_model_metrics_table(engine, table=MODEL_METRICS_TABLE):
    """Создаёт общую таблицу метрик всех моделей, если её нет."""
    ddl = text(f"""
         CREATE TABLE IF NOT EXISTS {table} (
             id INT AUTO_INCREMENT PRIMARY KEY,
             created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
             scope VARCHAR(32) NULL,
             spc VARCHAR(255) NULL,
             nominal DOUBLE NULL,
             backend VARCHAR(32) NULL,
             model_type VARCHAR(64) NULL,
             n_train INT NULL,
             n_test INT NULL,
             pct_lt50_train DOUBLE NULL,
             pct_lt50_test DOUBLE NULL,
             mae_train DOUBLE NULL,
             mae_test DOUBLE NULL,
             rmse_train DOUBLE NULL,
             rmse_test DOUBLE NULL,
             fmax DOUBLE NULL,
             extra TEXT NULL
         ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
     """)
    with engine.begin() as conn:
        conn.execute(ddl)


def save_model_metrics(engine, rows, table=MODEL_METRICS_TABLE):
    """rows: список dict'ов; недостающие колонки заполняются NULL."""
    if not rows:
        print(f"  [db] нет строк для записи в {table}")
        return
    ensure_model_metrics_table(engine, table)
    df = pd.DataFrame(rows)
    cols = ("scope", "spc", "nominal", "backend", "model_type",
            "n_train", "n_test", "pct_lt50_train", "pct_lt50_test",
            "mae_train", "mae_test", "rmse_train", "rmse_test",
            "fmax", "extra")
    for c in cols:
        if c not in df.columns:
            df[c] = None
    df = df[list(cols)]
    df.to_sql(table, engine, if_exists="append", index=False)
    print(f"  [db] записано в {table}: {len(df)} строк")


def make_metrics_row(spec, spc_key, scope, sub, fmax, backend):
    """
    Универсальный конструктор строки для model_metrics.
    spec  — то, что вернул train_group();
            sklearn: {"metrics": {"mlp": {"train","test"}, "hgb": {...}}, "best": ...}
            TF/torch: {"metrics": {"train","test"}, ...}
    spc_key — "*" для global, иначе имя Spc;
    sub     — DataFrame этой группы (для среднего Nominal);
    """
    m = spec["metrics"]
    best = spec.get("best")
    if best is not None and best in m:
        tr, te = m[best]["train"], m[best]["test"]
        model_type = f"{backend}_{best}"
    else:
        tr, te = m["train"], m["test"]
        model_type = backend

    nominal = None
    if sub is not None and "Nominal" in getattr(sub, "columns", []):
        if len(sub):
            nominal = float(sub["Nominal"].mean())

    return {
        "scope": scope,
        "spc": str(spc_key),
        "nominal": nominal,
        "backend": backend,
        "model_type": model_type,
        "n_train": int(spec["n_train"]),
        "n_test": int(spec["n_test"]),
        "pct_lt50_train": float(tr["frac_50hz"]) * 100.0,
        "pct_lt50_test": float(te["frac_50hz"]) * 100.0,
        "mae_train": float(tr["mae"]),
        "mae_test": float(te["mae"]),
        "rmse_train": float(tr["rmse"]),
        "rmse_test": float(te["rmse"]),
        "fmax": float(fmax),
        "extra": None,
    }

# ============================================================================
#  Метрики моделей: сохранение в БД (единая таблица для всех бэкендов)
# ============================================================================

MODEL_METRICS_TABLE = "model_metrics"


