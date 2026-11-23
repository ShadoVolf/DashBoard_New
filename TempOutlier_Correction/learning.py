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


def save_model_to_db(param: str, blob: bytes, meta: dict, kind: str = KIND_TOC_IF) -> bool:
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
                "k": kind,
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


def load_model_bytes_from_db(param: str, kind: str = KIND_TOC_IF) -> Optional[bytes]:
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
                "k": kind,
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

    # TCN/seq2seq vosstanovlenie probelov (tog zhe nabor obrazcov)
    try:
        result["tcn"] = retrain_tcn_models(samples)
    except Exception as e:
        result["tcn"] = f"error: {e}"

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


# ---------------------------------------------------------------------------
# TCN / seq2seq: vosstanovlenie probelov po krivoj F(T).
# Inference - chistyj numpy (kak mlp / ae v Virtual_NN).
# Model: npz v virtual_nn_models (Kind=toc_tcn, Rtype=toc::<PARAM>)
# ili lokalnyj fajl TOC_Learning/tcn_<param>.npz. Obuchenie - chistyj numpy
# (Adam) na chistyh krivyh iz TOC_Learning, maskirovanie dyh pri trenirgove.
# ---------------------------------------------------------------------------

KIND_TCN = "toc_tcn"
_tcn_models: Dict[str, Any] = {}
# (in, out, kernel, dilation) po sloyam; poslednij sloy - linearnyj vyhod
_TCN_ARCH = [(1, 8, 3, 1), (8, 8, 3, 2), (8, 1, 3, 4)]


def _parse_tcn_npz(npz) -> Dict[str, Any]:
    n_layers = int(npz["n_layers"][0])
    return {
        "Ws": [np.asarray(npz[f"W{i}"], dtype=float) for i in range(n_layers)],
        "bs": [np.asarray(npz[f"b{i}"], dtype=float) for i in range(n_layers)],
        "dils": [int(npz[f"dil{i}"][0]) for i in range(n_layers)],
    }


def _load_tcn_from_bytes(data: bytes) -> Dict[str, Any]:
    with np.load(io.BytesIO(data)) as npz:
        return _parse_tcn_npz(npz)


def _serialize_tcn(m: Dict[str, Any]) -> bytes:
    buf = io.BytesIO()
    args: Dict[str, Any] = {"n_layers": np.array([len(m["Ws"])], dtype=int)}
    for i, (W, b, dil) in enumerate(zip(m["Ws"], m["bs"], m["dils"])):
        args[f"W{i}"] = W
        args[f"b{i}"] = b
        args[f"dil{i}"] = np.array([dil], dtype=int)
    np.savez(buf, **args)
    return buf.getvalue()


def _init_tcn(rng, arch=None) -> Dict[str, Any]:
    Ws, bs, dils = [], [], []
    for c_in, c_out, k, d in (arch or _TCN_ARCH):
        Ws.append(rng.normal(0.0, np.sqrt(2.0 / (c_in * k)), size=(c_out, c_in, k)))
        bs.append(np.zeros(c_out, dtype=float))
        dils.append(int(d))
    return {"Ws": Ws, "bs": bs, "dils": dils}


def _causal_conv(x: np.ndarray, W: np.ndarray, b: np.ndarray, dil: int) -> np.ndarray:
    """x: [Cin, T] -> [Cout, T], causal dilated conv1d (levyj nulevoj padding)."""
    T = x.shape[1]
    K = W.shape[2]
    pad = (K - 1) * int(dil)
    xp = np.zeros((x.shape[0], T + pad), dtype=float)
    xp[:, pad:] = x[:, :T]
    out = np.tile(np.asarray(b, dtype=float)[:, None], (1, T))
    for k in range(K):
        seg = xp[:, k * dil:k * dil + T]
        out += W[:, :, k] @ seg
    return out


def _causal_conv_backward(
    dout: np.ndarray, x_in: np.ndarray, W: np.ndarray, dil: int
):
    C_out, C_in, K = W.shape
    T = x_in.shape[1]
    pad = (K - 1) * int(dil)
    dW = np.zeros_like(W)
    db = dout.sum(axis=1)
    dxp = np.zeros((C_in, T + pad), dtype=float)
    for k in range(K):
        seg = x_in[:, k * dil:k * dil + T]
        dW[:, :, k] += dout @ seg.T
        dxp[:, k * dil:k * dil + T] += W[:, :, k].T @ dout
    dx = dxp[:, pad:pad + T]
    return dW, db, dx


def _tcn_forward(m: Dict[str, Any], xs: np.ndarray) -> np.ndarray:
    h = xs
    last = len(m["Ws"]) - 1
    for i in range(len(m["Ws"])):
        h = _causal_conv(h, m["Ws"][i], m["bs"][i], m["dils"][i])
        if i < last:
            h = np.maximum(h, 0.0)
    return h


def _tcn_train(
    curves: List[np.ndarray],
    seed: int = 42,
    epochs: int = 500,
    lr: float = 3e-3,
) -> Dict[str, Any]:
    """Seq2seq-trening: vhod - krivaya s maskirovannymi dyrami, celi - celaya."""
    rng = np.random.default_rng(seed)
    m = _init_tcn(rng)
    n_layers = len(m["Ws"])
    adam = [
        {
            "W": (np.zeros_like(m["Ws"][i]), np.zeros_like(m["Ws"][i])),
            "b": (np.zeros_like(m["bs"][i]), np.zeros_like(m["bs"][i])),
        }
        for i in range(n_layers)
    ]
    beta1, beta2, eps = 0.9, 0.999, 1e-8
    idxs = np.arange(len(curves))
    step = 0
    for _epoch in range(epochs):
        rng.shuffle(idxs)
        for ci in idxs:
            step += 1
            curve = curves[int(ci)]
            if curve.size < 5:
                continue
            mu = float(np.mean(curve))
            sd = float(np.std(curve)) or 1.0
            y = (curve - mu) / sd
            holes = rng.random(curve.size) < 0.25
            if holes.sum() >= curve.size - 3:
                holes = np.zeros(curve.size, dtype=bool)
            x = y.copy()
            x[holes] = 0.0

            caches = []
            h = x[None, :]
            for i in range(n_layers):
                pre = _causal_conv(h, m["Ws"][i], m["bs"][i], m["dils"][i])
                h_next = np.maximum(pre, 0.0) if i < n_layers - 1 else pre
                caches.append((h, pre))
                h = h_next
            err = h - y[None, :]
            loss = float(np.mean(err ** 2))
            if not np.isfinite(loss):
                m = _init_tcn(rng)
                adam = [
                    {
                        "W": (np.zeros_like(m["Ws"][i]), np.zeros_like(m["Ws"][i])),
                        "b": (np.zeros_like(m["bs"][i]), np.zeros_like(m["bs"][i])),
                    }
                    for i in range(n_layers)
                ]
                continue

            dout = (2.0 / err.size) * err
            grads = [None] * n_layers
            for i in range(n_layers - 1, -1, -1):
                h_in, pre = caches[i]
                dpre = dout * (pre > 0) if i < n_layers - 1 else dout
                dW, db, dh = _causal_conv_backward(
                    dpre, h_in, m["Ws"][i], m["dils"][i]
                )
                grads[i] = (dW, db)
                dout = dh

            for i in range(n_layers):
                for name, gi in (("W", grads[i][0]), ("b", grads[i][1])):
                    m1, m2 = adam[i][name]
                    m1 += (1 - beta1) * (gi - m1)
                    m2 += (1 - beta2) * (gi * gi - m2)
                    mh = m1 / (1 - beta1 ** step)
                    vh = m2 / (1 - beta2 ** step)
                    if name == "W":
                        m["Ws"][i] -= lr * mh / (np.sqrt(vh) + eps)
                    else:
                        m["bs"][i] -= lr * mh / (np.sqrt(vh) + eps)
    return m


def retrain_tcn_models(samples: Optional[List[Dict[str, Any]]] = None) -> Dict[str, str]:
    """Trening TCN na chistyh krivyh iz obrazcov; zapis' v BD Kind=toc_tcn."""
    global _tcn_models
    result: Dict[str, str] = {}
    if samples is None:
        samples = load_samples()
    if not samples:
        return {"status": "net obrazcov"}
    by_param: Dict[str, List[np.ndarray]] = {}
    for s in samples:
        param = (s.get("param") or "F").upper()
        pts = sorted(s.get("points") or [], key=lambda p: p.get("temp", 0.0))
        vals = []
        for p in pts:
            try:
                v = float(p["value"])
            except (TypeError, ValueError, KeyError):
                continue
            if np.isfinite(v):
                vals.append(v)
        if len(vals) >= 6:
            by_param.setdefault(param, []).append(np.asarray(vals, dtype=float))
    for param, curves in by_param.items():
        if len(curves) < 2:
            result[param] = f"malo krivyh ({len(curves)})"
            continue
        try:
            m = _tcn_train(curves)
            blob = _serialize_tcn(m)
            _tcn_models[param] = m
            ok = save_model_to_db(
                param,
                blob,
                meta={"algorithm": "tcn_numpy", "n_curves": len(curves)},
                kind=KIND_TCN,
            )
            try:
                local = _ensure_dir() / f"tcn_{param}.npz"
                local.write_bytes(blob)
            except Exception as e:
                print(f"[TOC] local tcn write: {e}", flush=True)
            result[param] = f"OK cur={len(curves)} db={'yes' if ok else 'no'}"
        except Exception as e:
            result[param] = f"error: {e}"
    result["status"] = "ok" if by_param else "net dannyh"
    return result


def get_tcn_model(param: str) -> Optional[Dict[str, Any]]:
    " Prioritet: pamiat -> BD (Kind=toc_tcn, active) -> lokalnyj fajl. "
    p = (param or "F").upper()
    if p in _tcn_models:
        return _tcn_models[p]
    try:
        blob = load_model_bytes_from_db(p, kind=KIND_TCN)
        if blob:
            m = _load_tcn_from_bytes(blob)
            _tcn_models[p] = m
            print(f"[TOC] TCN model from DB param={p}", flush=True)
            return m
    except Exception as e:
        print(f"[TOC] load TCN db: {e}", flush=True)
    local = learning_dir() / f"tcn_{p}.npz"
    if local.exists():
        try:
            with np.load(local) as npz:
                m = _parse_tcn_npz(npz)
            _tcn_models[p] = m
            print(f"[TOC] TCN model from file {local}", flush=True)
            return m
        except Exception as e:
            print(f"[TOC] load TCN file: {e}", flush=True)
    return None


def tcn_restore_curve(
    values: np.ndarray, bad_mask: np.ndarray, param: str = "F"
) -> Optional[np.ndarray]:
    """
    Seq2seq/TCN vosstanovlenie probelov po krivoj.
    Bez modeli (ili nestabilnom prognoze) - interpolyaciya + median sglazh.
    Vozvrashaet novyj massiv ili None (net dannh / ne poluchilos).
    """
    vals = np.asarray(values, dtype=float)
    bad = np.asarray(bad_mask, dtype=bool)
    if vals.size < 3 or not bad.any():
        return None
    good = ~bad & np.isfinite(vals)
    good_vals = vals[good]
    if good_vals.size < 3:
        return None
    out = vals.copy()
    m = None
    try:
        m = get_tcn_model(param)
    except Exception:
        m = None
    if m is not None:
        try:
            mu = float(np.mean(good_vals))
            sd = float(np.std(good_vals)) or 1.0
            with np.errstate(all="ignore"):
                y = _tcn_forward(m, ((vals - mu) / sd)[None, :])[0]
            pred = y * sd + mu
            if np.all(np.isfinite(pred[bad])):
                out[bad] = pred[bad]
                return out
        except Exception as e:
            print(f"[TOC] tcn forward: {e}", flush=True)
    # fallback bez modeli
    gi = np.flatnonzero(good).astype(float)
    if gi.size:
        out[bad] = np.interp(np.flatnonzero(bad), gi, good_vals)
    for _ in range(3):
        for i in np.flatnonzero(bad):
            lo, hi = max(0, i - 2), min(vals.size, i + 3)
            seg = [
                out[j] for j in range(lo, hi)
                if j != i and not bad[j] and np.isfinite(out[j])
            ]
            if seg:
                out[i] = float(np.median(seg))
    return out if np.all(np.isfinite(out)) else None

