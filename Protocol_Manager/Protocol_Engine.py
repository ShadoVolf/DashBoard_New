"""Тонкий слой engine-хелперов для печатных модулей.

Здесь реэкспортируются `_engine` и общие утилиты, чтобы
`Protocol_Print.py` / `Protocol_Passport.py` не тянули напрямую
тяжёлый `Protocol_Data`.
"""
import re

from .Protocol_Data import _engine  # noqa: F401  (реэкспорт)

__all__ = ["_engine", "_nat_sort_key", "_status"]


def _nat_sort_key(value):
    """Естественная сортировка 'N' (JN2 < JN10, а не наоборот).

    Работает и со строками вида 'JN4450', '25-2456', '123'.
    """
    s = str(value if value is not None else "")
    return [int(tok) if tok.isdigit() else tok.lower()
            for tok in re.split(r"(\d+)", s)]


def _status(msg):
    """Статусная строка для печатных модулей.

    Если UI-тег существует — пишем туда, иначе в stdout.
    Не импортируем dpg на уровне модуля, чтобы Protocol_Engine
    оставался легковесным.
    """
    text = str(msg)
    try:
        import dearpygui.dearpygui as dpg
        from . import Protocol_Constants as _C
        if dpg.does_item_exist(_C.PM_STATUS_TAG):
            dpg.set_value(_C.PM_STATUS_TAG, text)
            return
    except Exception:
        pass
    print(f"[Protocol_Engine] {text}")