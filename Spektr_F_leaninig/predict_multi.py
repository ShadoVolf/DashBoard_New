# -*- coding: utf-8 -*-
"""
Интерактивный инференс per-spc моделей Filtr_Freq.
Возможности:
- выбор каталогов с index.json;
- OOD-фильтр по границам clean_data (опционально);
- клиппинг предсказаний в [FILTR_MIN, FILTR_MAX];
- сравнение выбранных моделей (общая таблица + по Spc);
- покрытие по Spc (модель/фичи/OOD/pred);
- топ-N худших ошибок;
- единый CSV со всеми предсказаниями.
"""
import glob, json, os, sys
import numpy as np, pandas as pd
from sqlalchemy import text
import joblib

from training_common import (
    TARGET, SPC_FILTER, FILTR_MIN, FILTR_MAX,
    NOMINAL_RANGE, F_RANGE,
    get_engine, prompt_yn,
    print_model_comparison, print_per_spc_comparison,
    save_comparison_csv,
)

GARBAGE_Y = 1e20


# ---------------- вспомогательное ----------------

def _uniq(name, results):
    if name not in results:
        return name
    i = 2
    while f"{name}#{i}" in results:
        i += 1
    return f"{name}#{i}"


def find_per_spc_dirs(search_dir="."):
    found = []
    for f in sorted(glob.glob(os.path.join(search_dir, "*/index.json"))):
        d = os.path.abspath(os.path.dirname(f))
        try:
            with open(f, encoding="utf-8") as fh:
                idx = json.load(fh)
            if (idx.get("scope", "").startswith("per-spc")
                    or any(k != "*" for k in idx.get("models", {}))):
                found.append(d)
        except Exception:
            found.append(d)
    return found


def load_persps(model_dir):
    with open(os.path.join(model_dir, "index.json"), encoding="utf-8") as f:
        index = json.load(f)
    for spec in index["models"].values():
        bundle = joblib.load(os.path.join(model_dir, spec["dir"], "model.joblib"))
        spec["_bundle"] = bundle
        if not spec.get("features"):
            spec["features"] = list(bundle.get("features", []))
    return index


# ---------------- интерактив ----------------

def select_models_interactive():
    found = [("dir", d) for d in find_per_spc_dirs()]
    if not found:
        print("  [!] per-spc моделей не найдено — добавьте путь через '+'")
    while True:
        print("\n=== Доступные per-spc модели ===")
        for i, (k, p) in enumerate(found, 1):
            print(f"  {i}) {p}")
        print("\nНомера через запятую (например 1,2), Enter = все, '+' = добавить путь")
        s = input("Выбор: ").strip()
        if s == "+":
            p = input("Путь к каталогу с index.json: ").strip()
            if p and os.path.isdir(p) and os.path.exists(os.path.join(p, "index.json")):
                found.append(("dir", os.path.abspath(p)))
            else:
                print("  [!] каталог не найден или нет index.json")
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


# ---------------- OOD-фильтр (те же границы, что в clean_data) ----------------

def apply_ood_filter(df):
    """Оставляет только строки, которые модель видела на train по границам признаков."""
    n0 = len(df)
    df = df.copy()
    df = df[df["Nominal"].between(*NOMINAL_RANGE) | df["Nominal"].isna()]
    df = df[df["F"].between(*F_RANGE) | df["F"].isna()]
    pos_cols = [c for c in ["R", "Q", "C0", "Cq"] if c in df.columns]
    if pos_cols:
        df = df[~((df[pos_cols] <= 0).any(axis=1))]
    return df.reset_index(drop=True), {"n_in": n0, "n_out": len(df), "dropped": n0 - len(df)}


# ---------------- предсказания ----------------

def run_predictions(models, df):
    results, dfe = {}, df.reset_index(drop=True)
    for kind, path in models:
        base = os.path.basename(path.rstrip(os.sep)) or "model"
        try:
            index = load_persps(path)
            fmax = float(index["fmax"])
            fallback = index["models"].get("*")
            pred = np.full(len(dfe), np.nan)
            n_no_model = 0
            n_no_feats = 0
            for spc, sub in dfe.groupby("Spc"):
                spec = index["models"].get(spc) or fallback
                if spec is None:
                    n_no_model += len(sub)
                    continue
                feats = spec["features"]
                ok = sub.dropna(subset=feats)
                n_no_feats += len(sub) - len(ok)
                if len(ok) == 0:
                    continue
                raw = spec["_bundle"]["model"].predict(ok[feats].to_numpy(float))
                # клиппинг: модель не может выйти за тренировочные границы таргета
                pred[ok.index.to_numpy()] = np.clip(raw, FILTR_MIN, FILTR_MAX)

            name = _uniq(base, results)
            results[name] = {
                "pred": pred, "fmax": fmax, "path": path,
                "n_no_model": n_no_model, "n_no_feats": n_no_feats,
            }
            n_pred = int((~np.isnan(pred)).sum())
            print(f"  + {name:<24} pred {n_pred}/{len(pred)}  fmax={fmax:g}  "
                  f"no_model={n_no_model}  no_feats={n_no_feats}")
        except Exception as e:
            print(f"  ! {path}: {e}")
    return results, dfe


# ---------------- покрытие ----------------

def print_coverage(dfe, results, y, top=25):
    if not results:
        return
    names = list(results.keys())
    print("\n=== Покрытие по Spc ===")
    head = f"{'Spc':<28} {'rows':>6} {'y_ok':>6}"
    for n in names:
        head += f"  {n[:16]:>22}"
    print(head)
    print("-" * len(head))

    rows = []
    for spc, sub in dfe.groupby("Spc"):
        idx = sub.index.to_numpy()
        r = {"spc": str(spc), "rows": len(idx), "y_ok": 0, "pred": {}}
        if y is not None:
            ysub = y[idx]
            m = ~np.isnan(ysub)
            for name, res in results.items():
                m &= (np.abs(ysub) <= res["fmax"])
            r["y_ok"] = int(m.sum())
        for name, res in results.items():
            r["pred"][name] = int((~np.isnan(res["pred"][idx])).sum())
        rows.append(r)

    # сначала проблемные
    rows.sort(key=lambda r: (r["rows"] - sum(r["pred"].values()) / max(len(names), 1)),
              reverse=True)
    for r in rows[:top]:
        line = f"{r['spc'][:28]:<28} {r['rows']:>6} {r['y_ok']:>6}"
        for n in names:
            p = r["pred"][n]
            mark = "" if p == r["rows"] else (" !" if p == 0 else " ~")
            line += f"  {p:>6}/{r['rows']:<6}{mark:<8}"
        print(line)
    if len(rows) > top:
        print(f"  ... и ещё {len(rows) - top} Spc")

    print(f"\n  Всего Spc: {len(rows)}, строк: {sum(r['rows'] for r in rows)}")
    for name, res in results.items():
        n_pred = int((~np.isnan(res["pred"])).sum())
        print(f"  {name:<24} pred={n_pred}  no_model={res['n_no_model']}  "
              f"no_feats={res['n_no_feats']}")


def print_worst_errors(dfe, results, y, top=15):
    if y is None or not results:
        return
    # берём модель с наименьшей MAE
    scored = [(float(np.mean(np.abs(
        y[(~np.isnan(y)) & (~np.isnan(r["pred"]))] -
        r["pred"][(~np.isnan(y)) & (~np.isnan(r["pred"]))]
    ))), name) for name, r in results.items()
        if ((~np.isnan(y)) & (~np.isnan(r["pred"]))).sum() > 0]
    if not scored:
        return
    _, name = min(scored)
    r = results[name]
    ok = (~np.isnan(y)) & (~np.isnan(r["pred"])) & (np.abs(y) <= r["fmax"])
    if ok.sum() < 2:
        return
    err = np.abs(y[ok] - r["pred"][ok])
    order = np.argsort(err)[-top:][::-1]
    orig = np.where(ok)[0][order]
    print(f"\n=== Топ-{top} худших ошибок: {name} ===")
    for j in orig:
        row = dfe.iloc[j]
        print(f"  Spc={str(row['Spc'])[:22]:<22} "
              f"F={row['F']:>7.3g} R={row['R']:>7.3g} Q={row['Q']:>7.3g} "
              f"C0={row['C0']:>6.3g} Cq={row['Cq']:>6.3g} "
              f"| y={y[j]:>9.4g}  pred={r['pred'][j]:>9.4g}  "
              f"err={y[j]-r['pred'][j]:>+9.4g}")


# ---------------- main ----------------

def main():
    print("=== predict_multi.py: интерактивный инференс и сравнение (per-spc) ===")
    mode = "validate" if prompt_yn("Режим validate (с проверкой)?", default_yes=True) else "predict"
    s = input("Лимит строк (Enter = без лимита): ").strip()
    limit = int(s) if s.isdigit() else None
    apply_ood = prompt_yn(
        f"Применять OOD-фильтр (Nominal∈{NOMINAL_RANGE}, F∈{F_RANGE}, R,Q,C0,Cq>0)?",
        default_yes=True,
    )

    models = select_models_interactive()
    if not models:
        sys.exit("[ERROR] модели не выбраны")
    print(f"\nВыбрано моделей: {len(models)}")

    spc_like = SPC_FILTER
    for kind, path in models:
        try:
            with open(os.path.join(path, "index.json"), encoding="utf-8") as f:
                spc_like = json.load(f).get("spc_filter", spc_like)
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
    print(f"Строк из БД: {len(df)}   Spc LIKE '%{spc_like}%'   mode={mode}")
    if len(df) == 0:
        return

    for c in ["F", "R", "Q", "C0", "Cq", "L", "Nominal"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    if apply_ood:
        df, ood_stats = apply_ood_filter(df)
        print(f"OOD-фильтр: {ood_stats['n_in']} → {ood_stats['n_out']} "
              f"(отброшено {ood_stats['dropped']})")
        if len(df) == 0:
            print("[!] после OOD-фильтра не осталось строк — попробуйте без него")
            return

    print("\n--- Запуск предсказаний ---")
    results, dfe = run_predictions(models, df)
    if not results:
        sys.exit("[ERROR] ни одна модель не сработала")

    y = (pd.to_numeric(dfe[TARGET], errors="coerce").to_numpy(float)
         if mode == "validate" else None)

    if mode == "validate" and y is not None:
        print_coverage(dfe, results, y)
        print_model_comparison(results, y)
        print_per_spc_comparison(results, dfe, y)
        print_worst_errors(dfe, results, y, top=15)

    merged = save_comparison_csv(results, dfe, y, mode,
                                 f"comparison_multi_{mode}.csv")
    with pd.option_context("display.max_columns", None, "display.width", 280):
        print("\nПервые 20 строк:")
        print(merged.head(20).to_string(index=False))


if __name__ == "__main__":
    main()