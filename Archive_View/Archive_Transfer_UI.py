"""UI: переключение источника, диалоги переноса, журнал операций с откатом."""
import pandas as pd
import dearpygui.dearpygui as dpg

from .Archive_Constants import WINDOW_TAG, _source_state
from .Archive_ActionsLog import (
    read_log, ensure_log_table, ACTION_ARCHIVE, ACTION_OVERWRITE,
)
from .Archive_Transfer import (
    overwrite_temp_to_main, archive_main_to_archive, restore_archive,
)

DIALOG_OVERWRITE = 'archive_overwrite_dialog'
DIALOG_ARCHIVE   = 'archive_archive_dialog'
LOG_WINDOW       = 'archive_actions_log_window'
LOG_TABLE_GROUP  = 'archive_actions_log_group'

SOURCES = [
    ('Основная',   'psidata',           'psidatatemp'),
    ('Временная',  'psidata_temporary', 'psidatatemp_temporary'),
    ('Архивная',   'psidata_archive',   'psidatatemp_archive'),
]


def _label_for(table_main: str) -> str:
    for label, main, _ in SOURCES:
        if main == table_main:
            return label
    return 'Основная'


def _refresh_main_view():
    try:
        from .Archive_Cascade import _bootstrap
        _bootstrap()
    except Exception as e:
        print(f"[Archive] Обновление после переноса: {e}")


def _get_current_msk() -> str:
    v = dpg.get_value('archive_msk_combo') if dpg.does_item_exist(
        'archive_msk_combo') else ''
    return '' if not v or v == 'Все МСК' else str(v)


def _get_current_mid():
    df = dpg.get_item_user_data(WINDOW_TAG)
    if df is not None and not df.empty and 'Measure_ID' in df.columns:
        uniq = df['Measure_ID'].dropna().unique()
        if len(uniq) == 1:
            return int(uniq[0])
    return None


# -------------------------------------------------- диалог: temp → main
def open_overwrite_dialog():
    if dpg.does_item_exist(DIALOG_OVERWRITE):
        dpg.delete_item(DIALOG_OVERWRITE)

    msk = _get_current_msk()
    mid = _get_current_mid()

    with dpg.window(label='Перезапись временной в основную',
                    tag=DIALOG_OVERWRITE, modal=True,
                    width=520, height=260, no_collapse=True):
        dpg.add_text('MSK и Measure_ID определяют, какой замер заменяется.')
        dpg.add_separator()
        dpg.add_input_text(label='МСК', tag='ow_msk', width=-1,
                           default_value=msk)
        dpg.add_input_int(label='Measure_ID', tag='ow_mid', width=150,
                          default_value=mid or 0)
        dpg.add_spacer(height=8)
        dpg.add_text('', tag='ow_status', color=(255, 180, 100), wrap=500)
        dpg.add_spacer(height=10)
        with dpg.group(horizontal=True):
            dpg.add_button(label='Перезаписать', width=140,
                           callback=lambda s, a: _do_overwrite())
            dpg.add_button(label='Отмена', width=140,
                           callback=lambda s, a: dpg.delete_item(DIALOG_OVERWRITE))


def _do_overwrite():
    msk = (dpg.get_value('ow_msk') or '').strip()
    try:
        mid = int(dpg.get_value('ow_mid'))
    except (TypeError, ValueError):
        dpg.set_value('ow_status', 'Некорректный Measure_ID')
        return
    if not msk or mid <= 0:
        dpg.set_value('ow_status', 'Заполните МСК и Measure_ID')
        return

    res = overwrite_temp_to_main(msk, mid)
    if not res['ok']:
        dpg.set_value('ow_status', f"Ошибка: {res.get('error', '?')}")
        return
    dpg.set_value(
        'ow_status',
        f"Готово. main: было {res['main_replaced']} → стало "
        f"{res['main_inserted']}; temp: было {res['temp_replaced']} → "
        f"{res['temp_inserted']}. Журнал id={res['log_id']}")
    _refresh_main_view()


# -------------------------------------------------- диалог: main → archive
def open_archive_dialog():
    if dpg.does_item_exist(DIALOG_ARCHIVE):
        dpg.delete_item(DIALOG_ARCHIVE)

    msk = _get_current_msk()

    with dpg.window(label='Архивирование (основная -> архив)',
                    tag=DIALOG_ARCHIVE, modal=True,
                    width=580, height=460, no_collapse=True):
        dpg.add_text('Данные сначала пишутся в архив и журнал отката, '
                     'и только потом удаляются из основной.',
                     color=(150, 200, 255), wrap=540)
        dpg.add_separator()
        dpg.add_input_text(label='МСК', tag='ar_msk', width=-1,
                           default_value=msk)
        dpg.add_radio_button(
            ['Один Measure_ID', 'Диапазон Measure_ID'],
            tag='ar_mode', horizontal=True,
            default_value='Один Measure_ID')
        with dpg.group(horizontal=True):
            dpg.add_input_int(label='Measure_ID', tag='ar_mid',
                              width=140, default_value=0)
        with dpg.group(horizontal=True, tag='ar_range_group'):
            dpg.add_input_int(label='от', tag='ar_mid_from',
                              width=140, default_value=0)
            dpg.add_input_int(label='до', tag='ar_mid_to',
                              width=140, default_value=0)
        dpg.add_spacer(height=6)
        dpg.add_text('Фильтр по N (опционально):')
        with dpg.group(horizontal=True):
            dpg.add_input_text(label='от N', tag='ar_n_from', width=180)
            dpg.add_input_text(label='до N', tag='ar_n_to', width=180)
        dpg.add_spacer(height=8)
        dpg.add_text('', tag='ar_status', color=(255, 180, 100), wrap=540)
        dpg.add_spacer(height=10)
        with dpg.group(horizontal=True):
            dpg.add_button(label='Архивировать', width=160,
                           callback=lambda s, a: _do_archive())
            dpg.add_button(label='Отмена', width=140,
                           callback=lambda s, a: dpg.delete_item(DIALOG_ARCHIVE))


def _do_archive():
    msk = (dpg.get_value('ar_msk') or '').strip()
    mode = dpg.get_value('ar_mode')
    kw = dict(msk=msk)

    if mode == 'Один Measure_ID':
        try:
            mid = int(dpg.get_value('ar_mid'))
        except (TypeError, ValueError):
            dpg.set_value('ar_status', 'Некорректный Measure_ID')
            return
        if mid <= 0:
            dpg.set_value('ar_status', 'Введите Measure_ID > 0')
            return
        kw['measure_id'] = mid
    else:
        try:
            m_from = int(dpg.get_value('ar_mid_from'))
            m_to   = int(dpg.get_value('ar_mid_to'))
        except (TypeError, ValueError):
            dpg.set_value('ar_status', 'Некорректный диапазон')
            return
        if m_from <= 0 or m_to <= 0 or m_from > m_to:
            dpg.set_value('ar_status', 'Диапазон: 0 < от ≤ до')
            return
        kw['measure_id_from'] = m_from
        kw['measure_id_to']   = m_to

    n_from = (dpg.get_value('ar_n_from') or '').strip() or None
    n_to   = (dpg.get_value('ar_n_to') or '').strip() or None
    if n_from: kw['n_from'] = n_from
    if n_to:   kw['n_to']   = n_to

    if not msk:
        dpg.set_value('ar_status', 'Введите МСК')
        return

    res = archive_main_to_archive(**kw)
    if not res['ok']:
        dpg.set_value('ar_status', f"Ошибка: {res.get('error', '?')}")
        return
    dpg.set_value(
        'ar_status',
        f"Готово. В архив: main {res['archived_main']}, "
        f"temp {res['archived_temp']}. Удалено из основной: "
        f"main {res['deleted_main']}, temp {res['deleted_temp']}. "
        f"Журнал id={res['log_id']}")
    _refresh_main_view()


# -------------------------------------------------- журнал
def open_actions_log_window():
    if dpg.does_item_exist(LOG_WINDOW):
        dpg.delete_item(LOG_WINDOW)

    ensure_log_table()

    with dpg.window(label='Журнал операций с таблицами',
                    tag=LOG_WINDOW, width=1180, height=680):
        with dpg.group(horizontal=True):
            dpg.add_text('МСК:')
            dpg.add_input_text(tag='log_filter_msk', width=150)
            dpg.add_text('Measure_ID:')
            dpg.add_input_text(tag='log_filter_mid', width=100)
            dpg.add_checkbox(label='Только активные',
                             tag='log_filter_active',
                             default_value=True)
            dpg.add_button(label='Обновить',
                           callback=lambda s, a: _refresh_log_table())
        dpg.add_separator()
        dpg.add_text('', tag='log_status_text', color=(150, 200, 255))
        dpg.add_separator()
        with dpg.group(tag=LOG_TABLE_GROUP):
            pass

    _refresh_log_table()


def _refresh_log_table():
    if not dpg.does_item_exist(LOG_TABLE_GROUP):
        return
    for ch in dpg.get_item_children(LOG_TABLE_GROUP, 1) or []:
        dpg.delete_item(ch)

    msk_f = (dpg.get_value('log_filter_msk')
             if dpg.does_item_exist('log_filter_msk') else '')
    mid_f = (dpg.get_value('log_filter_mid')
             if dpg.does_item_exist('log_filter_mid') else '')
    try:
        mid = int(str(mid_f).strip()) if str(mid_f).strip() else None
    except ValueError:
        mid = None
    only_active = (dpg.get_value('log_filter_active')
                   if dpg.does_item_exist('log_filter_active') else True)

    df = read_log(measure_id=mid, msk=str(msk_f).strip() or None,
                  only_active=only_active)

    if dpg.does_item_exist('log_status_text'):
        dpg.set_value('log_status_text',
                      f'Записей: {len(df)}' if not df.empty else 'Записей нет')

    if df.empty:
        return

    with dpg.table(parent=LOG_TABLE_GROUP, header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True,
                   resizable=True, scrollY=True, height=550,
                   policy=dpg.mvTable_SizingFixedFit):
        for lbl, w in [('ID', 60), ('Дата', 140), ('Оператор', 110),
                       ('Действие', 90), ('МСК', 120), ('Measure_ID', 90),
                       ('Диапазон', 130), ('Строк', 80),
                       ('Статус', 150), ('', 130)]:
            dpg.add_table_column(label=lbl, width_fixed=True,
                                 init_width_or_weight=w)

        for _, r in df.iterrows():
            with dpg.table_row():
                dpg.add_text(str(int(r['id'])))
                dt_val = r['action_date']
                dpg.add_text(dt_val.strftime('%Y-%m-%d %H:%M:%S')
                             if pd.notna(dt_val) and hasattr(dt_val, 'strftime')
                             else '')
                dpg.add_text(str(r['operator'] or ''))
                dpg.add_text(str(r['action'] or ''))
                dpg.add_text(str(r['msk'] or ''))
                mid_v = r['measure_id']
                dpg.add_text(str(int(mid_v)) if pd.notna(mid_v) else '')
                if pd.notna(r['measure_id_from']) and pd.notna(r['measure_id_to']):
                    dpg.add_text(f"{int(r['measure_id_from'])}–"
                                 f"{int(r['measure_id_to'])}")
                else:
                    dpg.add_text('')
                dpg.add_text(f"{int(r['rows_main'])}/"
                             f"{int(r['rows_temp'])}")
                st = str(r['status'] or '')
                if r['restored']:
                    dpg.add_text('восстановлен', color=(140, 220, 140))
                elif st == 'completed':
                    dpg.add_text(st, color=(150, 220, 150))
                elif st.startswith('archived_pending'):
                    dpg.add_text(st, color=(255, 180, 100))
                else:
                    dpg.add_text(st, color=(220, 180, 180))

                lid = int(r['id'])
                action = str(r['action'] or '')
                if (not r['restored']) and action == ACTION_ARCHIVE and st in (
                        'completed', 'archived_pending_delete'):
                    dpg.add_button(
                        label='Откатить',
                        user_data=lid,
                        callback=_on_restore_action)
                else:
                    dpg.add_text('')


def _on_restore_action(sender=None, app_data=None, user_data=None):
    log_id = user_data
    if log_id is None:
        dpg.set_value('log_status_text', 'Не указан ID журнала')
        return
    res = restore_archive(log_id)
    if not res['ok']:
        dpg.set_value('log_status_text',
                      f"Ошибка отката: {res.get('error', '?')}")
        return
    dpg.set_value('log_status_text',
                  f"Откат выполнен: восстановлено main={res['restored_main']}, "
                  f"temp={res['restored_temp']}")
    _refresh_log_table()
    _refresh_main_view()


# -------------------------------------------------- callbacks для кнопок
def _on_open_overwrite(sender=None, data=None):
    open_overwrite_dialog()


def _on_open_archive(sender=None, data=None):
    open_archive_dialog()


def _on_open_actions_log(sender=None, data=None):
    open_actions_log_window()


def on_source_changed(sender=None, data=None):
    """Смена источника данных для просмотра."""
    label = dpg.get_value('archive_source_combo')
    for lb, main, temps in SOURCES:
        if lb == label:
            _source_state['main_table'] = main
            _source_state['temps_table'] = temps
            _source_state['label'] = lb
            break
    _refresh_main_view()

# -------------------------------------------------- перенос текущего замера

def _current_measure_context():
    """(df, measure_id, msk, error_str).

    Возвращает единственный Measure_ID и единственный МСК из загруженных
    данных. Если в выборке несколько замеров/МСК или данных нет —
    error_str содержит причину.
    """
    from .Archive_Constants import WINDOW_TAG
    df = dpg.get_item_user_data(WINDOW_TAG)
    if df is None or df.empty:
        return None, None, None, 'Нет загруженных данных'
    if 'Measure_ID' not in df.columns:
        return df, None, None, 'В данных нет колонки Measure_ID'

    mids = df['Measure_ID'].dropna().unique()
    if len(mids) == 0:
        return df, None, None, 'В данных нет Measure_ID'
    if len(mids) > 1:
        return df, None, None, (
            f'В выборке несколько замеров ({len(mids)}). '
            f'Загрузите один Measure_ID.')
    try:
        mid = int(mids[0])
    except (TypeError, ValueError):
        return df, None, None, f'Некорректный Measure_ID: {mids[0]!r}'

    msk = None
    if 'MSK' in df.columns:
        msks = [str(m) for m in df['MSK'].dropna().unique()
                if str(m).strip()]
        if len(msks) == 1:
            msk = msks[0]
    if not msk:
        return df, mid, None, 'В данных нет однозначного МСК'
    return df, mid, msk, None


def _show_confirm(title, message, on_confirm):
    """Простое модальное окно подтверждения."""
    tag = 'archive_confirm_dialog'
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.window(label=title, tag=tag, modal=True,
                    width=560, height=260, no_collapse=True):
        dpg.add_text(message, wrap=530)
        dpg.add_separator()
        with dpg.group(horizontal=True):
            def _ok():
                dpg.delete_item(tag)
                try:
                    on_confirm()
                except Exception as e:
                    dpg.set_value('archive_status_text', f'Ошибка: {e}')
            dpg.add_button(label='Да', width=110, callback=_ok)
            dpg.add_button(label='Отмена', width=110,
                           callback=lambda s, a: dpg.delete_item(tag))


def _switch_source_to(label: str, measure_id: int):
    """Переключить источник данных и загрузить нужный замер."""
    from .Archive_Constants import _source_state
    for lb, main_t, temps_t in SOURCES:
        if lb == label:
            _source_state['main_table'] = main_t
            _source_state['temps_table'] = temps_t
            _source_state['label'] = lb
            break
    if dpg.does_item_exist('archive_source_combo'):
        dpg.set_value('archive_source_combo', label)
    if dpg.does_item_exist('archive_measure_id_input'):
        dpg.set_value('archive_measure_id_input', str(measure_id))
    # Почистим номера, иначе приоритет numbers > ID
    if dpg.does_item_exist('archive_numbers_input'):
        dpg.set_value('archive_numbers_input', '')
    try:
        from .Archive_Cascade import reload_archive_data
        reload_archive_data()
    except Exception as e:
        print(f"[Archive] reload after switch: {e}")

def on_context_overwrite_current(sender=None, data=None):
    df, mid, msk, err = _current_measure_context()
    if err:
        dpg.set_value('archive_status_text', err)
        return
    _show_confirm(
        'Перенос временной записи',
        f'Замер Measure_ID={mid}, МСК {msk}\n\n'
        f'Если в основной таблице уже есть данные этого замера — '
        f'они НЕ изменятся, а временная запись будет просто удалена.\n'
        f'Если данных в основной нет — они будут перенесены.\n'
        f'Временная запись удаляется в обоих случаях.\n\n'
        f'Операция пишется в журнал.',
        lambda: _do_overwrite_current(mid, msk))


def _do_overwrite_current(mid: int, msk: str):
    res = overwrite_temp_to_main(msk, mid)
    if not res['ok']:
        dpg.set_value('archive_status_text',
                      f"Ошибка: {res.get('error', '?')}")
        return
    if res.get('mode') == 'skipped_exists':
        dpg.set_value(
            'archive_status_text',
            f"ID={mid}: в основной уже есть данные "
            f"(main {res['existing_main']}, temp {res['existing_temp']}). "
            f"Временная очищена: main {res['deleted_main']}, "
            f"temp {res['deleted_temp']}. Журнал id={res['log_id']}")
    else:
        dpg.set_value(
            'archive_status_text',
            f"Перенесено ID={mid}: main {res['main_inserted']}, "
            f"temp {res['temp_inserted']}; временная очищена "
            f"(main {res['deleted_main']}, temp {res['deleted_temp']}). "
            f"Журнал id={res['log_id']}")
    _switch_source_to('Основная', mid)




def on_context_archive_current(sender=None, data=None):
    """Правый клик по таблице при источнике psidata."""
    df, mid, msk, err = _current_measure_context()
    if err:
        dpg.set_value('archive_status_text', err)
        return
    _show_confirm(
        'Архивирование замера',
        f'Перенести замер Measure_ID={mid}, МСК {msk} '
        f'из основной таблицы в архивную?\n\n'
        f'Сначала данные пишутся в архив и в журнал отката, проверяются, '
        f'и только затем удаляются из основной. Операцию можно отменить '
        f'в журнале операций.',
        lambda: _do_archive_current(mid, msk))


def _do_archive_current(mid: int, msk: str):
    res = archive_main_to_archive(msk, measure_id=mid)
    if not res['ok']:
        dpg.set_value('archive_status_text',
                      f"Ошибка архивирования: {res.get('error', '?')}")
        return
    dpg.set_value(
        'archive_status_text',
        f"Архив ID={mid}: main {res['archived_main']}, "
        f"temp {res['archived_temp']}; удалено main {res['deleted_main']}, "
        f"temp {res['deleted_temp']}. Журнал id={res['log_id']}")
    # Показать результат в архивной таблице
    _switch_source_to('Архивная', mid)