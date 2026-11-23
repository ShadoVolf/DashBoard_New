"""Nastrojki modulya TOC: NN-opcii (otklyuchaemye)."""

from __future__ import annotations

from typing import Any, Dict

import dearpygui.dearpygui as dpg

SETTINGS_WIN = "toc_settings_window"

# default flags
DEFAULT_NN: Dict[str, bool] = {
    "use_isolation_forest": False,
    "use_autoencoder": False,
    "use_tcn_restore": False,
    "use_failure_classifier": False,
    "use_active_learning": False,
}

_state: Dict[str, bool] = dict(DEFAULT_NN)


def get_nn_options() -> Dict[str, bool]:
    return dict(_state)


def set_nn_options(opts: Dict[str, Any]) -> None:
    for k, v in opts.items():
        if k in _state:
            _state[k] = bool(v)


def open_settings_window() -> None:
    if dpg.does_item_exist(SETTINGS_WIN):
        dpg.focus_item(SETTINGS_WIN)
        return

    labels = {
        "use_isolation_forest": "Isolation Forest / autoencoder outlier score",
        "use_autoencoder": "Autoencoder anomaly detection",
        "use_tcn_restore": "TCN / seq2seq curve restore",
        "use_failure_classifier": "Failure type classifier (stand / single / noise)",
        "use_active_learning": "Active learning (operator feedback)",
    }

    with dpg.window(
        label="TOC - настройки NN",
        tag=SETTINGS_WIN,
        width=480,
        height=320,
        modal=False,
    ):
        dpg.add_text("Нейросетевые методы (все отключены по умолчанию)")
        dpg.add_separator()
        for key, title in labels.items():
            tag = f"toc_nn_{key}"
            dpg.add_checkbox(
                label=title,
                tag=tag,
                default_value=_state.get(key, False),
            )
        dpg.add_separator()
        dpg.add_text(
            "При включении алгоритмы подключаются в build_corrected_temps "
            "(hooks). Без моделей - классика: MAD + consensus + регрессия.",
            wrap=450,
        )
        with dpg.group(horizontal=True):
            dpg.add_button(label="Применить", callback=_on_apply, width=120)
            dpg.add_button(
                label="Закрыть",
                callback=lambda: dpg.delete_item(SETTINGS_WIN)
                if dpg.does_item_exist(SETTINGS_WIN)
                else None,
                width=100,
            )


def _on_apply(sender=None, app_data=None, user_data=None):
    for key in list(_state.keys()):
        tag = f"toc_nn_{key}"
        if dpg.does_item_exist(tag):
            _state[key] = bool(dpg.get_value(tag))
    print(f"[TOC] NN options: {_state}", flush=True)
