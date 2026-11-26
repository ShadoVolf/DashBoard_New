# -*- coding: utf-8 -*-
"""
Модель для малого числа измерений (2..30 на Spc):
предсказание через среднюю разницу avg(F*Nominal - Filtr_Freq).

Для каждого Spc с 2..30 измерениями:
    delta_i  = F_i*Nominal_i - Filtr_Freq_i
    mean_d   = mean(delta по train)
    pred_i   = F_i*Nominal_i - mean_d
    err_i    = Filtr_Freq_i - pred_i

Метрики (% |err| < 50 Hz) на train и test сохраняются в БД
в таблицу small_model_metrics.
"""
import os
import json
import numpy as np
from sklearn.model_selection import train_test_split
import joblib

from training_common import (
    TARGET, FILTR_MIN, FILTR_MAX, TEST_SIZE, RANDOM_STATE, DEFAULT_FMAX,
    get_engine, load_raw, clean_data, print_diag,
    report_predictions, safe_name, save_index,
    prompt_yn, prompt_float,
    save_model_metrics, make_metrics_row, dump_model_blob,
)

OUT_DIR = "models_small"
MIN_SMALL, MAX_SMALL = 2, 30


def _predict(F, Nominal, mean_delta):
    return F * Nominal - mean_delta


def train_group_small(sub, spc, out_dir):
    n = len(sub)
    print(f"\n=== Spc={spc!r}  n={n} ===")
    if n < MIN_SMALL or n > MAX_SMALL:
        print(f"[skip] n={n} вне [{MIN_SMALL},{MAX_SMALL}]")
        return None

    F    = sub["F"].to_numpy(float)
    Nom  = sub["Nominal"].to_numpy(float)
    y    = sub[TARGET].to_numpy(float)
    delta = F * Nom - y

    # train / test
    idx_tr, idx_te = train_test_split(
        np.arange(n), test_size=TEST_SIZE, random_state=RANDOM_STATE)

    mean_delta = float(np.mean(delta[idx_tr]))
    pred_tr = _predict(F[idx_tr], Nom[idx_tr], mean_delta)
    pred_te = _predict(F[idx_te], Nom[idx_te], mean_delta)

    print("Baselines:")
    report_predictions("mean_y", y, np.full_like(y, y.mean()))

    print("\n=== Метрики (delta = y - pred) ===")
    res_tr = report_predictions("small-train", y[idx_tr], pred_tr)
    res_te = report_predictions("small-test",  y[idx_te], pred_te)

    tag = "spc_" + safe_name(spc)
    d = os.path.join(out_dir, tag)
    os.makedirs(d, exist_ok=True)
    joblib.dump({
        "type":       "mean_delta",
        "spc":        spc,
        "mean_delta": mean_delta,
        "nominal":    float(np.mean(Nom)),
        "n_train":    int(len(idx_tr)),
        "n_test":     int(len(idx_te)),
        "metrics":    {"train": res_tr, "test": res_te},
    }, os.path.join(d, "model.joblib"))
    print(f"Сохранено: {d}")

    return {
        "spc":             spc,
        "nominal":         float(np.mean(Nom)),
        "model_type":      "mean_delta",
        "mean_delta":      mean_delta,
        "n_train":         int(len(idx_tr)),
        "n_test":          int(len(idx_te)),
        "pct_lt50_train":  res_tr["frac_50hz"] * 100.0,
        "pct_lt50_test":   res_te["frac_50hz"] * 100.0,
        "metrics":         {"train": res_tr, "test": res_te},
        "dir":             tag,
    }


def main():
    print("=== Small-data model (mean_delta) | n ∈ [2, 30] ===")
    engine = get_engine()
    df_raw = load_raw(engine)
    print(f"Загружено: {len(df_raw)}")
    print_diag(df_raw)

    if prompt_yn("\nТолько диагностика (без обучения)?", default_yes=False):
        return

    fmax = prompt_float(f"|{TARGET}| < fmax", DEFAULT_FMAX)
    df = clean_data(df_raw, fmax=fmax)

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"\n=== Режим: small-mean_delta  fmax={fmax:g}  "
          f"диапазон n=[{MIN_SMALL},{MAX_SMALL}] ===")

    counts   = df.groupby("Spc").size().sort_values(ascending=False)
    in_range = [(spc, n) for spc, n in counts.items()
                if MIN_SMALL <= n <= MAX_SMALL]
    print(f"\nSpc в диапазоне: {len(in_range)} из {len(counts)}")

    results = []
    for i, (spc, n) in enumerate(in_range, 1):
        print(f"\n[{i}/{len(in_range)}]")
        sub = df[df["Spc"] == spc]
        spec = train_group_small(sub, spc, OUT_DIR)
        if spec:
            results.append(spec)

    if results:
        all_rows = []
        for r in results:
            # make_metrics_row ожидает spec с ключами n_train / n_test / metrics
            spec = {
                "n_train": r["n_train"],
                "n_test": r["n_test"],
                "metrics": r["metrics"],  # {"train": res_tr, "test": res_te}
            }
            sub_spc = df[df["Spc"] == r["spc"]]
            # blob для Knowledge: kind=mean_delta (pred = F*Nominal - mean_delta)
            pack = {
                "kind": "mean_delta",
                "type": "mean_delta",
                "spc": r["spc"],
                "mean_delta": float(r["mean_delta"]),
                "nominal": float(r["nominal"]),
                "features": ["F", "Nominal"],
                "target": TARGET,
                "filtr_bounds": (FILTR_MIN, FILTR_MAX),
                "n_train": r["n_train"],
                "n_test": r["n_test"],
                "metrics": r["metrics"],
            }
            try:
                model_blob = dump_model_blob(pack)
            except Exception as e:
                print(f"  [small] dump blob failed spc={r['spc']!r}: {e}")
                model_blob = None
            row = make_metrics_row(
                spec,
                spc_key=r["spc"],
                scope="small",
                sub=sub_spc,
                fmax=fmax,
                backend="small",  # → model_type = "small"
                model_blob=model_blob,
                features=["F", "Nominal"],
            )
            # mean_delta кладём в extra как JSON (полезно для анализа)
            row["extra"] = json.dumps(
                {"mean_delta": r["mean_delta"], "kind": "mean_delta"},
                ensure_ascii=False,
            )
            all_rows.append(row)

        save_model_metrics(engine, all_rows)  # <-- общая таблица model_metrics
        print(f"\nОбработано Spc: {len(results)}")

    index = {
        "model_type": "mean_delta",
        "min_small": MIN_SMALL,
        "max_small": MAX_SMALL,
        "fmax": fmax,
        "db_table": "model_metrics",  # <-- было: SMALL_METRICS_TABLE
        "models": {r["spc"]: r for r in results},
    }
    save_index(os.path.join(OUT_DIR, "index.json"), index)



if __name__ == "__main__":
    main()