"""Универсальный справочник (МСК / MeasureID / Номер резонатора)."""

import logging
import dearpygui.dearpygui as dpg
from .PhaseNoise_Data import (
    load_msk_lookup, load_resonator_lookup, load_measure_id_lookup,
)

log = logging.getLogger("PhaseNoise.Lookup")


def _s(v) -> str:
    if v is None:
        return ""
    try:
        import pandas as pd
        if pd.isna(v):
            return ""
    except Exception:
        pass
    return str(v)


class LookupDialog:
    """Один универсальный диалог выбора. Открывается поверх, без modal=True."""

    def __init__(self, *, title: str, tag_prefix: str,
                 query_fn, format_fn, on_select,
                 width: int = 1000, height: int = 600):
        self.title       = title
        self.tag_win     = f"{tag_prefix}_win"
        self.tag_search  = f"{tag_prefix}_search"
        self.tag_list    = f"{tag_prefix}_list"
        self.query_fn    = query_fn
        self.format_fn   = format_fn
        self.on_select   = on_select
        self.width       = width
        self.height      = height
        log.info(f"LookupDialog init: {title}")
        self._build()
        self._reload()

    # --------------------------------------------------------------
    def _build(self):
        if dpg.does_item_exist(self.tag_win):
            dpg.delete_item(self.tag_win)
        with dpg.window(label=self.title, tag=self.tag_win,
                        width=self.width, height=self.height,
                        pos=(80, 80)):
            dpg.add_text("Фильтр (МСК / N / Spc / ID):")
            dpg.add_input_text(tag=self.tag_search, width=-1,
                               callback=self._on_search)
            dpg.add_listbox([], tag=self.tag_list,
                            width=-1, height=-80, num_items=25)
            with dpg.group(horizontal=True):
                dpg.add_button(label="Выбрать", callback=self._on_pick,
                               width=110)
                dpg.add_button(label="Обновить", callback=self._on_search,
                               width=110)
                dpg.add_button(label="Отмена", callback=self._on_cancel,
                               width=110)

    # --------------------------------------------------------------
    def _on_search(self, *args):
        self._reload()

    def _reload(self):
        q = (dpg.get_value(self.tag_search) or "").strip()
        log.info(f"Lookup reload: query={q!r}")
        try:
            df = self.query_fn(q)
        except Exception as e:
            log.exception(f"Lookup query error: {e}")
            df = None
        if df is None or df.empty:
            log.warning(f"Lookup {self.title}: пустой результат")
            items = ["(нет данных)"]
        else:
            items = [self.format_fn(r) for _, r in df.iterrows()]
            log.info(f"Lookup {self.title}: {len(items)} строк")
        dpg.configure_item(self.tag_list, items=items,
                           default_value=items[0])

    # --------------------------------------------------------------
    def _on_pick(self, *args):
        sel = dpg.get_value(self.tag_list)
        log.info(f"Lookup pick: {sel!r}")
        if not sel or sel == "(нет данных)":
            return
        try:
            self.on_select(sel)
        except Exception as e:
            log.exception(f"on_select error: {e}")
        try:
            dpg.delete_item(self.tag_win)
        except Exception:
            pass

    def _on_cancel(self, *args):
        log.info(f"Lookup cancel: {self.title}")
        try:
            dpg.delete_item(self.tag_win)
        except Exception:
            pass


# ======================================================================
# Обёртки
# ======================================================================
def open_msk_lookup(on_select):
    def fmt(r):
        return (f"{_s(r.get('MSK'))} | N={_s(r.get('N_list'))} | "
                f"Spc={_s(r.get('Spc_list'))} | "
                f"{_s(r.get('last_date'))} | cnt={_s(r.get('cnt'))}")
    def cb(sel):
        msk = sel.split(" | ")[0].strip()
        on_select(msk)
    LookupDialog(title="Справочник МСК", tag_prefix="pn_lookup_msk",
                 query_fn=load_msk_lookup, format_fn=fmt, on_select=cb)


def open_measure_id_lookup(on_select):
    def fmt(r):
        return (f"{_s(r.get('MeasureID'))} | MSK={_s(r.get('MSK_list'))} | "
                f"N={_s(r.get('N_list'))} | "
                f"Spc={_s(r.get('Spc_list'))} | "
                f"{_s(r.get('last_date'))} | cnt={_s(r.get('cnt'))}")
    def cb(sel):
        mid = sel.split(" | ")[0].strip()
        on_select(int(mid))
    LookupDialog(title="Справочник MeasureID", tag_prefix="pn_lookup_mid",
                 query_fn=load_measure_id_lookup, format_fn=fmt, on_select=cb)


def open_resonator_lookup(on_select):
    def fmt(r):
        return (f"{_s(r.get('N'))} | MSK={_s(r.get('MSK_list'))} | "
                f"{_s(r.get('last_date'))} | cnt={_s(r.get('cnt'))}")
    def cb(sel):
        n = sel.split(" | ")[0].strip()
        on_select(n)
    LookupDialog(title="Справочник номеров резонаторов",
                 tag_prefix="pn_lookup_n",
                 query_fn=load_resonator_lookup,
                 format_fn=fmt, on_select=cb)