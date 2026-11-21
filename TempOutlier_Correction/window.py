"""
Главное окно модуля «Коррекция выбросов ТЧХ».

UI:
  • выбор МСК и нескольких Measure_ID (как в Архиве)
  • запуск анализа / коррекции
  • график кривых номера (колесо — смена N, кнопка — увеличить)
  • сводная таблица метрик с пересчётом
  • сохранение скорректированного замера в БД
"""

from __future__ import annotations

import traceback
from typing import Any, Dict, List, Optional

import dearpygui.dearpygui as dpg
import pandas as pd

from . import data as toc_data
from . import graph as toc_graph
from . import logic as toc_logic
from . import metrics as toc_metrics
from .constants import (
    LEFT_PANEL,
    MID_LIST,
    MSK_COMBO,
    MSK_INPUT,
    NUMBER_COMBO,
    PARAM_COMBO,
    PLOT_CONTAINER,
    RIGHT_PANEL,
    SELECTED_LIST,
    STATUS_TAG,
    SUMMARY_CONTAINER,
    SUMMARY_TABLE,
    WIN_TAG,
    OUTLIER_PARAMS,
    SOURCES,
    SUMMARY_METRICS,
)


_state: Dict[str, Any] = {
    "msk": "",
    "available_mids": [],
    "selected_mids": [],
    "psi_df": pd.DataFrame(),
    "temps_df": pd.DataFrame(),
    "corrected_temps": pd.DataFrame(),
    "corrections": [],
    "report": {},
    "numbers": [],
    "current_number": "",
    "param": "F",
    "summary": pd.DataFrame(),
    "base_mid": None,
}


def _log(msg: str) -> None:
    print(f"[TOC] {msg}", flush=True)
    try:
        if dpg.does_item_exist(STATUS_TAG):
            dpg.set_value(STATUS_TAG, str(msg)[:200])
    except Exception:
        pass


def _set_combo(tag: str, items: list, value: str = "") -> None:
    if not dpg.does_item_exist(tag):
        return
    items = list(items or [])
    try:
        dpg.configure_item(tag, items=items)
        if value and value in items:
            dpg.set_value(tag, value)
        elif items:
            dpg.set_value(tag, items[0])
        else:
            dpg.set_value(tag, "")
    except Exception as e:
        _log(f"combo {tag}: {e}")


def _on_source_change(sender, app_data, user_data=None):
    toc_data.set_source(app_data)
    _log(f"Источник: {app_data}")


def _on_msk_search(sender=None, app_data=None, user_data=None):
    q = dpg.get_value(MSK_INPUT) if dpg.does_item_exist(MSK_INPUT) else ""
    found = toc_data.search_msk(q)
    _set_combo(MSK_COMBO, found, found[0] if found else "")
    _log(f"МСК найдено: {len(found)}")


def _on_msk_pick(sender=None, app_data=None, user_data=None):
    msk = dpg.get_value(MSK_COMBO) if dpg.does_item_exist(MSK_COMBO) else ""
    if not msk:
        msk = dpg.get_value(MSK_INPUT) if dpg.does_item_exist(MSK_INPUT) else ""
    msk = (msk or "").strip()
    _state["msk"] = msk
    if not msk:
        return
    mids = toc_data.list_measure_ids_for_msk(msk)
    _state["available_mids"] = mids
    labels = [
        f"{r['Measure_ID']}  |  {r.get('Date') or ''}  |  N×{r.get('n_count') or '?'}"
        for r in mids
    ]
    if dpg.does_item_exist(MID_LIST):
        dpg.configure_item(MID_LIST, items=labels)
    _state["selected_mids"] = []
    _refresh_selected_list()
    _log(f"МСК {msk}: {len(mids)} замеров")


def _mid_from_label(label: str) -> Optional[int]:
    try:
        return int(str(label).split("|")[0].strip())
    except (TypeError, ValueError):
        return None


def _on_add_selected(sender=None, app_data=None, user_data=None):
    if not dpg.does_item_exist(MID_LIST):
        return
    selected = dpg.get_value(MID_LIST) or []
    if isinstance(selected, str):
        selected = [selected]
    for lab in selected:
        mid = _mid_from_label(lab)
        if mid and mid not in _state["selected_mids"]:
            _state["selected_mids"].append(mid)
    _refresh_selected_list()


def _on_add_all(sender=None, app_data=None, user_data=None):
    for r in _state["available_mids"]:
        mid = int(r["Measure_ID"])
        if mid not in _state["selected_mids"]:
            _state["selected_mids"].append(mid)
    _refresh_selected_list()


def _on_remove_selected(sender=None, app_data=None, user_data=None):
    if not dpg.does_item_exist(SELECTED_LIST):
        return
    selected = dpg.get_value(SELECTED_LIST) or []
    if isinstance(selected, str):
        selected = [selected]
    remove = set()
    for lab in selected:
        mid = _mid_from_label(lab)
        if mid:
            remove.add(mid)
    _state["selected_mids"] = [m for m in _state["selected_mids"] if m not in remove]
    _refresh_selected_list()


def _on_clear_selected(sender=None, app_data=None, user_data=None):
    _state["selected_mids"] = []
    _refresh_selected_list()


def _refresh_selected_list():
    labels = []
    by_id = {int(r["Measure_ID"]): r for r in _state["available_mids"]}
    for mid in _state["selected_mids"]:
        r = by_id.get(mid, {})
        labels.append(
            f"{mid}  |  {r.get('Date') or ''}  |  N×{r.get('n_count') or '?'}"
        )
    if dpg.does_item_exist(SELECTED_LIST):
        dpg.configure_item(SELECTED_LIST, items=labels)
    _log(f"Выбрано замеров: {len(_state['selected_mids'])}")


def _on_load(sender=None, app_data=None, user_data=None):
    mids = list(_state["selected_mids"])
    if len(mids) < 1:
        _log("Выберите хотя бы один замер")
        return
    _log("Загрузка данных…")
    try:
        psi = toc_data.load_psidata(mids)
        temps = toc_data.load_temps(mids)
        _state["psi_df"] = psi
        _state["temps_df"] = temps
        nums = toc_data.unique_numbers(psi)
        _state["numbers"] = nums
        _state["current_number"] = nums[0] if nums else ""
        _state["base_mid"] = mids[0]
        _state["corrected_temps"] = pd.DataFrame()
        _state["corrections"] = []
        _state["report"] = {}
    except Exception as e:
        _log(f"Ошибка загрузки: {e}")
        traceback.print_exc()
        return
    _set_combo(NUMBER_COMBO, _state["numbers"], _state["current_number"])
    _refresh_plot()
    _refresh_summary(_state["base_mid"])
    _log(
        f"Загружено: psi={len(_state['psi_df'])}, "
        f"temp={len(_state['temps_df'])}, N={len(_state['numbers'])}"
    )


def _on_analyze(sender=None, app_data=None, user_data=None):
    mids = list(_state["selected_mids"])
    if len(mids) < 2:
        _log("Для сравнения нужно ≥ 2 замера одной МСК")
        return
    if _state["temps_df"].empty:
        _on_load()
        if _state["temps_df"].empty:
            return

    _log("Анализ выбросов…")
    prefer = _state.get("base_mid") or mids[0]
    corrected, corrections, report = toc_logic.build_corrected_temps(
        _state["temps_df"],
        mids,
        params=OUTLIER_PARAMS,
        prefer_mid=prefer,
    )
    _state["corrected_temps"] = corrected
    _state["corrections"] = corrections
    _state["report"] = report
    _state["base_mid"] = report.get("base_mid", prefer)

    base_mid = _state["base_mid"]
    temps_view = _state["temps_df"].copy()
    if not corrected.empty:
        mask = temps_view["Measure_ID"] == base_mid
        temps_view = temps_view[~mask]
        temps_view = pd.concat([temps_view, corrected], ignore_index=True)
    _state["_temps_for_summary"] = temps_view
    _refresh_plot()
    _refresh_summary(base_mid, temps_override=temps_view)
    n_corr = report.get("n_corrections", 0)
    _log(f"Готово: правок {n_corr}, base MID={base_mid}")


def _on_recalc_metrics(sender=None, app_data=None, user_data=None):
    base = _state.get("base_mid")
    if not base:
        _log("Нет базового Measure_ID")
        return
    temps = _state.get("_temps_for_summary")
    if temps is None or (isinstance(temps, pd.DataFrame) and temps.empty):
        temps = (
            _state["corrected_temps"]
            if not _state["corrected_temps"].empty
            else _state["temps_df"]
        )
    _refresh_summary(base, temps_override=temps)
    _log("Метрики пересчитаны")


def _curves_for_current() -> Dict[str, pd.DataFrame]:
    n = _state.get("current_number") or ""
    temps = _state["temps_df"]
    curves: Dict[str, pd.DataFrame] = {}
    if temps is None or temps.empty or not n:
        return curves
    for mid in _state["selected_mids"]:
        sub = temps[
            (temps["Measure_ID"] == mid)
            & (temps["N"].astype(str).str.strip().str.upper() == n)
        ]
        if not sub.empty:
            curves[f"MID {mid}"] = sub
    corr = _state.get("corrected_temps")
    if corr is not None and not corr.empty:
        csub = corr[corr["N"].astype(str).str.strip().str.upper() == n]
        if not csub.empty:
            curves["corrected"] = csub
    return curves


def _refresh_plot():
    param = dpg.get_value(PARAM_COMBO) if dpg.does_item_exist(PARAM_COMBO) else "F"
    _state["param"] = param or "F"
    curves = _curves_for_current()
    if not dpg.does_item_exist(PLOT_CONTAINER):
        return
    toc_graph.render_curves(
        PLOT_CONTAINER,
        curves,
        param=_state["param"],
        height=360,
        title=f"N {_state.get('current_number') or ''}",
    )


def _on_param_change(sender=None, app_data=None, user_data=None):
    _refresh_plot()


def _on_number_change(sender=None, app_data=None, user_data=None):
    n = dpg.get_value(NUMBER_COMBO) if dpg.does_item_exist(NUMBER_COMBO) else ""
    _state["current_number"] = (n or "").strip().upper()
    _refresh_plot()


def _shift_number(delta: int):
    nums = _state.get("numbers") or []
    if not nums:
        return
    cur = _state.get("current_number") or nums[0]
    try:
        idx = nums.index(cur)
    except ValueError:
        idx = 0
    idx = (idx + delta) % len(nums)
    _state["current_number"] = nums[idx]
    if dpg.does_item_exist(NUMBER_COMBO):
        dpg.set_value(NUMBER_COMBO, nums[idx])
    _refresh_plot()


def _on_wheel(sender, app_data, user_data=None):
    try:
        delta = int(app_data)
    except Exception:
        delta = 0
    if delta == 0:
        return
    _shift_number(-1 if delta > 0 else 1)


def _on_enlarge(sender=None, app_data=None, user_data=None):
    curves = _curves_for_current()
    toc_graph.open_enlarged_graph(
        curves,
        _state.get("param") or "F",
        _state.get("current_number") or "",
        on_wheel=_on_wheel,
    )


def _refresh_summary(measure_id: int, temps_override: Optional[pd.DataFrame] = None):
    temps = temps_override if temps_override is not None else _state["temps_df"]
    psi = _state["psi_df"]
    summary = toc_metrics.build_summary_table(psi, temps, measure_id)
    _state["summary"] = summary

    if not dpg.does_item_exist(SUMMARY_CONTAINER):
        return
    try:
        dpg.delete_item(SUMMARY_CONTAINER, children_only=True)
    except Exception:
        pass

    cols = ["N", "Status"] + list(SUMMARY_METRICS)
    with dpg.table(
        parent=SUMMARY_CONTAINER,
        tag=SUMMARY_TABLE,
        header_row=True,
        resizable=True,
        borders_innerH=True,
        borders_outerH=True,
        borders_innerV=True,
        borders_outerV=True,
        scrollY=True,
        height=280,
        policy=dpg.mvTable_SizingStretchProp,
    ):
        for c in cols:
            dpg.add_table_column(label=c)
        if summary is None or summary.empty:
            return
        for _, row in summary.iterrows():
            with dpg.table_row():
                for c in cols:
                    val = row.get(c, "")
                    if val is None or (isinstance(val, float) and pd.isna(val)):
                        txt = ""
                    elif isinstance(val, float):
                        txt = f"{val:.4g}"
                    else:
                        txt = str(val)
                    dpg.add_text(txt)


def _on_save(sender=None, app_data=None, user_data=None):
    msk = _state.get("msk") or ""
    base = _state.get("base_mid")
    corr_temps = _state.get("corrected_temps")
    if not msk or not base:
        _log("Нет МСК / base MID")
        return
    if corr_temps is None or corr_temps.empty:
        _log("Нет скорректированных температур — сначала «Анализ»")
        return

    psi = _state["psi_df"]
    psi_base = psi[psi["Measure_ID"] == base].copy()
    if psi_base.empty:
        _log("Нет строк psidata для base MID")
        return

    temps_for_metrics = corr_temps.copy()
    temps_for_metrics["Measure_ID"] = base
    psi_upd = toc_metrics.apply_metrics_to_psidata(psi_base, temps_for_metrics, base)

    try:
        new_mid = toc_data.save_corrected_measure(
            psi_upd,
            corr_temps,
            msk=msk,
            source_mids=_state["selected_mids"],
            login="toc",
        )
        _log(f"Сохранено как Measure_ID={new_mid}")
    except Exception as e:
        _log(f"Ошибка сохранения: {e}")
        traceback.print_exc()



def _register_for_window_manager():
    """Регистрация в меню «Окна» (как PhaseNoise / Assistant)."""
    try:
        from window_manager import register, rebuild_menu
        register(WIN_TAG, "Коррекция выбросов ТЧХ", create_temp_outlier_window)
        try:
            rebuild_menu()
        except Exception:
            pass
    except Exception as e:
        print(f"[TOC] window_manager недоступен: {e}", flush=True)

def create_temp_outlier_window():
    if dpg.does_item_exist(WIN_TAG):
        try:
            dpg.configure_item(WIN_TAG, show=True)
        except Exception:
            pass
        try:
            dpg.focus_item(WIN_TAG)
        except Exception:
            pass
        _register_for_window_manager()
        return

    try:
        sw = dpg.get_viewport_client_width() or 1400
        sh = dpg.get_viewport_client_height() or 900
    except Exception:
        sw, sh = 1400, 900

    w = min(1280, int(sw * 0.92))
    h = min(820, int(sh * 0.90))
    x = max(0, (sw - w) // 2)
    y = max(20, (sh - h) // 2)

    with dpg.window(
        label="Коррекция выбросов ТЧХ",
        tag=WIN_TAG,
        width=w,
        height=h,
        pos=(x, y),
        on_close=lambda: None,
    ):
        with dpg.group(horizontal=True):
            with dpg.child_window(tag=LEFT_PANEL, width=340, height=-1, border=True):
                dpg.add_text("Источник данных")
                dpg.add_combo(
                    [s[0] for s in SOURCES],
                    default_value=SOURCES[0][0],
                    width=-1,
                    callback=_on_source_change,
                )
                dpg.add_separator()
                dpg.add_text("МСК")
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag=MSK_INPUT, width=180, hint="часть номера")
                    dpg.add_button(label="Найти", callback=_on_msk_search, width=60)
                dpg.add_combo([], tag=MSK_COMBO, width=-1, callback=_on_msk_pick)
                dpg.add_button(
                    label="Загрузить список MID", callback=_on_msk_pick, width=-1
                )

                dpg.add_spacer(height=4)
                dpg.add_text("Доступные Measure_ID")
                dpg.add_listbox([], tag=MID_LIST, num_items=8, width=-1)
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Добавить", callback=_on_add_selected, width=100)
                    dpg.add_button(label="Все", callback=_on_add_all, width=60)
                dpg.add_text("Выбранные для сравнения")
                dpg.add_listbox([], tag=SELECTED_LIST, num_items=6, width=-1)
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Убрать", callback=_on_remove_selected, width=100
                    )
                    dpg.add_button(
                        label="Очистить", callback=_on_clear_selected, width=80
                    )

                dpg.add_separator()
                dpg.add_button(label="1. Загрузить данные", callback=_on_load, width=-1)
                dpg.add_button(
                    label="2. Анализ и коррекция", callback=_on_analyze, width=-1
                )
                dpg.add_button(
                    label="3. Пересчёт метрик", callback=_on_recalc_metrics, width=-1
                )
                dpg.add_button(
                    label="4. Сохранить скорректированный замер",
                    callback=_on_save,
                    width=-1,
                )
                dpg.add_separator()
                dpg.add_text("—", tag=STATUS_TAG, wrap=320)

            with dpg.child_window(tag=RIGHT_PANEL, width=-1, height=-1, border=True):
                with dpg.group(horizontal=True):
                    dpg.add_text("Параметр:")
                    dpg.add_combo(
                        list(OUTLIER_PARAMS) + ["FL", "Q", "Mono"],
                        default_value="F",
                        tag=PARAM_COMBO,
                        width=90,
                        callback=_on_param_change,
                    )
                    dpg.add_text("  Номер:")
                    dpg.add_combo(
                        [], tag=NUMBER_COMBO, width=120, callback=_on_number_change
                    )
                    dpg.add_button(
                        label="◀", callback=lambda: _shift_number(-1), width=30
                    )
                    dpg.add_button(
                        label="▶", callback=lambda: _shift_number(1), width=30
                    )
                    dpg.add_button(
                        label="Увеличить график", callback=_on_enlarge, width=140
                    )

                dpg.add_text(
                    "Колесо мыши над окном — смена номера. "
                    "Жёлтая кривая — corrected.",
                    color=(140, 180, 220),
                )
                with dpg.child_window(tag=PLOT_CONTAINER, height=380, border=False):
                    pass

                dpg.add_separator()
                dpg.add_text("Сводная таблица (метрики по температурам)")
                with dpg.child_window(tag=SUMMARY_CONTAINER, height=-1, border=False):
                    pass

    handler = "toc_wheel_handler"
    if dpg.does_item_exist(handler):
        try:
            dpg.delete_item(handler)
        except Exception:
            pass
    with dpg.handler_registry(tag=handler):
        dpg.add_mouse_wheel_handler(callback=_on_wheel)

    _log("Окно готово. Выберите МСК и ≥2 замера.")
