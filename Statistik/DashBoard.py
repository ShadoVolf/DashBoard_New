"""Statistik.DashBoard — точка сборки главного интерфейса.

После разбиения на подмодули этот файл сохраняет обратную совместимость:
все публичные имена DashBoard.<name> остаются доступны как раньше.
"""
from .dashboard_helpers import (
    MSKState,
    _layout, _get_screen_size,
    show_indicator, hide_indicator, show_message,
    get_checked_msks, _is_single_mode, _get_single_selected_msk,
    _show_msk_info, print_date_time,
)
from .dashboard_norms import update_spc_norm
from .dashboard_results import (
    update_result, update_msk_result, print_msk_plots,
    mes_select, export_xls,
)
from .dashboard_slots import (
    set_slot_data, add_del_slot,
    repaint_signal_window, repaint_action_window,
    set_id_count, update_slot_use_data,
    without_cap_changed, clear_all_data,
)

from .dashboard_ui import (
    create_filtrnom_window, create_nom_window, create_msk_window,
    create_plot_window, create_result_table_window,
    create_result_msk_table_window, create_action_window,
    create_data_signal_windows, create_plot_msk_window,
    show_nom_window, show_msk_window, show_filtr_window,
    show_plot_window, show_result_window, show_signal_window,
    show_action_window, show_result_msk_window, show_plot_msk_window,
    close_all_windows,
)

from .dashboard_menu import configure_windows_menu, _build_fallback_menu

from .dashboard_llm import (
    create_assistant_window, show_assistant_window,
    run_llm_report, stop_llm_report,
    run_nl_query, check_llm, clear_assistant_log,
)

from .dashboard_msk import (
    rebuild_msk_list, on_msk_row_click,
    _on_msk_search, _on_nom_search,
    _on_selection_mode_change,
    get_res_nom, get_res_nom1, get_msk_list, show_hide_msk_list,
    load_msk_dat, del_msk_from_list, test_msk_measure_types,
    select_last_n_msks, clear_msk_selection,          # <-- НОВЫЕ
)
def create_main_windows(dpg_):
    create_nom_window(dpg_)
    create_msk_window(dpg_)
    create_filtrnom_window(None, None, dpg_)
    create_plot_window(dpg_)
    create_result_table_window(dpg_)
    create_action_window(dpg_)
    create_data_signal_windows(dpg_)
    create_assistant_window(dpg_)
    configure_windows_menu(dpg_)