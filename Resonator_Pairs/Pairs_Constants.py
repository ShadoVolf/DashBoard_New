"""Общие константы и разделяемое состояние модуля формирования пар."""

WINDOW_TAG            = 'resonator_pairs_window'
SEARCH_CONTAINER      = 'rp_search_container'
POOL_CONTAINER        = 'rp_pool_container'
PAIRS_CONTAINER       = 'rp_pairs_container'
PRINT_PAIRS_CONTAINER = 'rp_print_pairs_container'   # <-- новое

# Ключи состояния
_state: dict = {
    'search_df':        None,
    'pool_df':          None,
    'pairs_df':         None,
    'pair_checks':      {},
    'print_pairs_df':   None,      # <-- новое: пары из БД
    'print_pair_checks': {},       # <-- новое: галочки печати
}

# Имена алгоритмов (ключи)
ALGO_MAX_COUNT = 'max_count'
ALGO_MIN_DIFF  = 'min_diff'

ALGO_LABELS = {
    ALGO_MAX_COUNT: 'Максимум пар',
    ALGO_MIN_DIFF:  'Максимум пар с минимальной разницей',
}

# --- прогресс формирования пар (разделяемое состояние) ---
_pairs_progress: dict = {
    'active': False,
    'done': False,
    'percent': 0.0,
    'message': '',
    'result_df': None,
    'stats': None,
    'error': None,
    'start_time': 0.0,
    'spec1': None,
    'spec2': None,
    'use_f': False,
    'use_r': False,
    'max_ppm': 0.0,
    'max_ohm': 0.0,
    'target_delta_f': 0.0,
    'max_pairs': 0,
    'algorithm': None,
}