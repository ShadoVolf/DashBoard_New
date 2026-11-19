"""
Коррекция выбросов в температурных точках psidatatemp.

Правила:
  * Коррекция применяется только если базовый резонатор годен
    (Status ∈ {'годен','pass','1','true'} И параметры в диапазонах param_ranges).
  * Выброс — это:
        - маркерное значение 100000;
        - либо |x - median| > 3 * 1.4826 * MAD (устойчивый критерий).
  * Замена — медиана соседних точек (окно ±2), fallback — медиана по колонке.
  * Проверяются только измеримые колонки (F, R, Rb, C0, Cq, L, Q, FL,
    Mono, RC_Rb, F_int, Spur, SpurR). Служебные поля (Status, pos,
    Measure_ID, N, ProtokolN, variant_*) не трогаем.
"""
from __future__ import annotations

import json
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
import pandas as pd


OUTLIER_MARKER = 100000.0
MAD_K = 3.0

# Колонки, которые реально являются измеряемыми параметрами температуры.
MEASURABLE_COLS = {
    'F', 'R', 'Rb', 'C0', 'Cq', 'L', 'Q',
    'FL', 'Mono', 'RC_Rb', 'F_int', 'Spur', 'SpurR',
}


def _safe_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        v = float(value)
        if np.isnan(v) or np.isinf(v):
            return None
        return v
    except (TypeError, ValueError):
        return None


def _local_median_estimate(series: pd.Series, idx, window: int = 2) -> Optional[float]:
    """Медиана ближайших соседей (окно ±window), исключая сам idx и маркер 100000."""
    positions = list(series.index)
    try:
        pos = positions.index(idx)
    except ValueError:
        return None

    lo = max(0, pos - window)
    hi = min(len(positions), pos + window + 1)

    neighbors = []
    for p in positions[lo:hi]:
        if p == idx:
            continue
        v = _safe_float(series.loc[p])
        if v is not None and v != OUTLIER_MARKER:
            neighbors.append(v)

    if not neighbors:
        return None
    return float(np.median(neighbors))


def is_resonator_good_by_params(row_dict: Dict[str, Any], param_ranges: List) -> bool:
    """
    Резонатор годен, если:
      1) Status ∈ {'годен','pass','1','true'} (если поле Status присутствует);
      2) все параметры из param_ranges попадают в [min, max].
    """
    status = row_dict.get('Status')
    if status is not None:
        status_str = str(status).strip().lower()
        if status_str not in ('годен', 'pass', '1', 'true', '1.0'):
            # Status может быть числом 1 → str(1) = '1' → попадает в набор
            try:
                if int(float(status)) != 1:
                    return False
            except (TypeError, ValueError):
                return False

    for pr in param_ranges or []:
        if isinstance(pr, dict):
            param_name = pr.get('param')
            min_v = pr.get('min')
            max_v = pr.get('max')
        else:
            param_name = getattr(pr, 'param', None)
            min_v = getattr(pr, 'min', None)
            max_v = getattr(pr, 'max', None)

        if not param_name:
            continue

        val = _safe_float(row_dict.get(param_name))
        if val is None:
            continue

        if min_v is not None and val < min_v:
            return False
        if max_v is not None and val > max_v:
            return False

    return True


def correct_temperature_outliers(
    temp_df: pd.DataFrame,
    base_row,
    param_ranges: List,
    tnastr: float = 25.0,
) -> Tuple[pd.DataFrame, List[Dict[str, Any]]]:
    """
    Возвращает (исправленный DataFrame, список коррекций).
    Список коррекций — для записи в virtual_measure_log.Corrections.
    """
    corrections: List[Dict[str, Any]] = []
    if temp_df is None or temp_df.empty:
        return temp_df, corrections

    if isinstance(base_row, dict):
        base_row_dict = base_row
    else:
        try:
            base_row_dict = base_row.to_dict() if hasattr(base_row, 'to_dict') else dict(base_row)
        except Exception:
            base_row_dict = {}

    if not is_resonator_good_by_params(base_row_dict, param_ranges):
        return temp_df, corrections

    result_df = temp_df.copy()

    for param in result_df.columns:
        if param not in MEASURABLE_COLS:
            continue

        series = result_df[param]

        numeric_values: List[float] = []
        for v in series:
            fv = _safe_float(v)
            if fv is not None and fv != OUTLIER_MARKER:
                numeric_values.append(fv)

        # Мало данных — обрабатываем только явный маркер.
        if len(numeric_values) < 3:
            for idx in series.index:
                fv = _safe_float(series.loc[idx])
                if fv is None or fv != OUTLIER_MARKER:
                    continue
                estimate = _local_median_estimate(series, idx, window=3)
                if estimate is None:
                    estimate = float(np.median(numeric_values)) if numeric_values else tnastr

                corrections.append({
                    'Param': param,
                    'Index': idx,
                    'OldValue': fv,
                    'NewValue': estimate,
                    'Reason': 'marker_100000',
                })
                result_df.at[idx, param] = estimate
            continue

        arr = np.asarray(numeric_values, dtype=float)
        median_val = float(np.median(arr))
        mad = float(np.median(np.abs(arr - median_val)))
        robust_sigma = 1.4826 * mad
        threshold = MAD_K * robust_sigma if robust_sigma > 0 else None

        for idx in series.index:
            fv = _safe_float(series.loc[idx])
            if fv is None:
                continue

            is_marker = (fv == OUTLIER_MARKER)
            is_statistical = False
            if threshold is not None and threshold > 0:
                is_statistical = abs(fv - median_val) > threshold

            if not (is_marker or is_statistical):
                continue

            estimate = _local_median_estimate(series, idx, window=2)
            if estimate is None:
                estimate = median_val
            if estimate is None:
                estimate = tnastr

            corrections.append({
                'Param': param,
                'Index': idx,
                'OldValue': fv,
                'NewValue': estimate,
                'Reason': 'marker_100000' if is_marker else 'statistical_mad',
            })
            result_df.at[idx, param] = estimate

    return result_df, corrections


def log_corrections(msk, source_mid, virtual_mid, corrections_log):
    """
    Записывает коррекции в virtual_measure_log.

    _engine — это ФУНКЦИЯ в Virtual_Data, её надо ВЫЗВАТЬ (with _engine().begin()).
    _ensure_virtual_log_table создаёт таблицу и добавляет колонки
    Corrections/Has_Corrections (если их нет).
    """
    if not corrections_log:
        return

    try:
        from .Virtual_Data import _engine, _ensure_virtual_log_table
    except ImportError as e:
        print(f"[Corrections] import from Virtual_Data failed: {e}", flush=True)
        return

    try:
        if not _ensure_virtual_log_table():
            print("[Corrections] _ensure_virtual_log_table() = False, пропуск",
                  flush=True)
            return
    except Exception as e:
        print(f"[Corrections] _ensure_virtual_log_table() error: {e}", flush=True)
        return

    try:
        payload = json.dumps(corrections_log, ensure_ascii=False, default=str)
    except Exception as e:
        print(f"[Corrections] json error: {e}", flush=True)
        return

    from sqlalchemy import text

    try:
        with _engine().begin() as conn:
            res = conn.execute(
                text(
                    "UPDATE `virtual_measure_log` "
                    "SET `Corrections` = :c, `Has_Corrections` = 1 "
                    "WHERE `Virtual_Measure_ID` = :v"
                ),
                {'c': payload, 'v': int(virtual_mid)},
            )
            if res.rowcount == 0:
                conn.execute(
                    text(
                        "INSERT INTO `virtual_measure_log` "
                        "(`MSK`, `Source_Measure_ID`, `Virtual_Measure_ID`, "
                        " `Login`, `Corrections`, `Has_Corrections`) "
                        "VALUES (:m, :s, :v, :l, :c, 1)"
                    ),
                    {
                        'm': str(msk or ''),
                        's': int(source_mid),
                        'v': int(virtual_mid),
                        'l': 'system',
                        'c': payload,
                    },
                )
        print(
            f"[Corrections] сохранено {len(corrections_log)} шт. "
            f"для virtual_mid={virtual_mid}",
            flush=True,
        )
    except Exception as e:
        print(f"[Corrections] log error: {e}", flush=True)
        import traceback
        traceback.print_exc()