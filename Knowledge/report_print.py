# -*- coding: utf-8 -*-
"""
Печать протокола с параметрами F, R, C0, C1, Q и Filtr_Freq.
Опирается на Temperature_Measure.Report при наличии, иначе - упрощённый PDF/CSV.
"""
from __future__ import annotations

import os
from datetime import datetime
from typing import Any, Dict, List, Optional

import pandas as pd

from .constants import PROTOCOL_PARAMS, PARAM_ALIASES, TARGET_COL


def _resolve_col(df: pd.DataFrame, param: str) -> Optional[str]:
    aliases = PARAM_ALIASES.get(param, (param,))
    cols_lower = {c.lower(): c for c in df.columns}
    for a in aliases:
        if a in df.columns:
            return a
        if a.lower() in cols_lower:
            return cols_lower[a.lower()]
    return None


def prepare_protocol_df(data_df: pd.DataFrame) -> pd.DataFrame:
    """Таблица для протокола: Number + PROTOCOL_PARAMS."""
    rows = []
    num_col = None
    for c in ("Number", "number", "Nomer", "№"):
        if c in data_df.columns:
            num_col = c
            break

    for _, row in data_df.iterrows():
        item: Dict[str, Any] = {}
        item["Number"] = row[num_col] if num_col else ""
        for p in PROTOCOL_PARAMS:
            col = _resolve_col(data_df, p)
            if col is not None:
                val = row[col]
            elif p == TARGET_COL and "Filtr_Freq_pred" in data_df.columns:
                val = row["Filtr_Freq_pred"]
            else:
                val = None
            item[p] = val
        rows.append(item)
    return pd.DataFrame(rows)


def generate_filename(measure_id: Any, extension: str = "pdf", print_version: bool = False) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = "_print" if print_version else ""
    return f"Knowledge_{measure_id}_{timestamp}{suffix}.{extension}"


def try_temperature_report(
    data_df: pd.DataFrame,
    measure_id: Any,
    view_data: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Попытка использовать Temperature_Measure.Report.create_protocol.
    Возвращает путь к файлу или None, если модуль недоступен / ошибка.
    """
    try:
        from Temperature_Measure import Report as tm_report
    except Exception as e:
        print(f"[Knowledge/report] Temperature_Measure.Report недоступен: {e}")
        return None

    try:
        import Options
        path_dir = Options.get_measure_protokol_path()
    except Exception:
        path_dir = os.getcwd()

    os.makedirs(path_dir, exist_ok=True)
    filename = generate_filename(measure_id, "pdf")
    full = os.path.join(path_dir, filename)

    proto = prepare_protocol_df(data_df)
    # status / headers / spc_map / stats - минимальные заглушки
    status_df = pd.DataFrame({"Status": ["OK"] * len(proto)})
    headers = list(proto.columns)
    spc_map: Dict[str, Any] = {}
    stats_df = pd.DataFrame()
    view = view_data or {
        "Operator": "Knowledge",
        "Protokol_Type": "Filtr_Freq",
        "MSK": "",
        "Spc": "",
    }

    try:
        # сигнатура create_protocol может отличаться - пробуем основной вариант
        tm_report.create_protocol(
            proto, status_df, headers, spc_map, view, stats_df, measure_id, filename=filename
        )
        # create_protocol сам пишет в path+filename
        candidate = os.path.join(path_dir, filename)
        if os.path.isfile(candidate):
            return candidate
        if os.path.isfile(full):
            return full
        return candidate
    except TypeError:
        # другая сигнатура - только CSV fallback
        print("[Knowledge/report] create_protocol: несовместимая сигнатура")
        return None
    except Exception as e:
        print(f"[Knowledge/report] create_protocol error: {e}")
        return None


def export_protocol_csv(data_df: pd.DataFrame, measure_id: Any, out_dir: Optional[str] = None) -> str:
    out_dir = out_dir or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    fname = generate_filename(measure_id, "csv")
    path = os.path.join(out_dir, fname)
    proto = prepare_protocol_df(data_df)
    proto.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def print_or_export(
    data_df: pd.DataFrame,
    measure_id: Any,
    view_data: Optional[Dict[str, Any]] = None,
    prefer_pdf: bool = True,
) -> str:
    """
    Основная точка входа: PDF через Report, иначе CSV.
    Возвращает путь к файлу.
    """
    if prefer_pdf:
        path = try_temperature_report(data_df, measure_id, view_data)
        if path:
            try:
                from Temperature_Measure.Report import open_pdf
                open_pdf(path)
            except Exception:
                pass
            return path
    try:
        import Options
        out_dir = Options.get_measure_protokol_path()
    except Exception:
        out_dir = os.getcwd()
    return export_protocol_csv(data_df, measure_id, out_dir)
