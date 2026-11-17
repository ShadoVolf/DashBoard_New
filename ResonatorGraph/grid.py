"""
Окно "Сетка 3x3" - 9 графиков номеров текущей МСК на одной странице
с постраничной навигацией.
"""
import dearpygui.dearpygui as dpg

from .constants import (
    WIN_GRID_TAG, TAG_GRID_INFO, TAG_GRID_CONTENT, TAG_GRID_REFRESH,
)


CELL_W = 430
CELL_H = 260
GRID_COLS = 3
GRID_ROWS = 3
GRID_PER_PAGE = GRID_COLS * GRID_ROWS

_state = {
    "controller":  None,
    "opts_from_ui": None,
    "sync":        None,
    "error":       None,
    "set_if":      None,
}

_grid_page = 0
_grid_total_pages = 1
_grid_page_numbers = []


def configure(controller, opts_from_ui, sync_cb, error_cb, set_if_cb):
    _state["controller"]  = controller
    _state["opts_from_ui"] = opts_from_ui
    _state["sync"]         = sync_cb
    _state["error"]        = error_cb
    _state["set_if"]       = set_if_cb


def _ctrl():
    return _state["controller"]


def _render_grid_cell(number, opts):
    controller = _ctrl()
    save_number = controller.number
    controller.number = number
    try:
        base = controller.build_points(show_points=True, show_msk=False)
        appr = controller.build_approximation(opts)
    except Exception as e:
        with dpg.child_window(width=CELL_W, height=CELL_H, border=True):
            dpg.add_text(f"N{number}\nошибка: {e}")
        controller.number = save_number
        return

    ylabel = appr.ylabel
    title = f"N{number}"

    with dpg.plot(label=title, width=CELL_W, height=CELL_H,
                  anti_aliased=True, fit_button=True):
        dpg.add_plot_axis(dpg.mvXAxis, label="T, C")
        with dpg.plot_axis(dpg.mvYAxis, label=ylabel) as yax:
            for s in list(appr.series) + list(base.series):
                if s.kind == "line":
                    dpg.add_line_series(s.xs, s.ys, parent=yax,
                                        label=s.label)
                else:
                    dpg.add_scatter_series(s.xs, s.ys, parent=yax,
                                           label=s.label)

    controller.number = save_number


def build_page():
    global _grid_total_pages, _grid_page_numbers

    if not dpg.does_item_exist(TAG_GRID_CONTENT):
        return

    for ch in dpg.get_item_children(TAG_GRID_CONTENT, 1) or []:
        dpg.delete_item(ch)

    controller = _ctrl()
    if controller is None or not controller.msk:
        dpg.add_text("Не выбрано МСК", parent=TAG_GRID_CONTENT)
        return

    numbers = controller.load_numbers(controller.msk)
    if not numbers:
        dpg.add_text("Нет номеров для выбранной МСК",
                     parent=TAG_GRID_CONTENT)
        return

    _grid_total_pages = max(1,
                            (len(numbers) + GRID_PER_PAGE - 1)
                            // GRID_PER_PAGE)
    global _grid_page
    if _grid_page >= _grid_total_pages:
        _grid_page = _grid_total_pages - 1
    if _grid_page < 0:
        _grid_page = 0

    start = _grid_page * GRID_PER_PAGE
    _grid_page_numbers = numbers[start:start + GRID_PER_PAGE]

    if _state["set_if"]:
        _state["set_if"](
            TAG_GRID_INFO,
            f"Стр. {_grid_page + 1}/{_grid_total_pages}   |   "
            f"МСК {controller.msk}   |   всего номеров: {len(numbers)}",
        )

    opts = _state["opts_from_ui"]() if _state["opts_from_ui"] else {}
    save_number = controller.number

    for row in range(GRID_ROWS):
        with dpg.group(horizontal=True, parent=TAG_GRID_CONTENT):
            for col in range(GRID_COLS):
                i = row * GRID_COLS + col
                if i >= len(_grid_page_numbers):
                    dpg.add_spacer(width=CELL_W, height=CELL_H)
                    continue
                _render_grid_cell(_grid_page_numbers[i], opts)

    controller.number = save_number


def page_delta(delta):
    global _grid_page
    _grid_page += delta
    if _grid_page < 0:
        _grid_page = 0
    if _grid_page >= _grid_total_pages:
        _grid_page = _grid_total_pages - 1
    if _state["sync"]:
        _state["sync"]()
    build_page()


def _create_grid_window():
    if dpg.does_item_exist(WIN_GRID_TAG):
        dpg.configure_item(WIN_GRID_TAG, show=True)
        return
    with dpg.window(label="Сетка 3x3 - номера МСК",
                    tag=WIN_GRID_TAG,
                    width=1360, height=900,
                    pos=(40, 40)):
        with dpg.group(horizontal=True):
            dpg.add_button(label="<  Пред. страница",
                           callback=lambda s, a, u: page_delta(-1))
            dpg.add_text("Стр. 1/1", tag=TAG_GRID_INFO)
            dpg.add_button(label="След. страница  >",
                           callback=lambda s, a, u: page_delta(+1))
            dpg.add_spacer(width=20)
            dpg.add_button(label="Обновить",
                           tag=TAG_GRID_REFRESH,
                           callback=lambda s, a, u: build_page())
        dpg.add_separator()
        with dpg.group(tag=TAG_GRID_CONTENT):
            dpg.add_text("Нет данных")


def open_grid(sender=None, app_data=None, user_data=None):
    global _grid_page
    if _state["sync"]:
        _state["sync"]()
    controller = _ctrl()
    if controller is None or not controller.msk:
        if _state["error"]:
            _state["error"]("Не выбрано МСК")
        return
    _grid_page = 0
    _create_grid_window()
    build_page()