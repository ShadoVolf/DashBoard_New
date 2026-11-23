"""Нормы ФШ: стандартные отстройки при отсутствии спецификации."""

from __future__ import annotations

DEFAULT_OFFSETS = [1, 10, 100, 1000]


def ensure_norms(norms: list[dict] | None) -> list[dict]:
    """Если в спецификации нет активных норм - отстройки 1/10/100/1000 Гц."""
    if norms:
        return list(norms)
    return [
        {
            "num": i + 1,
            "offset": off,
            "min": None,
            "max": None,
            "flag_field": None,
        }
        for i, off in enumerate(DEFAULT_OFFSETS)
    ]
