import pandas as pd
from sqlalchemy import create_engine, text, bindparam
from datetime import datetime
import Options
import re
from sqlalchemy import inspect as _sa_inspect


# --- безопасные bind-имена для колонок с дефисами: F0-Fl, Rmax-Rmin, MSK-M ---
_BIND_RE = re.compile(r'[^A-Za-z0-9_]')


def _sanitize_bind(name):
    """Имя колонки → валидное имя bind-параметра SQLAlchemy."""
    return _BIND_RE.sub('_', str(name))


def _quote_ident(name):
    """MySQL-экранирование идентификатора (таблица/колонка)."""
    return '`' + str(name).replace('`', '``') + '`'


_DTYPE_TO_SQL = {
    'int64': 'INT', 'Int64': 'INT', 'int32': 'INT',
    'float64': 'DOUBLE', 'Float64': 'DOUBLE', 'float32': 'FLOAT',
    'bool': 'TINYINT(1)', 'datetime64[ns]': 'DATETIME',
}


def _ensure_columns_autocommit(engine, table_name, df):
    """Добавляет в БД отсутствующие колонки из df (ALTER TABLE, autocommit)."""
    if df is None or len(df.columns) == 0:
        return
    try:
        insp = _sa_inspect(engine)
        existing = {c['name'].lower() for c in insp.get_columns(table_name)}
    except Exception as e:
        print(f"[Protocol_Data] _ensure_columns_autocommit inspect "
              f"{table_name}: {e}")
        return
    missing = [c for c in df.columns if str(c).lower() not in existing]
    if not missing:
        return
    for col in missing:
        sql_type = _DTYPE_TO_SQL.get(str(df[col].dtype), 'TEXT')
        try:
            with engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(
                    f"ALTER TABLE {_quote_ident(table_name)} "
                    f"ADD COLUMN {_quote_ident(col)} {sql_type} NULL"
                ))
            print(f"[Protocol_Data] ALTER TABLE {table_name}: "
                  f"добавлена колонка {col} {sql_type}")
        except Exception as e:
            print(f"[Protocol_Data] ALTER TABLE {table_name}.{col} failed: {e}")


def _insert_df_ignore(engine, table_name, df):
    """INSERT IGNORE DataFrame.

    - Имена колонок экранируются `...`.
    - Имена bind-параметров санитайзятся: `:F0-Fl` → `:F0_Fl`.
      Без этого SQLAlchemy парсит `%(F0-Fl)s` как параметр `F0`
      + литерал `-Fl` и падает с `InvalidRequestError: bind parameter 'F0'`.
    - При отсутствии колонок в БД — авто-ALTER.
    """
    if df is None or df.empty:
        return 0

    _ensure_columns_autocommit(engine, table_name, df)

    cols = list(df.columns)
    col_sql = ", ".join(_quote_ident(c) for c in cols)

    bind_names = []
    used = set()
    for c in cols:
        base = _sanitize_bind(c) or 'col'
        name = base
        i = 1
        while name in used:
            i += 1
            name = f"{base}__{i}"
        used.add(name)
        bind_names.append(name)
    val_sql = ", ".join(f":{b}" for b in bind_names)

    stmt = text(
        f"INSERT IGNORE INTO {_quote_ident(table_name)} "
        f"({col_sql}) VALUES ({val_sql})"
    )

    records = []
    for _, row in df.iterrows():
        rec = {}
        for b, c in zip(bind_names, cols):
            v = row[c]
            try:
                if pd.isna(v):
                    v = None
            except (TypeError, ValueError):
                pass
            if hasattr(v, 'item'):          # numpy scalar → python scalar
                v = v.item()
            rec[b] = v
        records.append(rec)

    with engine.begin() as conn:
        conn.execute(stmt, records)
    return len(records)
def _engine():
    return create_engine(str(Options.get_connection_string()))


def get_measure_resonators(measure_id: int) -> pd.DataFrame:
    engine = _engine()
    sql = text("SELECT N, Status2 FROM psidata WHERE Measure_ID = :mid ORDER BY N")
    try:
        return pd.read_sql(sql, engine, params={'mid': measure_id})
    except Exception as e:
        print(f"[Protocol_Data] Ошибка загрузки резонаторов: {e}")
        return pd.DataFrame()


# ============================================================================
# Поиск протоколов (универсальный)
# ============================================================================
def search_archived_protocols(msk_partial: str = None,
                              n_partial: str = None,
                              *,
                              msk_exact: str = None,
                              spc: str = None,
                              rtype: str = None,
                              date: str = None,
                              file: str = None,
                              numbers: list = None,
                              psi_type: str = None,
                              limit: int = 500) -> pd.DataFrame:
    """Универсальный поиск протоколов.

    Параметры
    ---------
    msk_partial : str
        Подстрока номера МСК (LIKE %...%).
    n_partial : str
        Подстрока номера резонатора (LIKE %...%).
    msk_exact : str
        Точный номер МСК.
    spc : str
        Спецификация (Name или Text из specification).
    rtype : str
        Тип резонатора (NameR).
    date : str
        Дата протокола (YYYY-MM-DD), сравнивается с DATE(dataR).
    file : str
        Подстрока имени файла.
    numbers : list[str]
        Список номеров резонаторов. Ищет протоколы, содержащие
        хотя бы один из них — через psidata.Measure_ID или
        psi_protokol_archive.N.
    psi_type : str
        'ПСИ' или 'ОТК'. Фильтр по типу протокола. Если в БД нет
        колонки psi_type — все считаются 'ОТК'.
    limit : int
        Максимум строк.

    Возвращает pd.DataFrame со столбцами:
        Measure_protokol_ID, ProtokolN, MSK, Spc, dataR,
        Total_Count, PsiType, Measure_ID, Current_Count.
    """
    engine = _engine()
    conds, params = [], {}
    expanding = []

    # psi_type_expr нужен и в WHERE, и в SELECT, поэтому вычисляем
    # до сборки условия. На старых БД без колонки возвращаем 'ОТК'.
    psi_type_expr = ("COALESCE(p.psi_type, 'ОТК')"
                     if _has_psi_type_column(engine) else "'ОТК'")

    # --- Каскад ---
    if msk_exact:
        conds.append("p.MSK = :msk_exact")
        params['msk_exact'] = msk_exact
    if date:
        conds.append("DATE(p.dataR) = :date")
        params['date'] = date
    if file:
        conds.append("p.File LIKE :file")
        params['file'] = f"%{file}%"
    if spc:
        conds.append(
            "(p.Spc = :spc "
            " OR p.Spc IN (SELECT Text FROM specification WHERE Name = :spc))")
        params['spc'] = spc
    if rtype:
        conds.append(
            "p.Spc IN (SELECT Name FROM specification WHERE NameR = :rtype "
            "          UNION "
            "          SELECT Text FROM specification WHERE NameR = :rtype)")
        params['rtype'] = rtype

    # --- Тип протокола ---
    if psi_type:
        conds.append(f"{psi_type_expr} = :psi_type")
        params['psi_type'] = psi_type

    # --- Ввод пользователя ---
    if msk_partial:
        conds.append("p.MSK LIKE :msk_partial")
        params['msk_partial'] = f"%{msk_partial}%"

    # --- Номера ---
    mid_from_psidata: set[int] = set()
    if numbers:
        nums_upper = [str(n).strip().upper()
                      for n in numbers if str(n).strip()]
        if nums_upper:
            try:
                from sqlalchemy import bindparam as _bp
                sql_mids = text(
                    "SELECT DISTINCT Measure_ID FROM psidata "
                    "WHERE UPPER(TRIM(N)) IN :nums "
                    "  AND Measure_ID IS NOT NULL"
                ).bindparams(_bp("nums", expanding=True))
                df_mids = pd.read_sql(sql_mids, engine,
                                      params={'nums': nums_upper})
                if not df_mids.empty:
                    mid_from_psidata = {
                        int(x) for x in df_mids['Measure_ID'].dropna().unique()
                    }
            except Exception as e:
                print(f"[Protocol_Data] Поиск Measure_ID по номерам: {e}")

    if mid_from_psidata:
        conds.append(
            "(p.Measure_ID IN :mids "
            " OR EXISTS (SELECT 1 FROM psi_protokol_archive a "
            "            WHERE a.Measure_Protokol_ID = p.Measure_protokol_ID "
            "              AND a.N IN :nums))")
        params['mids'] = list(mid_from_psidata)
        params['nums'] = [str(n).strip().upper() for n in numbers]
        expanding.extend(['mids', 'nums'])
    elif numbers:
        conds.append(
            "EXISTS (SELECT 1 FROM psi_protokol_archive a "
            "        WHERE a.Measure_Protokol_ID = p.Measure_protokol_ID "
            "          AND a.N IN :nums)")
        params['nums'] = [str(n).strip().upper() for n in numbers]
        expanding.append('nums')
    elif n_partial:
        conds.append(
            "EXISTS (SELECT 1 FROM psi_protokol_archive a "
            "        WHERE a.Measure_Protokol_ID = p.Measure_protokol_ID "
            "          AND a.N LIKE :n_partial)")
        params['n_partial'] = f"%{n_partial}%"

    where = " AND ".join(conds) if conds else "1=1"

    sql_str = f"""
        SELECT p.Measure_protokol_ID, p.ProtokolN, p.MSK, p.Spc,
               p.dataR, p.Count AS Total_Count,
               {psi_type_expr} AS PsiType,
               p.Measure_ID,
               (SELECT COUNT(*) FROM psi_protokol_archive a2
                WHERE a2.Measure_Protokol_ID = p.Measure_protokol_ID)
                 AS Current_Count
        FROM psi_measure_protokol_id p
        WHERE {where}
        ORDER BY p.dataR DESC, p.Measure_protokol_ID DESC
        LIMIT {int(limit)}
    """

    try:
        stmt = text(sql_str)
        for name in expanding:
            stmt = stmt.bindparams(bindparam(name, expanding=True))
        df = pd.read_sql(stmt, engine, params=params)

        # Страховка: если по какой-то причине PsiType отсутствует —
        # заполняем 'ОТК', чтобы downstream-код не падал на df['PsiType'].
        if 'PsiType' not in df.columns:
            df['PsiType'] = 'ОТК'
        else:
            df['PsiType'] = df['PsiType'].fillna('ОТК').replace('', 'ОТК')

        return df
    except Exception as e:
        print(f"[Protocol_Data] search_archived_protocols: {e}")
        import traceback
        traceback.print_exc()
        return pd.DataFrame()
def search_archived_protocols_1(msk_partial: str = None,
                              n_partial: str = None,
                              *,
                              msk_exact: str = None,
                              spc: str = None,
                              rtype: str = None,
                              date: str = None,
                              file: str = None,
                              numbers: list = None,
                              limit: int = 500) -> pd.DataFrame:
    engine = _engine()
    conds, params = [], {}
    expanding = []

    # --- Каскад ---
    if msk_exact:
        conds.append("p.MSK = :msk_exact")
        params['msk_exact'] = msk_exact
    if date:
        conds.append("DATE(p.dataR) = :date")
        params['date'] = date
    if file:
        conds.append("p.File LIKE :file")
        params['file'] = f"%{file}%"
    if spc:
        conds.append(
            "(p.Spc = :spc "
            " OR p.Spc IN (SELECT Text FROM specification WHERE Name = :spc))")
        params['spc'] = spc
    if rtype:
        conds.append(
            "p.Spc IN (SELECT Name FROM specification WHERE NameR = :rtype "
            "          UNION "
            "          SELECT Text FROM specification WHERE NameR = :rtype)")
        params['rtype'] = rtype

    # --- Ввод пользователя ---
    if msk_partial:
        conds.append("p.MSK LIKE :msk_partial")
        params['msk_partial'] = f"%{msk_partial}%"

    # --- Номера ---
    mid_from_psidata: set[int] = set()
    if numbers:
        nums_upper = [str(n).strip().upper() for n in numbers if str(n).strip()]
        if nums_upper:
            try:
                from sqlalchemy import bindparam as _bp
                sql_mids = text(
                    "SELECT DISTINCT Measure_ID FROM psidata "
                    "WHERE UPPER(TRIM(N)) IN :nums "
                    "  AND Measure_ID IS NOT NULL"
                ).bindparams(_bp("nums", expanding=True))
                df_mids = pd.read_sql(sql_mids, engine,
                                      params={'nums': nums_upper})
                if not df_mids.empty:
                    mid_from_psidata = {
                        int(x) for x in df_mids['Measure_ID'].dropna().unique()
                    }
            except Exception as e:
                print(f"[Protocol_Data] Поиск Measure_ID по номерам: {e}")

    if mid_from_psidata:
        conds.append(
            "(p.Measure_ID IN :mids "
            " OR EXISTS (SELECT 1 FROM psi_protokol_archive a "
            "            WHERE a.Measure_Protokol_ID = p.Measure_protokol_ID "
            "              AND a.N IN :nums))")
        params['mids'] = list(mid_from_psidata)
        params['nums'] = [str(n).strip().upper() for n in numbers]
        expanding.extend(['mids', 'nums'])
    elif numbers:
        conds.append(
            "EXISTS (SELECT 1 FROM psi_protokol_archive a "
            "        WHERE a.Measure_Protokol_ID = p.Measure_protokol_ID "
            "          AND a.N IN :nums)")
        params['nums'] = [str(n).strip().upper() for n in numbers]
        expanding.append('nums')
    elif n_partial:
        conds.append(
            "EXISTS (SELECT 1 FROM psi_protokol_archive a "
            "        WHERE a.Measure_Protokol_ID = p.Measure_protokol_ID "
            "          AND a.N LIKE :n_partial)")
        params['n_partial'] = f"%{n_partial}%"

    where = " AND ".join(conds) if conds else "1=1"

    # ▼ Устойчиво к отсутствию колонки psi_type
    psi_type_expr = ("COALESCE(p.psi_type, 'ОТК')"
                     if _has_psi_type_column(engine) else "'ОТК'")

    sql_str = f"""
        SELECT p.Measure_protokol_ID, p.ProtokolN, p.MSK, p.Spc,
               p.dataR, p.Count AS Total_Count,
               {psi_type_expr} AS PsiType,
               p.Measure_ID,
               (SELECT COUNT(*) FROM psi_protokol_archive a2
                WHERE a2.Measure_Protokol_ID = p.Measure_protokol_ID)
                 AS Current_Count
        FROM psi_measure_protokol_id p
        WHERE {where}
        ORDER BY p.dataR DESC, p.Measure_protokol_ID DESC
        LIMIT {int(limit)}
    """

    try:
        stmt = text(sql_str)
        for name in expanding:
            stmt = stmt.bindparams(bindparam(name, expanding=True))
        df = pd.read_sql(stmt, engine, params=params)
        if 'PsiType' not in df.columns:
            df['PsiType'] = 'ОТК'
        else:
            df['PsiType'] = df['PsiType'].fillna('ОТК')
        return df
    except Exception as e:
        import traceback
        print(f"[Protocol_Data] Ошибка поиска: {e}")
        traceback.print_exc()
        return pd.DataFrame()
def search_archived_protocols_11(msk_partial: str = None,
                              n_partial: str = None,
                              *,
                              msk_exact: str = None,
                              spc: str = None,
                              rtype: str = None,
                              date: str = None,
                              file: str = None,
                              numbers: list = None,
                              limit: int = 500) -> pd.DataFrame:
    """Поиск протоколов в psi_measure_protokol_id.

    Каскадные фильтры (spc/rtype/msk_exact/date/file) — «И».
    Ввод пользователя (msk_partial / numbers) — приоритетный поиск:
    если они заданы, вызывающая сторона должна обнулить каскад
    (см. Protocol_UI._refresh_archive_list).

    Поиск по номерам:
      1) находим Measure_ID по номерам в psidata (прямой SQL);
      2) ищем протоколы по найденным Measure_ID;
      3) как fallback — EXISTS по psi_protokol_archive.N.
    """
    engine = _engine()
    conds, params = [], {}
    expanding = []

    # --- Каскадные фильтры ---
    if msk_exact:
        conds.append("p.MSK = :msk_exact")
        params['msk_exact'] = msk_exact
    if date:
        conds.append("DATE(p.dataR) = :date")
        params['date'] = date
    if file:
        conds.append("p.File LIKE :file")
        params['file'] = f"%{file}%"
    if spc:
        # Spc в psi_measure_protokol_id может быть Name или Text
        conds.append(
            "(p.Spc = :spc "
            " OR p.Spc IN (SELECT Text FROM specification WHERE Name = :spc))")
        params['spc'] = spc
    if rtype:
        conds.append(
            "p.Spc IN (SELECT Name FROM specification WHERE NameR = :rtype "
            "          UNION "
            "          SELECT Text FROM specification WHERE NameR = :rtype)")
        params['rtype'] = rtype

    # --- Ввод пользователя ---
    if msk_partial:
        conds.append("p.MSK LIKE :msk_partial")
        params['msk_partial'] = f"%{msk_partial}%"

    # --- Номера ---
    mid_from_psidata: set[int] = set()
    if numbers:
        nums_upper = [str(n).strip().upper() for n in numbers if str(n).strip()]
        if nums_upper:
            try:
                from sqlalchemy import bindparam as _bp
                sql_mids = text(
                    "SELECT DISTINCT Measure_ID FROM psidata "
                    "WHERE UPPER(TRIM(N)) IN :nums "
                    "  AND Measure_ID IS NOT NULL"
                ).bindparams(_bp("nums", expanding=True))
                df_mids = pd.read_sql(sql_mids, engine,
                                      params={'nums': nums_upper})
                if not df_mids.empty:
                    mid_from_psidata = {
                        int(x) for x in df_mids['Measure_ID'].dropna().unique()
                    }
            except Exception as e:
                print(f"[Protocol_Data] Поиск Measure_ID по номерам: {e}")

    if mid_from_psidata:
        conds.append(
            "(p.Measure_ID IN :mids "
            " OR EXISTS (SELECT 1 FROM psi_protokol_archive a "
            "            WHERE a.Measure_Protokol_ID = p.Measure_protokol_ID "
            "              AND a.N IN :nums))")
        params['mids'] = list(mid_from_psidata)
        params['nums'] = [str(n).strip().upper() for n in numbers]
        expanding.extend(['mids', 'nums'])
    elif numbers:
        conds.append(
            "EXISTS (SELECT 1 FROM psi_protokol_archive a "
            "        WHERE a.Measure_Protokol_ID = p.Measure_protokol_ID "
            "          AND a.N IN :nums)")
        params['nums'] = [str(n).strip().upper() for n in numbers]
        expanding.append('nums')
    elif n_partial:
        conds.append(
            "EXISTS (SELECT 1 FROM psi_protokol_archive a "
            "        WHERE a.Measure_Protokol_ID = p.Measure_protokol_ID "
            "          AND a.N LIKE :n_partial)")
        params['n_partial'] = f"%{n_partial}%"

    where = " AND ".join(conds) if conds else "1=1"

    sql_str = f"""
        SELECT p.Measure_protokol_ID, p.ProtokolN, p.MSK, p.Spc,
               p.dataR, p.Count AS Total_Count,
               COALESCE(p.psi_type, 'ОТК') AS PsiType,
               p.Measure_ID,
               (SELECT COUNT(*) FROM psi_protokol_archive a2
                WHERE a2.Measure_Protokol_ID = p.Measure_protokol_ID)
                 AS Current_Count
        FROM psi_measure_protokol_id p
        WHERE {where}
        ORDER BY p.dataR DESC, p.Measure_protokol_ID DESC
        LIMIT {int(limit)}
    """

    try:
        stmt = text(sql_str)
        for name in expanding:
            stmt = stmt.bindparams(bindparam(name, expanding=True))
        df = pd.read_sql(stmt, engine, params=params)
        if 'PsiType' in df.columns:
            df['PsiType'] = df['PsiType'].fillna('ОТК')
        else:
            df['PsiType'] = 'ОТК'
        return df
    except Exception as e:
        import traceback
        print(f"[Protocol_Data] Ошибка поиска: {e}")
        traceback.print_exc()
        return pd.DataFrame()

def _has_psi_type_column(engine) -> bool:
    try:
        with engine.connect() as conn:
            n = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "  AND TABLE_NAME = 'psi_measure_protokol_id' "
                "  AND COLUMN_NAME = 'psi_type'"
            )).scalar()
        return bool(n)
    except Exception:
        return False

def get_protocol_by_id(protokol_id: int) -> dict | None:
    """Заголовок протокола по ID."""
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT * FROM psi_measure_protokol_id "
                 "WHERE Measure_protokol_ID = :pid"),
            engine, params={'pid': int(protokol_id)})
        return None if df.empty else df.iloc[0].to_dict()
    except Exception as e:
        print(f"[Protocol_Data] Ошибка загрузки по ID: {e}")
        return None


def get_archive_protocol_data(protokol_id: int) -> pd.DataFrame:
    """Полные записи архивного протокола (для таблицы просмотра)."""
    engine = _engine()
    try:
        return pd.read_sql(
            text("SELECT * FROM psi_protokol_archive "
                 "WHERE Measure_Protokol_ID = :pid"),
            engine, params={'pid': int(protokol_id)})
    except Exception as e:
        print(f"[Protocol_Data] Ошибка загрузки данных протокола: {e}")
        return pd.DataFrame()


# ============================================================================
# Каскад для поиска протоколов (только по тем, что есть в psi_measure_protokol_id)
# ============================================================================
def get_protocol_types() -> list[str]:
    """Типы резонаторов, у которых есть сохранённый протокол.

    В psi_measure_protokol_id.Spc может лежать как Name (ключ), так и
    Text (человекочитаемое) — проверяем оба.
    """
    engine = _engine()
    try:
        df = pd.read_sql(
            "SELECT DISTINCT s.NameR FROM specification s "
            "WHERE s.NameR IS NOT NULL "
            "  AND (s.Name IN (SELECT Spc FROM psi_measure_protokol_id) "
            "    OR s.Text IN (SELECT Spc FROM psi_measure_protokol_id)) "
            "ORDER BY s.NameR", engine)
        return df['NameR'].dropna().tolist() if not df.empty else []
    except Exception as e:
        print(f"[Protocol_Data] Ошибка типов: {e}")
        return []


def get_protocol_specs_by_type(rtype: str) -> list[str]:
    """Спецификации типа rtype, у которых есть сохранённый протокол."""
    if not rtype:
        return []
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT DISTINCT s.Name FROM specification s "
                 "WHERE s.NameR = :rt "
                 "  AND (s.Name IN (SELECT Spc FROM psi_measure_protokol_id) "
                 "    OR s.Text IN (SELECT Spc FROM psi_measure_protokol_id)) "
                 "ORDER BY s.Name"),
            engine, params={'rt': rtype})
        return df['Name'].dropna().tolist() if not df.empty else []
    except Exception as e:
        print(f"[Protocol_Data] Ошибка спецификаций: {e}")
        return []


def resolve_spc_name(spc_val: str | None) -> str | None:
    """Приводит значение Spc (Name или Text) к Name из specification."""
    if not spc_val:
        return None
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT Name FROM specification WHERE Name = :v LIMIT 1"),
            engine, params={'v': spc_val})
        if not df.empty:
            return str(df.iloc[0]['Name'])
        df = pd.read_sql(
            text("SELECT Name FROM specification WHERE Text = :v LIMIT 1"),
            engine, params={'v': spc_val})
        if not df.empty:
            return str(df.iloc[0]['Name'])
    except Exception as e:
        print(f"[Protocol_Data] resolve_spc_name error: {e}")
    return None
def get_protocol_types_10() -> list[str]:
    """Типы резонаторов, у которых есть хотя бы один сохранённый протокол."""
    engine = _engine()
    try:
        df = pd.read_sql(
            "SELECT DISTINCT NameR FROM specification "
            "WHERE Name IN (SELECT DISTINCT Spc FROM psi_measure_protokol_id) "
            "  AND NameR IS NOT NULL "
            "ORDER BY NameR", engine)
        return df['NameR'].dropna().tolist() if not df.empty else []
    except Exception as e:
        print(f"[Protocol_Data] Ошибка типов: {e}")
        return []


def get_protocol_specs_by_type(rtype: str) -> list[str]:
    if not rtype:
        return []
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT DISTINCT Name FROM specification "
                 "WHERE NameR = :rt "
                 "  AND Name IN (SELECT DISTINCT Spc FROM psi_measure_protokol_id) "
                 "ORDER BY Name"),
            engine, params={'rt': rtype})
        return df['Name'].dropna().tolist() if not df.empty else []
    except Exception as e:
        print(f"[Protocol_Data] Ошибка спецификаций: {e}")
        return []

def get_protocol_msk_list(spc: str | None = None) -> list[str]:
    """Список МСК из psi_measure_protokol_id.

    spc — Name из specification; в таблице Spc может храниться как Name,
    так и Text → проверяем оба.
    """
    engine = _engine()
    try:
        if spc:
            df = pd.read_sql(
                text("SELECT DISTINCT MSK FROM psi_measure_protokol_id "
                     "WHERE MSK IS NOT NULL AND "
                     "      (Spc = :spc OR Spc IN "
                     "       (SELECT Text FROM specification WHERE Name = :spc)) "
                     "ORDER BY MSK"),
                engine, params={'spc': spc})
        else:
            df = pd.read_sql(
                "SELECT DISTINCT MSK FROM psi_measure_protokol_id "
                "WHERE MSK IS NOT NULL ORDER BY MSK", engine)
        return df['MSK'].dropna().tolist() if not df.empty else []
    except Exception as e:
        print(f"[Protocol_Data] Ошибка МСК: {e}")
        return []


def get_protocol_dates_list(spc: str | None = None,
                            msk: str | None = None) -> list[str]:
    """Даты протоколов (DATE(dataR)) с учётом Name-or-Text."""
    engine = _engine()
    conds, params = [], {}
    if spc:
        conds.append("(Spc = :spc OR Spc IN "
                     " (SELECT Text FROM specification WHERE Name = :spc))")
        params['spc'] = spc
    if msk:
        conds.append("MSK = :msk")
        params['msk'] = msk
    where = " AND ".join(conds) if conds else "1=1"
    try:
        df = pd.read_sql(
            text(f"SELECT DISTINCT DATE(dataR) AS d "
                 f"FROM psi_measure_protokol_id "
                 f"WHERE {where} AND dataR IS NOT NULL "
                 f"ORDER BY d DESC"),
            engine, params=params)
        return [str(x) for x in df['d'].dropna().tolist()] \
            if not df.empty else []
    except Exception as e:
        print(f"[Protocol_Data] Ошибка дат: {e}")
        return []


def get_protocol_files_list(spc: str | None = None,
                            msk: str | None = None,
                            date: str | None = None) -> list[str]:
    """Список файлов (File) с учётом Name-or-Text."""
    engine = _engine()
    conds, params = [], {}
    if spc:
        conds.append("(Spc = :spc OR Spc IN "
                     " (SELECT Text FROM specification WHERE Name = :spc))")
        params['spc'] = spc
    if msk:
        conds.append("MSK = :msk")
        params['msk'] = msk
    if date:
        conds.append("DATE(dataR) = :date")
        params['date'] = date
    where = " AND ".join(conds) if conds else "1=1"
    try:
        df = pd.read_sql(
            text(f"SELECT DISTINCT File FROM psi_measure_protokol_id "
                 f"WHERE {where} AND File IS NOT NULL "
                 f"ORDER BY File"),
            engine, params=params)
        return df['File'].dropna().tolist() if not df.empty else []
    except Exception as e:
        print(f"[Protocol_Data] Ошибка файлов: {e}")
        return []
def get_protocol_msk_list_10(spc: str | None = None) -> list[str]:
    engine = _engine()
    try:
        if spc:
            df = pd.read_sql(
                text("SELECT DISTINCT MSK FROM psi_measure_protokol_id "
                     "WHERE Spc = :spc AND MSK IS NOT NULL "
                     "ORDER BY MSK"),
                engine, params={'spc': spc})
        else:
            df = pd.read_sql(
                "SELECT DISTINCT MSK FROM psi_measure_protokol_id "
                "WHERE MSK IS NOT NULL ORDER BY MSK", engine)
        return df['MSK'].dropna().tolist() if not df.empty else []
    except Exception as e:
        print(f"[Protocol_Data] Ошибка МСК: {e}")
        return []


def get_protocol_dates_list(spc: str | None = None,
                            msk: str | None = None) -> list[str]:
    engine = _engine()
    conds, params = [], {}
    if spc:
        conds.append("Spc = :spc")
        params['spc'] = spc
    if msk:
        conds.append("MSK = :msk")
        params['msk'] = msk
    where = " AND ".join(conds) if conds else "1=1"
    try:
        df = pd.read_sql(
            text(f"SELECT DISTINCT DATE(dataR) AS d "
                 f"FROM psi_measure_protokol_id "
                 f"WHERE {where} AND dataR IS NOT NULL "
                 f"ORDER BY d DESC"),
            engine, params=params)
        return [str(x) for x in df['d'].dropna().tolist()] \
            if not df.empty else []
    except Exception as e:
        print(f"[Protocol_Data] Ошибка дат: {e}")
        return []


def get_protocol_files_list(spc: str | None = None,
                            msk: str | None = None,
                            date: str | None = None) -> list[str]:
    engine = _engine()
    conds, params = [], {}
    if spc:
        conds.append("Spc = :spc")
        params['spc'] = spc
    if msk:
        conds.append("MSK = :msk")
        params['msk'] = msk
    if date:
        conds.append("DATE(dataR) = :date")
        params['date'] = date
    where = " AND ".join(conds) if conds else "1=1"
    try:
        df = pd.read_sql(
            text(f"SELECT DISTINCT File FROM psi_measure_protokol_id "
                 f"WHERE {where} AND File IS NOT NULL ORDER BY File"),
            engine, params=params)
        return df['File'].dropna().tolist() if not df.empty else []
    except Exception as e:
        print(f"[Protocol_Data] Ошибка файлов: {e}")
        return []

def get_archive_protocol_numbers(protokol_id: int) -> pd.DataFrame:
    engine = _engine()
    sql = text("SELECT N FROM psi_protokol_archive WHERE Measure_Protokol_ID = :pid")
    try:
        return pd.read_sql(sql, engine, params={'pid': protokol_id})
    except Exception as e:
        print(f"[Protocol_Data] Ошибка загрузки номеров: {e}")
        return pd.DataFrame()


def is_number_good_for_protocol(measure_id: int, n_val: str, psi_type: str) -> bool:
    """Проверяет, проходит ли номер резонатора по нормам (ПСИ или ОТК)."""
    from Archive_View.Archive_Data import (
        rename_fields_to_parameters, load_specification,
        resolve_param_column, _prepare_spc_map
    )
    from Archive_View.Archive_UI import _load_spc_map_for_display
    from Archive_View.Archive_Data import build_presentation_params, load_tu_parameters_for_spec

    engine = _engine()
    # Загружаем строку из psidata
    df_row = pd.read_sql(text("SELECT * FROM psidata WHERE Measure_ID = :mid AND N = :n"), engine,
                         params={'mid': measure_id, 'n': n_val})
    if df_row.empty:
        return False

    spc_name = df_row.iloc[0].get('Spc')
    if not spc_name: return False

    spc_df = load_specification(spc_name)
    if spc_df.empty: return False
    spc_row = spc_df.iloc[0]

    from .Presentation_Cache import get_or_build_presentation_params
    tu_data = load_tu_parameters_for_spec(spc_name)
    presentation_params = get_or_build_presentation_params(spc_name, tu_data)

    spc_map = _load_spc_map_for_display(spc_name, psi_type)
    if psi_type == 'ОТК':
        spc_map = _prepare_spc_map(spc_map)

    mapped = rename_fields_to_parameters(df_row)

    for p in presentation_params:
        if not p['has_norm']: continue
        col = resolve_param_column(mapped, p['param'])
        if col is None: continue
        vals = pd.to_numeric(mapped[col], errors='coerce')
        if p['has_max'] and p['max_otk'] is not None and not pd.isna(p['max_otk']):
            if not (vals <= float(p['max_otk'])).all(): return False
        if p['has_min'] and p['min_otk'] is not None and not pd.isna(p['min_otk']):
            if not (vals >= float(p['min_otk'])).all(): return False
        if vals.isna().any(): return False

    return True


def add_numbers_to_protocol(protokol_id: int, measure_id: int,
                            numbers: list[str], psi_type: str) -> list[str]:
    if not numbers:
        return []

    engine = _engine()
    sql_src = text(
        "SELECT * FROM psidata WHERE Measure_ID = :mid AND N IN :nums"
    ).bindparams(bindparam("nums", expanding=True))

    try:
        with engine.connect() as conn:
            df = pd.read_sql(sql_src, conn,
                             params={'mid': measure_id, 'nums': numbers})
    except Exception as e:
        print(f"[Protocol_Data] Ошибка чтения psidata: {e}")
        return []
    if df is None or df.empty:
        return []

    # --- Один раз: спецификация / ТУ / presentation_params / spc_map ---
    spc_name = None
    if 'Spc' in df.columns:
        try:
            v = df.iloc[0].get('Spc')
            if v is not None and not pd.isna(v):
                spc_name = str(v).strip() or None
        except (TypeError, ValueError):
            spc_name = None
    if not spc_name:
        return []

    from Archive_View.Archive_Data import (
        rename_fields_to_parameters, resolve_param_column,
        _prepare_spc_map,
    )
    from Archive_View.Archive_UI import _load_spc_map_for_display
    from .Presentation_Cache import get_or_build_presentation_params
    from Archive_View.Archive_Data import load_tu_parameters_for_spec

    tu_data = load_tu_parameters_for_spec(spc_name) or {}
    pres_params = get_or_build_presentation_params(spc_name, tu_data)
    spc_map = _load_spc_map_for_display(spc_name, psi_type)
    if psi_type == 'ОТК':
        spc_map = _prepare_spc_map(spc_map)

    mapped = rename_fields_to_parameters(df)
    good_mask = pd.Series(True, index=mapped.index)
    for p in pres_params:
        if not p.get('has_norm'):
            continue
        col = resolve_param_column(mapped, p['param'])
        if col is None:
            continue
        vals = pd.to_numeric(mapped[col], errors='coerce')
        if p.get('has_max') and p['max_otk'] is not None:
            good_mask &= (vals <= float(p['max_otk']))
        if p.get('has_min') and p['min_otk'] is not None:
            good_mask &= (vals >= float(p['min_otk']))
        good_mask &= vals.notna()

    df_good = df[good_mask].copy()
    if df_good.empty:
        return []

    df_good = df_good.drop(columns=[c for c in ('ID',) if c in df_good.columns],
                           errors='ignore')
    df_good['Measure_Protokol_ID'] = protokol_id
    df_good['Measure_ID'] = measure_id

    try:
        _insert_df_ignore(engine, 'psi_protokol_archive', df_good)
    except Exception as e:
        print(f"[Protocol_Data] Ошибка вставки: {e}")
        return []

    return [str(x) for x in df_good['N'].dropna().tolist()]

def remove_numbers_from_protocol(protokol_id: int, numbers: list[str]):
    engine = _engine()
    if not numbers: return
    sql = text("DELETE FROM psi_protokol_archive WHERE Measure_Protokol_ID = :pid AND N IN :nums").bindparams(
        bindparam("nums", expanding=True))
    try:
        with engine.begin() as conn:
            conn.execute(sql, {'pid': protokol_id, 'nums': numbers})
    except Exception as e:
        print(f"[Protocol_Data] Ошибка удаления номеров: {e}")


def delete_protocol_completely(protokol_id: int):
    engine = _engine()
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM psi_protokol_archive WHERE Measure_Protokol_ID = :pid"),
                         {'pid': protokol_id})
            conn.execute(text("DELETE FROM psi_measure_protokol_id WHERE Measure_protokol_ID = :pid"),
                         {'pid': protokol_id})
    except Exception as e:
        print(f"[Protocol_Data] Ошибка удаления протокола: {e}")

def log_action(action: str, protokol_id, measure_id,
               details: str, operator: str):
    """Лог действия. Приводит id к встроенным int — иначе mysql-драйвер
    падает на numpy.int64 ('Python type numpy.int64 cannot be converted')."""
    def _to_int(v):
        if v is None:
            return None
        try:
            if pd.isna(v):          # numpy.nan / pd.NA
                return None
        except (TypeError, ValueError):
            pass
        try:
            return int(v)
        except (TypeError, ValueError):
            return None

    engine = _engine()
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS `psi_protokol_actions_log` (
                    `id` INT AUTO_INCREMENT PRIMARY KEY,
                    `action` VARCHAR(50),
                    `protokol_id` INT,
                    `measure_id` INT,
                    `details` TEXT,
                    `operator` VARCHAR(100),
                    `created_at` DATETIME
                )
            """))
            conn.execute(text("""
                INSERT INTO `psi_protokol_actions_log`
                    (action, protokol_id, measure_id, details, operator, created_at)
                VALUES (:act, :pid, :mid, :det, :op, :dt)
            """), {
                'act': str(action) if action is not None else None,
                'pid': _to_int(protokol_id),
                'mid': _to_int(measure_id),
                'det': str(details) if details is not None else None,
                'op':  str(operator) if operator is not None else None,
                'dt':  datetime.now(),
            })
    except Exception as e:
        print(f"[Protocol_Data] Ошибка логирования: {e}")



# ============================================================================
# Заказ / Договор / Контрагент  и  Даты изготовления/перепроверки
# ============================================================================
# ============================================================================
# Гарантированное создание колонок заказа/дат
# ============================================================================
def ensure_order_columns() -> set:
    """Создаёт в psi_measure_protokol_id колонки заказа/дат, если их нет.
    Возвращает множество существующих колонок.
    Использует отдельное autocommit-соединение для DDL (MySQL)."""
    engine = _engine()
    wanted = [
        ('LotNumber', 'VARCHAR(100)'),
        ('Dogovor',   'VARCHAR(255)'),
        ('Customer',  'VARCHAR(255)'),
        ('MakeDate',  'VARCHAR(50)'),
        ('MakeDate1', 'VARCHAR(50)'),
    ]

    # 1. Читаем текущий список колонок
    existing = set()
    try:
        with engine.connect() as conn:
            df = pd.read_sql(
                text("SELECT COLUMN_NAME FROM information_schema.COLUMNS "
                     "WHERE TABLE_SCHEMA = DATABASE() "
                     "  AND TABLE_NAME = 'psi_measure_protokol_id'"),
                conn)
            if df is not None and not df.empty:
                existing = {str(x) for x in df['COLUMN_NAME'].dropna()}
    except Exception as e:
        print(f"[Protocol_Data] ensure_order_columns check error: {e}")
        return existing

    # 2. Добавляем недостающие через AUTOCOMMIT
    missing = [(c, t) for c, t in wanted if c not in existing]
    for col, typ in missing:
        try:
            with engine.connect().execution_options(
                    isolation_level="AUTOCOMMIT") as conn:
                conn.execute(text(
                    f"ALTER TABLE `psi_measure_protokol_id` "
                    f"ADD COLUMN `{col}` {typ} NULL"
                ))
            existing.add(col)
            print(f"[Protocol_Data] ALTER ADD `{col}` {typ} - OK")
        except Exception as e:
            print(f"[Protocol_Data] ALTER ADD `{col}` failed: {e}")

    print(f"[Protocol_Data] ensure_order_columns: {sorted(existing)}")
    return existing


# ============================================================================
# Сохранение заказа (проверяем, что строка реально обновилась)
# ============================================================================
def save_order_info(protokol_id: int, lot_number: str,
                    dogovor: str, customer: str) -> None:
    if not protokol_id:
        raise ValueError("Не передан Measure_protokol_ID")

    ensure_order_columns()
    engine = _engine()
    with engine.begin() as conn:
        res = conn.execute(text("""
            UPDATE `psi_measure_protokol_id`
               SET `LotNumber` = :ln,
                   `Dogovor`   = :dg,
                   `Customer`  = :cs
             WHERE `Measure_protokol_ID` = :pid
        """), {
            'ln': (lot_number or '').strip() or None,
            'dg': (dogovor or '').strip() or None,
            'cs': (customer or '').strip() or None,
            'pid': int(protokol_id),
        })
        if (res.rowcount or 0) == 0:
            raise RuntimeError(
                f"UPDATE не затронул ни одной строки для "
                f"Measure_protokol_ID={protokol_id}. "
                f"Возможно, протокол не существует в таблице.")
    print(f"[Protocol_Data] save_order_info OK: pid={protokol_id}, "
          f"lot='{lot_number}', dogovor='{dogovor}', "
          f"customer='{customer}'")


# ============================================================================
# Данные заказа из заголовка
# ============================================================================
def get_protocol_order_info(protokol_id: int) -> dict:
    header = get_protocol_by_id(protokol_id) or {}
    return {
        'LotNumber': str(header.get('LotNumber') or ''),
        'Dogovor':   str(header.get('Dogovor')   or ''),
        'Customer':  str(header.get('Customer')  or ''),
        'MakeDate':  str(header.get('MakeDate')  or ''),
        'MakeDate1': str(header.get('MakeDate1') or ''),
        'Spc':       str(header.get('Spc')       or ''),
    }


# ============================================================================
# Отправка в LotRK (детальные сообщения об ошибках на каждом шаге)
# ============================================================================
def send_to_lot_rk(protokol_id: int) -> tuple[bool, str]:
    print(f"[Protocol_Data] send_to_lot_rk: pid={protokol_id}")

    header = get_protocol_by_id(protokol_id)
    if not header:
        return False, "Протокол не найден в БД"

    lot = str(header.get('LotNumber') or '').strip()
    print(f"[Protocol_Data] header LotNumber='{lot}'")
    if not lot:
        return False, ("Не заполнен номер заказа в протоколе. "
                       "Откройте [Данные заказа] и сохраните заказ.")

    spc_hdr = str(header.get('Spc') or '').strip()
    if not spc_hdr:
        return False, "В протоколе не указана спецификация (Spc)"

    # 1. Номенклатура (name -> full_name из nomeklatura_rk)
    nom_rq = get_nomenclature_rq(spc_hdr)
    if not nom_rq:
        return False, (f"Номенклатура '{spc_hdr}' не найдена в "
                       f"таблице [nomeklatura_rk]. "
                       f"Сначала заведите номенклатуру.")
    spc_full = nom_rq['full_name']
    print(f"[Protocol_Data] resolved spc_full='{spc_full}'")

    # 2. Извещение (Code/Customer)
    lot_info = get_lot_info(lot, spc_full)
    if not lot_info:
        return False, (f"Заказ '{lot}' не найден в [Извещение] для "
                       f"спецификации '{spc_full}'. "
                       f"Проверьте номер заказа и спецификацию.")
    print(f"[Protocol_Data] lot_info: code='{lot_info['code']}', "
          f"customer='{lot_info['customer']}'")

    # 3. Номера из архива
    df = get_archive_protocol_data(protokol_id)
    if df is None or df.empty:
        return False, "В протоколе нет ни одного номера"
    numbers = [str(x) for x in df['N'].dropna().tolist()]
    if not numbers:
        return False, "В протоколе нет корректных номеров"

    numbers_str = ', '.join(numbers)
    if len(numbers_str) > 65000:
        return False, "Слишком много номеров для одной записи LotRK"

    # 4. Вставка
    try:
        insert_lot_rk(
            lot=lot,
            lot_code=lot_info['code'],
            numbers_str=numbers_str,
            customer=lot_info['customer'],
            nomeklature=spc_full,
            count=len(numbers),
            date_str=datetime.now().strftime('%d-%m-%Y'),
        )
    except Exception as e:
        return False, f"Ошибка записи в LotRK: {e}"

    print(f"[Protocol_Data] insert LotRK OK: {len(numbers)} номеров")
    return True, (f"Отправлено {len(numbers)} номеров в LotRK "
                  f"(заказ {lot})")
def ensure_order_columns_14():
    """Добавляет колонки LotNumber/Dogovor/Customer/MakeDate/MakeDate1
    в psi_measure_protokol_id, если их ещё нет."""
    engine = _engine()
    cols = [
        ('LotNumber', 'VARCHAR(100)'),
        ('Dogovor',   'VARCHAR(255)'),
        ('Customer',  'VARCHAR(255)'),
        ('MakeDate',  'VARCHAR(50)'),
        ('MakeDate1', 'VARCHAR(50)'),
    ]
    with engine.begin() as conn:
        for col, typ in cols:
            try:
                conn.execute(text(
                    f"ALTER TABLE `psi_measure_protokol_id` "
                    f"ADD COLUMN `{col}` {typ}"
                ))
            except Exception:
                pass  # колонка уже есть


def save_order_info_14(protokol_id: int, lot_number: str,
                    dogovor: str, customer: str) -> None:
    """Сохраняет номер заказа/договор/контрагента в заголовок протокола."""
    if not protokol_id:
        return
    ensure_order_columns()
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(text("""
            UPDATE `psi_measure_protokol_id`
               SET `LotNumber` = :ln,
                   `Dogovor`   = :dg,
                   `Customer`  = :cs
             WHERE `Measure_protokol_ID` = :pid
        """), {
            'ln': (lot_number or '').strip() or None,
            'dg': (dogovor or '').strip() or None,
            'cs': (customer or '').strip() or None,
            'pid': int(protokol_id),
        })


def save_make_dates(protokol_id: int,
                    make_date: str = None,
                    make_date1: str = None) -> None:
    """Сохраняет даты изготовления/перепроверки в заголовок протокола."""
    if not protokol_id:
        return
    ensure_order_columns()
    sets, params = [], {'pid': int(protokol_id)}
    if make_date is not None:
        sets.append("`MakeDate` = :md")
        params['md'] = (make_date or '').strip() or None
    if make_date1 is not None:
        sets.append("`MakeDate1` = :md1")
        params['md1'] = (make_date1 or '').strip() or None
    if not sets:
        return
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(
            text(f"UPDATE `psi_measure_protokol_id` "
                 f"SET {', '.join(sets)} "
                 f"WHERE `Measure_protokol_ID` = :pid"),
            params)


def update_psidata_make_dates(measure_id: int, numbers: list,
                              make_date: str = None,
                              make_date1: str = None) -> int:
    """Обновляет MakeDate / MakeDate1 в psidata для указанных номеров.
    Возвращает число обновлённых строк."""
    if not measure_id or not numbers:
        return 0
    sets, params = [], {
        'mid':  int(measure_id),
        'nums': [str(n) for n in numbers],
    }
    if make_date is not None:
        sets.append("`MakeDate` = :md")
        params['md'] = (make_date or '').strip() or None
    if make_date1 is not None:
        sets.append("`MakeDate1` = :md1")
        params['md1'] = (make_date1 or '').strip() or None
    if not sets:
        return 0
    sql = text(
        f"UPDATE psidata SET {', '.join(sets)} "
        f"WHERE Measure_ID = :mid AND N IN :nums"
    ).bindparams(bindparam("nums", expanding=True))
    engine = _engine()
    with engine.begin() as conn:
        res = conn.execute(sql, params)
        return int(res.rowcount or 0)


# ============================================================================
# Отправка данных в LotRK
# ============================================================================

def get_lot_info(lot_number: str, spc_full: str) -> dict | None:
    """Code/Customer из таблицы Извещение по паре (Name, Spc)."""
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT `Code`,`Customer` FROM `Извещение` "
                 "WHERE `Name` = :n AND `Spc` = :s LIMIT 1"),
            engine, params={'n': lot_number, 's': spc_full})
        if df.empty:
            return None
        return {
            'code':     str(df.iloc[0]['Code'] or ''),
            'customer': str(df.iloc[0]['Customer'] or ''),
        }
    except Exception as e:
        print(f"[Protocol_Data] get_lot_info error: {e}")
        return None


def get_nomenclature_rq(spc_text: str) -> dict | None:
    """Номенклатура из nomeklatura_rk по наименованию."""
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT `номенклатура`,`наименование` FROM nomeklatura_rk "
                 "WHERE `наименование` = :s LIMIT 1"),
            engine, params={'s': spc_text})
        if df.empty:
            return None
        return {
            'nom_id':    str(df.iloc[0]['номенклатура'] or ''),
            'full_name': str(df.iloc[0]['наименование'] or ''),
        }
    except Exception as e:
        print(f"[Protocol_Data] get_nomenclature_rq error: {e}")
        return None


def insert_lot_rk(lot: str, lot_code: str, numbers_str: str,
                  customer: str, nomeklature: str,
                  count: int, date_str: str) -> None:
    """Вставка записи в LotRK (полный аналог Create_LOT_RQ из C++)."""
    engine = _engine()
    with engine.begin() as conn:
        conn.execute(text("""
            INSERT INTO `LotRK`
                (`Lot`,`LotCode`,`Numbers`,`Customer`,
                 `Nomeklature`,`Count`,`_Date`)
            VALUES
                (:lot, :code, :nums, :cust, :nom, :cnt, :dt)
        """), {
            'lot':  lot,
            'code': lot_code,
            'nums': numbers_str,
            'cust': customer,
            'nom':  nomeklature,
            'cnt':  int(count),
            'dt':   date_str,
        })

def send_to_lot_rk_14(protokol_id: int) -> tuple[bool, str]:
    """Отправка номеров протокола в LotRK (аналог Create_LOT_RQ)."""
    header = get_protocol_by_id(protokol_id)
    if not header:
        return False, "Протокол не найден в БД"

    lot = str(header.get('LotNumber') or '').strip()
    if not lot:
        return False, ("Не заполнен номер заказа. "
                       "Откройте [Данные заказа] и заполните.")

    spc_hdr = str(header.get('Spc') or '').strip()
    if not spc_hdr:
        return False, "В протоколе не указана спецификация"

    # 1. Разрешаем спецификацию через nomeklatura_rk (как в C++)
    nom_rq = get_nomenclature_rq(spc_hdr)
    if not nom_rq:
        return False, (f"Номенклатура '{spc_hdr}' не найдена в "
                       f"таблице [nomeklatura_rk]. "
                       f"Сначала заведите номенклатуру.")
    spc_full = nom_rq['full_name']

    # 2. Проверяем Извещение
    lot_info = get_lot_info(lot, spc_full)
    if not lot_info:
        return False, (f"Заказ '{lot}' не найден в [Извещение] "
                       f"для спецификации '{spc_full}'. "
                       f"Проверьте номер заказа и спецификацию.")

    # 3. Номера из архива
    df = get_archive_protocol_data(protokol_id)
    if df is None or df.empty:
        return False, "В протоколе нет ни одного номера"
    numbers = [str(x) for x in df['N'].dropna().tolist()]
    if not numbers:
        return False, "В протоколе нет корректных номеров"

    numbers_str = ', '.join(numbers)
    if len(numbers_str) > 65000:
        return False, "Слишком много номеров для одной записи LotRK"

    try:
        insert_lot_rk(
            lot=lot,
            lot_code=lot_info['code'],
            numbers_str=numbers_str,
            customer=lot_info['customer'],
            nomeklature=spc_full,
            count=len(numbers),
            date_str=datetime.now().strftime('%d-%m-%Y'),
        )
    except Exception as e:
        return False, f"Ошибка записи в LotRK: {e}"

    return True, f"Отправлено {len(numbers)} номеров в LotRK (заказ {lot})"


def get_protocol_order_info_14(protokol_id: int) -> dict:
    """Возвращает поля заказа и дат из заголовка протокола."""
    header = get_protocol_by_id(protokol_id) or {}
    return {
        'LotNumber': header.get('LotNumber') or '',
        'Dogovor':   header.get('Dogovor') or '',
        'Customer':  header.get('Customer') or '',
        'MakeDate':  header.get('MakeDate') or '',
        'MakeDate1': header.get('MakeDate1') or '',
        'Spc':       header.get('Spc') or '',
    }
def send_to_lot_rk_10(protokol_id: int) -> tuple[bool, str]:
    """Пробует отправить номера протокола в LotRK.
    Возвращает (успех, сообщение об ошибке/успехе)."""
    header = get_protocol_by_id(protokol_id)
    if not header:
        return False, "Протокол не найден в БД"

    lot = str(header.get('LotNumber') or '').strip()
    if not lot:
        return False, ("Не заполнен номер заказа. "
                       "Откройте [Данные заказа] и заполните поле.")

    spc_full = str(header.get('Spc') or '').strip()
    if not spc_full:
        return False, "В протоколе не указана спецификация"

    # Проверяем, что заказ есть в Извещении
    lot_info = get_lot_info(lot, spc_full)
    if not lot_info:
        return False, (f"Заказ '{lot}' не найден в таблице [Извещение] "
                       f"для спецификации '{spc_full}'. "
                       f"Проверьте номер заказа и спецификацию.")

    # Номера из архива
    df = get_archive_protocol_data(protokol_id)
    if df is None or df.empty:
        return False, "В протоколе нет ни одного номера"
    numbers = [str(x) for x in df['N'].dropna().tolist()]
    if not numbers:
        return False, "В протоколе нет корректных номеров"

    # Номенклатура
    nom_rq = get_nomenclature_rq(spc_full)
    if not nom_rq:
        return False, (f"Номенклатура '{spc_full}' не найдена в "
                       f"таблице [nomeklatura_rk]. "
                       f"Сначала заведите номенклатуру.")

    numbers_str = ', '.join(numbers)
    if len(numbers_str) > 65000:
        return False, "Слишком много номеров для одной записи LotRK"

    try:
        insert_lot_rk(
            lot=lot,
            lot_code=lot_info['code'],
            numbers_str=numbers_str,
            customer=lot_info['customer'],
            nomeklature=spc_full,
            count=len(numbers),
            date_str=datetime.now().strftime('%d-%m-%Y'),
        )
    except Exception as e:
        return False, f"Ошибка записи в LotRK: {e}"

    return True, f"Отправлено {len(numbers)} номеров в LotRK (заказ {lot})"


def get_protocol_order_info_15(protokol_id: int) -> dict:
    """Возвращает {LotNumber, Dogovor, Customer, MakeDate, MakeDate1}."""
    header = get_protocol_by_id(protokol_id) or {}
    return {
        'LotNumber': header.get('LotNumber') or '',
        'Dogovor':   header.get('Dogovor') or '',
        'Customer':  header.get('Customer') or '',
        'MakeDate':  header.get('MakeDate') or '',
        'MakeDate1': header.get('MakeDate1') or '',
    }


# ============================================================================
# Каскад заказа: Номер заказа -> Номенклатура -> Дата заказа
# (аналог LotNumber / LotSpc / ZakazData_Combo из protokol.cpp)
# ============================================================================

def get_lot_numbers() -> list[str]:
    """Список номеров заказов с ОсталосьВыпуститьПоГрафику > 0."""
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT DISTINCT `ЗаказНомер` FROM `заказы1С_новые` "
                 "WHERE `ОсталосьВыпуститьПоГрафику` > 0 "
                 "ORDER BY `ЗаказНомер`"),
            engine)
        if df.empty:
            return []
        return [str(x) for x in df.iloc[:, 0].dropna().tolist()]
    except Exception as e:
        print(f"[Protocol_Data] get_lot_numbers error: {e}")
        return []


def get_lot_spc_list(lot_number: str) -> list[str]:
    """Список номенклатур для заказа (только позиции с остатком)."""
    if not lot_number:
        return []
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT DISTINCT `Номенклатура` FROM `заказы1С_новые` "
                 "WHERE `ЗаказНомер` = :lot "
                 "  AND `ОсталосьВыпуститьПоГрафику` > 0 "
                 "ORDER BY `Номенклатура`"),
            engine, params={'lot': lot_number})
        if df.empty:
            return []
        return [str(x) for x in df.iloc[:, 0].dropna().tolist()]
    except Exception as e:
        print(f"[Protocol_Data] get_lot_spc_list error: {e}")
        return []


def get_lot_msk_list(lot_number: str, spc_name: str) -> list[str]:
    """Доступные МСК для пары (заказ, номенклатура) через MSK_Join."""
    if not (lot_number and spc_name):
        return []
    nom = get_nomenclature_rq(spc_name)
    if not nom:
        return []
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT DISTINCT `Msk_Name` FROM `MSK_Join` "
                 "WHERE `MSK_NOM_ID` = :nom "
                 "  AND `Msk_Name` IS NOT NULL "
                 "ORDER BY `Msk_Name`"),
            engine, params={'nom': nom['nom_id']})
        if df.empty:
            return []
        return [str(x) for x in df.iloc[:, 0].dropna().tolist()]
    except Exception as e:
        print(f"[Protocol_Data] get_lot_msk_list error: {e}")
        return []


def get_lot_dates_list(lot_number: str, spc_name: str) -> list[str]:
    """Список дат заказа (ЗаказДата) для пары (заказ, номенклатура)."""
    if not (lot_number and spc_name):
        return []
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT DISTINCT `ЗаказДата` FROM `заказы1С_новые` "
                 "WHERE `ЗаказНомер` = :lot "
                 "  AND `Номенклатура` = :spc "
                 "  AND `ОсталосьВыпуститьПоГрафику` > 0 "
                 "ORDER BY `ЗаказДата` DESC"),
            engine, params={'lot': lot_number, 'spc': spc_name})
        if df.empty:
            return []
        return [str(x) for x in df.iloc[:, 0].dropna().tolist()]
    except Exception as e:
        print(f"[Protocol_Data] get_lot_dates_list error: {e}")
        return []


def get_lot_details(lot_number: str, spc_name: str,
                    lot_date: str) -> dict | None:
    """Детали заказа по (заказ, номенклатура, дата).

    Аналог ZakazData_ComboChange + GetCustomerExecute из protokol.cpp:
      customer   = ЗаказКонтрагент + ' ' + ГородКонтрагент
      contractor = ЗаказКонтрагент
      city       = ГородКонтрагент
      dogovor    = ДоговорКонтрагентаРодитель
      remainder  = ОсталосьВыпуститьПоГрафику
    """
    if not (lot_number and spc_name and lot_date):
        return None
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT `ЗаказКонтрагент`, `ГородКонтрагент`, "
                 "`ДоговорКонтрагентаРодитель`, "
                 "`ОсталосьВыпуститьПоГрафику` "
                 "FROM `заказы1С_новые` "
                 "WHERE `ЗаказНомер` = :lot "
                 "  AND `Номенклатура` = :spc "
                 "  AND `ЗаказДата` = :dt "
                 "LIMIT 1"),
            engine, params={'lot': lot_number,
                            'spc': spc_name,
                            'dt':  lot_date})
        if df.empty:
            return None
        r = df.iloc[0]
        cust1 = str(r.get('ЗаказКонтрагент') or '').strip()
        cust2 = str(r.get('ГородКонтрагент') or '').strip()
        customer = (cust1 + ' ' + cust2).strip()
        return {
            'customer':   customer,
            'contractor': cust1,
            'city':       cust2,
            'dogovor':    str(r.get('ДоговорКонтрагентаРодитель') or '').strip(),
            'remainder':  r.get('ОсталосьВыпуститьПоГрафику'),
        }
    except Exception as e:
        print(f"[Protocol_Data] get_lot_details error: {e}")
        return None


def resolve_spc_text(spc_val: str | None) -> str | None:
    """Приводит Spc (Name или Text) к Text из specification."""
    if not spc_val:
        return None
    engine = _engine()
    try:
        df = pd.read_sql(
            text("SELECT `Text` FROM specification WHERE `Text` = :v LIMIT 1"),
            engine, params={'v': spc_val})
        if not df.empty:
            return str(df.iloc[0]['Text'])
        df = pd.read_sql(
            text("SELECT `Text` FROM specification WHERE `Name` = :v LIMIT 1"),
            engine, params={'v': spc_val})
        if not df.empty:
            return str(df.iloc[0]['Text'])
    except Exception as e:
        print(f"[Protocol_Data] resolve_spc_text error: {e}")
    return None