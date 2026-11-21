"""Фильтрация и сглаживание кривых фазовых шумов (стандартная и AI)."""

from __future__ import annotations

import logging
import numpy as np
import pandas as pd
from scipy.signal import medfilt, savgol_filter

log = logging.getLogger("PhaseNoise.Filter")

FILTER_NONE = "Без обработки"
FILTER_STD = "Стандартная"
FILTER_AI = "AI обработка"
FILTER_MODES = [FILTER_NONE, FILTER_STD, FILTER_AI]
from scipy.ndimage import gaussian_filter1d


def _smooth_standard(pn: np.ndarray) -> np.ndarray:
    """Усиленная классическая очистка: адаптивная медиана + Гаусс + Савицкий-Голей."""
    n = len(pn)
    if n < 5:
        return pn.copy()

    # 1. Адаптивный медианный фильтр (~3-4% от длины кривой, но не меньше 5 и не больше 31)
    k_med = max(5, min(31, int(n * 0.035)))
    if k_med % 2 == 0:
        k_med += 1
    if k_med >= n:
        k_med = n if n % 2 == 1 else n - 1
    y = medfilt(pn, kernel_size=k_med)

    # 2. Гауссовское сглаживание (сигма пропорциональна длине ряда, убирает высокочастотную «пилу»)
    sigma = max(1.8, n * 0.015)
    y = gaussian_filter1d(y, sigma=sigma, mode="nearest")

    # 3. Финишное сглаживание Савицкого-Голея с широким адаптивным окном (~10-12% от длины кривой)
    win = max(9, min(81, int(n * 0.11)))
    if win % 2 == 0:
        win += 1
    if win >= n:
        win = n if n % 2 == 1 else n - 1
    if win >= 5:
        y = savgol_filter(y, window_length=win, polyorder=2, mode="interp")

    return y


def _smooth_standard_1(pn: np.ndarray) -> np.ndarray:
    """Классическая очистка: медиана от выбросов + полином Савицкого-Голея."""
    n = len(pn)
    if n < 5:
        return pn.copy()

    # 1. Убираем узкие пики/провалы (окно 3 или 5)
    k_med = 5 if n >= 15 else 3
    y = medfilt(pn, kernel_size=k_med)

    # 2. Сглаживаем мелкую неравномерность без завала наклона кривой
    win = min(15, n if n % 2 == 1 else n - 1)
    if win >= 5:
        y = savgol_filter(y, window_length=win, polyorder=2, mode="interp")
    return y


def _smooth_ai_torch(log_freq: np.ndarray, pn: np.ndarray) -> np.ndarray | None:
    """1D Denoising Autoencoder на PyTorch для выделения гладкой огибающей."""
    try:
        import torch
        import torch.nn as nn
    except ImportError:
        return None

    n = len(pn)
    if n < 10:
        return None

    torch.manual_seed(42)

    f_norm = (log_freq - log_freq.mean()) / (log_freq.std() + 1e-8)
    pn_mean, pn_std = float(pn.mean()), float(pn.std() + 1e-8)
    y_norm = (pn - pn_mean) / pn_std

    x_tensor = torch.tensor(
        np.stack([f_norm, y_norm], axis=0)[None, :, :], dtype=torch.float32
    )
    target = torch.tensor(y_norm[None, None, :], dtype=torch.float32)

    class CurveDenoiser1D(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Conv1d(2, 16, kernel_size=5, padding=2, padding_mode="replicate"),
                nn.GELU(),
                nn.Conv1d(16, 8, kernel_size=5, padding=2, padding_mode="replicate"),
                nn.GELU(),
                nn.Conv1d(8, 16, kernel_size=5, padding=2, padding_mode="replicate"),
                nn.GELU(),
                nn.Conv1d(16, 1, kernel_size=5, padding=2, padding_mode="replicate"),
            )

        def forward(self, x):
            return self.net(x)

    model = CurveDenoiser1D()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.015)
    loss_fn = nn.SmoothL1Loss(beta=0.5)

    model.train()
    for _ in range(90):
        noisy_in = x_tensor.clone()
        noisy_in[:, 1, :] += torch.randn_like(noisy_in[:, 1, :]) * 0.25
        pred = model(noisy_in)
        smooth_penalty = torch.mean(
            (pred[:, :, 2:] - 2 * pred[:, :, 1:-1] + pred[:, :, :-2]) ** 2
        )
        loss = loss_fn(pred, target) + 1.5 * smooth_penalty
        optimizer.zero_grad()
        loss.backward()
        optimizer.step()

    model.eval()
    with torch.no_grad():
        cleaned_norm = model(x_tensor).squeeze().numpy()

    return cleaned_norm * pn_std + pn_mean


def _smooth_ai_sklearn(log_freq: np.ndarray, pn: np.ndarray) -> np.ndarray | None:
    """Резервная нейросеть (MLPRegressor), если PyTorch не установлен."""
    try:
        from sklearn.neural_network import MLPRegressor
    except ImportError:
        return None

    n = len(pn)
    if n < 8:
        return None

    X = ((log_freq - log_freq.mean()) / (log_freq.std() + 1e-8)).reshape(-1, 1)
    y_clean_init = medfilt(pn, kernel_size=5 if n >= 15 else 3)

    mlp = MLPRegressor(
        hidden_layer_sizes=(32, 16),
        activation="tanh",
        alpha=0.15,
        max_iter=400,
        random_state=42,
    )
    mlp.fit(X, y_clean_init)
    return mlp.predict(X)


def _smooth_ai(freq: np.ndarray, pn: np.ndarray) -> np.ndarray:
    """AI-очистка кривой с автоматическим выбором бэкенда."""
    safe_freq = np.maximum(freq, 1e-3)
    log_f = np.log10(safe_freq)

    res = _smooth_ai_torch(log_f, pn)
    if res is not None:
        return res

    res = _smooth_ai_sklearn(log_f, pn)
    if res is not None:
        return res

    log.warning(
        "PyTorch и scikit-learn недоступны — используется усиленный стандартный фильтр"
    )
    return _smooth_standard(_smooth_standard(pn))


def apply_curve_filter(points: pd.DataFrame | None, mode: str) -> pd.DataFrame | None:
    """Применяет выбранный режим очистки к каждой кривой (MeasureID, N) в DataFrame."""
    if points is None or points.empty or not mode or mode == FILTER_NONE:
        return points

    df = points.copy()
    if "PN" not in df.columns or "Freq" not in df.columns:
        return df

    group_cols = [c for c in ("MeasureID", "N") if c in df.columns]
    if not group_cols:
        group_cols = [df.index]

    for _, idx in df.groupby(group_cols, sort=False).groups.items():
        sub = df.loc[idx].sort_values("Freq")
        pn_vals = pd.to_numeric(sub["PN"], errors="coerce").to_numpy(dtype=float)
        freq_vals = pd.to_numeric(sub["Freq"], errors="coerce").to_numpy(dtype=float)

        valid = ~np.isnan(pn_vals) & ~np.isnan(freq_vals)
        if valid.sum() < 5:
            continue

        if mode == FILTER_STD:
            filtered = _smooth_standard(pn_vals[valid])
        elif mode == FILTER_AI:
            filtered = _smooth_ai(freq_vals[valid], pn_vals[valid])
        else:
            filtered = pn_vals[valid]

        pn_vals[valid] = filtered
        df.loc[sub.index, "PN"] = pn_vals

    return df
