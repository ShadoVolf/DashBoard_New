import pandas as pd
import dearpygui.dearpygui as dpg
from datetime import datetime
from sqlalchemy import create_engine, text, bindparam
import Options

from Temperature_Measure.Report import (
    create_presentation_protocol, create_psi_protocol, create_simple_otk_protocol,
    open_pdf, generate_filename
)
from Archive_View.Archive_Data import (
    load_specification, load_tu_parameters_for_spec, build_presentation_params,
    rename_fields_to_parameters, build_archive_print_data, build_archive_status_df,
    build_view_data_from_archive, resolve_param_column, _prepare_spc_map,
    get_next_protocol_number_archive
)
from Archive_View.Archive_UI import _load_spc_map_for_display
from .Protocol_Data import log_action, add_numbers_to_protocol
from .Presentation_Cache import get_or_build_presentation_params
from .Protocol_Passport import print_passport_for_protocol

def _engine():
    return create_engine(str(Options.get_connection_string()))


def _nat_sort_key(val):
    """Числа сортируются как числа, строки — как строки."""
    if pd.isna(val): return (2, 0)
    s = str(val).strip()
    if not s: return (2, 0)
    if s.isdigit(): return (0, int(s))
    return (1, s.lower())


def _save_protocol_header(protokol_n, msk, filename, measure_id, count, spc, psi_type):
    """Сохраняет заголовок протокола в psi_measure_protokol_id с указанием типа."""
    engine = _engine()
    with engine.begin() as conn:
        # Добавляем колонку psi_type, если её ещё нет в старой схеме БД
        try:
            conn.execute(text(
                "ALTER TABLE `psi_measure_protokol_id` "
                "ADD COLUMN `psi_type` VARCHAR(10) DEFAULT 'ОТК'"
            ))
        except Exception:
            pass  # Колонка уже существует

        res = conn.execute(text("""
            INSERT INTO `psi_measure_protokol_id` 
            (`ProtokolN`, `MSK`, `File`, `Measure_ID`, `dataR`, `Count`, `Spc`, `psi_type`)
            VALUES (:pn, :msk, :file, :mid, :dataR, :count, :spc, :ptype)
        """), {
            'pn': protokol_n,
            'msk': msk,
            'file': filename,
            'mid': measure_id,
            'dataR': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'count': count,
            'spc': spc,
            'ptype': psi_type
        })
        return res.lastrowid
def print_custom_protocol(measure_id: int, selected_numbers: list[str],
                          psi_type: str = 'ОТК',
                          spc_name: str | None = None):
    """Генерирует новый протокол для выбранных номеров Measure_ID.

    spc_name — резервная спецификация на случай, если в psidata поле Spc
    пустое/NaN (тогда берётся значение из комбо `pm_spc_combo`).
    """
    print(f"[Print] Генерация {psi_type} для Measure_ID={measure_id}, "
          f"N={len(selected_numbers)}")

    if not selected_numbers:
        _status('Не выбрано ни одного номера')
        return

    engine = _engine()
    sql = text("SELECT * FROM psidata WHERE Measure_ID = :mid AND N IN :nums") \
        .bindparams(bindparam("nums", expanding=True))
    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql, conn,
                             params={'mid': measure_id,
                                     'nums': selected_numbers})
    except Exception as e:
        print(f"[Print] Ошибка БД: {e}")
        _status(f'Ошибка БД: {e}')
        return

    if df.empty:
        _status('Данные не найдены')
        return

    # --- Сортировка: числа как числа, строки как строки ---
    if 'N' in df.columns:
        df['_sort_key'] = df['N'].map(_nat_sort_key)
        df = (df.sort_values('_sort_key')
                .drop(columns=['_sort_key'])
                .reset_index(drop=True))

    # --- Спецификация: Spc из данных → fallback → ошибка ---
    spc_val = None
    if 'Spc' in df.columns:
        try:
            v = df.iloc[0].get('Spc')
            if v is not None and not pd.isna(v):
                spc_val = str(v).strip() or None
        except (TypeError, ValueError):
            spc_val = None

    if not spc_val:
        spc_val = (spc_name or '').strip() or None

    if not spc_val:
        _status('Не удалось определить спецификацию — выберите её в списке')
        return

    spc_df = load_specification(spc_val)
    if spc_df.empty:
        _status(f'Спецификация "{spc_val}" не найдена в БД')
        return
    spc_row = spc_df.iloc[0]

    tu_data = load_tu_parameters_for_spec(spc_val) or {
        'tu_name': '', 'tu_row': {}, 'rtype': ''}
    presentation_params = get_or_build_presentation_params(spc_val, tu_data)
    if not presentation_params:
        _status(f'Нет параметров ТУ для спецификации "{spc_val}"')
        return

    # --- Нормы ---
    # _prepare_spc_map добавляет вычисляемые параметры (в т.ч. ABS(Fmax, Fmin)).
    # Нужно для ОБОИХ типов протокола, иначе колонка ABS не появится в data_df
    # и в PDF для ПСИ будет прочерк.
    spc_map = _load_spc_map_for_display(spc_val, psi_type)
    spc_map = _prepare_spc_map(spc_map)
    # --- Фильтрация годных по нормам ---
    mapped = rename_fields_to_parameters(df)
    use_tu_norms = psi_type in ('ОТКп', 'ОТК_простой', 'ОТК-простой')
    good_mask = pd.Series(True, index=mapped.index)
    for p in presentation_params:
        if not p['has_norm']:
            continue
        col = resolve_param_column(mapped, p['param'])
        if col is None:
            continue
        vals = pd.to_numeric(mapped[col], errors='coerce')
        if use_tu_norms:
            if p.get('max_tu') is not None:
                try:
                    good_mask &= (vals <= float(p['max_tu']))
                except (TypeError, ValueError):
                    pass
            if p.get('min_tu') is not None:
                try:
                    good_mask &= (vals >= float(p['min_tu']))
                except (TypeError, ValueError):
                    pass
        else:
            if p['has_max'] and p['max_otk'] is not None:
                good_mask &= (vals <= float(p['max_otk']))
            if p['has_min'] and p['min_otk'] is not None:
                good_mask &= (vals >= float(p['min_otk']))
        good_mask &= vals.notna()

    df_good = df[good_mask].copy()
    if df_good.empty:
        _status(f'Нет годных изделий для протокола ({psi_type})')
        return

    # --- Подготовка данных для PDF ---
    data_df   = build_archive_print_data(df_good, spc_map)
    status_df = build_archive_status_df(df_good, spc_map)
    view_data = build_view_data_from_archive(df_good, spc_row,
                                             psi_type=psi_type)

    def _s(v):
        if v is None:
            return ''
        try:
            if pd.isna(v):
                return ''
        except (TypeError, ValueError):
            pass
        return str(v)

    view_data['TU']       = _s(spc_row.get('TU'))
    view_data['TGK']      = _s(spc_row.get('TGK'))
    view_data['Spc_Text'] = _s(spc_row.get('Text')) or spc_val
    view_data['Date']     = _s(df.iloc[0].get('Date'))

    # 1. Регистрация заголовка протокола
    protokol_n = get_next_protocol_number_archive()
    filename = generate_filename(measure_id).replace('.pdf', f'_{psi_type}.pdf')

    mp_id = _save_protocol_header(
        protokol_n=protokol_n,
        msk=view_data.get('MSK', ''),
        filename=filename,
        measure_id=measure_id,
        count=len(data_df),
        spc=view_data.get('Spc_Text', ''),
        psi_type=psi_type,
    )

    # 2. Сохраняем номера в psi_protokol_archive
    if mp_id:
        add_numbers_to_protocol(mp_id, measure_id,
                                df_good['N'].tolist(), psi_type)
        log_action("CREATE", mp_id, measure_id,
                   f"Создан протокол {psi_type} на {len(df_good)} номеров",
                   "Admin")

    # 3. Генерация PDF
    if psi_type == 'ОТК':
        path = create_presentation_protocol(
            data_df=data_df, status_df=status_df, view_data=view_data,
            tu_data=tu_data, presentation_params=presentation_params,
            spc_row=spc_row, measure_id=measure_id,
            filename=filename, measure_protokol_id=mp_id)
    elif psi_type in ('ОТКп', 'ОТК_простой', 'ОТК-простой'):
        path = create_simple_otk_protocol(
            data_df=data_df, status_df=status_df, view_data=view_data,
            tu_data=tu_data, presentation_params=presentation_params,
            spc_row=spc_row, measure_id=measure_id,
            filename=filename, measure_protokol_id=mp_id,
            protokol_n=protokol_n)
    else:
        path = create_psi_protocol(
            data_df=data_df, status_df=status_df, view_data=view_data,
            tu_data=tu_data, presentation_params=presentation_params,
            spc_row=spc_row, measure_id=measure_id,
            filename=filename, measure_protokol_id=mp_id)

    open_pdf(path)
    _status(f'Протокол N {protokol_n} ({psi_type}) создан '
            f'на {len(df_good)} номеров')

def _status(msg):
    """Статус-строка с ASCII-заменой спецсимволов (иначе в UI видны '?')."""
    try:
        from Archive_View.Archive_UI import _screen_safe
        msg = _screen_safe(str(msg))
    except Exception:
        pass
    if dpg.does_item_exist('protocol_status_text'):
        dpg.set_value('protocol_status_text', msg)


def print_archived_protocol(protokol_id: int):
    """Восстанавливает существующий протокол из psi_protokol_archive
    и печатает его (с сохранением типа ПСИ/ОТК из заголовка)."""
    engine = _engine()

    # 1. Заголовок протокола
    with engine.connect() as conn:
        df_head = pd.read_sql(
            text("SELECT * FROM psi_measure_protokol_id "
                 "WHERE Measure_protokol_ID = :pid"),
            conn, params={'pid': protokol_id})

    if df_head.empty:
        _status('Протокол не найден')
        return

    p_info      = df_head.iloc[0]
    measure_id  = p_info['Measure_ID']
    protokol_n  = p_info['ProtokolN']

    psi_type = 'ОТК'
    if 'psi_type' in p_info.index:
        v = p_info.get('psi_type')
        if v is not None and not pd.isna(v) and str(v).strip():
            psi_type = str(v).strip()
    if psi_type not in ('ПСИ', 'ОТК', 'Паспорт', 'ОТКп', 'ОТК_простой', 'ОТК-простой'):
        psi_type = 'ОТК'

    # 2. Номера из архива
    with engine.connect() as conn:
        df = pd.read_sql(
            text("SELECT * FROM psi_protokol_archive "
                 "WHERE Measure_Protokol_ID = :pid"),
            conn, params={'pid': protokol_id})

    if df.empty:
        _status('В протоколе нет номеров')
        return

    # 3. Сортировка
    if 'N' in df.columns:
        df['_sort_key'] = df['N'].map(_nat_sort_key)
        df = (df.sort_values('_sort_key')
                .drop(columns=['_sort_key'])
                .reset_index(drop=True))

    # 4. Спецификация: из данных → из заголовка → ошибка
    spc_val = None
    if 'Spc' in df.columns:
        try:
            v = df.iloc[0].get('Spc')
            if v is not None and not pd.isna(v):
                spc_val = str(v).strip() or None
        except (TypeError, ValueError):
            spc_val = None

    if not spc_val:
        hv = p_info.get('Spc') if 'Spc' in p_info.index else None
        if hv is not None and not pd.isna(hv):
            spc_val = str(hv).strip() or None

    if not spc_val:
        _status('Не удалось определить спецификацию протокола')
        return


    spc_df = load_specification(spc_val)
    if spc_df.empty:
        _status(f'Спецификация "{spc_val}" не найдена в БД')
        return
    spc_row = spc_df.iloc[0]

    tu_data = load_tu_parameters_for_spec(spc_val) or {
        'tu_name': '', 'tu_row': {}, 'rtype': ''}
    presentation_params = build_presentation_params(spc_val, tu_data)
    if not presentation_params:
        _status(f'Нет параметров ТУ для спецификации "{spc_val}"')
        return

    # 5. Нормы
    spc_map = _load_spc_map_for_display(spc_val, psi_type)
    spc_map = _prepare_spc_map(spc_map)

    # 6. Подготовка данных
    data_df   = build_archive_print_data(df, spc_map)
    status_df = build_archive_status_df(df, spc_map)
    view_data = build_view_data_from_archive(df, spc_row, psi_type=psi_type)

    def _s(v):
        if v is None:
            return ''
        try:
            if pd.isna(v):
                return ''
        except (TypeError, ValueError):
            pass
        return str(v)

    view_data['TU']       = _s(spc_row.get('TU'))
    view_data['TGK']      = _s(spc_row.get('TGK'))
    view_data['Spc_Text'] = _s(spc_row.get('Text')) or spc_val
    view_data['Date']     = _s(df.iloc[0].get('Date'))

    # 7. PDF с тем же Measure_protokol_ID (для QR)
    filename = f"arch_protocol_{protokol_n}_{psi_type}.pdf"

    if psi_type == 'Паспорт':
        # Делегируем генерацию паспорта специализированной функции
        print_passport_for_protocol(protokol_id)
        return
    elif psi_type == 'ОТК':
        path = create_presentation_protocol(
            data_df=data_df, status_df=status_df, view_data=view_data,
            tu_data=tu_data, presentation_params=presentation_params,
            spc_row=spc_row, measure_id=measure_id,
            filename=filename, measure_protokol_id=protokol_id)
    elif psi_type in ('ОТКп', 'ОТК_простой', 'ОТК-простой'):
        path = create_simple_otk_protocol(
            data_df=data_df, status_df=status_df, view_data=view_data,
            tu_data=tu_data, presentation_params=presentation_params,
            spc_row=spc_row, measure_id=measure_id,
            filename=filename, measure_protokol_id=protokol_id,
            protokol_n=protokol_n)
    else:
        path = create_psi_protocol(
            data_df=data_df, status_df=status_df, view_data=view_data,
            tu_data=tu_data, presentation_params=presentation_params,
            spc_row=spc_row, measure_id=measure_id,
            filename=filename, measure_protokol_id=protokol_id)

    open_pdf(path)
    _status(f'Протокол N {protokol_n} ({psi_type}) распечатан')
    log_action("PRINT_ARCHIVE", protokol_id, measure_id,
               f"Печать {psi_type}", "Admin")

