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
from queue import Queue, Empty
from typing import Any, Dict, List, Optional

import dearpygui.dearpygui as dpg
import pandas as pd

from . import data as toc_data
from . import graph as toc_graph
from . import logic as toc_logic
from . import metrics as toc_metrics
from . import settings as toc_settings
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
        _progress_q.put(("done", 100.0, "Gotovo"))
    except Exception:
        pass


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
                _apply_progress_ui(0, f"Oshibka: {msg}")
                _log(f"Oshibka analiza: {msg}")
                try:
                    if dpg.does_item_exist(PROGRESS_WIN):
                        dpg.delete_item(PROGRESS_WIN)
                except Exception:
                    pass
                _worker_busy = False
            elif kind == "done":
                _apply_progress_ui(100, msg or "Gotovo")
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
    try:
        if dpg.does_item_exist(PROGRESS_WIN):
            dpg.delete_item(PROGRESS_WIN)
    except Exception:
        pass
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
    temps_view = _state["temps_df"].copy()
    if not corrected.empty:
        # pokazat corrected kak otdelnuyu seriyu; ne podmenyat raw mid
        pass
    _state["_temps_for_summary"] = corrected if not corrected.empty else temps_view
    _refresh_plot()
    # metriki po corrected: vremенно prostaem Measure_ID base
    if not corrected.empty and base_mid is not None:
        corr_for_sum = corrected.copy()
        corr_for_sum["Measure_ID"] = base_mid
        # nuzhny stroki psi dlya base
        _refresh_summary(base_mid, temps_override=corr_for_sum)
    n_corr = report.get("n_corrections", 0)
    _log(f"Gotovo: pravok {n_corr}, base MID={base_mid}")



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
    _show_progress("Пересчёт метрик")
    _update_progress(30, "Schitaem...")
    try:
        _refresh_summary(base, temps_override=temps)
        _update_progress(100, "Gotovo")
    finally:
        _hide_progress()
    _log("Metriki pereschitany")


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
    psi_upd = toc_metrics.apply_metrics_to_psidata(psi_base, temps_for_metrics, base)

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

                dpg.add_text(
                    "Колесо мыши - смена номера. Желтая кривая - corrected.",
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

    _register_for_window_manager()
    _cascade_bootstrap()
    _log("Okno gotovo. Vyberite zamery (v t.ch. s raznymi MSK).")
