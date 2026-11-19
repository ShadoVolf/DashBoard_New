"""Константы модуля ФШ. Соответствуют C++ PhazeNoise.cpp."""

WINDOW_TAG         = "phase_noise_window"
TABLE_CONTAINER    = "phase_noise_table_container"
TABLE_TAG          = "phase_noise_table"
GRAPH_CONTAINER    = "phase_noise_graph_container"
GRAPH_IMAGE_TAG    = "phase_noise_graph_image"
INFO_PANEL_TAG     = "phase_noise_info_panel"
NORMS_GROUP        = "phase_noise_norms_group"
STATUS_TEXT_TAG    = "phase_noise_status_text"

# Отстройка -> поле данных в phaze_noise (как в edtNumberChange)
OFFSET_TO_FIELD = {
    1:        "Shum1",
    3:        "Shum3",
    10:       "Shum10",
    50:       "Shum50",
    100:      "Shum100",
    1000:     "Shum1K",
    10000:    "Shum10K",
    100000:   "Shum100K",
    1000000:  "Shum1M",
}

# Пять норм: (флаг, min-поле, max-поле, поле отстройки, номер маркера в SubTitle)
NORM_DEFS = [
    ("Shum",  "ShMin",  "ShMax",  "ShOT",  1),
    ("Shum1", "Sh1Min", "Sh1Max", "Sh1OT", 2),
    ("Shum2", "Sh2Min", "Sh2Max", "Sh2OT", 3),
    ("Shum3", "Sh3Min", "Sh3Max", "Sh3OT", 4),
    ("Shum4", "Sh4Min", "Sh4Max", "Sh4OT", 5),
]

ALL_MSK_LABEL   = "<все МСК>"
ALL_MEAS_LABEL  = "<все ID>"
NO_RESONATOR    = "<любой>"

STATUS_OK   = "Годен"
STATUS_FAIL = "Брак"

# Цвета точек норм (как Series3..Series6 в DFM)
NORM_COLORS = ["teal", "blue", "green", "purple", "orange"]
