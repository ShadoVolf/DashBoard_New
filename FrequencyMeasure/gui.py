"""UI для измерения частоты на Ч3-85/6. Интегрируется в общий viewport."""
import os
import sys
import subprocess

import numpy as np
import dearpygui.dearpygui as dpg

from .calculations import to_ppm
from .config import load_config
from .controller import MeasurementController


WINDOW_TAG = "freq_measure_main_win"

CYCLE_COLORS = {
    'MAX_TO_NORMAL':     (255, 80, 80),
    'MINUS60_TO_NORMAL': (80, 150, 255),
}

_controller = None
_gui = None

# Флаг: цепочка _process_queue_loop уже запланирована.
# Не даёт создать дублирующие цепочки при повторных вызовах
# _schedule_queue_loop() из разных мест.
_queue_loop_scheduled = False


def _open_file(path):
    try:
        if sys.platform.startswith('win'):
            os.startfile(path)
        elif sys.platform == 'darwin':
            subprocess.Popen(['open', path])
        else:
            subprocess.Popen(['xdg-open', path])
    except Exception as e:
        print(f"Не удалось открыть файл {path}: {e}")


def _get_screen_size():
    try:
        w = dpg.get_viewport_client_width()
        h = dpg.get_viewport_client_height()
        if w > 100 and h > 100:
            return w, h
    except Exception:
        pass
    return 1920, 1080


def _schedule_queue_loop():
    """Поставить _process_queue_loop в очередь на следующий кадр.

    Идемпотентно: если цепочка уже запланирована - ничего не делает.
    Вызывается из нескольких мест (старт модуля, закрытие модалок),
    чтобы после любого сбоя цепочка возобновлялась.
    """
    global _queue_loop_scheduled
    if _queue_loop_scheduled:
        return
    try:
        _queue_loop_scheduled = True
        dpg.set_frame_callback(dpg.get_frame_count() + 1,
                               _process_queue_loop)
    except Exception as e:
        _queue_loop_scheduled = False
        print(f"[FreqMeasure] schedule error: {e}")

_process_counter = 0

def _process_queue_loop():
    global _queue_loop_scheduled, _process_counter
    _queue_loop_scheduled = False
    _process_counter += 1
    if _process_counter % 60 == 0 and _controller is not None:
        print(f"[FreqMeasure] ticks={_process_counter} "
              f"qsize={_controller.data_queue.qsize()} "
              f"state={_controller.state} "
              f"mcu={_controller.current_mcu}")
    try:
        if _controller is not None:
            _controller.process_queue()
    except Exception as e:
        import traceback
        print(f"[FreqMeasure] queue error: {e}")
        traceback.print_exc()
    _schedule_queue_loop()


def _process_queue_loop_test():
    """Один шаг перекачки очереди данных контроллера в UI.

    Всегда перепланируется, даже если сам шаг упал с ошибкой -
    иначе цепочка оборвётся навсегда и модуль «зависнет» в
    WAIT_SIGNAL.
    """
    global _queue_loop_scheduled
    _queue_loop_scheduled = False

    try:
        if _controller is not None:
            _controller.process_queue()
    except Exception as e:
        import traceback
        print(f"[FreqMeasure] queue error: {e}")
        traceback.print_exc()

    _schedule_queue_loop()


class ResonatorGUI:
    """Всё, что связано с DearPyGui. Логику берёт из controller."""

    def __init__(self, controller, window_tag=WINDOW_TAG):
        self.c = controller
        self.window_tag = window_tag
        self._plot_series_tags = []
        self._log_lines = []

        self._wire_controller_hooks()
        self.build_gui()

    # =========================================================== wiring
    def _wire_controller_hooks(self):
        c = self.c
        c.on_log = self._append_log
        c.on_state_changed = lambda st: dpg.set_value('lbl_state', st)
        c.on_device_status = lambda text: dpg.set_value('status_device', text)
        c.on_mcu_labels = self._update_mcu_labels
        c.on_ask_mcu_dialog = self.show_mcu_dialog
        c.on_ask_resonator_dialog = self.show_resonator_dialog
        c.on_measurement_finished = self._on_measurement_finished
        c.on_summary_updated = self.update_summary_table
        c.on_plot_refresh = self.refresh_plot_series
        c.on_plot_live = self.update_plot_live
        c.on_pdf_created = _open_file

        c.epsilon_provider = lambda: (
            dpg.get_value('inp_epsilon')
            if dpg.does_item_exist('inp_epsilon')
            else c.meas_cfg.get('epsilon', 2.0)
        )

    # =========================================================== log
    def _append_log(self, line):
        self._log_lines.append(line)
        if len(self._log_lines) > 200:
            self._log_lines = self._log_lines[-200:]
        dpg.set_value('lbl_log', '\n'.join(self._log_lines))
        try:
            dpg.set_y_scroll('lbl_log', 1e9)
        except Exception:
            pass

    # =========================================================== hooks
    def _update_mcu_labels(self, mcu, nominal_khz):
        dpg.set_value('lbl_mcu', mcu)
        dpg.set_value('lbl_nominal', f'{nominal_khz:.6f} кГц')
        if dpg.does_item_exist('inp_nominal_khz'):
            dpg.set_value('inp_nominal_khz', f'{nominal_khz:g}')

    def _on_measurement_finished(self, m):
        info = (
            f"Резонатор {m['resonator']}  |  цикл {m['cycle']}\n"
            f"Номинал: {m['nominal_khz']:.6f} кГц\n"
            f"Точек: {len(m['f'])}   Длительность: {m['t'][-1]:.1f} с\n"
            f"Макс: {m['max']:.3f} Гц ({m['max_ppm']:+.3f} ppm)\n"
            f"Мин:  {m['min']:.3f} Гц ({m['min_ppm']:+.3f} ppm)\n"
            f"Монотонность: {m['mono_ppm']:.3f} ppm\n"
            f"Макс. выброс: {m['max_outlier_ppm']:.3f} ppm\n"
            f"Причина остановки: {m['reason']}"
        )
        dpg.set_value('lbl_done_info', info)
        dpg.configure_item('dlg_done', show=True)

    def show_mcu_dialog(self):
        dpg.configure_item('dlg_mcu', show=True)
        dpg.focus_item('inp_mcu')

    def show_resonator_dialog(self):
        if dpg.does_item_exist('dlg_done') and dpg.is_item_shown('dlg_done'):
            dpg.configure_item('dlg_done', show=False)
        dpg.configure_item('dlg_res', show=True)
        dpg.focus_item('inp_res')
        dpg.set_value('inp_res', '')

    # =========================================================== GUI build
    def build_gui(self):
        with dpg.font_registry():
            font_path = self.c.cfg['pdf'].get('font_path', '')
            candidates = [font_path,
                          'C:/Windows/Fonts/DejaVuSans.ttf',
                          'C:/Windows/Fonts/arial.ttf']
            font_loaded = None
            for p in candidates:
                if p and os.path.exists(p):
                    try:
                        font_loaded = dpg.add_font(p, 16)
                        break
                    except Exception:
                        pass
            if font_loaded is None:
                font_loaded = dpg.add_font_range_hint(
                    dpg.mvFontRangeHint_Cyrillic)
            dpg.bind_font(font_loaded)

        with dpg.theme(tag='theme_bad_row'):
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_Text, (255, 60, 60, 255))
            with dpg.theme_component(dpg.mvTableRow):
                dpg.add_theme_color(dpg.mvThemeCol_Header, (120, 0, 0, 255))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered,
                                    (160, 0, 0, 255))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive,
                                    (160, 0, 0, 255))

        sw, sh = _get_screen_size()
        w = int(sw * 0.85)
        h = int(sh * 0.90)
        pos_x = max(10, (sw - w) // 2)
        pos_y = max(10, (sh - h) // 2)

        with dpg.window(tag=self.window_tag,
                        label='CH3-85/6 - Freq measurement TGK',
                        width=w, height=h, pos=(pos_x, pos_y),
                        no_collapse=True):
            with dpg.group(horizontal=True):
                dpg.add_text('МСК:')
                dpg.add_text('-', tag='lbl_mcu')
                dpg.add_text('| Номинал:')
                dpg.add_text('-', tag='lbl_nominal')
                dpg.add_button(label='Новая МСК', callback=self.on_new_mcu)
                dpg.add_spacer(width=20)
                dpg.add_text('Устройство:')
                dpg.add_text('-', tag='status_device')
                dpg.add_spacer(width=20)
                dpg.add_text('Состояние:')
                dpg.add_text('-', tag='lbl_state')

            dpg.add_separator()

            with dpg.group(horizontal=True):
                dpg.add_text('Текущий резонатор:')
                dpg.add_text('-', tag='lbl_resonator')
                dpg.add_spacer(width=20)
                dpg.add_text('Цикл:')
                dpg.add_text('-', tag='lbl_cycle')
                dpg.add_spacer(width=20)
                dpg.add_text('Epsilon (ppm):')
                dpg.add_input_float(tag='inp_epsilon', width=100,
                                    default_value=self.c.meas_cfg['epsilon'],
                                    step=0.1, format='%.3f')
                dpg.add_spacer(width=20)
                dpg.add_button(label='Настройки',
                               callback=self.on_open_settings)
                dpg.add_button(label='Сохранить в БД',
                               callback=self.on_save_db)
                dpg.add_button(label='PDF: сводная таблица',
                               callback=self.on_pdf_table)
                dpg.add_button(label='PDF: графики',
                               callback=self.on_pdf_graphs)

            dpg.add_separator()

            with dpg.group(horizontal=True):
                with dpg.child_window(width=760, height=440,
                                      tag='summary_panel'):
                    dpg.add_text('Сводная таблица (ppm относительно '
                                 'номинала МСК; клик по No - показать график)')
                    with dpg.table(tag='summary_table', header_row=True,
                                   policy=dpg.mvTable_SizingFixedFit,
                                   scrollY=True, height=400):
                        dpg.add_table_column(label='No', width_fixed=True,
                                             init_width_or_weight=55)
                        dpg.add_table_column(label='Резонатор',
                                             init_width_or_weight=140)
                        dpg.add_table_column(label='Макс, ppm',
                                             init_width_or_weight=100)
                        dpg.add_table_column(label='Мин, ppm',
                                             init_width_or_weight=100)
                        dpg.add_table_column(label='Монот., ppm',
                                             init_width_or_weight=100)
                        dpg.add_table_column(label='Выброс, ppm',
                                             init_width_or_weight=100)
                        dpg.add_table_column(label='Статус',
                                             init_width_or_weight=90)

                with dpg.group():
                    with dpg.group(horizontal=True):
                        dpg.add_text('Просмотр:')
                        dpg.add_radio_button(
                            tag='plot_filter',
                            items=['MAX_TO_NORMAL',
                                   'MINUS60_TO_NORMAL',
                                   'BOTH'],
                            default_value='BOTH',
                            horizontal=True,
                            callback=self.on_filter_changed,
                        )
                        dpg.add_spacer(width=15)
                        dpg.add_button(
                            label='Автомасштаб',
                            callback=lambda *_: self.autoscale_plot())

                    dpg.add_text('График: (пусто)', tag='plot_label')

                    with dpg.plot(tag='plot', height=340, width=-1,
                                  anti_aliased=True):
                        dpg.add_plot_legend()
                        dpg.add_plot_axis(dpg.mvXAxis, label='Время, с',
                                          tag='x_axis')
                        with dpg.plot_axis(dpg.mvYAxis,
                                           label='Отклонение, ppm',
                                           tag='y_axis'):
                            pass

            dpg.add_separator()
            dpg.add_text('Лог:')
            dpg.add_input_text(tag='lbl_log', readonly=True,
                               width=-1, height=-1,
                               multiline=True, default_value='')

        # ---- диалоги ----
        with dpg.window(tag='dlg_mcu', modal=True, show=False,
                        no_title_bar=True, width=460, height=230,
                        pos=(480, 280)):
            dpg.add_text('Введите номер МСК:')
            dpg.add_input_text(tag='inp_mcu', width=-1, on_enter=True,
                               callback=lambda *_: self.on_mcu_ok())
            dpg.add_spacer(height=6)
            dpg.add_text('Номинал частоты МСК, кГц:')
            dpg.add_input_text(tag='inp_nominal_khz', width=-1,
                               default_value='10000', on_enter=True,
                               callback=lambda *_: self.on_mcu_ok())
            dpg.add_spacer(height=10)
            with dpg.group(horizontal=True):
                dpg.add_button(label='OK', callback=self.on_mcu_ok,
                               width=100)
                dpg.add_button(label='Отмена', callback=self.on_mcu_cancel,
                               width=100)

        with dpg.window(tag='dlg_res', modal=True, show=False,
                        no_title_bar=True, width=460, height=240,
                        pos=(480, 280)):
            dpg.add_text('Обнаружен новый резонатор!')
            dpg.add_text('Введите номер резонатора:')
            # ФИКС: было set_frame_callback(1, ...) - кадр 1 давно прошёл,
            # колбэк никогда не срабатывал.
            dpg.add_input_text(tag='inp_res', width=-1, on_enter=True,
                               callback=lambda *_: dpg.set_frame_callback(
                                   dpg.get_frame_count() + 1,
                                   self.on_res_ok))
            dpg.add_spacer(height=6)
            dpg.add_text('Тип цикла:')
            dpg.add_radio_button(tag='inp_cycle',
                                 items=['MAX_TO_NORMAL',
                                        'MINUS60_TO_NORMAL'],
                                 default_value='MAX_TO_NORMAL')
            dpg.add_spacer(height=8)
            with dpg.group(horizontal=True):
                dpg.add_button(label='Начать', callback=self.on_res_ok,
                               width=100)
                dpg.add_button(label='Пропустить',
                               callback=self.on_res_skip, width=100)

        with dpg.window(tag='dlg_done', modal=True, show=False,
                        no_title_bar=True, width=560, height=280,
                        pos=(440, 280)):
            dpg.add_text('Измерение завершено', tag='lbl_done_title')
            dpg.add_text('', tag='lbl_done_info', wrap=540)
            dpg.add_spacer(height=10)
            dpg.add_button(label='OK', callback=self.on_done_ok, width=100)

        with dpg.window(tag='dlg_settings', modal=True, show=False,
                        no_title_bar=True, width=560, height=620,
                        pos=(440, 140)):
            dpg.add_text('Настройки (config.json)')
            dpg.add_separator()

            dpg.add_text('Измерение')
            with dpg.group(horizontal=True):
                dpg.add_text('Epsilon (ppm):')
                dpg.add_input_float(tag='set_epsilon', width=120,
                                    step=0.1, format='%.4f')
                dpg.add_spacer(width=20)
                dpg.add_text('Окно epsilon:')
                dpg.add_input_int(tag='set_epsilon_window', width=120)

            with dpg.group(horizontal=True):
                dpg.add_text('Мин. длительность, с:')
                dpg.add_input_float(tag='set_min_duration', width=120,
                                    step=1.0, format='%.2f')
                dpg.add_spacer(width=20)
                dpg.add_text('Макс. длительность, с:')
                dpg.add_input_float(tag='set_max_duration', width=120,
                                    step=60.0, format='%.1f')

            with dpg.group(horizontal=True):
                dpg.add_text('Мин. частота, Гц:')
                dpg.add_input_float(tag='set_min_frequency', width=120,
                                    step=100.0, format='%.1f')
                dpg.add_spacer(width=20)
                dpg.add_text('Стабильность сигнала, с:')
                dpg.add_input_float(tag='set_signal_stable', width=120,
                                    step=0.1, format='%.2f')

            dpg.add_separator()
            dpg.add_text('Устройство')
            with dpg.group(horizontal=True):
                dpg.add_text('Gate time, с:')
                dpg.add_input_float(tag='set_gate_time', width=120,
                                    step=0.01, format='%.3f')
                dpg.add_spacer(width=20)
                dpg.add_text('Опрос, с:')
                dpg.add_input_float(tag='set_poll_interval', width=120,
                                    step=0.01, format='%.3f')

            dpg.add_separator()
            dpg.add_text('Допусковый контроль (Статус)')
            with dpg.group(horizontal=True):
                dpg.add_text('Макс. отклонение, ppm:')
                dpg.add_input_float(tag='set_max_ppm', width=120,
                                    step=1.0, format='%.3f')
            with dpg.group(horizontal=True):
                dpg.add_text('Мин. отклонение, ppm:')
                dpg.add_input_float(tag='set_min_ppm', width=120,
                                    step=1.0, format='%.3f')
            with dpg.group(horizontal=True):
                dpg.add_text('Макс. монотонность, ppm:')
                dpg.add_input_float(tag='set_max_mono', width=120,
                                    step=1.0, format='%.3f')
            with dpg.group(horizontal=True):
                dpg.add_text('Порог выброса, ppm:')
                dpg.add_input_float(tag='set_outlier_threshold', width=120,
                                    step=1.0, format='%.3f')

            dpg.add_spacer(height=12)
            with dpg.group(horizontal=True):
                dpg.add_button(label='Сохранить',
                               callback=self.on_save_settings, width=120)
                dpg.add_button(label='Отмена',
                               callback=lambda *_: dpg.configure_item(
                                   'dlg_settings', show=False),
                               width=120)

    # =========================================================== dialogs
    def on_new_mcu(self, s=None, a=None):
        self.c.current_mcu = None
        self.c.current_mcu_nominal_khz = None
        self.c.ask_mcu()
        _schedule_queue_loop()

    def on_mcu_ok(self, s=None, a=None):
        if not dpg.is_item_shown('dlg_mcu'):
            return
        val = str(dpg.get_value('inp_mcu')).strip()
        nominal_raw = str(dpg.get_value('inp_nominal_khz')).strip()\
            .replace(',', '.')
        try:
            nominal_khz = float(nominal_raw)
        except ValueError:
            self.c.log(f'Некорректный номинал: {nominal_raw!r}')
            return
        if not val or nominal_khz <= 0:
            self.c.log(f'Некорректный ввод: МСК="{val}", '
                       f'номинал={nominal_khz}')
            return
        dpg.configure_item('dlg_mcu', show=False)
        self.c.set_mcu(val, nominal_khz)
        _schedule_queue_loop()

    def on_mcu_cancel(self, s=None, a=None):
        dpg.configure_item('dlg_mcu', show=False)
        _schedule_queue_loop()

    def on_res_ok(self, s=None, a=None):
        if not dpg.is_item_shown('dlg_res'):
            return
        res = dpg.get_value('inp_res').strip()
        if not res:
            return
        cycle = dpg.get_value('inp_cycle')
        dpg.set_value('lbl_resonator', res)
        dpg.set_value('lbl_cycle', cycle)
        dpg.configure_item('dlg_res', show=False)
        try:
            self.c.begin_measurement(res, cycle)
        except Exception as e:
            import traceback
            self.c.log(f'Ошибка запуска измерения: {e}')
            traceback.print_exc()
        _schedule_queue_loop()

    def on_res_skip(self, s=None, a=None):
        dpg.configure_item('dlg_res', show=False)
        _schedule_queue_loop()

    def on_done_ok(self, s=None, a=None):
        dpg.configure_item('dlg_done', show=False)
        _schedule_queue_loop()

    # =========================================================== settings
    def on_open_settings(self, s=None, a=None):
        m = self.c.meas_cfg
        dpg.set_value('set_epsilon', m.get('epsilon', 2.0))
        dpg.set_value('set_epsilon_window', int(m.get('epsilon_window', 15)))
        dpg.set_value('set_min_duration', m.get('min_duration', 10.0))
        dpg.set_value('set_max_duration', m.get('max_duration', 3600.0))
        dpg.set_value('set_min_frequency', m.get('min_frequency', 1000.0))
        dpg.set_value('set_signal_stable', m.get('signal_stable_time', 0.5))
        dpg.set_value('set_gate_time', self.c.dev_cfg.get('gate_time', 0.1))
        dpg.set_value('set_poll_interval',
                      self.c.dev_cfg.get('poll_interval', 0.05))

        ac = self.c.accept_cfg
        dpg.set_value('set_max_ppm', ac.get('max_ppm', 100.0))
        dpg.set_value('set_min_ppm', ac.get('min_ppm', -100.0))
        dpg.set_value('set_max_mono',
                      ac.get('max_monotonicity_ppm', 50.0))
        dpg.set_value('set_outlier_threshold',
                      ac.get('outlier_threshold_ppm', 20.0))

        dpg.configure_item('dlg_settings', show=True)

    def on_save_settings(self, s=None, a=None):
        from .config import save_config
        try:
            cfg = self.c.cfg
            cfg['measurement']['epsilon'] = float(
                dpg.get_value('set_epsilon'))
            cfg['measurement']['epsilon_window'] = int(
                dpg.get_value('set_epsilon_window'))
            cfg['measurement']['min_duration'] = float(
                dpg.get_value('set_min_duration'))
            cfg['measurement']['max_duration'] = float(
                dpg.get_value('set_max_duration'))
            cfg['measurement']['min_frequency'] = float(
                dpg.get_value('set_min_frequency'))
            cfg['measurement']['signal_stable_time'] = float(
                dpg.get_value('set_signal_stable'))
            cfg['device']['gate_time'] = float(
                dpg.get_value('set_gate_time'))
            cfg['device']['poll_interval'] = float(
                dpg.get_value('set_poll_interval'))
            cfg['acceptance'] = {
                'max_ppm': float(dpg.get_value('set_max_ppm')),
                'min_ppm': float(dpg.get_value('set_min_ppm')),
                'max_monotonicity_ppm': float(dpg.get_value('set_max_mono')),
                'outlier_threshold_ppm': float(
                    dpg.get_value('set_outlier_threshold')),
            }
            save_config(cfg)

            self.c.meas_cfg = cfg['measurement']
            self.c.dev_cfg = cfg['device']
            self.c.accept_cfg = cfg['acceptance']

            dpg.set_value('inp_epsilon', self.c.meas_cfg['epsilon'])
            self.update_summary_table()
            dpg.configure_item('dlg_settings', show=False)
            self.c.log('Настройки сохранены в config.json')
        except Exception as e:
            self.c.log(f'Ошибка сохранения настроек: {e}')
        _schedule_queue_loop()

    # =========================================================== plot
    def refresh_plot_series(self):
        for tag in self._plot_series_tags:
            if dpg.does_item_exist(tag):
                dpg.delete_item(tag)
        self._plot_series_tags.clear()

        c = self.c
        filt = (dpg.get_value('plot_filter')
                if dpg.does_item_exist('plot_filter') else 'BOTH')

        if c.state == c.ST_MEASURING:
            if c.cur_f and c.current_mcu_nominal_khz:
                ref_hz = c.current_mcu_nominal_khz * 1e3
                y_ppm = [to_ppm(v, ref_hz) for v in c.cur_f]
                color = CYCLE_COLORS.get(c.current_cycle, (255, 255, 255))
                label = f"LIVE {c.current_resonator} ({c.current_cycle})"
                dpg.add_line_series(c.cur_t, y_ppm, parent='y_axis',
                                    tag='series_live', label=label)
                dpg.bind_item_theme('series_live',
                                    self._make_series_theme(color))
                self._plot_series_tags.append('series_live')
            dpg.set_value('plot_label',
                          f"LIVE: резонатор {c.current_resonator} "
                          f"({c.current_cycle})")
            self.autoscale_plot()
            return

        if c.selected_resonator is None:
            dpg.set_value('plot_label',
                          'График: (кликните No в таблице для просмотра)')
            self.autoscale_plot()
            return

        shown = 0
        for i, m in enumerate(c.measurements):
            if m['resonator'] != c.selected_resonator:
                continue
            if filt != 'BOTH' and m['cycle'] != filt:
                continue
            if not m.get('t') or not m.get('f'):
                continue

            nominal_khz = (m.get('nominal_khz')
                           or c.current_mcu_nominal_khz or 0)
            ref_hz = nominal_khz * 1e3
            if ref_hz <= 0:
                continue

            y_ppm = [to_ppm(v, ref_hz) for v in m['f']]

            tag = f'series_view_{i}'
            label = f"{m['resonator']} ({m['cycle']})"
            dpg.add_line_series(m['t'], y_ppm, parent='y_axis',
                                tag=tag, label=label)
            color = CYCLE_COLORS.get(m['cycle'], (255, 255, 255))
            dpg.bind_item_theme(tag, self._make_series_theme(color))
            self._plot_series_tags.append(tag)
            shown += 1

        dpg.set_value('plot_label',
                      f"Резонатор {c.selected_resonator} - "
                      f"серий: {shown} (фильтр: {filt})")
        self.autoscale_plot()

    def update_plot_live(self):
        c = self.c
        if c.state != c.ST_MEASURING:
            return
        if not dpg.does_item_exist('series_live'):
            self.refresh_plot_series()
            return
        if not c.cur_f or not c.current_mcu_nominal_khz:
            return

        ref_hz = c.current_mcu_nominal_khz * 1e3
        y_ppm = [to_ppm(v, ref_hz) for v in c.cur_f]

        x = list(c.cur_t)
        if len(x) > 5000:
            idx = np.linspace(0, len(x) - 1, 5000).astype(int)
            x = [x[i] for i in idx]
            y_ppm = [y_ppm[i] for i in idx]

        dpg.set_value('series_live', [x, y_ppm])
        self.autoscale_plot()

    def autoscale_plot(self):
        try:
            dpg.fit_axis_data('x_axis')
            dpg.fit_axis_data('y_axis')
        except Exception:
            pass

    def _make_series_theme(self, rgb):
        tag = f'theme_{rgb[0]}_{rgb[1]}_{rgb[2]}'
        if dpg.does_item_exist(tag):
            return tag
        with dpg.theme(tag=tag):
            with dpg.theme_component(dpg.mvLineSeries):
                dpg.add_theme_color(dpg.mvPlotCol_Line, (*rgb, 255),
                                    category=dpg.mvThemeCat_Plots)
                dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 1.0,
                                    category=dpg.mvThemeCat_Plots)
        return tag

    def on_filter_changed(self, s, a):
        self.refresh_plot_series()

    # =========================================================== summary
    def on_resonator_selected(self, sender, app_data, user_data):
        if self.c.state == self.c.ST_MEASURING:
            self.c.log('Идёт измерение - выбор резонатора заблокирован')
            return
        self.c.selected_resonator = user_data['resonator']
        self.c.log(f"Показан график резонатора {self.c.selected_resonator}")
        self.update_summary_table()
        self.refresh_plot_series()

    def on_resonator_edited(self, sender, app_data, user_data):
        old = user_data['resonator']
        new = app_data
        if self.c.rename_resonator(old, new):
            self.c.log(f'Резонатор {old} -> {new}')

    def update_summary_table(self):
        if not dpg.does_item_exist('summary_table'):
            return
        dpg.delete_item('summary_table', children_only=True, slot=1)
        rows = self.c.build_summary_rows()
        for i, r in enumerate(rows, 1):
            is_sel = (r['resonator'] == self.c.selected_resonator)
            label = f"{i} *" if is_sel else str(i)

            row_id = dpg.add_table_row(parent='summary_table')

            dpg.add_button(label=label, width=55, user_data=r,
                           callback=self.on_resonator_selected,
                           parent=row_id)
            dpg.add_input_text(default_value=r['resonator'], width=140,
                               user_data=r,
                               callback=self.on_resonator_edited,
                               parent=row_id)
            dpg.add_text(f"{r['max_ppm']:+.3f}"
                         if r['max_ppm'] is not None else '-', parent=row_id)
            dpg.add_text(f"{r['min_ppm']:+.3f}"
                         if r['min_ppm'] is not None else '-', parent=row_id)
            dpg.add_text(f"{r['monotonicity_ppm']:.3f}", parent=row_id)
            mo = r.get('max_outlier_ppm', 0.0) or 0.0
            dpg.add_text(f"{mo:.3f}" if mo > 0 else "-", parent=row_id)
            dpg.add_text(r['status'], parent=row_id)

            if r['status'] == 'Брак':
                dpg.bind_item_theme(row_id, 'theme_bad_row')

    # =========================================================== actions
    def on_save_db(self, s=None, a=None):
        eps = (dpg.get_value('inp_epsilon')
               if dpg.does_item_exist('inp_epsilon') else 0.0)
        self.c.save_to_db(eps)

    def on_pdf_table(self, s=None, a=None):
        try:
            self.c.export_summary()
        except Exception as e:
            self.c.log(f'Ошибка PDF: {e}')

    def on_pdf_graphs(self, s=None, a=None):
        try:
            filt = (dpg.get_value('plot_filter')
                    if dpg.does_item_exist('plot_filter') else 'BOTH')
            if filt == 'BOTH':
                data = self.c.measurements
            else:
                data = [m for m in self.c.measurements if m['cycle'] == filt]
            self.c.export_graphs(data)
        except Exception as e:
            self.c.log(f'Ошибка PDF: {e}')


# ============================================================================
# Интеграция с основным приложением
# ============================================================================
def _register_for_window_manager():
    try:
        from window_manager import register, rebuild_menu
    except Exception:
        return
    try:
        register(WINDOW_TAG,
                 "Измерение частоты (Ч3-85/6)",
                 create_frequency_measure_window)
        rebuild_menu()
    except Exception as e:
        print(f"[FreqMeasure] window_manager register error: {e}")


def create_frequency_measure_window():
    global _controller, _gui

    if dpg.does_item_exist(WINDOW_TAG):
        dpg.configure_item(WINDOW_TAG, show=True)
        try:
            dpg.focus_item(WINDOW_TAG)
        except Exception:
            pass
        _register_for_window_manager()
        _schedule_queue_loop()
        return

    if _controller is not None:
        dpg.configure_item(WINDOW_TAG, show=True)
        _register_for_window_manager()
        _schedule_queue_loop()
        return

    try:
        cfg = load_config()
    except Exception as e:
        print(f"[FreqMeasure] load_config error: {e}")
        return

    _controller = MeasurementController(cfg)
    _gui = ResonatorGUI(_controller, window_tag=WINDOW_TAG)
    # Сообщаем главному циклу комплекса: опрашивай мою очередь.
    # В standalone (python -m FrequencyMeasure.app) register_controller
    # в builtins нет — молча пропускаем.
    try:
        from builtins import register_controller
        register_controller(_controller)
    except Exception:
        pass

    # ФИКС: планируем обработку очереди ДО открытия модального
    # окна МСК, иначе цепочка кадровых колбэков может не запуститься
    # в контексте модального диалога.
    _schedule_queue_loop()

    try:
        _controller.start_device()
        _controller.start_worker()
    except Exception as e:
        _controller.log(f"Ошибка запуска устройства: {e}")

    _controller.ask_mcu()

    _register_for_window_manager()


def show_frequency_measure_window(sender=None, app_data=None, dpg_ref=None):
    create_frequency_measure_window()