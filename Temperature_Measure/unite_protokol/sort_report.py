"""Печать PDF-протокола совмещения (архивный стиль)."""
import pandas as pd
from contextlib import contextmanager

import Temperature_Measure.Report as _Report
from Temperature_Measure.Report import create_protocol, open_pdf

try:
    from Temperature_Measure.Archive.Archive_Data import (
        load_specification, load_spc_map_for_archive,
        build_archive_print_data, build_archive_status_df,
        build_view_data_from_archive, get_archive_statistics,
        get_headers_dict, get_round_dict,
    )
    from Temperature_Measure.Archive.Archive_Helpers import (
        load_spc_map_otk_for_archive,
    )
except ImportError:
    from Archive_View.Archive_Data import (
        load_specification, load_spc_map_for_archive,
        build_archive_print_data, build_archive_status_df,
        build_view_data_from_archive, get_archive_statistics,
        get_headers_dict, get_round_dict,
    )
    from Archive_View.Archive_Helpers import (
        load_spc_map_otk_for_archive,
    )


_orig_format_stat = _Report.format_parameter_stat
_round_map_ctx = {'round_map': None}


def _patched_format_parameter_stat(col, metric, stats_df):
    param_stats = stats_df[stats_df['Parameter'] == col]
    if param_stats.empty:
        return '-'
    value = param_stats[metric].values[0]
    if pd.isna(value):
        return '-'
    if metric in ['Брак', 'Годные']:
        return f"{int(value)}"
    decimals = 2
    rm = _round_map_ctx.get('round_map') or {}
    if col in rm:
        try:
            decimals = int(rm[col])
        except (TypeError, ValueError):
            decimals = 2
    try:
        return f"{float(value):.{decimals}f}"
    except (TypeError, ValueError):
        return str(value)


@contextmanager
def _stat_rounding_ctx(round_map):
    _round_map_ctx['round_map'] = round_map or {}
    _Report.format_parameter_stat = _patched_format_parameter_stat
    try:
        yield
    finally:
        _Report.format_parameter_stat = _orig_format_stat
        _round_map_ctx['round_map'] = None


def _resolve_spc(merged_df: pd.DataFrame):
    if 'Spc' not in merged_df.columns:
        return None
    uniq = merged_df['Spc'].dropna().unique()
    return uniq[0] if len(uniq) > 0 else None


def _load_spc_map_for_print(spc_name: str, psi_type: str) -> pd.DataFrame:
    """Карта норм для печати: ПСИ (без техзапаса) / ОТК (с техзапасом)."""
    psi_type = psi_type if psi_type in ('ПСИ', 'ОТК') else 'ОТК'
    if psi_type == 'ОТК':
        spc_map = load_spc_map_otk_for_archive(spc_name)
        if spc_map is not None and not spc_map.empty:
            spc_map = spc_map.copy()
            if 'Max_otk' in spc_map.columns:
                spc_map['Max'] = spc_map['Max_otk']
            if 'Min_otk' in spc_map.columns:
                spc_map['Min'] = spc_map['Min_otk']
        return spc_map
    return load_spc_map_for_archive(spc_name)


def create_merged_protocol_pdf(
    merged_df: pd.DataFrame,
    measure_id,
    msk: str,
    file_name: str = None,
    program_type: str = None,
    operator: str = None,
    output_dir: str = None,
    psi_type: str = 'ОТК',
) -> str:
    """Создаёт PDF-протокол совмещения (архивный стиль) и открывает его.

    measure_id — Measure_ID сохранённого протокола (обязателен —
                 попадает в заголовок PDF и имя файла <measure_id>.pdf).
    psi_type   — 'ПСИ' / 'ОТК' (влияет только на набор норм).
    В шапке и заголовке печатается Measure_ID, никаких «Совмещение» —
    PDF полностью совпадает с обычным протоколом ПСИ/ОТК.
    """
    if merged_df is None or merged_df.empty:
        raise ValueError("merged_df пуст")

    if measure_id is None or str(measure_id).strip() == '':
        raise ValueError(
            "Не передан Measure_ID сохранённого протокола — "
            "его нельзя вывести в заголовке PDF"
        )
    try:
        mid_int = int(str(measure_id).strip())
    except (TypeError, ValueError):
        raise ValueError(
            f"Некорректный Measure_ID: {measure_id!r}"
        )

    spc_name = _resolve_spc(merged_df)
    if not spc_name:
        raise ValueError("Не удалось определить спецификацию из данных")

    spc_df = load_specification(spc_name)
    if spc_df.empty:
        raise ValueError(f"Спецификация '{spc_name}' не найдена")
    spc_row = spc_df.iloc[0]

    psi_type = psi_type if psi_type in ('ПСИ', 'ОТК') else 'ОТК'

    spc_map = _load_spc_map_for_print(spc_name, psi_type)
    if spc_map is None or spc_map.empty:
        raise ValueError(
            f"Нормы ({psi_type}) для '{spc_name}' не найдены"
        )

    data_df = build_archive_print_data(merged_df, spc_map)
    status_df = build_archive_status_df(merged_df, spc_map)
    view_data = build_view_data_from_archive(merged_df, spc_row)
    stats_df = get_archive_statistics(merged_df, spc_map)
    headers = get_headers_dict(spc_map)
    round_map = get_round_dict(spc_map)

    # ▼ В шапке — обычный тип протокола, без упоминания «Совмещение»
    view_data['Protokol_Type'] = psi_type
    if msk:
        view_data['MSK'] = msk
        view_data['Full_Msk'] = msk
    if file_name:
        view_data['FileName'] = file_name
    if program_type:
        view_data['Machine_Type'] = program_type
    if operator:
        view_data['Operator'] = operator

    # ▼ Имя файла — по Measure_ID
    if output_dir:
        import os
        filename = os.path.join(output_dir, f"{mid_int}.pdf")
    else:
        filename = f"{mid_int}.pdf"

    with _stat_rounding_ctx(round_map):
        path = create_protocol(
            data_df=data_df,
            status_df=status_df,
            headers=headers,
            spc_map=spc_map,
            view_data=view_data,
            stats_df=stats_df,
            measure_id=mid_int,        # ← Measure_ID в заголовке PDF
            filename=filename,
        )
    open_pdf(path)
    return path