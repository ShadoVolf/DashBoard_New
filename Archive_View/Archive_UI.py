"""Сборка фильтр-бара, инфо-панели, заполнение таблицы/норм/инфо, lookup UI."""
import pandas as pd
import dearpygui.dearpygui as dpg

from ResonatorGraph import open_for_measure_id, open_for_msk

from .Archive_Print import (
    print_archive_protocol, print_archive_test_protocol,
    print_archive_presentation_protocol, print_archive_temperatures,
    print_archive_protocol_selected,
    print_archive_psi_protocol, print_archive_msk_label  # <-- ДОБАВИТЬ
)
from .Archive_Export import export_archive_to_excel

from .Archive_Constants import (
    WINDOW_TAG,                              # ← добавить
    TABLE_CONTAINER, TABLE_TAG, NORMS_GROUP, NORMS_TAG,
    ALL_MSK, _lookup_sync_state, _view_state,
)

from .Archive_Data import (
    load_spc_map_for_archive, get_archive_info,
    rename_fields_to_parameters, apply_rounding,
    build_archive_status_df,
    resolve_param_column, log_missing_params,   # ← добавить
    set_include_shum,                           # NEW
)
from .Archive_Helpers import _current_psi_type, _load_spc_map_for_display, sanitize_tmax_tmin_value
# ============================================================
# Экранная замена спецсимволов
# ============================================================
_SCREEN_SAFE_TABLE = {
    '\u25bc': '>>',   '\u25b2': '<<',   '\u25b6': '>',    '\u25c0': '<',
    '\u25aa': '*',    '\u25a0': '*',
    '\u00b1': '+/-',  '\u00d7': 'x',    '\u00f7': '/',
    '\u2265': '>=',   '\u2264': '<=',   '\u2260': '!=',
    '\u2248': '~',    '\u2261': '=',    '\u221e': 'inf',
    '\u221a': 'sqrt', '\u2211': 'sum',  '\u2202': 'd',
    '\u2205': 'empty','\u2212': '-',
    '\u00b0': ' deg', '\u00b5': 'u',    '\u03bc': 'u',
    '\u03a9': 'Ohm',  '\u2126': 'Ohm',  '\u2103': ' C',   '\u2109': ' F',
    '\u2013': '-',    '\u2014': '-',
    '\u2018': "'",    '\u2019': "'",    '\u201c': '"',    '\u201d': '"',
    '\u00ab': '"',    '\u00bb': '"',    '\u2026': '...',
    '\u00b7': '.',    '\u22c5': '.',    '\u00a0': ' ',
    '\u2192': '->',   '\u2190': '<-',   '\u2191': '^',    '\u2193': 'v',
    '\u00b9': '^1', '\u00b2': '^2', '\u00b3': '^3',
    '\u2070': '^0', '\u2074': '^4', '\u2075': '^5',
    '\u2076': '^6', '\u2077': '^7', '\u2078': '^8',
    '\u2079': '^9', '\u207b': '^-',
    '\u2080': '_0', '\u2081': '_1', '\u2082': '_2',
    '\u2083': '_3', '\u2084': '_4', '\u2085': '_5',
    '\u2086': '_6', '\u2087': '_7', '\u2088': '_8', '\u2089': '_9',
    '\u03b1': 'a', '\u03b2': 'b', '\u03b3': 'g', '\u03b4': 'd',
    '\u03b5': 'e', '\u03b6': 'z', '\u03b7': 'h', '\u03b8': 'th',
    '\u03bb': 'l', '\u03bd': 'v', '\u03be': 'x', '\u03c0': 'pi',
    '\u03c1': 'r', '\u03c3': 's', '\u03c4': 't', '\u03c6': 'f',
    '\u03c7': 'ch', '\u03c8': 'ps', '\u03c9': 'w',
    '\u0394': 'Delta', '\u03a3': 'Sigma', '\u03a6': 'Phi',
    '\u03a8': 'Psi', '\u03a0': 'Pi', '\u0398': 'Theta', '\u039b': 'Lambda',
    '\u2022': '*', '\u2023': '>', '\u2043': '-',
    '\u2713': '+', '\u2714': '+', '\u2717': 'x', '\u2718': 'x',
    '\u2610': '[ ]', '\u2611': '[v]', '\u2612': '[x]',
    '\u25cf': '*', '\u25cb': 'o', '\u25c6': '*', '\u25c7': '<>', '\u2217': '*',
}


def _screen_safe(v) -> str:
    """Строка с ASCII-заменой спецсимволов (для показа в DearPyGui)."""
    if v is None:
        return ''
    try:
        if pd.isna(v):
            return ''
    except (TypeError, ValueError):
        pass
    s = str(v)
    if not s:
        return ''
    if s.isascii():
        return s
    for src, dst in _SCREEN_SAFE_TABLE.items():
        if src in s:
            s = s.replace(src, dst)
    return s


# ------------------------------------------------------- история: колбэки
def _on_history_load(sender=None, data=None):
    from .Archive_History import load_history_for_current_view
    load_history_for_current_view()


def _on_history_print(sender=None, data=None):
    from .Archive_History import print_history_grouped_protocol
    print_history_grouped_protocol()


def _on_history_export(sender=None, data=None):
    from .Archive_History import export_history_to_excel
    export_history_to_excel()

# ------------------------------------------------------- тип протокола
def _apply_psi_type_from_df(df: pd.DataFrame):
    """Установить тип протокола из загруженных данных."""
    if not dpg.does_item_exist('archive_psi_type_combo'):
        return
    psi_type = 'ОТК'
    if (df is not None and not df.empty
            and 'psi_type' in df.columns):
        vals = df['psi_type'].dropna().unique()
        if len(vals) > 0 and vals[0] in ('ПСИ', 'ОТК'):
            psi_type = vals[0]
    dpg.set_value('archive_psi_type_combo', psi_type)


def _on_psi_type_changed(sender=None, data=None):
    """Смена типа протокола — перерисовать таблицу и нормы."""
    df = dpg.get_item_user_data(WINDOW_TAG)
    if df is not None and not df.empty:
        _fill_table(df)
    spc_name = dpg.get_value('archive_spc_combo') or ''
    _fill_norms(spc_name)


# ------------------------------------------------------- видимость Shum
# NEW: единая точка проверки, включена ли галочка Shum*
def _shum_visible() -> bool:
    return (dpg.does_item_exist('archive_shum_check')
            and bool(dpg.get_value('archive_shum_check')))


# NEW: переключение галочки — обновляет глобальный флаг в Archive_Data
# и перерисовывает таблицу + нормы. Протоколы подхватят флаг автоматически,
# так как и они, и UI используют load_spc_map_for_archive().
def _on_shum_check_changed(sender=None, data=None):
    set_include_shum(_shum_visible())

    df = dpg.get_item_user_data(WINDOW_TAG)
    if df is not None and not df.empty:
        _fill_table(df)
    spc_name = dpg.get_value('archive_spc_combo') or ''
    _fill_norms(spc_name)


# ---------------------------------------------------------------- фильтр-бар
def _build_filter_bar():
    from .Archive_Cascade import (
        on_type_changed, on_spc_changed, on_msk_changed, on_date_changed,
        _on_measure_id_enter, _on_measure_id_pick,
        _on_clear_numbers, reload_archive_data,
    )
    from .Archive_Search import _on_msk_search, _on_clear_msk_search
    from .Archive_Constants import MODE_ONLY_NUM, MODE_FULL_MSK
    from .Archive_Transfer_UI import on_source_changed, SOURCES

    # Источник данных
    with dpg.group(horizontal=True):
        dpg.add_text("Источник данных:", color=(180, 220, 255))
        dpg.add_combo([lbl for lbl, _, _ in SOURCES],
                      tag='archive_source_combo',
                      width=160, default_value='Основная',
                      callback=on_source_changed)

    # Основной каскад
    with dpg.group(horizontal=True):
        with dpg.group(width=180):
            dpg.add_text("Тип резонатора")
            dpg.add_combo([], tag='archive_type_combo', width=180,
                          callback=on_type_changed)
        with dpg.group(width=220):
            dpg.add_text("Спецификация")
            dpg.add_combo([], tag='archive_spc_combo', width=220,
                          callback=on_spc_changed)
        with dpg.group(width=180):
            dpg.add_text("МСК")
            dpg.add_combo([], tag='archive_msk_combo', width=180,
                          callback=on_msk_changed)
        with dpg.group(width=150):
            dpg.add_text("Дата")
            dpg.add_combo([], tag='archive_date_combo', width=150,
                          callback=on_date_changed)
        with dpg.group(width=200):
            dpg.add_text("Файл")
            dpg.add_combo([], tag='archive_file_combo', width=200)

    # Поиск МСК
    with dpg.group(horizontal=True):
        with dpg.group(width=420):
            dpg.add_text("Поиск МСК по части номера")
            dpg.add_input_text(
                tag='archive_msk_search_input', width=420,
                hint="456  |  25-2456", on_enter=True,
                callback=lambda s, a: _on_msk_search())
        with dpg.group(width=140):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Найти МСК', width=140,
                           callback=lambda s, a: _on_msk_search())
        with dpg.group(width=140):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Очистить МСК', width=140,
                           callback=_on_clear_msk_search)

    # ID замера
    with dpg.group(horizontal=True):
        with dpg.group(width=150):
            dpg.add_text("ID замера (Enter)")
            dpg.add_input_text(tag='archive_measure_id_input', width=150,
                               decimal=True, on_enter=True,
                               callback=_on_measure_id_enter)
        with dpg.group(width=170):
            dpg.add_text("Список ID замера")
            dpg.add_combo([], tag='archive_measure_id_combo', width=170,
                          callback=_on_measure_id_pick)
        with dpg.group(width=140):
            dpg.add_spacer(height=18)
            dpg.add_checkbox(label="Только годные",
                             tag='archive_only_good_check')
        with dpg.group(width=130):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Загрузить', width=130,
                           callback=lambda s, a: reload_archive_data())

    # Номера
    with dpg.group(horizontal=True):
        with dpg.group(width=420):
            dpg.add_text("Номера (одиночный / список / диапазон)")
            dpg.add_input_text(
                tag='archive_numbers_input', width=420,
                hint="JN4450  |  JN4450,JN4451  |  JN4450-JN4460",
                on_enter=True,
                callback=lambda s, a: reload_archive_data())
        with dpg.group(width=220):
            dpg.add_text("Режим поиска по номерам")
            dpg.add_radio_button(
                [MODE_ONLY_NUM, MODE_FULL_MSK],
                tag='archive_search_mode',
                horizontal=True, default_value=MODE_ONLY_NUM)
            with dpg.tooltip(dpg.last_item()):
                dpg.add_text(
                    "Только номер: только записи с указанным номером\n"
                    "Вся МСК: все замеры, содержащие этот номер")
        with dpg.group(width=140):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Очистить номера', width=140,
                           callback=_on_clear_numbers)

    dpg.add_separator()


# ------------------------------------------------------------- инфо-панель
def _build_info_panel():
    from .Archive_LookupUI import open_lookup_window as _open_lookup_window
    from .Archive_TablesWindow import open_tables_window as _open_tables_window
    from .Archive_Print import (
        print_archive_protocol, print_archive_test_protocol,
        print_archive_presentation_protocol, print_archive_temperatures,
        print_archive_protocol_selected, print_archive_msk_label,
    )
    dpg.add_text("Информация о записи", color=(180, 220, 255))
    dpg.add_separator()

    def info_row(label, tag):
        with dpg.group(horizontal=True):
            dpg.add_text(f"{label}:", color=(150, 200, 255))
            dpg.add_text("", tag=tag)

    info_row("МСК", 'archive_info_msk')
    info_row("Файл", 'archive_info_file')
    info_row("Спецификация", 'archive_info_spc')
    info_row("Дата", 'archive_info_date')
    info_row("Время", 'archive_info_time')
    info_row("Номинал", 'archive_info_nominal')
    info_row("ID замера", 'archive_info_measure_id')
    info_row("Записей", 'archive_info_count')

    dpg.add_separator()
    dpg.add_text("Параметры спецификации", color=(180, 220, 255))
    with dpg.group(horizontal=True):
        dpg.add_text("Тип протокола:", color=(150, 200, 255))
        dpg.add_combo(['ПСИ', 'ОТК'],
                      tag='archive_psi_type_combo', width=120,
                      default_value='ОТК',
                      callback=_on_psi_type_changed)

    with dpg.group(tag=NORMS_GROUP):
        dpg.add_text("- спецификация не выбрана -",
                     tag='archive_norms_hint', color=(140, 140, 140))

    # ---- Протоколы ----
    dpg.add_separator()
    with dpg.collapsing_header(label="Протоколы", default_open=True):
        dpg.add_button(label='Печать всех протоколов', width=-1, height=28,
                       tag='archive_print_button',
                       callback=lambda s, a: print_archive_protocol())
        dpg.add_button(label='Тестовый протокол', width=-1, height=28,
                       tag='archive_test_print_button',
                       callback=lambda s, a: print_archive_test_protocol())
        dpg.add_button(label='Предъявительский протокол (ОТК)',
                       width=-1, height=28,
                       tag='archive_presentation_button',
                       callback=lambda s, a: print_archive_presentation_protocol())
        dpg.add_button(label='Протокол ПСИ (Приемо-сдаточный)',
                       width=-1, height=28,
                       tag='archive_psi_button',
                       callback=lambda s, a: print_archive_psi_protocol())
        dpg.add_button(label='Печать этикетки МСК',
                       width=-1, height=28,
                       tag='archive_label_button',
                       callback=lambda s, a: print_archive_msk_label())
        dpg.add_button(label='Распечатка (температуры)',
                       width=-1, height=28,
                       tag='archive_print_temps_button',
                       callback=lambda s, a: print_archive_temperatures())
        dpg.add_spacer(height=4)
        dpg.add_text("Печать выбранного замера", color=(180, 220, 255))
        dpg.add_combo([], tag='archive_print_measure_combo', width=-1)
        dpg.add_button(label='Печать выбранного', width=-1, height=28,
                       callback=lambda s, a: print_archive_protocol_selected())

    # ---- Данные ----
    dpg.add_separator()
    with dpg.collapsing_header(label="Данные", default_open=False):
        dpg.add_checkbox(label='Коэффициенты полинома',
                         tag='archive_coeff_check', default_value=False)
        # NEW: галочка отображения норм и данных по Shum*
        dpg.add_checkbox(label='Параметры шума (Shum)',
                         tag='archive_shum_check', default_value=False,
                         callback=_on_shum_check_changed)
        dpg.add_button(label='Экспорт в Excel', width=-1, height=28,
                       tag='archive_excel_button',
                       callback=lambda s, a: export_archive_to_excel())
        dpg.add_button(label='Открыть в Графиках', width=-1, height=28,
                       tag='archive_open_graphs_button',
                       callback=lambda s, a: _on_open_in_graphs())

    # ---- Инструменты ----
    dpg.add_separator()
    dpg.add_text("Инструменты", color=(180, 220, 255))
    dpg.add_button(label='Справочник номеров...', width=-1, height=28,
                   tag='archive_lookup_button',
                   callback=lambda s, a: _open_lookup_window())
    dpg.add_button(label='Управление таблицами...', width=-1, height=28,
                   tag='archive_tables_button',
                   callback=lambda s, a: _open_tables_window())


def _build_info_panel_1():
    from .Archive_Delete import _on_open_delete_dialog, _on_open_log_window
    from .Archive_Transfer_UI import (
        _on_open_overwrite, _on_open_archive, _on_open_actions_log,
    )
    dpg.add_text("Информация о записи", color=(180, 220, 255))
    dpg.add_separator()

    def info_row(label, tag):
        with dpg.group(horizontal=True):
            dpg.add_text(f"{label}:", color=(150, 200, 255))
            dpg.add_text("", tag=tag)

    info_row("МСК", 'archive_info_msk')
    info_row("Файл", 'archive_info_file')
    info_row("Спецификация", 'archive_info_spc')
    info_row("Дата", 'archive_info_date')
    info_row("Время", 'archive_info_time')
    info_row("Номинал", 'archive_info_nominal')
    info_row("ID замера", 'archive_info_measure_id')
    info_row("Записей", 'archive_info_count')

    dpg.add_separator()
    dpg.add_text("Параметры спецификации", color=(180, 220, 255))
    with dpg.group(horizontal=True):
        dpg.add_text("Тип протокола:", color=(150, 200, 255))
        dpg.add_combo(['ПСИ', 'ОТК'],
                      tag='archive_psi_type_combo',
                      width=120,
                      default_value='ОТК',
                      callback=_on_psi_type_changed)

    with dpg.group(tag=NORMS_GROUP):
        dpg.add_text("- спецификация не выбрана -", color=(140, 140, 140))

    dpg.add_separator()
    dpg.add_button(label='Печать всех протоколов', width=-1, height=32,
                   tag='archive_print_button',
                   callback=lambda s, a: print_archive_protocol())
    dpg.add_button(label='Тестовый протокол (нормы внизу, стат. в конце)',
                   width=-1, height=32,
                   tag='archive_test_print_button',
                   callback=lambda s, a: print_archive_test_protocol())
    dpg.add_button(label='Предъявительский протокол', width=-1, height=32,
                   tag='archive_presentation_button',
                   callback=lambda s, a: print_archive_presentation_protocol())
    dpg.add_button(label='Распечатка (температуры)', width=-1, height=32,
                   tag='archive_print_temps_button',
                   callback=lambda s, a: print_archive_temperatures())

    dpg.add_separator()
    dpg.add_text("Печать выбранного замера", color=(180, 220, 255))
    dpg.add_combo([], tag='archive_print_measure_combo', width=-1)
    dpg.add_button(label='Печать выбранного замера',
                   width=-1, height=30,
                   callback=lambda s, a: print_archive_protocol_selected())
    dpg.add_separator()
    dpg.add_text("Просмотр в других модулях", color=(180, 220, 255))
    dpg.add_button(label='Открыть в Графиках', width=-1, height=32,
                   tag='archive_open_graphs_button',
                   callback=lambda s, a: _on_open_in_graphs())

    with dpg.group(horizontal=True):
        dpg.add_checkbox(label='Коэффициенты полинома',
                         tag='archive_coeff_check', default_value=False)
        # NEW: галочка отображения норм и данных по Shum*
        dpg.add_checkbox(label='Параметры шума (Shum)',
                         tag='archive_shum_check', default_value=False,
                         callback=_on_shum_check_changed)

    dpg.add_separator()
    dpg.add_button(label='Экспорт в Excel', width=-1, height=30,
                   tag='archive_excel_button',
                   callback=lambda s, a: export_archive_to_excel())
    # ---- Удаление номеров резонаторов ----
    dpg.add_separator()
    dpg.add_text("Управление номерами резонаторов",
                 color=(180, 220, 255))
    dpg.add_button(label='Удалить номер(а) из замера...',
                   width=-1, height=30,
                   tag='archive_delete_button',
                   callback=lambda s, a: _on_open_delete_dialog())
    dpg.add_button(label='Журнал удалений / восстановление',
                   width=-1, height=30,
                   tag='archive_log_button',
                   callback=lambda s, a: _on_open_log_window())
    dpg.add_separator()
    # ---- Источник данных ----
    from .Archive_Transfer_UI import on_source_changed, SOURCES
    with dpg.group(horizontal=True):
        dpg.add_text("Источник данных:", color=(180, 220, 255))
        dpg.add_combo([lbl for lbl, _, _ in SOURCES],
                      tag='archive_source_combo',
                      width=160, default_value='Основная',
                      callback=on_source_changed)

    dpg.add_separator()
    dpg.add_text("Управление таблицами", color=(180, 220, 255))
    dpg.add_button(label='Перезапись: временная → основная',
                   width=-1, height=30,
                   tag='archive_overwrite_button',
                   callback=lambda s, a: _on_open_overwrite())
    dpg.add_button(label='Архивировать: основная → архив',
                   width=-1, height=30,
                   tag='archive_archive_button',
                   callback=lambda s, a: _on_open_archive())
    dpg.add_button(label='Журнал операций / откат',
                   width=-1, height=30,
                   tag='archive_actions_log_button',
                   callback=lambda s, a: _on_open_actions_log())
    dpg.add_text("Справочник номеров резонаторов",
                 color=(180, 220, 255))
    dpg.add_text("***", tag='archive_lookup_status',
                 color=(150, 200, 255))
    dpg.add_button(label='Проверить', width=-1,
                   callback=lambda s, a: _on_lookup_check())
    dpg.add_button(label='Досинхронизировать', width=-1,
                   callback=lambda s, a: _on_lookup_sync(False))
    dpg.add_button(label='Полная пересборка', width=-1,
                   callback=lambda s, a: _on_lookup_sync(True))


# ------------------------------------------------------- заполнение таблицы
def _fill_table(df: pd.DataFrame):
    from .Archive_Delete import _on_open_delete_dialog

    if dpg.does_item_exist(TABLE_CONTAINER):
        for ch in dpg.get_item_children(TABLE_CONTAINER, 1) or []:
            dpg.delete_item(ch)

    if df is None or df.empty:
        dpg.set_value('archive_status_text', 'Данные не найдены')
        dpg.add_text("- нет данных -", parent=TABLE_CONTAINER,
                     tag='archive_table_hint', color=(140, 140, 140))
        return

    spc_name = _resolve_display_spc(df)
    if spc_name:
        spc_map = _load_spc_map_for_display(spc_name, _current_psi_type())
    else:
        spc_map = pd.DataFrame()

    mapped = rename_fields_to_parameters(df)

    spec_status = build_archive_status_df(df, spc_map)
    overall_ok = spec_status['Status'].tolist()
    param_ok = {
        c[:-len('_status')]: spec_status[c].tolist()
        for c in spec_status.columns
        if c.endswith('_status') and not c.endswith('_anomal_status')
    }

    if not spc_map.empty:
        mapped = apply_rounding(mapped, spc_map)

    is_history = (_view_state.get('mode') == 'history')

    display_cols: list[tuple[str, str, str | None]] = []

    if 'Position' in mapped.columns:
        display_cols.append(('Position', 'Позиция', None))
    elif 'Positions' in mapped.columns:
        display_cols.append(('Positions', 'Позиция', None))

    if 'N' in mapped.columns:
        display_cols.append(('N', 'N', None))
    elif 'Numbers' in mapped.columns:
        display_cols.append(('Numbers', 'N', None))

    if is_history and 'Date' in mapped.columns:
        display_cols.append(('Date', 'Дата', None))

    show_msk = (dpg.get_value('archive_msk_combo') == ALL_MSK)
    if not show_msk and 'MSK' in mapped.columns:
        if mapped['MSK'].dropna().nunique() > 1:
            show_msk = True
    if show_msk and 'MSK' in mapped.columns:
        display_cols.append(('MSK', 'МСК', None))

    if 'Measure_ID' in mapped.columns:
        if mapped['Measure_ID'].dropna().nunique() > 1:
            display_cols.append(('Measure_ID', 'ID замера', None))

    if not spc_map.empty:
        log_missing_params(mapped, spc_map,
                           context=f"_fill_table spc={spc_name}")

        ordered = (spc_map.sort_values('Order')
                   if 'Order' in spc_map.columns else spc_map)
        for _, spc_item in ordered.iterrows():
            param = spc_item['Parameter']
            col = resolve_param_column(mapped, param, spc_item)
            if col is None:
                continue
            label = spc_item.get('Note_mini') or spc_item.get('Note') or param
            display_cols.append((col, str(label), param))

    display_cols.append(('__status__', 'Статус', None))

    if dpg.get_value('archive_coeff_check'):
        for c in ('A0', 'A1', 'A2', 'A3', 'A4'):
            if c in mapped.columns:
                display_cols.append((c, c, None))

    if not display_cols:
        dpg.set_value('archive_status_text', 'Нет столбцов для отображения')
        dpg.add_text("- нет столбцов по спецификации -",
                     parent=TABLE_CONTAINER, color=(140, 140, 140))
        return

    ROW_BAD_COLOR      = (255, 220, 100)
    PARAM_BAD_COLOR    = (255,  90,  90)
    STATUS_GOOD        = (100, 220, 100)
    STATUS_BAD         = (255,  90,  90)
    GROUP_HEADER_COLOR = (255, 200, 100)

    n_key = None
    if is_history:
        if 'N' in mapped.columns:
            n_key = 'N'
        elif 'Numbers' in mapped.columns:
            n_key = 'Numbers'

    with dpg.table(tag=TABLE_TAG, parent=TABLE_CONTAINER,
                   header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True,
                   resizable=True, scrollX=True, scrollY=True,
                   policy=dpg.mvTable_SizingFixedFit, height=-1):
        for _, label, _ in display_cols:
            dpg.add_table_column(label=_screen_safe(label))

        prev_n = None
        for pos_idx, (_, row) in enumerate(mapped.iterrows()):
            if n_key:
                cur_n = str(row.get(n_key, '') or '').strip().upper()
                if cur_n and cur_n != prev_n:
                    with dpg.table_row():
                        for key, _, _ in display_cols:
                            if key == n_key:
                                dpg.add_text(_screen_safe(f'>> {cur_n}'),
                                             color=GROUP_HEADER_COLOR)
                            else:
                                dpg.add_text('')
                    prev_n = cur_n

            is_rejected = not overall_ok[pos_idx]
            with dpg.table_row():
                for key, _, param_name in display_cols:
                    if key == '__status__':
                        if spc_map.empty:
                            dpg.add_text('-', color=(140, 140, 140))
                        elif is_rejected:
                            dpg.add_text('Брак', color=STATUS_BAD)
                        else:
                            dpg.add_text('Годен', color=STATUS_GOOD)
                        continue

                    val = row.get(key, '')
                    if pd.isna(val):
                        val = ''
                    # extr_1/extr_2 (spc Parameter, Note_mini «Tmax, C»/«Tmin, C»)
                    # и Tmax/Tmin (psidata) вне [-60, 150] — пустая строка
                    if (param_name in ('Tmax', 'Tmin', 'extr_1', 'extr_2')
                            or key in ('Tmax', 'Tmin', 'extr_1', 'extr_2')):
                        val = sanitize_tmax_tmin_value(val, param_name or key)
                    text = _screen_safe(val)

                    color = None
                    if param_name and param_name in param_ok:
                        if not param_ok[param_name][pos_idx]:
                            color = PARAM_BAD_COLOR
                        elif is_rejected:
                            color = ROW_BAD_COLOR
                    elif is_rejected:
                        color = ROW_BAD_COLOR

                    if color:
                        dpg.add_text(text, color=color)
                    else:
                        dpg.add_text(text)

    if dpg.does_item_exist('archive_table_context'):
        dpg.delete_item('archive_table_context')

    from .Archive_Transfer_UI import (
        on_context_overwrite_current, on_context_archive_current,
    )
    from .Archive_Constants import _source_state
    active_table = _source_state.get('main_table', 'psidata')

    with dpg.popup(parent=TABLE_CONTAINER,
                   mousebutton=dpg.mvMouseButton_Right,
                   tag='archive_table_context'):
        dpg.add_menu_item(label='История по номерам',
                          callback=_on_history_load)
        dpg.add_menu_item(label='Печать истории',
                          callback=_on_history_print)
        dpg.add_menu_item(label='Экспорт истории в Excel',
                          callback=_on_history_export)
        dpg.add_separator()
        dpg.add_menu_item(label='Экспорт в Excel',
                          callback=lambda s, a: export_archive_to_excel())
        dpg.add_separator()
        dpg.add_menu_item(label='Удалить номера из замера...',
                          callback=_on_open_delete_dialog)
        dpg.add_separator()

        if active_table == 'psidata_temporary':
            dpg.add_menu_item(label='Перенести в основную...',
                              callback=on_context_overwrite_current)
        elif active_table == 'psidata':
            dpg.add_menu_item(label='Перенести в архив...',
                              callback=on_context_archive_current)

        dpg.add_separator()
        dpg.add_menu_item(label='Открыть в Графиках',
                          callback=lambda s, a: _on_open_in_graphs())


def _fill_table_1(df: pd.DataFrame):
    from .Archive_Delete import _on_open_delete_dialog

    if dpg.does_item_exist(TABLE_CONTAINER):
        for ch in dpg.get_item_children(TABLE_CONTAINER, 1) or []:
            dpg.delete_item(ch)

    if df is None or df.empty:
        dpg.set_value('archive_status_text', 'Данные не найдены')
        dpg.add_text("- нет данных -", parent=TABLE_CONTAINER,
                     tag='archive_table_hint', color=(140, 140, 140))
        return

    spc_name = _resolve_display_spc(df)
    spc_map = load_spc_map_for_archive(spc_name) if spc_name else pd.DataFrame()
    mapped = rename_fields_to_parameters(df)

    spec_status = build_archive_status_df(df, spc_map)
    overall_ok = spec_status['Status'].tolist()
    param_ok = {
        c[:-len('_status')]: spec_status[c].tolist()
        for c in spec_status.columns
        if c.endswith('_status') and not c.endswith('_anomal_status')
    }

    if not spc_map.empty:
        mapped = apply_rounding(mapped, spc_map)

    is_history = (_view_state.get('mode') == 'history')

    display_cols: list[tuple[str, str, str | None]] = []

    if 'Position' in mapped.columns:
        display_cols.append(('Position', 'Позиция', None))
    elif 'Positions' in mapped.columns:
        display_cols.append(('Positions', 'Позиция', None))

    if 'N' in mapped.columns:
        display_cols.append(('N', 'N', None))
    elif 'Numbers' in mapped.columns:
        display_cols.append(('Numbers', 'N', None))

    if is_history and 'Date' in mapped.columns:
        display_cols.append(('Date', 'Дата', None))

    show_msk = (dpg.get_value('archive_msk_combo') == ALL_MSK)
    if not show_msk and 'MSK' in mapped.columns:
        if mapped['MSK'].dropna().nunique() > 1:
            show_msk = True
    if show_msk and 'MSK' in mapped.columns:
        display_cols.append(('MSK', 'МСК', None))

    if 'Measure_ID' in mapped.columns:
        if mapped['Measure_ID'].dropna().nunique() > 1:
            display_cols.append(('Measure_ID', 'ID замера', None))

    if not spc_map.empty:
        log_missing_params(mapped, spc_map,
                           context=f"_fill_table spc={spc_name}")

        ordered = (spc_map.sort_values('Order')
                   if 'Order' in spc_map.columns else spc_map)
        for _, spc_item in ordered.iterrows():
            param = spc_item['Parameter']
            col = resolve_param_column(mapped, param, spc_item)
            if col is None:
                continue
            label = spc_item.get('Note_mini') or spc_item.get('Note') or param
            display_cols.append((col, str(label), param))

    display_cols.append(('__status__', 'Статус', None))

    if dpg.get_value('archive_coeff_check'):
        for c in ('A0', 'A1', 'A2', 'A3', 'A4'):
            if c in mapped.columns:
                display_cols.append((c, c, None))

    if not display_cols:
        dpg.set_value('archive_status_text', 'Нет столбцов для отображения')
        dpg.add_text("- нет столбцов по спецификации -",
                     parent=TABLE_CONTAINER, color=(140, 140, 140))
        return

    ROW_BAD_COLOR      = (255, 220, 100)
    PARAM_BAD_COLOR    = (255,  90,  90)
    STATUS_GOOD        = (100, 220, 100)
    STATUS_BAD         = (255,  90,  90)
    GROUP_HEADER_COLOR = (255, 200, 100)

    n_key = None
    if is_history:
        if 'N' in mapped.columns:
            n_key = 'N'
        elif 'Numbers' in mapped.columns:
            n_key = 'Numbers'

    with dpg.table(tag=TABLE_TAG, parent=TABLE_CONTAINER,
                   header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True,
                   resizable=True, scrollX=True, scrollY=True,
                   policy=dpg.mvTable_SizingFixedFit, height=-1):
        for _, label, _ in display_cols:
            dpg.add_table_column(label=_screen_safe(label))

        prev_n = None
        for pos_idx, (_, row) in enumerate(mapped.iterrows()):
            if n_key:
                cur_n = str(row.get(n_key, '') or '').strip().upper()
                if cur_n and cur_n != prev_n:
                    with dpg.table_row():
                        for key, _, _ in display_cols:
                            if key == n_key:
                                dpg.add_text(_screen_safe(f'>> {cur_n}'),
                                             color=GROUP_HEADER_COLOR)
                            else:
                                dpg.add_text('')
                    prev_n = cur_n

            is_rejected = not overall_ok[pos_idx]
            with dpg.table_row():
                for key, _, param_name in display_cols:
                    if key == '__status__':
                        if spc_map.empty:
                            dpg.add_text('-', color=(140, 140, 140))
                        elif is_rejected:
                            dpg.add_text('Брак', color=STATUS_BAD)
                        else:
                            dpg.add_text('Годен', color=STATUS_GOOD)
                        continue

                    val = row.get(key, '')
                    if pd.isna(val):
                        val = ''
                    # extr_1/extr_2 (spc Parameter, Note_mini «Tmax, C»/«Tmin, C»)
                    # и Tmax/Tmin (psidata) вне [-60, 150] — пустая строка
                    if (param_name in ('Tmax', 'Tmin', 'extr_1', 'extr_2')
                            or key in ('Tmax', 'Tmin', 'extr_1', 'extr_2')):
                        val = sanitize_tmax_tmin_value(val, param_name or key)
                    text = _screen_safe(val)

                    color = None
                    if param_name and param_name in param_ok:
                        if not param_ok[param_name][pos_idx]:
                            color = PARAM_BAD_COLOR
                        elif is_rejected:
                            color = ROW_BAD_COLOR
                    elif is_rejected:
                        color = ROW_BAD_COLOR

                    if color:
                        dpg.add_text(text, color=color)
                    else:
                        dpg.add_text(text)

    if dpg.does_item_exist('archive_table_context'):
        dpg.delete_item('archive_table_context')

    from .Archive_Transfer_UI import (
        on_context_overwrite_current, on_context_archive_current,
    )
    from .Archive_Constants import _source_state
    active_table = _source_state.get('main_table', 'psidata')

    with dpg.popup(parent=TABLE_CONTAINER,
                   mousebutton=dpg.mvMouseButton_Right,
                   tag='archive_table_context'):
        dpg.add_menu_item(label='История по номерам',
                          callback=_on_history_load)
        dpg.add_menu_item(label='Печать истории',
                          callback=_on_history_print)
        dpg.add_menu_item(label='Экспорт истории в Excel',
                          callback=_on_history_export)
        dpg.add_separator()
        dpg.add_menu_item(label='Экспорт в Excel',
                          callback=lambda s, a: export_archive_to_excel())
        dpg.add_separator()
        dpg.add_menu_item(label='Удалить номера из замера...',
                          callback=_on_open_delete_dialog)
        dpg.add_separator()

        if active_table == 'psidata_temporary':
            dpg.add_menu_item(label='Перенести в основную...',
                              callback=on_context_overwrite_current)
        elif active_table == 'psidata':
            dpg.add_menu_item(label='Перенести в архив...',
                              callback=on_context_archive_current)

        dpg.add_separator()
        dpg.add_menu_item(label='Открыть в Графиках',
                          callback=lambda s, a: _on_open_in_graphs())


# ------------------------------------------------------------------- нормы
def _fill_norms(spc_name: str):
    if dpg.does_item_exist(NORMS_TAG):
        dpg.delete_item(NORMS_TAG)
    if dpg.does_item_exist('archive_norms_hint'):
        dpg.delete_item('archive_norms_hint')

    if not spc_name:
        dpg.add_text("- спецификация не выбрана -",
                     parent=NORMS_GROUP, tag='archive_norms_hint',
                     color=(140, 140, 140))
        return

    psi_type = _current_psi_type()
    spc_map = _load_spc_map_for_display(spc_name, psi_type)
    if spc_map.empty:
        dpg.add_text("- нормы не заданы -",
                     parent=NORMS_GROUP, tag='archive_norms_hint',
                     color=(140, 140, 140))
        return

    if 'Order' in spc_map.columns:
        spc_map = spc_map.sort_values('Order')

    with dpg.table(tag=NORMS_TAG, parent=NORMS_GROUP,
                   header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True,
                   policy=dpg.mvTable_SizingStretchProp):
        dpg.add_table_column(label='Параметр')
        dpg.add_table_column(label='Макс')
        dpg.add_table_column(label='Мин')
        for _, row in spc_map.iterrows():
            label = row.get('Note_mini') or row.get('Note') or row['Parameter']
            mx = row['Max']
            mn = row['Min']
            with dpg.table_row():
                dpg.add_text(_screen_safe(label))
                dpg.add_text(f'{mx:.4g}' if mx is not None and not pd.isna(mx) else '-')
                dpg.add_text(f'{mn:.4g}' if mn is not None and not pd.isna(mn) else '-')


def _fill_print_measure_combo(df: pd.DataFrame):
    if not dpg.does_item_exist('archive_print_measure_combo'):
        return
    items = []
    if df is not None and not df.empty and 'Measure_ID' in df.columns:
        try:
            items = [str(int(x)) for x in sorted(df['Measure_ID'].dropna().unique())]
        except Exception:
            items = []
    dpg.configure_item('archive_print_measure_combo', items=items)
    dpg.set_value('archive_print_measure_combo', items[0] if items else '')

def _on_open_in_graphs(sender=None, data=None):
    """Открыть окно «Графики» для текущего замера из архива."""
    try:
        df = dpg.get_item_user_data(WINDOW_TAG)
        if df is None or df.empty:
            dpg.set_value('archive_status_text',
                          'Нет данных — сначала загрузите замер')
            return

        if dpg.does_item_exist('archive_print_measure_combo'):
            mid_str = dpg.get_value('archive_print_measure_combo')
            if mid_str:
                try:
                    mid = int(mid_str)
                except (TypeError, ValueError):
                    mid = None
                if mid is not None:
                    open_for_measure_id(mid)
                    dpg.set_value('archive_status_text',
                                  f'Открыто в Графиках: ID {mid}')
                    return

        if 'Measure_ID' in df.columns:
            mids = df['Measure_ID'].dropna().unique()
            if len(mids) == 1:
                mid = int(mids[0])
                open_for_measure_id(mid)
                dpg.set_value('archive_status_text',
                              f'Открыто в Графиках: ID {mid}')
                return

        if 'MSK' in df.columns:
            msks = df['MSK'].dropna().unique()
            if len(msks) == 1 and msks[0]:
                msk = str(msks[0])
                open_for_msk(msk)
                dpg.set_value('archive_status_text',
                              f'Открыто в Графиках: МСК {msk}')
                return

        dpg.set_value(
            'archive_status_text',
            'Не удалось определить Measure_ID или МСК для открытия в Графиках')
    except Exception as e:
        import traceback
        print(f"[Archive] Ошибка открытия в Графиках: {e}")
        traceback.print_exc()
        dpg.set_value('archive_status_text', f'Ошибка: {e}')


def _fill_info(df: pd.DataFrame):
    info = get_archive_info(df)
    if df is not None and not df.empty:
        if 'MSK' in df.columns:
            uniq = df['MSK'].dropna().unique()
            if len(uniq) > 1:
                info['MSK'] = f'{ALL_MSK} ({len(uniq)})'
        if 'Measure_ID' in df.columns:
            uniq = df['Measure_ID'].dropna().unique()
            if len(uniq) > 1:
                info['Measure_ID'] = f'Несколько ({len(uniq)})'

    for key, tag in [
        ('MSK', 'archive_info_msk'), ('File', 'archive_info_file'),
        ('Spc', 'archive_info_spc'), ('Date', 'archive_info_date'),
        ('Time', 'archive_info_time'), ('Nominal', 'archive_info_nominal'),
        ('Measure_ID', 'archive_info_measure_id'),
        ('Count', 'archive_info_count'),
    ]:
        dpg.set_value(tag, _screen_safe(info.get(key, '')))

    _fill_print_measure_combo(df)


# ------------------------------------------------------------- lookup UI
def _lookup_status_str(st: dict) -> str:
    last_sync = st.get('last_sync')
    ls = last_sync.strftime('%Y-%m-%d %H:%M') if last_sync else 'никогда'
    if st.get('is_empty'):
        return f"пуст (нужна полная пересборка, синхр.: {ls})"
    if st.get('is_actual'):
        return f"актуален, {st['lookup_count']:,} записей, синхр.: {ls}"
    return (f"нужна досинхр.: новых строк {st['new_psidata_rows']}, "
            f"всего {st['lookup_count']:,}, синхр.: {ls}")


def _on_lookup_check():
    try:
        from .Archive_Lookup import check_lookup_actual
        st = check_lookup_actual()
        msg = _lookup_status_str(st)
        if dpg.does_item_exist('archive_lookup_status'):
            dpg.set_value('archive_lookup_status', msg)
        print(f"[Archive] lookup: {st}")
    except Exception as e:
        print(f"[Archive] Ошибка проверки справочника: {e}")


def _on_lookup_sync(full_rebuild: bool):
    import threading
    if _lookup_sync_state.get('running'):
        dpg.set_value('archive_status_text',
                      'Синхронизация справочника уже идёт...')
        return

    _lookup_sync_state.update({
        'running': True, 'done': False,
        'message': 'Запуск...', 'error': None,
    })
    if dpg.does_item_exist('archive_lookup_status'):
        dpg.set_value('archive_lookup_status', 'Синхронизация...')

    def _worker():
        try:
            from .Archive_Lookup import sync_lookup_table
            res = sync_lookup_table(full_rebuild=full_rebuild)
            _lookup_sync_state['message'] = (
                f"Готово ({res['mode']}): добавлено {res['inserted']}, "
                f"всего {res['total']}")
        except Exception as e:
            _lookup_sync_state['error'] = str(e)
        finally:
            _lookup_sync_state['done'] = True
            _lookup_sync_state['running'] = False

    threading.Thread(target=_worker, daemon=True).start()

    def _poll():
        if _lookup_sync_state.get('done'):
            if _lookup_sync_state.get('error'):
                msg = f"Ошибка синхронизации: {_lookup_sync_state['error']}"
            else:
                msg = _lookup_sync_state.get('message', 'Готово')
            if dpg.does_item_exist('archive_lookup_status'):
                dpg.set_value('archive_lookup_status', msg)
            print(f"[Archive] {msg}")
            return
        dpg.set_frame_callback(dpg.get_frame_count() + 10, _poll)

    dpg.set_frame_callback(dpg.get_frame_count() + 10, _poll)

def _resolve_display_spc(df) -> str:
    """Единая спецификация для отображения данных."""
    cur = dpg.get_value('archive_spc_combo') or ''
    if df is None or df.empty or 'Spc' not in df.columns:
        return cur

    uniq = [str(s) for s in df['Spc'].dropna().unique() if s]
    if not uniq:
        return cur

    if len(uniq) == 1:
        result = uniq[0]
    elif cur in uniq:
        result = cur
    else:
        try:
            result = str(df['Spc'].value_counts().idxmax())
        except Exception:
            result = uniq[0]

    try:
        dpg.set_value('archive_spc_combo', result)
    except Exception:
        pass
    return result