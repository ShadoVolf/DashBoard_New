"""
Чистая математика: МНК-аппроксимация, монотонность, экстремумы, скачки.
Не зависит от DPG и БД.
"""
import numpy as np


def poly_fit(x, y, degree: int):
    """МНК-аппроксимация; коэффициенты от старшей степени к младшей."""
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size == 0 or y.size == 0:
        return np.zeros(degree + 1)
    if x.size <= degree:
        degree = max(0, x.size - 1)
    return np.polyfit(x, y, degree)


def poly_val(coeffs, x):
    return np.polyval(coeffs, x)

def monotonicity(x, y, A: float, B: float, degree: int,
                 exclude_edges: bool = True) -> tuple[float, float | None]:
    """
    Максимальное по модулю отклонение измеренной функции от
    аппроксимирующей в узлах измерения внутри [A, B] — как Mono/MonoT
    в Make_Measure.calculate_metrics.

    Возвращает (delta_value, T_at_max):
        delta_value = y_approx - y_meas  (со знаком, как delta_f)
        T_at_max    — температура точки с максимальным |delta|

    exclude_edges=True — первая и последняя точка температурного
    интервала не участвуют в поиске максимума (граничные точки ТЧХ
    часто шумные и искажают монотонность).
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = (x >= A) & (x <= B) & np.isfinite(x) & np.isfinite(y)
    if mask.sum() < degree + 1:
        return 0.0, None

    x_in = x[mask]
    y_in = y[mask]

    coeffs = poly_fit(x_in, y_in, degree)
    y_approx = np.polyval(coeffs, x_in)
    delta = y_approx - y_in          # = f_interp − F_

    if exclude_edges and delta.size > 2:
        order = np.argsort(x_in)
        keep = np.ones(delta.size, dtype=bool)
        keep[order[0]] = False       # T_min
        keep[order[-1]] = False      # T_max
        x_in = x_in[keep]
        delta = delta[keep]

    if delta.size == 0:
        return 0.0, None

    idx = int(np.argmax(np.abs(delta)))
    return float(delta[idx]), float(x_in[idx])


def jumps(x, y, A: float, B: float, degree: int,
          exclude_edges: bool = False
          ) -> tuple[float, float | None, float, float | None]:
    """
    Максимальное перпендикулярное расстояние от точек измерения до
    аппроксимирующей кривой в одну и другую сторону.

    Для каждого узла (x_i, y_i):
        d_i = (y_i − P(x_i)) / sqrt(1 + P'(x_i)^2)

    Возвращает (jump_plus, T_plus, jump_minus, T_minus):
        jump_plus  — max положительного d_i  (точка выше кривой)
        jump_minus — min (по значению) d_i   (точка ниже кривой, знак «−»)
        T_*        — температура соответствующей точки или None
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = (x >= A) & (x <= B) & np.isfinite(x) & np.isfinite(y)
    if mask.sum() < degree + 1:
        return 0.0, None, 0.0, None

    x_in = x[mask]
    y_in = y[mask]

    coeffs = poly_fit(x_in, y_in, degree)
    y_approx = np.polyval(coeffs, x_in)
    dy = np.polyval(np.polyder(coeffs, 1), x_in)
    perp = (y_in - y_approx) / np.sqrt(1.0 + dy ** 2)

    if exclude_edges and perp.size > 2:
        order = np.argsort(x_in)
        keep = np.ones(perp.size, dtype=bool)
        keep[order[0]] = False
        keep[order[-1]] = False
        x_in = x_in[keep]
        perp = perp[keep]

    if perp.size == 0:
        return 0.0, None, 0.0, None

    i_max = int(np.argmax(perp))
    i_min = int(np.argmin(perp))

    j_plus = float(perp[i_max]) if perp[i_max] > 0 else 0.0
    t_plus = float(x_in[i_max]) if perp[i_max] > 0 else None

    j_minus = float(perp[i_min]) if perp[i_min] < 0 else 0.0
    t_minus = float(x_in[i_min]) if perp[i_min] < 0 else None

    return j_plus, t_plus, j_minus, t_minus

def monotonicity_2(x, y, A: float, B: float, degree: int,
                 step: float = 0.1) -> float:
    """
    Максимальное по модулю отклонение измеренной функции от
    аппроксимирующей в узлах измерения (для точек внутри [A, B]).

    step сохранён для обратной совместимости, но не используется.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = (x >= A) & (x <= B)
    if not mask.any():
        return 0.0
    x_in = x[mask]
    y_in = y[mask]
    if x_in.size < degree + 1:
        return 0.0
    coeffs = poly_fit(x_in, y_in, degree)
    y_approx = np.polyval(coeffs, x_in)
    return float(np.max(np.abs(y_in - y_approx)))

def monotonicity_old(x, y, A: float, B: float, degree: int, step: float = 0.1) -> float:
    """Максимальное приращение полинома на [A,B]."""
    coeffs = poly_fit(x, y, degree)
    xs = np.arange(A, B + step / 2, step)
    if xs.size < 2:
        return 0.0
    ys = np.polyval(coeffs, xs)
    return float(np.max(np.abs(np.diff(ys))))


def monotonicity_profile(x, y, A: float, B: float, degree: int, step: float = 0.1):
    """Возвращает (xs, ys) — узлы и значения полинома."""
    coeffs = poly_fit(x, y, degree)
    xs = np.arange(A, B + step / 2, step)
    ys = np.polyval(coeffs, xs)
    return xs, ys


def extremes(coeffs, A: float, B: float, step: float = 0.01):
    """Локальные максимум/минимум полинома на [A,B]."""
    xs = np.arange(A, B + step / 2, step)
    if xs.size < 3:
        return None, None
    ys = np.polyval(coeffs, xs)
    dy = np.diff(ys)
    t_max = t_min = None
    for i in range(len(dy) - 1):
        if dy[i] > 0 >= dy[i + 1]:
            t_max = float(xs[i + 1])
        elif dy[i] < 0 <= dy[i + 1]:
            t_min = float(xs[i + 1])
    return t_max, t_min

def gaussian_kde(x, n_points: int = 200, bw=None):
    """
    Оценка плотности распределения (гауссово ядро, правило Сильвермана).
    Возвращает (xs, ys).
    """
    x = np.asarray(x, dtype=float)
    n = x.size
    if n == 0:
        return np.array([]), np.array([])
    if n == 1:
        return np.array([x[0]]), np.array([1.0])

    std = float(np.std(x, ddof=1))
    iqr = float(np.percentile(x, 75) - np.percentile(x, 25))
    a = min(std, iqr / 1.34) if (std > 0 and iqr > 0) else (std or iqr or 1.0)
    if a <= 0:
        a = 1.0
    if bw is None:
        bw = 0.9 * a * n ** (-0.2)
    if bw <= 0:
        bw = 1.0

    lo, hi = float(np.min(x)), float(np.max(x))
    xs = np.linspace(lo - 3 * bw, hi + 3 * bw, n_points)
    diff = (xs[:, None] - x[None, :]) / bw
    kernel = np.exp(-0.5 * diff ** 2) / np.sqrt(2 * np.pi)
    ys = kernel.sum(axis=1) / (n * bw)
    return xs, ys

def jumps(x, y, A: float, B: float, degree: int,
          exclude_edges: bool = False
          ) -> tuple[float, float | None, float, float | None]:
    """
    Максимальное перпендикулярное расстояние от точек измерения до
    аппроксимирующей кривой в одну и другую сторону.

    Для каждого узла (x_i, y_i):
        d_i = (y_i − P(x_i)) / sqrt(1 + P'(x_i)^2)

    Возвращает (jump_plus, T_plus, jump_minus, T_minus):
        jump_plus  — max положительного d_i  (точка выше кривой)
        jump_minus — min (по значению) d_i   (точка ниже кривой, знак «−»)
        T_*        — температура соответствующей точки или None
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = (x >= A) & (x <= B) & np.isfinite(x) & np.isfinite(y)
    if mask.sum() < degree + 1:
        return 0.0, None, 0.0, None

    x_in = x[mask]
    y_in = y[mask]

    coeffs = poly_fit(x_in, y_in, degree)
    y_approx = np.polyval(coeffs, x_in)
    dy = np.polyval(np.polyder(coeffs, 1), x_in)
    perp = (y_in - y_approx) / np.sqrt(1.0 + dy ** 2)

    if exclude_edges and perp.size > 2:
        order = np.argsort(x_in)
        keep = np.ones(perp.size, dtype=bool)
        keep[order[0]] = False
        keep[order[-1]] = False
        x_in = x_in[keep]
        perp = perp[keep]

    if perp.size == 0:
        return 0.0, None, 0.0, None

    i_max = int(np.argmax(perp))
    i_min = int(np.argmin(perp))

    j_plus = float(perp[i_max]) if perp[i_max] > 0 else 0.0
    t_plus = float(x_in[i_max]) if perp[i_max] > 0 else None

    j_minus = float(perp[i_min]) if perp[i_min] < 0 else 0.0
    t_minus = float(x_in[i_min]) if perp[i_min] < 0 else None

    return j_plus, t_plus, j_minus, t_minus

def jumps_2(x, y, A: float, B: float, degree: int, step: float = 0.01):
    """Максимальное приращение / падение аппроксимации на [A,B]."""
    coeffs = poly_fit(x, y, degree)
    xs = np.arange(A, B + step / 2, step)
    if xs.size < 2:
        return 0.0, None, 0.0, None
    ys = np.polyval(coeffs, xs)
    d = np.diff(ys)
    i_max = int(np.argmax(d))
    i_min = int(np.argmin(d))
    return (float(d[i_max]), float(xs[i_max + 1]),
            float(d[i_min]), float(xs[i_min + 1]))

def inflection_point(coeffs, A: float, B: float):
    """
    Точка перегиба (TurnOver_1) — первый вещественный корень второй
    производной аппроксимирующего полинома в диапазоне [A, B].

    Метод 1:1 с Make_Measure.calculate_metrics:
        deriv2 = np.polyder(coeffs, 2)
        roots  = np.roots(deriv2)
        real   = [r.real for r in roots if r.imag == 0 and A <= r.real <= B]
        TurnOver_1 = sorted(real)[0] if real else None
    """
    try:
        deriv2 = np.polyder(coeffs, 2)
    except Exception:
        return None
    if len(deriv2) == 0:
        return None
    try:
        roots = np.roots(deriv2)
    except Exception:
        return None
    real_roots = [float(r.real) for r in roots
                  if r.imag == 0 and A <= r.real <= B]
    if not real_roots:
        return None
    return float(sorted(real_roots)[0])

def inflection_point_1(coeffs, A: float, B: float, step: float = 0.01):
    """Точка перегиба — где вторая производная меняет знак на [A,B]."""
    xs = np.arange(A, B + step / 2, step)
    if xs.size < 3:
        return None
    d2 = np.polyval(np.polyder(coeffs, 2), xs)
    sign = np.sign(d2)
    for i in range(len(sign) - 1):
        if sign[i] != 0 and sign[i + 1] != 0 and sign[i] != sign[i + 1]:
            return float(xs[i + 1])
    return None