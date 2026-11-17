"""Реестр окон DearPyGui для меню «Окна»."""
import dearpygui.dearpygui as dpg

MENU_TAG = "Windows_Menu"

_windows: dict[str, dict] = {}   # tag -> {'label', 'factory'}


def register(tag: str, label: str, factory) -> None:
    """Зарегистрировать окно (factory — функция, создающая окно заново)."""
    _windows[tag] = {"label": label, "factory": factory}


def unregister(tag: str) -> None:
    _windows.pop(tag, None)


def is_open(tag: str) -> bool:
    try:
        return dpg.does_item_exist(tag) and dpg.is_item_shown(tag)
    except Exception:
        return False


def show_or_create(tag: str) -> None:
    """Показать/сфокусировать окно или создать заново."""
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, show=True)
        try:
            dpg.focus_item(tag)
        except Exception:
            pass
    else:
        info = _windows.get(tag)
        if info and callable(info.get("factory")):
            info["factory"]()


def close_window(tag: str) -> None:
    if dpg.does_item_exist(tag):
        dpg.configure_item(tag, show=False)


def close_all() -> None:
    for tag in list(_windows):
        close_window(tag)
    rebuild_menu()


def _on_menu_click(sender, app_data, user_data):
    show_or_create(user_data)
    rebuild_menu()


def rebuild_menu() -> None:
    """Перестроить содержимое меню «Окна»."""
    if not dpg.does_item_exist(MENU_TAG):
        return
    for child in dpg.get_item_children(MENU_TAG, 1) or []:
        dpg.delete_item(child)

    opened = [(t, i) for t, i in _windows.items() if is_open(t)]
    closed = [(t, i) for t, i in _windows.items() if not is_open(t)]

    if not _windows:
        dpg.add_menu_item(label="(нет зарегистрированных окон)",
                          parent=MENU_TAG, enabled=False)
        return

    if opened:
        for tag, info in opened:
            dpg.add_menu_item(
                label=info["label"],
                parent=MENU_TAG,
                callback=_on_menu_click,
                user_data=tag,
            )
    else:
        dpg.add_menu_item(label="(нет открытых окон)",
                          parent=MENU_TAG, enabled=False)

    if closed:
        dpg.add_separator(parent=MENU_TAG)
        dpg.add_menu_item(label="Открыть заново",
                          parent=MENU_TAG, enabled=False)
        for tag, info in closed:
            dpg.add_menu_item(
                label=f"[ ]  {info['label']}",  # было: "↻  ..."
                parent=MENU_TAG,
                callback=_on_menu_click,
                user_data=tag,
            )

    dpg.add_separator(parent=MENU_TAG)
    dpg.add_menu_item(label="Закрыть все",
                      parent=MENU_TAG,
                      callback=lambda s, a, u: close_all())