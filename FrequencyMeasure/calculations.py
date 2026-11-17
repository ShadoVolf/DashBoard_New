import numpy as np


def to_ppm(freq_hz, nominal_hz):
    if not nominal_hz or nominal_hz <= 0:
        return 0.0
    return (freq_hz - nominal_hz) / nominal_hz * 1e6


def calc_residuals_ppm(freqs, nominal_hz, window=15, poly_deg=2):
    """Невязки реальной кривой относительно локальной полиномиальной
    аппроксимации. Возвращает массив отклонений в ppm.
    """
    if len(freqs) < 5 or not nominal_hz:
        return np.zeros(len(freqs))
    f = np.asarray(freqs, dtype=float)
    n = len(f)
    half = max(2, window // 2)
    x_all = np.arange(n, dtype=float)
    res = np.zeros(n)
    for i in range(n):
        lo = max(0, i - half)
        hi = min(n, i + half + 1)
        xs = x_all[lo:hi]
        ys = f[lo:hi]
        if len(xs) <= poly_deg:
            res[i] = 0.0
            continue
        try:
            coeffs = np.polyfit(xs, ys, poly_deg)
            y_fit = np.polyval(coeffs, i)
            res[i] = f[i] - y_fit
        except Exception:
            res[i] = 0.0
    return res / nominal_hz * 1e6


def calc_monotonicity_ppm(freqs, nominal_hz, window=15, poly_deg=2):
    """Максимальное отклонение от аппроксимирующей функции, ppm."""
    res = calc_residuals_ppm(freqs, nominal_hz, window, poly_deg)
    if len(res) == 0:
        return 0.0
    return float(np.max(np.abs(res)))


def calc_ppm_relative(freqs, ref_hz=None):
    """Отклонение частот в ppm относительно опорной частоты.
    Если ref_hz не задан - берётся последняя точка (конец измерения).
    """
    f = np.asarray(freqs, dtype=float)
    if f.size == 0:
        return f
    if ref_hz is None or ref_hz <= 0:
        ref_hz = float(f[-1])
    if ref_hz <= 0:
        return np.zeros_like(f)
    return (f - ref_hz) / ref_hz * 1e6


def calc_outliers(freqs, nominal_hz, threshold_ppm=20.0,
                  window=15, poly_deg=2):
    """Максимум |residual| среди точек, где |residual| > threshold_ppm."""
    res = calc_residuals_ppm(freqs, nominal_hz, window, poly_deg)
    if len(res) == 0:
        return 0.0
    abs_res = np.abs(res)
    hits = abs_res > threshold_ppm
    if not np.any(hits):
        return 0.0
    return float(np.max(abs_res[hits]))