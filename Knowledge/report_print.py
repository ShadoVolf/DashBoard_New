# -*- coding: utf-8 -*-
"""
Печать протокола Knowledge в PDF.

Форма как в Archive_View: Temperature_Measure.Report.create_protocol
(+ open_pdf после экспорта).

Filtr_Freq берётся из колонки Filtr_Freq, иначе из Filtr_Freq_pred.
"""
from __future__ import annotations

import os
import platform
import subprocess
import traceback
from datetime import datetime
from typing import Any, Dict, Optional

import pandas as pd

from .constants import PROTOCOL_PARAMS, PARAM_ALIASES, TARGET_COL


def _resolve_col(df: pd.DataFrame, param: str) -> Optional[str]:
    aliases = PARAM_ALIASES.get(param, (param,))
    cols_lower = {c.lower(): c for c in df.columns}
    for a in aliases:
        if a in df.columns:
            return a
        if a.lower() in cols_lower:
            return cols_lower[a.lower()]
    return None


def _protocol_dir() -> str:
    try:
        import Options
        path = Options.get_measure_protokol_path()
        if path:
            os.makedirs(path, exist_ok=True)
            return path
    except Exception as e:
        print(f"[Knowledge/report] get_measure_protokol_path: {e}", flush=True)
    path = os.path.join(os.getcwd(), "protocols")
    os.makedirs(path, exist_ok=True)
    return path


def generate_filename(measure_id: Any, extension: str = "pdf", print_version: bool = False) -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    suffix = "_print" if print_version else ""
    mid = measure_id if measure_id not in (None, "", 0, "0") else "Knowledge"
    return f"{mid}_{timestamp}{suffix}.{extension}"


def open_pdf(filename: str) -> None:
    """Открыть PDF в системной программе просмотра (как Temperature_Measure.Report.open_pdf)."""
    if not filename:
        return
    try:
        from Temperature_Measure.Report import open_pdf as tm_open
        tm_open(filename)
        return
    except Exception:
        pass
    try:
        if not os.path.isfile(filename):
            print(f"[Knowledge/report] файл не найден: {filename}", flush=True)
            return
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["open", filename], check=False)
        elif system == "Windows":
            os.startfile(filename)  # type: ignore[attr-defined]
        else:
            subprocess.run(["xdg-open", filename], check=False)
    except Exception as e:
        print(f"[Knowledge/report] open_pdf: {e}", flush=True)


def ensure_filtr_freq(df: pd.DataFrame) -> pd.DataFrame:
    """
    Для протокола нужна колонка Filtr_Freq.
    Если пусто — подставляем Filtr_Freq_pred.
    """
    out = df.copy()
    pred_col = "Filtr_Freq_pred" if "Filtr_Freq_pred" in out.columns else None
    ff_col = _resolve_col(out, TARGET_COL)

    if ff_col is None and pred_col:
        out[TARGET_COL] = pd.to_numeric(out[pred_col], errors="coerce")
        return out

    if ff_col is not None:
        if ff_col != TARGET_COL:
            out[TARGET_COL] = out[ff_col]
        ff = pd.to_numeric(out[TARGET_COL], errors="coerce")
        if pred_col:
            pred = pd.to_numeric(out[pred_col], errors="coerce")
            out[TARGET_COL] = ff.where(ff.notna(), pred)
        else:
            out[TARGET_COL] = ff
    return out


def _pick_spc(df: pd.DataFrame, view_data: Optional[Dict[str, Any]] = None) -> str:
    if view_data:
        for k in ("Spc", "spc", "Spec"):
            v = view_data.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()
    for c in ("Spc", "SPC", "spc", "Spec"):
        if c in df.columns:
            vals = df[c].dropna().astype(str).str.strip()
            vals = vals[vals != ""]
            if not vals.empty:
                return str(vals.iloc[0])
    return ""


def _pick_psi_type(view_data: Optional[Dict[str, Any]] = None) -> str:
    if view_data:
        for k in ("Protokol_Type", "psi_type", "Psi_Type"):
            v = view_data.get(k)
            if v in ("ПСИ", "ОТК"):
                return str(v)
    return "ПСИ"


def _filtr_freq_series(df: pd.DataFrame) -> pd.Series:
    """Числовые Filtr_Freq в Гц (из Filtr_Freq или Filtr_Freq_pred)."""
    work = ensure_filtr_freq(df)
    col = TARGET_COL if TARGET_COL in work.columns else None
    if col is None:
        return pd.Series([pd.NA] * len(work), index=work.index)
    return pd.to_numeric(work[col], errors="coerce")


def _format_filtr_hz(v: Any) -> Any:
    """Значение для ячейки протокола: целое Гц или ''."""
    if v is None:
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return str(v)


def inject_filtr_freq_column(
    data_df: pd.DataFrame,
    source_df: pd.DataFrame,
    headers: Dict[str, Any],
) -> tuple:
    """
    Обязательная колонка Filtr_Freq (Гц) в data_df для PDF.

    - только значения, без норм (колонка НЕ добавляется в spc_map →
      в шапке Макс/Мин пустые, как у служебных полей);
    - вставляется перед Status / Status2;
    - выравнивание по Numbers/Number, иначе по порядку строк.
    """
    if data_df is None or data_df.empty:
        return data_df, headers

    out = data_df.copy()
    hdrs = dict(headers or {})
    col_name = "Filtr_Freq"
    hdrs[col_name] = "Filtr_Freq, Гц"

    src = ensure_filtr_freq(source_df)
    ff = _filtr_freq_series(src)

    # ключ для стыковки строк протокола с исходными данными
    def _num_key(frame: pd.DataFrame) -> Optional[pd.Series]:
        for c in ("Numbers", "Number", "N", "number"):
            if c in frame.columns:
                return frame[c].map(lambda x: str(x).strip() if pd.notna(x) else "")
        return None

    keys_out = _num_key(out)
    keys_src = _num_key(src)

    values: list = []
    if keys_out is not None and keys_src is not None:
        # map number -> first filtr value
        tmp = pd.DataFrame({"_k": keys_src, "_ff": ff})
        tmp = tmp.dropna(subset=["_k"])
        tmp = tmp[tmp["_k"] != ""]
        mapping = {}
        for k, v in zip(tmp["_k"], tmp["_ff"]):
            if k not in mapping:
                mapping[k] = v
        for k in keys_out:
            values.append(_format_filtr_hz(mapping.get(k, "")))
    else:
        # fallback: по позиции
        ff_list = [_format_filtr_hz(v) for v in ff.tolist()]
        for i in range(len(out)):
            values.append(ff_list[i] if i < len(ff_list) else "")

    # убрать старую колонку, если уже была (из spc_map) — перезапишем без норм
    if col_name in out.columns:
        out = out.drop(columns=[col_name])

    # вставить перед Status
    insert_at = len(out.columns)
    for i, c in enumerate(out.columns):
        if c in ("Status", "Status2"):
            insert_at = i
            break
    out.insert(insert_at, col_name, values)

    n_filled = sum(1 for v in values if v != "" and v is not None)
    print(
        f"[Knowledge/report] колонка Filtr_Freq (Гц) добавлена в протокол, "
        f"заполнено {n_filled}/{len(values)}",
        flush=True,
    )
    return out, hdrs


def prepare_protocol_df(data_df: pd.DataFrame) -> pd.DataFrame:
    """Упрощённая таблица Number + PROTOCOL_PARAMS (fallback)."""
    data_df = ensure_filtr_freq(data_df)
    rows = []
    num_col = None
    for c in ("Number", "Numbers", "number", "Nomer", "N", "№"):
        if c in data_df.columns:
            num_col = c
            break
    for _, row in data_df.iterrows():
        item: Dict[str, Any] = {"Number": row[num_col] if num_col else ""}
        for p in PROTOCOL_PARAMS:
            col = _resolve_col(data_df, p)
            if col is not None:
                item[p] = row[col]
            elif p == TARGET_COL and "Filtr_Freq_pred" in data_df.columns:
                item[p] = row["Filtr_Freq_pred"]
            else:
                item[p] = None
        rows.append(item)
    return pd.DataFrame(rows)


def _print_via_archive(
    df: pd.DataFrame,
    measure_id: Any,
    view_data: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Тот же путь, что Archive_View.Archive_Print._print_single_protocol:
    build_archive_* → Temperature_Measure.Report.create_protocol → open_pdf.
    """
    from Temperature_Measure.Report import (
        create_protocol,
        generate_filename as tm_generate_filename,
        open_pdf as tm_open_pdf,
    )
    from Archive_View.Archive_Data import (
        load_specification,
        load_spc_map_for_archive,
        build_archive_print_data,
        build_archive_status_df,
        build_view_data_from_archive,
        get_archive_statistics,
        get_headers_dict,
        get_round_dict,
    )

    work = ensure_filtr_freq(df)
    spc_name = _pick_spc(work, view_data)
    if not spc_name:
        print("[Knowledge/report] нет Spc — нельзя собрать нормы для протокола", flush=True)
        return None

    spc_df = load_specification(spc_name)
    if spc_df is None or spc_df.empty:
        print(f"[Knowledge/report] спецификация «{spc_name}» не найдена", flush=True)
        return None
    spc_row = spc_df.iloc[0]

    psi_type = _pick_psi_type(view_data)
    # Archive_UI._load_spc_map_for_display может зависеть от UI-галочек —
    # для Knowledge берём load_spc_map_for_archive (Use=1 из specification).
    try:
        from Archive_View.Archive_UI import _load_spc_map_for_display
        spc_map = _load_spc_map_for_display(spc_name, psi_type)
    except Exception:
        spc_map = load_spc_map_for_archive(spc_name)
    if spc_map is None or getattr(spc_map, "empty", True):
        print(f"[Knowledge/report] пустой spc_map для «{spc_name}»", flush=True)
        return None

    data_df = build_archive_print_data(work, spc_map)
    # create_protocol всегда делает drop('Status2') без errors='ignore'
    if "Status2" not in data_df.columns:
        data_df = data_df.copy()
        data_df["Status2"] = data_df["Status"] if "Status" in data_df.columns else ""

    status_df = build_archive_status_df(work, spc_map)
    vd = build_view_data_from_archive(work, spc_row, psi_type=psi_type)
    if view_data:
        for k, v in view_data.items():
            if v is not None and str(v).strip() != "":
                vd[k] = v
    # пометка, что протокол из Knowledge (предсказанный Filtr_Freq)
    if "Note" not in vd or not vd.get("Note"):
        vd["Note"] = "Knowledge / Filtr_Freq"

    stats_df = get_archive_statistics(work, spc_map)
    headers = get_headers_dict(spc_map)
    round_map = get_round_dict(spc_map)

    # Обязательная колонка Filtr_Freq в Гц — только значения, без норм
    data_df, headers = inject_filtr_freq_column(data_df, work, headers)
    # убрать Filtr_Freq из spc_map, чтобы в шапке не было Макс/Мин
    try:
        if spc_map is not None and not getattr(spc_map, "empty", True):
            if "Parameter" in spc_map.columns:
                spc_map = spc_map[
                    ~spc_map["Parameter"].astype(str).str.strip().isin(
                        ("Filtr_Freq", "FiltrFreq", "filtr_freq")
                    )
                ].copy()
    except Exception as e:
        print(f"[Knowledge/report] spc_map Filtr_Freq strip: {e}", flush=True)

    if "MSK" in work.columns:
        uniq = work["MSK"].dropna().unique()
        if len(uniq) > 1:
            vd["MSK"] = f"- все МСК - ({len(uniq)})"
            vd["Full_Msk"] = "- все МСК -"

    fname = tm_generate_filename(measure_id)
    print(
        f"[Knowledge/report] create_protocol mid={measure_id} spc={spc_name!r} "
        f"rows={len(data_df)} file={fname}",
        flush=True,
    )

    # округление статистики как в Archive (если доступен patch-контекст — не обязателен)
    try:
        import Temperature_Measure.Report as _Report
        _orig = _Report.format_parameter_stat

        def _fmt(col, metric, stats_df_):
            param_stats = stats_df_[stats_df_["Parameter"] == col]
            if param_stats.empty:
                return "-"
            value = param_stats[metric].values[0]
            if pd.isna(value):
                return "-"
            if metric in ("Брак", "Годные"):
                return f"{int(value)}"
            decimals = 2
            if col in (round_map or {}):
                try:
                    decimals = int(round_map[col])
                except (TypeError, ValueError):
                    decimals = 2
            try:
                return f"{float(value):.{decimals}f}"
            except (TypeError, ValueError):
                return str(value)

        _Report.format_parameter_stat = _fmt
        try:
            path = create_protocol(
                data_df, status_df, headers, spc_map, vd, stats_df, measure_id, fname
            )
        finally:
            _Report.format_parameter_stat = _orig
    except Exception:
        path = create_protocol(
            data_df, status_df, headers, spc_map, vd, stats_df, measure_id, fname
        )

    if path and os.path.isfile(path):
        tm_open_pdf(path)
        print(f"[Knowledge/report] PDF открыт: {path}", flush=True)
        return path
    print(f"[Knowledge/report] create_protocol вернул путь без файла: {path!r}", flush=True)
    return path


def _print_fallback_simple(
    df: pd.DataFrame,
    measure_id: Any,
    view_data: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """Простой PDF (reportlab), если Archive/TM недоступны."""
    try:
        from reportlab.lib.pagesizes import A4, landscape
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib import colors
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except Exception as e:
        print(f"[Knowledge/report] reportlab недоступен: {e}", flush=True)
        return None

    proto = prepare_protocol_df(df)
    if proto.empty:
        return None

    out_dir = _protocol_dir()
    fname = generate_filename(measure_id, "pdf")
    full = os.path.join(out_dir, fname)

    try:
        for font_name, font_path in (
            ("Arial", os.path.join("fonts", "ArialRegular.ttf")),
            ("Arial", "ArialRegular.ttf"),
        ):
            if os.path.isfile(font_path):
                pdfmetrics.registerFont(TTFont(font_name, font_path))
                break
    except Exception:
        pass

    styles = getSampleStyleSheet()
    try:
        title_style = styles["Heading2"]
        title_style.fontName = "Arial"
    except Exception:
        title_style = styles["Heading2"]

    doc = SimpleDocTemplate(
        full,
        pagesize=landscape(A4),
        leftMargin=10 * mm,
        rightMargin=10 * mm,
        topMargin=10 * mm,
        bottomMargin=12 * mm,
    )
    elements = []
    spc = _pick_spc(df, view_data)
    elements.append(
        Paragraph(
            f"Протокол Knowledge / Filtr_Freq  MID={measure_id}  Spc={spc}",
            title_style,
        )
    )
    elements.append(Spacer(1, 4 * mm))

    cols = list(proto.columns)
    header = cols
    body = []
    for _, row in proto.iterrows():
        line = []
        for c in cols:
            v = row[c]
            if v is None or (isinstance(v, float) and pd.isna(v)):
                line.append("")
            else:
                try:
                    line.append(f"{float(v):.6g}")
                except (TypeError, ValueError):
                    line.append(str(v))
        body.append(line)

    table = Table([header] + body, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 7),
                ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    elements.append(table)
    doc.build(elements)
    open_pdf(full)
    print(f"[Knowledge/report] fallback PDF: {full}", flush=True)
    return full


def export_protocol_csv(
    data_df: pd.DataFrame,
    measure_id: Any,
    out_dir: Optional[str] = None,
) -> str:
    out_dir = out_dir or _protocol_dir()
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, generate_filename(measure_id, "csv"))
    prepare_protocol_df(data_df).to_csv(path, index=False, encoding="utf-8-sig")
    return path


def print_or_export(
    data_df: pd.DataFrame,
    measure_id: Any,
    view_data: Optional[Dict[str, Any]] = None,
    prefer_pdf: bool = True,
    open_after: bool = True,
) -> str:
    """
    Основная точка входа из window.do_print.

    1) PDF через Archive + Temperature_Measure.Report (форма как в archive_view)
    2) fallback — простой PDF
    3) CSV, если PDF не удалось
    После успешного PDF файл открывается (open_after=True).
    """
    if data_df is None or data_df.empty:
        raise ValueError("Нет данных для протокола")

    work = ensure_filtr_freq(data_df)
    path: Optional[str] = None

    if prefer_pdf:
        try:
            path = _print_via_archive(work, measure_id, view_data)
        except Exception as e:
            print(f"[Knowledge/report] archive/TM protocol failed: {e}", flush=True)
            traceback.print_exc()
            path = None

        if not path or not os.path.isfile(str(path)):
            try:
                path = _print_fallback_simple(work, measure_id, view_data)
            except Exception as e:
                print(f"[Knowledge/report] fallback PDF failed: {e}", flush=True)
                traceback.print_exc()
                path = None

    if not path or not os.path.isfile(str(path)):
        path = export_protocol_csv(work, measure_id)
        print(f"[Knowledge/report] экспорт CSV: {path}", flush=True)
        if open_after:
            try:
                if platform.system() == "Windows":
                    os.startfile(path)  # type: ignore[attr-defined]
                elif platform.system() == "Darwin":
                    subprocess.run(["open", path], check=False)
                else:
                    subprocess.run(["xdg-open", path], check=False)
            except Exception:
                pass
        return path

    # open_pdf уже вызван внутри _print_via_archive / fallback;
    # если open_after и путь есть — повторно не мешает
    if open_after and path and os.path.isfile(path):
        try:
            open_pdf(path)
        except Exception:
            pass
    return str(path)
