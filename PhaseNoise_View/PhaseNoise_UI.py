"""UI ФШ: каскад как в Архиве, график справа, спецификация под графиком."""

import io
import logging
import os
import tempfile

import dearpygui.dearpygui as dpg
import pandas as pd
import matplotlib.pyplot as plt

from .PhaseNoise_Constants import (
    GRAPH_CONTAINER, GRAPH_IMAGE_TAG, TABLE_CONTAINER,
    STATUS_TEXT_TAG, ALL_MSK_LABEL, ALL_MEAS_LABEL, WINDOW_TAG,
    NORMS_GROUP, STATS_GROUP, INFO_PANEL_TAG,
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
from .PhaseNoise_Graph import build_graph
from .PhaseNoise_Export import export_to_pdf
from .PhaseNoise_Lookup import (
    sync_lookup_table, check_lookup_actual, ensure_lookup_table,
)

log = logging.getLogger("PhaseNoise.UI")

_suppress_cascade = False


# ===================================================================
# 1. Фильтр-бар — callbacks сразу при создании (как в Archive)
# ===================================================================
def build_filter_bar():
    with dpg.group(horizontal=True):
        with dpg.group(width=180):
            dpg.add_text("Тип резонатора")
            dpg.add_combo([], tag="pn_type", width=180,
                          callback=_on_type_change)
        with dpg.group(width=220):
            dpg.add_text("Спецификация")
            dpg.add_combo([], tag="pn_spc", width=220,
                          callback=_on_spc_change)
        with dpg.group(width=180):
            dpg.add_text("МСК")
            dpg.add_combo([ALL_MSK_LABEL], tag="pn_msk", width=180,
                          callback=_on_msk_change)
        with dpg.group(width=140):
            dpg.add_text("MeasureID")
            dpg.add_combo([ALL_MEAS_LABEL], tag="pn_mid", width=140,
                          callback=_on_mid_change)
        with dpg.group(width=160):
            dpg.add_text("Номер")
            dpg.add_combo([], tag="pn_number", width=160,
                          callback=_on_number_change)

    with dpg.group(horizontal=True):
        with dpg.group(width=320):
            dpg.add_text("Поиск МСК по части номера")
            dpg.add_input_text(
                tag="pn_msk_search", width=320,
                hint="456  |  25-2456", on_enter=True,
                callback=lambda s, a: _on_msk_search())
        with dpg.group(width=120):
            dpg.add_spacer(height=18)
            dpg.add_button(label="Найти МСК", width=120,
                           callback=lambda s, a: _on_msk_search())
        with dpg.group(width=120):
            dpg.add_spacer(height=18)
            dpg.add_button(label="Очистить МСК", width=120,
                           callback=_on_clear_msk_search)

    with dpg.group(horizontal=True):
        with dpg.group(width=360):
            dpg.add_text("Номера (одиночный / список / диапазон)")
            dpg.add_input_text(
                tag="pn_numbers_input", width=360,
                hint="JN4450  |  JN4450,JN4451  |  JN4450-JN4460",
                on_enter=True,
                callback=lambda s, a: _on_load())
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
    """Правая панель: график, спецификация, статистика, действия."""
    dpg.add_text("График PN(Freq)", color=(180, 220, 255))
    with dpg.child_window(height=280, tag=GRAPH_CONTAINER, border=True):
        dpg.add_text("(график появится после <Загрузить>)",
                     color=(120, 120, 120))

    dpg.add_separator()
    dpg.add_text("Спецификация ФШ", color=(180, 220, 255))
    with dpg.group(tag=NORMS_GROUP):
        dpg.add_text("- спецификация не выбрана -",
                     tag="pn_norms_hint", color=(140, 140, 140))

    dpg.add_separator()
    dpg.add_text("Статистика по отстройкам", color=(180, 220, 255))
    with dpg.child_window(height=160, tag=STATS_GROUP, border=True):
        dpg.add_text("- загрузите данные -", color=(140, 140, 140))

    dpg.add_separator()
    dpg.add_text("Действия", color=(180, 220, 255))
    dpg.add_button(label="Протокол PDF", width=-1, height=26,
                   callback=lambda: _on_pdf("protocol"))
    dpg.add_button(label="Экспорт (протокол+графики)", width=-1, height=26,
                   callback=lambda: _on_pdf("both"))
    dpg.add_button(label="Только графики PDF", width=-1, height=26,
                   callback=lambda: _on_pdf("graphs"))
    dpg.add_spacer(height=4)
    dpg.add_button(label="Синхронизировать справочник", width=-1, height=26,
                   callback=_on_sync_lookup)
    dpg.add_button(label="Закрыть", width=-1, height=26, callback=_on_close)


def init_cascade():
    """Заполнение каскада при открытии + синхронизация lookup."""
    global _suppress_cascade

    # --- справочник ---
    try:
        ensure_lookup_table()
        st = check_lookup_actual()
        log.info(f"lookup status: {st}")
        if st.get("needs_full_rebuild") or st.get("needs_incremental"):
            mode = "full" if st.get("needs_full_rebuild") else "incremental"
            log.info(f"lookup sync starting ({mode})...")
            if dpg.does_item_exist(STATUS_TEXT_TAG):
                dpg.set_value(STATUS_TEXT_TAG, f"Синхронизация справочника ({mode})...")
            res = sync_lookup_table(full_rebuild=bool(st.get("needs_full_rebuild")))
            msg = (f"Справочник: {res.get('mode')} +{res.get('inserted')} "
                   f"(всего {res.get('total')})")
            log.info(msg)
            if dpg.does_item_exist(STATUS_TEXT_TAG):
                dpg.set_value(STATUS_TEXT_TAG, msg)
        else:
            if dpg.does_item_exist(STATUS_TEXT_TAG):
                dpg.set_value(
                    STATUS_TEXT_TAG,
                    f"Справочник актуален ({st.get('lookup_count', 0)} строк)")
    except Exception as e:
        log.exception(f"lookup bootstrap error: {e}")
        if dpg.does_item_exist(STATUS_TEXT_TAG):
            dpg.set_value(STATUS_TEXT_TAG, f"Ошибка справочника: {e}")

    # --- каскад ---
    types = get_resonator_types()
    log.info(f"init_cascade types: {types[:10] if types else types}")
    dpg.configure_item("pn_type", items=types)
    if types:
        _suppress_cascade = True
        try:
            dpg.set_value("pn_type", types[0])
        finally:
            _suppress_cascade = False
        _on_type_change()
    else:
        log.warning("init_cascade: типы резонаторов пусты — каскад неактивен")
        if dpg.does_item_exist(STATUS_TEXT_TAG):
            dpg.set_value(STATUS_TEXT_TAG,
                          "Нет типов резонаторов (specification.NameR пуст)")


# ===================================================================
# 2. Callbacks каскада
# ===================================================================
def _on_type_change(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    try:
        t = dpg.get_value("pn_type") or ""
        log.info(f"on_type_change: {t!r}")
        spcs = get_spc_by_type(t) if t else []
        log.info(f"  spcs: {len(spcs)}")
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
        log.info(f"on_spc_change: {s!r}")
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
        log.info(f"  msks={len(msks)} mids={len(mids)}")
        msk_list = [ALL_MSK_LABEL] + msks
        mid_list = [ALL_MEAS_LABEL] + [str(i) for i in mids]
        dpg.configure_item("pn_msk", items=msk_list)
        dpg.set_value("pn_msk", ALL_MSK_LABEL)
        dpg.configure_item("pn_mid", items=mid_list)
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
        log.info(f"on_msk_change: {msk!r}")
        dpg.set_value("pn_mid", ALL_MEAS_LABEL)
        if msk and msk != ALL_MSK_LABEL:
            mids = get_measure_ids_by_msk(msk)
            mid_list = [ALL_MEAS_LABEL] + [str(i) for i in mids]
            dpg.configure_item("pn_mid", items=mid_list)
            dpg.set_value("pn_mid", ALL_MEAS_LABEL)
        _refresh_numbers()
    except Exception as e:
        log.exception(f"on_msk_change error: {e}")


def _on_mid_change(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    log.info(f"on_mid_change: {dpg.get_value('pn_mid')!r}")
    _refresh_numbers()


def _on_number_change(sender=None, app_data=None, user_data=None):
    if _suppress_cascade:
        return
    n = dpg.get_value("pn_number") or ""
    log.info(f"on_number_change: {n!r}")
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
        log.info(f"refresh_numbers: spc={s!r} msk={msk_val!r} "
                 f"mid={mid!r} -> {len(nums)}")
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
    log.info(f"msk search '{q}': {len(found)} hits")
    if not found:
        dpg.set_value(STATUS_TEXT_TAG, f"МСК по '{q}' не найдены")
        return
    items = [ALL_MSK_LABEL] + found
    dpg.configure_item("pn_msk", items=items)
    dpg.set_value("pn_msk", found[0])
    _on_msk_change()
    dpg.set_value(STATUS_TEXT_TAG, f"Найдено МСК: {len(found)}")


def _on_clear_msk_search(*_):
    dpg.set_value("pn_msk_search", "")
    _on_spc_change()


# ===================================================================
# 3. Нормы / статистика
# ===================================================================
def _fill_norms(spc: str | None):
    dpg.delete_item(NORMS_GROUP, children_only=True)
    if not spc:
        dpg.add_text("- спецификация не выбрана -",
                     parent=NORMS_GROUP, color=(140, 140, 140))
        return
    spec = load_specification(spc)
    norms = build_norms(spec)
    if not norms:
        dpg.add_text(f"{spc}: нет активных норм ФШ",
                     parent=NORMS_GROUP, color=(180, 140, 80))
        return
    dpg.add_text(f"Spc: {spc}", parent=NORMS_GROUP, color=(150, 200, 255))
    for nm in norms:
        off = nm["offset"]
        vmin = nm["min"]
        vmax = nm["max"]
        vmin_s = f"{vmin:g}" if vmin is not None else "—"
        vmax_s = f"{vmax:g}" if vmax is not None else "—"
        line = (f"Норма {nm['num']}: отстройка {off} Гц  "
                f"min={vmin_s}  max={vmax_s} дБ/Гц")
        dpg.add_text(line, parent=NORMS_GROUP)


def _fill_stats(measurements: pd.DataFrame, norms: list[dict]):
    dpg.delete_item(STATS_GROUP, children_only=True)
    if measurements is None or measurements.empty or not norms:
        dpg.add_text("- нет данных -", parent=STATS_GROUP, color=(140, 140, 140))
        return

    oy = overall_yield(measurements, norms)
    pct = oy["pct_good"]
    pct_s = f"{pct:.1f}%" if pct is not None else "—"
    header = (f"Выборка: {oy['n_total']} | Годных: {oy['n_good']} "
              f"({pct_s}) | Брак: {oy['n_fail']}")
    dpg.add_text(header, parent=STATS_GROUP, color=(150, 220, 150))

    stats = build_offset_stats(measurements, norms)
    if not stats:
        dpg.add_text("Нет активных норм", parent=STATS_GROUP)
        return

    with dpg.table(parent=STATS_GROUP, header_row=True, resizable=True,
                   policy=dpg.mvTable_SizingStretchProp,
                   scrollY=True, height=-1):
        for col in ("Отстр.", "n", "mean", "σ", "min", "max", "med",
                    "% годн.", "Cpk"):
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
                dpg.add_text(f"{pct:.1f}" if pct is not None else "—")
                dpg.add_text(_fmt_num(st["cpk"]))


def _on_sync_lookup(*_):
    try:
        dpg.set_value(STATUS_TEXT_TAG, "Синхронизация справочника...")
        try:
            dpg.split_frame()
        except Exception:
            pass
        st = check_lookup_actual()
        full = bool(st.get("needs_full_rebuild"))
        res = sync_lookup_table(full_rebuild=full)
        dpg.set_value(
            STATUS_TEXT_TAG,
            f"Справочник: mode={res.get('mode')} +{res.get('inserted')} "
            f"(всего {res.get('total')})")
    except Exception as e:
        log.exception(f"sync lookup: {e}")
        dpg.set_value(STATUS_TEXT_TAG, f"Ошибка синхронизации: {e}")


# ===================================================================
# 4. Загрузка
# ===================================================================
def _on_load(*_):
    try:
        s = dpg.get_value("pn_spc") or ""
        msk = dpg.get_value("pn_msk") or ""
        mid_raw = dpg.get_value("pn_mid") or ""
        n = dpg.get_value("pn_number") or ""
        numbers_raw = dpg.get_value("pn_numbers_input") or ""
        numbers = parse_numbers_input(numbers_raw)

        log.info(f"on_load: spc={s!r} msk={msk!r} mid={mid_raw!r} "
                 f"n={n!r} numbers={numbers}")

        msk_val = msk if msk and msk != ALL_MSK_LABEL else None
        mid = int(mid_raw) if str(mid_raw).isdigit() else None

        if numbers:
            meas = load_phaze_noise(numbers=numbers)
        elif mid or msk_val or n:
            meas = load_phaze_noise(msk_val, mid, n or None)
        else:
            dpg.set_value(STATUS_TEXT_TAG,
                          "Выберите МСК / MeasureID / Номер или введите номера")
            return

        log.info(f"on_load: meas rows = {len(meas)}")
        if meas.empty:
            dpg.set_value(STATUS_TEXT_TAG, "Нет данных по фильтру")
            _render_table(pd.DataFrame())
            _fill_stats(pd.DataFrame(), [])
            return

        spec_row = load_specification(s) or {}
        norms = build_norms(spec_row)
        _fill_norms(s)

        if dpg.get_value("pn_only_good") and norms:
            good_ids = [
                row["ID"] for _, row in meas.iterrows()
                if all(p["status"] != "Брак"
                       for p in collect_norm_points(row.to_dict(), norms))
            ]
            meas = meas[meas["ID"].isin(good_ids)]
            log.info(f"on_load: only_good -> {len(meas)}")
            if meas.empty:
                dpg.set_value(STATUS_TEXT_TAG, "Годных нет")
                _render_table(pd.DataFrame())
                _fill_stats(pd.DataFrame(), [])
                return

        summary = build_summary_table(meas, norms)
        _render_table(summary)
        _fill_stats(meas, norms)

        mids = [int(x) for x in meas["MeasureID"].dropna().unique().tolist()]
        points = load_phaze_noise_data(measure_ids=mids)
        log.info(f"on_load: points rows = {len(points)} for {len(mids)} mid")
        if points.empty:
            dpg.set_value(STATUS_TEXT_TAG,
                          f"Загружено {len(meas)} изм., точки графиков отсутствуют")
            return

        operators = {
            int(m["ID"]): get_operator_fname(m.get("Operator") or "")
            for _, m in meas.iterrows()
        }
        fig = build_graph(
            points, meas, norms, operators,
            group_mode=dpg.get_value("pn_group_mode") or "msk")
        _render_graph(fig)
        plt.close(fig)

        dpg.set_value(
            STATUS_TEXT_TAG,
            f"Загружено {len(meas)} изм. ({len(points)} точек, "
            f"{len(mids)} MeasureID)")
    except Exception as e:
        log.exception(f"on_load error: {e}")
        dpg.set_value(STATUS_TEXT_TAG, f"Ошибка: {e}")


# ===================================================================
# 5. Отрисовка
# ===================================================================
def _render_table(df: pd.DataFrame):
    dpg.delete_item(TABLE_CONTAINER, children_only=True)
    if df.empty:
        dpg.add_text("Нет данных", parent=TABLE_CONTAINER)
        return
    headers = list(df.columns)
    with dpg.table(parent=TABLE_CONTAINER, header_row=True, resizable=True,
                   policy=dpg.mvTable_SizingStretchProp,
                   scrollY=True, height=-1):
        for h in headers:
            dpg.add_table_column(label=str(h))
        for _, row in df.iterrows():
            with dpg.table_row():
                for h in headers:
                    v = row[h]
                    dpg.add_text("-" if pd.isna(v) else str(v))


def _render_graph(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, bbox_inches="tight")
    buf.seek(0)
    png = buf.read()
    buf.close()

    if dpg.does_item_exist("pn_graph_texture"):
        dpg.delete_item("pn_graph_texture")
    if dpg.does_item_exist(GRAPH_IMAGE_TAG):
        dpg.delete_item(GRAPH_IMAGE_TAG)

    dpg.delete_item(GRAPH_CONTAINER, children_only=True)

    try:
        from PIL import Image
        import numpy as np
        img = Image.open(io.BytesIO(png)).convert("RGBA")
        w, h = img.size
        arr = (np.asarray(img, dtype=np.float32) / 255.0).flatten().tolist()
        with dpg.texture_registry(show=False):
            dpg.add_static_texture(w, h, arr, tag="pn_graph_texture")
        log.info(f"Graph texture (PIL): {w}x{h}")
    except ImportError:
        log.warning("PIL недоступен — фолбэк на dpg.load_image")
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        tmp.write(png)
        tmp.close()
        try:
            w, h, _c, data = dpg.load_image(tmp.name)
            with dpg.texture_registry(show=False):
                dpg.add_static_texture(w, h, data, tag="pn_graph_texture")
            log.info(f"Graph texture (dpg): {w}x{h}")
        finally:
            os.unlink(tmp.name)

    dpg.add_image("pn_graph_texture", parent=GRAPH_CONTAINER,
                  tag=GRAPH_IMAGE_TAG)


# ===================================================================
# 6. PDF / закрытие
# ===================================================================
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
        else:
            meas = load_phaze_noise(msk_val, mid, n or None)
        if meas.empty:
            dpg.set_value(STATUS_TEXT_TAG, "Нечего экспортировать")
            return
        export_to_pdf(
            meas, s,
            norms=build_norms(load_specification(s)),
            mode=mode, group_mode=dpg.get_value("pn_group_mode") or "msk",
            filepath=f"phase_noise_{mode}.pdf")
        dpg.set_value(STATUS_TEXT_TAG,
                      f"PDF сохранён: phase_noise_{mode}.pdf")
        log.info(f"PDF exported: phase_noise_{mode}.pdf")
    except Exception as e:
        log.exception(f"PDF error: {e}")
        dpg.set_value(STATUS_TEXT_TAG, f"PDF ошибка: {e}")


def _on_close(*_):
    log.info("close window")
    if dpg.does_item_exist(WINDOW_TAG):
        dpg.configure_item(WINDOW_TAG, show=False)
