"""
Aktivnoe obuchenie TOC.

Obrazcy:  <cwd>/TOC_Learning/samples.json
  (analogichno Options.get_measure_protokol_path() dlya "Protokoly")

Modeli:
  - tip Kind='toc_if' v tablice virtual_nn_models (ryadom s mlp/ae)
  - flag Finetuned=1 v Meta, Active=1
  - pri nalichii ispolzuetsya doobuchennaya model' (IsolationForest)

mlp/ae - Virtual_Measure; toc_if - TempOutlier_Correction.
"""

from __future__ import annotations

import io
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

# ---- Kind v virtual_nn_models (otdel'no ot mlp / ae) ----
KIND_TOC_IF = "toc_if"

_models: Dict[str, Any] = {}  # param -> sklearn model
_engine = None
_table_ready = False


def _cwd() -> Path:
    """Direktoriya zapuska (ne put' k paketu)."""
    try:
        return Path(os.getcwd()).resolve()
    except Exception:
        return Path(".").resolve()


def learning_dir() -> Path:
    """
    <cwd>/TOC_Learning — kak Protokoly cherez Options.get_measure_protokol_path().
    Esli Options.daet put' k protokolam — kladyom ryadom.
    """
    base = None
    try:
        import Options
        if hasattr(Options, "get_measure_protokol_path"):
            proto = Options.get_measure_protokol_path()
            if proto:
                # parent of Protokoly or the path itself
                p = Path(str(proto)).resolve()
                # put TOC_Learning next to Protokoly folder
                if p.name.lower() in ("protokoly", "protocols", "протокол", "протоколы"):
                    base = p.parent / "TOC_Learning"
                else:
                    base = p.parent / "TOC_Learning"
    except Exception:
        pass
    if base is None:
        base = _cwd() / "TOC_Learning"
    return base


def samples_path() -> Path:
    return learning_dir() / "samples.json"


def _ensure_dir() -> Path:
    d = learning_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_samples() -> List[Dict[str, Any]]:
    _ensure_dir()
    fp = samples_path()
    if not fp.exists():
        return []
    try:
        return json.loads(fp.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[TOC] load_samples: {e}", flush=True)
        return []


def save_samples(samples: List[Dict[str, Any]]) -> None:
    _ensure_dir()
    samples_path().write_text(
        json.dumps(samples, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_training_sample(
    number: str,
    points: List[Dict[str, Any]],
    param: str = "F",
    label: str = "corrected",
) -> int:
    samples = load_samples()
    samples.append({
        "number": str(number),
        "param": param,
        "label": label,
        "points": points,
        "added_at": datetime.now().isoformat(timespec="seconds"),
    })
    save_samples(samples)
    print(f"[TOC] sample -> {samples_path()} (n={len(samples)})", flush=True)
    return len(samples)


def samples_count() -> int:
    return len(load_samples())


# ---------------------------------------------------------------------------
# DB: virtual_nn_models, Kind = toc_if  (mlp / ae ostayutsya)
# ---------------------------------------------------------------------------

def _get_engine():
    global _engine
    if _engine is not None:
        return _engine if _engine is not False else None
    try:
        from Options import get_connection_string
        from sqlalchemy import create_engine
        _engine = create_engine(
            str(get_connection_string()),
            pool_pre_ping=True,
            future=True,
        )
        return _engine
    except Exception as e:
        print(f"[TOC] engine: {e}", flush=True)
        _engine = False
        return None


def _ensure_table(eng) -> bool:
    """
    virtual_nn_models kak v Virtual_NN + kolonka Active (esli net).
    Kind: mlp | ae | toc_if
    """
    global _table_ready
    if _table_ready:
        return True
    if eng is None:
        return False
    try:
        from sqlalchemy import text
        ddl = (
            "CREATE TABLE IF NOT EXISTS `virtual_nn_models` ("
            "`ID` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
            "`Kind` VARCHAR(16) NOT NULL,"
            "`Rtype` VARCHAR(255) NOT NULL DEFAULT '',"
            "`Data` LONGBLOB NOT NULL,"
            "`Meta` VARCHAR(2048) DEFAULT NULL,"
            "`TrainedAt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "`Size` INT UNSIGNED DEFAULT 0,"
            "PRIMARY KEY (`ID`),"
            "UNIQUE KEY `uq_kind_rtype` (`Kind`, `Rtype`)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        with eng.begin() as conn:
            conn.execute(text(ddl))
        _table_ready = True
        return True
    except Exception as e:
        print(f"[TOC] ensure table: {e}", flush=True)
        return False


def _param_tag(param: str) -> str:
    """Rtype field ispolzuem kak tag parametra: F / R / ..."""
    return f"toc::{(param or 'F').upper()}"


def save_model_to_db(param: str, blob: bytes, meta: dict) -> bool:
    eng = _get_engine()
    if eng is None or not _ensure_table(eng):
        return False
    try:
        from sqlalchemy import text
        meta = dict(meta or {})
        meta.setdefault("finetuned", True)
        meta.setdefault("active", True)
        meta.setdefault("module", "TempOutlier_Correction")
        meta.setdefault("kind", KIND_TOC_IF)
        meta.setdefault("param", param)
        meta_str = json.dumps(meta, ensure_ascii=False)[:2000]
        sql = text(
            "INSERT INTO virtual_nn_models "
            "(Kind, Rtype, Data, Meta, Size) "
            "VALUES (:k, :r, :d, :m, :s) "
            "ON DUPLICATE KEY UPDATE "
            "Data=VALUES(Data), Meta=VALUES(Meta), "
            "Size=VALUES(Size), TrainedAt=CURRENT_TIMESTAMP"
        )
        with eng.begin() as conn:
            conn.execute(sql, {
                "k": KIND_TOC_IF,
                "r": _param_tag(param),
                "d": blob,
                "m": meta_str,
                "s": len(blob),
            })
        print(f"[TOC] model saved DB kind={KIND_TOC_IF} tag={_param_tag(param)}",
              flush=True)
        return True
    except Exception as e:
        print(f"[TOC] save_model_to_db: {e}", flush=True)
        return False


def load_model_bytes_from_db(param: str) -> Optional[bytes]:
    eng = _get_engine()
    if eng is None or not _ensure_table(eng):
        return None
    try:
        from sqlalchemy import text
        sql = text(
            "SELECT Data, Meta FROM virtual_nn_models "
            "WHERE Kind = :k AND Rtype = :r LIMIT 1"
        )
        with eng.connect() as conn:
            row = conn.execute(sql, {
                "k": KIND_TOC_IF,
                "r": _param_tag(param),
            }).fetchone()
        if not row or not row[0]:
            return None
        meta = {}
        try:
            meta = json.loads(row[1] or "{}")
        except Exception:
            pass
        # esli active=false - ne ispolzuem
        if meta.get("active") is False:
            print(f"[TOC] model {param} inactive, skip", flush=True)
            return None
        return bytes(row[0])
    except Exception as e:
        print(f"[TOC] load_model_bytes: {e}", flush=True)
        return None


def _dump_iforest(clf) -> bytes:
    import joblib
    buf = io.BytesIO()
    joblib.dump(clf, buf)
    return buf.getvalue()


def _load_iforest(blob: bytes):
    import joblib
    return joblib.load(io.BytesIO(blob))


def retrain_models() -> Dict[str, str]:
    """Doobuchenie IsolationForest i zapis' v BD (Kind=toc_if)."""
    global _models
    result: Dict[str, str] = {"samples_dir": str(learning_dir())}
    samples = load_samples()
    if not samples:
        return {"status": "net obrazcov", **result}

    try:
        from sklearn.ensemble import IsolationForest
        import joblib  # noqa: F401
    except Exception as e:
        return {"status": f"sklearn/joblib: {e}", **result}

    by_param: Dict[str, List[np.ndarray]] = {}
    for s in samples:
        param = (s.get("param") or "F").upper()
        pts = s.get("points") or []
        if len(pts) < 4:
            continue
        temps = np.array([float(p["temp"]) for p in pts], dtype=float)
        vals = np.array([float(p["value"]) for p in pts], dtype=float)
        order = np.argsort(temps)
        temps, vals = temps[order], vals[order]
        deg = min(3, len(temps) - 1)
        try:
            coeffs = np.polyfit(temps, vals, deg)
            resid = vals - np.polyval(coeffs, temps)
            t_norm = (temps - temps.min()) / (temps.max() - temps.min() + 1e-9)
            feat = np.column_stack([resid, t_norm])
            by_param.setdefault(param, []).append(feat)
        except Exception:
            continue

    for param, feats in by_param.items():
        X = np.vstack(feats)
        if len(X) < 8:
            result[param] = f"malo tochek ({len(X)})"
            continue
        clf = IsolationForest(
            contamination=0.08,
            random_state=42,
            n_estimators=120,
        )
        clf.fit(X)
        _models[param] = clf
        blob = _dump_iforest(clf)
        ok = save_model_to_db(
            param,
            blob,
            meta={
                "finetuned": True,
                "active": True,
                "n_samples": int(len(X)),
                "algorithm": "IsolationForest",
                "trained_at": datetime.now().isoformat(timespec="seconds"),
            },
        )
        # lokal'naya kopiya ryadom s obrazcami (ne vnutri modulya)
        try:
            local = _ensure_dir() / f"iforest_{param}.joblib"
            local.write_bytes(blob)
        except Exception as e:
            print(f"[TOC] local model write: {e}", flush=True)
        result[param] = f"OK n={len(X)} db={'yes' if ok else 'no'}"

    result["status"] = "ok"
    return result


def get_trained_model(param: str):
    """
    Prioritet:
      1) pamyat'
      2) BD Kind=toc_if (doobuchennaya, active)
      3) lokal'nyj fajl v TOC_Learning/
    """
    p = (param or "F").upper()
    if p in _models:
        return _models[p]

    blob = load_model_bytes_from_db(p)
    if blob:
        try:
            clf = _load_iforest(blob)
            _models[p] = clf
            print(f"[TOC] IF model from DB param={p}", flush=True)
            return clf
        except Exception as e:
            print(f"[TOC] load IF from DB: {e}", flush=True)

    local = learning_dir() / f"iforest_{p}.joblib"
    if local.exists():
        try:
            import joblib
            clf = joblib.load(local)
            _models[p] = clf
            print(f"[TOC] IF model from file {local}", flush=True)
            return clf
        except Exception as e:
            print(f"[TOC] load IF file: {e}", flush=True)
    return None


def list_toc_models() -> List[Dict[str, Any]]:
    """Spisok toc_if modelej v BD."""
    eng = _get_engine()
    if eng is None or not _ensure_table(eng):
        return []
    try:
        from sqlalchemy import text
        sql = text(
            "SELECT Kind, Rtype, Meta, Size, TrainedAt "
            "FROM virtual_nn_models WHERE Kind = :k ORDER BY TrainedAt DESC"
        )
        with eng.connect() as conn:
            rows = conn.execute(sql, {"k": KIND_TOC_IF}).mappings().fetchall()
        out = []
        for r in rows:
            meta = {}
            try:
                meta = json.loads(r["Meta"] or "{}")
            except Exception:
                pass
            out.append({
                "kind": r["Kind"],
                "tag": r["Rtype"],
                "meta": meta,
                "size": r["Size"],
                "trained_at": str(r["TrainedAt"]),
                "finetuned": bool(meta.get("finetuned", True)),
                "active": meta.get("active", True),
            })
        return out
    except Exception as e:
        print(f"[TOC] list_toc_models: {e}", flush=True)
        return []
