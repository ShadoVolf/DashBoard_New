"""Nastrojki modulya TOC: NN-opcii (otklyuchaemye)."""

from __future__ import annotations

from typing import Any, Dict

import dearpygui.dearpygui as dpg

SETTINGS_WIN = "toc_settings_window"

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
        try:
            dpg.focus_item(SETTINGS_WIN)
        except Exception:
            pass
        return

    labels = {
        "use_isolation_forest": "Лес изолирующих деревьев (Isolation Forest)",
        "use_autoencoder": "Автоэнкодер (поиск аномалий)",
        "use_tcn_restore": "TCN / seq2seq восстановление кривой",
        "use_failure_classifier": "Классификатор типа сбоя (стенд / один / шум)",
        "use_active_learning": "Активное обучение (правки оператора)",
    }

    with dpg.window(
        label="TOC - настройки NN",
        tag=SETTINGS_WIN,
        width=520,
        height=360,
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
            "Изолирующий лес: скор выбросов по остатку от полинома (модель toc_if).\n"
            "TCN / seq2seq: восстановление «дыр» по кривой F(T) вместо полиномиального "
            "заполнения (модель toc_tcn; без модели - интерполяция сглаживанием).\n"
            "Классификатор сбоев: «сбой стенда / единичный резонатор / шум» по паттерну "
            "аномалий по всем N на одной T; температуры «сбоя стенда» удаляются "
            "со всех кривых замера и восстанавливаются моделью.\n"
            "Активное обучение: правки под графиком + кнопка «Добавить в обучение». "
            "Дообучить модель = toc_if + toc_tcn по TOC_Learning/samples.json.",
            wrap=490,
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
