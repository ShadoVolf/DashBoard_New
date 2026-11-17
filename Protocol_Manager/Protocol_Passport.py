"""Печать паспорта изделия по архивному протоколу.

Использует Temperature_Measure.Report.create_passport_protocol.
Один PDF на номер; если есть pypdf/PyPDF2 — склеивается
в один файл, иначе открывается первый паспорт.
"""
from __future__ import annotations

import os

import pandas as pd

from Temperature_Measure.Report import (
    create_passport_protocol,
    load_passport_config_from_tu,
    open_pdf,
    generate_filename,
)
from Archive_View.Archive_Data import (
    load_specification, load_tu_parameters_for_spec, build_presentation_params,
    build_archive_print_data, build_archive_status_df,
    build_view_data_from_archive, _prepare_spc_map,
)
from Archive_View.Archive_UI import _load_spc_map_for_display
from .Protocol_Print import _engine, _nat_sort_key, _status
from .Protocol_Data import log_action


def _merge_pdfs(paths, out_path):
    writer_cls = reader_cls = None
    try:
        from pypdf import PdfWriter, PdfReader
        writer_cls, reader_cls = PdfWriter, PdfReader
    except Exception:
        try:
            from PyPDF2 import PdfWriter, PdfReader
            writer_cls, reader_cls = PdfWriter, PdfReader
        except Exception:
            return None
    w = writer_cls()
    for p in paths:
        if p and os.path.isfile(p):
            w.append(reader_cls(p))
    with open(out_path, 'wb') as f:
        w.write(f)
    return out_path


def print_passport_for_protocol(protokol_id: int):
    """Паспорт на каждый номер архивного протокола."""
    engine = _engine()
    with engine.connect() as conn:
        df_head = pd.read_sql(
            "SELECT * FROM psi_measure_protokol_id "
            "WHERE Measure_protokol_ID = %(pid)s",
            conn, params={'pid': int(protokol_id)})
    if df_head is None or df_head.empty:
        _status('Протокол не найден')
        return {'error': 'Протокол не найден'}

    p_info = df_head.iloc[0]
    measure_id = p_info['Measure_ID']
    protokol_n = p_info['ProtokolN']
    psi_type = 'ОТК'
    if 'psi_type' in p_info.index:
        v = p_info.get('psi_type')
        if v is not None and not pd.isna(v) and str(v).strip():
            psi_type = str(v).strip()
    if psi_type not in ('ПСИ', 'ОТК'):
        psi_type = 'ОТК'

    with engine.connect() as conn:
        df = pd.read_sql(
            "SELECT * FROM psi_protokol_archive "
            "WHERE Measure_Protokol_ID = %(pid)s",
            conn, params={'pid': int(protokol_id)})
    if df is None or df.empty:
        _status('В протоколе нет номеров')
        return {'error': 'В протоколе нет номеров'}

    if 'N' in df.columns:
        df['_sort_key'] = df['N'].map(_nat_sort_key)
        df = (df.sort_values('_sort_key')
                .drop(columns=['_sort_key'])
                .reset_index(drop=True))

    spc_val = None
    if 'Spc' in df.columns:
        v = df.iloc[0].get('Spc')
        if v is not None and not pd.isna(v):
            spc_val = str(v).strip() or None
    if not spc_val and 'Spc' in p_info.index:
        hv = p_info.get('Spc')
        if hv is not None and not pd.isna(hv):
            spc_val = str(hv).strip() or None
    if not spc_val:
        _status('Не удалось определить спецификацию')
        return {'error': 'Нет спецификации'}

    spc_df = load_specification(spc_val)
    if spc_df is None or spc_df.empty:
        _status(f'Спецификация "{spc_val}" не найдена')
        return {'error': f'Спецификация {spc_val} не найдена'}
    spc_row = spc_df.iloc[0]

    tu_data = load_tu_parameters_for_spec(spc_val) or {
        'tu_name': '', 'tu_row': {}, 'rtype': ''}
    presentation_params = build_presentation_params(spc_val, tu_data) or []
    spc_map = _prepare_spc_map(_load_spc_map_for_display(spc_val, psi_type))
    cfg = load_passport_config_from_tu(tu_data.get('tu_row') or {})
    if cfg.get('presentation_params'):
        presentation_params = cfg['presentation_params']

    def _s(v):
        if v is None:
            return ''
        try:
            if pd.isna(v):
                return ''
        except (TypeError, ValueError):
            pass
        return str(v)

    paths = []
    for _, row in df.iterrows():
        one = df.loc[[row.name]].copy()
        data_df = build_archive_print_data(one, spc_map)
        view_data = build_view_data_from_archive(one, spc_row, psi_type=psi_type)
        view_data['TU'] = _s(spc_row.get('TU'))
        view_data['TGK'] = _s(spc_row.get('TGK'))
        view_data['Spc_Text'] = _s(spc_row.get('Text')) or spc_val
        view_data['Date'] = _s(row.get('Date'))
        num = _s(row.get('N')) or 'item'
        fname = generate_filename(measure_id).replace(
            '.pdf', f'_passport_{num}.pdf')
        path = create_passport_protocol(
            data_df=data_df,
            view_data=view_data,
            tu_data=tu_data,
            presentation_params=presentation_params,
            spc_row=spc_row,
            measure_id=measure_id,
            filename=fname,
            measure_protokol_id=int(protokol_id),
            pinout_images=cfg.get('pinout_images'),
            additional_lines=cfg.get('additional_lines'),
            power_dissipation=cfg.get('power_dissipation'),
        )
        paths.append(path)

    out = paths[0] if paths else None
    if len(paths) > 1:
        merged_name = generate_filename(measure_id).replace(
            '.pdf', f'_passports_{protokol_n}.pdf')
        # create_passport_protocol сам добавляет каталог протоколов
        base = os.path.dirname(paths[0]) if paths[0] else ''
        merged = _merge_pdfs(paths, os.path.join(base, os.path.basename(merged_name))) \
            if base else None
        if merged:
            out = merged

    if out:
        open_pdf(out)
    _status(f'Паспорт: {len(paths)} шт. (протокол N {protokol_n})')
    try:
        log_action('PRINT_PASSPORT', int(protokol_id), measure_id,
                   f'Паспорт {len(paths)} шт.', 'Assistant')
    except Exception:
        pass
    return {'action': 'printed', 'count': len(paths), 'path': out,
            'protokol_id': int(protokol_id)}
