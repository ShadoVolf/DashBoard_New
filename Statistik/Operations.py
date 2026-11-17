import numpy
import pandas as pd
import numpy as np
from scipy.stats import gaussian_kde
from sqlalchemy import create_engine

import Statistik.Data
from Options import get_connection_string
# добавляем модульный кэш норм спецификаций
_SPC_NORMS_CACHE = {}   # spc_name -> DataFrame | None

# Удаляем все данные для данной мск
def delete_msk_data(msk):
    print("DELETE MSK DATA")
    msk_data = Statistik.Data.Data.get_msk_list()
    cur_slot_list = msk_data[msk]
    print(' DELETE MSK DATA" MSK', msk)

    for index, row in cur_slot_list.iterrows():
        if 'Mes_ID' in cur_slot_list.columns:
            data_full = Statistik.Data.Data.get_data(row['Name'])
            print('DELETE MSK DATA" Data ', 'Slot _', row['Name'], data_full.columns)
            if row['Mes_ID'] == 0:
                if not data_full.empty:
                    data_full.drop(data_full[data_full['MSK'] == msk].index, inplace=True)
            else:
                if not data_full.empty:
                    print("DELETE MSK DATA data ", data_full)
                    print("DELETE MSK DATA Mes ID", row['Mes_ID'])
                    print('DELETE MSK DATA data columns', data_full.columns)
                    print("DELETE MSK DATA size", data_full.shape[0])
                    print('De', data_full[data_full['Measure_ID'] == int(row['Mes_ID'])].index)
                    data_full.drop(data_full[data_full['Measure_ID'] == int(row['Mes_ID'])].index, inplace=True)
                    print("DELETE MSK DATA size after delete", data_full.shape[0])
            Statistik.Data.Data.set_data(row['Name'], data_full)


# Обновляет список графиков на экране
def update_plot_seris(dpg):
    print('UPADTE PLOT SERIES')
    sdf = dpg.get_all_items()
    active_slot_list = Statistik.Data.Data.get_active_data()
    print("SLot list", active_slot_list)
    for item in sdf:
        item_alies = dpg.get_item_alias(item)
        if item_alies is not None:
            if 'slot' in item_alies and '_slot' not in item_alies:
                print('Slot  ', item, item_alies)
                pltExist = False
                for index, row in active_slot_list.iterrows():
                    plot_name = 'slot' + str(row['Name']) + '_plot'
                    if item_alies == plot_name:
                        if 'Use' in active_slot_list.columns:
                            pltExist = row['Use']
                        else:
                            pltExist = True
                if not pltExist:
                    print('Delete item', item_alies)
                    dpg.delete_item(item_alies)


# Создате нормальное распределение с заданными парметрами
def create_normal_dev(mean, std):
    data = np.random.normal(mean, std, 1000)
    df = pd.DataFrame({'F': data})
    kde = gaussian_kde(df['F'])
    x = np.linspace(df['F'].min(), df['F'].max(), 5000)
    pdf = kde(x)
    return pdf, x

def get_pdf(slot_name, field, clear_data=True, msk=None):
    """Плотность вероятности (KDE) + статистика для слота.

    Args:
        slot_name: номер слота ('1', '2', '3', ...) или int.
        field:     параметр ('Fr', 'Fs', 'FL', 'R', 'C0', 'C1', 'L1', 'Q').
        clear_data: если True — выбросы IQR 1.5x отсекаются до построения KDE.
        msk:       имя МСК; если задано — фильтруем данные по этой МСК.

    Returns:
        (pdf, x, stat)
          pdf — list[float] или [] (пусто, если данных мало);
          x   — list[float] или [];
          stat — dict со статистикой (см. get_stat).
    """
    if msk is None:
        df = Statistik.Data.Data.get_data(slot_name)
    else:
        df = Statistik.Data.Data.get_data(slot_name)
        msk_list = Statistik.Data.Data.get_msk_list()
        msk_slot_list = msk_list[msk]
        msk_measure_id = msk_slot_list[
            msk_slot_list['Name'] == slot_name]

        try:
            mid = int(msk_measure_id['Mes_ID'].to_string(index=False))
        except (ValueError, TypeError, IndexError):
            mid = 0

        if mid != 0:
            df = df[df['Measure_ID'] == mid]
        else:
            # PSI: psidata.MSK содержит маски вида '26-6130****',
            # поэтому точное сравнение с '26-6130' не сработает.
            # Используем подстрочный поиск, как в load_psi_data().
            if 'MSK' in df.columns:
                mask = df['MSK'].astype(str).str.contains(
                    str(msk), na=False, case=False, regex=False)
                df = df[mask]

    # защита от пустого df и отсутствия колонки
    if df is None or df.empty or field not in df.columns:
        return [], [], get_stat(df if df is not None else pd.DataFrame(),
                                field, clear_data)

    df = df.copy()

    # режим «без ёмкости»: FL считаем по Fr
    if (Statistik.Data.Data.get_without_cap_mode()
            and field.lower() == 'fl' and 'Fr' in df.columns):
        df[field] = pd.to_numeric(df['Fr'], errors='coerce')
    else:
        df[field] = pd.to_numeric(df[field], errors='coerce')

    df = df[df[field].notna()]
    df_clened = df[df[field] < 1e12]

    if df_clened.shape[0] > 2:
        if clear_data:
            Q1 = df_clened[field].quantile(0.25)
            Q3 = df_clened[field].quantile(0.75)
            IQR = Q3 - Q1
            df_clened = df_clened[
                (df_clened[field] >= (Q1 - 1.5 * IQR)) &
                (df_clened[field] <= (Q3 + 1.5 * IQR))
            ]

        # KDE требует минимум 2 различных значений
        if df_clened[field].nunique() < 2:
            pdf = []
            x = []
        else:
            kde = gaussian_kde(df_clened[field])
            x = np.linspace(df_clened[field].min(),
                            df_clened[field].max(), 1000)
            pdf = kde(x)
            Statistik.Data.Data.set_axis_limits(x, pdf)
    else:
        pdf = []
        x = []

    return pdf, x, get_stat(df, field, clear_data)
# Расчитывает PDF функцию для заданной колонки ДФ
def get_pdf_1(slot_name, field, clear_data=True, msk=None):
    """
    :param msk: str
    :param clear_data: Boolean # Включает алгорим очистки данных от аномальных значений
    :param field: str # Название парметра для вывода на график
    :param slot_name: # Номер слота
    """
    stat_data = {}
    if msk is None:
        df = Statistik.Data.Data.get_data(slot_name)
    else:
        data_value = Statistik.Data.Data.data_full
        print('data', data_value)
        print("field", field)
        print("slot", slot_name)
        df = Statistik.Data.Data.get_data(slot_name)
        print("Data original", df.shape, df.columns)
        msk_list = Statistik.Data.Data.get_msk_list()
        msk_slot_list = msk_list[msk]
        msk_measure_id = msk_slot_list[msk_slot_list['Name'] == slot_name]
        print("Measure_ID=", msk_measure_id['Mes_ID'].to_string(index=False))
        print('DF colums', df.columns)
        if int(msk_measure_id['Mes_ID'].to_string(index=False)) != 0:
            df = df[df['Measure_ID'] == int(msk_measure_id['Mes_ID'].to_string(index=False))]
            print('Measure ID==', msk_measure_id['Mes_ID'].to_string(index=False))
        else:
            print("MSK data", df.shape)
            df = df[df['MSK'] == str(msk)]
            print("MSK data", df.shape)

    # FIX: защита от пустого df и отсутствия колонки — раньше падало на astype().
    if df is None or df.empty or field not in df.columns:
        return [], [], get_stat(df if df is not None else pd.DataFrame(),
                                field, clear_data)

    # FIX: astype(float) на колонке с 'nan'-строками бросает ValueError.
    df = df.copy()
    # Настройка без емкости: для Fl использовать данные Fr
    if (Statistik.Data.Data.get_without_cap_mode()
            and field.lower() == 'fl' and 'Fr' in df.columns):
        df[field] = pd.to_numeric(df['Fr'], errors='coerce')
    df[field] = pd.to_numeric(df[field], errors='coerce')
    df = df[df[field].notna()]
    df_clened = df[df[field] < 1e12]
    print("DF SIZE", df_clened.shape)
    if df_clened.shape[0] > 2:
        if clear_data:
            Q1 = df_clened[field].quantile(0.25)
            Q3 = df_clened[field].quantile(0.75)
            IQR = Q3 - Q1
            df_clened = df_clened[(df_clened[field] >= (Q1 - 1.5 * IQR)) &
                                  (df_clened[field] <= (Q3 + 1.5 * IQR))]
        # KDE требует минимум 2 различных значения
        if df_clened[field].nunique() < 2:
            pdf = []
            x = []
        else:
            kde = gaussian_kde(df_clened[field])
            x = np.linspace(df_clened[field].min(), df_clened[field].max(), 1000)
            pdf = kde(x)
            Statistik.Data.Data.set_axis_limits(x, pdf)
    else:
        pdf = []
        x = []
    return pdf, x, get_stat(df, field, clear_data)


# Расчет статистики для заданного датафрейм
def get_stat(df, field, clear_data=True):
    # FIX: порог 100000 отсекал все реальные Fr (Гц ~ 1e6-1e8). Согласуем
    # с порогом очистки в get_pdf.
    empty = {'Max': 0, 'Min': 0, 'Mean': 0, 'Median': 0, 'StDev': 0,
             'Lower_bound': 0, 'Upper_bound': 0,
             'Anomal_count': 0, 'Bad_Count': 0, 'Count': 0, 'Out': 0}
    if df is None or df.empty or field not in df.columns:
        return empty

    df = df.copy()
    if (Statistik.Data.Data.get_without_cap_mode()
            and field.lower() == 'fl' and 'Fr' in df.columns):
        df[field] = pd.to_numeric(df['Fr'], errors='coerce')
    df[field] = pd.to_numeric(df[field], errors='coerce')
    df = df[df[field].notna()]
    df = df[df[field] < 1e12]

    if df.shape[0] > 2:
        if clear_data:
            Q1 = df[field].quantile(0.25)
            Q3 = df[field].quantile(0.75)
            IQR = Q3 - Q1
            df = df[(df[field] >= (Q1 - 1.5 * IQR)) &
                    (df[field] <= (Q3 + 1.5 * IQR))]
            print('Cleared DF', df)
            print('IQR', IQR, 'Q1', Q1, 'Q3', Q3)
        Q1 = df[field].quantile(0.25)
        Q3 = df[field].quantile(0.75)
        IQR = Q3 - Q1

        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        anomalies = df[(df[field] < lower_bound) | (df[field] > upper_bound)]
        count_bad = 0
        out = 0
        if Statistik.Data.Data.get_spc_norm_status():
            spc_norm = Statistik.Data.Data.get_spc_norm(field)
            if spc_norm[field + 'max'] is not None and spc_norm[field + 'min'] is not None:
                norm_max = float(spc_norm[field + 'max'])
                norm_min = float(spc_norm[field + 'min'])
                count_bad = len(df[(df[field] > norm_max) | (df[field] < norm_min)])
                out = ((df.shape[0] - count_bad) / df.shape[0]) * 100
            elif spc_norm[field + 'max'] is None and spc_norm[field + 'min'] is not None:
                norm_min = float(spc_norm[field + 'min'])
                count_bad = len(df[df[field] < norm_min])
                out = ((df.shape[0] - count_bad) / df.shape[0]) * 100
            elif spc_norm[field + 'max'] is not None and spc_norm[field + 'min'] is None:
                norm_max = float(spc_norm[field + 'max'])
                count_bad = len(df[df[field] > norm_max])
                out = ((df.shape[0] - count_bad) / df.shape[0]) * 100
            else:
                count_bad = 0
                out = 100
        result = {'Max': df[field].max(), 'Min': df[field].min(),
                  'Mean': df[field].mean(axis=0), 'Median': df[field].median(axis=0),
                  'StDev': df[field].std(),
                  'Lower_bound': lower_bound, 'Upper_bound': upper_bound,
                  'Anomal_count': anomalies.shape[0], 'Bad_Count': count_bad,
                  'Count': df.shape[0], 'Out': out}
    else:
        result = empty
    return result


# добавляет данные на график распределения
def add_to_plot(dpg, x, y, slot_name):
    update_plot_seris(dpg)
    active_slot_list = Statistik.Data.Data.get_active_data()
    measure_type_list = Statistik.Data.Data.get_measure_type_list()
    if slot_name in active_slot_list['Name'].to_list():
        plot_name = 'slot' + str(slot_name) + '_plot'
        slot_data = active_slot_list[active_slot_list['Name'] == slot_name]
        print('Active_slot_list', active_slot_list)
        print('measure_type_list', measure_type_list)
        print('Slot Type', slot_data['Value'])
        mes_type_current = measure_type_list[
            measure_type_list['ID'] == int(slot_data['Value'].to_string(index=False))]
        print(mes_type_current['Name'].to_string(index=False))
        plot_label = mes_type_current['Name'].to_string(index=False)
        sdf = dpg.get_all_items()
        pltExist = False
        for item in sdf:
            item_alies = dpg.get_item_alias(item)
            if item_alies == plot_name:
                pltExist = True
        if pltExist:
            dpg.set_value(plot_name, [x, y])
            dpg.set_item_label(plot_name, plot_label)
        else:
            dpg.add_line_series(x, y, parent="y_axis", tag=plot_name, label=plot_label)
    axis_limits = Statistik.Data.Data.get_axis_limits()
    dpg.set_axis_limits("y_axis", axis_limits['Y_Min'] - 0.2 * axis_limits['Y_Min'],
                        axis_limits['Y_Max'] + 0.2 * axis_limits['Y_Max'])
    dpg.set_axis_limits("x_axis", axis_limits['X_Min'] - 0.3 * axis_limits['X_Min'],
                        axis_limits['X_Max'] + 0.3 * axis_limits['X_Max'])
    dpg.set_axis_limits_auto("x_axis")
    dpg.set_axis_limits_auto("y_axis")
    dpg.fit_axis_data('x_axis')
    dpg.fit_axis_data('y_axis')


def add_to_plot_msk(dpg, x, y, slot_name, msk):
    active_slot_list = Statistik.Data.Data.get_active_data()
    print('ADD to PLOT MSK')
    print('Active_slot_list', active_slot_list)
    print("Slot", slot_name)
    if int(slot_name) in active_slot_list['Name'].to_list():
        plot_name = 'msk_id' + str(msk) + '_plot'
        print('Active_slot_list', active_slot_list)
        plot_label = msk
        sdf = dpg.get_all_items()
        pltExist = False
        for item in sdf:
            item_alies = dpg.get_item_alias(item)
            # FIX: item_alies может быть None — 'in None' бросает TypeError.
            # Кроме того, раньше delete(plot_name) вызывался много раз в цикле
            # для одной и той же серии. Удаляем один раз через does_item_exist.
            if item_alies is None:
                continue
            if item_alies == 'y_axis_msk':
                pltExist = True
        if dpg.does_item_exist(plot_name):
            dpg.delete_item(plot_name)

        if pltExist:
            dpg.add_line_series(x, y, parent="y_axis_msk", tag=plot_name, label=plot_label)
            axis_limits = Statistik.Data.Data.get_axis_limits()
            dpg.set_axis_limits("y_axis_msk",
                                axis_limits['Y_Min'] - 0.2 * axis_limits['Y_Min'],
                                axis_limits['Y_Max'] + 0.2 * axis_limits['Y_Max'])
            dpg.set_axis_limits("x_axis_msk",
                                axis_limits['X_Min'] - 0.3 * axis_limits['X_Min'],
                                axis_limits['X_Max'] + 0.3 * axis_limits['X_Max'])
            dpg.set_axis_limits_auto("x_axis_msk")
            dpg.set_axis_limits_auto("y_axis_msk")
            dpg.fit_axis_data('x_axis_msk')
            dpg.fit_axis_data('y_axis_msk')


# Возвращает список типов резонаторов
def get_resonator_types():
    engine = create_engine(str(get_connection_string()))
    sql = "Select `ID`, `Name` from resonatortype_rq order by `Name`"
    df = pd.read_sql_query(sql, engine)
    return df["Name"].tolist()


# Получает список возможных номиналов резоанторов из таблицы номнеклатуры (mysql)
def get_resonator_nominals_list(resonator_type=None):
    engine = create_engine(str(get_connection_string()))
    res_id = 0
    if resonator_type is not None:
        res_id = get_resonator_type_id(resonator_type)
    if resonator_type is None:
        sql = "Select distinct `частота`, `Гармоника` from nomeklatura_rk order by `частота`"
    else:
        sql = "Select distinct `частота`, `Гармоника` from nomeklatura_rk where `РКНомер`= '" + str(
            res_id) + "' order by`частота`"
    df_nom = pd.read_sql_query(sql, engine)
    df_nom['Номинал'] = np.where(
        df_nom['Гармоника'] > 1,
        (df_nom['частота'] / 1000).astype(str) + "M",
        df_nom['частота'].astype(str) + "K"
    )
    return df_nom['Номинал'].tolist()


# Возвращает лист номенклатур
def get_resonator_nom_list(resonator_type=None, resonator_nominal=None):
    sql = ''
    engine = create_engine(str(get_connection_string()))
    if resonator_type is not None and (resonator_nominal is None or resonator_nominal == 'nanK'):
        res_id = get_resonator_type_id(resonator_type)
        sql = ("Select `номенклатура`, `наименование`,  `РКНомер`,`частота`, `Гармоника` from nomeklatura_rk where "
               "`РКНомер`='" + str(res_id) + "' order by `наименование`")
    elif resonator_type is not None and resonator_nominal is not None and resonator_nominal != 'nanK':
        res_id = get_resonator_type_id(resonator_type)
        res_nom = get_Nominal_Value(resonator_nominal)
        sql = ("Select `номенклатура`, `наименование`,  `РКНомер`,`частота`, `Гармоника` from nomeklatura_rk where "
               "`РКНомер`='" + str(res_id) + "' and `частота` between " + str(
            modify_last_digit(res_nom[0], 'subtract')) + " and " + str(
            modify_last_digit(res_nom[0], 'add')) + "  order by `наименование`")
    elif resonator_type is None and resonator_nominal is not None and resonator_nominal != 'nanK':
        res_nom = get_Nominal_Value(resonator_nominal)
        sql = ("Select `номенклатура`, `наименование`,  `РКНомер`,`частота`, `Гармоника` from nomeklatura_rk where "
               "`Гармоника`='" + str(res_nom[1]) + "' and `частота` between " + str(
            modify_last_digit(res_nom[0], 'subtract')) + " and " + str(
            modify_last_digit(res_nom[0], 'add')) + "  order by `наименование`")
    elif resonator_type is None and resonator_nominal is None:
        sql = ("Select `номенклатура`, `наименование`,  `РКНомер`,`частота`, `Гармоника` from nomeklatura_rk "
               "order by `наименование`")
    print(resonator_nominal)

    df = pd.read_sql_query(sql, engine)
    return df['наименование'].tolist()


# Возвращает код по типу резонатора
def get_resonator_type_id(resonator_type):
    engine = create_engine(str(get_connection_string()))
    sql_type = "Select `ID`, `Name` from resonatortype_rq where `Name`='" + str(resonator_type) + "'"
    df = pd.read_sql_query(sql_type, engine)
    return df["ID"][0]


# Функция для разделения строки
def split_string(s):
    return s[:-1], s[-1]


# Возвращает численное значение номинальной частоты в кГц
def get_Nominal_Value(nom_str):
    if nom_str == 'nanK':
        return None, None
    tem = split_string(nom_str)
    garmonica = 1
    if tem[1] == 'M':
        nom_value = float(tem[0]) * 1000
        garmonica = 3
    elif tem[1] == 'K':
        nom_value = float(tem[0])
        garmonica = 1
    else:
        nom_value = 0
    return nom_value, garmonica


def modify_last_digit(number, operation):
    number_str = str(number)
    point_index = number_str.find('.')

    if point_index != -1:
        last_digit = int(number_str[point_index + 1]) if point_index + 1 < len(number_str) else 0
        if operation == 'add':
            last_digit = (last_digit + 1) % 10
            new_number_str = number_str[:point_index + 1] + str(last_digit)
            return float(new_number_str)
        elif operation == 'subtract':
            if last_digit >= 1:
                last_digit = (last_digit - 1) % 10
                new_number_str = number_str[:point_index + 1] + str(last_digit)
                return float(new_number_str)
            else:
                last_digit = (last_digit - 1) % 10
                new_number_str = number_str[:point_index + 1] + str(last_digit)
                return float(new_number_str) - 1
        else:
            raise ValueError("Operation must be 'add' or 'subtract'")
    else:
        if operation == 'add':
            return number + 1
        elif operation == 'subtract':
            return number - 1
        else:
            raise ValueError("Operation must be 'add' or 'subtract'")


# Получаем список мск в формате датафрейм
def get_msk(nomenklatura=None):
    sql = ''
    engine = create_engine(str(get_connection_string()))
    if nomenklatura is None:
        sql = "Select `мскРеал`, `мск`, `запущено шт` from `msk_rk` order by `мскРеал`"
    else:
        nom_id = get_nomenklatura_id(nomenklatura)
        sql = "Select `мскРеал`, `мск`, `запущено шт`,`дата запуска` from `msk_rk` where `КодНоменклатуры`='" + str(
            nom_id) + "' order by `мскРеал`"
    df = pd.read_sql_query(sql, engine)
    return df


# Возвращает значение кода по названию номенклатуры RQ
def get_nomenklatura_id(nomenklatura):
    engine = create_engine(str(get_connection_string()))
    sql = "Select `номенклатура`,`наименование` from `nomeklatura_rk` where `наименование`='" + nomenklatura + "'"
    df = pd.read_sql_query(sql, engine)
    return df['номенклатура'][0]


# Возвращает список типов измерений из таблицы final_plating_measure_type
def get_measure_type():
    df = Statistik.Data.Data.get_measure_type_list()
    return df['Name'].tolist()


# Возвращает список парметров измерения
def get_measure_parameters(type_s='1'):
    engine = create_engine(str(get_connection_string()))
    sql = "Select `Name`, `units` from `measure_parameters` where `Type` ='" + type_s + "' order by `ID`"
    df = pd.read_sql_query(sql, engine)
    return df['Name'].tolist(), df['units'].tolist()

def _dedup_psi_last_per_n(df):
    """PSI: оставить на каждый N одну строку - последнюю по Date.

    final_plating НЕ трогаем. Применяется только к psidata.
    """
    if df is None or df.empty:
        return df
    if 'N' not in df.columns or 'Date' not in df.columns:
        return df
    try:
        df = df.copy()
        df['_dt'] = pd.to_datetime(df['Date'], errors='coerce')
        df = df.sort_values('_dt', ascending=False, na_position='last')
        before = len(df)
        df = df.drop_duplicates(subset='N', keep='first')
        df = df.drop(columns=['_dt'])
        print(f'[_dedup_psi_last_per_n] {before} -> {len(df)}')
        return df
    except Exception as e:
        print(f'[_dedup_psi_last_per_n] error: {e}')
        return df
# Загрузка данных измерений
def load_data(msk, current_slot_list):
    """Загрузить данные по МСК в слоты.

    Args:
        msk: имя МСК.
        current_slot_list: DataFrame с колонками Name, Value, Use, Mes_ID.
            Для каждого слота с Use=True выполняется запрос:
              * final_plating (Value != 6):
                  - если Mes_ID != 0 -> WHERE Measure_ID = ...
                  - иначе            -> WHERE MSK=... AND Measure_Type=...
              * psidata (Value == 6):
                  - если Mes_ID != 0 -> WHERE Measure_ID = ...
                  - иначе            -> для каждого Measure_ID из
                                        load_psi_data(msk)
            PSI-результат дедуплицируется: на каждый N остаётся только
            последняя запись по Date (см. _dedup_psi_last_per_n).
            final_plating НЕ дедуплицируется - там все замеры важны.

    Побочные эффекты:
        * Data.add_msk_to_list(msk, current_slot_list) - регистрирует МСК;
        * Data.append_data(...) - накапливает данные в data_full[slot];
        * Data.active_data_list обновляется (Use=True, Count=N).
    """
    engine = create_engine(str(get_connection_string()))
    Statistik.Data.Data.add_msk_to_list(msk, current_slot_list)
    active_slot_list = Statistik.Data.Data.get_active_data()
    print('Load_data', active_slot_list)

    for index, row in current_slot_list.iterrows():
        if not row.get('Use'):
            continue

        slot_name = row['Name']
        slot_value = row['Value']
        mes_id = row.get('Mes_ID', 0)

        # ============================================================
        # final_plating: все замеры, без дедупликации
        # ============================================================
        if slot_value != 6:
            try:
                if mes_id != 0:
                    sql = ("Select * from `final_plating` "
                           "where `Measure_ID`='" + str(mes_id) + "' "
                           "order by `ID`")
                else:
                    sql = ("Select * from `final_plating` "
                           "where `MSK`='" + str(msk) + "' "
                           "and `Measure_Type`='" + str(slot_value) + "' "
                           "order by `ID`")
                df = pd.read_sql_query(sql, engine)
                print("Load Final Plating", 'Slot=', slot_name,
                      'shape=', df.shape)

                if df is not None and not df.empty:
                    Statistik.Data.Data.append_data(
                        data_current=df, slot_name=slot_name)
                else:
                    print(f"Load Final Plating Slot={slot_name}: "
                          f"пустой DataFrame, пропуск")
            except Exception as e:
                print(f"[load_data] final_plating slot={slot_name} "
                      f"MSK={msk}: {e}")

        # ============================================================
        # psidata: дедуп по N (последняя запись по Date)
        # ============================================================
        else:
            try:
                if mes_id != 0:
                    sql = (
                        "Select `N`,`MSK`,`F`,`R`,`C0`,`Cq`,`L`,`Q`,"
                        "`Date`,`Status`,`Nominal`, `Measure_ID` "
                        "from `psidata` "
                        "where `Measure_ID`='" + str(mes_id) + "'"
                    )
                    df = pd.read_sql_query(sql, engine)
                    df = _dedup_psi_last_per_n(df)
                    print("Load PSI (single Measure_ID)",
                          'Slot=', slot_name, 'shape=', df.shape)

                    if df is not None and not df.empty:
                        Statistik.Data.Data.append_data(
                            data_current=df, slot_name=slot_name)
                    else:
                        print(f"Load PSI Slot={slot_name}: "
                              f"пустой DataFrame, пропуск")
                else:
                    # без Mes_ID - тянем все Measure_ID по МСК
                    mes_list = load_psi_data(msk)
                    if not mes_list:
                        print(f"Load PSI Slot={slot_name}: "
                              f"нет Measure_ID для MSK={msk}")
                        continue

                    all_frames = []
                    for i in mes_list:
                        sql = (
                            "Select `N`,`MSK`,`F`,`R`,`C0`,`Cq`,`L`,`Q`,"
                            "`Date`,`Status`,`Nominal`, `Measure_ID` "
                            "from `psidata` "
                            "where `Measure_ID`='" + str(i) + "'"
                        )
                        try:
                            part = pd.read_sql_query(sql, engine)
                            if part is not None and not part.empty:
                                all_frames.append(part)
                        except Exception as e:
                            print(f"[load_data] psidata "
                                  f"Measure_ID={i} MSK={msk}: {e}")

                    if not all_frames:
                        print(f"Load PSI Slot={slot_name}: "
                              f"нет данных ни по одному Measure_ID")
                        continue

                    df = pd.concat(all_frames, ignore_index=True)
                    # ВАЖНО: дедуп по N применяется после объединения
                    # всех Measure_ID, иначе последний замер может
                    # потеряться между разными партиями.
                    df = _dedup_psi_last_per_n(df)
                    print("Load PSI (all Measure_ID)",
                          'Slot=', slot_name, 'shape=', df.shape)

                    if df is not None and not df.empty:
                        Statistik.Data.Data.append_data(
                            data_current=df, slot_name=slot_name)
                    else:
                        print(f"Load PSI Slot={slot_name}: "
                              f"пустой DataFrame после дедупа, пропуск")
            except Exception as e:
                print(f"[load_data] psidata slot={slot_name} "
                      f"MSK={msk}: {e}")

    print('Load_data done. data_full keys:', list(
        Statistik.Data.Data.data_full.keys()))
def load_data_1(msk, current_slot_list):
    engine = create_engine(str(get_connection_string()))
    measure_types_filtered = None
    Statistik.Data.Data.add_msk_to_list(msk, current_slot_list)
    active_slot_list = Statistik.Data.Data.get_active_data()
    print('Load_data', active_slot_list)
    for index, row in current_slot_list.iterrows():
        if row['Use']:
            if row['Value'] != 6:
                if row['Mes_ID'] != 0:
                    sql = "Select * from `final_plating` where `Measure_ID`='" + str(row['Mes_ID']) + "' order by `ID`"
                else:
                    sql = ("Select * from `final_plating` where `MSK`='" + msk + "' and `Measure_Type`='"
                           + str(row['Value']) + "' order by `ID`")
                df = pd.read_sql_query(sql, engine)
                Statistik.Data.Data.append_data(data_current=df, slot_name=row['Name'])
                print("Load Final Plating", 'Slot=', row['Name'])
                print(df.shape)
            else:
                if row["Mes_ID"] != 0:
                    sql = ("Select `N`,`MSK`,`F`,`R`,`C0`,`Cq`,`L`,`Q`,`Date`,`Status`,`Nominal`, `Measure_ID` from "
                           "`psidata` where"
                           "`Measure_ID`='" + str(row["Mes_ID"]) + "'")
                    df = pd.read_sql_query(sql, engine)
                    Statistik.Data.Data.append_data(data_current=df, slot_name=row['Name'])
                else:
                    mes_list = load_psi_data(msk)
                    for i in mes_list:
                        sql = (
                            "Select `N`,`MSK`,`F`,`R`,`C0`,`Cq`,`L`,`Q`,`Date`,`Status`,`Nominal`, `Measure_ID` "
                            "from"
                            "`psidata` where"
                            "`Measure_ID`='" + str(i) + "'")
                        df = pd.read_sql_query(sql, engine)
                        Statistik.Data.Data.append_data(data_current=df, slot_name=row['Name'])
    print(Statistik.Data.Data.data_full)


# Проверяет набор данных настройки для задданной мск и выдает список имеющихcя замеров
def test_msk_plating_data(msk):
    engine = create_engine(str(get_connection_string()))
    sql = "Select distinct `Measure_Type`, `Measure_ID` from `final_plating` where `MSK`='" + msk + "' order by `ID`"
    df = pd.read_sql_query(sql, engine)
    list_temp = df['Measure_Type'].unique().tolist()
    measure_types = Statistik.Data.Data.get_measure_type_list()
    measure_types_filtered = measure_types[measure_types['ID'].isin(list_temp)]
    return measure_types_filtered['Name'].tolist(), df


# Получает количество замеров по мск
def get_msk_plating_count(msk, measure_type=0, measure_id=0):
    sql = ''
    engine = create_engine(str(get_connection_string()))
    if measure_type == 0 and measure_id == 0:
        sql = "Select count(`ID`) as `count` from `final_plating` where `MSK`='" + msk + "'"
    elif measure_type != 0 and measure_id == 0:
        sql = "Select count(`ID`) as `count` from `final_plating` where `MSK`='" + msk + "' and `Measure_Type`='" + str(
            measure_type) + "'"
    elif measure_type != 0 and measure_id != 0:
        sql = "Select count(`ID`) as `count` from `final_plating` where `MSK`='" + msk + "' and `Measure_Type`='" + str(
            measure_type) + "' and `Measure_ID`='" + str(measure_id) + "'"
    elif measure_type == 0 and measure_id != 0:
        sql = ("Select count(`ID`) as `count` from `final_plating` where `MSK`='" + msk +
               "' and `Measure_ID`='" + str(measure_id) + "'")
    df = pd.read_sql_query(sql, engine)
    str_count = df['count'].to_string(index=False)
    return str_count


# Получает замеры ПСИ для заданного значения МСК

def load_psi_data(msk):
    """Оптимизированная версия: один запрос вместо N по номерам и MSK."""
    numbers_list = get_msk_numbers_list(msk)
    engine = create_engine(str(get_connection_string()))
    result_list = []

    # --- один запрос вместо цикла по numbers_list ---
    if numbers_list:
        placeholders = ','.join(['%s'] * len(numbers_list))
        sql = ("Select distinct `Measure_ID` from `psidata` "
               "where `N` IN (" + placeholders + ")")
        df = pd.read_sql_query(sql, engine, params=tuple(numbers_list))
        if not df.empty:
            result_list += df['Measure_ID'].tolist()

    # --- выборка по spc и MSK-подстроке: один запрос на весь набор ---
    spc = Statistik.Data.Data.get_spc_value()
    if spc != '':
        sql = "Select distinct `MSK` from `psidata` where `spc` = %s"
        df = pd.read_sql_query(sql, engine, params=(spc,))
    else:
        sql = "Select distinct `MSK` from `psidata`"
        df = pd.read_sql_query(sql, engine)

    if not df.empty:
        filtered = df[df['MSK'].str.contains(msk, na=False, case=False)]
        if not filtered.empty:
            msk_strings = filtered['MSK'].tolist()
            placeholders = ','.join(['%s'] * len(msk_strings))
            sql = ("Select distinct `Measure_ID` from `psidata` "
                   "where `MSK` IN (" + placeholders + ")")
            df_m = pd.read_sql_query(sql, engine, params=tuple(msk_strings))
            if not df_m.empty:
                result_list += df_m['Measure_ID'].tolist()

    return list(set(result_list))

def load_psi_data_1(msk):
    numbers_list = get_msk_numbers_list(msk)
    engine = create_engine(str(get_connection_string()))
    result_list = []
    print("LOAD PSI DATA")
    if len(numbers_list) > 0:
        for number in numbers_list:
            sql = "Select distinct `Measure_ID`, `N`, `MSK` from `psidata` where `N`='" + number + "'"
            df = pd.read_sql_query(sql, engine)
            if not df.empty:
                result_list += df['Measure_ID'].to_list()
    spc = Statistik.Data.Data.get_spc_value()
    print('SPC ', spc)
    if spc != '':
        sql = "Select distinct `MSK` from `psidata` where `spc`='" + spc + "' order by `MSK`"
    else:
        sql = "Select distinct `MSK` from `psidata`"
    df = pd.read_sql_query(sql, engine)
    filtered_df = df[df['MSK'].str.contains(msk, na=False, case=False)]
    for index, msk_str in filtered_df.iterrows():
        sql = "Select `Measure_ID` from `psidata` where `MSK`='" + str(msk_str["MSK"]) + "'"
        df_m = pd.read_sql_query(sql, engine)
        if not df_m.empty:
            result_list += df_m['Measure_ID'].to_list()
    unique_values = list(set(result_list))
    print('get uniq', unique_values)
    result_list = unique_values.copy()
    return result_list


# Получает номера текущей мск
def get_msk_numbers_list(msk):
    result_list = []
    engine = create_engine(str(get_connection_string()))
    sql = "Select `MSK`,`Type`,`Begin`, `End` from `marker` where `MSK`='" + msk + "'"
    df = pd.read_sql_query(sql, engine)
    if not df.empty:
        begin = df['Begin'][0]
        end = df['End'][0]
        serial = begin[:2]
        begin_f = int(begin[2:])
        end_f = int(end[2:])
        for i in range(begin_f, end_f):
            str_i = str(i)
            if i < 10:
                str_i = '0' + str_i
            elif i < 100:
                str_i = '00' + str_i
            elif i < 1000:
                str_i = '000' + str_i
            else:
                str_i = str_i
            result_list.append(serial + str_i)
    return result_list


'''
Тестовый вариант функции (НЕ ПРОВЕРЕН)
'''


def get_msk_numbers_list_test(msk):
    engine = create_engine(str(get_connection_string()))
    query = f"SELECT `Begin`, `End` FROM `marker` WHERE `MSK` = '{msk}' LIMIT 1"
    df = pd.read_sql(query, engine)

    if df.empty:
        return []

    begin, end = df.iloc[0]['Begin'], df.iloc[0]['End']
    serial, start = begin[:2], int(begin[2:])
    return [f"{serial}{i:04d}" for i in range(start, int(end[2:]))]


# Получаем количество элементов для ПСИ по номеру мск и ид  замера
def get_msk_psi_count(msk, measure_id=0):
    sql = ''
    df = pd.DataFrame()
    engine = create_engine(str(get_connection_string()))
    str_count = ''
    if measure_id == 0:
        count = 0
        mes_id_list = load_psi_data(msk)
        for i in mes_id_list:
            sql = "Select count(`ID`) as `count` from `psidata` where  `Measure_ID`='" + str(i) + "'"
            df = pd.read_sql_query(sql, engine)
            if not df.empty:
                count = count + int(df['count'].to_string(index=False))
        str_count = str(count)
    else:
        sql = "Select count(`ID`) as `count` from `psidata` where  `Measure_ID`='" + str(
            measure_id) + "'"
        df = pd.read_sql_query(sql, engine)
        str_count = df['count'].to_string(index=False)
    return str_count


# Получить спецификацию и дату измерения для ПСИ по ид замера
def get_msk_psi_spc(measure_id):
    engine = create_engine(str(get_connection_string()))
    sql = "Select distinct `spc`, `Date`, `MSK`  from `psidata` where  `Measure_ID`='" + measure_id + "'"
    df = pd.read_sql_query(sql, engine)
    return df


# Получаем нормы для заданной спецификации
def get_spc_norms(spc, measure_id: str = None):
    """Обёрнута кэшем по имени спецификации."""
    engine = create_engine(str(get_connection_string()))

    nom_df = pd.read_sql_query(
        "Select `номенклатура`, `наименование` from `nomeklatura_rk` "
        "where `наименование` = %s", engine, params=(spc,))
    if nom_df.empty:
        Statistik.Data.Data.set_spc_norm_status(False)
        return
    nom_id = str(nom_df.loc[0, 'номенклатура'])

    # 1) имя спецификации из маппинга
    df = pd.read_sql_query(
        "Select `SpcName` from `nomeklatura_rk_psi` "
        "where `NomenklaturaID` = %s", engine, params=(nom_id,))
    spc_name = df.loc[0, 'SpcName'] if not df.empty else None
    spc_exist = not df.empty

    # 2) fallback по Measure_ID
    if spc_name is None and measure_id is not None:
        df = pd.read_sql_query(
            "Select distinct `spc` from `psidata` where `Measure_ID` = %s",
            engine, params=(str(measure_id),))
        if not df.empty:
            spc_name = df.loc[0, 'spc']

    if spc_name is None:
        Statistik.Data.Data.set_spc_norm_status(False)
        return

    # --- кэш ---
    if spc_name in _SPC_NORMS_CACHE:
        cached = _SPC_NORMS_CACHE[spc_name]
        if cached is not None:
            Statistik.Data.Data.add_spc_norm(cached)
            Statistik.Data.Data.set_spc_norm_status(True)
        else:
            Statistik.Data.Data.set_spc_norm_status(False)
        return

    Statistik.Data.Data.set_spc_value(spc_name)
    spec_df = pd.read_sql_query(
        "Select `C0`,`Cq`, `R`,`F`,`Q`, `L`, "
        "`Fmax`,`Fmin`,`Rmax`, `Rmin`,`C0max`,`C0min`,`Cqmax`, `Cqmin`, "
        "`Lmax`,`Lmin`, `Qmax`, `Qmin`, `Name`, `ID` "
        "from `specification` where `Name` = %s",
        engine, params=(spc_name,))

    if spec_df.empty:
        _SPC_NORMS_CACHE[spc_name] = None
        Statistik.Data.Data.set_spc_norm_status(False)
        return

    _SPC_NORMS_CACHE[spc_name] = spec_df
    Statistik.Data.Data.add_spc_norm(spec_df)
    Statistik.Data.Data.set_spc_norm_status(True)

    # однократная запись маппинга
    if not spc_exist:
        exists = pd.read_sql_query(
            "SELECT 1 FROM `nomeklatura_rk_psi` "
            "WHERE `NomenklaturaID` = %s LIMIT 1",
            engine, params=(nom_id,))
        if exists.empty:
            pd.DataFrame([{
                'SpcName': spec_df.loc[0, 'Name'],
                'SpcID': spec_df.loc[0, 'ID'],
                'NomenklaturaID': nom_df.loc[0, 'номенклатура'],
                'NomenklaturaName': nom_df.loc[0, 'наименование'],
            }]).to_sql('nomeklatura_rk_psi', engine,
                       schema='coordinator', if_exists='append', index=False)

def get_spc_norms_1(spc, measure_id: str = None):
    engine = create_engine(str(get_connection_string()))
    print('GET SPC NORM')
    sql = "Select `номенклатура`, `наименование` from `nomeklatura_rk` where `наименование` ='" + spc + "'"
    print('SQL nomenkaltura_rk', sql)
    nom_rq = pd.read_sql_query(sql, engine)
    print("NOmenklatura RQ", nom_rq)
    if not nom_rq.empty:
        sql = ("Select `SpcName`, `SpcID`, `NomenklaturaID`, `NomenklaturaName` from `nomeklatura_rk_psi` where "
               "`NomenklaturaID`='" + str(nom_rq.loc[0, 'номенклатура']) + "'")
        print('SQL nomeklatura_rk_psi', sql)
        df = pd.read_sql_query(sql, engine)
        print('nomeklatura_rk_psi data', df)
        spc_rq_str = ''
        spc_losd = False
        spc_rq_exist = False
        if not df.empty:
            spc_rq_str = df.loc[0, 'SpcName']
            spc_losd = spc_rq_exist = True
            print("Spc name ", spc_rq_str)
        if not spc_losd and measure_id is not None:
            print('measure ID', measure_id)
            sql = "Select distinct `spc` from `psidata` where `Measure_ID`='" + str(measure_id) + "'"
            print('Psi data SQL', sql)
            df = pd.read_sql_query(sql, engine)
            print('')
            if not df.empty:
                spc_rq_str = df.loc[0, 'spc']
                spc_losd = True
        if spc_losd:
            sql = ("Select `C0`,`Cq`, `R`,`F`,`Q`, `L`, `Fmax`,`Fmin`,`Rmax`, `Rmin`,`C0max`,`C0min`,`Cqmax`, `Cqmin`, "
                   "`Lmax`,`Lmin`, `Qmax`, `Qmin`, `Name`, `ID` from `specification` where `Name`='" + spc_rq_str + "'")
            print('SQL', sql)
            Statistik.Data.Data.set_spc_value(spc_rq_str)
            df = pd.read_sql_query(sql, engine)
            if not df.empty:
                Statistik.Data.Data.add_spc_norm(df)
                if not spc_rq_exist:
                    # FIX: перед INSERT проверяем существование строки, чтобы
                    # избежать дубликатов при повторных вызовах.
                    exists = pd.read_sql_query(
                        "SELECT 1 FROM `nomeklatura_rk_psi` "
                        "WHERE `NomenklaturaID`='" + str(nom_rq.loc[0, 'номенклатура']) + "' LIMIT 1",
                        engine)
                    if exists.empty:
                        spc_edit = {
                            'SpcName': [df.loc[0, 'Name']],
                            'SpcID': [df.loc[0, 'ID']],
                            'NomenklaturaID': [nom_rq.loc[0, 'номенклатура']],
                            'NomenklaturaName': [nom_rq.loc[0, 'наименование']]
                        }
                        spc_edit_df = pd.DataFrame(spc_edit)
                        spc_edit_df.to_sql('nomeklatura_rk_psi', engine,
                                           schema='coordinator',
                                           if_exists='append', index=False)
        Statistik.Data.Data.set_spc_norm_status(spc_losd)


'''
Тестовый вариант (НЕ ПРОВЕРЕНО)
'''


def get_spc_norms_test(spc, measure_id: str = None):
    engine = create_engine(str(get_connection_string()))
    nom_query = f"SELECT `номенклатура`, `наименование` FROM `nomeklatura_rk` WHERE `наименование` = '{spc}'"
    nom_df = pd.read_sql(nom_query, engine)
    if nom_df.empty:
        Statistik.Data.Data.set_spc_norm_status(False)
        return
    nomen_id = nom_df.iloc[0]['номенклатура']
    psi_query = f"""
        SELECT `SpcName`, `SpcID`, `NomenklaturaID`, `NomenklaturaName` 
        FROM `nomeklatura_rk_psi` 
        WHERE `NomenklaturaID` = '{nomen_id}'
    """
    psi_df = pd.read_sql(psi_query, engine)
    if not psi_df.empty:
        spc_name = psi_df.iloc[0]['SpcName']
        spc_exist = True
    else:
        spc_exist = False
        if measure_id:
            measure_query = f"SELECT DISTINCT `spc` FROM `psidata` WHERE `Measure_ID` = '{measure_id}'"
            measure_df = pd.read_sql(measure_query, engine)
            spc_name = measure_df.iloc[0]['spc'] if not measure_df.empty else None
    if spc_name:
        spec_query = f"""
            SELECT `C0`,`Cq`, `R`,`F`,`Q`, `L`, `Fmax`,`Fmin`,`Rmax`, `Rmin`,
                   `C0max`,`C0min`,`Cqmax`, `Cqmin`, `Lmax`,`Lmin`, `Qmax`, `Qmin`,
                   `Name`, `ID` 
            FROM `specification` 
            WHERE `Name` = '{spc_name}'
        """
        spec_df = pd.read_sql(spec_query, engine)
        if not spec_df.empty:
            Statistik.Data.Data.add_spc_norm(spec_df)
            if not spc_exist:
                new_record = pd.DataFrame([{
                    'SpcName': spec_df.iloc[0]['Name'],
                    'SpcID': spec_df.iloc[0]['ID'],
                    'NomenklaturaID': nomen_id,
                    'NomenklaturaName': nom_df.iloc[0]['наименование']
                }])
                new_record.to_sql('nomeklatura_rk_psi', engine,
                                  if_exists='append', index=False)
    Statistik.Data.Data.set_spc_norm_status(bool(spc_name))