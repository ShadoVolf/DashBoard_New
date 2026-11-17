"""Общие константы, теги и разделяемое изменяемое состояние."""
import pandas as pd

WINDOW_TAG = "protocol_manager_window"

# ---- вкладка «Создание» ----
PM_TABLE_CONTAINER = "pm_create_table_container"
PM_TABLE_TAG       = "pm_data_table"
PM_NORMS_GROUP     = "pm_norms_group"
PM_NORMS_TAG       = "pm_norms_table"
PM_STATUS_TAG      = "protocol_status_text"

# ---- вкладка «Архив протоколов» ----
PM_ARCH_TABLE_CONTAINER = "pm_arch_table_container"
PM_ARCH_TABLE_TAG       = "pm_arch_data_table"
PM_ARCH_NORMS_GROUP     = "pm_arch_norms_group"
PM_ARCH_NORMS_TAG       = "pm_arch_norms_table"
PM_ARCH_STATUS_TAG      = "pm_arch_status_text"

# ---- диалоги ----
PM_ORDER_DIALOG     = "pm_order_dialog"
PM_DATES_DIALOG     = "pm_arch_dates_dialog"
PM_CREATE_DATES_DLG = "pm_create_dates_dialog"
PM_WARN_DIALOG      = "pm_warn_dialog"
PM_INFO_DIALOG      = "pm_info_dialog"

# Сентинелы «нет фильтра» в каскаде архива
ARCH_ALL_DATES = 'Все даты'
ARCH_ALL_FILES = 'Все файлы'

# ---- разделяемое изменяемое состояние ----
_selected_numbers: dict = {}      # pos_idx -> (mid, n_raw)
_loaded_df: pd.DataFrame | None = None
_active_archive_id  = None
_active_archive_mid = None
_active_archive_psi_type = None
_suppress_cascade = False        # для «Создания»
_arch_suppress    = False        # для «Архива»