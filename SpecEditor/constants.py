"""
Теги, секции, метки и группы полей редактора спецификаций.
"""

# ---------------------------------------------------------------------------
# Теги DPG
# ---------------------------------------------------------------------------
WIN_LIST_TAG = "spec_editor_list_win"
WIN_EDIT_TAG = "spec_editor_edit_win"
WIN_NEW_TAG = "spec_editor_new_win"
WIN_ERR_TAG = "spec_editor_err"

TAG_SEARCH = "spec_search"
TAG_TABLE = "spec_table"
TAG_TAB_BAR = "spec_tabbar"
TAG_STATUS = "spec_status"

# ---------------------------------------------------------------------------
# Секции (вкладки редактора)
# ---------------------------------------------------------------------------
SECTION_ORDER = [
    ("main",       "Основное"),
    ("nu_params",  "Параметры НУ"),
    ("tch_params", "Параметры ТЧХ"),
    ("extra",      "Доп. параметры"),
    ("rt",         "Параметры РТ"),
    ("sphere",     "Радиус сферы"),
    ("quality",    "Качество и характеристики"),
    ("corrections","Корректировка"),
    ("tolerances", "Допуска"),
    ("spur",       "Нежелательные резонансы"),
    ("phase",      "Фазовые шумы"),
    ("options",    "Опции вывода"),
    ("print",      "Печать"),
]
SECTION_LABELS = dict(SECTION_ORDER)

# ---------------------------------------------------------------------------
# Допуски (вкладка 'Допуска')
# ---------------------------------------------------------------------------
TOLERANCE_GROUPS = [
    ("Точность настройки",         "DopuskF",       "DopuskF_P"),
    ("Точность настройки ТГК",     "DopuskFtgk",    None),
    ("Сопротивление",              "DopuskR",       None),
    ("Добротность",                "DopuskQ",       None),
    ("Статическая ёмкость C0",     "DopuskC0",      None),
    ("Динамическая ёмкость Cq",    "DopuskCq",      None),
    ("F(T), ppm",                  "DopuskFT",      None),
    ("Нежелательные резонансы",    "DopuskSR",      None),
    ("Частота в интервале Т",      "DopuskFi_Real", "DopuskFi"),
    ("Изменение сопротивления",    "DopuskRR",      None),
    ("Fptp",                       "DopuskFptp",    None),
    ("Наклон (10E-8)",             "DopuskSlope",   None),
    ("Экстремум, C",              "DopuskT",       None),
    ("Сопротивление ТГК",          "DopuskRtgk",    None),
    ("Rc/Rb",                      "DopuskRcRb",    None),
    ("Макс. сопротивление",        "DopuskRmax",    None),
    ("Перестройка",                "DopuskC1_2C0",  None),
    ("Монотонность",               "Dopusk_M",      None),
]

# ---------------------------------------------------------------------------
# Метки для известных колонок
# ---------------------------------------------------------------------------
LABELS = {
    # Основное
    "Name": "Название",
    "NameR": "Тип резонатора",
    "Spc_Code": "Код спецификации",
    "Profile": "Температурный профиль",
    "String": "Установочный файл",
    "Type": "Корпус",
    "TypeF": "Тип F (FL)",
    "LoadType": "Тип измерения",
    "Loadvalue": "Значение ёмкости, pF",
    "Nominal": "Номинал",
    "TU": "ТУ",
    "Power": "Мощность, uW",
    "Tnastr": "Опорная T, C",
    "Tpar": "T пара, C",
    "Tq": "T добротности, C",
    "Tc0": "T C0, C",
    "Tcq": "T Cq, C",
    "Lt": "T L, C",
    "Garmonica": "Гармоника",
    "Solve_Date": "Решение от",
    "PrintProfile": "Профиль печати",
    "ID": "ID",
    "Multy": "Мультиспецификация",
    # Доп. характеристики
    "Favg": "Средняя частота",
    "Qavg": "Средняя добротность",
    "K": "Поправочный коэффициент",
    "TGK": "Эквивалент генератора",
    "MetalAu": "Содержание золота",
    "MetalAg": "Содержание серебра",
    "MetalNi": "Содержание никеля",
    "MinNar": "Минимальная наработка",
    "Hran": "Срок хранения",
    "FnastrHZ": "Точность настройки, Гц",
    "TintValue": "Значение стат. ёмкости",
    "AVG_C0": "Среднее ожидаемое значение C0",
    "W2200_CL": "Нагрузка W2200, pF",
    "KH7700_CL": "Нагрузка KH7700, pF",
    "TTS100_CL": "Нагрузка TTS-100, pF",
    "Spur_Search": "Определять как",
    # Опции вывода
    "Stat": "Статистика",
    "Snumber": "Номер резонатора",
    "Number": "Порядковый номер",
    "Position": "Позиция в круге",
    "Status": "Статус",
    "BadOnly": "Брак",
    "GoodOnly": "Годные",
    "OnlyNumbers": "Только числа",
    "BD": "Вносить в БД",
    "norm": "Выводить нормы",
    "PrintProtokol": "Печать протокола",
    "PrintGraph": "Печать графиков",
    "GraphP": "Печать в файл",
    "GraphF": "Тип графика",
    "Anomal": "Аномальные",
    "AnomalR": "Аномальные по R",
    "GraphOnlyAprox": "Только аппроксимация",
    "GraphOnluMeasure": "Только замеренные точки",
    "Print": "Тип протокола",
    # TCH
    "TCHType": "Тип замера ТЧХ",
    "TCH_Approx_Type": "Аппроксимация",
    "TCH_Interval_Type": "Тип интервала",
    "TCH_Approx_IST": "Использовать расчёт аппроксимации",
    "Ftgk_Measure": "Расчёт точности настройки для ТГК",
    "TCHTable": "Разбраковка ТЧХ по таблице",
    "AltAppprox": "Альтернативный полином",
    "Mono_Approx_Type": "Монотонность W2200",
    "INVERT_Rc_RB": "Инвертировать Rc/Rb",
    "TCH_correction": "ТЧХ коррекция",
    "F_correction": "Точность настройки коррекция",
    "R_correction": "Коррекция R (по RK)",
    "Q_correction": "Коррекция Q (по RK)",
    "FL_Num": "FL расчётное",
    "FL_Num_Virt": "FL расчётное коррекция",
    # Физические коррекции
    "physical_R_Correction": "Коррекция R (физ.)",
    "physical_C0_correction": "Коррекция C0 (физ.)",
    "physical_C1_correction": "Коррекция C1 (физ.)",
}

# ---------------------------------------------------------------------------
# Колонка -> секция
# ---------------------------------------------------------------------------
COLUMN_SECTION = {
    # ---------------- Основное ----------------
    **{c: "main" for c in (
        "Name", "NameR", "Spc_Code", "Profile", "String", "Type", "TypeF",
        "LoadType", "Loadvalue", "Nominal", "TU", "Power",
        "Solve_Date", "ID", "Multy",
        "Tnastr", "Tpar", "Tq", "Tc0", "Tcq", "Lt",
    )},
    # ---------------- Опции вывода ----------------
    **{c: "options" for c in (
        "Stat", "Snumber", "Number", "Position", "Status",
        "BadOnly", "GoodOnly", "OnlyNumbers", "BD", "norm",
        "PrintProtokol", "PrintGraph", "GraphP", "GraphF",
        "Anomal", "AnomalR", "GraphOnlyAprox", "GraphOnluMeasure",
        "Print",
    )},
    # ---------------- Нежелательные резонансы ----------------
    **{c: "spur" for c in (
        "Spur_Use", "Spur_Temp", "Spur_Search",
        "Spur_F_1_use", "Spur_F_1_Min", "Spur_F_1_Max", "Spur_F_1_AMP_Unit",
        "Spur_F_2_use", "Spur_F_2_Min", "Spur_F_2_Max", "Spur_F_2_AMP_Unit",
        "Spur_F_3_use", "Spur_F_3_Min", "Spur_F_3_Max", "Spur_F_3_AMP_Unit",
        "Rsp1", "Rsp1min", "Rsp1max", "Rsp1tBegin", "Rsp1tEnd",
        "Rsp2", "Rsp2min", "Rsp2max", "Rsp2tBegin", "Rsp2tEnd",
        "Rsp3", "Rsp3min", "Rsp3max", "Rsp3tBegin", "Rsp3tEnd",
    )},
    # ---------------- Фазовые шумы ----------------
    **{c: "phase" for c in (
        "Shum", "ShMin", "ShMax", "ShOT",
        "Shum1", "Sh1Min", "Sh1Max", "Sh1OT",
        "Shum2", "Sh2Min", "Sh2Max", "Sh2OT",
        "Shum3", "Sh3Min", "Sh3Max", "Sh3OT",
        "Shum4", "Sh4Min", "Sh4Max", "Sh4OT",
        "Generator_Type",
        "PhazeNoise_Options",
    )},
    # ---------------- Качество и характеристики ----------------
    **{c: "quality" for c in (
        "MetalAu", "MetalAg", "MetalNi", "TGK",
        "MinNar", "Hran",
        "Favg", "Qavg", "K", "FnastrHZ",
        "INVERT_Rc_RB", "Mono_Approx_Type", "Ftgk_Measure",
    )},
    # ---------------- Параметры НУ ----------------
    **{c: "nu_params" for c in (
        "Ft", "Fmin", "Fmax", "R", "Rmin", "Rmax", "Q", "Qmin", "Qmax",
        "C0", "C0min", "C0max", "Cq", "Cqmin", "Cqmax", "L", "Lmin", "Lmax",
        "Fmx", "Fmaxmin", "Fmaxmax", "Fmn", "Fminmin", "Fminmax",
        "Fptp", "Fptpmin", "Fptpmax", "Fptp_2", "Fptp_2min", "Fptp_2max",
        "F", "F0FL", "F0FLmin", "F0FLmax", "Fmaxm",
        "Rmx", "Rmaxmin", "Rmaxmax", "Rmn", "Rminmin", "Rminmax",
        "Rb", "Rbmin", "Rbmax", "RbT", "Rc_Rb", "Rc_Rbmin", "Rc_Rbmax",
        "TbBegin", "TbEnd",
        "C0_C1", "C0_C1min", "C0_C1max", "C0_C1_T",
        "C1_2C0", "C1_2C0min", "C1_2C0max", "C1_2C0T",
        "FtVP", "Ftgk", "Rtgk",
        "Tft",
    )},
    # ---------------- Параметры ТЧХ ----------------
    **{c: "tch_params" for c in (
        "Tmax", "Tmaxmin", "Tmaxmax", "Tmin", "Tminmin", "Tminmax",
        "IT_Temp_A", "IT_Temp_B",
        "TurnOver", "Tomin", "Tomax",
        "S", "Smin", "Smax", "Tnakl",
        "M", "Mmin", "Mmax", "TmBegin", "TmEnd",
        "FTx", "FTmin", "FTmax", "FTxt",
        "Ft1", "Ft1min", "Ft1max", "Ft1t",
        "Ft2", "Ft2min", "Ft2max", "Ft2t",
        "Ft3", "Ft3min", "Ft3max", "Ft3t",
        "Ft4", "Ft4min", "Ft4max", "Ft4t",
        "RR", "RRmin", "RRmax",
        "Rmax-Rmin", "RR1min", "RR1max",
        "RR2", "RR2min", "RR2max", "RR3", "RR3min", "RR3max",
        "RR4", "RR4min", "RR4max", "RR5", "RR5min", "RR5max",
        "TCH_Interval_Type", "IntervalName", "A", "B",
        "TCHType", "TCH_Approx_Type", "TCH_Approx_IST", "TCHTable",
        "AltAppprox", "polinom", "Garmonica",
        "TCH_Temp_A", "TCH_Temp_B",
    )},
    # ---------------- Доп. параметры ----------------
    **{c: "extra" for c in (
        "F1min", "F1max", "Rmax1min", "Rmax1max",
        "Fmax1min", "Fmax1max", "Fmin1min", "Fmin1max",
        "C01min", "C01max", "Cq1min", "Cq1max",
        "IT1min", "IT1max", "M1min", "M1max", "M2min", "M2max",
        "Old1", "old1min", "old1max", "Told1",
        "Old2n", "old2min", "Old2Max", "Told2", "Old2",
        "Old3", "Old3Min", "Old3Max", "Told3",
        "Jump", "JumpMin", "JumpMax", "JumpT", "JumpP", "JumpPTP", "MonoT",
    )},
    # ---------------- Печать ----------------
    **{c: "print" for c in ("Text", "Protokol", "PrintProfile")},
    # ---------------- Параметры РТ ----------------
    **{c: "rt" for c in (
        "Imax", "Imaxmax", "Imaxmin", "Imax_T",
        "Iust", "Iust_max", "Iust_min", "Iust_T",
        "Uust_1", "Uust_1_max", "Uust_1_min", "Uust_1_T",
        "Uust_2", "Uust_2_max", "Uust_2_min", "Uust_2_T",
        "Uust_3", "Uust_3_max", "Uust_3_min", "Uust_3_T",
        "DF_Time_1", "DF_Time_1_Min", "DF_Time_1_max", "DF_Time_1_T", "DF_Time_1_time",
        "DF_Time_2", "DF_Time_2_min", "DF_Time_2_max", "DF_Time_2_T", "DF_Time_2_time",
        "DF_Time_3", "DF_Time_3_min", "DF_Time_3_max", "DF_Time_3_T", "DF_Time_3_time",
    )},
    # ---------------- Корректировка ----------------
    **{c: "corrections" for c in (
        "AVG_C0", "W2200_CL", "KH7700_CL", "TTS100_CL",
        "Tint", "TintValue",
        "physical_R_Correction", "physical_C0_correction", "physical_C1_correction",
        "F_correction", "TCH_correction", "R_correction", "Q_correction",
        "FL_Num", "FL_Num_Virt",
        "Fmax_int", "Fmax_int_Min", "Fmax_int_Max",
        "Fmin_int", "Fmin_int_Min", "Fmin_int_Max",
        "F_int", "Fint_Min", "Fint_Max",
        "Rekv", "Rekv_min", "Rekv_max",
    )},
    # ---------------- Радиус сферы ----------------
    **{c: "sphere" for c in (
        "Rsphere", "RsphereK1", "RsphereK2", "RsphereT", "RsphereMin", "RsphereMax",
    )},
}

# ---------------------------------------------------------------------------
# Группы параметров
# (метка, bool, min, max, T, T-метка, секция, блок)
# ---------------------------------------------------------------------------
PARAM_GROUPS = [
    # --- Параметры НУ ---
    ("Точность настройки, ppm", "Ft", "Fmin", "Fmax", "Tnastr", "T, C", "nu_params", "Основные параметры"),
    ("Сопротивление, Ohm", "R", "Rmin", "Rmax", "Tpar", "T, C", "nu_params", "Основные параметры"),
    ("Добротность", "Q", "Qmin", "Qmax", "Tq", "T, C", "nu_params", "Основные параметры"),
    ("C0, pF", "C0", "C0min", "C0max", "Tc0", "T, C", "nu_params", "Основные параметры"),
    ("Cq, fF", "Cq", "Cqmin", "Cqmax", "Tcq", "T, C", "nu_params", "Основные параметры"),
    ("L, mH", "L", "Lmin", "Lmax", "Lt", "T, C", "nu_params", "Основные параметры"),

    ("Макс. частота, Гц", "Fmx", "Fmaxmin", "Fmaxmax", None, None, "nu_params", "Доп. параметры частоты"),
    ("Мин. частота, Гц", "Fmn", "Fminmin", "Fminmax", None, None, "nu_params", "Доп. параметры частоты"),
    ("F ptp, Гц", "Fptp", "Fptpmin", "Fptpmax", None, None, "nu_params", "Доп. параметры частоты"),
    ("F ptp/2, Гц", "Fptp_2", "Fptp_2min", "Fptp_2max", None, None, "nu_params", "Доп. параметры частоты"),
    ("Частота", "F", None, None, "Tft", "T, C", "nu_params", "Доп. параметры частоты"),
    ("F0-FL", "F0FL", "F0FLmin", "F0FLmax", None, None, "nu_params", "Доп. параметры частоты"),
    ("Fmax (max)", "Fmaxm", None, None, None, None, "nu_params", "Доп. параметры частоты"),

    ("Макс. сопротивление, Ohm", "Rmx", "Rmaxmin", "Rmaxmax", None, None, "nu_params", "Доп. параметры сопротивления"),
    ("Мин. сопротивление, Ohm", "Rmn", "Rminmin", "Rminmax", None, None, "nu_params", "Доп. параметры сопротивления"),
    ("Rb, Ohm", "Rb", "Rbmin", "Rbmax", "RbT", "T, C", "nu_params", "Доп. параметры сопротивления"),
    ("Rc/Rb max", "Rc_Rb", "Rc_Rbmin", "Rc_Rbmax", None, None, "nu_params", "Доп. параметры сопротивления"),

    ("C0/C1", "C0_C1", "C0_C1min", "C0_C1max", "C0_C1_T", "T, C", "nu_params", "Соотношения ёмкостей"),
    ("C1/2C0", "C1_2C0", "C1_2C0min", "C1_2C0max", "C1_2C0T", "T, C", "nu_params", "Соотношения ёмкостей"),

    ("Ft ВП", "FtVP", None, None, None, None, "nu_params", "Параметры ТГК"),
    ("Ftgk", "Ftgk", None, None, None, None, "nu_params", "Параметры ТГК"),
    ("Rtgk", "Rtgk", None, None, None, None, "nu_params", "Параметры ТГК"),

    # --- Параметры ТЧХ ---
    ("T экстремум max, C", "Tmax", "Tmaxmin", "Tmaxmax", None, None, "tch_params", "Температурные экстремумы"),
    ("T экстремум min, C", "Tmin", "Tminmin", "Tminmax", None, None, "tch_params", "Температурные экстремумы"),
    ("T перегиба, C", "TurnOver", "Tomin", "Tomax", None, None, "tch_params", "Температурные экстремумы"),

    ("Наклон ТЧХ", "S", "Smin", "Smax", "Tnakl", "T, C", "tch_params", "Наклон и монотонность"),
    ("Монотонность ТЧХ", "M", "Mmin", "Mmax", None, None, "tch_params", "Наклон и монотонность"),

    ("F(T)", "FTx", "FTmin", "FTmax", "FTxt", "T, C", "tch_params", "Частота от температуры"),
    ("F(T1)", "Ft1", "Ft1min", "Ft1max", "Ft1t", "T, C", "tch_params", "Частота от температуры"),
    ("F(T2)", "Ft2", "Ft2min", "Ft2max", "Ft2t", "T, C", "tch_params", "Частота от температуры"),
    ("F(T3)", "Ft3", "Ft3min", "Ft3max", "Ft3t", "T, C", "tch_params", "Частота от температуры"),
    ("F(T4)", "Ft4", "Ft4min", "Ft4max", "Ft4t", "T, C", "tch_params", "Частота от температуры"),

    ("Изменение R, Ohm", "RR", "RRmin", "RRmax", None, None, "tch_params", "Изменение сопротивления"),
    ("Rmax-Rmin", "Rmax-Rmin", "RR1min", "RR1max", None, None, "tch_params", "Изменение сопротивления"),
    ("Rmax/R25", "RR2", "RR2min", "RR2max", None, None, "tch_params", "Изменение сопротивления"),
    ("R25/Rmin", "RR3", "RR3min", "RR3max", None, None, "tch_params", "Изменение сопротивления"),
    ("(Rmax-R25)/R25*100%", "RR4", "RR4min", "RR4max", None, None, "tch_params", "Изменение сопротивления"),
    ("(Rmin-R25)/R25*100%", "RR5", "RR5min", "RR5max", None, None, "tch_params", "Изменение сопротивления"),

    # --- Доп. параметры ---
    ("Старение 1", "Old1", "old1min", "old1max", "Told1", "T, C", "extra", "Старение"),
    ("Старение 2 (F3-F2)", "Old2n", "old2min", "Old2Max", "Told2", "T, C", "extra", "Старение"),
    ("Старение 2 (F3-F1)", "Old2", None, None, None, None, "extra", "Старение"),
    ("Старение 3", "Old3", "Old3Min", "Old3Max", "Told3", "T, C", "extra", "Старение"),

    ("Точность настройки (цех)", None, "F1min", "F1max", None, None, "extra", "Цеховые нормы"),
    ("Макс. сопротивление (цех)", None, "Rmax1min", "Rmax1max", None, None, "extra", "Цеховые нормы"),
    ("Макс. изменение частоты", None, "Fmax1min", "Fmax1max", None, None, "extra", "Цеховые нормы"),
    ("Мин. изменение частоты", None, "Fmin1min", "Fmin1max", None, None, "extra", "Цеховые нормы"),
    ("Стат. ёмкость (цех)", None, "C01min", "C01max", None, None, "extra", "Цеховые нормы"),
    ("Дин. ёмкость (цех)", None, "Cq1min", "Cq1max", None, None, "extra", "Цеховые нормы"),
    ("Перегиб (цех)", None, "IT1min", "IT1max", None, None, "extra", "Цеховые нормы"),
    ("Монотонность, группа 1", None, "M1min", "M1max", None, None, "extra", "Цеховые нормы"),
    ("Монотонность, группа 2", None, "M2min", "M2max", None, None, "extra", "Цеховые нормы"),

    ("Скачок", "Jump", "JumpMin", "JumpMax", "JumpT", "T, C", "extra", "Скачки и монотонность"),
    ("Скачок PTP", "JumpP", "JumpPTP", None, None, None, "extra", "Скачки и монотонность"),
    ("Монотонность T", "MonoT", None, None, None, None, "extra", "Скачки и монотонность"),

    # --- Параметры РТ ---
    ("Imax, мА", "Imax", "Imaxmax", "Imaxmin", "Imax_T", "T, C", "rt", "Режим работы"),
    ("I уст., мА", "Iust", "Iust_max", "Iust_min", "Iust_T", "T, C", "rt", "Режим работы"),
    ("U уст. 1, В", "Uust_1", "Uust_1_max", "Uust_1_min", "Uust_1_T", "T, C", "rt", "Режим работы"),
    ("U уст. 2, В", "Uust_2", "Uust_2_max", "Uust_2_min", "Uust_2_T", "T, C", "rt", "Режим работы"),
    ("U уст. 3, В", "Uust_3", "Uust_3_max", "Uust_3_min", "Uust_3_T", "T, C", "rt", "Режим работы"),

    ("Время выхода 1, с", "DF_Time_1", "DF_Time_1_Min", "DF_Time_1_max", "DF_Time_1_T", "T, C", "rt", "Время выхода на режим"),
    ("Время выхода 2, с", "DF_Time_2", "DF_Time_2_min", "DF_Time_2_max", "DF_Time_2_T", "T, C", "rt", "Время выхода на режим"),
    ("Время выхода 3, с", "DF_Time_3", "DF_Time_3_min", "DF_Time_3_max", "DF_Time_3_T", "T, C", "rt", "Время выхода на режим"),

    # --- Фазовые шумы ---
    ("Фазовые шумы 1", "Shum",  "ShMin",  "ShMax",  "ShOT",  "Отстройка", "phase", "Фазовые шумы"),
    ("Фазовые шумы 2", "Shum1", "Sh1Min", "Sh1Max", "Sh1OT", "Отстройка", "phase", "Фазовые шумы"),
    ("Фазовые шумы 3", "Shum2", "Sh2Min", "Sh2Max", "Sh2OT", "Отстройка", "phase", "Фазовые шумы"),
    ("Фазовые шумы 4", "Shum3", "Sh3Min", "Sh3Max", "Sh3OT", "Отстройка", "phase", "Фазовые шумы"),
    ("Фазовые шумы 5", "Shum4", "Sh4Min", "Sh4Max", "Sh4OT", "Отстройка", "phase", "Фазовые шумы"),
]

# ---------------------------------------------------------------------------
# Температурные интервалы для строк, где это предусмотрено формой
# ---------------------------------------------------------------------------
# Ключ: (секция, метка_из_PARAM_GROUPS) -> (колонка T-начало, колонка T-конец)
TEMP_INTERVALS = {
    ("tch_params", "T экстремум min, C"): ("IT_Temp_A", "IT_Temp_B"),
    ("tch_params", "Монотонность ТЧХ"):    ("TmBegin",   "TmEnd"),
    ("nu_params",  "Rc/Rb max"):           ("TbBegin",   "TbEnd"),
}

# ---------------------------------------------------------------------------
# Списки опций для combo
# ---------------------------------------------------------------------------
GRAPH_F_OPTIONS = ["FS", "FL", "FL0", "FS+FL", "FS+FL0"]
LOADTYPE_OPTIONS = ["SERIES", "EQREACT", "PHYSICAL", "NUMERICAL", "0"]
TCHTYPE_OPTIONS = ["W2200", "KH7700", "TTS100", "W2200+KH7700", "Другой"]
AMP_UNIT_OPTIONS = ["dB", "dBc", "dBm", "%", "V"]