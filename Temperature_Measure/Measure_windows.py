"""Окна модуля «Измерения параметров».

Содержит:
  * создание трёх основных окон (файл / обработка / результаты);
  * утилитные окна (АЧХ, объединение протоколов, совмещение протоколов,
    старение), которые открываются из меню «Измерения → Утилиты»
    и автоматически попадают в меню «Окна» через window_manager.
"""
import locale

from Temperature_Measure import _layout
from Authorization.Login import LoginUser
from Options import (get_current_date, get_current_datetime, get_current_time)
from Statistik.Operations import get_msk
from Temperature_Measure import Report
from Temperature_Measure.Analyze_Data import (load_measure_file_data,
    get_file_inf_KH7700, get_file_inf_TTS100, get_file_inf_W2200,
    test_temp_interval_points, get_multy_spec, get_file_inf_TCH2200,
    build_ranked_spc_combo_list)
from Temperature_Measure.Control_RK import load_control_rk
from Temperature_Measure.File_Select import (get_machine_types_list,
    get_files_types_list)
from Temperature_Measure.Load_Data import (load_numbers_list, fill_numbers,
    test_numbers_dataframe, generate_msk_name, get_resonator_spc_psi_data,
    clean_MSK, get_msk_pmi_status)
from Temperature_Measure.Make_Measure import (process_measure,
    analyze_quality_control, prepare_print)
from Temperature_Measure.Report import (open_pdf, generate_filename,
    generate_pdf, create_accuracy_correction_protocol,
    create_calibration_protocol)
from Temperature_Measure.Save_To_mySql import save_psidata
from Temperature_Measure.Windows_units import Measure_Number_Window
from Temperature_Measure.Windows_units.Measure_MSK_WIndow import \
    create_set_msk_windows
from Temperature_Measure.Windows_units.Measure_Spc_Window import \
    create_set_specification_windows, add_local_spc_to_list
from Temperature_Measure.Windows_units.Measure_Spur_Add import \
    create_add_spur_window
from Temperature_Measure.Windows_units.Measure_Table_Window import \
    create_measure_table_window
from Temperature_Measure.Windows_units.Measure_Window import \
    create_measure_window
from Temperature_Measure.Protokol_join.Measure_join_data_Window import \
    create_join_data_windows
from Temperature_Measure.unite_protokol.sort_gui import SortResultWindow
from Temperature_Measure.measure_data_class import MEASURE_DATA
from Temperature_Measure.Spektr_OLD import AgingWindow as _AgingWindow

import pandas as pd
import numpy as np

locale.setlocale(locale.LC_ALL, 'ru_RU.UTF-8')


# ============================================================================
#                      Основные окна модуля «Измерения»
# ============================================================================
def create_main_measure_windows(dpg):
    create_themes(dpg)
    # Создаём окна только если их ещё нет (идемпотентность)
    if not dpg.does_item_exist('select_measure_file_windows'):
        create_select_file_window(dpg)
    if not dpg.does_item_exist('measure_window'):
        create_measure_window(dpg)
    if not dpg.does_item_exist('stat_result_window'):
        create_stat_result_window(dpg)
    # Показываем их (на случай, если были скрыты)
    for tag in ('select_measure_file_windows', 'measure_window',
                'stat_result_window'):
        if dpg.does_item_exist(tag):
            try:
                dpg.configure_item(tag, show=True)
            except Exception:
                pass
    _register_measure_windows(dpg)          # ← вместо configure_windows_menu
    _layout.init()

def create_main_measure_windows_1(dpg):
    create_themes(dpg)
    create_select_file_window(dpg)
    create_measure_window(dpg)
    create_stat_result_window(dpg)
    configure_windows_menu(dpg)
    _layout.init()

def close_all_windows(sender, data, dpg):
    for tag in ('select_measure_file_windows', 'measure_window',
                'stat_result_window', 'spur_add_measure_window',
                'sort_result_window', 'join_data_window', 'aging_window'):
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)
    _register_measure_windows(dpg)          # ← обновить «Окна»

def close_all_windows_1(sender, data, dpg):
    for tag in ('select_measure_file_windows', 'measure_window',
                'stat_result_window', 'spur_add_measure_window',
                'sort_result_window', 'join_data_window', 'aging_window'):
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

def _register_measure_windows(dpg):
    """Регистрирует ВСЕ окна модуля Измерений в window_manager.

    По аналогии с модулем Архив: единая точка регистрации + rebuild_menu.
    Регистрируем и основные, и утилитные окна — тогда после первого
    открытия модуля «Окна» уже показывает их все.
    """
    try:
        from window_manager import register, rebuild_menu
    except Exception as e:
        print(f"[Measure_windows] window_manager not available: {e}")
        return
    try:
        register('select_measure_file_windows', "Выбор файла",
                 lambda: open_select_file_window(dpg))
        register('measure_window', "Измерения",
                 lambda: open_measure_window(dpg))
        register('stat_result_window', "Результаты",
                 lambda: open_stat_result_window(dpg))
        register('spur_add_measure_window', "Добавление АЧХ",
                 lambda: open_spur_add_measure_window(dpg))
        register('join_data_window', "Объединение протоколов",
                 lambda: open_join_data_window(dpg))
        register('sort_result_window', "Совмещение протоколов",
                 lambda: open_unite_protokol_window(dpg))
        register('aging_window', "Старение (Спектр)",
                 lambda: open_aging_window(dpg))
        rebuild_menu()
    except Exception as e:
        print(f"[Measure_windows] window_manager registration error: {e}")

def open_select_file_window(dpg):
    tag = 'select_measure_file_windows'
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, show=True)
        try: dpg.focus_item(tag)
        except Exception: pass
    else:
        create_select_file_window(dpg)
    _register_measure_windows(dpg)


def open_measure_window(dpg):
    tag = 'measure_window'
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, show=True)
        try: dpg.focus_item(tag)
        except Exception: pass
    else:
        create_measure_window(dpg)
    _register_measure_windows(dpg)


def open_stat_result_window(dpg):
    tag = 'stat_result_window'
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, show=True)
        try: dpg.focus_item(tag)
        except Exception: pass
    else:
        create_stat_result_window(dpg)
    _register_measure_windows(dpg)


def configure_windows_menu(dpg):
    """Пересоздать пункт меню «Окна» для основных окон модуля.

    Утилитные окна (АЧХ / объединение / совмещение / старение)
    добавляются в это меню автоматически через window_manager —
    при вызове rebuild_menu() ниже.
    """
    if dpg.does_item_exist('Windows_Menu'):
        dpg.delete_item('Windows_Menu', children_only=False)
    with dpg.viewport_menu_bar():
        with dpg.menu(label="Окна", tag='Windows_Menu'):
            dpg.add_menu_item(label="Выбор файла",
                              callback=lambda: create_select_file_window(dpg),
                              user_data=dpg)
            dpg.add_menu_item(label="Измерения",
                              callback=lambda: create_measure_window(dpg),
                              user_data=dpg)
            dpg.add_menu_item(label="Результаты",
                              callback=lambda: create_stat_result_window(dpg),
                              user_data=dpg)
            dpg.add_menu_item(label="Закрыть все",
                              callback=close_all_windows, user_data=dpg)

    # Восстанавливаем пункты утилитных окон, если они уже были
    # зарегистрированы (через «Измерения → Утилиты» или через «Окна»).
    try:
        from window_manager import rebuild_menu
        rebuild_menu()
    except Exception as e:
        print(f"[Measure_windows] rebuild_menu error: {e}")


# ============================================================================
#           Утилиты: idempotent-открытие окон + регистрация в меню
# ============================================================================
def _register_utils_with_window_manager(dpg):
    """Зарегистрировать окна утилит в глобальном window_manager.

    После register() вызывается rebuild_menu() — окна появятся
    в меню «Окна» наряду с «Архив БД» и другими модулями.
    """
    try:
        from window_manager import register, rebuild_menu
    except Exception as e:
        print(f"[Measure_windows] window_manager not available: {e}")
        return
    try:
        register('spur_add_measure_window', "Добавление АЧХ",
                 lambda: open_spur_add_measure_window(dpg))
        register('join_data_window', "Объединение протоколов",
                 lambda: open_join_data_window(dpg))
        register('sort_result_window', "Совмещение протоколов",
                 lambda: open_unite_protokol_window(dpg))
        register('aging_window', "Старение (Спектр)",
                 lambda: open_aging_window(dpg))
        rebuild_menu()
    except Exception as e:
        print(f"[Measure_windows] window_manager registration error: {e}")


def open_spur_add_measure_window(dpg):
    """Открыть/показать окно «Добавление АЧХ» (idempotent)."""
    tag = 'spur_add_measure_window'
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, show=True)
        try:
            dpg.focus_item(tag)
        except Exception:
            pass
    else:
        create_add_spur_window(dpg)
        _layout.center_on_screen(tag)
    _register_measure_windows(dpg)


def open_join_data_window(dpg):
    """Открыть/показать окно «Объединение протоколов» (idempotent)."""
    tag = 'join_data_window'
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, show=True)
        try:
            dpg.focus_item(tag)
        except Exception:
            pass
    else:
        create_join_data_windows(dpg)
        _layout.center_on_screen(tag)
    _register_measure_windows(dpg)


def open_unite_protokol_window(dpg):
    """Открыть/показать окно «Совмещение протоколов» (idempotent)."""
    tag = 'sort_result_window'
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, show=True)
        try:
            dpg.focus_item(tag)
        except Exception:
            pass
    else:
        sort_win = SortResultWindow(dpg_context=dpg)
        sort_win.show()
        _layout.center_on_screen(tag)
    _register_measure_windows(dpg)


def open_aging_window(dpg):
    """Открыть/показать окно «Старение (Спектр)» (idempotent)."""
    tag = 'aging_window'
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, show=True)
        try:
            dpg.focus_item(tag)
        except Exception:
            pass
    else:
        _AgingWindow(dpg)
        _layout.center_on_screen(tag)
    _register_measure_windows(dpg)


# --- обратная совместимость (старые имена) ---
def create_spur_add_measure_window(dpg):
    return open_spur_add_measure_window(dpg)


def create_join_data_window(dpg):
    return open_join_data_window(dpg)


def create_unite_protokol_windows(dpg):
    return open_unite_protokol_window(dpg)


def create_aging_window(dpg):
    return open_aging_window(dpg)


# ============================================================================
#                         Вспомогательные
# ============================================================================
def center_window(dpg, name_window):
    _layout.center_on_screen(name_window)


def create_themes(dpg):
    with dpg.theme(tag='Use_button_theme'):
        with dpg.theme_component(dpg.mvButton, tag='Use_button_theme_button'):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (49, 215, 88, 100))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (37, 98, 145, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (191, 101, 68, 255))
    with dpg.theme(tag='Not_Use_button_theme'):
        with dpg.theme_component(dpg.mvButton, tag='Not_Use_button_theme_button'):
            dpg.add_theme_color(dpg.mvThemeCol_Button, (232, 111, 67, 100))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (37, 98, 145, 255))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (191, 101, 68, 255))


# ============================================================================
#                              Окна модуля
# ============================================================================
def create_stat_result_window(dpg):
    pos, size = _layout.compute_main_layout()["stat_result_window"]
    with dpg.window(label="Результаты обработки измерений",
                    width=size[0], height=size[1], pos=pos,
                    tag='stat_result_window'):
        update_result_table(dpg)


def create_select_file_window(dpg):
    pos, size = _layout.compute_main_layout()["select_measure_file_windows"]
    with dpg.window(label="Выбор файла измерений",
                    width=size[0], height=size[1], pos=pos,
                    tag='select_measure_file_windows'):
        dpg.add_input_text(label='Идентификатор', on_enter=True, callback='',
                           tag='file_id_enter_select')
        dpg.add_text("Измерительная установка")
        dpg.add_combo(get_machine_types_list(), user_data=dpg,
                      callback=get_file_list,
                      tag='measure_machine_select', default_value='Все')
        dpg.add_text("Список файлов")
        dpg.add_text("| ID      |  Название файла     | Дата измерения |")
        dpg.add_listbox(width=-1, num_items=55, tag='file_select',
                        user_data=dpg)
        with dpg.popup(dpg.last_item(), min_size=[80, 30]):
            dpg.add_selectable(label="Выбрать", callback=get_file_inf,
                               user_data=dpg)


# ============================================================================
#                        Работа с файлом и обработка
# ============================================================================
def get_file_list(sender, data, dpg):
    tt = dpg.get_value('measure_machine_select')
    if tt is not None:
        nom_list = get_files_types_list(machine_type=tt)
        if len(nom_list) > 0:
            dpg.configure_item('file_select', items=nom_list)


def get_file_inf(sender, data, dpg):
    MEASURE_DATA.clear_number_spc_data()
    tt = dpg.get_value('file_select')
    (file_name, machine_serial, machine_type, machine_poverka,
     difference, archive, file_id) = load_measure_file_data(tt)
    dpg.set_value("machine_name", machine_serial)
    dpg.set_value("machine_type", machine_type)
    dpg.set_value("file_name", file_name)
    if dpg.does_item_exist('archive'):
        dpg.delete_item('archive')
    if machine_poverka:
        dpg.set_value("poverka_actual_dif", str(difference.days))
    else:
        dpg.set_value("poverka_actual_dif", 'Не поверяется')
    if archive:
        dpg.add_text("Архив", color=(255, 0, 0, 255),
                     parent='file_inf_gr', tag='archive')

    file_data = pd.DataFrame()
    if machine_type == 'KH7700':
        file_data = get_file_inf_KH7700(file_id, archive)
    elif machine_type == 'Transat':
        file_data = get_file_inf_TTS100(file_id, archive)
    elif machine_type == 'Saunders':
        file_data = get_file_inf_W2200(file_id, archive)
    elif machine_type == 'ТЧХ2200':
        file_data = get_file_inf_TCH2200(file_id, archive)

    if dpg.does_item_exist('measure_table'):
        dpg.delete_item('measure_table')
    for item in dpg.get_all_items():
        alias = dpg.get_item_alias(item)
        if alias and len(alias) > 1:
            if any(p in alias for p in ('spc_set_', 'num_set_', 'msk_set_',
                                        'control_set_', 'msk_wrt_',
                                        'spc_ins_', 'start_set_')):
                dpg.delete_item(alias)

    with dpg.table(header_row=True, row_background=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True,
                   user_data=dpg, tag='measure_table', label='Данные',
                   parent='measure_window'):
        dpg.add_table_column(label='N', width_fixed=True,
                             init_width_or_weight=30)
        dpg.add_table_column(label='Номинал, Гц', width_fixed=True,
                             init_width_or_weight=100)
        dpg.add_table_column(label='Позиции', width_fixed=True,
                             init_width_or_weight=170)
        dpg.add_table_column(label='Количество, шт.', width_fixed=True,
                             init_width_or_weight=90)
        dpg.add_table_column(label='Температуры', width_fixed=True,
                             init_width_or_weight=170)
        dpg.add_table_column(label='Нагрузка', width_fixed=True,
                             init_width_or_weight=70)
        dpg.add_table_column(label='CL,пф', width_fixed=True,
                             init_width_or_weight=50)
        dpg.add_table_column(label='Спецификация', width_fixed=True,
                             init_width_or_weight=270)
        dpg.add_table_column(label='Номера')
        dpg.add_table_column(label='МСК')
        dpg.add_table_column(label='>>', width_fixed=True,
                             init_width_or_weight=50)

    count = 1
    if not file_data.empty:
        for index, row in file_data.iterrows():
            with dpg.table_row(parent='measure_table'):
                dpg.add_text(count)
                dpg.add_text(f"{row['Номинал']:,.0f}")
                dpg.add_text(row['Position_str'],
                             tag='Position_' + str(count) + '_select')
                with dpg.popup('Position_' + str(count) + '_select',
                               min_size=[100, 30]):
                    dpg.add_selectable(label="Контрольные",
                                       callback=load_control_rk, user_data=dpg,
                                       tag='control_set_' + str(count) + '_select')
                dpg.add_text(row['Position_Count'])
                if row['Temp_Step'] is None:
                    dpg.add_text(row['Temp'])
                else:
                    dpg.add_text(str(row['Temp']) + ' Шаг ' + str(row['Temp_Step']))
                dpg.add_text(row['CL_Metod'])
                dpg.add_text(row['CL_Value'])
                # Ранжированный список: score номинала → temp-фильтр → multi-spec
                # default = лучший по score (первый), без sort() по имени
                spc_list = build_ranked_spc_combo_list(row)
                dpg.add_combo(spc_list, user_data=dpg,
                              tag='spc_' + str(count) + 'select', width=270,
                              default_value=spc_list[0])
                with dpg.popup('spc_' + str(count) + 'select',
                               min_size=[80, 30]):
                    dpg.add_selectable(label="Подтвердить",
                                       callback=add_local_spc_to_list,
                                       user_data=dpg,
                                       tag='spc_ins_' + str(count) + '_select')
                    dpg.add_selectable(label="Задать",
                                       callback=create_spc_window, user_data=dpg,
                                       tag='spc_set_' + str(count) + '_select')
                dpg.add_selectable(label="Нет",
                                   tag='numbers_' + str(count) + '_select')
                with dpg.popup('numbers_' + str(count) + '_select',
                               min_size=[80, 30]):
                    dpg.add_selectable(label="Задать",
                                       callback=create_number_window,
                                       user_data=dpg,
                                       tag='num_set_' + str(count) + '_select')
                dpg.add_selectable(label="Нет",
                                   tag='msk_' + str(count) + '_select')
                with dpg.popup('msk_' + str(count) + '_select',
                               min_size=[80, 30]):
                    dpg.add_selectable(label="Выбрать",
                                       callback=create_msk_window, user_data=dpg,
                                       tag='msk_set_' + str(count) + '_select')
                    dpg.add_selectable(label="Задать",
                                       callback=show_msk_input_window,
                                       user_data=dpg,
                                       tag='msk_wrt_' + str(count) + '_select')
                dpg.add_button(label='ПУСК', user_data=dpg,
                               tag='start_' + str(count) + '_button',
                               callback=make_measure)
                with dpg.popup('start_' + str(count) + '_button',
                               min_size=[100, 30]):
                    dpg.add_selectable(label="Обработать все",
                                       callback=auto_make_measure, user_data=dpg,
                                       tag='start_set_' + str(count) + '_select')
            dpg.bind_item_theme('start_' + str(count) + '_button',
                                "Use_button_theme")
            MEASURE_DATA.slot_count = count
            count = count + 1


def set_msk_auto(sender, data, dpg):
    result = str(sender).split('_')
    slot = result[1]
    msk_str = MEASURE_DATA.get_msk(slot)
    if msk_str is None or msk_str == 'Нет':
        msk = generate_msk_name()
        dpg.configure_item('msk_' + str(slot) + '_select', label=msk)
        MEASURE_DATA.add_msk(slot, msk)


def create_spc_window(sender, data, dpg):
    if dpg.does_item_exist('spc_select_window'):
        dpg.delete_item('spc_select_window')
    create_set_specification_windows(sender, dpg)
    _layout.center_on_screen('spc_select_window')


def create_number_window(sender, data, dpg):
    if dpg.does_item_exist('numbers_select_window'):
        dpg.delete_item('numbers_select_window')
    Measure_Number_Window.create_set_numbers_windows(sender, dpg)
    _layout.center_on_screen('numbers_select_window')


def create_msk_window(sender, data, dpg):
    if dpg.does_item_exist('msk_select_window'):
        dpg.delete_item('msk_select_window')
    create_set_msk_windows(sender, dpg)
    _layout.center_on_screen('msk_select_window')


def get_msk_list_callback(sender, data, dpg):
    ms_list = get_msk(dpg.get_value(sender))
    if not ms_list.empty:
        msk_list = ms_list['мскРеал'].to_list()
        dpg.configure_item('msk_resonator_select_msk', items=msk_list,
                           default_value=msk_list[0])


# ============================================================================
#                            Авто-обработка
# ============================================================================
def auto_save_result_psi(sender, data, dpg):
    for i in range(1, MEASURE_DATA.slot_count + 1):
        tag = f"Save_bd_PSI_result_{i}_button"
        df = dpg.get_item_user_data(tag)
        save_measures_data(sender, data, df)


def auto_save_result_otk(sender, data, dpg):
    for i in range(1, MEASURE_DATA.slot_count + 1):
        tag = f"Save_bd_OTK_result_{i}_button"
        df = dpg.get_item_user_data(tag)
        save_measures_data(sender, data, df)


def auto_print_result_psi(sender, data, dpg):
    for i in range(1, MEASURE_DATA.slot_count + 1):
        tag = f"Print_bd_PSI_result_{i}_button"
        df = dpg.get_item_user_data(tag)
        print_report(sender, data, df)


def auto_print_result_otk(sender, data, dpg):
    for i in range(1, MEASURE_DATA.slot_count + 1):
        tag = f"Print_bd_PSI_result_{i}_button"
        df = dpg.get_item_user_data(tag)
        print_report(sender, data, df)


def auto_make_measure(sender, data, dpg):
    for i in range(1, MEASURE_DATA.slot_count + 1):
        make_measure('start_' + str(i) + '_button', data, dpg)


def make_measure(sender, data, dpg):
    result = str(sender).split('_')
    setupnum = result[1]
    MEASURE_DATA.active_slot_number = setupnum
    df_sorted = load_numbers_list(setupnum)
    pos_list = df_sorted['Positions'].to_list()
    if 'Numbers' in df_sorted.columns:
        if df_sorted['Numbers'].isnull().all() or len(df_sorted['Numbers']) == 0:
            fill_numbers(pos_list[0], pos_list[-1], 'T0001', setupnum)
    else:
        fill_numbers(pos_list[0], pos_list[-1], 'T0001', setupnum)

    spc_list = MEASURE_DATA.get_spc_sel_list(setupnum)
    if spc_list is None or len(spc_list) == 0:
        spc_current = dpg.get_value('spc_' + str(setupnum) + 'select')
        if spc_current != 'Нет':
            result = get_resonator_spc_psi_data(spc_current)
            if not result.empty:
                MEASURE_DATA.add_spc_to_list(setupnum, result)
            spc_df = MEASURE_DATA.get_spc_sel_list(setupnum)
            if not spc_df.empty:
                spc_sel_list = spc_df['Name'].tolist()
                dpg.configure_item('spc_' + str(setupnum) + 'select',
                                   items=spc_sel_list,
                                   default_value=spc_sel_list[0])

    set_msk_auto(sender, data, dpg)
    numbers_res = test_numbers_dataframe(setupnum)
    dpg.configure_item('numbers_' + str(setupnum) + '_select',
                       label=numbers_res)
    process_measure(setupnum)
    update_result_table(dpg)
    dpg.bind_item_theme(sender, 'Not_Use_button_theme')


# ============================================================================
#                       Таблица результатов
# ============================================================================
def update_result_table(dpg):
    data = MEASURE_DATA.measure_data
    for tag in ('result_view_table', 'result_view_table_container'):
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

    for item in dpg.get_all_items():
        alias = dpg.get_item_alias(item)
        if alias and len(alias) > 1:
            if 'save_set_' in alias or 'print_set' in alias:
                dpg.delete_item(alias)

    with dpg.group(parent="stat_result_window",
                   tag="result_view_table_container",
                   horizontal=True, width=-1):
        with dpg.table(header_row=True,
                       borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True,
                       scrollX=True, scrollY=True,
                       policy=dpg.mvTable_SizingFixedFit,
                       tag='result_view_table',
                       label='Результат измерения параметров'):
            dpg.add_table_column(label="N", width_fixed=True,
                                 init_width_or_weight=30)
            dpg.add_table_column(label="Код партии", width_fixed=True,
                                 init_width_or_weight=80)
            dpg.add_table_column(label="Спецификация", width_fixed=True,
                                 init_width_or_weight=250)
            dpg.add_table_column(label="МСК", width_fixed=True,
                                 init_width_or_weight=120)
            dpg.add_table_column(label="Статус", width_fixed=True,
                                 init_width_or_weight=80)
            dpg.add_table_column(label="Всего", width_fixed=True,
                                 init_width_or_weight=60)
            dpg.add_table_column(label="Годных", width_fixed=True,
                                 init_width_or_weight=60)
            dpg.add_table_column(label="Брак", width_fixed=True,
                                 init_width_or_weight=60)
            dpg.add_table_column(label="Коды брака", width_fixed=True,
                                 init_width_or_weight=360)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=80)
            dpg.add_table_column(width_fixed=True, init_width_or_weight=60)
            if len(data) > 0:
                for key, value in data.items():
                    status = MEASURE_DATA.get_save_status(value['Slot'])
                    with dpg.table_row(parent='result_view_table'):
                        dpg.add_text(value['Slot'])
                        dpg.add_text(value['File_Slot'])
                        spc = value['Spc']
                        dpg.add_text(spc['Name'])
                        msk = MEASURE_DATA.get_msk(value['File_Slot'])
                        dpg.add_text(msk)
                        dpg.add_text('ПСИ', color=[255, 0, 0])
                        stt = analyze_quality_control(value['Psi_Data_Status'])
                        dpg.add_text(stt['total'])
                        dpg.add_text(stt['passed'])
                        dpg.add_text(stt['failed'])
                        dpg.add_text(stt['error_codes'])
                        dpg.add_button(label='Таблица',
                                       callback=view_table_show,
                                       user_data=[dpg, value['Psi_Data'],
                                                  value['Psi_Data_Status'],
                                                  value['Spc_Map']])
                        if status['Save_PSI']:
                            dpg.add_text('Сохранено', color=[255, 0, 0],
                                         tag=f"Save_bd_PSI_result_{value['Slot']}_button",
                                         user_data=[value['Psi_Data'],
                                                    value['Psi_Data_Status'],
                                                    value['Spc_Map'],
                                                    value['Psi_Stat'],
                                                    value['Spc'],
                                                    value['File_Slot'],
                                                    'ПСИ', value['Result'],
                                                    value['Data_Temp'], dpg,
                                                    value['Slot']])
                        else:
                            dpg.add_button(label='Сохранить',
                                           callback=save_measures_data,
                                           user_data=[value['Psi_Data'],
                                                      value['Psi_Data_Status'],
                                                      value['Spc_Map'],
                                                      value['Psi_Stat'],
                                                      value['Spc'],
                                                      value['File_Slot'],
                                                      'ПСИ', value['Result'],
                                                      value['Data_Temp'], dpg,
                                                      value['Slot']],
                                           tag=f"Save_bd_PSI_result_{value['Slot']}_button")
                            with dpg.popup(f"Save_bd_PSI_result_{value['Slot']}_button",
                                           min_size=[100, 30]):
                                dpg.add_selectable(label="Сохранить ПСИ",
                                                   callback=auto_save_result_psi,
                                                   user_data=dpg,
                                                   tag='save_set_PSI_' + str(value['Slot']) + '_select')

                        dpg.add_button(label='Печать', callback=print_report,
                                       user_data=[value['Psi_Data'],
                                                  value['Psi_Data_Status'],
                                                  value['Spc_Map'],
                                                  value['Psi_Stat'],
                                                  value['Spc'],
                                                  value['File_Slot'],
                                                  'ПСИ', value['Result'],
                                                  value['Data_Temp'], dpg,
                                                  value['Slot']],
                                       tag=f"Print_bd_PSI_result_{value['Slot']}_button")
                        with dpg.popup(f"Print_bd_PSI_result_{value['Slot']}_button",
                                       min_size=[100, 30]):
                            dpg.add_selectable(label="Печать ПСИ",
                                               callback=auto_print_result_psi,
                                               user_data=dpg,
                                               tag='print_set_PSI_' + str(value['Slot']) + '_select')
                            dpg.add_checkbox(label='Сводная таблица',
                                             default_value=True,
                                             tag=f"print_set_psi_ch_table_{str(value['Slot'])}_chose",
                                             callback=save_protokol_type,
                                             user_data=dpg)
                            dpg.add_checkbox(label='Распечатка',
                                             default_value=True,
                                             tag=f"print_set_psi_ch_temp_{str(value['Slot'])}_chose",
                                             callback=save_protokol_type,
                                             user_data=dpg)
                            dpg.add_checkbox(label='Коррекция',
                                             default_value=False,
                                             tag=f"print_set_psi_corr_ch_{str(value['Slot'])}_chose",
                                             callback=save_protokol_type,
                                             user_data=dpg)
                        if status['Print_PSI']:
                            dpg.bind_item_theme(
                                f"Print_bd_PSI_result_{value['Slot']}_button",
                                "Not_Use_button_theme")
                        else:
                            dpg.bind_item_theme(
                                f"Print_bd_PSI_result_{value['Slot']}_button",
                                "Use_button_theme")

                    if len(value['OTK_Data']) > 0:
                        with dpg.table_row(parent='result_view_table'):
                            dpg.add_text(value['Slot'])
                            dpg.add_text(value['File_Slot'])
                            dpg.add_text(spc['Name'])
                            dpg.add_text(msk)
                            dpg.add_text('ОТК', color=[0, 255, 0])
                            stt = analyze_quality_control(value['OTK_Data_Status'])
                            dpg.add_text(stt['total'])
                            dpg.add_text(stt['passed'])
                            dpg.add_text(stt['failed'])
                            dpg.add_text(stt['error_codes'])
                            dpg.add_button(label='Таблица',
                                           callback=view_table_show,
                                           user_data=[dpg, value['OTK_Data'],
                                                      value['OTK_Data_Status'],
                                                      value['Spc_Map_OTK']])
                            if status['Save_OTK']:
                                dpg.add_text('Сохранено', color=[255, 0, 0],
                                             tag=f"Save_bd_OTK_result_{value['Slot']}_button")
                            else:
                                dpg.add_button(label='Сохранить',
                                               callback=save_measures_data,
                                               user_data=[value['OTK_Data'],
                                                          value['OTK_Data_Status'],
                                                          value['Spc_Map_OTK'],
                                                          value['OTK_Stat'],
                                                          value['Spc'],
                                                          value['File_Slot'],
                                                          'ОТК', value['Result'],
                                                          value['Data_Temp'], dpg,
                                                          value['Slot']],
                                               tag=f"Save_bd_OTK_result_{value['Slot']}_button")
                                with dpg.popup(f"Save_bd_OTK_result_{value['Slot']}_button",
                                               min_size=[100, 30]):
                                    dpg.add_selectable(label="Сохранить ОТК",
                                                       callback=auto_save_result_otk,
                                                       user_data=dpg,
                                                       tag='save_set_OTK_' + str(value['Slot']) + '_select')

                            dpg.add_button(label='Печать', callback=print_report,
                                           user_data=[value['OTK_Data'],
                                                      value['OTK_Data_Status'],
                                                      value['Spc_Map_OTK'],
                                                      value['OTK_Stat'],
                                                      value['Spc'],
                                                      value['File_Slot'],
                                                      'ОТК', value['Result'],
                                                      value['Data_Temp'], dpg,
                                                      value['Slot']],
                                           tag=f"Print_bd_OTK_result_{value['Slot']}_button")
                            with dpg.popup(f"Print_bd_OTK_result_{value['Slot']}_button",
                                           min_size=[100, 30]):
                                dpg.add_selectable(label="Печать ОТК",
                                                   callback=auto_print_result_otk,
                                                   user_data=dpg,
                                                   tag='print_set_OTK_' + str(value['Slot']) + '_select')
                                dpg.add_checkbox(label='Сводная таблица',
                                                 default_value=True,
                                                 tag=f"print_set_otk_ch_table_{str(value['Slot'])}_chose",
                                                 callback=save_protokol_type,
                                                 user_data=dpg)
                                dpg.add_checkbox(label='Распечатка',
                                                 default_value=True,
                                                 tag=f"print_set_otk_ch_temp_{str(value['Slot'])}_chose",
                                                 callback=save_protokol_type,
                                                 user_data=dpg)
                                dpg.add_checkbox(label='Коррекция',
                                                 default_value=False,
                                                 tag=f"print_set_corr_ch_{str(value['Slot'])}_chose",
                                                 callback=save_protokol_type,
                                                 user_data=dpg)
                            if status['Print_OTK']:
                                dpg.bind_item_theme(
                                    f"Print_bd_OTK_result_{value['Slot']}_button",
                                    "Not_Use_button_theme")
                            else:
                                dpg.bind_item_theme(
                                    f"Print_bd_OTK_result_{value['Slot']}_button",
                                    "Use_button_theme")


def save_protokol_type(sender, data, dpg):
    if 'table' in sender:
        MEASURE_DATA.set_protokol_print_sel('Main_Table', data)
    elif 'temp' in sender:
        MEASURE_DATA.set_protokol_print_sel('Temperatures_Table', data)
    elif 'corr' in sender:
        MEASURE_DATA.set_protokol_print_sel('Correction', data)


def view_table_show(sender, data, df):
    (dpg, data, data_status, spc) = df
    print_data, print_headers = prepare_print(data, data_status)
    if dpg.does_item_exist('measure_data_table_window'):
        dpg.delete_item('measure_data_table_window')
    create_measure_table_window(dpg, print_data, data_status, spc)


# ============================================================================
#                            Печать / сохранение
# ============================================================================
def print_report(sender, data, df):
    (data, data_status, spc_map, stat_df,
     spc, slot, protokol_type, result_df, data_temp, dpg, slot_m) = df
    (print_data, data_status, print_headers, spc_map, print_view_dict,
     stat_df, data_temp, mid) = prepare_print_func(df, True, 'Numbers')
    print_select = MEASURE_DATA.get_protokol_print_sel()
    if print_select['Main_Table']:
        filename = Report.create_protocol(print_data, data_status,
                                          print_headers, spc_map,
                                          print_view_dict, stat_df, mid,
                                          generate_filename(mid))
        open_pdf(filename)
    if print_select['Temperatures_Table']:
        filename_print = generate_pdf(mid, print_view_dict, data_temp,
                                      generate_filename(mid,
                                                        print_version=True),
                                      num_columns=4)
        open_pdf(filename_print)

    if MEASURE_DATA.get_control_RK_status() and print_select['Correction']:
        data = MEASURE_DATA.get_control_data_RK()
        control_measurements_df = data['Result']
        numbers = control_measurements_df['Numbers'].tolist()
        create_accuracy_correction_protocol(
            MEASURE_DATA.get_control_RK_corection_f_table())
        create_calibration_protocol(
            MEASURE_DATA.get_control_RK_corection_temp_table(), numbers,
            MEASURE_DATA.get_control_RK_type())

    MEASURE_DATA.set_save_status(slot=slot_m, status_type='Print',
                                 status=True, protokol_type=protokol_type)
    update_result_table(dpg)


def save_measures_data(sender, data, df):
    prepare_print_func(df, False)
    (data, data_status, spc_map, stat_df,
     spc, slot, protokol_type, result_df, data_temp, dpg, slot_m) = df
    MEASURE_DATA.set_save_status(slot=slot_m, status_type='Save',
                                 status=True, protokol_type=protokol_type)
    update_result_table(dpg)


def prepare_print_func(df, temp=True, sorted='Positions'):
    (data, data_status, spc_map, stat_df,
     spc, slot, protokol_type, result_df, data_temp, dpg, slot_m) = df
    data = data.drop(columns=['Anomal_Status'])
    data_status = data_status.drop(columns=['Anomal_Status'])
    m_data = MEASURE_DATA.get_setupnum_data(slot)
    file_data = MEASURE_DATA.get_data()
    operator = str(LoginUser.login[3]) + " " + str(LoginUser.login[5])
    mid = MEASURE_DATA.get_measure_id(slot=slot_m, type_=protokol_type)
    msk = clean_MSK(MEASURE_DATA.get_msk(slot))
    msk_pmi = get_msk_pmi_status(msk) if msk is not None else 0
    cor_tch = result_df['KO'].iloc[0] if 'KO' in result_df.columns else 0
    cor_f = result_df['KO_F'].iloc[0] if 'KO_F' in result_df.columns else 0
    print_view_dict = {
        'MSK': MEASURE_DATA.get_msk(slot),
        'Spc_Text': spc['Text'], 'Protokol_Type': protokol_type,
        'Position_str': m_data['Position_str'], 'Temp': m_data['Temp'],
        'Profile': spc['Profile'], 'Nominal': spc['Nominal'],
        'LoadType': spc['LoadType'], 'LoadValue': spc['Loadvalue'],
        'Virtual': spc['FL_Num'], 'FileName': file_data['FileName'],
        'File_ID': file_data['File_ID'],
        'Machine_Type': file_data['Machine_Type'],
        'Machine_Serial': file_data['Machine_Serial'],
        'Poverka': file_data['Poverka'],
        'Poverka_Date': file_data['Poverka_Date'],
        'Operator': operator, 'Full_Msk': msk, 'PMI': msk_pmi,
        'TCH_Type': spc['TCH_Approx_Type'],
        'TCH_correction': cor_tch, 'F_correction': cor_f,
        'R_correction': bool(spc['R_correction']) if 'R_correction' in spc.index else False,
        'Q_correction': bool(spc['Q_correction']) if 'Q_correction' in spc.index else False,
    }
    print_data, print_headers = prepare_print(data, data_status)
    result_df = result_df.merge(
        print_data[['Positions', 'Status', 'Status2']],
        on='Positions', how='left')
    result_df['Measure_ID'] = mid
    stat_data = {
        'MSK': MEASURE_DATA.get_msk(slot),
        'DateR': get_current_datetime(), 'Date': get_current_date(),
        'Time': get_current_time(), 'Spc': spc['Name'],
        'Nominal': spc['Nominal'], 'File': file_data['FileName'],
        'Operator': operator, 'intervalgf': spc['Profile'],
        'PrintSelect': 1, 'Cn': spc['Loadvalue'],
        'MachineType': file_data['Machine_Type'],
        'Machine_ID': file_data['Machine_ID'],
        'M_Type': file_data['Machine_Type_ID'],
        'Machine_Serial': file_data['Machine_Serial'],
        'Machine_Call_Date': file_data['Poverka_Date'],
        'PoverKa': file_data['Poverka'], 'Version': 'M 10.0.2',
        'REF_F': float(spc['Nominal']) * 1E6,
        'Measure_Metod': spc['LoadType'],
        'File_ID': file_data['File_ID'],
        'Virtual_CL': spc['FL_Num'], 'psi_type': protokol_type,
        'PMI': msk_pmi,
    }
    save_psidata(result_df, stat_data, mid, table_name='psidata', temp=temp)
    numeric_cols = data_temp.columns.difference(
        ['Positions', 'Numbers', 'SETUPNUM', 'Position_index',
         'Temp_status', 'KO_S_Numbers', 'Status2'])
    data_temp[numeric_cols] = data_temp[numeric_cols].apply(
        pd.to_numeric, errors='coerce')
    data_temp[numeric_cols] = data_temp[numeric_cols].mask(
        abs(data_temp[numeric_cols]) >= 10000, np.nan)
    data_temp = data_temp.merge(
        print_data[['Positions', 'Status']], on='Positions', how='left')
    data_temp['Measure_ID'] = mid
    stat_data1 = {'MSK': MEASURE_DATA.get_msk(slot),
                  'File': file_data['FileName']}
    save_psidata(data_temp, stat_data1, mid, table_name='psidatatemp',
                 temp=temp)
    if spc['Spur_Temp'] == 1:
        save_psidata(data_temp, {'MSK': MEASURE_DATA.get_msk(slot)}, mid,
                     table_name='psidata_spur', temp=temp)

    print_data = print_data.sort_values(by=sorted).reset_index(drop=True)
    data_temp = data_temp.sort_values(by=sorted).reset_index(drop=True)
    return (print_data, data_status, print_headers, spc_map,
            print_view_dict, stat_df, data_temp, mid)


# ============================================================================
#                          Ручной ввод МСК
# ============================================================================
def show_msk_input_window(sender, data, dpg):
    result = str(sender).split('_')
    slot = result[2]
    MEASURE_DATA.active_slot_number = slot
    pos, size = _layout.dialog_rect(fraction_w=0.18, fraction_h=0.12,
                                    min_w=280, min_h=140,
                                    max_w=380, max_h=190)
    with dpg.window(label="Выбор МСК", width=size[0], height=size[1],
                    pos=pos, tag='msk_add_window'):
        dpg.add_input_text(hint="Пример: 24-2501", decimal=False,
                           callback=set_msk_manual, tag="msk_input_text",
                           user_data=dpg, on_enter=True)
        dpg.add_button(label="Сохранить", callback=set_msk_manual,
                       user_data=dpg)


def set_msk_manual(sender, data, dpg):
    slot = MEASURE_DATA.active_slot_number
    msk = dpg.get_value('msk_input_text')
    dpg.configure_item('msk_' + str(slot) + '_select', label=msk)
    MEASURE_DATA.add_msk(slot, msk)
    dpg.delete_item('msk_add_window')