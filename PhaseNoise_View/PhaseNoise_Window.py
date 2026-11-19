"""Окно ФШ: выбор сверху → таблица → график → кнопки под графиком."""

import logging
import dearpygui.dearpygui as dpg
from Temperature_Measure import _layout
from .PhaseNoise_Constants import (
    WINDOW_TAG, GRAPH_CONTAINER, TABLE_CONTAINER, STATUS_TEXT_TAG,
)
from .PhaseNoise_UI import (
    build_selection_bar, build_load_bar, build_bottom_bar,
    wire_callbacks, init_cascade,
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
    if dpg.does_item_exist(WINDOW_TAG):
        dpg.configure_item(WINDOW_TAG, show=True)
        try: dpg.focus_item(WINDOW_TAG)
        except Exception: pass
        return

    log.info("Создание окна фазовых шумов")
    sw, sh = _layout.screen_size()
    w, h = max(1200, sw - 16), max(750, sh - 16)

    with dpg.window(label="Фазовые шумы", tag=WINDOW_TAG,
                    width=w, height=h, pos=(8, 8), no_collapse=True):
        # 1. Выбор сверху
        build_selection_bar()
        # 2. Кнопки «Загрузить» + чекбоксы
        build_load_bar()
        dpg.add_separator()
        # 3. Таблица
        with dpg.child_window(height=190, tag=TABLE_CONTAINER, border=True):
            dpg.add_text("(сводная таблица)", color=(120, 120, 120))
        # 4. График — растягиваем, оставляем 90px под кнопки+статус
        with dpg.child_window(height=-90, tag=GRAPH_CONTAINER, border=False):
            dpg.add_text("(график появится после <Загрузить>)",
                         color=(120, 120, 120))
        # 5. Кнопки Справочник / Экспорт / Печать — под графиком
        build_bottom_bar()
        # 6. Статус
        dpg.add_text("Готово", tag=STATUS_TEXT_TAG, color=(120, 180, 120))

    # --- КЛЮЧЕВОЕ: подключаем callbacks ПОСЛЕ создания всех combo ---
    wire_callbacks()
    init_cascade()
    _register_for_window_manager()
    log.info("Окно фазовых шумов создано")