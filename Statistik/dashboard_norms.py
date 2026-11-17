"""Обновление таблицы норм и вертикальных линий границ на графиках."""
import numpy as np
import dearpygui.dearpygui as dpg

import Statistik.Data
from Statistik.Operations import get_spc_norms

def update_spc_norm(dpg_):
    """Обновить таблицу норм и вертикальные линии на графиках.

    Устойчиво к:
      * отсутствию окна 'Filtr' (закрыто пользователем);
      * отсутствию полей 'spc_select' / 'measure_select';
      * отсутствию норм для параметра (пустой dict, неполные ключи);
      * отсутствию графика ('y_axis' / 'y_axis_msk');
      * нечисловым значениям норм (строки, 'no', NaN).
    """
    # ---- 1. Проверка окружения ----
    if not dpg_.does_item_exist('Filtr'):
        return
    if not dpg_.does_item_exist('spc_select'):
        return
    if not dpg_.does_item_exist('measure_select'):
        return

    parameytr_name = dpg_.get_value('measure_select')
    if not parameytr_name:
        return

    # ---- 2. Загрузка норм (без падения) ----
    spc_value = dpg_.get_value('spc_select')
    try:
        get_spc_norms(spc_value)
    except Exception as e:
        print(f'[update_spc_norm] get_spc_norms({spc_value!r}): {e}')

    # ---- 3. Пересборка таблицы норм ----
    if dpg_.does_item_exist('spc_norm_table'):
        dpg_.delete_item('spc_norm_table')

    with dpg_.table(header_row=True, row_background=True, parent='Filtr',
                    borders_innerH=True, borders_outerH=True,
                    borders_innerV=True, borders_outerV=True,
                    user_data=dpg_, tag='spc_norm_table', label='Нормы'):
        dpg_.add_table_column(label='Параметр')
        dpg_.add_table_column(label='Норма снизу')
        dpg_.add_table_column(label='Норма сверху')

    # ---- 4. Безопасное чтение норм для выбранного параметра ----
    try:
        spc_norm_par = Statistik.Data.Data.get_spc_norm(parameytr_name)
    except (KeyError, TypeError):
        spc_norm_par = {}
    if not isinstance(spc_norm_par, dict):
        spc_norm_par = {}

    norm_min_raw = spc_norm_par.get(parameytr_name + 'min')
    norm_max_raw = spc_norm_par.get(parameytr_name + 'max')

    with dpg_.table_row(parent='spc_norm_table'):
        dpg_.add_text(parameytr_name)
        dpg_.add_text('-' if norm_min_raw is None else str(norm_min_raw))
        dpg_.add_text('-' if norm_max_raw is None else str(norm_max_raw))

    # ---- 5. Чистим старые линии (все 4 алиаса) ----
    for alias in ('Norm_Max', 'Norm_Min',
                  'Norm_Max_msk', 'Norm_Min_msk'):
        if dpg_.does_item_exist(alias):
            try:
                dpg_.delete_item(alias)
            except Exception as e:
                print(f'[update_spc_norm] delete {alias}: {e}')

    # ---- 6. Нечего рисовать ----
    if norm_max_raw is None and norm_min_raw is None:
        return

    # ---- 7. Рисуем вертикальные линии ----
    has_main = dpg_.does_item_exist('y_axis')
    has_msk = dpg_.does_item_exist('y_axis_msk')
    if not has_main and not has_msk:
        return

    try:
        y_max = Statistik.Data.Data.get_axis_limits().get('Y_Max') or 0.5
        y_max = float(y_max)
        if y_max <= 0:
            y_max = 0.5
    except (TypeError, ValueError):
        y_max = 0.5
    y = np.linspace(0, y_max, 100)

    def _num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    nmax = _num(norm_max_raw)
    nmin = _num(norm_min_raw)

    try:
        # --- верхняя граница ---
        if nmax is not None:
            x = [nmax for _ in range(100)]
            if has_main:
                dpg_.add_line_series(x, y, parent='y_axis',
                                     tag='Norm_Max',
                                     label='Граница сверху')
            if has_msk:
                dpg_.add_line_series(x, y, parent='y_axis_msk',
                                     tag='Norm_Max_msk',
                                     label='Граница сверху')

        # --- нижняя граница ---
        if nmin is not None:
            x = [nmin for _ in range(100)]
            if has_main:
                dpg_.add_line_series(x, y, parent='y_axis',
                                     tag='Norm_Min',
                                     label='Граница снизу')
            if has_msk:
                dpg_.add_line_series(x, y, parent='y_axis_msk',
                                     tag='Norm_Min_msk',
                                     label='Граница снизу')

        # --- пересчёт осей для графика МСК (только один раз) ---
        if has_msk and (nmax is not None or nmin is not None):
            dpg_.set_axis_limits_auto('x_axis_msk')
            dpg_.set_axis_limits_auto('y_axis_msk')
            dpg_.fit_axis_data('x_axis_msk')
            dpg_.fit_axis_data('y_axis_msk')
    except Exception as e:
        print(f'[update_spc_norm] draw norm lines: {e}')

def update_spc_norm_1(dpg_):
    if not dpg_.does_item_exist('spc_select'):
        return
    if not dpg_.does_item_exist('measure_select'):
        return
    spc_value = dpg_.get_value('spc_select')
    get_spc_norms(spc_value)
    if dpg_.does_item_exist('spc_norm_table'):
        dpg_.delete_item('spc_norm_table')
    parameytr_name = dpg_.get_value('measure_select')
    with dpg_.table(header_row=True, row_background=True, parent='Filtr',
                    borders_innerH=True, borders_outerH=True,
                    borders_innerV=True, borders_outerV=True,
                    user_data=dpg_, tag='spc_norm_table', label='Нормы'):
        dpg_.add_table_column(label='Параметр')
        dpg_.add_table_column(label='Норма снизу')
        dpg_.add_table_column(label='Норма сверху')
    spc_norm_par = Statistik.Data.Data.get_spc_norm(parameytr_name) or {}
    nmin = spc_norm_par.get(parameytr_name + 'min')
    nmax = spc_norm_par.get(parameytr_name + 'max')
    with dpg_.table_row(parent='spc_norm_table'):
        dpg_.add_text(parameytr_name)
        dpg_.add_text('-' if nmin is None else str(nmin))
        dpg_.add_text('-' if nmax is None else str(nmax))

    pltExist = dpg_.does_item_exist('y_axis_msk')
    for item in dpg_.get_all_items():
        alias = dpg_.get_item_alias(item)
        if alias in ('Norm_Max', 'Norm_Min'):
            dpg_.delete_item(alias)
    axis_limits = Statistik.Data.Data.get_axis_limits()
    if spc_norm_par[parameytr_name + 'max'] is not None:
        norm_max = float(spc_norm_par[parameytr_name + 'max'])
        x = [norm_max for _ in range(100)]
        y_max = axis_limits['Y_Max'] or 0.5
        y = np.linspace(0, y_max, 100)
        dpg_.add_line_series(x, y, parent="y_axis",
                             tag='Norm_Max', label='Граница сверху')
        if pltExist:
            if dpg_.does_item_exist('Norm_Max_msk'):
                dpg_.delete_item('Norm_Max_msk')
            dpg_.add_line_series(x, y, parent="y_axis_msk",
                                 tag='Norm_Max_msk', label='Граница сверху')
    if spc_norm_par[parameytr_name + 'min'] is not None:
        norm_min = float(spc_norm_par[parameytr_name + 'min'])
        x = [norm_min for _ in range(100)]
        y_max = axis_limits['Y_Max'] or 0.5
        y = np.linspace(0, y_max, 100)
        dpg_.add_line_series(x, y, parent="y_axis",
                             tag='Norm_Min', label='Граница снизу')
        if pltExist:
            if dpg_.does_item_exist('Norm_Min_msk'):
                dpg_.delete_item('Norm_Min_msk')
            dpg_.add_line_series(x, y, parent="y_axis_msk",
                                 tag='Norm_Min_msk', label='Граница снизу')
            dpg_.set_axis_limits_auto("x_axis_msk")
            dpg_.set_axis_limits_auto("y_axis_msk")
            dpg_.fit_axis_data('x_axis_msk')
            dpg_.fit_axis_data('y_axis_msk')