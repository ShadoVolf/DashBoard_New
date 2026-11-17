import pandas as pd
import dearpygui.dearpygui as dpg
from sqlalchemy import create_engine

from Options import get_connection_string
from Temperature_Measure import _layout


def apply_cell_color(row_data, column):
    if column in ['Status', 'Positions', 'Numbers']:
        return ([255, 255, 0, 255] if row_data.get('Status') == 'Брак'
                else [255, 255, 255, 255])
    status_col = f"{column}_status"
    if status_col in row_data:
        return [255, 0, 0, 255] if not row_data[status_col] else [255, 255, 255, 255]
    return [255, 255, 255, 255]


def create_measure_table_window(dpg, data, data_status: pd.DataFrame,
                                 spc: pd.DataFrame):
    engine = create_engine(get_connection_string())
    sql = "SELECT `Parameter_Name`, `Note_mini` FROM `spc_map_table`"
    spc_map = pd.read_sql(sql, engine)

    pos, size = _layout.dialog_rect(fraction_w=0.72, fraction_h=0.82,
                                    min_w=800, min_h=600,
                                    max_w=1500, max_h=1200)
    create_spc_table_window(dpg, spc, spc_map, main_pos=pos,
                             main_size=size)

    header_mapping = dict(zip(spc_map['Parameter_Name'],
                              spc_map['Note_mini']))

    data_merged = data.drop(columns=['Status', 'Anomal_Status', 'Status2'],
                            errors='ignore')
    data_status = data_status.drop(columns=['Error_Code'], errors='ignore')
    merged_data = pd.merge(data_merged, data_status,
                           on=['Positions', 'Numbers'], how='left')
    merged_data['Status'] = merged_data['Status'].map(
        {True: 'Годен', False: 'Брак'})

    displayed_columns = []
    for col in merged_data.columns:
        if col in ['Status', 'Positions', 'Numbers', 'Status2']:
            displayed_columns.append({
                'original': col,
                'display': 'Статус' if col == 'Status' else
                           'Позиция' if col == 'Positions' else
                           'Номер' if col == 'Numbers' else 'Измерение',
            })
        else:
            if not col.endswith('_status') and col not in ('SETUPNUM',
                                                            'Position_index'):
                displayed_columns.append({
                    'original': col,
                    'display': header_mapping.get(col, col),
                })

    with dpg.window(label="Таблица измерений", width=size[0],
                    height=size[1], pos=pos,
                    tag='measure_data_table_window'):
        with dpg.table(header_row=True, resizable=True,
                       borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, tag='measure_data_table'):
            for col_info in displayed_columns:
                dpg.add_table_column(label=col_info['display'])

            for _, row in merged_data.iterrows():
                with dpg.table_row(parent='measure_data_table'):
                    for col_info in displayed_columns:
                        cell_value = row[col_info['original']]
                        color = apply_cell_color(row.to_dict(),
                                                  col_info['original'])
                        dpg.add_text(str(cell_value), color=color)


def create_spc_table_window(dpg, spc, spc_map, main_pos=None,
                             main_size=None):
    header_mapping = dict(zip(spc_map['Parameter_Name'],
                              spc_map['Note_mini']))

    spc_display = spc.copy()
    spc_display['Parameter'] = spc['Parameter'].map(header_mapping).fillna(
        spc['Parameter'])
    spc_display = spc_display[['Parameter', 'Max', 'Min']].fillna('---')

    sw, sh = _layout.screen_size()
    norms_w = max(280, min(420, int(sw * 0.20)))
    norms_h = max(240, min(400, int(sh * 0.35)))

    if main_pos and main_size:
        norms_x = main_pos[0] + main_size[0] + 10
        if norms_x + norms_w > sw - 10:
            norms_x = max(10, main_pos[0] - norms_w - 10)
        norms_y = main_pos[1]
    else:
        norms_x = max(10, sw - norms_w - 10)
        norms_y = 60

    with dpg.window(label="Нормы параметров",
                    width=norms_w, height=norms_h,
                    pos=(norms_x, norms_y)):
        with dpg.table(header_row=True, borders_innerH=True,
                       borders_outerH=True, borders_innerV=True):
            header_translations = {'Parameter': 'Параметр',
                                    'Max': 'Макс', 'Min': 'Мин'}
            for column in spc_display.columns:
                dpg.add_table_column(
                    label=header_translations.get(column, column))

            for _, row in spc_display.iterrows():
                with dpg.table_row():
                    for col in spc_display.columns:
                        cell_value = row[col]
                        if isinstance(cell_value, float):
                            cell_value = (f"{cell_value:.3f}"
                                          if cell_value % 1
                                          else f"{cell_value:.0f}")
                        else:
                            cell_value = str(cell_value)
                        color = ([0, 255, 0, 255] if col == 'Parameter'
                                 else [255, 0, 0, 255])
                        dpg.add_text(cell_value, color=color)