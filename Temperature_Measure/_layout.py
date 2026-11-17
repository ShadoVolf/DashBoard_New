"""Адаптивная раскладка окон модуля «Измерения параметров».

Позиции и размеры окон считаются от размера клиентской области
вьюпорта, а не от жёстко заданных пикселей. Это позволяет модулю
корректно работать на мониторах с любым разрешением.

Экспорт:
    screen_size()          — (ширина, высота) клиентской области
    compute_main_layout()  — {tag: ((x, y), (w, h))} для трёх основных
                             окон (файл, обработка, результаты)
    apply_main_layout()    — применить раскладку к уже созданным окнам
    dialog_rect(...)       — (pos, size) для модального диалога
    center_on_screen(tag)  — центрировать существующее окно
    init()                 — применить раскладку и подписать resize
"""
import sys

import dearpygui.dearpygui as dpg


MENU_OFFSET = 30
MARGIN = 8


def screen_size():
    """Размер клиентской области вьюпорта (не монитора)."""
    try:
        w = dpg.get_viewport_client_width()
        h = dpg.get_viewport_client_height()
        if w > 200 and h > 200:
            return int(w), int(h)
    except Exception:
        pass
    try:
        w = dpg.get_viewport_width()
        h = dpg.get_viewport_height()
        if w > 200 and h > 200:
            return int(w), int(h)
    except Exception:
        pass
    return 1920, 1080


def compute_main_layout():
    """Прямоугольники трёх основных окон по размеру вьюпорта.

    +-----------------+----------------------------+
    |                 | Обработка измерений        |
    | Выбор файла     +----------------------------+
    |                 | Результаты обработки       |
    +-----------------+----------------------------+
    """
    sw, sh = screen_size()
    top = MENU_OFFSET + MARGIN
    avail_h = max(sh - top - MARGIN, 500)
    avail_w = max(sw - MARGIN * 3, 800)

    left_w = max(340, int(sw * 0.22))
    mid_w = max(500, avail_w - left_w)

    proc_h = max(280, int(avail_h * 0.45))
    res_h = max(280, avail_h - proc_h - MARGIN)

    return {
        "select_measure_file_windows": (
            (MARGIN, top),
            (left_w, avail_h),
        ),
        "measure_window": (
            (MARGIN * 2 + left_w, top),
            (mid_w, proc_h),
        ),
        "stat_result_window": (
            (MARGIN * 2 + left_w, top + proc_h + MARGIN),
            (mid_w, res_h),
        ),
    }


def apply_main_layout():
    """Применить раскладку к существующим окнам модуля."""
    for tag, (pos, size) in compute_main_layout().items():
        if not dpg.does_item_exist(tag):
            continue
        try:
            dpg.configure_item(tag, pos=list(pos),
                               width=size[0], height=size[1])
        except Exception:
            pass


def dialog_rect(fraction_w=0.6, fraction_h=0.6,
                min_w=400, min_h=300,
                max_w=1400, max_h=1000):
    """Прямоугольник (pos, size) для модального окна по центру экрана."""
    sw, sh = screen_size()
    w = max(min_w, min(max_w, int(sw * fraction_w)))
    h = max(min_h, min(max_h, int(sh * fraction_h)))
    x = max(10, (sw - w) // 2)
    y = max(10, (sh - h) // 2)
    return (x, y), (w, h)


def center_on_screen(tag, width=None, height=None):
    """Центрировать существующее окно, сохранив его размеры."""
    if not dpg.does_item_exist(tag):
        return
    sw, sh = screen_size()
    try:
        if width is None:
            width = dpg.get_item_width(tag) or 400
        if height is None:
            height = dpg.get_item_height(tag) or 300
        x = max(10, (sw - int(width)) // 2)
        y = max(10, (sh - int(height)) // 2)
        dpg.configure_item(tag, pos=[x, y])
    except Exception:
        pass


_hooked = False


def _ensure_resize_hook():
    global _hooked
    if _hooked:
        return
    try:
        main_mod = sys.modules.get("main") or sys.modules.get("__main__")
        prev = getattr(main_mod, "_on_viewport_resize", None) \
            if main_mod else None

        def _combined(sender=None, app_data=None):
            if callable(prev):
                try:
                    prev(sender, app_data)
                except Exception:
                    pass
            apply_main_layout()

        dpg.set_viewport_resize_callback(_combined)
        _hooked = True
    except Exception:
        pass


def init():
    """Применить раскладку и подписать обработчик resize."""
    apply_main_layout()
    _ensure_resize_hook()