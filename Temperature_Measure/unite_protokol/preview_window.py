"""Просмотр DataFrame с колонками только по спецификации + таблица норм."""
import pandas as pd
import dearpygui.dearpygui as dpg

from Temperature_Measure import _layout

try:
    from Archive_View.Archive_Data import (
        load_spc_map_for_archive, rename_fields_to_parameters, apply_rounding,
    )
except ImportError:
    from Archive_View.Archive_Data import (
        load_spc_map_for_archive, rename_fields_to_parameters, apply_rounding,
    )


def open_spec_preview(title, df, spc_name, tag="spec_preview_window",
                      note=None):
    """Открывает окно просмотра: слева — данные по спецификации,
    справа — нормы (Max/Min). Если спецификация не задана или не
    совпала ни одна колонка, показываются все колонки без норм."""
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)

    if df is None or df.empty:
        _open_empty_preview(title, tag, "Нет данных для отображения")
        return

    spc_map = load_spc_map_for_archive(spc_name) if spc_name else pd.DataFrame()
    mapped = rename_fields_to_parameters(df)
    if not spc_map.empty:
        mapped = apply_rounding(mapped, spc_map)

    has_spec = _has_spec_params(mapped, spc_map)
    display_cols = _get_display_columns(mapped, spc_map, show_all=not has_spec)
    if not display_cols:
        _open_empty_preview(title, tag, "Нет столбцов для отображения")
        return

    df_display = mapped[[c for c, _ in display_cols]].copy()
    df_display.columns = [label for _, label in display_cols]

    sw, sh = _layout.screen_size()
    w = max(900, min(1700, int(sw * 0.88))) if has_spec \
        else max(700, min(1400, int(sw * 0.72)))
    h = max(500, min(1000, int(sh * 0.82)))
    pos = (max(10, (sw - w) // 2), max(10, (sh - h) // 2))

    right_w = 320 if has_spec else 0
    left_w = w - right_w - (24 if has_spec else 8)

    with dpg.window(label=title, tag=tag, width=w, height=h, pos=pos,
                    no_collapse=True):
        if note:
            dpg.add_text(note, color=(150, 150, 150))
        dpg.add_text(
            f"Строк: {len(mapped)}   |   Спецификация: "
            f"{spc_name or '—'}",
            color=(180, 180, 180),
        )
        dpg.add_separator()

        with dpg.group(horizontal=True):
            with dpg.child_window(width=left_w, height=-40, border=True):
                _build_data_table(df_display, tag=f"{tag}_data")
            if has_spec:
                with dpg.child_window(width=right_w, height=-40,
                                      border=True):
                    dpg.add_text("Нормы спецификации",
                                 color=(180, 220, 255))
                    dpg.add_separator()
                    _build_norms_table(spc_map, tag=f"{tag}_norms")

        dpg.add_separator()
        dpg.add_button(label="Закрыть",
                       callback=lambda: dpg.delete_item(tag), width=120)


def _open_empty_preview(title, tag, message):
    sw, sh = _layout.screen_size()
    w, h = 420, 150
    pos = ((sw - w) // 2, (sh - h) // 2)
    with dpg.window(label=title, tag=tag, width=w, height=h, pos=pos):
        dpg.add_text(message, color=(160, 160, 160))
        dpg.add_button(label="Закрыть",
                       callback=lambda: dpg.delete_item(tag), width=120)


def _has_spec_params(mapped, spc_map):
    if spc_map is None or spc_map.empty:
        return False
    return any(
        item['Parameter'] in mapped.columns
        for _, item in spc_map.iterrows()
    )


def _get_display_columns(mapped, spc_map, show_all=False):
    cols = []
    for src, label in (('Position', 'Позиция'),
                       ('Positions', 'Позиция'),
                       ('N', 'N'), ('Numbers', 'N'),
                       ('MSK', 'МСК'), ('Measure_ID', 'ID'),
                       ('Status2', 'Статус')):
        if src in mapped.columns and not any(c[0] == src for c in cols):
            # не добавлять 'Positions', если уже есть 'Position'
            if src == 'Positions' and any(c[0] == 'Position' for c in cols):
                continue
            if src == 'Numbers' and any(c[0] == 'N' for c in cols):
                continue
            cols.append((src, label))

    if show_all or spc_map is None or spc_map.empty:
        existing = {c[0] for c in cols}
        for c in mapped.columns:
            if c not in existing:
                cols.append((c, c))
        return cols

    ordered = (spc_map.sort_values('Order')
               if 'Order' in spc_map.columns else spc_map)
    for _, item in ordered.iterrows():
        param = item['Parameter']
        if param in mapped.columns:
            label = item.get('Note_mini') or item.get('Note') or param
            cols.append((param, str(label)))
    return cols


def _build_data_table(df, tag):
    if df is None or df.empty:
        dpg.add_text("- нет данных -", color=(140, 140, 140))
        return
    with dpg.table(tag=tag, header_row=True, borders_innerH=True,
                   borders_outerH=True, borders_innerV=True,
                   borders_outerV=True, resizable=True,
                   scrollX=True, scrollY=True,
                   policy=dpg.mvTable_SizingFixedFit,
                   freeze_rows=1, height=-1):
        for col in df.columns:
            dpg.add_table_column(label=str(col))
        for _, row in df.iterrows():
            with dpg.table_row():
                for val in row.values:
                    dpg.add_text(_fmt(val))


def _build_norms_table(spc_map, tag):
    if spc_map is None or spc_map.empty:
        dpg.add_text("- нормы не заданы -", color=(140, 140, 140))
        return
    if 'Order' in spc_map.columns:
        spc_map = spc_map.sort_values('Order')
    with dpg.table(tag=tag, header_row=True, borders_innerH=True,
                   borders_outerH=True, borders_innerV=True,
                   policy=dpg.mvTable_SizingStretchProp):
        dpg.add_table_column(label='Параметр')
        dpg.add_table_column(label='Макс')
        dpg.add_table_column(label='Мин')
        for _, row in spc_map.iterrows():
            label = (row.get('Note_mini') or row.get('Note')
                     or row['Parameter'])
            mx, mn = row['Max'], row['Min']
            with dpg.table_row():
                dpg.add_text(str(label))
                dpg.add_text(f'{mx:.4g}'
                             if mx is not None and not pd.isna(mx) else '-')
                dpg.add_text(f'{mn:.4g}'
                             if mn is not None and not pd.isna(mn) else '-')


def _fmt(val):
    if val is None or (isinstance(val, float) and pd.isna(val)):
        return ""
    if isinstance(val, float):
        return f"{val:.4g}"
    return str(val)