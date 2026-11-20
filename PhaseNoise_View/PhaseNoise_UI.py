"""UI ФШ: каскад как в Архиве, график справа, спецификация под графиком."""

import logging
import threading

import dearpygui.dearpygui as dpg
import pandas as pd

from .PhaseNoise_Constants import (
    GRAPH_CONTAINER, TABLE_CONTAINER,
    STATUS_TEXT_TAG, ALL_MSK_LABEL, ALL_MEAS_LABEL, WINDOW_TAG,
    NORMS_GROUP, STATS_GROUP, INFO_PANEL_TAG,
    LOOKUP_STATUS_TAG, LOOKUP_SYNC_STATE,
)
from .PhaseNoise_Data import (
    get_resonator_types, get_spc_by_type, get_msk_by_spc,
    get_measure_ids_by_spc, get_measure_ids_by_msk, get_numbers,
    load_phaze_noise, load_phaze_noise_data, load_specification,
    build_norms, get_operator_fname, search_msk_partial, parse_numbers_input,
)
from .PhaseNoise_Helpers import (
    build_summary_table, collect_norm_points,
    build_offset_stats, overall_yield, _fmt_num,
)
from .PhaseNoise_Graph import render_graph, list_series_from_points
from . import PhaseNoise_SeriesUI as series_ui
from .PhaseNoise_Export import export_to_pdf
from .PhaseNoise_Lookup import sync_lookup_table, check_lookup_actual


log = logging.getLogger("PhaseNoise.UI")

_suppress_cascade = False


def _lookup_status_str(st: dict) -> str:
    last_sync = st.get("last_sync")
    ls = last_sync.strftime("%Y-%m-%d %H:%M") if last_sync else "никогда"
    if st.get("is_empty"):
        return f"пуст (нужна полная пересборка, синхр.: {ls})"
    if st.get("is_actual"):
        return f"актуален, {st.get('lookup_count', 0):,} записей, синхр.: {ls}"
    return (
        f"нужна досинхр.: новых строк {st.get('new_phaze_rows', 0)}, "
        f"всего {st.get('lookup_count', 0):,}, синхр.: {ls}"
    )


def _poll_sync_state(poll_cb):
    if LOOKUP_SYNC_STATE.get("done"):
        poll_cb()
        return
    dpg.set_frame_callback(dpg.get_frame_count() + 10,
                           lambda: _poll_sync_state(poll_cb))


def build_filter_bar():
    with dpg.group(horizontal=True):
        with dpg.group(width=180):
            dpg.add_text("Тип резонатора")
            dpg.add_combo([], tag="pn_type", width=180, callback=_on_type_change)
        with dpg.group(width=220):
            dpg.add_text("Спецификация")
            dpg.add_combo([], tag="pn_spc", width=220, callback=_on_spc_change)
        with dpg.group(width=180):
            dpg.add_text("МСК")
            dpg.add_combo([ALL_MSK_LABEL], tag="pn_msk", width=180, callback=_on_msk_change)
        with dpg.group(width=140):
            dpg.add_text("MeasureID")
            dpg.add_combo([ALL_MEAS_LABEL], tag="pn_mid", width=140, callback=_on_mid_change)
        with dpg.group(width=160):
            dpg.add_text("Номер")
            dpg.add_combo([], tag="pn_number", width=160, callback=_on_number_change)

    with dpg.group(horizontal=True):
        with dpg.group(width=320):
            dpg.add_text("Поиск МСК по части номера")
            dpg.add_input_text(tag="pn_msk_search", width=320,
                hint="456  |  25-2456", on_enter=True,
                callback=lambda s, a: _on_msk_search())
        with dpg.group(width=120):
            dpg.add_spacer(height=18)
            dpg.add_button(label="Найти МСК", width=120,
                           callback=lambda s, a: _on_msk_search())
        with dpg.group(width=120):
            dpg.add_spacer(height=18)
            dpg.add_button(label="Очистить МСК", width=120, callback=_on_clear_msk_search)

    with dpg.group(horizontal=True):
        with dpg.group(width=360):
            dpg.add_text("Номера (одиночный / список / диапазон)")
            dpg.add_input_text(tag="pn_numbers_input", width=360,
                hint="JN4450  |  JN4450,JN4451  |  JN4450-JN4460",
                on_enter=True, callback=lambda s, a: _on_load())
        with dpg.group(width=120):
            dpg.add_spacer(height=18)
            dpg.add_checkbox(label="Только годные", tag="pn_only_good")
        with dpg.group(width=140):
            dpg.add_spacer(height=18)
            dpg.add_combo(["msk", "resonator_single", "resonator_multi"],
                          default_value="msk", tag="pn_group_mode", width=140)
        with dpg.group(width=110):
            dpg.add_spacer(height=18)
            dpg.add_button(label="Загрузить", width=110, callback=_on_load)
    dpg.add_separator()


def build_info_panel():
    dpg.add_text("График PN(Freq)", color=(180, 220, 255))
    with dpg.child_window(height=340, tag=GRAPH_CONTAINER, border=True):
        dpg.add_text("(график появится после <Загрузить>)", color=(120, 120, 120))
    dpg.add_separator()
    dpg.add_text("Спецификация ФШ", color=(180, 220, 255))
    with dpg.group(tag=NORMS_GROUP):
        dpg.add_text("- спецификация не выбрана -", tag="pn_norms_hint", color=(140, 140, 140))
    dpg.add_separator()
    dpg.add_text("Статистика по отстройкам", color=(180, 220, 255))
    with dpg.child_window(height=160, tag=STATS_GROUP, border=True):
        dpg.add_text("- загрузите данные -", color=(140, 140, 140))
    dpg.add_separator()
    dpg.add_text("Действия", color=(180, 220, 255))
    dpg.add_button(label="Протокол PDF", width=-1, height=26, callback=lambda s, a: _on_pdf("protocol"))
    dpg.add_button(label="Экспорт (протокол+графики)", width=-1, height=26, callback=lambda s, a: _on_pdf("both"))
    dpg.add_button(label="Только графики PDF", width=-1, height=26, callback=lambda s, a: _on_pdf("graphs"))
    dpg.add_separator()
    dpg.add_text("Справочник номеров", color=(180, 220, 255))
    dpg.add_text("не проверен", tag=LOOKUP_STATUS_TAG, color=(150, 200, 255), wrap=400)
    dpg.add_button(label="Проверить", width=-1, height=26, callback=lambda s, a: _on_lookup_check())
    dpg.add_button(label="Досинхронизировать", width=-1, height=26, callback=lambda s, a: _on_lookup_sync(False))
    dpg.add_button(label="Полная пересборка", width=-1, height=26, callback=lambda s, a: _on_lookup_sync(True))
    dpg.add_spacer(height=4)
    dpg.add_button(label="Закрыть", width=-1, height=26, callback=_on_close)


def init_cascade():
    global _suppress_cascade
    log.info("init_cascade start")
    try:
        types = get_resonator_types()
        if not dpg.does_item_exist("pn_type"):
            return
        dpg.configure_item("pn_type", items=types)
        if types:
            _suppress_cascade = True
            try:
                dpg.set_value("pn_type", types[0])
            finally:
                _suppress_cascade = False
            _on_type_change()
    except Exception as e:
        log.exception(f"cascade fill error: {e}")
    dpg.set_frame_callback(dpg.get_frame_count() + 15, _on_lookup_check)
    try:
        series_ui.ensure_wheel_handler()
    except Exception:
        pass


def _on_type_change(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    try:
        t = dpg.get_value("pn_type") or ""
        spcs = get_spc_by_type(t) if t else []
        dpg.configure_item("pn_spc", items=spcs)
        dpg.set_value("pn_spc", spcs[0] if spcs else "")
        _on_spc_change()
    except Exception as e:
        log.exception(f"on_type_change error: {e}")


def _on_spc_change(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    try:
        s = dpg.get_value("pn_spc") or ""
        if not s:
            dpg.configure_item("pn_msk", items=[ALL_MSK_LABEL])
            dpg.set_value("pn_msk", ALL_MSK_LABEL)
            dpg.configure_item("pn_mid", items=[ALL_MEAS_LABEL])
            dpg.set_value("pn_mid", ALL_MEAS_LABEL)
            dpg.configure_item("pn_number", items=[])
            dpg.set_value("pn_number", "")
            _fill_norms(None)
            return
        msks = get_msk_by_spc(s)
        mids = get_measure_ids_by_spc(s)
        dpg.configure_item("pn_msk", items=[ALL_MSK_LABEL] + msks)
        dpg.set_value("pn_msk", ALL_MSK_LABEL)
        dpg.configure_item("pn_mid", items=[ALL_MEAS_LABEL] + [str(i) for i in mids])
        dpg.set_value("pn_mid", ALL_MEAS_LABEL)
        _refresh_numbers()
        _fill_norms(s)
    except Exception as e:
        log.exception(f"on_spc_change error: {e}")


def _on_msk_change(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    try:
        msk = dpg.get_value("pn_msk") or ""
        dpg.set_value("pn_mid", ALL_MEAS_LABEL)
        if msk and msk != ALL_MSK_LABEL:
            mids = get_measure_ids_by_msk(msk)
            dpg.configure_item("pn_mid", items=[ALL_MEAS_LABEL] + [str(i) for i in mids])
            dpg.set_value("pn_mid", ALL_MEAS_LABEL)
        _refresh_numbers()
    except Exception as e:
        log.exception(f"on_msk_change error: {e}")


def _on_mid_change(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    _refresh_numbers()


def _on_number_change(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    if series_ui.is_number_cb_suppressed():
        return
    n = dpg.get_value("pn_number") or ""
    if series_ui.get_numbers():
        if n:
            series_ui.set_current_number(n, update_combo=False)
        return
    if n:
        _on_load()


def _refresh_numbers():
    try:
        s = dpg.get_value("pn_spc") or ""
        msk = dpg.get_value("pn_msk") or ""
        mid_raw = dpg.get_value("pn_mid") or ""
        mid = int(mid_raw) if str(mid_raw).isdigit() else None
        msk_val = msk if msk and msk != ALL_MSK_LABEL else None
        nums = get_numbers(msk_val, mid, s or None)
        dpg.configure_item("pn_number", items=nums)
        dpg.set_value("pn_number", nums[0] if nums else "")
    except Exception as e:
        log.exception(f"refresh_numbers error: {e}")


def _on_msk_search(*_):
    q = (dpg.get_value("pn_msk_search") or "").strip()
    spc = dpg.get_value("pn_spc") or None
    if not q:
        dpg.set_value(STATUS_TEXT_TAG, "Введите часть МСК для поиска")
        return
    found = search_msk_partial(q, spc=spc)
    if not found:
        dpg.set_value(STATUS_TEXT_TAG, f"МСК по '{q}' не найдены")
        return
    dpg.configure_item("pn_msk", items=[ALL_MSK_LABEL] + found)
    dpg.set_value("pn_msk", found[0])
    _on_msk_change()
    dpg.set_value(STATUS_TEXT_TAG, f"Найдено МСК: {len(found)}")


def _on_clear_msk_search(*_):
    dpg.set_value("pn_msk_search", "")
    _on_spc_change()


def _fill_norms(spc: str | None):
    dpg.delete_item(NORMS_GROUP, children_only=True)
    if not spc:
        dpg.add_text("- спецификация не выбрана -", parent=NORMS_GROUP, color=(140, 140, 140))
        return
    spec = load_specification(spc)
    norms = build_norms(spec)
    if not norms:
        dpg.add_text(f"{spc}: нет активных норм ФШ", parent=NORMS_GROUP, color=(180, 140, 80))
        return
    dpg.add_text(f"Spc: {spc}", parent=NORMS_GROUP, color=(150, 200, 255))
    for nm in norms:
        vmin, vmax = nm["min"], nm["max"]
        vmin_s = f"{vmin:g}" if vmin is not None else "-"
        vmax_s = f"{vmax:g}" if vmax is not None else "-"
        dpg.add_text(
            f"Норма {nm['num']}: отстройка {nm['offset']} Гц  min={vmin_s}  max={vmax_s} дБ/Гц",
            parent=NORMS_GROUP)


def _fill_stats(measurements: pd.DataFrame, norms: list[dict]):
    dpg.delete_item(STATS_GROUP, children_only=True)
    if measurements is None or measurements.empty or not norms:
        dpg.add_text("- нет данных -", parent=STATS_GROUP, color=(140, 140, 140))
        return
    oy = overall_yield(measurements, norms)
    pct = oy["pct_good"]
    pct_s = f"{pct:.1f}%" if pct is not None else "-"
    dpg.add_text(
        f"Выборка: {oy['n_total']} | Годных: {oy['n_good']} ({pct_s}) | Брак: {oy['n_fail']}",
        parent=STATS_GROUP, color=(150, 220, 150))
    stats = build_offset_stats(measurements, norms)
    if not stats:
        return
    with dpg.table(parent=STATS_GROUP, header_row=True, resizable=True,
                   policy=dpg.mvTable_SizingStretchProp, scrollY=True, height=-1):
        for col in ("Отстр.", "n", "mean", "std", "min", "max", "med", "% годн.", "Cpk"):
            dpg.add_table_column(label=col)
        for st in stats:
            with dpg.table_row():
                dpg.add_text(st["offset_label"])
                dpg.add_text(str(st["n"]))
                dpg.add_text(_fmt_num(st["mean"]))
                dpg.add_text(_fmt_num(st["std"]))
                dpg.add_text(_fmt_num(st["min"]))
                dpg.add_text(_fmt_num(st["max"]))
                dpg.add_text(_fmt_num(st["median"]))
                pct = st["pct_good"]
                dpg.add_text(f"{pct:.1f}" if pct is not None else "-")
                dpg.add_text(_fmt_num(st["cpk"]))


def _on_lookup_check(*_):
    if LOOKUP_SYNC_STATE.get("running"):
        return
    LOOKUP_SYNC_STATE.update({"running": True, "done": False, "message": "Проверка...", "error": None})
    if dpg.does_item_exist(LOOKUP_STATUS_TAG):
        dpg.set_value(LOOKUP_STATUS_TAG, "Проверка...")

    def _worker():
        try:
            st = check_lookup_actual()
            LOOKUP_SYNC_STATE["message"] = _lookup_status_str(st)
        except Exception as e:
            log.exception(f"lookup check error: {e}")
            LOOKUP_SYNC_STATE["error"] = str(e)
        finally:
            LOOKUP_SYNC_STATE["done"] = True
            LOOKUP_SYNC_STATE["running"] = False

    threading.Thread(target=_worker, daemon=True).start()

    def _finish():
        msg = LOOKUP_SYNC_STATE.get("message", "")
        if LOOKUP_SYNC_STATE.get("error"):
            msg = f"Ошибка проверки: {LOOKUP_SYNC_STATE['error']}"
        if dpg.does_item_exist(LOOKUP_STATUS_TAG):
            dpg.set_value(LOOKUP_STATUS_TAG, msg)

    _poll_sync_state(_finish)


def _on_lookup_sync(full_rebuild: bool):
    if LOOKUP_SYNC_STATE.get("running"):
        return
    mode = "full" if full_rebuild else "incremental"
    LOOKUP_SYNC_STATE.update({"running": True, "done": False,
        "message": f"Синхронизация ({mode})...", "error": None})
    if dpg.does_item_exist(LOOKUP_STATUS_TAG):
        dpg.set_value(LOOKUP_STATUS_TAG, f"Синхронизация ({mode})...")

    def _worker():
        try:
            res = sync_lookup_table(full_rebuild=full_rebuild)
            LOOKUP_SYNC_STATE["message"] = (
                f"Готово ({res.get('mode')}): +{res.get('inserted')}, всего {res.get('total')}"
            )
        except Exception as e:
            log.exception(f"lookup sync error: {e}")
            LOOKUP_SYNC_STATE["error"] = str(e)
        finally:
            LOOKUP_SYNC_STATE["done"] = True
            LOOKUP_SYNC_STATE["running"] = False

    threading.Thread(target=_worker, daemon=True).start()

    def _finish():
        msg = (f"Ошибка синхронизации: {LOOKUP_SYNC_STATE['error']}"
               if LOOKUP_SYNC_STATE.get("error")
               else LOOKUP_SYNC_STATE.get("message", "Готово"))
        if dpg.does_item_exist(LOOKUP_STATUS_TAG):
            dpg.set_value(LOOKUP_STATUS_TAG, msg)
        if dpg.does_item_exist(STATUS_TEXT_TAG):
            dpg.set_value(STATUS_TEXT_TAG, msg)
        try:
            _on_type_change()
        except Exception:
            pass

    _poll_sync_state(_finish)


def _on_load(*_):
    try:
        s = dpg.get_value("pn_spc") or ""
        msk = dpg.get_value("pn_msk") or ""
        mid_raw = dpg.get_value("pn_mid") or ""
        n = dpg.get_value("pn_number") or ""
        numbers = parse_numbers_input(dpg.get_value("pn_numbers_input") or "")

        msk_val = msk if msk and msk != ALL_MSK_LABEL else None
        mid = int(mid_raw) if str(mid_raw).isdigit() else None

        if numbers:
            meas = load_phaze_noise(numbers=numbers)
        elif mid:
            meas = load_phaze_noise(None, mid, None)
        elif msk_val:
            meas = load_phaze_noise(msk_val, None, None)
        elif n:
            meas = load_phaze_noise(None, None, n)
        else:
            dpg.set_value(STATUS_TEXT_TAG,
                          "Выберите МСК / MeasureID / Номер или введите номера")
            return

        if meas.empty:
            dpg.set_value(STATUS_TEXT_TAG, "Данные не найдены")
            series_ui.render_series_table(pd.DataFrame(), [])
            _fill_stats(pd.DataFrame(), [])
            return

        spec_row = load_specification(s) if s else None
        norms = build_norms(spec_row)
        _fill_norms(s)

        if dpg.get_value("pn_only_good") and norms:
            good_ids = [
                row["ID"] for _, row in meas.iterrows()
                if all(p["status"] != "Брак"
                       for p in collect_norm_points(row.to_dict(), norms))
            ]
            meas = meas[meas["ID"].isin(good_ids)]
            if meas.empty:
                dpg.set_value(STATUS_TEXT_TAG, "Годных нет")
                series_ui.render_series_table(pd.DataFrame(), [])
                _fill_stats(pd.DataFrame(), [])
                return

        _fill_stats(meas, norms)

        pairs = []
        for _, m in meas.iterrows():
            mid_v = m.get("MeasureID")
            n_v = m.get("N")
            if mid_v is None or (isinstance(mid_v, float) and pd.isna(mid_v)):
                continue
            try:
                pairs.append((int(mid_v), str(n_v or "").strip()))
            except (TypeError, ValueError):
                continue
        pairs = list(dict.fromkeys(pairs))
        mids = sorted({p[0] for p in pairs})

        points = load_phaze_noise_data(pairs=pairs) if pairs else pd.DataFrame()
        if points.empty and mids:
            points = load_phaze_noise_data(measure_ids=mids)

        log.info(f"on_load: points={len(points)} mids={len(mids)} pairs={len(pairs)}")

        operators = {}
        for _, m in meas.iterrows():
            if "ID" not in m or pd.isna(m.get("ID")):
                continue
            try:
                operators[int(m["ID"])] = get_operator_fname(m.get("Operator") or "")
            except (TypeError, ValueError):
                pass

        series = list_series_from_points(points) if not points.empty else list(pairs)

        prefer = (n or "").strip()
        series_ui.store_load(points, meas, norms, operators, series,
                             current_number=prefer or None)
        cur = series_ui.get_current_number()
        nums = series_ui.get_numbers()
        if nums and dpg.does_item_exist("pn_number"):
            dpg.configure_item("pn_number", items=nums)
            if cur:
                series_ui.set_current_number(cur, update_combo=True)

        series_ui.render_series_table(meas, series)
        series_ui.ensure_wheel_handler()
        if not points.empty:
            series_ui.redraw_graph()

        dpg.set_value(
            STATUS_TEXT_TAG,
            f"Загружено {len(meas)} изм. - {len(points)} точек - "
            f"{len(series)} кривых - график N {series_ui.get_current_number() or '-'} "
            f"(колесо мыши - смена номера)"
            + ("" if not points.empty else " (точек нет)")
        )
    except Exception as e:
        log.exception(f"on_load error: {e}")
        dpg.set_value(STATUS_TEXT_TAG, f"Ошибка: {e}")


def _on_pdf(mode: str, *_):
    try:
        s = dpg.get_value("pn_spc") or ""
        msk = dpg.get_value("pn_msk") or ""
        mid_raw = dpg.get_value("pn_mid") or ""
        n = dpg.get_value("pn_number") or ""
        numbers = parse_numbers_input(dpg.get_value("pn_numbers_input") or "")
        msk_val = msk if msk and msk != ALL_MSK_LABEL else None
        mid = int(mid_raw) if str(mid_raw).isdigit() else None
        if numbers:
            meas = load_phaze_noise(numbers=numbers)
        elif mid:
            meas = load_phaze_noise(None, mid, None)
        elif msk_val:
            meas = load_phaze_noise(msk_val, None, None)
        else:
            meas = load_phaze_noise(None, None, n or None)
        if meas.empty:
            dpg.set_value(STATUS_TEXT_TAG, "Нечего экспортировать")
            return
        export_to_pdf(
            meas, s,
            norms=build_norms(load_specification(s)),
            mode=mode, group_mode=dpg.get_value("pn_group_mode") or "msk",
            filepath=f"phase_noise_{mode}.pdf")
        dpg.set_value(STATUS_TEXT_TAG, f"PDF сохранён: phase_noise_{mode}.pdf")
    except Exception as e:
        log.exception(f"PDF error: {e}")
        dpg.set_value(STATUS_TEXT_TAG, f"PDF ошибка: {e}")


def _on_close(*_):
    if dpg.does_item_exist(WINDOW_TAG):
        try:
            dpg.delete_item(WINDOW_TAG)
        except Exception:
            try:
                dpg.configure_item(WINDOW_TAG, show=False)
            except Exception:
                pass
