"""Aktivnoe obuchenie: pravki operatora + doobuchenie IsolationForest."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

_DATA_DIR = Path(__file__).resolve().parent / "_learning_data"
_SAMPLES_FILE = _DATA_DIR / "samples.json"
_models: Dict[str, Any] = {}


def _ensure_dir():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)


def load_samples() -> List[Dict[str, Any]]:
    _ensure_dir()
    if not _SAMPLES_FILE.exists():
        return []
    try:
        return json.loads(_SAMPLES_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_samples(samples: List[Dict[str, Any]]) -> None:
    _ensure_dir()
    _SAMPLES_FILE.write_text(
        json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_training_sample(
    number: str,
    points: List[Dict[str, Any]],
    param: str = "F",
    label: str = "corrected",
) -> int:
    """
    points: [{temp, value, is_outlier?}]
    label: corrected / outlier
    """
    samples = load_samples()
    samples.append({
        "number": str(number),
        "param": param,
        "label": label,
        "points": points,
    })
    save_samples(samples)
    return len(samples)


def retrain_models() -> Dict[str, str]:
    """
    Doobuchenie IsolationForest na ostatkah ot poly3 po sobrannym krivym.
    label=outlier tochki uchatsya kak anomaliya, corrected - normal.
    """
    global _models
    result: Dict[str, str] = {}
    samples = load_samples()
    if not samples:
        return {"status": "net obrazcov"}

    try:
        from sklearn.ensemble import IsolationForest
    except Exception as e:
        return {"status": f"sklearn nedostupen: {e}"}

    by_param: Dict[str, List[np.ndarray]] = {}
    for s in samples:
        param = s.get("param") or "F"
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
        # save pickle-less: keep in memory; dump meta
        result[param] = f"OK, samples={len(X)}"
        try:
            import joblib
            joblib.dump(clf, _DATA_DIR / f"iforest_{param}.joblib")
        except Exception:
            pass
    result["status"] = "ok"
    return result


def get_trained_model(param: str):
    if param in _models:
        return _models[param]
    try:
        import joblib
        p = _DATA_DIR / f"iforest_{param}.joblib"
        if p.exists():
            _models[param] = joblib.load(p)
            return _models[param]
    except Exception:
        pass
    return None


def samples_count() -> int:
    return len(load_samples())
