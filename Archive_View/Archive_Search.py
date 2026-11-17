"""Прогресс-окно, фоновый поиск по номерам и по МСК."""
import time
import threading
import pandas as pd
import dearpygui.dearpygui as dpg

from Temperature_Measure import _layout
from .Archive_Constants import (
    WINDOW_TAG, PROGRESS_WINDOW, PROGRESS_BAR, PROGRESS_TEXT,
    PROGRESS_DETAIL, ALL_MSK, MODE_ONLY_NUM, MODE_FULL_MSK,
    _progress_state,
)
from .Archive_Data import (
    find_measure_ids_by_numbers, load_archive_by_numbers,
    search_archive_msk, load_spc_map_for_archive,
    build_archive_status_df,
)
from .Archive_Helpers import _filter_good_only

from .Archive_UI import (_fill_table, _fill_info, _fill_norms,
                         _resolve_display_spc, _apply_psi_type_from_df)


# ------------------------------------------------------------- прогресс-окно
def _show_progress_window():
    if dpg.does_item_exist(PROGRESS_WINDOW):
        dpg.delete_item(PROGRESS_WINDOW)

    sw, sh = _layout.screen_size()
    w, h = 540, 170
    pos = ((sw - w) // 2, (sh - h) // 2)
    kind = _progress_state.get('kind', 'numbers')
    label = "Поиск по номерам" if kind == 'numbers' else "Поиск по МСК"

    with dpg.window(label=label, tag=PROGRESS_WINDOW,
                    width=w, height=h, pos=pos,
                    modal=True, no_close=True,
                    no_collapse=True, no_resize=True):
        dpg.add_text("Инициализация...", tag=PROGRESS_TEXT)
        dpg.add_spacer(height=6)
        dpg.add_progress_bar(tag=PROGRESS_BAR, width=-1, default_value=0.0)
        dpg.add_spacer(height=6)
        dpg.add_text("", tag=PROGRESS_DETAIL, color=(150, 150, 150))


def _update_progress_ui():
    if dpg.does_item_exist(PROGRESS_BAR):
        p = max(0.0, min(1.0, _progress_state['percent'] / 100.0))
        dpg.set_value(PROGRESS_BAR, p)
    if dpg.does_item_exist(PROGRESS_TEXT):
        dpg.set_value(PROGRESS_TEXT, _progress_state['message'])
    if dpg.does_item_exist(PROGRESS_DETAIL):
        dpg.set_value(PROGRESS_DETAIL, _progress_state.get('detail', ''))


def _poll_progress():
    if not _progress_state['active']:
        return
    if not dpg.does_item_exist(WINDOW_TAG):
        _progress_state['active'] = False
        if dpg.does_item_exist(PROGRESS_WINDOW):
            dpg.delete_item(PROGRESS_WINDOW)
        return
    if _progress_state['done']:
        _finish_progress()
        return

    elapsed = time.time() - _progress_state['start_time']
    if not _progress_state['window_shown']:
        if elapsed < 0.5:
            dpg.set_frame_callback(dpg.get_frame_count() + 1, _poll_progress)
            return
        _show_progress_window()
        _progress_state['window_shown'] = True

    _update_progress_ui()
    dpg.set_frame_callback(dpg.get_frame_count() + 1, _poll_progress)


def _finish_progress():
    if dpg.does_item_exist(PROGRESS_WINDOW):
        dpg.delete_item(PROGRESS_WINDOW)

    if _progress_state.get('error'):
        _progress_state['active'] = False
        msg = f"Ошибка поиска: {_progress_state['error']}"
        dpg.set_value('archive_status_text', msg)
        print(f"[Archive] {msg}")
        return

    kind = _progress_state.get('kind', 'numbers')
    if kind == 'msk':
        _display_msk_search_results(
            _progress_state.get('msk_results') or [],
            _progress_state.get('msk_partial') or '')
    else:
        _display_search_results(
            _progress_state.get('result_df'),
            _progress_state.get('numbers_filter') or [],
            _progress_state.get('mode') or MODE_ONLY_NUM)
    _progress_state['active'] = False


# ------------------------------------------------------ поиск по номерам
def _search_worker(numbers_filter, mode, only_good):
    try:
        _progress_state['percent'] = 15
        _progress_state['message'] = 'Поиск замеров по номерам...'
        _progress_state['detail'] = f'Номеров в запросе: {len(numbers_filter)}'

        mids = find_measure_ids_by_numbers(numbers_filter, only_good=False)
        if not mids:
            _progress_state['percent'] = 100
            _progress_state['message'] = 'Замеры не найдены'
            _progress_state['detail'] = ''
            _progress_state['result_df'] = pd.DataFrame()
            _progress_state['done'] = True
            return

        _progress_state['percent'] = 55
        _progress_state['message'] = (
            f'Найдено замеров: {len(mids)}. Загрузка записей...')
        _progress_state['detail'] = ''

        df = load_archive_by_numbers(numbers_filter, mode,
                                     only_good=False, found_mids=mids)

        _progress_state['percent'] = 100
        _progress_state['message'] = 'Готово'
        _progress_state['detail'] = (
            'Записей загружено: 0' if df is None or df.empty
            else f'Записей загружено: {len(df)}')
        _progress_state['result_df'] = df
        _progress_state['done'] = True
    except Exception as e:
        _progress_state['error'] = str(e)
        _progress_state['done'] = True


def _start_numbers_search(numbers_filter, mode, only_good):
    if _progress_state['active']:
        dpg.set_value('archive_status_text', 'Поиск уже выполняется...')
        return

    _progress_state.update({
        'active': True, 'percent': 0.0,
        'message': 'Запуск поиска...', 'detail': '',
        'done': False, 'result_df': None, 'error': None,
        'numbers_filter': numbers_filter, 'mode': mode,
        'start_time': time.time(), 'window_shown': False,
        'kind': 'numbers', 'msk_results': None, 'msk_partial': None,
    })

    threading.Thread(target=_search_worker,
                     args=(numbers_filter, mode, only_good),
                     daemon=True).start()
    dpg.set_frame_callback(dpg.get_frame_count() + 1, _poll_progress)


def _display_search_results(df, numbers_filter, mode):
    from .Archive_Constants import _view_state
    _view_state['mode'] = 'normal'
    _view_state['target_numbers'] = []
    only_good = dpg.get_value('archive_only_good_check')
    fallback_spc = dpg.get_value('archive_spc_combo') or ''
    if only_good and df is not None and not df.empty:
        n_before = len(df)
        df = _filter_good_only(df, fallback_spc)
        print(f"[Archive] only_good (поиск по номерам): "
              f"{n_before} → {len(df)} строк")

    dpg.set_item_user_data(WINDOW_TAG, df)
    _apply_psi_type_from_df(df)
    _fill_table(df)
    _fill_info(df)

    spc_for_norms = _resolve_display_spc(df)
    _fill_norms(spc_for_norms)
    if df is None or df.empty:
        dpg.set_value('archive_status_text',
                      f'По номерам ({len(numbers_filter)} шт.) ничего не найдено')
        return

    n_mids = df['Measure_ID'].nunique() if 'Measure_ID' in df.columns else 0
    n_msks = df['MSK'].nunique() if 'MSK' in df.columns else 0
    mode_str = 'вся МСК' if mode == MODE_FULL_MSK else 'только номер'

    n_good = n_bad = 0
    try:
        spc_map = (load_spc_map_for_archive(spc_for_norms)
                   if spc_for_norms else pd.DataFrame())
        st = build_archive_status_df(df, spc_map)
        n_good = int(st['Status'].sum())
        n_bad = len(st) - n_good
    except Exception:
        pass

    dpg.set_value(
        'archive_status_text',
        f'Поиск по номерам: {len(numbers_filter)} | '
        f'замеров: {n_mids} | МСК: {n_msks} | '
        f'записей: {len(df)} | Годных: {n_good} | Брак: {n_bad} | '
        f'режим: {mode_str}')


# --------------------------------------------------------- поиск по МСК
def _msk_search_worker(partial):
    try:
        _progress_state['percent'] = 15
        _progress_state['message'] = 'Поиск МСК...'
        _progress_state['detail'] = f'Подстрока: {partial}'
        matches = search_archive_msk(partial)
        _progress_state['percent'] = 100
        _progress_state['message'] = 'Готово'
        _progress_state['detail'] = f'Найдено МСК: {len(matches)}'
        _progress_state['msk_results'] = matches
        _progress_state['done'] = True
    except Exception as e:
        _progress_state['error'] = str(e)
        _progress_state['done'] = True


def _start_msk_search(partial):
    if _progress_state['active']:
        dpg.set_value('archive_status_text', 'Поиск уже выполняется...')
        return

    _progress_state.update({
        'active': True, 'percent': 0.0,
        'message': 'Запуск поиска МСК...', 'detail': '',
        'done': False, 'result_df': None, 'error': None,
        'numbers_filter': None, 'mode': MODE_ONLY_NUM,
        'start_time': time.time(), 'window_shown': False,
        'kind': 'msk', 'msk_results': None, 'msk_partial': partial,
    })

    threading.Thread(target=_msk_search_worker, args=(partial,),
                     daemon=True).start()
    dpg.set_frame_callback(dpg.get_frame_count() + 1, _poll_progress)


def _display_msk_search_results(matches, partial):
    from .Archive_Cascade import on_msk_changed
    items = [ALL_MSK] + list(matches) if matches else [ALL_MSK]
    dpg.configure_item('archive_msk_combo', items=items)
    dpg.set_value('archive_msk_combo', matches[0] if matches else ALL_MSK)
    on_msk_changed()

    dpg.set_value(
        'archive_status_text',
        f'Поиск МСК по "{partial}": найдено {len(matches)}. '
        f'Выберите МСК из списка.' if matches
        else f'Поиск МСК по "{partial}": ничего не найдено')


def _on_msk_search(sender=None, data=None):
    if not dpg.does_item_exist('archive_msk_search_input'):
        return
    partial = (dpg.get_value('archive_msk_search_input') or '').strip()
    if not partial:
        dpg.set_value('archive_status_text', 'Введите часть номера МСК')
        return
    _start_msk_search(partial)


def _on_clear_msk_search(sender=None, data=None):
    from .Archive_Cascade import on_spc_changed
    if dpg.does_item_exist('archive_msk_search_input'):
        dpg.set_value('archive_msk_search_input', '')
    on_spc_changed()