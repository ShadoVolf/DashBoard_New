"""CRUD + журнал + корзина для температурных профилей."""
import json
import traceback

import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from Options import get_connection_string


# =====================================================================
# Буфер между окнами
# =====================================================================
class PROFILE:
    df = pd.DataFrame()
    save = False
    current_name = None

    @staticmethod
    def set_profile_value(df):
        PROFILE.df = df.copy() if df is not None else pd.DataFrame()

    @staticmethod
    def get_profile_value():
        return PROFILE.df

    @staticmethod
    def set_current_name(name):
        PROFILE.current_name = name

    @staticmethod
    def get_current_name():
        return PROFILE.current_name


def _engine():
    return create_engine(str(get_connection_string()))


# =====================================================================
# Пользователь (для журнала)
# =====================================================================
_current_user = "unknown"


def set_current_user(login: str):
    global _current_user
    _current_user = (login or "unknown").strip() or "unknown"


def get_current_user() -> str:
    return _current_user


# =====================================================================
# Журнал и корзина
# =====================================================================
_log_ready = False


def _ensure_log_tables():
    global _log_ready
    if _log_ready:
        return
    ddl_log = (
        "CREATE TABLE IF NOT EXISTS `temperatureprofile_log` ("
        "`ID` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
        "`Action` VARCHAR(20) NOT NULL,"
        "`ProfileName` VARCHAR(255) NOT NULL,"
        "`Changes` MEDIUMTEXT,"
        "`UserLogin` VARCHAR(255),"
        "`DateTime` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "PRIMARY KEY (`ID`),"
        "KEY `idx_name` (`ProfileName`),"
        "KEY `idx_dt` (`DateTime`)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    ddl_trash = (
        "CREATE TABLE IF NOT EXISTS `temperatureprofile_trash` ("
        "`ID` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
        "`ProfileName` VARCHAR(255) NOT NULL,"
        "`OriginalData` LONGTEXT NOT NULL,"
        "`DeletedBy` VARCHAR(255),"
        "`DeletedAt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "`RestoredAt` DATETIME NULL,"
        "`RestoredBy` VARCHAR(255),"
        "PRIMARY KEY (`ID`),"
        "KEY `idx_name` (`ProfileName`)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )
    eng = _engine()
    with eng.begin() as conn:
        conn.execute(text(ddl_log))
        conn.execute(text(ddl_trash))
    _log_ready = True


def _log(action: str, name: str, changes: str):
    _ensure_log_tables()
    try:
        eng = _engine()
        with eng.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO `temperatureprofile_log` "
                    "(`Action`, `ProfileName`, `Changes`, `UserLogin`) "
                    "VALUES (:a, :n, :c, :u)"
                ),
                {"a": action, "n": name, "c": changes or "", "u": _current_user},
            )
    except Exception as e:
        print(f"[TempProfile] log error: {e}")


# =====================================================================
# Чтение
# =====================================================================
def get_profile_names_list() -> list:
    try:
        eng = _engine()
        with eng.connect() as conn:
            result = conn.execute(text(
                "SELECT `Name` FROM `temperatureprofile` ORDER BY `Name`"
            ))
            return [row[0] for row in result]
    except Exception as e:
        print(f"[TempProfile] names error: {e}")
        return []


def get_profile_data(name: str) -> pd.DataFrame:
    eng = _engine()
    try:
        with eng.connect() as conn:
            return pd.read_sql_query(
                text(
                    "SELECT `N`, `Temperature`, `Name`, `Time` "
                    "FROM `profiledata` WHERE `Name` = :n ORDER BY `N`"
                ),
                conn, params={"n": name},
            )
    except Exception as e:
        print(f"[TempProfile] data error: {e}")
        return pd.DataFrame()


def get_profile_meta(name: str) -> dict:
    eng = _engine()
    try:
        with eng.connect() as conn:
            row = conn.execute(
                text(
                    "SELECT `ID`, `Name`, `Temperatures`, `code`, `IntervalName` "
                    "FROM `temperatureprofile` WHERE `Name` = :n"
                ),
                {"n": name},
            ).fetchone()
        return dict(row._mapping) if row else {}
    except Exception as e:
        print(f"[TempProfile] meta error: {e}")
        return {}


def get_all_profiles() -> pd.DataFrame:
    eng = _engine()
    try:
        with eng.connect() as conn:
            return pd.read_sql_query(
                text(
                    "SELECT `ID`, `Name`, `code`, `IntervalName`, `Temperatures` "
                    "FROM `temperatureprofile` ORDER BY `Name`"
                ),
                conn,
            )
    except Exception as e:
        print(f"[TempProfile] all error: {e}")
        return pd.DataFrame()


# =====================================================================
# Построение данных
# =====================================================================
def get_profile_list_by_interval(a, b, step) -> list:
    try:
        a = float(str(a).replace(",", "."))
        b = float(str(b).replace(",", "."))
        step = float(str(step).replace(",", "."))
    except (TypeError, ValueError):
        return []
    if step == 0 or a > b:
        return []
    return [round(float(x), 3) for x in np.arange(a, b + step / 2, step)]


def build_profile_df(points: list, name: str) -> pd.DataFrame:
    """points: [(Temperature, Time), ...]."""
    if not points:
        return pd.DataFrame(columns=["N", "Name", "Temperature", "Time"])
    return pd.DataFrame({
        "N": list(range(len(points))),
        "Name": [name] * len(points),
        "Temperature": [p[0] for p in points],
        "Time": [p[1] for p in points],
    })


def create_new_profile(temperature_list, time, name) -> pd.DataFrame:
    pts = [(t, time) for t in temperature_list]
    return build_profile_df(pts, name)


# =====================================================================
# CRUD
# =====================================================================
def _diff_profile(old_df: pd.DataFrame, new_df: pd.DataFrame) -> str:
    if old_df is None or old_df.empty:
        return f"создан профиль из {len(new_df)} точек" if new_df is not None and not new_df.empty else ""
    if new_df is None or new_df.empty:
        return "профиль очищен"
    old_pts = list(zip(old_df["Temperature"], old_df["Time"]))
    new_pts = list(zip(new_df["Temperature"], new_df["Time"]))
    lines = []
    if len(old_pts) != len(new_pts):
        lines.append(f"Количество точек: {len(old_pts)} → {len(new_pts)}")
    for i in range(min(len(old_pts), len(new_pts))):
        if old_pts[i] != new_pts[i]:
            lines.append(
                f"Точка {i}: T={old_pts[i][0]} t={old_pts[i][1]} → "
                f"T={new_pts[i][0]} t={new_pts[i][1]}"
            )
    return "\n".join(lines) if lines else ""


def save_profile(name: str, points: list, code: str = "",
                 interval_name: str = "") -> bool:
    """Создать новый или обновить существующий профиль."""
    if not name or not name.strip():
        print("[TempProfile] save: пустое имя")
        return False
    name = name.strip()
    if not points:
        print("[TempProfile] save: нет точек")
        return False

    _ensure_log_tables()
    eng = _engine()
    try:
        with eng.begin() as conn:
            row = conn.execute(
                text("SELECT `ID` FROM `temperatureprofile` WHERE `Name` = :n"),
                {"n": name},
            ).fetchone()
            exists = row is not None

            old_df = pd.DataFrame()
            if exists:
                old_df = pd.read_sql_query(
                    text(
                        "SELECT `N`, `Temperature`, `Name`, `Time` "
                        "FROM `profiledata` WHERE `Name` = :n ORDER BY `N`"
                    ),
                    conn, params={"n": name},
                )

            new_df = build_profile_df(points, name)
            temperatures_str = " ".join(str(p[0]) for p in points)

            if exists:
                conn.execute(
                    text(
                        "UPDATE `temperatureprofile` "
                        "SET `Temperatures` = :t, `code` = :c, `IntervalName` = :i "
                        "WHERE `Name` = :n"
                    ),
                    {"t": temperatures_str, "c": code or "",
                     "i": interval_name or "", "n": name},
                )
                conn.execute(text("DELETE FROM `profiledata` WHERE `Name` = :n"),
                             {"n": name})
                profile_id = row[0]
            else:
                conn.execute(
                    text(
                        "INSERT INTO `temperatureprofile` "
                        "(`Name`, `Temperatures`, `code`, `IntervalName`) "
                        "VALUES (:n, :t, :c, :i)"
                    ),
                    {"n": name, "t": temperatures_str,
                     "c": code or "", "i": interval_name or ""},
                )
                row = conn.execute(
                    text("SELECT `ID` FROM `temperatureprofile` WHERE `Name` = :n"),
                    {"n": name},
                ).fetchone()
                profile_id = row[0]

            new_df["ProfileIndex"] = profile_id
            new_df.to_sql("profiledata", conn, if_exists="append", index=False)

        if exists:
            diff = _diff_profile(old_df, new_df)
            _log("UPDATE", name, diff or "обновление без видимых изменений")
        else:
            _log("CREATE", name, f"Создан профиль из {len(points)} точек")

        PROFILE.set_current_name(name)
        PROFILE.set_profile_value(new_df)
        return True
    except Exception as e:
        print(f"[TempProfile] save error: {e}")
        traceback.print_exc()
        return False


def delete_profile(name: str) -> bool:
    if not name:
        return False
    _ensure_log_tables()
    eng = _engine()
    try:
        with eng.begin() as conn:
            row = conn.execute(
                text("SELECT * FROM `temperatureprofile` WHERE `Name` = :n"),
                {"n": name},
            ).fetchone()
            if row is None:
                print(f"[TempProfile] delete: '{name}' не найден")
                return False

            meta = dict(row._mapping)
            points_df = pd.read_sql_query(
                text(
                    "SELECT `N`, `Temperature`, `Name`, `Time` "
                    "FROM `profiledata` WHERE `Name` = :n ORDER BY `N`"
                ),
                conn, params={"n": name},
            )
            points = points_df[["N", "Temperature", "Time"]].to_dict("records")
            payload = json.dumps({"meta": meta, "points": points},
                                 ensure_ascii=False, default=str)

            conn.execute(
                text(
                    "INSERT INTO `temperatureprofile_trash` "
                    "(`ProfileName`, `OriginalData`, `DeletedBy`) "
                    "VALUES (:n, :d, :u)"
                ),
                {"n": name, "d": payload, "u": _current_user},
            )
            conn.execute(text("DELETE FROM `profiledata` WHERE `Name` = :n"),
                         {"n": name})
            conn.execute(text("DELETE FROM `temperatureprofile` WHERE `Name` = :n"),
                         {"n": name})

        _log("DELETE", name, f"Перемещён в корзину ({len(points)} точек)")
        if PROFILE.get_current_name() == name:
            PROFILE.set_current_name(None)
            PROFILE.set_profile_value(pd.DataFrame())
        return True
    except Exception as e:
        print(f"[TempProfile] delete error: {e}")
        traceback.print_exc()
        return False


def restore_profile(trash_id: int) -> bool:
    _ensure_log_tables()
    eng = _engine()
    try:
        with eng.begin() as conn:
            row = conn.execute(
                text("SELECT * FROM `temperatureprofile_trash` WHERE `ID` = :i"),
                {"i": trash_id},
            ).fetchone()
            if row is None:
                return False
            data = json.loads(row._mapping["OriginalData"])
            name = data["meta"]["Name"]

            if conn.execute(
                text("SELECT `ID` FROM `temperatureprofile` WHERE `Name` = :n"),
                {"n": name},
            ).fetchone():
                print(f"[TempProfile] restore: '{name}' уже существует")
                return False

            meta = data["meta"]
            conn.execute(
                text(
                    "INSERT INTO `temperatureprofile` "
                    "(`Name`, `Temperatures`, `code`, `IntervalName`) "
                    "VALUES (:n, :t, :c, :i)"
                ),
                {"n": name, "t": meta.get("Temperatures", ""),
                 "c": meta.get("code", ""), "i": meta.get("IntervalName", "")},
            )
            new_id = conn.execute(
                text("SELECT `ID` FROM `temperatureprofile` WHERE `Name` = :n"),
                {"n": name},
            ).fetchone()[0]

            for pt in data["points"]:
                conn.execute(
                    text(
                        "INSERT INTO `profiledata` "
                        "(`N`, `Temperature`, `Name`, `Time`, `ProfileIndex`) "
                        "VALUES (:n, :t, :nm, :tm, :pi)"
                    ),
                    {"n": pt["N"], "t": pt["Temperature"], "nm": name,
                     "tm": pt["Time"], "pi": new_id},
                )

            conn.execute(
                text(
                    "UPDATE `temperatureprofile_trash` "
                    "SET `RestoredAt` = CURRENT_TIMESTAMP, `RestoredBy` = :u "
                    "WHERE `ID` = :i"
                ),
                {"u": _current_user, "i": trash_id},
            )

        _log("RESTORE", name, "Восстановлен из корзины")
        return True
    except Exception as e:
        print(f"[TempProfile] restore error: {e}")
        return False


def list_trash() -> pd.DataFrame:
    _ensure_log_tables()
    try:
        eng = _engine()
        with eng.connect() as conn:
            return pd.read_sql_query(
                text(
                    "SELECT `ID`, `ProfileName`, `DeletedBy`, `DeletedAt`, `RestoredAt` "
                    "FROM `temperatureprofile_trash` "
                    "WHERE `RestoredAt` IS NULL ORDER BY `DeletedAt` DESC"
                ),
                conn,
            )
    except Exception as e:
        print(f"[TempProfile] trash error: {e}")
        return pd.DataFrame()


def get_profile_log(name: str = None, limit: int = 100) -> pd.DataFrame:
    _ensure_log_tables()
    try:
        eng = _engine()
        with eng.connect() as conn:
            if name:
                return pd.read_sql_query(
                    text(
                        "SELECT `ID`, `Action`, `ProfileName`, `Changes`, "
                        "`UserLogin`, `DateTime` "
                        "FROM `temperatureprofile_log` WHERE `ProfileName` = :n "
                        "ORDER BY `DateTime` DESC LIMIT :lim"
                    ),
                    conn, params={"n": name, "lim": limit},
                )
            return pd.read_sql_query(
                text(
                    "SELECT `ID`, `Action`, `ProfileName`, `Changes`, "
                    "`UserLogin`, `DateTime` "
                    "FROM `temperatureprofile_log` "
                    "ORDER BY `DateTime` DESC LIMIT :lim"
                ),
                conn, params={"lim": limit},
            )
    except Exception as e:
        print(f"[TempProfile] log error: {e}")
        return pd.DataFrame()


# =====================================================================
# Совместимость со старым API
# =====================================================================
def save_new_profile(profile: pd.DataFrame, code, Name) -> bool:
    if profile is None or profile.empty:
        return False
    name = str(profile.loc[0, "Name"])
    points = [(float(r["Temperature"]), float(r["Time"]))
              for _, r in profile.iterrows()]
    return save_profile(name, points, code, Name)