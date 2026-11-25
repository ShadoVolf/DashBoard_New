# -*- coding: utf-8 -*-
"""
Главное окно модуля Knowledge: каскад замера, автоподбор модели,
предсказание Filtr_Freq, таблица, печать, сохранение в БД, экспорт.
"""
from __future__ import annotations

import os
import traceback
from datetime import datetime
from typing import Any, Dict, List, Optional

import dearpygui.dearpygui as dpg
import pandas as pd

from . import data as kn_data
from . import logic as kn_logic
from . import models as kn_models
from . import report_print as kn_report
from .constants import (
    ALL_MSK,
    DATE_COMBO,
    EXPORT_BTN,
    FILE_COMBO,
    MID_COMBO,
    MID_INPUT,
    MODEL_INFO,
    MODEL_NAME_COMBO,
    MODEL_TYPE_COMBO,
    MSK_COMBO,
    NUMBERS_INPUT,
    ONLY_MISSING_CHECK,
    PREDICT_BTN,
    PRINT_BTN,
    RELOAD_BTN,
    RESULT_CONTAINER,
    RESULT_TABLE,
    SAVE_DB_BTN,
    SPC_COMBO,
    STATUS_TAG,
    TYPE_COMBO,
    WIN_TAG,
)

# Каскад моделей
MODEL_RTYPE_COMBO = "kn_model_rtype_combo"
MODEL_SPC_COMBO = "kn_model_spc_combo"
MODEL_ALGO_COMBO = "kn_model_algo_combo"  # model_type

_suppress_cascade = False

_state: Dict[str, Any] = {
    "all_models": [],
    "available_models": [],
    "selected_model": None,
    "psi_df": pd.DataFrame(),
    "result_df": pd.DataFrame(),
    "measure_id": None,
    "cascade_tree": {},
    "mid_meta": {},
}


def _log(msg: str) -> None:
    print(f"[Knowledge] {msg}", flush=True)
    try:
        if dpg.does_item_exist(STATUS_TAG):
            dpg.set_value(STATUS_TAG, str(msg)[:240])
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


def _mid_label(r: dict) -> str:
    mid = r.get("Measure_ID", "")
    msk = r.get("MSK") or ""
    date = r.get("Date") or ""
    n = r.get("n_count") or "?"
    return f"{mid} | {msk} | {date} | Nx{n}"


def _mid_from_label(label: str) -> Optional[int]:
    try:
        return int(str(label).split("|")[0].strip())
    except (TypeError, ValueError):
        return None


def _fmt_frac50(m: Optional[kn_models.ModelSpec]) -> str:
    if m is None or m.frac_50hz is None:
        return "n/a"
    v = m.frac_50hz
    if v <= 1.5:
        return f"{v * 100:.1f}%"
    return f"{v:.1f}%"


# ---------------------------------------------------------------------------
# Cascade measure
# ---------------------------------------------------------------------------

def on_type_changed(sender=None, app_data=None):
    if _suppress_cascade:
        return
    rtype = dpg.get_value(TYPE_COMBO) if dpg.does_item_exist(TYPE_COMBO) else ""
    specs = kn_data.get_specs_by_type(rtype) if rtype else kn_data.get_specs_by_type(None)
    _set_combo(SPC_COMBO, specs)
    on_spc_changed()


def on_spc_changed(sender=None, app_data=None):
    if _suppress_cascade:
        return
    spc = dpg.get_value(SPC_COMBO) if dpg.does_item_exist(SPC_COMBO) else ""
    msks = kn_data.get_msk_list(spc if spc else None)
    _set_combo(MSK_COMBO, [ALL_MSK] + msks, msks[0] if msks else ALL_MSK)
    on_msk_changed()


def on_msk_changed(sender=None, app_data=None):
    if _suppress_cascade:
        return
    if dpg.does_item_exist(MID_INPUT):
        dpg.set_value(MID_INPUT, "")
    msk = dpg.get_value(MSK_COMBO) if dpg.does_item_exist(MSK_COMBO) else ""
    spc = dpg.get_value(SPC_COMBO) if dpg.does_item_exist(SPC_COMBO) else ""
    dates = kn_data.get_dates_list(msk if msk != ALL_MSK else None, spc or None)
    _set_combo(DATE_COMBO, dates)
    mids = kn_data.list_measure_ids(
        msk=msk if msk != ALL_MSK else None,
        spc=spc or None,
    )
    labels = [_mid_label(r) for r in mids]
    _state["mid_meta"] = {_mid_label(r): r for r in mids}
    _set_combo(MID_COMBO, labels)
    on_date_changed()


def on_date_changed(sender=None, app_data=None):
    if _suppress_cascade:
        return
    msk = dpg.get_value(MSK_COMBO) if dpg.does_item_exist(MSK_COMBO) else ""
    spc = dpg.get_value(SPC_COMBO) if dpg.does_item_exist(SPC_COMBO) else ""
    date = dpg.get_value(DATE_COMBO) if dpg.does_item_exist(DATE_COMBO) else ""
    files = kn_data.get_files_list(
        msk if msk != ALL_MSK else None,
        spc or None,
        date or None,
    )
    _set_combo(FILE_COMBO, files)


def on_mid_combo_changed(sender=None, app_data=None):
    label = dpg.get_value(MID_COMBO) if dpg.does_item_exist(MID_COMBO) else ""
    mid = _mid_from_label(label)
    if mid is not None and dpg.does_item_exist(MID_INPUT):
        dpg.set_value(MID_INPUT, str(mid))


# ---------------------------------------------------------------------------
# Models cascade: rtype -> spc -> model_type -> model
# ---------------------------------------------------------------------------

def refresh_models(search_dir: Optional[str] = None):
    all_m = kn_models.discover_models()
    _state["all_models"] = all_m
    _state["available_models"] = list(all_m)
    _rebuild_model_cascade(all_m)
    _log(f"Моделей в model_metrics: {len(all_m)}")


def _rebuild_model_cascade(models: List[kn_models.ModelSpec], prefer: Optional[kn_models.ModelSpec] = None):
    tree = kn_models.cascade_levels(models)
    _state["cascade_tree"] = tree
    rtypes = sorted(tree.keys())
    pref_rt = prefer.rtype or prefer.scope or "all" if prefer else ""
    _set_combo(MODEL_RTYPE_COMBO, rtypes, pref_rt if pref_rt in rtypes else "")
    on_model_rtype_changed(prefer=prefer)


def on_model_rtype_changed(sender=None, app_data=None, prefer: Optional[kn_models.ModelSpec] = None):
    tree = _state.get("cascade_tree") or {}
    rt = dpg.get_value(MODEL_RTYPE_COMBO) if dpg.does_item_exist(MODEL_RTYPE_COMBO) else ""
    spcs = sorted((tree.get(rt) or {}).keys())
    pref_sp = prefer.spc_key if prefer else ""
    _set_combo(MODEL_SPC_COMBO, spcs, pref_sp if pref_sp in spcs else "")
    on_model_spc_changed(prefer=prefer)


def on_model_spc_changed(sender=None, app_data=None, prefer: Optional[kn_models.ModelSpec] = None):
    tree = _state.get("cascade_tree") or {}
    rt = dpg.get_value(MODEL_RTYPE_COMBO) if dpg.does_item_exist(MODEL_RTYPE_COMBO) else ""
    sp = dpg.get_value(MODEL_SPC_COMBO) if dpg.does_item_exist(MODEL_SPC_COMBO) else ""
    algos = sorted((tree.get(rt) or {}).get(sp, {}).keys())
    pref_mt = prefer.model_type if prefer else ""
    _set_combo(MODEL_ALGO_COMBO, algos, pref_mt if pref_mt in algos else "")
    on_model_algo_changed(prefer=prefer)


def on_model_algo_changed(sender=None, app_data=None, prefer: Optional[kn_models.ModelSpec] = None):
    tree = _state.get("cascade_tree") or {}
    rt = dpg.get_value(MODEL_RTYPE_COMBO) if dpg.does_item_exist(MODEL_RTYPE_COMBO) else ""
    sp = dpg.get_value(MODEL_SPC_COMBO) if dpg.does_item_exist(MODEL_SPC_COMBO) else ""
    mt = dpg.get_value(MODEL_ALGO_COMBO) if dpg.does_item_exist(MODEL_ALGO_COMBO) else ""
    models = list((tree.get(rt) or {}).get(sp, {}).get(mt, []) or [])
    _state["_type_models"] = models
    names = [m.name for m in models]
    pref_name = prefer.name if prefer else ""
    _set_combo(MODEL_NAME_COMBO, names, pref_name if pref_name in names else "")
    on_model_name_changed()


def on_model_name_changed(sender=None, app_data=None):
    name = dpg.get_value(MODEL_NAME_COMBO) if dpg.does_item_exist(MODEL_NAME_COMBO) else ""
    models = _state.get("_type_models") or []
    selected = None
    for m in models:
        if m.name == name:
            selected = m
            break
    _state["selected_model"] = selected
    if selected:
        info = (
            f"{selected.name}\n"
            f"type={selected.model_type}  spc={selected.spc_key}  "
            f"P(|e|<50Hz)={_fmt_frac50(selected)}\n"
            f"score={selected.test_score:.4f}  features={selected.features}"
        )
        _log(
            f"Model: type={selected.model_type}  "
            f"P(|err|<50Hz)={_fmt_frac50(selected)}  "
            f"spc={selected.spc_key}  id={selected.db_id}"
        )
    else:
        info = "-"
    if dpg.does_item_exist(MODEL_INFO):
        dpg.set_value(MODEL_INFO, info)


def auto_pick_model_ui():
    df = _state.get("psi_df")
    all_m = _state.get("all_models") or []
    if df is None or df.empty or not all_m:
        return
    avail = kn_logic.available_models_for_df(df, all_m)
    _state["available_models"] = avail if avail else list(all_m)
    best = kn_logic.auto_model_for_df(df, all_m)
    pool = avail if avail else all_m
    _rebuild_model_cascade(pool, prefer=best)
    if best:
        _log(
            f"Автомодель: type={best.model_type}  "
            f"P(|err|<50Hz)={_fmt_frac50(best)}  "
            f"spc={best.spc_key}  name={best.name}"
        )


# ---------------------------------------------------------------------------
# Load / Predict / Save
# ---------------------------------------------------------------------------

def reload_data(sender=None, app_data=None):
    try:
        mid_str = dpg.get_value(MID_INPUT) if dpg.does_item_exist(MID_INPUT) else ""
        measure_id = None
        if mid_str and str(mid_str).strip().isdigit():
            measure_id = int(str(mid_str).strip())

        numbers = []
        if dpg.does_item_exist(NUMBERS_INPUT):
            numbers = kn_data.parse_numbers_input(dpg.get_value(NUMBERS_INPUT) or "")

        msk = dpg.get_value(MSK_COMBO) if dpg.does_item_exist(MSK_COMBO) else None
        spc = dpg.get_value(SPC_COMBO) if dpg.does_item_exist(SPC_COMBO) else None
        date = dpg.get_value(DATE_COMBO) if dpg.does_item_exist(DATE_COMBO) else None

        df = kn_data.load_psi_filtered(
            measure_id=measure_id,
            msk=msk,
            spc=spc or None,
            numbers=numbers or None,
            date=date or None,
        )
        _state["psi_df"] = df
        ctx = kn_logic.resolve_context(df)
        _state["measure_id"] = ctx.get("measure_id") or measure_id
        _log(
            f"Загружено строк: {len(df)}; "
            f"Spc={ctx.get('spc')}; nominal~={ctx.get('nominal_mhz')}; "
            f"MID={_state['measure_id']}"
        )
        if not _state.get("all_models"):
            refresh_models()
        auto_pick_model_ui()
        # Сразу показать данные замера в таблице (без Filtr_Freq)
        _state["result_df"] = df.copy() if df is not None else pd.DataFrame()
        _fill_result_table(_state["result_df"], show_pred=False)
    except Exception as e:
        _log(f"Ошибка загрузки: {e}")
        traceback.print_exc()


def do_predict(sender=None, app_data=None):
    try:
        df = _state.get("psi_df")
        model = _state.get("selected_model")
        if df is None or df.empty:
            _log("Нет данных замера - сначала Загрузить")
            return
        if model is None:
            _log("Модель не выбрана")
            return
        only_missing = True
        if dpg.does_item_exist(ONLY_MISSING_CHECK):
            only_missing = bool(dpg.get_value(ONLY_MISSING_CHECK))

        work = df
        if only_missing and "Filtr_Freq" in df.columns:
            ff = pd.to_numeric(df["Filtr_Freq"], errors="coerce")
            work = df[ff.isna()].copy()
            if work.empty:
                _log("Все строки уже имеют Filtr_Freq")
                return

        result = kn_logic.predict_for_measure(work, model)
        if only_missing and len(result) < len(df):
            full = df.copy()
            if "Filtr_Freq_pred" not in full.columns:
                full["Filtr_Freq_pred"] = pd.NA
            full.loc[result.index, "Filtr_Freq_pred"] = result["Filtr_Freq_pred"]
            if "Filtr_Freq" in result.columns:
                full.loc[result.index, "Filtr_Freq"] = result["Filtr_Freq"]
            result = full

        _state["result_df"] = result
        _fill_result_table(result, show_pred=True)
        n_ok = int(pd.to_numeric(result.get("Filtr_Freq_pred"), errors="coerce").notna().sum())
        _log(
            f"Предсказание: {n_ok}/{len(result)}  "
            f"type={model.model_type}  P(|err|<50Hz)={_fmt_frac50(model)}"
        )
    except Exception as e:
        _log(f"Ошибка предсказания: {e}")
        traceback.print_exc()


def do_save_db(sender=None, app_data=None):
    try:
        result = _state.get("result_df")
        mid = _state.get("measure_id")
        if result is None or result.empty:
            _log("Нет результата для сохранения")
            return
        if mid is None and "Measure_ID" in result.columns:
            try:
                mid = int(result["Measure_ID"].dropna().iloc[0])
            except Exception:
                mid = None
        if mid is None:
            _log("Неизвестен Measure_ID - сохранение невозможно")
            return
        n = kn_logic.save_predictions(int(mid), result)
        _log(f"Сохранено в БД: {n} strok (Measure_ID={mid})")
    except Exception as e:
        _log(f"Ошибка сохранения: {e}")
        traceback.print_exc()


def do_export(sender=None, app_data=None):
    try:
        result = _state.get("result_df")
        if result is None or result.empty:
            _log("Нет данных для экспорта")
            return
        mid = _state.get("measure_id") or "unknown"
        try:
            import Options
            out_dir = Options.get_measure_protokol_path()
        except Exception:
            out_dir = os.getcwd()
        os.makedirs(out_dir, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        path = os.path.join(out_dir, f"Knowledge_FiltrFreq_{mid}_{ts}.csv")
        kn_logic.export_result(result, path)
        _log(f"Экспорт: {path}")
    except Exception as e:
        _log(f"Ошибка экспорта: {e}")
        traceback.print_exc()


def do_print(sender=None, app_data=None):
    try:
        result = _state.get("result_df")
        if result is None or result.empty:
            result = _state.get("psi_df")
        if result is None or result.empty:
            _log("Нет данных для печати")
            return
        mid = _state.get("measure_id") or "-"
        view = {
            "Operator": "Knowledge",
            "Protokol_Type": "Filtr_Freq",
            "MSK": dpg.get_value(MSK_COMBO) if dpg.does_item_exist(MSK_COMBO) else "",
            "Spc": dpg.get_value(SPC_COMBO) if dpg.does_item_exist(SPC_COMBO) else "",
        }
        path = kn_report.print_or_export(result, mid, view_data=view, prefer_pdf=True)
        _log(f"Протокол: {path}")
    except Exception as e:
        _log(f"Ошибка печати: {e}")
        traceback.print_exc()


def _fill_result_table(df: pd.DataFrame, show_pred: bool = False):
    if not dpg.does_item_exist(RESULT_TABLE):
        return
    children = dpg.get_item_children(RESULT_TABLE, slot=1) or []
    for ch in children:
        try:
            dpg.delete_item(ch)
        except Exception:
            pass

    if df is None or df.empty:
        return

    # Filtr_Freq из таблицы убран; pred показываем только после предсказания
    show_cols = [
        c for c in (
            "ID", "Number", "MSK", "Spc", "F", "R", "Q", "C0", "Cq",
            "Nominal", "Filtr_Freq_pred",
        ) if c in df.columns
    ]
    if not show_pred:
        show_cols = [c for c in show_cols if c != "Filtr_Freq_pred"]
    if not show_cols:
        show_cols = [c for c in df.columns if str(c).lower() != "filtr_freq"][:12]

    view = df[show_cols].head(500)
    for _, row in view.iterrows():
        with dpg.table_row(parent=RESULT_TABLE):
            for c in show_cols:
                val = row[c]
                if pd.isna(val):
                    txt = ""
                elif isinstance(val, float):
                    txt = f"{val:.6g}"
                else:
                    txt = str(val)
                dpg.add_text(txt)


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------

def create_knowledge_window():
    if dpg.does_item_exist(WIN_TAG):
        dpg.focus_item(WIN_TAG)
        return

    try:
        from Temperature_Measure import _layout
        sw, sh = _layout.screen_size()
    except Exception:
        try:
            sw = dpg.get_viewport_client_width() or 1400
            sh = dpg.get_viewport_client_height() or 900
        except Exception:
            sw, sh = 1400, 900

    margin = 8
    w = max(1000, sw - margin * 2)
    h = max(650, sh - margin * 2)
    x = margin
    y = margin + 24

    with dpg.window(
        label="Knowledge - Filtr_Freq",
        tag=WIN_TAG,
        width=w,
        height=h,
        pos=(x, y),
        no_collapse=True,
    ):
        with dpg.group(horizontal=True):
            with dpg.child_window(width=360, border=True):
                dpg.add_text("Выбор замера (как Архив)")
                dpg.add_separator()
                dpg.add_text("Тип")
                dpg.add_combo(items=[], tag=TYPE_COMBO, width=-1, callback=on_type_changed)
                dpg.add_text("Спецификация")
                dpg.add_combo(items=[], tag=SPC_COMBO, width=-1, callback=on_spc_changed)
                dpg.add_text("MSK")
                dpg.add_combo(items=[], tag=MSK_COMBO, width=-1, callback=on_msk_changed)
                dpg.add_text("Дата")
                dpg.add_combo(items=[], tag=DATE_COMBO, width=-1, callback=on_date_changed)
                dpg.add_text("Файл")
                dpg.add_combo(items=[], tag=FILE_COMBO, width=-1)
                dpg.add_text("Measure_ID (список)")
                dpg.add_combo(items=[], tag=MID_COMBO, width=-1, callback=on_mid_combo_changed)
                dpg.add_text("Measure_ID (ввод)")
                dpg.add_input_text(tag=MID_INPUT, width=-1, hint="ID замера")
                dpg.add_text("Номера (через запятую / диапазон)")
                dpg.add_input_text(tag=NUMBERS_INPUT, width=-1, hint="1,2,5-10")
                dpg.add_spacer(height=6)
                dpg.add_button(label="Загрузить замер", tag=RELOAD_BTN, width=-1, callback=reload_data)

                dpg.add_separator()
                dpg.add_text("Модели (таблица model_metrics)")
                dpg.add_button(label="Обновить список моделей", width=-1, callback=lambda: refresh_models())
                dpg.add_text("Тип модели (rtype/scope)")
                dpg.add_combo(items=[], tag=MODEL_RTYPE_COMBO, width=-1,
                              callback=on_model_rtype_changed)
                dpg.add_text("Спецификация модели")
                dpg.add_combo(items=[], tag=MODEL_SPC_COMBO, width=-1,
                              callback=on_model_spc_changed)
                dpg.add_text("model_type")
                dpg.add_combo(items=[], tag=MODEL_ALGO_COMBO, width=-1,
                              callback=on_model_algo_changed)
                dpg.add_text("Model")
                dpg.add_combo(items=[], tag=MODEL_NAME_COMBO, width=-1,
                              callback=on_model_name_changed)
                dpg.add_text("Info")
                dpg.add_input_text(tag=MODEL_INFO, multiline=True, height=80, width=-1, readonly=True)

                dpg.add_separator()
                dpg.add_checkbox(
                    label="Только без Filtr_Freq",
                    tag=ONLY_MISSING_CHECK,
                    default_value=True,
                )
                dpg.add_button(label="Предсказать Filtr_Freq", tag=PREDICT_BTN, width=-1, callback=do_predict)
                dpg.add_button(label="Сохранить в БД", tag=SAVE_DB_BTN, width=-1, callback=do_save_db)
                dpg.add_button(label="Печать протокола", tag=PRINT_BTN, width=-1, callback=do_print)
                dpg.add_button(label="Экспорт CSV", tag=EXPORT_BTN, width=-1, callback=do_export)

            with dpg.child_window(border=True, tag=RESULT_CONTAINER):
                dpg.add_text("Результат / данные замера")
                with dpg.table(
                    tag=RESULT_TABLE,
                    header_row=True,
                    resizable=True,
                    policy=dpg.mvTable_SizingStretchProp,
                    borders_innerH=True,
                    borders_outerH=True,
                    borders_innerV=True,
                    borders_outerV=True,
                    scrollY=True,
                    height=-40,
                ):
                    for col in (
                        "ID", "Number", "MSK", "Spc", "F", "R", "Q", "C0", "Cq",
                        "Nominal", "Filtr_Freq_pred",
                    ):
                        dpg.add_table_column(label=col)

        dpg.add_text("Готово", tag=STATUS_TAG)

    try:
        types = kn_data.get_types()
        _set_combo(TYPE_COMBO, types)
        if types:
            on_type_changed()
    except Exception as e:
        _log(f"init types: {e}")
    try:
        refresh_models()
    except Exception as e:
        _log(f"init models: {e}")
