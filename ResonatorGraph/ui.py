"""
DearPyGui-интерфейс: график слева, панель выбора и окно метрик справа.
"""
import os
import sys
import datetime
import traceback

import dearpygui.dearpygui as dpg

from .constants import (
    WIN_TAG, WIN_CTRL_TAG, WIN_METRICS_TAG, OPT_TAG, ERR_TAG, PLOT_TAG,
    X_AXIS_TAG, Y_AXIS_TAG, LEGEND_TAG,
    WIN_GRID_TAG,
    TAG_TYPE, TAG_SPEC, TAG_MSK, TAG_NUMBER, TAG_PARAM,
    TAG_DEGREE, TAG_A, TAG_B, TAG_T, TAG_METRICS_GROUP,
    TAG_MEASURE_ID, TAG_MEASURE_ID_LIST, TAG_MSK_MANUAL,
    PARAMETERS, COLOR_KDE,
    TAG_WHEEL_SWITCH,
)

# ---- Источник данных: из constants (может отсутствовать — fallback) ----
try:
    from .constants import SOURCES, _source_state
except ImportError:  # pragma: no cover — на случай старой constants.py
    SOURCES = [
        ('Основная',  'psidata',           'psidatatemp'),
        ('Временная', 'psidata_temporary', 'psidatatemp_temporary'),
        ('Архивная',  'psidata_archive',   'psidatatemp_archive'),
    ]
    _source_state = {
        'main_table':  'psidata',
        'temps_table': 'psidatatemp',
        'label':       'Основная',
    }

# ---- Тег «Зафиксировать масштаб» (локально, если нет в constants) ----
try:
    from .constants import TAG_LOCK_SCALE
except ImportError:
    TAG_LOCK_SCALE = "rg_lock_scale"

from . import grid
from .logic import GraphController, GraphLogicError, Series


_grid_page = 0
_grid_total_pages = 1
_grid_page_numbers = []

_wheel_registered = False
_suppress_cascade = False

# ---------------------------------------------------------------------------
# Состояние
# ---------------------------------------------------------------------------
controller = GraphController()
_series_seq = 0
_last_series = []
_last_ylabel = "F, ppm"
_last_title = ""

# Фиксация масштаба:
#   enabled   — галочка установлена
#   captured  — текущие пределы захвачены и заморожены
_scale_state = {
    'enabled': False,
    'captured': False,
    'x_min': None, 'x_max': None,
    'y_min': None, 'y_max': None,
}

MARGIN = 8
RIGHT_COL_FRACTION = 0.20
MIN_RIGHT_W = 340
MIN_CHART_W = 600
CTRL_HEIGHT = 600
CTRL_MIN_H = 240
MIN_METRICS_H = 200


# ---------------------------------------------------------------------------
# Хелперы
# ---------------------------------------------------------------------------
def _on_plot_wheel(sender, app_data, user_data):
    """Колесо мыши над основным графиком - следующий/предыдущий номер."""
    if not dpg.does_item_exist(PLOT_TAG):
        return
    if not dpg.is_item_hovered(PLOT_TAG):
        return
    if not _get_chk(TAG_WHEEL_SWITCH, True):
        return
    if not (controller.msk or controller.measure_id):
        return

    numbers = controller.load_numbers(controller.msk)
    if not numbers:
        return

    cur = dpg.get_value(TAG_NUMBER) if dpg.does_item_exist(TAG_NUMBER) \
          else controller.number
    try:
        idx = numbers.index(cur)
    except ValueError:
        idx = 0

    delta = int(app_data)
    if delta > 0:
        idx = (idx - 1) % len(numbers)
    elif delta < 0:
        idx = (idx + 1) % len(numbers)
    else:
        return

    new_num = numbers[idx]
    controller.number = new_num
    _set_if_exists(TAG_NUMBER, new_num)
    _on_number_change()


def _render_distribution(stats):
    """Гладкая кривая плотности распределения."""
    global _last_ylabel, _last_title
    _clear_plot()

    if dpg.does_item_exist(LEGEND_TAG):
        dpg.configure_item(LEGEND_TAG, show=False)

    kx = stats.get("kde_x", [])
    ky = stats.get("kde_y", [])
    if not kx or not ky:
        _show_error("Недостаточно данных для кривой распределения")
        return

    _add_series(Series("Плотность", kx, ky, COLOR_KDE, "line"))

    unit = stats.get("unit", "")
    xlabel = stats["label"] + (f", {unit}" if unit else "")
    dpg.configure_item(X_AXIS_TAG, label=xlabel)
    dpg.configure_item(Y_AXIS_TAG, label="Плотность вероятности")

    dpg.set_axis_limits(X_AXIS_TAG, min(kx), max(kx))
    dpg.set_axis_limits(Y_AXIS_TAG, 0.0, max(ky) * 1.12)

    if stats.get("measure_id"):
        _last_title = (f"Распределение {stats['label']}  |  "
                       f"ID {stats['measure_id']}  |  n = {stats['count']}")
    else:
        _last_title = (f"Распределение {stats['label']}  |  "
                       f"МСК {controller.msk}  |  n = {stats['count']}")
    _last_ylabel = "Плотность вероятности"


def _ensure_wheel_handler():
    global _wheel_registered
    if _wheel_registered:
        return
    with dpg.handler_registry():
        dpg.add_mouse_wheel_handler(callback=_on_plot_wheel)
    _wheel_registered = True


def _next_tag():
    global _series_seq
    _series_seq += 1
    return f"rg_series_{_series_seq}"


def _set_if_exists(tag, value):
    if dpg.does_item_exist(tag):
        dpg.set_value(tag, value)


def _configure_if_exists(tag, **kwargs):
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, **kwargs)


def _get_chk(tag, default=False):
    return dpg.get_value(tag) if dpg.does_item_exist(tag) else default


def _reset_id_mode():
    if controller.measure_id is not None:
        controller.measure_id = None
    _set_if_exists(TAG_MEASURE_ID, "")
    _set_if_exists(TAG_MEASURE_ID_LIST, "")


def _make_line_theme(rgb):
    r, g, b = rgb
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvLineSeries):
            dpg.add_theme_color(dpg.mvPlotCol_Line, (r, g, b, 255),
                                category=dpg.mvThemeCat_Plots)
            dpg.add_theme_style(dpg.mvPlotStyleVar_LineWeight, 1.5,
                                category=dpg.mvThemeCat_Plots)
    return th


def _make_scatter_theme(rgb):
    r, g, b = rgb
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvScatterSeries):
            dpg.add_theme_color(dpg.mvPlotCol_MarkerFill, (r, g, b, 255),
                                category=dpg.mvThemeCat_Plots)
            dpg.add_theme_color(dpg.mvPlotCol_MarkerOutline, (r, g, b, 255),
                                category=dpg.mvThemeCat_Plots)
            dpg.add_theme_style(dpg.mvPlotStyleVar_MarkerSize, 4.0,
                                category=dpg.mvThemeCat_Plots)
    return th


def _clear_plot():
    children = dpg.get_item_children(Y_AXIS_TAG, 1) or []
    for ch in children:
        dpg.delete_item(ch)
    _last_series.clear()


def _add_series(series):
    tag = _next_tag()
    if series.kind == "line":
        dpg.add_line_series(series.xs, series.ys,
                            parent=Y_AXIS_TAG, tag=tag, label=series.label)
        th = _make_line_theme(series.color)
    else:
        dpg.add_scatter_series(series.xs, series.ys,
                               parent=Y_AXIS_TAG, tag=tag, label=series.label)
        th = _make_scatter_theme(series.color)
    dpg.bind_item_theme(tag, th)
    _last_series.append(series)


def _autofit_y(ys):
    """Подбор Y-границ. Если масштаб зафиксирован — ставим сохранённые."""
    if _scale_state['enabled'] and _scale_state['captured']:
        dpg.set_axis_limits(Y_AXIS_TAG,
                            _scale_state['y_min'],
                            _scale_state['y_max'])
        return
    if not ys:
        return
    ymin, ymax = min(ys), max(ys)
    if ymax == ymin:
        ymax = ymin + 1.0
    pad = max(0.1 * (ymax - ymin), 1e-6)
    dpg.set_axis_limits(Y_AXIS_TAG, ymin - pad, ymax + pad)


def _apply_x_limits():
    """Подбор X-границ. Если масштаб зафиксирован — ставим сохранённые."""
    if _scale_state['enabled'] and _scale_state['captured']:
        dpg.set_axis_limits(X_AXIS_TAG,
                            _scale_state['x_min'],
                            _scale_state['x_max'])
        return
    try:
        a, b = float(controller.A), float(controller.B)
        if b > a:
            dpg.set_axis_limits(X_AXIS_TAG, a, b)
    except Exception:
        pass


def _show_error(msg, exc=None):
    text = msg
    if exc is not None:
        text += f"\n{exc}"
        traceback.print_exc()
    if dpg.does_item_exist(ERR_TAG):
        dpg.delete_item(ERR_TAG)
    with dpg.window(label="Сообщение", modal=True, autosize=True,
                    pos=(400, 300), tag=ERR_TAG):
        dpg.add_text(text)
        dpg.add_button(label="OK",
                       callback=lambda: dpg.delete_item(ERR_TAG))


def _render_result(res):
    global _last_ylabel, _last_title
    _clear_plot()
    for s in res.series:
        _add_series(s)
    dpg.configure_item(X_AXIS_TAG, label=res.xlabel)
    dpg.configure_item(Y_AXIS_TAG, label=res.ylabel)
    _last_ylabel = res.ylabel
    _last_title = res.title

    hide = bool(res.meta.get("hide_legend", False))
    if dpg.does_item_exist(LEGEND_TAG):
        dpg.configure_item(LEGEND_TAG, show=not hide)

    # --- Фиксация масштаба ---
    # 1. Уже захвачен — принудительно ставим сохранённые пределы.
    if _scale_state['enabled'] and _scale_state['captured']:
        dpg.set_axis_limits(X_AXIS_TAG,
                            _scale_state['x_min'], _scale_state['x_max'])
        dpg.set_axis_limits(Y_AXIS_TAG,
                            _scale_state['y_min'], _scale_state['y_max'])
        return

    # 2. Обычный autofit.
    ys_all = []
    for s in res.series:
        ys_all.extend(s.ys)
    _autofit_y(ys_all)
    _apply_x_limits()

    # 3. Первый номер после включения галочки — захватываем пределы.
    if (_scale_state['enabled']
            and not _scale_state['captured']
            and res.series):
        try:
            x_lim = dpg.get_axis_limits(X_AXIS_TAG)
            y_lim = dpg.get_axis_limits(Y_AXIS_TAG)
            if x_lim and y_lim:
                _scale_state['x_min'], _scale_state['x_max'] = x_lim
                _scale_state['y_min'], _scale_state['y_max'] = y_lim
                _scale_state['captured'] = True
        except Exception:
            pass


def _render_result_old(res):
    global _last_ylabel, _last_title
    _clear_plot()
    for s in res.series:
        _add_series(s)
    dpg.configure_item(X_AXIS_TAG, label=res.xlabel)
    dpg.configure_item(Y_AXIS_TAG, label=res.ylabel)
    _last_ylabel = res.ylabel
    _last_title = res.title

    ys_all = []
    for s in res.series:
        ys_all.extend(s.ys)
    _autofit_y(ys_all)
    _apply_x_limits()


def _render_histogram(stats):
    """Нарисовать гистограмму распределения по МСК (оставлено для справки)."""
    global _last_ylabel, _last_title
    _clear_plot()

    centers = stats["hist_centers"]
    counts = stats["hist_counts"]

    if dpg.does_item_exist(LEGEND_TAG):
        dpg.configure_item(LEGEND_TAG, show=False)

    tag = _next_tag()
    dpg.add_bar_series(centers, counts, parent=Y_AXIS_TAG, tag=tag,
                       weight=0.9, label="Частота")
    th = _make_bar_theme((120, 180, 240))
    dpg.bind_item_theme(tag, th)

    dpg.configure_item(X_AXIS_TAG, label=stats["label"])
    dpg.configure_item(Y_AXIS_TAG, label="Количество, шт")

    dpg.set_axis_limits(X_AXIS_TAG, stats["hist_edges"][0],
                        stats["hist_edges"][-1])
    ymax = max(counts) if counts else 1
    dpg.set_axis_limits(Y_AXIS_TAG, 0, ymax * 1.15)

    _last_title = (f"Гистограмма {stats['label']} | "
                   f"МСК {controller.msk} | n = {stats['count']}")
    _last_ylabel = "Количество, шт"


def _make_bar_theme(rgb):
    r, g, b = rgb
    with dpg.theme() as th:
        with dpg.theme_component(dpg.mvBarSeries):
            dpg.add_theme_color(dpg.mvPlotCol_Fill, (r, g, b, 220),
                                category=dpg.mvThemeCat_Plots)
    return th


def _show_statistics(stats):
    if not dpg.does_item_exist(TAG_METRICS_GROUP):
        return

    for ch in dpg.get_item_children(TAG_METRICS_GROUP, 1) or []:
        dpg.delete_item(ch)

    if stats.get("measure_id"):
        head = (f"ID {stats['measure_id']}  |  {stats['label']} "
                f"при T = {stats['T_ref']:.1f} C")
    else:
        head = (f"МСК {controller.msk}  |  {stats['label']} "
                f"при T = {stats['T_ref']:.1f} C")
    dpg.add_text(head, parent=TAG_METRICS_GROUP, color=(200, 200, 255))
    dpg.add_separator(parent=TAG_METRICS_GROUP)

    if stats.get("skipped"):
        dpg.add_text(
            f"Пропущено (нет данных при T_ref): {len(stats['skipped'])}",
            parent=TAG_METRICS_GROUP, color=(230, 180, 100),
        )
        with dpg.tooltip(dpg.last_item()):
            dpg.add_text(", ".join(stats["skipped"][:50]) +
                         ("..." if len(stats["skipped"]) > 50 else ""))
        dpg.add_spacer(height=4, parent=TAG_METRICS_GROUP)

    dpg.add_text("Статистические параметры",
                 parent=TAG_METRICS_GROUP, color=(180, 220, 180))

    with dpg.table(parent=TAG_METRICS_GROUP, header_row=False,
                   borders_innerH=False, borders_innerV=False,
                   policy=dpg.mvTable_SizingStretchProp):
        dpg.add_table_column(init_width_or_weight=0.65)
        dpg.add_table_column(init_width_or_weight=0.35)

        rows = [
            ("Количество, шт", stats["count"]),
            ("Среднее",        _fmt(stats["mean"])),
            ("Медиана",        _fmt(stats["median"])),
            ("СКО (sigma)",    _fmt(stats["std"])),
            ("Минимум",        _fmt(stats["min"])),
            ("Максимум",       _fmt(stats["max"])),
            ("Q1 (25 %)",      _fmt(stats["q1"])),
            ("Q3 (75 %)",      _fmt(stats["q3"])),
            ("IQR",            _fmt(stats["iqr"])),
            ("Размах",         _fmt(stats["range"])),
        ]
        for k, v in rows:
            with dpg.table_row():
                dpg.add_text(k)
                dpg.add_text(str(v))

    dpg.add_spacer(height=6, parent=TAG_METRICS_GROUP)

    an = stats.get("anomalies", [])
    color = (255, 160, 160) if an else (180, 220, 180)
    dpg.add_text(f"Аномальные экземпляры ({len(an)})",
                 parent=TAG_METRICS_GROUP, color=color)

    if not an:
        dpg.add_text("Не обнаружено", parent=TAG_METRICS_GROUP)
        return

    with dpg.table(parent=TAG_METRICS_GROUP, header_row=True,
                   borders_innerH=True, borders_innerV=True,
                   policy=dpg.mvTable_SizingStretchProp):
        dpg.add_table_column(label="N",      init_width_or_weight=0.35)
        dpg.add_table_column(label="Знач.",  init_width_or_weight=0.30)
        dpg.add_table_column(label="|z|",    init_width_or_weight=0.20)
        dpg.add_table_column(label="IQR",    init_width_or_weight=0.15)

        for a in an:
            with dpg.table_row():
                dpg.add_text(a["number"])
                dpg.add_text(_fmt(a["value"]))
                dpg.add_text(str(a["z_score"]))
                dpg.add_text("да" if a["iqr_out"] else "-")

        with dpg.tooltip(dpg.last_item()):
            dpg.add_text(
                "IQR - выход за пределы\n"
                "[Q1 - 1.5*IQR ; Q3 + 1.5*IQR]"
            )

    dpg.add_spacer(height=4, parent=TAG_METRICS_GROUP)
    dpg.add_text("Критерий: |z| > 3  или  выход за 1.5*IQR",
                 parent=TAG_METRICS_GROUP, color=(140, 140, 140))


# ---------------------------------------------------------------------------
# Форматирование чисел
# ---------------------------------------------------------------------------
def _fmt(v, digits: int = 4) -> str:
    if isinstance(v, str):
        return v
    try:
        f = float(v)
    except (TypeError, ValueError):
        return str(v)

    a = abs(f)
    if a == 0:
        return "0"
    if a >= 1e6 or a < 1e-3:
        return f"{f:.{digits}g}"
    return f"{f:.{digits}f}".rstrip("0").rstrip(".")


def _show_statistics_old(stats):
    if not dpg.does_item_exist(TAG_METRICS_GROUP):
        return
    for ch in dpg.get_item_children(TAG_METRICS_GROUP, 1) or []:
        dpg.delete_item(ch)

    dpg.add_text(f"МСК {controller.msk}  |  {stats['label']}",
                 parent=TAG_METRICS_GROUP, color=(200, 200, 255))
    dpg.add_separator(parent=TAG_METRICS_GROUP)

    dpg.add_text("Статистические параметры",
                 parent=TAG_METRICS_GROUP, color=(180, 220, 180))
    with dpg.table(parent=TAG_METRICS_GROUP, header_row=False,
                   borders_innerH=False, borders_innerV=False,
                   policy=dpg.mvTable_SizingStretchProp):
        dpg.add_table_column(init_width_or_weight=0.65)
        dpg.add_table_column(init_width_or_weight=0.35)
        rows = [
            ("Количество, шт", stats["count"]),
            ("Среднее",        round(stats["mean"], 4)),
            ("Медиана",        round(stats["median"], 4)),
            ("СКО (sigma)",    round(stats["std"], 4)),
            ("Минимум",        round(stats["min"], 4)),
            ("Максимум",       round(stats["max"], 4)),
            ("Q1 (25 %)",      round(stats["q1"], 4)),
            ("Q3 (75 %)",      round(stats["q3"], 4)),
            ("IQR",            round(stats["iqr"], 4)),
            ("Размах",         round(stats["range"], 4)),
        ]
        for k, v in rows:
            with dpg.table_row():
                dpg.add_text(k)
                dpg.add_text(str(v))

    dpg.add_spacer(height=6, parent=TAG_METRICS_GROUP)

    an = stats["anomalies"]
    color = (255, 160, 160) if an else (180, 220, 180)
    dpg.add_text(f"Аномальные экземпляры ({len(an)})",
                 parent=TAG_METRICS_GROUP, color=color)
    if not an:
        dpg.add_text("Не обнаружено", parent=TAG_METRICS_GROUP)
        return

    with dpg.table(parent=TAG_METRICS_GROUP, header_row=True,
                   borders_innerH=True, borders_innerV=True,
                   policy=dpg.mvTable_SizingStretchProp):
        dpg.add_table_column(label="N")
        dpg.add_table_column(label="Знач.")
        dpg.add_table_column(label="|z|")
        dpg.add_table_column(label="IQR")
        for a in an:
            with dpg.table_row():
                dpg.add_text(a["number"])
                dpg.add_text(f"{a['value']:.4g}")
                dpg.add_text(f"{a['z_score']}")
                dpg.add_text("да" if a["iqr_out"] else "-")


def _on_msk_statistics(sender=None, app_data=None, user_data=None):
    _sync_controller_from_ui()
    try:
        stats = controller.compute_msk_statistics(bins=15)
    except GraphLogicError as e:
        _show_error(str(e))
        return
    except Exception as e:
        _show_error("Ошибка расчёта статистики", e)
        return

    _render_distribution(stats)
    _show_statistics(stats)


# ---------------------------------------------------------------------------
# Метрики
# ---------------------------------------------------------------------------
def _update_metrics():
    if not dpg.does_item_exist(TAG_METRICS_GROUP):
        return
    for ch in dpg.get_item_children(TAG_METRICS_GROUP, 1) or []:
        dpg.delete_item(ch)

    if not (controller.number and (controller.msk or controller.measure_id)):
        dpg.add_text("Нет данных", parent=TAG_METRICS_GROUP)
        return

    try:
        m = controller.compute_metrics()
    except GraphLogicError as e:
        dpg.add_text(str(e), parent=TAG_METRICS_GROUP)
        return
    except Exception as e:
        dpg.add_text(f"Ошибка: {e}", parent=TAG_METRICS_GROUP)
        traceback.print_exc()
        return

    if controller.measure_id:
        header = f"N{controller.number}  |  ID {controller.measure_id}"
    else:
        header = f"N{controller.number}  |  МСК {controller.msk}"
    dpg.add_text(header, parent=TAG_METRICS_GROUP, color=(200, 200, 255))
    dpg.add_separator(parent=TAG_METRICS_GROUP)

    groups = {
        "Общие": ["Точек", "T минимум, C", "T максимум, C"],
        "Частоты": ["F min, Гц", "F max, Гц", "FL min, Гц", "FL max, Гц"],
        "Экстремумы": ["T экстремум min, C", "T экстремум max, C"],
        "Анализ": [],
    }
    known = set()
    for v in groups.values():
        known.update(v)
    for k in m.keys():
        if k not in known:
            groups["Анализ"].append(k)

    for title, keys in groups.items():
        present = [k for k in keys if k in m]
        if not present:
            continue
        dpg.add_text(title, parent=TAG_METRICS_GROUP, color=(180, 220, 180))
        with dpg.table(parent=TAG_METRICS_GROUP,
                       header_row=False, borders_innerH=False,
                       borders_innerV=False, policy=dpg.mvTable_SizingStretchProp):
            dpg.add_table_column(init_width_or_weight=0.65)
            dpg.add_table_column(init_width_or_weight=0.35)
            for k in present:
                with dpg.table_row():
                    dpg.add_text(k)
                    dpg.add_text(str(m[k]))
        dpg.add_spacer(height=4, parent=TAG_METRICS_GROUP)


# ---------------------------------------------------------------------------
# Каскад
# ---------------------------------------------------------------------------
def _on_type_change(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    _reset_id_mode()
    controller.rtype = dpg.get_value(TAG_TYPE)
    try:
        specs = controller.load_specs(controller.rtype)
    except Exception as e:
        _show_error("Ошибка загрузки спецификаций", e)
        return
    _configure_if_exists(TAG_SPEC, items=specs)
    _set_if_exists(TAG_SPEC, specs[0] if specs else "")
    for t in (TAG_MSK, TAG_NUMBER):
        _configure_if_exists(t, items=[])
        _set_if_exists(t, "")
    if specs:
        _on_spec_change()


def _on_spec_change(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    _reset_id_mode()
    controller.spec = dpg.get_value(TAG_SPEC)
    # Степень полинома по умолчанию — из спецификации (если юзер не задал вручную)
    try:
        controller.load_spec_defaults(controller.spec)
    except Exception:
        pass
    _set_if_exists(TAG_DEGREE, controller.degree)
    try:
        msks = controller.load_msks(controller.spec)
    except Exception as e:
        _show_error("Ошибка загрузки МСК", e)
        return
    _configure_if_exists(TAG_MSK, items=msks)
    if msks:
        _set_if_exists(TAG_MSK, msks[0])
        _on_msk_change()
    else:
        _set_if_exists(TAG_MSK, "")


def _apply_msk_selection(msk: str):
    """
    Единая логика выбора МСК:
      1. Загрузить все Measure_ID, принадлежащие этой МСК.
      2. Заселить поле ручного ввода и combo этими ID.
      3. Если ID ровно один - выбрать его и загрузить данные.
      4. Если ID несколько - выбрать первый, загрузить данные.
      5. Если ID нет - очистить оба поля и загрузить по МСК.
    """
    try:
        ids = controller.load_measure_ids(msk)
    except Exception as e:
        _show_error("Ошибка загрузки ID замеров", e)
        ids = []

    _configure_if_exists(TAG_MEASURE_ID_LIST, items=ids)

    if ids:
        controller.measure_id = ids[0]
        _set_if_exists(TAG_MEASURE_ID, ids[0])
        _set_if_exists(TAG_MEASURE_ID_LIST, ids[0])
    else:
        controller.measure_id = None
        _set_if_exists(TAG_MEASURE_ID, "")
        _set_if_exists(TAG_MEASURE_ID_LIST, "")

    try:
        nums = controller.load_numbers(msk)
    except Exception as e:
        _show_error("Ошибка загрузки номеров", e)
        return
    _configure_if_exists(TAG_NUMBER, items=nums)
    if nums:
        _set_if_exists(TAG_NUMBER, nums[0])
        _on_number_change()
    else:
        _set_if_exists(TAG_NUMBER, "")
        _update_metrics()


def _on_msk_change(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    _reset_id_mode()
    controller.msk = dpg.get_value(TAG_MSK)
    _apply_msk_selection(controller.msk)


def _on_msk_manual_enter(sender=None, app_data=None, user_data=None):
    """Загрузить данные по введённому вручную МСК (по Enter)."""
    global _suppress_cascade

    if _suppress_cascade:
        return
    if not dpg.does_item_exist(TAG_MSK_MANUAL):
        return
    msk = (dpg.get_value(TAG_MSK_MANUAL) or "").strip()
    if not msk:
        return

    controller.measure_id = None
    _set_if_exists(TAG_MEASURE_ID, "")
    _set_if_exists(TAG_MEASURE_ID_LIST, "")

    try:
        info = controller.load_by_msk(msk)
    except Exception as e:
        _show_error("Ошибка загрузки по МСК", e)
        return
    if info is None:
        _show_error(f"МСК \"{msk}\" не найден в БД")
        return

    controller.msk = msk
    controller.spec = info["spc"]
    controller.rtype = info["rtype"]

    _suppress_cascade = True
    try:
        _set_if_exists(TAG_TYPE, info["rtype"] or "")
        if info["rtype"]:
            try:
                specs = controller.load_specs(info["rtype"])
                _configure_if_exists(TAG_SPEC, items=specs)
            except Exception:
                pass
        _set_if_exists(TAG_SPEC, info["spc"] or "")
        _set_if_exists(TAG_MSK, msk)
        _set_if_exists(TAG_DEGREE, controller.degree)
    finally:
        _suppress_cascade = False

    _apply_msk_selection(msk)


def _on_measure_id_pick(sender=None, app_data=None, user_data=None):
    """Выбор ID из выпадающего списка: копируем в поле ввода и грузим."""
    if not dpg.does_item_exist(TAG_MEASURE_ID_LIST):
        return
    mid = (dpg.get_value(TAG_MEASURE_ID_LIST) or "").strip()
    if not mid:
        return
    _set_if_exists(TAG_MEASURE_ID, mid)
    _on_measure_id_enter()


def _on_measure_id_enter(sender=None, app_data=None, user_data=None):
    """Обработчик поля ручного ввода ID замера (по Enter)."""
    global _suppress_cascade

    if _suppress_cascade:
        return
    if not dpg.does_item_exist(TAG_MEASURE_ID):
        return
    mid = (dpg.get_value(TAG_MEASURE_ID) or "").strip()
    if not mid:
        return

    try:
        info = controller.load_by_measure_id(mid)
    except Exception as e:
        _show_error("Ошибка загрузки по ID замера", e)
        return
    if info is None:
        _show_error(f"ID замера \"{mid}\" не найден в БД")
        return

    controller.measure_id = mid
    controller.rtype = info["rtype"]
    controller.spec = info["spc"]
    controller.msk = info["msk"] or ""

    _suppress_cascade = True
    try:
        _set_if_exists(TAG_TYPE, info["rtype"] or "")
        if info["rtype"]:
            try:
                specs = controller.load_specs(info["rtype"])
                _configure_if_exists(TAG_SPEC, items=specs)
            except Exception:
                pass
        _set_if_exists(TAG_SPEC, info["spc"] or "")
        if info["spc"]:
            try:
                msks = controller.load_msks(info["spc"])
                _configure_if_exists(TAG_MSK, items=msks)
            except Exception:
                pass
        _set_if_exists(TAG_MSK, info["msk"] or "")
        # Степень могла обновиться из спецификации — синхронизируем UI
        _set_if_exists(TAG_DEGREE, controller.degree)
    finally:
        _suppress_cascade = False

    try:
        ids = controller.load_measure_ids(controller.msk)
        _configure_if_exists(TAG_MEASURE_ID_LIST, items=ids)
        _set_if_exists(TAG_MEASURE_ID_LIST, mid if mid in ids else "")
    except Exception:
        pass

    numbers = info["numbers"]
    _configure_if_exists(TAG_NUMBER, items=numbers)
    if numbers:
        _set_if_exists(TAG_NUMBER, numbers[0])
        _on_number_change()
    else:
        _set_if_exists(TAG_NUMBER, "")
        _update_metrics()
        _show_error(f"В замере \"{mid}\" нет номеров")


def _on_number_change(sender=None, app_data=None, user_data=None):
    controller.number = dpg.get_value(TAG_NUMBER)
    if not controller.number:
        _update_metrics()
        return
    try:
        t0, t1 = controller.load_temperature_bounds(controller.msk,
                                                    controller.number)
        if t0 is not None and t1 is not None:
            rng = t1 - t0
            # Границы A/B пересчитываются автоматически,
            # только если пользователь не задавал их вручную.
            if not controller.A_user_set:
                controller.A = t0 - 0.1 * rng
            if not controller.B_user_set:
                controller.B = t1 + 0.1 * rng
            _set_if_exists(TAG_A, controller.A)
            _set_if_exists(TAG_B, controller.B)
            _apply_x_limits()

        tref = controller.load_reference_temperature(controller.spec)
        if tref is not None:
            controller.T_ref = tref
            _set_if_exists(TAG_T, controller.T_ref)
    except Exception as e:
        _show_error("Ошибка загрузки данных о номере", e)
        return

    _auto_draw()
    _update_metrics()


def _on_param_change(sender=None, app_data=None, user_data=None):
    controller.param_label = dpg.get_value(TAG_PARAM)
    if controller.number:
        _auto_draw()
        _update_metrics()


# ---------------------------------------------------------------------------
# Источник данных и поиск (по образцу Archive)
# ---------------------------------------------------------------------------
def _on_source_changed(sender=None, app_data=None, user_data=None):
    try:
        from .constants import set_source
    except ImportError:
        return
    label = dpg.get_value("rg_source_combo")
    if not set_source(label):
        return

    # Сброс текущего состояния — данные из другого источника.
    controller.measure_id = None
    _set_if_exists(TAG_MEASURE_ID, "")
    _set_if_exists(TAG_MEASURE_ID_LIST, "")
    _set_if_exists(TAG_MEASURE_ID_LIST, "")
    _configure_if_exists(TAG_MEASURE_ID_LIST, items=[])

    try:
        types = controller.load_types()
        dpg.configure_item(TAG_TYPE, items=types)
        if types:
            dpg.set_value(TAG_TYPE, types[0])
            _on_type_change()
    except Exception as e:
        _show_error("Ошибка загрузки типов после смены источника", e)


def _on_numbers_search(sender=None, app_data=None, user_data=None):
    from .numbers_search import (
        parse_numbers_input, find_measure_ids_by_numbers,
    )
    if not dpg.does_item_exist("rg_numbers_input"):
        return
    raw = dpg.get_value("rg_numbers_input") or ""
    nums = parse_numbers_input(raw)
    if not nums:
        _show_error("Введите номера: 'JN4450' | 'JN4450,JN4451' | "
                    "'JN4450-JN4460'")
        return
    try:
        mids = find_measure_ids_by_numbers(nums)
    except Exception as e:
        _show_error("Ошибка поиска по номерам", e)
        return
    if not mids:
        _show_error(f"Замеры по {len(nums)} номерам не найдены")
        return
    items = [str(m) for m in mids]
    dpg.configure_item(TAG_MEASURE_ID_LIST, items=items)
    first = items[0]
    dpg.set_value(TAG_MEASURE_ID_LIST, first)
    dpg.set_value(TAG_MEASURE_ID, first)
    _on_measure_id_enter()


def _on_msk_partial_search(sender=None, app_data=None, user_data=None):
    from .numbers_search import search_msk_by_partial
    if not dpg.does_item_exist("rg_msk_partial_input"):
        return
    partial = (dpg.get_value("rg_msk_partial_input") or "").strip()
    if not partial:
        return
    try:
        msks = search_msk_by_partial(partial)
    except Exception as e:
        _show_error("Ошибка поиска МСК", e)
        return
    if not msks:
        _show_error(f'МСК по "{partial}" не найдены')
        return
    dpg.configure_item(TAG_MSK, items=msks)
    dpg.set_value(TAG_MSK, msks[0])
    _on_msk_change()


# ---------------------------------------------------------------------------
# Настройки: степень / границы / фиксация масштаба
# ---------------------------------------------------------------------------
def _on_degree_changed(sender=None, app_data=None, user_data=None):
    if dpg.does_item_exist(TAG_DEGREE):
        try:
            controller.degree = int(dpg.get_value(TAG_DEGREE))
            controller.degree_user_set = True
        except (TypeError, ValueError):
            pass
    _auto_draw()
    _update_metrics()


def _on_bounds_changed(sender=None, app_data=None, user_data=None):
    if dpg.does_item_exist(TAG_A):
        try:
            controller.A = float(dpg.get_value(TAG_A))
            controller.A_user_set = True
        except (TypeError, ValueError):
            pass
    if dpg.does_item_exist(TAG_B):
        try:
            controller.B = float(dpg.get_value(TAG_B))
            controller.B_user_set = True
        except (TypeError, ValueError):
            pass
    _apply_x_limits()
    _auto_draw()
    _update_metrics()


def _on_lock_scale_changed(sender=None, app_data=None, user_data=None):
    if not dpg.does_item_exist(TAG_LOCK_SCALE):
        return
    enabled = bool(dpg.get_value(TAG_LOCK_SCALE))

    _scale_state.update({
        'enabled': enabled,
        'captured': False,
        'x_min': None, 'x_max': None,
        'y_min': None, 'y_max': None,
    })

    if not enabled:
        # Снят — обычный autofit текущего номера.
        if controller.number and (controller.msk or controller.measure_id):
            _auto_draw()
        return

    # Включён: если что-то уже нарисовано — захватываем сразу.
    if (_last_series and controller.number
            and (controller.msk or controller.measure_id)):
        try:
            x_lim = dpg.get_axis_limits(X_AXIS_TAG)
            y_lim = dpg.get_axis_limits(Y_AXIS_TAG)
            if x_lim and y_lim:
                _scale_state['x_min'], _scale_state['x_max'] = x_lim
                _scale_state['y_min'], _scale_state['y_max'] = y_lim
                _scale_state['captured'] = True
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Автопостроение
# ---------------------------------------------------------------------------
def _opts_from_ui():
    degree = controller.degree
    if dpg.does_item_exist(TAG_DEGREE):
        degree = int(dpg.get_value(TAG_DEGREE))
    return {
        "degree":       degree,
        "show_approx":  _get_chk("chk_show_approx",  True),
        "show_coeffs":  _get_chk("chk_show_coeffs",  False),
        "show_order":   _get_chk("chk_show_order",   True),
        "show_msk":     _get_chk("chk_show_msk",     True),
    }


def _sync_controller_from_ui():
    if dpg.does_item_exist(TAG_A):
        controller.A = float(dpg.get_value(TAG_A))
    if dpg.does_item_exist(TAG_B):
        controller.B = float(dpg.get_value(TAG_B))
    if dpg.does_item_exist(TAG_T):
        controller.T_ref = float(dpg.get_value(TAG_T))
    if dpg.does_item_exist(TAG_DEGREE):
        controller.degree = int(dpg.get_value(TAG_DEGREE))
    controller.param_label = dpg.get_value(TAG_PARAM)
    controller.msk = dpg.get_value(TAG_MSK)
    controller.number = dpg.get_value(TAG_NUMBER)
    if dpg.does_item_exist(TAG_MEASURE_ID):
        mid = (dpg.get_value(TAG_MEASURE_ID) or "").strip()
        controller.measure_id = mid or None


def _auto_draw(silent=True):
    if not (controller.number and (controller.msk or controller.measure_id)):
        return
    try:
        base = controller.build_points(show_points=True, show_msk=True)
        appr = controller.build_approximation(_opts_from_ui())
        appr.series = appr.series + base.series
    except GraphLogicError as e:
        if not silent:
            _show_error(str(e))
        return
    except Exception as e:
        if not silent:
            _show_error("Ошибка автопостроения", e)
        else:
            traceback.print_exc()
        return
    _render_result(appr)


# ---------------------------------------------------------------------------
# Кнопки
# ---------------------------------------------------------------------------
def _on_build(sender=None, app_data=None, user_data=None):
    _sync_controller_from_ui()
    try:
        res = controller.build_points(show_points=True, show_msk=True)
    except GraphLogicError as e:
        _show_error(str(e))
        return
    except Exception as e:
        _show_error("Ошибка выборки данных", e)
        return
    _render_result(res)
    _update_metrics()


def _on_approx(sender=None, app_data=None, user_data=None):
    _sync_controller_from_ui()
    try:
        base = controller.build_points(show_points=True, show_msk=True)
        appr = controller.build_approximation(_opts_from_ui())
        appr.series = appr.series + base.series
    except GraphLogicError as e:
        _show_error(str(e))
        return
    except Exception as e:
        _show_error("Ошибка аппроксимации", e)
        return
    _render_result(appr)
    _update_metrics()


def _on_all_numbers(sender=None, app_data=None, user_data=None):
    _sync_controller_from_ui()
    try:
        res = controller.build_all_numbers(show_msk=True)
    except GraphLogicError as e:
        _show_error(str(e))
        return
    except Exception as e:
        _show_error("Ошибка построения всех номеров", e)
        return
    _render_result(res)


# ---------------------------------------------------------------------------
# Экспорт PNG
# ---------------------------------------------------------------------------
def _save_png(path, title, ylabel):
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        _show_error("Установите matplotlib:\n pip install matplotlib")
        return False

    fig, ax = plt.subplots(figsize=(10, 6))
    for s in _last_series:
        rgb = tuple(c / 255 for c in s.color)
        if s.kind == "line":
            ax.plot(s.xs, s.ys, "-", color=rgb, linewidth=1.5, label=s.label)
        else:
            ax.scatter(s.xs, s.ys, s=22, color=rgb, label=s.label,
                       edgecolors="black", linewidths=0.5, zorder=3)
    ax.set_xlabel("T, C")
    ax.set_ylabel(ylabel)
    ax.set_title(title)
    ax.grid(True, linestyle="--", alpha=0.5)
    ax.legend()
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return True


def _on_print(sender=None, app_data=None, user_data=None):
    if not _last_series:
        _show_error("Нет построенного графика")
        return
    out_dir = os.path.join(os.path.expanduser("~"), "ResonatorGraphs")
    os.makedirs(out_dir, exist_ok=True)
    fname = f"{controller.number}_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
    path = os.path.join(out_dir, fname)
    if _save_png(path, _last_title, _last_ylabel):
        _show_error(f"График сохранён:\n{path}")


# ---------------------------------------------------------------------------
# Экспорт PDF (9 графиков на страницу)
# ---------------------------------------------------------------------------
def _open_file(path):
    try:
        if os.name == "nt":
            os.startfile(path)
        elif sys.platform == "darwin":
            os.system(f'open "{path}"')
        else:
            os.system(f'xdg-open "{path}"')
    except Exception:
        traceback.print_exc()


def _on_export_pdf(sender=None, app_data=None, user_data=None):
    _sync_controller_from_ui()
    if not (controller.msk or controller.measure_id):
        _show_error("Не выбрано МСК")
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
    except ImportError:
        _show_error("Установите matplotlib:\n pip install matplotlib")
        return

    numbers = controller.load_numbers(controller.msk)
    if not numbers:
        _show_error("Нет номеров для выбранной МСК")
        return

    charts = []
    save_number = controller.number
    for n in numbers:
        controller.number = n
        try:
            base = controller.build_points(show_points=True, show_msk=True)
            appr = controller.build_approximation(_opts_from_ui())
        except Exception:
            continue
        charts.append((n, appr, base))
    controller.number = save_number

    if not charts:
        _show_error("Не удалось собрать ни одного графика")
        return

    out_dir = os.path.join(os.path.expanduser("~"), "ResonatorGraphs")
    os.makedirs(out_dir, exist_ok=True)
    tag = controller.measure_id or controller.msk
    fname = f"MSK_{tag}_{datetime.datetime.now():%Y%m%d_%H%M%S}.pdf"
    path = os.path.join(out_dir, fname)

    per_page = 9
    with PdfPages(path) as pdf:
        total_pages = (len(charts) + per_page - 1) // per_page
        for page_i, start in enumerate(range(0, len(charts), per_page)):
            page_charts = charts[start:start + per_page]
            fig, axes = plt.subplots(3, 3, figsize=(16.5, 23.4))
            fig.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.04,
                                wspace=0.35, hspace=0.45)
            flat = axes.flatten()
            for i, ax in enumerate(flat):
                if i >= len(page_charts):
                    ax.axis("off")
                    continue
                n, appr, base = page_charts[i]
                for s in appr.series + base.series:
                    rgb = tuple(c / 255 for c in s.color)
                    if s.kind == "line":
                        ax.plot(s.xs, s.ys, "-", color=rgb,
                                linewidth=1.2, label=s.label)
                    else:
                        ax.scatter(s.xs, s.ys, s=10, color=rgb,
                                   edgecolors="black", linewidths=0.3,
                                   zorder=3, label=s.label)
                ax.set_title(appr.title, fontsize=8)
                ax.set_xlabel("T, C", fontsize=7)
                ax.set_ylabel(appr.ylabel, fontsize=7)
                ax.grid(True, linestyle="--", alpha=0.4)
                ax.tick_params(labelsize=6)
                ax.legend(fontsize=5, loc="best")

            title_tag = controller.measure_id or controller.msk
            fig.suptitle(
                f"МСК/ID {title_tag} - стр. {page_i + 1}/{total_pages}",
                fontsize=14,
            )
            pdf.savefig(fig)
            plt.close(fig)

    _open_file(path)
    _show_error(f"PDF сохранён и открыт:\n{path}")


# ---------------------------------------------------------------------------
# Окно настроек
# ---------------------------------------------------------------------------
def _open_options(sender=None, app_data=None, user_data=None):
    if dpg.does_item_exist(OPT_TAG):
        _set_if_exists(TAG_DEGREE, controller.degree)
        _set_if_exists(TAG_A, controller.A)
        _set_if_exists(TAG_B, controller.B)
        _set_if_exists(TAG_T, controller.T_ref)
        dpg.configure_item(OPT_TAG, show=True)
        return

    with dpg.window(label="Настройки", tag=OPT_TAG,
                    width=380, height=460, pos=(350, 150)):

        dpg.add_text("Параметры аппроксимации")
        dpg.add_separator()
        dpg.add_slider_int(label="Степень полинома",
                           default_value=controller.degree,
                           min_value=1, max_value=10, tag=TAG_DEGREE,
                           callback=_on_degree_changed)
        dpg.add_input_float(label="Граница A", default_value=controller.A,
                            tag=TAG_A, width=150,
                            callback=_on_bounds_changed)
        dpg.add_input_float(label="Граница B", default_value=controller.B,
                            tag=TAG_B, width=150,
                            callback=_on_bounds_changed)
        dpg.add_input_float(label="Опорная T", default_value=controller.T_ref,
                            tag=TAG_T, width=150)

        dpg.add_separator()
        dpg.add_text("Отображение на графике")
        dpg.add_checkbox(label="МСК в заголовке", default_value=True,
                         tag="chk_show_msk")
        dpg.add_checkbox(label="Порядок полинома", default_value=True,
                         tag="chk_show_order")
        dpg.add_checkbox(label="Коэффициенты полинома", default_value=False,
                         tag="chk_show_coeffs")
        dpg.add_checkbox(label="Аппроксимацию", default_value=True,
                         tag="chk_show_approx")

        dpg.add_separator()
        dpg.add_button(label="Закрыть",
                       callback=lambda: dpg.configure_item(OPT_TAG, show=False))


# ---------------------------------------------------------------------------
# Окна
# ---------------------------------------------------------------------------
def _apply_layout():
    vp_w = dpg.get_viewport_client_width()
    vp_h = dpg.get_viewport_client_height()

    right_w = max(MIN_RIGHT_W, int(vp_w * RIGHT_COL_FRACTION))
    chart_w = max(MIN_CHART_W, vp_w - right_w - MARGIN * 3)
    chart_h = vp_h - MARGIN * 2

    ctrl_h = min(CTRL_HEIGHT, vp_h - MIN_METRICS_H - MARGIN * 3)
    ctrl_h = max(ctrl_h, CTRL_MIN_H)
    metr_h = max(MIN_METRICS_H, vp_h - ctrl_h - MARGIN * 3)

    x_right = MARGIN * 2 + chart_w

    if dpg.does_item_exist(WIN_TAG):
        dpg.configure_item(WIN_TAG,
                           pos=(MARGIN, MARGIN),
                           width=chart_w, height=chart_h)

    if dpg.does_item_exist(WIN_CTRL_TAG):
        dpg.configure_item(WIN_CTRL_TAG,
                           pos=(x_right, MARGIN),
                           width=right_w, height=ctrl_h)

    if dpg.does_item_exist(WIN_METRICS_TAG):
        dpg.configure_item(WIN_METRICS_TAG,
                           pos=(x_right, MARGIN * 2 + ctrl_h),
                           width=right_w, height=metr_h)


def _create_plot_window():
    if dpg.does_item_exist(WIN_TAG):
        dpg.configure_item(WIN_TAG, show=True)
        return
    with dpg.window(label="График", tag=WIN_TAG,
                    width=800, height=600,
                    no_close=True):
        with dpg.plot(label="", height=-1, width=-1, tag=PLOT_TAG,
                      anti_aliased=True, fit_button=True):
            dpg.add_plot_legend(tag=LEGEND_TAG)
            dpg.add_plot_axis(dpg.mvXAxis, label="T, C", tag=X_AXIS_TAG)
            dpg.add_plot_axis(dpg.mvYAxis, label="F, ppm", tag=Y_AXIS_TAG)


def _create_control_window():
    if dpg.does_item_exist(WIN_CTRL_TAG):
        dpg.configure_item(WIN_CTRL_TAG, show=True)
        return
    with dpg.window(label="Выбор резонатора", tag=WIN_CTRL_TAG,
                    width=360, height=CTRL_HEIGHT,
                    no_close=True):
        with dpg.child_window(height=-1, width=-1, border=False):

            # ---- Источник данных ----
            dpg.add_text("Источник данных")
            dpg.add_combo([lbl for lbl, _, _ in SOURCES],
                          tag="rg_source_combo",
                          width=-1,
                          default_value=_source_state.get('label', 'Основная'),
                          callback=_on_source_changed)
            dpg.add_spacer(height=3)

            dpg.add_text("Тип резонатора")
            dpg.add_combo([], tag=TAG_TYPE, width=-1,
                          callback=_on_type_change)

            dpg.add_spacer(height=3)
            dpg.add_text("Спецификация")
            dpg.add_combo([], tag=TAG_SPEC, width=-1,
                          callback=_on_spec_change)

            dpg.add_spacer(height=3)
            dpg.add_text("МСК")
            dpg.add_combo([], tag=TAG_MSK, width=-1,
                          callback=_on_msk_change)
            dpg.add_input_text(tag=TAG_MSK_MANUAL, width=-1,
                               hint="МСК вручную + Enter",
                               on_enter=True,
                               callback=_on_msk_manual_enter)

            dpg.add_spacer(height=3)
            dpg.add_text("Поиск МСК по части номера")
            dpg.add_input_text(tag="rg_msk_partial_input", width=-1,
                               hint="456 | 25-2456",
                               on_enter=True,
                               callback=_on_msk_partial_search)
            dpg.add_button(label="Найти МСК", width=-1,
                           callback=_on_msk_partial_search)

            dpg.add_spacer(height=3)
            dpg.add_text("Номер")
            dpg.add_combo([], tag=TAG_NUMBER, width=-1,
                          callback=_on_number_change)

            dpg.add_spacer(height=3)
            dpg.add_text("Поиск по номерам (одиночный / список / диапазон)")
            dpg.add_input_text(tag="rg_numbers_input", width=-1,
                               hint="JN4450 | JN4450,JN4451 | JN4450-JN4460",
                               on_enter=True,
                               callback=_on_numbers_search)
            dpg.add_button(label="Найти по номерам", width=-1,
                           callback=_on_numbers_search)

            dpg.add_spacer(height=3)
            dpg.add_text("ID замера")
            dpg.add_input_text(tag=TAG_MEASURE_ID, width=-1,
                               hint="ID замера + Enter",
                               on_enter=True,
                               callback=_on_measure_id_enter)
            dpg.add_combo([], tag=TAG_MEASURE_ID_LIST, width=-1,
                          callback=_on_measure_id_pick)

            dpg.add_spacer(height=3)
            dpg.add_text("Параметр")
            dpg.add_combo([p[1] for p in PARAMETERS],
                          tag=TAG_PARAM, width=-1,
                          default_value=PARAMETERS[0][1],
                          callback=_on_param_change)

            dpg.add_separator()
            dpg.add_spacer(height=3)

            with dpg.group(horizontal=True):
                dpg.add_button(label="Построить", width=105,
                               callback=_on_build)
                dpg.add_button(label="Аппроксимация", width=105,
                               callback=_on_approx)
                dpg.add_button(label="Настройки", width=105,
                               callback=_open_options)

            dpg.add_spacer(height=3)
            dpg.add_button(label="Все номера МСК на одном графике",
                           width=-1, callback=_on_all_numbers)
            dpg.add_spacer(height=3)
            dpg.add_button(label="Сетка 3x3 (9 графиков)",
                           width=-1, callback=grid.open_grid)
            dpg.add_spacer(height=3)
            dpg.add_button(label="Статистика МСК + гистограмма",
                           width=-1, callback=_on_msk_statistics)
            dpg.add_spacer(height=3)
            dpg.add_button(label="Экспорт в PDF (9 на страницу)",
                           width=-1, callback=_on_export_pdf)
            dpg.add_button(label="Экспорт PDF: все номера на одном поле",
                           callback=_on_export_pdf_overlay)
            dpg.add_spacer(height=3)

            dpg.add_checkbox(
                label="Колесо мыши: переключение номеров",
                tag=TAG_WHEEL_SWITCH,
                default_value=True,
            )
            dpg.add_checkbox(
                label="Зафиксировать масштаб",
                tag=TAG_LOCK_SCALE,
                default_value=False,
                callback=_on_lock_scale_changed,
            )

            dpg.add_spacer(height=3)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Сохранить PNG", width=160,
                               callback=_on_print)
                dpg.add_button(label="Закрыть", width=160,
                               callback=_close_all)


def _create_metrics_window():
    if dpg.does_item_exist(WIN_METRICS_TAG):
        dpg.configure_item(WIN_METRICS_TAG, show=True)
        return
    with dpg.window(label="Расчётные величины", tag=WIN_METRICS_TAG,
                    width=360, height=460,
                    no_close=True):
        with dpg.child_window(height=-1, width=-1,
                              tag=TAG_METRICS_GROUP):
            dpg.add_text("Нет данных")


# ---------------------------------------------------------------------------
# Точка входа
# ---------------------------------------------------------------------------
def _close_all():
    for t in (WIN_TAG, WIN_CTRL_TAG, WIN_METRICS_TAG, OPT_TAG):
        if dpg.does_item_exist(t):
            dpg.configure_item(t, show=False)


def _register_for_window_manager():
    """Зарегистрировать окна графиков в менеджере окон и обновить меню."""
    try:
        from window_manager import register, rebuild_menu
    except Exception:
        return

    register(WIN_TAG, "Графики резонаторов - график",
             _create_plot_window)
    register(WIN_CTRL_TAG, "Графики резонаторов - выбор",
             _create_control_window)
    register(WIN_METRICS_TAG, "Графики резонаторов - метрики",
             _create_metrics_window)

    try:
        register(WIN_GRID_TAG, "Графики резонаторов - сетка 3x3",
                 grid.open_grid)
    except Exception:
        pass

    try:
        rebuild_menu()
    except Exception:
        pass


def create_graph_window():
    grid.configure(
        controller=controller,
        opts_from_ui=_opts_from_ui,
        sync_cb=_sync_controller_from_ui,
        error_cb=_show_error,
        set_if_cb=_set_if_exists,
    )

    _create_plot_window()
    _create_control_window()
    _create_metrics_window()

    _apply_layout()
    _ensure_wheel_handler()

    _register_for_window_manager()

    if not dpg.get_item_children(TAG_TYPE, 1):
        try:
            types = controller.load_types()
            dpg.configure_item(TAG_TYPE, items=types)
            if types:
                dpg.set_value(TAG_TYPE, types[0])
                _on_type_change()
        except Exception as e:
            _show_error("Не удалось загрузить типы резонаторов", e)


def open_for_measure_id(measure_id):
    """Открыть окно «Графики» и загрузить указанный Measure_ID.

    Используется из других модулей (например, «Архив») для перехода
    к просмотру графиков конкретного замера.
    """
    create_graph_window()
    if dpg.does_item_exist(TAG_MEASURE_ID):
        dpg.set_value(TAG_MEASURE_ID, str(measure_id))
    _on_measure_id_enter()
    if dpg.does_item_exist(WIN_TAG):
        try:
            dpg.focus_item(WIN_TAG)
        except Exception:
            pass

def _on_export_pdf_overlay(sender=None, app_data=None, user_data=None):
    """
    PDF: все номера текущей МСК (или ID замера) на одном поле.

    В отличие от _on_export_pdf (сетка 3x3, по 9 графиков на страницу),
    здесь все номера строятся одновременно на одних осях — удобно для
    визуальной оценки разброса и сравнения ТЧХ разных экземпляров.

    Сохраняет одностраничный PDF (лист A3-альбом) и открывает его.
    """
    _sync_controller_from_ui()
    if not (controller.msk or controller.measure_id):
        _show_error("Не выбрано МСК")
        return

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
    except ImportError:
        _show_error("Установите matplotlib:\n pip install matplotlib")
        return

    # Учитываем галочки из окна «Настройки».
    opts = _opts_from_ui()
    try:
        res = controller.build_all_numbers(
            show_msk=True,
            show_approx=opts.get("show_approx", True),
            show_points=True,
        )
    except GraphLogicError as e:
        _show_error(str(e))
        return
    except Exception as e:
        _show_error("Ошибка построения всех номеров", e)
        return

    if not res.series:
        _show_error("Не удалось построить ни одного номера")
        return

    # A3-альбом: много кривых — нужно место.
    fig, ax = plt.subplots(figsize=(16.5, 11.7))

    # Z-порядок: сначала линии аппроксимации, поверх — точки замеров.
    for s in res.series:
        if s.kind != "line":
            continue
        rgb = tuple(c / 255 for c in s.color)
        ax.plot(s.xs, s.ys, "-", color=rgb, linewidth=1.0,
                alpha=0.8, label=s.label)

    for s in res.series:
        if s.kind != "scatter":
            continue
        rgb = tuple(c / 255 for c in s.color)
        ax.scatter(s.xs, s.ys, s=12, color=rgb,
                   edgecolors="black", linewidths=0.25,
                   zorder=3, label=s.label)

    ax.set_xlabel(res.xlabel, fontsize=11)
    ax.set_ylabel(res.ylabel, fontsize=11)
    ax.set_title(res.title, fontsize=13)
    ax.grid(True, linestyle="--", alpha=0.4)

    # Легенда в 1–3 колонки в зависимости от количества серий.
    n_series = len(res.series)
    ncol = 1 if n_series <= 10 else (2 if n_series <= 20 else 3)
    fsize = 8 if n_series <= 10 else (6 if n_series <= 20 else 5)
    ax.legend(fontsize=fsize, loc="best", ncol=ncol, framealpha=0.9)

    out_dir = os.path.join(os.path.expanduser("~"), "ResonatorGraphs")
    os.makedirs(out_dir, exist_ok=True)
    tag = controller.measure_id or controller.msk
    fname = f"MSK_{tag}_overlay_{datetime.datetime.now():%Y%m%d_%H%M%S}.pdf"
    path = os.path.join(out_dir, fname)

    with PdfPages(path) as pdf:
        pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)

    _open_file(path)
    _show_error(f"PDF (все номера на одном поле) сохранён и открыт:\n{path}")

def open_for_msk(msk):
    """Открыть окно «Графики» и загрузить указанный МСК."""
    create_graph_window()
    if dpg.does_item_exist(TAG_MSK_MANUAL):
        dpg.set_value(TAG_MSK_MANUAL, str(msk))
    _on_msk_manual_enter()
    if dpg.does_item_exist(WIN_TAG):
        try:
            dpg.focus_item(WIN_TAG)
        except Exception:
            pass


def show_graph_window(sender=None, app_data=None, dpg_ref=None):
    create_graph_window()