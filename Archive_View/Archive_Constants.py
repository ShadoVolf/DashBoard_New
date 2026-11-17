"""Общие константы и разделяемые состояния модуля Архив."""
from contextlib import contextmanager

# ---- теги окна ----
WINDOW_TAG = 'archive_view_window'
TABLE_GROUP = 'archive_table_group'
TABLE_CONTAINER = 'archive_table_container'
TABLE_TAG = 'archive_data_table'
NORMS_GROUP = 'archive_norms_group'
NORMS_TAG = 'archive_norms_table'

# ---- строковые константы ----
ALL_MSK = 'Все МСК'
MODE_ONLY_NUM = 'Только номер'
MODE_FULL_MSK = 'Вся МСК'

# ---- прогресс-окно ----
PROGRESS_WINDOW = 'archive_progress_window'
PROGRESS_BAR = 'archive_progress_bar'
PROGRESS_TEXT = 'archive_progress_text'
PROGRESS_DETAIL = 'archive_progress_detail'

# ---- разделяемое состояние ----
_progress_state: dict = {
    'active': False,
    'percent': 0.0,
    'message': '',
    'detail': '',
    'done': False,
    'result_df': None,
    'error': None,
    'numbers_filter': None,
    'mode': MODE_ONLY_NUM,
    'start_time': 0.0,
    'window_shown': False,
    'kind': 'numbers',           # 'numbers' | 'msk'
    'msk_results': None,
    'msk_partial': None,
}

_lookup_sync_state: dict = {
    'running': False,
    'done': False,
    'message': '',
    'error': None,
}

# ---- разделяемый режим отображения ----
_view_state: dict = {
    'mode': 'normal',        # 'normal' | 'history'
    'target_numbers': [],    # номера из выбранного замера
}

# ---- источник данных для просмотра ----
_source_state: dict = {
    'main_table': 'psidata',
    'temps_table': 'psidatatemp',
    'label': 'Основная',
}