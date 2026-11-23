"""Окно ФШ: фильтры сверху → слева таблица, справа график + спецификация."""

import logging
import dearpygui.dearpygui as dpg
from Temperature_Measure import _layout
from .PhaseNoise_Constants import (
    WINDOW_TAG, TABLE_CONTAINER, STATUS_TEXT_TAG,
    INFO_PANEL_TAG,
)
from .PhaseNoise_UI import (
    build_filter_bar, build_info_panel, init_cascade,
)

log = logging.getLogger("PhaseNoise.Window")


def _register_for_window_manager():
    try:
        from window_manager import register, rebuild_menu
        register(WINDOW_TAG, "Фазовые шумы", create_phase_noise_window)
        try:
            rebuild_menu()
        except Exception:
            pass
    except Exception as e:
        log.warning(f"window_manager недоступен: {e}")


def create_phase_noise_window(dpg_ctx=None):
    # если окно уже есть — показать и ПЕРЕЗАПУСТИТЬ каскад
    if dpg.does_item_exist(WINDOW_TAG):
        log.info("Окно ФШ уже существует — show + init_cascade")
        dpg.configure_item(WINDOW_TAG, show=True)
        try:
            dpg.focus_item(WINDOW_TAG)
        except Exception:
            pass
        try:
            init_cascade()
        except Exception as e:
            log.exception(f"init_cascade on reopen: {e}")
        return

    log.info("Создание окна фазовых шумов")
    print("[PhaseNoise] Создание окна...")
    sw, sh = _layout.screen_size()
    margin = 8
    w = max(1200, sw - margin * 2)
    h = max(750, sh - margin * 2)
    right_w = 420
    left_w = max(500, w - right_w - 24)

    with dpg.window(label="Фазовые шумы", tag=WINDOW_TAG,
                    width=w, height=h, pos=(margin, margin), no_collapse=True):
        build_filter_bar()

        with dpg.group(horizontal=True):
            with dpg.child_window(width=left_w, height=-30, border=False):
                dpg.add_text("Результаты", tag=STATUS_TEXT_TAG,
                             color=(120, 180, 120))
                dpg.add_separator()
                with dpg.child_window(tag=TABLE_CONTAINER, height=-1,
                                      border=True):
                    dpg.add_text("(сводная таблица после <Загрузить>)",
                                 color=(120, 120, 120))

            with dpg.child_window(width=right_w, height=-30, border=True,
                                  tag=INFO_PANEL_TAG):
                build_info_panel()

    try:
        init_cascade()
    except Exception as e:
        log.exception(f"init_cascade failed: {e}")
        print(f"[PhaseNoise] init_cascade ERROR: {e}")
        try:
            if dpg.does_item_exist(STATUS_TEXT_TAG):
                dpg.set_value(STATUS_TEXT_TAG, f"Ошибка инициализации: {e}")
        except Exception:
            pass

    _register_for_window_manager()
    log.info("Окно фазовых шумов создано")
    print("[PhaseNoise] Окно создано")
