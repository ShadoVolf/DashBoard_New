"""
Общие функции сопоставления спецификаций и измерительных файлов
(температурные профили, режимы нагрузки, номиналы).

Используется:
  * Temperature_Measure.Analyze_Data — гибкий подбор кандидатов
    (test_temp_interval_points, get_multy_spec, rank_spec_candidates);
  * Temperature_Measure.Load_Data    — проверка перед сохранением
    (test_spcecification);
  * Virtual_Measure.Spc_Search_NN    — признаки совместимости
    «измерительный файл ↔ спецификация» для нейросетевого подбора
    (kind='spcnn' в таблице virtual_nn_models).

Изменения относительно прежней логики:
  * подбор по ёмкости нагрузки (Cn / Loadvalue) убран как ненадёжный —
    он отбраковывал корректные номенклатуры из-за различий в форме
    записи значения CL;
  * сравнение температур устойчиво к формату записи: 25 vs 25.0,
    разделители ',' / ';' / пробелы, None (раньше строки сравнивались
    в исходном виде и падали на неожиданном формате);
  * температурный профиль спецификации считается подходящим, если
    выполнено хотя бы одно из условий (гибкий режим):
      - точное совпадение набора точек (± TEMP_EPS);
      - профиль полностью покрыт измеренными точками (бывшее 'OK');
      - диапазон профиля вложен в диапазон измерения;
      - пересечение множеств IoU >= TEMP_IOU_MIN;
  * допуск по номинальной частоте — FREQ_TOL_PPM ppm вместо строгого
    равенства float.
"""

import math

# Допуск при сравнении температур, °C
TEMP_EPS = 0.5
# Минимальное пересечение (Jaccard) температурных множеств в гибком режиме
TEMP_IOU_MIN = 0.75
# Допуск совпадения номинальной частоты, ppm
FREQ_TOL_PPM = 100.0
# Допуск «точного» совпадения номинала, ppm
FREQ_EPS_PPM = 2.0

# Разрешённые сочетания режима измерения файла (CL_Metod) и типа
# нагрузки спецификации (LoadType) — как прежняя valid_combinations
LOAD_TYPE_COMBINATIONS = {
    'EQREACT':   ('EQREACT', 'SERIES'),
    'NUMERICAL': ('NUMERICAL', 'SERIES'),
    'PHYSICAL':  ('PHYSICAL',),
    'SERIES':    ('SERIES',),
}

# Приведение формы записи типа нагрузки к каноническому виду
LOAD_TYPE_ALIASES = {
    'Series': 'SERIES',
    'EqReact': 'EQREACT',
    'Phisical': 'PHYSICAL',
    'Saunders (FR+FL)': 'EQREACT',
    'Saunders(FR)': 'SERIES',
    'Saunders(FL)': 'PHYSICAL',
    '0': 'SERIES',
}


def normalize_load_type(value) -> str:
    """Приводит тип нагрузки (LoadType) к канонической форме."""
    v = '' if value is None else str(value).strip()
    if not v:
        return 'SERIES'
    if v in LOAD_TYPE_ALIASES:
        return LOAD_TYPE_ALIASES[v]
    up = v.upper()
    for canon in ('EQREACT', 'NUMERICAL', 'PHYSICAL', 'SERIES'):
        if canon in up or up.startswith(canon):
            return canon
    return up


def load_types_compatible(cl_metod, load_type) -> bool:
    """Совместимы ли режим измерения файла и тип нагрузки спецификации."""
    cl = normalize_load_type(cl_metod)
    lt = normalize_load_type(load_type)
    return lt in LOAD_TYPE_COMBINATIONS.get(cl, ())


def parse_temp_list(value):
    """
    '25 85 125' | '25,85;125' | [25.0, 85.0] | numpy-массив | None
    → список float (некорректные элементы пропускаются).
    """
    if value is None:
        return []
    if hasattr(value, 'tolist'):
        value = value.tolist()
    if isinstance(value, (list, tuple, set)):
        items = value
    else:
        text = str(value).replace(',', ' ').replace(';', ' ')
        items = text.split()
    out = []
    for it in items:
        try:
            f = float(str(it).strip())
        except (TypeError, ValueError):
            continue
        if math.isfinite(f):
            out.append(f)
    return out


def temps_covered(spec_temps, data_temps, eps=TEMP_EPS) -> bool:
    """
    True, если каждая точка температурного профиля спецификации покрыта
    хотя бы одной измеренной точкой файла (± eps). Профиль шире набора
    точек файла — прежнее 'OK (Интервал избыточен)'.
    """
    if not spec_temps or not data_temps:
        return False
    return all(any(abs(s - d) <= eps for d in data_temps)
               for s in spec_temps)


def temps_sets_equal(data_temps, spec_temps, eps=TEMP_EPS) -> bool:
    """True, если наборы точек совпадают с точностью до eps
    (без учёта порядка)."""
    if len(data_temps) != len(spec_temps):
        return False
    rest = list(data_temps)
    for t in spec_temps:
        if not rest:
            return False
        idx = min(range(len(rest)), key=lambda i: abs(rest[i] - t))
        if abs(rest[idx] - t) > eps:
            return False
        rest.pop(idx)
    return not rest


def temps_iou(data_temps, spec_temps, eps=TEMP_EPS) -> float:
    """Пересечение по Жаккару температурных множеств с допуском eps."""
    if not data_temps or not spec_temps:
        return 0.0
    inter = sum(1 for s in spec_temps
                if any(abs(s - d) <= eps for d in data_temps))
    if inter == 0:
        return 0.0
    union = len(data_temps) + len(spec_temps) - inter
    return inter / union if union else 0.0


def temps_match(spec_temps, data_temps, eps=TEMP_EPS,
                min_iou=TEMP_IOU_MIN) -> bool:
    """
    Гибкое сопоставление температурных профилей: True, если

      * наборы точек совпадают (± eps), либо
      * профиль спецификации полностью покрыт измерением, либо
      * диапазон профиля вложен в диапазон файла (± eps), либо
      * пересечение (IoU) не меньше min_iou.

    :param spec_temps: точки профиля спецификации
    :param data_temps: точки измерительного файла
    """
    spec = parse_temp_list(spec_temps) if isinstance(spec_temps, str) \
        else list(spec_temps or [])
    data = parse_temp_list(data_temps) if isinstance(data_temps, str) \
        else list(data_temps or [])
    if not spec or not data:
        return False
    try:
        if temps_sets_equal(data, spec, eps):
            return True
    except Exception:
        pass
    if temps_covered(spec, data, eps):
        return True
    if (min(spec) >= min(data) - eps) and (max(spec) <= max(data) + eps):
        return True
    return temps_iou(data, spec, eps) >= min_iou


def freq_diff_ppm(freq_hz, ref_hz):
    """
    Относительная разница частот в ppm.
    None — если ссылка некорректна (0 / None / NaN).
    """
    try:
        ref = float(ref_hz)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(ref) or ref == 0:
        return None
    try:
        f = float(freq_hz)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(f):
        return None
    return abs(f - ref) / abs(ref) * 1e6


def nominal_matches(freq_hz, ref_hz, tol_ppm=FREQ_TOL_PPM) -> bool:
    """True, если частота попадает в допуск по номиналу."""
    d = freq_diff_ppm(freq_hz, ref_hz)
    return d is not None and d < tol_ppm


def nominal_exact(freq_hz, ref_hz, tol_ppm=FREQ_EPS_PPM) -> bool:
    """True, если частота совпадает с номиналом «начисто»."""
    d = freq_diff_ppm(freq_hz, ref_hz)
    return d is not None and d < tol_ppm
