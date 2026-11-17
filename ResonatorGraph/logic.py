"""
Бизнес-логика: выборки данных, подготовка серий, расчёт метрик.
"""
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from . import db
from .constants import (
    PARAM_BY_LABEL, COLORS, COLOR_POINTS, COLOR_APPROX,
    get_main_table, get_temps_table,
)
from .polynomial import (
    poly_fit, poly_val, monotonicity, extremes, jumps, inflection_point,
    gaussian_kde,
)


# ---------------------------------------------------------------------------
# Структуры
# ---------------------------------------------------------------------------
@dataclass
class Series:
    label: str
    xs: list
    ys: list
    color: tuple
    kind: str          # "line" | "scatter"


@dataclass
class GraphResult:
    series: list = field(default_factory=list)
    title: str = ""
    xlabel: str = "T, C"
    ylabel: str = ""
    meta: dict = field(default_factory=dict)


class GraphLogicError(Exception):
    pass


# ---------------------------------------------------------------------------
# Контроллер
# ---------------------------------------------------------------------------
class GraphController:

    def __init__(self):
        self.degree: int = 3
        self.T_ref: float = 25.0
        self.A: float = -60.0
        self.B: float = 150.0
        self.T_ref_tolerance: float = 5.0

        # Пользователь вручную задал границы / степень — не перезаписывать
        # автоматическими значениями из данных / спецификации.
        self.A_user_set: bool = False
        self.B_user_set: bool = False
        self.degree_user_set: bool = False

        self.rtype: Optional[str] = None
        self.spec: Optional[str] = None
        self.msk: Optional[str] = None
        self.number: Optional[str] = None
        self.param_label: str = "F (без нагрузки)"

        self.measure_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Справочники
    # ------------------------------------------------------------------
    def load_types(self) -> list:
        rows = db.fetchall("SELECT `Type` FROM `resonatortype` ORDER BY `Type`")
        return [r["Type"] for r in rows if r["Type"]]

    def load_specs(self, rtype: str) -> list:
        if not rtype:
            return []
        rows = db.fetchall(
            "SELECT `Name` FROM `specification` WHERE NameR = :t ORDER BY `Name`",
            t=rtype,
        )
        return [r["Name"] for r in rows if r["Name"]]

    def load_msks(self, spec: str) -> list:
        if not spec:
            return []
        table = get_main_table()
        rows = db.fetchall(
            f"SELECT DISTINCT `Msk` FROM `{table}` WHERE Spc = :s "
            f"AND `Msk` IS NOT NULL ORDER BY `Msk`",
            s=spec,
        )
        return [r["Msk"] for r in rows if r["Msk"]]

    def load_numbers(self, msk: Optional[str] = None) -> list:
        """Номера в текущем режиме (приоритет - measure_id)."""
        table = get_main_table()
        if self.measure_id:
            rows = db.fetchall(
                f"SELECT DISTINCT `N` FROM `{table}` WHERE Measure_ID = :m "
                f"AND `N` IS NOT NULL ORDER BY `N`",
                m=self.measure_id,
            )
            return [r["N"] for r in rows if r["N"]]
        if not msk:
            msk = self.msk
        if not msk:
            return []
        rows = db.fetchall(
            f"SELECT DISTINCT `N` FROM `{table}` WHERE Msk = :m "
            f"AND `N` IS NOT NULL ORDER BY `N`",
            m=msk,
        )
        return [r["N"] for r in rows if r["N"]]

    def load_temperature_bounds(self, msk: str, number: str):
        table = get_temps_table()
        if self.measure_id:
            row = db.fetchone(
                f"SELECT MIN(Temp) AS t0, MAX(Temp) AS t1 FROM `{table}` "
                f"WHERE Measure_ID = :m AND `N` = :n",
                m=self.measure_id, n=number,
            )
        else:
            row = db.fetchone(
                f"SELECT MIN(Temp) AS t0, MAX(Temp) AS t1 FROM `{table}` "
                f"WHERE Msk = :m AND `N` = :n",
                m=msk, n=number,
            )
        if row and row["t0"] is not None:
            return float(row["t0"]), float(row["t1"])
        return None, None

    def load_reference_temperature(self, spec: str):
        if not spec:
            return None
        row = db.fetchone(
            "SELECT `Tnastr` FROM `specification` WHERE `Name` = :s",
            s=spec,
        )
        if row and row["Tnastr"] not in (None, ""):
            try:
                return float(row["Tnastr"])
            except (TypeError, ValueError):
                return None
        return None

    def load_spec_defaults(self, spec: str):
        """
        Загружает значения по умолчанию из specification.

        Сейчас — только степень аппроксимирующего полинома (polinom).
        Пользовательское значение (введённое вручную) не перезаписывается.
        """
        if not spec:
            return
        try:
            row = db.fetchone(
                "SELECT `polinom` FROM `specification` WHERE `Name` = :s",
                s=spec,
            )
        except Exception as e:
            print(f"[Graphs] load_spec_defaults: {e}")
            return
        if not row:
            return
        polinom = row.get("polinom")
        if polinom is None or self.degree_user_set:
            return
        try:
            deg = int(polinom)
        except (TypeError, ValueError):
            return
        if deg > 0:
            self.degree = deg

    # ------------------------------------------------------------------
    # Загрузка по уникальному ключу (Measure_ID) / по МСК
    # ------------------------------------------------------------------
    def load_by_measure_id(self, measure_id: str):
        """Найти спецификацию, МСК, тип резонатора и номера по ID замера."""
        if not measure_id:
            return None

        table = get_main_table()
        row = db.fetchone(
            f"SELECT `Spc`,`Msk` FROM `{table}` WHERE Measure_ID = :m LIMIT 1",
            m=measure_id,
        )
        if not row:
            return None

        spc = row["Spc"]
        msk = row["Msk"]

        rtype = None
        if spc:
            srow = db.fetchone(
                "SELECT `NameR` FROM `specification` WHERE `Name` = :s",
                s=spc,
            )
            if srow:
                rtype = srow["NameR"]

        if spc:
            self.load_spec_defaults(spc)

        nrows = db.fetchall(
            f"SELECT DISTINCT `N` FROM `{table}` WHERE Measure_ID = :m "
            f"AND `N` IS NOT NULL ORDER BY `N`",
            m=measure_id,
        )
        numbers = [r["N"] for r in nrows if r["N"]]

        return {
            "measure_id": measure_id,
            "spc": spc,
            "msk": msk,
            "rtype": rtype,
            "numbers": numbers,
        }

    def load_by_msk(self, msk: str):
        """Найти спецификацию, тип резонатора и номера по МСК."""
        if not msk:
            return None

        table = get_main_table()
        row = db.fetchone(
            f"SELECT DISTINCT `Spc` FROM `{table}` WHERE Msk = :m LIMIT 1",
            m=msk,
        )
        if not row or not row["Spc"]:
            return None
        spc = row["Spc"]

        rtype = None
        srow = db.fetchone(
            "SELECT `NameR` FROM `specification` WHERE `Name` = :s",
            s=spc,
        )
        if srow:
            rtype = srow["NameR"]

        self.load_spec_defaults(spc)

        nrows = db.fetchall(
            f"SELECT DISTINCT `N` FROM `{table}` WHERE Msk = :m "
            f"AND `N` IS NOT NULL ORDER BY `N`",
            m=msk,
        )
        numbers = [r["N"] for r in nrows if r["N"]]

        return {
            "msk": msk,
            "spc": spc,
            "rtype": rtype,
            "numbers": numbers,
        }

    def load_measure_ids(self, msk: str) -> list:
        """Все уникальные Measure_ID, принадлежащие данной МСК."""
        if not msk:
            return []
        table = get_main_table()
        rows = db.fetchall(
            f"SELECT DISTINCT `Measure_ID` FROM `{table}` "
            f"WHERE `Msk` = :m AND `Measure_ID` IS NOT NULL "
            f"ORDER BY `Measure_ID`",
            m=msk,
        )
        return [r["Measure_ID"] for r in rows if r["Measure_ID"]]

    # ------------------------------------------------------------------
    # Внутренние
    # ------------------------------------------------------------------
    def _fetch_meas_points(self):
        table = get_temps_table()
        base = ("SELECT `F`,`FL`,`R`,`Temp`,`Mono`,`Q`,`C0`,`Cq`,`Rb`,`L`,`N` "
                f"FROM `{table}` ")
        if self.measure_id:
            sql = base + "WHERE Measure_ID = :m AND `N` = :n ORDER BY Temp"
            return db.fetchall(sql, m=self.measure_id, n=self.number)
        sql = base + "WHERE Msk = :m AND `N` = :n ORDER BY Temp"
        return db.fetchall(sql, m=self.msk, n=self.number)

    def _extract_value(self, row, key):
        if key == "RcRb":
            rb = float(row["Rb"] or 0)
            return float(row["R"] or 0) / rb if rb else 1.0
        col = PARAM_BY_LABEL[self.param_label][2]
        v = float(row[col])
        if key == "C0":
            v *= 1e9
        elif key == "Cq":
            v *= 1e12
        return v

    def _extract_value_Old(self, row, key):
        if key == "RcRb":
            rb = float(row["Rb"] or 0)
            return float(row["R"] or 0) / rb if rb else 1.0
        col = PARAM_BY_LABEL[self.param_label][2]
        return float(row[col])

    def _prepare_xy(self, rows):
        key = PARAM_BY_LABEL[self.param_label][0]
        ref_val = None
        if key in ("F", "FL"):
            temps = [float(r["Temp"]) for r in rows]
            idx = int(np.argmin(np.abs(np.array(temps) - self.T_ref)))
            ref_val = self._extract_value(rows[idx], key)

        xs, ys = [], []
        for r in rows:
            try:
                t = float(r["Temp"])
                v = self._extract_value(r, key)
            except (TypeError, ValueError):
                continue
            if key in ("F", "FL"):
                v = v - ref_val
            xs.append(t)
            ys.append(v)
        return xs, ys

    def _value_at_tref(self, rows, key):
        """Значение параметра при T_ref (ближайшая точка)."""
        if not rows:
            return None

        pairs = []
        for r in rows:
            try:
                t = float(r["Temp"])
                v = self._extract_value(r, key)
            except (TypeError, ValueError):
                continue
            pairs.append((t, v))

        if not pairs:
            return None

        pairs.sort(key=lambda p: abs(p[0] - self.T_ref))
        t_near, v_near = pairs[0]

        if abs(t_near - self.T_ref) > self.T_ref_tolerance:
            return None

        return v_near

    # ------------------------------------------------------------------
    # Одиночное построение
    # ------------------------------------------------------------------
    def build_points(self, show_points: bool = True,
                     show_msk: bool = True) -> GraphResult:
        if not (self.number and (self.msk or self.measure_id)):
            raise GraphLogicError("Не выбраны МСК и номер")
        rows = self._fetch_meas_points()
        if not rows:
            raise GraphLogicError("Нет данных")
        xs, ys = self._prepare_xy(rows)
        if not xs:
            raise GraphLogicError("Нет корректных данных")

        key, label, _, unit = PARAM_BY_LABEL[self.param_label]
        res = GraphResult()
        if show_points:
            res.series.append(Series(label, xs, ys, COLOR_POINTS, "scatter"))
        parts = [f"N{self.number}"]
        if show_msk:
            if self.measure_id:
                parts.append(f"ID {self.measure_id}")
            else:
                parts.append(f"МСК {self.msk}")
        res.title = "  ".join(parts)
        res.ylabel = f"{label}, {unit}" if unit else label
        res.meta.update({"xs": xs, "ys": ys, "key": key, "unit": unit})
        return res

    def build_approximation(self, opts: dict) -> GraphResult:
        if not (self.number and (self.msk or self.measure_id)):
            raise GraphLogicError("Не выбраны МСК и номер")
        rows = self._fetch_meas_points()
        if not rows:
            raise GraphLogicError("Данные отсутствуют")

        degree = int(opts.get("degree", self.degree))
        if len(rows) < degree + 1:
            raise GraphLogicError(
                f"Недостаточно данных (нужно >={degree + 1}, есть {len(rows)})"
            )

        xs_all, ys_all = self._prepare_xy(rows)
        xy = [(x, y) for x, y in zip(xs_all, ys_all) if self.A <= x <= self.B]
        if len(xy) < degree + 1:
            raise GraphLogicError("Недостаточно точек в диапазоне [A,B]")

        xs = [p[0] for p in xy]
        ys = [p[1] for p in xy]
        coeffs = poly_fit(xs, ys, degree)
        gx = np.linspace(self.A, self.B, 400).tolist()
        gy = poly_val(coeffs, np.asarray(gx)).tolist()

        key, label, _, unit = PARAM_BY_LABEL[self.param_label]
        res = GraphResult()
        if opts.get("show_approx", True):
            res.series.append(Series("Аппроксимация", gx, gy,
                                     COLOR_APPROX, "line"))

        parts = [f"N{self.number}"]
        if opts.get("show_msk", True):
            if self.measure_id:
                parts.append(f"ID {self.measure_id}")
            else:
                parts.append(f"МСК {self.msk}")
        if opts.get("show_order", True):
            parts.append(f"Полином {degree} порядка")
        if opts.get("show_coeffs", False):
            coef_str = "  ".join(f"A{i}={c:.4g}"
                                 for i, c in enumerate(coeffs[::-1]))
            parts.append(coef_str)

        meta = {"coeffs": coeffs.tolist(), "degree": degree,
                "xs": xs, "ys": ys, "key": key, "unit": unit}

        res.title = "  ".join(parts)
        res.ylabel = f"{label}, {unit}" if unit else label
        res.meta = meta
        return res

    # ------------------------------------------------------------------
    # Все номера МСК / замера на одном графике
    # ------------------------------------------------------------------
    def build_all_numbers(self, show_msk: bool = True,
                          show_approx: bool = True,
                          show_points: bool = True) -> GraphResult:
        """
        Строит все номера текущей МСК (или ID замера) на одном поле.

        Параметры:
            show_msk     — добавить в заголовок количество номеров;
            show_approx  — рисовать линии аппроксимации;
            show_points  — рисовать точки замеров.

        Значения по умолчанию полностью совпадают с прежним поведением,
        поэтому существующие вызовы `build_all_numbers(show_msk=True)`
        продолжают работать без изменений.
        """
        if not (self.msk or self.measure_id):
            raise GraphLogicError("Не выбрано МСК")
        numbers = self.load_numbers(self.msk)
        if not numbers:
            raise GraphLogicError("Нет номеров для выбранной МСК")

        _, label, _, unit = PARAM_BY_LABEL[self.param_label]
        res = GraphResult()
        used = 0
        all_xs, all_ys = [], []

        save_number = self.number
        for n in numbers:
            self.number = n
            try:
                rows = self._fetch_meas_points()
                if not rows:
                    continue
                xs, ys = self._prepare_xy(rows)
                xy = [(x, y) for x, y in zip(xs, ys)
                      if self.A <= x <= self.B]
                if len(xy) < 2:
                    continue
                xs = [p[0] for p in xy]
                ys = [p[1] for p in xy]
            except Exception:
                continue

            color = COLORS[used % len(COLORS)]
            used += 1

            if show_points:
                res.series.append(Series(f"N{n}", xs, ys, color, "scatter"))

            if show_approx:
                try:
                    degree = min(self.degree, max(1, len(xs) - 1))
                    coeffs = poly_fit(xs, ys, degree)
                    gx = np.linspace(self.A, self.B, 200).tolist()
                    gy = poly_val(coeffs, np.asarray(gx)).tolist()
                    res.series.append(Series(f"N{n} аппрокс.",
                                             gx, gy, color, "line"))
                except Exception:
                    pass

            all_xs.extend(xs)
            all_ys.extend(ys)

        self.number = save_number

        if not res.series:
            raise GraphLogicError("Не удалось построить ни одного номера")

        if self.measure_id:
            parts = [f"ID {self.measure_id}"]
        else:
            parts = [f"МСК {self.msk}"]
        if show_msk:
            parts.append(f"все номера ({used})")
        res.title = "  ".join(parts)
        res.ylabel = f"{label}, {unit}" if unit else label
        res.meta["all_xs"] = all_xs
        res.meta["all_ys"] = all_ys
        res.meta["hide_legend"] = True
        return res


    # ------------------------------------------------------------------
    # Расчётные величины
    # ------------------------------------------------------------------
    def compute_metrics(self) -> dict:
        if not (self.number and (self.msk or self.measure_id)):
            raise GraphLogicError("Не выбраны МСК и номер")

        rows = self._fetch_meas_points()
        if not rows:
            raise GraphLogicError("Нет данных")

        key, label, _, unit = PARAM_BY_LABEL[self.param_label]
        xs_all, ys_all = self._prepare_xy(rows)
        xy = [(x, y) for x, y in zip(xs_all, ys_all)
              if self.A <= x <= self.B]
        if len(xy) < 2:
            raise GraphLogicError("Недостаточно точек в диапазоне")

        xs = [p[0] for p in xy]
        ys = [p[1] for p in xy]

        m = {}
        m["Точек"] = len(xs)
        m["T минимум, C"] = round(min(xs), 2)
        m["T максимум, C"] = round(max(xs), 2)
        m[f"Y минимум, {unit}"] = round(min(ys), 4)
        m[f"Y максимум, {unit}"] = round(max(ys), 4)

        f_vals, fl_vals = [], []
        for r in rows:
            try:
                f_vals.append(float(r["F"]))
            except (TypeError, ValueError):
                pass
            try:
                if r["FL"] is not None:
                    fl_vals.append(float(r["FL"]))
            except (TypeError, ValueError):
                pass
        if f_vals:
            m["F max, Гц"] = round(max(f_vals), 4)
            m["F min, Гц"] = round(min(f_vals), 4)
        if fl_vals:
            m["FL max, Гц"] = round(max(fl_vals), 4)
            m["FL min, Гц"] = round(min(fl_vals), 4)

        degree = min(self.degree, max(1, len(xs) - 1))
        if len(xs) >= degree + 1:
            coeffs = poly_fit(xs, ys, degree)
            tmax_poly, tmin_poly = extremes(coeffs, self.A, self.B)
            m["T экстремум max, C"] = (round(tmax_poly, 2)
                                       if tmax_poly is not None else "-")
            m["T экстремум min, C"] = (round(tmin_poly, 2)
                                       if tmin_poly is not None else "-")

            # Монотонность: max |y_approx − y_meas| в узлах, крайние точки
            # интервала исключаются (как Mono/MonoT в Make_Measure).
            mono_val, mono_t = monotonicity(
                xs, ys, self.A, self.B, degree, exclude_edges=True)
            m[f"Монотонность, {unit}"] = round(mono_val, 4)
            m["T монотонности, C"] = (round(mono_t, 2)
                                      if mono_t is not None else "-")

            # Скачок: максимальное перпендикулярное расстояние
            # от точек измерения до аппроксимирующей кривой.
            jp, tp, jm, tm = jumps(xs, ys, self.A, self.B, degree)
            m[f"Скачок +, {unit}"] = round(jp, 4)
            m["T скачка +, C"] = round(tp, 2) if tp is not None else "-"
            m[f"Скачок -, {unit}"] = round(jm, 4)
            m["T скачка -, C"] = round(tm, 2) if tm is not None else "-"

            infl = inflection_point(coeffs, self.A, self.B)
            m["Точка перегиба, C"] = (round(infl, 2)
                                      if infl is not None else "-")

        return m

    # ------------------------------------------------------------------
    # Статистика по МСК / ID замера + распределение + аномалии
    # ------------------------------------------------------------------
    def compute_msk_statistics(self, bins: int = 15) -> dict:
        """Статистика по номерам МСК или ID замера."""
        if not (self.msk or self.measure_id):
            raise GraphLogicError("Не выбрано МСК")

        numbers = self.load_numbers(self.msk)
        if not numbers:
            raise GraphLogicError("Нет номеров для выбранной МСК")

        key, label, _, unit = PARAM_BY_LABEL[self.param_label]

        save_number = self.number
        values = []
        skipped = []
        for n in numbers:
            self.number = n
            try:
                rows = self._fetch_meas_points()
                v = self._value_at_tref(rows, key)
            except Exception:
                v = None
            if v is None:
                skipped.append(str(n))
            else:
                values.append((str(n), float(v)))
        self.number = save_number

        if len(values) < 2:
            raise GraphLogicError(
                f"Недостаточно данных для статистики: "
                f"найдено {len(values)} из {len(numbers)} "
                f"(нет значения при T_ref = {self.T_ref} C)"
            )

        vals = np.array([v for _, v in values], dtype=float)
        mean = float(np.mean(vals))
        std = float(np.std(vals, ddof=1)) if len(vals) > 1 else 0.0
        q1 = float(np.percentile(vals, 25))
        q3 = float(np.percentile(vals, 75))
        iqr = q3 - q1

        stats = {
            "label": label,
            "unit": unit,
            "T_ref": self.T_ref,
            "count": len(vals),
            "skipped": skipped,
            "mean": mean,
            "median": float(np.median(vals)),
            "std": std,
            "min": float(np.min(vals)),
            "max": float(np.max(vals)),
            "q1": q1,
            "q3": q3,
            "iqr": iqr,
            "range": float(np.max(vals) - np.min(vals)),
            "values": values,
            "measure_id": self.measure_id,
        }

        counts, edges = np.histogram(vals, bins=bins)
        stats["hist_counts"] = counts.tolist()
        stats["hist_edges"] = edges.tolist()
        stats["hist_centers"] = ((edges[:-1] + edges[1:]) / 2).tolist()

        kde_x, kde_y = gaussian_kde(vals)
        stats["kde_x"] = kde_x.tolist()
        stats["kde_y"] = kde_y.tolist()

        anomalies = []
        for n, v in values:
            z = abs(v - mean) / std if std > 0 else 0.0
            iqr_out = (v < q1 - 1.5 * iqr) or (v > q3 + 1.5 * iqr)
            if z > 3 or iqr_out:
                anomalies.append({
                    "number": n,
                    "value": v,
                    "z_score": round(z, 2),
                    "iqr_out": bool(iqr_out),
                })
        anomalies.sort(key=lambda a: a["z_score"], reverse=True)
        stats["anomalies"] = anomalies
        return stats

    def iter_numbers(self, msk: str):
        for n in self.load_numbers(msk):
            yield n