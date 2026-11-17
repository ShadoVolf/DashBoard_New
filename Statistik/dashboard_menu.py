"""Регистрация окон в window_manager и fallback-меню."""
import dearpygui.dearpygui as dpg

from .dashboard_ui import (
    create_nom_window, create_msk_window, create_filtrnom_window,
    create_plot_window, create_result_table_window, create_action_window,
    create_data_signal_windows, create_plot_msk_window,
    create_result_msk_table_window,
    show_nom_window, show_msk_window, show_filtr_window,
    show_plot_window, show_result_window, show_signal_window,
    show_action_window, show_plot_msk_window, show_result_msk_window,
    close_all_windows,
)

from .dashboard_llm import (
    create_assistant_window, show_assistant_window,
    run_llm_report,
)
def configure_windows_menu(dpg_):
    try:
        from window_manager import register, rebuild_menu
        register('Nomenklatura', 'Номенклатура',
                 lambda: create_nom_window(dpg_))
        register('MSK', 'Выбор МСК',
                 lambda: create_msk_window(dpg_))
        register('Filtr', 'Фильтр',
                 lambda: create_filtrnom_window(None, None, dpg_))
        register('Stat_plot', 'График распределения',
                 lambda: create_plot_window(dpg_))
        register('result_window', 'Результаты',
                 lambda: create_result_table_window(dpg_))
        register('actions', 'Действия',
                 lambda: create_action_window(dpg_))
        register('view_msk', 'МСК (просмотр)',
                 lambda: create_data_signal_windows(dpg_))
        register('view_msk_plot', 'Графики (МСК)',
                 lambda: create_plot_msk_window(dpg_))
        register('result_msk_window', 'Результаты по МСК',
                 lambda: create_result_msk_table_window(dpg_))
        register('assistant', 'Ассистент (LLM)',
                 lambda: create_assistant_window(dpg_))
        try:
            rebuild_menu()
        except Exception as e:
            print(f'[window_manager] rebuild_menu: {e}')
        return
    except Exception as e:
        print(f'[window_manager] not available, fallback menu: {e}')
    _build_fallback_menu(dpg_)


def _build_fallback_menu(dpg_):
    if dpg_.does_item_exist('Windows_Menu'):
        dpg_.delete_item('Windows_Menu', children_only=False)
    with dpg_.viewport_menu_bar():
        with dpg_.menu(label="Окна", tag='Windows_Menu'):
            dpg_.add_menu_item(label="Номенклатура",
                               callback=show_nom_window, user_data=dpg_)
            dpg_.add_menu_item(label="МСК",
                               callback=show_msk_window, user_data=dpg_)
            dpg_.add_menu_item(label="График",
                               callback=show_plot_window, user_data=dpg_)
            dpg_.add_menu_item(label="Фильтр",
                               callback=show_filtr_window, user_data=dpg_)
            dpg_.add_menu_item(label="Результаты",
                               callback=show_result_window, user_data=dpg_)
            dpg_.add_menu_item(label="Просмотр",
                               callback=show_signal_window, user_data=dpg_)
            dpg_.add_menu_item(label="Действия",
                               callback=show_action_window, user_data=dpg_)
            dpg_.add_menu_item(label="Графики (Мск)",
                               callback=show_plot_msk_window, user_data=dpg_)
            dpg_.add_menu_item(label="Статистика",
                               callback=show_result_msk_window, user_data=dpg_)
            dpg_.add_menu_item(label="Ассистент (LLM)",
                               callback=show_assistant_window, user_data=dpg_)
            dpg_.add_menu_item(label="LLM Отчёт",
                               callback=run_llm_report, user_data=dpg_)
            dpg_.add_menu_item(label="Закрыть все",
                               callback=close_all_windows, user_data=dpg_)