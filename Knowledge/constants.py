# -*- coding: utf-8 -*-
"""Константы модуля Knowledge (предсказание Filtr_Freq)."""

from __future__ import annotations

WIN_TAG = "knowledge_window"
STATUS_TAG = "knowledge_status"

# Cascade (как Archive / TOC)
TYPE_COMBO = "kn_type_combo"
SPC_COMBO = "kn_spc_combo"
MSK_COMBO = "kn_msk_combo"
DATE_COMBO = "kn_date_combo"
FILE_COMBO = "kn_file_combo"
MID_COMBO = "kn_mid_combo"
MID_INPUT = "kn_mid_input"
NUMBERS_INPUT = "kn_numbers_input"

# Модели
MODEL_DIR_INPUT = "kn_model_dir_input"
MODEL_TYPE_COMBO = "kn_model_type_combo"   # global / per-spc / file
MODEL_NAME_COMBO = "kn_model_name_combo"   # конкретная модель
MODEL_INFO = "kn_model_info"

# Таблица / действия
RESULT_TABLE = "kn_result_table"
RESULT_CONTAINER = "kn_result_container"
PREDICT_BTN = "kn_predict_btn"
PRINT_BTN = "kn_print_btn"
SAVE_DB_BTN = "kn_save_db_btn"
EXPORT_BTN = "kn_export_btn"
RELOAD_BTN = "kn_reload_btn"
ONLY_MISSING_CHECK = "kn_only_missing_check"

ALL_MSK = "- все МСК -"
SPC_RK731 = "РК731"
TARGET_COL = "Filtr_Freq"
REF_F_COL = "Ref_f"          # Гц в psidata
NOMINAL_COL = "Nominal"      # МГц

# Признаки по умолчанию (как в Spektr_F_leaninig)
DEFAULT_FEATURES = ["F", "R", "Q", "C0", "Cq"]
DEFAULT_FEATURES_WITH_NOM = ["F", "R", "Q", "C0", "Cq", "Nominal"]

# Колонки протокола (базовые + Filtr_Freq)
PROTOCOL_PARAMS = ("F", "R", "C0", "C1", "Q", "Filtr_Freq")
# C1 часто хранится как Cq
PARAM_ALIASES = {
    "C1": ("C1", "Cq", "Cq1"),
    "Cq": ("Cq", "C1"),
    "Filtr_Freq": ("Filtr_Freq", "filtr_freq", "FiltrFreq"),
}

# Канонические имена -> возможные имена колонок в psidata
# Используется normalize_psi_columns / resolve_column
COLUMN_ALIASES = {
    "Number": ("Number", "N", "Num", "nomer", "Номер", "number"),
    "F": ("F", "F0", "Freq", "freq"),
    "R": ("R", "R1", "Rs", "ESR"),
    "Q": ("Q", "Q0", "Ql", "QL"),
    "C0": ("C0", "C_0", "c0"),
    "Cq": ("Cq", "C1", "CQ", "cq0", "C_q", "C_1", "cq"),
    "L": ("L", "Lq", "L1", "LQ"),
    "Nominal": ("Nominal", "nominal", "Nom", "nom"),
    "Ref_f": ("Ref_f", "Ref_F", "ref_f", "REF_F"),
    "Filtr_Freq": ("Filtr_Freq", "filtr_freq", "FiltrFreq", "filtrfreq"),
    "ID": ("ID", "Id", "id"),
    "Measure_ID": ("Measure_ID", "MeasureId", "measure_id", "MID"),
    "MSK": ("MSK", "Msk", "msk"),
    "Spc": ("Spc", "SPC", "spc", "Spec"),
}

# Колонки, которые показываем в таблице результатов
TABLE_COLUMNS = (
    "Number", "F", "R", "Q", "C0", "Cq",
    "Nominal", "Filtr_Freq", "Filtr_Freq_pred",
)

DEFAULT_MODELS_SUBDIR = "models_sklearn"
