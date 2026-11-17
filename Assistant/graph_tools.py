"""Инструменты ассистента для модуля Графики (ResonatorGraph).

Соглашения (как в protocol_tools):
  * Каждый tool возвращает dict. Ошибка — {'error': str, 'hint': str|None}.
  * Побочные эффекты (открытие окон, PDF) выполняются сразу.
  * Параметр по умолчанию — F (без нагрузки).
  * При нескольких замерах на номер берётся последний по дате.
"""
from __future__ import annotations

import os
import re
import tempfile
from typing import Optional

from Archive_View.Archive_Data import parse_numbers_input

# ---------------------------------------------------------------------------
# Логирование в окно ассистента
# ---------------------------------------------------------------------------
def _log(dpg_, text, color=None):
    try:
        from Statistik.dashboard_llm import _append_assistant_log
        _append_assistant_log(dpg_, text, color=color)
    except Exception:
        print(f'[Assistant.graph] {text}')


# ---------------------------------------------------------------------------
# Параметры
# ---------------------------------------------------------------------------
_PARAM_ALIASES = {
    'f': 'F (без нагрузки)',
    'f без': 'F (без нагрузки)',
    'f без нагрузки': 'F (без нагрузки)',
    'частота': 'F (без нагрузки)',
    'fl': 'FL (с нагрузкой)',
    'f с нагрузкой': 'FL (с нагрузкой)',
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
    # прямое совпадение с label
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


# ---------------------------------------------------------------------------
# Запуск модуля
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
# Tools
# ---------------------------------------------------------------------------
def _tool_open_graphs_msk(params, dpg_):
    """Открыть окно графиков для МСК (опционально параметр)."""
    msk = _norm_msk(params.get('msk') or params.get('msk_partial'))
    if not msk:
        return {'error': 'Не указана МСК', 'hint': 'Пример: открыть графики МСК 456'}

    param = _resolve_param(params.get('param'))
    res = _ensure_graph_module(dpg_)
    if res.get('status') == 'error':
        return res

    try:
        from ResonatorGraph.ui import open_for_msk
        open_for_msk(msk)
        ctrl = _get_controller()
        _set_param(ctrl, param)
        # перестроить после смены параметра
        try:
            from ResonatorGraph import ui as rg_ui
            if hasattr(rg_ui, '_on_param_change'):
                rg_ui._on_param_change()
        except Exception:
            pass
        return {
            'action': 'opened',
            'msk': msk,
            'param': param,
            'note': f'Открыты графики МСК {msk}, параметр {param}',
        }
    except Exception as e:
        return {'error': f'{type(e).__name__}: {e}'}


def _tool_open_graphs_numbers(params, dpg_):
    """Открыть графики по списку/диапазону номеров.

    Если номера из разных МСК/замеров — берём последний замер по дате.
    """
    numbers = _as_numbers(params.get('numbers'))
    if not numbers:
        return {'error': 'Не указаны номера',
                'hint': 'Пример: графики номеров JN4450-JN4460'}

    param = _resolve_param(params.get('param'))
    res = _ensure_graph_module(dpg_)
    if res.get('status') == 'error':
        return res

    try:
        from ResonatorGraph.ui import create_graph_window, open_for_measure_id
        from ResonatorGraph.logic import GraphController
        # Найти лучший Measure_ID для первого номера (или группы)
        mid, msk, info = _resolve_latest_measure_for_numbers(numbers)
        if not mid and not msk:
            return {'error': f'Не найдены данные для номеров {numbers[:5]}...',
                    'hint': 'Проверьте номера или источник данных (основная/архив)'}

        create_graph_window()
        ctrl = _get_controller()
        _set_param(ctrl, param)

        if mid:
            open_for_measure_id(str(mid))
        elif msk:
            from ResonatorGraph.ui import open_for_msk
            open_for_msk(msk)

        # Выбрать первый номер
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


def _resolve_latest_measure_for_numbers(numbers):
    """Для списка номеров найти Measure_ID последнего по дате замера.

    Возвращает (measure_id, msk, info_dict).
    """
    from ResonatorGraph import db
    from ResonatorGraph.constants import get_main_table

    table = get_main_table()
    # Ищем все Measure_ID, где есть хотя бы один из номеров
    placeholders = ','.join(f':n{i}' for i in range(len(numbers)))
    binds = {f'n{i}': n for i, n in enumerate(numbers)}

    # Предпочитаем таблицу с датой, если есть
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
        # fallback без dataR
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


def _tool_all_on_one(params, dpg_):
    """Все номера МСК (или ID) на одном поле."""
    msk = _norm_msk(params.get('msk'))
    measure_id = params.get('measure_id')
    param = _resolve_param(params.get('param'))
    do_print = bool(params.get('print') or params.get('pdf'))

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

        # Построить все на одном поле
        from ResonatorGraph import ui as rg_ui
        build_res = ctrl.build_all_numbers(show_msk=True, show_approx=True, show_points=True)
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

        if do_print:
            pdf_res = _export_all_on_one_pdf(ctrl, build_res)
            out['pdf'] = pdf_res

        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}


def _export_all_on_one_pdf(ctrl, res):
    """PDF: все серии на одном поле (A3-альбом)."""
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
    # легенда только если мало серий
    if len(res.series) <= 24:
        ax.legend(fontsize=7, loc='best')

    fd, path = tempfile.mkstemp(suffix='.pdf', prefix='graphs_all_')
    os.close(fd)
    with PdfPages(path) as pdf:
        pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)

    try:
        os.startfile(path)  # Windows
    except Exception:
        try:
            import subprocess
            subprocess.Popen(['xdg-open', path])
        except Exception:
            pass

    return {'path': path, 'status': 'saved_and_opened'}


def _tool_density(params, dpg_):
    """Плотность распределения параметра по МСК (KDE)."""
    msk = _norm_msk(params.get('msk'))
    measure_id = params.get('measure_id')
    param = _resolve_param(params.get('param'))
    do_print = bool(params.get('print') or params.get('pdf'))

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

        # Расчёт статистики + KDE (используем метод контроллера, если есть)
        stats = None
        if hasattr(ctrl, 'compute_distribution'):
            stats = ctrl.compute_distribution()
        elif hasattr(ctrl, 'build_distribution'):
            stats = ctrl.build_distribution()
        else:
            # fallback: ручной сбор значений при T_ref
            stats = _compute_density_fallback(ctrl)

        if isinstance(stats, dict) and stats.get('error'):
            return stats
        if not stats:
            return {'error': 'Не удалось рассчитать распределение'}

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
        }

        if do_print:
            out['pdf'] = _export_density_pdf(stats, ctrl)

        return out
    except Exception as e:
        import traceback
        traceback.print_exc()
        return {'error': f'{type(e).__name__}: {e}'}


def _compute_density_fallback(ctrl):
    """Собрать значения параметра при T_ref по всем номерам МСК/ID."""
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
        'label': label,
        'unit': unit,
        'count': len(values),
        'mean': float(np.mean(arr)),
        'median': float(np.median(arr)),
        'std': float(np.std(arr, ddof=1)) if len(arr) > 1 else 0.0,
        'min': float(np.min(arr)),
        'max': float(np.max(arr)),
        'q1': float(np.percentile(arr, 25)),
        'q3': float(np.percentile(arr, 75)),
        'iqr': float(np.percentile(arr, 75) - np.percentile(arr, 25)),
        'range': float(np.max(arr) - np.min(arr)),
        'kde_x': kde_x.tolist() if hasattr(kde_x, 'tolist') else list(kde_x),
        'kde_y': kde_y.tolist() if hasattr(kde_y, 'tolist') else list(kde_y),
        'T_ref': ctrl.T_ref,
        'skipped': skipped,
        'measure_id': ctrl.measure_id,
        'anomalies': [],
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

    fig, ax = plt.subplots(figsize=(11.69, 8.27))  # A4 landscape
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
    ax.set_title(title)
    ax.grid(True, alpha=0.3)

    # аннотация статистик
    txt = (f"mean={stats.get('mean'):.4g}  median={stats.get('median'):.4g}\n"
           f"σ={stats.get('std'):.4g}  n={stats.get('count')}")
    ax.text(0.98, 0.97, txt, transform=ax.transAxes, ha='right', va='top',
            fontsize=9, bbox=dict(boxstyle='round', facecolor='wheat', alpha=0.5))

    fd, path = tempfile.mkstemp(suffix='.pdf', prefix='density_')
    os.close(fd)
    with PdfPages(path) as pdf:
        pdf.savefig(fig, bbox_inches='tight')
    plt.close(fig)

    try:
        os.startfile(path)
    except Exception:
        try:
            import subprocess
            subprocess.Popen(['xdg-open', path])
        except Exception:
            pass

    return {'path': path, 'status': 'saved_and_opened'}


def _tool_pdf_numbers(params, dpg_):
    """PDF графиков по диапазону номеров (даже из разных МСК/замеров).

    Для каждого номера берётся последний по дате замер.
    """
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
        import numpy as np
    except ImportError:
        return {'error': 'matplotlib не установлен'}

    from ResonatorGraph.logic import GraphController
    from ResonatorGraph.constants import PARAM_BY_LABEL

    ctrl = GraphController()
    ctrl.param_label = param

    # Для каждого номера — последний Measure_ID
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
                    'degree': ctrl.degree,
                    'show_approx': True,
                    'show_msk': False,
                    'show_order': False,
                })
            except Exception:
                pass
            pages_data.append({
                'number': n,
                'measure_id': mid,
                'msk': msk,
                'points': res,
                'approx': approx,
            })
        except Exception as e:
            skipped.append(f'{n} ({e})')

    if not pages_data:
        return {'error': 'Не удалось построить ни одного графика',
                'skipped': skipped}

    fd, path = tempfile.mkstemp(suffix='.pdf', prefix='graphs_range_')
    os.close(fd)

    cols = 3
    rows = 3
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
                pts = item['points']
                for s in pts.series:
                    rgb = tuple(c / 255 for c in s.color)
                    if s.kind == 'scatter':
                        ax.scatter(s.xs, s.ys, s=10, color=rgb, edgecolors='k',
                                   linewidths=0.2)
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

            fig.suptitle(f'Графики {param}  |  {i+1}–{i+len(chunk)} из {len(pages_data)}',
                         fontsize=12)
            fig.tight_layout(rect=[0, 0, 1, 0.96])
            pdf.savefig(fig)
            plt.close(fig)

    try:
        os.startfile(path)
    except Exception:
        try:
            import subprocess
            subprocess.Popen(['xdg-open', path])
        except Exception:
            pass

    return {
        'action': 'pdf_numbers',
        'path': path,
        'built': len(pages_data),
        'skipped': skipped[:30],
        'param': param,
        'status': 'saved_and_opened',
    }


def _tool_print_graphs_msk(params, dpg_):
    """Печать/PDF всех графиков МСК (сетка или all-on-one)."""
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
    'all_on_one':           _tool_all_on_one,
    'density':              _tool_density,
    'pdf_numbers':          _tool_pdf_numbers,
    'print_graphs_msk':     _tool_print_graphs_msk,
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
    if res.get('param'):
        parts.append(f"параметр {res['param']}")
    if res.get('count') is not None:
        parts.append(f"n={res['count']}")
    if res.get('series_count') is not None:
        parts.append(f"серий={res['series_count']}")
    if res.get('built') is not None:
        parts.append(f"построено={res['built']}")
    if res.get('path'):
        parts.append(f"PDF: {res['path']}")
    if res.get('note'):
        parts.append(res['note'])
    if res.get('pdf') and isinstance(res['pdf'], dict):
        if res['pdf'].get('path'):
            parts.append(f"PDF: {res['pdf']['path']}")
    return '  '.join(parts)
