# -*- coding: utf-8 -*-
"""Бизнес-логика Knowledge: выбор замера -> модель -> предсказание -> сохранение."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd

from . import data as kn_data
from . import models as kn_models
from .constants import TARGET_COL


def pick_representative_row(df: pd.DataFrame) -> Optional[pd.Series]:
    if df is None or df.empty:
        return None
    return df.iloc[0]


def resolve_context(df: pd.DataFrame) -> Dict[str, Any]:
    """Spc, nominal_mhz, measure_id из загруженных данных."""
    row = pick_representative_row(df)
    if row is None:
        return {"spc": None, "nominal_mhz": None, "measure_id": None}
    spc = row.get("Spc") if "Spc" in row.index else None
    nom = kn_data.resolve_ref_f_mhz(row)
    mid = row.get("Measure_ID") if "Measure_ID" in row.index else None
    try:
        mid = int(mid) if mid is not None and str(mid).strip() != "" else None
    except (TypeError, ValueError):
        mid = None
    return {"spc": spc, "nominal_mhz": nom, "measure_id": mid}


def auto_model_for_df(
    df: pd.DataFrame,
    all_models: Sequence[kn_models.ModelSpec],
) -> Optional[kn_models.ModelSpec]:
    ctx = resolve_context(df)
    return kn_models.auto_select_model(
        all_models,
        spc=ctx.get("spc"),
        nominal_mhz=ctx.get("nominal_mhz"),
    )


def available_models_for_df(
    df: pd.DataFrame,
    all_models: Sequence[kn_models.ModelSpec],
) -> List[kn_models.ModelSpec]:
    """Список моделей, доступных для текущего замера (для UI-каскада)."""
    ctx = resolve_context(df)
    spc = ctx.get("spc")
    nom = ctx.get("nominal_mhz")
    if kn_data.spc_contains_rk731(spc):
        return kn_models.models_for_spc(all_models, str(spc))
    if nom is not None:
        return kn_models.models_for_nominal(all_models, float(nom))
    return list(all_models)


def predict_for_measure(
    df: pd.DataFrame,
    model: kn_models.ModelSpec,
) -> pd.DataFrame:
    """Предсказание + удобные колонки для таблицы."""
    result = kn_models.run_prediction(model, df)
    # порядок колонок для отображения
    prefer = [
        "ID", "Measure_ID", "MSK", "Number", "Spc",
        "F", "R", "Q", "C0", "Cq", "C1", "L", "Nominal",
        "Ref_f", TARGET_COL, "Filtr_Freq_pred",
    ]
    cols = [c for c in prefer if c in result.columns]
    rest = [c for c in result.columns if c not in cols]
    return result[cols + rest]


def build_save_map(result_df: pd.DataFrame) -> Dict[int, float]:
    """ID строки -> предсказанное Filtr_Freq."""
    out: Dict[int, float] = {}
    if result_df is None or result_df.empty:
        return out
    pred_col = "Filtr_Freq_pred" if "Filtr_Freq_pred" in result_df.columns else TARGET_COL
    if pred_col not in result_df.columns or "ID" not in result_df.columns:
        return out
    for _, row in result_df.iterrows():
        try:
            rid = int(row["ID"])
        except (TypeError, ValueError):
            continue
        val = row[pred_col]
        if val is None or (isinstance(val, float) and np.isnan(val)):
            continue
        try:
            out[rid] = float(val)
        except (TypeError, ValueError):
            continue
    return out


def save_predictions(measure_id: int, result_df: pd.DataFrame) -> int:
    mapping = build_save_map(result_df)
    return kn_data.update_filtr_freq(measure_id, mapping)


def export_result(result_df: pd.DataFrame, path: str) -> str:
    # компактный набор для выгрузки
    prefer = [
        "ID", "Measure_ID", "MSK", "Number", "Spc",
        "F", "R", "Q", "C0", "Cq", "C1", "Nominal",
        TARGET_COL, "Filtr_Freq_pred",
    ]
    cols = [c for c in prefer if c in result_df.columns]
    export_df = result_df[cols] if cols else result_df
    return kn_data.export_predictions_csv(export_df, path)
