"""Список МСК, поиск, загрузка/удаление МСК, номенклатура."""
import pandas as pd
import dearpygui.dearpygui as dpg
from datetime import datetime

import Statistik.Data
from Statistik.Operations import (
    get_msk,
    get_resonator_nominals_list,
    get_resonator_nom_list,
    load_data,
    load_psi_data,
    delete_msk_data,
    test_msk_plating_data,
    get_msk_plating_count,
    get_msk_psi_count,
    get_spc_norms,
)


from .dashboard_norms import update_spc_norm
from .dashboard_results import update_result, update_msk_result
from .dashboard_slots import (
    repaint_signal_window, repaint_action_window, set_id_count,
)
from .dashboard_helpers import (
    MSKState, show_indicator, hide_indicator, show_message,
    _get_single_selected_msk, _is_single_mode, get_checked_msks,
    _show_msk_info,
    _deselect_other_rows, _restore_single_selection,     # ← НОВЫЕ
)

# ===========================================================================
# Построение / поиск списка МСК
# ===========================================================================
def rebuild_msk_list(dpg_, display_items, raw_msks):
    MSKState.display_now = list(display_items)
    MSKState.raw_now = list(raw_msks)

    prev = dpg_.get_item_user_data('msk_list_container') or {}
    for tag in prev.get('popup_tags', []):
        if dpg_.does_item_exist(tag):
            try:
                dpg_.delete_item(tag)
            except Exception as e:
                print(f'[rebuild_msk_list] delete popup {tag}: {e}')

    if dpg_.does_item_exist('msk_list_table'):
        dpg_.delete_item('msk_list_table')

    if dpg_.does_item_exist('msk_info_area'):
        dpg_.delete_item('msk_info_area', children_only=True)
        with dpg_.group(parent='msk_info_area'):
            dpg_.add_text("Клик по МСК - информация о ней",
                          color=(150, 150, 150))

    popup_tags = []
    if dpg_.does_item_exist('msk_list_container'):
        with dpg_.table(parent='msk_list_container', header_row=False,
                        tag='msk_list_table', scrollY=True, height=-1):
            dpg_.add_table_column(label='МСК', width_stretch=True,
                                  init_width_or_weight=1.0)
            for i, (disp, raw) in enumerate(zip(display_items, raw_msks)):
                row_tag = f'msk_row_{i}'
                popup_tag = f'msk_ctx_{i}'
                popup_tags.append(popup_tag)
                with dpg_.table_row():
                    dpg_.add_selectable(label=disp, tag=row_tag,
                                        user_data=raw,
                                        callback=on_msk_row_click)
                    with dpg_.popup(row_tag,
                                    mousebutton=dpg_.mvMouseButton_Right,
                                    tag=popup_tag, min_size=[200, 30]):
                        dpg_.add_menu_item(label="Добавить выбранные",
                                           callback=load_msk_dat,
                                           user_data=dpg_)
                        dpg_.add_menu_item(label="Удалить выбранные",
                                           callback=del_msk_from_list,
                                           user_data=dpg_)

    if dpg_.does_item_exist('msk_list_container'):
        dpg_.set_item_user_data('msk_list_container', {
            'count': len(display_items),
            'raw': list(raw_msks),
            'popup_tags': popup_tags,
        })

    # Восстановить одиночное выделение после перестройки
    if _is_single_mode(dpg_):
        _restore_single_selection(dpg_, display_items, raw_msks)


def on_msk_row_click(sender, app_data, user_data):
    is_single = _is_single_mode(dpg)

    if is_single:
        # Клик по уже выбранной строке → DPG снимает галочку.
        # В одиночном режиме принудительно возвращаем True и ничего больше не делаем.
        if not app_data:
            dpg.set_value(sender, True)
            return

        # Снять выделение со всех остальных строк
        _deselect_other_rows(dpg, sender)

        # Запомнить выбор
        if isinstance(user_data, dict):
            MSKState.selected_single = user_data.get('name', '')
        else:
            MSKState.selected_single = str(user_data)

        # Запустить сканирование замеров и показать информацию
        # (test_msk_measure_types внутри вызывает _show_msk_info)
        test_msk_measure_types(sender, True, dpg)
        return

    # Множественный режим — прежнее поведение
    if not app_data:
        return
    if isinstance(user_data, dict):
        _show_msk_info(dpg, user_data)
    else:
        _show_msk_info(dpg, {'name': str(user_data),
                             'date': '', 'count': ''})




def _on_msk_search(sender, app_data, user_data):
    dpg_ = user_data
    q = (dpg_.get_value('msk_search') or '').strip().lower()
    if not q:
        rebuild_msk_list(dpg_, MSKState.all_display, MSKState.all_raw)
        return
    di, ri = [], []
    for d, r in zip(MSKState.all_display, MSKState.all_raw):
        name = r.get('name', '') if isinstance(r, dict) else str(r)
        if q in name.lower() or q in str(d).lower():
            di.append(d)
            ri.append(r)
    rebuild_msk_list(dpg_, di, ri)

def _on_nom_search(sender, app_data, user_data):
    """Фильтр combo spc_select по подстроке (как в редакторе спецификаций)."""
    dpg_ = user_data
    q = (dpg_.get_value('nom_search') or '').strip().lower()

    if not dpg_.does_item_exist('spc_select'):
        return

    if not q:
        dpg_.configure_item('spc_select', items=MSKState.nom_all)
        return

    filtered = [n for n in MSKState.nom_all
                if q in str(n).lower()]
    dpg_.configure_item('spc_select', items=filtered)
    if filtered:
        dpg_.set_value('spc_select', filtered[0])

def _on_selection_mode_change(sender, app_data, user_data):
    dpg_ = user_data
    is_multi = bool(app_data)

    if is_multi:
        # Уходя в множественный режим — сбрасываем одиночное выделение
        MSKState.selected_single = None

    # Снять галочки со всех строк при смене режима
    info = dpg_.get_item_user_data('msk_list_container') or {}
    for i in range(info.get('count', 0)):
        tag = f'msk_row_{i}'
        if dpg_.does_item_exist(tag):
            try:
                dpg_.set_value(tag, False)
            except Exception:
                pass

    if dpg_.does_item_exist('signal_header'):
        try:
            dpg_.set_value('signal_header', is_multi)
        except Exception as e:
            print(f'[_on_selection_mode_change] signal_header: {e}')
    if dpg_.does_item_exist('msk_info_header'):
        try:
            dpg_.set_value('msk_info_header', not is_multi)
        except Exception as e:
            print(f'[_on_selection_mode_change] msk_info_header: {e}')



# ===========================================================================
# Номенклатура
# ===========================================================================
def get_res_nom(sender, data, dpg_):
    res_list = get_resonator_nominals_list(data)
    if len(res_list) > 0:
        dpg_.configure_item('nominal_select', items=res_list,
                            default_value=res_list[0])
        nom_list = get_resonator_nom_list(resonator_type=data,
                                          resonator_nominal=res_list[0])
        if len(nom_list) > 0:
            MSKState.nom_all = list(nom_list)                # ← НОВОЕ
            dpg_.configure_item('spc_select', items=nom_list,
                                default_value=nom_list[0])
            get_msk_list(None, nom_list[0], dpg_)


def get_res_nom1(sender, data, dpg_):
    tt = dpg_.get_value('type_select')
    if tt is not None:
        nom_list = get_resonator_nom_list(resonator_type=tt,
                                          resonator_nominal=data)
    else:
        nom_list = get_resonator_nom_list(resonator_nominal=data)
    if len(nom_list) > 0:
        MSKState.nom_all = list(nom_list)                    # ← НОВОЕ
        dpg_.configure_item('spc_select', items=nom_list,
                            default_value=nom_list[0])
        get_msk_list(None, nom_list[0], dpg_)





# ===========================================================================
# Загрузка списка МСК из БД
# ===========================================================================
def get_msk_list(sender, data, dpg_):
    if not data:
        MSKState.all_display, MSKState.all_raw = [], []
        rebuild_msk_list(dpg_, [], [])
        return
    try:
        msk_df = get_msk(data)
    except Exception as e:
        print(f'[get_msk_list] error get_msk({data!r}): {e}')
        MSKState.all_display, MSKState.all_raw = [], []
        rebuild_msk_list(dpg_, [], [])
        return

    display_items, raw_msks = [], []
    for index, row in msk_df.iterrows():
        msk_name = str(row['мскРеал'])
        date_str = '00-00-0000'
        raw_date = row.get('дата запуска') if hasattr(row, 'get') else None
        try:
            if raw_date is not None and pd.notna(raw_date):
                date_obj = datetime.strptime(str(raw_date),
                                             "%Y-%m-%d %H:%M:%S.%f")
                date_str = date_obj.strftime("%d-%m-%Y")
        except (ValueError, TypeError):
            pass
        display_items.append(
            f"{index}. {msk_name} ({date_str}) - {row['запущено шт']} шт.")
        raw_msks.append({'name': msk_name, 'date': date_str,
                         'count': row['запущено шт']})
        MSKState.full_info[msk_name] = raw_msks[-1]

    MSKState.all_display = display_items
    MSKState.all_raw = raw_msks

    if dpg_.does_item_exist('msk_search'):
        q = (dpg_.get_value('msk_search') or '').strip()
        if q:
            _on_msk_search(None, q, dpg_)
            try:
                update_spc_norm(dpg_)
            except Exception as e:
                print(f'[get_msk_list] update_spc_norm: {e}')
            return

    rebuild_msk_list(dpg_, display_items, raw_msks)
    try:
        update_spc_norm(dpg_)
    except Exception as e:
        print(f'[get_msk_list] update_spc_norm: {e}')


def show_hide_msk_list(sender, data, dpg_):
    if data == 'Список добавленных МСК':
        if dpg_.does_item_exist('add_data_button'):
            dpg_.configure_item('add_data_button', enabled=False)
        if dpg_.does_item_exist('del_data_button'):
            dpg_.configure_item('del_data_button', enabled=True)
        msk_data = Statistik.Data.Data.get_msk_list()
        display_items, raw_msks = [], []
        for i, key in enumerate(msk_data.keys(), start=1):
            display_items.append(f"{i}. {key}")
            raw_msks.append(MSKState.full_info.get(key,
                                                   {'name': key, 'date': '',
                                                    'count': ''}))
        MSKState.all_display = display_items
        MSKState.all_raw = raw_msks
        rebuild_msk_list(dpg_, display_items, raw_msks)
    else:
        if dpg_.does_item_exist('add_data_button'):
            dpg_.configure_item('add_data_button', enabled=True)
        if dpg_.does_item_exist('del_data_button'):
            dpg_.configure_item('del_data_button', enabled=False)
        get_msk_list(sender, dpg_.get_value('spc_select'), dpg_)


# ===========================================================================
# Добавление / удаление МСК
# ===========================================================================
def load_msk_dat(sender, data, dpg_):
    if dpg_.get_value('radio_group_list_view') == 'Список добавленных МСК':
        show_message('Переключитесь на Список МСК для добавления', dpg_)
        return

    if _is_single_mode(dpg_):
        msk = _get_single_selected_msk(dpg_)
        if not msk:
            show_message('Не выбрана МСК', dpg_)
            return
        checked = [msk]
    else:
        checked = get_checked_msks(dpg_)
        if not checked:
            show_message('Не выбрано ни одной МСК', dpg_)
            return

    show_indicator(dpg_)
    try:
        try:
            get_spc_norms(dpg_.get_value('spc_select'))
        except Exception as e:
            print(f'[load_msk_dat] get_spc_norms: {e}')
        added = 0
        for msk in checked:
            if msk in Statistik.Data.Data.get_msk_list():
                continue
            try:
                active_slot_list = Statistik.Data.Data.get_active_data()
                current_slot_list = active_slot_list.copy()
                current_slot_list['Mes_ID'] = 0
                current_slot_list['Use'] = True
                load_data(msk, current_slot_list)
                added += 1
            except Exception as e:
                print(f'[load_msk_dat] MSK {msk}: {e}')

        if added == 0:
            show_message('Все выбранные МСК уже добавлены', dpg_)
            return

        # Набор МСК изменился. Помечаем данные как «требующие
        # перезагрузки»: следующий NL-запрос ассистента один раз
        # вызовет _reload_current_msks() и синхронизирует data_full
        # с актуальной конфигурацией слотов.
        # В остальных случаях (вопрос без изменения набора МСК)
        # reload больше не выполняется — UI не блокируется.
        Statistik.Data.Data.dirty = True

        if not _is_single_mode(dpg_):
            info = dpg_.get_item_user_data('msk_list_container') or {}
            for i in range(info.get('count', 0)):
                tag = f'msk_row_{i}'
                if dpg_.does_item_exist(tag):
                    dpg_.set_value(tag, False)

        repaint_signal_window(None, None, dpg_)
        repaint_action_window(None, None, dpg_)
        update_result(dpg_)
        update_msk_result(dpg_)
    finally:
        hide_indicator(dpg_)

def load_msk_dat_1(sender, data, dpg_):
    if dpg_.get_value('radio_group_list_view') == 'Список добавленных МСК':
        show_message('Переключитесь на Список МСК для добавления', dpg_)
        return

    if _is_single_mode(dpg_):
        msk = _get_single_selected_msk(dpg_)
        if not msk:
            show_message('Не выбрана МСК', dpg_)
            return
        checked = [msk]
    else:
        checked = get_checked_msks(dpg_)
        if not checked:
            show_message('Не выбрано ни одной МСК', dpg_)
            return

    show_indicator(dpg_)
    try:
        try:
            get_spc_norms(dpg_.get_value('spc_select'))
        except Exception as e:
            print(f'[load_msk_dat] get_spc_norms: {e}')
        added = 0
        for msk in checked:
            if msk in Statistik.Data.Data.get_msk_list():
                continue
            try:
                active_slot_list = Statistik.Data.Data.get_active_data()
                current_slot_list = active_slot_list.copy()
                current_slot_list['Mes_ID'] = 0
                current_slot_list['Use'] = True
                load_data(msk, current_slot_list)
                added += 1
            except Exception as e:
                print(f'[load_msk_dat] MSK {msk}: {e}')

        if added == 0:
            show_message('Все выбранные МСК уже добавлены', dpg_)
            return

        if not _is_single_mode(dpg_):
            info = dpg_.get_item_user_data('msk_list_container') or {}
            for i in range(info.get('count', 0)):
                tag = f'msk_row_{i}'
                if dpg_.does_item_exist(tag):
                    dpg_.set_value(tag, False)

        repaint_signal_window(None, None, dpg_)
        repaint_action_window(None, None, dpg_)
        update_result(dpg_)
        update_msk_result(dpg_)
    finally:
        hide_indicator(dpg_)

def del_msk_from_list(sender, data, dpg_):
    if dpg_.get_value('radio_group_list_view') != 'Список добавленных МСК':
        show_message('Удаление доступно только в Список добавленных МСК', dpg_)
        return

    if _is_single_mode(dpg_):
        msk = _get_single_selected_msk(dpg_)
        if not msk:
            show_message('Не выбрана МСК', dpg_)
            return
        checked = [msk]
    else:
        checked = get_checked_msks(dpg_)
        if not checked:
            show_message('Не выбрано ни одной МСК для удаления', dpg_)
            return

    show_indicator(dpg_)
    try:
        msk_data = Statistik.Data.Data.get_msk_list()
        removed = 0
        for msk in checked:
            if msk not in msk_data:
                continue
            try:
                delete_msk_data(msk)
                Statistik.Data.Data.del_msk_from_list(msk)
                removed += 1
            except Exception as e:
                print(f'[del_msk_from_list] MSK {msk}: {e}')
        if removed == 0:
            show_message('Не удалось удалить ни одной МСК', dpg_)
            return

        # Набор МСК изменился — данные в data_full потенциально
        # не соответствуют актуальному набору. Перезагрузка
        # произойдёт при следующем NL-запросе.
        Statistik.Data.Data.dirty = True

        show_hide_msk_list(sender, 'Список добавленных МСК', dpg_)
        repaint_action_window(sender, None, dpg_)
        update_result(dpg_)
        update_msk_result(dpg_)
    finally:
        hide_indicator(dpg_)

def del_msk_from_list_1(sender, data, dpg_):
    if dpg_.get_value('radio_group_list_view') != 'Список добавленных МСК':
        show_message('Удаление доступно только в Список добавленных МСК', dpg_)
        return

    if _is_single_mode(dpg_):
        msk = _get_single_selected_msk(dpg_)
        if not msk:
            show_message('Не выбрана МСК', dpg_)
            return
        checked = [msk]
    else:
        checked = get_checked_msks(dpg_)
        if not checked:
            show_message('Не выбрано ни одной МСК для удаления', dpg_)
            return

    show_indicator(dpg_)
    try:
        msk_data = Statistik.Data.Data.get_msk_list()
        removed = 0
        for msk in checked:
            if msk not in msk_data:
                continue
            try:
                delete_msk_data(msk)
                Statistik.Data.Data.del_msk_from_list(msk)
                removed += 1
            except Exception as e:
                print(f'[del_msk_from_list] MSK {msk}: {e}')
        if removed == 0:
            show_message('Не удалось удалить ни одной МСК', dpg_)
            return
        show_hide_msk_list(sender, 'Список добавленных МСК', dpg_)
        repaint_action_window(sender, None, dpg_)
        update_result(dpg_)
        update_msk_result(dpg_)
    finally:
        hide_indicator(dpg_)


# ===========================================================================
# Клик по одиночному listbox + combo Measure_ID
# ===========================================================================
def test_msk_measure_types(sender, data, dpg_):
    msk = _get_single_selected_msk(dpg_)
    if not msk:
        return
    info = MSKState.full_info.get(msk, {'name': msk, 'date': '', 'count': ''})
    _show_msk_info(dpg_, info)

    show_indicator(dpg_)
    try:
        radio_data = dpg_.get_value('radio_group_list_view')
        if radio_data != 'Список добавленных МСК':
            mes_types, all_list_mes = test_msk_plating_data(msk)
            data_types = Statistik.Data.Data.get_measure_type_list()
            active_slot_list = Statistik.Data.Data.get_active_data()
            for index, row in active_slot_list.iterrows():
                if row['Value'] != 6:
                    mes_list_current = all_list_mes[
                        all_list_mes['Measure_Type'] == row['Value']]
                    list_temp = mes_list_current['Measure_ID'].tolist()
                    list_temp.append('все')
                    dpg_.configure_item(
                        'combo' + str(row['Name']) + '_check_box',
                        items=list_temp, default_value='все')
                    item_name = 'data' + str(row['Name']) + '_check_box'
                    item_label = dpg_.get_item_label(item_name)
                    dpg_.configure_item(
                        item_name, default_value=item_label in mes_types)
                    count = get_msk_plating_count(msk, row['Value'])
                    dpg_.set_value(
                        'text' + str(row['Name']) + '_check_box',
                        str(count) + ' шт.')
                else:
                    mes_list_current = load_psi_data(msk)
                    if len(mes_list_current) > 0:
                        max_id = max(mes_list_current)
                        if not Statistik.Data.Data.get_spc_norm_status():
                            get_spc_norms(spc=dpg_.get_value('spc_select'),
                                          measure_id=max_id)
                    else:
                        max_id = 'все'
                    mes_list_current.append("все")
                    for item in dpg_.get_all_items():
                        alias = dpg_.get_item_alias(item)
                        if alias == 'id_info':
                            dpg_.delete_item(alias)
                    if len(mes_list_current) > 1:
                        dpg_.configure_item(
                            'combo' + str(row['Name']) + '_check_box',
                            items=mes_list_current,
                            default_value=str(max_id))
                        item_name = 'data' + str(row['Name']) + '_check_box'
                        dpg_.configure_item(item_name, default_value=True)
                        count = get_msk_psi_count(msk, max_id)
                        dpg_.set_value(
                            'text' + str(row['Name']) + '_check_box',
                            str(count) + ' шт.')
                        set_id_count('combo' + str(row['Name']) + '_check_box',
                                     str(max_id), dpg_)
    finally:
        hide_indicator(dpg_)

# ===========================================================================
# Массовый выбор: последние N МСК
# ===========================================================================
def _msk_date_key(pair):
    """Ключ сортировки: (год, месяц, день, индекс).

    Если дата отсутствует или '00-00-0000' - падаем на порядок в списке.
    """
    idx, raw = pair
    if isinstance(raw, dict):
        d = (raw.get('date') or '').strip()
        if d and d != '00-00-0000':
            try:
                dd, mm, yy = d.split('-')
                return (int(yy), int(mm), int(dd), idx)
            except (ValueError, AttributeError):
                pass
    return (0, 0, 0, idx)


def select_last_n_msks(sender, data, dpg_):
    """Отметить N последних МСК (по дате запуска) в видимом списке."""
    if not dpg_.does_item_exist('last_n_msk'):
        return

    # --- парсим N ---
    try:
        n = int((dpg_.get_value('last_n_msk') or '').strip())
    except (TypeError, ValueError):
        show_message('N: введите целое число', dpg_)
        return

    single = _is_single_mode(dpg_)
    if single:
        n = 1                      # в одиночном режиме - только 1
    elif n <= 0:
        show_message('N должно быть больше 0', dpg_)
        return

    raw_list = MSKState.raw_now
    if not raw_list:
        show_message('Список МСК пуст', dpg_)
        return

    n = min(n, len(raw_list))

    # --- индексы последних N ---
    indexed = list(enumerate(raw_list))
    indexed.sort(key=_msk_date_key)
    last_indices = set(i for i, _ in indexed[-n:])

    info = dpg_.get_item_user_data('msk_list_container') or {}
    count = info.get('count', 0)

    # --- выставляем галочки ---
    if single:
        last_idx = indexed[-1][0]
        for i in range(count):
            tag = f'msk_row_{i}'
            if dpg_.does_item_exist(tag):
                dpg_.set_value(tag, i == last_idx)
        # эмулируем клик, чтобы single-логика (info area, test_msk)
        # сработала как при обычном клике
        row_tag = f'msk_row_{last_idx}'
        if dpg_.does_item_exist(row_tag):
            try:
                on_msk_row_click(row_tag, True, raw_list[last_idx])
            except Exception as e:
                print(f'[select_last_n_msks] single click: {e}')
    else:
        for i in range(count):
            tag = f'msk_row_{i}'
            if dpg_.does_item_exist(tag):
                dpg_.set_value(tag, i in last_indices)

    print(f'[select_last_n_msks] выбрано {len(last_indices)} '
          f'из {count} (single={single})')


def clear_msk_selection(sender, data, dpg_):
    """Снять все галочки в списке МСК."""
    info = dpg_.get_item_user_data('msk_list_container') or {}
    for i in range(info.get('count', 0)):
        tag = f'msk_row_{i}'
        if dpg_.does_item_exist(tag):
            try:
                dpg_.set_value(tag, False)
            except Exception:
                pass
    MSKState.selected_single = None