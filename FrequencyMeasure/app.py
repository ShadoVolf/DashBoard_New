"""Автономный запуск модуля измерения частоты.

    python -m FrequencyMeasure.app
"""
import dearpygui.dearpygui as dpg

from .config import load_config
from .controller import MeasurementController
from .gui import ResonatorGUI


def main():
    dpg.create_context()

    cfg = load_config()
    controller = MeasurementController(cfg)
    gui = ResonatorGUI(controller)

    controller.start_device()
    controller.start_worker()
    controller.ask_mcu()

    dpg.create_viewport(title='CH3-85/6 - TCH TGK Measure',
                        width=1440, height=820)
    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.set_primary_window(gui.window_tag, True)

    while dpg.is_dearpygui_running():
        try:
            controller.process_queue()
        except Exception as e:
            import traceback
            controller.log(f'Ошибка в process_queue: {e}')
            traceback.print_exc()
        dpg.render_dearpygui_frame()

    controller.shutdown()
    dpg.destroy_context()


if __name__ == '__main__':
    main()