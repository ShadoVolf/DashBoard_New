"""
Окно виртуального замера на DearPyGui.

Кнопки действий — на левой панели:
    * Генерация           — генерирует замер и показывает форму;
    * Сохранить в БД      — сохраняет сгенерированный замер;
    * Предпросмотр        — открыть форму с уже сгенерированными данными;
    * Печать протокола    — PDF протокол;
    * Распечатка          — PDF распечатка температур.

Правая панель — статистика по параметру: базовый vs виртуальный
Measure_ID (плотность распределения + метрики).

Поиск базового замера (по образцу модуля Архив):
    * фильтр МСК в текущем списке (быстрый, по уже загруженным);
    * глобальный поиск МСК по части номера в БД (LIKE '%...%') —
      результаты складываются в combo vmsk_combo;
    * поиск Measure_ID по номерам резонаторов через справочник
      psidata_resonator_lookup + fallback — результаты складываются
      в combo vbase_mid_combo;
    * прямой ввод МСК и Measure_ID.

Окно прогресса открывается СРАЗУ при старте операции, логирует каждый
шаг со штампом времени, автоматически закрывается по завершении.
"""
import threading
import time
import traceback
from datetime import datetime

import dearpygui.dearpygui as dpg
import pandas as pd

from Temperature_Measure import _layout
from . import Virtual_Data as vd
from . import Virtual_Stats as vs
from . import Virtual_Settings as vset

try:
    from Archive_View.Archive_Data import (
        prepare_temperatures_for_pdf,
        build_archive_print_data,
        build_archive_status_df,
        build_view_data_from_archive,
        get_archive_statistics,
        get_headers_dict,
        get_round_dict,
        load_spc_map_for_archive,
    )
    from Temperature_Measure.Report import (
        create_protocol, generate_pdf, open_pdf, generate_filename,
    )
    HAS_PREVIEW = True
except ImportError as _e:
    print(f"[Virtual] PDF preview unavailable: {_e}", flush=True)
    HAS_PREVIEW = False


# ============================================================================
# Логирование
# ============================================================================
_DEBUG = True


def _ts():
    return datetime.now().strftime("%H:%M:%S.%f")[:-3]


def _log(msg):
    if _DEBUG:
        print(f"[Virtual {_ts()}] {msg}", flush=True)


def _log_exc(context, exc=None):
    print(f"[Virtual {_ts()}] ERROR in {context}: "
          f"{exc or 'см. traceback'}", flush=True)
    traceback.print_exc()


# ============================================================================
# Теги
# ============================================================================
WINDOW_TAG      = 'virtual_measure_window'
PREVIEW_TAG     = 'virtual_preview_window'
NUMBERS_TAG     = 'virtual_numbers_dialog'
SETTINGS_TAG    = 'virtual_settings_dialog'
PROGRESS_TAG    = 'virtual_progress_window'
PROGRESS_TEXT   = 'virtual_progress_text'
PROGRESS_BAR    = 'virtual_progress_bar'
PROGRESS_DETAIL = 'virtual_progress_detail'

STATUS_LABEL    = 'vstatus_label'
NEW_MID_LABEL   = 'vnew_mid_label'
PARAM_COMBO     = 'vparam_combo'
VIRT_MID_COMBO  = 'vvirt_mid_combo'
PLOT_TAG        = 'vdist_plot'
PLOT_Y_AXIS     = 'vdist_y_axis'
STATS_TABLE     = 'vstats_table'

PROGRESS_TIMEOUT_SEC = 180

_state = {
    'preview':     None,
    'numbers':     [],
    'mode':        'Все',
    'virtual_mid': None,
    'machine_info': None,
    'all_msks':    [],
}

_suppress_cascade = False


# ============================================================================
# Прогресс-индикатор (через register_controller из main.py)
# ============================================================================
_progress = {
    'active':       False,
    'token':        0,
    'title':        'Операция',
    'percent':      0.0,
    'message':      '',
    'detail':       '',
    'done':         False,
    'result':       None,
    'error':        None,
    'on_done':      None,
    'on_error':     None,
    'start_time':   0.0,
    'window_shown': False,
}

_current_token = 0
PROGRESS_TIMEOUT_SEC = 180


def _progress_update(percent, message, detail=''):
    try:
        _progress['percent'] = float(percent)
        _progress['message'] = str(message)
        _progress['detail']  = str(detail)
    except Exception:
        pass


def _show_progress_window():
    try:
        if dpg.does_item_exist(PROGRESS_TAG):
            try:
                dpg.delete_item(PROGRESS_TAG)
            except Exception:
                pass

        sw, sh = _layout.screen_size()
        w, h = 540, 180
        x = (sw - w) // 2
        y = (sh - h) // 2
        title = _progress.get('title') or 'Операция'

        with dpg.window(label=title, tag=PROGRESS_TAG,
                        width=w, height=h, pos=(x, y),
                        no_close=True, no_collapse=True,
                        no_resize=True):
            dpg.add_text("Подготовка...", tag=PROGRESS_TEXT)
            dpg.add_spacer(height=6)
            dpg.add_progress_bar(tag=PROGRESS_BAR, width=-1,
                                 default_value=0.0)
            dpg.add_spacer(height=6)
            dpg.add_text("", tag=PROGRESS_DETAIL,
                         color=(150, 150, 150))
        _log(f"progress window показано: '{title}'")
        return True
    except Exception as e:
        _log_exc("_show_progress_window", e)
        return False


def _cleanup_progress_window():
    try:
        if dpg.does_item_exist(PROGRESS_TAG):
            dpg.delete_item(PROGRESS_TAG)
            _log("progress window удалено")
    except Exception as e:
        _log_exc("_cleanup_progress_window", e)


def _update_progress_ui():
    try:
        if dpg.does_item_exist(PROGRESS_BAR):
            p = max(0.0, min(1.0, float(_progress['percent']) / 100.0))
            dpg.set_value(PROGRESS_BAR, p)
        if dpg.does_item_exist(PROGRESS_TEXT):
            dpg.set_value(PROGRESS_TEXT,
                          _progress.get('message', ''))
        if dpg.does_item_exist(PROGRESS_DETAIL):
            dpg.set_value(PROGRESS_DETAIL,
                          _progress.get('detail', ''))
    except Exception as e:
        _log_exc("_update_progress_ui", e)


# ---------------------------------------------------------------------------
# Контроллер, регистрируемый в main.py — опрашивается каждый кадр
# ---------------------------------------------------------------------------
class _ProgressController:
    """Опрашивает состояние прогресса раз в кадр из главного цикла."""

    def process_queue(self):
        try:
            if not _progress.get('active'):
                return
            if _progress.get('token') != _current_token:
                return

            if not dpg.does_item_exist(WINDOW_TAG):
                _log("controller: главное окно закрыто — очистка")
                _progress['active'] = False
                _cleanup_progress_window()
                return

            elapsed = time.time() - _progress.get('start_time', 0)
            if (elapsed > PROGRESS_TIMEOUT_SEC
                    and not _progress.get('done')):
                _log(f"controller: таймаут {elapsed:.1f}s")
                _progress['error'] = (
                    f"таймаут операции ({int(elapsed)}s)")
                _progress['done'] = True

            if _progress.get('done'):
                _finish_progress()
                return

            _update_progress_ui()
        except Exception as e:
            print(f"[Virtual {_ts()}] controller error: {e}",
                  flush=True)
            try:
                if not _progress.get('done'):
                    _progress['error'] = f"controller: {e}"
                    _progress['done'] = True
                    _finish_progress()
            except Exception:
                pass


_progress_controller = _ProgressController()
_controller_registered = False


def _register_progress_controller():
    """Зарегистрировать контроллер в главном цикле main.py."""
    global _controller_registered
    if _controller_registered:
        return
    try:
        import builtins
        register = getattr(builtins, 'register_controller', None)
        if register is not None:
            register(_progress_controller)
            _controller_registered = True
            _log("progress controller зарегистрирован")
        else:
            _log("builtins.register_controller недоступен — "
                 "использую только set_frame_callback")
    except Exception as e:
        _log_exc("_register_progress_controller", e)


# ---------------------------------------------------------------------------
# Fallback: set_frame_callback на случай отсутствия register_controller
# ---------------------------------------------------------------------------
def _reschedule_poll():
    try:
        dpg.set_frame_callback(
            dpg.get_frame_count() + 1, _poll_progress)
    except Exception as e:
        print(f"[Virtual {_ts()}] _reschedule_poll: {e}", flush=True)


def _poll_progress():
    """Резервный механизм, если register_controller недоступен."""
    try:
        if not _progress.get('active'):
            return
        if _progress.get('token') != _current_token:
            return
        if not dpg.does_item_exist(WINDOW_TAG):
            _progress['active'] = False
            _cleanup_progress_window()
            return
        if _progress.get('done'):
            _finish_progress()
            return
        _update_progress_ui()
        _reschedule_poll()
    except Exception as e:
        print(f"[Virtual {_ts()}] _poll_progress: {e}", flush=True)
        try:
            _reschedule_poll()
        except Exception:
            pass


def _start_polling():
    _register_progress_controller()
    _reschedule_poll()


def _finish_progress():
    # guard: если уже завершено — выходим
    if not _progress.get('active'):
        return

    print(f"[Virtual {_ts()}] _finish_progress: start", flush=True)
    _progress['active'] = False
    _cleanup_progress_window()

    if _progress.get('error'):
        err = str(_progress['error'])
        _log(f"_finish_progress: ошибка: {err}")
        try:
            dpg.set_value(NEW_MID_LABEL, f"Ошибка: {err}")
        except Exception:
            pass
        cb = _progress.get('on_error')
        if cb:
            try:
                cb(err)
            except Exception as e:
                _log_exc("on_error callback", e)
        return

    cb = _progress.get('on_done')
    if cb:
        try:
            cb(_progress.get('result'))
        except Exception as e:
            _log_exc("on_done callback", e)
            try:
                dpg.set_value(STATUS_LABEL,
                              f"Ошибка применения: {e}")
                dpg.set_value(NEW_MID_LABEL,
                              f"Ошибка применения: {e}")
            except Exception:
                pass


def _run_with_progress(worker, on_done=None, on_error=None,
                       start_msg='Подготовка...', title='Операция'):
    """Запустить worker() в фоне с немодальным окном прогресса."""
    global _current_token
    _current_token += 1
    token = _current_token

    _progress.update({
        'active':       True,
        'token':        token,
        'title':        title,
        'percent':      0.0,
        'message':      start_msg,
        'detail':       '',
        'done':         False,
        'result':       None,
        'error':        None,
        'on_done':      on_done,
        'on_error':     on_error,
        'start_time':   time.time(),
        'window_shown': False,
    })

    # 1. Показываем окно СРАЗУ
    _log(f"_run_with_progress: '{title}' — показ окна")
    ok = _show_progress_window()
    _progress['window_shown'] = ok
    _update_progress_ui()

    # 2. Воркер
    def _wrapper():
        t0 = time.time()
        try:
            _log(f"worker[{title}]: старт")
            result = worker()
            dt = time.time() - t0
            if token != _current_token:
                _log(f"worker[{title}]: устарел, отмена")
                return
            _progress['result']  = result
            _progress['percent'] = 100.0
            _progress['message'] = 'Готово'
            _progress['detail']  = ''
            _progress['done']    = True
            _log(f"worker[{title}]: OK ({dt:.2f}s)")
        except Exception as e:
            dt = time.time() - t0
            if token != _current_token:
                return
            _progress['error'] = str(e)
            _progress['done']  = True
            _log(f"worker[{title}]: FAILED ({dt:.2f}s): {e}")
            _log_exc(f"worker({title})", e)

    th = threading.Thread(target=_wrapper, daemon=True)
    th.start()

    # 3. Активируем опрос
    _start_polling()


# ============================================================================
# UI-утилиты
# ============================================================================
def _safe_set_combo(tag: str, items: list, value: str = ''):
    if not dpg.does_item_exist(tag):
        _log(f"_safe_set_combo: tag '{tag}' отсутствует")
        return
    items = list(items or [])
    try:
        dpg.set_value(tag, '')
    except Exception:
        pass
    try:
        dpg.configure_item(tag, items=items)
    except Exception as e:
        _log_exc(f"configure_item({tag}, len={len(items)})", e)
        return
    if value and value in items:
        dpg.set_value(tag, value)
    elif items:
        dpg.set_value(tag, items[0])
    else:
        dpg.set_value(tag, '')


def _get_combo_value(tag: str) -> str:
    if not dpg.does_item_exist(tag):
        return ''
    try:
        return dpg.get_value(tag) or ''
    except Exception:
        return ''


# ============================================================================
# Точка входа
# ============================================================================
def create_virtual_measure_window(dpg_ctx=None):
    try:
        if dpg.does_item_exist(WINDOW_TAG):
            dpg.configure_item(WINDOW_TAG, show=True)
            try:
                dpg.focus_item(WINDOW_TAG)
            except Exception:
                pass
            _register_for_window_manager()
            return

        _progress['active']       = False
        _progress['done']         = False
        _progress['window_shown'] = False
        if dpg.does_item_exist(PROGRESS_TAG):
            dpg.delete_item(PROGRESS_TAG)

        sw, sh = _layout.screen_size()
        margin = 8
        w = max(1100, sw - 2 * margin)
        h = max(700,  sh - 2 * margin)

        with dpg.window(label="Виртуальный замер",
                        tag=WINDOW_TAG, width=w, height=h,
                        pos=(margin, margin), no_collapse=True):
            with dpg.group(horizontal=True):
                with dpg.child_window(width=520, height=-1, border=True):
                    _build_left_panel()
                with dpg.child_window(width=-1, height=-1, border=True):
                    _build_right_panel()

        _bootstrap()
        _register_for_window_manager()
        _log("окно создано")
    except Exception as e:
        _log_exc("create_virtual_measure_window", e)


def _register_for_window_manager():
    try:
        from window_manager import register, rebuild_menu
    except Exception as e:
        _log(f"window_manager недоступен: {e}")
        return
    try:
        register(WINDOW_TAG, "Виртуальный замер",
                 create_virtual_measure_window)
        rebuild_menu()
    except Exception as e:
        _log_exc("register for window_manager", e)


# ============================================================================
# Левая панель
# ============================================================================
def _build_left_panel():
    # ------------------------------------------------------------------
    # 1. Базовый замер
    # ------------------------------------------------------------------
    dpg.add_text("Базовый замер", color=(180, 220, 255))
    dpg.add_separator()

    with dpg.group(horizontal=True):
        with dpg.group(width=220):
            dpg.add_text("Тип резонатора")
            dpg.add_combo([], tag='vtype_combo', width=220,
                          callback=_on_type_changed)
        with dpg.group(width=260):
            dpg.add_text("Спецификация")
            dpg.add_combo([], tag='vspc_combo', width=260,
                          callback=_on_spc_changed)

    # МСК: локальный фильтр по уже загруженному списку + combo
    with dpg.group(horizontal=True):
        with dpg.group(width=220):
            dpg.add_text("Фильтр МСК (в списке)")
            dpg.add_input_text(tag='vmsk_search_input', width=220,
                               hint="часть номера",
                               callback=_on_msk_search_changed)
        with dpg.group(width=260):
            dpg.add_text("МСК")
            dpg.add_combo([], tag='vmsk_combo', width=260,
                          callback=_on_msk_changed)

    dpg.add_text("", tag='vmsk_count_label', color=(150, 150, 150))

    # Глобальный поиск МСК в БД (LIKE '%...%')
    with dpg.group(horizontal=True):
        with dpg.group(width=220):
            dpg.add_text("Поиск МСК в БД (Enter)")
            dpg.add_input_text(tag='vmsk_db_search_input', width=220,
                               hint="напр. 2456",
                               on_enter=True,
                               callback=_on_msk_db_search)
        with dpg.group(width=260):
            dpg.add_text("")
            dpg.add_button(label="Найти МСК в БД", width=260,
                           callback=_on_msk_db_search)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text(
                    "Глобальный поиск по всей psidata.\n"
                    "LIKE '%часть%' по полю MSK.\n"
                    "Результаты — в списке МСК.")

    # Прямой ввод МСК по Enter
    with dpg.group(horizontal=True):
        with dpg.group(width=220):
            dpg.add_text("МСК вручную (Enter)")
            dpg.add_input_text(tag='vmsk_manual_input', width=220,
                               hint="напр. 25-2456",
                               on_enter=True,
                               callback=_on_msk_manual_enter)

    # Measure_ID + ручной ввод
    with dpg.group(horizontal=True):
        with dpg.group(width=220):
            dpg.add_text("Measure_ID базовый")
            dpg.add_combo([], tag='vbase_mid_combo', width=220,
                          callback=_on_base_mid_changed)
        with dpg.group(width=260):
            dpg.add_text("Ввести ID вручную (Enter)")
            dpg.add_input_text(tag='vbase_mid_input', width=260,
                               hint="напр. 84649", on_enter=True,
                               callback=_on_base_mid_manual)

    # Поиск по номерам резонаторов (через справочник, как в Архиве)
    with dpg.group(horizontal=True):
        with dpg.group(width=220):
            dpg.add_text("Поиск по номерам (Enter)")
            dpg.add_input_text(tag='vresonator_search_input', width=220,
                               hint="JN4450 | JN4450-JN4460",
                               on_enter=True,
                               callback=_on_resonator_search)
        with dpg.group(width=260):
            dpg.add_text("")
            dpg.add_button(label="Найти замеры по номерам",
                           width=260,
                           callback=_on_resonator_search)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text(
                    "Поиск Measure_ID по номерам резонаторов\n"
                    "через справочник psidata_resonator_lookup\n"
                    "(аналогично модулю Архив).\n"
                    "Результаты — в списке Measure_ID.")

    with dpg.group(horizontal=True):
        dpg.add_spacer(width=220)
        dpg.add_checkbox(label="Только годные",
                         tag='vonly_good_check',
                         default_value=False)

    # ------------------------------------------------------------------
    # 2. Выбор номеров
    # ------------------------------------------------------------------
    dpg.add_separator()
    dpg.add_text("Выбор номеров", color=(180, 220, 255))
    dpg.add_radio_button(
        ['Все', 'По интервалу', 'Списком'],
        tag='vnum_mode', horizontal=True, default_value='Все',
        callback=_on_num_mode_changed,
    )
    with dpg.group(tag='vnum_interval_group', show=False):
        dpg.add_text("Интервал или список номеров")
        dpg.add_input_text(tag='vnum_interval_input', width=-1,
                           hint="JN4450-JN4460  |  JN4450, JN4451")
    with dpg.group(tag='vnum_list_group', show=False):
        dpg.add_button(label="Выбрать номера...",
                       width=-1, height=28,
                       callback=lambda s, a: _show_numbers_dialog())
        dpg.add_text("", tag='vnum_selected_label',
                     color=(180, 255, 180))

    # ------------------------------------------------------------------
    # 3. Установка измерения
    # ------------------------------------------------------------------
    dpg.add_separator()
    dpg.add_text("Установка измерения", color=(180, 220, 255))
    dpg.add_text("Тип установки")
    dpg.add_combo([], tag='vmachine_type_combo', width=-1,
                  callback=_on_machine_type_changed)
    dpg.add_text("S/N установки")
    dpg.add_combo([], tag='vmachine_sn_combo', width=-1,
                  callback=_on_machine_sn_changed)
    dpg.add_text("", tag='vmachine_info_label',
                 color=(180, 255, 180))

    # ------------------------------------------------------------------
    # 4. Новый замер
    # ------------------------------------------------------------------
    dpg.add_separator()
    dpg.add_text("Новый замер", color=(180, 220, 255))
    dpg.add_text("Новая МСК")
    dpg.add_input_text(tag='vnew_msk_input', width=-1)
    dpg.add_text("Имя файла")
    dpg.add_input_text(tag='vnew_file_input', width=-1)
    dpg.add_text("Оператор")
    dpg.add_combo([], tag='vop_combo', width=-1)

    # ------------------------------------------------------------------
    # 5. Действия
    # ------------------------------------------------------------------
    dpg.add_separator()
    dpg.add_text("Действия", color=(180, 220, 255))

    dpg.add_button(label='Настройки "ворот"',
                   width=-1, height=28,
                   callback=lambda s, a: _open_settings_dialog())

    dpg.add_button(label="Генерация",
                   width=-1, height=36, tag='vgenerate_btn',
                   callback=lambda s, a: _on_generate())

    with dpg.group(horizontal=True):
        dpg.add_button(label="Сохранить в БД",
                       width=240, height=34,
                       callback=lambda s, a: _on_save())
        dpg.add_button(label="Предпросмотр",
                       width=180, height=34,
                       callback=lambda s, a: _on_show_preview())

    dpg.add_button(label="Печать протокола",
                   width=-1, height=34,
                   callback=lambda s, a: _on_print_protocol())

    dpg.add_button(label="Распечатка температур",
                   width=-1, height=34,
                   callback=lambda s, a: _on_print_temps())

    dpg.add_spacer(height=4)
    dpg.add_text("", tag=NEW_MID_LABEL, color=(180, 255, 180))


# ============================================================================
# Правая панель
# ============================================================================
def _build_right_panel():
    dpg.add_text("Статистика по параметру партии",
                 color=(180, 220, 255))
    dpg.add_separator()

    with dpg.group(horizontal=True):
        with dpg.group(width=180):
            dpg.add_text("Параметр")
            dpg.add_combo([], tag=PARAM_COMBO, width=180,
                          callback=lambda s, a: _refresh_stats())
        with dpg.group(width=200):
            dpg.add_text("Виртуальный Measure_ID")
            dpg.add_combo([], tag=VIRT_MID_COMBO, width=200,
                          callback=lambda s, a: _refresh_stats())
        with dpg.group(width=140):
            dpg.add_spacer(height=18)
            dpg.add_button(label="Обновить", width=140,
                           callback=_on_refresh_button)

    dpg.add_text("", tag=STATUS_LABEL, color=(200, 200, 120))
    dpg.add_separator()

    dpg.add_text("Распределение", color=(180, 220, 255))
    with dpg.plot(tag=PLOT_TAG, height=300, width=-1):
        dpg.add_plot_legend()
        dpg.add_plot_axis(dpg.mvXAxis, label="Значение")
        dpg.add_plot_axis(dpg.mvYAxis, label="Плотность",
                          tag=PLOT_Y_AXIS)

    dpg.add_separator()
    dpg.add_text("Метрики", color=(180, 220, 255))
    with dpg.table(tag=STATS_TABLE, header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True,
                   policy=dpg.mvTable_SizingFixedFit):
        dpg.add_table_column(label="Метрика")
        dpg.add_table_column(label="Базовый")
        dpg.add_table_column(label="Виртуальный")


def _on_refresh_button(sender=None, data=None):
    """Обновить и список виртуальных замеров, и статистику."""
    try:
        _log("_on_refresh_button: обновление")
        _refresh_virtual_mid_combo()
    except Exception as e:
        _log_exc("_on_refresh_button: virtual", e)
    _refresh_stats()


# ============================================================================
# Bootstrap
# ============================================================================
def _bootstrap():
    try:
        _log("bootstrap: старт")
        types = vd.get_rtypes()
        _log(f"bootstrap: типов резонаторов {len(types)}")
        _safe_set_combo('vtype_combo', types)
        if types:
            _on_type_changed()

        try:
            ops = pd.read_sql(
                "SELECT DISTINCT Name FROM пользователи "
                "WHERE Name IS NOT NULL ORDER BY Name", vd._engine())
            _safe_set_combo('vop_combo', ops['Name'].tolist())
        except Exception as e:
            _log_exc("bootstrap: операторы", e)

        params = ['F', 'R', 'C0', 'Cq', 'L', 'Q', 'FT', 'Mono',
                  'Fmaxm', 'Fptp', 'Slope', 'Rsp1', 'Rsp2', 'Rsp3',
                  'Fmax', 'Fmin', 'Rmax', 'Rmin', 'C0_C1', 'C1_2C0']
        _safe_set_combo(PARAM_COMBO, params, value='F')

        try:
            mtypes = vd.get_machine_types()
            _log(f"bootstrap: типов установок {len(mtypes)}")
            _safe_set_combo('vmachine_type_combo', mtypes)
            if mtypes:
                _on_machine_type_changed()
        except Exception as e:
            _log_exc("bootstrap: установки", e)

        _on_num_mode_changed()

        try:
            lu = vset.load_settings().get('last_used', {})
            mtype = lu.get('machine_type', '')
            msn   = lu.get('machine_sn', '')
            cur_types = dpg.get_item_configuration(
                'vmachine_type_combo').get('items', [])
            if mtype and mtype in cur_types:
                dpg.set_value('vmachine_type_combo', mtype)
                _on_machine_type_changed()
                cur_sns = dpg.get_item_configuration(
                    'vmachine_sn_combo').get('items', [])
                if msn and msn in cur_sns:
                    dpg.set_value('vmachine_sn_combo', msn)
                    _on_machine_sn_changed()
        except Exception as e:
            _log_exc("bootstrap: восстановление установки", e)

        _log("bootstrap: завершён")
    except Exception as e:
        _log_exc("bootstrap", e)


# ============================================================================
# Каскад
# ============================================================================
def _on_type_changed(sender=None, data=None):
    global _suppress_cascade
    if _suppress_cascade:
        return
    try:
        rtype = _get_combo_value('vtype_combo')
        _log(f"_on_type_changed: rtype='{rtype}'")
        spcs = vd.get_spcs(rtype) if rtype else []
        _log(f"_on_type_changed: спецификаций {len(spcs)}")

        _suppress_cascade = True
        try:
            _safe_set_combo('vspc_combo', spcs)
        finally:
            _suppress_cascade = False

        _on_spc_changed()
    except Exception as e:
        _log_exc("_on_type_changed", e)


def _on_spc_changed(sender=None, data=None):
    global _suppress_cascade
    if _suppress_cascade:
        return
    try:
        spc = _get_combo_value('vspc_combo')
        _log(f"_on_spc_changed: spc='{spc}'")

        if not spc:
            _suppress_cascade = True
            try:
                _safe_set_combo('vmsk_combo', [])
                _safe_set_combo('vbase_mid_combo', [])
                _state['all_msks'] = []
                if dpg.does_item_exist('vmsk_count_label'):
                    dpg.set_value('vmsk_count_label', '')
            finally:
                _suppress_cascade = False
            try:
                _refresh_virtual_mid_combo()
            except Exception as e:
                _log_exc("_on_spc_changed: refresh virtual", e)
            return

        def worker():
            _log(f"worker[spec]: старт spc='{spc}'")
            _progress_update(20, 'Загрузка МСК...',
                             f'Спецификация: {spc}')
            msks = vd.get_msks(spc)
            _log(f"worker[spec]: get_msks -> {len(msks)}")

            msk = msks[0] if msks else ''
            mids = []
            if msk:
                _progress_update(60, 'Загрузка Measure_ID...',
                                 f'МСК: {msk}   всего МСК: {len(msks)}')
                mids = vd.get_measure_ids(msk)
                _log(f"worker[spec]: get_measure_ids -> {len(mids)}")

            _progress_update(
                90, 'Подготовка списков...',
                f'МСК: {len(msks)}, замеров: {len(mids)}')
            return {'msks': msks, 'msk': msk, 'mids': mids}

        def on_done(result):
            global _suppress_cascade
            _log("_on_spc_changed: on_done start")
            msks = result.get('msks') or []
            msk  = result.get('msk') or ''
            mids = result.get('mids') or []

            _state['all_msks'] = msks

            _suppress_cascade = True
            try:
                preview = list(msks)
                _safe_set_combo('vmsk_combo', preview, value=msk)

                str_ids = [str(x) for x in mids]
                _safe_set_combo('vbase_mid_combo', str_ids)

                if dpg.does_item_exist('vmsk_count_label'):
                    dpg.set_value('vmsk_count_label',
                                  f"Всего МСК: {len(msks)}")
            finally:
                _suppress_cascade = False

            _log("_on_spc_changed: on_done -> виртуальные")
            try:
                _refresh_virtual_mid_combo()
            except Exception as e:
                _log_exc("_on_spc_changed: refresh virtual", e)

            _log("_on_spc_changed: on_done -> base_mid_changed")
            _on_base_mid_changed()
            _log("_on_spc_changed: on_done завершён")

        def on_error(err):
            global _suppress_cascade
            _log(f"_on_spc_changed: on_error: {err}")
            _suppress_cascade = True
            try:
                _safe_set_combo('vmsk_combo', [])
                _safe_set_combo('vbase_mid_combo', [])
                _state['all_msks'] = []
            finally:
                _suppress_cascade = False
            dpg.set_value(STATUS_LABEL, f'Ошибка загрузки МСК: {err}')

        _run_with_progress(
            worker, on_done=on_done, on_error=on_error,
            start_msg='Загрузка МСК по спецификации...',
            title='Загрузка спецификации')

    except Exception as e:
        _log_exc("_on_spc_changed", e)


def _on_msk_search_changed(sender=None, data=None):
    """Фильтр МСК по подстроке в текущем списке. Не запускает загрузку."""
    try:
        all_msks = _state.get('all_msks') or []
        search = dpg.get_value('vmsk_search_input') or ''
        if search:
            s = search.lower()
            preview = [m for m in all_msks if s in str(m).lower()]
        else:
            preview = list(all_msks)

        current = _get_combo_value('vmsk_combo')
        new_value = current if current in preview else ''

        _safe_set_combo('vmsk_combo', preview, value=new_value)

        if dpg.does_item_exist('vmsk_count_label'):
            if search:
                dpg.set_value('vmsk_count_label',
                              f"Найдено МСК по '{search}': "
                              f"{len(preview)}")
            else:
                dpg.set_value('vmsk_count_label',
                              f"Всего МСК: {len(all_msks)}")
    except Exception as e:
        _log_exc("_on_msk_search_changed", e)


def _on_msk_manual_enter(sender=None, data=None):
    """
    Прямой выбор МСК по Enter.

    Загружает каскад по введённой МСК:
      1. Находит спецификацию, тип резонатора и номера (vd.load_by_msk).
      2. Обновляет combo тип → спецификация → МСК.
      3. Запускает стандартный _on_msk_changed, который загрузит
         Measure_ID с окном прогресса "Загрузка МСК".
      4. Обновляет список виртуальных замеров для статистики.
    """
    global _suppress_cascade
    if _suppress_cascade:
        return
    if not dpg.does_item_exist('vmsk_manual_input'):
        return
    msk = (dpg.get_value('vmsk_manual_input') or '').strip()
    if not msk:
        return

    _log(f"_on_msk_manual_enter: msk='{msk}'")

    info = vd.load_by_msk(msk)
    if info is None:
        dpg.set_value(STATUS_LABEL,
                      f"МСК '{msk}' не найдена в БД")
        return

    _suppress_cascade = True
    try:
        # ---- 1. Тип резонатора ----
        if info['rtype']:
            cur_types = dpg.get_item_configuration(
                'vtype_combo').get('items', [])
            if info['rtype'] in cur_types:
                dpg.set_value('vtype_combo', info['rtype'])
                try:
                    spcs = vd.get_spcs(info['rtype'])
                    _safe_set_combo('vspc_combo', spcs)
                except Exception as e:
                    _log_exc("manual msk: get_spcs", e)

        # ---- 2. Спецификация ----
        if info['spc']:
            cur_specs = dpg.get_item_configuration(
                'vspc_combo').get('items', [])
            if info['spc'] in cur_specs:
                dpg.set_value('vspc_combo', info['spc'])
            else:
                new_specs = [info['spc']] + list(cur_specs)
                _safe_set_combo('vspc_combo', new_specs,
                                value=info['spc'])

        # ---- 3. МСК ----
        try:
            msks = vd.get_msks(info['spc']) if info['spc'] else []
            if msk not in msks:
                msks = [msk] + list(msks)
            _state['all_msks'] = msks
            _safe_set_combo('vmsk_combo', msks, value=msk)
            if dpg.does_item_exist('vmsk_count_label'):
                dpg.set_value('vmsk_count_label',
                              f"Всего МСК: {len(msks)}")
        except Exception as e:
            _log_exc("manual msk: get_msks", e)
    finally:
        _suppress_cascade = False

    # ---- 4. Загрузка Measure_ID (штатный путь с прогрессом) ----
    _log("_on_msk_manual_enter: каскад обновлён — "
         "загрузка Measure_ID")
    try:
        _on_msk_changed()
    except Exception as e:
        _log_exc("manual msk: _on_msk_changed", e)

    # ---- 5. Обновление списка виртуальных замеров ----
    try:
        _refresh_virtual_mid_combo()
    except Exception as e:
        _log_exc("manual msk: refresh virtual", e)


def _on_msk_changed(sender=None, data=None):
    global _suppress_cascade
    if _suppress_cascade:
        return
    try:
        msk = _get_combo_value('vmsk_combo')
        _log(f"_on_msk_changed: msk='{msk}'")

        if not msk:
            _suppress_cascade = True
            try:
                _safe_set_combo('vbase_mid_combo', [])
            finally:
                _suppress_cascade = False
            return

        def worker():
            _progress_update(30, 'Загрузка Measure_ID...',
                             f'МСК: {msk}')
            mids = vd.get_measure_ids(msk)
            _progress_update(90, 'Подготовка списка...',
                             f'Замеров: {len(mids)}')
            return {'mids': mids}

        def on_done(result):
            global _suppress_cascade
            str_ids = [str(x) for x in result['mids']]
            _suppress_cascade = True
            try:
                _safe_set_combo('vbase_mid_combo', str_ids)
            finally:
                _suppress_cascade = False
            _on_base_mid_changed()

        def on_error(err):
            global _suppress_cascade
            _suppress_cascade = True
            try:
                _safe_set_combo('vbase_mid_combo', [])
            finally:
                _suppress_cascade = False
            dpg.set_value(STATUS_LABEL,
                          f'Ошибка загрузки замеров: {err}')

        _run_with_progress(
            worker, on_done=on_done, on_error=on_error,
            start_msg='Загрузка Measure_ID...',
            title='Загрузка МСК')

    except Exception as e:
        _log_exc("_on_msk_changed", e)


def _on_base_mid_manual(sender=None, data=None):
    """Ручной ввод Measure_ID."""
    try:
        if not dpg.does_item_exist('vbase_mid_input'):
            return
        text = (dpg.get_value('vbase_mid_input') or '').strip()
        if not text:
            return
        try:
            mid = int(text)
        except ValueError:
            dpg.set_value(STATUS_LABEL,
                          f"Некорректный Measure_ID: {text}")
            return

        _log(f"_on_base_mid_manual: mid={mid}")

        global _suppress_cascade
        cur = dpg.get_item_configuration('vbase_mid_combo').get(
            'items', [])
        _suppress_cascade = True
        try:
            if str(mid) in cur:
                dpg.set_value('vbase_mid_combo', str(mid))
            else:
                _safe_set_combo('vbase_mid_combo',
                                [str(mid)] + list(cur),
                                value=str(mid))
        finally:
            _suppress_cascade = False

        if dpg.does_item_exist('vnew_file_input'):
            dpg.set_value('vnew_file_input', f"VIRT_{mid}")

        _on_base_mid_changed()
    except Exception as e:
        _log_exc("_on_base_mid_manual", e)


def _on_base_mid_changed(sender=None, data=None):
    """
    Вызывается при смене базового Measure_ID.

    Загружает базовый замер, обновляет «новую МСК» по MSK из самого
    замера (а не по текущему значению vmsk_combo — оно может быть
    неактуальным после поиска по номерам), а также выставляет
    тип/серийник установки.
    """
    try:
        mid = _get_combo_value('vbase_mid_combo')
        _log(f"_on_base_mid_changed: mid='{mid}'")

        base_df = None
        if mid:
            try:
                base_df = vd.load_base_psidata(int(mid))
            except Exception as e:
                _log_exc("_on_base_mid_changed: load base", e)

        # MSK для новой МСК — из самого замера, если загрузился
        actual_msk = _get_combo_value('vmsk_combo')
        if base_df is not None and not base_df.empty:
            base_msk = vd._safe_str(base_df.iloc[0].get('MSK'))
            if base_msk:
                actual_msk = base_msk

        if actual_msk and dpg.does_item_exist('vnew_msk_input'):
            suggested = (actual_msk
                         if actual_msk.endswith('_VIRT')
                         else f"{actual_msk}_VIRT")
            dpg.set_value('vnew_msk_input', suggested)
        if mid and dpg.does_item_exist('vnew_file_input'):
            dpg.set_value('vnew_file_input', f"VIRT_{mid}")

        if not mid or base_df is None or base_df.empty:
            return

        try:
            mtype = vd._safe_str(base_df.iloc[0].get('MachineType'))
            msn   = vd._safe_str(base_df.iloc[0].get('Machine_Serial'))
            _log(f"_on_base_mid_changed: установка {mtype}/{msn}")
            if not mtype:
                return
            cur_types = dpg.get_item_configuration(
                'vmachine_type_combo').get('items', [])
            if mtype in cur_types:
                dpg.set_value('vmachine_type_combo', mtype)
                _on_machine_type_changed()
                cur_sns = dpg.get_item_configuration(
                    'vmachine_sn_combo').get('items', [])
                if msn and msn in cur_sns:
                    dpg.set_value('vmachine_sn_combo', msn)
                    _on_machine_sn_changed()
            else:
                _log(f"_on_base_mid_changed: тип '{mtype}' "
                     f"не в списке")
        except Exception as e:
            _log_exc("_on_base_mid_changed: machine", e)
    except Exception as e:
        _log_exc("_on_base_mid_changed", e)


# ============================================================================
# Установка
# ============================================================================
def _on_machine_type_changed(sender=None, data=None):
    global _suppress_cascade
    if _suppress_cascade:
        return
    try:
        type_name = _get_combo_value('vmachine_type_combo')
        _log(f"_on_machine_type_changed: '{type_name}'")
        df = vd.get_machines_for_type(type_name)
        if df.empty:
            _suppress_cascade = True
            _safe_set_combo('vmachine_sn_combo', [])
            _suppress_cascade = False
            _state['machine_info'] = None
            if dpg.does_item_exist('vmachine_info_label'):
                dpg.set_value('vmachine_info_label', '')
            return

        items = [str(x) for x in df['Serial_N'].dropna().tolist()]
        _suppress_cascade = True
        _safe_set_combo('vmachine_sn_combo', items)
    except Exception as e:
        _log_exc("_on_machine_type_changed", e)
    finally:
        _suppress_cascade = False
    _on_machine_sn_changed()


def _on_machine_sn_changed(sender=None, data=None):
    if _suppress_cascade:
        return
    try:
        type_name = _get_combo_value('vmachine_type_combo')
        sn = _get_combo_value('vmachine_sn_combo')
        if not type_name or not sn:
            _state['machine_info'] = None
            if dpg.does_item_exist('vmachine_info_label'):
                dpg.set_value('vmachine_info_label', '')
            return

        df = vd.get_machines_for_type(type_name)
        if df.empty:
            _state['machine_info'] = None
            return

        mask = df['Serial_N'].astype(str).str.strip() == str(sn).strip()
        subset = df[mask]
        if subset.empty:
            _state['machine_info'] = None
            if dpg.does_item_exist('vmachine_info_label'):
                dpg.set_value('vmachine_info_label', '')
            return

        info = vd.build_machine_info(subset.iloc[0])
        _state['machine_info'] = info

        if dpg.does_item_exist('vmachine_info_label'):
            poverka = info.get('Machine_Call_Date') or '—'
            dpg.set_value(
                'vmachine_info_label',
                f"Поверка: {poverka}   "
                f"({'Да' if info.get('PoverKa') else 'Нет'})")
    except Exception as e:
        _log_exc("_on_machine_sn_changed", e)


# ============================================================================
# Номера
# ============================================================================
def _on_num_mode_changed(sender=None, data=None):
    try:
        mode = dpg.get_value('vnum_mode')
        _state['mode'] = mode

        if dpg.does_item_exist('vnum_interval_group'):
            dpg.configure_item('vnum_interval_group',
                               show=(mode == 'По интервалу'))
        if dpg.does_item_exist('vnum_list_group'):
            dpg.configure_item('vnum_list_group',
                               show=(mode == 'Списком'))
        if mode == 'Списком':
            _refresh_numbers_list_label()
    except Exception as e:
        _log_exc("_on_num_mode_changed", e)


def _refresh_numbers_list_label():
    try:
        n = len(_state.get('numbers') or [])
        if dpg.does_item_exist('vnum_selected_label'):
            dpg.set_value('vnum_selected_label',
                          "Не выбрано" if n == 0
                          else f"Выбрано номеров: {n}")
    except Exception as e:
        _log_exc("_refresh_numbers_list_label", e)


def _show_numbers_dialog():
    try:
        mid_str = _get_combo_value('vbase_mid_combo')
        if not mid_str:
            dpg.set_value(NEW_MID_LABEL,
                          "Не выбран базовый Measure_ID")
            return
        try:
            mid = int(mid_str)
        except ValueError:
            return

        all_numbers = vd.get_all_numbers(mid)
        if not all_numbers:
            dpg.set_value(NEW_MID_LABEL,
                          "Нет номеров в базовом замере")
            return

        if dpg.does_item_exist(NUMBERS_TAG):
            dpg.delete_item(NUMBERS_TAG)

        sw, sh = _layout.screen_size()
        w = max(400, min(600, int(sw * 0.35)))
        h = max(400, min(700, int(sh * 0.60)))
        x = (sw - w) // 2
        y = (sh - h) // 2
        selected_set = set(_state.get('numbers') or [])

        with dpg.window(label="Выбор номеров", tag=NUMBERS_TAG,
                        modal=True, width=w, height=h, pos=(x, y),
                        no_collapse=True):
            dpg.add_text(f"Всего номеров: {len(all_numbers)}",
                         color=(180, 220, 255))
            with dpg.group(horizontal=True):
                dpg.add_button(label="Выбрать все",
                               callback=lambda: _select_all_numbers(
                                   all_numbers, True))
                dpg.add_button(label="Снять все",
                               callback=lambda: _select_all_numbers(
                                   all_numbers, False))
            dpg.add_separator()
            with dpg.child_window(width=-1, height=-60, border=True):
                for n in all_numbers:
                    dpg.add_checkbox(label=n, tag=f"vnum_chk_{n}",
                                     default_value=(n in selected_set))
            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Применить", width=140, height=28,
                    callback=lambda: _apply_numbers_selection(
                        all_numbers))
                dpg.add_button(
                    label="Отмена", width=140, height=28,
                    callback=lambda: dpg.delete_item(NUMBERS_TAG))
    except Exception as e:
        _log_exc("_show_numbers_dialog", e)


def _select_all_numbers(all_numbers, value):
    try:
        for n in all_numbers:
            tag = f"vnum_chk_{n}"
            if dpg.does_item_exist(tag):
                dpg.set_value(tag, value)
    except Exception as e:
        _log_exc("_select_all_numbers", e)


def _apply_numbers_selection(all_numbers):
    try:
        selected = []
        for n in all_numbers:
            tag = f"vnum_chk_{n}"
            if dpg.does_item_exist(tag) and dpg.get_value(tag):
                selected.append(n)
        _state['numbers'] = selected
        _refresh_numbers_list_label()
        dpg.delete_item(NUMBERS_TAG)
    except Exception as e:
        _log_exc("_apply_numbers_selection", e)


def _get_selected_numbers():
    try:
        mode = dpg.get_value('vnum_mode')
        if mode == 'Все':
            return None
        if mode == 'По интервалу':
            text = dpg.get_value('vnum_interval_input') or ''
            return vd.parse_numbers_input(text)
        if mode == 'Списком':
            return _state.get('numbers') or None
        return None
    except Exception as e:
        _log_exc("_get_selected_numbers", e)
        return None


# ============================================================================
# Поиск базового замера по частичному МСК (как в модуле Архив:
# результаты складываются в combo, без всплывающих диалогов)
# ============================================================================
def _on_msk_db_search(sender=None, data=None):
    """Глобальный поиск МСК по подстроке в БД. Результаты — в
    vmsk_combo + status text. Аналогично _display_msk_search_results
    в модуле Архив."""
    if not dpg.does_item_exist('vmsk_db_search_input'):
        return
    partial = (dpg.get_value('vmsk_db_search_input') or '').strip()
    if not partial:
        dpg.set_value(STATUS_LABEL, 'Введите часть номера МСК')
        return

    _log(f"_on_msk_db_search: partial='{partial}'")

    def worker():
        _progress_update(20, 'Поиск МСК в БД...',
                         f'Подстрока: {partial}')
        df = vd.search_msks_partial(partial)
        _progress_update(95, f'Найдено МСК: {len(df)}', '')
        return df

    def on_done(df):
        if df is None or df.empty:
            dpg.set_value(
                STATUS_LABEL,
                f'По подстроке "{partial}" МСК не найдены')
            return

        msks = df['MSK'].astype(str).tolist()
        _state['all_msks'] = msks

        global _suppress_cascade
        _suppress_cascade = True
        try:
            _safe_set_combo('vmsk_combo', msks, value=msks[0])
            if dpg.does_item_exist('vmsk_count_label'):
                dpg.set_value('vmsk_count_label',
                              f"Всего МСК: {len(msks)}")
            # очищаем локальный фильтр — иначе новый список будет
            # сразу отфильтрован старым значением
            if dpg.does_item_exist('vmsk_search_input'):
                dpg.set_value('vmsk_search_input', '')
        finally:
            _suppress_cascade = False

        dpg.set_value(
            STATUS_LABEL,
            f'Поиск МСК по "{partial}": найдено {len(msks)}. '
            f'Выберите МСК из списка.')

        # Загружаем Measure_ID для первой найденной МСК — как
        # on_msk_changed() в Архиве
        _on_msk_changed()

    def on_error(err):
        dpg.set_value(STATUS_LABEL, f'Ошибка поиска МСК: {err}')

    _run_with_progress(
        worker, on_done=on_done, on_error=on_error,
        start_msg=f'Поиск МСК по "{partial}"...',
        title='Поиск МСК')


# ============================================================================
# Поиск базового замера по номерам резонаторов (как в модуле Архив:
# результаты складываются в combo, без всплывающих диалогов)
# ============================================================================
def _on_resonator_search(sender=None, data=None):
    """Глобальный поиск Measure_ID по номерам резонаторов.
    Результаты — в vbase_mid_combo + status text."""
    if not dpg.does_item_exist('vresonator_search_input'):
        return
    text_input = (dpg.get_value('vresonator_search_input') or '').strip()
    if not text_input:
        dpg.set_value(STATUS_LABEL, 'Введите номера резонаторов')
        return

    numbers = vd.parse_numbers_input(text_input)
    if not numbers:
        dpg.set_value(STATUS_LABEL,
                      'Не удалось распознать номера резонаторов')
        return

    only_good = bool(dpg.get_value('vonly_good_check'))
    _log(f"_on_resonator_search: numbers={len(numbers)}, "
         f"only_good={only_good}")

    def worker():
        _progress_update(15, 'Поиск замеров по номерам...',
                         f'Номеров в запросе: {len(numbers)}')
        mids = vd.search_measure_ids_by_numbers(
            numbers, only_good=only_good)
        if not mids:
            return pd.DataFrame()

        _progress_update(
            60, f'Найдено замеров: {len(mids)}',
            'Загрузка информации по замерам...')
        df = vd.load_measure_ids_info(mids)

        _progress_update(95, 'Готово', f'Найдено: {len(df)}')
        return df

    def on_done(df):
        if df is None or df.empty:
            preview = ', '.join(numbers[:3])
            if len(numbers) > 3:
                preview += '...'
            dpg.set_value(
                STATUS_LABEL,
                f'Замеры с номерами {preview} не найдены')
            return

        str_ids = [str(x) for x in df['Measure_ID'].tolist()]
        n_msk = (int(df['MSK'].nunique())
                 if 'MSK' in df.columns else 0)

        global _suppress_cascade
        _suppress_cascade = True
        try:
            _safe_set_combo('vbase_mid_combo', str_ids,
                            value=str_ids[0])
        finally:
            _suppress_cascade = False

        dpg.set_value(
            STATUS_LABEL,
            f'Поиск по {len(numbers)} номерам: замеров {len(str_ids)}, '
            f'МСК {n_msk}. Выберите Measure_ID из списка.')

        # Первый замер — подгружаем сразу (установка, MSK, новая МСК)
        _on_base_mid_changed()

    def on_error(err):
        dpg.set_value(STATUS_LABEL,
                      f'Ошибка поиска по номерам: {err}')

    _run_with_progress(
        worker, on_done=on_done, on_error=on_error,
        start_msg='Поиск по номерам резонаторов...',
        title='Поиск по номерам')


# ============================================================================
# Настройки
# ============================================================================
def _open_settings_dialog():
    try:
        if dpg.does_item_exist(SETTINGS_TAG):
            dpg.delete_item(SETTINGS_TAG)

        s = vset.load_settings()
        var = s.get('variance', {})
        nn = s.get('nn', {})

        rtype = (dpg.get_value('vtype_combo')
                 if dpg.does_item_exist('vtype_combo') else None)
        spc_name = (dpg.get_value('vspc_combo')
                    if dpg.does_item_exist('vspc_combo') else None)

        try:
            from . import Virtual_NN
            mlp_info = Virtual_NN.get_mlp_info(rtype)
            ae_info = Virtual_NN.get_autoenc_info(rtype, spc=spc_name)
            models_path = Virtual_NN.models_dir()
        except Exception:
            mlp_info = None
            ae_info = None
            models_path = "(Virtual_NN недоступен)"

        def _src_label(info):
            if not info:
                return "нет"
            src = info.get('source', '?')
            if src == 'db_spc':
                return f"БД (spec='{info.get('spc')}')"
            if src == 'file_spc':
                return f"файл (spec='{info.get('spc')}')"
            if src == 'db_rtype':
                return f"БД (rtype='{info.get('rtype')}')"
            if src == 'file_rtype':
                return f"файл (rtype='{info.get('rtype')}')"
            if src == 'db_global':
                return "БД (глоб.)"
            if src == 'file_global':
                return "файл (глоб.)"
            return src

        sw, sh = _layout.screen_size()
        with dpg.window(label="Настройки виртуального замера",
                        tag=SETTINGS_TAG, modal=True,
                        width=480, height=620,
                        pos=((sw - 480) // 2, (sh - 620) // 2)):
            dpg.add_input_float(
                label="Макс. отклонение, %", tag='vset_pct',
                width=200,
                default_value=float(
                    var.get('max_delta_percent', 0.5)))
            dpg.add_input_float(
                label="Макс. абс. отклонение", tag='vset_abs',
                width=200,
                default_value=float(
                    var.get('max_delta_absolute', 0.05)))
            dpg.add_checkbox(
                label="Использовать абсолютное отклонение",
                tag='vset_use_abs',
                default_value=bool(var.get('use_absolute', False)))
            dpg.add_checkbox(
                label="Сохранять статус", tag='vset_preserve',
                default_value=bool(var.get('preserve_status', True)))
            dpg.add_input_int(
                label="Попыток подбора", tag='vset_attempts',
                width=120,
                default_value=int(var.get('max_attempts', 64)))

            dpg.add_separator()
            dpg.add_text("Нейросетевые модели", color=(180, 220, 255))
            dpg.add_text(
                f"MLP: {_src_label(mlp_info)}  |  "
                f"Autoencoder: {_src_label(ae_info)}",
                color=(180, 255, 180)
                      if (mlp_info or ae_info) else (200, 180, 120))
            dpg.add_text(f"Файлы: {models_path}",
                         color=(150, 150, 150), wrap=460)
            dpg.add_text(
                "Приоритет: БД → файл. Обучение — "
                "python -m Virtual_Measure.train_models",
                color=(140, 140, 140), wrap=460)

            dpg.add_checkbox(
                label="MLP: подбор значения (Stage 1)",
                tag='vset_nn_mlp',
                default_value=bool(nn.get('mlp_enabled', False)))
            dpg.add_checkbox(
                label="Autoencoder: проверка реалистичности (Stage 2)",
                tag='vset_nn_autoenc',
                default_value=bool(nn.get('autoenc_enabled', True)))
            dpg.add_input_float(
                label="Порог AE (0..1)", tag='vset_nn_ae_thr',
                width=200,
                default_value=float(nn.get('autoenc_threshold', 0.27)))
            dpg.add_checkbox(
                label="Блокировать сохранение при аномалии AE",
                tag='vset_nn_ae_block',
                default_value=bool(nn.get('autoenc_block', False)))

            with dpg.group(horizontal=True):
                dpg.add_button(
                    label="Перезагрузить модели", width=200,
                    callback=_reload_nn_models)

            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_button(label="Сохранить", width=140,
                               callback=_save_settings_dialog)
                dpg.add_button(label="Отмена", width=140,
                               callback=lambda: dpg.delete_item(
                                   SETTINGS_TAG))
    except Exception as e:
        _log_exc("_open_settings_dialog", e)


def _save_settings_dialog():
    try:
        s = vset.load_settings()
        var = s.setdefault('variance', {})
        var['max_delta_percent']  = float(dpg.get_value('vset_pct'))
        var['max_delta_absolute'] = float(dpg.get_value('vset_abs'))
        var['use_absolute']       = bool(dpg.get_value('vset_use_abs'))
        var['preserve_status']    = bool(dpg.get_value('vset_preserve'))
        var['max_attempts']       = int(dpg.get_value('vset_attempts'))
        nn = s.setdefault('nn', {})
        if dpg.does_item_exist('vset_nn_mlp'):
            nn['mlp_enabled'] = bool(dpg.get_value('vset_nn_mlp'))
        if dpg.does_item_exist('vset_nn_autoenc'):
            nn['autoenc_enabled'] = bool(dpg.get_value('vset_nn_autoenc'))
        if dpg.does_item_exist('vset_nn_ae_thr'):
            nn['autoenc_threshold'] = float(
                dpg.get_value('vset_nn_ae_thr'))
        if dpg.does_item_exist('vset_nn_ae_block'):
            nn['autoenc_block'] = bool(
                dpg.get_value('vset_nn_ae_block'))
        vset.save_settings(s)
        dpg.delete_item(SETTINGS_TAG)
    except Exception as e:
        _log_exc("_save_settings_dialog", e)


def _reload_nn_models(sender=None, data=None):
    try:
        from . import Virtual_NN
        Virtual_NN.reload_models()
        mlp_av = Virtual_NN.is_mlp_available()
        ae_av  = Virtual_NN.is_autoenc_available()
        dpg.set_value(
            STATUS_LABEL,
            f"Модели перезагружены. MLP: "
            f"{'OK' if mlp_av else 'нет'}, AE: "
            f"{'OK' if ae_av else 'нет'}")
        _log("NN models reloaded")
    except Exception as e:
        _log_exc("_reload_nn_models", e)


# ============================================================================
# Генерация
# ============================================================================
def _on_generate():
    try:
        base_mid_str = _get_combo_value('vbase_mid_combo')
        new_msk      = (dpg.get_value('vnew_msk_input') or '').strip()
        new_file     = (dpg.get_value('vnew_file_input') or '').strip()
        operator     = (dpg.get_value('vop_combo') or '').strip() or None
        only_good    = bool(dpg.get_value('vonly_good_check'))

        if not base_mid_str:
            dpg.set_value(NEW_MID_LABEL, "Не выбран базовый Measure_ID")
            return
        if not new_msk:
            dpg.set_value(NEW_MID_LABEL, "Не задана новая МСК")
            return
        try:
            base_mid = int(base_mid_str)
        except ValueError:
            dpg.set_value(NEW_MID_LABEL, "Некорректный Measure_ID")
            return

        selected_numbers = _get_selected_numbers()
        machine_info = _state.get('machine_info')
        settings = vset.load_settings()

        def worker():
            def cb(percent, message):
                _progress_update(
                    10 + percent * 0.8, message,
                    f'Базовый Measure_ID: {base_mid}')

            preview = vd.generate_virtual_data(
                base_measure_id=base_mid,
                new_msk=new_msk,
                file_name=new_file or None,
                operator=operator,
                settings=settings,
                only_good=only_good,
                selected_numbers=selected_numbers,
                machine_info=machine_info,
                progress_cb=cb,
            )
            if not preview:
                raise RuntimeError(
                    'generate_virtual_data вернул None')
            _progress_update(95, 'Подготовка предпросмотра...', '')
            return preview

        def on_done(preview):
            _state['preview'] = preview
            _log(f"_on_generate: psidata={preview['n_psidata']}, "
                 f"temp={preview['n_psidatatemp']}")

            try:
                s = vset.load_settings()
                s.setdefault('last_used', {})
                s['last_used']['machine_type'] = _get_combo_value(
                    'vmachine_type_combo')
                s['last_used']['machine_sn'] = _get_combo_value(
                    'vmachine_sn_combo')
                s['last_used']['rtype'] = _get_combo_value('vtype_combo')
                s['last_used']['spc']   = _get_combo_value('vspc_combo')
                s['last_used']['msk']   = _get_combo_value('vmsk_combo')
                s['last_used']['measure_id'] = base_mid_str
                s['last_used']['only_good']  = only_good
                vset.save_settings(s)
            except Exception as e:
                _log_exc("_on_generate: last_used", e)

            dpg.set_value(
                NEW_MID_LABEL,
                f"Готово: {preview['n_psidata']} изделий, "
                f"{preview['n_psidatatemp']} темп-точек. "
                f"Можно сохранить или распечатать.")
            _show_preview_dialog(preview)

        def on_error(err):
            dpg.set_value(NEW_MID_LABEL, f"Ошибка генерации: {err}")

        dpg.set_value(NEW_MID_LABEL, "Генерация...")
        _run_with_progress(
            worker, on_done=on_done, on_error=on_error,
            start_msg='Генерация виртуального замера...',
            title='Генерация виртуального замера')

    except Exception as e:
        _log_exc("_on_generate", e)
        dpg.set_value(NEW_MID_LABEL, f"Ошибка: {e}")


# ============================================================================
# Предпросмотр
# ============================================================================
def _on_show_preview():
    preview = _state.get('preview')
    if not preview:
        dpg.set_value(NEW_MID_LABEL,
                      "Нет данных: сначала нажмите «Генерация»")
        return
    _show_preview_dialog(preview)

def _compute_preview_overall_ok(preview) -> list:
    """Единый источник правды для статусов в предпросмотре:
    тот же механизм, что в PDF (Archive_Data.build_archive_status_df)."""
    try:
        from Archive_View.Archive_Data import (
            build_archive_status_df, load_spc_map_for_archive,
        )
        rows = preview.get('psidata_rows') or []
        if not rows:
            return []
        spc_name = preview.get('spc_name') or ''
        spc_map = (load_spc_map_for_archive(spc_name)
                   if spc_name else pd.DataFrame())
        if spc_map.empty:
            return [True] * len(rows)
        raw_df = pd.DataFrame(rows)
        status_df = build_archive_status_df(raw_df, spc_map)
        return status_df['Status'].tolist()
    except Exception as e:
        _log_exc("_compute_preview_overall_ok", e)
        return [True] * len(preview.get('psidata_rows') or [])

def _show_preview_dialog(preview):
    try:
        if dpg.does_item_exist(PREVIEW_TAG):
            dpg.delete_item(PREVIEW_TAG)

        sw, sh = _layout.screen_size()
        w = max(900, min(1400, int(sw * 0.85)))
        h = max(600, min(900,  int(sh * 0.85)))
        x = (sw - w) // 2
        y = (sh - h) // 2

        # ============================================================
        # Единый расчёт статусов — тот же путь, что в PDF.
        # ============================================================
        from Archive_View.Archive_Data import (
            build_archive_status_df, load_spc_map_for_archive,
        )
        rows = preview.get('psidata_rows') or []
        raw_df = pd.DataFrame(rows) if rows else pd.DataFrame()
        spc_name = preview.get('spc_name') or ''
        spc_map = (load_spc_map_for_archive(spc_name)
                   if spc_name else pd.DataFrame())
        status_df = None
        if not spc_map.empty and not raw_df.empty:
            status_df = build_archive_status_df(raw_df, spc_map)
            overall_ok = status_df['Status'].tolist()
        else:
            overall_ok = [True] * len(raw_df)

        n_good = sum(1 for v in overall_ok if v)
        n_bad = len(overall_ok) - n_good

        # ============================================================
        # ДИАГНОСТИКА (в консоль)
        # ============================================================
        spc_params = (list(spc_map['Parameter'])
                      if not spc_map.empty else [])
        _log("=" * 70)
        _log(f"[PREVIEW] spc_name = {spc_name!r}")
        _log(f"[PREVIEW] psidata rows = {len(raw_df)}")
        _log(f"[PREVIEW] spc_map params ({len(spc_params)}): "
             f"{spc_params}")
        if status_df is not None:
            status_cols = [c for c in status_df.columns
                           if c.endswith('_status')]
            _log(f"[PREVIEW] status_df._status cols ({len(status_cols)}): "
                 f"{status_cols}")
        _log(f"[PREVIEW] overall: Good={n_good}, Bad={n_bad}")

        # --- Специально про R / Rsp / SPFR ---
        for check in ('R', 'Rmax', 'Rmin', 'Rmax-Rmin', 'RcRb',
                      'Rsp1', 'Rsp2', 'Rsp3',
                      'SPFR_1', 'SPFR_2', 'SPFR_3'):
            in_spc = check in spc_params
            in_ps = (status_df is not None
                     and f'{check}_status' in status_df.columns)
            if in_spc or in_ps:
                _log(f"[PREVIEW] {check}: "
                     f"in_spc_map={in_spc}, in_status_df={in_ps}")

        if status_df is not None and 'R_status' in status_df.columns:
            r_statuses = status_df['R_status'].tolist()
            n_bad_r = sum(1 for s in r_statuses if not s)
            _log(f"[PREVIEW] R: bad={n_bad_r}/{len(r_statuses)}")
            bad_r_idx = [i for i, s in enumerate(r_statuses) if not s]
            pr_r = next(
                (pp for pp in (preview.get('param_ranges') or [])
                 if pp['param'] == 'R' or pp['field'] == 'R'),
                None)
            if pr_r:
                _log(f"[PREVIEW] R range: "
                     f"min={pr_r['min']}, max={pr_r['max']}")
            for i in bad_r_idx[:5]:
                try:
                    v = raw_df.iloc[i].get('R')
                    rsp1 = raw_df.iloc[i].get('Rsp1')
                    spfr1 = raw_df.iloc[i].get('SPFR_1')
                    _log(f"[PREVIEW]   R bad row {i}: "
                         f"R={v!r}, Rsp1={rsp1!r}, SPFR_1={spfr1!r}")
                except Exception:
                    pass

        if n_bad > 0:
            bad_rows = [i for i, v in enumerate(overall_ok) if not v][:5]
            _log(f"[PREVIEW] first bad rows: {bad_rows}")
        _log("=" * 70)

        with dpg.window(label="Предпросмотр виртуального замера",
                        tag=PREVIEW_TAG,
                        width=w, height=h, pos=(x, y),
                        no_collapse=True):
            dpg.add_text(
                f"Спецификация: {spc_name or '(не задана)'}",
                color=(180, 220, 255))
            dpg.add_text(
                f"Базовый Measure_ID: {preview['base_mid']}  |  "
                f"Новая МСК: {preview['new_msk']}  |  "
                f"Изделий: {preview['n_psidata']}  |  "
                f"Темп-точек: {preview['n_psidatatemp']}",
                color=(180, 220, 255))

            if not spc_map.empty:
                color = (180, 255, 180) if n_bad == 0 else (255, 180, 180)
                dpg.add_text(
                    f"По спецификации: Годен {n_good}  |  Брак {n_bad}",
                    color=color)

            mi = preview.get('machine_info') or {}
            if mi:
                dpg.add_text(
                    f"Установка: {mi.get('MachineType', '')}  |  "
                    f"S/N: {mi.get('Machine_Serial', '')}  |  "
                    f"Поверка: {mi.get('Machine_Call_Date', '')}",
                    color=(200, 200, 120))
            dpg.add_separator()
            ae = preview.get('ae_validation') or {}
            if ae:
                color = ((255, 160, 160) if ae['anomaly_count'] > 0
                         else (180, 255, 180))
                dpg.add_text(
                    f"AE: средний score {ae['mean_score']:.3f}  |  "
                    f"макс {ae['max_score']:.3f}  |  "
                    f"аномалий {ae['anomaly_count']}/{ae['total']}  |  "
                    f"порог {ae.get('threshold', 0):.3f}",
                    color=color)

            with dpg.tab_bar():
                with dpg.tab(label="Данные"):
                    _build_preview_data_tab(
                        preview, spc_map=spc_map,
                        status_df=status_df, raw_df=raw_df)
                with dpg.tab(label="Статистика"):
                    _build_preview_stats_tab(preview)

            dpg.add_separator()
            dpg.add_button(label="Закрыть", width=140, height=30,
                           callback=lambda: dpg.delete_item(PREVIEW_TAG))
    except Exception as e:
        _log_exc("_show_preview_dialog", e)


def _show_preview_dialog_3(preview):
    try:
        if dpg.does_item_exist(PREVIEW_TAG):
            dpg.delete_item(PREVIEW_TAG)

        sw, sh = _layout.screen_size()
        w = max(900, min(1400, int(sw * 0.85)))
        h = max(600, min(900,  int(sh * 0.85)))
        x = (sw - w) // 2
        y = (sh - h) // 2

        # Счётчики — по эталону Archive (как в PDF)
        overall_ok = _compute_preview_overall_ok(preview)
        n_good = sum(1 for v in overall_ok if v)
        n_bad = len(overall_ok) - n_good

        with dpg.window(label="Предпросмотр виртуального замера",
                        tag=PREVIEW_TAG,
                        width=w, height=h, pos=(x, y),
                        no_collapse=True):
            # ▼ Спецификация в шапке
            dpg.add_text(
                f"Спецификация: {preview.get('spc_name') or '(не задана)'}",
                color=(180, 220, 255))
            dpg.add_text(
                f"Базовый Measure_ID: {preview['base_mid']}  |  "
                f"Новая МСК: {preview['new_msk']}  |  "
                f"Изделий: {preview['n_psidata']}  |  "
                f"Темп-точек: {preview['n_psidatatemp']}",
                color=(180, 220, 255))

            if preview.get('spec_per_row') or overall_ok:
                color = (180, 255, 180) if n_bad == 0 else (255, 180, 180)
                dpg.add_text(
                    f"По спецификации: Годен {n_good}  |  Брак {n_bad}",
                    color=color)

            mi = preview.get('machine_info') or {}
            if mi:
                dpg.add_text(
                    f"Установка: {mi.get('MachineType', '')}  |  "
                    f"S/N: {mi.get('Machine_Serial', '')}  |  "
                    f"Поверка: {mi.get('Machine_Call_Date', '')}",
                    color=(200, 200, 120))
            dpg.add_separator()
            ae = preview.get('ae_validation') or {}
            if ae:
                color = ((255, 160, 160) if ae['anomaly_count'] > 0
                         else (180, 255, 180))
                dpg.add_text(
                    f"AE: средний score {ae['mean_score']:.3f}  |  "
                    f"макс {ae['max_score']:.3f}  |  "
                    f"аномалий {ae['anomaly_count']}/{ae['total']}  |  "
                    f"порог {ae.get('threshold', 0):.3f}",
                    color=color)

            with dpg.tab_bar():
                with dpg.tab(label="Данные"):
                    _build_preview_data_tab(preview)
                with dpg.tab(label="Статистика"):
                    _build_preview_stats_tab(preview)

            dpg.add_separator()
            dpg.add_button(label="Закрыть", width=140, height=30,
                           callback=lambda: dpg.delete_item(PREVIEW_TAG))
    except Exception as e:
        _log_exc("_show_preview_dialog", e)

def _show_preview_dialog_1(preview):
    try:
        if dpg.does_item_exist(PREVIEW_TAG):
            dpg.delete_item(PREVIEW_TAG)

        sw, sh = _layout.screen_size()
        w = max(900, min(1400, int(sw * 0.85)))
        h = max(600, min(900,  int(sh * 0.85)))
        x = (sw - w) // 2
        y = (sh - h) // 2

        with dpg.window(label="Предпросмотр виртуального замера",
                        tag=PREVIEW_TAG,
                        width=w, height=h, pos=(x, y),
                        no_collapse=True):
            dpg.add_text(
                f"Базовый Measure_ID: {preview['base_mid']}  |  "
                f"Новая МСК: {preview['new_msk']}  |  "
                f"Изделий: {preview['n_psidata']}  |  "
                f"Темп-точек: {preview['n_psidatatemp']}",
                color=(180, 220, 255))
            spec_per_row = preview.get('spec_per_row') or []
            if spec_per_row:
                n_good = sum(1 for st in spec_per_row
                             if st and all(st.values()))
                n_bad = len(spec_per_row) - n_good
                color = (180, 255, 180) if n_bad == 0 else (255, 180, 180)
                dpg.add_text(
                    f"По спецификации: Годен {n_good}  |  Брак {n_bad}",
                    color=color)

            mi = preview.get('machine_info') or {}
            if mi:
                dpg.add_text(
                    f"Установка: {mi.get('MachineType', '')}  |  "
                    f"S/N: {mi.get('Machine_Serial', '')}  |  "
                    f"Поверка: {mi.get('Machine_Call_Date', '')}",
                    color=(200, 200, 120))
            dpg.add_separator()
            ae = preview.get('ae_validation') or {}
            if ae:
                color = ((255, 160, 160) if ae['anomaly_count'] > 0
                         else (180, 255, 180))
                dpg.add_text(
                    f"AE: средний score {ae['mean_score']:.3f}  |  "
                    f"макс {ae['max_score']:.3f}  |  "
                    f"аномалий {ae['anomaly_count']}/{ae['total']}  |  "
                    f"порог {ae.get('threshold', 0):.3f}",
                    color=color)

            with dpg.tab_bar():
                with dpg.tab(label="Данные"):
                    _build_preview_data_tab(preview)
                with dpg.tab(label="Статистика"):
                    _build_preview_stats_tab(preview)

            dpg.add_separator()
            dpg.add_button(label="Закрыть", width=140, height=30,
                           callback=lambda: dpg.delete_item(PREVIEW_TAG))
    except Exception as e:
        _log_exc("_show_preview_dialog", e)
def _build_preview_data_tab(preview, spc_map=None, status_df=None,
                             raw_df=None):
    """
    Таблица предпросмотра — как в модуле Архив.

    Колонки: Position(s), N + параметры спецификации (Order)
    + MachineType, Machine_Serial + AE score + Статус.

    Цвет:
      * параметр ВНЕ спеки (is_param_bad) → ярко-красный;
      * параметр в спеке, но строка брак → светло-красный (ROW_BAD);
      * AE-аномалия → ПЕРВАЯ КОЛОНКА (Positions/Numbers) оранжевая
        + тултип с топ-3 вкладами. Параметры AE-цветом НЕ красятся.
    """
    try:
        from Archive_View.Archive_Data import (
            build_archive_status_df, load_spc_map_for_archive,
            apply_rounding, rename_fields_to_parameters,
        )

        rows = preview.get('psidata_rows') or []
        if not rows:
            dpg.add_text("Нет данных")
            return

        if raw_df is None:
            raw_df = pd.DataFrame(rows)
        if spc_map is None:
            spc_name = preview.get('spc_name') or ''
            spc_map = (load_spc_map_for_archive(spc_name)
                       if spc_name else pd.DataFrame())
        if status_df is None and not spc_map.empty:
            status_df = build_archive_status_df(raw_df, spc_map)

        # --- Статусы по эталону (как в PDF) -------------------------
        if status_df is not None:
            overall_ok = status_df['Status'].tolist()
            param_status = {
                col[:-len('_status')]: status_df[col].tolist()
                for col in status_df.columns
                if col.endswith('_status') and col != 'Status'
            }
        else:
            overall_ok = [True] * len(raw_df)
            param_status = {}

        # --- Данные для отображения: rename + round ----------------
        display_df = rename_fields_to_parameters(raw_df)
        if not spc_map.empty:
            display_df = apply_rounding(display_df, spc_map)

        # --- Набор колонок — только spec-параметры -----------------
        cols = []
        shown = set()

        if 'Position' in display_df.columns:
            cols.append(('Position', 'Позиция'))
            shown.add('Position')
        elif 'Positions' in display_df.columns:
            cols.append(('Positions', 'Позиция'))
            shown.add('Positions')

        if 'N' in display_df.columns:
            cols.append(('N', 'N'))
            shown.add('N')
        elif 'Numbers' in display_df.columns:
            cols.append(('Numbers', 'N'))
            shown.add('Numbers')

        if not spc_map.empty:
            ordered = (spc_map.sort_values('Order')
                       if 'Order' in spc_map.columns else spc_map)
            for _, spc_item in ordered.iterrows():
                p = spc_item['Parameter']
                if p in display_df.columns and p not in shown:
                    label = (spc_item.get('Note_mini')
                             or spc_item.get('Note') or p)
                    cols.append((p, str(label)))
                    shown.add(p)
        else:
            for b in ('F', 'R', 'C0', 'Cq', 'Q', 'L'):
                if b in display_df.columns and b not in shown:
                    cols.append((b, b))
                    shown.add(b)

        for c in ('MachineType', 'Machine_Serial'):
            if c in display_df.columns and c not in shown:
                cols.append((c, c))
                shown.add(c)

        ae_per_row = preview.get('ae_per_row') or {}
        ae_summary = preview.get('ae_validation') or {}
        have_ae = bool(ae_per_row)
        if have_ae:
            cols.append(('__ae_score__', 'AE score'))
        cols.append(('__spec_status__', 'Статус'))

        first_col_key = cols[0][0] if cols else None

        # ============================================================
        # Диагностика C0/C1/C0_C1 (base → generated)
        # ============================================================
        try:
            base_df = vd.load_base_psidata(preview['base_mid'])
            if not base_df.empty:
                def _g(df, c):
                    if df is None:
                        return None
                    v = df.get(c)
                    try:
                        return float(v) if v is not None else None
                    except (TypeError, ValueError):
                        return None
                _log("[PREVIEW-TAB] C0/C1/C0_C1 check "
                     "(base → generated, first 3):")
                for i in range(min(3, len(raw_df))):
                    br = base_df.iloc[i] if i < len(base_df) else None
                    gr = raw_df.iloc[i]
                    b_c0 = _g(br, 'C0'); b_cq = _g(br, 'Cq'); b_c01 = _g(br, 'C0_C1')
                    g_c0 = _g(gr, 'C0'); g_cq = _g(gr, 'Cq'); g_c01 = _g(gr, 'C0_C1')
                    calc = (g_c0 / (g_cq * 1e-3)
                            if g_c0 and g_cq else None)
                    calc_str = f"{calc:.1f}" if calc is not None else "n/a"
                    _log(f"  [{i}] C0: {b_c0} → {g_c0}  |  "
                         f"Cq: {b_cq} → {g_cq}  |  "
                         f"C0_C1: {b_c01} → {g_c01} "
                         f"(calc={calc_str})")
        except Exception as e:
            _log_exc("_build_preview_data_tab: C0/C1 diagnostic", e)

        # --- Цвета -------------------------------------------------
        COLOR_ROW_ANOM    = (255, 200, 100)
        COLOR_CELL_BAD    = (255, 60, 60)
        COLOR_ROW_BAD     = (255, 200, 200)
        COLOR_STATUS_GOOD = (100, 220, 100)
        COLOR_STATUS_BAD  = (255, 90, 90)
        COLOR_OK          = (255, 255, 255)

        # --- Рендер ------------------------------------------------
        with dpg.child_window(width=-1, height=-1, border=False):
            with dpg.table(header_row=True, resizable=True,
                           borders_innerH=True, borders_outerH=True,
                           borders_innerV=True,
                           policy=dpg.mvTable_SizingFixedFit,
                           scrollX=True):
                for _, label in cols:
                    dpg.add_table_column(label=label)

                for i, (_, row) in enumerate(display_df.iterrows()):
                    row_ok = (overall_ok[i]
                              if i < len(overall_ok) else True)
                    ae_info = ae_per_row.get(i) or {}
                    is_row_anom = bool(ae_info.get('is_anom'))
                    per_feat = ae_info.get('per_feature') or {}

                    ae_top = []
                    if is_row_anom and per_feat:
                        ae_top = sorted(
                            ((p, info.get('contrib_frac', 0))
                             for p, info in per_feat.items()
                             if info.get('contrib_frac', 0) > 0.2),
                            key=lambda x: -x[1])[:3]

                    with dpg.table_row():
                        for c, _label in cols:
                            # ----- Статус -----
                            if c == '__spec_status__':
                                if spc_map.empty:
                                    dpg.add_text('-',
                                                 color=(140, 140, 140))
                                elif row_ok:
                                    dpg.add_text('Годен',
                                                 color=COLOR_STATUS_GOOD)
                                else:
                                    dpg.add_text('Брак',
                                                 color=COLOR_STATUS_BAD)
                                continue

                            # ----- AE score -----
                            if c == '__ae_score__':
                                if ae_info:
                                    sc = ae_info.get('score')
                                    thr = ae_info.get('threshold')
                                    if sc is not None:
                                        dpg.add_text(
                                            f"{sc:.3f}",
                                            color=(COLOR_CELL_BAD
                                                   if is_row_anom
                                                   else COLOR_OK))
                                    else:
                                        dpg.add_text("-")
                                else:
                                    dpg.add_text("-")
                                continue

                            v = row.get(c, '')
                            if isinstance(v, float):
                                if pd.isna(v):
                                    v = ''
                                else:
                                    v = f"{v:.6g}"

                            # ▼ AE-аномалия: подсветка только
                            #   ПЕРВОЙ колонки (Positions/Numbers)
                            if c == first_col_key and is_row_anom:
                                txt = dpg.add_text(
                                    str(v), color=COLOR_ROW_ANOM)
                                if ae_top:
                                    with dpg.tooltip(txt):
                                        dpg.add_text(
                                            "AE: отклонение от типичного\n"
                                            f"score={ae_info.get('score', 0):.3f}  "
                                            f"thr={ae_info.get('threshold', 0):.3f}\n"
                                            + "\n".join(
                                                f"{p}: "
                                                f"{frac*100:.0f}%"
                                                for p, frac in ae_top))
                                continue

                            # ▼ Спек-статус параметра
                            p_status = param_status.get(c)
                            in_spec = p_status is not None
                            is_param_bad = (
                                in_spec and not row_ok
                                and i < len(p_status)
                                and not bool(p_status[i])
                            )

                            if is_param_bad:
                                txt = dpg.add_text(
                                    str(v), color=COLOR_CELL_BAD)
                                pr = next(
                                    (pp for pp in (preview.get(
                                        'param_ranges') or [])
                                     if pp['param'] == c
                                     or pp['field'] == c),
                                    None)
                                if pr:
                                    with dpg.tooltip(txt):
                                        dpg.add_text(
                                            f"Вне нормы\n"
                                            f"Min: "
                                            f"{pr['min'] if pr['min'] is not None else '—'}\n"
                                            f"Max: "
                                            f"{pr['max'] if pr['max'] is not None else '—'}")
                            elif in_spec and not row_ok:
                                # параметр в спеке, сам OK, но строка
                                # брак → светло-красный (как в Архиве)
                                dpg.add_text(str(v),
                                             color=COLOR_ROW_BAD)
                            else:
                                dpg.add_text(str(v))

            if len(display_df) > 200:
                dpg.add_text(
                    f"... показаны первые 200 из {len(display_df)}",
                    color=(150, 150, 150))

            if have_ae and ae_summary:
                dpg.add_spacer(height=4)
                dpg.add_text(
                    f"AE: mean={ae_summary.get('mean_score', 0):.3f} | "
                    f"max={ae_summary.get('max_score', 0):.3f} | "
                    f"аномалий {ae_summary.get('anomaly_count', 0)}/"
                    f"{ae_summary.get('total', 0)} | "
                    f"порог {ae_summary.get('threshold', 0):.3f}",
                    color=(180, 220, 180))
    except Exception as e:
        _log_exc("_build_preview_data_tab", e)

def _build_preview_data_tab_3(preview, spc_map=None, status_df=None,
                             raw_df=None):
    """
    Таблица предпросмотра — как в модуле Архив.

    Колонки: Position, N + параметры спецификации (в порядке Order)
    + MachineType, Machine_Serial + AE score + Статус.

    Базовые F/R/C0/Cq/Q/L добавляются ТОЛЬКО если они есть в spc_map
    (т.е. когда эта спецификация их реально проверяет). Иначе R не
    отображается — и ложной подсветки R быть не может.
    """
    try:
        from Archive_View.Archive_Data import (
            build_archive_status_df, load_spc_map_for_archive,
            apply_rounding, rename_fields_to_parameters,
        )

        rows = preview.get('psidata_rows') or []
        if not rows:
            dpg.add_text("Нет данных")
            return

        # --- Вход: либо передано, либо считаем сами ------------------
        if raw_df is None:
            raw_df = pd.DataFrame(rows)
        if spc_map is None:
            spc_name = preview.get('spc_name') or ''
            spc_map = (load_spc_map_for_archive(spc_name)
                       if spc_name else pd.DataFrame())
        if status_df is None and not spc_map.empty:
            status_df = build_archive_status_df(raw_df, spc_map)

        # --- Статусы -------------------------------------------------
        if status_df is not None:
            overall_ok = status_df['Status'].tolist()
            param_status = {
                col[:-len('_status')]: status_df[col].tolist()
                for col in status_df.columns
                if col.endswith('_status') and col != 'Status'
            }
        else:
            overall_ok = [True] * len(raw_df)
            param_status = {}

        # --- Данные для отображения (rename + round) -----------------
        display_df = rename_fields_to_parameters(raw_df)
        if not spc_map.empty:
            display_df = apply_rounding(display_df, spc_map)

        # --- Набор колонок — как в Архиве ---------------------------
        cols = []
        shown = set()

        if 'Position' in display_df.columns:
            cols.append(('Position', 'Позиция'))
            shown.add('Position')
        elif 'Positions' in display_df.columns:
            cols.append(('Positions', 'Позиция'))
            shown.add('Positions')

        if 'N' in display_df.columns:
            cols.append(('N', 'N'))
            shown.add('N')
        elif 'Numbers' in display_df.columns:
            cols.append(('Numbers', 'N'))
            shown.add('Numbers')

        # ▼ ТОЛЬКО параметры спецификации (в порядке Order) — как Архив
        if not spc_map.empty:
            ordered = (spc_map.sort_values('Order')
                       if 'Order' in spc_map.columns else spc_map)
            for _, spc_item in ordered.iterrows():
                p = spc_item['Parameter']
                if p in display_df.columns and p not in shown:
                    label = (spc_item.get('Note_mini')
                             or spc_item.get('Note') or p)
                    cols.append((p, str(label)))
                    shown.add(p)
        else:
            # Норм нет — показываем базовые БЕЗ подсветки
            for b in ('F', 'R', 'C0', 'Cq', 'Q', 'L'):
                if b in display_df.columns and b not in shown:
                    cols.append((b, b))
                    shown.add(b)

        for c in ('MachineType', 'Machine_Serial'):
            if c in display_df.columns and c not in shown:
                cols.append((c, c))
                shown.add(c)

        ae_per_row = preview.get('ae_per_row') or {}
        ae_summary = preview.get('ae_validation') or {}
        have_ae = bool(ae_per_row)
        if have_ae:
            cols.append(('__ae_score__', 'AE score'))
        cols.append(('__spec_status__', 'Статус'))

        # --- Диагностика колонок ------------------------------------
        _log("=" * 70)
        _log(f"[PREVIEW-TAB] cols ({len(cols)}): "
             f"{[k for k, _ in cols]}")
        _log(f"[PREVIEW-TAB] spc_map params: "
             f"{list(spc_map['Parameter']) if not spc_map.empty else []}")
        _log(f"[PREVIEW-TAB] param_status.keys: "
             f"{list(param_status.keys())}")
        for c, _l in cols:
            if c.startswith('__'):
                continue
            tag = 'spec' if c in param_status else 'base'
            _log(f"[PREVIEW-TAB]   col={c!r} ({tag})")
        _log("=" * 70)

        # --- Цвета ---------------------------------------------------
        AE_PARAM_COLS     = {'F', 'R', 'C0', 'Cq', 'Q', 'L'}
        COLOR_ROW_ANOM    = (255, 200, 100)
        COLOR_CELL_ANOM   = (255, 80, 80)
        COLOR_ROW_BAD     = (255, 200, 200)
        COLOR_CELL_BAD    = (255, 60, 60)
        COLOR_STATUS_GOOD = (100, 220, 100)
        COLOR_STATUS_BAD  = (255, 90, 90)
        COLOR_OK          = (255, 255, 255)

        # --- Рендер --------------------------------------------------
        with dpg.child_window(width=-1, height=-1, border=False):
            with dpg.table(header_row=True, resizable=True,
                           borders_innerH=True, borders_outerH=True,
                           borders_innerV=True,
                           policy=dpg.mvTable_SizingFixedFit,
                           scrollX=True):
                for _, label in cols:
                    dpg.add_table_column(label=label)

                for i, (_, row) in enumerate(display_df.iterrows()):
                    row_ok = (overall_ok[i]
                              if i < len(overall_ok) else True)
                    ae_info = ae_per_row.get(i) or {}
                    is_row_anom = bool(ae_info.get('is_anom'))
                    per_feat = ae_info.get('per_feature') or {}

                    with dpg.table_row():
                        for c, _label in cols:
                            # ----- Статус -----
                            if c == '__spec_status__':
                                if spc_map.empty:
                                    dpg.add_text('-',
                                                 color=(140, 140, 140))
                                elif row_ok:
                                    dpg.add_text('Годен',
                                                 color=COLOR_STATUS_GOOD)
                                else:
                                    dpg.add_text('Брак',
                                                 color=COLOR_STATUS_BAD)
                                continue

                            # ----- AE score -----
                            if c == '__ae_score__':
                                if ae_info:
                                    sc = ae_info.get('score')
                                    thr = ae_info.get('threshold')
                                    if sc is not None:
                                        txt = dpg.add_text(
                                            f"{sc:.3f}",
                                            color=(COLOR_CELL_ANOM
                                                   if is_row_anom
                                                   else COLOR_OK))
                                        thr_str = (f"{thr:.4f}"
                                                   if thr is not None
                                                   else "n/a")
                                        status_txt = (
                                            'АНОМАЛИЯ' if is_row_anom
                                            else 'OK')
                                        with dpg.tooltip(txt):
                                            dpg.add_text(
                                                f"Score: {sc:.4f}\n"
                                                f"Threshold: {thr_str}\n"
                                                f"{status_txt}")
                                    else:
                                        dpg.add_text("-")
                                else:
                                    dpg.add_text("-")
                                continue

                            # ----- Обычная ячейка -----
                            v = row.get(c, '')
                            if isinstance(v, float):
                                if pd.isna(v):
                                    v = ''
                                else:
                                    v = f"{v:.6g}"

                            p_status = param_status.get(c)
                            in_spec = p_status is not None

                            is_param_bad = (
                                in_spec
                                and not row_ok
                                and i < len(p_status)
                                and not bool(p_status[i])
                            )

                            is_ae_bad = False
                            cell_info = None
                            if (c in AE_PARAM_COLS
                                    and c in per_feat
                                    and is_row_anom):
                                cell_info = per_feat[c]
                                frac = cell_info.get('contrib_frac', 0)
                                rz   = cell_info.get('residual_z', 0)
                                if frac > 0.4 or rz > 2.5:
                                    is_ae_bad = True

                            if is_param_bad:
                                txt = dpg.add_text(
                                    str(v), color=COLOR_CELL_BAD)
                                pr = next(
                                    (pp for pp in (preview.get(
                                        'param_ranges') or [])
                                     if pp['param'] == c
                                     or pp['field'] == c),
                                    None)
                                if pr:
                                    with dpg.tooltip(txt):
                                        dpg.add_text(
                                            f"Вне нормы\n"
                                            f"Min: "
                                            f"{pr['min'] if pr['min'] is not None else '—'}\n"
                                            f"Max: "
                                            f"{pr['max'] if pr['max'] is not None else '—'}")
                            elif is_ae_bad:
                                txt = dpg.add_text(
                                    str(v), color=COLOR_CELL_ANOM)
                                with dpg.tooltip(txt):
                                    dpg.add_text(
                                        f"x = {cell_info['x']:.4g}\n"
                                        f"recon = "
                                        f"{cell_info['recon']:.4g}\n"
                                        f"residual = "
                                        f"{cell_info['residual_z']:.2f}σ\n"
                                        f"contribution = "
                                        f"{cell_info['contrib_frac'] * 100:.0f}%")
                            elif in_spec and not row_ok:
                                # параметр в спеке, сам ok, но строка брак
                                dpg.add_text(str(v), color=COLOR_ROW_BAD)
                            elif is_row_anom:
                                dpg.add_text(str(v),
                                             color=COLOR_ROW_ANOM)
                            else:
                                dpg.add_text(str(v))

            if len(display_df) > 200:
                dpg.add_text(
                    f"... показаны первые 200 из {len(display_df)}",
                    color=(150, 150, 150))

            if have_ae and ae_summary:
                dpg.add_spacer(height=4)
                dpg.add_text(
                    f"AE: mean={ae_summary.get('mean_score', 0):.3f} | "
                    f"max={ae_summary.get('max_score', 0):.3f} | "
                    f"аномалий {ae_summary.get('anomaly_count', 0)}/"
                    f"{ae_summary.get('total', 0)} | "
                    f"порог {ae_summary.get('threshold', 0):.3f}",
                    color=(180, 220, 180))
    except Exception as e:
        _log_exc("_build_preview_data_tab", e)


def _build_preview_data_tab_2(preview):
    """
    Таблица предпросмотра — эталон = тот же путь, что в PDF.

      * Статусы   — build_archive_status_df(df, spc_map) (как в Архиве);
      * Значения  — apply_rounding(rename_fields_to_parameters(df), spc_map);
      * Колонки   — базовые (F,R,C0,Cq,Q,L) + параметры спецификации
                    в порядке Order (как в Архиве), только для показа;
      * Подсветка:
          - параметр ВНЕ спеки     → обычный чёрный (в Архиве его
                                     вообще не показывают — здесь
                                     показываем, но НЕ подсвечиваем);
          - параметр в спеке, брак → ярко-красный (PARAM_BAD);
          - параметр в спеке, ok,
            но строка брак         → светло-красный (ROW_BAD) —
                                     как в Архиве;
          - AE-аномалия            → оранжевый + тултип;
          - AE-аномальный параметр → ярко-красный + тултип.
    """
    try:
        from Archive_View.Archive_Data import (
            build_archive_status_df, load_spc_map_for_archive,
            apply_rounding, rename_fields_to_parameters,
        )

        rows = preview.get('psidata_rows') or []
        if not rows:
            dpg.add_text("Нет данных")
            return

        raw_df = pd.DataFrame(rows)
        spc_name = preview.get('spc_name') or ''
        spc_map = (load_spc_map_for_archive(spc_name)
                   if spc_name else pd.DataFrame())

        # --- Статусы по эталону (как в PDF) -----------------------------
        if not spc_map.empty:
            status_df = build_archive_status_df(raw_df, spc_map)
            overall_ok = status_df['Status'].tolist()
            param_status = {}
            for col in status_df.columns:
                if col.endswith('_status') and col != 'Status':
                    p = col[:-len('_status')]
                    param_status[p] = status_df[col].tolist()
        else:
            overall_ok = [True] * len(raw_df)
            param_status = {}

        # --- Данные для отображения: rename + round (как в Архиве) ------
        display_df = rename_fields_to_parameters(raw_df)
        if not spc_map.empty:
            display_df = apply_rounding(display_df, spc_map)

        # --- Набор колонок ----------------------------------------------
        cols = []          # list of (key_in_display_df, header_label)
        shown = set()

        if 'Position' in display_df.columns:
            cols.append(('Position', 'Позиция'))
            shown.add('Position')
        elif 'Positions' in display_df.columns:
            cols.append(('Positions', 'Позиция'))
            shown.add('Positions')

        if 'N' in display_df.columns:
            cols.append(('N', 'N'))
            shown.add('N')
        elif 'Numbers' in display_df.columns:
            cols.append(('Numbers', 'N'))
            shown.add('Numbers')

        # Базовые параметры — показываем всегда (для наглядности)
        for b in ('F', 'R', 'C0', 'Cq', 'Q', 'L'):
            if b in display_df.columns and b not in shown:
                cols.append((b, b))
                shown.add(b)

        # Параметры спецификации в порядке Order
        if not spc_map.empty:
            ordered = (spc_map.sort_values('Order')
                       if 'Order' in spc_map.columns else spc_map)
            for _, spc_item in ordered.iterrows():
                p = spc_item['Parameter']
                if p in display_df.columns and p not in shown:
                    label = (spc_item.get('Note_mini')
                             or spc_item.get('Note') or p)
                    cols.append((p, str(label)))
                    shown.add(p)

        for c in ('MachineType', 'Machine_Serial'):
            if c in display_df.columns and c not in shown:
                cols.append((c, c))
                shown.add(c)

        ae_per_row = preview.get('ae_per_row') or {}
        ae_summary = preview.get('ae_validation') or {}
        have_ae = bool(ae_per_row)
        if have_ae:
            cols.append(('__ae_score__', 'AE score'))
        cols.append(('__spec_status__', 'Статус'))

        # --- Цвета ------------------------------------------------------
        AE_PARAM_COLS     = {'F', 'R', 'C0', 'Cq', 'Q', 'L'}
        COLOR_ROW_ANOM    = (255, 200, 100)
        COLOR_CELL_ANOM   = (255, 80, 80)
        COLOR_ROW_BAD     = (255, 200, 200)
        COLOR_CELL_BAD    = (255, 60, 60)
        COLOR_STATUS_GOOD = (100, 220, 100)
        COLOR_STATUS_BAD  = (255, 90, 90)
        COLOR_OK          = (255, 255, 255)

        # --- Рендер -----------------------------------------------------
        with dpg.child_window(width=-1, height=-1, border=False):
            with dpg.table(header_row=True, resizable=True,
                           borders_innerH=True, borders_outerH=True,
                           borders_innerV=True,
                           policy=dpg.mvTable_SizingFixedFit,
                           scrollX=True):
                for _, label in cols:
                    dpg.add_table_column(label=label)

                for i, (_, row) in enumerate(display_df.iterrows()):
                    row_ok = overall_ok[i] if i < len(overall_ok) else True
                    ae_info = ae_per_row.get(i) or {}
                    is_row_anom = bool(ae_info.get('is_anom'))
                    per_feat = ae_info.get('per_feature') or {}

                    with dpg.table_row():
                        for c, _label in cols:
                            # --- Статус ---
                            if c == '__spec_status__':
                                if spc_map.empty:
                                    dpg.add_text('-', color=(140, 140, 140))
                                elif row_ok:
                                    dpg.add_text('Годен',
                                                 color=COLOR_STATUS_GOOD)
                                else:
                                    dpg.add_text('Брак',
                                                 color=COLOR_STATUS_BAD)
                                continue

                            # --- AE score ---
                            if c == '__ae_score__':
                                if ae_info:
                                    sc = ae_info.get('score')
                                    thr = ae_info.get('threshold')
                                    if sc is not None:
                                        txt = dpg.add_text(
                                            f"{sc:.3f}",
                                            color=(COLOR_CELL_ANOM
                                                   if is_row_anom
                                                   else COLOR_OK))
                                        thr_str = (f"{thr:.4f}"
                                                   if thr is not None
                                                   else "n/a")
                                        status_txt = (
                                            'АНОМАЛИЯ' if is_row_anom
                                            else 'OK')
                                        with dpg.tooltip(txt):
                                            dpg.add_text(
                                                f"Score: {sc:.4f}\n"
                                                f"Threshold: {thr_str}\n"
                                                f"{status_txt}")
                                    else:
                                        dpg.add_text("-")
                                else:
                                    dpg.add_text("-")
                                continue

                            # --- Обычная ячейка ---
                            v = row.get(c, '')
                            if isinstance(v, float):
                                if pd.isna(v):
                                    v = ''
                                else:
                                    v = f"{v:.6g}"

                            # ▼ Ключевое: in_spec определяем по наличию
                            #   статуса из build_archive_status_df.
                            #   Если параметра нет в spc_map — не подсвечиваем
                            #   (в Архиве он вообще не отображается;
                            #    здесь показываем, но БЕЗ цвета).
                            p_status = param_status.get(c)
                            in_spec = p_status is not None

                            is_param_bad = (
                                in_spec
                                and not row_ok
                                and i < len(p_status)
                                and not bool(p_status[i])
                            )

                            # AE-аномалия параметра
                            is_ae_bad = False
                            cell_info = None
                            if (c in AE_PARAM_COLS
                                    and c in per_feat
                                    and is_row_anom):
                                cell_info = per_feat[c]
                                frac = cell_info.get('contrib_frac', 0)
                                rz   = cell_info.get('residual_z', 0)
                                if frac > 0.4 or rz > 2.5:
                                    is_ae_bad = True

                            # Цвет
                            if is_param_bad:
                                txt = dpg.add_text(
                                    str(v), color=COLOR_CELL_BAD)
                                pr = next(
                                    (pp for pp in (preview.get(
                                        'param_ranges') or [])
                                     if pp['param'] == c
                                     or pp['field'] == c),
                                    None)
                                if pr:
                                    with dpg.tooltip(txt):
                                        dpg.add_text(
                                            f"Вне нормы\n"
                                            f"Min: "
                                            f"{pr['min'] if pr['min'] is not None else '—'}\n"
                                            f"Max: "
                                            f"{pr['max'] if pr['max'] is not None else '—'}")
                            elif is_ae_bad:
                                txt = dpg.add_text(
                                    str(v), color=COLOR_CELL_ANOM)
                                with dpg.tooltip(txt):
                                    dpg.add_text(
                                        f"x = {cell_info['x']:.4g}\n"
                                        f"recon = "
                                        f"{cell_info['recon']:.4g}\n"
                                        f"residual = "
                                        f"{cell_info['residual_z']:.2f}σ\n"
                                        f"contribution = "
                                        f"{cell_info['contrib_frac'] * 100:.0f}%")
                            elif in_spec and not row_ok:
                                # Параметр в спеке, сам ok, но строка брак
                                # → светло-красный (как в Архиве)
                                dpg.add_text(str(v), color=COLOR_ROW_BAD)
                            elif is_row_anom:
                                dpg.add_text(str(v),
                                             color=COLOR_ROW_ANOM)
                            else:
                                # Не в спеке — обычный цвет
                                # (в Архиве не отображается; здесь
                                # показываем нейтрально)
                                dpg.add_text(str(v))

            if len(display_df) > 200:
                dpg.add_text(
                    f"... показаны первые 200 из {len(display_df)}",
                    color=(150, 150, 150))

            if have_ae and ae_summary:
                dpg.add_spacer(height=4)
                dpg.add_text(
                    f"AE: mean={ae_summary.get('mean_score', 0):.3f} | "
                    f"max={ae_summary.get('max_score', 0):.3f} | "
                    f"аномалий {ae_summary.get('anomaly_count', 0)}/"
                    f"{ae_summary.get('total', 0)} | "
                    f"порог {ae_summary.get('threshold', 0):.3f}",
                    color=(180, 220, 180))
    except Exception as e:
        _log_exc("_build_preview_data_tab", e)

def _build_preview_data_tab_1(preview):
    """
    Таблица предпросмотра с разбраковкой по спецификации + AE:

    Статус (Годен/Брак) считается по всем параметрам спецификации:
        NaN или вне [Min, Max] → Брак.
    Status/Status2 psidata не используются.
    """
    try:
        rows = preview['psidata_rows']
        ae_per_row = preview.get('ae_per_row') or {}
        ae_summary = preview.get('ae_validation') or {}
        spec_per_row = preview.get('spec_per_row') or []
        have_ae = bool(ae_per_row)

        spec_params = set()
        if spec_per_row:
            spec_params = set(spec_per_row[0].keys())

        cols = ['N', 'Position']

        for c in ['F', 'R', 'C0', 'Cq', 'Q', 'L']:
            if rows and c in rows[0] and c not in cols:
                cols.append(c)

        for p in spec_params:
            if p not in cols:
                cols.append(p)

        cols += ['MachineType', 'Machine_Serial']
        if have_ae:
            cols.append('__ae_score__')
        cols.append('__spec_status__')

        AE_PARAM_COLS = {'F', 'R', 'C0', 'Cq', 'Q', 'L'}

        COLOR_ROW_ANOM    = (255, 200, 100)
        COLOR_CELL_ANOM   = (255, 80, 80)
        COLOR_ROW_BAD     = (255, 200, 200)
        COLOR_CELL_BAD    = (255, 60, 60)
        COLOR_STATUS_GOOD = (100, 220, 100)
        COLOR_STATUS_BAD  = (255, 90, 90)
        COLOR_OK          = (255, 255, 255)

        if not rows:
            dpg.add_text("Нет данных")
            return

        with dpg.child_window(width=-1, height=-1, border=False):
            with dpg.table(header_row=True, resizable=True,
                           borders_innerH=True, borders_outerH=True,
                           borders_innerV=True,
                           policy=dpg.mvTable_SizingFixedFit,
                           scrollX=True):
                for c in cols:
                    if c == '__ae_score__':
                        dpg.add_table_column(label='AE score')
                    elif c == '__spec_status__':
                        dpg.add_table_column(label='Статус')
                    else:
                        dpg.add_table_column(label=c)

                for i, r in enumerate(rows[:200]):
                    ae_info = ae_per_row.get(i) or {}
                    is_row_anom = bool(ae_info.get('is_anom'))
                    per_feat = ae_info.get('per_feature') or {}

                    if i < len(spec_per_row) and spec_per_row[i]:
                        row_param_status = spec_per_row[i]
                        row_ok = all(row_param_status.values())
                    else:
                        row_param_status = {}
                        row_ok = True

                    with dpg.table_row():
                        for c in cols:
                            if c == '__ae_score__':
                                if ae_info:
                                    sc = ae_info.get('score')
                                    thr = ae_info.get('threshold')
                                    if sc is not None:
                                        txt = dpg.add_text(
                                            f"{sc:.3f}",
                                            color=(COLOR_CELL_ANOM
                                                   if is_row_anom
                                                   else COLOR_OK))
                                        thr_str = (f"{thr:.4f}"
                                                   if thr is not None
                                                   else "n/a")
                                        status_txt = (
                                            'АНОМАЛИЯ' if is_row_anom
                                            else 'OK')
                                        with dpg.tooltip(txt):
                                            dpg.add_text(
                                                f"Score: {sc:.4f}\n"
                                                f"Threshold: {thr_str}\n"
                                                f"{status_txt}")
                                    else:
                                        dpg.add_text("-")
                                else:
                                    dpg.add_text("-")
                                continue

                            if c == '__spec_status__':
                                if not spec_params:
                                    dpg.add_text('-',
                                                 color=(140, 140, 140))
                                elif row_ok:
                                    dpg.add_text('Годен',
                                                 color=COLOR_STATUS_GOOD)
                                else:
                                    dpg.add_text('Брак',
                                                 color=COLOR_STATUS_BAD)
                                continue

                            v = r.get(c, '')
                            if isinstance(v, float):
                                if pd.isna(v):
                                    v = ''
                                else:
                                    v = f"{v:.6g}"

                            is_param_bad = (
                                not row_ok
                                and c in row_param_status
                                and not row_param_status.get(c, True)
                            )

                            is_ae_bad = False
                            cell_info = None
                            if (c in AE_PARAM_COLS
                                    and c in per_feat
                                    and is_row_anom):
                                cell_info = per_feat[c]
                                frac = cell_info.get('contrib_frac', 0)
                                rz   = cell_info.get('residual_z', 0)
                                if frac > 0.4 or rz > 2.5:
                                    is_ae_bad = True

                            if is_param_bad:
                                txt = dpg.add_text(
                                    str(v), color=COLOR_CELL_BAD)
                                pr = next(
                                    (pp for pp in (preview.get(
                                        'param_ranges') or [])
                                     if pp['field'] == c
                                     or pp['param'] == c),
                                    None)
                                if pr:
                                    with dpg.tooltip(txt):
                                        dpg.add_text(
                                            f"Вне нормы\n"
                                            f"Min: "
                                            f"{pr['min'] if pr['min'] is not None else '—'}\n"
                                            f"Max: "
                                            f"{pr['max'] if pr['max'] is not None else '—'}")
                            elif is_ae_bad:
                                txt = dpg.add_text(
                                    str(v), color=COLOR_CELL_ANOM)
                                with dpg.tooltip(txt):
                                    dpg.add_text(
                                        f"x = {cell_info['x']:.4g}\n"
                                        f"recon = "
                                        f"{cell_info['recon']:.4g}\n"
                                        f"residual = "
                                        f"{cell_info['residual_z']:.2f}σ\n"
                                        f"contribution = "
                                        f"{cell_info['contrib_frac'] * 100:.0f}%")
                            elif not row_ok:
                                dpg.add_text(str(v),
                                             color=COLOR_ROW_BAD)
                            elif is_row_anom:
                                dpg.add_text(str(v),
                                             color=COLOR_ROW_ANOM)
                            else:
                                dpg.add_text(str(v))

            if len(rows) > 200:
                dpg.add_text(
                    f"... показаны первые 200 из {len(rows)}",
                    color=(150, 150, 150))

            if have_ae and ae_summary:
                dpg.add_spacer(height=4)
                dpg.add_text(
                    f"AE: mean={ae_summary.get('mean_score', 0):.3f} | "
                    f"max={ae_summary.get('max_score', 0):.3f} | "
                    f"аномалий {ae_summary.get('anomaly_count', 0)}/"
                    f"{ae_summary.get('total', 0)} | "
                    f"порог {ae_summary.get('threshold', 0):.3f}",
                    color=(180, 220, 180))
    except Exception as e:
        _log_exc("_build_preview_data_tab", e)


def _build_preview_stats_tab(preview):
    try:
        dpg.add_text(
            "Статистика по параметру (базовый vs виртуальный)")
        with dpg.group(horizontal=True):
            with dpg.group(width=200):
                dpg.add_text("Параметр")
                params = ['F', 'R', 'C0', 'Cq', 'L', 'Q', 'FT',
                          'Mono', 'Fmaxm', 'Fptp', 'Slope']
                dpg.add_combo(params, tag='vprev_param', width=200,
                              default_value='F')
        dpg.add_spacer(height=4)
        with dpg.group(horizontal=True):
            dpg.add_button(
                label="Пересчитать", width=140,
                callback=lambda s, a: _refresh_preview_stats(preview))
        dpg.add_separator()
        with dpg.plot(tag='vprev_plot', height=250, width=-1):
            dpg.add_plot_legend()
            dpg.add_plot_axis(dpg.mvXAxis, label="Значение")
            dpg.add_plot_axis(dpg.mvYAxis, label="Плотность",
                              tag='vprev_plot_y')
        dpg.add_separator()
        with dpg.table(tag='vprev_stats_table', header_row=True,
                       borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True,
                       policy=dpg.mvTable_SizingFixedFit):
            dpg.add_table_column(label="Метрика")
            dpg.add_table_column(label="Базовый")
            dpg.add_table_column(label="Виртуальный")
        _refresh_preview_stats(preview)
    except Exception as e:
        _log_exc("_build_preview_stats_tab", e)


def _refresh_preview_stats(preview):
    try:
        param = dpg.get_value('vprev_param')
        if not param:
            return

        base_vals = []
        base_df = vd.load_base_psidata(preview['base_mid'])
        if not base_df.empty and param in base_df.columns:
            base_vals = [float(v) for v in
                         base_df[param].dropna().tolist()]

        virt_vals = []
        for r in preview.get('psidata_rows', []):
            v = r.get(param)
            if isinstance(v, (int, float)):
                virt_vals.append(float(v))

        dist = vs.compute_distribution(base_vals, virt_vals, 200)
        _draw_distribution('vprev_plot_y', dist)

        bs = vs.compute_stats(base_vals)
        vs_ = vs.compute_stats(virt_vals)

        if dpg.does_item_exist('vprev_stats_table'):
            for c in dpg.get_item_children(
                    'vprev_stats_table', 1) or []:
                dpg.delete_item(c)
            for label, fn in [
                ('n',       lambda s: f"{s['n']}"),
                ('Среднее', lambda s: _fmt(s['mean'])),
                ('СКО',     lambda s: _fmt(s['std'])),
                ('Мин',     lambda s: _fmt(s['min'])),
                ('Макс',    lambda s: _fmt(s['max'])),
                ('Медиана', lambda s: _fmt(s['median'])),
                ('Q1',      lambda s: _fmt(s['q1'])),
                ('Q3',      lambda s: _fmt(s['q3'])),
                ('IQR',     lambda s: _fmt(s['iqr'])),
            ]:
                with dpg.table_row(parent='vprev_stats_table'):
                    dpg.add_text(label)
                    dpg.add_text(fn(bs))
                    dpg.add_text(fn(vs_))
    except Exception as e:
        _log_exc("_refresh_preview_stats", e)


# ============================================================================
# Сохранение
# ============================================================================
def _on_save():
    preview = _state.get('preview')
    if not preview:
        dpg.set_value(NEW_MID_LABEL,
                      "Нет данных: сначала нажмите «Генерация»")
        return

    try:
        def worker():
            def cb(percent, message):
                _progress_update(percent, message,
                                 f"МСК: {preview['new_msk']}")
            _log("worker[save]: старт")
            result = vd.save_generated_data(preview, progress_cb=cb)
            _log(f"worker[save]: result={result}")
            return result

        def on_done(result):
            try:
                new_mid, n_psi, n_temp = result
            except Exception as e:
                _log_exc("_on_save: разбор result", e)
                dpg.set_value(NEW_MID_LABEL,
                              f"Ошибка разбора: {e}")
                return
            if not new_mid:
                dpg.set_value(NEW_MID_LABEL,
                              "Не удалось сохранить (mid=None)")
                return
            _state['preview'] = None
            _state['virtual_mid'] = new_mid
            dpg.set_value(
                NEW_MID_LABEL,
                f"Сохранено: Measure_ID = {new_mid}  "
                f"(psidata: {n_psi}, psidatatemp: {n_temp})")
            if dpg.does_item_exist(PREVIEW_TAG):
                dpg.delete_item(PREVIEW_TAG)
            _refresh_virtual_mid_combo()
            _refresh_stats()

        def on_error(err):
            dpg.set_value(NEW_MID_LABEL, f"Ошибка сохранения: {err}")

        dpg.set_value(NEW_MID_LABEL, "Сохранение в БД...")
        _run_with_progress(
            worker, on_done=on_done, on_error=on_error,
            start_msg='Сохранение в БД...',
            title='Сохранение виртуального замера')
    except Exception as e:
        _log_exc("_on_save", e)
        dpg.set_value(NEW_MID_LABEL, f"Ошибка: {e}")


# ============================================================================
# Печать
# ============================================================================
def _on_print_protocol():
    preview = _state.get('preview')
    if not preview:
        dpg.set_value(NEW_MID_LABEL,
                      "Нет данных: сначала нажмите «Генерация»")
        return
    _generate_preview_protocol(preview)


def _on_print_temps():
    preview = _state.get('preview')
    if not preview:
        dpg.set_value(NEW_MID_LABEL,
                      "Нет данных: сначала нажмите «Генерация»")
        return
    _generate_preview_temps(preview)


def _generate_preview_protocol(preview):
    try:
        spec_row = preview['spec_row']
        spc_map = load_spc_map_for_archive(preview['spc_name'])
        if spc_map.empty:
            dpg.set_value(NEW_MID_LABEL, "Не удалось загрузить нормы")
            return

        df = pd.DataFrame(preview['psidata_rows'])
        if df.empty:
            dpg.set_value(NEW_MID_LABEL, "Нет данных для протокола")
            return

        data_df = build_archive_print_data(df, spc_map)
        status_df = build_archive_status_df(df, spc_map)
        view_data = build_view_data_from_archive(df, spec_row)
        stats_df = get_archive_statistics(df, spc_map)
        headers = get_headers_dict(spc_map)
        round_map = get_round_dict(spc_map)

        preview_mid = preview.get('new_mid')
        if not preview_mid:
            preview_mid = vd.peek_next_measure_id()

        import Temperature_Measure.Report as _rep
        orig = _rep.format_parameter_stat

        def _patched(col, metric, stats_df_):
            ps = stats_df_[stats_df_['Parameter'] == col]
            if ps.empty:
                return '-'
            v = ps[metric].values[0]
            if pd.isna(v):
                return '-'
            if metric in ('Брак', 'Годные'):
                return f"{int(v)}"
            dec = int(round_map.get(col, 2)) if col in round_map else 2
            try:
                return f"{float(v):.{dec}f}"
            except Exception:
                return str(v)

        try:
            _rep.format_parameter_stat = _patched
            filename = generate_filename(preview_mid)
            path = create_protocol(
                data_df=data_df, status_df=status_df, headers=headers,
                spc_map=spc_map, view_data=view_data,
                stats_df=stats_df, measure_id=preview_mid,
                filename=filename)
        finally:
            _rep.format_parameter_stat = orig

        open_pdf(path)
        dpg.set_value(NEW_MID_LABEL, f"Протокол: {path}")
    except Exception as e:
        _log_exc("_generate_preview_protocol", e)
        dpg.set_value(NEW_MID_LABEL, f"Ошибка протокола: {e}")


def _generate_preview_temps(preview):
    try:
        spec_row = preview['spec_row']
        tnastr = vd._safe_float(spec_row.get('Tnastr')) or 25.0

        temp_df = pd.DataFrame(preview['temp_rows'])
        if temp_df.empty:
            dpg.set_value(NEW_MID_LABEL, "Нет температурных данных")
            return

        pdf_df = prepare_temperatures_for_pdf(
            temp_df, tnastr, spec_row)
        if pdf_df.empty:
            dpg.set_value(NEW_MID_LABEL,
                          "Не удалось подготовить температуры")
            return

        df = pd.DataFrame(preview['psidata_rows'])
        view_data = build_view_data_from_archive(df, spec_row)

        preview_mid = preview.get('new_mid')
        if not preview_mid:
            preview_mid = vd.peek_next_measure_id()
        filename = generate_filename(preview_mid, print_version=True)
        path = generate_pdf(
            measure_id=preview_mid, view_data=view_data,
            df=pdf_df, filename=filename, num_columns=4)
        open_pdf(path)
        dpg.set_value(NEW_MID_LABEL, f"Распечатка: {path}")
    except Exception as e:
        _log_exc("_generate_preview_temps", e)
        dpg.set_value(NEW_MID_LABEL, f"Ошибка распечатки: {e}")


# ============================================================================
# Статистика
# ============================================================================
def _refresh_virtual_mid_combo():
    try:
        spc = _get_combo_value('vspc_combo')
        _log(f"_refresh_virtual_mid_combo: spc='{spc}'")
        mids = vs.list_virtual_measure_ids(spc if spc else None)
        _log(f"_refresh_virtual_mid_combo: найдено {len(mids)}")
        str_ids = [str(x) for x in mids]
        _safe_set_combo(VIRT_MID_COMBO, str_ids)
        if _state.get('virtual_mid') in mids:
            dpg.set_value(VIRT_MID_COMBO, str(_state['virtual_mid']))
        elif str_ids:
            dpg.set_value(VIRT_MID_COMBO, str_ids[-1])
            _state['virtual_mid'] = mids[-1]
        else:
            _state['virtual_mid'] = None
    except Exception as e:
        _log_exc("_refresh_virtual_mid_combo", e)


def _refresh_stats():
    try:
        if not dpg.does_item_exist(PARAM_COMBO):
            return

        param = dpg.get_value(PARAM_COMBO)
        base_mid_str = _get_combo_value('vbase_mid_combo')
        virt_mid_str = _get_combo_value(VIRT_MID_COMBO)

        _log(f"_refresh_stats: param='{param}', base='{base_mid_str}', "
             f"virt='{virt_mid_str}'")

        if not param or not base_mid_str:
            dpg.set_value(STATUS_LABEL,
                          "Выберите параметр и базовый Measure_ID")
            return

        try:
            base_mid = int(base_mid_str)
        except ValueError:
            return

        virt_mid = None
        if virt_mid_str:
            try:
                virt_mid = int(virt_mid_str)
                _state['virtual_mid'] = virt_mid
            except ValueError:
                virt_mid = None

        base_vals = vs.collect_param_values(
            base_mid, param, only_virtual=False)
        virt_vals = []
        if virt_mid:
            virt_vals = vs.collect_param_values(
                virt_mid, param, only_virtual=True)

        _log(f"_refresh_stats: base={len(base_vals)}, "
             f"virt={len(virt_vals)}")

        if not base_vals and not virt_vals:
            dpg.set_value(STATUS_LABEL,
                          "Нет данных для выбранного параметра")
            _clear_plot(PLOT_Y_AXIS)
            _clear_stats_table(STATS_TABLE)
            return

        bs = vs.compute_stats(base_vals)
        vs_ = vs.compute_stats(virt_vals)
        dpg.set_value(
            STATUS_LABEL,
            f"Базовый n={bs['n']}, Виртуальный n={vs_['n']}")

        dist = vs.compute_distribution(base_vals, virt_vals, 200)
        _draw_distribution(PLOT_Y_AXIS, dist)

        _clear_stats_table(STATS_TABLE)
        for label, fn in [
            ('n',       lambda s: f"{s['n']}"),
            ('Среднее', lambda s: _fmt(s['mean'])),
            ('СКО',     lambda s: _fmt(s['std'])),
            ('Мин',     lambda s: _fmt(s['min'])),
            ('Макс',    lambda s: _fmt(s['max'])),
            ('Медиана', lambda s: _fmt(s['median'])),
            ('Q1',      lambda s: _fmt(s['q1'])),
            ('Q3',      lambda s: _fmt(s['q3'])),
            ('IQR',     lambda s: _fmt(s['iqr'])),
        ]:
            with dpg.table_row(parent=STATS_TABLE):
                dpg.add_text(label)
                dpg.add_text(fn(bs))
                dpg.add_text(fn(vs_))
    except Exception as e:
        _log_exc("_refresh_stats", e)


def _clear_plot(y_axis):
    try:
        if not dpg.does_item_exist(y_axis):
            return
        for c in dpg.get_item_children(y_axis, 1) or []:
            dpg.delete_item(c)
    except Exception as e:
        _log_exc("_clear_plot", e)


def _clear_stats_table(table_tag):
    try:
        if not dpg.does_item_exist(table_tag):
            return
        for c in dpg.get_item_children(table_tag, 1) or []:
            dpg.delete_item(c)
    except Exception as e:
        _log_exc("_clear_stats_table", e)


def _draw_distribution(y_axis, dist):
    try:
        _clear_plot(y_axis)
        if not dist:
            return
        x    = dist['x']
        base = dist['base']
        virt = dist['virt']
        if base:
            dpg.add_line_series(x, base, label="Базовый",
                                parent=y_axis)
        if virt:
            dpg.add_line_series(x, virt, label="Виртуальный",
                                parent=y_axis)
    except Exception as e:
        _log_exc("_draw_distribution", e)


def _fmt(v):
    if v is None:
        return '-'
    if isinstance(v, int):
        return str(v)
    return f"{v:.6g}"