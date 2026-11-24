"""Вспомогательные функции: безопасные конвертеры, ОТК-нормы, фильтр «Только годные»."""
import pandas as pd
from sqlalchemy import create_engine

import Options
from .Archive_Data import (
    load_spc_map_for_archive, load_specification,
    build_archive_status_df,
)


def _safe_float(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() == 'no':
            return None
        try:
            return float(s.replace(',', '.'))
        except (ValueError, TypeError):
            return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_int(v, default=None):
    if v is None:
        return default
    try:
        if pd.isna(v):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def _safe_str(v) -> str:
    if v is None:
        return ''
    try:
        if pd.isna(v):
            return ''
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    if s.lower() in ('none', 'nan', ''):
        return ''
    return s


def _filter_good_only(df: pd.DataFrame, fallback_spc: str = '') -> pd.DataFrame:
    """Оставить только «Годен» по актуальной спецификации.
    psidata.Status2 НЕ используется — статус вычисляется заново.
    """
    if df is None or df.empty:
        return df

    spc_col = 'Spc' if 'Spc' in df.columns else None

    if spc_col is None:
        spc_name = fallback_spc or ''
        if not spc_name:
            print("[Archive] only_good: нет Spc — фильтр пропущен")
            return df
        spc_map = load_spc_map_for_archive(spc_name)
        if spc_map.empty:
            print(f"[Archive] only_good: нет норм для Spc={spc_name!r}")
            return df
        status_df = build_archive_status_df(df, spc_map)
        return df[status_df['Status'].values].reset_index(drop=True)

    parts = []
    for spc_name, group in df.groupby(spc_col, dropna=False):
        sn = spc_name if spc_name else fallback_spc
        spc_map = load_spc_map_for_archive(sn) if sn else pd.DataFrame()
        if spc_map.empty:
            print(f"[Archive] only_good: нет норм для Spc={sn!r}, "
                  f"группа отброшена ({len(group)} строк)")
            continue
        status_df = build_archive_status_df(group, spc_map)
        good_mask = status_df['Status'].values
        if not good_mask.any():
            continue
        parts.append(group[good_mask].reset_index(drop=True))

    if not parts:
        return df.iloc[0:0].copy()
    return pd.concat(parts, ignore_index=True)


def load_spc_map_otk_for_archive(spc_name: str) -> pd.DataFrame:
    """Нормы ОТК (с техзапасом). Полная логика — см. комментарий в источнике."""
    spc_map = load_spc_map_for_archive(spc_name)
    if spc_map is None or spc_map.empty:
        return spc_map if spc_map is not None else pd.DataFrame()

    engine = create_engine(str(Options.get_connection_string()))
    try:
        dopusk_map = pd.read_sql(
            "SELECT * FROM spc_dopusk_map_table ORDER BY ID", engine)
    except Exception as e:
        print(f"[Archive] spc_dopusk_map_table недоступна: {e}")
        spc_map['Max_otk'] = spc_map['Max']
        spc_map['Min_otk'] = spc_map['Min']
        return spc_map

    spc_df = load_specification(spc_name)
    if spc_df.empty:
        spc_map['Max_otk'] = spc_map['Max']
        spc_map['Min_otk'] = spc_map['Min']
        return spc_map
    row = spc_df.iloc[0]

    result = []
    for _, r in spc_map.iterrows():
        d = dict(r)
        param = d['Parameter']
        mx = d['Max']
        mn = d['Min']

        dm = dopusk_map[dopusk_map['Parameter'] == param]
        if not dm.empty:
            units_col = dm.iloc[0].get('Dopusk_units')
            pct_col   = dm.iloc[0].get('Dopusk_%')
            units = _safe_float(row.get(units_col)) if units_col else None
            pct   = _safe_float(row.get(pct_col))   if pct_col   else None

            has_mx = mx is not None and not pd.isna(mx)
            has_mn = mn is not None and not pd.isna(mn)

            if units is not None and units > 0:
                if has_mx:
                    mx = float(mx) - float(units)
                if has_mn:
                    mn = float(mn) + float(units)
            elif pct is not None and pct > 0:
                if has_mx:
                    mx = float(mx) - abs(float(mx)) * float(pct) / 100.0
                if has_mn:
                    mn = float(mn) + abs(float(mn)) * float(pct) / 100.0

        d['Max_otk'] = mx
        d['Min_otk'] = mn
        result.append(d)

    return pd.DataFrame(result)

import dearpygui.dearpygui as dpg   # ← в шапку файла


# ===========================================================================
# Тип протокола: ПСИ (нормы без техзапаса) / ОТК (нормы с техзапасом)
# ===========================================================================
def _current_psi_type() -> str:
    """Текущий выбранный тип протокола в комбо 'Тип протокола'."""
    if dpg.does_item_exist('archive_psi_type_combo'):
        v = dpg.get_value('archive_psi_type_combo')
        if v in ('ПСИ', 'ОТК'):
            return v
    return 'ОТК'


def _load_spc_map_for_display(spc_name: str, psi_type: str) -> pd.DataFrame:
    """Карта норм для отображения / печати / экспорта.

    Для ОТК колонки Max_otk / Min_otk копируются в Max / Min,
    чтобы build_archive_status_df, _fill_norms и _fill_table
    работали единообразно и считали «Брак» по тем же нормам,
    которые уйдут в PDF / Excel.
    """
    if not spc_name:
        return pd.DataFrame()

    if psi_type == 'ОТК':
        spc_map = load_spc_map_otk_for_archive(spc_name)
        if not spc_map.empty:
            spc_map = spc_map.copy()
            if 'Max_otk' in spc_map.columns:
                spc_map['Max'] = spc_map['Max_otk']
            if 'Min_otk' in spc_map.columns:
                spc_map['Min'] = spc_map['Min_otk']
        return spc_map

    return load_spc_map_for_archive(spc_name)

# ---------------------------------------------------------------------------
# Tmax / Tmin: значения вне рабочего диапазона не показываем
# ---------------------------------------------------------------------------
_TMAX_TMIN_PARAMS = frozenset({
    'Tmax', 'Tmin',           # имена в psidata / алиасы
    'extr_1', 'extr_2',       # Parameter в spc_map_table (Note_mini: «Tmax, C» / «Tmin, C»)
})
_TMAX_TMIN_LO = -60.0
_TMAX_TMIN_HI = 150.0


def sanitize_tmax_tmin_value(val, param_name=None):
    """Для Tmax/Tmin (psidata) и extr_1/extr_2 (spc_map Parameter):
    если значение вне [-60, +150] — пустая строка.

    На экране (Note_mini «Tmax, C» / «Tmin, C») и в протоколе вместо
    «мусорных» экстремумов — пустое место. Остальные параметры без изменений.
    """
    if param_name is not None and param_name not in _TMAX_TMIN_PARAMS:
        return val
    if val is None:
        return ''
    try:
        if pd.isna(val):
            return ''
    except (TypeError, ValueError):
        pass
    try:
        f = float(val)
    except (TypeError, ValueError):
        # Нечисловое — тоже не показываем для Tmax/Tmin
        if param_name in _TMAX_TMIN_PARAMS or param_name is None:
            return ''
        return val
    if f < _TMAX_TMIN_LO or f > _TMAX_TMIN_HI:
        return ''
    return val


def sanitize_tmax_tmin_columns(df: pd.DataFrame,
                               param_cols=('Tmax', 'Tmin', 'extr_1', 'extr_2')) -> pd.DataFrame:
    """Обнуляет Tmax/Tmin/extr_1/extr_2 вне [-60, 150] в DataFrame (на копии)."""
    if df is None or df.empty:
        return df
    out = df
    for col in param_cols:
        if col not in out.columns:
            continue
        def _cell(v, _col=col):
            return sanitize_tmax_tmin_value(v, _col)
        out = out.copy()
        out[col] = out[col].map(_cell)
    return out
