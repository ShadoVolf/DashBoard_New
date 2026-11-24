"""
Glavnoe okno modulya korreksii vybrosov TCH.

UI:
  - kaskad Type -> Spec -> MSK -> Date (kak v Archive)
  - poisk MSK / Measure_ID po chasti (raznye imena MSK)
  - neskolko Measure_ID iz raznyh MSK v odnom spiske
  - grafik, svodnaya tablitsa, sohranenie
"""

from __future__ import annotations

import threading
import traceback
from datetime import datetime
from pathlib import Path as _Path
from queue import Queue, Empty
from typing import Any, Dict, List, Optional

import dearpygui.dearpygui as dpg
import pandas as pd

from . import data as toc_data
from . import graph as toc_graph
from . import logic as toc_logic
from . import metrics as toc_metrics
from . import settings as toc_settings
from . import learning as toc_learning
from .constants import (
    WIN_TAG,
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
    OUTLIER_PARAMS,
    SOURCES,
    SUMMARY_METRICS,
)

# Cascade tags
TYPE_COMBO = "toc_type_combo"
SPC_COMBO = "toc_spc_combo"
DATE_COMBO = "toc_date_combo"
FILE_COMBO = "toc_file_combo"
MID_SEARCH = "toc_mid_search"
MID_SEARCH_BTN = "toc_mid_search_btn"
PROGRESS_WIN = "toc_progress_win"
PROGRESS_BAR = "toc_progress_bar"
PROGRESS_TEXT = "toc_progress_text"
SETTINGS_BTN = "toc_settings_btn"
EDIT_CONTAINER = "toc_edit_container"
EDIT_TABLE = "toc_edit_table"
EXPORT_CHECK = "toc_export_check"
SAVE_DEBUG_CHECK = "toc_save_debug_check"
ONLY_CORR_CHECK = "toc_only_corr_check"

_suppress_cascade = False

_state: Dict[str, Any] = {
    "msk": "",
    "available_mids": [],       # list[dict] with Measure_ID, MSK, Date, ...
    "selected_mids": [],       # list[int] - can be from different MSK
    "selected_meta": {},       # mid -> dict meta (for display)
    "psi_df": pd.DataFrame(),
    "temps_df": pd.DataFrame(),
    "corrected_temps": pd.DataFrame(),
    "corrections": [],
    "report": {},
    "numbers": [],
    "current_number": "",
    "param": "F",
    "only_corrected": False,
    "summary": pd.DataFrame(),
    "base_mid": None,
}


def _log(msg: str) -> None:
    print(f"[TOC] {msg}", flush=True)
    try:
        if dpg.does_item_exist(STATUS_TAG):
            dpg.set_value(STATUS_TAG, str(msg)[:220])
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
    """ASCII-safe label: MID | MSK | Date | Nx"""
    mid = r.get("Measure_ID", "")
    msk = r.get("MSK") or ""
    date = r.get("Date") or ""
    n = r.get("n_count") or "?"
    return f"{mid} | {msk} | {date} | N x {n}"


def _mid_from_label(label: str) -> Optional[int]:
    try:
        return int(str(label).split("|")[0].strip())
    except (TypeError, ValueError):
        return None


def _resolve_spec_params() -> Dict[str, Any]:
    """Parametry specifikacii dlya metrik: Tnakl/Tnastr/polinom/TCH_Temp_A/B."""
    spc = ""
    if dpg.does_item_exist(SPC_COMBO):
        spc = (dpg.get_value(SPC_COMBO) or "").strip()
    if not spc:
        psi = _state.get("psi_df")
        if psi is not None and not psi.empty and "Spc" in psi.columns:
            vals = psi["Spc"].dropna().astype(str).str.strip()
            if not vals.empty:
                spc = str(vals.iloc[0])
    params = toc_data.get_spec_params(spc if spc else None)
    _state["spec_params"] = params
    tn = params.get("t_nakl") or params.get("t_nastr")
    _log(
        f"Spec: Tnakl={tn}, polinom={params.get('degree')}, "
        f"T=[{params.get('ta')}; {params.get('tb')}]"
    )
    return params


# ---------------------------------------------------------------------------
# Source / cascade
# ---------------------------------------------------------------------------

def _on_source_change(sender, app_data, user_data=None):
    toc_data.set_source(app_data)
    _log(f"Istochnik: {app_data}")
    _cascade_bootstrap()


def _cascade_bootstrap():
    global _suppress_cascade
    _suppress_cascade = True
    try:
        types = toc_data.get_types()
        _set_combo(TYPE_COMBO, types, types[0] if types else "")
    finally:
        _suppress_cascade = False
    _on_type_changed()


def _on_type_changed(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    rtype = dpg.get_value(TYPE_COMBO) if dpg.does_item_exist(TYPE_COMBO) else ""
    specs = toc_data.get_specs_by_type(rtype) if rtype else []
    _set_combo(SPC_COMBO, specs, specs[0] if specs else "")
    _on_spc_changed()


def _on_spc_changed(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    spc = dpg.get_value(SPC_COMBO) if dpg.does_item_exist(SPC_COMBO) else ""
    _state["spec_params"] = None  # perechitat pri sleduyushchem pereschete
    msks = toc_data.get_msk_list(spc if spc else None)
    _set_combo(MSK_COMBO, msks, msks[0] if msks else "")
    _on_msk_changed()


def _on_msk_changed(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    msk = dpg.get_value(MSK_COMBO) if dpg.does_item_exist(MSK_COMBO) else ""
    spc = dpg.get_value(SPC_COMBO) if dpg.does_item_exist(SPC_COMBO) else ""
    _state["msk"] = (msk or "").strip()
    dates = toc_data.get_dates_list(msk if msk else None, spc if spc else None)
    _set_combo(DATE_COMBO, dates, dates[0] if dates else "")
    _on_date_changed()


def _on_date_changed(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    msk = dpg.get_value(MSK_COMBO) if dpg.does_item_exist(MSK_COMBO) else ""
    spc = dpg.get_value(SPC_COMBO) if dpg.does_item_exist(SPC_COMBO) else ""
    date = dpg.get_value(DATE_COMBO) if dpg.does_item_exist(DATE_COMBO) else ""
    files = toc_data.get_files_list(
        msk if msk else None,
        spc if spc else None,
        date if date else None,
    )
    _set_combo(FILE_COMBO, files, files[0] if files else "")
    _refresh_available_mids()


def _refresh_available_mids():
    msk = dpg.get_value(MSK_COMBO) if dpg.does_item_exist(MSK_COMBO) else ""
    spc = dpg.get_value(SPC_COMBO) if dpg.does_item_exist(SPC_COMBO) else ""
    date = dpg.get_value(DATE_COMBO) if dpg.does_item_exist(DATE_COMBO) else ""
    file = dpg.get_value(FILE_COMBO) if dpg.does_item_exist(FILE_COMBO) else ""
    mids = toc_data.list_measure_ids(
        msk=msk or None,
        spc=spc or None,
        date=date or None,
        file=file or None,
    )
    _state["available_mids"] = mids
    labels = [_mid_label(r) for r in mids]
    if dpg.does_item_exist(MID_LIST):
        dpg.configure_item(MID_LIST, items=labels)
    _log(f"Dostupno Measure_ID: {len(mids)}")


# ---------------------------------------------------------------------------
# Free search (MSK / MID) - different names allowed
# ---------------------------------------------------------------------------

def _on_msk_search(sender=None, app_data=None, user_data=None):
    q = dpg.get_value(MSK_INPUT) if dpg.does_item_exist(MSK_INPUT) else ""
    found = toc_data.search_msk(q)
    _set_combo(MSK_COMBO, found, found[0] if found else "")
    if found:
        _state["msk"] = found[0]
        _on_msk_changed()
    _log(f"MSK naydeno: {len(found)}")


def _on_mid_search(sender=None, app_data=None, user_data=None):
    q = dpg.get_value(MID_SEARCH) if dpg.does_item_exist(MID_SEARCH) else ""
    found = toc_data.search_measure_id(q)
    if not found:
        _log("Measure_ID ne nayden")
        return
    # merge into available list (may be different MSK)
    by_id = {int(r["Measure_ID"]): r for r in _state["available_mids"]}
    for r in found:
        by_id[int(r["Measure_ID"])] = r
    _state["available_mids"] = list(by_id.values())
    labels = [_mid_label(r) for r in _state["available_mids"]]
    if dpg.does_item_exist(MID_LIST):
        dpg.configure_item(MID_LIST, items=labels)
    _log(f"Poisk MID: naydeno {len(found)}, v spiske {len(labels)}")


# ---------------------------------------------------------------------------
# Selection (multi-MSK ok)
# ---------------------------------------------------------------------------

def _on_add_selected(sender=None, app_data=None, user_data=None):
    if not dpg.does_item_exist(MID_LIST):
        return
    selected = dpg.get_value(MID_LIST) or []
    if isinstance(selected, str):
        selected = [selected]
    by_id = {int(r["Measure_ID"]): r for r in _state["available_mids"]}
    for lab in selected:
        mid = _mid_from_label(lab)
        if mid and mid not in _state["selected_mids"]:
            _state["selected_mids"].append(mid)
            meta = by_id.get(mid, {"Measure_ID": mid})
            _state["selected_meta"][mid] = meta
    _refresh_selected_list()


def _on_add_all(sender=None, app_data=None, user_data=None):
    for r in _state["available_mids"]:
        mid = int(r["Measure_ID"])
        if mid not in _state["selected_mids"]:
            _state["selected_mids"].append(mid)
            _state["selected_meta"][mid] = r
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
    for m in remove:
        _state["selected_meta"].pop(m, None)
    _refresh_selected_list()


def _on_clear_selected(sender=None, app_data=None, user_data=None):
    _state["selected_mids"] = []
    _state["selected_meta"] = {}
    _refresh_selected_list()


def _refresh_selected_list():
    labels = []
    for mid in _state["selected_mids"]:
        r = _state["selected_meta"].get(mid) or {"Measure_ID": mid}
        labels.append(_mid_label(r))
    if dpg.does_item_exist(SELECTED_LIST):
        dpg.configure_item(SELECTED_LIST, items=labels)
    # primary MSK for save = first selected meta
    if _state["selected_mids"]:
        first = _state["selected_meta"].get(_state["selected_mids"][0], {})
        if first.get("MSK"):
            _state["msk"] = str(first["MSK"])
    _log(f"Vybrano zamеров: {len(_state['selected_mids'])}")


# ---------------------------------------------------------------------------
# Load / analyze
# ---------------------------------------------------------------------------


_progress_q: Queue = Queue()
_worker_busy = False


def _show_progress(title: str = "Анализ..."):
    try:
        if dpg.does_item_exist(PROGRESS_WIN):
            dpg.delete_item(PROGRESS_WIN)
    except Exception:
        pass
    try:
        sw = dpg.get_viewport_client_width() or 1280
        sh = dpg.get_viewport_client_height() or 800
    except Exception:
        sw, sh = 1280, 800
    w, h = 460, 130
    with dpg.window(
        label=title,
        tag=PROGRESS_WIN,
        width=w,
        height=h,
        pos=((sw - w) // 2, (sh - h) // 2),
        no_close=True,
        no_collapse=True,
        no_resize=True,
    ):
        dpg.add_text("Подготовка...", tag=PROGRESS_TEXT)
        dpg.add_spacer(height=6)
        dpg.add_progress_bar(tag=PROGRESS_BAR, width=-1, default_value=0.0)
        dpg.add_text("Не закрывайте окно", color=(160, 160, 160))


def _update_progress(pct: float, msg: str = ""):
    """Thread-safe: queue update for main loop."""
    try:
        _progress_q.put(("progress", float(pct), str(msg or "")))
    except Exception:
        pass


def _hide_progress():
    try:
        _progress_q.put(("done", 100.0, "Готово"))
    except Exception:
        pass
    # also force-delete on main thread if possible
    try:
        if dpg.does_item_exist(PROGRESS_WIN):
            dpg.delete_item(PROGRESS_WIN)
    except Exception:
        pass


def _force_hide_progress():
    global _worker_busy
    try:
        while True:
            try:
                _progress_q.get_nowait()
            except Empty:
                break
    except Exception:
        pass
    try:
        if dpg.does_item_exist(PROGRESS_WIN):
            dpg.delete_item(PROGRESS_WIN)
    except Exception:
        pass
    _worker_busy = False


def _apply_progress_ui(pct: float, msg: str):
    try:
        if dpg.does_item_exist(PROGRESS_BAR):
            dpg.set_value(PROGRESS_BAR, max(0.0, min(1.0, float(pct) / 100.0)))
        if dpg.does_item_exist(PROGRESS_TEXT) and msg:
            dpg.set_value(PROGRESS_TEXT, str(msg)[:100])
        if dpg.does_item_exist(STATUS_TAG) and msg:
            dpg.set_value(STATUS_TAG, str(msg)[:220])
    except Exception:
        pass


def _poll_progress():
    """Vyzyvaetsya iz frame callback - tjanet ochered iz workera."""
    global _worker_busy
    try:
        while True:
            try:
                kind, pct, msg = _progress_q.get_nowait()
            except Empty:
                break
            if kind == "progress":
                _apply_progress_ui(pct, msg)
            elif kind == "result":
                # msg is unused; pct holds nothing; actual payload in _state['_worker_result']
                _finish_analyze_ui()
            elif kind == "error":
                _apply_progress_ui(0, f"Ошибка: {msg}")
                _log(f"Ошибка анализа: {msg}")
                _force_hide_progress()
            elif kind == "done":
                _apply_progress_ui(100, msg or "Готово")
                try:
                    if dpg.does_item_exist(PROGRESS_WIN):
                        dpg.delete_item(PROGRESS_WIN)
                except Exception:
                    pass
    except Exception as e:
        print(f"[TOC] poll: {e}", flush=True)
    try:
        dpg.set_frame_callback(dpg.get_frame_count() + 2, lambda: _poll_progress())
    except Exception:
        pass


def _start_progress_polling():
    try:
        dpg.set_frame_callback(dpg.get_frame_count() + 1, lambda: _poll_progress())
    except Exception:
        pass


def _on_load(sender=None, app_data=None, user_data=None):
    mids = list(_state["selected_mids"])
    if len(mids) < 1:
        _log("Vyberite hotya by odin zamer")
        return
    _log("Zagruzka dannyh...")
    try:
        psi = toc_data.load_psidata(mids)
        temps = toc_data.load_temps(mids)
        _state["psi_df"] = psi
        _state["temps_df"] = temps
        nums = toc_data.unique_numbers(psi)
        _state["numbers"] = nums
        _state["current_number"] = nums[0] if nums else ""
        _state["base_mid"] = mids[0]
        _resolve_spec_params()
        _state["corrected_temps"] = pd.DataFrame()
        _state["corrections"] = []
        _state["report"] = {}
    except Exception as e:
        _log(f"Oshibka zagruzki: {e}")
        traceback.print_exc()
        return
    _set_combo(NUMBER_COMBO, _state["numbers"], _state["current_number"])
    _refresh_plot()
    _refresh_summary(_state["base_mid"])
    _log(
        f"Zagruzheno: psi={len(_state['psi_df'])}, "
        f"temp={len(_state['temps_df'])}, N={len(_state['numbers'])}"
    )


def _on_analyze(sender=None, app_data=None, user_data=None):
    global _worker_busy
    if _worker_busy:
        _log("Analiz uzhe idet...")
        return
    mids = list(_state["selected_mids"])
    if len(mids) < 2:
        _log("Dlya sravneniya nuzhno >= 2 zamera")
        return
    if _state["temps_df"].empty:
        _on_load()
        if _state["temps_df"].empty:
            return

    prefer = _state.get("base_mid")  # None -> logic vyberet MID s menshim chislom sboev
    _show_progress("Анализ и коррекция")
    _apply_progress_ui(1, "Zapusk...")
    _worker_busy = True
    _start_progress_polling()

    temps_df = _state["temps_df"]
    nn_opts = toc_settings.get_nn_options()

    def worker():
        try:
            def _prog(pct, msg):
                _update_progress(pct, msg)

            corrected, corrections, report = toc_logic.build_corrected_temps(
                temps_df,
                mids,
                params=OUTLIER_PARAMS,
                prefer_mid=prefer,
                progress=_prog,
                nn_options=nn_opts,
            )
            _state["_worker_result"] = (corrected, corrections, report, mids)
            _progress_q.put(("result", 100.0, ""))
        except Exception as e:
            traceback.print_exc()
            _progress_q.put(("error", 0.0, str(e)))

    threading.Thread(target=worker, daemon=True).start()
    _log("Analiz zapushchen...")


def _finish_analyze_ui():
    global _worker_busy
    _worker_busy = False
    _force_hide_progress()
    payload = _state.pop("_worker_result", None)
    if not payload:
        return
    corrected, corrections, report, mids = payload
    _state["corrected_temps"] = corrected
    _state["corrections"] = corrections
    _state["report"] = report
    prefer = _state.get("base_mid")
    _state["base_mid"] = report.get("base_mid", prefer)

    base_mid = _state["base_mid"]
    _resolve_spec_params()
    if not corrected.empty:
        corr_for_sum = corrected.copy()
        if "Measure_ID" not in corr_for_sum.columns:
            corr_for_sum["Measure_ID"] = base_mid
        else:
            corr_for_sum["Measure_ID"] = base_mid
        _state["_temps_for_summary"] = corr_for_sum
        _refresh_summary(base_mid, temps_override=corr_for_sum)
    else:
        _state["_temps_for_summary"] = _state["temps_df"]
        _refresh_summary(base_mid)

    _refresh_plot()
    _refresh_edit_table()
    n_corr = report.get("n_corrections", 0)
    _log(f"Готово: правок {n_corr}, base MID={base_mid}")

    # export debug if checked
    try:
        if dpg.does_item_exist(SAVE_DEBUG_CHECK) and dpg.get_value(SAVE_DEBUG_CHECK):
            _export_debug_bundle()
    except Exception as e:
        _log(f"Экспорт отладки: {e}")


def _export_debug_bundle():
    """Syrye + corrected + log metodov v CSV/JSON."""
    out_dir = _Path("toc_debug_exports")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception:
        out_dir = _Path(".")
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    prefix = out_dir / f"toc_{stamp}"

    raw = _state.get("temps_df")
    corr = _state.get("corrected_temps")
    corr_list = _state.get("corrections") or []
    report = _state.get("report") or {}

    paths = []
    if raw is not None and not raw.empty:
        fp = f"{prefix}_raw.csv"
        raw.to_csv(fp, index=False)
        paths.append(fp)
    if corr is not None and not corr.empty:
        fp = f"{prefix}_corrected.csv"
        corr.to_csv(fp, index=False)
        paths.append(fp)
    if corr_list:
        fp = f"{prefix}_methods.csv"
        pd.DataFrame(corr_list).to_csv(fp, index=False)
        paths.append(fp)
    import json
    meta = {
        "mids": list(_state.get("selected_mids") or []),
        "base_mid": _state.get("base_mid"),
        "n_corrections": report.get("n_corrections"),
        "nn_options": report.get("nn_options"),
        "per_number": report.get("per_number"),
        "global": report.get("global"),
    }
    fp = f"{prefix}_report.json"
    with open(fp, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2, default=str)
    paths.append(fp)
    _log("Экспорт: " + ", ".join(str(x) for x in paths))


def _build_edit_table(parent: str):
    """Tablitsa skorrektirovannyh tochek v ukazannom parent (okno uvelicheniya)."""
    corr = _state.get("corrected_temps")
    n = (_state.get("current_number") or "").strip().upper()
    if corr is None or (hasattr(corr, "empty") and corr.empty) or not n:
        dpg.add_text("Нет скорректированных данных", parent=parent)
        return

    sub = corr[corr["N"].astype(str).str.strip().str.upper() == n].copy()
    if sub.empty:
        dpg.add_text(f"Нет данных для N={n}", parent=parent)
        return
    sub = sub.sort_values("Temp").reset_index(drop=True)
    _state["_edit_rows"] = sub

    with dpg.group(horizontal=True, parent=parent):
        dpg.add_button(
            label="Применить все правки",
            callback=_on_apply_edits,
            width=160,
        )
        dpg.add_text("  Изменение поля сразу обновляет кривую corrected", color=(140, 180, 220))

    with dpg.table(
        parent=parent,
        tag=EDIT_TABLE,
        header_row=True,
        resizable=True,
        borders_innerH=True,
        borders_outerH=True,
        borders_innerV=True,
        borders_outerV=True,
        scrollY=True,
        height=-1,
        policy=dpg.mvTable_SizingStretchProp,
    ):
        dpg.add_table_column(label="Temp", width_fixed=True, init_width_or_weight=70)
        dpg.add_table_column(label="F", width_fixed=True, init_width_or_weight=110)
        dpg.add_table_column(label="R", width_fixed=True, init_width_or_weight=110)
        dpg.add_table_column(label="F method")
        dpg.add_table_column(label="R method")
        for i, row in sub.iterrows():
            with dpg.table_row():
                dpg.add_text(
                    f"{float(row['Temp']):.2f}" if pd.notna(row.get("Temp")) else ""
                )
                ftag = f"toc_edit_f_{i}"
                rtag = f"toc_edit_r_{i}"
                fv = float(row["F"]) if "F" in row and pd.notna(row.get("F")) else 0.0
                rv = float(row["R"]) if "R" in row and pd.notna(row.get("R")) else 0.0
                dpg.add_input_float(
                    tag=ftag,
                    default_value=fv,
                    width=100,
                    step=0.1,
                    callback=_on_edit_cell_changed,
                    user_data=("F", i, float(row["Temp"]) if pd.notna(row.get("Temp")) else None),
                )
                dpg.add_input_float(
                    tag=rtag,
                    default_value=rv,
                    width=100,
                    step=0.01,
                    callback=_on_edit_cell_changed,
                    user_data=("R", i, float(row["Temp"]) if pd.notna(row.get("Temp")) else None),
                )
                fm = row.get("F_method", "") if "F_method" in row.index else ""
                rm = row.get("R_method", "") if "R_method" in row.index else ""
                dpg.add_text(str(fm)[:28])
                dpg.add_text(str(rm)[:28])


def _on_edit_cell_changed(sender=None, app_data=None, user_data=None):
    """Mgnovennoye obnovlenie corrected krivoj pri pravke yachejki."""
    if not user_data:
        return
    param, row_i, temp = user_data
    try:
        val = float(app_data) if app_data is not None else float(dpg.get_value(sender))
    except Exception:
        return
    corr = _state.get("corrected_temps")
    n = (_state.get("current_number") or "").strip().upper()
    if corr is None or corr.empty or not n or temp is None:
        return
    if param not in corr.columns:
        return
    mask = (
        (corr["N"].astype(str).str.strip().str.upper() == n)
        & ((corr["Temp"].astype(float) - float(temp)).abs() < 0.05)
    )
    if not mask.any():
        return
    corr.loc[mask, param] = val
    method_col = f"{param}_method"
    if method_col in corr.columns:
        corr.loc[mask, method_col] = "operator_edit"
    _state["corrected_temps"] = corr
    # refresh both plots
    _refresh_plot()
    _refresh_big_if_open()


def _refresh_edit_table():
    """Sovmestimost': esli est' big window - tuda, inache nichego na main."""
    if dpg.does_item_exist("toc_big_edit_area"):
        try:
            dpg.delete_item("toc_big_edit_area", children_only=True)
        except Exception:
            pass
        _build_edit_table("toc_big_edit_area")


def _refresh_big_if_open():
    if not dpg.does_item_exist("toc_window") and not dpg.does_item_exist("toc_big_graph_window"):
        pass
    from .constants import BIG_WIN_TAG
    if not dpg.does_item_exist(BIG_WIN_TAG):
        return
    curves = _curves_for_current()
    param = _state.get("param") or "F"
    n = _state.get("current_number") or ""
    toc_graph.refresh_enlarged_graph(
        curves,
        param,
        n,
        edit_builder=_build_edit_table,
        only_corrected=bool(_state.get("only_corrected")),
    )



def _on_apply_edits(sender=None, app_data=None, user_data=None):
    corr = _state.get("corrected_temps")
    n = (_state.get("current_number") or "").strip().upper()
    edit_rows = _state.get("_edit_rows")
    if corr is None or edit_rows is None or edit_rows.empty or not n:
        _log("Нечего применять")
        return
    sub_idx = corr.index[corr["N"].astype(str).str.strip().str.upper() == n].tolist()
    if len(sub_idx) != len(edit_rows):
        # rebuild by Temp match
        for i, row in edit_rows.iterrows():
            t = float(row["Temp"])
            ftag = f"toc_edit_f_{i}"
            rtag = f"toc_edit_r_{i}"
            if not dpg.does_item_exist(ftag):
                continue
            fv = dpg.get_value(ftag)
            rv = dpg.get_value(rtag)
            mask = (
                (corr["N"].astype(str).str.strip().str.upper() == n)
                & ((corr["Temp"].astype(float) - t).abs() < 0.05)
            )
            if mask.any():
                if "F" in corr.columns:
                    corr.loc[mask, "F"] = float(fv)
                if "R" in corr.columns:
                    corr.loc[mask, "R"] = float(rv)
                if "F_method" in corr.columns:
                    corr.loc[mask, "F_method"] = "operator_edit"
                if "R_method" in corr.columns:
                    corr.loc[mask, "R_method"] = "operator_edit"
    else:
        for k, idx in enumerate(sub_idx):
            ftag = f"toc_edit_f_{k}"
            rtag = f"toc_edit_r_{k}"
            if dpg.does_item_exist(ftag) and "F" in corr.columns:
                corr.at[idx, "F"] = float(dpg.get_value(ftag))
            if dpg.does_item_exist(rtag) and "R" in corr.columns:
                corr.at[idx, "R"] = float(dpg.get_value(rtag))
            if "F_method" in corr.columns:
                corr.at[idx, "F_method"] = "operator_edit"
            if "R_method" in corr.columns:
                corr.at[idx, "R_method"] = "operator_edit"
    _state["corrected_temps"] = corr
    _refresh_plot()
    _refresh_big_if_open()
    base = _state.get("base_mid")
    if base:
        c = corr.copy()
        c["Measure_ID"] = base
        _refresh_summary(base, temps_override=c)
    _log("Правки оператора применены")


def _on_add_to_training(sender=None, app_data=None, user_data=None):
    # apply edits first
    _on_apply_edits()
    corr = _state.get("corrected_temps")
    n = (_state.get("current_number") or "").strip().upper()
    if corr is None or corr.empty or not n:
        _log("Нет данных для обучения")
        return
    sub = corr[corr["N"].astype(str).str.strip().str.upper() == n].sort_values("Temp")
    for param in ("F", "R"):
        if param not in sub.columns:
            continue
        points = []
        for _, row in sub.iterrows():
            if pd.isna(row.get("Temp")) or pd.isna(row.get(param)):
                continue
            points.append({
                "temp": float(row["Temp"]),
                "value": float(row[param]),
            })
        if points:
            cnt = toc_learning.add_training_sample(n, points, param=param, label="corrected")
            _log(f"В обучение: N={n} {param}, всего образцов {cnt}")
            if dpg.does_item_exist("toc_samples_count"):
                dpg.set_value("toc_samples_count", f"  образцов: {toc_learning.samples_count()}")


def _on_retrain(sender=None, app_data=None, user_data=None):
    _show_progress("Дообучение модели")
    _apply_progress_ui(10, "Обучение...")
    try:
        res = toc_learning.retrain_models()
        _log(f"Дообучение: {res}")
    except Exception as e:
        _log(f"Ошибка дообучения: {e}")
        traceback.print_exc()
    finally:
        _force_hide_progress()



def _on_recalc_metrics(sender=None, app_data=None, user_data=None):
    base = _state.get("base_mid")
    if not base:
        _log("Net bazovogo Measure_ID")
        return
    temps = _state.get("_temps_for_summary")
    if temps is None or (isinstance(temps, pd.DataFrame) and temps.empty):
        temps = (
            _state["corrected_temps"]
            if not _state["corrected_temps"].empty
            else _state["temps_df"]
        )
    spec = _resolve_spec_params()
    _show_progress("Пересчёт метрик")
    _apply_progress_ui(30, "Считаем...")
    try:
        _refresh_summary(base, temps_override=temps, spec=spec)
        _apply_progress_ui(100, "Готово")
    finally:
        _force_hide_progress()
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
            meta = _state["selected_meta"].get(mid, {})
            msk = meta.get("MSK") or ""
            label = f"MID {mid}" + (f" ({msk})" if msk else "")
            curves[label] = sub
    corr = _state.get("corrected_temps")
    if corr is not None and not corr.empty:
        csub = corr[corr["N"].astype(str).str.strip().str.upper() == n]
        if not csub.empty:
            curves["corrected"] = csub
    return curves


def _apply_only_corrected(val: bool) -> None:
    """Rezhim 'Только corrected': skryt' vse krivye, krome skorrektirovannoj."""
    _state["only_corrected"] = bool(val)
    # sinhroniziruem obochezekboksy (osnovnoe okno + okno uvelicheniya)
    big_tag = getattr(toc_graph, "ONLY_CORR_CHECK_BIG", "toc_only_corr_check_big")
    for tag in (ONLY_CORR_CHECK, big_tag):
        if dpg.does_item_exist(tag):
            try:
                dpg.set_value(tag, bool(val))
            except Exception:
                pass
    _refresh_plot()
    _refresh_big_if_open()


def _on_only_corr_change(sender=None, app_data=None, user_data=None):
    _apply_only_corrected(bool(dpg.get_value(ONLY_CORR_CHECK)))


def _on_only_corr_change_big(sender=None, app_data=None, user_data=None):
    big_tag = getattr(toc_graph, "ONLY_CORR_CHECK_BIG", "toc_only_corr_check_big")
    val = bool(dpg.get_value(big_tag)) if dpg.does_item_exist(big_tag) else False
    _apply_only_corrected(val)


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
        height=400,
        title=f"N {_state.get('current_number') or ''}",
        only_corrected=bool(_state.get("only_corrected")),
    )


def _on_param_change(sender=None, app_data=None, user_data=None):
    _refresh_plot()


def _on_number_change(sender=None, app_data=None, user_data=None):
    n = dpg.get_value(NUMBER_COMBO) if dpg.does_item_exist(NUMBER_COMBO) else ""
    _state["current_number"] = (n or "").strip().upper()
    _refresh_plot()
    _refresh_big_if_open()


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
    _refresh_big_if_open()


def _on_wheel(sender, app_data, user_data=None):
    """Smena nomera kolesom. Rabotaet i na osnovnoj paneli, i v okne uvelicheniya."""
    try:
        delta = int(app_data)
    except Exception:
        delta = 0
    if delta == 0:
        return
    # zashchita ot dvojnogo sdviga: big-handler i main-handler
    # esli big okno navedeno - obrabatyvaet tol'ko big (cherez user_data flag)
    from .constants import BIG_WIN_TAG
    if user_data == "from_big":
        _shift_number(-1 if delta > 0 else 1)
        return
    if dpg.does_item_exist(BIG_WIN_TAG):
        try:
            if dpg.is_item_hovered(BIG_WIN_TAG):
                return  # big handler srabotaet
            for tag in ("toc_big_plot_area", "toc_plot_big", "toc_big_edit_area"):
                if dpg.does_item_exist(tag) and dpg.is_item_hovered(tag):
                    return
        except Exception:
            pass
    _shift_number(-1 if delta > 0 else 1)


def _on_enlarge(sender=None, app_data=None, user_data=None):
    curves = _curves_for_current()
    toc_graph.open_enlarged_graph(
        curves,
        _state.get("param") or "F",
        _state.get("current_number") or "",
        on_wheel=_on_wheel,
        on_prev=lambda: _shift_number(-1),
        on_next=lambda: _shift_number(1),
        edit_builder=_build_edit_table,
        only_corrected=bool(_state.get("only_corrected")),
        on_only_corrected=_on_only_corr_change_big,
    )


def _refresh_summary(
    measure_id: int,
    temps_override: Optional[pd.DataFrame] = None,
    spec: Optional[Dict[str, Any]] = None,
):
    temps = temps_override if temps_override is not None else _state["temps_df"]
    psi = _state["psi_df"]
    if spec is None:
        spec = _state.get("spec_params") or None
    summary = toc_metrics.build_summary_table(psi, temps, measure_id, spec=spec)
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
        height=-1,
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
    if not base:
        _log("Net base MID")
        return
    if not msk:
        meta = _state["selected_meta"].get(base, {})
        msk = str(meta.get("MSK") or "TOC")
    if corr_temps is None or corr_temps.empty:
        _log("Net skorrektirovannyh temperatur - snachala Analiz")
        return

    psi = _state["psi_df"]
    psi_base = psi[psi["Measure_ID"] == base].copy()
    if psi_base.empty:
        _log("Net strok psidata dlya base MID")
        return

    temps_for_metrics = corr_temps.copy()
    temps_for_metrics["Measure_ID"] = base
    psi_upd = toc_metrics.apply_metrics_to_psidata(
        psi_base, temps_for_metrics, base, spec=_state.get("spec_params") or None
    )

    try:
        new_mid = toc_data.save_corrected_measure(
            psi_upd,
            corr_temps,
            msk=msk,
            source_mids=_state["selected_mids"],
            login="toc",
        )
        _log(f"Sohraneno kak Measure_ID={new_mid}")
    except Exception as e:
        _log(f"Oshibka sohraneniya: {e}")
        traceback.print_exc()


def _register_for_window_manager():
    try:
        from window_manager import register, rebuild_menu
        register(WIN_TAG, "Коррекция выбросов ТЧХ", create_temp_outlier_window)
        try:
            rebuild_menu()
        except Exception:
            pass
    except Exception as e:
        print(f"[TOC] window_manager: {e}", flush=True)


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

    # Size from screen (like Archive / PhaseNoise)
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
        label="Коррекция выбросов ТЧХ",
        tag=WIN_TAG,
        width=w,
        height=h,
        pos=(x, y),
        on_close=lambda: None,
    ):
        with dpg.group(horizontal=True):
            with dpg.child_window(tag=LEFT_PANEL, width=360, height=-1, border=True):
                dpg.add_text("Источник данных")
                dpg.add_combo(
                    [s[0] for s in SOURCES],
                    default_value=SOURCES[0][0],
                    width=-1,
                    callback=_on_source_change,
                )
                dpg.add_separator()
                dpg.add_text("Каскад (как в Архиве)")
                dpg.add_text("Тип резонатора")
                dpg.add_combo([], tag=TYPE_COMBO, width=-1, callback=_on_type_changed)
                dpg.add_text("Спецификация")
                dpg.add_combo([], tag=SPC_COMBO, width=-1, callback=_on_spc_changed)
                dpg.add_text("МСК")
                dpg.add_combo([], tag=MSK_COMBO, width=-1, callback=_on_msk_changed)
                dpg.add_text("Дата")
                dpg.add_combo([], tag=DATE_COMBO, width=-1, callback=_on_date_changed)
                dpg.add_text("Файл")
                dpg.add_combo([], tag=FILE_COMBO, width=-1, callback=_refresh_available_mids)

                dpg.add_separator()
                dpg.add_text("Поиск МСК по части (любое имя)")
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag=MSK_INPUT, width=200, hint="часть номера")
                    dpg.add_button(label="Найти", callback=_on_msk_search, width=70)

                dpg.add_text("Поиск Measure_ID / МСК / File")
                with dpg.group(horizontal=True):
                    dpg.add_input_text(tag=MID_SEARCH, width=200, hint="ID или часть")
                    dpg.add_button(label="Найти", callback=_on_mid_search, width=70)

                dpg.add_separator()
                dpg.add_text("Доступные Measure_ID")
                dpg.add_listbox([], tag=MID_LIST, num_items=7, width=-1)
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Добавить", callback=_on_add_selected, width=100)
                    dpg.add_button(label="Все", callback=_on_add_all, width=60)
                dpg.add_text("Выбранные (разные МСК допустимы)")
                dpg.add_listbox([], tag=SELECTED_LIST, num_items=6, width=-1)
                with dpg.group(horizontal=True):
                    dpg.add_button(label="Убрать", callback=_on_remove_selected, width=100)
                    dpg.add_button(label="Очистить", callback=_on_clear_selected, width=80)

                dpg.add_separator()
                dpg.add_button(label="Настройки NN", callback=lambda: toc_settings.open_settings_window(), width=-1)
                dpg.add_checkbox(
                    label="Сохранять сырые+обработанные+методы в файл",
                    tag=SAVE_DEBUG_CHECK,
                    default_value=False,
                )
                dpg.add_button(label="1. Загрузить данные", callback=_on_load, width=-1)
                dpg.add_button(label="2. Анализ и коррекция", callback=_on_analyze, width=-1)
                dpg.add_button(label="3. Пересчёт метрик", callback=_on_recalc_metrics, width=-1)
                dpg.add_button(
                    label="4. Сохранить скорректированный замер",
                    callback=_on_save,
                    width=-1,
                )
                dpg.add_separator()
                dpg.add_text("-", tag=STATUS_TAG, wrap=340)

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
                    dpg.add_button(label="<", callback=lambda: _shift_number(-1), width=28)
                    dpg.add_button(label=">", callback=lambda: _shift_number(1), width=28)
                    dpg.add_button(label="Увеличить график", callback=_on_enlarge, width=140)
                    dpg.add_checkbox(
                        label="Только corrected",
                        tag=ONLY_CORR_CHECK,
                        default_value=False,
                        callback=_on_only_corr_change,
                    )

                dpg.add_text(
                    "Колесо мыши - смена номера. Желтая кривая - corrected. "
                    "Правки точек - в окне «Увеличить график».",
                    color=(140, 180, 220),
                )
                with dpg.group(horizontal=True):
                    dpg.add_button(
                        label="Добавить в обучение",
                        callback=_on_add_to_training,
                        width=160,
                    )
                    dpg.add_button(
                        label="Дообучить модель",
                        callback=_on_retrain,
                        width=140,
                    )
                    dpg.add_text(
                        f"  образцов: {toc_learning.samples_count()}",
                        tag="toc_samples_count",
                    )

                # grafik: fiksir. vysota dostatochnaya, bez obrezki
                with dpg.child_window(tag=PLOT_CONTAINER, height=420, border=False):
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

    _register_for_window_manager()
    _cascade_bootstrap()
    _log("Okno gotovo. Vyberite zamery (v t.ch. s raznymi MSK).")
