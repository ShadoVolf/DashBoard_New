"""UI с каскадом, логом и защитой от преждевременных callback-ов."""

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
)
from .PhaseNoise_Data import (
    get_resonator_types, get_spc_by_type, get_msk_by_spc,
    get_measure_ids_by_spc, get_numbers,
    load_phaze_noise, load_phaze_noise_data, load_specification,
    build_norms, get_operator_fname,
)
from .PhaseNoise_Helpers import build_summary_table, collect_norm_points
from .PhaseNoise_Graph import build_graph, fig_to_png_bytes
from .PhaseNoise_Export import export_to_pdf
from .PhaseNoise_Lookup import (
    open_msk_lookup, open_measure_id_lookup, open_resonator_lookup,
)

log = logging.getLogger("PhaseNoise.UI")


# ===================================================================
# 1. Построение формы
# ===================================================================
def build_selection_bar():
    types = get_resonator_types()
    with dpg.group(horizontal=True):
        dpg.add_text("Тип резонатора:")
        dpg.add_combo(types, tag="pn_type", width=150)
        dpg.add_text("  Спецификация:")
        dpg.add_combo([], tag="pn_spc", width=220)
    with dpg.group(horizontal=True):
        dpg.add_text("МСК:")
        dpg.add_combo([ALL_MSK_LABEL], tag="pn_msk", width=200)
        dpg.add_text("  MeasureID:")
        dpg.add_combo([ALL_MEAS_LABEL], tag="pn_mid", width=140)
        dpg.add_text("  Номер:")
        dpg.add_combo([], tag="pn_number", width=160)


def build_load_bar():
    with dpg.group(horizontal=True):
        dpg.add_button(label="Загрузить", width=120, callback=_on_load)
        dpg.add_checkbox(label="Только годные", tag="pn_only_good")
        dpg.add_checkbox(label="Полноразмерная печать", tag="pn_full_print")
        dpg.add_text("  Группировка графиков:")
        dpg.add_combo(["msk", "resonator_single", "resonator_multi"],
                      default_value="msk", tag="pn_group_mode", width=170)


def build_bottom_bar():
    with dpg.group(horizontal=True):
        dpg.add_button(label="Справочник МСК", width=150,
                       callback=_open_msk_lookup)
        dpg.add_button(label="Справочник MeasureID", width=170,
                       callback=_open_mid_lookup)
        dpg.add_button(label="Справочник номеров", width=160,
                       callback=_open_res_lookup)
        dpg.add_spacer(width=15)
        dpg.add_button(label="Протокол", width=100,
                       callback=lambda: _on_pdf("protocol"))
        dpg.add_button(label="Экспорт", width=100,
                       callback=lambda: _on_pdf("both"))
        dpg.add_button(label="Печать всех", width=110,
                       callback=_on_print_all)
        dpg.add_button(label="Печать данных", width=110,
                       callback=lambda: _on_pdf("graphs"))
        dpg.add_button(label="Закрыть", width=90, callback=_on_close)


def wire_callbacks():
    """Callbacks подключаем ПОСЛЕ того, как все комбо созданы."""
    dpg.configure_item("pn_type",   callback=_on_type_change)
    dpg.configure_item("pn_spc",    callback=_on_spc_change)
    dpg.configure_item("pn_msk",    callback=_on_msk_change)
    dpg.configure_item("pn_mid",    callback=_on_mid_change)
    dpg.configure_item("pn_number", callback=_on_number_change)


def init_cascade():
    """Явно дёргаем каскад, чтобы он заполнил зависимые комбо при старте."""
    t = dpg.get_value("pn_type")
    log.info(f"init_cascade: type={t!r}")
    if t:
        _on_type_change()
    else:
        log.warning("init_cascade: тип не выбран — каскад пропущен")


# ===================================================================
# 2. Callbacks каскада
# ===================================================================
def _on_type_change(*_):
    try:
        t = dpg.get_value("pn_type") or ""
        log.info(f"on_type_change: {t!r}")
        spcs = get_spc_by_type(t) if t else []
        dpg.configure_item("pn_spc", items=spcs,
                           default_value=spcs[0] if spcs else "")
        _on_spc_change()
    except Exception as e:
        log.exception(f"on_type_change error: {e}")


def _on_spc_change(*_):
    try:
        s = dpg.get_value("pn_spc") or ""
        log.info(f"on_spc_change: {s!r}")
        if not s:
            dpg.configure_item("pn_msk", items=[ALL_MSK_LABEL],
                               default_value=ALL_MSK_LABEL)
            dpg.configure_item("pn_mid", items=[ALL_MEAS_LABEL],
                               default_value=ALL_MEAS_LABEL)
            dpg.configure_item("pn_number", items=[], default_value="")
            return
        msk_list = [ALL_MSK_LABEL] + get_msk_by_spc(s)
        mid_list = [ALL_MEAS_LABEL] + [str(i) for i in get_measure_ids_by_spc(s)]
        dpg.configure_item("pn_msk", items=msk_list,
                           default_value=ALL_MSK_LABEL)
        dpg.configure_item("pn_mid", items=mid_list,
                           default_value=ALL_MEAS_LABEL)
        _refresh_numbers()
    except Exception as e:
        log.exception(f"on_spc_change error: {e}")


def _on_msk_change(*_):
    log.info(f"on_msk_change: {dpg.get_value('pn_msk')!r}")
    _refresh_numbers()


def _on_mid_change(*_):
    log.info(f"on_mid_change: {dpg.get_value('pn_mid')!r}")
    _refresh_numbers()


def _on_number_change(*_):
    n = dpg.get_value("pn_number") or ""
    log.info(f"on_number_change: {n!r}")
    if n:
        _on_load()


def _refresh_numbers():
    try:
        s = dpg.get_value("pn_spc") or ""
        msk = dpg.get_value("pn_msk") or ""
        mid_raw = dpg.get_value("pn_mid") or ""
        mid = int(mid_raw) if mid_raw.isdigit() else None
        msk_val = msk if msk and msk != ALL_MSK_LABEL else None
        nums = get_numbers(msk_val, mid, s or None)
        log.info(f"refresh_numbers: spc={s!r} msk={msk_val!r} "
                 f"mid={mid!r} -> {len(nums)}")
        dpg.configure_item("pn_number", items=nums,
                           default_value=nums[0] if nums else "")
    except Exception as e:
        log.exception(f"refresh_numbers error: {e}")


# ===================================================================
# 3. Справочники
# ===================================================================
def _open_msk_lookup():
    log.info("open MSK lookup")
    def _pick(msk: str):
        log.info(f"MSK picked: {msk!r}")
        dpg.set_value("pn_msk", msk)
        dpg.set_value("pn_mid", ALL_MEAS_LABEL)
        _refresh_numbers()
    open_msk_lookup(_pick)


def _open_mid_lookup():
    log.info("open MeasureID lookup")
    def _pick(mid: int):
        log.info(f"MID picked: {mid!r}")
        dpg.set_value("pn_mid", str(mid))
        dpg.set_value("pn_msk", ALL_MSK_LABEL)
        _refresh_numbers()
    open_measure_id_lookup(_pick)


def _open_res_lookup():
    log.info("open Resonator lookup")
    def _pick(n: str):
        log.info(f"N picked: {n!r}")
        items = list(dpg.get_item_configuration("pn_number").get("items") or [])
        if n not in items:
            items.insert(0, n)
            dpg.configure_item("pn_number", items=items)
        dpg.set_value("pn_number", n)
        _on_load()
    open_resonator_lookup(_pick)


# ===================================================================
# 4. Загрузка
# ===================================================================
def _on_load(*_):
    try:
        s = dpg.get_value("pn_spc") or ""
        msk = dpg.get_value("pn_msk") or ""
        mid_raw = dpg.get_value("pn_mid") or ""
        n = dpg.get_value("pn_number") or ""
        log.info(f"on_load: spc={s!r} msk={msk!r} mid={mid_raw!r} n={n!r}")

        msk_val = msk if msk and msk != ALL_MSK_LABEL else None
        mid = int(mid_raw) if mid_raw.isdigit() else None
        if not (msk_val or mid or n):
            dpg.set_value(STATUS_TEXT_TAG,
                          "Выберите МСК / MeasureID / Номер")
            log.warning("on_load: пустой фильтр")
            return

        meas = load_phaze_noise(msk_val, mid, n or None)
        log.info(f"on_load: meas rows = {len(meas)}")
        if meas.empty:
            dpg.set_value(STATUS_TEXT_TAG, "Нет данных по фильтру")
            return

        spec_row = load_specification(s) or {}
        norms = build_norms(spec_row)

        if dpg.get_value("pn_only_good") and norms:
            good_ids = [row["ID"] for _, row in meas.iterrows()
                        if all(p["status"] != "Брак"
                               for p in collect_norm_points(row.to_dict(), norms))]
            meas = meas[meas["ID"].isin(good_ids)]
            log.info(f"on_load: only_good -> {len(meas)}")
            if meas.empty:
                dpg.set_value(STATUS_TEXT_TAG, "Годных нет")
                return

        summary = build_summary_table(meas, norms)
        _render_table(summary)

        points = load_phaze_noise_data(msk_val, mid, n or None)
        log.info(f"on_load: points rows = {len(points)}")
        if points.empty:
            dpg.set_value(STATUS_TEXT_TAG, "Точки графиков отсутствуют")
            return

        operators = {int(m["ID"]): get_operator_fname(m.get("Operator") or "")
                     for _, m in meas.iterrows()}
        fig = build_graph(points, meas, norms, operators,
                          group_mode=dpg.get_value("pn_group_mode") or "msk")
        _render_graph(fig)
        plt.close(fig)

        dpg.set_value(STATUS_TEXT_TAG,
                      f"Загружено {len(meas)} изм. ({len(points)} точек)")
    except Exception as e:
        log.exception(f"on_load error: {e}")
        dpg.set_value(STATUS_TEXT_TAG, f"Ошибка: {e}")


# ===================================================================
# 5. Отрисовка таблицы и графика
# ===================================================================
def _render_table(df: pd.DataFrame):
    dpg.delete_item(TABLE_CONTAINER, children_only=True)
    if df.empty:
        dpg.add_text("Нет данных", parent=TABLE_CONTAINER)
        return
    headers = list(df.columns)
    with dpg.table(parent=TABLE_CONTAINER, header_row=True, resizable=True,
                   policy=dpg.mvTable_SizingStretchProp,
                   scrollY=True, height=170):
        for h in headers:
            dpg.add_table_column(label=str(h))
        for _, row in df.iterrows():
            with dpg.table_row():
                for h in headers:
                    v = row[h]
                    dpg.add_text("-" if pd.isna(v) else str(v))


def _render_graph(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, bbox_inches="tight")
    buf.seek(0)
    png = buf.read()
    buf.close()

    if dpg.does_item_exist("pn_graph_texture"):
        dpg.delete_item("pn_graph_texture")
    if dpg.does_item_exist(GRAPH_IMAGE_TAG):
        dpg.delete_item(GRAPH_IMAGE_TAG)

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
        tmp.write(png); tmp.close()
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
# 6. Действия
# ===================================================================
def _on_pdf(mode: str, *_):
    try:
        s = dpg.get_value("pn_spc") or ""
        msk = dpg.get_value("pn_msk") or ""
        mid_raw = dpg.get_value("pn_mid") or ""
        n = dpg.get_value("pn_number") or ""
        msk_val = msk if msk and msk != ALL_MSK_LABEL else None
        mid = int(mid_raw) if mid_raw.isdigit() else None

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


def _on_print_all(*_):
    _on_pdf("both")


def _on_close(*_):
    log.info("close window")
    if dpg.does_item_exist(WINDOW_TAG):
        dpg.configure_item(WINDOW_TAG, show=False)