"""Статистика и распределение по выбранному параметру."""
import numpy as np
import pandas as pd
from sqlalchemy import text

from .Virtual_Data import _engine


# ------------ сбор значений ------------
def collect_param_values(measure_id: int, param: str,
                         only_virtual: bool = None) -> list:
    if not measure_id or not param:
        return []

    sql = f"SELECT `{param}` FROM psidata WHERE Measure_ID = :m"
    if only_virtual is True:
        sql += " AND Virtual_Data = 1"
    elif only_virtual is False:
        sql += " AND (Virtual_Data = 0 OR Virtual_Data IS NULL)"

    try:
        df = pd.read_sql(text(sql), _engine(), params={'m': measure_id})
        if param not in df.columns:
            return []
        vals = df[param].dropna().astype(float).tolist()
        return [v for v in vals if not np.isnan(v) and not np.isinf(v)]
    except Exception as e:
        print(f"[Virtual] collect_param_values error: {e}")
        return []


# ------------ базовые статистики ------------
def compute_stats(values: list) -> dict:
    if not values:
        return {'n': 0, 'mean': None, 'std': None, 'min': None,
                'max': None, 'median': None, 'q1': None, 'q3': None,
                'iqr': None}
    arr = np.asarray(values, dtype=float)
    if len(arr) == 1:
        v = float(arr[0])
        return {'n': 1, 'mean': v, 'std': 0.0, 'min': v, 'max': v,
                'median': v, 'q1': v, 'q3': v, 'iqr': 0.0}
    q1, median, q3 = np.percentile(arr, [25, 50, 75])
    return {
        'n': int(len(arr)),
        'mean': float(np.mean(arr)),
        'std': float(np.std(arr, ddof=1)),
        'min': float(np.min(arr)),
        'max': float(np.max(arr)),
        'median': float(median),
        'q1': float(q1),
        'q3': float(q3),
        'iqr': float(q3 - q1),
    }


# ------------ распределение (плотность) ------------
def _finite_or_none(v):
    """Привести v к float; вернуть None для NaN/inf/не-числа."""
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    return fv if np.isfinite(fv) else None


def compute_distribution(base_vals: list, virt_vals: list,
                         n_points: int = 200) -> dict:
    """
    Плотность распределения для базового и виртуального рядов.

    NaN, inf и нечисловые значения отбрасываются ДО построения
    гистограммы/KDE — иначе np.histogram падает с
    'autodetected range of [nan, nan] is not finite'.

    Возвращает:
        {'x': [...], 'base': [...], 'virt': [...], 'min': f, 'max': f}
        или {} если после фильтра не осталось данных.
    """
    try:
        from scipy.stats import gaussian_kde
        has_scipy = True
    except ImportError:
        has_scipy = False

    base_clean = [
        fv for fv in (_finite_or_none(v) for v in base_vals)
        if fv is not None
    ]
    virt_clean = [
        fv for fv in (_finite_or_none(v) for v in virt_vals)
        if fv is not None
    ]

    if not base_clean and not virt_clean:
        return {}

    all_vals = base_clean + virt_clean
    lo, hi = float(min(all_vals)), float(max(all_vals))
    if hi <= lo:
        hi = lo + 1.0
    pad = (hi - lo) * 0.1
    x = np.linspace(lo - pad, hi + pad, n_points)

    def density(vals):
        if not vals:
            return [0.0] * n_points
        arr = np.asarray(vals, dtype=float)
        if arr.size == 0:
            return [0.0] * n_points
        if arr.size < 2:
            d = np.zeros_like(x)
            idx = int(np.abs(x - arr[0]).argmin())
            d[idx] = 1.0
            return d.tolist()
        if has_scipy:
            try:
                kde = gaussian_kde(arr, bw_method='scott')
                return kde(x).tolist()
            except Exception as e:
                print(f"[Virtual] KDE error, fallback to hist: {e}",
                      flush=True)
        bins = max(10, min(50, arr.size // 3))
        try:
            hist, edges = np.histogram(arr, bins=bins, density=True)
            centers = (edges[:-1] + edges[1:]) / 2
            return np.interp(x, centers, hist).tolist()
        except Exception as e:
            print(f"[Virtual] hist error: {e}", flush=True)
            return [0.0] * n_points

    return {
        'x':    x.tolist(),
        'base': density(base_clean),
        'virt': density(virt_clean),
        'min':  float(lo),
        'max':  float(hi),
    }
def compute_distribution_1(base_vals: list, virt_vals: list,
                         n_points: int = 200) -> dict:
    """
    Плотность распределения для базового и виртуального рядов.

    Возвращает:
        {
            'x':    [..],
            'base': [плотность base],
            'virt': [плотность virt],
            'min':  float,
            'max':  float,
        }
    """
    try:
        from scipy.stats import gaussian_kde
        has_scipy = True
    except ImportError:
        has_scipy = False

    all_vals = [v for v in list(base_vals) + list(virt_vals)
                if v is not None]
    if not all_vals:
        return {}

    lo, hi = float(min(all_vals)), float(max(all_vals))
    if hi <= lo:
        hi = lo + 1.0
    pad = (hi - lo) * 0.1
    x = np.linspace(lo - pad, hi + pad, n_points)

    def density(vals):
        arr = np.asarray([v for v in vals if v is not None], dtype=float)
        if arr.size == 0:
            return [0.0] * n_points
        if arr.size < 2:
            d = np.zeros_like(x)
            idx = int(np.abs(x - arr[0]).argmin())
            d[idx] = 1.0
            return d.tolist()
        if has_scipy:
            try:
                kde = gaussian_kde(arr, bw_method='scott')
                return kde(x).tolist()
            except Exception as e:
                print(f"[Virtual] KDE error, fallback to hist: {e}")
        # Fallback: сглаженная гистограмма через интерполяцию
        bins = max(10, min(50, arr.size // 3))
        hist, edges = np.histogram(arr, bins=bins, density=True)
        centers = (edges[:-1] + edges[1:]) / 2
        return np.interp(x, centers, hist).tolist()

    return {
        'x':    x.tolist(),
        'base': density(base_vals),
        'virt': density(virt_vals),
        'min':  float(lo),
        'max':  float(hi),
    }


# ------------ список виртуальных Measure_ID для combo ------------
def list_virtual_measure_ids(spc_name: str = None) -> list:
    """Все Measure_ID с Virtual_Data=1 (опционально — по спецификации)."""
    sql = ("SELECT DISTINCT Measure_ID FROM psidata "
           "WHERE Virtual_Data = 1 AND Measure_ID IS NOT NULL")
    params = {}
    if spc_name:
        sql += " AND Spc = :s"
        params['s'] = spc_name
    sql += " ORDER BY Measure_ID"
    try:
        df = pd.read_sql(text(sql), _engine(), params=params)
        return [int(x) for x in df['Measure_ID'].dropna().tolist()]
    except Exception as e:
        print(f"[Virtual] list_virtual_measure_ids error: {e}")
        return []