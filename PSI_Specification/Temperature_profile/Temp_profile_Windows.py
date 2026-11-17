"""UI-редактор температурных профилей.
Строгая классическая вёрстка, удаление точек кнопкой X, адаптивная раскладка."""

import sys

import dearpygui.dearpygui as dpg

from .Temp_profile_data import (
    get_profile_names_list, get_profile_data, get_profile_meta,
    get_profile_list_by_interval, build_profile_df,
    PROFILE, save_profile, delete_profile, restore_profile,
    list_trash, get_profile_log,
)


# =====================================================================
# Состояние редактора
# =====================================================================
_edit_points: list = []          # [[Temperature, Time], ...]
_edit_name = ""
_edit_code = ""
_edit_interval_name = ""


# =====================================================================
# Раскладка
# =====================================================================
MENU_OFFSET = 30
MARGIN = 10


def _screen_size():
    try:
        w = dpg.get_viewport_client_width()
        h = dpg.get_viewport_client_height()
        if w and h and w > 200 and h > 200:
            return int(w), int(h)
    except Exception:
        pass
    try:
        w = dpg.get_viewport_width()
        h = dpg.get_viewport_height()
        if w and h and w > 200 and h > 200:
            return int(w), int(h)
    except Exception:
        pass
    return 1920, 1080


def _compute_layout():
    sw, sh = _screen_size()
    top = MENU_OFFSET + MARGIN
    avail_h = max(sh - top - MARGIN, 400)

    left_w = int(sw * 0.28)
    mid_w = int(sw * 0.44)
    right_w = max(sw - left_w - mid_w - MARGIN * 4, 240)

    select_h = int(avail_h * 0.25)
    view_h = max(avail_h - select_h - MARGIN, 200)

    log_w = max(int(sw * 0.60), 520)
    log_h = max(int(sh * 0.55), 320)
    log_pos = ((sw - log_w) // 2, (sh - log_h) // 2)

    return {
        "select_profile_windows": ((MARGIN, top), (left_w, select_h)),
        "view_profile_window":    ((MARGIN, top + select_h + MARGIN),
                                   (left_w, view_h)),
        "new_profile_window":     ((MARGIN + left_w + MARGIN, top),
                                   (mid_w, avail_h)),
        "trash_profile_window":   ((MARGIN + left_w + MARGIN + mid_w + MARGIN,
                                    top), (right_w, avail_h)),
        "profile_log_window":     (log_pos, (log_w, log_h)),
    }


def _apply_layout():
    for tag, (pos, size) in _compute_layout().items():
        if not dpg.does_item_exist(tag):
            continue
        try:
            dpg.configure_item(tag, pos=list(pos),
                               width=size[0], height=size[1])
        except Exception:
            pass


_resize_hooked = False


def _ensure_resize_hook():
    global _resize_hooked
    if _resize_hooked:
        return
    try:
        main_mod = sys.modules.get("main") or sys.modules.get("__main__")
        prev = getattr(main_mod, "_on_viewport_resize", None) if main_mod else None

        def _combined(sender=None, app_data=None):
            if callable(prev):
                try:
                    prev(sender, app_data)
                except Exception:
                    pass
            _apply_layout()

        dpg.set_viewport_resize_callback(_combined)
        _resize_hooked = True
    except Exception:
        pass


def _show_window(tag):
    if not dpg.does_item_exist(tag):
        return
    layout = _compute_layout().get(tag)
    if layout:
        pos, size = layout
        try:
            dpg.configure_item(tag, pos=list(pos),
                               width=size[0], height=size[1])
        except Exception:
            pass
    dpg.configure_item(tag, show=True)
    try:
        dpg.focus_item(tag)
    except Exception:
        pass


def _ensure_show(tag, factory):
    if not dpg.does_item_exist(tag):
        factory()
    _show_window(tag)


# =====================================================================
# Точка входа
# =====================================================================
def create_main_temp_profile_windows(dpg_ref=None):
    if not dpg.does_item_exist("select_profile_windows"):
        create_profile_select_window()
    if not dpg.does_item_exist("view_profile_window"):
        create_profile_view_window()
    if not dpg.does_item_exist("new_profile_window"):
        create_profile_create_window()
    if not dpg.does_item_exist("trash_profile_window"):
        create_trash_window()

    _apply_layout()
    _ensure_resize_hook()
    _register_for_window_manager()


def _register_for_window_manager():
    try:
        from window_manager import register, rebuild_menu
    except Exception:
        return
    register("select_profile_windows", "Выбор температурной таблицы",
             lambda: _ensure_show("select_profile_windows",
                                  create_profile_select_window))
    register("view_profile_window", "Температурная таблица",
             lambda: _ensure_show("view_profile_window",
                                  create_profile_view_window))
    register("new_profile_window", "Профиль температур",
             lambda: _ensure_show("new_profile_window",
                                  create_profile_create_window))
    register("trash_profile_window", "Корзина профилей",
             lambda: _ensure_show("trash_profile_window",
                                  create_trash_window))
    # Обновить меню «Окна» сразу после регистрации
    try:
        rebuild_menu()
    except Exception:
        pass


# =====================================================================
# Окно выбора
# =====================================================================
def create_profile_select_window():
    pos, size = _compute_layout()["select_profile_windows"]
    with dpg.window(label="Выбор температурной таблицы",
                    width=size[0], height=size[1],
                    pos=pos, tag="select_profile_windows"):
        dpg.add_text("Температурный профиль")
        dpg.add_separator()
        dpg.add_combo(get_profile_names_list(), tag="profile_select",
                      callback=_on_profile_selected, width=-1)

        dpg.add_spacer(height=6)
        dpg.add_separator()
        dpg.add_spacer(height=4)

        with dpg.table(header_row=False,
                       policy=dpg.mvTable_SizingStretchSame,
                       borders_innerH=False, borders_innerV=False,
                       pad_outerX=False):
            for _ in range(4):
                dpg.add_table_column()
            with dpg.table_row():
                dpg.add_button(label="Новый",    width=-1, callback=_on_new_clicked)
                dpg.add_button(label="Изменить", width=-1, callback=_on_edit_clicked)
                dpg.add_button(label="Удалить",  width=-1, callback=_on_delete_clicked)
                dpg.add_button(label="Обновить", width=-1,
                               callback=_refresh_profiles_list)

        dpg.add_spacer(height=4)

        with dpg.table(header_row=False,
                       policy=dpg.mvTable_SizingStretchSame,
                       borders_innerH=False, borders_innerV=False,
                       pad_outerX=False):
            dpg.add_table_column()
            dpg.add_table_column()
            with dpg.table_row():
                dpg.add_button(label="Корзина", width=-1,
                               callback=lambda: _show_window("trash_profile_window"))
                dpg.add_button(label="Журнал",  width=-1,
                               callback=_open_log_window)


def _refresh_profiles_list():
    if not dpg.does_item_exist("profile_select"):
        return
    dpg.configure_item("profile_select", items=get_profile_names_list())


def _on_profile_selected(sender, app_data, user_data=None):
    if not app_data:
        return
    _render_profile_view(get_profile_data(app_data), app_data)


# =====================================================================
# Окно просмотра
# =====================================================================
def create_profile_view_window():
    pos, size = _compute_layout()["view_profile_window"]
    with dpg.window(label="Температурная таблица",
                    width=size[0], height=size[1],
                    pos=pos, tag="view_profile_window"):
        with dpg.group(tag="view_profile_container"):
            dpg.add_text("(выберите профиль сверху)")


def _render_profile_view(df, name):
    if not dpg.does_item_exist("view_profile_container"):
        return
    for c in dpg.get_item_children("view_profile_container", 1) or []:
        dpg.delete_item(c)

    with dpg.table(parent="view_profile_container",
                   header_row=True, row_background=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True,
                   tag="result_msk_table"):
        dpg.add_table_column(label="N",      init_width_or_weight=0.15)
        dpg.add_table_column(label="T, °C",  init_width_or_weight=0.55)
        dpg.add_table_column(label="t, мин", init_width_or_weight=0.30)

        if df is None or df.empty:
            with dpg.table_row():
                dpg.add_text("—")
                dpg.add_text("—")
                dpg.add_text("—")
        else:
            for _, row in df.iterrows():
                with dpg.table_row():
                    dpg.add_text(str(row["N"]))
                    dpg.add_text(str(row["Temperature"]))
                    dpg.add_text(str(row["Time"]))

    dpg.configure_item("view_profile_window",
                       label=f"Температурная таблица ({name})")


# =====================================================================
# Окно создания / редактирования
# =====================================================================
def create_profile_create_window():
    pos, size = _compute_layout()["new_profile_window"]
    with dpg.window(label="Профиль температур",
                    width=size[0], height=size[1],
                    pos=pos, tag="new_profile_window"):

        # ---------- Идентификация ----------
        dpg.add_text("Идентификация")
        dpg.add_separator()
        with dpg.table(header_row=False,
                       policy=dpg.mvTable_SizingStretchProp,
                       borders_innerH=False, borders_innerV=False,
                       no_pad_innerX=True, pad_outerX=False):
            dpg.add_table_column(init_width_or_weight=0.32)
            dpg.add_table_column(init_width_or_weight=0.68)
            with dpg.table_row():
                dpg.add_text("Название")
                dpg.add_input_text(width=-1, tag="profile_name")
            with dpg.table_row():
                dpg.add_text("Код")
                dpg.add_input_text(width=-1, tag="profile_code_")
            with dpg.table_row():
                dpg.add_text("Отображаемое название")
                dpg.add_input_text(width=-1, tag="profile_interval_name")

        dpg.add_spacer(height=8)

        # ---------- Генератор интервала ----------
        dpg.add_text("Генератор линейного интервала")
        dpg.add_separator()
        with dpg.table(header_row=False,
                       policy=dpg.mvTable_SizingStretchProp,
                       borders_innerH=False, borders_innerV=False,
                       no_pad_innerX=True, pad_outerX=False):
            dpg.add_table_column(init_width_or_weight=0.15)
            dpg.add_table_column(init_width_or_weight=0.35)
            dpg.add_table_column(init_width_or_weight=0.15)
            dpg.add_table_column(init_width_or_weight=0.35)
            with dpg.table_row():
                dpg.add_text("От")
                dpg.add_input_text(width=-1, decimal=True, tag="begin_temp")
                dpg.add_text("До")
                dpg.add_input_text(width=-1, decimal=True, tag="end_temp")
            with dpg.table_row():
                dpg.add_text("Шаг")
                dpg.add_input_text(width=-1, decimal=True, tag="step_temp")
                dpg.add_text("Выдержка")
                dpg.add_input_text(width=-1, decimal=True, tag="wait_time")

        dpg.add_spacer(height=4)
        dpg.add_button(label="Заполнить профиль", width=-1,
                       callback=_on_fill_interval)

        dpg.add_spacer(height=8)

        # ---------- Точки профиля ----------
        with dpg.table(header_row=False,
                       policy=dpg.mvTable_SizingStretchProp,
                       borders_innerH=False, borders_innerV=False,
                       no_pad_innerX=True, pad_outerX=False):
            dpg.add_table_column(init_width_or_weight=0.70)
            dpg.add_table_column(init_width_or_weight=0.30)
            with dpg.table_row():
                dpg.add_text("Точки профиля")
                dpg.add_button(label="Очистить", width=-1,
                               callback=_on_clear_points)

        dpg.add_separator()

        tbl_h = max(size[1] - 520, 140)
        with dpg.child_window(height=tbl_h, tag="points_table_container",
                              border=True):
            _rebuild_points_table()

        dpg.add_spacer(height=8)

        # ---------- Вставка точки: строка ввода ----------
        dpg.add_text("Вставить точку")
        dpg.add_separator()

        # Значения для новой точки — три равных поля
        with dpg.table(header_row=True,
                       policy=dpg.mvTable_SizingStretchSame,
                       borders_innerH=True, borders_innerV=True,
                       no_pad_innerX=False, pad_outerX=False):
            dpg.add_table_column(label="Позиция")
            dpg.add_table_column(label="T, °C")
            dpg.add_table_column(label="t, мин")
            with dpg.table_row():
                dpg.add_input_int(tag="insert_pos", width=-1,
                                  default_value=0, step=1)
                dpg.add_input_text(tag="insert_temp", width=-1,
                                   decimal=True, default_value="0")
                dpg.add_input_text(tag="insert_time", width=-1,
                                   decimal=True, default_value="5")

        dpg.add_spacer(height=4)

        # Действия — четыре равноширинные кнопки, ровно 1/4 каждая
        with dpg.table(header_row=False,
                       policy=dpg.mvTable_SizingStretchSame,
                       borders_innerH=False, borders_innerV=False,
                       pad_outerX=False):
            for _ in range(4):
                dpg.add_table_column()
            with dpg.table_row():
                dpg.add_button(label="Вставить", width=-1,
                               callback=_on_insert_point)
                dpg.add_button(label="-> в начало", width=-1,
                               callback=_on_go_start)
                dpg.add_button(label="-> в конец", width=-1,
                               callback=_on_go_end)
                dpg.add_button(label="Сортировать", width=-1,
                               callback=_on_sort_by_temp)

        dpg.add_spacer(height=8)
        dpg.add_separator()
        dpg.add_spacer(height=4)

        # ---------- Сохранить / Отмена ----------
        with dpg.table(header_row=False,
                       policy=dpg.mvTable_SizingStretchSame,
                       borders_innerH=False, borders_innerV=False,
                       pad_outerX=False):
            dpg.add_table_column()
            dpg.add_table_column()
            with dpg.table_row():
                dpg.add_button(label="Сохранить", width=-1,
                               callback=_on_save_profile)
                dpg.add_button(label="Отмена", width=-1,
                               callback=_on_cancel_edit)


# =====================================================================
# Таблица точек + callback-обёртки
# =====================================================================
def _cb_remove_point(sender, app_data, user_data):
    _on_remove_point(user_data)


def _cb_point_edit(sender, app_data, user_data):
    if not user_data:
        return
    try:
        idx, field = user_data
    except (TypeError, ValueError):
        return
    if not (0 <= idx < len(_edit_points)):
        return
    try:
        _edit_points[idx][field] = float(str(app_data).replace(",", "."))
    except (TypeError, ValueError):
        pass


def _rebuild_points_table():
    if not dpg.does_item_exist("points_table_container"):
        return
    for c in dpg.get_item_children("points_table_container", 1) or []:
        dpg.delete_item(c)

    with dpg.table(parent="points_table_container",
                   header_row=True, row_background=True,
                   borders_innerH=True, borders_innerV=True,
                   policy=dpg.mvTable_SizingStretchProp):
        dpg.add_table_column(label="N",      init_width_or_weight=0.12)
        dpg.add_table_column(label="T, °C",  init_width_or_weight=0.42)
        dpg.add_table_column(label="t, мин", init_width_or_weight=0.36)
        dpg.add_table_column(label="",       init_width_or_weight=0.10)

        if not _edit_points:
            with dpg.table_row():
                dpg.add_text("—")
                dpg.add_text("(добавьте точки)")
                dpg.add_text("—")
                dpg.add_text("")
            return

        for i, (t, tm) in enumerate(_edit_points):
            with dpg.table_row():
                dpg.add_text(str(i))
                dpg.add_input_text(
                    tag=f"pt_{i}_temp", width=-1, decimal=True,
                    default_value=str(t),
                    callback=_cb_point_edit,
                    user_data=(i, 0),
                )
                dpg.add_input_text(
                    tag=f"pt_{i}_time", width=-1, decimal=True,
                    default_value=str(tm),
                    callback=_cb_point_edit,
                    user_data=(i, 1),
                )
                dpg.add_button(
                    label="X", width=-1,
                    callback=_cb_remove_point,
                    user_data=i,
                )


# =====================================================================
# Обработчики
# =====================================================================
def _sync_points_from_widgets():
    for i in range(len(_edit_points)):
        for field, suffix in ((0, "temp"), (1, "time")):
            tag = f"pt_{i}_{suffix}"
            if not dpg.does_item_exist(tag):
                continue
            try:
                _edit_points[i][field] = float(
                    str(dpg.get_value(tag)).replace(",", ".")
                )
            except (TypeError, ValueError):
                pass


def _on_remove_point(idx):
    if idx is None:
        return
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return
    if not (0 <= idx < len(_edit_points)):
        return
    _sync_points_from_widgets()
    _edit_points.pop(idx)
    _rebuild_points_table()


def _on_insert_point():
    _sync_points_from_widgets()

    try:
        pos = int(dpg.get_value("insert_pos") or 0)
    except (TypeError, ValueError):
        pos = len(_edit_points)

    try:
        t = float(str(dpg.get_value("insert_temp")).replace(",", "."))
    except (TypeError, ValueError):
        _popup("Некорректное значение температуры")
        return

    try:
        tm = float(str(dpg.get_value("insert_time")).replace(",", "."))
    except (TypeError, ValueError):
        tm = 0.0

    pos = max(0, min(pos, len(_edit_points)))
    _edit_points.insert(pos, [t, tm])
    _rebuild_points_table()

    try:
        dpg.set_value("insert_pos", min(pos + 1, len(_edit_points)))
    except Exception:
        pass


def _on_go_start():
    try:
        dpg.set_value("insert_pos", 0)
    except Exception:
        pass


def _on_go_end():
    try:
        dpg.set_value("insert_pos", len(_edit_points))
    except Exception:
        pass


def _on_sort_by_temp():
    _sync_points_from_widgets()
    _edit_points.sort(key=lambda p: p[0])
    _rebuild_points_table()


def _on_clear_points():
    _edit_points.clear()
    _rebuild_points_table()


def _on_fill_interval():
    a = dpg.get_value("begin_temp")
    b = dpg.get_value("end_temp")
    step = dpg.get_value("step_temp")
    wait = dpg.get_value("wait_time")
    temps = get_profile_list_by_interval(a, b, step)
    try:
        wait_v = float(str(wait).replace(",", "."))
    except (TypeError, ValueError):
        wait_v = 0.0
    _edit_points.clear()
    for t in temps:
        _edit_points.append([float(t), wait_v])
    _rebuild_points_table()


def _on_cancel_edit():
    if dpg.does_item_exist("new_profile_window"):
        dpg.delete_item("new_profile_window")


# =====================================================================
# Действия со списком
# =====================================================================
def _on_new_clicked():
    global _edit_points, _edit_name, _edit_code, _edit_interval_name
    _edit_points, _edit_name, _edit_code, _edit_interval_name = [], "", "", ""
    if dpg.does_item_exist("new_profile_window"):
        dpg.delete_item("new_profile_window")
    create_profile_create_window()
    _show_window("new_profile_window")


def _on_edit_clicked():
    global _edit_points, _edit_name, _edit_code, _edit_interval_name
    name = dpg.get_value("profile_select")
    if not name:
        _popup("Профиль не выбран")
        return

    meta = get_profile_meta(name)
    df = get_profile_data(name)
    _edit_name = name
    _edit_code = meta.get("code", "") if meta else ""
    _edit_interval_name = meta.get("IntervalName", "") if meta else ""
    _edit_points = [[float(r["Temperature"]), float(r["Time"])]
                    for _, r in df.iterrows()]

    if dpg.does_item_exist("new_profile_window"):
        dpg.delete_item("new_profile_window")
    create_profile_create_window()

    dpg.set_value("profile_name", _edit_name)
    dpg.set_value("profile_code_", _edit_code)
    dpg.set_value("profile_interval_name", _edit_interval_name)
    _show_window("new_profile_window")


def _on_save_profile():
    global _edit_name, _edit_code, _edit_interval_name
    _sync_points_from_widgets()
    name = (dpg.get_value("profile_name") or "").strip()
    if not name:
        _popup("Не задано имя профиля")
        return
    if not _edit_points:
        _popup("Профиль не содержит точек")
        return
    _edit_code = dpg.get_value("profile_code_") or ""
    _edit_interval_name = dpg.get_value("profile_interval_name") or ""

    ok = save_profile(name, [tuple(p) for p in _edit_points],
                      _edit_code, _edit_interval_name)
    if ok:
        _refresh_profiles_list()
        dpg.set_value("profile_select", name)
        _render_profile_view(get_profile_data(name), name)
        _popup(f"Профиль «{name}» сохранён")
    else:
        _popup("Ошибка сохранения профиля")


def _on_delete_clicked():
    name = dpg.get_value("profile_select")
    if not name:
        _popup("Профиль не выбран")
        return
    if delete_profile(name):
        _refresh_profiles_list()
        dpg.set_value("profile_select", "")
        if dpg.does_item_exist("result_msk_table"):
            dpg.delete_item("result_msk_table")
        _popup(f"Профиль «{name}» перемещён в корзину")
    else:
        _popup("Не удалось удалить профиль")


# =====================================================================
# Корзина
# =====================================================================
def create_trash_window():
    pos, size = _compute_layout()["trash_profile_window"]
    with dpg.window(label="Корзина профилей",
                    width=size[0], height=size[1],
                    pos=pos, tag="trash_profile_window", show=False):
        dpg.add_text("Удалённые профили (можно восстановить)")
        dpg.add_separator()
        with dpg.child_window(height=-40, tag="trash_table_container",
                              border=True):
            _rebuild_trash_table()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Обновить", callback=_rebuild_trash_table)


def _cb_restore(sender, app_data, user_data):
    _on_restore(user_data)


def _rebuild_trash_table():
    if not dpg.does_item_exist("trash_table_container"):
        return
    for c in dpg.get_item_children("trash_table_container", 1) or []:
        dpg.delete_item(c)

    df = list_trash()
    with dpg.table(parent="trash_table_container",
                   header_row=True, row_background=True,
                   borders_innerH=True, borders_innerV=True,
                   policy=dpg.mvTable_SizingStretchProp):
        dpg.add_table_column(label="Профиль")
        dpg.add_table_column(label="Удалил")
        dpg.add_table_column(label="Когда")
        dpg.add_table_column(label="", init_width_or_weight=0.2)

        if df.empty:
            with dpg.table_row():
                dpg.add_text("(корзина пуста)")
                dpg.add_text("")
                dpg.add_text("")
                dpg.add_text("")
            return

        for _, row in df.iterrows():
            with dpg.table_row():
                dpg.add_text(str(row["ProfileName"]))
                dpg.add_text(str(row.get("DeletedBy") or ""))
                dpg.add_text(str(row.get("DeletedAt") or ""))
                dpg.add_button(
                    label="Восстановить",
                    callback=_cb_restore,
                    user_data=int(row["ID"]),
                )


def _on_restore(trash_id):
    if trash_id is None:
        return
    try:
        trash_id = int(trash_id)
    except (TypeError, ValueError):
        return
    if restore_profile(trash_id):
        _rebuild_trash_table()
        _refresh_profiles_list()
        _popup("Профиль восстановлен")
    else:
        _popup("Не удалось восстановить профиль")


# =====================================================================
# Журнал
# =====================================================================
def _open_log_window():
    tag = "profile_log_window"
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)

    pos, size = _compute_layout()["profile_log_window"]
    with dpg.window(label="Журнал изменений профилей",
                    width=size[0], height=size[1],
                    pos=pos, tag=tag, modal=False):
        df = get_profile_log(limit=200)
        with dpg.child_window(height=-1, border=False):
            with dpg.table(header_row=True, row_background=True,
                           borders_innerH=True, borders_innerV=True,
                           policy=dpg.mvTable_SizingStretchProp):
                dpg.add_table_column(label="Действие",     init_width_or_weight=0.12)
                dpg.add_table_column(label="Профиль",      init_width_or_weight=0.20)
                dpg.add_table_column(label="Изменения",    init_width_or_weight=0.38)
                dpg.add_table_column(label="Пользователь", init_width_or_weight=0.15)
                dpg.add_table_column(label="Когда",        init_width_or_weight=0.15)
                if df.empty:
                    with dpg.table_row():
                        for _ in range(5):
                            dpg.add_text("—")
                else:
                    for _, row in df.iterrows():
                        with dpg.table_row():
                            dpg.add_text(str(row.get("Action") or ""))
                            dpg.add_text(str(row.get("ProfileName") or ""))
                            ch = str(row.get("Changes") or "")
                            dpg.add_text(ch[:80] + ("..." if len(ch) > 80 else ""))
                            dpg.add_text(str(row.get("UserLogin") or ""))
                            dpg.add_text(str(row.get("DateTime") or ""))


# =====================================================================
# Сообщение
# =====================================================================
def _popup(text: str):
    tag = "temp_profile_msg"
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.window(label="Сообщение", modal=True, autosize=True,
                    pos=(500, 350), tag=tag):
        dpg.add_text(text, wrap=400)
        dpg.add_button(label="OK",
                       callback=lambda: dpg.delete_item(tag))