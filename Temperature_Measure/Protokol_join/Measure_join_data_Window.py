import sys
import threading
import traceback
from io import StringIO

import pandas as pd

from Pictures.Theme_View.Load_Themes import load_themes
from Temperature_Measure import _layout
from Temperature_Measure.Protokol_join.Join_Measure_Data import (
    process_measure_ids_with_copy,
    search_msk_by_partial,
    search_measure_ids_by_msk_partial,
    search_measure_ids_by_number_partial,
    format_measure_combo_label,
    get_measure_summary,
    _parse_numbers_filter,
)
from Temperature_Measure.unite_protokol.sort_logic import (
    load_psidata_by_measure_id,
)
from Temperature_Measure.unite_protokol.sort_report import (
    create_merged_protocol_pdf,
)
from Temperature_Measure.unite_protokol.preview_window import (
    open_spec_preview,
)


# Высота нижней полосы: кнопки + прогресс + отступы
BOTTOM_H = 110

# Ширина колонок табличной разметки опций
OPT_LABEL_W = 110
OPT_FIELD_W = 220

# ▼ NEW: параметры последнего успешного объединения (для просмотра / печати)
_join_state = {
    'measure_id':   None,   # Measure_ID нового протокола
    'msk':          None,
    'program_type': None,
    'operator':     None,
    'psi_type':     'ОТК',
}


def create_join_data_windows(dpg):
    """Окно объединения данных в новый протокол.

    Содержимое (поля ввода, лог) прокручивается в child_window.
    Кнопки и прогресс-бар закреплены внизу и всегда видны,
    независимо от размера экрана и объёма лога.
    """
    load_themes(dpg)

    pos, size = _layout.dialog_rect(
        fraction_w=0.62, fraction_h=0.7,
        min_w=820, min_h=560,
        max_w=1100, max_h=850,
    )

    with dpg.window(label="Объединение данных в протокол",
                    width=size[0], height=size[1],
                    pos=pos, tag='join_data_window',
                    no_resize=True, no_collapse=True):

        # ------- Прокручиваемая область -------
        with dpg.child_window(width=-1, height=-BOTTOM_H, border=False):
            _build_content(dpg)

        # ------- Нижняя полоса: кнопки и прогресс -------
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(
                label='Выполнить',
                callback=lambda: join_data_callback(dpg),
                tag='join_data_start_button',
                width=200, height=32,
            )
            dpg.add_button(
                label='Просмотр результата',
                callback=lambda: _on_join_preview(dpg),
                tag='join_preview_button',
                enabled=False,
                width=180, height=32,
            )
            dpg.add_button(
                label='Печать PDF',
                callback=lambda: _on_join_print_pdf(dpg),
                tag='join_print_button',
                enabled=False,
                width=140, height=32,
            )
        dpg.add_spacer(height=6)
        dpg.add_progress_bar(tag="join_data_progress",
                             default_value=0.0, width=-1, height=10)

    dpg.bind_item_theme('join_data_start_button', 'Use_button_theme_rt_3')
    dpg.bind_item_theme("join_data_progress", 'progress_bar_theme')

    fill_interface_data(dpg)
    _layout.center_on_screen('join_data_window')


def _build_content(dpg):
    """Содержимое окна без нижней полосы."""

    # ============================================================
    # Поиск замера (основной замер)
    # ============================================================
    with dpg.collapsing_header(
            label="Поиск замера (основной замер)",
            default_open=True,
            closable=False,
            tag='join_search_header'):
        _build_search_panel(dpg)

    dpg.add_separator()

    # ============================================================
    # Номера протоколов
    # ============================================================
    dpg.add_text("Номера протоколов для объединения")
    with dpg.group(horizontal=True):
        dpg.add_input_text(tag='protokol_id_select', readonly=False,
                           width=-120)
        dpg.add_button(
            label='Очистить', width=110,
            callback=lambda: dpg.set_value('protokol_id_select', ''),
        )
    dpg.add_text("Формат: 253799, 253216 или 253799-253216",
                 color=(140, 140, 140))

    dpg.add_separator()

    # ============================================================
    # Опции
    # ============================================================
    dpg.add_text("Опции")
    with dpg.table(header_row=False,
                   borders_innerH=False, borders_innerV=False,
                   pad_outerX=False,
                   policy=dpg.mvTable_SizingFixedFit):
        dpg.add_table_column(init_width_or_weight=OPT_LABEL_W,
                             width_fixed=True)
        dpg.add_table_column(init_width_or_weight=OPT_FIELD_W,
                             width_fixed=True)
        dpg.add_table_column(init_width_or_weight=OPT_LABEL_W,
                             width_fixed=True)
        dpg.add_table_column(init_width_or_weight=OPT_FIELD_W,
                             width_fixed=True)

        with dpg.table_row():
            dpg.add_text("Номер МСК")
            dpg.add_input_text(tag='MSK_number_edit', readonly=False, width=-1)
            dpg.add_text("Установка")
            dpg.add_combo(tag='machine_edit', items=[], width=-1)

        with dpg.table_row():
            dpg.add_text("Оператор")
            dpg.add_combo(tag='operator_edit', items=[], width=-1)
            dpg.add_text("")
            dpg.add_text("")

        # ▼ NEW: тип протокола (ПСИ / ОТК)
        with dpg.table_row():
            dpg.add_text("Тип протокола")
            dpg.add_combo(
                ['ПСИ', 'ОТК'],
                tag='join_psi_type',
                width=-1,
                default_value='ОТК',
            )
            dpg.add_text("")
            dpg.add_text("")

    dpg.add_separator()
    # ============================================================
    # Фильтр номеров, остающихся в протоколе
    # ============================================================
    dpg.add_text("Номера для протокола")
    with dpg.group(horizontal=True):
        dpg.add_input_text(
            tag='join_numbers_filter', width=-130,
            hint='XL0001, XL0005-XL0025',
        )
        dpg.add_button(
            label='Очистить', width=120,
            callback=lambda: dpg.set_value('join_numbers_filter', ''),
        )
    dpg.add_text(
        "Пусто — все номера. Формат: XL0001, XL0005-XL0025, ...",
        color=(140, 140, 140),
    )

    with dpg.group(horizontal=True):
        dpg.add_checkbox(
            tag='join_only_good',
            label='Только годные изделия',
            default_value=False,
        )

    dpg.add_separator()

    # ============================================================
    # Режим объединения
    # ============================================================
    dpg.add_text("Режим объединения")
    dpg.add_radio_button(
        items=["Не изменять данные", "Изменять данные"],
        horizontal=True,
        tag="join_data_random_add",
        default_value="Не изменять данные",
    )

    dpg.add_separator()

    # ============================================================
    # Результат
    # ============================================================
    with dpg.group(horizontal=True):
        dpg.add_text("Результаты объединения:")
        dpg.add_text("-----------", tag='Result_measure_ID',
                     color=(200, 220, 255))

    dpg.add_spacer(height=4)

    # Лог занимает всё оставшееся место в прокручиваемой области.
    dpg.add_input_text(
        tag='join_data_result_log_process_window',
        multiline=True,
        readonly=True,
        width=-1,
        height=-1,
        tracked=False,
        track_offset=1.0,
    )


# ---------------------------------------------------------------------------
#                          Панель поиска
# ---------------------------------------------------------------------------
def _build_search_panel(dpg):
    """Поиск замеров по частичному МСК и по номеру резонатора."""
    # ---------------- Поиск по МСК ----------------
    dpg.add_text("Поиск по МСК:", color=(200, 220, 255))
    with dpg.group(horizontal=True):
        dpg.add_input_text(
            tag='join_msk_search_input', width=240,
            hint='456  |  25-2456',
            on_enter=True,
            callback=lambda: _on_msk_search(dpg),
        )
        dpg.add_button(label='Найти МСК', width=110,
                       callback=lambda: _on_msk_search(dpg))
    with dpg.group(horizontal=True):
        dpg.add_text("МСК:", color=(180, 200, 230))
        dpg.add_combo([], tag='join_msk_combo', width=260,
                      callback=lambda: _on_msk_selected(dpg))
        dpg.add_text("Замер:", color=(180, 200, 230))
        dpg.add_combo([], tag='join_mid_by_msk_combo', width=400,
                      callback=lambda: _on_mid_by_msk_selected(dpg))
        dpg.add_button(
            label='+ В список', width=110,
            callback=lambda: _add_to_list_from_combo(
                dpg, 'join_mid_by_msk_combo'),
        )

    dpg.add_spacer(height=6)

    # ---------------- Поиск по номеру резонатора ----------------
    dpg.add_text("Поиск по номеру резонатора:", color=(200, 220, 255))
    with dpg.group(horizontal=True):
        dpg.add_input_text(
            tag='join_number_search_input', width=240,
            hint='SU8525  |  8525  |  SU85',
            on_enter=True,
            callback=lambda: _on_number_search(dpg),
        )
        dpg.add_button(label='Найти', width=110,
                       callback=lambda: _on_number_search(dpg))
    with dpg.group(horizontal=True):
        dpg.add_text("Найденные замеры:", color=(180, 200, 230))
        dpg.add_combo([], tag='join_mid_by_number_combo', width=520,
                      callback=lambda: _on_mid_by_number_selected(dpg))
        dpg.add_button(
            label='+ В список', width=110,
            callback=lambda: _add_to_list_from_combo(
                dpg, 'join_mid_by_number_combo'),
        )

    dpg.add_spacer(height=4)
    with dpg.group(horizontal=True):
        dpg.add_text("Информация:", color=(200, 220, 255))
        dpg.add_text("-", tag='join_measure_info',
                     color=(180, 200, 230))
    dpg.add_text(
        'После выбора нажмите «+ В список» — Measure_ID добавится '
        'в поле «Номера протоколов для объединения»',
        color=(140, 140, 140),
    )


# ---------------------------------------------------------------------------
#                  Поиск по МСК — обработчики
# ---------------------------------------------------------------------------
def _on_msk_search(dpg):
    partial = (dpg.get_value('join_msk_search_input') or '').strip()
    if not partial:
        return
    _set_info(dpg, f'Поиск МСК "{partial}"...')
    try:
        msks = search_msk_by_partial(partial)
    except Exception as e:
        print(f'[join_data] MSK search error: {e}')
        traceback.print_exc()
        _set_info(dpg, f'Ошибка поиска МСК: {e}')
        return

    dpg.configure_item('join_msk_combo', items=msks)
    if msks:
        dpg.set_value('join_msk_combo', msks[0])
        _on_msk_selected(dpg)
    else:
        dpg.configure_item('join_mid_by_msk_combo', items=[])
        dpg.set_value('join_mid_by_msk_combo', '')
        _set_info(dpg, f'МСК по "{partial}" не найдены')


def _on_msk_selected(dpg):
    msk = dpg.get_value('join_msk_combo')
    if not msk:
        return
    _set_info(dpg, f'Загрузка замеров для МСК "{msk}"...')
    try:
        df = search_measure_ids_by_msk_partial(msk)
    except Exception as e:
        print(f'[join_data] MSK measures error: {e}')
        traceback.print_exc()
        _set_info(dpg, f'Ошибка загрузки замеров: {e}')
        return

    items = [format_measure_combo_label(r) for _, r in df.iterrows()]
    dpg.configure_item('join_mid_by_msk_combo', items=items)
    if items:
        dpg.set_value('join_mid_by_msk_combo', items[0])
        _on_mid_by_msk_selected(dpg)
    else:
        dpg.set_value('join_mid_by_msk_combo', '')
        _set_info(dpg, f'Для МСК "{msk}" замеры не найдены')


def _on_mid_by_msk_selected(dpg):
    val = dpg.get_value('join_mid_by_msk_combo')
    if not val:
        return
    mid = _extract_mid(val)
    if mid:
        _show_measure_info(dpg, mid)


# ---------------------------------------------------------------------------
#               Поиск по номеру резонатора — обработчики
# ---------------------------------------------------------------------------
def _on_number_search(dpg):
    partial = (dpg.get_value('join_number_search_input') or '').strip()
    if not partial:
        return
    _set_info(dpg, f'Поиск по номеру "{partial}"...')
    try:
        df = search_measure_ids_by_number_partial(partial)
    except Exception as e:
        print(f'[join_data] number search error: {e}')
        traceback.print_exc()
        _set_info(dpg, f'Ошибка поиска: {e}')
        return

    items = [format_measure_combo_label(r) for _, r in df.iterrows()]
    dpg.configure_item('join_mid_by_number_combo', items=items)
    if items:
        dpg.set_value('join_mid_by_number_combo', items[0])
        _on_mid_by_number_selected(dpg)
    else:
        dpg.set_value('join_mid_by_number_combo', '')
        _set_info(dpg, f'По номеру "{partial}" ничего не найдено')


def _on_mid_by_number_selected(dpg):
    val = dpg.get_value('join_mid_by_number_combo')
    if not val:
        return
    mid = _extract_mid(val)
    if mid:
        _show_measure_info(dpg, mid)


# ---------------------------------------------------------------------------
#                     Общие хелперы поиска
# ---------------------------------------------------------------------------
def _extract_mid(label):
    """Извлечь Measure_ID из строки '253799 | N=... | ...'."""
    if not label:
        return None
    try:
        return str(int(str(label).split('|')[0].strip()))
    except (ValueError, IndexError):
        return None


def _show_measure_info(dpg, mid):
    try:
        info = get_measure_summary(mid)
    except Exception as e:
        print(f'[join_data] get_measure_summary error: {e}')
        _set_info(dpg, f'Ошибка сводки: {e}')
        return

    if not info:
        _set_info(dpg, f'Measure_ID {mid} не найден')
        return

    parts = [f"ID={info.get('measure_id')}"]
    if info.get('msk'):
        parts.append(f"MSK={info['msk']}")
    if info.get('spc'):
        parts.append(f"Spc={info['spc']}")
    if info.get('n_count') is not None:
        parts.append(f"N={info['n_count']}")
    if info.get('date'):
        parts.append(str(info['date']))
    if info.get('protocol_n'):
        parts.append(f"Прот={info['protocol_n']}")
    _set_info(dpg, " | ".join(parts))


def _add_to_list_from_combo(dpg, source_tag):
    """Добавить выбранный Measure_ID в поле protokol_id_select."""
    val = dpg.get_value(source_tag)
    if not val:
        return
    mid = _extract_mid(val)
    if not mid:
        return

    current = (dpg.get_value('protokol_id_select') or '').strip()
    existing = _parse_measure_ids(current)
    try:
        mid_int = int(mid)
    except ValueError:
        return

    if mid_int in existing:
        _set_info(dpg, f'Measure_ID {mid} уже в списке')
        return

    new_val = f"{current}, {mid}" if current else mid
    dpg.set_value('protokol_id_select', new_val)
    _set_info(
        dpg,
        f'Добавлен Measure_ID {mid} '
        f'(всего в списке: {len(existing) + 1})',
    )


def _parse_measure_ids(text):
    """Развернуть строку 'a, b-c, d' в множество int (диапазоны учтены)."""
    ids = set()
    if not text:
        return ids
    for item in str(text).split(','):
        item = item.strip()
        if not item:
            continue
        if '-' in item:
            try:
                start, end = map(int, item.split('-', 1))
                ids.update(range(start, end + 1))
            except ValueError:
                pass
        else:
            try:
                ids.add(int(item))
            except ValueError:
                pass
    return ids


def _set_info(dpg, message):
    """Записать текст в строку информации о замере."""
    if dpg.does_item_exist('join_measure_info'):
        dpg.set_value('join_measure_info', str(message))


# ---------------------------------------------------------------------------
# Callback: запуск объединения
# ---------------------------------------------------------------------------
def join_data_callback(dpg):
    input_text = dpg.get_value('protokol_id_select')
    msk = dpg.get_value('MSK_number_edit')
    program_type = dpg.get_value('machine_edit')
    operator = dpg.get_value('operator_edit')
    change_data = dpg.get_value('join_data_random_add')

    psi_type = 'ОТК'
    if dpg.does_item_exist('join_psi_type'):
        v = dpg.get_value('join_psi_type')
        if v in ('ПСИ', 'ОТК'):
            psi_type = v

    # ▼ NEW: whitelist номеров и «только годные»
    numbers_filter_text = ''
    if dpg.does_item_exist('join_numbers_filter'):
        numbers_filter_text = dpg.get_value('join_numbers_filter') or ''
    only_good = False
    if dpg.does_item_exist('join_only_good'):
        only_good = bool(dpg.get_value('join_only_good'))

    numbers_filter, parse_warnings = _parse_numbers_filter(numbers_filter_text)
    if parse_warnings:
        for w in parse_warnings:
            print(f'[join_data] ⚠ {w}')

    if not input_text.strip():
        dpg.set_value('join_data_result_log_process_window',
                      "Ошибка: не введены номера протоколов")
        return

    _join_state.update({
        'measure_id':    None,
        'msk':           None,
        'program_type':  None,
        'operator':      None,
        'psi_type':      psi_type,
        'only_good':     only_good,
        'numbers_count': len(numbers_filter) if numbers_filter else 0,
    })
    if dpg.does_item_exist('join_preview_button'):
        dpg.configure_item('join_preview_button', enabled=False)
    if dpg.does_item_exist('join_print_button'):
        dpg.configure_item('join_print_button', enabled=False)

    try:
        measure_ids = []
        for item in input_text.split(','):
            item = item.strip()
            if '-' in item:
                start, end = map(int, item.split('-'))
                measure_ids.extend(range(start, end + 1))
            else:
                measure_ids.append(int(item))

        measure_ids = sorted(set(measure_ids))

        info_message = f"Начинаю обработку протоколов: {measure_ids}\n"
        info_message += f"Количество протоколов: {len(measure_ids)}\n"
        info_message += f"Тип протокола: {psi_type}\n"

        if numbers_filter:
            sample = sorted(numbers_filter)[:5]
            info_message += (
                f"Фильтр номеров: {len(numbers_filter)} шт. "
                f"(например: {sample}{'...' if len(numbers_filter) > 5 else ''})\n"
            )
        else:
            info_message += "Фильтр номеров: не задан\n"
        info_message += f"Только годные изделия: {'да' if only_good else 'нет'}\n"

        if change_data == "Изменять данные":
            info_message += "Будут обновлены:\n"
            if msk:
                info_message += f"  - MSK: {msk}\n"
            if program_type:
                info_message += f"  - Программа: {program_type}\n"
            if operator:
                info_message += f"  - Оператор: {operator}\n"
        info_message += "Подготовка к объединению..."

        dpg.set_value('join_data_result_log_process_window', info_message)

        thread = threading.Thread(
            target=process_measure_ids_with_thread,
            args=(measure_ids, dpg, msk, program_type, operator,
                  change_data, psi_type, only_good, numbers_filter),
        )
        thread.daemon = True
        thread.start()

    except ValueError as e:
        dpg.set_value('join_data_result_log_process_window',
                      f"Ошибка в формате ввода: {e}\n"
                      f"Пример: 253799, 253216 или 253799-253216")

def join_data_callback_1(dpg):
    input_text = dpg.get_value('protokol_id_select')
    msk = dpg.get_value('MSK_number_edit')
    program_type = dpg.get_value('machine_edit')
    operator = dpg.get_value('operator_edit')
    change_data = dpg.get_value('join_data_random_add')

    # ▼ NEW: тип протокола из combo
    psi_type = 'ОТК'
    if dpg.does_item_exist('join_psi_type'):
        v = dpg.get_value('join_psi_type')
        if v in ('ПСИ', 'ОТК'):
            psi_type = v

    if not input_text.strip():
        dpg.set_value('join_data_result_log_process_window',
                      "Ошибка: не введены номера протоколов")
        return

    # ▼ NEW: сброс состояния и блокировка кнопок до нового результата
    _join_state = {
        'measure_id': None,
        'msk': None,
        'program_type': None,
        'operator': None,
        'psi_type': 'ОТК',
        'only_good': False,
        'numbers_count': 0,
    }
    if dpg.does_item_exist('join_preview_button'):
        dpg.configure_item('join_preview_button', enabled=False)
    if dpg.does_item_exist('join_print_button'):
        dpg.configure_item('join_print_button', enabled=False)

    try:
        measure_ids = []
        for item in input_text.split(','):
            item = item.strip()
            if '-' in item:
                start, end = map(int, item.split('-'))
                measure_ids.extend(range(start, end + 1))
            else:
                measure_ids.append(int(item))

        measure_ids = sorted(set(measure_ids))

        info_message = f"Начинаю обработку протоколов: {measure_ids}\n"
        info_message += f"Количество протоколов: {len(measure_ids)}\n"
        info_message += f"Тип протокола: {psi_type}\n"
        if change_data == "Изменять данные":
            info_message += "Будут обновлены:\n"
            if msk:
                info_message += f"  - MSK: {msk}\n"
            if program_type:
                info_message += f"  - Программа: {program_type}\n"
            if operator:
                info_message += f"  - Оператор: {operator}\n"
        info_message += "Подготовка к объединению..."

        dpg.set_value('join_data_result_log_process_window', info_message)

        thread = threading.Thread(
            target=process_measure_ids_with_thread,
            args=(measure_ids, dpg, msk, program_type, operator,
                  change_data, psi_type),
        )
        thread.daemon = True
        thread.start()

    except ValueError as e:
        dpg.set_value('join_data_result_log_process_window',
                      f"Ошибка в формате ввода: {e}\n"
                      f"Пример: 253799, 253216 или 253799-253216")


# ---------------------------------------------------------------------------
# Callback: обработка в фоне
# ---------------------------------------------------------------------------
def process_measure_ids_with_thread(measure_ids, dpg, msk, program_type,
                                     operator, change_data, psi_type='ОТК',
                                     only_good=False, numbers_filter=None):
    old_stdout = sys.stdout
    output_capture = StringIO()
    sys.stdout = output_capture

    try:
        dpg.set_value("join_data_progress", 0.1)
        dpg.set_value(
            'join_data_result_log_process_window',
            dpg.get_value('join_data_result_log_process_window') +
            "\nЗагружаю данные...",
        )

        if change_data == "Изменять данные":
            msk_to_use = msk if msk else None
            program_type_to_use = program_type if program_type else None
            operator_to_use = operator if operator else None
        else:
            msk_to_use = None
            program_type_to_use = None
            operator_to_use = None

        new_measure_id, psi_count, temp_count = process_measure_ids_with_copy(
            measure_ids,
            msk=msk_to_use,
            program_type=program_type_to_use,
            operator=operator_to_use,
            psi_type=psi_type,
            only_good=only_good,
            numbers_filter=numbers_filter,
        )

        sys.stdout = old_stdout
        captured_output = output_capture.getvalue()

        dpg.set_value("join_data_progress", 1.0)

        if new_measure_id:
            _join_state.update({
                'measure_id':   int(new_measure_id),
                'msk':          msk_to_use,
                'program_type': program_type_to_use,
                'operator':     operator_to_use,
                'psi_type':     psi_type,
            })
            if dpg.does_item_exist('join_preview_button'):
                dpg.configure_item('join_preview_button', enabled=True)
            if dpg.does_item_exist('join_print_button'):
                dpg.configure_item('join_print_button', enabled=True)

            dpg.set_value('Result_measure_ID', str(new_measure_id))

            filter_msg = (
                f"- Фильтр номеров: {len(numbers_filter)} шт.\n"
                if numbers_filter else
                "- Фильтр номеров: не задан\n"
            )
            only_good_msg = f"- Только годные: {'да' if only_good else 'нет'}\n"

            result_message = (
                f"Объединение успешно завершено.\n\n"
                f"Результаты:\n"
                f"- Новый протокол: {new_measure_id}\n"
                f"- Тип протокола: {psi_type}\n"
                f"- MSK: {msk_to_use if msk_to_use else 'не изменялся'}\n"
                f"- Программа: {program_type_to_use if program_type_to_use else 'не изменялась'}\n"
                f"- Оператор: {operator_to_use if operator_to_use else 'не изменялся'}\n"
                f"{filter_msg}{only_good_msg}"
                f"- Записей в psidata: {psi_count}\n"
                f"- Записей в psidatatemp: {temp_count}\n"
                f"- Обработано протоколов: {len(measure_ids)}\n\n"
                f"Доступны кнопки «Просмотр результата» и «Печать PDF».\n\n"
                f"Лог выполнения:\n{captured_output}"
            )
        else:
            dpg.set_value('Result_measure_ID', 'Ошибка')
            result_message = (
                f"Ошибка при создании нового протокола\n\n"
                f"Лог выполнения:\n{captured_output}"
            )

        dpg.set_value('join_data_result_log_process_window', result_message)

    except Exception as e:
        sys.stdout = old_stdout
        error_message = (
            f"Критическая ошибка:\n{str(e)}\n\n"
            f"Трассировка:\n{traceback.format_exc()}"
        )
        dpg.set_value('join_data_result_log_process_window', error_message)
        dpg.set_value("join_data_progress", 0.0)

def process_measure_ids_with_thread_1(measure_ids, dpg, msk, program_type,
                                     operator, change_data, psi_type='ОТК'):
    old_stdout = sys.stdout
    output_capture = StringIO()
    sys.stdout = output_capture

    try:
        dpg.set_value("join_data_progress", 0.1)
        dpg.set_value(
            'join_data_result_log_process_window',
            dpg.get_value('join_data_result_log_process_window') +
            "\nЗагружаю данные...",
        )

        if change_data == "Изменять данные":
            msk_to_use = msk if msk else None
            program_type_to_use = program_type if program_type else None
            operator_to_use = operator if operator else None
        else:
            msk_to_use = None
            program_type_to_use = None
            operator_to_use = None

        new_measure_id, psi_count, temp_count = process_measure_ids_with_copy(
            measure_ids,
            msk=msk_to_use,
            program_type=program_type_to_use,
            operator=operator_to_use,
            psi_type=psi_type,
        )

        sys.stdout = old_stdout
        captured_output = output_capture.getvalue()

        dpg.set_value("join_data_progress", 1.0)

        if new_measure_id:
            # ▼ NEW: сохранить параметры для просмотра / печати
            _join_state.update({
                'measure_id':   int(new_measure_id),
                'msk':          msk_to_use,
                'program_type': program_type_to_use,
                'operator':     operator_to_use,
                'psi_type':     psi_type,
            })
            if dpg.does_item_exist('join_preview_button'):
                dpg.configure_item('join_preview_button', enabled=True)
            if dpg.does_item_exist('join_print_button'):
                dpg.configure_item('join_print_button', enabled=True)

            dpg.set_value('Result_measure_ID', str(new_measure_id))
            result_message = (
                f"Объединение успешно завершено.\n\n"
                f"Результаты:\n"
                f"- Новый протокол: {new_measure_id}\n"
                f"- Тип протокола: {psi_type}\n"
                f"- MSK: {msk_to_use if msk_to_use else 'не изменялся'}\n"
                f"- Программа: {program_type_to_use if program_type_to_use else 'не изменялась'}\n"
                f"- Оператор: {operator_to_use if operator_to_use else 'не изменялся'}\n"
                f"- Записей в psidata: {psi_count}\n"
                f"- Записей в psidatatemp: {temp_count}\n"
                f"- Обработано протоколов: {len(measure_ids)}\n\n"
                f"Доступны кнопки «Просмотр результата» и «Печать PDF».\n\n"
                f"Лог выполнения:\n{captured_output}"
            )
        else:
            dpg.set_value('Result_measure_ID', 'Ошибка')
            result_message = (
                f"Ошибка при создании нового протокола\n\n"
                f"Лог выполнения:\n{captured_output}"
            )

        dpg.set_value('join_data_result_log_process_window', result_message)

    except Exception as e:
        sys.stdout = old_stdout
        error_message = (
            f"Критическая ошибка:\n{str(e)}\n\n"
            f"Трассировка:\n{traceback.format_exc()}"
        )
        dpg.set_value('join_data_result_log_process_window', error_message)
        dpg.set_value("join_data_progress", 0.0)


# ---------------------------------------------------------------------------
# Callback: предпросмотр результата объединения
# ---------------------------------------------------------------------------
def _on_join_preview(dpg):
    """Открыть окно просмотра для сохранённого протокола."""
    mid = _join_state.get('measure_id')
    if not mid:
        dpg.set_value('join_data_result_log_process_window',
                      "Предпросмотр недоступен: сначала выполните объединение.")
        return

    try:
        df = load_psidata_by_measure_id(mid)
    except Exception as e:
        traceback.print_exc()
        dpg.set_value('join_data_result_log_process_window',
                      f"Ошибка загрузки для предпросмотра: {e}")
        return

    if df is None or df.empty:
        dpg.set_value('join_data_result_log_process_window',
                      f"Нет данных в psidata для Measure_ID {mid}")
        return

    spc_name = ''
    if 'Spc' in df.columns:
        uniq = df['Spc'].dropna().unique()
        if len(uniq) > 0:
            spc_name = str(uniq[0])

    psi_type = _join_state.get('psi_type', 'ОТК')
    try:
        open_spec_preview(
            title=f"Результат объединения (Measure_ID {mid})",
            df=df,
            spc_name=spc_name,
            tag='join_merged_preview_window',
            note=(f"Протокол {mid} | тип {psi_type} | "
                  f"строк: {len(df)}"),
        )
    except Exception as e:
        traceback.print_exc()
        dpg.set_value('join_data_result_log_process_window',
                      f"Ошибка предпросмотра: {e}")


# ---------------------------------------------------------------------------
# Callback: печать PDF протокола объединения
# ---------------------------------------------------------------------------
def _on_join_print_pdf(dpg):
    """Сформировать PDF по сохранённому протоколу."""
    mid = _join_state.get('measure_id')
    if not mid:
        dpg.set_value('join_data_result_log_process_window',
                      "Печать недоступна: сначала выполните объединение.")
        return

    try:
        df = load_psidata_by_measure_id(mid)
    except Exception as e:
        traceback.print_exc()
        dpg.set_value('join_data_result_log_process_window',
                      f"Ошибка загрузки для печати: {e}")
        return

    if df is None or df.empty:
        dpg.set_value('join_data_result_log_process_window',
                      f"Нет данных в psidata для Measure_ID {mid}")
        return

    psi_type = _join_state.get('psi_type', 'ОТК')
    try:
        path = create_merged_protocol_pdf(
            merged_df=df,
            measure_id=mid,
            msk=_join_state.get('msk') or '-',
            file_name=None,
            program_type=_join_state.get('program_type'),
            operator=_join_state.get('operator'),
            psi_type=psi_type,
        )
        dpg.set_value(
            'join_data_result_log_process_window',
            f"PDF сохранён ({psi_type}): {path}\n"
            f"Measure_ID: {mid}",
        )
    except Exception as e:
        traceback.print_exc()
        dpg.set_value('join_data_result_log_process_window',
                      f"Ошибка печати PDF: {e}")


# ---------------------------------------------------------------------------
# Заполнение справочников
# ---------------------------------------------------------------------------
def fill_interface_data(dpg):
    try:
        from Options import get_connection_string
        from sqlalchemy import create_engine

        engine = create_engine(str(get_connection_string()))

        operators_query = ("SELECT DISTINCT Name FROM пользователи "
                           "WHERE Name IS NOT NULL ORDER BY Name")
        operators = pd.read_sql(operators_query, engine)['Name'].tolist()

        machines_query = ("SELECT DISTINCT Name FROM machines "
                          "WHERE Function = 'Measure' "
                          "AND Name IS NOT NULL ORDER BY Name")
        machines = pd.read_sql(machines_query, engine)['Name'].tolist()

        dpg.configure_item('operator_edit', items=operators)
        dpg.configure_item('machine_edit', items=machines)

    except Exception as e:
        print(f"Ошибка при загрузке данных интерфейса: {e}")