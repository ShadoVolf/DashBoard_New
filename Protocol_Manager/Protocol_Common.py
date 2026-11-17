"""Хелперы статуса, модальные диалоги, общие display-функции."""
import pandas as pd
import dearpygui.dearpygui as dpg

from Temperature_Measure import _layout
from Archive_View.Archive_Data import (
    rename_fields_to_parameters, resolve_param_column,
    apply_rounding, build_archive_status_df,
    load_spc_map_for_archive, log_missing_params,
)
from Archive_View.Archive_Helpers import load_spc_map_otk_for_archive
from Archive_View.Archive_UI import _screen_safe

from . import Protocol_Constants as _C

# ============================================================================
# Кэш параметров представления (см. Presentation_Cache.py)
# ============================================================================
from .Presentation_Cache import get_or_build_presentation_params, \
                                  clear as _pres_cache_clear

__all__ = [
    '_pm_status', '_pm_arch_status',
    '_show_dialog', '_show_warning', '_show_info',
    '_pm_current_psi_type', '_pm_load_spc_map_for_display',
    '_pm_resolve_display_spc', '_build_display_cols', '_render_data_table',
    '_pm_fill_norms', '_pm_fill_arch_norms', '_pm_fill_info',
    '_pm_fill_arch_info',
    'get_or_build_presentation_params', 'clear_presentation_params_cache',
]


def clear_presentation_params_cache():
    """Сбросить кэш параметров представления протокола."""
    _pres_cache_clear()
# ============================================================================
# Хелперы статуса
# ============================================================================
def _pm_status(msg):
    if dpg.does_item_exist(_C.PM_STATUS_TAG):
        dpg.set_value(_C.PM_STATUS_TAG, _screen_safe(str(msg)))


def _pm_arch_status(msg):
    if dpg.does_item_exist(_C.PM_ARCH_STATUS_TAG):
        dpg.set_value(_C.PM_ARCH_STATUS_TAG, _screen_safe(str(msg)))


# ============================================================================
# Модальные диалоги
# ============================================================================
def _show_dialog(tag: str, title: str, message: str,
                 width: int = 560, height: int = None):
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)

    if height is None:
        lines = message.count('\n') + 1 + len(message) // max(40, width // 8)
        height = max(200, min(700, 100 + lines * 20))

    try:
        sw, sh = _layout.screen_size()
    except Exception:
        sw, sh = 1920, 1080
    pos = (max(20, (sw - width) // 2), max(20, (sh - height) // 2))
    with dpg.window(label=title, tag=tag, modal=True,
                    width=width, height=height, pos=pos):
        dpg.add_text(message, wrap=width - 40)
        dpg.add_spacer(height=10)
        with dpg.group(horizontal=True):
            dpg.add_button(label="OK", width=120,
                           callback=lambda: dpg.delete_item(tag))


def _show_warning(title: str, message: str):
    _show_dialog(_C.PM_WARN_DIALOG, "Внимание - " + title, message)


def _show_info(title: str, message: str):
    _show_dialog(_C.PM_INFO_DIALOG, "Готово - " + title, message)


# ============================================================================
# Отображение: SPC-нормы
# ============================================================================
def _pm_current_psi_type() -> str:
    if dpg.does_item_exist('pm_psi_type_combo'):
        v = dpg.get_value('pm_psi_type_combo')
        if v in ('ПСИ', 'ОТК'):
            return v
    return 'ОТК'


def _pm_load_spc_map_for_display(spc_name: str, psi_type: str) -> pd.DataFrame:
    if not spc_name:
        return pd.DataFrame()
    if psi_type == 'ОТК':
        spc_map = load_spc_map_otk_for_archive(spc_name)
        if not spc_map.empty:
            spc_map = spc_map.copy()
            if 'Max_otk' in spc_map.columns:
                spc_map['Max'] = spc_map['Max_otk']
            if 'Min_otk' in spc_map.columns:
                spc_map['Min'] = spc_map['Min_otk']
        return spc_map
    return load_spc_map_for_archive(spc_name)


def _pm_resolve_display_spc(df) -> str:
    cur = dpg.get_value('pm_spc_combo') or ''
    if df is None or df.empty or 'Spc' not in df.columns:
        return cur
    uniq = [str(s) for s in df['Spc'].dropna().unique() if s]
    if not uniq:
        return cur
    if len(uniq) == 1:
        result = uniq[0]
    elif cur in uniq:
        result = cur
    else:
        try:
            result = str(df['Spc'].value_counts().idxmax())
        except Exception:
            result = uniq[0]
    try:
        dpg.set_value('pm_spc_combo', result)
    except Exception:
        pass
    return result


# ============================================================================
# Отображение: колонки и таблица
# ============================================================================
def _build_display_cols(df, spc_map, is_archive=False):
    mapped = rename_fields_to_parameters(df)
    cols = []
    if 'Position' in mapped.columns:
        cols.append(('Position', 'Позиция', None))
    elif 'Positions' in mapped.columns:
        cols.append(('Positions', 'Позиция', None))
    if 'N' in mapped.columns:
        cols.append(('N', 'N', None))
    elif 'Numbers' in mapped.columns:
        cols.append(('Numbers', 'N', None))
    if not is_archive:
        if 'MSK' in mapped.columns and mapped['MSK'].dropna().nunique() > 1:
            cols.append(('MSK', 'МСК', None))
        if ('Measure_ID' in mapped.columns
                and mapped['Measure_ID'].dropna().nunique() > 1):
            cols.append(('Measure_ID', 'ID', None))
    if not spc_map.empty:
        ordered = (spc_map.sort_values('Order')
                   if 'Order' in spc_map.columns else spc_map)
        for _, spc_item in ordered.iterrows():
            param = spc_item['Parameter']
            col = resolve_param_column(mapped, param, spc_item)
            if col is None:
                continue
            label = (spc_item.get('Note_mini')
                     or spc_item.get('Note') or param)
            cols.append((col, str(label), param))
    cols.append(('__status__', 'Статус', None))
    return cols


def _render_data_table(df, parent_container, table_tag, spc_map,
                       display_cols, with_checkbox=False):
    mapped = rename_fields_to_parameters(df)
    spec_status = build_archive_status_df(df, spc_map)
    overall_ok = spec_status['Status'].tolist()
    param_ok = {
        c[:-len('_status')]: spec_status[c].tolist()
        for c in spec_status.columns
        if c.endswith('_status') and not c.endswith('_anomal_status')
    }
    if not spc_map.empty:
        mapped = apply_rounding(mapped, spc_map)

    ROW_BAD_COLOR   = (255, 220, 100)
    PARAM_BAD_COLOR = (255,  90,  90)
    STATUS_GOOD     = (100, 220, 100)
    STATUS_BAD      = (255,  90,  90)

    n_col   = ('N' if 'N' in mapped.columns
               else ('Numbers' if 'Numbers' in mapped.columns else None))
    mid_col = 'Measure_ID' if 'Measure_ID' in mapped.columns else None

    with dpg.table(tag=table_tag, parent=parent_container,
                   header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True,
                   resizable=True, scrollX=True, scrollY=True,
                   policy=dpg.mvTable_SizingFixedFit, height=-1):
        if with_checkbox:
            dpg.add_table_column(label='Выбрать', width_fixed=True,
                                 init_width_or_weight=60)
        for _, label, _ in display_cols:
            dpg.add_table_column(label=_screen_safe(label))

        for pos_idx, (_, row) in enumerate(mapped.iterrows()):
            is_rejected = not overall_ok[pos_idx]
            with dpg.table_row():
                if with_checkbox:
                    n_raw = row.get(n_col) if n_col else None
                    try:
                        if n_raw is None or pd.isna(n_raw):
                            n_raw = ''
                    except (TypeError, ValueError):
                        pass
                    mid_raw = row.get(mid_col) if mid_col else None
                    try:
                        mid_val = (int(mid_raw)
                                   if mid_raw is not None
                                   and not pd.isna(mid_raw) else None)
                    except (TypeError, ValueError):
                        mid_val = None

                    if n_raw != '':
                        _C._selected_numbers[pos_idx] = (mid_val, n_raw)
                        dpg.add_checkbox(tag=f'pm_sel_{pos_idx}',
                                         default_value=True)
                    else:
                        dpg.add_text('')

                for key, _, param_name in display_cols:
                    if key == '__status__':
                        if spc_map.empty:
                            dpg.add_text('-', color=(140, 140, 140))
                        elif is_rejected:
                            dpg.add_text('Брак', color=STATUS_BAD)
                        else:
                            dpg.add_text('Годен', color=STATUS_GOOD)
                        continue

                    val = row.get(key, '')
                    if pd.isna(val):
                        val = ''
                    text = _screen_safe(val)
                    color = None
                    if param_name and param_name in param_ok:
                        if not param_ok[param_name][pos_idx]:
                            color = PARAM_BAD_COLOR
                        elif is_rejected:
                            color = ROW_BAD_COLOR
                    elif is_rejected:
                        color = ROW_BAD_COLOR

                    if color:
                        dpg.add_text(text, color=color)
                    else:
                        dpg.add_text(text)


# ============================================================================
# Отображение: панель норм
# ============================================================================
def _pm_fill_norms(spc_name: str):
    if dpg.does_item_exist(_C.PM_NORMS_GROUP):
        for ch in dpg.get_item_children(_C.PM_NORMS_GROUP, 1) or []:
            dpg.delete_item(ch)

    if not spc_name:
        dpg.add_text("- спецификация не выбрана -",
                     parent=_C.PM_NORMS_GROUP, tag='pm_norms_hint',
                     color=(140, 140, 140))
        return

    psi_type = _pm_current_psi_type()
    spc_map = _pm_load_spc_map_for_display(spc_name, psi_type)
    if spc_map.empty:
        dpg.add_text(f"- нормы для '{_screen_safe(spc_name)}' не заданы -",
                     parent=_C.PM_NORMS_GROUP, tag='pm_norms_hint',
                     color=(140, 140, 140))
        return

    if 'Order' in spc_map.columns:
        spc_map = spc_map.sort_values('Order')

    with dpg.table(tag=_C.PM_NORMS_TAG, parent=_C.PM_NORMS_GROUP,
                   header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True,
                   policy=dpg.mvTable_SizingStretchProp):
        dpg.add_table_column(label='Параметр')
        dpg.add_table_column(label='Макс')
        dpg.add_table_column(label='Мин')
        for _, r in spc_map.iterrows():
            label = r.get('Note_mini') or r.get('Note') or r['Parameter']
            mx = r['Max']
            mn = r['Min']
            with dpg.table_row():
                dpg.add_text(_screen_safe(label))
                dpg.add_text(f'{mx:.4g}'
                             if mx is not None and not pd.isna(mx) else '-')
                dpg.add_text(f'{mn:.4g}'
                             if mn is not None and not pd.isna(mn) else '-')


def _pm_fill_arch_norms(spc_name, psi_type='ОТК'):
    if dpg.does_item_exist(_C.PM_ARCH_NORMS_GROUP):
        for ch in dpg.get_item_children(_C.PM_ARCH_NORMS_GROUP, 1) or []:
            dpg.delete_item(ch)

    if not spc_name:
        dpg.add_text("- спецификация не выбрана -",
                     parent=_C.PM_ARCH_NORMS_GROUP, tag='pm_arch_norms_hint',
                     color=(140, 140, 140))
        return

    spc_map = _pm_load_spc_map_for_display(spc_name, psi_type)
    if spc_map.empty:
        dpg.add_text(f"- нормы для '{_screen_safe(spc_name)}' не заданы -",
                     parent=_C.PM_ARCH_NORMS_GROUP, tag='pm_arch_norms_hint',
                     color=(140, 140, 140))
        return

    if 'Order' in spc_map.columns:
        spc_map = spc_map.sort_values('Order')

    with dpg.table(tag=_C.PM_ARCH_NORMS_TAG, parent=_C.PM_ARCH_NORMS_GROUP,
                   header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True,
                   policy=dpg.mvTable_SizingStretchProp):
        dpg.add_table_column(label='Параметр')
        dpg.add_table_column(label='Макс')
        dpg.add_table_column(label='Мин')
        for _, r in spc_map.iterrows():
            label = r.get('Note_mini') or r.get('Note') or r['Parameter']
            mx = r['Max']
            mn = r['Min']
            with dpg.table_row():
                dpg.add_text(_screen_safe(label))
                dpg.add_text(f'{mx:.4g}'
                             if mx is not None and not pd.isna(mx) else '-')
                dpg.add_text(f'{mn:.4g}'
                             if mn is not None and not pd.isna(mn) else '-')


# ============================================================================
# Отображение: информационные панели
# ============================================================================
def _pm_fill_info(df):
    info = {}
    if df is not None and not df.empty:
        row = df.iloc[0]
        info = {
            'MSK': row.get('MSK', ''),
            'File': row.get('File', ''),
            'Spc': row.get('Spc', ''),
            'Date': row.get('Date', ''),
            'Time': row.get('Time', ''),
            'Measure_ID': row.get('Measure_ID', ''),
            'Count': len(df),
        }
        if 'Measure_ID' in df.columns:
            uniq = df['Measure_ID'].dropna().unique()
            if len(uniq) > 1:
                info['Measure_ID'] = f'Несколько ({len(uniq)})'
        if 'MSK' in df.columns:
            uniq = df['MSK'].dropna().unique()
            if len(uniq) > 1:
                info['MSK'] = f'{_C.ARCH_ALL_FILES} ({len(uniq)})'

    for key, tag in [
        ('MSK', 'pm_info_msk'), ('File', 'pm_info_file'),
        ('Spc', 'pm_info_spc'), ('Date', 'pm_info_date'),
        ('Time', 'pm_info_time'), ('Measure_ID', 'pm_info_measure_id'),
        ('Count', 'pm_info_count'),
    ]:
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, _screen_safe(info.get(key, '')))


def _pm_fill_arch_info(df, header=None):
    info = {}

    if header:
        info['Protokol_ID'] = header.get('Measure_protokol_ID', '')
        info['ProtokolN']   = header.get('ProtokolN', '')
        info['MSK']         = header.get('MSK', '')
        info['Spc']         = header.get('Spc', '')
        info['Measure_ID']  = header.get('Measure_ID', '')
        info['dataR']       = header.get('dataR', '')

    if df is not None and not df.empty:
        row = df.iloc[0]
        for k_src, k_dst in [
            ('MSK', 'MSK'), ('Spc', 'Spc'),
            ('Date', 'Date'), ('Measure_ID', 'Measure_ID'),
        ]:
            if not info.get(k_dst):
                info[k_dst] = row.get(k_src, '')
        info['Count'] = len(df)

    info.setdefault('Protokol_ID', _C._active_archive_id or '')

    for key, tag in [
        ('Protokol_ID', 'pm_arch_info_protokol_id'),
        ('ProtokolN',   'pm_arch_info_protokol_n'),
        ('MSK',         'pm_arch_info_msk'),
        ('Spc',         'pm_arch_info_spc'),
        ('dataR',       'pm_arch_info_date'),
        ('Measure_ID',  'pm_arch_info_measure_id'),
        ('Count',       'pm_arch_info_count'),
    ]:
        if dpg.does_item_exist(tag):
            dpg.set_value(tag, _screen_safe(info.get(key, '')))