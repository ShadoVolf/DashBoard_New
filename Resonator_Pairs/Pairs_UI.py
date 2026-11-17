"""UI-сборка модуля формирования пар."""
import pandas as pd
import dearpygui.dearpygui as dpg

from Archive_View.Archive_Data import (
    get_archive_types, get_archive_specs_by_type,
    get_archive_msk_list, get_archive_dates_list,
    get_archive_files_list, load_archive_data,
    parse_numbers_input, load_archive_by_numbers,
)

from .Pairs_Constants import (
    WINDOW_TAG, SEARCH_CONTAINER, POOL_CONTAINER, PAIRS_CONTAINER,
    PRINT_PAIRS_CONTAINER,
    ALGO_MAX_COUNT, ALGO_MIN_DIFF, ALGO_LABELS, _state,
    _pairs_progress,
)
from .Pairs_Data import (
    add_measurement_to_pool, clear_pool, load_pool, reset_used_in_pool,
    save_pairs_to_db, load_pairs_from_db,
)
from .Pairs_Algorithm import form_pairs
from .Pairs_DDL import log_operation
from .Pairs_Export import (
    export_pairs_xls, export_pairs_pdf, open_file,
)


# ============================================================================
# Экранная замена спецсимволов (аналогично Archive_UI)
# ============================================================================
try:
    from Archive_View.Archive_UI import _screen_safe
except ImportError:
    def _screen_safe(v):
        if v is None:
            return ''
        try:
            if pd.isna(v):
                return ''
        except Exception:
            pass
        return str(v)


# Читаемые заголовки столбцов таблицы пар
_SCREEN_PAIR_COLS = {
    'measure_id_1':    'ID1',
    'measure_id_2':    'ID2',
    'n_1':             'N1',
    'n_2':             'N2',
    'spc_1':           'Spc1',
    'spc_2':           'Spc2',
    'msk_1':           'MSK1',
    'msk_2':           'MSK2',
    'f_1':             'F1',
    'f_2':             'F2',
    'r_1':             'R1',
    'r_2':             'R2',
    'signed_delta_f':  'F1-F2, ppm',
    'delta_f':         'dF, ppm',
    'dev_from_target': 'dF от цели',
    'delta_r':         'dR, Ohm',
    'created_at':      'Дата',
    'created_by':      'Оператор',
}


# =============================================================================
# Поиск (упрощённый каскад: Measure_ID | Numbers | фильтры)
# =============================================================================
def _on_type_changed(sender=None, data=None):
    rtype = dpg.get_value('rp_type_combo')
    specs = get_archive_specs_by_type(rtype) if rtype else []
    dpg.configure_item('rp_spc_combo', items=specs)
    if specs:
        dpg.set_value('rp_spc_combo', specs[0])
    _on_spc_changed()


def _on_spc_changed(sender=None, data=None):
    spc = dpg.get_value('rp_spc_combo')
    msks = get_archive_msk_list(spc if spc else None)
    dpg.configure_item('rp_msk_combo', items=msks)
    if msks:
        dpg.set_value('rp_msk_combo', msks[0])
    _on_msk_changed()


def _on_msk_changed(sender=None, data=None):
    msk = dpg.get_value('rp_msk_combo')
    spc = dpg.get_value('rp_spc_combo')
    dates = get_archive_dates_list(msk if msk else None,
                                   spc if spc else None)
    dpg.configure_item('rp_date_combo', items=dates)
    if dates:
        dpg.set_value('rp_date_combo', dates[0])
    _on_date_changed()


def _on_date_changed(sender=None, data=None):
    msk = dpg.get_value('rp_msk_combo')
    spc = dpg.get_value('rp_spc_combo')
    date = dpg.get_value('rp_date_combo')
    files = get_archive_files_list(msk if msk else None,
                                   spc if spc else None,
                                   date if date else None)
    dpg.configure_item('rp_file_combo', items=files)
    if files:
        dpg.set_value('rp_file_combo', files[0])


def _on_search():
    mid_str = (dpg.get_value('rp_measure_id_input') or '').strip()
    numbers_str = (dpg.get_value('rp_numbers_input') or '').strip()

    df = pd.DataFrame()

    if mid_str.isdigit() and int(mid_str) > 0:
        df = load_archive_data(measure_id=int(mid_str), only_good=False)
    elif numbers_str:
        numbers = parse_numbers_input(numbers_str)
        if numbers:
            df = load_archive_by_numbers(numbers, mode='Только номер')
    else:
        msk = dpg.get_value('rp_msk_combo') or None
        spc = dpg.get_value('rp_spc_combo') or None
        date = dpg.get_value('rp_date_combo') or None
        file = dpg.get_value('rp_file_combo') or None
        if not any((msk, spc, date, file)):
            dpg.set_value('rp_status_text',
                          'Задайте фильтры или ID замера')
            return
        df = load_archive_data(msk=msk, spc=spc, date=date, file=file)

    _state['search_df'] = df

    n = 0 if df is None or df.empty else len(df)
    n_mids = (df['Measure_ID'].nunique()
              if not df.empty and 'Measure_ID' in df.columns else 0)
    dpg.set_value('rp_status_text',
                  f'Найдено записей: {n} | замеров: {n_mids}')
    _fill_search_table(df)


def _fill_search_table(df: pd.DataFrame):
    if dpg.does_item_exist(SEARCH_CONTAINER):
        for ch in dpg.get_item_children(SEARCH_CONTAINER, 1) or []:
            dpg.delete_item(ch)

    if df is None or df.empty:
        dpg.add_text('- нет данных -', parent=SEARCH_CONTAINER,
                     color=(140, 140, 140))
        return

    cols = [c for c in ('Measure_ID', 'N', 'Position', 'Spc', 'MSK',
                        'F', 'R', 'Status2') if c in df.columns]

    with dpg.table(parent=SEARCH_CONTAINER, header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True,
                   scrollY=True, scrollX=True, height=260,
                   policy=dpg.mvTable_SizingFixedFit):
        for c in cols:
            dpg.add_table_column(label=c)
        for _, row in df.head(1000).iterrows():
            with dpg.table_row():
                for c in cols:
                    v = row.get(c, '')
                    if pd.isna(v):
                        v = ''
                    dpg.add_text(_screen_safe(v))


# =============================================================================
# Добавление в пул
# =============================================================================
def _on_add_to_pool():
    df = _state.get('search_df')
    if df is None or df.empty:
        dpg.set_value('rp_status_text',
                      'Нет данных — сначала выполните поиск')
        return
    if 'Measure_ID' not in df.columns:
        dpg.set_value('rp_status_text', 'В данных нет Measure_ID')
        return

    mids = df['Measure_ID'].dropna().unique()
    if not len(mids):
        return

    total = 0
    for mid in mids:
        total += add_measurement_to_pool(int(mid))

    dpg.set_value('rp_status_text',
                  f'В пул добавлено: {total} резонаторов '
                  f'из {len(mids)} замеров')
    _reload_pool_view()


# =============================================================================
# Пул
# =============================================================================
def _reload_pool_view():
    pool = load_pool()
    _state['pool_df'] = pool

    if dpg.does_item_exist(POOL_CONTAINER):
        for ch in dpg.get_item_children(POOL_CONTAINER, 1) or []:
            dpg.delete_item(ch)

    free = (pool[pool['status'] == 'free']
            if not pool.empty and 'status' in pool.columns
            else pool)

    if free.empty:
        dpg.add_text('- пул пуст -', parent=POOL_CONTAINER,
                     color=(140, 140, 140))
    else:
        dpg.add_text(f'Свободных резонаторов: {len(free)}',
                     parent=POOL_CONTAINER, color=(200, 220, 255))

        cols = [c for c in ('id', 'measure_id', 'spc', 'msk',
                            'n_normalized', 'f_value', 'r_value')
                if c in free.columns]
        with dpg.table(parent=POOL_CONTAINER, header_row=True,
                       borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True,
                       scrollY=True, scrollX=True, height=200,
                       policy=dpg.mvTable_SizingFixedFit):
            for c in cols:
                dpg.add_table_column(label=c)
            for _, row in free.head(500).iterrows():
                with dpg.table_row():
                    for c in cols:
                        v = row.get(c, '')
                        if pd.isna(v):
                            v = ''
                        elif isinstance(v, float):
                            v = f'{v:.6g}'
                        dpg.add_text(_screen_safe(v))

    # Обновить списки спецификаций
    if not free.empty and 'spc' in free.columns:
        specs = sorted(str(s) for s in free['spc'].dropna().unique() if s)
        dpg.configure_item('rp_spec1_combo', items=specs)
        dpg.configure_item('rp_spec2_combo', items=specs)
        if specs:
            if not dpg.get_value('rp_spec1_combo'):
                dpg.set_value('rp_spec1_combo', specs[0])
            if not dpg.get_value('rp_spec2_combo'):
                dpg.set_value('rp_spec2_combo',
                              specs[-1] if len(specs) > 1 else specs[0])

    dpg.set_value('rp_pool_count', f'Свободных: {len(free)}')
    _update_spec_counts()


def _update_spec_counts():
    pool = _state.get('pool_df')
    if pool is None or pool.empty or 'spc' not in pool.columns:
        if dpg.does_item_exist('rp_spec_counts'):
            dpg.set_value('rp_spec_counts', 'Пул: пуст')
        return

    free = (pool[pool['status'] == 'free']
            if 'status' in pool.columns else pool)
    total = len(free)

    spec1 = dpg.get_value('rp_spec1_combo') or ''
    spec2 = dpg.get_value('rp_spec2_combo') or ''

    n1 = int((free['spc'] == spec1).sum()) if spec1 else 0
    n2 = int((free['spc'] == spec2).sum()) if spec2 else 0
    possible = n1 * n2

    msg = (f'Пул free: {total}   |   '
           f'Spc1: {n1}   |   Spc2: {n2}   |   '
           f'возможных пар: {possible}')
    if dpg.does_item_exist('rp_spec_counts'):
        dpg.set_value('rp_spec_counts', msg)
    print(f'[Pairs] {msg}')


def _on_spec_selection_changed(sender=None, data=None):
    _update_spec_counts()


def _on_clear_pool():
    n = clear_pool()
    dpg.set_value('rp_status_text',
                  f'Очищено (свободные): {n}')
    _reload_pool_view()


def _on_reset_used():
    n = reset_used_in_pool()
    dpg.set_value('rp_status_text',
                  f'Возвращено в пул (used->free): {n}')
    _reload_pool_view()


# =============================================================================
# Формирование пар
# =============================================================================
def _on_form_pairs():
    pool = _state.get('pool_df')
    if pool is None or pool.empty:
        pool = load_pool()
        _state['pool_df'] = pool
    if pool is None or pool.empty:
        dpg.set_value('rp_status_text', 'Пул пуст')
        return

    spec1 = dpg.get_value('rp_spec1_combo')
    spec2 = dpg.get_value('rp_spec2_combo')
    if not spec1 or not spec2:
        dpg.set_value('rp_status_text',
                      'Выберите обе спецификации')
        return
    if spec1 == spec2:
        dpg.set_value('rp_status_text',
                      'Спецификации должны различаться')
        return

    use_f = dpg.get_value('rp_use_f_check')
    use_r = dpg.get_value('rp_use_r_check')
    if not use_f and not use_r:
        dpg.set_value('rp_status_text',
                      'Выберите хотя бы один параметр (F или R)')
        return

    try:
        max_ppm = float(dpg.get_value('rp_max_ppm_input') or 0.5)
        max_ohm = float(dpg.get_value('rp_max_ohm_input') or 5.0)
        max_pairs = int(dpg.get_value('rp_max_pairs_input') or 100)
        target_delta_f = float(
            dpg.get_value('rp_target_delta_f_input') or 0.0)
    except (TypeError, ValueError):
        dpg.set_value('rp_status_text', 'Некорректные параметры')
        return

    if max_ppm < 0:
        dpg.set_value('rp_status_text',
                      'dF max должен быть >= 0')
        return
    if max_ohm < 0:
        dpg.set_value('rp_status_text',
                      'dR max должен быть >= 0')
        return
    if max_pairs < 1:
        dpg.set_value('rp_status_text', 'Требуемое число пар >= 1')
        return

    _algo_disp = (dpg.get_value('rp_algorithm_radio')
                  or ALGO_LABELS[ALGO_MAX_COUNT])
    algorithm = (ALGO_MAX_COUNT
                 if _algo_disp == ALGO_LABELS[ALGO_MAX_COUNT]
                 else ALGO_MIN_DIFF)

    if _pairs_progress.get('active'):
        dpg.set_value('rp_status_text',
                      'Формирование уже идёт...')
        return

    import time
    _pairs_progress.update({
        'active': True, 'done': False, 'percent': 0.0,
        'message': 'Запуск...', 'result_df': None,
        'stats': None, 'error': None,
        'start_time': time.time(),
        'spec1': spec1, 'spec2': spec2,
        'use_f': use_f, 'use_r': use_r,
        'max_ppm': max_ppm, 'max_ohm': max_ohm,
        'target_delta_f': target_delta_f,
        'max_pairs': max_pairs, 'algorithm': algorithm,
    })

    if dpg.does_item_exist('rp_progress_bar'):
        dpg.configure_item('rp_progress_bar', show=True)
        dpg.set_value('rp_progress_bar', 0.0)
    if dpg.does_item_exist('rp_progress_text'):
        dpg.set_value('rp_progress_text', 'Запуск...')

    dpg.set_value('rp_status_text', 'Формирование пар...')

    free = (pool[pool['status'] == 'free']
            if 'status' in pool.columns else pool)
    print(f"\n[Pairs] === Запуск формирования ===")
    print(f"[Pairs] spec1={spec1!r}, spec2={spec2!r}")
    print(f"[Pairs] use_f={use_f} (max_ppm={max_ppm}, "
          f"target_delta_f={target_delta_f:+.3f}), "
          f"use_r={use_r} (max_ohm={max_ohm})")
    print(f"[Pairs] max_pairs={max_pairs}, algorithm={algorithm}")
    print(f"[Pairs] Пул: всего {len(pool)}, free {len(free)}")
    if 'spc' in free.columns:
        for spc in free['spc'].dropna().unique():
            cnt = int((free['spc'] == spc).sum())
            print(f"[Pairs]   spc={spc!r}: {cnt}")
    n1 = int((free['spc'] == spec1).sum()) if 'spc' in free.columns else 0
    n2 = int((free['spc'] == spec2).sum()) if 'spc' in free.columns else 0
    print(f"[Pairs] Возможных пар: {n1} x {n2} = {n1 * n2}")
    print(f"[Pairs] Целевая разница F1-F2: {target_delta_f:+.3f} ppm "
          f"(допуск +/- {max_ppm})")

    import threading
    threading.Thread(
        target=_form_worker,
        args=(pool, spec1, spec2, use_f, use_r,
              max_ppm, max_ohm, target_delta_f, max_pairs, algorithm),
        daemon=True,
    ).start()

    dpg.set_frame_callback(
        dpg.get_frame_count() + 1, _poll_form_progress)


def _form_worker(pool, spec1, spec2, use_f, use_r,
                 max_ppm, max_ohm, target_delta_f, max_pairs, algorithm):
    try:
        def _cb(done, total, msg):
            _pairs_progress['percent'] = (
                done / total * 100.0 if total else 0.0)
            _pairs_progress['message'] = msg

        pairs, stats = form_pairs(
            pool, spec1, spec2, use_f, use_r,
            max_ppm=max_ppm, max_ohm=max_ohm,
            max_pairs=max_pairs,
            target_delta_f=target_delta_f,
            algorithm=algorithm,
            progress_callback=_cb)
        _pairs_progress['result_df'] = pairs
        _pairs_progress['stats'] = stats
        _pairs_progress['percent'] = 100.0
        _pairs_progress['message'] = 'Готово'
        _pairs_progress['done'] = True
    except Exception as e:
        import traceback
        traceback.print_exc()
        _pairs_progress['error'] = str(e)
        _pairs_progress['done'] = True


def _poll_form_progress():
    if not _pairs_progress.get('active'):
        return

    if dpg.does_item_exist('rp_progress_bar'):
        p = max(0.0, min(1.0,
                         _pairs_progress.get('percent', 0.0) / 100.0))
        dpg.set_value('rp_progress_bar', p)
    if dpg.does_item_exist('rp_progress_text'):
        dpg.set_value('rp_progress_text',
                      _pairs_progress.get('message', ''))

    if _pairs_progress.get('done'):
        _finish_form_progress()
        return

    dpg.set_frame_callback(
        dpg.get_frame_count() + 1, _poll_form_progress)


def _finish_form_progress():
    _pairs_progress['active'] = False

    if dpg.does_item_exist('rp_progress_bar'):
        dpg.configure_item('rp_progress_bar', show=False)
    if dpg.does_item_exist('rp_progress_text'):
        dpg.set_value('rp_progress_text', '')

    if _pairs_progress.get('error'):
        msg = f"Ошибка формирования: {_pairs_progress['error']}"
        print(f"[Pairs] {msg}")
        dpg.set_value('rp_status_text', msg)
        return

    pairs = _pairs_progress.get('result_df')
    stats = _pairs_progress.get('stats') or {}
    spec1 = _pairs_progress.get('spec1')
    spec2 = _pairs_progress.get('spec2')

    print(f"\n[Pairs] === Результат формирования пар ===")
    print(f"[Pairs] Пул: всего {stats.get('pool_total', 0)}, "
          f"free {stats.get('pool_free', 0)}")
    print(f"[Pairs] spec1={spec1!r}: {stats.get('spec1_count', 0)}")
    print(f"[Pairs] spec2={spec2!r}: {stats.get('spec2_count', 0)}")
    checked = (stats.get('spec1_count', 0)
               * stats.get('spec2_count', 0))
    print(f"[Pairs] Проверено пар: {checked}")
    target = stats.get('target_delta_f', 0.0)
    print(f"[Pairs] Целевая разница F1-F2: {target:+.3f} ppm "
          f"(допуск +/- {stats.get('max_ppm', 0)})")
    print(f"[Pairs] Отсеяно по F (NaN): {stats.get('rejected_f_nan', 0)}")
    print(f"[Pairs] Отсеяно по F (откл. от цели > max): "
          f"{stats.get('rejected_f_ppm', 0)}")
    print(f"[Pairs] Отсеяно по R (NaN): {stats.get('rejected_r_nan', 0)}")
    print(f"[Pairs] Отсеяно по R (Ohm > max): "
          f"{stats.get('rejected_r_ohm', 0)}")
    print(f"[Pairs] Кандидатов: {stats.get('candidates', 0)}")
    print(f"[Pairs] Отобрано (итог): {stats.get('selected', 0)}")
    if stats.get('error'):
        print(f"[Pairs] ERROR: {stats['error']}")
    print(f"[Pairs] =====================================\n")

    _state['pairs_df'] = pairs

    if stats.get('error'):
        print(f"[Pairs] Причина: {stats['error']}")

    if pairs is None or pairs.empty:
        dpg.set_value(
            'rp_status_text',
            stats.get('error')
            or f'Пары не сформированы '
               f'(кандидатов {stats.get("candidates", 0)})')
        _fill_pairs_table(None)
        return

    dpg.set_value('rp_status_text',
                  f'Сформировано пар: {len(pairs)} '
                  f'(из {stats.get("candidates", 0)} кандидатов)')
    _fill_pairs_table(pairs)


# =============================================================================
# Таблица сформированных пар (в памяти)
# =============================================================================
def _fill_pairs_table(pairs: pd.DataFrame | None):
    if dpg.does_item_exist(PAIRS_CONTAINER):
        for ch in dpg.get_item_children(PAIRS_CONTAINER, 1) or []:
            dpg.delete_item(ch)

    _state['pair_checks'] = {}

    if pairs is None or pairs.empty:
        dpg.add_text('- нет пар -', parent=PAIRS_CONTAINER,
                     color=(140, 140, 140))
        return

    cols = [c for c in (
        'measure_id_1', 'n_1', 'spc_1', 'f_1', 'r_1',
        'measure_id_2', 'n_2', 'spc_2', 'f_2', 'r_2',
        'signed_delta_f', 'dev_from_target', 'delta_r',
    ) if c in pairs.columns]

    with dpg.table(parent=PAIRS_CONTAINER, header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True,
                   scrollY=True, scrollX=True, height=300,
                   policy=dpg.mvTable_SizingFixedFit):
        dpg.add_table_column(label='[V]')
        for c in cols:
            dpg.add_table_column(label=_SCREEN_PAIR_COLS.get(c, c))

        for idx, row in pairs.reset_index(drop=True).iterrows():
            ch_tag = f'rp_pair_chk_{idx}'
            _state['pair_checks'][idx] = ch_tag
            with dpg.table_row():
                dpg.add_checkbox(tag=ch_tag, default_value=True)
                for c in cols:
                    v = row.get(c, '')
                    if pd.isna(v):
                        v = ''
                    elif c in ('measure_id_1', 'measure_id_2'):
                        try:
                            v = str(int(v))
                        except (TypeError, ValueError):
                            v = str(v)
                    elif isinstance(v, float):
                        v = f'{v:.6g}'
                    dpg.add_text(_screen_safe(v))


# =============================================================================
# Сохранение / экспорт сформированных пар
# =============================================================================
def _on_save_pairs():
    pairs = _state.get('pairs_df')
    if pairs is None or pairs.empty:
        dpg.set_value('rp_status_text', 'Нет пар для сохранения')
        return

    checks = _state.get('pair_checks', {})
    selected_idx = []
    for idx, tag in checks.items():
        try:
            if dpg.get_value(tag):
                selected_idx.append(idx)
        except Exception:
            pass

    if not selected_idx:
        dpg.set_value('rp_status_text',
                      'Не выбрано ни одной пары')
        return

    to_save = pairs.reset_index(drop=True).loc[selected_idx]
    n = save_pairs_to_db(to_save.reset_index(drop=True))

    dpg.set_value('rp_status_text', f'Сохранено пар в БД: {n}')
    _state['pairs_df'] = None
    _state['pair_checks'] = {}
    _fill_pairs_table(None)
    _reload_pool_view()


def _on_export_xls():
    pairs = _state.get('pairs_df')
    if pairs is None or pairs.empty:
        dpg.set_value('rp_status_text', 'Нет пар для экспорта')
        return
    spec1 = dpg.get_value('rp_spec1_combo')
    spec2 = dpg.get_value('rp_spec2_combo')
    try:
        target = float(dpg.get_value('rp_target_delta_f_input') or 0.0)
        max_ppm = float(dpg.get_value('rp_max_ppm_input') or 0.5)
    except (TypeError, ValueError):
        target, max_ppm = 0.0, 0.5
    header = {
        'Спецификация 1': spec1,
        'Спецификация 2': spec2,
        'Алгоритм': dpg.get_value('rp_algorithm_radio') or '',
        'Целевая разница F1-F2': f'{target:+.3f} ppm',
        'Допуск по F': f'+/- {max_ppm} ppm',
    }
    path = export_pairs_xls(pairs, header)
    if path:
        dpg.set_value('rp_status_text', f'XLS: {path}')
        print(f"[Pairs] Открываю XLS: {path}")
        open_file(path)


def _on_export_pdf():
    pairs = _state.get('pairs_df')
    if pairs is None or pairs.empty:
        dpg.set_value('rp_status_text', 'Нет пар для экспорта')
        return
    try:
        target = float(dpg.get_value('rp_target_delta_f_input') or 0.0)
        max_ppm = float(dpg.get_value('rp_max_ppm_input') or 0.5)
    except (TypeError, ValueError):
        target, max_ppm = 0.0, 0.5
    header = {
        'Спецификация 1': dpg.get_value('rp_spec1_combo'),
        'Спецификация 2': dpg.get_value('rp_spec2_combo'),
        'Целевая разница F1-F2': f'{target:+.3f} ppm',
        'Допуск по F': f'+/- {max_ppm} ppm',
    }
    path = export_pairs_pdf(pairs, header)
    if path:
        dpg.set_value('rp_status_text', f'PDF: {path}')
        print(f"[Pairs] Открываю PDF: {path}")
        open_file(path)


# =============================================================================
# Печать сохранённых пар из БД (последние N / по дате / галочками)
# =============================================================================
def _on_load_pairs_last():
    try:
        n = int(dpg.get_value('rp_load_last_n_input') or 100)
    except (TypeError, ValueError):
        dpg.set_value('rp_print_status_text',
                      'Некорректное число пар')
        return
    if n < 1:
        dpg.set_value('rp_print_status_text',
                      'Число пар должно быть >= 1')
        return

    df = load_pairs_from_db(limit=n)
    _state['print_pairs_df'] = df
    _fill_print_pairs_table(df)

    if df is not None and not df.empty:
        dpg.set_value('rp_print_status_text',
                      f'Загружено {len(df)} последних пар')
    else:
        dpg.set_value('rp_print_status_text',
                      'Пар не найдено')


def _on_load_pairs_by_date():
    df_from = (dpg.get_value('rp_load_date_from_input') or '').strip()
    df_to = (dpg.get_value('rp_load_date_to_input') or '').strip()

    if not df_from and not df_to:
        dpg.set_value('rp_print_status_text',
                      'Задайте хотя бы одну дату')
        return

    df = load_pairs_from_db(
        date_from=df_from if df_from else None,
        date_to=df_to if df_to else None,
    )
    _state['print_pairs_df'] = df
    _fill_print_pairs_table(df)

    if df is not None and not df.empty:
        dpg.set_value('rp_print_status_text',
                      f'Загружено {len(df)} пар за период')
    else:
        dpg.set_value('rp_print_status_text',
                      'Пар не найдено')


def _on_load_pairs_all():
    df = load_pairs_from_db()
    _state['print_pairs_df'] = df
    _fill_print_pairs_table(df)

    if df is not None and not df.empty:
        dpg.set_value('rp_print_status_text',
                      f'Загружено {len(df)} пар')
    else:
        dpg.set_value('rp_print_status_text',
                      'Пар не найдено')


def _fill_print_pairs_table(df: pd.DataFrame | None):
    if dpg.does_item_exist(PRINT_PAIRS_CONTAINER):
        for ch in dpg.get_item_children(PRINT_PAIRS_CONTAINER, 1) or []:
            dpg.delete_item(ch)

    _state['print_pair_checks'] = {}

    if df is None or df.empty:
        dpg.add_text('- нет сохранённых пар -',
                     parent=PRINT_PAIRS_CONTAINER,
                     color=(140, 140, 140))
        return

    cols = [c for c in (
        'measure_id_1', 'n_1', 'spc_1', 'f_1', 'r_1',
        'measure_id_2', 'n_2', 'spc_2', 'f_2', 'r_2',
        'signed_delta_f', 'delta_r',
        'created_at', 'created_by',
    ) if c in df.columns]

    with dpg.table(parent=PRINT_PAIRS_CONTAINER, header_row=True,
                   borders_innerH=True, borders_outerH=True,
                   borders_innerV=True, borders_outerV=True,
                   scrollY=True, scrollX=True, height=250,
                   policy=dpg.mvTable_SizingFixedFit):
        dpg.add_table_column(label='[V]')
        for c in cols:
            dpg.add_table_column(label=_SCREEN_PAIR_COLS.get(c, c))

        for _, row in df.reset_index(drop=True).iterrows():
            try:
                pair_id = int(row.get('id', 0))
            except (TypeError, ValueError):
                pair_id = 0
            ch_tag = f'rp_print_chk_{pair_id}'
            _state['print_pair_checks'][pair_id] = ch_tag

            with dpg.table_row():
                dpg.add_checkbox(tag=ch_tag, default_value=True)
                for c in cols:
                    v = row.get(c, '')
                    if pd.isna(v):
                        v = ''
                    elif c in ('measure_id_1', 'measure_id_2'):
                        try:
                            v = str(int(v))
                        except (TypeError, ValueError):
                            v = str(v)
                    elif isinstance(v, float):
                        v = f'{v:.6g}'
                    dpg.add_text(_screen_safe(v))


def _on_check_all_print():
    for _, tag in _state.get('print_pair_checks', {}).items():
        try:
            dpg.set_value(tag, True)
        except Exception:
            pass


def _on_uncheck_all_print():
    for _, tag in _state.get('print_pair_checks', {}).items():
        try:
            dpg.set_value(tag, False)
        except Exception:
            pass


def _get_selected_print_pairs():
    df = _state.get('print_pairs_df')
    if df is None or df.empty:
        return None

    checks = _state.get('print_pair_checks', {})
    selected_ids = []
    for pair_id, tag in checks.items():
        try:
            if dpg.get_value(tag):
                selected_ids.append(pair_id)
        except Exception:
            pass

    if not selected_ids:
        return None

    return df[df['id'].isin(selected_ids)].copy()


def _on_print_saved_pdf():
    to_print = _get_selected_print_pairs()
    if to_print is None or to_print.empty:
        dpg.set_value('rp_print_status_text',
                      'Не выбрано ни одной пары для печати')
        return

    header = {
        'Источник': 'Сохранённые пары из БД',
        'Количество пар': str(len(to_print)),
        'Дата печати': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
    }
    path = export_pairs_pdf(to_print, header)
    if path:
        dpg.set_value('rp_print_status_text', f'PDF: {path}')
        print(f"[Pairs] Печать PDF из БД: {path}")
        open_file(path)


def _on_print_saved_xls():
    to_print = _get_selected_print_pairs()
    if to_print is None or to_print.empty:
        dpg.set_value('rp_print_status_text',
                      'Не выбрано ни одной пары для экспорта')
        return

    header = {
        'Источник': 'Сохранённые пары из БД',
        'Количество пар': str(len(to_print)),
        'Дата экспорта': pd.Timestamp.now().strftime('%Y-%m-%d %H:%M'),
    }
    path = export_pairs_xls(to_print, header)
    if path:
        dpg.set_value('rp_print_status_text', f'XLS: {path}')
        print(f"[Pairs] Экспорт XLS из БД: {path}")
        open_file(path)


# =============================================================================
# Сборка фильтр-бара и панелей
# =============================================================================
def _build_filter_bar():
    with dpg.group(horizontal=True):
        with dpg.group(width=160):
            dpg.add_text("Тип резонатора")
            dpg.add_combo([], tag='rp_type_combo', width=160,
                          callback=_on_type_changed)
        with dpg.group(width=200):
            dpg.add_text("Спецификация")
            dpg.add_combo([], tag='rp_spc_combo', width=200,
                          callback=_on_spc_changed)
        with dpg.group(width=160):
            dpg.add_text("МСК")
            dpg.add_combo([], tag='rp_msk_combo', width=160,
                          callback=_on_msk_changed)
        with dpg.group(width=130):
            dpg.add_text("Дата")
            dpg.add_combo([], tag='rp_date_combo', width=130,
                          callback=_on_date_changed)
        with dpg.group(width=180):
            dpg.add_text("Файл")
            dpg.add_combo([], tag='rp_file_combo', width=180)

    with dpg.group(horizontal=True):
        with dpg.group(width=140):
            dpg.add_text("ID замера")
            dpg.add_input_text(tag='rp_measure_id_input', width=140,
                               decimal=True, on_enter=True,
                               callback=lambda s, a: _on_search())
        with dpg.group(width=320):
            dpg.add_text("Номера (поиск)")
            dpg.add_input_text(tag='rp_numbers_input', width=320,
                               hint="JN4450  |  JN4450-JN4460",
                               on_enter=True,
                               callback=lambda s, a: _on_search())
        with dpg.group(width=130):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Найти', width=130,
                           callback=lambda s, a: _on_search())
        with dpg.group(width=170):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Добавить в пул', width=170,
                           callback=lambda s, a: _on_add_to_pool())
        with dpg.group(width=140):
            dpg.add_spacer(height=18)
            dpg.add_button(label='Очистить пул', width=140,
                           callback=lambda s, a: _on_clear_pool())


def _build_pairs_controls():
    dpg.add_text("Параметры подбора пар", color=(180, 220, 255))
    with dpg.group(horizontal=True):
        with dpg.group(width=260):
            dpg.add_text("Спецификация 1")
            dpg.add_combo([], tag='rp_spec1_combo', width=260,
                          callback=_on_spec_selection_changed)
        with dpg.group(width=260):
            dpg.add_text("Спецификация 2")
            dpg.add_combo([], tag='rp_spec2_combo', width=260,
                          callback=_on_spec_selection_changed)

    dpg.add_text('Пул: —', tag='rp_spec_counts',
                 color=(150, 200, 255))

    with dpg.group(horizontal=True):
        dpg.add_checkbox(label='F (ppm)', tag='rp_use_f_check',
                         default_value=True)
        dpg.add_spacer(width=20)
        dpg.add_checkbox(label='R (Ohm)', tag='rp_use_r_check',
                         default_value=False)
        dpg.add_spacer(width=30)
        dpg.add_text("dF max, ppm:")
        dpg.add_input_float(tag='rp_max_ppm_input', width=90,
                            default_value=0.5, step=0.1,
                            format='%.3f')
        dpg.add_spacer(width=20)
        dpg.add_text("dR max, Ohm:")
        dpg.add_input_float(tag='rp_max_ohm_input', width=90,
                            default_value=5.0, step=0.5,
                            format='%.3f')
        dpg.add_spacer(width=20)
        dpg.add_text("Требуемое число пар:")
        dpg.add_input_int(tag='rp_max_pairs_input', width=90,
                          default_value=100, min_value=1,
                          max_value=10000)

    with dpg.group(horizontal=True):
        dpg.add_text("Целевая разница F1-F2, ppm:")
        dpg.add_input_float(tag='rp_target_delta_f_input', width=100,
                            default_value=0.0, step=0.1,
                            format='%.3f')
        dpg.add_text(
            "(0 = равны; +N = F1 выше F2 на N; -N = F1 ниже F2)",
            color=(150, 150, 150))

    with dpg.group(horizontal=True):
        dpg.add_text("Алгоритм:")
        dpg.add_radio_button(
            [ALGO_LABELS[ALGO_MAX_COUNT], ALGO_LABELS[ALGO_MIN_DIFF]],
            tag='rp_algorithm_radio',
            default_value=ALGO_LABELS[ALGO_MAX_COUNT],
            horizontal=False,
        )
        with dpg.tooltip(dpg.last_item()):
            dpg.add_text(
                f"{ALGO_LABELS[ALGO_MAX_COUNT]}: жадный по порядку "
                f"(максимум пар)\n"
                f"{ALGO_LABELS[ALGO_MIN_DIFF]}: жадный по возрастанию "
                f"score (максимум качественных пар)"
            )

    with dpg.group(horizontal=True):
        dpg.add_button(label='Сформировать пары', width=200, height=32,
                       callback=lambda s, a: _on_form_pairs())
        dpg.add_button(label='Сохранить выбранные пары', width=240, height=32,
                       callback=lambda s, a: _on_save_pairs())
        dpg.add_button(label='Экспорт XLS', width=160, height=32,
                       callback=lambda s, a: _on_export_xls())
        dpg.add_button(label='Экспорт PDF', width=160, height=32,
                       callback=lambda s, a: _on_export_pdf())
        dpg.add_button(label='Вернуть used -> free', width=180, height=32,
                       callback=lambda s, a: _on_reset_used())

    with dpg.group(horizontal=True):
        dpg.add_progress_bar(tag='rp_progress_bar', width=400,
                             default_value=0.0, show=False)
        dpg.add_text("", tag='rp_progress_text',
                     color=(200, 220, 255))


def _build_print_saved_section():
    """Раздел печати уже сохранённых пар из БД."""
    with dpg.collapsing_header(
            label='Печать сохранённых пар из БД',
            tag='rp_print_saved_header',
            default_open=False):

        # --- Режим 1: последние N пар ---
        with dpg.group(horizontal=True):
            dpg.add_text("Последние")
            dpg.add_input_int(tag='rp_load_last_n_input', width=80,
                              default_value=100, min_value=1,
                              max_value=100000)
            dpg.add_text("пар")
            dpg.add_button(label='Загрузить',
                           width=120,
                           callback=lambda s, a: _on_load_pairs_last())

        # --- Режим 2: по дате и времени ---
        with dpg.group(horizontal=True):
            dpg.add_text("Дата/время с:")
            dpg.add_input_text(tag='rp_load_date_from_input',
                               width=180,
                               hint="YYYY-MM-DD или YYYY-MM-DD HH:MM")
            dpg.add_text("по:")
            dpg.add_input_text(tag='rp_load_date_to_input',
                               width=180,
                               hint="YYYY-MM-DD или YYYY-MM-DD HH:MM")
            dpg.add_button(label='Загрузить по дате',
                           width=170,
                           callback=lambda s, a: _on_load_pairs_by_date())

        # --- Режим 3: всё + отметки ---
        with dpg.group(horizontal=True):
            dpg.add_button(label='Загрузить все', width=140,
                           callback=lambda s, a: _on_load_pairs_all())
            dpg.add_button(label='Отметить все', width=140,
                           callback=lambda s, a: _on_check_all_print())
            dpg.add_button(label='Снять все', width=140,
                           callback=lambda s, a: _on_uncheck_all_print())

        # --- Статус ---
        dpg.add_text('', tag='rp_print_status_text',
                     color=(200, 220, 255))

        # --- Таблица ---
        dpg.add_group(tag=PRINT_PAIRS_CONTAINER)

        # --- Кнопки печати ---
        with dpg.group(horizontal=True):
            dpg.add_button(label='Печать выбранных PDF',
                           width=200, height=32,
                           callback=lambda s, a: _on_print_saved_pdf())
            dpg.add_button(label='Экспорт выбранных XLS',
                           width=200, height=32,
                           callback=lambda s, a: _on_print_saved_xls())


def _bootstrap_pairs():
    try:
        types = get_archive_types()
        dpg.configure_item('rp_type_combo', items=types)
        if types:
            dpg.set_value('rp_type_combo', types[0])
            _on_type_changed()
    except Exception as e:
        print(f"[Pairs] bootstrap error: {e}")
    _reload_pool_view()