"""Обработка старения (уходов частоты) резонаторов СПЕКТР.

Порт логики из SpektrOLD.cpp / old.cpp (C++ Builder).
"""
from Temperature_Measure.Spektr_OLD.aging_logic import (
    compute_aging,
    load_old_by_id,
    load_old_id_meta,
    load_spec_old,
    search_measure_ids_by_number_partial,
)
from Temperature_Measure.Spektr_OLD.aging_gui import AgingWindow

__all__ = [
    'compute_aging', 'load_old_by_id', 'load_old_id_meta',
    'load_spec_old', 'search_measure_ids_by_number_partial',
    'AgingWindow',
]