"""Создание окон DearPyGui и их отображение."""
import numpy as np
import dearpygui.dearpygui as dpg

import Statistik.Data
from Statistik.Operations import create_normal_dev, get_measure_parameters
from Statistik.Operations import get_resonator_types
from Statistik.Operations import get_resonator_nominals_list

from .dashboard_helpers import _layout, MSKState
from .dashboard_norms import update_spc_norm
from .dashboard_results import (
    mes_select, export_xls, update_result, update_msk_result, print_msk_plots,
)
from .dashboard_slots import (
    set_slot_data, add_del_slot,
    without_cap_changed, update_slot_use_data, clear_all_data, set_id_count,
)


from .dashboard_llm import (
    run_llm_report, stop_llm_report, show_assistant_window,
)
from .dashboard_msk import (
    _on_msk_search, _on_nom_search,
    _on_selection_mode_change,
    get_res_nom, get_res_nom1, get_msk_list, show_hide_msk_list,
    load_msk_dat, del_msk_from_list, test_msk_measure_types,
    select_last_n_msks, clear_msk_selection,          # <-- НОВЫЕ
)

# ===========================================================================
# Окна
# ===========================================================================
def create_filtrnom_window(sender, data, dpg_):
    if dpg_.does_item_exist('Filtr'):
        dpg_.configure_item('Filtr', show=True)
        return
    L = _layout()
    with dpg_.window(label="Фильтр", width=L['mid_w'], height=L['filt_h'],
                     pos=(L['mid_x'], L['filt_y']), tag='Filtr'):
        data_types = Statistik.Data.Data.get_measure_type_list()
        data_list = Statistik.Data.Data.get_active_data()
        with dpg_.collapsing_header(label="Выбор измерений",
                                    tag='Select_Measure_Type'):
            for index, row in data_list.iterrows():
                tag_str = 'combo' + str(row['Name']) + '_Select'
                data_types_temp = data_types[data_types['ID'] == row['Value']]
                dpg_.add_combo(data_types['Name'].tolist(),
                               label='Данные ' + str(row['Name']), tag=tag_str,
                               default_value=data_types_temp['Name'].to_string(index=False),
                               callback=set_slot_data, user_data=dpg_)
            with dpg_.popup('Select_Measure_Type', min_size=[80, 30],
                            tag='add_mes_select_menu'):
                dpg_.add_selectable(label="Добавить", user_data=dpg_,
                                    tag='add_data_slot', callback=add_del_slot)
                dpg_.add_selectable(label="Удалить", user_data=dpg_,
                                    tag='del_data_slot', callback=add_del_slot)
        dpg_.add_text("Выбор типа данных")
        parameters_list = get_measure_parameters('1')
        dpg_.add_combo(parameters_list[0], tag='measure_select',
                       default_value=parameters_list[0][0],
                       callback=mes_select, user_data=dpg_)
        with dpg_.table(header_row=True, row_background=True,
                        borders_innerH=True, borders_outerH=True,
                        borders_innerV=True, borders_outerV=True,
                        user_data=dpg_, tag='spc_norm_table', label='Нормы'):
            dpg_.add_table_column(label='Параметр')
            dpg_.add_table_column(label='Норма снизу')
            dpg_.add_table_column(label='Норма сверху')

def create_nom_window(dpg_):
    if dpg_.does_item_exist('Nomenklatura'):
        dpg_.configure_item('Nomenklatura', show=True)
        return
    L = _layout()
    with dpg_.window(label="Выбор номенклатуры", width=L['left_w'],
                     height=L['nom_h'], pos=(L['left_x'], L['nom_y']),
                     tag='Nomenklatura'):
        dpg_.add_text("Номенклатура")
        resonator_types = get_resonator_types()
        dpg_.add_combo(resonator_types, label='Тип резонатора', user_data=dpg_,
                       callback=get_res_nom, tag='type_select')
        resonator_nominals = get_resonator_nominals_list()
        dpg_.add_combo(resonator_nominals, label='Номинал', user_data=dpg_,
                       callback=get_res_nom1, tag='nominal_select')

        # Поиск по номенклатуре (фильтрует список спецификаций)
        with dpg_.group(horizontal=True):
            dpg_.add_text("Поиск")
            dpg_.add_input_text(tag='nom_search', width=-1, on_enter=True,
                                callback=_on_nom_search, user_data=dpg_)

        dpg_.add_combo(label='Спецификация', user_data=dpg_,
                       tag='spc_select', callback=get_msk_list)

def create_msk_window(dpg_):
    if dpg_.does_item_exist('MSK'):
        dpg_.configure_item('MSK', show=True)
        return
    L = _layout()

    with dpg_.window(label="Выбор МСК", width=L['left_w'],
                     height=L['msk_h'], pos=(L['left_x'], L['msk_y']),
                     tag='MSK'):
        dpg_.add_text("Список МСК (ЛКМ - выбрать, ПКМ - меню)")

        # --- поиск ---
        with dpg_.group(horizontal=True):
            dpg_.add_text("Поиск")
            dpg_.add_input_text(tag='msk_search', width=-1, on_enter=True,
                                callback=_on_msk_search, user_data=dpg_)

        dpg_.add_radio_button(('Список МСК', 'Список добавленных МСК'),
                              tag='radio_group_list_view',
                              callback=show_hide_msk_list, user_data=dpg_)

        # --- НОВОЕ: выбор последних N (из видимых) ---
        with dpg_.group(horizontal=True):
            dpg_.add_text("Последние N:")
            dpg_.add_input_text(tag='last_n_msk', width=60,
                                default_value='10', hint='N')
            dpg_.add_button(label='Выбрать', tag='last_n_btn',
                            callback=select_last_n_msks, user_data=dpg_)
            dpg_.add_button(label='Снять все',
                            callback=clear_msk_selection, user_data=dpg_)
        dpg_.add_text("(N применяется к видимому списку, сортировка по дате)",
                      color=(160, 160, 160))

        # --- единый контейнер списка ---
        with dpg_.child_window(tag='msk_list_container',
                               height=-1, width=-1):
            with dpg_.table(header_row=False, tag='msk_list_table',
                            scrollY=True, height=-1):
                dpg_.add_table_column(label='МСК', width_stretch=True,
                                      init_width_or_weight=1.0)

def create_msk_window_4(dpg_):
    if dpg_.does_item_exist('MSK'):
        dpg_.configure_item('MSK', show=True)
        return
    L = _layout()

    with dpg_.window(label="Выбор МСК", width=L['left_w'],
                     height=L['msk_h'], pos=(L['left_x'], L['msk_y']),
                     tag='MSK'):
        dpg_.add_text("Список МСК (ЛКМ - выбрать, ПКМ - меню)")

        with dpg_.group(horizontal=True):
            dpg_.add_text("Поиск")
            dpg_.add_input_text(tag='msk_search', width=-1, on_enter=True,
                                callback=_on_msk_search, user_data=dpg_)

        dpg_.add_radio_button(('Список МСК', 'Список добавленных МСК'),
                              tag='radio_group_list_view',
                              callback=show_hide_msk_list, user_data=dpg_)

        # Единый контейнер: список всегда в виде таблицы,
        # независимо от режима выбора.
        with dpg_.child_window(tag='msk_list_container',
                               height=-1, width=-1):
            with dpg_.table(header_row=False, tag='msk_list_table',
                            scrollY=True, height=-1):
                dpg_.add_table_column(label='МСК', width_stretch=True,
                                      init_width_or_weight=1.0)




def create_plot_window(dpg_):
    if dpg_.does_item_exist('Stat_plot'):
        dpg_.configure_item('Stat_plot', show=True)
        return
    L = _layout()
    with dpg_.window(label="График распределения", width=L['right_w'],
                     height=L['plot_h'], pos=(L['right_x'], L['plot_y']),
                     tag='Stat_plot'):
        with dpg_.plot(label="Распределение плотности вероятности",
                       height=-1, width=-1, tag='graph_plot'):
            dpg_.add_plot_legend()
            dpg_.add_plot_axis(dpg_.mvXAxis, label="x", tag="x_axis")
            dpg_.add_plot_axis(dpg_.mvYAxis, label="y", tag="y_axis")
            outdata = np.array(create_normal_dev(1, 0.5))
            dpg_.add_line_series(outdata[1], outdata[0], parent="y_axis",
                                 tag='slot1_plot')
            dpg_.set_axis_limits_auto("x_axis")
            dpg_.set_axis_limits_auto("y_axis")
            dpg_.fit_axis_data('x_axis')
            dpg_.fit_axis_data('y_axis')
    ch = dpg_.get_item_children('graph_plot', 0)
    Statistik.Data.Data.plot_children.append(ch)


def create_result_table_window(dpg_):
    if dpg_.does_item_exist('result_window'):
        dpg_.configure_item('result_window', show=True)
        return
    L = _layout()
    data_types = Statistik.Data.Data.get_measure_type_list()
    default_slot = (data_types.loc[5, 'Name']
                    if len(data_types) > 5
                    else (data_types['Name'].tolist()[-1]
                          if len(data_types) else ''))

    with dpg_.window(label="Результаты", width=L['mid_w'],
                     height=L['res_h'], pos=(L['mid_x'], L['res_y']),
                     tag='result_window'):
        with dpg_.collapsing_header(
                label="Результаты (ПКМ по заголовку - меню)",
                tag='result_table_header', default_open=True):
            with dpg_.popup('result_table_header',
                            mousebutton=dpg_.mvMouseButton_Right,
                            tag='result_menu', min_size=[280, 30]):
                dpg_.add_menu_item(label="Графики",
                                   callback=show_plot_msk_window,
                                   user_data=dpg_)
                dpg_.add_menu_item(label="Статистика",
                                   callback=show_result_msk_window,
                                   user_data=dpg_)
                dpg_.add_menu_item(label="Экспорт (EXCEL)",
                                   callback=export_xls, user_data=dpg_)
                dpg_.add_menu_item(label="LLM Отчёт",
                                   callback=run_llm_report, user_data=dpg_)
                dpg_.add_menu_item(label="Ассистент (LLM)",
                                   callback=show_assistant_window,
                                   user_data=dpg_)
                dpg_.add_separator()
                dpg_.add_checkbox(label='Удалить аномальные',
                                  tag='clear_check', default_value=False,
                                  callback=mes_select, user_data=dpg_)
                dpg_.add_separator()
                dpg_.add_text("Тип данных", color=(200, 200, 255))
                dpg_.add_combo(data_types['Name'].tolist(),
                               tag='data_slot_select', width=220,
                               default_value=default_slot)
            with dpg_.table(header_row=True, row_background=True,
                            borders_innerH=True, borders_outerH=True,
                            borders_innerV=True, borders_outerV=True,
                            user_data=dpg_, tag='result_table'):
                dpg_.add_table_column(label='##', width_fixed=True,
                                      init_width_or_weight=30)
                dpg_.add_table_column(label='Замер')
                dpg_.add_table_column(label='Макс', tag='Max',
                                      width_fixed=True, init_width_or_weight=60)
                dpg_.add_table_column(label='Мин', tag='Min',
                                      width_fixed=True, init_width_or_weight=60)
                dpg_.add_table_column(label='Среднее', tag='Mean',
                                      width_fixed=True, init_width_or_weight=60)
                dpg_.add_table_column(label='Медиана', tag='Median',
                                      width_fixed=True, init_width_or_weight=60)
                dpg_.add_table_column(label='СКО', tag='StDev',
                                      width_fixed=True, init_width_or_weight=60)
                dpg_.add_table_column(label='Нижняя граница',
                                      tag='Lower_bound', width_fixed=True,
                                      init_width_or_weight=90)
                dpg_.add_table_column(label='Верхняя граница',
                                      tag='Upper_bound', width_fixed=True,
                                      init_width_or_weight=110)
                dpg_.add_table_column(label='Количество аномальных',
                                      tag='Anomal_count')
                dpg_.add_table_column(label='Выше (ниже) нормы',
                                      tag='bad_count')
                dpg_.add_table_column(label='Всего', tag='Count',
                                      width_fixed=True, init_width_or_weight=60)
                dpg_.add_table_column(label='Выход годных', tag='out')


def create_result_msk_table_window(dpg_):
    if dpg_.does_item_exist('result_msk_window'):
        dpg_.configure_item('result_msk_window', show=True)
        return
    L = _layout()
    with dpg_.window(label="Результаты по отдельным МСК",
                     width=L['right_w'], height=L['rmsk_h'],
                     pos=(L['right_x'], L['rmsk_y']),
                     tag='result_msk_window'):
        with dpg_.table(header_row=True, row_background=True,
                        borders_innerH=True, borders_outerH=True,
                        borders_innerV=True, borders_outerV=True,
                        user_data=dpg_, tag='result_msk_table'):
            dpg_.add_table_column(label='N', width_fixed=True,
                                  init_width_or_weight=30)
            dpg_.add_table_column(label='МСК')
            dpg_.add_table_column(label='Макс', width_fixed=True,
                                  init_width_or_weight=60)
            dpg_.add_table_column(label='Мин', width_fixed=True,
                                  init_width_or_weight=60)
            dpg_.add_table_column(label='Среднее', width_fixed=True,
                                  init_width_or_weight=60)
            dpg_.add_table_column(label='Медиана', width_fixed=True,
                                  init_width_or_weight=60)
            dpg_.add_table_column(label='СКО', width_fixed=True,
                                  init_width_or_weight=60)
            dpg_.add_table_column(label='Нижняя граница', width_fixed=True,
                                  init_width_or_weight=90)
            dpg_.add_table_column(label='Верхняя граница', width_fixed=True,
                                  init_width_or_weight=110)
            dpg_.add_table_column(label='Количество аномальных')
            dpg_.add_table_column(label='Выше (ниже) нормы')
            dpg_.add_table_column(label='Всего', width_fixed=True,
                                  init_width_or_weight=60)
            dpg_.add_table_column(label='Выход годных')


def create_action_window(dpg_):
    if dpg_.does_item_exist('actions'):
        dpg_.configure_item('actions', show=True)
        return
    L = _layout()
    with dpg_.window(label="Действия", width=L['mid_w'],
                     height=L['act_h'], pos=(L['mid_x'], L['act_y']),
                     tag='actions'):
        dpg_.add_text("МСК", tag='msk_text_label', color=[255, 0, 0])
        dpg_.bind_item_font('msk_text_label', 'second_font')
        data_types = Statistik.Data.Data.get_measure_type_list()
        active_slot_list = Statistik.Data.Data.get_active_data()
        dpg_.add_separator()
        with dpg_.group(horizontal=True):
            dpg_.add_button(label='Добавить', callback=load_msk_dat,
                            user_data=dpg_, tag='add_data_button')
            dpg_.add_button(label='Удалить', callback=del_msk_from_list,
                            user_data=dpg_, tag='del_data_button',
                            enabled=False)
            dpg_.add_button(label='Удалить все данные',
                            tag='del_all_data_button',
                            user_data=dpg_, callback=clear_all_data)
        dpg_.add_separator()
        with dpg_.group(horizontal=True):
            dpg_.add_checkbox(label='Множественный выбор МСК',
                              tag='multi_select_mode', default_value=True,
                              callback=_on_selection_mode_change,
                              user_data=dpg_)
            dpg_.add_checkbox(label='Настройка без ёмкости (FL = Fr)',
                              tag='without_cap_check',
                              default_value=Statistik.Data.Data.get_without_cap_mode(),
                              callback=without_cap_changed, user_data=dpg_)
        dpg_.add_separator()
        # NEW — группа LLM
        with dpg_.group(horizontal=True):
            dpg_.add_text("LLM:", color=(200, 200, 255))
            dpg_.add_button(label='Отчёт', tag='llm_report_btn',
                            user_data=dpg_, callback=run_llm_report)
            dpg_.add_button(label='Стоп', tag='llm_report_stop_btn',
                            user_data=dpg_, callback=stop_llm_report,
                            enabled=False)
            dpg_.add_button(label='Ассистент',
                            user_data=dpg_, callback=show_assistant_window)
        dpg_.add_separator()
        with dpg_.table(header_row=False, tag='signal_all_table'):
            dpg_.add_table_column(width_fixed=True, init_width_or_weight=200)
            dpg_.add_table_column(width_fixed=True, init_width_or_weight=100)
            for index, row in active_slot_list.iterrows():
                with dpg_.table_row():
                    tag_str = 'data' + str(row['Name']) + '_check_box_all'
                    tag_str2 = 'text' + str(row['Name']) + '_check_box_all'
                    data_types_temp = data_types[data_types['ID'] == row['Value']]
                    dpg_.add_checkbox(
                        label=data_types_temp['Name'].to_string(index=False),
                        default_value=False, tag=tag_str,
                        callback=update_slot_use_data, user_data=dpg_)
                    dpg_.add_text("0 шт.", tag=tag_str2)

def create_data_signal_windows(dpg_):
    if dpg_.does_item_exist('view_msk'):
        dpg_.configure_item('view_msk', show=True)
        return
    L = _layout()
    is_multi = True
    if dpg_.does_item_exist('multi_select_mode'):
        is_multi = bool(dpg_.get_value('multi_select_mode'))

    with dpg_.window(label="МСК", width=L['right_w'],
                     height=L['sig_h'], pos=(L['right_x'], L['sig_y']),
                     tag='view_msk'):
        data_types = Statistik.Data.Data.get_measure_type_list()
        active_slot_list = Statistik.Data.Data.get_active_data()

        # ---- Панель 1: выбор ID замера (сворачиваемая) ----
        with dpg_.collapsing_header(label="Выбор ID замера",
                                    tag='signal_header',
                                    default_open=is_multi):
            with dpg_.table(header_row=False, tag='signal_table'):
                dpg_.add_table_column(width_fixed=True, init_width_or_weight=200)
                dpg_.add_table_column(width_fixed=True, init_width_or_weight=220)
                dpg_.add_table_column(width_fixed=True, init_width_or_weight=100)
                for index, row in active_slot_list.iterrows():
                    with dpg_.table_row():
                        tag_str = 'data' + str(row['Name']) + '_check_box'
                        tag_str1 = 'combo' + str(row['Name']) + '_check_box'
                        tag_str2 = 'text' + str(row['Name']) + '_check_box'
                        data_types_temp = data_types[data_types['ID'] == row['Value']]
                        dpg_.add_checkbox(
                            label=data_types_temp['Name'].to_string(index=False),
                            default_value=False, tag=tag_str)
                        dpg_.add_combo(tag=tag_str1, user_data=dpg_,
                                       callback=set_id_count)
                        dpg_.add_text("0 шт.", tag=tag_str2)

        # ---- Панель 2: информация о МСК (сворачиваемая) ----
        with dpg_.collapsing_header(label="Информация о МСК",
                                    tag='msk_info_header',
                                    default_open=not is_multi):
            with dpg_.child_window(tag='msk_info_area', height=-1, width=-1):
                dpg_.add_text("Клик по МСК в списке - информация о ней",
                              color=(150, 150, 150))



def create_plot_msk_window(dpg_):
    if dpg_.does_item_exist('view_msk_plot'):
        dpg_.configure_item('view_msk_plot', show=True)
        return
    L = _layout()
    with dpg_.window(label="Графики (МСК)", width=L['right_w'],
                     height=L['plot_h'],
                     pos=(L['right_x'], L['plot_y']),
                     tag='view_msk_plot'):
        with dpg_.plot(label="Распределение плотности вероятности",
                       height=-1, width=-1, tag='graph_plot_msk'):
            dpg_.add_plot_legend()
            dpg_.add_plot_axis(dpg_.mvXAxis, label="x", tag="x_axis_msk")
            dpg_.add_plot_axis(dpg_.mvYAxis, label="y", tag="y_axis_msk")
            dpg_.set_axis_limits_auto("x_axis_msk")
            dpg_.set_axis_limits_auto("y_axis_msk")
            dpg_.fit_axis_data('x_axis_msk')
            dpg_.fit_axis_data('y_axis_msk')
    ch = dpg_.get_item_children('graph_plot_msk', 0)
    Statistik.Data.Data.plot1_children.append(ch)


# ===========================================================================
# Show / Close обработчики
# ===========================================================================
def show_nom_window(sender, data, dpg_):
    create_nom_window(dpg_)


def show_msk_window(sender, data, dpg_):
    create_msk_window(dpg_)


def show_filtr_window(sender, data, dpg_):
    create_filtrnom_window(None, None, dpg_)


def show_plot_window(sender, data, dpg_):
    create_plot_window(dpg_)


def show_result_window(sender, data, dpg_):
    create_result_table_window(dpg_)
    update_result(dpg_)


def show_signal_window(sender, data, dpg_):
    create_data_signal_windows(dpg_)


def show_action_window(sender, data, dpg_):
    create_action_window(dpg_)


def show_result_msk_window(sender, data, dpg_):
    create_result_msk_table_window(dpg_)
    update_msk_result(dpg_)


def show_plot_msk_window(sender, data, dpg_):
    if dpg_.does_item_exist('view_msk_plot'):
        try:
            dpg_.delete_item(Statistik.Data.Data.plot1_children)
        except Exception:
            pass
        dpg_.delete_item('view_msk_plot')
        Statistik.Data.Data.plot1_children.clear()
    create_plot_msk_window(dpg_)
    update_spc_norm(dpg_)
    print_msk_plots(dpg_)


def close_all_windows(sender, data, dpg_):
    for tag in ('actions', 'Filtr', 'add_mes_select_menu',
                'graph_plot', 'Stat_plot', 'result_window',
                'view_msk', 'view_msk_plot', 'Nomenklatura', 'MSK',
                'result_msk_window'):
        if dpg_.does_item_exist(tag):
            dpg_.delete_item(tag)