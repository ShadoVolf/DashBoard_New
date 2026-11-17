"""Интерфейс модуля совмещения протоколов (стандартная тёмная тема)."""
import threading
import traceback
from datetime import datetime

import pandas as pd
import dearpygui.dearpygui as dpg

from Temperature_Measure import _layout

from Temperature_Measure.unite_protokol.sort_logic import (
    load_resonator_types, load_specifications,
    load_msk_from_psidata, load_measure_ids_from_psidata,
    load_main_data, load_secondary_data, merge_psidata,
    load_old_data, merge_old, save_merged_protocol,
    load_psidata_by_measure_id,
    load_msk_from_old, load_measure_ids_from_old,
    load_old_ids_from_old,
    load_old_meta_by_measure_id, load_old_meta_by_old_id,
    search_msk_by_partial,
    search_measure_ids_by_msk_partial,
    search_measure_ids_by_number_partial,
    format_measure_combo_label,
    get_measure_summary,
    get_next_protocol_number,
    protocol_number_exists,
    find_secondary_measure_candidates,
    load_measure_psi_type,
    reserve_measure_id,          # ← NEW
    save_merged_rows,            # ← NEW
)
from Archive_View.Archive_Data import (
    load_measure_ids_by_msk, load_archive_by_measure_id,
)
from Temperature_Measure.unite_protokol.sort_report import (
    create_merged_protocol_pdf,
)
from Temperature_Measure.unite_protokol.preview_window import open_spec_preview


# ---------------------------------------------------------------------------
#            Ширины колонок формы (выравнивание через dpg.table)
# ---------------------------------------------------------------------------
_W_LABEL = 150
_W_COMBO = 270
_W_INPUT = 130
_W_OK = 55
_W_VIEW = 100


def _add_form_columns() -> None:
    """Пять колонок формы: label | combo | input | OK | Просмотр."""
    dpg.add_table_column(init_width_or_weight=_W_LABEL, width_fixed=True)
    dpg.add_table_column(init_width_or_weight=_W_COMBO, width_fixed=True)
    dpg.add_table_column(init_width_or_weight=_W_INPUT, width_fixed=True)
    dpg.add_table_column(init_width_or_weight=_W_OK,    width_fixed=True)
    dpg.add_table_column(init_width_or_weight=_W_VIEW,  width_fixed=True)


def _form_table(tag: str):
    """Обёртка над dpg.table для формы (используется в with)."""
    return dpg.table(
        tag=tag, header_row=False,
        policy=dpg.mvTable_SizingFixedFit,
        borders_innerH=False, borders_innerV=False,
        borders_outerH=False, borders_outerV=False,
        pad_outerX=False,
        no_pad_outerX=True,
    )


# ---------------------------------------------------------------------------
#                  Стандартная тёмная тема DearPyGui
# ---------------------------------------------------------------------------
def _apply_standard_dark_theme(tag_window: str) -> None:
    tag = "sort_std_dark_theme"
    if not dpg.does_item_exist(tag):
        with dpg.theme(tag=tag):
            with dpg.theme_component(dpg.mvAll):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (30, 30, 30))
                dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (26, 26, 26))
                dpg.add_theme_color(dpg.mvThemeCol_PopupBg, (32, 32, 32))
                dpg.add_theme_color(dpg.mvThemeCol_Border, (90, 90, 90))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBg, (55, 55, 55))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgHovered, (75, 75, 75))
                dpg.add_theme_color(dpg.mvThemeCol_FrameBgActive, (95, 95, 95))
                dpg.add_theme_color(dpg.mvThemeCol_TitleBg, (20, 20, 20))
                dpg.add_theme_color(dpg.mvThemeCol_TitleBgActive, (45, 45, 45))
                dpg.add_theme_color(dpg.mvThemeCol_Button, (65, 65, 65))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (85, 85, 85))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (105, 105, 105))
                dpg.add_theme_color(dpg.mvThemeCol_Header, (55, 55, 55))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderHovered, (75, 75, 75))
                dpg.add_theme_color(dpg.mvThemeCol_HeaderActive, (95, 95, 95))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (230, 230, 230))
                dpg.add_theme_color(dpg.mvThemeCol_TextDisabled, (150, 150, 150))
                dpg.add_theme_color(dpg.mvThemeCol_Separator, (90, 90, 90))
    dpg.bind_item_theme(tag_window, tag)

def _load_spc_map_for_ui(spc_name: str, psi_type: str):
    """Нормы для отображения в UI по типу протокола.

    Для ОТК возвращает Max/Min, подменённые на Max_otk/Min_otk,
    чтобы таблица норм показывала именно ОТК-границы.
    """
    try:
        from Archive_View.Archive_Data import load_spc_map_for_archive
        from Archive_View.Archive_Helpers import load_spc_map_otk_for_archive
    except ImportError:
        print()


    if psi_type == 'ОТК':
        spc_map = load_spc_map_otk_for_archive(spc_name)
        if spc_map is not None and not spc_map.empty:
            spc_map = spc_map.copy()
            if 'Max_otk' in spc_map.columns:
                spc_map['Max'] = spc_map['Max_otk']
            if 'Min_otk' in spc_map.columns:
                spc_map['Min'] = spc_map['Min_otk']
        return spc_map
    return load_spc_map_for_archive(spc_name)

# ---------------------------------------------------------------------------
class SortResultWindow:
    def __init__(self, dpg_context, parent=None):
        self.dpg = dpg_context
        self.parent = parent
        self.window_tag = "sort_result_window"

        self._loaded = {"main": None, "secondary": None, "old": None}
        self._merged_df = None
        self._protocol_number = None
        #self._last_saved_id = None
        self._measure_id = None
        self._suppress_cascade = False

        self._init_ui()
        self._load_initial_data()
        self._source_ids = {}

        # ------------------------------------------------------------------ UI
    def _init_ui(self):
        pos, size = _layout.dialog_rect(
            fraction_w=0.66, fraction_h=0.88,
            min_w=880, min_h=680, max_w=1060, max_h=1040,
        )
        with dpg.window(label="Создание нового протокола (совмещение)",
                        tag=self.window_tag, width=size[0], height=size[1],
                        pos=pos, no_collapse=True):
            with dpg.child_window(height=-160, border=False):
                self._build_content()

            dpg.add_separator()
            with dpg.group(horizontal=True):
                dpg.add_button(label="Объединить", tag="btnMerge",
                               callback=self.on_merge, width=170, height=30)
                dpg.add_button(label="Сохранить в БД", tag="btnSaveToDb",
                               callback=self.on_save_to_db, enabled=False,
                               width=170, height=30)
                dpg.add_button(label="Очистить", tag="btnClear",
                               callback=self.on_clear, width=110, height=30)
                dpg.add_button(label="Закрыть", tag="btnClose",
                               callback=self.on_close, width=110, height=30)
            dpg.add_progress_bar(tag="progress", default_value=0.0,
                                 width=-1, height=8)

        _apply_standard_dark_theme(self.window_tag)

    # --------------------------------------------------------- форма
    def _build_content(self):
        # ---- Поиск замера (основной замер) ----
        with dpg.collapsing_header(
                label="Поиск замера (основной замер)",
                default_open=True, closable=False,
                tag='sort_search_header'):
            self._build_search_panel()
        dpg.add_separator()

        # ---- Тип ----
        with _form_table("form_type"):
            _add_form_columns()
            with dpg.table_row():
                dpg.add_text("Тип резонатора")
                dpg.add_combo(tag="edtType", width=-1,
                              callback=self.on_type_change)
                dpg.add_text("")
                dpg.add_text("")
                dpg.add_text("")
        dpg.add_separator()

        # ---- Основной замер ----
        dpg.add_text("Основной замер (интервал температур)")
        with _form_table("form_main"):
            _add_form_columns()
            with dpg.table_row():
                dpg.add_text("Спецификация")
                dpg.add_combo(tag="edtSpc", width=-1,
                              callback=self.on_spc_change)
                dpg.add_text("")
                dpg.add_text("")
                dpg.add_text("")
            self._row_msk_mid(
                "main", "edtMsk", "cmb_ID",
                "edtMskInput", "cmb_IDInput",
            )
        dpg.add_separator()

        # ---- Дополнительный замер ----
        dpg.add_checkbox(
            label="Дополнительный замер (температура настройки)",
            tag="chkUse1", default_value=True)
        dpg.add_checkbox(
            label="Автоподбор замера по номерам резонаторов основного замера",
            tag="chk_auto_secondary", default_value=False,
            callback=self.on_auto_secondary_toggle,
        )
        with _form_table("form_secondary"):
            _add_form_columns()
            with dpg.table_row():
                dpg.add_text("Спецификация")
                dpg.add_combo(tag="edtSpc1", width=-1,
                              callback=self.on_spc1_change)
                dpg.add_text("")
                dpg.add_text("")
                dpg.add_text("")
            self._row_msk_mid(
                "secondary", "edtMsk1", "cmb_ID1",
                "edtMskInput1", "cmb_IDInput1",
            )
        dpg.add_checkbox(label="Добавить нежелательные резонансы",
                         tag="chk_add_spur")
        dpg.add_checkbox(
            label="Только нежелательные резонансы "
                  "(без F, R, C0, Cq, L, Q)",
            tag="chk_only_spur")
        dpg.add_separator()

        # ---- Старение ----
        dpg.add_checkbox(label="Старение", tag="chkUse2",
                         default_value=False)
        with _form_table("form_old"):
            _add_form_columns()
            self._row_msk_mid(
                "old", "edtMsk2", "cmb_ID2",
                "edtMskInput2", "cmb_IDInput2",
            )
            with dpg.table_row():
                dpg.add_text("ID старения")
                dpg.add_combo(tag="cmb_id3", width=-1,
                              callback=self.on_old_id_change)
                dpg.add_text("")
                dpg.add_text("")
                dpg.add_button(label="Просмотр", width=-1,
                               user_data="old",
                               callback=lambda s, a, u: self._preview_source(u, s))
        dpg.add_radio_button(
            items=["Старение 1", "Старение 2", "Старение 3"],
            tag="aging_type", default_value="Старение 1",
            horizontal=True,
        )
        dpg.add_separator()

        # ---- Данные нового протокола ----
        dpg.add_text("Данные нового протокола")
        with _form_table("form_new"):
            _add_form_columns()
            with dpg.table_row():
                dpg.add_text("Тип программы")
                dpg.add_input_text(tag="program_type", width=-1)
                dpg.add_text("")
                dpg.add_text("")
                dpg.add_text("")
            with dpg.table_row():
                dpg.add_text("Оператор")
                dpg.add_input_text(tag="operator", width=-1)
                dpg.add_text("")
                dpg.add_text("")
                dpg.add_text("")
            with dpg.table_row():
                dpg.add_text("Имя файла")
                dpg.add_input_text(tag="sort_file_name", width=-1)
                dpg.add_text("")
                dpg.add_text("")
                dpg.add_text("")
            # ▼ НОВАЯ СТРОКА: тип протокола + кнопка «Спецификация»
            with dpg.table_row():
                dpg.add_text("Тип протокола")
                dpg.add_combo(
                    ['ПСИ', 'ОТК'], tag="psi_type", width=-1,
                    default_value='ОТК',
                )
                dpg.add_text("")
                dpg.add_text("")
                dpg.add_button(
                    label="Спецификация", width=-1,
                    callback=lambda s, a: self._on_view_spec(),
                )
        dpg.add_separator()

        # ---- Результат ----
        dpg.add_text("Результат совмещения")
        with dpg.group(horizontal=True):
            dpg.add_text("Статус:", color=(180, 180, 180))
            dpg.add_text("-", tag="merge_status_text")
        with dpg.group(horizontal=True):
            dpg.add_text("Measure_ID:", color=(180, 180, 180))
            dpg.add_text("-", tag="merge_protocol_text",
                         color=(150, 150, 150))
        with dpg.group(horizontal=True):
            dpg.add_button(label="Просмотр результата",
                           tag="btnOpenMerged",
                           callback=self._open_merged_window,
                           enabled=False, width=180)
            dpg.add_button(label="Печать PDF", tag="btnPrintPdf",
                           callback=self.on_print_pdf,
                           enabled=False, width=140)
        with dpg.group(horizontal=True):
            dpg.add_text("Результат:", color=(180, 180, 180))
            dpg.add_text("-", tag="merge_result_text",
                         color=(140, 200, 140))

    # --------------------------------------------------- панель поиска
    def _build_search_panel(self):
        """Поиск замеров по частичному МСК и по номеру резонатора.

        Результат выбора сразу заполняет edtType → edtSpc → edtMsk → cmb_ID
        (через существующий _on_mid_direct, без дублирования логики).
        """
        # ---------------- Поиск по МСК ----------------
        dpg.add_text("Поиск по МСК:", color=(200, 220, 255))
        with dpg.group(horizontal=True):
            dpg.add_input_text(
                tag='sort_search_msk_input', width=240,
                hint='456  |  25-2456',
                on_enter=True,
                callback=lambda: self._on_search_msk(),
            )
            dpg.add_button(label='Найти МСК', width=110,
                           callback=lambda: self._on_search_msk())
        with dpg.group(horizontal=True):
            dpg.add_text("МСК:", color=(180, 200, 230))
            dpg.add_combo([], tag='sort_search_msk_combo', width=260,
                          callback=lambda: self._on_search_msk_selected())
            dpg.add_text("Замер:", color=(180, 200, 230))
            dpg.add_combo([], tag='sort_search_mid_by_msk_combo',
                          width=420,
                          callback=self._on_search_mid_selected)

        dpg.add_spacer(height=6)

        # ---------------- Поиск по номеру резонатора ----------------
        dpg.add_text("Поиск по номеру резонатора:",
                     color=(200, 220, 255))
        with dpg.group(horizontal=True):
            dpg.add_input_text(
                tag='sort_search_number_input', width=240,
                hint='SU8525  |  8525  |  SU85',
                on_enter=True,
                callback=lambda: self._on_search_number(),
            )
            dpg.add_button(label='Найти', width=110,
                           callback=lambda: self._on_search_number())
        with dpg.group(horizontal=True):
            dpg.add_text("Найденные:", color=(180, 200, 230))
            dpg.add_combo([], tag='sort_search_mid_by_number_combo',
                          width=520,
                          callback=self._on_search_mid_selected)

        dpg.add_spacer(height=4)
        with dpg.group(horizontal=True):
            dpg.add_text("Информация:", color=(200, 220, 255))
            dpg.add_text("-", tag='sort_search_info',
                         color=(180, 200, 230))
        dpg.add_text(
            'Выбор замера автоматически заполнит Тип / Спецификацию / '
            'МСК / ID основного замера',
            color=(140, 140, 140),
        )

    # ------------------------------------ поиск: обработчики
    def _on_search_msk(self):
        partial = (dpg.get_value('sort_search_msk_input') or '').strip()
        if not partial:
            return
        self._set_search_info(f'Поиск МСК "{partial}"...')
        try:
            msks = search_msk_by_partial(partial)
        except Exception as e:
            print(f'[sort_gui] MSK search error: {e}')
            traceback.print_exc()
            self._set_search_info(f'Ошибка поиска МСК: {e}')
            return

        dpg.configure_item('sort_search_msk_combo', items=msks)
        if msks:
            dpg.set_value('sort_search_msk_combo', msks[0])
            self._on_search_msk_selected()
        else:
            dpg.configure_item('sort_search_mid_by_msk_combo', items=[])
            dpg.set_value('sort_search_mid_by_msk_combo', '')
            self._set_search_info(f'МСК по "{partial}" не найдены')

    def _on_search_msk_selected(self):
        msk = dpg.get_value('sort_search_msk_combo')
        if not msk:
            return
        self._set_search_info(f'Загрузка замеров для МСК "{msk}"...')
        try:
            df = search_measure_ids_by_msk_partial(msk)
        except Exception as e:
            print(f'[sort_gui] MSK measure ids error: {e}')
            traceback.print_exc()
            self._set_search_info(f'Ошибка загрузки замеров: {e}')
            return

        items = [format_measure_combo_label(r) for _, r in df.iterrows()]
        dpg.configure_item('sort_search_mid_by_msk_combo', items=items)
        if items:
            dpg.set_value('sort_search_mid_by_msk_combo', items[0])
        else:
            dpg.set_value('sort_search_mid_by_msk_combo', '')
            self._set_search_info(f'Для МСК "{msk}" замеры не найдены')

    def _on_search_number(self):
        partial = (dpg.get_value('sort_search_number_input')
                   or '').strip()
        if not partial:
            return
        self._set_search_info(f'Поиск по номеру "{partial}"...')
        try:
            df = search_measure_ids_by_number_partial(partial)
        except Exception as e:
            print(f'[sort_gui] number search error: {e}')
            traceback.print_exc()
            self._set_search_info(f'Ошибка поиска: {e}')
            return

        items = [format_measure_combo_label(r) for _, r in df.iterrows()]
        dpg.configure_item('sort_search_mid_by_number_combo', items=items)
        if items:
            dpg.set_value('sort_search_mid_by_number_combo', items[0])
        else:
            dpg.set_value('sort_search_mid_by_number_combo', '')
            self._set_search_info(
                f'По номеру "{partial}" ничего не найдено')

    def _on_search_mid_selected(self, sender=None, app_data=None):
        """Combo выбора замера — заполнить основной замер."""
        label = app_data if app_data else (
            dpg.get_value(sender) if sender else None)
        mid = self._extract_mid_from_label(label)
        if not mid:
            return

        # Записываем в поле ручного ввода и запускаем существующий
        # каскад (_on_mid_direct заполнит Тип / Spc / МСК / combo ID).
        self._suppress_cascade = True
        try:
            dpg.set_value(self._mid_input_tag("main"), mid)
        finally:
            self._suppress_cascade = False

        self._on_mid_direct("main")
        self._show_measure_info(mid)

    @staticmethod
    def _extract_mid_from_label(label):
        if not label:
            return None
        try:
            return str(int(str(label).split('|')[0].strip()))
        except (ValueError, IndexError):
            return None

    def _get_mid_from_combo(self, combo_tag):
        """Возвращает целочисленный Measure_ID из combo.

        Поддерживает оба вида значений:
          * int (обычный режим — из load_measure_ids_*)
          * str '253799 | N=SU8525 | ...' (режим автоподбора)
        """
        raw = dpg.get_value(combo_tag)
        if raw is None or raw == "":
            return None
        if isinstance(raw, int):
            return raw
        s = self._extract_mid_from_label(raw)
        if s is None:
            return None
        try:
            return int(s)
        except (ValueError, TypeError):
            return None

    def _show_measure_info(self, mid):
        try:
            info = get_measure_summary(mid)
        except Exception as e:
            print(f'[sort_gui] get_measure_summary error: {e}')
            self._set_search_info(f'Ошибка сводки: {e}')
            return
        if not info:
            self._set_search_info(f'Measure_ID {mid} не найден')
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
        self._set_search_info(" | ".join(parts))

    def _set_search_info(self, message):
        if dpg.does_item_exist('sort_search_info'):
            dpg.set_value('sort_search_info', str(message))

    def _row_msk_mid(self, key, msk_tag, mid_tag,
                     msk_input_tag, mid_input_tag):
        msk_cb = {
            "main": self.on_msk_change,
            "secondary": self.on_msk1_change,
            "old": self.on_msk2_change,
        }[key]
        id_cb = {
            "main": self.on_id_change,
            "secondary": self.on_id1_change,
            "old": self.on_id2_change,
        }[key]

        # Строка МСК
        with dpg.table_row():
            dpg.add_text("МСК")
            dpg.add_combo(tag=msk_tag, width=-1, callback=msk_cb)
            dpg.add_input_text(tag=msk_input_tag, width=-1,
                               hint="МСК вручную...", on_enter=True,
                               user_data=key,
                               callback=lambda s, a, u: self._on_msk_direct(u, s))
            dpg.add_button(label="OK", width=-1, user_data=key,
                           callback=lambda s, a, u: self._on_msk_direct(u, s))
            dpg.add_text("")

        # Строка ID замера
        with dpg.table_row():
            dpg.add_text("ID замера")
            dpg.add_combo(tag=mid_tag, width=-1, callback=id_cb)
            dpg.add_input_text(tag=mid_input_tag, width=-1,
                               decimal=True, hint="ID вручную...",
                               on_enter=True, user_data=key,
                               callback=lambda s, a, u: self._on_mid_direct(u, s))
            dpg.add_button(label="OK", width=-1, user_data=key,
                           callback=lambda s, a, u: self._on_mid_direct(u, s))
            dpg.add_button(label="Просмотр", width=-1, user_data=key,
                           callback=lambda s, a, u: self._preview_source(u, s))

    # ------------------------------------------------------ tag-утилиты
    @staticmethod
    def _msk_input_tag(key):
        return {"main": "edtMskInput",
                "secondary": "edtMskInput1",
                "old": "edtMskInput2"}[key]

    @staticmethod
    def _mid_input_tag(key):
        return {"main": "cmb_IDInput",
                "secondary": "cmb_IDInput1",
                "old": "cmb_IDInput2"}[key]

    @staticmethod
    def _msk_combo_tag(key):
        return {"main": "edtMsk",
                "secondary": "edtMsk1",
                "old": "edtMsk2"}[key]

    @staticmethod
    def _mid_combo_tag(key):
        return {"main": "cmb_ID",
                "secondary": "cmb_ID1",
                "old": "cmb_ID2"}[key]

    @staticmethod
    def _spc_tag(key):
        return {"main": "edtSpc", "secondary": "edtSpc1", "old": "edtSpc"}[key]

    def _resolve_key(self, key, sender=None):
        if key in ("main", "secondary", "old"):
            return key
        s = str(sender or "")
        if s.endswith("Input1") or s in ("edtMsk1", "cmb_ID1"):
            return "secondary"
        if s.endswith("Input2") or s in ("edtMsk2", "cmb_ID2", "cmb_id3"):
            return "old"
        return "main"

    # ---------------------------------------------- прямые вводы
    def _on_msk_direct(self, key=None, sender=None):
        key = self._resolve_key(key, sender)
        print(f"[debug] _on_msk_direct: key={key!r}, sender={sender!r}")

        tag = self._msk_input_tag(key)
        if not dpg.does_item_exist(tag):
            return
        msk = (dpg.get_value(tag) or "").strip()
        if not msk:
            return

        dpg.set_value(self._msk_combo_tag(key), msk)

        if key == "old":
            self.on_msk2_change()
            return

        try:
            ids = load_measure_ids_by_msk(msk)
            dpg.configure_item(self._mid_combo_tag(key), items=ids)
            dpg.set_value(self._mid_combo_tag(key), ids[0] if ids else "")
        except Exception as e:
            self._show_error(f"Ошибка поиска ID по МСК: {e}")

    def _on_mid_direct(self, key=None, sender=None):
        key = self._resolve_key(key, sender)
        print(f"[debug] _on_mid_direct: key={key!r}, sender={sender!r}")

        tag = self._mid_input_tag(key)
        if not dpg.does_item_exist(tag):
            return
        raw = (dpg.get_value(tag) or "").strip()
        if not raw.isdigit():
            self._show_error("ID должен быть числом")
            return
        mid = int(raw)

        if key == "old":
            # как cmb_ID2KeyPress в оригинале:
            # по MeasureID подтягиваем Msk2 и список Old_ID
            dpg.set_value(self._mid_combo_tag(key), mid)
            meta = load_old_meta_by_measure_id(mid)
            print(f"[old] _on_mid_direct meta: {meta}")
            if meta.get("msk"):
                dpg.set_value("edtMsk2", meta["msk"])
            self.on_id2_change()
            return

        try:
            info = load_archive_by_measure_id(mid)
            if info is None:
                self._show_error(f"Замер с ID {mid} не найден")
                return
        except Exception as e:
            self._show_error(f"Ошибка загрузки ID: {e}")
            return

        self._suppress_cascade = True
        try:
            if info.get("rtype"):
                dpg.set_value("edtType", info["rtype"])
                specs = load_specifications(info["rtype"])
                dpg.configure_item("edtSpc", items=specs)
                dpg.configure_item("edtSpc1", items=specs)

            if info.get("spc"):
                dpg.set_value(self._spc_tag(key), info["spc"])

            if info.get("msk"):
                dpg.set_value(self._msk_combo_tag(key), info["msk"])
                ids = load_measure_ids_by_msk(info["msk"])
                dpg.configure_item(self._mid_combo_tag(key), items=ids)
                dpg.set_value(self._mid_combo_tag(key),
                              mid if mid in ids else "")
            else:
                dpg.set_value(self._mid_combo_tag(key), mid)

            dpg.set_value(self._mid_input_tag(key), str(mid))
        finally:
            self._suppress_cascade = False

        if key == "main":
            try:
                psi_type = load_measure_psi_type(mid)
                if dpg.does_item_exist("psi_type"):
                    dpg.set_value("psi_type", psi_type)
            except Exception as e:
                print(f"[sort_gui] load_measure_psi_type error: {e}")

        # --- автоподбор доп. замера ---
        if key == "main" and dpg.get_value("chk_auto_secondary"):
            self._refresh_secondary_candidates()

    # ------------------------------------------------------------ старт
    def _load_initial_data(self):
        try:
            types = load_resonator_types()
            dpg.configure_item("edtType", items=types)
            if types:
                dpg.set_value("edtType", types[0])
                self.on_type_change()
        except Exception as e:
            self._show_error(f"Ошибка загрузки типов: {e}")

    # ---------------------------------------------------------- обработчики
    def on_type_change(self, sender=None, app_data=None):
        if self._suppress_cascade:
            return
        res_type = dpg.get_value("edtType")
        if not res_type:
            return
        try:
            specs = load_specifications(res_type)
            dpg.configure_item("edtSpc", items=specs)
            dpg.configure_item("edtSpc1", items=specs)
            if specs:
                dpg.set_value("edtSpc", specs[0])
                dpg.set_value("edtSpc1", specs[0])
                self.on_spc_change()
                self.on_spc1_change()
        except Exception as e:
            self._show_error(f"Ошибка загрузки спецификаций: {e}")

    def on_spc_change(self, sender=None, app_data=None):
        if self._suppress_cascade:
            return
        spc = dpg.get_value("edtSpc")
        if not spc:
            return
        try:
            msks = load_msk_from_psidata(spc)
            dpg.configure_item("edtMsk", items=msks)
            if msks:
                dpg.set_value("edtMsk", msks[0])
                self.on_msk_change()
            else:
                ids = load_measure_ids_from_psidata(spc)
                dpg.configure_item("cmb_ID", items=ids)
                if ids:
                    dpg.set_value("cmb_ID", ids[0])
        except Exception as e:
            self._show_error(f"Ошибка загрузки MSK: {e}")
            return

        # --- Заполнить блок старения из old (как в edtSpcChange оригинала) ---
        self._load_old_combos(spc)

    def _load_old_combos(self, spc):
        """edtSpcChange оригинала: заполнить Msk2 / ID2 / Old_ID из old по Spc."""
        print(f"[old] _load_old_combos: spc={spc!r}")
        self._suppress_cascade = True
        try:
            msks = load_msk_from_old(spc)
            dpg.configure_item("edtMsk2", items=msks)
            dpg.set_value("edtMsk2", msks[0] if msks else "")

            mids = load_measure_ids_from_old(spc=spc)
            dpg.configure_item("cmb_ID2", items=mids)
            dpg.set_value("cmb_ID2", mids[0] if mids else "")

            old_ids = load_old_ids_from_old(spc=spc)
            dpg.configure_item("cmb_id3", items=old_ids)
            dpg.set_value("cmb_id3", old_ids[0] if old_ids else "")

            print(f"[old] spc={spc!r} -> "
                  f"msk={len(msks)}, mid={len(mids)}, old_id={len(old_ids)}")
        finally:
            self._suppress_cascade = False

    def on_msk_change(self, sender=None, app_data=None):
        if self._suppress_cascade:
            return
        spc = dpg.get_value("edtSpc")
        msk = dpg.get_value("edtMsk") or None
        try:
            ids = load_measure_ids_from_psidata(spc, msk)
            dpg.configure_item("cmb_ID", items=ids)
            if ids:
                dpg.set_value("cmb_ID", ids[0])
        except Exception as e:
            self._show_error(f"Ошибка загрузки ID: {e}")

    def on_id_change(self, sender=None, app_data=None):
        if dpg.get_value("chk_auto_secondary"):
            self._refresh_secondary_candidates()

    def on_spc1_change(self, sender=None, app_data=None):
        if self._suppress_cascade:
            return
        if dpg.get_value("chk_auto_secondary"):
            return  # управляется _refresh_secondary_candidates
        spc = dpg.get_value("edtSpc1")
        if not spc:
            return
        try:
            msks = load_msk_from_psidata(spc)
            dpg.configure_item("edtMsk1", items=msks)
            if msks:
                dpg.set_value("edtMsk1", msks[0])
                self.on_msk1_change()
            else:
                ids = load_measure_ids_from_psidata(spc)
                dpg.configure_item("cmb_ID1", items=ids)
                if ids:
                    dpg.set_value("cmb_ID1", ids[0])
        except Exception as e:
            self._show_error(f"Ошибка загрузки MSK (доп): {e}")

    def on_msk1_change(self, sender=None, app_data=None):
        if self._suppress_cascade:
            return
        if dpg.get_value("chk_auto_secondary"):
            return
        spc = dpg.get_value("edtSpc1")
        msk = dpg.get_value("edtMsk1") or None
        try:
            ids = load_measure_ids_from_psidata(spc, msk)
            dpg.configure_item("cmb_ID1", items=ids)
            if ids:
                dpg.set_value("cmb_ID1", ids[0])
        except Exception as e:
            self._show_error(f"Ошибка загрузки ID (доп): {e}")

    def on_id1_change(self, sender=None, app_data=None):
        pass

    # ------------------------------------- автоподбор доп. замера
    def on_auto_secondary_toggle(self, sender=None, app_data=None):
        if app_data:
            if not self._get_mid_from_combo("cmb_ID"):
                self._show_error(
                    "Сначала выберите основной замер — "
                    "автоподбор ищет по его номерам резонаторов."
                )
                dpg.set_value("chk_auto_secondary", False)
                return
            self._refresh_secondary_candidates()
        else:
            # Возврат к обычной фильтрации по Spc/Msk
            self.on_spc1_change()
            self.on_msk1_change()

    def _refresh_secondary_candidates(self):
        """Заполнить cmb_ID1 замерами, где есть N из основного."""
        mid = self._get_mid_from_combo("cmb_ID")
        if not mid:
            return
        try:
            df = find_secondary_measure_candidates(mid)
        except Exception as e:
            print(f"[sort_gui] secondary auto-search error: {e}")
            traceback.print_exc()
            self._show_error(f"Автоподбор не удался: {e}")
            return

        items = [format_measure_combo_label(r) for _, r in df.iterrows()]
        dpg.configure_item("cmb_ID1", items=items)
        if items:
            dpg.set_value("cmb_ID1", items[0])
        else:
            dpg.set_value("cmb_ID1", "")

    # ---------------------------------------------- старое (old) combo
    def on_msk2_change(self, sender=None, app_data=None):
        if self._suppress_cascade:
            return
        msk = dpg.get_value("edtMsk2") or None
        print(f"[old] on_msk2_change: msk={msk!r}")
        try:
            mids = load_measure_ids_from_old(msk=msk)
            dpg.configure_item("cmb_ID2", items=mids)
            if mids:
                dpg.set_value("cmb_ID2", mids[0])

            old_ids = load_old_ids_from_old(msk=msk)
            dpg.configure_item("cmb_id3", items=old_ids)
            if old_ids:
                dpg.set_value("cmb_id3", old_ids[0])
        except Exception as e:
            self._show_error(f"Ошибка загрузки ID (старение): {e}")

    def on_id2_change(self, sender=None, app_data=None):
        if self._suppress_cascade:
            return
        msk = dpg.get_value("edtMsk2") or None
        mid = self._get_mid_from_combo("cmb_ID2")
        print(f"[old] on_id2_change: msk={msk!r}, mid={mid!r}")

        # подтянуть Msk2 из old, если он пуст (как cmb_ID2KeyPress)
        if mid and not msk:
            meta = load_old_meta_by_measure_id(mid)
            if meta.get("msk"):
                dpg.set_value("edtMsk2", meta["msk"])
                msk = meta["msk"]
            print(f"[old] on_id2_change meta: {meta}")

        try:
            old_ids = load_old_ids_from_old(msk=msk, measure_id=mid)
            dpg.configure_item("cmb_id3", items=old_ids)
            if old_ids:
                dpg.set_value("cmb_id3", old_ids[0])
        except Exception as e:
            self._show_error(f"Ошибка загрузки Old_ID: {e}")

    def on_old_id_change(self, sender=None, app_data=None):
        if self._suppress_cascade:
            return
        old_id = dpg.get_value("cmb_id3") or None
        if not old_id:
            return
        print(f"[old] on_old_id_change: old_id={old_id!r}")

        meta = load_old_meta_by_old_id(old_id)
        print(f"[old] on_old_id_change meta: {meta}")

        self._suppress_cascade = True
        try:
            if meta.get("msk"):
                dpg.set_value("edtMsk2", meta["msk"])
            if meta.get("measure_id") is not None:
                dpg.set_value("cmb_ID2", meta["measure_id"])
        finally:
            self._suppress_cascade = False

    # ---------------------------------------------------------- просмотр
    def _spc_for_block(self, key):
        if key == "main":
            return dpg.get_value("edtSpc") or ""
        if key == "secondary":
            return dpg.get_value("edtSpc1") or ""
        return ""

    def _preview_source(self, key=None, sender=None):
        key = self._resolve_key(key, sender)
        print(f"[preview] _preview_source: key={key!r}, sender={sender!r}")

        if key == "secondary" and not dpg.get_value("chkUse1"):
            self._show_error(
                "Дополнительный замер отключён.\n"
                "Поставьте флажок «Дополнительный замер» "
                "и нажмите «Просмотр» ещё раз."
            )
            return
        if key == "old" and not dpg.get_value("chkUse2"):
            self._show_error(
                "Старение отключено.\n"
                "Поставьте флажок «Старение» "
                "и нажмите «Просмотр» ещё раз."
            )
            return

        if not self._load_sources(show_errors=True):
            return

        df = self._loaded.get(key)
        print(f"[preview] _preview_source: "
              f"self._loaded['{key}'] = "
              f"{None if df is None else len(df)} строк")

        if df is None or df.empty:
            titles = {
                "main": "Основной замер",
                "secondary": "Дополнительный замер",
                "old": "Старение",
            }
            name = titles.get(key, key)
            self._show_error(
                f"{name}: нет данных по выбранным фильтрам.\n"
                f"Measure_ID={dpg.get_value(self._mid_combo_tag(key))!r}, "
                f"МСК={dpg.get_value(self._msk_combo_tag(key))!r}"
            )
            return

        titles = {
            "main": "Основной замер",
            "secondary": "Дополнительный замер",
            "old": "Старение",
        }
        open_spec_preview(
            title=titles.get(key, key),
            df=df,
            spc_name=self._spc_for_block(key),
            tag=f"src_preview_{key}",
            note=f"Источник: {titles.get(key, key)}",
        )

    def _load_sources(self, show_errors=False):
        spc = dpg.get_value("edtSpc") or None
        msk = dpg.get_value("edtMsk") or None
        mid = self._get_mid_from_combo("cmb_ID")

        if not mid:
            if show_errors:
                self._show_error("Не выбран ID замера")
            return False

        df_main = self._load_with_fallback(
            spc=spc, msk=msk, mid=mid, label="main")
        if df_main is None or df_main.empty:
            if show_errors:
                self._show_error(
                    f"Не удалось загрузить основной замер\n"
                    f"(Measure_ID={mid!r}, Spc={spc!r}, Msk={msk!r}).\n"
                    f"Проверьте, что замер существует в базе."
                )
            return False
        self._loaded["main"] = df_main

        if dpg.get_value("chkUse1"):
            spc2 = dpg.get_value("edtSpc1") or None
            msk2 = dpg.get_value("edtMsk1") or None
            mid2 = self._get_mid_from_combo("cmb_ID1")
            if mid2:
                self._loaded["secondary"] = self._load_with_fallback(
                    spc=spc2, msk=msk2, mid=mid2, label="secondary")
            else:
                self._loaded["secondary"] = None
        else:
            self._loaded["secondary"] = None

        if dpg.get_value("chkUse2"):
            self._loaded["old"] = self._load_old_sources()
        else:
            self._loaded["old"] = None

        return True

    def _load_old_sources(self):
        """Загрузка old. Соответствует btnSetClick в оригинале:
           фильтры Msk AND MeasureID AND Old_ID (непустые).
        """
        msk_o = dpg.get_value("edtMsk2") or None
        mid_o = self._get_mid_from_combo("cmb_ID2")
        old_id = dpg.get_value("cmb_id3") or None
        print(f"[old] _load_old_sources: msk={msk_o!r}, "
              f"mid={mid_o!r}, old_id={old_id!r}")

        # 1) основной вариант — все три фильтра
        if msk_o or mid_o or old_id:
            df = load_old_data(msk_o, mid_o, old_id)
            print(f"[old] [msk+mid+old_id]: {len(df)} строк")
            if not df.empty:
                return df

        # 2) fallback'и, если оператор не нажал Enter в каком-то поле
        if old_id:
            df = load_old_data(None, None, old_id)
            print(f"[old] [только old_id={old_id!r}]: {len(df)} строк")
            if not df.empty:
                return df
        if mid_o:
            df = load_old_data(None, mid_o, None)
            print(f"[old] [только mid={mid_o!r}]: {len(df)} строк")
            if not df.empty:
                return df
        if msk_o:
            df = load_old_data(msk_o, None, None)
            print(f"[old] [только msk={msk_o!r}]: {len(df)} строк")
            if not df.empty:
                return df

        print("[old] все варианты пусты")
        return pd.DataFrame()

    def _load_with_fallback(self, spc, msk, mid, label="main"):
        """Загрузка с fallback-цепочкой:
           1. spc+msk+id
           2. spc+id
           3. msk+id (если spc нет)
           4. только id
        """
        df = pd.DataFrame()

        if spc:
            df = load_main_data(spc, msk, mid)
            print(f"[preview] {label} [spc+msk+id]: {len(df)} строк")
            if not df.empty:
                return df

            df = load_main_data(spc, None, mid)
            print(f"[preview] {label} [spc+id]: {len(df)} строк")
            if not df.empty:
                return df
        else:
            df = load_main_data(None, msk, mid)
            print(f"[preview] {label} [msk+id]: {len(df)} строк")
            if not df.empty:
                return df

        df = load_psidata_by_measure_id(mid)
        print(f"[preview] {label} [только id={mid!r}]: {len(df)} строк")
        return df

    # ---------------------------------------------------------- слияние
    def on_merge(self):
        spc_main = dpg.get_value("edtSpc")
        msk_main = dpg.get_value("edtMsk") or ""
        id_main = self._get_mid_from_combo("cmb_ID")
        if not spc_main or not id_main:
            self._show_error("Заполните основной замер")
            return

        # ▼ Собираем источники → Notes
        source_ids = {'main': id_main}
        if dpg.get_value("chkUse1"):
            mid2 = self._get_mid_from_combo("cmb_ID1")
            if mid2:
                source_ids['secondary'] = mid2
        if dpg.get_value("chkUse2"):
            mid3 = self._get_mid_from_combo("cmb_ID2")
            if mid3:
                source_ids['old'] = mid3
        self._source_ids = source_ids
        notes = self._build_notes()

        # ▼ Параметры заголовка фиксируем до запуска потока
        program_type = dpg.get_value("program_type") or None
        operator_name = dpg.get_value("operator") or None
        file_name = dpg.get_value("sort_file_name") or None

        self._merged_df = None
        self._protocol_number = None
        self._measure_id = None

        dpg.configure_item("btnMerge", enabled=False)
        dpg.configure_item("btnSaveToDb", enabled=False)
        dpg.configure_item("btnPrintPdf", enabled=False)
        dpg.configure_item("btnOpenMerged", enabled=False)
        dpg.set_value("progress", 0.0)
        dpg.set_value("merge_status_text", "Выполняется...")
        dpg.set_value("merge_protocol_text", "-")
        dpg.set_value("merge_result_text", "-")

        def task():
            try:
                dpg.set_value("progress", 0.1)
                main_df = self._load_with_fallback(
                    spc=spc_main, msk=msk_main, mid=id_main, label="merge")
                if main_df is None or main_df.empty:
                    raise ValueError("Нет данных для основного замера")

                if dpg.get_value("chkUse1"):
                    spc2 = dpg.get_value("edtSpc1")
                    msk2 = dpg.get_value("edtMsk1") or None
                    mid2 = self._get_mid_from_combo("cmb_ID1")
                    if mid2:
                        dpg.set_value("progress", 0.3)
                        secondary_df = self._load_with_fallback(
                            spc=spc2, msk=msk2, mid=mid2,
                            label="merge-secondary")
                        if secondary_df is not None and not secondary_df.empty:
                            only_spur = bool(dpg.get_value("chk_only_spur"))
                            add_spur = (bool(dpg.get_value("chk_add_spur"))
                                        or only_spur)
                            main_df = merge_psidata(
                                main_df, secondary_df,
                                add_spur=add_spur,
                                only_spur=only_spur,
                            )

                if dpg.get_value("chkUse2"):
                    dpg.set_value("progress", 0.6)
                    old_df = self._load_old_sources()
                    if old_df is not None and not old_df.empty:
                        aging = {"Старение 1": 1, "Старение 2": 2,
                                 "Старение 3": 3}[
                            dpg.get_value("aging_type")]
                        main_df = merge_old(main_df, old_df, aging)

                self._merged_df = main_df
                self._protocol_number = self._generate_protocol_number()

                # ▼ Регистрируем заголовок: получаем Measure_ID сразу
                dpg.set_value("progress", 0.85)
                try:
                    self._measure_id = reserve_measure_id(
                        msk=msk_main,
                        protocol_number=self._protocol_number,
                        program_type=program_type,
                        operator_name=operator_name,
                        file_name=file_name,
                        notes=notes,
                    )
                except Exception as e_id:
                    # Строки готовы, но заголовок не создан → нельзя ни
                    # печатать (нет Measure_ID), ни сохранять psidata.
                    self._merged_df = None
                    raise RuntimeError(
                        f"Слияние готово, но не удалось создать заголовок "
                        f"протокола в psi_measure_id:\n{e_id}"
                    )

                dpg.set_value("progress", 0.95)
                dpg.set_value("merge_status_text",
                              f"Готово: {len(main_df)} строк")
                dpg.set_value("merge_protocol_text",
                              f"Measure_ID: {self._measure_id}")
                dpg.configure_item("btnSaveToDb", enabled=True)
                dpg.configure_item("btnPrintPdf", enabled=True)
                dpg.configure_item("btnOpenMerged", enabled=True)
                dpg.set_value("progress", 1.0)
            except Exception as e:
                dpg.set_value("progress", 0.0)
                dpg.set_value("merge_status_text", f"Ошибка: {e}")
                self._show_error(f"Ошибка совмещения:\n{e}\n\n"
                                 f"{traceback.format_exc()}")
            finally:
                dpg.configure_item("btnMerge", enabled=True)

        threading.Thread(target=task, daemon=True).start()

    def on_merge_4(self):
        spc_main = dpg.get_value("edtSpc")
        msk_main = dpg.get_value("edtMsk") or None
        id_main = self._get_mid_from_combo("cmb_ID")
        if not spc_main or not id_main:
            self._show_error("Заполните основной замер")
            return

        # ▼ Источники для Notes
        source_ids = {'main': id_main}
        if dpg.get_value("chkUse1"):
            mid2 = self._get_mid_from_combo("cmb_ID1")
            if mid2:
                source_ids['secondary'] = mid2
        if dpg.get_value("chkUse2"):
            mid3 = self._get_mid_from_combo("cmb_ID2")
            if mid3:
                source_ids['old'] = mid3
        self._source_ids = source_ids

        self._merged_df = None
        self._protocol_number = None
        self._last_saved_id = None

        dpg.configure_item("btnMerge", enabled=False)
        dpg.configure_item("btnSaveToDb", enabled=False)
        dpg.configure_item("btnPrintPdf", enabled=False)
        dpg.configure_item("btnOpenMerged", enabled=False)
        dpg.set_value("progress", 0.0)
        dpg.set_value("merge_status_text", "Выполняется...")
        dpg.set_value("merge_protocol_text", "-")
        dpg.set_value("merge_result_text", "-")

        def task():
            try:
                dpg.set_value("progress", 0.1)
                main_df = self._load_with_fallback(
                    spc=spc_main, msk=msk_main, mid=id_main, label="merge")
                if main_df is None or main_df.empty:
                    raise ValueError("Нет данных для основного замера")

                if dpg.get_value("chkUse1"):
                    spc2 = dpg.get_value("edtSpc1")
                    msk2 = dpg.get_value("edtMsk1") or None
                    mid2 = self._get_mid_from_combo("cmb_ID1")
                    if mid2:
                        dpg.set_value("progress", 0.3)
                        secondary_df = self._load_with_fallback(
                            spc=spc2, msk=msk2, mid=mid2,
                            label="merge-secondary")
                        if secondary_df is not None and not secondary_df.empty:
                            only_spur = bool(dpg.get_value("chk_only_spur"))
                            add_spur = (bool(dpg.get_value("chk_add_spur"))
                                        or only_spur)
                            main_df = merge_psidata(
                                main_df, secondary_df,
                                add_spur=add_spur,
                                only_spur=only_spur,
                            )

                if dpg.get_value("chkUse2"):
                    dpg.set_value("progress", 0.6)
                    old_df = self._load_old_sources()
                    if old_df is not None and not old_df.empty:
                        aging = {"Старение 1": 1, "Старение 2": 2,
                                 "Старение 3": 3}[
                            dpg.get_value("aging_type")]
                        main_df = merge_old(main_df, old_df, aging)

                dpg.set_value("progress", 0.95)
                self._merged_df = main_df
                self._protocol_number = self._generate_protocol_number()

                dpg.set_value("merge_status_text",
                              f"Готово: {len(main_df)} строк")
                # ▼ UI: Measure_ID появится только после сохранения
                dpg.set_value(
                    "merge_protocol_text",
                    "Не сохранён (сохраните для получения Measure_ID)")
                dpg.configure_item("btnSaveToDb", enabled=True)
                dpg.configure_item("btnOpenMerged", enabled=True)
                dpg.set_value("progress", 1.0)
            except Exception as e:
                dpg.set_value("progress", 0.0)
                dpg.set_value("merge_status_text", f"Ошибка: {e}")
                self._show_error(f"Ошибка совмещения:\n{e}\n\n"
                                 f"{traceback.format_exc()}")
            finally:
                dpg.configure_item("btnMerge", enabled=True)

        threading.Thread(target=task, daemon=True).start()

    def _build_notes(self) -> str | None:
        """Notes для psi_measure_id в формате:

        Совмещение (1: <ID осн.>, 2: <ID доп.>, 3: <ID старения>)
        Присутствуют только реально использованные источники.
        """
        src = self._source_ids or {}
        parts = []
        if src.get('main'):
            parts.append(f"1: {src['main']}")
        if src.get('secondary'):
            parts.append(f"2: {src['secondary']}")
        if src.get('old'):
            parts.append(f"3: {src['old']}")
        if not parts:
            return None
        return f"Совмещение ({', '.join(parts)})"

    def on_merge_1(self):
        spc_main = dpg.get_value("edtSpc")
        msk_main = dpg.get_value("edtMsk") or None
        id_main = self._get_mid_from_combo("cmb_ID")
        if not spc_main or not id_main:
            self._show_error("Заполните основной замер")
            return

        self._merged_df = None
        self._protocol_number = None
        self._last_saved_id = None

        dpg.configure_item("btnMerge", enabled=False)
        dpg.configure_item("btnSaveToDb", enabled=False)
        dpg.configure_item("btnPrintPdf", enabled=False)
        dpg.configure_item("btnOpenMerged", enabled=False)
        dpg.set_value("progress", 0.0)
        dpg.set_value("merge_status_text", "Выполняется...")
        dpg.set_value("merge_protocol_text", "-")
        dpg.set_value("merge_result_text", "-")

        def task():
            try:
                dpg.set_value("progress", 0.1)
                main_df = self._load_with_fallback(
                    spc=spc_main, msk=msk_main, mid=id_main, label="merge")
                if main_df is None or main_df.empty:
                    raise ValueError("Нет данных для основного замера")

                if dpg.get_value("chkUse1"):
                    spc2 = dpg.get_value("edtSpc1")
                    msk2 = dpg.get_value("edtMsk1") or None
                    mid2 = self._get_mid_from_combo("cmb_ID1")
                    # spc2 не обязателен: в режиме автоподбора замер
                    # может иметь другую спецификацию — _load_with_fallback
                    # сам упадёт на load_psidata_by_measure_id.
                    if mid2:
                        dpg.set_value("progress", 0.3)
                        secondary_df = self._load_with_fallback(
                            spc=spc2, msk=msk2, mid=mid2,
                            label="merge-secondary")
                        if secondary_df is not None and not secondary_df.empty:
                            only_spur = bool(dpg.get_value("chk_only_spur"))
                            add_spur = (bool(dpg.get_value("chk_add_spur"))
                                        or only_spur)
                            print(f"[merge] secondary: "
                                  f"only_spur={only_spur}, "
                                  f"add_spur={add_spur}")
                            main_df = merge_psidata(
                                main_df, secondary_df,
                                add_spur=add_spur,
                                only_spur=only_spur,
                            )

                if dpg.get_value("chkUse2"):
                    dpg.set_value("progress", 0.6)
                    old_df = self._load_old_sources()
                    if old_df is not None and not old_df.empty:
                        aging = {"Старение 1": 1, "Старение 2": 2,
                                 "Старение 3": 3}[
                            dpg.get_value("aging_type")]
                        print(f"[merge] старение: aging_type={aging}, "
                              f"строк old={len(old_df)}")
                        main_df = merge_old(main_df, old_df, aging)

                dpg.set_value("progress", 0.95)
                self._merged_df = main_df
                self._protocol_number = self._generate_protocol_number()

                dpg.set_value("merge_status_text",
                              f"Готово: {len(main_df)} строк")
                dpg.set_value("merge_protocol_text",
                              f"Новый протокол: N {self._protocol_number}")
                dpg.configure_item("btnSaveToDb", enabled=True)
                dpg.configure_item("btnPrintPdf", enabled=True)
                dpg.configure_item("btnOpenMerged", enabled=True)
                dpg.set_value("progress", 1.0)
            except Exception as e:
                dpg.set_value("progress", 0.0)
                dpg.set_value("merge_status_text", f"Ошибка: {e}")
                self._show_error(f"Ошибка совмещения:\n{e}\n\n"
                                 f"{traceback.format_exc()}")
            finally:
                dpg.configure_item("btnMerge", enabled=True)

        threading.Thread(target=task, daemon=True).start()

    def _generate_protocol_number(self):
        """Стандартный номер протокола: числовой, из psi_measure_id.ProtokolN.

        Пропускает уже занятые номера (на случай параллельной работы
        или ручного ввода старого протокола).
        """
        try:
            candidate = get_next_protocol_number()
            # защита от гонки: если номер уже появился в БД — берём следующий
            for _ in range(20):
                if not protocol_number_exists(candidate):
                    return str(candidate)
                candidate = str(int(candidate) + 1)
            return str(candidate)
        except Exception as e:
            print(f"[_generate_protocol_number] fallback: {e}")
            # аварийный fallback — тоже числовой
            return datetime.now().strftime('%Y%m%d%H%M%S')

    def _open_merged_window(self):
        if self._merged_df is None or self._merged_df.empty:
            self._show_error("Результат пуст")
            return
        open_spec_preview(
            title="Предпросмотр результата слияния",
            df=self._merged_df,
            spc_name=dpg.get_value("edtSpc") or "",
            tag="merged_preview_window",
            note=(f"Протокол N {self._protocol_number or '-'}. "
                  f"Сохранение - по кнопке 'Сохранить в БД'."),
        )

    # ------------------------------------------------------- спецификация
    def _on_view_spec(self):
        """Показать таблицу норм для текущей спецификации и типа протокола."""
        spc_name = dpg.get_value("edtSpc") or ""
        if not spc_name:
            self._show_error(
                "Сначала выберите спецификацию основного замера "
                "(combo «Спецификация»)."
            )
            return

        psi_type = 'ОТК'
        if dpg.does_item_exist("psi_type"):
            psi_type = dpg.get_value("psi_type") or 'ОТК'
        if psi_type not in ('ПСИ', 'ОТК'):
            psi_type = 'ОТК'

        try:
            spc_map = _load_spc_map_for_ui(spc_name, psi_type)
        except Exception as e:
            print(f"[_on_view_spec] load error: {e}")
            traceback.print_exc()
            self._show_error(f"Ошибка загрузки спецификации:\n{e}")
            return

        if spc_map is None or spc_map.empty:
            self._show_error(
                f"Нормы для «{spc_name}» ({psi_type}) не найдены"
            )
            return

        self._show_spc_window(spc_name, spc_map, psi_type)

    def _show_spc_window(self, spc_name, spc_map, psi_type):
        """Окно с таблицей норм — по аналогии с Measure_Table_Window."""
        tag = "sort_spec_window"
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

        if 'Order' in spc_map.columns:
            spc_map = spc_map.sort_values('Order')

        # Колонка-метка: Note_mini → Note → Parameter
        if 'Note_mini' in spc_map.columns:
            labels = spc_map['Note_mini'].fillna(
                spc_map.get('Note', spc_map['Parameter'])
            )
        elif 'Note' in spc_map.columns:
            labels = spc_map['Note'].fillna(spc_map['Parameter'])
        else:
            labels = spc_map['Parameter']

        sw, sh = _layout.screen_size()
        w = max(560, min(900, int(sw * 0.42)))
        h = max(420, min(900, int(sh * 0.72)))
        pos = (max(10, (sw - w) // 2), max(10, (sh - h) // 2))

        with dpg.window(
                label=f"Спецификация: {spc_name} ({psi_type})",
                tag=tag, width=w, height=h, pos=pos, no_collapse=True,
        ):
            dpg.add_text(
                f"Спецификация: {spc_name}   |   Тип норм: {psi_type}",
                color=(200, 220, 255),
            )
            if psi_type == 'ОТК':
                dpg.add_text(
                    "Нормы ОТК (с технологическим запасом).",
                    color=(180, 200, 230),
                )
            else:
                dpg.add_text(
                    "Нормы ПСИ (без технологического запаса).",
                    color=(180, 200, 230),
                )
            dpg.add_separator()

            with dpg.table(
                    header_row=True,
                    borders_innerH=True, borders_outerH=True,
                    borders_innerV=True, borders_outerV=True,
                    resizable=True, scrollX=True, scrollY=True,
                    policy=dpg.mvTable_SizingStretchProp,
                    height=-40,
            ):
                dpg.add_table_column(
                    label='Параметр', init_width_or_weight=2.4)
                dpg.add_table_column(
                    label='Макс', init_width_or_weight=1.0)
                dpg.add_table_column(
                    label='Мин', init_width_or_weight=1.0)

                for i, (_, row) in enumerate(spc_map.iterrows()):
                    label = labels.iloc[i]
                    mx = row['Max']
                    mn = row['Min']
                    with dpg.table_row():
                        dpg.add_text(str(label))
                        dpg.add_text(
                            f'{mx:.4g}'
                            if mx is not None and not pd.isna(mx) else '-'
                        )
                        dpg.add_text(
                            f'{mn:.4g}'
                            if mn is not None and not pd.isna(mn) else '-'
                        )

            dpg.add_separator()
            dpg.add_button(
                label="Закрыть",
                callback=lambda: dpg.delete_item(tag),
                width=120,
            )

    # ------------------------------------------------------ сохранение
    def on_save_to_db(self):
        print("=" * 70)
        print("[Save] Сохранение строк в psidata")
        print("=" * 70)

        if self._merged_df is None or self._merged_df.empty:
            self._show_error("Нет данных для сохранения")
            return

        if not self._measure_id:
            self._show_error(
                "Measure_ID не назначен.\n"
                "Нажмите «Объединить» — заголовок протокола создаётся "
                "именно там."
            )
            return

        psi_type = 'ОТК'
        if dpg.does_item_exist("psi_type"):
            psi_type = dpg.get_value("psi_type") or 'ОТК'
        if psi_type not in ('ПСИ', 'ОТК'):
            psi_type = 'ОТК'

        print(f"[Save] MeasureID = {self._measure_id}")
        print(f"[Save] Psi_Type = {psi_type!r}")
        print(f"[Save] Строк в df = {len(self._merged_df)}")

        try:
            # ▼ Measure_ID основного замера — источник температур для psidatatemp
            source_mid = (self._source_ids or {}).get('main')
            print(f"[Save] source_measure_id (для psidatatemp) = {source_mid}")

            save_merged_rows(
                merged_df=self._merged_df,
                measure_id=self._measure_id,
                psi_type=psi_type,
                source_measure_id=source_mid,  # ← NEW
            )
            dpg.configure_item("btnSaveToDb", enabled=False)
            dpg.set_value(
                "merge_result_text",
                f"Сохранено: Measure_ID = {self._measure_id}, "
                f"Протокол N {self._protocol_number}, "
                f"тип {psi_type}",
            )
            print(f"[Save] УСПЕХ: MeasureID = {self._measure_id}, "
                  f"psi_type = {psi_type!r}")
            print("=" * 70)
        except Exception as e:
            print(f"[Save] ОШИБКА: {e}")
            print(f"[Save] Traceback:\n{traceback.format_exc()}")
            self._show_error(f"Ошибка сохранения:\n{e}\n\n"
                             f"{traceback.format_exc()}")

    def on_save_to_db_4(self):
        print("=" * 70)
        print("[Save] Начало сохранения протокола совмещения в БД")
        print("=" * 70)

        if self._merged_df is None or self._merged_df.empty:
            print("[Save] ОТМЕНА: нет данных для сохранения")
            self._show_error("Нет данных для сохранения")
            return

        if not self._protocol_number:
            self._protocol_number = self._generate_protocol_number()
            print(f"[Save] Сгенерирован номер протокола (ProtokolN): "
                  f"{self._protocol_number}")

        msk = dpg.get_value("edtMsk") or None
        program_type = dpg.get_value("program_type") or None
        operator_name = dpg.get_value("operator") or None
        file_name = dpg.get_value("sort_file_name") or None

        psi_type = 'ОТК'
        if dpg.does_item_exist("psi_type"):
            psi_type = dpg.get_value("psi_type") or 'ОТК'
        if psi_type not in ('ПСИ', 'ОТК'):
            psi_type = 'ОТК'

        notes = self._build_notes()

        print(f"[Save] Параметры сохранения:")
        print(f"[Save]   MSK          = {msk!r}")
        print(f"[Save]   ProtokolN    = {self._protocol_number!r}")
        print(f"[Save]   Program_Type = {program_type!r}")
        print(f"[Save]   Operator     = {operator_name!r}")
        print(f"[Save]   File         = {file_name!r}")
        print(f"[Save]   Psi_Type     = {psi_type!r}")
        print(f"[Save]   Notes        = {notes!r}")
        print(f"[Save]   Строк в df   = {len(self._merged_df)}")

        try:
            new_id = save_merged_protocol(
                merged_df=self._merged_df,
                msk=msk,
                protocol_number=self._protocol_number,
                program_type=program_type,
                operator_name=operator_name,
                file_name=file_name,
                psi_type=psi_type,
                notes=notes,
            )
            self._last_saved_id = new_id
            dpg.configure_item("btnSaveToDb", enabled=False)

            # ▼ UI: показываем Measure_ID, он же пойдёт в заголовок PDF
            dpg.set_value("merge_protocol_text", f"Measure_ID: {new_id}")
            dpg.set_value(
                "merge_result_text",
                f"Сохранено: Measure_ID = {new_id}, "
                f"Протокол N {self._protocol_number}, "
                f"тип {psi_type}",
            )
            print(f"[Save] УСПЕХ: MeasureID = {new_id}, "
                  f"ProtokolN = {self._protocol_number!r}, "
                  f"psi_type = {psi_type!r}, notes = {notes!r}")
            print("=" * 70)
        except Exception as e:
            print(f"[Save] ОШИБКА сохранения: {e}")
            print(f"[Save] Traceback:\n{traceback.format_exc()}")
            print("=" * 70)
            self._show_error(f"Ошибка сохранения:\n{e}\n\n"
                             f"{traceback.format_exc()}")

    def on_save_to_db_2(self):
        print("=" * 70)
        print("[Save] Начало сохранения протокола совмещения в БД")
        print("=" * 70)

        if self._merged_df is None or self._merged_df.empty:
            print("[Save] ОТМЕНА: нет данных для сохранения")
            self._show_error("Нет данных для сохранения")
            return

        if not self._protocol_number:
            self._protocol_number = self._generate_protocol_number()
            dpg.set_value("merge_protocol_text",
                          f"Новый протокол: N {self._protocol_number}")
            print(f"[Save] Сгенерирован номер протокола: "
                  f"{self._protocol_number}")

        msk = dpg.get_value("edtMsk") or None
        program_type = dpg.get_value("program_type") or None
        operator_name = dpg.get_value("operator") or None
        file_name = dpg.get_value("sort_file_name") or None

        # ▼ psi_type ОБЯЗАТЕЛЬНО определяем ДО вызова save_merged_protocol
        psi_type = 'ОТК'
        if dpg.does_item_exist("psi_type"):
            psi_type = dpg.get_value("psi_type") or 'ОТК'
        if psi_type not in ('ПСИ', 'ОТК'):
            psi_type = 'ОТК'

        print(f"[Save] Параметры сохранения:")
        print(f"[Save]   MSK          = {msk!r}")
        print(f"[Save]   Протокол N   = {self._protocol_number!r}")
        print(f"[Save]   Program_Type = {program_type!r}")
        print(f"[Save]   Operator     = {operator_name!r}")
        print(f"[Save]   File         = {file_name!r}")
        print(f"[Save]   Psi_Type     = {psi_type!r}")
        print(f"[Save]   Строк в df   = {len(self._merged_df)}")
        print(f"[Save]   Колонок в df = {len(self._merged_df.columns)}")

        try:
            print("[Save] Вызов save_merged_protocol()...")
            new_id = save_merged_protocol(
                merged_df=self._merged_df,
                msk=msk,
                protocol_number=self._protocol_number,
                program_type=program_type,
                operator_name=operator_name,
                file_name=file_name,
                psi_type=psi_type,
            )
            self._last_saved_id = new_id
            dpg.configure_item("btnSaveToDb", enabled=False)
            dpg.set_value(
                "merge_result_text",
                f"Сохранено: MeasureID = {new_id}, "
                f"Протокол N {self._protocol_number}, "
                f"тип {psi_type}",
            )
            print(f"[Save] УСПЕХ: MeasureID = {new_id}, "
                  f"протокол N {self._protocol_number}, "
                  f"psi_type = {psi_type!r}")
            print("=" * 70)
        except Exception as e:
            print(f"[Save] ОШИБКА сохранения: {e}")
            print(f"[Save] Traceback:\n{traceback.format_exc()}")
            print("=" * 70)
            self._show_error(f"Ошибка сохранения:\n{e}\n\n"
                             f"{traceback.format_exc()}")

    def on_print_pdf(self):
        if self._merged_df is None or self._merged_df.empty:
            self._show_error("Нет данных для печати")
            return

        if not self._measure_id:
            self._show_error(
                "Measure_ID не назначен.\n"
                "Нажмите «Объединить» — заголовок протокола создаётся "
                "именно там."
            )
            return

        psi_type = 'ОТК'
        if dpg.does_item_exist("psi_type"):
            psi_type = dpg.get_value("psi_type") or 'ОТК'
        if psi_type not in ('ПСИ', 'ОТК'):
            psi_type = 'ОТК'

        try:
            path = create_merged_protocol_pdf(
                merged_df=self._merged_df,
                measure_id=self._measure_id,  # ← готовый ID из on_merge
                msk=dpg.get_value("edtMsk") or "-",
                file_name=dpg.get_value("sort_file_name") or None,
                program_type=dpg.get_value("program_type") or None,
                operator=dpg.get_value("operator") or None,
                psi_type=psi_type,
            )
            dpg.set_value("merge_result_text", f"PDF сохранён: {path}")
        except Exception as e:
            self._show_error(f"Ошибка печати:\n{e}")

    def on_print_pdf_4(self):
        if self._merged_df is None or self._merged_df.empty:
            self._show_error("Нет данных для печати")
            return

        # ▼ Measure_ID появляется только после сохранения
        if not self._last_saved_id:
            self._show_error(
                "Сначала сохраните протокол в БД.\n\n"
                "Measure_ID присваивается при сохранении "
                "и используется в заголовке и имени PDF-файла."
            )
            return

        psi_type = 'ОТК'
        if dpg.does_item_exist("psi_type"):
            psi_type = dpg.get_value("psi_type") or 'ОТК'
        if psi_type not in ('ПСИ', 'ОТК'):
            psi_type = 'ОТК'

        try:
            path = create_merged_protocol_pdf(
                merged_df=self._merged_df,
                measure_id=self._last_saved_id,
                msk=dpg.get_value("edtMsk") or "-",
                file_name=dpg.get_value("sort_file_name") or None,
                program_type=dpg.get_value("program_type") or None,
                operator=dpg.get_value("operator") or None,
                psi_type=psi_type,
            )
            dpg.set_value(
                "merge_result_text",
                f"PDF сохранён: {path}"
            )
        except Exception as e:
            self._show_error(f"Ошибка печати:\n{e}")

    def on_print_pdf_1(self):
        if self._merged_df is None or self._merged_df.empty:
            self._show_error("Нет данных для печати")
            return
        if not self._protocol_number:
            self._protocol_number = self._generate_protocol_number()
            dpg.set_value("merge_protocol_text",
                          f"Новый протокол: N {self._protocol_number}")

        # ▼ psi_type ОБЯЗАТЕЛЬНО определяем ДО вызова create_merged_protocol_pdf
        psi_type = 'ОТК'
        if dpg.does_item_exist("psi_type"):
            psi_type = dpg.get_value("psi_type") or 'ОТК'
        if psi_type not in ('ПСИ', 'ОТК'):
            psi_type = 'ОТК'

        try:
            path = create_merged_protocol_pdf(
                merged_df=self._merged_df,
                protocol_number=self._protocol_number,
                msk=dpg.get_value("edtMsk") or "-",
                file_name=dpg.get_value("sort_file_name") or None,
                program_type=dpg.get_value("program_type") or None,
                operator=dpg.get_value("operator") or None,
                psi_type=psi_type,
            )
            dpg.set_value("merge_result_text",
                          f"PDF сохранён ({psi_type}): {path}")
        except Exception as e:
            self._show_error(f"Ошибка печати:\n{e}")


    def on_save_to_db_1(self):
        print("=" * 70)
        print("[Save] Начало сохранения протокола совмещения в БД")
        print("=" * 70)

        if self._merged_df is None or self._merged_df.empty:
            print("[Save] ОТМЕНА: нет данных для сохранения")
            self._show_error("Нет данных для сохранения")
            return

        if not self._protocol_number:
            self._protocol_number = self._generate_protocol_number()
            dpg.set_value("merge_protocol_text",
                          f"Новый протокол: N {self._protocol_number}")
            print(f"[Save] Сгенерирован номер протокола: "
                  f"{self._protocol_number}")

        msk = dpg.get_value("edtMsk") or None
        program_type = dpg.get_value("program_type") or None
        operator_name = dpg.get_value("operator") or None
        file_name = dpg.get_value("sort_file_name") or None

        print(f"[Save] Параметры сохранения:")
        print(f"[Save]   MSK          = {msk!r}")
        print(f"[Save]   Протокол N   = {self._protocol_number!r}")
        print(f"[Save]   Program_Type = {program_type!r}")
        print(f"[Save]   Operator     = {operator_name!r}")
        print(f"[Save]   File         = {file_name!r}")
        print(f"[Save]   Строк в df   = {len(self._merged_df)}")
        print(f"[Save]   Колонок в df = {len(self._merged_df.columns)}")

        try:
            print("[Save] Вызов save_merged_protocol()...")
            new_id = save_merged_protocol(
                merged_df=self._merged_df,
                msk=msk,
                protocol_number=self._protocol_number,
                program_type=program_type,
                operator_name=operator_name,
                file_name=file_name,
            )
            self._last_saved_id = new_id
            dpg.configure_item("btnSaveToDb", enabled=False)
            dpg.set_value(
                "merge_result_text",
                f"Сохранено: MeasureID = {new_id}, "
                f"Протокол N {self._protocol_number}",
            )
            print(f"[Save] УСПЕХ: MeasureID = {new_id}, "
                  f"протокол N {self._protocol_number}")
            print("=" * 70)
        except Exception as e:
            print(f"[Save] ОШИБКА сохранения: {e}")
            print(f"[Save] Traceback:\n{traceback.format_exc()}")
            print("=" * 70)
            self._show_error(f"Ошибка сохранения:\n{e}\n\n"
                             f"{traceback.format_exc()}")



    # ---------------------------------------------------------- сервис
    def on_clear(self):
        self._merged_df = None
        self._protocol_number = None
        self._measure_id = None
        self._source_ids = {}
        self._loaded = {"main": None, "secondary": None, "old": None}
        dpg.set_value("merge_status_text", "-")
        dpg.set_value("merge_protocol_text", "-")
        dpg.set_value("merge_result_text", "-")
        dpg.configure_item("btnSaveToDb", enabled=False)
        dpg.configure_item("btnPrintPdf", enabled=False)
        dpg.configure_item("btnOpenMerged", enabled=False)
        dpg.set_value("progress", 0.0)

    def on_clear_4(self):
        self._merged_df = None
        self._protocol_number = None
        self._last_saved_id = None
        self._source_ids = {}
        self._loaded = {"main": None, "secondary": None, "old": None}
        dpg.set_value("merge_status_text", "-")
        dpg.set_value("merge_protocol_text", "-")
        dpg.set_value("merge_result_text", "-")
        dpg.configure_item("btnSaveToDb", enabled=False)
        dpg.configure_item("btnPrintPdf", enabled=False)
        dpg.configure_item("btnOpenMerged", enabled=False)
        dpg.set_value("progress", 0.0)

    def _show_error(self, message):
        tag = "sort_error_modal"
        if self.dpg.does_item_exist(tag):
            self.dpg.delete_item(tag)
        with self.dpg.window(label="Ошибка", modal=True,
                             width=560, height=220, tag=tag,
                             no_resize=True):
            self.dpg.add_text(message, wrap=540, color=(220, 80, 80))
            self.dpg.add_separator()
            self.dpg.add_button(label="OK",
                                callback=lambda: self.dpg.delete_item(tag),
                                width=100)

    def on_close(self):
        self.dpg.delete_item(self.window_tag)

    def show(self):
        self.dpg.show_item(self.window_tag)

    def hide(self):
        self.dpg.hide_item(self.window_tag)