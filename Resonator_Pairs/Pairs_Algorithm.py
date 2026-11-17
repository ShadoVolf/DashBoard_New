"""Алгоритмы подбора пар между резонаторами двух спецификаций.

ВАЖНО: колонки f_value и r_value в пуле (psidata) УЖЕ в целевых
единицах — ppm и Ом соответственно.

Логика по частоте:
    signed_delta = F1 - F2                    (со знаком)
    deviation    = signed_delta - target_delta_f
    Пара проходит, если |deviation| <= dFmax

Знак target_delta_f:
    = 0   -> F1 и F2 должны быть равны
    > 0   -> F1 должна быть выше F2
    < 0   -> F1 должна быть ниже F2

По сопротивлению (если включено):
    delta_r = |R1 - R2|
    Пара проходит, если delta_r <= dRmax
"""
import numpy as np
import pandas as pd


def _num(v):
    try:
        if v is None or pd.isna(v):
            return None
        return float(v)
    except (TypeError, ValueError):
        return None


def form_pairs(pool_df, spec1, spec2, use_f, use_r,
               max_ppm=0.5, max_ohm=5.0, max_pairs=100,
               target_delta_f=0.0,
               algorithm='max_count',
               progress_callback=None):
    """
    Сформировать пары между свободными резонаторами spec1 и spec2.

    Параметры
    ---------
    target_delta_f : float
        Целевая разница F1 - F2 в ppm (со знаком).
        0 - резонаторы равны. >0 - F1 выше F2. <0 - F1 ниже F2.
    max_ppm : float
        Допустимое отклонение фактической разницы от целевой.

    Возвращает (pairs_df, stats_dict).
    """
    stats = {
        'pool_total': 0, 'pool_free': 0,
        'spec1_count': 0, 'spec2_count': 0,
        'rejected_f_nan': 0, 'rejected_f_ppm': 0,
        'rejected_r_nan': 0, 'rejected_r_ohm': 0,
        'candidates': 0, 'selected': 0, 'error': None,
        'target_delta_f': float(target_delta_f or 0.0),
        'max_ppm': float(max_ppm),
        'max_ohm': float(max_ohm),
        'use_f': bool(use_f),
        'use_r': bool(use_r),
    }

    if pool_df is None or pool_df.empty:
        stats['error'] = 'Пул пуст'
        return pd.DataFrame(), stats

    pool = pool_df.copy()
    stats['pool_total'] = len(pool)
    if 'status' in pool.columns:
        pool = pool[pool['status'] == 'free']
    stats['pool_free'] = len(pool)

    if pool.empty:
        stats['error'] = 'Нет свободных резонаторов в пуле'
        return pd.DataFrame(), stats

    s1 = pool[pool['spc'] == spec1].reset_index(drop=True)
    s2 = pool[pool['spc'] == spec2].reset_index(drop=True)
    stats['spec1_count'] = len(s1)
    stats['spec2_count'] = len(s2)

    if s1.empty:
        stats['error'] = (f'В пуле нет свободных резонаторов '
                          f'spec1={spec1!r}')
        return pd.DataFrame(), stats
    if s2.empty:
        stats['error'] = (f'В пуле нет свободных резонаторов '
                          f'spec2={spec2!r}')
        return pd.DataFrame(), stats

    n1, n2 = len(s1), len(s2)
    total_cells = n1 * n2

    if progress_callback:
        progress_callback(0, total_cells, 'подготовка матриц...')

    f1 = pd.to_numeric(s1['f_value'], errors='coerce').to_numpy(dtype=float)
    f2 = pd.to_numeric(s2['f_value'], errors='coerce').to_numpy(dtype=float)
    r1v = pd.to_numeric(s1['r_value'], errors='coerce').to_numpy(dtype=float)
    r2v = pd.to_numeric(s2['r_value'], errors='coerce').to_numpy(dtype=float)

    # --- Знаковая разница и отклонение от цели ---
    target = float(target_delta_f or 0.0)
    signed_diff_mat = f1[:, None] - f2[None, :]           # F1 - F2
    deviation_mat = signed_diff_mat - target              # отклонение от цели
    abs_dev_mat = np.abs(deviation_mat)
    abs_dev_mat = np.where(np.isnan(abs_dev_mat), np.nan, abs_dev_mat)

    # --- Матрица разницы по сопротивлению ---
    ohm_mat = np.abs(r1v[:, None] - r2v[None, :])
    ohm_mat = np.where(np.isnan(ohm_mat), np.nan, ohm_mat)

    if progress_callback:
        progress_callback(total_cells // 3, total_cells, 'фильтрация...')

    valid_mask = np.ones((n1, n2), dtype=bool)

    if use_f:
        f_nan = np.isnan(abs_dev_mat)
        f_bad = ~f_nan & (abs_dev_mat > float(max_ppm))
        stats['rejected_f_nan'] = int(f_nan.sum())
        stats['rejected_f_ppm'] = int(f_bad.sum())
        valid_mask &= ~f_nan & ~f_bad

    if use_r:
        r_nan = np.isnan(ohm_mat)
        r_bad = ~r_nan & (ohm_mat > float(max_ohm))
        stats['rejected_r_nan'] = int((r_nan & valid_mask).sum())
        stats['rejected_r_ohm'] = int((r_bad & valid_mask).sum())
        valid_mask &= ~r_nan & ~r_bad

    ii, jj = np.where(valid_mask)
    n_cand = len(ii)
    stats['candidates'] = n_cand

    if progress_callback:
        progress_callback(total_cells, total_cells, 'отбор пар...')

    if n_cand == 0:
        stats['error'] = (
            f'Ни одна пара не прошла фильтр. Проверено {total_cells}, '
            f'F-NaN={stats["rejected_f_nan"]}, '
            f'F-отклонение>{max_ppm}={stats["rejected_f_ppm"]}, '
            f'R-NaN={stats["rejected_r_nan"]}, '
            f'R>{max_ohm}={stats["rejected_r_ohm"]}')
        return pd.DataFrame(), stats

    # --- Score: чем меньше отклонение, тем лучше ---
    scores = np.zeros(n_cand, dtype=float)
    n_metrics = 0
    if use_f and max_ppm > 0:
        scores += abs_dev_mat[ii, jj] / float(max_ppm)
        n_metrics += 1
    if use_r and max_ohm > 0:
        scores += ohm_mat[ii, jj] / float(max_ohm)
        n_metrics += 1
    if n_metrics > 0:
        scores /= n_metrics

    if algorithm == 'min_diff':
        order = np.argsort(scores, kind='stable')
    else:
        order = np.lexsort((jj, ii))

    used_i, used_j = set(), set()
    selected = []
    for k in order:
        i_idx = int(ii[k])
        j_idx = int(jj[k])
        if i_idx in used_i or j_idx in used_j:
            continue
        selected.append(k)
        used_i.add(i_idx)
        used_j.add(j_idx)
        if len(selected) >= int(max_pairs):
            break

    stats['selected'] = len(selected)
    if not selected:
        return pd.DataFrame(), stats

    rows = []
    for k in selected:
        i_idx = int(ii[k])
        j_idx = int(jj[k])
        row1 = s1.iloc[i_idx]
        row2 = s2.iloc[j_idx]
        signed_diff = signed_diff_mat[i_idx, j_idx]
        dev = deviation_mat[i_idx, j_idx]
        dr_v = ohm_mat[i_idx, j_idx]
        rows.append({
            'pool_id_1': (int(row1['id'])
                          if pd.notna(row1.get('id')) else None),
            'pool_id_2': (int(row2['id'])
                          if pd.notna(row2.get('id')) else None),
            'measure_id_1': int(row1['measure_id']),
            'measure_id_2': int(row2['measure_id']),
            'n_1': row1.get('n_normalized'),
            'n_2': row2.get('n_normalized'),
            'spc_1': row1.get('spc'),
            'spc_2': row2.get('spc'),
            'msk_1': row1.get('msk'),
            'msk_2': row2.get('msk'),
            'f_1': _num(row1.get('f_value')),
            'f_2': _num(row2.get('f_value')),
            'r_1': _num(row1.get('r_value')),
            'r_2': _num(row2.get('r_value')),
            # signed_delta_f = F1 - F2 (со знаком)
            'signed_delta_f': (float(signed_diff)
                               if not np.isnan(signed_diff) else None),
            # delta_f = |F1 - F2| (модуль, как раньше)
            'delta_f': (abs(float(signed_diff))
                        if not np.isnan(signed_diff) else None),
            # dev_from_target = (F1 - F2) - target_delta_f
            'dev_from_target': (float(dev)
                                if not np.isnan(dev) else None),
            'delta_r': float(dr_v) if not np.isnan(dr_v) else None,
        })

    return pd.DataFrame(rows), stats