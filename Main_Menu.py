from Archive_View import create_archive_view_window
from Console import ConsoleManager
from PSI_Specification.Temperature_profile.Temp_profile_Windows import create_main_temp_profile_windows
from Power_Measure import create_power_measure_window
from RT.RT_TECH_Parameters.Measure_RT_Windows import create_rt_windows
from SpecEditor import create_spec_editor_window
from Statistik.DashBoard import create_main_windows
from Temperature_Measure.Measure_windows import create_main_measure_windows
from ResonatorGraph import create_graph_window

from PhaseNoise_View import create_phase_noise_window
try:
    from Virtual_Measure import create_virtual_measure_window
except ImportError as _e:
    print(f"[Virtual_Measure] module not available: {_e}")
    create_virtual_measure_window = None

# Создание главного меню
def create_main_menu(dpg):
    # Защита от повторного создания
    if dpg.does_item_exist('MenuBar'):
        return

    with dpg.viewport_menu_bar(tag='MenuBar'):
        with dpg.menu(label="Файл"):
            dpg.add_separator()
            dpg.add_menu_item(label="Выход", callback=dpg.stop_dearpygui)

        with dpg.menu(label="Анализ данных"):
            with dpg.menu(label="Статистика"):
                dpg.add_menu_item(label="DashBoard",
                                  callback=show_stat_dashboard,
                                  tag='DashBoard_S')
                dpg.set_item_user_data("DashBoard_S", dpg)

            with dpg.menu(label="Данные"):
                dpg.add_menu_item(label="Графики резонаторов",
                                  callback=lambda: create_graph_window(),
                                  tag='ResonatorGraph_Menu')
                dpg.add_menu_item(label="Архив БД",
                                  callback=show_archive_window,
                                  tag='Archive_Menu',
                                  user_data=dpg)
                dpg.add_menu_item(label="Протоколы",
                                  callback=show_protocol_manager,
                                  tag='Protocol_Manager_Menu',
                                  user_data=dpg)
                dpg.add_menu_item(
                    label="Фазовые шумы",
                    callback=lambda: create_phase_noise_window(),
                    tag="PhaseNoise_Menu",
                    user_data=dpg,
                )

        # === НОВОЕ: пункт верхнего уровня «Ассистент» ===
        dpg.add_menu_item(
            label="Ассистент",
            callback=show_assistant,
            tag='Assistant_Menu',
            user_data=dpg,
        )

        with dpg.menu(label="Спецификации"):
            dpg.add_menu_item(label="Температурные таблицы",
                              callback=show_temp_profile,
                              tag='Temp_profile_', user_data=dpg)
            dpg.add_menu_item(
                label="Редактор спецификаций",
                callback=lambda: create_spec_editor_window(),
                tag='SpecEditor_Menu',
            )

        with dpg.menu(label="Измерения"):
            dpg.add_menu_item(label="Измерения электрических параметров",
                              callback=show_measure_dashboard,
                              tag='Measure_M', user_data=dpg)
            if create_virtual_measure_window is not None:
                dpg.add_menu_item(
                    label="Виртуальный замер",
                    callback=show_virtual_measure,
                    tag='VirtualMeasure_Menu'
                )
            with dpg.menu(label="Утилиты", tag='Measure_Utils_Menu'):
                dpg.add_menu_item(label="Добавление АЧХ",
                                  callback=show_spur_add_window,
                                  tag='Spur_Add_Menu', user_data=dpg)
                dpg.add_menu_item(label="Объединение протоколов",
                                  callback=show_join_data_window,
                                  tag='Join_Data_Menu', user_data=dpg)
                dpg.add_menu_item(label="Совмещение протоколов",
                                  callback=show_unite_protokol_window,
                                  tag='Unite_Protokol_Menu', user_data=dpg)
                dpg.add_menu_item(label="Старение (Спектр)",
                                  callback=show_aging_window,
                                  tag='Aging_Menu', user_data=dpg)
                dpg.add_menu_item(
                    label="Формирование пар резонаторов",
                    callback=show_pairs_window,
                    tag='Resonator_Pairs_Menu',
                )

        with dpg.menu(label="Установки"):
            dpg.add_menu_item(label="Стенд измерения параметров РТ",
                              callback=show_rt_tech_dashboard,
                              tag='RT_Tech_Parameters_status',
                              user_data=dpg)
            dpg.add_menu_item(
                label="Измерение частоты Ч3-85/6",
                callback=show_frequency_measure,
                tag='FrequencyMeasure_Menu',
            )
            if create_power_measure_window is not None:
                dpg.add_menu_item(
                    label="Монтаж РТ",
                    callback=lambda: create_power_measure_window(),
                    tag='PowerMeasure_Menu'
                )

        dpg.add_menu(label="Окна", tag='Windows_Menu')

        with dpg.menu(label="Справка"):
            dpg.add_menu_item(label="О программе",
                              callback=lambda: dpg.show_about())
            dpg.add_menu_item(label="Документация",
                              callback=show_documentation)
            dpg.add_menu_item(label="Отладка",
                              callback=lambda: dpg.show_debug())

        with dpg.menu(label="Консоль"):
            console_manager = ConsoleManager()
            dpg.add_menu_item(
                label="Показать/скрыть",
                callback=lambda: console_manager.toggle_console(),
            )

# =========================================================================
# Callbacks
# =========================================================================

def show_pairs_window(sender=None, data=None, dpg=None):
    """Открыть окно «Формирование пар резонаторов»."""
    try:
        from Resonator_Pairs import create_pairs_window
        create_pairs_window()
    except Exception as e:
        print(f"[Pairs] error: {e}")
        import traceback
        traceback.print_exc()


def show_protocol_manager(sender=None, data=None, dpg=None):
    """Открыть окно «Управление протоколами»."""
    try:
        from Protocol_Manager import create_protocol_manager_window
        create_protocol_manager_window()
    except Exception as e:
        print(f"[Protocol_Manager] error: {e}")
        import traceback
        traceback.print_exc()


def show_spur_add_window(sender=None, data=None, dpg=None):
    """Открыть окно «Добавление АЧХ»."""
    try:
        from Temperature_Measure.Measure_windows import open_spur_add_measure_window
        open_spur_add_measure_window(dpg)
    except Exception as e:
        print(f"[Spur_Add] error: {e}")
        import traceback
        traceback.print_exc()


def show_join_data_window(sender=None, data=None, dpg=None):
    """Открыть окно «Объединение протоколов»."""
    try:
        from Temperature_Measure.Measure_windows import open_join_data_window
        open_join_data_window(dpg)
    except Exception as e:
        print(f"[Join_Data] error: {e}")
        import traceback
        traceback.print_exc()


def show_unite_protokol_window(sender=None, data=None, dpg=None):
    """Открыть окно «Совмещение протоколов»."""
    try:
        from Temperature_Measure.Measure_windows import open_unite_protokol_window
        open_unite_protokol_window(dpg)
    except Exception as e:
        print(f"[Unite_Protokol] error: {e}")
        import traceback
        traceback.print_exc()


def show_aging_window(sender=None, data=None, dpg=None):
    """Открыть окно «Старение (Спектр)»."""
    try:
        from Temperature_Measure.Measure_windows import open_aging_window
        open_aging_window(dpg)
    except Exception as e:
        print(f"[Aging] error: {e}")
        import traceback
        traceback.print_exc()


def show_stat_dashboard(sender, data, dpg):
    print("test menu")
    print(sender)
    print(data)
    create_main_windows(dpg)


def show_temp_profile(sender, data, dpg):
    create_main_temp_profile_windows(dpg)


def show_measure_dashboard(sender, data, dpg):
    create_main_measure_windows(dpg)


def show_rt_tech_dashboard(sender, data, dpg):
    create_rt_windows(dpg)


def show_documentation(sender=None, data=None):
    try:
        from Documentation.ui import create_documentation_window
        create_documentation_window()
    except Exception as e:
        print(f"[Documentation] error: {e}")


def show_frequency_measure(sender=None, data=None):
    try:
        from FrequencyMeasure import create_frequency_measure_window
        create_frequency_measure_window()
    except Exception as e:
        print(f"[FrequencyMeasure] error: {e}")
        import traceback
        traceback.print_exc()


def show_archive_window(sender=None, data=None, dpg=None):
    try:
        if dpg is None:
            import dearpygui.dearpygui as dpg
        create_archive_view_window(dpg)
    except Exception as e:
        print(f"[Archive] error: {e}")
        import traceback
        traceback.print_exc()


def show_virtual_measure(sender=None, data=None):
    """Открытие окна формирования виртуального замера."""
    if create_virtual_measure_window is None:
        print("[Virtual_Measure] module not loaded")
        return
    try:
        create_virtual_measure_window()
    except Exception as e:
        print(f"[Virtual_Measure] error: {e}")
        import traceback
        traceback.print_exc()

def show_assistant(sender=None, data=None, dpg_mod=None):
    """Открыть окно ассистента (20 %×80 %, слева, под user-окном)."""
    try:
        if dpg_mod is None:
            import dearpygui.dearpygui as dpg_mod
        from Assistant import show_assistant_window
        show_assistant_window(sender, data, dpg_mod)
    except Exception as e:
        print(f"[Assistant] error: {e}")
        import traceback
        traceback.print_exc()