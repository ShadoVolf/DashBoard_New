"""Константы модуля TempOutlier_Correction."""

from __future__ import annotations

# DPG tags
WIN_TAG = "toc_window"
LEFT_PANEL = "toc_left"
RIGHT_PANEL = "toc_right"
STATUS_TAG = "toc_status"
MSK_INPUT = "toc_msk_input"
MSK_COMBO = "toc_msk_combo"
MID_LIST = "toc_mid_list"
SELECTED_LIST = "toc_selected_list"
PARAM_COMBO = "toc_param_combo"
NUMBER_COMBO = "toc_number_combo"
PLOT_TAG = "toc_plot"
X_AXIS_TAG = "toc_x_axis"
Y_AXIS_TAG = "toc_y_axis"
PLOT_CONTAINER = "toc_plot_container"
SUMMARY_TABLE = "toc_summary_table"
SUMMARY_CONTAINER = "toc_summary_container"
BIG_WIN_TAG = "toc_big_graph_window"
BIG_CONTAINER = "toc_big_container"
PLOT_TAG_BIG = "toc_plot_big"
X_AXIS_TAG_BIG = "toc_x_big"
Y_AXIS_TAG_BIG = "toc_y_big"
PROGRESS_TAG = "toc_progress"
LOG_TAG = "toc_log"

# Параметры, по которым ищем выбросы по умолчанию
OUTLIER_PARAMS = ("F", "R")

# Все измеримые колонки температурной таблицы
MEASURABLE_COLS = (
    "F", "R", "Rb", "C0", "Cq", "L", "Q",
    "FL", "Mono", "RC_Rb", "F_int", "Spur", "SpurR",
)

OUTLIER_MARKER = 100000.0
MAD_K = 3.0  # robust threshold: |x - median| > MAD_K * 1.4826 * MAD

# Цвета серий (измерения + corrected)
SERIES_COLORS = [
    (255, 85, 85, 255),
    (85, 170, 255, 255),
    (85, 255, 170, 255),
    (255, 200, 85, 255),
    (200, 85, 255, 255),
    (255, 85, 200, 255),
    (170, 255, 85, 255),
    (85, 255, 255, 255),
    (255, 140, 80, 255),
    (140, 140, 255, 255),
]
COLOR_CORRECTED = (255, 255, 80, 255)  # жёлтый — скорректированная кривая

# Источники данных
SOURCES = [
    ("Основная", "psidata", "psidatatemp"),
    ("Временная", "psidata_temporary", "psidatatemp_temporary"),
    ("Архивная", "psidata_archive", "psidatatemp_archive"),
]

# Сводные метрики (зависят от F/R по температурам)
SUMMARY_METRICS = [
    "Fmax", "Fmin", "Fptp", "Fptp/2",
    "Rmax", "Rmin", "Rptp",
    "Mono", "Slope",
    "Tmax", "Tmin", "Turnover",
]
