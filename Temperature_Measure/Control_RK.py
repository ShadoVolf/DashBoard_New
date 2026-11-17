import numpy as np
import pandas as pd
from scipy.interpolate import CubicSpline
from scipy.optimize import minimize_scalar
from sqlalchemy import create_engine
from tabulate import tabulate

from Options import get_connection_string
from Temperature_Measure.Load_Data import load_numbers_list, make_number_str, get_resonator_spc_psi_data
from Temperature_Measure.Report import create_calibration_protocol, create_accuracy_correction_protocol
from Temperature_Measure.measure_data_class import MEASURE_DATA

from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import PolynomialFeatures, StandardScaler


# Устанавливаем тип МСК на К.О.( Контрольный образец)
def load_control_rk(sender, data, dpg):
    result = str(sender).split('_')  # Получаем таг и разделяем его выделяя номер партии
    slot = result[2]
    dpg.configure_item('msk_' + str(slot) + '_select', label='K.O.')
    MEASURE_DATA.add_msk(slot, msk_str='K.O.')
    m_data = MEASURE_DATA.get_setupnum_data(slot)
    if 21910000 < m_data['Номинал'] < 22070000:
        MEASURE_DATA.set_control_type(slot, 'T')
    else:
        MEASURE_DATA.set_control_type(slot, 'RK')
    spc_list = find_control_spec(m_data['Номинал'])
    if len(spc_list) > 0:
        for spc_current in spc_list:
            result = get_resonator_spc_psi_data(spc_current)  # Получаем данные спецификации
            if not result.empty:
                MEASURE_DATA.add_spc_to_list(slot,
                                             result)  # Сохраняем спецификацию в список обработки
            spc_df = MEASURE_DATA.get_spc_sel_list(slot)  # Получаем заново список доступных спецификаций
            if not spc_df.empty:
                spc_sel_list = spc_df['Name'].tolist()
                dpg.configure_item('spc_' + str(slot) + 'select', items=spc_sel_list, default_value=spc_sel_list[0])
                print('Добавлена спецификация', spc_current)
    print('Тип датчика ', MEASURE_DATA.get_control_type(slot))


# подбор спецификаций для контрольного образца
def find_control_spec(nominal):
    result = []
    engine = create_engine(get_connection_string())
    query = f"SELECT Name, NameR, Profile, Nominal FROM `specification` WHERE `NameR`='Контрольный образец'"
    spc_df = pd.read_sql(query, engine)
    for index, row in spc_df.iterrows():  # По всем спецификациям контрольных образцов проверяем соответсвие номиналов
        dif_f = float((((float(row['Nominal']) * 1E+6) - nominal) / (float(row['Nominal']) * 1E+6) * 1E+6))
        if abs(dif_f) < 2000:
            result.append(row['Name'])
    return result


# Загружаем список номеров для контрогльных образцов заданного типа или для всех
def load_control_rk_numbers(slot=None):
    engine = create_engine(get_connection_string())
    print('Загрузка номеров контрольных образцов')
    m_data = MEASURE_DATA.get_setupnum_data(slot)
    # Получаем значение, конвертируем в float
    value_hz = float(m_data['Номинал'])
    # Конвертируем в МГц (1 МГц = 1 000 000 Гц)
    value_mhz = value_hz / 1_000_000
    if slot is not None:
        type_ = MEASURE_DATA.get_control_type(slot)
    else:
        type_ = None
    print('Control Type', type_)
    if type_ is not None:
        query = (f"SELECT N, Spc, Etalon_Type, Measure_ID FROM `control_rk` WHERE `Etalon_Type`='{type_}' and "
                 f"`Nominal` BETWEEN ({value_mhz}-0.001) and ({value_mhz} + 0.001) order by `N`")
        print(query)
    else:
        query = f"SELECT N, Spc, Etalon_Type, Measure_ID FROM `control_rk` order by `N`"
    numbers_df = pd.read_sql(query, engine)
    return numbers_df['N'].tolist(), numbers_df


# загружаем данные температурных измерений контрольных образцов
def load_control_rk_data(numbers):
    engine = create_engine(get_connection_string())
    query = f"SELECT Temp, F, R, N FROM `control_rk_data` order by `N`, `Temp`"
    data = pd.read_sql(query, engine)
    result = data[data['N'].isin(numbers)]
    return result


# загружаем данные эталонов
def load_control_rk_value(numbers):
    engine = create_engine(get_connection_string())
    query = f"SELECT  * FROM `control_rk` order by `N`"
    data = pd.read_sql(query, engine)
    result = data[data['N'].isin(numbers)]
    return result


def test_control_numbers_dataframe(slot: str, dpg):
    numbers_str = 'Нет'
    # Получаем номера и их сортируем
    df = load_numbers_list(slot)
    # Сохраняем данные
    MEASURE_DATA.set_numbers_list(slot, df)
    # Получаем название спецификации на номера контрольных образцов
    spc_name = is_numbers_in_db(slot)
    if spc_name is not None:  # Устанавливаем спецификацию для обработки
        result = get_resonator_spc_psi_data(spc_name)
        if not result.empty:
            MEASURE_DATA.delete_spc_slot(slot)
            MEASURE_DATA.add_spc_to_list(slot, result)
        spc_df = MEASURE_DATA.get_spc_sel_list(slot)
        if not spc_df.empty:
            spc_sel_list = spc_df['Name'].tolist()
            dpg.configure_item('spc_' + str(slot) + 'select', items=spc_sel_list, default_value=spc_sel_list[0])
    # Формируем результат
    result_df = load_numbers_list(slot)[['Positions', 'Numbers']]
    result_df.columns = ['Позиции', 'Номера']
    # Вывод таблицы с границами
    print("\nТаблица номеров:")
    print(tabulate(result_df, headers='keys', tablefmt='psql', showindex=False))
    return make_number_str(df)


def is_numbers_in_db(slot):
    """
        Проверяет, соответствуют ли температурные диапазоны номеров в базе данных
        заданным параметрам для указанного слота.

        Args:
            slot (str): Идентификатор слота, для которого проводится проверка.

        Returns:
            None: Всегда возвращает None. Если обнаружены ошибки, выводит таблицу с
                  проблемными номерами. Если всё в порядке, функция завершается без вывода.

        Raises:
            Exception: Возможны исключения при работе с базой данных, загрузке данных
                       или выполнении SQL-запросов (например, отсутствие соединения,
                       отсутствие данных, ошибки в запросе).

        Details:
            1. **Загрузка данных**:
               - Загружает данные из базы с помощью `load_control_rk_numbers(slot)[1]`.
               - Получает текущий список номеров из `MEASURE_DATA.get_numbers_list(slot)`.

            2. **Фильтрация номеров**:
               - Оставляет в данных только те номера, которые присутствуют в текущем списке.
               - Если количество уникальных номеров после фильтрации не совпадает с длиной
                 текущего списка, функция завершается (return None).

            3. **Проверка температурного диапазона**:
               - Определяет текущий температурный интервал (Tb, Ta) из `Temp_List`
                 в `MEASURE_DATA.get_setupnum_data(slot)`.
               - Выводит текущий интервал в формате "Tb...Ta".

            4. **Загрузка температурных данных из базы**:
               - Подключается к базе через SQLAlchemy.
               - Выполняет SQL-запрос для получения MAX(Temp) и MIN(Temp) для каждого номера
                 по `Measure_ID` из отфильтрованных данных.

            5. **Проверка соответствия диапазонов**:
               - Объединяет данные по номерам и проверяет, выполняются ли условия:
                 - T_max номера ≥ Ta (максимальная температура в базе ≥ заданная максимальная)
                 - T_min номера ≤ Tb (минимальная температура в базе ≤ заданная минимальная)
               - Если условия нарушаются, номер добавляется в список ошибок.

            6. **Вывод результатов**:
               - Если есть ошибки, выводит таблицу с номерами, текущим интервалом и
                 реальным диапазоном температур из базы.
               - Функция всегда возвращает None, но при ошибках информирует через print.

        Example:
            >>> is_numbers_in_db("slot_01")
            Текущий интервал: 20...30
            +--------+------------------+-----------------+
            | Serial |   Текущий интервал |   Требуемый интервал |
            +========+==================+=================+
            | 12345  |         20...30   |       18...28    |
            +--------+------------------+-----------------+
        """
    # Загрузка данных
    number_df = load_control_rk_numbers(slot=slot)[1]
    current_numbers = MEASURE_DATA.get_numbers_list(slot)['Numbers'].tolist()

    # Фильтрация номеров
    filtered_df = number_df[number_df['N'].isin(current_numbers)]
    if filtered_df['N'].nunique() != len(current_numbers):
        return None

    # Проверка температурного диапазона
    temp_list = MEASURE_DATA.get_setupnum_data(slot)['Temp_List']
    Ta, Tb = max(temp_list), min(temp_list)
    print(f'Текущий интервал: {Tb}...{Ta}')

    # Загрузка температурных данных для всех номеров
    engine = create_engine(get_connection_string())
    query = f"""
        SELECT `N`, MAX(Temp) as T_max, MIN(Temp) as T_min 
        FROM control_rk_data 
        WHERE Measure_ID = '{filtered_df['Measure_ID'].iloc[0]}' 
        GROUP BY `N`
    """
    temp_ranges = pd.read_sql(query, engine)

    # Проверка покрытия диапазонов
    merged = pd.merge(filtered_df, temp_ranges, on='N')
    errors = merged[(merged['T_max'] < Ta) | (merged['T_min'] > Tb)]

    if not errors.empty:
        print("Датчики с ошибкой температуры:")
        errors_df = errors[['N']].rename(columns={'N': 'Serial'})
        errors_df["Текущий интервал"] = f"{Tb}...{Ta}"
        errors_df["Требуемый интервал"] = errors.apply(lambda x: f"{x['T_min']}...{x['T_max']}", axis=1)
        print(tabulate(errors_df, headers='keys', tablefmt='grid', showindex=False))
        return None

    # Проверка уникальности Spc
    spc_values = filtered_df['Spc'].unique()
    return spc_values[0] if len(spc_values) == 1 else None


def create_network_model(X, Y):
    scaler = StandardScaler()
    X_ = X.to_numpy()
    Y_ = Y.to_numpy()
    X_train = scaler.fit_transform(X_.reshape(-1, 1))
    y_train = Y_
    model = MLPRegressor(
        hidden_layer_sizes=(100, 50, 30, 30),
        # hidden_layer_sizes=(500, 300, 200, 300, 100),
        activation='relu',
        max_iter=30000,
        early_stopping=False,
        random_state=62,
        learning_rate='adaptive'
    )
    model.fit(X_train, y_train)
    return model


def create_pipeline_model(X, Y):
    scaler = StandardScaler()
    X_ = X.to_numpy()
    Y_ = Y.to_numpy()
    X_train = scaler.fit_transform(X_.reshape(-1, 1))
    y_train = Y_
    model = make_pipeline(
        PolynomialFeatures(degree=3, include_bias=True),  # Полином 3-й степени
        StandardScaler(),  # Масштабирование
        MLPRegressor(
            hidden_layer_sizes=(100, 50, 30, 30),  # Архитектура сети
            activation='relu',  # Гиперболический тангенс
            solver='adam',
            alpha=0.001,  # Регуляризация
            learning_rate='adaptive',
            early_stopping=False,  # Ранняя остановка
            max_iter=15000,
            random_state=42
        )
    )
    model.fit(X_train, y_train)
    return model


def calc_temp_coefficient(temp, freq):
    cs = CubicSpline(temp, freq)
    derivatives = cs.derivative(1)(temp)
    return abs(derivatives)


# расчет коррекции ТЧХ резонаторов с использованием контрольных образцов типа РК
def find_temperature_correction_network(T_center):
    print("Расчет коррекции тип RK")
    scaler = StandardScaler()
    data = MEASURE_DATA.get_control_data_RK()
    result = pd.DataFrame()
    numbers = None
    if data:
        current_control_data = data['Result']
        slot = data['File_Slot']
        numbers = current_control_data['Numbers'].tolist()
        data_control_db = load_control_rk_data(numbers)
        type_sensor = MEASURE_DATA.get_control_type(slot)

        if not current_control_data.empty:
            current_temp = data['Data_Temp']
            first_number = current_control_data.iloc[0]['Numbers']
            first_temp_data = current_temp[current_temp['Numbers'] == first_number]
            common_temps = first_temp_data['Temps'].values
            c_temps = first_temp_data['Temps']
            common_temps_num = first_temp_data['Temps'].to_numpy()

            all_data = []
            # Создаем отдельный DataFrame с колонкой Temp
            temp_df_common = pd.DataFrame({'Temp': common_temps})
            all_data.append(temp_df_common)

            for index, row in current_control_data.iterrows():
                current_temp_data = current_temp[current_temp['Numbers'] == row['Numbers']].copy()
                temp_series = current_temp_data['Temps']
                f_series = current_temp_data['Fs_ppm']
                indexes = temp_series == T_center
                if not indexes.any():
                    raise ValueError(f"T_center {T_center} not found for Numbers {row['Numbers']}")
                f_center = f_series[indexes].iloc[0]
                f_data = f_series - f_center

                # model_current = create_network_model(c_temps, f_data)
                model_current = create_pipeline_model(c_temps, f_data)
                nn_input = scaler.fit_transform(common_temps_num.reshape(-1, 1))
                temp_f = model_current.predict(nn_input)
                der = calc_temp_coefficient(common_temps, temp_f)
                # Создаем временный DataFrame без колонки Temp
                temp_df = pd.DataFrame({
                    'Temp': common_temps,
                    f"{row['Numbers']}_F": temp_f,
                    f"{row['Numbers']}_dF": der,
                })

                db_temp_data = data_control_db[data_control_db['N'] == row['Numbers']].copy()
                temp_series_db = db_temp_data['Temp']
                f_db = db_temp_data['F']

                indexes_db = temp_series_db == T_center
                if not indexes_db.any():
                    # Интерполяция f_center_db для базовых данных
                    cs_db = CubicSpline(temp_series_db, f_db)
                    f_center_db = cs_db(T_center)
                    print('Температура настройки отсутствует в данных датчика, использована интерполяция')
                else:
                    f_center_db = f_db[indexes_db].iloc[0]
                f_data_db = f_db - f_center_db
                # model_db = create_network_model(temp_series_db, f_data_db)
                model_db = create_pipeline_model(temp_series_db, f_data_db)
                temp_f_base = model_db.predict(nn_input)
                der_db = calc_temp_coefficient(common_temps, temp_f_base)

                temp_df[f"{row['Numbers']}_F_Base"] = temp_f_base
                temp_df[f"{row['Numbers']}_dF_Base"] = der_db
                temp_df[f"{row['Numbers']}_delta_f"] = (temp_df[f"{row['Numbers']}_F"] -
                                                        temp_df[f"{row['Numbers']}_F_Base"])
                temp_df[f"{row['Numbers']}_DELTA_T"] = (temp_df[f"{row['Numbers']}_delta_f"] /
                                                        temp_df[f"{row['Numbers']}_dF_Base"])
                mask = abs(temp_df[f"{row['Numbers']}_dF_Base"]) < 0.16
                temp_df.loc[mask, f"{row['Numbers']}_DELTA_T"] = 0
                temp_df = temp_df.drop(columns=['Temp'])
                all_data.append(temp_df)
            # Объединяем все DataFrame
            result = pd.concat(all_data, axis=1)
            t_delta_columns = result.filter(regex='_DELTA_T$').columns

            def calculate_mean_without_outliers_iqr(row):
                values = row[t_delta_columns]
                Q1 = np.percentile(values, 25)
                Q3 = np.percentile(values, 75)
                IQR = Q3 - Q1
                # Фильтруем значения вне [Q1 - 1.5*IQR, Q3 + 1.5*IQR]
                filtered_values = values[(values >= (Q1 - 1.5 * IQR)) & (values <= (Q3 + 1.5 * IQR))]
                return filtered_values.mean() if len(filtered_values) > 0 else np.nan

            result['DELTA_T'] = result.apply(calculate_mean_without_outliers_iqr, axis=1)
            result['T_REF'] = result['Temp'] + result['DELTA_T']
            # Убедимся, что колонка Temp только одна
            result = result.loc[:, ~result.columns.duplicated()]
            table = tabulate(result[['Temp', 'T_REF', 'DELTA_T']], headers='keys', tablefmt='grid', showindex=False)
            print(table)
            #create_calibration_protocol(result, numbers, 'Тип RK')
            MEASURE_DATA.set_control_RK_corection_temp_table(result)
    return result, numbers


# Функция для рассчета и коррекции точности настройки на основе эталонных образцов
def calculate_corrections(main_df):
    """
    Рассчитывает поправки на основе контрольных образцов и применяет их к основным данным

    Параметры:
    main_df: основной датафрейм с данными резонаторов
    control_measurements_df: замеры контрольных образцов (с колонкой Numbers)
    reference_measurements_df: эталонные замеры (с колонкой N)

    Возвращает:
    main_df_corrected: основной датафрейм с добавленными скорректированными колонками
    F_cor, f_center_cor: рассчитанные поправки
    """
    # Загружаем данные измерений контрольных образцов
    data = MEASURE_DATA.get_control_data_RK()
    control_measurements_df = data['Result']

    # загружаем сохраненые данные для образцов по номерам
    slot = data['File_Slot']
    numbers = control_measurements_df['Numbers'].tolist()

    reference_measurements_df = load_control_rk_value(numbers)

    # Объединяем контрольные данные с эталонами (сопоставляем по номерам)
    merged_control = pd.merge(
        control_measurements_df,
        reference_measurements_df.rename(columns={'N': 'Numbers'}),
        on='Numbers',
        suffixes=('_meas', '_ref')
    )
    table = tabulate(
        merged_control[['Numbers', 'Fs_ppm_meas', 'Fs_ppm_ref',
                        'Fl_ppm_meas', 'Fl_ppm_ref',
                        'f_center','Fn',
                        'FL_Num_meas','FL_Num_ref']],
        headers='keys', tablefmt='grid', showindex=False)
    print(table)
    # Вычисляем разницы между замерами и эталонами
    merged_control['delta_Fs'] = merged_control['Fs_ppm_meas'] - merged_control['Fs_ppm_ref']
    merged_control['delta_FL'] = merged_control['Fl_ppm_meas'] - merged_control['Fl_ppm_ref']
    merged_control['delta_FL_Num'] = merged_control['FL_Num_meas'] - merged_control['FL_Num_ref']
    merged_control['delta_Fint'] = merged_control['f_center'] - merged_control['Fn']
    print('Коррекция точности настройки')
    table = tabulate(
        merged_control[['Numbers', 'delta_Fs',  'delta_FL',
                         'delta_FL_Num',  'delta_Fint']],
        headers='keys', tablefmt='grid', showindex=False)
    print(table)




    # Функция для фильтрации выбросов
    def remove_outliers_iqr(series):
        Q1 = series.quantile(0.25)
        Q3 = series.quantile(0.75)
        IQR = Q3 - Q1
        lower_bound = Q1 - 1.5 * IQR
        upper_bound = Q3 + 1.5 * IQR
        return series.between(lower_bound, upper_bound)

    # Проверяем, все ли значения в обеих колонках NaN
    if merged_control[['delta_Fs', 'delta_FL']].isna().all().all():
        print("Некорректные данные контрольных образцов.")
        filtered = merged_control  # возвращаем исходные данные без фильтрации
    else:
        # Создаем маски для каждой колонки отдельно
        mask_fs = (
            remove_outliers_iqr(merged_control['delta_Fs'])
            if not merged_control['delta_Fs'].isna().all()
            else True  # если все значения NaN, принимаем все значения
        )
        mask_fl = (
            remove_outliers_iqr(merged_control['delta_FL'])
            if not merged_control['delta_FL'].isna().all()
            else True
        )

        # Комбинируем маски
        mask = mask_fs & mask_fl
        filtered = merged_control[mask]
    # Рассчитываем средние поправки
    F_cor_s = filtered['delta_Fs'].mean()
    F_cor_l = filtered['delta_FL'].mean()
    F_cor_num = filtered['delta_FL_Num'].mean()
    f_center_cor = filtered['delta_Fint'].mean()

    # Создаем копию основного датафрейма для безопасности
    main_df_corrected = main_df.copy()

    # Добавляем скорректированные колонки
    main_df_corrected['Fs_cor'] = main_df_corrected['Fs_ppm'] - F_cor_s
    main_df_corrected['FL_cor'] = main_df_corrected['Fl_ppm'] - F_cor_l
    main_df_corrected['FL_Num_cor'] = main_df_corrected['FL_Num'] - F_cor_num
    main_df_corrected['f_center_cor'] = main_df_corrected['f_center'] - f_center_cor
    main_df_corrected['delta_Fs'] = F_cor_s
    main_df_corrected['delta_FL'] = F_cor_l
    main_df_corrected['delta_FL_Num'] = F_cor_num
    main_df_corrected['delta_Fint'] = f_center_cor

    print('Коррекция точности настройки T = ')
    table = tabulate(
        main_df_corrected[['Numbers', 'Fs_ppm', 'delta_Fs','Fs_cor',
                           'Fl_ppm', 'delta_FL','FL_cor',
                           'FL_Num', 'delta_FL_Num', 'FL_Num_cor',
                           'f_center', 'delta_Fint', 'f_center_cor']],
        headers='keys', tablefmt='grid', showindex=False)
    print(table)

    MEASURE_DATA.set_control_RK_corection_f_table(merged_control)
    #create_accuracy_correction_protocol(merged_control)
    return main_df_corrected, numbers


def find_temperature_correction_rk(T_center):
    print("Расчет коррекции тип RK")
    data = MEASURE_DATA.get_control_data_RK()
    result = pd.DataFrame()
    if data:
        current_control_data = data['Result']
        slot = data['File_Slot']
        numbers = current_control_data['Numbers'].tolist()
        data_control_db = load_control_rk_data(numbers)
        type_sensor = MEASURE_DATA.get_control_type(slot)

        if not current_control_data.empty:
            current_temp = data['Data_Temp']
            first_number = current_control_data.iloc[0]['Numbers']
            first_temp_data = current_temp[current_temp['Numbers'] == first_number]
            common_temps = first_temp_data['Temps'].values

            all_data = []
            # Создаем отдельный DataFrame с колонкой Temp
            temp_df_common = pd.DataFrame({'Temp': common_temps})
            all_data.append(temp_df_common)

            for index, row in current_control_data.iterrows():
                current_temp_data = current_temp[current_temp['Numbers'] == row['Numbers']].copy()
                temp_series = current_temp_data['Temps']
                f_series = current_temp_data['Fs_ppm']
                indexes = temp_series == T_center
                if not indexes.any():
                    raise ValueError(f"T_center {T_center} not found for Numbers {row['Numbers']}")
                f_center = f_series[indexes].iloc[0]
                f_data = f_series - f_center
                test_spline = CubicSpline(temp_series, f_data)
                temp_f = test_spline(common_temps)
                # Создаем временный DataFrame без колонки Temp
                temp_df = pd.DataFrame({
                    'Temp': common_temps,
                    f"{row['Numbers']}_F": temp_f,
                    f"{row['Numbers']}_dF": test_spline.derivative(1)(common_temps),
                })

                db_temp_data = data_control_db[data_control_db['N'] == row['Numbers']].copy()
                temp_series_db = db_temp_data['Temp']
                f_db = db_temp_data['F']

                indexes_db = temp_series_db == T_center
                if not indexes_db.any():
                    # Интерполяция f_center_db для базовых данных
                    cs_db = CubicSpline(temp_series_db, f_db)
                    f_center_db = cs_db(T_center)
                    print('Температура настройки отстувует в данных датчика, использована интерполяция')
                else:
                    f_center_db = f_db[indexes_db].iloc[0]
                f_data_db = f_db - f_center_db

                control_spline = CubicSpline(temp_series_db, f_data_db)
                temp_f_base = control_spline(common_temps)
                temp_df[f"{row['Numbers']}_F_Base"] = temp_f_base
                temp_df[f"{row['Numbers']}_dF_Base"] = control_spline.derivative(1)(common_temps)
                temp_df[f"{row['Numbers']}_delta_f"] = (temp_df[f"{row['Numbers']}_F"] -
                                                        temp_df[f"{row['Numbers']}_F_Base"])
                temp_df[f"{row['Numbers']}_DELTA_T"] = (temp_df[f"{row['Numbers']}_delta_f"] /
                                                        temp_df[f"{row['Numbers']}_dF_Base"])
                # Получаем температуру экстремума образцов
                extr_1 = row['extr_1']
                extr_2 = row['extr_2']
                T1_start, T1_end = extr_1 - 15, extr_1 + 15
                T2_start, T2_end = extr_2 - 15, extr_2 + 15

                mask = (
                        (temp_df['Temp'].between(T1_start, T1_end)) |
                        (temp_df['Temp'].between(T2_start, T2_end))
                )

                temp_df.loc[mask, f"{row['Numbers']}_DELTA_T"] = 0
                temp_df = temp_df.drop(columns=['Temp'])
                all_data.append(temp_df)
            # Объединяем все DataFrame
            result = pd.concat(all_data, axis=1)
            t_delta_columns = result.filter(regex='_DELTA_T$').columns

            def calculate_mean_without_outliers_iqr(row):
                values = row[t_delta_columns]
                Q1 = np.percentile(values, 25)
                Q3 = np.percentile(values, 75)
                IQR = Q3 - Q1
                # Фильтруем значения вне [Q1 - 1.5*IQR, Q3 + 1.5*IQR]
                filtered_values = values[(values >= (Q1 - 1.5 * IQR)) & (values <= (Q3 + 1.5 * IQR))]
                return filtered_values.mean() if len(filtered_values) > 0 else np.nan

            result['DELTA_T'] = result.apply(calculate_mean_without_outliers_iqr, axis=1)
            result['T_REF'] = result['Temp'] + result['DELTA_T']
            # Убедимся, что колонка Temp только одна
            result = result.loc[:, ~result.columns.duplicated()]
            table = tabulate(result[['Temp', 'T_REF', 'DELTA_T']], headers='keys', tablefmt='grid', showindex=False)
            print(table)
    return result


"""
Определение ошибки температуры для датчиков типа Т
"""


def find_temperature_correction(T_center):
    print("Расчет коррекции тип Т")
    data = MEASURE_DATA.get_control_data_T()
    result = pd.DataFrame()
    numbers = None
    if data:
        current_control_data = data['Result']
        slot = data['File_Slot']
        numbers = current_control_data['Numbers'].tolist()
        data_control_db = load_control_rk_data(numbers)
        type_sensor = MEASURE_DATA.get_control_type(slot)

        if not current_control_data.empty:
            current_temp = data['Data_Temp']
            first_number = current_control_data.iloc[0]['Numbers']
            first_temp_data = current_temp[current_temp['Numbers'] == first_number]
            common_temps = first_temp_data['Temps'].values

            all_data = []
            # Создаем отдельный DataFrame с колонкой Temp
            temp_df_common = pd.DataFrame({'Temp': common_temps})
            all_data.append(temp_df_common)

            for index, row in current_control_data.iterrows():
                current_temp_data = current_temp[current_temp['Numbers'] == row['Numbers']].copy()
                temp_series = current_temp_data['Temps']
                f_series = current_temp_data['Fs_ppm']

                indexes = temp_series == T_center
                if not indexes.any():
                    raise ValueError(f"T_center {T_center} not found for Numbers {row['Numbers']}")
                f_center = f_series[indexes].iloc[0]
                f_data = f_series - f_center

                test_spline = CubicSpline(temp_series, f_data)
                temp_f = test_spline(common_temps)
                # Создаем временный DataFrame без колонки Temp
                temp_df = pd.DataFrame({
                    f"{row['Numbers']}_F": temp_f,
                    f"{row['Numbers']}_dF": test_spline.derivative(1)(common_temps),
                })

                db_temp_data = data_control_db[data_control_db['N'] == row['Numbers']].copy()
                temp_series_db = db_temp_data['Temp']
                f_db = db_temp_data['F']

                indexes_db = temp_series_db == T_center
                if not indexes_db.any():
                    # Интерполяция f_center_db для базовых данных
                    cs_db = CubicSpline(temp_series_db, f_db)
                    f_center_db = cs_db(T_center)
                    print('Температура настройки отстувует в данных датчика, использована интерполяция')
                else:
                    f_center_db = f_db[indexes_db].iloc[0]
                f_data_db = f_db - f_center_db

                control_spline = CubicSpline(temp_series_db, f_data_db)
                temp_f_base = control_spline(common_temps)
                temp_df[f"{row['Numbers']}_F_Base"] = temp_f_base
                temp_df[f"{row['Numbers']}_dF_Base"] = control_spline.derivative(1)(common_temps)

                def find_t(f_val):
                    res = minimize_scalar(
                        lambda t: (control_spline(t) - f_val) ** 2,
                        bounds=(temp_series_db.min(), temp_series_db.max()),
                        method='bounded'
                    )
                    return res.x if res.success else np.nan

                t_ref = [find_t(f_val) for f_val in temp_f]
                temp_df[f"{row['Numbers']}_T_REF"] = t_ref

                all_data.append(temp_df)

            # Объединяем все DataFrame
            result = pd.concat(all_data, axis=1)
            t_ref_columns = result.filter(regex='_T_REF$').columns
            result['T_REF'] = result[t_ref_columns].mean(axis=1)
            result['DELTA_T'] = result['Temp'] - result['T_REF']
            # Убедимся, что колонка Temp только одна
            result = result.loc[:, ~result.columns.duplicated()]
            table = tabulate(result[['Temp', 'T_REF', 'DELTA_T']], headers='keys', tablefmt='grid', showindex=False)
            MEASURE_DATA.set_control_RK_corection_temp_table(result)
            #create_calibration_protocol(result, numbers, 'Тип T')
            print(table)
    return result, numbers

# Функция коррекции точности настйроки резонаторов для эталонов типа Т
def calculate_temperature_correction1(df_measurements, df_correction,
                                     group_columns='Positions', t_center=25):
    """
    Вычисляет поправки частоты через производную сплайна температурной зависимости

    Parameters:
    df_measurements : pd.DataFrame
        DataFrame с измерениями частот
    df_correction : pd.DataFrame
        DataFrame с поправками температуры
    group_columns : list
        Колонки для группировки данных (по умолчанию: SETUPNUM, Positions, Numbers)

    Returns:
    pd.DataFrame
        DataFrame с добавленными колонками *_corr
    """
    frequency_columns = ['Fs_ppm','Fl_ppm','FL_Num']
    # Создаем копию DataFrame
    df = df_measurements.copy()

    # Объединяем с поправками температуры
    df = df.merge(df_correction[['Temp', 'DELTA_T']],
                  left_on='Temps', right_on='Temp', how='left')

    # Для каждой группы и каждой колонки частоты строим сплайн и вычисляем производную
    for col in frequency_columns:
        if col not in df.columns:
            continue

        # Создаем колонку для скорректированных значений
        df[f'{col}_corr'] = np.nan
        df[f'{col}_derivative'] = np.nan  # Производная в точке

        # Группируем данные
        for name, group in df.groupby(group_columns):
            if len(group) < 4:  # Минимум 4 точки для кубического сплайна
                print(f"Предупреждение: для группы {name} недостаточно точек для построения сплайна")
                continue

            # Сортируем по температуре
            group_sorted = group.sort_values('Temps')
            temps = group_sorted['Temps'].values
            freqs = group_sorted[col].values

            try:
                # Строим кубический сплайн
                cs = CubicSpline(temps, freqs)

                # Вычисляем производную (наклон характеристики) в каждой точке
                derivatives = cs(temps, 1)  # 1 - первая производная

                # Для каждой точки в группе вычисляем поправку
                for idx, row in group_sorted.iterrows():
                    temp_point = row['Temps']
                    delta_T = row['DELTA_T']
                    derivative = cs(temp_point, 1)  # Производная в конкретной точке

                    # Поправка частоты: наклон * ошибка температуры
                    frequency_correction = derivative * delta_T

                    # Скорректированная частота
                    df.loc[idx, f'{col}_corr'] = row[col] + frequency_correction
                    df.loc[idx, f'{col}_derivative'] = derivative

            except Exception as e:
                print(f"Ошибка при построении сплайна для группы {name}, колонка {col}: {e}")
                continue

    # Удаляем временные колонки
    df = df.drop(['Temp', 'DELTA_T'], axis=1, errors='ignore')
    print('Коррекция точности настройки для контрольных образцов тип Т')
    table = tabulate(df[['Positions', 'Fs_ppm','Fs_ppm_corr','Fl_ppm','Fl_ppm_corr','FL_Num','FL_Num_corr']],
                     headers='keys', tablefmt='grid', showindex=False)
    print(table)
    return df


def calculate_temperature_correction(df_measurements, df_correction,
                                     group_columns='Positions', t_center=25):
    """
    Вычисляет поправки частоты через производную сплайна температурной зависимости

    Parameters:
    df_measurements : pd.DataFrame
        DataFrame с измерениями частот
    df_correction : pd.DataFrame
        DataFrame с поправками температуры
    group_columns : list или str
        Колонки для группировки данных
    t_center : float
        Температура, для которой выводить результаты в консоль

    Returns:
    pd.DataFrame
        DataFrame с добавленными колонками *_corr
    """
    frequency_columns = ['Fs_ppm', 'Fl_ppm', 'FL_Num']
    # Создаем копию DataFrame
    df = df_measurements.copy()

    # Объединяем с поправками температуры
    df = df.merge(df_correction[['Temp', 'DELTA_T']],
                  left_on='Temps', right_on='Temp', how='left')

    # Для каждой группы и каждой колонки частоты строим сплайн и вычисляем производную
    for col in frequency_columns:
        if col not in df.columns:
            continue

        # Создаем колонку для скорректированных значений
        df[f'{col}_corr'] = np.nan
        df[f'{col}_derivative'] = np.nan  # Производная в точке

        # Группируем данные
        for name, group in df.groupby(group_columns):
            if len(group) < 4:  # Минимум 4 точки для кубического сплайна
                print(f"Предупреждение: для группы {name} недостаточно точек для построения сплайна")
                continue

            # Сортируем по температуре
            group_sorted = group.sort_values('Temps')
            temps = group_sorted['Temps'].values
            freqs = group_sorted[col].values

            try:
                # Строим кубический сплайн
                cs = CubicSpline(temps, freqs)

                # Вычисляем производную (наклон характеристики) в каждой точке
                derivatives = cs(temps, 1)  # 1 - первая производная

                # Для каждой точки в группе вычисляем поправку
                for idx, row in group_sorted.iterrows():
                    temp_point = row['Temps']
                    delta_T = row['DELTA_T']
                    derivative = cs(temp_point, 1)  # Производная в конкретной точке

                    # Поправка частоты: наклон * ошибка температуры
                    frequency_correction = derivative * delta_T

                    # Скорректированная частота
                    df.loc[idx, f'{col}_corr'] = row[col] + frequency_correction
                    df.loc[idx, f'{col}_derivative'] = derivative

            except Exception as e:
                print(f"Ошибка при построении сплайна для группы {name}, колонка {col}: {e}")
                continue

    # Удаляем временные колонки
    df = df.drop(['Temp', 'DELTA_T'], axis=1, errors='ignore')

    # Выводим результаты только для указанной температуры
    print(f'Коррекция точности настройки для контрольных образцов тип Т при температуре {t_center}°C')

    # Фильтруем данные по указанной температуре
    df_center = df[df['Temps'] == t_center]

    if df_center.empty:
        print(f"Предупреждение: нет данных для температуры {t_center}°C")
        # Находим ближайшую доступную температуру
        available_temps = df['Temps'].unique()
        if len(available_temps) > 0:
            closest_temp = min(available_temps, key=lambda x: abs(x - t_center))
            print(f"Ближайшая доступная температура: {closest_temp}°C")
            df_center = df[df['Temps'] == closest_temp]

    if not df_center.empty:
        # Создаем таблицу только с нужными колонками
        display_columns = ['Positions', 'Fs_ppm', 'Fs_ppm_corr', 'Fl_ppm', 'Fl_ppm_corr', 'FL_Num', 'FL_Num_corr']

        # Проверяем, какие колонки существуют в DataFrame
        existing_columns = [col for col in display_columns if col in df_center.columns]

        table = tabulate(df_center[existing_columns],
                         headers='keys', tablefmt='grid', showindex=False)
        print(table)

        # Дополнительная информация: средние значения поправок
        print(f"\nСредние значения поправок при {t_center}°C:")
        for col in frequency_columns:
            corr_col = f'{col}_corr'
            if corr_col in df_center.columns and col in df_center.columns:
                mean_correction = (df_center[corr_col] - df_center[col]).mean()
                print(f"  {col}: {mean_correction:.6f}")
    else:
        print("Нет данных для отображения")

    return df