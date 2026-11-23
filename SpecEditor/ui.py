"""
Профессиональный редактор спецификаций.
Двухколоночный вид: список слева, редактор с вкладками справа.
"""
import os
import sys
import traceback
from contextlib import contextmanager

import dearpygui.dearpygui as dpg

from Authorization.Login import LoginUser
from .constants import (
    WIN_LIST_TAG, WIN_EDIT_TAG, WIN_NEW_TAG, WIN_ERR_TAG,
    TAG_SEARCH, TAG_TABLE, TAG_TAB_BAR, TAG_STATUS,
    SECTION_ORDER, SECTION_LABELS, LABELS, COLUMN_SECTION,
    PARAM_GROUPS, TEMP_INTERVALS,
    GRAPH_F_OPTIONS, LOADTYPE_OPTIONS, TCHTYPE_OPTIONS, AMP_UNIT_OPTIONS,
    TOLERANCE_GROUPS,
)
from .logic import SpecEditorController, SpecEditorError


# ===========================================================================
# Состояние
# ===========================================================================
controller = SpecEditorController()
_current_name = None
_field_values: dict = {}
_original_data: dict = {}
_ctx_spec_name = [None]

# Оформление
COLOR_SECTION = (200, 225, 200)
COLOR_HEADER = (210, 220, 255)
COLOR_HINT = (140, 140, 140)

FIELD_W = 220

# Один общий реестр для всех selectable-строк
_CTX_SHARED_REG = "spec_ctx_shared_registry"
# ===========================================================================
# Утилиты
# ===========================================================================
def _get_login_user() -> str:
    try:
        if LoginUser is not None and getattr(LoginUser, "login", None):
            val = str(LoginUser.login[0]).strip()
            if val:
                return val
    except Exception:
        pass
    return "unknown"


def _show_error(msg, exc=None):
    text = str(msg)
    if exc is not None:
        text += f"\n{exc}"
        traceback.print_exc()
    if dpg.does_item_exist(WIN_ERR_TAG):
        dpg.delete_item(WIN_ERR_TAG)
    with dpg.window(label="Сообщение", modal=True, autosize=True,
                    pos=(400, 300), tag=WIN_ERR_TAG):
        dpg.add_text(text, wrap=520)
        dpg.add_button(label="OK",
                       callback=lambda: dpg.delete_item(WIN_ERR_TAG))


def _section_of(col: str) -> str:
    return COLUMN_SECTION.get(col, "other")


def _label_of(col: str) -> str:
    return LABELS.get(col, col)


def _to_bool(val) -> bool:
    if val is None:
        return False
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    s = str(val).strip().lower()
    return s in ("1", "true", "t", "yes", "y", "да", "истина")


def _kind_of(col: str):
    if col in ("TypeF", "Multy"):
        return "bool"
    return controller.column_type(col)


_HIDDEN_SUBSTRINGS = ("Cb", "Color")
_HIDDEN_PREFIXES = ("Trmx", "Trmn", "Tfmn", "Tfptp", "Trr")
_HIDDEN_EXACT = {
    "DopuskFptp",
    "Tf",
    "RadiusF2", "RadiusR2", "RadiusF4", "RadiusR4",
}


def _is_hidden_col(col: str) -> bool:
    if not col:
        return True
    if col in _HIDDEN_EXACT:
        return True
    if any(col.startswith(p) for p in _HIDDEN_PREFIXES):
        return True
    low = col.lower()
    return any(s.lower() in low for s in _HIDDEN_SUBSTRINGS)

_NORM_COLUMNS_CACHE = None


def _get_norm_columns() -> set:
    """Колонки-нормы (min/max/T), для которых пустое значение
    сохраняется как 'no' («норма не задана»).
    """
    global _NORM_COLUMNS_CACHE
    if _NORM_COLUMNS_CACHE is not None:
        return _NORM_COLUMNS_CACHE
    try:
        _NORM_COLUMNS_CACHE = controller._norm_columns()
    except Exception as e:
        print(f"[SpecEditor] _get_norm_columns error: {e}")
        _NORM_COLUMNS_CACHE = set()
    return _NORM_COLUMNS_CACHE

def _combo_options_for(col: str):
    mapping = {
        "NameR":             controller.fetch_resonator_types,
        "Profile":           controller.fetch_profiles,
        "Type":              controller.fetch_korpus,
        "TU":                controller.fetch_tu,
        "LoadType":          controller.fetch_measure_modes,
        "GraphF":            lambda: GRAPH_F_OPTIONS,
        "TCHType":           controller.fetch_tch_types,
        "TCH_Approx_Type":   controller.fetch_tch_approx_types,
        "TCH_Interval_Type": controller.fetch_tch_interval_types,
    }
    fn = mapping.get(col)
    if fn is None:
        return []
    try:
        return fn()
    except Exception:
        return []
def _on_float_change(col, text):
    s = "" if text is None else str(text).strip()
    if col in _get_norm_columns() and (not s or s.lower() == "no"):
        _original_data[col] = "no"
        return
    try:
        val = float(s.replace(",", "."))
    except (TypeError, ValueError):
        val = 0.0
    _original_data[col] = val

def _on_float_change_1(col, text):
    try:
        val = float(str(text).replace(",", "."))
    except (TypeError, ValueError):
        val = 0.0
    _original_data[col] = val


# ===========================================================================
# Виджеты полей
# ===========================================================================
def _render_field_widget(col: str, width=FIELD_W):
    if _is_hidden_col(col):
        return

    tag = f"field_{col}"
    if dpg.does_item_exist(tag):
        return

    kind = _kind_of(col)
    _field_values[col] = tag

    if isinstance(kind, tuple):
        _, options = kind
        dpg.add_combo(options, tag=tag, width=width, default_value="",
                      callback=lambda s, a, u, c=col:
                          _original_data.update({c: a}))
    elif kind == "bool":
        dpg.add_checkbox(tag=tag,
                         callback=lambda s, a, u, c=col:
                             _original_data.update({c: bool(a)}))
    elif kind == "int":
        dpg.add_input_int(tag=tag, width=width,
                          callback=lambda s, a, u, c=col:
                              _original_data.update({c: int(a)}))
    elif kind == "float":
        dpg.add_input_text(tag=tag, width=width, decimal=True,
                           callback=lambda s, a, u, c=col:
                               _on_float_change(c, a))
    else:
        opts = _combo_options_for(col)
        if opts:
            dpg.add_combo(opts, tag=tag, width=width, default_value="",
                          callback=lambda s, a, u, c=col:
                              _original_data.update({c: a}))
        else:
            dpg.add_input_text(tag=tag, width=width,
                               callback=lambda s, a, u, c=col:
                                   _original_data.update({c: a}))


# ===========================================================================
# Секция и строки
# ===========================================================================
class _Section:
    def __init__(self, title):
        self.title = title

    def __enter__(self):
        dpg.add_text(self.title, color=COLOR_SECTION)
        dpg.add_separator()
        dpg.add_spacer(height=2)
        return self

    def __exit__(self, *a):
        dpg.add_spacer(height=10)


def _section(title):
    return _Section(title)


def _row_kv(label: str, col: str, width=FIELD_W, tooltip=None):
    with dpg.table_row():
        txt = dpg.add_text(label, wrap=250)
        if tooltip:
            with dpg.tooltip(txt):
                dpg.add_text(tooltip)
        _render_field_widget(col, width=width)


@contextmanager
def _table_kv():
    with dpg.table(header_row=False,
                   borders_innerH=False, borders_innerV=False,
                   row_background=False,
                   policy=dpg.mvTable_SizingStretchProp,
                   no_pad_innerX=True, pad_outerX=False):
        dpg.add_table_column(init_width_or_weight=0.45)
        dpg.add_table_column(init_width_or_weight=0.55)
        yield


# ===========================================================================
# Таблица параметров
# ===========================================================================
def _param_row(label, chk, mn, mx, t, t_label,
               t_begin=None, t_end=None, with_interval=False):
    all_cols = set(controller.columns())

    def _cell_float(col):
        if col and col in all_cols:
            tag = f"field_{col}"
            if dpg.does_item_exist(tag):
                dpg.add_text("")
                return
            _field_values[col] = tag
            dpg.add_input_text(tag=tag, width=-1, decimal=True,
                               callback=lambda s, a, u, c=col:
                                   _on_float_change(c, a))
        else:
            dpg.add_text("")

    with dpg.table_row():
        if chk and chk in all_cols:
            tag = f"field_{chk}"
            if dpg.does_item_exist(tag):
                dpg.add_text("")
            else:
                _field_values[chk] = tag
                dpg.add_checkbox(tag=tag,
                                 callback=lambda s, a, u, c=chk:
                                     _original_data.update({c: bool(a)}))
        else:
            dpg.add_text("")

        dpg.add_text(label, wrap=220)

        _cell_float(mn)
        _cell_float(mx)
        _cell_float(t)

        if with_interval:
            _cell_float(t_begin)
            _cell_float(t_end)


def _param_table(section_key):
    groups = [g for g in PARAM_GROUPS if g[6] == section_key]
    if not groups:
        dpg.add_text("Нет параметров", color=COLOR_HINT)
        return

    blocks = {}
    for g in groups:
        block_name = g[7] if len(g) > 7 else "Параметры"
        blocks.setdefault(block_name, []).append(g)

    for block_name, block_groups in blocks.items():
        has_interval = any(
            (section_key, g[0]) in TEMP_INTERVALS for g in block_groups
        )

        with _section(block_name):
            with dpg.table(header_row=True, resizable=False,
                           borders_innerH=True, borders_innerV=False,
                           row_background=True,
                           policy=dpg.mvTable_SizingStretchProp):
                dpg.add_table_column(label="Вкл",
                                     init_width_or_weight=0.07)
                dpg.add_table_column(label="Параметр",
                                     init_width_or_weight=0.28 if has_interval else 0.32)
                dpg.add_table_column(label="Минимум",
                                     init_width_or_weight=0.17 if has_interval else 0.22)
                dpg.add_table_column(label="Максимум",
                                     init_width_or_weight=0.17 if has_interval else 0.22)
                dpg.add_table_column(label="Температура",
                                     init_width_or_weight=0.14 if has_interval else 0.17)
                if has_interval:
                    dpg.add_table_column(label="T нач.",
                                         init_width_or_weight=0.085)
                    dpg.add_table_column(label="T кон.",
                                         init_width_or_weight=0.085)

                for g in block_groups:
                    label = g[0]
                    tb, te = TEMP_INTERVALS.get((section_key, label), (None, None))
                    _param_row(label, g[1], g[2], g[3], g[4], g[5],
                               t_begin=tb, t_end=te,
                               with_interval=has_interval)


# ===========================================================================
# Вкладки
# ===========================================================================
def _tab_main():
    with _section("Идентификация"):
        with _table_kv():
            _row_kv("Тип резонатора",    "NameR")
            _row_kv("Код спецификации",  "Spc_Code")
            _row_kv("Название",          "Name")

    with _section("Режим измерений"):
        with _table_kv():
            _row_kv("Температурный профиль", "Profile")
            _row_kv("Установочный файл",     "String")
            _row_kv("Тип F (FL/FS)",         "TypeF")
            _row_kv("Тип измерения",         "LoadType")
            _row_kv("Значение ёмкости, pF",  "Loadvalue")

    with _section("Номинал и исполнение"):
        with _table_kv():
            _row_kv("Номинал",            "Nominal")
            _row_kv("Корпус",             "Type")
            _row_kv("ТУ",                 "TU")
            _row_kv("Мощность, uW",       "Power")
            _row_kv("Мультиспецификация", "Multy")


def _tab_nu():
    _param_table("nu_params")


def _tab_tch():
    _param_table("tch_params")

    with _section("Настройки интервалов и аппроксимации"):
        with _table_kv():
            _row_kv("T нач. ТЧХ",                 "TCH_Temp_A")
            _row_kv("T кон. ТЧХ",                 "TCH_Temp_B")
            _row_kv("Тип интервала",              "TCH_Interval_Type")
            _row_kv("Имя интервала",              "IntervalName")
            _row_kv("Начало (A)",                 "A")
            _row_kv("Конец (B)",                  "B")
            _row_kv("Тип замера ТЧХ",             "TCHType")
            _row_kv("Аппроксимация",              "TCH_Approx_Type")
            _row_kv("Аппроксимация в программе",  "TCH_Approx_IST")
            _row_kv("Разбраковка ТЧХ по таблице", "TCHTable")
            _row_kv("Альтернативный полином",     "AltAppprox")
            _row_kv("Порядок полинома",           "polinom")
            _row_kv("Гармоника",                  "Garmonica")


def _tab_extra():
    _param_table("extra")


def _tab_rt():
    _param_table("rt")


def _tab_sphere():
    with _section("Коэффициенты"):
        with _table_kv():
            _row_kv("Коэффициент K1", "RsphereK1")
            _row_kv("Коэффициент K2", "RsphereK2")

    with _section("Нормы"):
        with dpg.table(header_row=True, resizable=False,
                       borders_innerH=True, borders_innerV=False,
                       row_background=True,
                       policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(label="Вкл",         init_width_or_weight=0.07)
            dpg.add_table_column(label="Параметр",    init_width_or_weight=0.32)
            dpg.add_table_column(label="Минимум",     init_width_or_weight=0.22)
            dpg.add_table_column(label="Максимум",    init_width_or_weight=0.22)
            dpg.add_table_column(label="Температура", init_width_or_weight=0.17)
            _param_row("Радиус сферы", "Rsphere",
                       "RsphereMin", "RsphereMax", "RsphereT", "T, C")


def _tab_quality():
    with _section("Материалы"):
        with _table_kv():
            _row_kv("Содержание золота",     "MetalAu")
            _row_kv("Содержание серебра",    "MetalAg")
            _row_kv("Содержание никеля",     "MetalNi")
            _row_kv("Эквивалент генератора", "TGK")

    with _section("Наработка и хранение"):
        with _table_kv():
            _row_kv("Минимальная наработка", "MinNar")
            _row_kv("Срок хранения",         "Hran")

    with _section("Параметры настройки"):
        with _table_kv():
            _row_kv("Средняя частота",         "Favg")
            _row_kv("Средняя добротность",     "Qavg")
            _row_kv("Поправочный коэф.",       "K")
            _row_kv("Точность настройки, Гц",  "FnastrHZ")

    with _section("Специальные флаги"):
        with _table_kv():
            _row_kv("Инвертировать Rc/Rb",     "INVERT_Rc_RB")
            _row_kv("Монотонность W2200",      "Mono_Approx_Type")
            _row_kv("Расчёт точности для ТГК", "Ftgk_Measure")


def _tab_corrections():
    with _section("Измерительные ёмкости, pF"):
        with _table_kv():
            _row_kv("Среднее ожидаемое C0",   "AVG_C0")
            _row_kv("Нагрузка W2200",         "W2200_CL")
            _row_kv("Нагрузка KH7700",        "KH7700_CL")
            _row_kv("Нагрузка TTS-100",       "TTS100_CL")
            _row_kv("Стат. ёмкость (флаг)",   "Tint")
            _row_kv("Стат. ёмкость, pF",      "TintValue")

    with _section("Коррекции"):
        with _table_kv():
            _row_kv("Коррекция R (физ.)",     "physical_R_Correction")
            _row_kv("Коррекция C0 (физ.)",    "physical_C0_correction")
            _row_kv("Коррекция C1 (физ.)",    "physical_C1_correction")
            _row_kv("Коррекция точности",     "F_correction")
            _row_kv("Коррекция ТЧХ",          "TCH_correction")
            _row_kv("Коррекция R (по RK)",    "R_correction")
            _row_kv("Коррекция Q (по RK)",    "Q_correction")
            _row_kv("FL расчётное",           "FL_Num")
            _row_kv("FL расчётное (вирт.)",   "FL_Num_Virt")

    with _section("Эквивалентное сопротивление"):
        with dpg.table(header_row=True, resizable=False,
                       borders_innerH=True, borders_innerV=False,
                       row_background=True,
                       policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(label="Вкл",         init_width_or_weight=0.07)
            dpg.add_table_column(label="Параметр",    init_width_or_weight=0.32)
            dpg.add_table_column(label="Минимум",     init_width_or_weight=0.22)
            dpg.add_table_column(label="Максимум",    init_width_or_weight=0.22)
            dpg.add_table_column(label="Температура", init_width_or_weight=0.17)
            _param_row("R экв., Ом", "Rekv",
                       "Rekv_min", "Rekv_max", None, None)

    with _section("Интерполяционные нормы"):
        with dpg.table(header_row=True, resizable=False,
                       borders_innerH=True, borders_innerV=False,
                       row_background=True,
                       policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(label="Вкл",         init_width_or_weight=0.07)
            dpg.add_table_column(label="Параметр",    init_width_or_weight=0.32)
            dpg.add_table_column(label="Минимум",     init_width_or_weight=0.22)
            dpg.add_table_column(label="Максимум",    init_width_or_weight=0.22)
            dpg.add_table_column(label="Температура", init_width_or_weight=0.17)
            _param_row("Макс. частота (интерп.)",
                       "Fmax_int", "Fmax_int_Min", "Fmax_int_Max", None, None)
            _param_row("Мин. частота (интерп.)",
                       "Fmin_int", "Fmin_int_Min", "Fmin_int_Max", None, None)
            _param_row("Частота (интерп.)",
                       "F_int", "Fint_Min", "Fint_Max", None, None)


def _tab_tolerances():
    all_cols = set(controller.columns())
    rows = controller.fetch_dopusk_map()

    if not rows:
        dpg.add_text(
            "Карта допусков недоступна (таблица spc_dopusk_map_table пуста).",
            color=COLOR_HINT,
        )
        return

    with _section("Допуски (абсолютные и процентные)"):
        with dpg.table(header_row=True, borders_innerH=True,
                       borders_innerV=True, row_background=True,
                       policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(label="Параметр",   init_width_or_weight=0.40)
            dpg.add_table_column(label="Абсолютный", init_width_or_weight=0.30)
            dpg.add_table_column(label="Процент, %", init_width_or_weight=0.30)

            for params, abs_col, pct_col in rows:
                if not params:
                    continue
                label = params[0]
                full = ", ".join(params)
                abs_ok = abs_col and abs_col in all_cols
                pct_ok = pct_col and pct_col in all_cols
                if not abs_ok and not pct_ok:
                    continue

                with dpg.table_row():
                    lbl_item = dpg.add_text(label, wrap=260)
                    with dpg.tooltip(lbl_item):
                        dpg.add_text(full, wrap=380)

                    if abs_ok:
                        _render_field_widget(abs_col, width=-1)
                    else:
                        dpg.add_text("")

                    if pct_ok and pct_col != abs_col:
                        _render_field_widget(pct_col, width=-1)
                    else:
                        dpg.add_text("")


def _tab_spur():
    all_cols = set(controller.columns())

    def cell(col):
        if col and col in all_cols:
            _render_field_widget(col, width=-1)
        else:
            dpg.add_text("")

    with _section("Общие"):
        with _table_kv():
            _row_kv("Использовать",                       "Spur_Use")
            _row_kv("Определять как",                     "Spur_Search")
            _row_kv("Записывать в интервале температур",  "Spur_Temp")

    resonances = [
        ("Номер 1", "Rsp1",
         "Spur_F_1_use", "Spur_F_1_Min", "Spur_F_1_Max", "Spur_F_1_AMP_Unit",
         "Rsp1min", "Rsp1max", "Rsp1tBegin", "Rsp1tEnd"),
        ("Номер 2", "Rsp2",
         "Spur_F_2_use", "Spur_F_2_Min", "Spur_F_2_Max", "Spur_F_2_AMP_Unit",
         "Rsp2min", "Rsp2max", "Rsp2tBegin", "Rsp2tEnd"),
        ("Номер 3", "Rsp3",
         "Spur_F_3_use", "Spur_F_3_Min", "Spur_F_3_Max", "Spur_F_3_AMP_Unit",
         "Rsp3min", "Rsp3max", "Rsp3tBegin", "Rsp3tEnd"),
    ]

    for (title, chk, use, mn, mx, amp, rmin, rmax, tb, te) in resonances:
        with _section(title):
            with dpg.table(header_row=True,
                           borders_innerH=True, borders_innerV=False,
                           row_background=True,
                           policy=dpg.mvTable_SizingStretchProp):
                dpg.add_table_column(label="",                init_width_or_weight=0.24)
                dpg.add_table_column(label="Вкл",             init_width_or_weight=0.06)
                dpg.add_table_column(label="Нижняя граница",  init_width_or_weight=0.18)
                dpg.add_table_column(label="Верхняя граница", init_width_or_weight=0.18)
                dpg.add_table_column(label="T нач., C",       init_width_or_weight=0.17)
                dpg.add_table_column(label="T кон., C",       init_width_or_weight=0.17)

                with dpg.table_row():
                    dpg.add_text(title)
                    cell(chk)
                    for _ in range(4):
                        dpg.add_text("")

                with dpg.table_row():
                    dpg.add_text("Полоса частот")
                    cell(use)
                    cell(mn)
                    cell(mx)
                    dpg.add_text("")
                    dpg.add_text("")

                with dpg.table_row():
                    dpg.add_text("По амплитуде")
                    cell(amp)
                    cell(rmin)
                    cell(rmax)
                    cell(tb)
                    cell(te)


def _tab_phase():
    with _section("Общее"):
        with _table_kv():
            _row_kv("Опции",          "PhazeNoise_Options")
            _row_kv("Тип генератора", "Generator_Type")

    _param_table("phase")


def _tab_options():
    with _section("Состав вывода"):
        with _table_kv():
            _row_kv("Статистика",       "Stat")
            _row_kv("Номер резонатора", "Snumber")
            _row_kv("Порядковый номер", "Number")
            _row_kv("Позиция в круге",  "Position")
            _row_kv("Статус",           "Status")
            _row_kv("Только числа",     "OnlyNumbers")

    with _section("Протокол"):
        with _table_kv():
            _row_kv("Печать протокола", "PrintProtokol")
            _row_kv("Тип протокола",    "Print")
            _row_kv("Вносить в БД",     "BD")
            _row_kv("Выводить нормы",   "norm")

    with _section("Графики"):
        with _table_kv():
            _row_kv("Печать графиков",          "PrintGraph")
            _row_kv("Печать в файл",            "GraphP")
            _row_kv("Тип графика",              "GraphF")
            _row_kv("Только аппроксимация",     "GraphOnlyAprox")
            _row_kv("Только замеренные точки",  "GraphOnluMeasure")

    with _section("Отбраковка"):
        with _table_kv():
            _row_kv("Брак",            "BadOnly")
            _row_kv("Годные",          "GoodOnly")
            _row_kv("Аномальные",      "Anomal")
            _row_kv("Аномальные по R", "AnomalR")


def _tab_print():
    with _section("Печать"):
        with _table_kv():
            _row_kv("Наименование при печати", "Text")
            _row_kv("Протокол",                "Protokol")
            _row_kv("Профиль печати",          "PrintProfile")


# ===========================================================================
# Окна
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


def _create_list_window():
    if dpg.does_item_exist(WIN_LIST_TAG):
        dpg.configure_item(WIN_LIST_TAG, show=True)
        return

    sw, sh = _get_screen_size()
    w = int(sw * 0.38)
    h = int(sh * 0.95)
    pos_x, pos_y = 10, 10

    with dpg.window(label="Спецификации", tag=WIN_LIST_TAG,
                    width=w, height=h, pos=(pos_x, pos_y), no_close=True):

        with dpg.group(horizontal=True):
            dpg.add_text("Поиск")
            # Поиск по Enter — не дёргаем SELECT на каждое нажатие
            dpg.add_input_text(tag=TAG_SEARCH, width=300, on_enter=True,
                               callback=lambda s, a, u: _refresh_list())
            dpg.add_button(label="Обновить", width=100,
                           callback=lambda: _refresh_list())
            dpg.add_button(label="Новая", width=100,
                           callback=lambda: _open_new_dialog())

        dpg.add_separator()

        with dpg.table(tag=TAG_TABLE, header_row=True, row_background=True,
                       resizable=True, borders_innerH=True,
                       borders_innerV=True,
                       policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(label="Название", init_width_or_weight=2.0)
            dpg.add_table_column(label="Тип",      init_width_or_weight=1.5)
            dpg.add_table_column(label="Номинал",  init_width_or_weight=1.0)
            dpg.add_table_column(label="Профиль",  init_width_or_weight=1.0)
            dpg.add_table_column(label="Тип изм.", init_width_or_weight=1.0)

        dpg.add_separator()
        dpg.add_text("", tag=TAG_STATUS, color=COLOR_SECTION)

    _refresh_list()


def _create_edit_window():
    if dpg.does_item_exist(WIN_EDIT_TAG):
        dpg.configure_item(WIN_EDIT_TAG, show=True)
        return

    # Прогреть метаданные колонок до отрисовки вкладок —
    # иначе _kind_of в момент создания виджетов вернёт "str".
    controller.columns()

    sw, sh = _get_screen_size()
    w = int(sw * 0.60)
    h = int(sh * 0.95)
    pos_x = int(sw * 0.38) + 20
    pos_y = 10

    with dpg.window(label="Редактор спецификации", tag=WIN_EDIT_TAG,
                    width=w, height=h, pos=(pos_x, pos_y), no_close=True):

        with dpg.group(horizontal=True):
            dpg.add_text("Спецификация:", color=COLOR_HEADER)
            dpg.add_input_text(tag="spec_editor_name_display",
                               width=340, readonly=True)
            dpg.add_spacer(width=20)
            dpg.add_button(label="Сохранить", width=110, callback=_on_save)
            dpg.add_button(label="Обновить",  width=110, callback=_on_reload)
            dpg.add_button(label="Удалить",   width=110, callback=_on_delete)

        dpg.add_separator()
        dpg.add_spacer(height=4)

        with dpg.tab_bar(tag=TAG_TAB_BAR):
            with dpg.tab(label="Основное"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_main()
            with dpg.tab(label="Параметры НУ"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_nu()
            with dpg.tab(label="Параметры ТЧХ"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_tch()
            with dpg.tab(label="Доп. параметры"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_extra()
            with dpg.tab(label="Параметры РТ"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_rt()
            with dpg.tab(label="Радиус сферы"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_sphere()
            with dpg.tab(label="Качество и характеристики"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_quality()
            with dpg.tab(label="Корректировка"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_corrections()
            with dpg.tab(label="Допуска"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_tolerances()
            with dpg.tab(label="Нежелательные резонансы"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_spur()
            with dpg.tab(label="Фазовые шумы"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_phase()
            with dpg.tab(label="Опции вывода"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_options()
            with dpg.tab(label="Печать"):
                with dpg.child_window(height=-1, width=-1, border=False):
                    _tab_print()


# ===========================================================================
# Контекстное меню (классическое оформление)
# ===========================================================================
CTX_MENU_TAG      = "spec_list_ctx_menu"
CTX_HEADER_TAG    = "spec_list_ctx_header"
CTX_HANDLER_TAG   = "spec_list_ctx_click_handler"
CTX_MENU_THEME    = "spec_list_ctx_menu_theme"
CTX_ITEM_THEME    = "spec_list_ctx_item_theme"

# Кеш item_handler_registry по имени спецификации
# { spec_name -> registry_tag }
#_ctx_registries: dict = {}


def _create_ctx_menu_themes():
    if not dpg.does_item_exist(CTX_MENU_THEME):
        with dpg.theme(tag=CTX_MENU_THEME):
            with dpg.theme_component(dpg.mvWindowAppItem):
                dpg.add_theme_color(dpg.mvThemeCol_WindowBg, (34, 37, 43, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Border, (110, 115, 125, 255))
                dpg.add_theme_color(dpg.mvThemeCol_PopupBg, (34, 37, 43, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Separator, (80, 85, 95, 255))
                dpg.add_theme_style(dpg.mvStyleVar_WindowRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_WindowBorderSize, 1)
                dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 2, 4)
                dpg.add_theme_style(dpg.mvStyleVar_ItemSpacing, 4, 2)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 12, 6)

    if not dpg.does_item_exist(CTX_ITEM_THEME):
        with dpg.theme(tag=CTX_ITEM_THEME):
            with dpg.theme_component(dpg.mvButton):
                dpg.add_theme_color(dpg.mvThemeCol_Button, (34, 37, 43, 0))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered, (65, 105, 160, 255))
                dpg.add_theme_color(dpg.mvThemeCol_ButtonActive, (85, 135, 195, 255))
                dpg.add_theme_color(dpg.mvThemeCol_Text, (225, 228, 235, 255))
                dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 0)
                dpg.add_theme_style(dpg.mvStyleVar_FramePadding, 12, 6)
                dpg.add_theme_style(dpg.mvStyleVar_FrameBorderSize, 0)


def _close_ctx_menu_on_click(sender, app_data):
    if not dpg.does_item_exist(CTX_MENU_TAG):
        return
    if not dpg.is_item_shown(CTX_MENU_TAG):
        return
    try:
        mx, my = dpg.get_mouse_pos(local=False)
        px, py = dpg.get_item_pos(CTX_MENU_TAG)
        mw = dpg.get_item_width(CTX_MENU_TAG) or 340
        mh = dpg.get_item_height(CTX_MENU_TAG) or 100
        inside = (px <= mx <= px + mw) and (py <= my <= py + mh)
        if not inside:
            dpg.configure_item(CTX_MENU_TAG, show=False)
    except Exception:
        pass


def _ensure_ctx_menu():
    """Создать окно контекстного меню (один раз)."""
    if dpg.does_item_exist(CTX_MENU_TAG):
        return CTX_MENU_TAG

    _create_ctx_menu_themes()

    dpg.add_window(
        tag=CTX_MENU_TAG,
        label="",
        modal=False,
        show=False,
        no_title_bar=True,
        no_resize=True,
        no_move=True,
        no_scrollbar=True,
        no_saved_settings=True,
        width=340,
        height=100,
    )
    dpg.bind_item_theme(CTX_MENU_TAG, CTX_MENU_THEME)

    dpg.add_text(
        "Спецификация",
        tag=CTX_HEADER_TAG,
        parent=CTX_MENU_TAG,
        color=(170, 180, 200, 255),
        wrap=320,
    )
    dpg.add_separator(parent=CTX_MENU_TAG)

    item1 = dpg.add_menu_item(
        label="Открыть редактор",
        parent=CTX_MENU_TAG,
        callback=_ctx_open_editor,
    )
    dpg.bind_item_theme(item1, CTX_ITEM_THEME)

    item2 = dpg.add_menu_item(
        label="Просмотр формы (как в измерениях)",
        parent=CTX_MENU_TAG,
        callback=_ctx_view_form,
    )
    dpg.bind_item_theme(item2, CTX_ITEM_THEME)

    if not dpg.does_item_exist(CTX_HANDLER_TAG):
        with dpg.handler_registry(tag=CTX_HANDLER_TAG):
            dpg.add_mouse_click_handler(
                button=dpg.mvMouseButton_Left,
                callback=_close_ctx_menu_on_click,
            )

    return CTX_MENU_TAG





def _on_spec_right_click(sender, app_data, spec_name):
    """Правый клик по строке списка спецификаций."""
    _ctx_spec_name[0] = spec_name
    tag = _ensure_ctx_menu()

    if dpg.does_item_exist(CTX_HEADER_TAG):
        short = spec_name if len(spec_name) <= 36 else spec_name[:33] + "..."
        dpg.set_value(CTX_HEADER_TAG, f"Спецификация: {short}")

    try:
        mx, my = dpg.get_mouse_pos(local=False)
        sw, sh = _get_screen_size()
        mw, mh = 340, 100
        px = max(4, min(int(mx), sw - mw - 10))
        py = max(4, min(int(my), sh - mh - 10))
        dpg.configure_item(tag, pos=(px, py))
    except Exception:
        pass

    dpg.configure_item(tag, show=True)
    dpg.focus_item(tag)


def _ctx_open_editor():
    name = _ctx_spec_name[0]
    dpg.configure_item(CTX_MENU_TAG, show=False)
    if name:
        _on_pick_spec(name)


def _ctx_view_form():
    name = _ctx_spec_name[0]
    dpg.configure_item(CTX_MENU_TAG, show=False)
    if name:
        _open_spec_preview_window(name)





def _ensure_ctx_shared_registry() -> str:
    if dpg.does_item_exist(_CTX_SHARED_REG):
        return _CTX_SHARED_REG
    with dpg.item_handler_registry(tag=_CTX_SHARED_REG):
        dpg.add_item_clicked_handler(
            button=dpg.mvMouseButton_Right,
            callback=_on_spec_right_click_shared,
        )
    return _CTX_SHARED_REG


def _on_spec_right_click_shared(sender, app_data, user_data):
    # spec_name лежит в user_data самого selectable
    spec_name = dpg.get_item_user_data(sender)
    _on_spec_right_click(sender, app_data, spec_name)


def _attach_right_click(item_id, spec_name):
    reg = _ensure_ctx_shared_registry()
    dpg.bind_item_handler_registry(item_id, reg)

# ===========================================================================
# Список спецификаций
# ===========================================================================
def _refresh_list():
    if not dpg.does_item_exist(TAG_TABLE):
        return
    for child in dpg.get_item_children(TAG_TABLE, 1) or []:
        dpg.delete_item(child)

    search = dpg.get_value(TAG_SEARCH) if dpg.does_item_exist(TAG_SEARCH) else ""
    try:
        rows = controller.list_specs(search=search)
    except Exception as e:
        _show_error("Ошибка загрузки списка", e)
        return


    for r in rows:
        spec_name = r["Name"]
        with dpg.table_row(parent=TAG_TABLE):
            item = dpg.add_selectable(
                label=str(spec_name or ""),
                callback=lambda s, a, u: _on_pick_spec(u),
                user_data=spec_name,
            )
            _attach_right_click(item, spec_name)
            dpg.add_text(str(r.get("NameR") or ""))
            dpg.add_text(str(r.get("Nominal") or ""))
            dpg.add_text(str(r.get("Profile") or ""))
            dpg.add_text(str(r.get("LoadType") or ""))

    if dpg.does_item_exist(TAG_STATUS):
        dpg.set_value(TAG_STATUS, f"Найдено: {len(rows)}")


def _fmt_num(v, prec=3):
    if v is None:
        return "---"
    if isinstance(v, float):
        if v == int(v):
            return f"{int(v)}"
        return f"{v:.{prec}f}"
    return str(v)


def _open_spec_preview_window(name: str):
    """Окно предпросмотра спецификации в стиле модуля измерений."""
    if not name:
        return
    win_tag = f"spec_preview_{name}"
    if dpg.does_item_exist(win_tag):
        dpg.delete_item(win_tag)
        return

    try:
        row = controller.load_spec(name)
    except SpecEditorError as e:
        _show_error(str(e))
        return

    norms = controller.get_spc_map_for_row(row)

    sw, sh = _get_screen_size()
    w = int(sw * 0.72)
    h = int(sh * 0.85)
    pos_x = max(20, (sw - w) // 2)
    pos_y = max(20, (sh - h) // 2)

    with dpg.window(label=f"Просмотр: {name}", tag=win_tag,
                    width=w, height=h, pos=(pos_x, pos_y),
                    no_collapse=True):

        with dpg.group(horizontal=True):
            dpg.add_text("Спецификация:", color=COLOR_HEADER)
            dpg.add_text(name)
            dpg.add_spacer(width=20)
            dpg.add_button(label="Закрыть", width=100,
                           callback=lambda: dpg.delete_item(win_tag))

        dpg.add_separator()

        dpg.add_text("Параметры спецификации", color=COLOR_SECTION)
        with dpg.table(header_row=True, borders_innerH=True,
                       borders_outerH=True, borders_innerV=True,
                       borders_outerV=True,
                       policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(label="Номинал")
            dpg.add_table_column(label="Профиль")
            dpg.add_table_column(label="Тип измерения")
            dpg.add_table_column(label="Ёмкость, пФ")
            dpg.add_table_column(label="Тип резонатора")
            with dpg.table_row():
                dpg.add_text(str(row.get("Nominal") or ""))
                dpg.add_text(str(row.get("Profile") or ""))
                dpg.add_text(str(row.get("LoadType") or ""))
                dpg.add_text(str(row.get("Loadvalue") or ""))
                dpg.add_text(str(row.get("NameR") or ""))

        dpg.add_spacer(height=8)

        dpg.add_text("Нормы параметров", color=COLOR_SECTION)
        dpg.add_separator()
        if not norms:
            dpg.add_text("Нормы не заданы (нет параметров с Use=1)",
                         color=COLOR_HINT)
        else:
            with dpg.table(header_row=True, borders_innerH=True,
                           borders_outerH=True, borders_innerV=True,
                           borders_outerV=True, resizable=True,
                           scrollY=True, height=int(h * 0.45),
                           policy=dpg.mvTable_SizingStretchProp):
                dpg.add_table_column(label="Параметр")
                dpg.add_table_column(label="Минимум")
                dpg.add_table_column(label="Максимум")
                dpg.add_table_column(label="Код")

                for n in norms:
                    with dpg.table_row():
                        dpg.add_text(n["Parameter"], color=(0, 255, 0))
                        dpg.add_text(_fmt_num(n["Min"]))
                        dpg.add_text(_fmt_num(n["Max"]))
                        dpg.add_text(n["Code"] or "")

        dpg.add_spacer(height=8)

        dpg.add_text("Значения в спецификации", color=COLOR_SECTION)
        dpg.add_separator()

        # Не показываем нули, "0.0", "False", "no" — только значимые данные
        skip_cols = {"Name", "ID"}
        common_defaults = {
            "0", "0.0", "0.00", "0.000", "0.0000",
            "false", "no", "",
        }
        value_rows = []
        for col, val in row.items():
            if col in skip_cols or val is None:
                continue
            sval = str(val).strip()
            if sval.lower() in common_defaults:
                continue
            value_rows.append((_label_of(col), sval))

        if not value_rows:
            dpg.add_text("Нет заполненных полей", color=COLOR_HINT)
        else:
            with dpg.table(header_row=True, borders_innerH=True,
                           borders_outerH=True, borders_innerV=True,
                           borders_outerV=True, resizable=True,
                           scrollY=True, height=int(h * 0.25),
                           policy=dpg.mvTable_SizingStretchProp):
                dpg.add_table_column(label="Поле")
                dpg.add_table_column(label="Значение")
                for label, sval in value_rows:
                    with dpg.table_row():
                        dpg.add_text(label, color=(180, 220, 255))
                        dpg.add_text(sval)


def _on_pick_spec(name: str):
    if not name:
        return
    _load_to_editor(name)
    if dpg.does_item_exist(WIN_EDIT_TAG):
        dpg.configure_item(WIN_EDIT_TAG, show=True)
        dpg.focus_item(WIN_EDIT_TAG)


# ===========================================================================
# Загрузка / сохранение
# ===========================================================================
def _load_to_editor(name: str):
    """Загрузить спецификацию в редактор (все зарегистрированные поля).

    Значение "no" в колонках-нормах трактуется как «норма не задана»
    и отображается пустым полем — так пользователю привычнее.
    """
    global _current_name
    try:
        data = controller.load_spec(name)
    except SpecEditorError as e:
        _show_error(str(e))
        return
    _current_name = name

    if dpg.does_item_exist("spec_editor_name_display"):
        dpg.set_value("spec_editor_name_display", name)
    if dpg.does_item_exist(WIN_EDIT_TAG):
        dpg.configure_item(WIN_EDIT_TAG,
                           label=f"Редактор спецификации - {name}")

    norm_cols = _get_norm_columns()

    for col, tag in _field_values.items():
        if not dpg.does_item_exist(tag):
            continue
        val = data.get(col)

        # "no" = «норма не задана» -> пустое поле в форме
        if col in norm_cols and isinstance(val, str) \
                and val.strip().lower() == "no":
            val = None

        try:
            kind = _kind_of(col)
            if isinstance(kind, tuple):
                dpg.set_value(tag, str(val) if val is not None else "")
            elif kind == "bool":
                dpg.set_value(tag, _to_bool(val))
            elif kind == "int":
                try:
                    dpg.set_value(tag, int(val or 0))
                except (TypeError, ValueError):
                    dpg.set_value(tag, 0)
            elif kind == "float":
                dpg.set_value(tag, "" if val is None else str(val))
            else:
                dpg.set_value(tag, "" if val is None else str(val))
        except Exception:
            pass

    _original_data.clear()
    _original_data.update(data)

def _load_to_editor_3(name: str):
    """Загрузить спецификацию в редактор (все зарегистрированные поля)."""
    global _current_name
    try:
        data = controller.load_spec(name)
    except SpecEditorError as e:
        _show_error(str(e))
        return
    _current_name = name

    if dpg.does_item_exist("spec_editor_name_display"):
        dpg.set_value("spec_editor_name_display", name)
    if dpg.does_item_exist(WIN_EDIT_TAG):
        dpg.configure_item(WIN_EDIT_TAG,
                           label=f"Редактор спецификации - {name}")

    for col, tag in _field_values.items():
        if not dpg.does_item_exist(tag):
            continue
        val = data.get(col)
        try:
            kind = _kind_of(col)
            if isinstance(kind, tuple):
                dpg.set_value(tag, str(val) if val is not None else "")
            elif kind == "bool":
                dpg.set_value(tag, _to_bool(val))
            elif kind == "int":
                try:
                    dpg.set_value(tag, int(val or 0))
                except (TypeError, ValueError):
                    dpg.set_value(tag, 0)
            elif kind == "float":
                dpg.set_value(tag, "" if val is None else str(val))
            else:
                dpg.set_value(tag, "" if val is None else str(val))
        except Exception:
            pass

    _original_data.clear()
    _original_data.update(data)


def _coerce_for_compare(v):
    if v is None:
        return None
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return str(float(v)) if isinstance(v, float) and v != int(v) else str(int(v))
    s = str(v).strip()
    if s.lower() in ("true", "1"):
        return "1"
    if s.lower() in ("false", "0", ""):
        return "0"
    try:
        return str(float(s.replace(",", ".")))
    except ValueError:
        return s

def _on_save():
    """Собрать значения из полей, нормализовать пустые нормы в "no"
    и сохранить спецификацию.

    Логика:
      * для колонок-норм (min/max/T, допуски, интервалы, резонансы…)
        пустое поле и значение "no"/"NO" трактуются как «норма не задана»
        и записываются в БД строкой "no";
      * остальные колонки сохраняются как есть (пустая строка / 0 / False);
      * в БД пишутся только реально изменившиеся значения
        (сравнение через _coerce_for_compare).
    """
    if not _current_name:
        _show_error("Не открыта спецификация")
        return

    norm_cols = _get_norm_columns()

    changed = {}
    total = 0
    print(f"\n[SpecEditor] === Сохранение '{_current_name}' ===")

    for col, tag in _field_values.items():
        if not dpg.does_item_exist(tag):
            continue
        total += 1
        v = dpg.get_value(tag)
        v_str = "" if v is None else str(v).strip()
        kind = _kind_of(col)

        # --- Нормализация значения ---
        # 1) Пустое поле или явное "no" в норме -> "no"
        if col in norm_cols and (not v_str or v_str.lower() == "no"):
            new_val = "no"

        # 2) Combo из enum-типа
        elif isinstance(kind, tuple):
            new_val = v

        # 3) Bool
        elif kind == "bool":
            new_val = bool(v)

        # 4) Int
        elif kind == "int":
            try:
                new_val = int(v)
            except (TypeError, ValueError):
                new_val = 0

        # 5) Float — через строку, т.к. поле input_text с decimal=True
        elif kind == "float":
            try:
                new_val = float(str(v).replace(",", "."))
            except (TypeError, ValueError):
                new_val = 0.0

        # 6) Строки / combo / прочее
        else:
            new_val = v

        old_val = _original_data.get(col)
        _original_data[col] = new_val

        # Сравниваем «как в БД» — чтобы 0 / "" / "no" / False
        # не порождали ложных изменений.
        if _coerce_for_compare(old_val) != _coerce_for_compare(new_val):
            changed[col] = (old_val, new_val)

    print(f"[SpecEditor] Всего виджетов: {total}")
    print(f"[SpecEditor] Изменилось полей: {len(changed)}")
    if changed:
        for col, (old, new) in changed.items():
            print(f"[SpecEditor]   {col}: {old!r} -> {new!r}")
    else:
        print("[SpecEditor] Изменений нет - БД не будет обновлена.")

    # Контроллер сам решит, что писать в БД и что в журнал.
    # Мы передаём полный набор _original_data, чтобы при сохранении
    # в БД попали все актуальные значения (а не только changed).
    try:
        controller.save_spec(_current_name, _original_data)
    except SpecEditorError as e:
        print(f"[SpecEditor] Ошибка сохранения: {e}")
        _show_error(str(e))
        return

    _refresh_list()
    if dpg.does_item_exist(TAG_STATUS):
        dpg.set_value(TAG_STATUS, f"Сохранено: {_current_name}")
    print(f"[SpecEditor] === Сохранение завершено ===\n")

def _on_save_3():
    if not _current_name:
        _show_error("Не открыта спецификация")
        return

    changed = {}
    total = 0
    print(f"\n[SpecEditor] === Сохранение '{_current_name}' ===")

    for col, tag in _field_values.items():
        if not dpg.does_item_exist(tag):
            continue
        total += 1
        v = dpg.get_value(tag)
        kind = _kind_of(col)

        if isinstance(kind, tuple):
            new_val = v
        elif kind == "bool":
            new_val = bool(v)
        elif kind == "int":
            try:
                new_val = int(v)
            except (TypeError, ValueError):
                new_val = 0
        elif kind == "float":
            try:
                new_val = float(str(v).replace(",", "."))
            except (TypeError, ValueError):
                new_val = 0.0
        else:
            new_val = v

        old_val = _original_data.get(col)
        _original_data[col] = new_val

        if _coerce_for_compare(old_val) != _coerce_for_compare(new_val):
            changed[col] = (old_val, new_val)

    print(f"[SpecEditor] Всего виджетов: {total}")
    print(f"[SpecEditor] Изменилось полей: {len(changed)}")
    if changed:
        for col, (old, new) in changed.items():
            print(f"[SpecEditor]   {col}: {old!r} -> {new!r}")
    else:
        print("[SpecEditor] Изменений нет - БД не будет обновлена.")

    try:
        controller.save_spec(_current_name, _original_data)
    except SpecEditorError as e:
        print(f"[SpecEditor] Ошибка сохранения: {e}")
        _show_error(str(e))
        return

    _refresh_list()
    if dpg.does_item_exist(TAG_STATUS):
        dpg.set_value(TAG_STATUS, f"Сохранено: {_current_name}")
    print(f"[SpecEditor] === Сохранение завершено ===\n")


def _on_reload():
    if _current_name:
        _load_to_editor(_current_name)


def _on_delete():
    global _current_name
    if not _current_name:
        _show_error("Не открыта спецификация")
        return
    name = _current_name
    try:
        controller.delete_spec(name)
    except SpecEditorError as e:
        _show_error(str(e))
        return
    _current_name = None
    if dpg.does_item_exist(WIN_EDIT_TAG):
        dpg.configure_item(WIN_EDIT_TAG, label="Редактор спецификации")
    if dpg.does_item_exist("spec_editor_name_display"):
        dpg.set_value("spec_editor_name_display", "")
    _refresh_list()
    if dpg.does_item_exist(TAG_STATUS):
        dpg.set_value(TAG_STATUS, f"Удалено: {name}")


# ===========================================================================
# Диалог новой спецификации
# ===========================================================================
def _on_toggle_nomenclature(sender, app_data, user_data):
    use_nom = bool(app_data)
    if dpg.does_item_exist("spec_new_nomenclature_group"):
        dpg.configure_item("spec_new_nomenclature_group", show=use_nom)
    if dpg.does_item_exist("spec_new_custom_group"):
        dpg.configure_item("spec_new_custom_group", show=not use_nom)


def _open_new_dialog():
    if dpg.does_item_exist(WIN_NEW_TAG):
        dpg.configure_item(WIN_NEW_TAG, show=True)
        return

    with dpg.window(label="Новая спецификация", tag=WIN_NEW_TAG,
                    modal=True, width=520, height=340, pos=(500, 280)):

        dpg.add_text("Имя новой спецификации")
        dpg.add_checkbox(
            label="Выбрать из номенклатуры",
            tag="spec_new_use_nomenclature",
            default_value=False,
            callback=_on_toggle_nomenclature,
        )

        with dpg.group(tag="spec_new_nomenclature_group", show=False):
            dpg.add_text("Наименование (номенклатура)")
            dpg.add_combo([], tag="spec_new_nomenclature", width=-1)

        with dpg.group(tag="spec_new_custom_group", show=True):
            dpg.add_text("Произвольное название")
            dpg.add_input_text(tag="spec_new_name", width=-1)

        dpg.add_spacer(height=8)
        dpg.add_text("Копировать поля из")
        dpg.add_combo([], tag="spec_new_base", width=-1)
        dpg.add_spacer(height=14)

        with dpg.group(horizontal=True):
            dpg.add_button(label="Создать", width=120,
                           callback=_on_create_new)
            dpg.add_button(label="Отмена", width=120,
                           callback=lambda: dpg.configure_item(WIN_NEW_TAG,
                                                               show=False))

    try:
        names = [r["Name"] for r in controller.list_specs()]
        dpg.configure_item("spec_new_base", items=[""] + names)
    except Exception:
        pass
    try:
        nom_names = controller.fetch_nominal()
        dpg.configure_item("spec_new_nomenclature", items=nom_names)
    except Exception as e:
        print(f"[SpecEditor] fetch_nominal error: {e}")


def _on_create_new():
    use_nom = bool(dpg.get_value("spec_new_use_nomenclature"))

    if use_nom:
        name = (dpg.get_value("spec_new_nomenclature") or "").strip()
    else:
        name = (dpg.get_value("spec_new_name") or "").strip()

    if not name:
        _show_error("Не задано имя спецификации")
        return

    base = dpg.get_value("spec_new_base") or None

    try:
        controller.create_spec(name, base_from=base)
    except SpecEditorError as e:
        _show_error(str(e))
        return

    dpg.configure_item(WIN_NEW_TAG, show=False)
    _refresh_list()
    _load_to_editor(name)


# ===========================================================================
# Точка входа
# ===========================================================================
def _register_for_window_manager():
    try:
        from window_manager import register, rebuild_menu
    except Exception:
        return
    register(WIN_LIST_TAG, "Редактор спецификаций - список",
             _create_list_window)
    register(WIN_EDIT_TAG, "Редактор спецификаций - форма",
             _create_edit_window)
    try:
        rebuild_menu()
    except Exception:
        pass

# ===========================================================================
# Первичная загрузка с индикатором выполнения
# ===========================================================================
LOADING_WINDOW_TAG = "spec_loading_window"

# Флаг «первичная загрузка уже выполнялась в этой сессии»
_initial_load_done = False

_LOADING_STATE = {
    "steps": [],
    "index": 0,
}


def _load_first_spec_to_editor():
    """Открыть первую спецификацию (если ничего ещё не открыто)."""
    if _current_name is not None:
        return
    try:
        rows = controller.list_specs()
        if rows:
            _load_to_editor(rows[0]["Name"])
    except Exception as e:
        print(f"[SpecEditor] load first spec error: {e}")


def _build_edit_tabs_only():
    """Создать только редактор (окна списка ещё нет — регистрируем позже)."""
    _create_edit_window()


def _loading_steps() -> list:
    """Список шагов загрузки: (label, callable).

    Порядок важен:
      1. сначала данные из БД (кеши),
      2. потом окна — список, редактор со всеми вкладками,
      3. потом первая спецификация,
      4. потом регистрация в менеджере окон.
    """
    return [
        # --- Данные из БД ---
        ("Метаданные колонок (specification)",    controller.columns),
        ("Список спецификаций",                   lambda: controller.list_specs()),
        ("Карта параметров (spc_map_table)",      controller._get_spc_map),
        ("Карта допусков (spc_dopusk_map_table)", controller.fetch_dopusk_map),
        ("Типы резонаторов",                      controller.fetch_resonator_types),
        ("Температурные профили",                 controller.fetch_profiles),
        ("Корпуса",                               controller.fetch_korpus),
        ("ТУ",                                    controller.fetch_tu),
        ("Режимы измерения (measuremode)",        controller.fetch_measure_modes),
        ("Типы ТЧХ (tch_measure_type)",           controller.fetch_tch_types),
        ("Аппроксимация ТЧХ (spc_approx_type)",   controller.fetch_tch_approx_types),
        ("Интервалы ТЧХ (spc_interval_type)",     controller.fetch_tch_interval_types),
        ("Номенклатура (nomeklatura_rk)",         controller.fetch_nominal),

        # --- Построение интерфейса ---
        ("Создание окна списка спецификаций",     _create_list_window),
        ("Создание окна редактора (вкладки)",     _build_edit_tabs_only),
        ("Загрузка первой спецификации",          _load_first_spec_to_editor),
        ("Регистрация в менеджере окон",          _register_for_window_manager),
    ]


def _show_loading_window():
    """Создать модальное окно с прогресс-баром."""
    if dpg.does_item_exist(LOADING_WINDOW_TAG):
        dpg.delete_item(LOADING_WINDOW_TAG)

    sw, sh = _get_screen_size()
    w, h = 540, 180
    pos_x = max(20, (sw - w) // 2)
    pos_y = max(20, (sh - h) // 2)

    with dpg.window(label="", tag=LOADING_WINDOW_TAG, modal=True,
                    no_title_bar=True, no_resize=True,
                    no_move=True, no_close=True,
                    width=w, height=h, pos=(pos_x, pos_y)):
        dpg.add_text("Первичная загрузка данных спецификаций",
                     color=COLOR_HEADER)
        dpg.add_separator()
        dpg.add_spacer(height=6)
        dpg.add_text("Подготовка...", tag="spec_loading_status",
                     color=COLOR_HINT)
        dpg.add_spacer(height=6)
        dpg.add_progress_bar(default_value=0.0, width=-1,
                             tag="spec_loading_progress")
        dpg.add_spacer(height=6)
        dpg.add_text("Выполняется один раз. Пожалуйста, подождите...",
                     color=COLOR_HINT)


def _loading_step_callback():
    """Обработать один шаг и запланировать следующий на следующем кадре."""
    state = _LOADING_STATE
    steps = state["steps"]
    idx = state["index"]
    total = len(steps)

    if idx >= total:
        if dpg.does_item_exist(LOADING_WINDOW_TAG):
            dpg.delete_item(LOADING_WINDOW_TAG)
        _finish_initial_load()
        return

    label, fn = steps[idx]

    # Обновляем статус перед выполнением шага
    if dpg.does_item_exist("spec_loading_status"):
        dpg.set_value("spec_loading_status",
                      f"({idx + 1}/{total}) {label}...")
    if dpg.does_item_exist("spec_loading_progress"):
        dpg.set_value("spec_loading_progress", idx / total)

    try:
        fn()
    except Exception as e:
        print(f"[SpecEditor] load '{label}' error: {e}")

    state["index"] = idx + 1

    if dpg.does_item_exist("spec_loading_progress"):
        dpg.set_value("spec_loading_progress", (idx + 1) / total)

    # Следующий шаг — на следующем кадре (UI успевает отрисоваться)
    dpg.set_frame_callback(dpg.get_frame_count() + 1,
                           _loading_step_callback)


def _finish_initial_load():
    """Финальный показ окон и регистрация в менеджере окон."""
    if dpg.does_item_exist(WIN_LIST_TAG):
        dpg.configure_item(WIN_LIST_TAG, show=True)
    if dpg.does_item_exist(WIN_EDIT_TAG):
        dpg.configure_item(WIN_EDIT_TAG, show=True)

    try:
        _register_for_window_manager()
    except Exception as e:
        print(f"[SpecEditor] register_for_window_manager error: {e}")

def create_spec_editor_window():
    """Точка входа: показать загрузку (один раз) и открыть редактор."""
    global _initial_load_done

    # Загрузка уже идёт — повторно не запускаем
    if dpg.does_item_exist(LOADING_WINDOW_TAG):
        return

    # Загрузка уже была — просто показываем готовые окна
    if _initial_load_done:
        if dpg.does_item_exist(WIN_LIST_TAG):
            dpg.configure_item(WIN_LIST_TAG, show=True)
        if dpg.does_item_exist(WIN_EDIT_TAG):
            dpg.configure_item(WIN_EDIT_TAG, show=True)
        try:
            _register_for_window_manager()
        except Exception:
            pass
        return

    # Пользователь для журнала
    try:
        controller.set_current_user(_get_login_user())
        print(f"[SpecEditor] user = {_get_login_user()}")
    except Exception as e:
        print(f"[SpecEditor] cannot set user: {e}")

    _LOADING_STATE["steps"] = _loading_steps()
    _LOADING_STATE["index"] = 0
    _show_loading_window()

    dpg.set_frame_callback(dpg.get_frame_count() + 1,
                           _loading_step_callback)
    _initial_load_done = True


def create_spec_editor_window_1():
    try:
        controller.set_current_user(_get_login_user())
        print(f"[SpecEditor] user = {_get_login_user()}")
    except Exception as e:
        print(f"[SpecEditor] cannot set user: {e}")
    _create_list_window()
    _create_edit_window()
    _register_for_window_manager()
    try:
        rows = controller.list_specs()
        if rows:
            _load_to_editor(rows[0]["Name"])
    except Exception as e:
        _show_error("Не удалось загрузить спецификации", e)


def show_spec_editor_window(sender=None, app_data=None, dpg_ref=None):
    create_spec_editor_window()