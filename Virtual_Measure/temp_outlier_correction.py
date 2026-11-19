"""Коррекция выбросов в температурных точках виртуальных замеров.

Если базовое изделие (psidata) годно по нормам спецификации, одиночные
аномальные точки в psidatatemp заменяются аппроксимацией (полином 2-й
степени). Журнал коррекций пишется в virtual_measure_log.
"""
from __future__ import annotations

import json
from typing import Optional

import numpy as np
import pandas as pd
from sqlalchemy import text

from .Virtual_Data import _safe_float, _engine, _ts, _ensure_virtual_log_table


def is_resonator_good_by_params(row_dict, param_ranges: list) -> bool:
    """Годность по нормам параметров (не по колонке Status)."""
    for pr in param_ranges:
        param = pr['param']
        field = pr['field']
        val = None
        if hasattr(row_dict, 'get'):
            val = row_dict.get(field)
            if val is None:
                val = row_dict.get(param)
        try:
            fv = float(val) if val is not None else None
        except (TypeError, ValueError):
            fv = None
        if fv is None:
            return False
        try:
            if np.isnan(fv):
                return False
        except (TypeError, ValueError):
            pass
        if pr.get('min') is not None and fv < pr['min']:
            return False
        if pr.get('max') is not None and fv > pr['max']:
            return False
    return True


def fit_polynomial_to_temps(temp_df: pd.DataFrame, param_name: str,
                            degree: int = 2):
    """Полином по температурным точкам параметра."""
    if temp_df is None or temp_df.empty:
        return None, None
    if 'Temp' not in temp_df.columns or param_name not in temp_df.columns:
        return None, None
    df = temp_df.dropna(subset=['Temp', param_name])
    if len(df) < degree + 1:
        return None, None
    X = df['Temp'].values
    y = df[param_name].values
    try:
        coefficients = np.polyfit(X, y, degree)
        return np.poly1d(coefficients), coefficients
    except Exception:
        return None, None


def correct_temperature_outliers(temp_df: pd.DataFrame, base_row,
                                 param_ranges: list, tnastr: float = 25.0):
    """
    Заменить выбросы в температурном интервале аппроксимацией.

    Условие: базовый резонатор (psidata) годен по нормам.
    Критерий выброса: |x - mean| > 3σ и |x - poly(T)| > 3σ.
    Returns (corrected_df, corrections_log).
    """
    if temp_df is None or (hasattr(temp_df, 'empty') and temp_df.empty):
        return temp_df, []

    if not is_resonator_good_by_params(base_row, param_ranges):
        return temp_df, []

    params_to_check = ['F', 'R', 'FL', 'Rb', 'C0', 'Cq', 'Q', 'L']
    corrected_df = temp_df.copy()
    corrections_log = []

    for param in params_to_check:
        if param not in temp_df.columns:
            continue
        poly, _coeffs = fit_polynomial_to_temps(temp_df, param)
        if poly is None:
            continue
        valid_values = temp_df[param].dropna().values
        if len(valid_values) < 2:
            continue
        std_dev = float(np.std(valid_values))
        mean_val = float(np.mean(valid_values))
        if std_dev <= 0:
            continue
        for idx, row in temp_df.iterrows():
            temp_val = _safe_float(row.get('Temp'))
            param_val = _safe_float(row.get(param))
            if temp_val is None or param_val is None:
                continue
            expected_val = float(poly(temp_val))
            deviation_from_mean = abs(param_val - mean_val)
            deviation_from_poly = abs(param_val - expected_val)
            if (deviation_from_mean > 3 * std_dev and
                    deviation_from_poly > 3 * std_dev):
                corrected_df.at[idx, param] = expected_val
                corrections_log.append({
                    'Temp': temp_val,
                    'param': param,
                    'original': param_val,
                    'corrected': expected_val,
                    'reason': 'outlier_correction',
                })
    return corrected_df, corrections_log


def log_corrections(msk: str, source_mid: int, virtual_mid: int,
                    corrections_log: list) -> bool:
    """Записать corrections_log в virtual_measure_log."""
    if not corrections_log or source_mid is None or virtual_mid is None:
        return False
    try:
        if not _ensure_virtual_log_table():
            return False
        corrections_json = json.dumps(corrections_log, ensure_ascii=False,
                                      default=str)
        sql = text(
            "UPDATE `virtual_measure_log` "
            "SET `Corrections` = :corrections, `Has_Corrections` = 1 "
            "WHERE `Virtual_Measure_ID` = :virt "
            "AND `Source_Measure_ID` = :src"
        )
        with _engine().begin() as conn:
            conn.execute(sql, {
                "corrections": corrections_json,
                "virt": int(virtual_mid),
                "src": int(source_mid),
            })
        print(f"[Virtual {_ts()}] corrections logged: "
              f"{len(corrections_log)} for virtual measure {virtual_mid}",
              flush=True)
        return True
    except Exception as e:
        print(f"[Virtual {_ts()}] log_corrections error: {e}", flush=True)
        return False
