"""Патч protocol_tools — п.2: flag latest (sort by dataR, head(1))."""
from __future__ import annotations


def install_protocol_tools_patches():
    from . import protocol_tools as pt

    if getattr(pt, '_assistant_patches_installed', False):
        return

    _orig_search = pt._tool_search_protocols

    def _tool_search_protocols(params, ctx, dpg_):
        params = dict(params or {})

        # soft MSK (п.1) — на случай прямого вызова tools
        if (params.get('msk')
                and not params.get('msk_partial')
                and not params.get('msk_exact_only')):
            params['msk_partial'] = params['msk']
            params['msk'] = None

        latest = bool(params.get('latest'))
        if latest:
            try:
                params['limit'] = max(int(params.get('limit') or 1), 50)
            except (TypeError, ValueError):
                params['limit'] = 50

        res = _orig_search(params, ctx, dpg_)
        if not isinstance(res, dict) or res.get('error'):
            return res

        df = ctx.get('last_search_df')
        if df is not None and not getattr(df, 'empty', True):
            if 'dataR' in getattr(df, 'columns', []):
                try:
                    df = df.sort_values('dataR', ascending=False)
                    ctx['last_search_df'] = df
                except Exception:
                    pass
            if latest:
                df = df.head(1)
                ctx['last_search_df'] = df
                if len(df) == 1:
                    try:
                        ctx['last_protokol_id'] = pt._int_or(
                            df.iloc[0].get('Measure_protokol_ID'), 0)
                    except Exception:
                        pass
                protocols = []
                for _, r in df.iterrows():
                    protocols.append({
                        'id': pt._int_or(r.get('Measure_protokol_ID'), 0),
                        'protokol_n': str(r.get('ProtokolN') or ''),
                        'msk': str(r.get('MSK') or ''),
                        'spc': str(r.get('Spc') or ''),
                        'date': str(r.get('dataR') or '')[:16],
                        'measure_id': pt._int_or(r.get('Measure_ID'), 0),
                        'type': str(r.get('PsiType') or 'ОТК'),
                        'count_items': pt._int_or(r.get('Current_Count'), 0),
                        'total_items': pt._int_or(r.get('Total_Count'), 0),
                        'rows': (
                            f"{pt._int_or(r.get('Current_Count'), 0)}/"
                            f"{pt._int_or(r.get('Total_Count'), 0)}"
                        ),
                    })
                res = dict(res)
                res['count'] = len(df)
                res['protocols'] = protocols
                res['latest'] = True

        return res

    pt._tool_search_protocols = _tool_search_protocols
    if hasattr(pt, '_TOOLS') and isinstance(pt._TOOLS, dict):
        pt._TOOLS['search_protocols'] = _tool_search_protocols

    pt._assistant_patches_installed = True
