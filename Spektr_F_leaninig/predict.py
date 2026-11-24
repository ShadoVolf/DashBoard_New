# -*- coding: utf-8 -*-
"""Интерактивный инференс Filtr_Freq: выбор моделей и сравнение."""
import json, os, sys
import numpy as np, pandas as pd
from sqlalchemy import text
import joblib

from training_common import (
    TARGET, SPC_FILTER, get_engine, find_models, prompt_yn,
    print_model_comparison, print_per_spc_comparison,
    print_coverage, save_comparison_csv,
)

GARBAGE_Y = 1e20  # порог мусора в Filtr_Freq (1e+30 и подобное)


def _uniq(name, results):
    if name not in results:
        return name
    i = 2
    while f"{name}#{i}" in results:
        i += 1
    return f"{name}#{i}"


def load_persps(model_dir):
    with open(os.path.join(model_dir, "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    for spec in index["models"].values():
        bundle = joblib.load(os.path.join(model_dir, spec["dir"], "model.joblib"))
        spec["_bundle"] = bundle
        if not spec.get("features"):
            spec["features"] = list(bundle.get("features", []))
    return index


def select_models_interactive():
    found = list(find_models())
    if not found:
        print("  [!] модели в рабочем каталоге не найдены — добавьте путь через '+'")
    while True:
        print("\n=== Доступные модели ===")
        for i, (k, p) in enumerate(found, 1):
            print(f"  {i}) [{k}] {p}")
        hint = ("Введите номера через запятую (например 1,2), "
                "Enter = все, '+' = добавить путь")
        s = input(f"\nВыбор: {hint}\n> ").strip()
        if s == "+":
            p = input("Путь (файл .joblib или каталог с index.json): ").strip()
            if p and os.path.exists(p):
                found.append(("dir" if os.path.isdir(p) else "file", os.path.abspath(p)))
            else:
                print("  [!] путь не найден")
            continue
        if not s and found:
            return found
        try:
            idx = [int(x.strip()) - 1 for x in s.split(",") if x.strip()]
            if idx and all(0 <= i < len(found) for i in idx):
                if len(idx) == 1 and len(found) > 1:
                    print(f"  [i] выбрана 1 модель из {len(found)}. "
                          f"Для сравнения — номера через запятую или Enter.")
                return [found[i] for i in idx]
        except ValueError:
            pass
        print(f"  Введите 1..{len(found)}, Enter (все) или '+' (свой путь)")


def run_predictions(models, df):
    results, dfe = {}, df.reset_index(drop=True)
    for kind, path in models:
        base = os.path.basename(path.rstrip(os.sep)) or "model"
        try:
            if kind == "dir":
                index = load_persps(path)
                fmax = float(index["fmax"])
                fallback = index["models"].get("*")
                pred = np.full(len(dfe), np.nan)
                skipped = []
                for spc, sub in dfe.groupby("Spc"):
                    spec = index["models"].get(spc) or fallback
                    if spec is None:
                        skipped.append(str(spc)); continue
                    feats = spec["features"]
                    ok = sub.dropna(subset=feats)
                    if len(ok) == 0:
                        continue
                    pred[ok.index.to_numpy()] = spec["_bundle"]["model"].predict(
                        ok[feats].to_numpy(float))
            else:
                b = joblib.load(path)
                feats = list(b.get("features", []))
                fmax = 500.0
                if "filtr_bounds" in b:
                    fmax = max(abs(b["filtr_bounds"][0]), abs(b["filtr_bounds"][1]))
                pred = np.full(len(dfe), np.nan)
                skipped = []
                ok = dfe.dropna(subset=feats) if feats else dfe
                if len(ok) > 0:
                    pred[ok.index.to_numpy()] = b["model"].predict(ok[feats].to_numpy(float))
            name = _uniq(base, results)
            results[name] = {"pred": pred, "fmax": fmax, "kind": kind,
                             "path": path, "skipped_spcs": skipped}
            n_pred = int((~np.isnan(pred)).sum())
            print(f"  + {name:<24} pred {n_pred}/{len(pred)}  fmax={fmax:g}"
                  + (f"  skip Spc={len(skipped)}" if skipped else ""))
        except Exception as e:
            print(f"  ! {path}: {e}")
    return results, dfe


def main():
    print("=== predict.py: интерактивный инференс и сравнение моделей ===")
    mode = "validate" if prompt_yn("Режим validate (с проверкой)?", default_yes=True) else "predict"
    s = input("Лимит строк (Enter = без лимита): ").strip()
    limit = int(s) if s.isdigit() else None

    models = select_models_interactive()
    if not models:
        sys.exit("[ERROR] модели не выбраны")
    print(f"\nВыбрано моделей: {len(models)}")

    # spc_filter — от первой модели
    spc_like = SPC_FILTER
    for kind, path in models:
        try:
            spc_like = (json.load(open(os.path.join(path, "index.json"), encoding="utf-8")).get("spc_filter", spc_like)
                        if kind == "dir" else joblib.load(path).get("spc", spc_like))
            break
        except Exception:
            pass

    engine = get_engine()
    if mode == "validate":
        cond = f"{TARGET} IS NOT NULL AND ABS({TARGET}) < {GARBAGE_Y:g}"
        tsel = TARGET
    else:
        cond = f"{TARGET} IS NULL"
        tsel = f"NULL AS {TARGET}"
    q = text(f"SELECT ID, Spc, F, R, Q, C0, Cq, L, Nominal, {tsel} "
             f"FROM psidata WHERE Spc LIKE :spc AND {cond}")
    df = pd.read_sql(q, engine, params={"spc": f"%{spc_like}%"})
    if limit:
        df = df.head(limit)
    print(f"Строк: {len(df)}   Spc LIKE '%{spc_like}%'   mode={mode}")
    if len(df) == 0:
        return

    for c in ["F", "R", "Q", "C0", "Cq", "L", "Nominal"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    print("\n--- Запуск предсказаний ---")
    results, dfe = run_predictions(models, df)
    if not results:
        sys.exit("[ERROR] ни одна модель не сработала")

    y = pd.to_numeric(dfe[TARGET], errors="coerce").to_numpy(float) if mode == "validate" else None

    if mode == "validate" and y is not None:
        print_coverage(dfe, results, y)
        print_model_comparison(results, y)
        print_per_spc_comparison(results, dfe, y)

    merged = save_comparison_csv(results, dfe, y, mode, f"comparison_{mode}.csv")
    with pd.option_context("display.max_columns", None, "display.width", 280):
        print("\nПервые 20 строк:")
        print(merged.head(20).to_string(index=False))


if __name__ == "__main__":
    main()