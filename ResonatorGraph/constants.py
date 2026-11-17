"""
Общие константы: теги DPG-элементов, параметры, палитра.
"""

# ---------------------------------------------------------------------------
# DPG-теги
# ---------------------------------------------------------------------------
WIN_TAG = "resonator_graph_window"
WIN_CTRL_TAG = "resonator_graph_controls"
WIN_METRICS_TAG = "resonator_graph_metrics"
OPT_TAG = "resonator_graph_options"
ERR_TAG = "resonator_graph_error"
PLOT_TAG = "resonator_graph_plot"
X_AXIS_TAG = "resonator_graph_x"
Y_AXIS_TAG = "resonator_graph_y"
LEGEND_TAG = "rg_legend"
WIN_GRID_TAG       = "resonator_graph_grid"
TAG_GRID_INFO      = "rg_grid_info"
TAG_GRID_CONTENT   = "rg_grid_content"
TAG_GRID_REFRESH   = "rg_grid_refresh"
TAG_WHEEL_SWITCH   = "rg_wheel_switch"

TAG_TYPE = "rg_type"
TAG_SPEC = "rg_spec"
TAG_MSK = "rg_msk"
TAG_NUMBER = "rg_number"
TAG_PARAM = "rg_param"
TAG_DEGREE = "rg_degree"
TAG_A = "rg_A"
TAG_B = "rg_B"
TAG_T = "rg_T"
TAG_METRICS_GROUP = "rg_metrics_group"
TAG_MEASURE_ID = "rg_measure_id"
TAG_MEASURE_ID_LIST = "rg_measure_id_list"
TAG_MSK_MANUAL = "rg_msk_manual"

# ---------------------------------------------------------------------------
# Параметры: (ключ, отображаемое имя, столбец БД, единица измерения)
# ---------------------------------------------------------------------------
PARAMETERS = [
    ("F",    "F (без нагрузки)",  "F",    "ppm"),
    ("FL",   "FL (с нагрузкой)",  "FL",   "ppm"),
    ("R",    "R (сопротивление)", "R",    "Ом"),
    ("Mono", "Монотонность",      "Mono", "ppm"),
    ("Q",    "Добротность",       "Q",    "Qx1000"),
    ("C0",   "C0, пФ",            "C0",   "пФ"),
    ("Cq",   "Cq, фФ",            "Cq",   "фФ"),
    ("L",    "L, мГн",            "L",    "мГн"),
    ("Rb",   "Rb (сопр. моды B)", "Rb",   "Ом"),
    ("RcRb", "Rc/Rb",             None,   "-"),
]

PARAM_BY_LABEL = {p[1]: p for p in PARAMETERS}

# ---------------------------------------------------------------------------
# Палитра для серий
# ---------------------------------------------------------------------------
COLOR_POINTS = (220, 30, 30)     # красный
COLOR_APPROX = (0, 160, 0)       # зелёный

COLORS = [
    (220,  30,  30), ( 30, 160,  30), ( 40,  40, 220), (220, 180,  30),
    ( 30, 180, 180), (200,  40, 180), (220, 130,  40), (140,  60, 200),
    (  0, 130, 130), (140, 140,  40), (140,  30,  30), (  0, 110,   0),
]

# Цвета ролей
COLOR_MONO   = (0, 90, 200)
COLOR_JUMP   = (200, 140, 0)
COLOR_KDE    = (40, 90, 220)

# ---------------------------------------------------------------------------
# Источник данных (аналог Archive_Constants._source_state)
# ---------------------------------------------------------------------------
SOURCES = [
    ('Основная',  'psidata',           'psidatatemp'),
    ('Временная', 'psidata_temporary', 'psidatatemp_temporary'),
    ('Архивная',  'psidata_archive',   'psidatatemp_archive'),
]

_source_state: dict = {
    'main_table':  'psidata',
    'temps_table': 'psidatatemp',
    'label':       'Основная',
}

TAG_LOCK_SCALE = "rg_lock_scale"


def get_main_table() -> str:
    return _source_state['main_table']


def get_temps_table() -> str:
    return _source_state['temps_table']


def set_source(label: str) -> bool:
    for lb, main_t, temps_t in SOURCES:
        if lb == label:
            _source_state['main_table']  = main_t
            _source_state['temps_table'] = temps_t
            _source_state['label']       = lb
            return True
    return False