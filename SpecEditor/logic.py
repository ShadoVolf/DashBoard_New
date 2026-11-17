"""
Контроллер редактора спецификаций.
"""
from typing import Optional
from typing import Optional, Set
# Используем общий движок графового модуля
from ResonatorGraph import db
from ResonatorGraph.db import execute_raw
import json
from .constants import PARAM_GROUPS, TOLERANCE_GROUPS, TEMP_INTERVALS
# ---------------------------------------------------------------------------
# Текущий пользователь (устанавливается из UI после авторизации)
# ---------------------------------------------------------------------------
_current_user = "unknown"


def set_current_user(login: str) -> None:
    """Установить логин текущего пользователя для журнала."""
    global _current_user
    _current_user = (login or "unknown").strip() or "unknown"


def _user_login() -> str:
    return _current_user


def _fmt(value) -> str:
    """Короткое представление значения для журнала."""
    if value is None:
        return "NULL"
    return str(value)


def _diff(old: dict, new: dict) -> list[tuple]:
    """[(col, old, new), ...] для полей, у которых значение изменилось."""
    changed = []
    for col, nv in new.items():
        if col not in old:
            continue
        ov = old[col]
        try:
            if str(ov).strip() == str(nv).strip():
                continue
            if ov is not None and nv is not None:
                try:
                    if float(ov) == float(nv):
                        continue
                except (TypeError, ValueError):
                    pass
        except Exception:
            pass
        changed.append((col, ov, nv))
    return changed


class SpecEditorError(Exception):
    pass


class SpecEditorController:
    """
    CRUD по таблице `specification` + справочники для combo.
    """

    def __init__(self):
        self._cols: Optional[list] = None
        self._col_types: dict = {}
        self._log_ready = False
        self._spc_map_cache: Optional[list] = None      # кеш spc_map_table
        self._specs_cache: Optional[list] = None        # кеш списка спецификаций
        self._norm_cols_cache: Optional[Set[str]] = None
    # ------------------------------------------------------------------
    # Журнал и корзина
    # ------------------------------------------------------------------
    def _ensure_log_tables(self):
        """Создать таблицы журнала и корзины при первом обращении."""
        if self._log_ready:
            return
        ddl_log = (
            "CREATE TABLE IF NOT EXISTS `specification_log` ("
            "`ID` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
            "`Action` VARCHAR(20) NOT NULL,"
            "`SpecName` VARCHAR(255) NOT NULL,"
            "`Changes` MEDIUMTEXT,"
            "`UserLogin` VARCHAR(255),"
            "`DateTime` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "PRIMARY KEY (`ID`),"
            "KEY `idx_spec` (`SpecName`),"
            "KEY `idx_dt` (`DateTime`),"
            "KEY `idx_user` (`UserLogin`)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        ddl_trash = (
            "CREATE TABLE IF NOT EXISTS `specification_trash` ("
            "`ID` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,"
            "`SpecName` VARCHAR(255) NOT NULL,"
            "`OriginalData` LONGTEXT NOT NULL,"
            "`DeletedBy` VARCHAR(255),"
            "`DeletedAt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
            "`RestoredAt` DATETIME NULL,"
            "`RestoredBy` VARCHAR(255),"
            "PRIMARY KEY (`ID`),"
            "KEY `idx_spec` (`SpecName`),"
            "KEY `idx_del` (`DeletedAt`)"
            ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
        )
        try:
            execute_raw(ddl_log, {})
            execute_raw(ddl_trash, {})
            self._log_ready = True
        except Exception as e:
            print(f"[SpecEditor] _ensure_log_tables error: {e}")

    def set_current_user(self, login: str) -> None:
        set_current_user(login)

    def _log(self, action: str, spec_name: str, changes_text: str):
        """Записать строку в журнал действий."""
        self._ensure_log_tables()
        sql = (
            "INSERT INTO `specification_log` "
            "(`Action`, `SpecName`, `Changes`, `UserLogin`) "
            "VALUES (%(a)s, %(n)s, %(c)s, %(u)s)"
        )
        try:
            execute_raw(sql, {
                "a": action,
                "n": spec_name,
                "c": changes_text or "",
                "u": _user_login(),
            })
            print(f"[SpecEditor] log: {action} {spec_name} (user={_user_login()})")
        except Exception as e:
            print(f"[SpecEditor] _log error: {e}")

    # ------------------------------------------------------------------
    # Метаданные таблицы
    # ------------------------------------------------------------------
    def columns(self) -> list:
        """Список колонок таблицы specification (кэшируется)."""
        if self._cols is None:
            rows = db.fetchall("""
                SELECT COLUMN_NAME AS name,
                       DATA_TYPE   AS dtype,
                       COLUMN_TYPE AS ctype
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE()
                  AND TABLE_NAME   = 'specification'
                ORDER BY ORDINAL_POSITION
            """)
            self._cols = [r["name"] for r in rows]
            for r in rows:
                self._col_types[r["name"]] = {
                    "dtype": (r["dtype"] or "").lower(),
                    "ctype": (r["ctype"] or "").lower(),
                }
        return self._cols

    # ------------------------------------------------------------------
    # spc_map_table (кеш)
    # ------------------------------------------------------------------
    def _get_spc_map(self) -> list:
        """Содержимое spc_map_table (кешируется на всё время жизни контроллера)."""
        if self._spc_map_cache is None:
            try:
                raw = db.fetchall("SELECT * FROM `spc_map_table` ORDER BY `ID`")
                self._spc_map_cache = [dict(r) for r in raw]
            except Exception as e:
                print(f"[SpecEditor] _get_spc_map error: {e}")
                self._spc_map_cache = []
        return self._spc_map_cache

    # ------------------------------------------------------------------
    # Нормы спецификации (аналог Make_Measure.load_spc_map)
    # ------------------------------------------------------------------
    def get_spc_map_for_row(self, row: dict) -> list:
        """Сформировать список норм (Parameter / Max / Min / Code)
        для строки спецификации. Логика повторяет
        Temperature_Measure.Make_Measure.load_spc_map.
        """
        raw = self._get_spc_map()

        def _to_num(v):
            if v is None:
                return None
            if isinstance(v, bool):
                return 1.0 if v else 0.0
            if isinstance(v, (int, float)):
                return float(v)
            s = str(v).strip()
            if not s or s.lower() == "no":
                return None
            try:
                return float(s.replace(",", "."))
            except (TypeError, ValueError):
                return None

        result = []
        for spc_row in raw:
            use_col = (spc_row.get("Use") or "").strip()
            if not use_col:
                continue
            used = row.get(use_col)
            try:
                used_n = int(float(used)) if used is not None else 0
            except (TypeError, ValueError):
                used_n = 0
            if used_n != 1:
                continue

            param = (spc_row.get("Parameter_Name") or "").strip()
            if not param:
                continue

            max_col = (spc_row.get("Max") or "").strip()
            min_col = (spc_row.get("Min") or "").strip()
            code = spc_row.get("Code")
            try:
                code_str = str(int(code)) if code is not None else ""
            except (TypeError, ValueError):
                code_str = ""

            result.append({
                "Parameter": param,
                "Max": _to_num(row.get(max_col)) if max_col else None,
                "Min": _to_num(row.get(min_col)) if min_col else None,
                "Code": code_str,
            })

        result = [r for r in result
                  if r["Parameter"] not in ("Rsp0", "Rsp1", "Rsp2")]
        return result

    # ------------------------------------------------------------------
    # Карта допусков
    # ------------------------------------------------------------------
    def fetch_dopusk_map(self) -> list:
        """Карта допусков с человекочитаемыми метками из spc_map_table."""
        sql = (
            "SELECT d.*, m.`Note_mini` AS `Note_mini` "
            "FROM `spc_dopusk_map_table` d "
            "LEFT JOIN `spc_map_table` m "
            "       ON m.`Parameter_Name` = d.`Parameter` "
            "ORDER BY d.`ID`"
        )
        try:
            raw = db.fetchall(sql)
        except Exception as e:
            import traceback
            print("[SpecEditor] fetch_dopusk_map error:", e)
            traceback.print_exc()
            return []

        rows = [dict(r) for r in raw]

        groups: dict = {}
        order: list = []
        for r in rows:
            units = (r.get("Dopusk_units") or "").strip() or None
            pct = (r.get("Dopusk_%") or "").strip() or None
            key = (units, pct)
            if key not in groups:
                groups[key] = []
                order.append(key)

            label = (r.get("Note_mini") or "").strip()
            if not label:
                label = (r.get("Parameter") or "").strip()
            if label:
                groups[key].append(label)

        result = []
        for key in order:
            seen, uniq = set(), []
            for lbl in groups[key]:
                if lbl not in seen:
                    seen.add(lbl)
                    uniq.append(lbl)
            result.append((uniq, key[0], key[1]))

        extras = [
            (["Точность настройки ТГК"], None, "DopuskFtgk"),
            (["Сопротивление ТГК"], None, "DopuskRtgk"),
        ]
        existing_pct = {pct for _, _, pct in result if pct}
        for item in extras:
            _, _, pct = item
            if pct and pct not in existing_pct:
                result.append(item)
                existing_pct.add(pct)

        return result

    def fetch_tch_types(self) -> list:
        try:
            rows = db.fetchall("SELECT `Name` FROM `tch_measure_type` ORDER BY `Name`")
            return [r["Name"] for r in rows if r["Name"]]
        except Exception:
            return []

    def fetch_tch_approx_types(self) -> list:
        try:
            rows = db.fetchall("SELECT `Name` FROM `spc_approx_type` ORDER BY `Name`")
            return [r["Name"] for r in rows if r["Name"]]
        except Exception:
            return []

    def fetch_tch_interval_types(self) -> list:
        try:
            rows = db.fetchall("SELECT `Name` FROM `spc_interval_type` ORDER BY `Name`")
            return [r["Name"] for r in rows if r["Name"]]
        except Exception:
            return []

    def fetch_measure_modes(self) -> list:
        try:
            rows = db.fetchall(
                "SELECT `ModeName` FROM `measuremode` "
                "ORDER BY `ModeIndex`"
            )
            return [r["ModeName"] for r in rows if r["ModeName"]]
        except Exception:
            return []

    def column_type(self, col: str) -> str:
        """Вернуть 'str' | 'int' | 'float' | 'bool' | 'enum' для колонки."""
        info = self._col_types.get(col)
        if not info:
            return "str"
        dt, ct = info["dtype"], info["ctype"]
        if dt in ("tinyint",) and "(1)" in ct:
            return "bool"
        if dt in ("int", "smallint", "mediumint", "bigint", "tinyint"):
            return "int"
        if dt in ("float", "double", "decimal", "real", "numeric"):
            return "float"
        if dt in ("enum", "set"):
            import re
            m = re.findall(r"'([^']*)'", ct)
            return ("enum", m)
        return "str"

    # ------------------------------------------------------------------
    # Чтение списка (кеш + фильтр в Python)
    # ------------------------------------------------------------------
    def list_specs(self, search: str = "") -> list:
        if self._specs_cache is None:
            sql = ("SELECT `Name`, `NameR`, `Nominal`, `Profile`, `LoadType` "
                   "FROM `specification` ORDER BY `Name`")
            rows = db.fetchall(sql)
            self._specs_cache = [dict(r) for r in rows]
        if not search:
            return list(self._specs_cache)
        q = search.lower()
        return [
            r for r in self._specs_cache
            if q in str(r.get("Name") or "").lower()
            or q in str(r.get("NameR") or "").lower()
        ]

    def load_spec(self, name: str) -> dict:
        row = db.fetchone(
            "SELECT * FROM `specification` WHERE `Name` = :n",
            n=name,
        )
        if row is None:
            raise SpecEditorError(f"Спецификация '{name}' не найдена")
        return dict(row)

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------
    def _coerce(self, col: str, value):
        """Привести питоновское значение к виду, пригодному для SQL."""
        t = self.column_type(col)
        if isinstance(t, tuple):
            t = t[0]
        if t == "bool":
            return 1 if value else 0
        if t == "int":
            try:
                return int(value)
            except (TypeError, ValueError):
                return 0
        if t == "float":
            try:
                return float(value)
            except (TypeError, ValueError):
                return 0.0
        if value is None:
            return ""
        return str(value)

    # ------------------------------------------------------------------
    # Нормы: колонки, для которых пустое значение трактуется как "no"
    # ------------------------------------------------------------------
    def _norm_columns(self) -> Set[str]:
        """Множество колонок-норм (min/max/T параметров, допуски и т.п.).

        Для таких колонок при сохранении пустое значение заменяется
        строкой 'no' — признак «норма не задана». Это совместимо
        с логикой `get_spc_map_for_row`, где 'no' читается как None.
        """
        if self._norm_cols_cache is not None:
            return self._norm_cols_cache

        cols: set = set()

        # PARAM_GROUPS: (label, chk, min, max, T, t_label, section, block)
        for g in PARAM_GROUPS:
            if len(g) >= 5:
                if g[2]: cols.add(g[2])   # min
                if g[3]: cols.add(g[3])   # max
                if g[4]: cols.add(g[4])   # T

        # Температурные интервалы (начало/конец)
        for tb, te in TEMP_INTERVALS.values():
            if tb: cols.add(tb)
            if te: cols.add(te)

        # Допуски (статический список)
        for _, abs_col, pct_col in TOLERANCE_GROUPS:
            if abs_col: cols.add(abs_col)
            if pct_col: cols.add(pct_col)

        # Допуски из динамической карты БД
        try:
            for _, abs_col, pct_col in self.fetch_dopusk_map():
                if abs_col: cols.add(abs_col)
                if pct_col: cols.add(pct_col)
        except Exception as e:
            print(f"[SpecEditor] _norm_columns: dopusk map unavailable: {e}")
            return cols   # не кешируем — повторим позже

        # Дополнительные нормы (не перечисленные в PARAM_GROUPS)
        cols.update({
            # Радиус сферы
            "RsphereMin", "RsphereMax", "RsphereT",
            # Эквивалентное сопротивление
            "Rekv_min", "Rekv_max",
            # Интерполяционные нормы
            "Fmax_int_Min", "Fmax_int_Max",
            "Fmin_int_Min", "Fmin_int_Max",
            "Fint_Min", "Fint_Max",
        })

        # Нежелательные резонансы
        for i in (1, 2, 3):
            cols.update({
                f"Spur_F_{i}_Min", f"Spur_F_{i}_Max",
                f"Rsp{i}min", f"Rsp{i}max",
                f"Rsp{i}tBegin", f"Rsp{i}tEnd",
            })

        self._norm_cols_cache = cols
        return cols
    def save_spec(self, name: str, data: dict) -> None:
        cols = set(self.columns())
        skip = {"Name", "ID"}
        norm_cols = self._norm_columns()

        # --- Читаем старую строку для журнала изменений ---
        try:
            old_row = db.fetchone(
                "SELECT * FROM `specification` WHERE `Name` = :n",
                n=name,
            )
            old_data = dict(old_row) if old_row else {}
        except Exception:
            old_data = {}

        # --- Собираем SET-выражение ---
        sets = []
        params = {"_pk": name}
        idx = 0
        for col, val in data.items():
            if col in skip or col not in cols:
                continue
            pname = f"p{idx}"
            idx += 1

            # Пустая норма -> "no" (признак «норма не задана»).
            # Значение "no" (в любом регистре), введённое руками,
            # тоже нормализуем в нижний регистр.
            if col in norm_cols:
                s = "" if val is None else str(val).strip().lower()
                if s == "" or s == "no":
                    val = "no"

            sets.append(f"`{col}` = %({pname})s")
            params[pname] = self._coerce(col, val)

        if not sets:
            print(f"[SpecEditor] save_spec: нет полей для сохранения ({name})")
            return

        sql = (
            f"UPDATE `specification` SET {', '.join(sets)} "
            f"WHERE `Name` = %(_pk)s"
        )

        print(f"[SpecEditor] save_spec -> {name}: {len(sets)} полей")

        # --- Запись в БД ---
        try:
            execute_raw(sql, params)
            print(f"[SpecEditor] save_spec: OK ({name})")
        except Exception as e:
            print(f"[SpecEditor] save_spec: ERROR ({name}): {e}")
            raise SpecEditorError(f"Ошибка сохранения: {e}")

        # Сбрасываем кеш списка — при следующем list_specs подтянутся свежие данные
        self._specs_cache = None

        # --- Журнал изменений ---
        try:
            changes = _diff(old_data, {**data, "Name": name})
            if changes:
                text = "\n".join(
                    f"{col}: {_fmt(old)} -> {_fmt(new)}"
                    for col, old, new in changes
                )
                self._log("UPDATE", name, text)
            else:
                print(f"[SpecEditor] save_spec: изменений нет — журнал не пишем")
        except Exception as e:
            print(f"[SpecEditor] save_spec: ошибка журнала: {e}")

    def save_spec_1(self, name: str, data: dict) -> None:
        cols = set(self.columns())
        skip = {"Name", "ID"}

        try:
            old_row = db.fetchone(
                "SELECT * FROM `specification` WHERE `Name` = :n",
                n=name,
            )
            old_data = dict(old_row) if old_row else {}
        except Exception:
            old_data = {}

        sets = []
        params = {"_pk": name}
        idx = 0
        for col, val in data.items():
            if col in skip or col not in cols:
                continue
            pname = f"p{idx}"
            idx += 1
            sets.append(f"`{col}` = %({pname})s")
            params[pname] = self._coerce(col, val)

        if not sets:
            print(f"[SpecEditor] save_spec: нет полей для сохранения ({name})")
            return

        sql = (
            f"UPDATE `specification` SET {', '.join(sets)} "
            f"WHERE `Name` = %(_pk)s"
        )

        print(f"[SpecEditor] save_spec -> {name}: {len(sets)} полей")

        try:
            execute_raw(sql, params)
            print(f"[SpecEditor] save_spec: OK ({name})")
        except Exception as e:
            print(f"[SpecEditor] save_spec: ERROR ({name}): {e}")
            raise SpecEditorError(f"Ошибка сохранения: {e}")

        self._specs_cache = None

        try:
            changes = _diff(old_data, {**data, "Name": name})
            if changes:
                text = "\n".join(
                    f"{col}: {_fmt(old)} -> {_fmt(new)}"
                    for col, old, new in changes
                )
                self._log("UPDATE", name, text)
            else:
                print(f"[SpecEditor] save_spec: изменений нет — журнал не пишем")
        except Exception as e:
            print(f"[SpecEditor] save_spec: ошибка журнала: {e}")

    def create_spec(self, name: str, base_from: Optional[str] = None) -> None:
        """
        Создать новую спецификацию.

        Если указан base_from — все поля копируются из существующей спецификации,
        КРОМЕ:
          * Name — заменяется на новое имя;
          * ID   — автоинкрементный первичный ключ, всегда генерируется MySQL заново.

        Копирование ID — критическая ошибка: она приводила к тому, что копии
        имели тот же ID, что и родитель, и запрос
            SELECT * FROM specification WHERE ID = <родительский>
        возвращал сразу все копии → в обработку измерений попадали лишние
        спецификации.
        """
        if not name:
            raise SpecEditorError("Имя не может быть пустым")

        exists = db.fetchone(
            "SELECT `Name` FROM `specification` WHERE `Name` = :n",
            n=name,
        )
        if exists:
            raise SpecEditorError(f"Спецификация '{name}' уже существует")

        cols = set(self.columns())

        # Поля, которые НЕ копируются из источника:
        #   Name — задаётся пользователем;
        #   ID   — автоинкрементный ключ, должен генерироваться БД.
        skip_on_copy = {"Name", "ID"}

        data: dict = {}
        if base_from:
            src = db.fetchone(
                "SELECT * FROM `specification` WHERE `Name` = :n",
                n=base_from,
            )
            if src is None:
                raise SpecEditorError(f"Источник '{base_from}' не найден")
            data = {c: src.get(c) for c in cols if c not in skip_on_copy}

        data["Name"] = name

        # Собираем INSERT только по реально существующим колонкам
        cols_in = [c for c in data.keys() if c in cols]
        if not cols_in:
            raise SpecEditorError("Нет полей для вставки")

        col_list = ", ".join(f"`{c}`" for c in cols_in)
        placeholders = []
        params = {}
        for idx, col in enumerate(cols_in):
            pname = f"p{idx}"
            placeholders.append(f"%({pname})s")
            params[pname] = self._coerce(col, data[col])

        sql = (
            f"INSERT INTO `specification` ({col_list}) "
            f"VALUES ({', '.join(placeholders)})"
        )
        try:
            execute_raw(sql, params)
        except Exception as e:
            raise SpecEditorError(f"Ошибка создания: {e}")

        # Сбрасываем кеш списка — при следующем list_specs подтянется новая строка
        self._specs_cache = None

        self._log(
            "CREATE",
            name,
            f"Создана спецификация '{name}'"
            + (f" (копия '{base_from}')" if base_from else ""),
        )

    def create_spec_1(self, name: str, base_from: Optional[str] = None) -> None:
        if not name:
            raise SpecEditorError("Имя не может быть пустым")
        exists = db.fetchone(
            "SELECT `Name` FROM `specification` WHERE `Name` = :n",
            n=name,
        )
        if exists:
            raise SpecEditorError(f"Спецификация '{name}' уже существует")

        cols = set(self.columns())
        data = {}
        if base_from:
            src = db.fetchone(
                "SELECT * FROM `specification` WHERE `Name` = :n",
                n=base_from,
            )
            if src is None:
                raise SpecEditorError(f"Источник '{base_from}' не найден")
            data = {c: src.get(c) for c in cols if c != "Name"}
        data["Name"] = name

        cols_in = [c for c in data.keys() if c in cols]
        col_list = ", ".join(f"`{c}`" for c in cols_in)
        placeholders = []
        params = {}
        for idx, col in enumerate(cols_in):
            pname = f"p{idx}"
            placeholders.append(f"%({pname})s")
            params[pname] = self._coerce(col, data[col])

        sql = (
            f"INSERT INTO `specification` ({col_list}) "
            f"VALUES ({', '.join(placeholders)})"
        )
        try:
            execute_raw(sql, params)
        except Exception as e:
            raise SpecEditorError(f"Ошибка создания: {e}")

        self._specs_cache = None

        self._log(
            "CREATE",
            name,
            f"Создана спецификация '{name}'"
            + (f" (копия '{base_from}')" if base_from else ""),
        )

    def delete_spec(self, name: str) -> None:
        if not name:
            raise SpecEditorError("Не указано имя")
        self._ensure_log_tables()

        try:
            row = db.fetchone(
                "SELECT * FROM `specification` WHERE `Name` = :n",
                n=name,
            )
        except Exception as e:
            raise SpecEditorError(f"Ошибка чтения: {e}")
        if row is None:
            raise SpecEditorError(f"Спецификация '{name}' не найдена")

        original = dict(row)

        def _default(o):
            try:
                return str(o)
            except Exception:
                return None
        try:
            payload = json.dumps(original, ensure_ascii=False, default=_default)
        except Exception as e:
            raise SpecEditorError(f"Не удалось сериализовать: {e}")

        try:
            execute_raw(
                "INSERT INTO `specification_trash` "
                "(`SpecName`, `OriginalData`, `DeletedBy`) "
                "VALUES (%(n)s, %(d)s, %(u)s)",
                {"n": name, "d": payload, "u": _user_login()},
            )
        except Exception as e:
            raise SpecEditorError(f"Ошибка записи в корзину: {e}")

        try:
            execute_raw(
                "DELETE FROM `specification` WHERE `Name` = %(n)s",
                {"n": name},
            )
        except Exception as e:
            raise SpecEditorError(f"Ошибка удаления: {e}")

        self._specs_cache = None

        self._log("DELETE", name,
                  f"Спецификация '{name}' перемещена в корзину")
        print(f"[SpecEditor] delete_spec: OK ({name})")

    # ------------------------------------------------------------------
    # Справочники для combo
    # ------------------------------------------------------------------
    def fetch_resonator_types(self) -> list:
        rows = db.fetchall("SELECT `Type` FROM `resonatortype` ORDER BY `Type`")
        return [r["Type"] for r in rows if r["Type"]]

    def fetch_profiles(self) -> list:
        rows = db.fetchall(
            "SELECT `Name` FROM `temperatureprofile` ORDER BY `Name`"
        )
        return [r["Name"] for r in rows if r["Name"]]

    def fetch_korpus(self) -> list:
        try:
            rows = db.fetchall("SELECT `Korpus` FROM `korpus` ORDER BY `Korpus`")
            return [r["Korpus"] for r in rows if r["Korpus"]]
        except Exception:
            return []

    def fetch_nominal(self) -> list:
        try:
            rows = db.fetchall(
                "SELECT DISTINCT `наименование` FROM `nomeklatura_rk` "
                "ORDER BY `наименование`"
            )
            return [r["наименование"] for r in rows if r["наименование"]]
        except Exception:
            return []

    def fetch_tu(self) -> list:
        try:
            rows = db.fetchall("SELECT DISTINCT `TUNAME` FROM `tu` ORDER BY `TUNAME`")
            return [r["TUNAME"] for r in rows if r["TUNAME"]]
        except Exception:
            return []

    def fetch_print_types(self) -> list:
        try:
            rows = db.fetchall("SELECT `Name` FROM `print` ORDER BY `Name`")
            return [r["Name"] for r in rows if r["Name"]]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Пакетные операции для списка
    # ------------------------------------------------------------------
    def count_by_field(self, field: str, value) -> int:
        try:
            row = db.fetchone(
                f"SELECT COUNT(*) AS c FROM `specification` WHERE `{field}` = :v",
                v=value,
            )
            return int(row["c"]) if row else 0
        except Exception:
            return 0