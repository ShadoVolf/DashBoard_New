"""
Пересчёт сводных метрик резонатора по температурной кривой.

Fmax, Fmin, Fptp, Fptp/2, Rmax, Rmin, Rptp,
Mono, Slope, Tmax, Tmin, Turnover.

Методика - как в Temperature_Measure/Make_Measure.py (calculate_metrics):
  - кривая фильтруется в диапазон спецификации [TCH_Temp_A; TCH_Temp_B];
  - аппроксимация полиномом степени polinom (из спецификации, по умолчанию 3);
  - Slope = производная полинома в точке Tnakl из спецификации
    ("наклон на температуре", ppm/°C); Tnakl == 0 -> Tnastr;
    fallback - хорда по крайним точкам отфильтрованной кривой (не 0.0);
  - Turnover = точка перегиба (корень 2-й производной полинома);
  - Mono = максимальное отклонение кривой от аппроксимации;
  - Tmax / Tmin = температуры первого и второго экстремума
    (как extr_1 / extr_2 в Make_Measure).
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

from .constants import OUTLIER_MARKER


def _clean_series(temps: np.ndarray, values: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    mask = np.isfinite(temps) & np.isfinite(values) & (values != OUTLIER_MARKER)
    t = temps[mask]
    v = values[mask]
    order = np.argsort(t)
    return t[order], v[order]


def _num(v) -> Optional[float]:
    if v is None:
        return None
    try:
        if isinstance(v, float) and (np.isnan(v) or np.isinf(v)):
            return None
        fv = float(str(v).strip().replace(",", "."))
    except (TypeError, ValueError):
        return None
    return fv if np.isfinite(fv) else None


def _normalize_spec(
    spec: Optional[Dict[str, Any]],
) -> Tuple[Optional[float], int, float, float]:
    """(t_nakl, degree, ta, tb) iz spec {t_nakl, t_nastr, degree, ta, tb}."""
    if not spec:
        return None, 3, -np.inf, np.inf
    t_nastr = _num(spec.get("t_nastr"))
    t_nakl = _num(spec.get("t_nakl"))
    if t_nakl is None or t_nakl == 0.0:
        # kak v Make_Measure.py: t_nakl == 0 -> t_nastr
        t_nakl = t_nastr
    deg = _num(spec.get("degree"))
    deg = int(deg) if (deg is not None and deg >= 1) else 3
    ta = _num(spec.get("ta"))
    tb = _num(spec.get("tb"))
    if (ta is None) != (tb is None):
        # odna iz granic intervala [TCH_Temp_A; TCH_Temp_B] ne zadana -
        # berem vse temperatury (kak Make_Measure.py)
        ta = None
        tb = None
    return (
        t_nakl,
        deg,
        ta if ta is not None else -np.inf,
        tb if tb is not None else np.inf,
    )


def _fit_poly(t: np.ndarray, f: np.ndarray, degree: int) -> Optional[np.ndarray]:
    n = t.size
    print("Metrics-SLope",t, "deg", degree)
    deg = min(int(degree), n - 1)
    if deg < 1 or n < deg + 1:
        return None
    try:
        with np.errstate(all="ignore"):
            coeffs = np.polyfit(t, f, deg)
    except Exception:
        return None
    if not np.all(np.isfinite(coeffs)):
        return None
    return coeffs


def _real_roots_in(coeffs: Optional[np.ndarray], tmin: float, tmax: float) -> np.ndarray:
    if coeffs is None or coeffs.size < 1:
        return np.array([])
    try:
        roots = np.roots(coeffs)
    except Exception:
        return np.array([])
    real = np.array([r.real for r in roots if abs(np.imag(r)) < 1e-8], dtype=float)
    if real.size == 0:
        return real
    return np.sort(real[(real >= tmin) & (real <= tmax)])


def _chord_slope(t: np.ndarray, f: np.ndarray) -> Optional[float]:
    if t.size < 2 or t[-1] == t[0]:
        return None
    return float((f[-1] - f[0]) / (t[-1] - t[0]))

def _at_data_edge(v, tf: np.ndarray, ta: float, tb: float, eps: float = 1e-6) -> bool:
    """True, если v совпадает с краем [ta; tb] или с краем фактических данных tf.

    Край интервала спецификации проверяем только если он конечен
    (при ta = -inf, tb = +inf проверка не применяется).
    Край фактических данных (первая/последняя отфильтрованная температура)
    считаем «не экстремумом» так же, как край интервала.
    """
    if v is None:
        return False
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return False
    if not np.isfinite(fv):
        return False

    # 1) край интервала спецификации (если задан)
    if np.isfinite(ta) and abs(fv - ta) <= eps:
        return True
    if np.isfinite(tb) and abs(fv - tb) <= eps:
        return True

    # 2) край фактических данных после фильтрации
    if tf is not None and tf.size >= 2:
        if abs(fv - tf.min()) <= eps or abs(fv - tf.max()) <= eps:
            return True

    return False

def compute_curve_metrics(
    temp_df: pd.DataFrame,
    f_col: str = "F",
    r_col: str = "R",
    mono_degree: int = 3,
    spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Сводные метрики по температурной кривой (как Make_Measure.calculate_metrics).

    Tmax / Tmin = None, если итоговое значение совпадает с краем
    интервала спецификации [TCH_Temp_A; TCH_Temp_B] ЛИБО с краем
    фактических данных в этом интервале (первая/последняя температура) —
    это не настоящий экстремум, а граница участка.
    """
    out: Dict[str, Any] = {
        "Fmax": None, "Fmin": None, "Fptp": None, "Fptp/2": None,
        "Rmax": None, "Rmin": None, "Rptp": None,
        "Mono": None, "Slope": None,
        "Tmax": None, "Tmin": None, "Turnover": None,
    }
    if temp_df is None or temp_df.empty or "Temp" not in temp_df.columns:
        return out

    t_raw = pd.to_numeric(temp_df["Temp"], errors="coerce").values.astype(float)
    t_nakl, degree, ta, tb = _normalize_spec(spec)
    if spec is None:
        degree = int(mono_degree)

    if f_col in temp_df.columns:
        f_raw = pd.to_numeric(temp_df[f_col], errors="coerce").values.astype(float)
        t, f = _clean_series(t_raw, f_raw)
        if f.size >= 1:
            # Рабочий диапазон [TCH_Temp_A; TCH_Temp_B].
            in_range = (t >= ta) & (t <= tb)
            tf, ff = (t[in_range], f[in_range]) if in_range.any() else (t, f)

            out["Fmax"] = float(np.max(ff))
            out["Fmin"] = float(np.min(ff))
            out["Fptp"] = float(out["Fmax"] - out["Fmin"])
            out["Fptp/2"] = out["Fptp"] / 2.0
            out["Tmax"] = float(tf[np.argmax(ff)])
            out["Tmin"] = float(tf[np.argmin(ff)])

            # Полином строим по отфильтрованным точкам [ta; tb].
            coeffs = None
            if tf.size >= max(3, degree + 1):
                coeffs = _fit_poly(tf, ff, degree)

            if coeffs is not None:
                # extr_1 / extr_2 — корни 1-й производной в [ta; tb].
                extr = _real_roots_in(np.polyder(coeffs, 1), ta, tb)
                if extr.size >= 2:
                    out["Tmax"] = float(extr[0])
                    out["Tmin"] = float(extr[1])
                elif extr.size == 1:
                    out["Tmax"] = float(extr[0])

                # TurnOver_1 — корень 2-й производной в [ta; tb].
                if coeffs.size >= 3:
                    infl = _real_roots_in(np.polyder(coeffs, 2), ta, tb)
                    if infl.size:
                        mid = 0.5 * (tf.min() + tf.max())
                        out["Turnover"] = float(
                            infl[int(np.argmin(np.abs(infl - mid)))]
                        )

                # Mono — max отклонение полинома от точек на [ta; tb].
                delta = np.polyval(coeffs, tf) - ff
                i = int(np.argmax(np.abs(delta)))
                out["Mono"] = float(delta[i])

            # Fallback Turnover, если полином не дал корней.
            if out["Turnover"] is None and tf.size >= 2:
                slopes = np.diff(ff) / np.diff(tf)
                finite = np.isfinite(slopes)
                if finite.any():
                    s_use = np.where(finite, slopes, np.inf)
                    idx = int(np.argmin(np.abs(s_use)))
                    out["Turnover"] = float(0.5 * (tf[idx] + tf[idx + 1]))

            # Slope — производная полинома в Tnakl; fallback — хорда.
            slope = None
            if t_nakl is not None and np.isfinite(t_nakl):
                if coeffs is None and tf.size >= max(3, degree + 1):
                    coeffs = _fit_poly(tf, ff, degree)
                if coeffs is not None:
                    try:
                        val = float(np.polyval(np.polyder(coeffs, 1), t_nakl))
                        slope = val if np.isfinite(val) else None
                    except Exception:
                        slope = None
            if slope is None:
                slope = _chord_slope(tf, ff)
            if slope is None:
                slope = _chord_slope(t, f)
            out["Slope"] = slope

            # Tmax/Tmin на краю [ta; tb] ИЛИ на краю фактических данных -> None
            if _at_data_edge(out["Tmax"], tf, ta, tb):
                out["Tmax"] = None
            if _at_data_edge(out["Tmin"], tf, ta, tb):
                out["Tmin"] = None

    if r_col in temp_df.columns:
        r_raw = pd.to_numeric(temp_df[r_col], errors="coerce").values.astype(float)
        t_r, rr = _clean_series(t_raw, r_raw)
        if rr.size >= 1:
            in_range_r = (t_r >= ta) & (t_r <= tb)
            rsub = rr[in_range_r] if in_range_r.any() else rr
            out["Rmax"] = float(np.max(rsub))
            out["Rmin"] = float(np.min(rsub))
            out["Rptp"] = float(out["Rmax"] - out["Rmin"])

    return out

def compute_curve_metrics_2(
    temp_df: pd.DataFrame,
    f_col: str = "F",
    r_col: str = "R",
    mono_degree: int = 3,
    spec: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Сводные метрики по температурной кривой.

    Как в Make_Measure.calculate_metrics:
      - кривая фильтруется в [TCH_Temp_A; TCH_Temp_B];
      - полином строится по отфильтрованным точкам;
      - корни 1-й/2-й производной обрезаются по [ta; tb];
      - Tmax / Tmin = None, если итоговое значение совпадает
        с краем интервала (это не настоящий экстремум);
      - Slope = производная полинома в Tnakl; fallback — хорда;
      - Mono — макс. отклонение полинома от точек на [ta; tb].
    """
    out: Dict[str, Any] = {
        "Fmax": None, "Fmin": None, "Fptp": None, "Fptp/2": None,
        "Rmax": None, "Rmin": None, "Rptp": None,
        "Mono": None, "Slope": None,
        "Tmax": None, "Tmin": None, "Turnover": None,
    }
    if temp_df is None or temp_df.empty or "Temp" not in temp_df.columns:
        return out

    t_raw = pd.to_numeric(temp_df["Temp"], errors="coerce").values.astype(float)
    t_nakl, degree, ta, tb = _normalize_spec(spec)
    if spec is None:
        degree = int(mono_degree)

    if f_col in temp_df.columns:
        f_raw = pd.to_numeric(temp_df[f_col], errors="coerce").values.astype(float)
        t, f = _clean_series(t_raw, f_raw)
        if f.size >= 1:
            # Рабочий диапазон [TCH_Temp_A; TCH_Temp_B] (как Make_Measure).
            in_range = (t >= ta) & (t <= tb)
            tf, ff = (t[in_range], f[in_range]) if in_range.any() else (t, f)

            out["Fmax"] = float(np.max(ff))
            out["Fmin"] = float(np.min(ff))
            out["Fptp"] = float(out["Fmax"] - out["Fmin"])
            out["Fptp/2"] = out["Fptp"] / 2.0
            out["Tmax"] = float(tf[np.argmax(ff)])
            out["Tmin"] = float(tf[np.argmin(ff)])

            # Полином строим по отфильтрованным точкам [ta; tb].
            coeffs = None
            if tf.size >= max(3, degree + 1):
                coeffs = _fit_poly(tf, ff, degree)

            if coeffs is not None:
                # extr_1 / extr_2 — корни 1-й производной в [ta; tb]
                # (как Make_Measure: Ta <= rt.real <= Tb).
                extr = _real_roots_in(np.polyder(coeffs, 1), ta, tb)
                if extr.size >= 2:
                    out["Tmax"] = float(extr[0])
                    out["Tmin"] = float(extr[1])
                elif extr.size == 1:
                    out["Tmax"] = float(extr[0])

                # TurnOver_1 — корень 2-й производной в [ta; tb].
                if coeffs.size >= 3:
                    infl = _real_roots_in(np.polyder(coeffs, 2), ta, tb)
                    if infl.size:
                        mid = 0.5 * (tf.min() + tf.max())
                        out["Turnover"] = float(
                            infl[int(np.argmin(np.abs(infl - mid)))]
                        )

                # Mono — max отклонение полинома от точек на [ta; tb].
                delta = np.polyval(coeffs, tf) - ff
                i = int(np.argmax(np.abs(delta)))
                out["Mono"] = float(delta[i])

            # Fallback Turnover, если полином не дал корней в [ta; tb].
            if out["Turnover"] is None and tf.size >= 2:
                slopes = np.diff(ff) / np.diff(tf)
                finite = np.isfinite(slopes)
                if finite.any():
                    s_use = np.where(finite, slopes, np.inf)
                    idx = int(np.argmin(np.abs(s_use)))
                    out["Turnover"] = float(0.5 * (tf[idx] + tf[idx + 1]))

            # Slope — производная полинома в Tnakl; fallback — хорда.
            slope = None
            if t_nakl is not None and np.isfinite(t_nakl):
                if coeffs is None and tf.size >= max(3, degree + 1):
                    coeffs = _fit_poly(tf, ff, degree)
                if coeffs is not None:
                    try:
                        val = float(np.polyval(np.polyder(coeffs, 1), t_nakl))
                        slope = val if np.isfinite(val) else None
                    except Exception:
                        slope = None
            if slope is None:
                slope = _chord_slope(tf, ff)
            if slope is None:
                slope = _chord_slope(t, f)
            out["Slope"] = slope

            # Tmax/Tmin = край интервала -> это не настоящий экстремум.
            if _at_interval_edge(out["Tmax"], ta, tb):
                out["Tmax"] = None
            if _at_interval_edge(out["Tmin"], ta, tb):
                out["Tmin"] = None

    if r_col in temp_df.columns:
        r_raw = pd.to_numeric(temp_df[r_col], errors="coerce").values.astype(float)
        t_r, rr = _clean_series(t_raw, r_raw)
        if rr.size >= 1:
            in_range_r = (t_r >= ta) & (t_r <= tb)
            rsub = rr[in_range_r] if in_range_r.any() else rr
            out["Rmax"] = float(np.max(rsub))
            out["Rmin"] = float(np.min(rsub))
            out["Rptp"] = float(out["Rmax"] - out["Rmin"])

    return out

def _at_interval_edge(v, ta: float, tb: float, eps: float = 1e-6) -> bool:
    """True, если v совпадает с краем интервала [ta; tb] (только для конечных границ)."""
    if v is None:
        return False
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return False
    if not np.isfinite(fv):
        return False
    if np.isfinite(ta) and abs(fv - ta) <= eps:
        return True
    if np.isfinite(tb) and abs(fv - tb) <= eps:
        return True
    return False


def _temps_for_number(
    temps_df: pd.DataFrame,
    number: str,
    measure_id: Optional[int] = None,
) -> pd.DataFrame:
    if temps_df is None or temps_df.empty:
        return pd.DataFrame()
    n = str(number).strip().upper()
    mask = temps_df["N"].astype(str).str.strip().str.upper() == n
    sub = temps_df[mask]
    if measure_id is not None and "Measure_ID" in temps_df.columns:
        by_mid = sub[sub["Measure_ID"] == measure_id]
        if not by_mid.empty:
            return by_mid
    return sub


# Aliasy kolonok psidata: kluch metyki -> realnye kolonki (kak v psidata_map_table)
_WRITE_ALIAS: Dict[str, Tuple[str, ...]] = {
    "Fmax": ("Fmax",),
    "Fmin": ("Fmin",),
    "Rmax": ("Rmax",),
    "Rmin": ("Rmin",),
    "Mono": ("Mono",),
    "Turnover": ("TurnOver_1", "Turnover", "TurnOver"),
    "Tmax": ("extr_1", "Tmax"),
    "Tmin": ("extr_2", "Tmin"),
    "Fptp": ("Fptp",),
    "Fptp/2": ("Fptp/2", "Fptp_2"),
    "Rptp": ("Rptp",),
    "Slope": ("Slope",),
}


def _write_metric(df: pd.DataFrame, idx: Any, metric: str, value: Any) -> None:
    if value is None:
        return
    for col in _WRITE_ALIAS.get(metric, (metric,)):
        if col in df.columns:
            df.at[idx, col] = value
            return


def build_summary_table(
    psi_df: pd.DataFrame,
    temps_df: pd.DataFrame,
    measure_id: int,
    spec: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    """
    Stroim svodnuyu po VSEM nomeram iz temps (corrected) i/ili psi.
    Esli psi po measure_id pustoj - berem nomera iz temps.
    """
    rows = []
    numbers = []
    psi_sub = pd.DataFrame()
    if psi_df is not None and not psi_df.empty and "Measure_ID" in psi_df.columns:
        psi_sub = psi_df[psi_df["Measure_ID"] == measure_id].copy()
        if not psi_sub.empty and "N" in psi_sub.columns:
            numbers = (
                psi_sub["N"].astype(str).str.strip().str.upper().unique().tolist()
            )
    if not numbers and temps_df is not None and not temps_df.empty and "N" in temps_df.columns:
        numbers = (
            temps_df["N"].astype(str).str.strip().str.upper().unique().tolist()
        )
    numbers = sorted({n for n in numbers if n and n != "NAN"})

    psi_by_n = {}
    if not psi_sub.empty and "N" in psi_sub.columns:
        for _, prow in psi_sub.iterrows():
            nn = str(prow.get("N") or "").strip().upper()
            if nn:
                psi_by_n[nn] = prow

    for n in numbers:
        tsub = _temps_for_number(temps_df, n, measure_id)
        m = compute_curve_metrics(tsub, spec=spec)
        prow = psi_by_n.get(n)
        status = prow.get("Status") if prow is not None else None
        row = {"N": n, "Measure_ID": measure_id, "Status": status}
        row.update(m)
        rows.append(row)

    return pd.DataFrame(rows)


def apply_metrics_to_psidata(
    psi_df: pd.DataFrame,
    temps_df: pd.DataFrame,
    measure_id: int,
    spec: Optional[Dict[str, Any]] = None,
) -> pd.DataFrame:
    out = psi_df[psi_df["Measure_ID"] == measure_id].copy()
    if out.empty:
        return out

    for idx, prow in out.iterrows():
        n = str(prow.get("N") or "").strip().upper()
        tsub = _temps_for_number(temps_df, n, measure_id)
        m = compute_curve_metrics(tsub, spec=spec)
        for metric in _WRITE_ALIAS:
            _write_metric(out, idx, metric, m.get(metric))

    return out
