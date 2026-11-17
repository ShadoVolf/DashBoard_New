"""Общее состояние, раскладка, индикатор загрузки, сообщения и MSK-хелперы."""
import dearpygui.dearpygui as dpg

import Statistik.Data
from Statistik.Operations import get_msk_plating_count


# ===========================================================================
# Разделяемое состояние (бывшие module-level global в DashBoard.py)
# ===========================================================================
class MSKState:
    full_info: dict = {}
    all_display: list = []
    all_raw: list = []
    display_now: list = []
    raw_now: list = []
    nom_all: list = []
    selected_single: str = None


# ===========================================================================
# Раскладка
# ===========================================================================
def _get_screen_size():
    try:
        w = dpg.get_viewport_client_width()
        h = dpg.get_viewport_client_height()
        if w > 100 and h > 100:
            return w, h
    except Exception:
        pass
    return 1920, 1080


def _layout() -> dict:
    sw, sh = _get_screen_size()
    m = 6
    menu_h = 30
    usable_h = sh - menu_h - 2 * m
    left_w = int(sw * 0.22)
    right_w = int(sw * 0.29)
    mid_w = sw - left_w - right_w - 4 * m
    nom_h = int(usable_h * 0.28)
    msk_h = usable_h - nom_h - m
    filt_h = int(usable_h * 0.36)
    res_h = int(usable_h * 0.36)
    act_h = usable_h - filt_h - res_h - 2 * m
    # --- ассистент: свободная ячейка правой колонки (между plot и signal) ---
    # На старте result_msk_window не создаётся, поэтому rmsk_y/rmsk_h — свободно.
    asst_x = m + left_w + m + mid_w + m           # = right_x
    asst_y = menu_h + m + filt_h + m              # = rmsk_y
    asst_w = right_w
    asst_h = res_h                                # = rmsk_h
    return {
        'm': m,
        'left_x': m, 'left_w': left_w,
        'mid_x': m + left_w + m, 'mid_w': mid_w,
        'right_x': m + left_w + m + mid_w + m, 'right_w': right_w,
        'nom_y': menu_h + m, 'nom_h': nom_h,
        'msk_y': menu_h + m + nom_h + m, 'msk_h': msk_h,
        'filt_y': menu_h + m, 'filt_h': filt_h,
        'res_y': menu_h + m + filt_h + m, 'res_h': res_h,
        'act_y': menu_h + m + filt_h + m + res_h + m, 'act_h': act_h,
        'plot_y': menu_h + m, 'plot_h': filt_h,
        'rmsk_y': menu_h + m + filt_h + m, 'rmsk_h': res_h,
        'sig_y': menu_h + m + filt_h + m + res_h + m, 'sig_h': act_h,
        'rmsk_y': menu_h + m + filt_h + m, 'rmsk_h': res_h,
        'sig_y': menu_h + m + filt_h + m + res_h + m, 'sig_h': act_h,
        # NEW:
        'asst_x': asst_x, 'asst_y': asst_y,
        'asst_w': asst_w, 'asst_h': asst_h,
    }


# ===========================================================================
# Индикатор загрузки
# ===========================================================================
def show_indicator(dpg_):
    hide_indicator(dpg_)
    vp_w = dpg_.get_viewport_client_width() or 1920
    vp_h = dpg_.get_viewport_client_height() or 1080
    win_w, win_h = 340, 140
    pos_x = max(0, (vp_w - win_w) // 2)
    pos_y = max(0, (vp_h - win_h) // 2)
    with dpg_.window(label="Загрузка", tag='load_ind',
                     width=win_w, height=win_h, pos=(pos_x, pos_y),
                     modal=True, no_resize=True, no_move=True,
                     no_collapse=True, no_close=True, no_scrollbar=True):
        dpg_.add_spacer(height=14)
        with dpg_.group(horizontal=True):
            try:
                dpg_.add_loading_indicator(style=1)
            except TypeError:
                dpg_.add_loading_indicator()
            dpg_.add_spacer(width=12)
            dpg_.add_text("Загрузка данных...", color=(230, 230, 240))
        dpg_.add_spacer(height=12)
        dpg_.add_text("Пожалуйста, подождите", color=(160, 160, 170))


def hide_indicator(dpg_):
    if dpg_.does_item_exist('load_ind'):
        dpg_.delete_item('load_ind')


# ===========================================================================
# Сообщение
# ===========================================================================
def show_message(mes_str, dpg_):
    sw = dpg_.get_viewport_width() or 1920
    sh = dpg_.get_viewport_height() or 1080
    window_width, window_height = 300, 50
    pos_x = (sw - window_width) // 2
    pos_y = (sh - window_height) // 2
    if dpg_.does_item_exist('Message'):
        dpg_.delete_item('Message')
    with dpg_.window(label="Сообщение", width=window_width,
                     height=window_height, pos=(pos_x, pos_y),
                     tag='Message', modal=True):
        dpg_.add_text(mes_str)
        dpg_.add_button(label='OK',
                        callback=lambda: dpg_.delete_item('Message'))


# ===========================================================================
# Хелперы выбора МСК
# ===========================================================================
def get_checked_msks(dpg_):
    if not dpg_.does_item_exist('msk_list_container'):
        return []
    info = dpg_.get_item_user_data('msk_list_container') or {}
    result = []
    for i in range(info.get('count', 0)):
        tag = f'msk_row_{i}'
        if dpg_.does_item_exist(tag) and dpg_.get_value(tag):
            raw = info['raw'][i]
            result.append(raw['name'] if isinstance(raw, dict) else str(raw))
    return result


def _is_single_mode(dpg_):
    if dpg_.does_item_exist('multi_select_mode'):
        return not bool(dpg_.get_value('multi_select_mode'))
    return False

def _get_single_selected_msk(dpg_):
    return MSKState.selected_single

def _get_single_selected_msk_1(dpg_):
    if not dpg_.does_item_exist('msk_select'):
        return None
    val = dpg_.get_value('msk_select')
    if not val:
        return None
    try:
        if val in MSKState.display_now:
            idx = MSKState.display_now.index(val)
            if 0 <= idx < len(MSKState.raw_now):
                raw = MSKState.raw_now[idx]
                return raw['name'] if isinstance(raw, dict) else str(raw)
    except (ValueError, IndexError):
        pass
    return None

def _deselect_other_rows(dpg_, keep_sender):
    """Снять выделение со всех строк таблицы, кроме keep_sender (одиночный режим)."""
    info = dpg_.get_item_user_data('msk_list_container') or {}
    for i in range(info.get('count', 0)):
        tag = f'msk_row_{i}'
        if tag != keep_sender and dpg_.does_item_exist(tag):
            try:
                dpg_.set_value(tag, False)
            except Exception:
                pass


def _restore_single_selection(dpg_, display_items, raw_msks):
    """После перестройки таблицы восстановить выделение (если МСК ещё в списке)."""
    sel = MSKState.selected_single
    if not sel:
        return
    for i, raw in enumerate(raw_msks):
        name = raw.get('name') if isinstance(raw, dict) else str(raw)
        if name == sel:
            tag = f'msk_row_{i}'
            if dpg_.does_item_exist(tag):
                try:
                    dpg_.set_value(tag, True)
                except Exception:
                    pass
            return
    # Выбранной МСК больше нет в списке — сбрасываем
    MSKState.selected_single = None


# ===========================================================================
# Информация о МСК
# ===========================================================================
def _show_msk_info(dpg_, msk_info):
    if not dpg_.does_item_exist('msk_info_area'):
        return
    dpg_.delete_item('msk_info_area', children_only=True)
    if isinstance(msk_info, dict):
        msk_name = msk_info.get('name', '')
        date_str = msk_info.get('date', '') or '—'
        started = msk_info.get('count', '')
    else:
        msk_name = str(msk_info)
        date_str = '—'
        started = ''
    with dpg_.group(parent='msk_info_area'):
        with dpg_.group(horizontal=True):
            dpg_.add_text("МСК:", color=(200, 200, 200))
            dpg_.add_text(str(msk_name), color=(255, 255, 150))
        with dpg_.group(horizontal=True):
            dpg_.add_text("Дата запуска:", color=(200, 200, 200))
            dpg_.add_text(str(date_str))
        with dpg_.group(horizontal=True):
            dpg_.add_text("Запущено:", color=(200, 200, 200))
            dpg_.add_text(f"{started} шт.")
        try:
            fp_count = get_msk_plating_count(str(msk_name))
            with dpg_.group(horizontal=True):
                dpg_.add_text("Замеров FP в БД:", color=(200, 200, 200))
                dpg_.add_text(str(fp_count))
        except Exception as e:
            print(f'[_show_msk_info] fp count error: {e}')
        try:
            in_set = str(msk_name) in Statistik.Data.Data.get_msk_list()
            status_text = "добавлена" if in_set else "не добавлена"
            color = (150, 255, 150) if in_set else (255, 180, 150)
            with dpg_.group(horizontal=True):
                dpg_.add_text("Статус:", color=(200, 200, 200))
                dpg_.add_text(status_text, color=color)
        except Exception as e:
            print(f'[_show_msk_info] status error: {e}')


# ===========================================================================
# Прочее
# ===========================================================================
def print_date_time(sender, data):
    print(data)