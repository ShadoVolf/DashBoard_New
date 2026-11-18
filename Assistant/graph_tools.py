"""Инструменты ассистента для модуля Графики (ResonatorGraph).

Соглашения (как в protocol_tools):
  * Каждый tool возвращает dict. Ошибка — {'error': str, 'hint': str|None}.
  * Побочные эффекты (открытие окон, PDF) выполняются сразу.
  * Параметр по умолчанию — F (без нагрузки).
  * При нескольких замерах на номер берётся последний по дате.
  * quality: only_good | only_reject | None.
"""
from __future__ import annotations

import os
import tempfile
from typing import Optional

from Archive_View.Archive_Data import parse_numbers_input

# ---------------------------------------------------------------------------
# Логирование
# ---------------------------------------------------------------------------
def _log(dpg_, text, color=None):
    try:
        from Statistik.dashboard_llm import _append_assistant_log
        _append_assistant_log(dpg_, text, color=color)
    except Exception:
        print(f'[Assistant.graph] {text}')


# ---------------------------------------------------------------------------
# Параметры / нормализация
# ---------------------------------------------------------------------------
_PARAM_ALIASES = {
    'f': 'F (без нагрузки)',
    'f без': 'F (без нагрузки)',
    'f без нагрузки': 'F (без нагрузки)',
    'без нагрузки': 'F (без нагрузки)',
    'частота': 'F (без нагрузки)',
    'fl': 'FL (с нагрузкой)',
    'f с нагрузкой': 'FL (с нагрузкой)',
    'с нагрузкой': 'FL (с нагрузкой)',
    'r': 'R (сопротивление)',
    'сопротивление': 'R (сопротивление)',
    'mono': 'Монотонность',
    'монотонность': 'Монотонность',
    'q': 'Добротность',
    'добротность': 'Добротность',
    'c0': 'C0, пФ',
    'cq': 'Cq, фФ',
    'l': 'L, мГн',
    'rb': 'Rb (сопр. моды B)',
    'rcrb': 'Rc/Rb',
    'rc/rb': 'Rc/Rb',
}

DEFAULT_PARAM = 'F (без нагрузки)'


def _resolve_param(raw) -> str:
    if not raw:
        return DEFAULT_PARAM
    s = str(raw).strip().lower()
    if s in _PARAM_ALIASES:
        return _PARAM_ALIASES[s]
    from ResonatorGraph.constants import PARAMETERS
    for key, label, *_ in PARAMETERS:
        if s == key.lower() or s == label.lower():
            return label
    return DEFAULT_PARAM


def _as_numbers(v):
    if v is None:
        return []
    if isinstance(v, str):
        return parse_numbers_input(v) or []
    if isinstance(v, list):
        flat = []
        for x in v:
            if isinstance(x, str):
                flat.extend(parse_numbers_input(x) or [x])
            else:
                flat.append(str(x))
        return flat
    return [str(v)]


def _norm_msk(v):
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _open_path(path: str):
    try:
        os.startfile(path)
    except Exception:
        try:
            import subprocess
            subprocess.Popen(['xdg-open', path])
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Запуск модуля / UI helpers
# ---------------------------------------------------------------------------
def _ensure_graph_module(dpg_):
    from .launcher import is_module_running, launch_module
    if is_module_running('graph'):
        return {'status': 'already_running'}
    return launch_module('graph', dpg_)


def _get_controller():
    from ResonatorGraph import ui as rg_ui
    return rg_ui.controller


def _set_param(ctrl, param_label: str):
    ctrl.param_label = param_label
    try:
        import dearpygui.dearpygui as dpg
        from ResonatorGraph.constants import TAG_PARAM
        if dpg.does_item_exist(TAG_PARAM):
            dpg.set_value(TAG_PARAM, param_label)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Качество (годные / брак) — через аномалии compute_msk_statistics
# ---------------------------------------------------------------------------
def _filter_numbers_by_quality(ctrl, numbers, quality: Optional[str]):
    """quality: only_good | only_reject | None.

    only_good  — номера без статистических аномалий (|z|<=3 и внутри 1.5*IQR)
    only_reject — только аномалии
    """
    if not quality or not numbers:
        return numbers, {}

    try:
        stats = ctrl.compute_msk_statistics()
    except Exception as e:
        return numbers, {'quality_warning': f'фильтр не применён: {e}'}

    anom_set = {a['number'] for a in stats.get('anomalies') or []}
    all_set = {str(n) for n, _ in (stats.get('values') or [])}
    # номера без значения при T_ref считаем «неизвестными» — оставляем при only_good
    if quality == 'only_reject':
        filtered = [n for n in numbers if str(n) in anom_set]
    else:  # only_good
        filtered = [n for n in numbers if str(n) not in anom_set]

    meta = {
        'quality': quality,
        'before': len(numbers),
        'after': len(filtered),
        'anomalies': len(anom_set),
    }
    return filtered, meta


def _apply_last_n(numbers, last_n):
    if not last_n or not numbers:
        return numbers
    try:
        n = int(last_n)
    except (TypeError, ValueError):
        return numbers
    if n <= 0:
        return numbers
    return numbers[-n:] if len(numbers) > n else numbers


# ---------------------------------------------------------------------------
# Resolve measure / numbers
# ---------------------------------------------------------------------------
def _resolve_latest_measure_for_numbers(numbers):
    from ResonatorGraph import db
    from ResonatorGraph.constants import get_main_table

    table = get_main_table()
    placeholders = ','.join(f':n{i}' for i in range(len(numbers)))
    binds = {f'n{i}': n for i, n in enumerate(numbers)}

    try:
        rows = db.fetchall(
            f"SELECT Measure_ID, Msk, MAX(dataR) AS last_date, COUNT(*) AS cnt "
            f"FROM `{table}` WHERE `N` IN ({placeholders}) "
            f"AND Measure_ID IS NOT NULL "
            f"GROUP BY Measure_ID, Msk "
            f"ORDER BY last_date DESC, cnt DESC LIMIT 5",
            **binds,
        )
    except Exception:
        try:
            rows = db.fetchall(
                f"SELECT Measure_ID, Msk, COUNT(*) AS cnt "
                f"FROM `{table}` WHERE `N` IN ({placeholders}) "
                f"AND Measure_ID IS NOT NULL "
                f"GROUP BY Measure_ID, Msk ORDER BY cnt DESC LIMIT 5",
                **binds,
            )
        except Exception as e:
            return None, None, {'error': str(e)}

    if not rows:
        return None, None, {'note': 'нет строк'}

    best = rows[0]
    mid = best.get('Measure_ID')
    msk = best.get('Msk')
    info = {
        'candidates': [
            {'measure_id': r.get('Measure_ID'), 'msk': r.get('Msk'),
             'date': str(r.get('last_date') or ''), 'count': r.get('cnt')}
            for r in rows
        ],
        'chosen': 'latest by date',
    }
    return mid, msk, info


# ---------------------------------------------------------------------------
# Tools: open
# ---------------------------------------------------------------------------
def _tool_open_graphs_msk(params, dpg_):
    msk = _norm_msk(params.get('msk') or params.get('msk_partial'))
    if not msk:
        return {'error': 'Не указана МСК', 'hint': 'Пример: открыть графики МСК 456'}

    param = _resolve_param(params.get('param'))
    quality = params.get('quality')
    last_n = params.get('last_n')

    res = _ensure_graph_module(dpg_)
    if res.get('status') == 'error':
        return res

    try:
        from ResonatorGraph.ui import open_for_msk
        open_for_msk(msk)
        ctrl = _get_controller()
        _set_param(ctrl, param)

        numbers = ctrl.load_numbers(msk)
        numbers = _apply_last_n(numbers, last_n)
        qmeta = {}
        if quality and numbers:
            numbers, qmeta = _filter_numbers_by_quality(ctrl, numbers, quality)

        try:
            from ResonatorGraph import ui as rg_ui
            if hasattr(rg_ui, '_on_param_change'):
                rg_ui._on_param_change()
        except Exception:
            pass

        out = {
            'action': 'opened',
            'msk': msk,
            'param': param,
            'numbers_count': len(numbers) if numbers else None,
            'note': f'Открыты графики МСК {msk}, параметр {param}',
        }
        if last_n:
            out['last_n'] = last_n
        if qmeta:
            out['quality'] = qmeta
        return out
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}


def _tool_open_by_measure_id(params, dpg_):
    """Открыть графики по ID замера (из Архива / Протоколов)."""
    mid = params.get('measure_id')
    if mid is None:
        return {'error': 'Не указан measure_id',
                'hint': 'Пример: открой графики id замера 12345'}
    mid = str(mid).strip()
    param = _resolve_param(params.get('param'))

    res = _ensure_graph_module(dpg_)
    if res.get('status') == 'error':
        return res

    try:
        from ResonatorGraph.ui import open_for_measure_id, create_graph_window
        create_graph_window()
        open_for_measure_id(mid)
        ctrl = _get_controller()
        _set_param(ctrl, param)
        info = ctrl.load_by_measure_id(mid) or {}
        return {
            'action': 'opened',
            'measure_id': mid,
            'msk': info.get('msk'),
            'spc': info.get('spc'),
            'numbers_count': len(info.get('numbers') or []),
            'param': param,
            'note': f'Открыты графики ID замера {mid}',
        }
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}


def _tool_open_graphs_numbers(params, dpg_):
    numbers = _as_numbers(params.get('numbers'))
    if not numbers:
        return {'error': 'Не указаны номера',
                'hint': 'Пример: графики номеров JN4450-JN4460'}

    param = _resolve_param(params.get('param'))
    res = _ensure_graph_module(dpg_)
    if res.get('status') == 'error':
        return res

    try:
        from ResonatorGraph.ui import create_graph_window, open_for_measure_id, open_for_msk
        mid, msk, info = _resolve_latest_measure_for_numbers(numbers)
        if not mid and not msk:
            return {'error': f'Не найдены данные для номеров {numbers[:5]}...',
                    'hint': 'Проверьте номера или источник данных'}

        create_graph_window()
        ctrl = _get_controller()
        _set_param(ctrl, param)

        if mid:
            open_for_measure_id(str(mid))
        elif msk:
            open_for_msk(msk)

        if numbers:
            ctrl.number = numbers[0]
            try:
                import dearpygui.dearpygui as dpg
                from ResonatorGraph.constants import TAG_NUMBER
                if dpg.does_item_exist(TAG_NUMBER):
                    dpg.set_value(TAG_NUMBER, numbers[0])
            except Exception:
                pass

        return {
            'action': 'opened',
            'numbers': numbers[:20],
            'count': len(numbers),
            'measure_id': mid,
            'msk': msk,
            'param': param,
            'info': info,
        }
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}


# ---------------------------------------------------------------------------
# all_on_one / density (с quality и last_n)
# ---------------------------------------------------------------------------
def _tool_all_on_one(params, dpg_):
    msk = _norm_msk(params.get('msk'))
    measure_id = params.get('measure_id')
    param = _resolve_param(params.get('param'))
    do_print = bool(params.get('print') or params.get('pdf'))
    quality = params.get('quality')
    last_n = params.get('last_n')

    res = _ensure_graph_module(dpg_)
    if res.get('status') == 'error':
        return res

    try:
        from ResonatorGraph.ui import open_for_msk, open_for_measure_id, create_graph_window
        create_graph_window()
        ctrl = _get_controller()
        _set_param(ctrl, param)

        if measure_id:
            open_for_measure_id(str(measure_id))
            ctrl.measure_id = str(measure_id)
        elif msk:
            open_for_msk(msk)
            ctrl.msk = msk
        else:
            return {'error': 'Нужна МСК или measure_id'}

        # quality / last_n: строим вручную по отфильтрованным номерам
        numbers = ctrl.load_numbers(ctrl.msk)
        numbers = _apply_last_n(numbers, last_n)
        qmeta = {}
        if quality:
            numbers, qmeta = _filter_numbers_by_quality(ctrl, numbers, quality)

        from ResonatorGraph import ui as rg_ui
        from ResonatorGraph.logic import GraphResult, Series, GraphLogicError
        from ResonatorGraph.constants import PARAM_BY_LABEL, COLORS
        from ResonatorGraph.polynomial import poly_fit, poly_val
        import numpy as np

        if quality or last_n:
            _, label, _, unit = PARAM_BY_LABEL[ctrl.param_label]
            build_res = GraphResult()
            used = 0
            save_n = ctrl.number
            for n in numbers:
                ctrl.number = n
                try:
                    rows = ctrl._fetch_meas_points()
                    if not rows:
                        continue
                    xs, ys = ctrl._prepare_xy(rows)
                    xy = [(x, y) for x, y in zip(xs, ys) if ctrl.A <= x <= ctrl.B]
                    if len(xy) < 2:
                        continue
                    xs = [p[0] for p in xy]
                    ys = [p[1] for p in xy]
                except Exception:
                    continue
                color = COLORS[used % len(COLORS)]
                used += 1
                build_res.series.append(Series(f'N{n}', xs, ys, color, 'scatter'))
                try:
                    degree = min(ctrl.degree, max(1, len(xs) - 1))
                    coeffs = poly_fit(xs, ys, degree)
                    gx = np.linspace(ctrl.A, ctrl.B, 200).tolist()
                    gy = poly_val(coeffs, np.asarray(gx)).tolist()
                    build_res.series.append(
                        Series(f'N{n} аппрокс.', gx, gy, color, 'line'))
                except Exception:
                    pass
            ctrl.number = save_n
            if not build_res.series:
                raise GraphLogicError('Не удалось построить ни одного номера')
            parts = [f'ID {ctrl.measure_id}'] if ctrl.measure_id else [f'МСК {ctrl.msk}']
            parts.append(f'номера ({used})')
            if quality:
                parts.append(quality)
            build_res.title = '  '.join(parts)
            build_res.ylabel = f'{label}, {unit}' if unit else label
            build_res.meta['hide_legend'] = True
        else:
            build_res = ctrl.build_all_numbers(
                show_msk=True, show_approx=True, show_points=True)

        if hasattr(rg_ui, '_render_result'):
            rg_ui._render_result(build_res)

        out = {
            'action': 'all_on_one',
            'msk': msk or ctrl.msk,
            'measure_id': measure_id or ctrl.measure_id,
            'param': param,
            'series_count': len(build_res.series),
            'title': build_res.title,
        }
        if qmeta:
            out['quality'] = qmeta
        if do_print:
            out['pdf'] = _export_all_on_one_pdf(ctrl, build_res)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}


def _export_all_on_one_pdf(ctrl, res):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
    except ImportError:
        return {'error': 'matplotlib не установлен'}

    if not res.series:
        return {'error': 'Нет серий для экспорта'}

    fig, ax = plt.subplots(figsize=(16.5, 11.7))
    for s in res.series:
        if s.kind != 'line':
            continue
        rgb = tuple(c / 255 for c in s.color)
        ax.plot(s.xs, s.ys, '-', color=rgb, linewidth=1.0, alpha=0.8, label=s.label)
    for s in res.series:
        if s.kind != 'scatter':
            continue
        rgb = tuple(c / 255 for c in s.color)
        ax.scatter(s.xs, s.ys, s=12, color=rgb, edgecolors='black', linewidths=0.25)

    ax.set_xlabel(res.xlabel or 'T, C')
    ax.set_ylabel(res.ylabel or '')
    ax.set_title(res.title or '')
    ax.grid(True, alpha=0.3)
    if len(res.series) <= 24:
        ax.legend(fontsize=7, loc='best')

    fd, path = tempfile.mkstemp(suffix='.pdf', prefix='graphs_all_')
    os.close(fd)
    with PdfPages(path) as pdf:
        pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)
    _open_path(path)
    return {'path': path, 'status': 'saved_and_opened'}


def _tool_density(params, dpg_):
    msk = _norm_msk(params.get('msk'))
    measure_id = params.get('measure_id')
    param = _resolve_param(params.get('param'))
    do_print = bool(params.get('print') or params.get('pdf'))
    quality = params.get('quality')

    if not msk and not measure_id:
        return {'error': 'Нужна МСК или measure_id'}

    res = _ensure_graph_module(dpg_)
    if res.get('status') == 'error':
        return res

    try:
        from ResonatorGraph.ui import open_for_msk, open_for_measure_id, create_graph_window
        create_graph_window()
        ctrl = _get_controller()
        _set_param(ctrl, param)

        if measure_id:
            open_for_measure_id(str(measure_id))
        else:
            open_for_msk(msk)

        try:
            stats = ctrl.compute_msk_statistics()
        except Exception:
            stats = _compute_density_fallback(ctrl)

        if isinstance(stats, dict) and stats.get('error'):
            return stats
        if not stats:
            return {'error': 'Не удалось рассчитать распределение'}

        # quality: пересчитать KDE только по нужным номерам
        if quality and stats.get('values'):
            anom_set = {a['number'] for a in stats.get('anomalies') or []}
            if quality == 'only_reject':
                vals = [v for n, v in stats['values'] if n in anom_set]
            else:
                vals = [v for n, v in stats['values'] if n not in anom_set]
            if len(vals) >= 3:
                import numpy as np
                from ResonatorGraph.polynomial import gaussian_kde
                arr = np.asarray(vals, dtype=float)
                kx, ky = gaussian_kde(arr)
                stats = dict(stats)
                stats['count'] = len(vals)
                stats['mean'] = float(np.mean(arr))
                stats['median'] = float(np.median(arr))
                stats['std'] = float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0
                stats['min'] = float(np.min(arr))
                stats['max'] = float(np.max(arr))
                stats['kde_x'] = kx.tolist() if hasattr(kx, 'tolist') else list(kx)
                stats['kde_y'] = ky.tolist() if hasattr(ky, 'tolist') else list(ky)
                stats['quality'] = quality

        from ResonatorGraph import ui as rg_ui
        if hasattr(rg_ui, '_render_distribution'):
            rg_ui._render_distribution(stats)
        if hasattr(rg_ui, '_show_statistics'):
            rg_ui._show_statistics(stats)

        out = {
            'action': 'density',
            'msk': msk or ctrl.msk,
            'param': param,
            'count': stats.get('count'),
            'mean': stats.get('mean'),
            'std': stats.get('std'),
            'median': stats.get('median'),
            'anomalies': len(stats.get('anomalies') or []),
        }
        if quality:
            out['quality'] = quality
        if do_print:
            out['pdf'] = _export_density_pdf(stats, ctrl)
        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}


def _compute_density_fallback(ctrl):
    import numpy as np
    from ResonatorGraph.polynomial import gaussian_kde
    from ResonatorGraph.constants import PARAM_BY_LABEL

    numbers = ctrl.load_numbers(ctrl.msk)
    if not numbers:
        return {'error': 'Нет номеров'}

    key = PARAM_BY_LABEL[ctrl.param_label][0]
    label = PARAM_BY_LABEL[ctrl.param_label][1]
    unit = PARAM_BY_LABEL[ctrl.param_label][3]
    values = []
    skipped = []
    save_n = ctrl.number

    for n in numbers:
        ctrl.number = n
        try:
            rows = ctrl._fetch_meas_points()
            if not rows:
                skipped.append(n)
                continue
            v = ctrl._value_at_tref(rows, key)
            if v is None:
                skipped.append(n)
                continue
            values.append(float(v))
        except Exception:
            skipped.append(n)

    ctrl.number = save_n
    if len(values) < 3:
        return {'error': f'Мало точек для KDE ({len(values)})'}

    arr = np.asarray(values, dtype=float)
    kde_x, kde_y = gaussian_kde(arr)

    return {
        'label': label, 'unit': unit, 'count': len(values),
        'mean': float(np.mean(arr)), 'median': float(np.median(arr)),
        'std': float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
        'min': float(np.min(arr)), 'max': float(np.max(arr)),
        'q1': float(np.percentile(arr, 25)),
        'q3': float(np.percentile(arr, 75)),
        'iqr': float(np.percentile(arr, 75) - np.percentile(arr, 25)),
        'range': float(np.max(arr) - np.min(arr)),
        'kde_x': kde_x.tolist() if hasattr(kde_x, 'tolist') else list(kde_x),
        'kde_y': kde_y.tolist() if hasattr(kde_y, 'tolist') else list(kde_y),
        'T_ref': ctrl.T_ref, 'skipped': skipped,
        'measure_id': ctrl.measure_id, 'anomalies': [],
        'values': list(zip([str(n) for n in numbers if n not in skipped], values)),
    }


def _export_density_pdf(stats, ctrl):
    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
    except ImportError:
        return {'error': 'matplotlib не установлен'}

    kx = stats.get('kde_x') or []
    ky = stats.get('kde_y') or []
    if not kx or not ky:
        return {'error': 'Нет данных KDE'}

    fig, ax = plt.subplots(figsize=(11.69, 8.27))
    ax.plot(kx, ky, '-', color='#285acc', linewidth=2.0)
    ax.fill_between(kx, ky, alpha=0.25, color='#285acc')
    unit = stats.get('unit') or ''
    xlabel = stats.get('label', '') + (f', {unit}' if unit else '')
    ax.set_xlabel(xlabel)
    ax.set_ylabel('Плотность вероятности')
    title = f"Распределение {stats.get('label')} | "
    if stats.get('measure_id'):
        title += f"ID {stats['measure_id']}"
    else:
        title += f"МСК {ctrl.msk}"
    title += f" | n = {stats.get('count')}"
    if stats.get('quality'):
        title += f" | {stats['quality']}"
    ax.set_title(title)
    ax.grid(True, alpha=0.3)
    txt = (f"mean={stats.get('mean'):.4g}  median={stats.get('median'):.4g}\n"
           f"σ={stats.get('std'):.4g}  n={stats.get('count')}")
    ax.text(0.98, 0.97, txt, transform=ax.transAxes, ha='right', va='top',
            fontsize=9, bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    fd, path = tempfile.mkstemp(suffix='.pdf', prefix='density_')
    os.close(fd)
    with PdfPages(path) as pdf:
        pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)
    _open_path(path)
    return {'path': path, 'status': 'saved_and_opened'}


# ---------------------------------------------------------------------------
# 1. Сравнение двух МСК
# ---------------------------------------------------------------------------
def _tool_compare_msk(params, dpg_):
    """Сравнить две МСК: KDE + boxplot на одном PDF."""
    msk_a = _norm_msk(params.get('msk_a') or params.get('msk'))
    msk_b = _norm_msk(params.get('msk_b'))
    if not msk_a or not msk_b:
        return {'error': 'Нужны две МСК',
                'hint': 'Пример: сравни МСК 456 и 457 по F'}
    param = _resolve_param(params.get('param'))

    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
        import numpy as np
    except ImportError:
        return {'error': 'matplotlib не установлен'}

    from ResonatorGraph.logic import GraphController

    def _stats_for(msk):
        c = GraphController()
        c.param_label = param
        c.msk = msk
        info = c.load_by_msk(msk)
        if info and info.get('spc'):
            c.spec = info['spc']
            c.load_spec_defaults(info['spc'])
            tref = c.load_reference_temperature(info['spc'])
            if tref is not None:
                c.T_ref = tref
        try:
            return c.compute_msk_statistics()
        except Exception as e:
            return {'error': str(e), 'msk': msk}

    sa = _stats_for(msk_a)
    sb = _stats_for(msk_b)
    if sa.get('error') and sb.get('error'):
        return {'error': f"Обе МСК: {sa.get('error')}; {sb.get('error')}"}

    fig, axes = plt.subplots(1, 2, figsize=(14, 6))

    # --- KDE ---
    ax = axes[0]
    for stats, label, color in (
        (sa, f'МСК {msk_a}', '#285acc'),
        (sb, f'МСК {msk_b}', '#cc3a28'),
    ):
        if stats.get('error'):
            continue
        kx, ky = stats.get('kde_x') or [], stats.get('kde_y') or []
        if kx and ky:
            ax.plot(kx, ky, '-', color=color, lw=2, label=f"{label} (n={stats.get('count')})")
            ax.fill_between(kx, ky, alpha=0.15, color=color)
    ax.set_xlabel(param)
    ax.set_ylabel('Плотность')
    ax.set_title('KDE')
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)

    # --- Boxplot ---
    ax = axes[1]
    data, labels, colors = [], [], []
    for stats, label, color in (
        (sa, f'МСК {msk_a}', '#285acc'),
        (sb, f'МСК {msk_b}', '#cc3a28'),
    ):
        if stats.get('error'):
            continue
        vals = [v for _, v in (stats.get('values') or [])]
        if vals:
            data.append(vals)
            labels.append(f"{label}\nn={len(vals)}")
            colors.append(color)
    if data:
        bp = ax.boxplot(data, labels=labels, patch_artist=True, showmeans=True)
        for patch, c in zip(bp['boxes'], colors):
            patch.set_facecolor(c)
            patch.set_alpha(0.4)
    ax.set_ylabel(param)
    ax.set_title('Boxplot')
    ax.grid(True, axis='y', alpha=0.3)

    fig.suptitle(f'Сравнение МСК {msk_a} vs {msk_b}  |  {param}', fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.95])

    fd, path = tempfile.mkstemp(suffix='.pdf', prefix='compare_msk_')
    os.close(fd)
    with PdfPages(path) as pdf:
        pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)
    _open_path(path)

    def _sum(s):
        if s.get('error'):
            return {'error': s['error']}
        return {
            'count': s.get('count'), 'mean': s.get('mean'),
            'std': s.get('std'), 'median': s.get('median'),
            'anomalies': len(s.get('anomalies') or []),
        }

    return {
        'action': 'compare_msk',
        'msk_a': msk_a, 'msk_b': msk_b, 'param': param,
        'stats_a': _sum(sa), 'stats_b': _sum(sb),
        'path': path, 'status': 'saved_and_opened',
    }


# ---------------------------------------------------------------------------
# 2. Авто-отчёт по МСК
# ---------------------------------------------------------------------------
def _tool_auto_report(params, dpg_):
    """PDF: all-on-one + density + таблица аномалий + нормы из спецификации."""
    msk = _norm_msk(params.get('msk'))
    measure_id = params.get('measure_id')
    param = _resolve_param(params.get('param'))
    quality = params.get('quality')

    if not msk and not measure_id:
        return {'error': 'Нужна МСК или measure_id',
                'hint': 'Пример: отчёт по МСК 456'}

    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
        import numpy as np
    except ImportError:
        return {'error': 'matplotlib не установлен'}

    from ResonatorGraph.logic import GraphController
    from ResonatorGraph.constants import PARAM_BY_LABEL, COLORS
    from ResonatorGraph.polynomial import poly_fit, poly_val

    ctrl = GraphController()
    ctrl.param_label = param
    if measure_id:
        ctrl.measure_id = str(measure_id)
        info = ctrl.load_by_measure_id(str(measure_id)) or {}
        msk = msk or info.get('msk')
        ctrl.msk = msk
    else:
        ctrl.msk = msk
        info = ctrl.load_by_msk(msk) or {}

    if info.get('spc'):
        ctrl.spec = info['spc']
        ctrl.load_spec_defaults(info['spc'])
        tref = ctrl.load_reference_temperature(info['spc'])
        if tref is not None:
            ctrl.T_ref = tref

    # статистика
    try:
        stats = ctrl.compute_msk_statistics()
    except Exception as e:
        return {'error': f'Статистика: {e}'}

    numbers = ctrl.load_numbers(ctrl.msk)
    qmeta = {}
    if quality:
        numbers, qmeta = _filter_numbers_by_quality(ctrl, numbers, quality)

    # нормы из specification (мягкий поиск колонок)
    norms = _load_spec_norms(info.get('spc'), param)

    fd, path = tempfile.mkstemp(suffix='.pdf', prefix='report_msk_')
    os.close(fd)

    with PdfPages(path) as pdf:
        # ---- page 1: all-on-one ----
        fig, ax = plt.subplots(figsize=(16.5, 11.7))
        used = 0
        save_n = ctrl.number
        for n in numbers:
            ctrl.number = n
            try:
                rows = ctrl._fetch_meas_points()
                if not rows:
                    continue
                xs, ys = ctrl._prepare_xy(rows)
                xy = [(x, y) for x, y in zip(xs, ys) if ctrl.A <= x <= ctrl.B]
                if len(xy) < 2:
                    continue
                xs = [p[0] for p in xy]
                ys = [p[1] for p in xy]
                color = tuple(c / 255 for c in COLORS[used % len(COLORS)])
                used += 1
                ax.scatter(xs, ys, s=8, color=color, alpha=0.7)
                try:
                    deg = min(ctrl.degree, max(1, len(xs) - 1))
                    coeffs = poly_fit(xs, ys, deg)
                    gx = np.linspace(ctrl.A, ctrl.B, 200)
                    gy = poly_val(coeffs, gx)
                    ax.plot(gx, gy, '-', color=color, lw=0.9, alpha=0.8)
                except Exception:
                    pass
            except Exception:
                continue
        ctrl.number = save_n
        title = f"МСК {msk or ''}  ID {measure_id or ''}  |  {param}  |  n={used}"
        if quality:
            title += f"  |  {quality}"
        ax.set_title(title)
        ax.set_xlabel('T, C')
        _, label, _, unit = PARAM_BY_LABEL[param]
        ax.set_ylabel(f'{label}, {unit}' if unit else label)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        pdf.savefig(fig)
        plt.close(fig)

        # ---- page 2: density + stats + anomalies ----
        fig = plt.figure(figsize=(11.69, 8.27))
        gs = fig.add_gridspec(2, 2, height_ratios=[1.2, 1], hspace=0.35, wspace=0.3)

        ax_kde = fig.add_subplot(gs[0, :])
        kx, ky = stats.get('kde_x') or [], stats.get('kde_y') or []
        if kx and ky:
            ax_kde.plot(kx, ky, '-', color='#285acc', lw=2)
            ax_kde.fill_between(kx, ky, alpha=0.25, color='#285acc')
        ax_kde.set_xlabel(param)
        ax_kde.set_ylabel('Плотность')
        ax_kde.set_title(f"Распределение  n={stats.get('count')}  mean={stats.get('mean'):.4g}  σ={stats.get('std'):.4g}")
        ax_kde.grid(True, alpha=0.3)

        # нормы — вертикальные линии
        if norms.get('lo') is not None:
            ax_kde.axvline(norms['lo'], color='green', ls='--', lw=1.2, label=f"min {norms['lo']}")
        if norms.get('hi') is not None:
            ax_kde.axvline(norms['hi'], color='red', ls='--', lw=1.2, label=f"max {norms['hi']}")
        if norms.get('lo') is not None or norms.get('hi') is not None:
            ax_kde.legend(fontsize=8)

        # таблица статистик
        ax_tbl = fig.add_subplot(gs[1, 0])
        ax_tbl.axis('off')
        rows_txt = [
            ['count', str(stats.get('count'))],
            ['mean', f"{stats.get('mean'):.5g}"],
            ['median', f"{stats.get('median'):.5g}"],
            ['std', f"{stats.get('std'):.5g}"],
            ['min', f"{stats.get('min'):.5g}"],
            ['max', f"{stats.get('max'):.5g}"],
            ['Q1', f"{stats.get('q1'):.5g}"],
            ['Q3', f"{stats.get('q3'):.5g}"],
        ]
        if norms:
            rows_txt.append(['норма min', str(norms.get('lo', '—'))])
            rows_txt.append(['норма max', str(norms.get('hi', '—'))])
        t = ax_tbl.table(cellText=rows_txt, colLabels=['Параметр', 'Значение'],
                         loc='center', cellLoc='center')
        t.auto_set_font_size(False)
        t.set_fontsize(9)
        t.scale(1.1, 1.3)
        ax_tbl.set_title('Статистика', fontsize=11)

        # аномалии
        ax_an = fig.add_subplot(gs[1, 1])
        ax_an.axis('off')
        anoms = stats.get('anomalies') or []
        if anoms:
            cells = [[a['number'], f"{a['value']:.4g}", str(a['z_score'])]
                     for a in anoms[:15]]
            t2 = ax_an.table(cellText=cells,
                             colLabels=['N', 'Знач.', '|z|'],
                             loc='center', cellLoc='center')
            t2.auto_set_font_size(False)
            t2.set_fontsize(8)
            t2.scale(1.1, 1.2)
            ax_an.set_title(f'Аномалии ({len(anoms)})', fontsize=11, color='#aa3030')
        else:
            ax_an.text(0.5, 0.5, 'Аномалий нет', ha='center', va='center',
                       fontsize=12, color='green')
            ax_an.set_title('Аномалии', fontsize=11)

        fig.suptitle(
            f"Отчёт МСК {msk or ''}  ID {measure_id or ''}  |  {param}  |  "
            f"спека {info.get('spc') or '—'}",
            fontsize=12,
        )
        pdf.savefig(fig)
        plt.close(fig)

    _open_path(path)
    return {
        'action': 'auto_report',
        'msk': msk,
        'measure_id': measure_id,
        'param': param,
        'count': stats.get('count'),
        'anomalies': len(anoms),
        'norms': norms or None,
        'quality': qmeta or None,
        'path': path,
        'status': 'saved_and_opened',
    }


def _load_spec_norms(spc, param_label):
    """Мягкая попытка прочитать нормы из specification."""
    if not spc:
        return {}
    from ResonatorGraph import db
    from ResonatorGraph.constants import PARAM_BY_LABEL

    key = PARAM_BY_LABEL.get(param_label, (None,))[0]
    if not key:
        return {}

    # возможные имена колонок
    candidates = [
        (f'{key}_min', f'{key}_max'),
        (f'{key}min', f'{key}max'),
        (f'min{key}', f'max{key}'),
        (f'{key}_lo', f'{key}_hi'),
    ]
    try:
        row = db.fetchone("SELECT * FROM `specification` WHERE `Name` = :s", s=spc)
    except Exception:
        return {}
    if not row:
        return {}

    # case-insensitive ключи
    lower_map = {str(k).lower(): k for k in row.keys()}
    for lo_n, hi_n in candidates:
        lo_k = lower_map.get(lo_n.lower())
        hi_k = lower_map.get(hi_n.lower())
        lo = row.get(lo_k) if lo_k else None
        hi = row.get(hi_k) if hi_k else None
        try:
            lo = float(lo) if lo not in (None, '') else None
        except (TypeError, ValueError):
            lo = None
        try:
            hi = float(hi) if hi not in (None, '') else None
        except (TypeError, ValueError):
            hi = None
        if lo is not None or hi is not None:
            return {'lo': lo, 'hi': hi, 'source': 'specification'}
    return {}


# ---------------------------------------------------------------------------
# PDF numbers / print
# ---------------------------------------------------------------------------
def _tool_pdf_numbers(params, dpg_):
    numbers = _as_numbers(params.get('numbers'))
    if not numbers:
        return {'error': 'Не указаны номера'}

    param = _resolve_param(params.get('param'))
    per_page = int(params.get('per_page') or 9)

    try:
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from matplotlib.backends.backend_pdf import PdfPages
    except ImportError:
        return {'error': 'matplotlib не установлен'}

    from ResonatorGraph.logic import GraphController

    ctrl = GraphController()
    ctrl.param_label = param

    pages_data = []
    skipped = []
    for n in numbers:
        mid, msk, _ = _resolve_latest_measure_for_numbers([n])
        if not mid and not msk:
            skipped.append(n)
            continue
        ctrl.measure_id = str(mid) if mid else None
        ctrl.msk = msk
        ctrl.number = n
        try:
            res = ctrl.build_points(show_points=True, show_msk=True)
            approx = None
            try:
                approx = ctrl.build_approximation({
                    'degree': ctrl.degree, 'show_approx': True,
                    'show_msk': False, 'show_order': False,
                })
            except Exception:
                pass
            pages_data.append({
                'number': n, 'measure_id': mid, 'msk': msk,
                'points': res, 'approx': approx,
            })
        except Exception as e:
            skipped.append(f'{n} ({e})')

    if not pages_data:
        return {'error': 'Не удалось построить ни одного графика', 'skipped': skipped}

    fd, path = tempfile.mkstemp(suffix='.pdf', prefix='graphs_range_')
    os.close(fd)

    cols, rows = 3, 3
    with PdfPages(path) as pdf:
        for i in range(0, len(pages_data), per_page):
            chunk = pages_data[i:i + per_page]
            fig, axes = plt.subplots(rows, cols, figsize=(16.5, 11.7))
            axes = axes.flatten()
            for ax in axes:
                ax.set_visible(False)
            for j, item in enumerate(chunk):
                ax = axes[j]
                ax.set_visible(True)
                for s in item['points'].series:
                    rgb = tuple(c / 255 for c in s.color)
                    if s.kind == 'scatter':
                        ax.scatter(s.xs, s.ys, s=10, color=rgb,
                                   edgecolors='k', linewidths=0.2)
                    else:
                        ax.plot(s.xs, s.ys, '-', color=rgb, lw=1.0)
                if item.get('approx'):
                    for s in item['approx'].series:
                        if s.kind == 'line':
                            rgb = tuple(c / 255 for c in s.color)
                            ax.plot(s.xs, s.ys, '-', color=rgb, lw=1.2, alpha=0.85)
                title = f"N{item['number']}"
                if item.get('msk'):
                    title += f"  МСК {item['msk']}"
                if item.get('measure_id'):
                    title += f"  ID {item['measure_id']}"
                ax.set_title(title, fontsize=9)
                ax.grid(True, alpha=0.25)
                ax.tick_params(labelsize=7)
            fig.suptitle(
                f'Графики {param}  |  {i+1}–{i+len(chunk)} из {len(pages_data)}',
                fontsize=12)
            fig.tight_layout(rect=[0, 0, 1, 0.96])
            pdf.savefig(fig)
            plt.close(fig)

    _open_path(path)
    return {
        'action': 'pdf_numbers', 'path': path,
        'built': len(pages_data), 'skipped': skipped[:30],
        'param': param, 'status': 'saved_and_opened',
    }


def _tool_print_graphs_msk(params, dpg_):
    params = dict(params or {})
    params['print'] = True
    mode = (params.get('mode') or 'all_on_one').lower()
    if mode in ('density', 'распределение', 'kde'):
        return _tool_density(params, dpg_)
    return _tool_all_on_one(params, dpg_)


# ---------------------------------------------------------------------------
# Диспетчер
# ---------------------------------------------------------------------------
_TOOLS = {
    'open_graphs_msk':      _tool_open_graphs_msk,
    'open_graphs_numbers':  _tool_open_graphs_numbers,
    'open_by_measure_id':   _tool_open_by_measure_id,
    'all_on_one':           _tool_all_on_one,
    'density':              _tool_density,
    'pdf_numbers':          _tool_pdf_numbers,
    'print_graphs_msk':     _tool_print_graphs_msk,
    'compare_msk':          _tool_compare_msk,
    'auto_report':          _tool_auto_report,
}


def execute(name: str, params: dict, dpg_) -> dict:
    fn = _TOOLS.get(name)
    if not fn:
        return {'error': f'Неизвестный graph-tool: {name}',
                'hint': f'Доступны: {list(_TOOLS)}'}
    try:
        return fn(params or {}, dpg_)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}


def format_result(name: str, res: dict) -> str:
    if not isinstance(res, dict):
        return str(res)
    if res.get('error'):
        msg = f"Ошибка ({name}): {res['error']}"
        if res.get('hint'):
            msg += f"\n→ {res['hint']}"
        return msg
    action = res.get('action') or name
    parts = [f"[{action}]"]
    if res.get('msk'):
        parts.append(f"МСК {res['msk']}")
    if res.get('msk_a') and res.get('msk_b'):
        parts.append(f"МСК {res['msk_a']} vs {res['msk_b']}")
    if res.get('measure_id'):
        parts.append(f"ID {res['measure_id']}")
    if res.get('param'):
        parts.append(f"параметр {res['param']}")
    if res.get('count') is not None:
        parts.append(f"n={res['count']}")
    if res.get('series_count') is not None:
        parts.append(f"серий={res['series_count']}")
    if res.get('built') is not None:
        parts.append(f"построено={res['built']}")
    if res.get('anomalies') is not None:
        parts.append(f"аномалий={res['anomalies']}")
    if res.get('quality') and isinstance(res['quality'], dict):
        q = res['quality']
        parts.append(f"{q.get('quality')}: {q.get('after')}/{q.get('before')}")
    elif res.get('quality'):
        parts.append(str(res['quality']))
    if res.get('path'):
        parts.append(f"PDF: {res['path']}")
    if res.get('note'):
        parts.append(res['note'])
    if res.get('pdf') and isinstance(res['pdf'], dict) and res['pdf'].get('path'):
        parts.append(f"PDF: {res['pdf']['path']}")
    if res.get('stats_a') and res.get('stats_b'):
        sa, sb = res['stats_a'], res['stats_b']
        if not sa.get('error') and not sb.get('error'):
            parts.append(
                f"A: n={sa.get('count')} mean={sa.get('mean'):.4g}; "
                f"B: n={sb.get('count')} mean={sb.get('mean'):.4g}"
            )
    return '  '.join(parts)
