# -*- coding: utf-8 -*-
"""
Модели Filtr_Freq только из БД (таблица model_metrics).
Веса: BLOB из строки или путь из колонки path (значение из БД, без сканирования диска).
"""
from __future__ import annotations

import io
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd
from sqlalchemy import text

from .constants import DEFAULT_FEATURES, TARGET_COL

_COL_ALIASES = {
    "id": ("id", "model_id", "ID", "Model_ID"),
    "name": ("name", "model_name", "tag", "model_tag", "Title", "title"),
    "scope": ("scope", "model_scope", "Scope"),
    "spc": ("spc", "spc_key", "Spc", "specification", "Spec", "spec_name"),
    "nominal": ("nominal", "Nominal", "nom", "f_nom", "F_nom"),
    "features": ("features", "feature_list", "Features", "feats"),
    "backend": ("backend", "Backend", "framework"),
    "model_type": ("model_type", "Model_Type", "algo", "algorithm", "best", "best_algo", "type"),
    "rtype": ("rtype", "Rtype", "res_type", "resonator_type", "Type", "psi_type"),
    "n_train": ("n_train", "N_train", "train_n"),
    "n_test": ("n_test", "N_test", "test_n"),
    "mae": ("mae_test", "mae", "MAE", "test_mae"),
    "rmse": ("rmse_test", "rmse", "RMSE", "test_rmse"),
    "r2": ("r2", "R2", "r_2", "test_r2"),
    "frac_10hz": ("frac_10hz", "frac10", "pct_10hz", "match_10hz", "hit_10"),
    "frac_50hz": ("pct_lt50_test", "frac_50hz", "frac50", "pct_50hz", "match_50hz",
                  "hit_50", "prob_50hz", "p_lt_50", "lt50", "frac_lt_50"),
    "frac_50hz_train": ("pct_lt50_train",),
    "test_score": ("test_score", "score", "test_pct", "match_pct", "accuracy"),
    "filtr_min": ("filtr_min", "fmin", "Filtr_Min"),
    "filtr_max": ("filtr_max", "fmax", "Filtr_Max"),
    "blob": ("model_blob", "blob", "data", "Data", "model", "Model", "joblib", "payload",
             "model_data", "weights", "Weights"),
    "fmax": ("fmax", "Fmax", "filtr_max"),
    "path": ("path", "Path", "model_path", "file_path", "filepath", "FilePath",
             "joblib_path", "storage_path"),
    "metrics_json": ("metrics", "metrics_json", "Metrics", "meta", "Meta"),
    "extra": ("extra", "Extra", "extra_json", "params", "Params"),
    "active": ("active", "is_active", "Active", "enabled"),
    "target": ("target", "Target", "target_col"),
}


def _pick_col(columns: Sequence[str], keys: Sequence[str]) -> Optional[str]:
    lower = {str(c).lower(): c for c in columns}
    for k in keys:
        if k in columns:
            return k
        if k.lower() in lower:
            return lower[k.lower()]
    return None


def _map_columns(df: pd.DataFrame) -> Dict[str, Optional[str]]:
    cols = list(df.columns)
    return {logical: _pick_col(cols, aliases) for logical, aliases in _COL_ALIASES.items()}


def _as_float(v: Any) -> Optional[float]:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_features(raw: Any) -> List[str]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return list(DEFAULT_FEATURES)
    if isinstance(raw, (list, tuple)):
        return [str(x) for x in raw]
    s = str(raw).strip()
    if not s:
        return list(DEFAULT_FEATURES)
    try:
        parsed = json.loads(s)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except Exception:
        pass
    return [p.strip() for p in s.replace(";", ",").split(",") if p.strip()] or list(DEFAULT_FEATURES)


def _parse_metrics_json(raw: Any) -> Dict[str, Any]:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(str(raw))
    except Exception:
        return {}


def _extract_frac_50(row: pd.Series, cmap: Dict[str, Optional[str]], metrics: Dict) -> Optional[float]:
    col = cmap.get("frac_50hz")
    if col and col in row.index:
        v = _as_float(row[col])
        if v is not None:
            return float(v / 100.0) if v > 1.5 else float(v)
    # metrics JSON
    for c in (metrics, metrics.get("test") if isinstance(metrics.get("test"), dict) else None):
        if not isinstance(c, dict):
            continue
        for k in ("frac_50hz", "frac50", "pct_50hz", "match_50hz", "lt50"):
            if k in c:
                v = _as_float(c[k])
                if v is not None:
                    return float(v / 100.0) if v > 1.5 else float(v)
    best = metrics.get("best")
    if best and isinstance(metrics.get(best), dict):
        test = metrics[best].get("test") or metrics[best]
        if isinstance(test, dict) and "frac_50hz" in test:
            v = _as_float(test["frac_50hz"])
            if v is not None:
                return float(v / 100.0) if v > 1.5 else float(v)
    return None


def _score_from_row(row: pd.Series, cmap: Dict[str, Optional[str]], metrics: Dict,
                    frac50: Optional[float]) -> float:
    def g(key: str) -> Optional[float]:
        col = cmap.get(key)
        if not col or col not in row.index:
            return None
        return _as_float(row[col])

    for key in ("test_score", "frac_10hz"):
        v = g(key)
        if v is not None and np.isfinite(v):
            return float(v / 100.0) if v > 1.5 else float(v)
    if frac50 is not None and np.isfinite(frac50):
        return float(frac50)

    best_r2, best_mae = None, None
    candidates = []
    if metrics.get("best") and isinstance(metrics.get(metrics["best"]), dict):
        candidates.append(metrics[metrics["best"]])
    if isinstance(metrics.get("test"), dict):
        candidates.append(metrics)
    for k, v in metrics.items():
        if isinstance(v, dict):
            candidates.append(v)
    for c in candidates:
        test = c.get("test") if isinstance(c.get("test"), dict) else c
        if not isinstance(test, dict):
            continue
        if "r2" in test:
            r2 = _as_float(test["r2"])
            if r2 is not None and (best_r2 is None or r2 > best_r2):
                best_r2 = r2
        if "mae" in test:
            mae = _as_float(test["mae"])
            if mae is not None and (best_mae is None or mae < best_mae):
                best_mae = mae
    r2c, maec = g("r2"), g("mae")
    if r2c is not None:
        best_r2 = r2c if best_r2 is None else max(best_r2, r2c)
    if maec is not None:
        best_mae = maec if best_mae is None else min(best_mae, maec)
    if best_r2 is not None and np.isfinite(best_r2):
        return float(best_r2)
    if best_mae is not None and np.isfinite(best_mae):
        return float(1.0 / (1.0 + abs(best_mae)))
    return 0.0



def _materialize_tf_bundle(bundle: dict) -> dict:
    """
    Собрать Keras-модель из pack {kind=tensorflow, arch_json, weights_bytes, scaler_*}.
    Возвращает dict с ключом "model" (готовый keras.Model).
    """
    import os
    import tempfile

    if not isinstance(bundle, dict):
        return bundle
    # уже есть живая модель
    m = bundle.get("model")
    if m is not None and not isinstance(m, (bytes, bytearray, str, dict)):
        return bundle

    arch = bundle.get("arch_json")
    weights = bundle.get("weights_bytes")
    if not arch:
        raise RuntimeError("tensorflow pack: нет arch_json")

    try:
        from tensorflow import keras
    except Exception as e:
        raise RuntimeError(
            f"TensorFlow не установлен или не импортируется: {e}. "
            "Установите tensorflow для моделей kind=tensorflow."
        ) from e

    model = keras.models.model_from_json(arch)
    if weights is not None:
        raw = bytes(weights)
        tmp_path = None
        try:
            # save_weights писал .weights.h5
            with tempfile.NamedTemporaryFile(suffix=".weights.h5", delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            model.load_weights(tmp_path)
        except Exception:
            # fallback: обычный .h5
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass
            with tempfile.NamedTemporaryFile(suffix=".h5", delete=False) as tmp:
                tmp.write(raw)
                tmp_path = tmp.name
            model.load_weights(tmp_path)
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except Exception:
                    pass

    out = dict(bundle)
    out["model"] = model
    return out


def _materialize_pytorch_bundle(bundle: dict) -> dict:
    """
    Собрать PyTorch MLP из pack:
      {kind=pytorch, state_dict_bytes|state_dict, n_in, hidden, scaler_x, scaler_y}.
    Возвращает dict с ключом "model" = callable(X_np) -> y_np (уже с inverse scaler_y).
    """
    if not isinstance(bundle, dict):
        return bundle
    m = bundle.get("model")
    if callable(m) and not isinstance(m, (bytes, bytearray, str, dict)):
        return bundle

    try:
        import torch
        import torch.nn as nn
    except Exception as e:
        raise RuntimeError(
            f"PyTorch не установлен или не импортируется: {e}. "
            "Установите torch для моделей kind=pytorch."
        ) from e

    n_in = bundle.get("n_in")
    hidden = bundle.get("hidden")
    if n_in is None or not hidden:
        raise RuntimeError("pytorch pack: нет n_in/hidden")

    class MLP(nn.Module):
        def __init__(self, n_in_, hidden_):
            super().__init__()
            layers_ = []
            prev = int(n_in_)
            for h in hidden_:
                layers_ += [nn.Linear(prev, int(h)), nn.ReLU()]
                prev = int(h)
            layers_.append(nn.Linear(prev, 1))
            self.net = nn.Sequential(*layers_)

        def forward(self, x):
            return self.net(x).squeeze(-1)

    model = MLP(int(n_in), list(hidden))
    sd = bundle.get("state_dict")
    if sd is None:
        raw = bundle.get("state_dict_bytes")
        if raw is None:
            raise RuntimeError("pytorch pack: нет state_dict / state_dict_bytes")
        sd = torch.load(io.BytesIO(bytes(raw)), map_location="cpu", weights_only=False)
    model.load_state_dict(sd)
    model.eval()

    sx = bundle.get("scaler_x") or bundle.get("sx")
    sy = bundle.get("scaler_y") or bundle.get("sy")

    def _predict_fn(X: np.ndarray) -> np.ndarray:
        X = np.asarray(X, dtype=float)
        if sx is not None:
            X_in = sx.transform(X)
        else:
            X_in = X
        with torch.no_grad():
            t = torch.tensor(X_in, dtype=torch.float32)
            ys = model(t).numpy()
        if sy is not None:
            try:
                ys = sy.inverse_transform(ys.reshape(-1, 1)).ravel()
            except Exception:
                ys = np.asarray(ys, dtype=float).ravel()
        else:
            ys = np.asarray(ys, dtype=float).ravel()
        return ys

    out = dict(bundle)
    out["model"] = _predict_fn
    out["_torch_module"] = model
    out["kind"] = "pytorch"
    return out


def _is_mean_delta_pack(b: Any) -> bool:
    if not isinstance(b, dict):
        return False
    k = str(b.get("kind") or b.get("type") or "").lower()
    return k in ("mean_delta", "small") or "mean_delta" in b


@dataclass
class ModelSpec:
    kind: str = "db"
    path: str = ""              # filesystem path from DB column (optional)
    name: str = ""
    scope: str = ""
    spc_key: str = ""
    model_type: str = ""        # mlp / hgb / torch / ...
    rtype: str = ""             # тип резонатора / группа
    features: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    test_score: float = 0.0
    frac_50hz: Optional[float] = None  # 0..1 доля |err|<50 Hz на test
    nominal: Optional[float] = None
    filtr_bounds: Tuple[float, float] = (-500.0, 500.0)
    backend: str = ""
    db_id: Optional[int] = None
    # для small/mean_delta: mean_delta из extra или blob (без blob тоже работает)
    mean_delta: Optional[float] = None
    extra: Dict[str, Any] = field(default_factory=dict)
    _blob: Optional[bytes] = field(default=None, repr=False)
    _bundle: Any = field(default=None, repr=False)

    def ensure_weights(self) -> None:
        """Подгрузить blob из БД по id, если ещё нет."""
        if self._blob or self._bundle:
            return
        if self.db_id is None:
            return
        try:
            eng = _get_engine()
            # пробуем известные имена колонок blob
            cols = pd.read_sql(text("SHOW COLUMNS FROM model_metrics"), eng)
            col_names = [str(x) for x in cols["Field"].tolist()]
            blob_col = _pick_col(col_names, _COL_ALIASES["blob"])
            if not blob_col:
                return
            id_col = _pick_col(col_names, _COL_ALIASES["id"]) or "id"
            q = text(f"SELECT `{blob_col}` FROM model_metrics WHERE `{id_col}` = :id LIMIT 1")
            with eng.connect() as conn:
                row = conn.execute(q, {"id": int(self.db_id)}).fetchone()
            if row and row[0] is not None:
                raw = row[0]
                if isinstance(raw, (bytes, bytearray, memoryview)):
                    self._blob = bytes(raw)
                elif isinstance(raw, str) and raw:
                    import base64
                    try:
                        self._blob = base64.b64decode(raw)
                    except Exception:
                        self._blob = raw.encode("latin-1", errors="ignore")
        except Exception as e:
            print(f"[Knowledge/models] ensure_weights id={self.db_id}: {e}", flush=True)

    def _is_small_backend(self) -> bool:
        bt = f"{self.backend} {self.model_type}".lower()
        return "small" in bt or "mean_delta" in bt

    def _try_build_mean_delta_bundle(self) -> Optional[dict]:
        """Собрать pack mean_delta без blob: из mean_delta / extra / БД.extra."""
        mean_d = self.mean_delta
        if mean_d is None and isinstance(self.extra, dict):
            mean_d = self.extra.get("mean_delta")
        if mean_d is None and self.db_id is not None:
            try:
                eng = _get_engine()
                cols = pd.read_sql(text("SHOW COLUMNS FROM model_metrics"), eng)
                col_names = [str(x) for x in cols["Field"].tolist()]
                extra_col = _pick_col(col_names, _COL_ALIASES["extra"])
                if extra_col:
                    q = text(
                        f"SELECT `{extra_col}` FROM model_metrics "
                        f"WHERE `{_pick_col(col_names, _COL_ALIASES['id']) or 'id'}` = :id LIMIT 1"
                    )
                    with eng.connect() as conn:
                        row = conn.execute(q, {"id": int(self.db_id)}).fetchone()
                    if row and row[0] is not None:
                        parsed = _parse_metrics_json(row[0])
                        mean_d = parsed.get("mean_delta")
                        if mean_d is not None:
                            self.extra = {**(self.extra or {}), **parsed}
            except Exception as e:
                print(f"[Knowledge/models] mean_delta from extra id={self.db_id}: {e}", flush=True)
        if mean_d is None:
            return None
        return {
            "kind": "mean_delta",
            "type": "mean_delta",
            "mean_delta": float(mean_d),
            "nominal": self.nominal,
            "features": ["F", "Nominal"],
            "spc": self.spc_key,
            "filtr_bounds": self.filtr_bounds,
        }

    def load(self):
        if self._bundle is not None:
            return self._bundle
        self.ensure_weights()
        import joblib
        if self._blob:
            self._bundle = joblib.load(io.BytesIO(self._blob))
        elif self.path:
            self._bundle = joblib.load(self.path)
        else:
            # small / mean_delta: blob не обязателен — достаточно mean_delta в extra
            if self._is_small_backend():
                pack = self._try_build_mean_delta_bundle()
                if pack is not None:
                    self._bundle = pack
                    return self._bundle
            raise RuntimeError(
                f"Model '{self.name}' (id={self.db_id}): net model_blob v model_metrics "
                f"(zapustite migrate_models_tf_to_db.py ili backfill_small_blobs.py)"
            )
        if isinstance(self._bundle, dict):
            if not self.features:
                self.features = list(self._bundle.get("features") or DEFAULT_FEATURES)
            if "filtr_bounds" in self._bundle:
                self.filtr_bounds = tuple(self._bundle["filtr_bounds"])
            # TensorFlow pack: arch_json + weights_bytes
            if self._bundle.get("kind") == "tensorflow" and "arch_json" in self._bundle:
                self._bundle = _materialize_tf_bundle(self._bundle)
            elif self._bundle.get("kind") == "pytorch":
                self._bundle = _materialize_pytorch_bundle(self._bundle)
            # mean_delta / small: без материализации, pred считается в predict()
        return self._bundle

    def predict(self, df: pd.DataFrame) -> np.ndarray:
        b = self.load()

        # --- small / mean_delta: pred = F * Nominal - mean_delta ---
        if _is_mean_delta_pack(b) or self._is_small_backend():
            mean_d = None
            if isinstance(b, dict):
                mean_d = b.get("mean_delta")
                if mean_d is None and isinstance(b.get("extra"), dict):
                    mean_d = b["extra"].get("mean_delta")
            if mean_d is None:
                mean_d = self.mean_delta
            if mean_d is None and isinstance(self.extra, dict):
                mean_d = self.extra.get("mean_delta")
            if mean_d is None:
                raise RuntimeError(
                    f"Model '{self.name}' (id={self.db_id}): mean_delta pack без mean_delta"
                )
            mean_d = float(mean_d)
            work = df.copy()
            for col in ("F", "Nominal"):
                if col not in work.columns:
                    try:
                        from .data import resolve_column
                        src = resolve_column(work, col)
                        if src and src in work.columns:
                            work[col] = pd.to_numeric(work[src], errors="coerce")
                        else:
                            work[col] = np.nan
                    except Exception:
                        work[col] = np.nan
                else:
                    work[col] = pd.to_numeric(work[col], errors="coerce")
            pred = np.full(len(df), np.nan, dtype=float)
            # позиционная маска (не label-index) — иначе IndexError при не-RangeIndex
            ok_mask = (work["F"].notna() & work["Nominal"].notna()).to_numpy()
            if ok_mask.any():
                pred[ok_mask] = (
                    work["F"].to_numpy(dtype=float)[ok_mask]
                    * work["Nominal"].to_numpy(dtype=float)[ok_mask]
                    - mean_d
                )
            return pred

        model = b["model"] if isinstance(b, dict) and "model" in b else b
        feats = self.features or (
            list(b.get("features") or DEFAULT_FEATURES)
            if isinstance(b, dict) else list(DEFAULT_FEATURES)
        )
        pred = np.full(len(df), np.nan, dtype=float)
        if not feats:
            return pred
        # Алиасы колонок (Cq/cq0/C1, Number/N, ...)
        try:
            from .data import resolve_column
        except Exception:
            resolve_column = None  # type: ignore
        work = df.copy()
        for c in feats:
            src = None
            if resolve_column is not None:
                try:
                    src = resolve_column(work, c)
                except Exception:
                    src = None
            if src is None:
                src = c if c in work.columns else None
            if src is None:
                work[c] = np.nan
            elif src == c:
                work[c] = pd.to_numeric(work[c], errors="coerce")
            else:
                work[c] = pd.to_numeric(work[src], errors="coerce")
        # позиционная маска: len(pred)==len(df), индексы строк df могут быть 13, 40, ...
        ok_mask = work[feats].notna().all(axis=1).to_numpy()
        if not ok_mask.any():
            return pred
        X = work.loc[ok_mask, feats].to_numpy(dtype=float)

        kind = (b.get("kind") if isinstance(b, dict) else None) or ""
        backend = (b.get("backend") if isinstance(b, dict) else None) or ""
        is_pytorch = str(kind).lower() == "pytorch" or str(backend).lower() in (
            "pytorch", "torch",
        )

        # PyTorch: model уже callable (из _materialize_pytorch_bundle), scalers внутри
        if is_pytorch and callable(model):
            yp = np.asarray(model(X), dtype=float).reshape(-1)
            pred[ok_mask] = yp
            return pred

        # TensorFlow pack: scaler_x / scaler_y (как в Spektr_F_leaninig.train_model_tf*)
        sx = b.get("scaler_x") if isinstance(b, dict) else None
        sy = b.get("scaler_y") if isinstance(b, dict) else None
        is_tf = isinstance(b, dict) and (
            b.get("kind") == "tensorflow"
            or b.get("backend") == "tensorflow"
            or sx is not None
        )

        if is_tf and sx is not None:
            X_in = sx.transform(X)
        else:
            X_in = X

        # keras Model.predict vs sklearn / callable
        if callable(model) and not hasattr(model, "predict"):
            yp = model(X_in)
        else:
            try:
                yp = model.predict(X_in, verbose=0)
            except TypeError:
                yp = model.predict(X_in)
        yp = np.asarray(yp, dtype=float).reshape(-1)

        if is_tf and sy is not None:
            try:
                yp = sy.inverse_transform(yp.reshape(-1, 1)).ravel()
            except Exception:
                pass

        pred[ok_mask] = yp
        return pred


def _get_engine():
    from Options import get_connection_string
    from sqlalchemy import create_engine
    return create_engine(get_connection_string(), pool_pre_ping=True)


def discover_models(search_dirs: Optional[Sequence[str]] = None) -> List[ModelSpec]:
    """Метаданные всех моделей из model_metrics (без загрузки всех blob в память)."""
    eng = _get_engine()
    try:
        # Не тянем огромные BLOB в SELECT * - исключим известные blob-колонки если есть
        cols_df = pd.read_sql(text("SHOW COLUMNS FROM model_metrics"), eng)
        all_cols = [str(c) for c in cols_df["Field"].tolist()]
        blob_names = {a.lower() for a in _COL_ALIASES["blob"]}
        select_cols = [c for c in all_cols if c.lower() not in blob_names]
        if not select_cols:
            select_cols = all_cols
        cols_sql = ", ".join(f"`{c}`" for c in select_cols)
        df = pd.read_sql(text(f"SELECT {cols_sql} FROM model_metrics"), eng)
    except Exception as e:
        print(f"[Knowledge/models] model_metrics read failed: {e}", flush=True)
        return []

    if df is None or df.empty:
        print("[Knowledge/models] model_metrics is empty", flush=True)
        return []

    cmap = _map_columns(df)
    found: List[ModelSpec] = []

    for _, row in df.iterrows():
        act_col = cmap.get("active")
        if act_col and act_col in row.index:
            av = row[act_col]
            if av is not None and str(av).strip().lower() in ("0", "false", "no", "n"):
                continue
            if isinstance(av, (int, float)) and not pd.isna(av) and int(av) == 0:
                continue

        name_col = cmap.get("name")
        id_col = cmap.get("id")
        name = str(row[name_col]) if name_col and pd.notna(row.get(name_col)) else ""
        db_id = None
        if id_col and pd.notna(row.get(id_col)):
            try:
                db_id = int(row[id_col])
            except (TypeError, ValueError):
                db_id = None
        if not name:
            name = f"model_{db_id}" if db_id is not None else "model"

        scope = ""
        if cmap.get("scope") and pd.notna(row.get(cmap["scope"])):
            scope = str(row[cmap["scope"]])

        spc_key = ""
        if cmap.get("spc") and pd.notna(row.get(cmap["spc"])):
            spc_key = str(row[cmap["spc"]]).strip()
        if not spc_key and scope.startswith("global"):
            spc_key = "*"

        model_type = ""
        if cmap.get("model_type") and pd.notna(row.get(cmap["model_type"])):
            model_type = str(row[cmap["model_type"]]).strip()

        rtype = ""
        if cmap.get("rtype") and pd.notna(row.get(cmap["rtype"])):
            rtype = str(row[cmap["rtype"]]).strip()

        nominal = _as_float(row[cmap["nominal"]]) if cmap.get("nominal") else None
        features = _parse_features(row[cmap["features"]]) if cmap.get("features") else list(DEFAULT_FEATURES)
        backend = str(row[cmap["backend"]]) if cmap.get("backend") and pd.notna(row.get(cmap["backend"])) else ""

        fmin = _as_float(row[cmap["filtr_min"]]) if cmap.get("filtr_min") else None
        fmax = _as_float(row[cmap["filtr_max"]]) if cmap.get("filtr_max") else None
        bounds = (fmin if fmin is not None else -500.0, fmax if fmax is not None else 500.0)

        metrics = _parse_metrics_json(row[cmap["metrics_json"]]) if cmap.get("metrics_json") else {}
        frac50 = _extract_frac_50(row, cmap, metrics)
        score = _score_from_row(row, cmap, metrics, frac50)

        file_path = ""
        if cmap.get("path") and pd.notna(row.get(cmap["path"])):
            file_path = str(row[cmap["path"]]).strip()

        extra: Dict[str, Any] = {}
        if cmap.get("extra") and pd.notna(row.get(cmap["extra"])):
            extra = _parse_metrics_json(row[cmap["extra"]])
        mean_delta = _as_float(extra.get("mean_delta")) if extra else None
        # small без features в БД — F, Nominal
        bt = f"{backend} {model_type}".lower()
        if ("small" in bt or "mean_delta" in bt) and (
            not features or features == list(DEFAULT_FEATURES)
        ):
            features = ["F", "Nominal"]

        display = name
        if spc_key and spc_key != "*":
            display = f"{name} [{spc_key}]"
        if model_type:
            display = f"{display} ({model_type})"

        found.append(ModelSpec(
            kind="db",
            path=file_path,
            name=display,
            scope=scope or ("global" if spc_key in ("", "*") else "per-spc"),
            spc_key=spc_key or "*",
            model_type=model_type or "unknown",
            rtype=rtype,
            features=features,
            metrics=metrics,
            test_score=score,
            frac_50hz=frac50,
            nominal=nominal,
            filtr_bounds=bounds,
            backend=backend,
            db_id=db_id,
            mean_delta=mean_delta,
            extra=extra,
        ))

    found.sort(key=lambda m: -m.test_score)
    print(f"[Knowledge/models] loaded from model_metrics: {len(found)}", flush=True)
    return found


def models_for_spc(all_models: Sequence[ModelSpec], spc: str) -> List[ModelSpec]:
    spc_s = str(spc or "").strip()
    exact, global_ones = [], []
    for m in all_models:
        if m.spc_key and m.spc_key != "*" and m.spc_key == spc_s:
            exact.append(m)
        elif m.spc_key in ("", "*") or (m.scope or "").startswith("global"):
            global_ones.append(m)
    return exact if exact else global_ones


def models_for_nominal(
    all_models: Sequence[ModelSpec],
    nominal_mhz: float,
    tol_mhz: float = 0.15,
) -> List[ModelSpec]:
    with_nom = [m for m in all_models if m.nominal is not None]
    if not with_nom:
        return sorted(
            [m for m in all_models
             if m.spc_key in ("", "*") or (m.scope or "").startswith("global")],
            key=lambda x: -x.test_score,
        )
    ranked = sorted(with_nom, key=lambda m: abs(float(m.nominal) - nominal_mhz))
    best_dist = abs(float(ranked[0].nominal) - nominal_mhz)
    close = [
        m for m in ranked
        if abs(float(m.nominal) - nominal_mhz) <= max(tol_mhz, best_dist + 1e-9)
    ]
    return sorted(close, key=lambda x: -x.test_score)


def auto_select_model(
    all_models: Sequence[ModelSpec],
    spc: Optional[str],
    nominal_mhz: Optional[float],
) -> Optional[ModelSpec]:
    if not all_models:
        return None
    from .data import spc_contains_rk731

    if spc_contains_rk731(spc):
        cands = models_for_spc(all_models, str(spc))
        if not cands:
            cands = list(all_models)
        return max(cands, key=lambda m: (m.frac_50hz if m.frac_50hz is not None else m.test_score))

    if nominal_mhz is not None and np.isfinite(nominal_mhz):
        cands = models_for_nominal(all_models, float(nominal_mhz))
        if cands:
            return max(cands, key=lambda m: (m.frac_50hz if m.frac_50hz is not None else m.test_score))

    return max(all_models, key=lambda m: (m.frac_50hz if m.frac_50hz is not None else m.test_score))


def cascade_levels(models: Sequence[ModelSpec]) -> Dict[str, Any]:
    """
    Каскад UI:
      rtype (тип) -> spc_key (спецификация модели) -> model_type -> list[ModelSpec]
    """
    tree: Dict[str, Dict[str, Dict[str, List[ModelSpec]]]] = {}
    for m in models:
        rt = m.rtype or m.scope or "all"
        sp = m.spc_key or "*"
        mt = m.model_type or "unknown"
        tree.setdefault(rt, {}).setdefault(sp, {}).setdefault(mt, []).append(m)
    for rt in tree:
        for sp in tree[rt]:
            for mt in tree[rt][sp]:
                tree[rt][sp][mt].sort(
                    key=lambda x: -(x.frac_50hz if x.frac_50hz is not None else x.test_score)
                )
    return tree


def group_model_types(all_models: Sequence[ModelSpec]) -> Dict[str, List[ModelSpec]]:
    """Совместимость: группировка global / per-spc."""
    groups: Dict[str, List[ModelSpec]] = {}
    for m in all_models:
        key = "global" if m.spc_key in ("", "*") or (m.scope or "").startswith("global") else "per-spc"
        groups.setdefault(key, []).append(m)
    for k in groups:
        groups[k] = sorted(
            groups[k],
            key=lambda x: (-(x.frac_50hz if x.frac_50hz is not None else x.test_score), x.name),
        )
    return groups


def run_prediction(model: ModelSpec, df: pd.DataFrame) -> pd.DataFrame:
    n = len(df)
    print(
        f"[Knowledge/models] run_prediction: id={model.db_id} "
        f"type={model.model_type!r} backend={model.backend!r} rows={n}",
        flush=True,
    )
    out = df.copy()
    pred = model.predict(out)
    try:
        n_ok = int(np.isfinite(np.asarray(pred, dtype=float)).sum())
    except Exception:
        n_ok = 0
    print(
        f"[Knowledge/models] run_prediction done: predicted {n_ok}/{n}",
        flush=True,
    )
    out["Filtr_Freq_pred"] = pred
    if TARGET_COL not in out.columns:
        out[TARGET_COL] = pred
    else:
        existing = pd.to_numeric(out[TARGET_COL], errors="coerce")
        out[TARGET_COL] = existing.where(existing.notna(), pred)
    return out
