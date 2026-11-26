"""
Загрузка данных из архива.

Каскад: Тип резонатора -> Спецификация -> МСК -> Дата -> Файл / Measure_ID.
Источник данных (основная / временная / архивная таблица) выбирается через
_source_state в Archive_Constants — все «данные замеров» берутся через
_main()/psidatatemp через _temps(). Справочники (specification,
spc_map_table, tu, psidata_map_table, psidata_resonator_lookup) всегда
читаются из статических таблиц.
"""
import pandas as pd
from sqlalchemy import create_engine, text

from Options import get_connection_string

from .Archive_Constants import _source_state

import traceback
import re
import unicodedata


# Явные алиасы: spc-имя -> Column-в-mapped (после rename_fields_to_parameters)
# либо Field из psidata_map_table.
_PARAM_ALIASES = {
    # --- Rb / Rc family (физическая колонка = 'RcRb') ---
    'Rc_Rb':        'Rc_Rbmax',   # ← строка 21 spc_map_table
    'Rb/Rc':        'Rc_Rbmax',   # Note_mini
    'Rb_Rc':        'Rc_Rbmax',
    'RbRc':         'Rc_Rbmax',
    'Rc/Rb':        'Rc_Rbmax',
    'RcRb':         'Rc_Rbmax',
    'Rb/Rbmax':     'Rc_Rbmax',
    'Rc/Rbmax':     'Rc_Rbmax',
    'RcRbmax':      'Rc_Rbmax',
    'Rc_Rbmax':     'Rc_Rbmax',
    'ABS(Fmax, Fmin)': 'Fmaxm',
    'Rmax-Rmin': 'RR1',

    # --- прочие «двойные» имена с / или _ ---
    'ABS(Fmax,Fmin)':       'ABS(Fmax, Fmin)',
    'ABS_Fmax_Fmin':        'ABS(Fmax, Fmin)',
    '(Rmax-R25)/R25*100':   '(Rmax-R25)/R25*100%',
    '(Rmin-R25)/R25*100':   '(Rmin-R25)/R25*100%',
    '(Rmax-R25)/R25%':      '(Rmax-R25)/R25*100%',
    '(Rmin-R25)/R25%':      '(Rmin-R25)/R25*100%',
    'F0-Fl':   'F0-FL', 'F0_FL': 'F0-FL', 'F0-F1': 'F0-FL', 'F0FL': 'F0-FL',
    'Fptp_2':  'Fptp/2',
    'C1-2C0':  'C1_2C0', 'C12C0': 'C1_2C0',
    'C0-C1':   'C0_C1',  'C0C1':  'C0_C1',
    'Rmax_Rmin': 'Rmax/Rmin', 'RmaxRmin': 'Rmax/Rmin',
    'Tmax': 'extr_1', 'Tmin': 'extr_2',
    'TurnOver': 'TurnOver_1',
    # NEW: фазовый шум — явные алиасы, чтобы не полагаться на fuzzy
    'Shum': 'Shum',
    'Shum1': 'Shum_1',
    'Shum2': 'Shum_2',
    'Shum3': 'Shum_3',
    'Shum4': 'Shum_4',
}
# Если основная колонка psidata содержит NULL — берём значение из резервной.
# Ключ — имя параметра как он приходит из спецификации, значение — резервная колонка.
# Резервная колонка psidata, если основная содержит NULL.
_PARAM_FALLBACKS = {
    'Rmax-Rmin': 'RR1',
    'Rmax_Rmin': 'RR1',
    'RmaxRmin':  'RR1',
}


def _coalesce_fallback_inplace(mapped, param, primary_col):
    """Если у param есть fallback-колонка — заполнить NULL в primary_col из неё.

    Меняет mapped in-place; возвращает имя колонки, которую дальше читать.
    Если primary_col нет, но fallback есть — вернёт fallback.
    """
    fb = _PARAM_FALLBACKS.get(param)
    if not fb:
        return primary_col

    if fb not in mapped.columns:
        # fallback-колонки нет — работаем как раньше, но сообщаем один раз
        key = (str(param), 'no_fallback_col')
        if key not in _PARAM_RESOLVE_WARNED:
            _PARAM_RESOLVE_WARNED.add(key)
            print(f"[Archive] fallback-колонка {fb!r} отсутствует, param={param!r}")
        return primary_col

    if primary_col is None or primary_col not in mapped.columns:
        return fb

    if primary_col == fb:
        return primary_col

    s_primary = mapped[primary_col]
    s_fb = mapped[fb]
    if s_primary.isna().any():
        mapped[primary_col] = s_primary.where(s_primary.notna(), s_fb)
        key = (str(param), f'coalesced:{fb}')
        if key not in _PARAM_RESOLVE_WARNED:
            _PARAM_RESOLVE_WARNED.add(key)
            print(f"[Archive] {param!r}: NULL в {primary_col!r} заполнены из {fb!r}")
    return primary_col
# Fuzzy-match запрещаем для пар имён, которые нормализуются одинаково.
# Иначе Rb/Rc и Rc/Rbmax могут случайно «сойтись» не туда.
_PARAM_FUZZY_BLOCK = {
    'rmaxrmin',   # Rmax/Rmin  и  Rmax-Rmin
    'f0fl',       # F0-FL/F0-Fl  — но здесь случай безобидный, можно оставить
}

_PARAM_RESOLVE_WARNED = set()


def _norm_param_name(s: str) -> str:
    """NFKC + casefold + удалить всё, кроме [a-z0-9]."""
    if s is None:
        return ''
    s = unicodedata.normalize('NFKC', str(s))
    s = s.casefold()
    return re.sub(r'[^a-z0-9]', '', s)


def _find_col_by_name(mapped: pd.DataFrame, name: str) -> str | None:
    if not name or mapped is None or mapped.empty:
        return None
    if name in mapped.columns:
        return name
    cf = str(name).strip().casefold()
    for col in mapped.columns:
        if str(col).strip().casefold() == cf:
            return col
    return None
def resolve_param_column(mapped, param, spc_row=None):
    """Найти реальную колонку в mapped для параметра из spc_map_table.

    Порядок поиска:
      1. Точное совпадение имени param.
      2. Явные алиасы (_PARAM_ALIASES).
      3. Через psidata_map_table: Parameter -> Field (и обратно).
      4. Колонки из spc_row: Max / Min / Use (это столбцы в specification;
         для Rc_Rb совпадает с psidata_map_table.Parameter='Rc_Rbmax').
      5. Fuzzy (без регистра/пунктуации), если единственное совпадение.

    Дополнительно: если для параметра задан fallback (_PARAM_FALLBACKS),
    NULL-значения в найденной колонке заполняются из fallback-колонки
    (in-place в mapped). Это нужно для Rmax-Rmin, где исторические записи
    хранят значение в psidata.RR1, а psidata.`Rmax-Rmin` = NULL.
    """
    if mapped is None or mapped.empty or param is None:
        return None

    field_map = get_psidata_field_map()            # {Parameter: Field}
    reverse_map = {f: p for p, f in field_map.items() if p and f}

    candidates = []
    def _add(x):
        if x and x not in candidates:
            candidates.append(x)

    _add(param)

    # (2) алиасы
    a = _PARAM_ALIASES.get(param)
    if a:
        _add(a)
        _add(field_map.get(a))
        _add(reverse_map.get(a))

    # (3) прямой Field из psidata_map_table
    f = field_map.get(param)
    if f:
        _add(f)
        _add(reverse_map.get(f))

    # (4) колонки spec-таблицы: Max/Min/Use
    if spc_row is not None:
        for key in ('Max', 'Min', 'Use'):
            v = spc_row.get(key) if hasattr(spc_row, 'get') else (
                spc_row[key] if isinstance(spc_row, dict) else None)
            if isinstance(v, str) and v:
                _add(v)

    for cand in candidates:
        hit = _find_col_by_name(mapped, cand)
        if hit:
            return _coalesce_fallback_inplace(mapped, param, hit)

    # (5) fuzzy
    target = _norm_param_name(param)
    if not target or target in _PARAM_FUZZY_BLOCK:
        return _coalesce_fallback_inplace(mapped, param, None)
    hits = [c for c in mapped.columns if _norm_param_name(c) == target]
    if len(hits) == 1:
        hit = hits[0]
        key = (str(param), str(hit))
        if key not in _PARAM_RESOLVE_WARNED:
            _PARAM_RESOLVE_WARNED.add(key)
            print(f"[Archive] resolve_param: {param!r} -> колонка {hit!r} (fuzzy)")
        return _coalesce_fallback_inplace(mapped, param, hit)
    return _coalesce_fallback_inplace(mapped, param, None)

def resolve_param_column_4(mapped, param, spc_row=None):
    """Найти реальную колонку в mapped для параметра из spc_map_table.

    Порядок поиска:
      1. Точное совпадение имени param.
      2. Явные алиасы (_PARAM_ALIASES).
      3. Через psidata_map_table: Parameter -> Field (и обратно).
      4. Колонки из spc_row: Max / Min / Use (это столбцы в specification;
         для Rc_Rb совпадает с psidata_map_table.Parameter='Rc_Rbmax').
      5. Fuzzy (без регистра/пунктуации), если единственное совпадение.
    """
    if mapped is None or mapped.empty or param is None:
        return None

    field_map = get_psidata_field_map()            # {Parameter: Field}
    reverse_map = {f: p for p, f in field_map.items() if p and f}

    candidates = []
    def _add(x):
        if x and x not in candidates:
            candidates.append(x)

    _add(param)

    # (2) алиасы
    a = _PARAM_ALIASES.get(param)
    if a:
        _add(a)
        _add(field_map.get(a))
        _add(reverse_map.get(a))

    # (3) прямой Field из psidata_map_table
    f = field_map.get(param)
    if f:
        _add(f)
        _add(reverse_map.get(f))

    # (4) колонки spec-таблицы: Max/Min/Use
    if spc_row is not None:
        for key in ('Max', 'Min', 'Use'):
            v = spc_row.get(key) if hasattr(spc_row, 'get') else (
                spc_row[key] if isinstance(spc_row, dict) else None)
            if isinstance(v, str) and v:
                _add(v)

    for cand in candidates:
        hit = _find_col_by_name(mapped, cand)
        if hit:
            return hit

    # (5) fuzzy
    target = _norm_param_name(param)
    if not target or target in _PARAM_FUZZY_BLOCK:
        return None
    hits = [c for c in mapped.columns if _norm_param_name(c) == target]
    if len(hits) == 1:
        hit = hits[0]
        key = (str(param), str(hit))
        if key not in _PARAM_RESOLVE_WARNED:
            _PARAM_RESOLVE_WARNED.add(key)
            print(f"[Archive] resolve_param: {param!r} -> колонка {hit!r} (fuzzy)")
        return hit
    return None

def resolve_param_column_3(mapped: pd.DataFrame, param: str) -> str | None:
    """Найти реальную колонку в mapped для параметра из spc_map_table.

    Стратегии (по порядку):
      1. Точное совпадение с именем колонки.
      2. Регистронезависимое совпадение.
      3. Через psidata_map_table: Parameter -> Field, поиск Field.
      4. Явный алиас из _PARAM_ALIASES (может быть Parameter или Field).
      5. Fuzzy: нормализованное имя (без регистра/пунктуации),
         только если найдено РОВНО одно совпадение и имя не в блок-листе.
    """
    if mapped is None or mapped.empty or param is None:
        return None

    field_map = get_psidata_field_map()          # {Parameter: Field}
    reverse_map = {f: p for p, f in field_map.items() if p and f}

    candidates = [param]
    f = field_map.get(param)
    if f:
        candidates.append(f)
    a = _PARAM_ALIASES.get(param)
    if a:
        candidates.append(a)
        if a in reverse_map:
            candidates.append(reverse_map[a])
        af = field_map.get(a)
        if af:
            candidates.append(af)

    # 1-2 (для каждого кандидата)
    for cand in candidates:
        hit = _find_col_by_name(mapped, cand)
        if hit:
            return hit

    # 5) fuzzy
    target = _norm_param_name(param)
    if not target or target in _PARAM_FUZZY_BLOCK:
        return None
    hits = [c for c in mapped.columns if _norm_param_name(c) == target]
    if len(hits) == 1:
        hit = hits[0]
        key = (str(param), str(hit))
        if key not in _PARAM_RESOLVE_WARNED:
            _PARAM_RESOLVE_WARNED.add(key)
            print(f"[Archive] resolve_param: {param!r} -> колонка {hit!r} (fuzzy)")
        return hit
    return None


def log_missing_params(mapped: pd.DataFrame, spc_map: pd.DataFrame,
                       context: str = '') -> list[str]:
    """Диагностика: параметры спеки без колонки в данных (однократно в лог)."""
    if mapped is None or mapped.empty or spc_map is None or spc_map.empty:
        return []
    missing = [p for p in spc_map['Parameter']
               if resolve_param_column(mapped, p) is None]
    if missing:
        ctx = f" ({context})" if context else ''
        key = tuple(sorted(missing))
        if key not in _PARAM_RESOLVE_WARNED:
            _PARAM_RESOLVE_WARNED.add(key)
            print(f"[Archive] Нет колонки для параметров{ctx}: {missing}; "
                  f"колонки: {list(mapped.columns)}")
    return missing
# ===========================================================================
# Источник данных
# ===========================================================================

def _main() -> str:
    """Активная таблица замеров (psidata / psidata_temporary / psidata_archive)."""
    return _source_state.get('main_table', 'psidata')


def _temps() -> str:
    """Активная таблица температур (psidatatemp / *_temporary / *_archive)."""
    return _source_state.get('temps_table', 'psidatatemp')


# ===========================================================================
# Справочники
# ===========================================================================

def get_archive_types() -> list[str]:
    engine = create_engine(str(get_connection_string()))
    sql = "SELECT `Type` FROM `resonatortype` ORDER BY `Type`"
    try:
        return pd.read_sql(sql, engine)['Type'].dropna().tolist()
    except Exception as e:
        print(f"[Archive] Ошибка загрузки типов: {e}")
        return []


def get_archive_specs_by_type(rtype: str) -> list[str]:
    if not rtype:
        return []
    engine = create_engine(str(get_connection_string()))
    sql = "SELECT `Name` FROM `specification` WHERE NameR = :t ORDER BY `Name`"
    try:
        return pd.read_sql(text(sql), engine,
                           params={'t': rtype})['Name'].dropna().tolist()
    except Exception as e:
        print(f"[Archive] Ошибка загрузки спецификаций: {e}")
        return []


def get_archive_msk_list(spc: str | None = None) -> list[str]:
    engine = create_engine(str(get_connection_string()))
    table = _main()
    if spc:
        sql = (f"SELECT DISTINCT MSK FROM `{table}` "
               f"WHERE Spc = :spc AND MSK IS NOT NULL ORDER BY MSK")
        params = {'spc': spc}
    else:
        sql = (f"SELECT DISTINCT MSK FROM `{table}` "
               f"WHERE MSK IS NOT NULL ORDER BY MSK")
        params = {}
    try:
        return pd.read_sql(text(sql), engine,
                           params=params)['MSK'].tolist()
    except Exception as e:
        print(f"[Archive] Ошибка загрузки МСК: {e}")
        return []


def get_archive_dates_list(msk: str | None = None,
                           spc: str | None = None) -> list[str]:
    engine = create_engine(str(get_connection_string()))
    table = _main()
    cond, params = [], {}
    if msk:
        cond.append("MSK = :msk")
        params['msk'] = msk
    if spc:
        cond.append("Spc = :spc")
        params['spc'] = spc
    where = " AND ".join(cond) if cond else "1=1"
    sql = (f"SELECT DISTINCT Date FROM `{table}` WHERE {where} "
           f"AND Date IS NOT NULL ORDER BY Date")
    try:
        return pd.read_sql(text(sql), engine, params=params)['Date'].tolist()
    except Exception as e:
        print(f"[Archive] Ошибка загрузки дат: {e}")
        return []


def get_archive_files_list(msk: str | None = None,
                           spc: str | None = None,
                           date: str | None = None) -> list[str]:
    engine = create_engine(str(get_connection_string()))
    table = _main()
    cond, params = [], {}
    if msk:
        cond.append("MSK = :msk")
        params['msk'] = msk
    if spc:
        cond.append("Spc = :spc")
        params['spc'] = spc
    if date:
        cond.append("Date = :date")
        params['date'] = date
    where = " AND ".join(cond) if cond else "1=1"
    sql = (f"SELECT DISTINCT File FROM `{table}` WHERE {where} "
           f"AND File IS NOT NULL ORDER BY File")
    try:
        return pd.read_sql(text(sql), engine,
                           params=params)['File'].tolist()
    except Exception as e:
        print(f"[Archive] Ошибка загрузки файлов: {e}")
        return []


# ===========================================================================
# Measure_ID
# ===========================================================================

def load_measure_ids_by_msk(msk: str) -> list[int]:
    if not msk:
        return []
    engine = create_engine(str(get_connection_string()))
    table = _main()
    sql = (f"SELECT DISTINCT Measure_ID FROM `{table}` "
           f"WHERE MSK = :m AND Measure_ID IS NOT NULL "
           f"ORDER BY Measure_ID")
    try:
        return pd.read_sql(text(sql), engine,
                           params={'m': msk})['Measure_ID'].tolist()
    except Exception as e:
        print(f"[Archive] Ошибка загрузки ID: {e}")
        return []


def load_archive_by_measure_id(mid) -> dict | None:
    if not mid:
        return None
    engine = create_engine(str(get_connection_string()))
    table = _main()
    try:
        row = pd.read_sql(
            text(f"SELECT Spc, MSK FROM `{table}` "
                 f"WHERE Measure_ID = :m LIMIT 1"),
            engine, params={'m': mid})
        if row.empty:
            return None
        spc = row['Spc'].iloc[0]
        msk = row['MSK'].iloc[0]

        rtype = None
        if spc:
            sr = pd.read_sql(
                text("SELECT NameR FROM specification WHERE Name = :s"),
                engine, params={'s': spc})
            if not sr.empty:
                rtype = sr['NameR'].iloc[0]

        return {'measure_id': mid, 'spc': spc, 'msk': msk, 'rtype': rtype}
    except Exception as e:
        print(f"[Archive] Ошибка загрузки по Measure_ID: {e}")
        return None


# ===========================================================================
# Основная загрузка
# ===========================================================================
def load_archive_data(msk: str | None = None,
                      spc: str | None = None,
                      date: str | None = None,
                      file: str | None = None,
                      measure_id=None,
                      only_good: bool = False,
                      numbers_filter: list[str] | None = None
                      ) -> pd.DataFrame:
    """
    Загрузка записей из активной таблицы замеров.

    numbers_filter (list[str] | None):
      - если задан - фильтр N IN (:nums) совместно с другими условиями;
      - если задан без остальных фильтров - поиск по всем МСК;
      - если None - работают только остальные фильтры (МСК/ID/дата/файл).
    """
    from sqlalchemy import bindparam

    engine = create_engine(str(get_connection_string()))
    table = _main()

    cond, params = [], {}
    if measure_id:
        cond.append("Measure_ID = :mid")
        params['mid'] = measure_id
    if msk:
        cond.append("MSK = :msk")
        params['msk'] = msk
    if spc:
        cond.append("Spc = :spc")
        params['spc'] = spc
    if date:
        cond.append("Date = :date")
        params['date'] = date
    if file:
        cond.append("File = :file")
        params['file'] = file
    if only_good:
        cond.append("Status2 = 'Good'")

    if numbers_filter:
        cond.append("N IN :nums")
        params['nums'] = list(numbers_filter)

    if not cond:
        return pd.DataFrame()

    stmt = (f"SELECT * FROM `{table}` WHERE " + " AND ".join(cond) +
            " ORDER BY N")
    sql = text(stmt)
    if numbers_filter:
        sql = sql.bindparams(bindparam("nums", expanding=True))

    try:
        return pd.read_sql(sql, engine, params=params)
    except Exception as e:
        print(f"[Archive] Ошибка загрузки данных: {e}")
        return pd.DataFrame()




def get_archive_info(df: pd.DataFrame) -> dict:
    if df is None or df.empty:
        return {}
    row = df.iloc[0]
    return {
        'MSK': row.get('MSK', ''),
        'File': row.get('File', ''),
        'Spc': row.get('Spc', ''),
        'Date': row.get('Date', ''),
        'Time': row.get('Time', ''),
        'Nominal': row.get('Nominal', ''),
        'Measure_ID': row.get('Measure_ID', ''),
        'Count': len(df),
    }


# ===========================================================================
# Маппинг Parameter <-> Field (ключ к "пропавшим" колонкам)
# ===========================================================================

_FIELD_MAP_CACHE = None


def get_psidata_field_map() -> dict:
    """Parameter (spc_map_table.Parameter_Name) -> Field (psidata)."""
    global _FIELD_MAP_CACHE
    if _FIELD_MAP_CACHE is not None:
        return _FIELD_MAP_CACHE
    engine = create_engine(str(get_connection_string()))
    try:
        df = pd.read_sql(
            "SELECT Parameter, Field FROM psidata_map_table", engine)
        _FIELD_MAP_CACHE = {
            str(p): str(f) for p, f in zip(df['Parameter'], df['Field'])
            if pd.notna(p) and pd.notna(f)
        }
    except Exception as e:
        print(f"[Archive] psidata_map_table недоступна: {e}")
        _FIELD_MAP_CACHE = {}
    return _FIELD_MAP_CACHE


# В Archive_Data.py
def rename_fields_to_parameters(df: pd.DataFrame) -> pd.DataFrame:
    """Переименовывает колонки и вычисляет производные параметры."""
    if df is None or df.empty:
        return df
    field_map = get_psidata_field_map()
    reverse = {f: p for p, f in field_map.items() if f and p}

    result = df.copy()

    # 1. Вычисляем Fmaxm (ABS(Fmax, Fmin)), если его нет
    if 'Fmaxm' not in result.columns:
        # Пытаемся найти колонки для Fmax и Fmin
        fmax_field = field_map.get('Fmax', 'Fmax')
        fmin_field = field_map.get('Fmin', 'Fmin')

        col_fmax = None
        for c in result.columns:
            if c.lower() == fmax_field.lower() or c.lower() == 'fmax':
                col_fmax = c
                break

        col_fmin = None
        for c in result.columns:
            if c.lower() == fmin_field.lower() or c.lower() == 'fmin':
                col_fmin = c
                break

        if col_fmax and col_fmin:
            # Считаем максимальное по модулю значение: max(|Fmax|, |Fmin|)
            result['Fmaxm'] = result[[col_fmax, col_fmin]].abs().max(axis=1)

    # 2. Переименование
    for field, param in reverse.items():
        if field in result.columns and param not in result.columns:
            result = result.rename(columns={field: param})
    return result
def rename_fields_to_parameters_9(df: pd.DataFrame) -> pd.DataFrame:
    """Переименовывает колонки и вычисляет производные параметры."""
    if df is None or df.empty:
        return df
    field_map = get_psidata_field_map()
    reverse = {f: p for p, f in field_map.items() if f and p}

    result = df.copy()

    # 1. Вычисляем Fmaxm (ABS(Fmax, Fmin)), если его нет
    if 'Fmaxm' not in result.columns:
        fmax_field = field_map.get('Fmax', 'Fmax')
        fmin_field = field_map.get('Fmin', 'Fmin')

        col_fmax = next((c for c in result.columns if c.lower() == fmax_field.lower()), None)
        col_fmin = next((c for c in result.columns if c.lower() == fmin_field.lower()), None)

        if col_fmax and col_fmin:
            result['Fmaxm'] = result[[col_fmax, col_fmin]].abs().max(axis=1)

    # 2. Переименование
    for field, param in reverse.items():
        if field in result.columns and param not in result.columns:
            result = result.rename(columns={field: param})
    return result
def _prepare_spc_map(spc_map: pd.DataFrame) -> pd.DataFrame:
    """Замена Fmax(15)+Fmin(16) на ABS(Fmax, Fmin)(30).
    Применяется ТОЛЬКО для предъявительского протокола.

    Если в spc_map есть и Fmax(15), и Fmin(16) — создаёт (или обновляет)
    строку 30 на основе норм 15, после чего удаляет 15 и 16.
    Иначе возвращает spc_map без изменений.
    """
    if spc_map is None or spc_map.empty:
        return spc_map

    spc_map = spc_map.copy()
    param_30 = 'ABS(Fmax, Fmin)'
    param_15 = 'Fmax'
    param_16 = 'Fmin'

    idx_15 = spc_map[spc_map['Parameter'] == param_15].index
    idx_16 = spc_map[spc_map['Parameter'] == param_16].index

    # Замена имеет смысл только если включены оба
    if idx_15.empty or idx_16.empty:
        return spc_map

    idx_30 = spc_map[spc_map['Parameter'] == param_30].index

    if not idx_30.empty:
        # 30 уже есть — обновим нормы из 15
        spc_map.at[idx_30[0], 'Max'] = spc_map.at[idx_15[0], 'Max']
        spc_map.at[idx_30[0], 'Min'] = spc_map.at[idx_15[0], 'Min']
        spc_map.at[idx_30[0], 'Note_mini'] = 'ABS(Fmax, Fmin), ppm'
    else:
        # 30 отсутствует (Use=Fmaxm=0) — создаём на основе 15
        new_row = spc_map.loc[idx_15[0]].to_dict()
        new_row['Parameter'] = param_30
        new_row['Note'] = 'Максимальный модуль изменения частоты в интервале, ppm'
        new_row['Note_mini'] = 'ABS(Fmax, Fmin), ppm'
        new_row['Order'] = 20
        new_row['Code'] = 98
        new_row['Round'] = 2
        spc_map = pd.concat([spc_map, pd.DataFrame([new_row])],
                            ignore_index=True)
        print(f"[Archive] _prepare_spc_map: добавлен {param_30!r} "
              f"на основе {param_15}")

    # Удаляем 15 и 16
    spc_map = spc_map[~spc_map['Parameter'].isin([param_15, param_16])]
    return spc_map.reset_index(drop=True)

def _prepare_spc_map_99(spc_map: pd.DataFrame) -> pd.DataFrame:
    """Замена Fmax(15)+Fmin(16) на ABS(Fmax,Fmin)(30).
    Применяется ТОЛЬКО для предъявительского протокола.

    Если в spc_map есть и Fmax(15), и Fmin(16), то:
      - добавляем ABS(Fmax, Fmin)(30) с нормами из Fmax,
      - удаляем Fmax и Fmin из карты.
    Иначе — возвращаем spc_map без изменений.
    """
    if spc_map is None or spc_map.empty:
        return spc_map

    spc_map = spc_map.copy()
    param_30 = 'ABS(Fmax, Fmin)'
    param_15 = 'Fmax'
    param_16 = 'Fmin'

    idx_15 = spc_map[spc_map['Parameter'] == param_15].index
    idx_16 = spc_map[spc_map['Parameter'] == param_16].index

    # Замена имеет смысл только если есть оба
    if idx_15.empty or idx_16.empty:
        return spc_map

    idx_30 = spc_map[spc_map['Parameter'] == param_30].index

    if not idx_30.empty:
        # 30 уже в spc_map — обновим нормы из 15
        spc_map.at[idx_30[0], 'Max'] = spc_map.at[idx_15[0], 'Max']
        spc_map.at[idx_30[0], 'Min'] = spc_map.at[idx_15[0], 'Min']
        spc_map.at[idx_30[0], 'Note_mini'] = 'ABS(Fmax, Fmin), ppm'
    else:
        # 30 отсутствует (Use=Fmaxm=0) — создаём на основе 15
        new_row = spc_map.loc[idx_15[0]].to_dict()
        new_row['Parameter'] = param_30
        new_row['Note'] = 'Максимальный модуль изменения частоты в интервале, ppm'
        new_row['Note_mini'] = 'ABS(Fmax, Fmin), ppm'
        new_row['Order'] = 20
        new_row['Code'] = 98
        new_row['Round'] = 2
        spc_map = pd.concat([spc_map, pd.DataFrame([new_row])],
                            ignore_index=True)

    # Удаляем 15 и 16
    spc_map = spc_map[~spc_map['Parameter'].isin([param_15, param_16])]
    return spc_map.reset_index(drop=True)

def _prepare_spc_map_1(spc_map: pd.DataFrame) -> pd.DataFrame:
    """
    Специальная обработка карты норм:
    Если есть параметр 30 (ABS(Fmax, Fmin)), то берем нормы из Fmax (15),
    а сами параметры 15 и 16 удаляем из вывода.
    """
    if spc_map is None or spc_map.empty:
        return spc_map

    spc_map = spc_map.copy()
    param_30 = 'ABS(Fmax, Fmin)'
    param_15 = 'Fmax'
    param_16 = 'Fmin'

    if param_30 in spc_map['Parameter'].values:
        # Если есть 30, копируем нормы из 15 (если он есть)
        idx_30 = spc_map[spc_map['Parameter'] == param_30].index
        idx_15 = spc_map[spc_map['Parameter'] == param_15].index

        if not idx_15.empty and not idx_30.empty:
            spc_map.at[idx_30[0], 'Max'] = spc_map.at[idx_15[0], 'Max']
            spc_map.at[idx_30[0], 'Min'] = spc_map.at[idx_15[0], 'Min']
            spc_map.at[idx_30[0], 'Note_mini'] = 'ABS(Fmax, Fmin), ppm'

        # Удаляем 15 и 16, чтобы не дублировать в протоколе
        spc_map = spc_map[~spc_map['Parameter'].isin([param_15, param_16])]

    return spc_map



def rename_fields_to_parameters_5(df: pd.DataFrame) -> pd.DataFrame:
    """
    Переименовывает колонки (Field) в Parameter_Name.
    Не перезаписывает колонки, если Parameter уже присутствует.
    Дополнительно вычисляет производные параметры (например, ABS(Fmax, Fmin)).
    """
    if df is None or df.empty:
        return df
    field_map = get_psidata_field_map()
    reverse = {f: p for p, f in field_map.items() if f and p}

    result = df.copy()

    # --- ВЫЧИСЛЕНИЕ ПРОИЗВОДНЫХ ПАРАМЕТРОВ ---
    # Параметр 30: ABS(Fmax, Fmin) = max(abs(Fmax), abs(Fmin))
    if 'Fmaxm' not in result.columns:
        # Находим реальные имена колонок для Fmax (ID 15) и Fmin (ID 16)
        fmax_field = field_map.get('Fmax', 'Fmax')
        fmin_field = field_map.get('Fmin', 'Fmin')

        col_fmax = next((c for c in result.columns if c.lower() == fmax_field.lower()), None)
        col_fmin = next((c for c in result.columns if c.lower() == fmin_field.lower()), None)

        if col_fmax and col_fmin:
            # Считаем максимальное по модулю значение: max(|Fmax|, |Fmin|)
            result['Fmaxm'] = result[[col_fmax, col_fmin]].abs().max(axis=1)
            # print("[Archive] Вычислена колонка Fmaxm (ABS(Fmax, Fmin))")
    # -----------------------------------------

    for field, param in reverse.items():
        if field in result.columns and param not in result.columns:
            result = result.rename(columns={field: param})
    return result

def rename_fields_to_parameters_1(df: pd.DataFrame) -> pd.DataFrame:
    """
    Переименовывает колонки (Field) в Parameter_Name.
    Не перезаписывает колонки, если Parameter уже присутствует.
    """
    if df is None or df.empty:
        return df
    field_map = get_psidata_field_map()
    reverse = {f: p for p, f in field_map.items() if f and p}

    result = df.copy()
    for field, param in reverse.items():
        if field in result.columns and param not in result.columns:
            result = result.rename(columns={field: param})
    return result


# ===========================================================================
# Спецификация и карта норм (защита от "потерянных" строк)
# ===========================================================================

def load_specification(spc_name: str) -> pd.DataFrame:
    engine = create_engine(str(get_connection_string()))
    sql = "SELECT * FROM specification WHERE Name = :name"
    try:
        return pd.read_sql(text(sql), engine, params={'name': spc_name})
    except Exception as e:
        print(f"[Archive] Ошибка загрузки спецификации {spc_name}: {e}")
        return pd.DataFrame()


def _safe_float(v):
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, str):
        s = v.strip()
        if not s or s.lower() == 'no':
            return None
        try:
            return float(s.replace(',', '.'))
        except (ValueError, TypeError):
            return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _safe_str(v) -> str:
    """Безопасное приведение к строке: None/NaN/пустые → ''."""
    if v is None:
        return ''
    try:
        if pd.isna(v):
            return ''
    except (TypeError, ValueError):
        pass
    s = str(v).strip()
    if s.lower() in ('none', 'nan', ''):
        return ''
    return s


def _safe_int(v, default=None):
    if v is None:
        return default
    try:
        if pd.isna(v):
            return default
    except (TypeError, ValueError):
        pass
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default
# NEW: глобальный флаг «показывать Shum*». Управляется чекбоксом
# archive_shum_check в Archive_UI через set_include_shum().
_INCLUDE_SHUM: bool = False


def set_include_shum(flag: bool) -> None:
    """Включить/выключить параметры фазового шума (Shum, Shum1..4)."""
    global _INCLUDE_SHUM
    _INCLUDE_SHUM = bool(flag)


def is_include_shum() -> bool:
    """Текущее состояние флага Shum*."""
    return _INCLUDE_SHUM
def load_spc_map_for_archive(spc_name: str) -> pd.DataFrame:
    """
    Карта норм из spc_map_table, фильтр по Use=1.

    Содержит: Parameter, Max, Min, Code, Round, Order, Note, Note_mini.
    Не пропускает строки, если Max/Min = 'no'/NaN/пустое.

    Особый случай — параметры фазового шума (Shum, Shum1..4):
      * в spc_map_table у них в колонке Use записан литерал '1'
        (это НЕ имя столбца specification, поэтому старый код
        `row.get('1')` возвращал None и всегда отбрасывал эти строки);
      * флаг использования берётся из одноимённой колонки specification
        (`Shum`, `Shum1`, `Shum2`, `Shum3`, `Shum4`);
      * дополнительно требуется включённый глобальный флаг _INCLUDE_SHUM
        (галочка «Параметры шума (Shum)» в Archive_UI);
      * при выключенной галочке Shum* не попадают в spc_map вообще —
        ни в таблицу, ни в нормы, ни в протоколы.
    """
    spc_df = load_specification(spc_name)
    if spc_df.empty:
        return pd.DataFrame()

    row = spc_df.iloc[0]
    engine = create_engine(str(get_connection_string()))
    try:
        spc_map_table = pd.read_sql(
            "SELECT * FROM spc_map_table ORDER BY ID", engine)
    except Exception as e:
        print(f"[Archive] Ошибка загрузки spc_map_table: {e}")
        return pd.DataFrame()

    result = []
    for _, spc_row in spc_map_table.iterrows():
        param_name = str(spc_row['Parameter_Name'])
        is_shum = param_name.startswith('Shum')

        # NEW: для Shum* флаг использования берётся из одноимённого столбца
        # specification (Shum, Shum1..4), а НЕ из spc_map_table.Use — там
        # записан литерал '1', не являющийся именем столбца спецификации.
        if is_shum:
            if not _INCLUDE_SHUM:
                continue
            use_val = _safe_int(row.get(param_name), default=0)
            if use_val != 1:
                continue
        else:
            use_val = _safe_int(row.get(spc_row['Use']), default=0)
            if use_val != 1:
                continue

        max_val = _safe_float(row.get(spc_row['Max']))
        min_val = _safe_float(row.get(spc_row['Min']))

        note = spc_row.get('Note')
        note = str(note) if pd.notna(note) and note != '' else param_name

        note_mini = spc_row.get('Note_mini')
        note_mini = (str(note_mini)
                     if pd.notna(note_mini) and note_mini != ''
                     else note)

        order = _safe_int(spc_row.get('Order'), default=999)
        rnd = _safe_int(spc_row.get('Round'), default=None)

        result.append({
            'Parameter': param_name,
            'Max': max_val,
            'Min': min_val,
            'Code': _safe_int(spc_row.get('Code'), 0) or 0,
            'Round': rnd,
            'Order': order,
            'Note': note,
            'Note_mini': note_mini,
        })
    return pd.DataFrame(result)




# ===========================================================================
# Печать: порядок колонок по Order, округление по Round
# ===========================================================================
def apply_rounding(df, spc_map):
    if df is None or df.empty or spc_map is None or spc_map.empty:
        return df
    out = df.copy()
    for _, spc_item in spc_map.iterrows():
        rnd = spc_item.get('Round')
        if rnd is None or pd.isna(rnd):
            continue
        param = spc_item['Parameter']
        col = resolve_param_column(out, param, spc_item)
        if col is None:
            continue
        try:
            out[col] = pd.to_numeric(out[col], errors='coerce').round(int(rnd))
        except Exception:
            pass
    return out




def get_round_dict(spc_map: pd.DataFrame) -> dict:
    if spc_map is None or spc_map.empty or 'Round' not in spc_map.columns:
        return {}
    out = {}
    for _, r in spc_map.iterrows():
        v = r['Round']
        if v is not None and not pd.isna(v):
            out[r['Parameter']] = int(v)
    return out

def get_headers_dict(spc_map: pd.DataFrame) -> dict:
    if spc_map is None or spc_map.empty:
        return {}
    headers = {}
    for _, r in spc_map.iterrows():
        # Приоритет отдаем Note_mini (короткое название, как в FR3)
        note = r.get('Note_mini')
        if pd.isna(note) or not note:
            note = r.get('Note')
        if pd.isna(note) or not note:
            note = r['Parameter']
        headers[r['Parameter']] = note
    return headers

def get_headers_dict_3(spc_map: pd.DataFrame) -> dict:
    if spc_map is None or spc_map.empty:
        return {}
    headers = {}
    for _, r in spc_map.iterrows():
        note = r.get('Note')
        if pd.isna(note) or not note:
            note = r['Parameter']
        headers[r['Parameter']] = note
    return headers

def build_archive_print_data(df: pd.DataFrame,
                             spc_map: pd.DataFrame) -> pd.DataFrame:
    """
    Готовит data_df для create_protocol:

      1) переименовывает Field -> Parameter по psidata_map_table
         (Position -> Positions, N -> Numbers);
      2) СТАТУС формируется по спецификации (Status psidata НЕ используется);
      3) оставляет только Positions, Numbers + параметры спецификации,
         реально присутствующие в данных (через resolve_param_column,
         с fallback по spc_row.Max/Min/Use — например 'Rc_Rb' → 'Rc_Rbmax');
      4) сортирует параметры по Order из spc_map_table;
      5) переименовывает реальные колонки в имена параметров (для PDF);
      6) округляет значения по Round из spc_map_table;
      7) пустые значения -> ''.
    """
    # ------------------------------------------------------------------
    # 1) Field -> Parameter, Position -> Positions, N -> Numbers
    # ------------------------------------------------------------------
    result = rename_fields_to_parameters(df)
    if 'Position' in result.columns and 'Positions' not in result.columns:
        result = result.rename(columns={'Position': 'Positions'})
    if 'N' in result.columns and 'Numbers' not in result.columns:
        result = result.rename(columns={'N': 'Numbers'})

    # ------------------------------------------------------------------
    # 2) СТАТУС по спецификации (Status psidata НЕ используется)
    # ------------------------------------------------------------------
    spec_ok = _compute_spec_status(result, spc_map)

    result['Status']  = spec_ok.map({True: 'Годен', False: 'Брак'})
    result['Status2'] = spec_ok.map({True: 'Good',  False: 'Bad'})

    # ------------------------------------------------------------------
    # 3) Пары (имя_параметра, реальная_колонка), с resolve + spc_item
    # ------------------------------------------------------------------
    param_pairs: list[tuple[str, str]] = []
    seen_params: set[str] = set()
    seen_cols:   set[str] = set()

    if spc_map is not None and not spc_map.empty:
        for _, spc_item in spc_map.iterrows():
            p = spc_item['Parameter']
            col = resolve_param_column(result, p, spc_item)
            if col is None:
                continue
            if p in seen_params or col in seen_cols:
                continue
            param_pairs.append((p, col))
            seen_params.add(p)
            seen_cols.add(col)

    # ------------------------------------------------------------------
    # 4) Сортировка по Order
    # ------------------------------------------------------------------
    if (spc_map is not None and not spc_map.empty
            and 'Order' in spc_map.columns):
        order_map = dict(zip(spc_map['Parameter'], spc_map['Order']))
        param_pairs.sort(key=lambda pc: order_map.get(pc[0], 999))

    # ------------------------------------------------------------------
    # 5) Переименование реальных колонок в имена параметров
    #    (чтобы PDF показывал 'Rc_Rb', а не 'Rc_Rbmax')
    # ------------------------------------------------------------------
    out = result.copy()
    rename_map = {}
    for p, col in param_pairs:
        if col != p and p not in out.columns and col in out.columns:
            rename_map[col] = p
    if rename_map:
        out = out.rename(columns=rename_map)

    base_cols  = [c for c in ('Positions', 'Numbers') if c in out.columns]
    tail_cols  = [c for c in ('Status', 'Status2')    if c in out.columns]
    param_cols = [p for p, _ in param_pairs if p in out.columns]

    # ------------------------------------------------------------------
    # 6) Итоговый набор колонок
    # ------------------------------------------------------------------
    final_cols: list[str] = []
    seen: set[str] = set()
    for c in base_cols + param_cols + tail_cols:
        if c not in seen and c in out.columns:
            seen.add(c)
            final_cols.append(c)

    if not final_cols:
        return out[base_cols + tail_cols].copy().fillna('')

    out = out[final_cols].copy()

    # ------------------------------------------------------------------
    # 7) Округление по Round
    # ------------------------------------------------------------------
    round_dict = get_round_dict(spc_map)
    for param, decimals in round_dict.items():
        if param in out.columns:
            try:
                out[param] = pd.to_numeric(
                    out[param], errors='coerce').round(int(decimals))
            except Exception:
                pass

    # ------------------------------------------------------------------
    # 7b) Tmax / Tmin вне [-60, +150] -> пусто (в протоколе пустое место)
    # ------------------------------------------------------------------
    for _tmax_col in ('Tmax', 'Tmin', 'extr_1', 'extr_2'):
        if _tmax_col not in out.columns:
            continue
        def _mask_out_of_range(v):
            if v is None:
                return ''
            try:
                if pd.isna(v):
                    return ''
            except (TypeError, ValueError):
                pass
            try:
                f = float(v)
            except (TypeError, ValueError):
                return ''
            if f < -60.0 or f > 150.0:
                return ''
            return v
        out[_tmax_col] = out[_tmax_col].map(_mask_out_of_range)

    # ------------------------------------------------------------------
    # 8) Пустые значения -> ''  (для отрисовки в PDF)
    # ------------------------------------------------------------------
    return out.fillna('')

def build_archive_print_data_3(df, spc_map):
    result = rename_fields_to_parameters(df)
    if 'Position' in result.columns and 'Positions' not in result.columns:
        result = result.rename(columns={'Position': 'Positions'})
    if 'N' in result.columns and 'Numbers' not in result.columns:
        result = result.rename(columns={'N': 'Numbers'})

    spec_ok = _compute_spec_status(result, spc_map)
    result['Status']  = spec_ok.map({True: 'Годен', False: 'Брак'})
    result['Status2'] = spec_ok.map({True: 'Good',  False: 'Bad'})

    # (имя_параметра, реальная_колонка)
    param_pairs: list[tuple[str, str]] = []
    seen_params, seen_cols = set(), set()
    if spc_map is not None and not spc_map.empty:
        for _, spc_item in spc_map.iterrows():
            p = spc_item['Parameter']
            col = resolve_param_column(result, p)
            if col is None or p in seen_params or col in seen_cols:
                continue
            param_pairs.append((p, col))
            seen_params.add(p)
            seen_cols.add(col)

    if (spc_map is not None and not spc_map.empty
            and 'Order' in spc_map.columns):
        order_map = dict(zip(spc_map['Parameter'], spc_map['Order']))
        param_pairs.sort(key=lambda pc: order_map.get(pc[0], 999))

    # Переименуем реальные колонки в имена параметров
    out = result.copy()
    rename_map = {}
    for p, col in param_pairs:
        if col != p and p not in out.columns:
            rename_map[col] = p
    if rename_map:
        out = out.rename(columns=rename_map)

    base_cols  = [c for c in ('Positions', 'Numbers') if c in out.columns]
    tail_cols  = [c for c in ('Status', 'Status2')    if c in out.columns]
    param_cols = [p for p, _ in param_pairs]

    final_cols, seen = [], set()
    for c in base_cols + param_cols + tail_cols:
        if c not in seen and c in out.columns:
            seen.add(c)
            final_cols.append(c)

    if not final_cols:
        return out[base_cols + tail_cols].copy().fillna('')

    out = out[final_cols].copy()
    round_dict = get_round_dict(spc_map)
    for param, decimals in round_dict.items():
        if param in out.columns:
            out[param] = pd.to_numeric(
                out[param], errors='coerce').round(int(decimals))

    # Tmax / Tmin вне [-60, +150] -> пусто (в протоколе пустое место)
    for _tmax_col in ('Tmax', 'Tmin', 'extr_1', 'extr_2'):
        if _tmax_col not in out.columns:
            continue
        def _mask_out_of_range(v):
            if v is None:
                return ''
            try:
                if pd.isna(v):
                    return ''
            except (TypeError, ValueError):
                pass
            try:
                f = float(v)
            except (TypeError, ValueError):
                return ''
            if f < -60.0 or f > 150.0:
                return ''
            return v
        out[_tmax_col] = out[_tmax_col].map(_mask_out_of_range)

    return out.fillna('')




def build_archive_status_df(df: pd.DataFrame,
                            spc_map: pd.DataFrame) -> pd.DataFrame:
    """
    Построчные статусы. Per-parameter статусы теперь учитывают
    логику Rsp/SPFR — SPFR всегда годен, Rsp зависит от SPFR.
    """
    mapped = rename_fields_to_parameters(df)
    out = pd.DataFrame(index=mapped.index)
    if 'Position' in mapped.columns:
        out['Positions'] = mapped['Position'].values
    elif 'Positions' in mapped.columns:
        out['Positions'] = mapped['Positions'].values
    else:
        out['Positions'] = range(len(mapped))

    # Номер РК — чтобы печать протокола сопоставляла статусы
    # по паре (Позиция, Номер), а не только по позиции: при
    # повторяющихся позициях (ВСЕ МСК, история) совпадение
    # только по позиции подсвечивало чужие строки.
    if 'N' in mapped.columns:
        out['Numbers'] = mapped['N'].values
    elif 'Numbers' in mapped.columns:
        out['Numbers'] = mapped['Numbers'].values

    param_masks = _compute_param_masks(mapped, spc_map)
    for param, mask in param_masks.items():
        out[f"{param}_status"] = mask.values

    overall = _compute_spec_status(mapped, spc_map)
    out['Status'] = overall.values
    out['Status2'] = overall.map({True: 'Good', False: 'Bad'}).values
    return out


def build_view_data_from_archive(df: pd.DataFrame,
                                 spc_row: pd.Series,
                                 psi_type: str = 'ПСИ') -> dict:
    row = df.iloc[0]
    positions = (df['Position'].tolist() if 'Position' in df.columns
                 else [])
    if positions:
        position_str = (str(positions[0]) if len(positions) == 1
                        else f"{positions[0]}...{positions[-1]}")
    else:
        position_str = ''

    if psi_type not in ('ПСИ', 'ОТК'):
        psi_type = 'ПСИ'

    return {
        'MSK': row.get('MSK', ''),
        'Spc_Text': spc_row.get('Text', spc_row.get('Name', '')),
        'Protokol_Type': psi_type,          # ← было 'ПСИ'
        'Position_str': position_str,
        'Temp': '',
        'Profile': spc_row.get('Profile', ''),
        'Nominal': spc_row.get('Nominal', ''),
        'LoadType': spc_row.get('LoadType', 'SERIES'),
        'LoadValue': spc_row.get('Loadvalue', 0),
        'Virtual': spc_row.get('FL_Num', 0),
        'FileName': row.get('File', ''),
        'File_ID': '',
        'Machine_Type': row.get('MachineType', ''),
        'Machine_Serial': row.get('Machine_Serial', ''),
        'Poverka': row.get('PoverKa', 0),
        'Poverka_Date': row.get('Machine_Call_Date', ''),
        'Operator': row.get('Operator', ''),
        'Full_Msk': row.get('MSK', ''),
        'PMI': row.get('PMI', 0),
        'TCH_Type': spc_row.get('TCH_Approx_Type', 'Измерения'),
        'TCH_correction': row.get('KO', 0),
        'F_correction': row.get('KO_F', 0),
    }

def build_view_data_from_archive_1(df: pd.DataFrame,
                                 spc_row: pd.Series) -> dict:
    row = df.iloc[0]
    positions = (df['Position'].tolist() if 'Position' in df.columns
                 else [])
    if positions:
        position_str = (str(positions[0]) if len(positions) == 1
                        else f"{positions[0]}...{positions[-1]}")
    else:
        position_str = ''

    return {
        'MSK': row.get('MSK', ''),
        'Spc_Text': spc_row.get('Text', spc_row.get('Name', '')),
        'Protokol_Type': 'ПСИ',
        'Position_str': position_str,
        'Temp': '',
        'Profile': spc_row.get('Profile', ''),
        'Nominal': spc_row.get('Nominal', ''),
        'LoadType': spc_row.get('LoadType', 'SERIES'),
        'LoadValue': spc_row.get('Loadvalue', 0),
        'Virtual': spc_row.get('FL_Num', 0),
        'FileName': row.get('File', ''),
        'File_ID': '',
        'Machine_Type': row.get('MachineType', ''),
        'Machine_Serial': row.get('Machine_Serial', ''),
        'Poverka': row.get('PoverKa', 0),
        'Poverka_Date': row.get('Machine_Call_Date', ''),
        'Operator': row.get('Operator', ''),
        'Full_Msk': row.get('MSK', ''),
        'PMI': row.get('PMI', 0),
        'TCH_Type': spc_row.get('TCH_Approx_Type', 'Измерения'),
        'TCH_correction': row.get('KO', 0),
        'F_correction': row.get('KO_F', 0),
    }
def get_archive_statistics(df: pd.DataFrame,
                           spc_map: pd.DataFrame | None = None
                           ) -> pd.DataFrame:
    """
    Построчная статистика по каждому параметру спецификации + итоговая строка.

    Параметр ищется через resolve_param_column(mapped, param, spc_item),
    что позволяет корректно находить колонки, чьё имя в psidata_map_table
    не совпадает с spc_map_table.Parameter_Name (например 'Rc_Rb' vs
    'Rc_Rbmax').

    Логика Rsp/SPFR — как в _compute_param_masks: SPFR всегда «в норме»,
    Rsp отбраковывается только если соответствующий SPFR в норме.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    mapped = rename_fields_to_parameters(df)
    param_masks = _compute_param_masks(mapped, spc_map)

    # Индекс spc_row по имени параметра (нужен для resolve_param_column
    # и для получения Min/Max при подсчёте)
    spc_index: dict = {}
    if spc_map is not None and not spc_map.empty:
        for _, r in spc_map.iterrows():
            spc_index[r['Parameter']] = r

    stats = []
    for param, mask in param_masks.items():
        spc_row = spc_index.get(param)
        col = resolve_param_column(mapped, param, spc_row)
        if col is None:
            continue

        values = pd.to_numeric(mapped[col], errors='coerce')
        valid = values[mask]

        defect = 0 if param.startswith('SPFR_') else int((~mask).sum())
        good   = (int(len(mask)) if param.startswith('SPFR_')
                  else int(mask.sum()))

        stats.append({
            'Parameter': param,
            'Брак':      defect,
            'Годные':    good,
            'Макс':      valid.max()  if not valid.empty else None,
            'Мин':       valid.min()  if not valid.empty else None,
            'Среднее':   valid.mean() if not valid.empty else None,
            'СтОткл':    valid.std()  if not valid.empty else None,
        })

    if not stats:
        return pd.DataFrame()

    stats_df = pd.DataFrame(stats)

    overall = _compute_spec_status(mapped, spc_map)
    total_valid  = int(overall.sum())
    total_defect = len(mapped) - total_valid

    total_row = {
        'Parameter': 'Общий статус',
        'Брак': total_defect, 'Годные': total_valid,
        'Макс': None, 'Мин': None, 'Среднее': None, 'СтОткл': None,
    }
    # pd.concat без FutureWarning:
    total_df = pd.DataFrame([total_row], columns=stats_df.columns)
    return pd.concat([stats_df, total_df], ignore_index=True)



# ===========================================================================
# Распечатка температур (аналог N1Click / Temperatures_Table)
# ===========================================================================

def load_archive_temperatures(measure_id=None, msk=None) -> pd.DataFrame:
    """
    Загрузка данных температур из активной таблицы.
    Приоритет: Measure_ID, иначе МСК.
    """
    if not measure_id and not msk:
        return pd.DataFrame()

    engine = create_engine(str(get_connection_string()))
    table = _temps()
    if measure_id:
        sql = (f"SELECT * FROM `{table}` WHERE Measure_ID = :m "
               f"ORDER BY N, Temp")
        params = {'m': measure_id}
    else:
        sql = (f"SELECT * FROM `{table}` WHERE MSK = :m "
               f"ORDER BY N, Temp")
        params = {'m': msk}
    try:
        return pd.read_sql(text(sql), engine, params=params)
    except Exception as e:
        print(f"[Archive] Ошибка загрузки температур: {e}")
        return pd.DataFrame()


def prepare_temperatures_for_pdf(df_temp: pd.DataFrame,
                                 t_ref: float,
                                 spc_row=None) -> pd.DataFrame:
    """
    Готовит данные для Report.generate_pdf.

    В таблице температур (см. graph/logic.py) есть только N, Temp, F, FL, R, ...
    без Position/Positions. Поэтому:
      - универсально ищем колонки по вариантам имён;
      - если Positions нет, но есть N/Numbers - используем его
        (группировка в create_measurements_table пойдёт по номерам).
    """
    if df_temp is None or df_temp.empty:
        return pd.DataFrame()

    import numpy as np

    print(f"[Archive] temperatures columns: {df_temp.columns.tolist()}")

    result = df_temp.copy()

    def _find_col(candidates):
        for c in candidates:
            if c in result.columns:
                return c
        return None

    pos_c = _find_col(['Positions', 'Position', 'position', 'pos'])
    num_c = _find_col(['Numbers', 'N', 'n', 'Number'])
    temp_c = _find_col(['Temps', 'Temp', 'temp', 'TEMP', 'Temperature'])
    f_c = _find_col(['F_', 'F', 'f', 'Fs', 'FS'])
    r_c = _find_col(['R', 'r', 'Res', 'Resistance'])

    rename = {}
    if pos_c and pos_c != 'Positions':
        rename[pos_c] = 'Positions'
    if num_c and num_c != 'Numbers':
        rename[num_c] = 'Numbers'
    if temp_c and temp_c != 'Temps':
        rename[temp_c] = 'Temps'
    if f_c and f_c != 'F_':
        rename[f_c] = 'F_'
    if r_c and r_c != 'R':
        rename[r_c] = 'R'
    if rename:
        result = result.rename(columns=rename)

    if 'Positions' not in result.columns and 'Numbers' in result.columns:
        result['Positions'] = result['Numbers']

    missing = [c for c in ('Positions', 'Numbers', 'Temps', 'F_', 'R')
               if c not in result.columns]
    if missing:
        print(f"[Archive] Нет колонок для распечатки: {missing}. "
              f"Есть: {result.columns.tolist()}")
        return pd.DataFrame()

    for col in ('Temps', 'F_', 'R'):
        result[col] = pd.to_numeric(result[col], errors='coerce')

    result['f_center'] = np.nan
    try:
        t_ref = float(t_ref) if t_ref is not None else 25.0
    except (TypeError, ValueError):
        t_ref = 25.0

    for pos in result['Positions'].dropna().unique():
        mask = result['Positions'] == pos
        sub = result[mask].copy()
        if sub.empty:
            continue
        sub['_dt'] = (sub['Temps'] - t_ref).abs()
        idx = sub['_dt'].idxmin()
        if pd.notna(idx):
            result.loc[mask, 'f_center'] = sub.loc[idx, 'F_']

    if 'f_interp' not in result.columns:
        result['f_interp'] = result['F_']

    result = result.dropna(subset=['Positions', 'Numbers', 'Temps'])
    result = result.sort_values(by=['Numbers', 'Positions', 'Temps'])

    return result




# ===========================================================================
# Поиск по номерам резонаторов
# ===========================================================================
import re


_NUM_SPLIT_RE = re.compile(r'[,;\s]+')
_NUM_RANGE_RE = re.compile(r'^([A-Za-z]*)(\d+)\s*-\s*([A-Za-z]*)(\d+)$')


def parse_numbers_input(text) -> list[str] | None:
    """
    Парсит строку с номерами резонаторов.

    Поддерживаемые форматы (можно комбинировать через запятую, пробел, ';'):
      - одиночный:  'JN4450', '12345'
      - диапазон:   'JN4450-JN4460', 'JN4450-4460', '4450-4460'
      - список:     'JN4450, JN4451, JN4452'

    Возвращает:
      - None, если строка пустая (фильтр не задан)
      - list[str] - отсортированный список номеров (в верхнем регистре)

    Защита от гигантских диапазонов: не более 10000 значений.
    """
    if text is None:
        return None
    text = str(text).strip()
    if not text:
        return None

    result = set()
    for part in _NUM_SPLIT_RE.split(text):
        part = part.strip()
        if not part:
            continue

        if '-' in part:
            m = _NUM_RANGE_RE.match(part)
            if m:
                pre1, n1, pre2, n2 = m.groups()
                prefix = (pre1 or pre2 or '').upper()
                try:
                    start, end = int(n1), int(n2)
                except ValueError:
                    result.add(part.upper())
                    continue
                if start > end:
                    start, end = end, start
                width = max(len(n1), len(n2))
                if end - start > 10000:
                    print(f"[Archive] Диапазон '{part}' слишком велик, "
                          f"ограничен 10000 значениями")
                    end = start + 10000
                for i in range(start, end + 1):
                    result.add(f"{prefix}{i:0{width}d}")
            else:
                result.add(part.upper())
        else:
            result.add(part.upper())

    return sorted(result) if result else None


# ===========================================================================
# Поиск по номерам резонаторов (по всей БД активной таблицы замеров)
# ===========================================================================
def find_measure_ids_by_numbers(numbers: list[str],
                                only_good: bool = False) -> list[int]:
    """
    Поиск Measure_ID по номерам резонаторов.

    Для основной таблицы (psidata) — через справочник
    psidata_resonator_lookup с fallback на psidata.
    Для временной/архивной — прямой запрос по N IN (...)
    (справочник индексирует только psidata).
    """
    if not numbers:
        return []

    numbers_set = {str(n).strip().upper() for n in numbers if str(n).strip()}
    if not numbers_set:
        return []

    table = _main()
    from sqlalchemy import bindparam

    # --- Не основная таблица: прямой запрос, без lookup ------------------
    if table != 'psidata':
        engine = create_engine(str(get_connection_string()))
        cond = ["UPPER(TRIM(N)) IN :nums", "Measure_ID IS NOT NULL"]
        if only_good:
            cond.append("Status2 = 'Good'")
        stmt = (f"SELECT DISTINCT Measure_ID FROM `{table}` "
                f"WHERE " + " AND ".join(cond) + " ORDER BY Measure_ID")
        sql = text(stmt).bindparams(bindparam("nums", expanding=True))
        try:
            return pd.read_sql(sql, engine,
                               params={'nums': list(numbers_set)}
                               )['Measure_ID'].tolist()
        except Exception as e:
            print(f"[Archive] Ошибка поиска по {table}: {e}")
            return []

    # --- Основная таблица: lookup + fallback ----------------------------
    from . import Archive_Lookup

    engine = create_engine(str(get_connection_string()))

    # 1) Справочник -------------------------------------------------------
    found_numbers, found_mids, _ = Archive_Lookup.find_in_lookup(
        numbers_set, engine=engine)

    # 2) Fallback: variant 3 — прямой поиск по индексу N ------------------
    missing = numbers_set - found_numbers
    if missing:
        try:
            stmt = ("SELECT DISTINCT N, Measure_ID FROM psidata "
                    "WHERE N IN :nums AND Measure_ID IS NOT NULL")
            sql = text(stmt).bindparams(bindparam("nums", expanding=True))
            df_fb = pd.read_sql(sql, engine, params={'nums': list(missing)})
            if not df_fb.empty:
                fb_pairs, fb_nums, fb_mids = [], set(), set()
                for _, r in df_fb.iterrows():
                    n_raw, mid_raw = r['N'], r['Measure_ID']
                    if pd.isna(n_raw) or pd.isna(mid_raw):
                        continue
                    n_norm = str(n_raw).strip().upper()
                    mid = int(mid_raw)
                    fb_nums.add(n_norm)
                    fb_mids.add(mid)
                    fb_pairs.append((mid, n_norm))

                found_numbers |= fb_nums
                found_mids |= fb_mids

                # Self-heal — следующий раз найдётся через справочник
                try:
                    Archive_Lookup.add_pairs_to_lookup(fb_pairs, engine=engine)
                except Exception as e:
                    print(f"[Archive] Self-heal ошибка: {e}")
        except Exception as e:
            print(f"[Archive] Fallback поиск ошибка: {e}")

    # 3) Фильтр only_good через psidata (с батчингом IN) ------------------
    if only_good and found_mids:
        try:
            good_mids = set()
            mids_list = list(found_mids)
            chunk = 1000
            for i in range(0, len(mids_list), chunk):
                part = mids_list[i:i + chunk]
                sql = text(
                    "SELECT DISTINCT Measure_ID FROM psidata "
                    "WHERE Measure_ID IN :mids AND Status2 = 'Good'"
                ).bindparams(bindparam("mids", expanding=True))
                dfg = pd.read_sql(sql, engine, params={'mids': part})
                good_mids |= {int(x) for x in dfg['Measure_ID'].unique()}
            found_mids = good_mids
        except Exception as e:
            print(f"[Archive] only_good фильтр ошибка: {e}")

    return sorted(found_mids)


def find_measure_ids_by_numbers_old(numbers: list[str],
                                only_good: bool = False) -> list[int]:
    """
    Найти все Measure_ID, содержащие указанные номера (по активной таблице).
    Ищет без учёта регистра и пробелов: UPPER(TRIM(N)) IN :nums.
    """
    if not numbers:
        return []

    from sqlalchemy import bindparam

    engine = create_engine(str(get_connection_string()))
    table = _main()
    cond = ["UPPER(TRIM(N)) IN :nums", "Measure_ID IS NOT NULL"]
    if only_good:
        cond.append("Status2 = 'Good'")
    stmt = (f"SELECT DISTINCT Measure_ID FROM `{table}` WHERE "
            + " AND ".join(cond) + " ORDER BY Measure_ID")
    sql = text(stmt).bindparams(bindparam("nums", expanding=True))

    try:
        return pd.read_sql(sql, engine,
                           params={'nums': list(numbers)}
                           )['Measure_ID'].tolist()
    except Exception as e:
        print(f"[Archive] Ошибка поиска Measure_ID по номерам: {e}")
        return []


def load_archive_by_numbers(numbers: list[str],
                            mode: str = 'Только номер',
                            only_good: bool = False,
                            found_mids: list[int] | None = None
                            ) -> pd.DataFrame:
    """
    Загрузка записей из активной таблицы по номерам.

    mode:
      'Только номер' — только строки с указанными номерами;
      'Вся МСК'      — все строки замеров, содержащих указанные номера.
    """
    if not numbers:
        return pd.DataFrame()

    numbers_set = {str(n).strip().upper() for n in numbers if str(n).strip()}
    if not numbers_set:
        return pd.DataFrame()

    if found_mids is None:
        found_mids = find_measure_ids_by_numbers(
            list(numbers_set), only_good=only_good)
    if not found_mids:
        return pd.DataFrame()

    from sqlalchemy import bindparam
    engine = create_engine(str(get_connection_string()))
    table = _main()

    cond = ["Measure_ID IN :mids"]
    params = {'mids': list(found_mids)}
    if only_good:
        cond.append("Status2 = 'Good'")

    stmt = (f"SELECT * FROM `{table}` WHERE " + " AND ".join(cond) +
            " ORDER BY Measure_ID, N")
    sql = text(stmt).bindparams(bindparam("mids", expanding=True))

    try:
        df = pd.read_sql(sql, engine, params=params)
    except Exception as e:
        print(f"[Archive] Ошибка загрузки по номерам: {e}")
        return pd.DataFrame()

    if df.empty:
        return df

    if mode == 'Только номер' and 'N' in df.columns:
        mask = (df['N'].astype(str).str.strip().str.upper()
                .isin(numbers_set))
        df = df[mask].reset_index(drop=True)

    return df


def load_archive_by_numbers_old(numbers: list[str],
                            mode: str = 'Только номер',
                            only_good: bool = False) -> pd.DataFrame:
    """
    Загрузка записей из активной таблицы по номерам.

    mode:
      'Только номер' - только строки с введёнными номерами
      'Вся МСК'      - все строки всех замеров, содержащих эти номера
    """
    if not numbers:
        return pd.DataFrame()

    mids = find_measure_ids_by_numbers(numbers, only_good=only_good)
    if not mids:
        return pd.DataFrame()

    from sqlalchemy import bindparam

    engine = create_engine(str(get_connection_string()))
    table = _main()
    cond = ["Measure_ID IN :mids"]
    params = {'mids': list(mids)}
    if only_good:
        cond.append("Status2 = 'Good'")
    if mode == 'Только номер':
        cond.append("UPPER(TRIM(N)) IN :nums")
        params['nums'] = list(numbers)

    stmt = (f"SELECT * FROM `{table}` WHERE " + " AND ".join(cond) +
            " ORDER BY Measure_ID, N")
    sql = text(stmt).bindparams(bindparam("mids", expanding=True))
    if mode == 'Только номер':
        sql = sql.bindparams(bindparam("nums", expanding=True))

    try:
        return pd.read_sql(sql, engine, params=params)
    except Exception as e:
        print(f"[Archive] Ошибка загрузки по номерам: {e}")
        return pd.DataFrame()


def load_archive_temperatures_by_mids(measure_ids: list[int]) -> pd.DataFrame:
    """Температуры по списку Measure_ID за один запрос (активная таблица)."""
    if not measure_ids:
        return pd.DataFrame()

    from sqlalchemy import bindparam

    engine = create_engine(str(get_connection_string()))
    table = _temps()
    sql = text(f"SELECT * FROM `{table}` WHERE Measure_ID IN :mids "
               f"ORDER BY Measure_ID, N, Temp")
    sql = sql.bindparams(bindparam("mids", expanding=True))
    try:
        return pd.read_sql(sql, engine,
                           params={'mids': list(measure_ids)})
    except Exception as e:
        print(f"[Archive] Ошибка загрузки температур по mids: {e}")
        return pd.DataFrame()


def search_archive_msk(partial: str | None = None) -> list[str]:
    """
    Поиск МСК по неполному номеру в активной таблице замеров.

    Примеры:
        partial='456'     -> 25-2456, 25-2456*, 25-2456` и т.п.
        partial='25-2456' -> все МСК, содержащие '25-2456'
    """
    if not partial:
        return []

    partial = str(partial).strip()
    if not partial:
        return []

    engine = create_engine(str(get_connection_string()))
    table = _main()
    sql = (
        f"SELECT DISTINCT MSK FROM `{table}` "
        f"WHERE MSK IS NOT NULL AND MSK LIKE :pat "
        f"ORDER BY MSK"
    )
    try:
        df = pd.read_sql(
            text(sql),
            engine,
            params={'pat': f'%{partial}%'}
        )
        return df['MSK'].dropna().astype(str).tolist()
    except Exception as e:
        print(f"[Archive] Ошибка поиска МСК: {e}")
        return []

def _compute_param_masks(mapped, spc_map):
    if spc_map is None or spc_map.empty:
        return {}
    param_masks = {}
    for _, spc_item in spc_map.iterrows():
        param = spc_item['Parameter']
        col = resolve_param_column(mapped, param, spc_item)   # ← spc_item!
        if col is None:
            continue
        values = pd.to_numeric(mapped[col], errors='coerce')
        mask = values.notna()
        mn, mx = spc_item.get('Min'), spc_item.get('Max')
        if mn is not None and not pd.isna(mn):
            mask &= values >= float(mn)
        if mx is not None and not pd.isna(mx):
            mask &= values <= float(mx)
        param_masks[param] = mask

    for rsp in [p for p in param_masks if p.startswith('Rsp')]:
        spfr = f"SPFR_{rsp[3:]}"
        if spfr in param_masks:
            param_masks[rsp] = (~param_masks[spfr]) | param_masks[rsp]
    for spfr in [p for p in param_masks if p.startswith('SPFR_')]:
        param_masks[spfr] = pd.Series(True, index=mapped.index, dtype=bool)
    return param_masks

def _compute_param_masks_3(mapped, spc_map):
    if spc_map is None or spc_map.empty:
        return {}

    param_masks = {}
    for _, spc_item in spc_map.iterrows():
        param = spc_item['Parameter']
        col = resolve_param_column(mapped, param)
        if col is None:
            continue
        values = pd.to_numeric(mapped[col], errors='coerce')
        mask = values.notna()
        min_val = spc_item.get('Min')
        max_val = spc_item.get('Max')
        if min_val is not None and not pd.isna(min_val):
            mask &= values >= float(min_val)
        if max_val is not None and not pd.isna(max_val):
            mask &= values <= float(max_val)
        param_masks[param] = mask

    # Rsp/SPFR
    for rsp_param in [p for p in param_masks if p.startswith('Rsp')]:
        rsp_index = rsp_param[3:]
        spfr_param = f"SPFR_{rsp_index}"
        if spfr_param in param_masks:
            param_masks[rsp_param] = (
                (~param_masks[spfr_param]) | param_masks[rsp_param])
    for spfr_param in [p for p in param_masks if p.startswith('SPFR_')]:
        param_masks[spfr_param] = pd.Series(
            True, index=mapped.index, dtype=bool)

    return param_masks




def _compute_spec_status(mapped: pd.DataFrame,
                         spc_map: pd.DataFrame) -> pd.Series:
    """
    Общий статус изделия с учётом логики Rsp/SPFR
    (аналог Make_Measure).
    """
    param_masks = _compute_param_masks(mapped, spc_map)
    if not param_masks:
        return pd.Series(True, index=mapped.index, dtype=bool)

    overall = pd.Series(True, index=mapped.index, dtype=bool)
    for mask in param_masks.values():
        overall &= mask
    return overall




def load_tu_parameters_for_spec(spc_name: str) -> dict | None:
    """
    Загружает параметры ТУ для спецификации.

    Каскад:
      1. specification.Name = spc_name → NameR (тип резонатора), TU (имя ТУ)
      2. tu.TUName = TU AND tu.ResonatorName = NameR → TUIndex
         (если не найдено — без фильтра по резонатору)
      3. tu_parameters.TU_ID = TUIndex (или TU = TUName)

    Возвращает:
    {
        'tu_index': int,
        'tu_name': str,
        'spc_name': str,
        'rtype': str,
        'tu_row': dict,   # строка tu_parameters
    }
    или None.
    """
    if not spc_name:
        return None
    engine = create_engine(str(get_connection_string()))
    try:
        spc_df = pd.read_sql(
            text("SELECT * FROM specification WHERE Name = :n LIMIT 1"),
            engine, params={'n': spc_name})
        if spc_df.empty:
            print(f"[Archive] spec '{spc_name}' not found")
            return None
        spc_row = spc_df.iloc[0]
        rtype = _safe_str(spc_row.get('NameR'))
        tu_name = _safe_str(spc_row.get('TU'))
        if not tu_name:
            print(f"[Archive] spec '{spc_name}' has empty TU")
            return None

        tu_df = pd.read_sql(
            text("SELECT TUIndex, TUName FROM tu "
                 "WHERE TUName = :tu AND ResonatorName = :rt LIMIT 1"),
            engine, params={'tu': tu_name, 'rt': rtype})
        if tu_df.empty:
            tu_df = pd.read_sql(
                text("SELECT TUIndex, TUName FROM tu "
                     "WHERE TUName = :tu LIMIT 1"),
                engine, params={'tu': tu_name})
        if tu_df.empty:
            print(f"[Archive] TU '{tu_name}' not found")
            return None
        tu_index = int(tu_df.iloc[0]['TUIndex'])

        tp_df = pd.read_sql(
            text("SELECT * FROM tu_parameters "
                 "WHERE TU_ID = :i OR TU = :tu LIMIT 1"),
            engine, params={'i': tu_index, 'tu': tu_name})
        if tp_df.empty:
            print(f"[Archive] tu_parameters for TU '{tu_name}' "
                  f"(index {tu_index}) not found")
            return None

        return {
            'tu_index': tu_index,
            'tu_name': tu_name,
            'spc_name': spc_name,
            'rtype': rtype,
            'tu_row': tp_df.iloc[0].to_dict(),
        }
    except Exception as e:
        print(f"[Archive] load_tu_parameters_for_spec error: {e}")
        traceback.print_exc()
        return None

def build_presentation_params(spc_name: str, tu_data: dict) -> list[dict]:
    print(f"\n{'='*70}")
    print(f"[Presentation] build_presentation_params для Spc: {spc_name!r}")
    print(f"{'='*70}")

    spc_df = load_specification(spc_name)
    if spc_df.empty:
        print(f"[Presentation] Спецификация не найдена!")
        return []
    spec_row = spc_df.iloc[0]

    engine = create_engine(str(get_connection_string()))
    try:
        spc_map_table = pd.read_sql(
            "SELECT * FROM spc_map_table ORDER BY ID", engine)
    except Exception as e:
        print(f"[Presentation] spc_map_table недоступна: {e}")
        return []

    try:
        dopusk_map = pd.read_sql(
            "SELECT * FROM spc_dopusk_map_table ORDER BY ID", engine)
    except Exception:
        dopusk_map = pd.DataFrame()

    field_map = get_psidata_field_map()
    tu_row = (tu_data or {}).get('tu_row') or {}
    if not tu_row:
        print(f"[Presentation] tu_row пуст!")
        return []

    # --- Предварительный просмотр ---
    present_ids = set()
    for n in range(1, 10):
        id_field = 'Parametr_ID' if n == 7 else f'Parametr_{n}_ID'
        pid = _safe_int(tu_row.get(id_field))
        if pid is not None:
            present_ids.add(pid)

    print(f"[Presentation] ID в ТУ ({len(present_ids)}): {sorted(present_ids)}")
    has_param_30 = 30 in present_ids
    print(f"[Presentation] Есть параметр 30 (ABS): {has_param_30}")

    # --- Включены ли Fmax(15) и Fmin(16) в спецификации? ---
    p15 = spc_map_table[spc_map_table['ID'] == 15]
    p16 = spc_map_table[spc_map_table['ID'] == 16]
    use_15 = (_safe_str(p15.iloc[0]['Use']) if not p15.empty else '')
    use_16 = (_safe_str(p16.iloc[0]['Use']) if not p16.empty else '')
    fmax_use = _safe_int(spec_row.get(use_15), default=0) if use_15 else 0
    fmin_use = _safe_int(spec_row.get(use_16), default=0) if use_16 else 0
    print(f"[Presentation] Fmax(15).Use({use_15})={fmax_use}, "
          f"Fmin(16).Use({use_16})={fmin_use}")

    result = []
    seen_ids = set()

    for n in range(1, 10):
        id_field = 'Parametr_ID' if n == 7 else f'Parametr_{n}_ID'
        param_id = _safe_int(tu_row.get(id_field))

        if param_id is None or param_id in seen_ids:
            continue

        # Пропускаем 15/16, если есть 30 в ТУ
        if param_id in (15, 16) and has_param_30:
            print(f"[Presentation] N={n}: ID={param_id} пропущен "
                  f"(есть ID=30 в ТУ)")
            continue

        smt = spc_map_table[spc_map_table['ID'] == param_id]
        if smt.empty:
            print(f"[Presentation] N={n}: ID={param_id} нет в spc_map_table")
            continue
        smt = smt.iloc[0]

        # --- ПРОВЕРКА Use с учётом ID=30 ---
        if param_id == 30:
            # Для 30 смотрим Use не его самого (Fmaxm),
            # а 15 и 16 (Fmx и Fmn)
            if fmax_use != 1 or fmin_use != 1:
                print(f"[Presentation] N={n}: ID=30 (ABS) — "
                      f"15/16 не включены (Fmx={fmax_use}, "
                      f"Fmn={fmin_use}), пропуск")
                continue
            print(f"[Presentation] N={n}: ID=30 (ABS) — включён по Fmax+Fmin")
        else:
            use_field = _safe_str(smt.get('Use'))
            if not use_field:
                print(f"[Presentation] N={n}: ID={param_id} без Use-колонки")
                continue
            use_val = _safe_int(spec_row.get(use_field), default=0)
            if use_val != 1:
                print(f"[Presentation] N={n}: ID={param_id} "
                      f"Use={use_field}={use_val}, пропуск")
                continue

        param_name = _safe_str(smt.get('Parameter_Name'))
        if not param_name:
            continue

        field = param_name

        # --- Нормы (Max/Min) ---
        mx_f = _safe_str(smt.get('Max'))
        mn_f = _safe_str(smt.get('Min'))

        if param_id == 30:
            fmax_row = spc_map_table[spc_map_table['ID'] == 15]
            if not fmax_row.empty:
                mx_f = _safe_str(fmax_row.iloc[0].get('Max'))
                mn_f = _safe_str(fmax_row.iloc[0].get('Min'))
                print(f"[Presentation] N={n}: ID=30 → нормы из ID=15: "
                      f"Max={mx_f}, Min={mn_f}")

        max_tu = _safe_float(spec_row.get(mx_f)) if mx_f else None
        min_tu = _safe_float(spec_row.get(mn_f)) if mn_f else None

        has_mx = max_tu is not None and not pd.isna(max_tu)
        has_mn = min_tu is not None and not pd.isna(min_tu)

        # --- Нормы ОТК ---
        units = None
        pct = None
        if not dopusk_map.empty:
            dm = dopusk_map[dopusk_map['Parameter'] == param_name]
            if not dm.empty:
                u_f = _safe_str(dm.iloc[0].get('Dopusk_units'))
                p_f = _safe_str(dm.iloc[0].get('Dopusk_%'))
                units = _safe_float(spec_row.get(u_f)) if u_f else None
                pct = _safe_float(spec_row.get(p_f)) if p_f else None

        max_otk = max_tu
        min_otk = min_tu
        use_units = units is not None and units > 0
        use_pct = pct is not None and pct > 0
        if use_units and use_pct:
            use_pct = False

        if has_mx:
            if use_units:
                max_otk = float(max_tu) - float(units)
            elif use_pct:
                max_otk = (float(max_tu)
                           - abs(float(max_tu)) * float(pct) / 100.0)
        if has_mn:
            if use_units:
                min_otk = float(min_tu) + float(units)
            elif use_pct:
                min_otk = (float(min_tu)
                           + abs(float(min_tu)) * float(pct) / 100.0)

        print(f"[Presentation] N={n}: ID={param_id} '{param_name}' "
              f"field='{field}' Max_ТУ={max_tu} Min_ТУ={min_tu} "
              f"Max_ОТК={max_otk} Min_ОТК={min_otk}")

        result.append({
            'field': field,
            'param': param_name,
            'name': _safe_str(tu_row.get(f'Parametr_{n}_Name')) or param_name,
            'units': _safe_str(tu_row.get(f'Parametr_{n}_Units')),
            'max_tu': max_tu,
            'min_tu': min_tu,
            'max_otk': max_otk,
            'min_otk': min_otk,
            'has_max': has_mx,
            'has_min': has_mn,
            'has_norm': has_mx or has_mn,
            'cntrl': _safe_str(tu_row.get(f'Parametr_{n}_Cntrl_P')),
            'norm_p': _safe_str(tu_row.get(f'Parametr_{n}_Norm_P')),
            'norm_otk': _safe_str(tu_row.get(f'Parametr_{n}_Norm_OTK')),
        })
        seen_ids.add(param_id)

    print(f"[Presentation] Итого параметров: {len(result)}")
    print(f"[Presentation] Параметры: {[p['param'] for p in result]}")
    print(f"{'='*70}\n")
    return result

def build_presentation_params_99(spc_name: str, tu_data: dict) -> list[dict]:
    print(f"\n{'=' * 70}")
    print(f"[Presentation] build_presentation_params для Spc: {spc_name!r}")
    print(f"{'=' * 70}")

    spc_df = load_specification(spc_name)
    if spc_df.empty:
        print(f"[Presentation] Спецификация не найдена!")
        return []
    spec_row = spc_df.iloc[0]

    engine = create_engine(str(get_connection_string()))
    try:
        spc_map_table = pd.read_sql(
            "SELECT * FROM spc_map_table ORDER BY ID", engine)
    except Exception as e:
        print(f"[Presentation] spc_map_table недоступна: {e}")
        return []

    try:
        dopusk_map = pd.read_sql(
            "SELECT * FROM spc_dopusk_map_table ORDER BY ID", engine)
    except Exception as e:
        dopusk_map = pd.DataFrame()

    field_map = get_psidata_field_map()
    tu_row = (tu_data or {}).get('tu_row') or {}
    if not tu_row:
        print(f"[Presentation] tu_row пуст!")
        return []

    # --- ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР: собираем все ID, которые есть в ТУ ---
    present_ids = set()
    for n in range(1, 10):
        id_field = 'Parametr_ID' if n == 7 else f'Parametr_{n}_ID'
        pid = _safe_int(tu_row.get(id_field))
        if pid is not None:
            present_ids.add(pid)

    print(f"[Presentation] ID в ТУ ({len(present_ids)}): {sorted(present_ids)}")

    has_param_30 = 30 in present_ids
    print(f"[Presentation] Есть параметр 30 (ABS): {has_param_30}")

    result = []
    seen_ids = set()

    for n in range(1, 10):
        id_field = 'Parametr_ID' if n == 7 else f'Parametr_{n}_ID'
        param_id = _safe_int(tu_row.get(id_field))

        if param_id is None:
            continue
        if param_id in seen_ids:
            print(f"[Presentation] N={n}: ID={param_id} уже обработан, пропуск")
            continue

        # --- ПРОПУСКАЕМ 15 (Fmax) и 16 (Fmin), если есть 30 (ABS) ---
        if param_id in (15, 16) and has_param_30:
            print(f"[Presentation] N={n}: ID={param_id} пропущен (есть ID=30)")
            continue

        smt = spc_map_table[spc_map_table['ID'] == param_id]
        if smt.empty:
            print(f"[Presentation] N={n}: ID={param_id} нет в spc_map_table")
            continue
        smt = smt.iloc[0]

        use_field = _safe_str(smt.get('Use'))
        if not use_field:
            print(f"[Presentation] N={n}: ID={param_id} без Use-колонки")
            continue
        use_val = _safe_int(spec_row.get(use_field), default=0)
        if use_val != 1:
            print(f"[Presentation] N={n}: ID={param_id} Use={use_field}={use_val}, пропуск")
            continue

        param_name = _safe_str(smt.get('Parameter_Name'))
        if not param_name:
            print(f"[Presentation] N={n}: ID={param_id} без Parameter_Name")
            continue

        field = param_name  # в data_df колонки называются по Parameter_Name

        # --- ОПРЕДЕЛЕНИЕ НОРМ (Max/Min) ---
        mx_f = _safe_str(smt.get('Max'))
        mn_f = _safe_str(smt.get('Min'))

        # Для параметра 30 принудительно берем нормы из Fmax (ID 15)
        if param_id == 30:
            fmax_row = spc_map_table[spc_map_table['ID'] == 15]
            if not fmax_row.empty:
                mx_f = _safe_str(fmax_row.iloc[0].get('Max'))
                mn_f = _safe_str(fmax_row.iloc[0].get('Min'))
                print(f"[Presentation] N={n}: ID=30 → нормы из ID=15: Max={mx_f}, Min={mn_f}")

        max_tu = _safe_float(spec_row.get(mx_f)) if mx_f else None
        min_tu = _safe_float(spec_row.get(mn_f)) if mn_f else None

        has_mx = max_tu is not None and not pd.isna(max_tu)
        has_mn = min_tu is not None and not pd.isna(min_tu)

        # --- РАСЧЕТ НОРМ ОТК ---
        units = None
        pct = None
        if not dopusk_map.empty:
            dm = dopusk_map[dopusk_map['Parameter'] == param_name]
            if not dm.empty:
                u_f = _safe_str(dm.iloc[0].get('Dopusk_units'))
                p_f = _safe_str(dm.iloc[0].get('Dopusk_%'))
                units = _safe_float(spec_row.get(u_f)) if u_f else None
                pct = _safe_float(spec_row.get(p_f)) if p_f else None

        max_otk = max_tu
        min_otk = min_tu
        use_units = units is not None and units > 0
        use_pct = pct is not None and pct > 0
        if use_units and use_pct:
            use_pct = False

        if has_mx:
            if use_units:
                max_otk = float(max_tu) - float(units)
            elif use_pct:
                max_otk = (float(max_tu)
                           - abs(float(max_tu)) * float(pct) / 100.0)
        if has_mn:
            if use_units:
                min_otk = float(min_tu) + float(units)
            elif use_pct:
                min_otk = (float(min_tu)
                           + abs(float(min_tu)) * float(pct) / 100.0)

        print(f"[Presentation] N={n}: ID={param_id} '{param_name}' "
              f"field='{field}' Max_ТУ={max_tu} Min_ТУ={min_tu} "
              f"Max_ОТК={max_otk} Min_ОТК={min_otk}")

        result.append({
            'field': field,
            'param': param_name,
            'name': _safe_str(tu_row.get(f'Parametr_{n}_Name')) or param_name,
            'units': _safe_str(tu_row.get(f'Parametr_{n}_Units')),
            'max_tu': max_tu,
            'min_tu': min_tu,
            'max_otk': max_otk,
            'min_otk': min_otk,
            'has_max': has_mx,
            'has_min': has_mn,
            'has_norm': has_mx or has_mn,
            'cntrl': _safe_str(tu_row.get(f'Parametr_{n}_Cntrl_P')),
            'norm_p': _safe_str(tu_row.get(f'Parametr_{n}_Norm_P')),
            'norm_otk': _safe_str(tu_row.get(f'Parametr_{n}_Norm_OTK')),
        })
        seen_ids.add(param_id)

    print(f"[Presentation] Итого параметров: {len(result)}")
    print(f"[Presentation] Параметры: {[p['param'] for p in result]}")
    print(f"{'=' * 70}\n")
    return result
def build_presentation_params_10(spc_name: str, tu_data: dict) -> list[dict]:
    """
    Возвращает список параметров для предъявительского протокола.
    """
    spc_df = load_specification(spc_name)
    if spc_df.empty:
        return []
    spec_row = spc_df.iloc[0]

    engine = create_engine(str(get_connection_string()))
    try:
        spc_map_table = pd.read_sql(
            "SELECT * FROM spc_map_table ORDER BY ID", engine)
    except Exception as e:
        print(f"[Archive] spc_map_table недоступна: {e}")
        return []

    try:
        dopusk_map = pd.read_sql(
            "SELECT * FROM spc_dopusk_map_table ORDER BY ID", engine)
    except Exception as e:
        dopusk_map = pd.DataFrame()

    field_map = get_psidata_field_map()
    tu_row = (tu_data or {}).get('tu_row') or {}
    if not tu_row:
        return []

    # --- ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР: собираем все ID, которые есть в ТУ ---
    present_ids = set()
    for n in range(1, 10):
        id_field = 'Parametr_ID' if n == 7 else f'Parametr_{n}_ID'
        pid = _safe_int(tu_row.get(id_field))
        if pid is not None:
            present_ids.add(pid)

    has_param_30 = 30 in present_ids

    result = []
    seen_ids = set()

    for n in range(1, 10):
        id_field = 'Parametr_ID' if n == 7 else f'Parametr_{n}_ID'
        param_id = _safe_int(tu_row.get(id_field))

        if param_id is None or param_id in seen_ids:
            continue

        # --- ПРОПУСКАЕМ 15 (Fmax) и 16 (Fmin), если есть 30 (ABS) ---
        if param_id in (15, 16) and has_param_30:
            continue

        smt = spc_map_table[spc_map_table['ID'] == param_id]
        if smt.empty:
            continue
        smt = smt.iloc[0]

        use_field = _safe_str(smt.get('Use'))
        if not use_field:
            continue
        if _safe_int(spec_row.get(use_field), default=0) != 1:
            continue

        param_name = _safe_str(smt.get('Parameter_Name'))
        if not param_name:
            continue

        # --- ОПРЕДЕЛЕНИЕ КОЛОНКИ С ДАННЫМИ ---
        # data_df всегда использует имена параметров (Parameter_Name),
        # поэтому передаем param_name вместо физического field
        field = param_name

        # --- ОПРЕДЕЛЕНИЕ НОРМ (Max/Min) ---
        mx_f = _safe_str(smt.get('Max'))
        mn_f = _safe_str(smt.get('Min'))

        # Для параметра 30 принудительно берем нормы из Fmax (ID 15)
        if param_id == 30:
            fmax_row = spc_map_table[spc_map_table['ID'] == 15]
            if not fmax_row.empty:
                mx_f = _safe_str(fmax_row.iloc[0].get('Max'))
                mn_f = _safe_str(fmax_row.iloc[0].get('Min'))

        max_tu = _safe_float(spec_row.get(mx_f)) if mx_f else None
        min_tu = _safe_float(spec_row.get(mn_f)) if mn_f else None

        has_mx = max_tu is not None and not pd.isna(max_tu)
        has_mn = min_tu is not None and not pd.isna(min_tu)

        # --- РАСЧЕТ НОРМ ОТК (С ТЕХЗАПАСОМ) ---
        units = None
        pct = None
        if not dopusk_map.empty:
            dm = dopusk_map[dopusk_map['Parameter'] == param_name]
            if not dm.empty:
                u_f = _safe_str(dm.iloc[0].get('Dopusk_units'))
                p_f = _safe_str(dm.iloc[0].get('Dopusk_%'))
                units = _safe_float(spec_row.get(u_f)) if u_f else None
                pct = _safe_float(spec_row.get(p_f)) if p_f else None

        max_otk = max_tu
        min_otk = min_tu
        use_units = units is not None and units > 0
        use_pct = pct is not None and pct > 0
        if use_units and use_pct:
            use_pct = False

        if has_mx:
            if use_units:
                max_otk = float(max_tu) - float(units)
            elif use_pct:
                max_otk = (float(max_tu)
                           - abs(float(max_tu)) * float(pct) / 100.0)
        if has_mn:
            if use_units:
                min_otk = float(min_tu) + float(units)
            elif use_pct:
                min_otk = (float(min_tu)
                           + abs(float(min_tu)) * float(pct) / 100.0)

        result.append({
            'field': field,
            'param': param_name,
            'name': _safe_str(tu_row.get(f'Parametr_{n}_Name')) or param_name,
            'units': _safe_str(tu_row.get(f'Parametr_{n}_Units')),
            'max_tu': max_tu,
            'min_tu': min_tu,
            'max_otk': max_otk,
            'min_otk': min_otk,
            'has_max': has_mx,
            'has_min': has_mn,
            'has_norm': has_mx or has_mn,
            'cntrl': _safe_str(tu_row.get(f'Parametr_{n}_Cntrl_P')),  # Метод контроля
            'norm_p': _safe_str(tu_row.get(f'Parametr_{n}_Norm_P')),  # Пункт ТУ
            'norm_otk': _safe_str(tu_row.get(f'Parametr_{n}_Norm_OTK')),
        })
        seen_ids.add(param_id)

    return result
def build_presentation_params_9(spc_name: str, tu_data: dict) -> list[dict]:
    """
    Возвращает список параметров для предъявительского протокола.

    Источник порядка и имён — tu_parameters:
        Parametr_N_ID  →  spc_map_table.ID  (для N=7: Parametr_ID)
    Для каждого активного в спецификации параметра собираются:
        * field   — Field в таблице замеров (через psidata_map_table)
        * param   — Parameter_Name из spc_map_table
        * name    — tu_parameters.Parametr_N_Name  (заголовок столбца)
        * max_tu, min_tu   — нормы ТУ из specification
        * max_otk, min_otk — нормы с техзапасом
        * cntrl    — tu_parameters.Parametr_N_Cntrl_P
        * norm_p   — tu_parameters.Parametr_N_Norm_P
        * norm_otk — tu_parameters.Parametr_N_Norm_OTK
        * has_norm — True, если задан хотя бы Max или Min
    """
    spc_df = load_specification(spc_name)
    if spc_df.empty:
        return []
    spec_row = spc_df.iloc[0]

    engine = create_engine(str(get_connection_string()))
    try:
        spc_map_table = pd.read_sql(
            "SELECT * FROM spc_map_table ORDER BY ID", engine)
    except Exception as e:
        print(f"[Archive] spc_map_table недоступна: {e}")
        return []

    try:
        dopusk_map = pd.read_sql(
            "SELECT * FROM spc_dopusk_map_table ORDER BY ID", engine)
    except Exception as e:
        print(f"[Archive] spc_dopusk_map_table недоступна: {e} "
              f"→ техзапас не применяется")
        dopusk_map = pd.DataFrame()

    field_map = get_psidata_field_map()
    tu_row = (tu_data or {}).get('tu_row') or {}
    if not tu_row:
        return []

    # --- ПРЕДВАРИТЕЛЬНЫЙ ПРОСМОТР: собираем все ID, которые есть в ТУ ---
    # Это нужно, чтобы понять, есть ли параметр 30 (ABS(Fmax, Fmin))
    present_ids = set()
    for n in range(1, 10):
        id_field = 'Parametr_ID' if n == 7 else f'Parametr_{n}_ID'
        pid = _safe_int(tu_row.get(id_field))
        if pid is not None:
            present_ids.add(pid)

    has_param_30 = 30 in present_ids

    result = []
    seen_ids = set()

    for n in range(1, 10):
        id_field = 'Parametr_ID' if n == 7 else f'Parametr_{n}_ID'
        param_id = _safe_int(tu_row.get(id_field))

        if param_id is None or param_id in seen_ids:
            continue

        # --- ПРОПУСКАЕМ 15 (Fmax) и 16 (Fmin), если есть 30 (ABS) ---
        if param_id in (15, 16) and has_param_30:
            continue

        smt = spc_map_table[spc_map_table['ID'] == param_id]
        if smt.empty:
            continue
        smt = smt.iloc[0]

        use_field = _safe_str(smt.get('Use'))
        if not use_field:
            continue
        if _safe_int(spec_row.get(use_field), default=0) != 1:
            continue

        param_name = _safe_str(smt.get('Parameter_Name'))
        if not param_name:
            continue

        # --- ОПРЕДЕЛЕНИЕ КОЛОНКИ С ДАННЫМИ ---
        if param_name == 'ABS(Fmax, Fmin)':
            field = 'Fmaxm'  # Берем из вычисленной колонки
        else:
            field = field_map.get(param_name, param_name)

        # --- ОПРЕДЕЛЕНИЕ НОРМ (Max/Min) ---
        mx_f = _safe_str(smt.get('Max'))
        mn_f = _safe_str(smt.get('Min'))

        # Для параметра 30 принудительно берем нормы из Fmax (ID 15)
        if param_id == 30:
            fmax_row = spc_map_table[spc_map_table['ID'] == 15]
            if not fmax_row.empty:
                mx_f = _safe_str(fmax_row.iloc[0].get('Max'))
                mn_f = _safe_str(fmax_row.iloc[0].get('Min'))

        max_tu = _safe_float(spec_row.get(mx_f)) if mx_f else None
        min_tu = _safe_float(spec_row.get(mn_f)) if mn_f else None

        has_mx = max_tu is not None and not pd.isna(max_tu)
        has_mn = min_tu is not None and not pd.isna(min_tu)

        # --- РАСЧЕТ НОРМ ОТК (С ТЕХЗАПАСОМ) ---
        units = None
        pct = None
        if not dopusk_map.empty:
            dm = dopusk_map[dopusk_map['Parameter'] == param_name]
            if not dm.empty:
                u_f = _safe_str(dm.iloc[0].get('Dopusk_units'))
                p_f = _safe_str(dm.iloc[0].get('Dopusk_%'))
                units = _safe_float(spec_row.get(u_f)) if u_f else None
                pct = _safe_float(spec_row.get(p_f)) if p_f else None

        max_otk = max_tu
        min_otk = min_tu
        use_units = units is not None and units > 0
        use_pct = pct is not None and pct > 0
        if use_units and use_pct:
            use_pct = False

        if has_mx:
            if use_units:
                max_otk = float(max_tu) - float(units)
            elif use_pct:
                max_otk = (float(max_tu)
                           - abs(float(max_tu)) * float(pct) / 100.0)
        if has_mn:
            if use_units:
                min_otk = float(min_tu) + float(units)
            elif use_pct:
                min_otk = (float(min_tu)
                           + abs(float(min_tu)) * float(pct) / 100.0)

        result.append({
            'field': field,
            'param': param_name,
            'name': _safe_str(tu_row.get(f'Parametr_{n}_Name')) or param_name,
            'units': _safe_str(tu_row.get(f'Parametr_{n}_Units')),
            'max_tu': max_tu,
            'min_tu': min_tu,
            'max_otk': max_otk,
            'min_otk': min_otk,
            'has_max': has_mx,
            'has_min': has_mn,
            'has_norm': has_mx or has_mn,
            'cntrl': _safe_str(tu_row.get(f'Parametr_{n}_Cntrl_P')),  # Метод контроля
            'norm_p': _safe_str(tu_row.get(f'Parametr_{n}_Norm_P')),  # Пункт ТУ
            'norm_otk': _safe_str(tu_row.get(f'Parametr_{n}_Norm_OTK')),
        })
        seen_ids.add(param_id)

    return result

def build_presentation_params_3(spc_name: str, tu_data: dict) -> list[dict]:
    """
    Возвращает список параметров для предъявительского протокола.

    Источник порядка и имён — tu_parameters:
        Parametr_N_ID  →  spc_map_table.ID  (для N=7: Parametr_ID)
    Для каждого активного в спецификации параметра собираются:
        * field   — Field в таблице замеров (через psidata_map_table)
        * param   — Parameter_Name из spc_map_table
        * name    — tu_parameters.Parametr_N_Name  (заголовок столбца)
        * max_tu, min_tu   — нормы ТУ из specification
        * max_otk, min_otk — нормы с техзапасом
        * cntrl    — tu_parameters.Parametr_N_Cntrl_P
        * norm_p   — tu_parameters.Parametr_N_Norm_P
        * norm_otk — tu_parameters.Parametr_N_Norm_OTK
        * has_norm — True, если задан хотя бы Max или Min
    """
    spc_df = load_specification(spc_name)
    if spc_df.empty:
        return []
    spec_row = spc_df.iloc[0]

    engine = create_engine(str(get_connection_string()))
    try:
        spc_map_table = pd.read_sql(
            "SELECT * FROM spc_map_table ORDER BY ID", engine)
    except Exception as e:
        print(f"[Archive] spc_map_table недоступна: {e}")
        return []

    try:
        dopusk_map = pd.read_sql(
            "SELECT * FROM spc_dopusk_map_table ORDER BY ID", engine)
    except Exception as e:
        print(f"[Archive] spc_dopusk_map_table недоступна: {e} "
              f"→ техзапас не применяется")
        dopusk_map = pd.DataFrame()

    field_map = get_psidata_field_map()
    tu_row = (tu_data or {}).get('tu_row') or {}
    if not tu_row:
        return []

    result = []
    seen_ids = set()

    for n in range(1, 10):
        id_field = 'Parametr_ID' if n == 7 else f'Parametr_{n}_ID'
        param_id = _safe_int(tu_row.get(id_field))
        if param_id is None or param_id in seen_ids:
            continue

        smt = spc_map_table[spc_map_table['ID'] == param_id]
        if smt.empty:
            continue
        smt = smt.iloc[0]

        use_field = _safe_str(smt.get('Use'))
        if not use_field:
            continue
        if _safe_int(spec_row.get(use_field), default=0) != 1:
            continue

        param_name = _safe_str(smt.get('Parameter_Name'))
        if not param_name:
            continue
        field = field_map.get(param_name, param_name)

        mx_f = _safe_str(smt.get('Max'))
        mn_f = _safe_str(smt.get('Min'))
        max_tu = _safe_float(spec_row.get(mx_f)) if mx_f else None
        min_tu = _safe_float(spec_row.get(mn_f)) if mn_f else None

        has_mx = max_tu is not None and not pd.isna(max_tu)
        has_mn = min_tu is not None and not pd.isna(min_tu)

        units = None
        pct = None
        if not dopusk_map.empty:
            dm = dopusk_map[dopusk_map['Parameter'] == param_name]
            if not dm.empty:
                u_f = _safe_str(dm.iloc[0].get('Dopusk_units'))
                p_f = _safe_str(dm.iloc[0].get('Dopusk_%'))
                units = _safe_float(spec_row.get(u_f)) if u_f else None
                pct   = _safe_float(spec_row.get(p_f)) if p_f else None

        max_otk = max_tu
        min_otk = min_tu
        use_units = units is not None and units > 0
        use_pct   = pct   is not None and pct   > 0
        if use_units and use_pct:
            use_pct = False

        if has_mx:
            if use_units:
                max_otk = float(max_tu) - float(units)
            elif use_pct:
                max_otk = (float(max_tu)
                           - abs(float(max_tu)) * float(pct) / 100.0)
        if has_mn:
            if use_units:
                min_otk = float(min_tu) + float(units)
            elif use_pct:
                min_otk = (float(min_tu)
                           + abs(float(min_tu)) * float(pct) / 100.0)

        result.append({
            'field': field,
            'param': param_name,
            'name': _safe_str(tu_row.get(f'Parametr_{n}_Name')) or param_name,
            'units': _safe_str(tu_row.get(f'Parametr_{n}_Units')),
            'max_tu': max_tu,
            'min_tu': min_tu,
            'max_otk': max_otk,
            'min_otk': min_otk,
            'has_max': has_mx,
            'has_min': has_mn,
            'has_norm': has_mx or has_mn,
            'cntrl': _safe_str(tu_row.get(f'Parametr_{n}_Cntrl_P')),
            'norm_p': _safe_str(tu_row.get(f'Parametr_{n}_Norm_P')),
            'norm_otk': _safe_str(tu_row.get(f'Parametr_{n}_Norm_OTK')),
        })
        seen_ids.add(param_id)

    return result

def get_next_protocol_number_archive() -> int:
    """Получить следующий номер протокола из таблицы psi_measure_protokol_id."""
    engine = create_engine(str(get_connection_string()))
    try:
        df = pd.read_sql(
            "SELECT MAX(CAST(ProtokolN AS UNSIGNED)) AS mx FROM psi_measure_protokol_id",
            engine
        )
        if not df.empty:
            mx = df.iloc[0]['mx']
            if pd.notna(mx):
                return int(mx) + 1
    except Exception as e:
        print(f"[Archive] Ошибка получения номера протокола: {e}")
    return 1
def save_protocol_to_db(protokol_n: int, msk: str, file_name: str, measure_id: int, count: int, spc: str) -> int:
    """Сохранить информацию о созданном протоколе в psi_measure_protokol_id.
    Возвращает Measure_protokol_ID."""
    from datetime import datetime
    engine = create_engine(str(get_connection_string()))
    try:
        with engine.begin() as conn:
            res = conn.execute(text("""
                INSERT INTO `psi_measure_protokol_id` 
                (`ProtokolN`, `MSK`, `File`, `Measure_ID`, `dataR`, `Count`, `Spc`)
                VALUES (:pn, :msk, :file, :mid, :dataR, :count, :spc)
            """), {
                'pn': protokol_n,
                'msk': msk,
                'file': file_name,
                'mid': measure_id,
                'dataR': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'count': count,
                'spc': spc
            })
            new_id = res.lastrowid
        print(f"[Archive] Протокол N {protokol_n} сохранён (ID={new_id})")
        return new_id
    except Exception as e:
        print(f"[Archive] Ошибка сохранения в psi_measure_protokol_id: {e}")
        return None

def save_protocol_to_db_12(protokol_n: int, msk: str, file_name: str, measure_id: int, count: int, spc: str):
    """Сохранить информацию о созданном протоколе в psi_measure_protokol_id."""
    from datetime import datetime
    engine = create_engine(str(get_connection_string()))
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                INSERT INTO `psi_measure_protokol_id` 
                (`ProtokolN`, `MSK`, `File`, `Measure_ID`, `dataR`, `Count`, `Spc`)
                VALUES (:pn, :msk, :file, :mid, :dataR, :count, :spc)
            """), {
                'pn': protokol_n,
                'msk': msk,
                'file': file_name,
                'mid': measure_id,
                'dataR': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'count': count,
                'spc': spc
            })
        print(f"[Archive] Протокол N {protokol_n} сохранён в psi_measure_protokol_id")
    except Exception as e:
        print(f"[Archive] Ошибка сохранения в psi_measure_protokol_id: {e}")


def log_protocol_creation(measure_id: int, protokol_n: int):
    """Логирование операции создания протокола в отдельную таблицу."""
    from .Archive_ActionsLog import get_operator
    from datetime import datetime
    engine = create_engine(str(get_connection_string()))
    try:
        with engine.begin() as conn:
            # Создаем таблицу, если её нет
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS `protocol_creation_log` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `measure_id` INT,
                    `protokol_n` INT,
                    `action` VARCHAR(50) DEFAULT 'create_presentation',
                    `operator` VARCHAR(100),
                    `created_at` DATETIME
                )
            """))
            conn.execute(text("""
                INSERT INTO `protocol_creation_log` 
                (`measure_id`, `protokol_n`, `action`, `operator`, `created_at`)
                VALUES (:mid, :pn, 'create_presentation', :op, :dt)
            """), {
                'mid': measure_id,
                'pn': protokol_n,
                'op': get_operator(),
                'dt': datetime.now()
            })
        print(f"[Archive] Запись в журнал создания протоколов добавлена (ID={measure_id})")
    except Exception as e:
        print(f"[Archive] Ошибка записи в журнал: {e}")