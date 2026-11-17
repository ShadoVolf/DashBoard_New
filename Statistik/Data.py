import numpy as np
import pandas as pd
from sqlalchemy import create_engine

from Options import get_connection_string


class Data:
    msk_list = {}
    measure_type_list = pd.DataFrame()
    active_data_list = pd.DataFrame()
    data_full = {}
    axis_limits = {'X_Max': 0, 'X_Min': 0, 'Y_Max': 0, 'Y_Min': 0}
    spc_norm = {'Fr': {}, 'Fs': {}, 'FL': {}, 'R': {}, 'C0': {},
                'C1': {}, 'L1': {}, 'Q': {}, 'Status': False}
    spc_value = ''
    # NEW: номинальная частота текущей спецификации ПСИ, Гц
    spc_freq_nominal = None
    plot_children = []
    plot1_children = []


    without_cap_mode = False
    dirty = True

    @staticmethod
    def set_dirty(v=True):
        """Пометить данные как устаревшие (True) или свежие (False)."""
        Data.dirty = bool(v)

    @staticmethod
    def is_dirty():
        """Нужно ли перезагрузить data_full перед следующим NL-запросом."""
        return Data.dirty

    @staticmethod
    def set_without_cap_mode(v):
        Data.without_cap_mode = bool(v)

    @staticmethod
    def get_without_cap_mode():
        return Data.without_cap_mode

    @staticmethod
    def set_spc_value(spc):
        Data.spc_value = spc

    @staticmethod
    def get_spc_value():
        return Data.spc_value

    @staticmethod
    def set_spc_norm_status(status):
        Data.spc_norm['Status'] = status

    @staticmethod
    def get_spc_norm_status():
        return Data.spc_norm['Status']

    @staticmethod
    def get_spec_freq_nominal_hz():
        """Номинальная частота спецификации ПСИ в Гц (или None)."""
        return Data.spc_freq_nominal

    @staticmethod
    def add_spc_norm(data: pd.DataFrame):
        spc_parameters_list = {'Fr': 'F', 'Fs': 'F', 'FL': 'F',
                               'R': 'R', 'C0': 'C0', 'C1': 'Cq',
                               'L': 'L', 'Q': 'Q', 'Tmin': 'Tmin',
                               'Tmax': 'Tmax'}
        print('ADD SPC NORM ', data.columns)

        # Сбрасываем на каждом новом spec
        Data.spc_freq_nominal = None

        if data.empty:
            return

        Data.spc_norm['Status'] = True
        for key in spc_parameters_list.keys():
            temp = {}
            str_max = spc_parameters_list[key] + 'max'
            key_str = key + 'max'
            temp[key_str] = (
                data.loc[0, str_max]
                if (str_max in data.columns and data.loc[0, str_max] != 'no')
                else None)
            str_min = spc_parameters_list[key] + 'min'
            key_str = key + 'min'
            temp[key_str] = (
                data.loc[0, str_min]
                if (str_min in data.columns and data.loc[0, str_min] != 'no')
                else None)
            Data.spc_norm[key] = temp

        # 1. Пытаемся взять номинал из specification.F
        if 'F' in data.columns:
            raw = data.loc[0, 'F']
            if raw not in (None, '', 'no'):
                hz = Data._detect_freq_hz(raw)
                if hz is not None and hz > 0:
                    Data.spc_freq_nominal = hz
                    print(f'[add_spc_norm] F={raw} → номинал {hz} Гц')

        # 2. Fallback: Nominal из psidata по имени спецификации
        if not Data.spc_freq_nominal:
            spc_name = (data.loc[0, 'Name']
                        if 'Name' in data.columns else None)
            if spc_name:
                try:
                    engine = create_engine(str(get_connection_string()))
                    df_psi = pd.read_sql_query(
                        "SELECT `Nominal` FROM `psidata` "
                        "WHERE `spc` = %(spc)s "
                        "AND `Nominal` IS NOT NULL AND `Nominal` > 0 "
                        "LIMIT 1",
                        engine, params={'spc': spc_name})
                    if not df_psi.empty:
                        hz = Data._detect_freq_hz(df_psi.iloc[0]['Nominal'])
                        if hz is not None and hz > 0:
                            Data.spc_freq_nominal = hz
                            print(f'[add_spc_norm] F=0, PSI Nominal='
                                  f'{df_psi.iloc[0]["Nominal"]} → {hz} Гц')
                except Exception as e:
                    print(f'[add_spc_norm] PSI Nominal lookup error: {e}')

    @staticmethod
    def add_spc_norm_old(data: pd.DataFrame):
        spc_parameters_list = {'Fr': 'F', 'Fs': 'F', 'FL': 'F',
                               'R': 'R', 'C0': 'C0', 'C1': 'Cq',
                               'L': 'L', 'Q': 'Q', 'Tmin': 'Tmin',
                               'Tmax': 'Tmax'}
        print('ADD SPC NORM ', data.columns)
        if not data.empty:
            Data.spc_norm['Status'] = True
            for key in spc_parameters_list.keys():
                temp = {}
                str_max = spc_parameters_list[key] + 'max'
                key_str = key + 'max'
                if str_max in data.columns:
                    temp[key_str] = (data.loc[0, str_max]
                                     if data.loc[0, str_max] != 'no'
                                     else None)
                else:
                    temp[key_str] = None
                str_min = spc_parameters_list[key] + 'min'
                key_str = key + 'min'
                if str_min in data.columns:
                    temp[key_str] = (data.loc[0, str_min]
                                     if data.loc[0, str_min] != 'no'
                                     else None)
                else:
                    temp[key_str] = None
                Data.spc_norm[key] = temp

            # NEW: сохраняем номинальную частоту спецификации в Гц.
            # specification.F может быть в МГц, кГц или Гц — определяем
            # по порядку величины. Для типичных резонаторов (десятки МГц)
            # это работает надёжно; при экзотически низких частотах
            # (< 1 кГц) пороги можно скорректировать.
            Data.spc_freq_nominal = None
            if 'F' in data.columns:
                raw = data.loc[0, 'F']
                if raw not in (None, '', 'no'):
                    try:
                        fv = float(raw)
                        av = abs(fv)
                        if 0 < av < 1000:
                            fv *= 1e6          # МГц → Гц
                        elif 0 < av < 1e6:
                            fv *= 1e3          # кГц → Гц
                        Data.spc_freq_nominal = abs(fv)
                        print(f'[add_spc_norm] F={raw} → '
                              f'номинал {Data.spc_freq_nominal} Гц')
                    except (TypeError, ValueError):
                        pass

    @staticmethod
    def get_spc_norm(mes_parametr):
        return Data.spc_norm[mes_parametr]

    @staticmethod
    def clear_all_data():
        Data.msk_list = {}
        Data.data_full = {}
        slot_list = Data.get_active_data()
        for index, row in slot_list.iterrows():
            if 'Use' in slot_list.columns:
                slot_list.loc[slot_list['Name'] == row['Name'], "Use"] = False
            else:
                slot_list['Use'] = False
            if 'Count' in slot_list.columns:
                slot_list.loc[slot_list['Name'] == row['Name'], "Count"] = 0
            else:
                slot_list['Count'] = 0

    @staticmethod
    def set_axis_limits(x, y):
        x_min, x_max = min(x), max(x)
        y_min, y_max = min(y), max(y)
        if abs(Data.axis_limits['X_Max']) < x_max:
            Data.axis_limits['X_Max'] = x_max
        if abs(Data.axis_limits['X_Min']) > x_min:
            Data.axis_limits['X_Min'] = x_min
        if abs(Data.axis_limits['Y_Min']) > y_min:
            Data.axis_limits['Y_Min'] = y_min
        if abs(Data.axis_limits['Y_Max']) < y_max:
            Data.axis_limits['Y_Max'] = y_max

    @staticmethod
    def get_axis_limits():
        return Data.axis_limits

    @staticmethod
    def clear_axis_limits():
        Data.axis_limits = {'X_Max': 0, 'X_Min': 0,
                            'Y_Max': 0, 'Y_Min': 0}

    @staticmethod
    def get_measure_type_list():
        if Data.measure_type_list.empty:
            engine = create_engine(str(get_connection_string()))
            sql = ("Select `Name`,`ID` from `final_plating_measure_type` "
                   "order by `ID`")
            Data.measure_type_list = pd.read_sql_query(sql, engine)
        return Data.measure_type_list

    @staticmethod
    def get_data(slot_name):
        """Вернуть DataFrame слота из data_full.

        Если data_full ещё пуст — инициализируется пустыми DataFrame
        по всем слотам active_data_list. Если слота нет в data_full,
        возвращается пустой DataFrame (без KeyError).
        """
        if not Data.data_full:
            active_slot_list = Data.get_active_data()
            Data.data_full = {key: pd.DataFrame()
                              for key in active_slot_list['Name'].to_list()}

        if slot_name not in Data.data_full:
            # слот мог быть добавлен в UI, но ещё не инициализирован
            Data.data_full[slot_name] = pd.DataFrame()

        return Data.data_full[slot_name]

    @staticmethod
    def set_data(slot_name, data):
        Data.data_full[slot_name] = data

    # ------------------------------------------------------------------
    # NEW: распознавание единиц частоты и приведение к ppm
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_freq_units(df: pd.DataFrame) -> None:
        """
        Определяет единицы Fr во final_plating и пересчитывает к ppm
        относительно номинала спецификации ПСИ (Data.spc_freq_nominal).

        Правила:
          • |Fr| > 20000 и Fr близка к Nominal (±10%)  → Fr в Гц
          • |Fr| < 20000                                → Fr в ppm отн. Nominal
          • иначе                                       → оставляем как есть

        Результат: Fr в ppm относительно номинала спецификации (если он
        известен), либо относительно final_plating.Nominal (старое
        поведение).
        """
        if df is None or df.empty or 'Fr' not in df.columns:
            return

        spec_hz = Data.get_spec_freq_nominal_hz()
        use_spec = spec_hz is not None and spec_hz > 0

        # Nominal для расчёта относительной разницы — с защитой от 0/NaN
        nominal = pd.to_numeric(df['Nominal'], errors='coerce')
        safe_nominal = nominal.where(nominal.abs() > 0, other=1.0)

        abs_fr = df['Fr'].abs()
        rel_diff = (df['Fr'] - nominal).abs() / safe_nominal.abs()

        # Случай 1: Fr в Гц (|Fr| > 20000 и близка к Nominal ±10%)
        mask_hz = (abs_fr > 20000) & (rel_diff <= 0.10) & nominal.notna()
        # Случай 2: Fr в ppm (|Fr| < 20000)
        mask_ppm = abs_fr < 20000

        if use_spec:
            ref = float(spec_hz)
            # Гц → ppm отн. спец.
            if mask_hz.any():
                df.loc[mask_hz, 'Fr'] = (
                    (df.loc[mask_hz, 'Fr'] - ref) / ref * 1e6
                )
            # ppm (отн. Nominal) → ppm отн. спец.
            if mask_ppm.any():
                df.loc[mask_ppm, 'Fr'] = (
                    nominal.loc[mask_ppm]
                    * (1 + df.loc[mask_ppm, 'Fr'] / 1e6)
                    - ref
                ) / ref * 1e6
        else:
            # Fallback: как в исходной версии — ppm отн. final_plating.Nominal
            if mask_hz.any():
                df.loc[mask_hz, 'Fr'] = (
                    (df.loc[mask_hz, 'Fr'] - nominal.loc[mask_hz])
                    / nominal.loc[mask_hz] * 1e6
                )
            # ppm отн. Nominal — оставляем как есть

        undecided = (~mask_hz) & (~mask_ppm)
        if undecided.any():
            print(f'[append_data] {int(undecided.sum())} строк с '
                  f'неопределёнными единицами Fr — оставлены без изменений')

    # ------------------------------------------------------------------
    @staticmethod
    def append_data(data_current, slot_name):
        print('Append Data')
        print('Data', data_current.shape)
        print('Slot=', slot_name)
        active_list_slot = Data.get_active_data()
        print('Active slot', active_list_slot)
        current_mes_type = active_list_slot[
            active_list_slot['Name'] == slot_name]
        print('Current_mes_type', current_mes_type)

        if data_current is None or data_current.empty:
            print('Append Data: пустой DataFrame, пропуск')
            return

        mtype_str = (current_mes_type['Value'].to_string(index=False)
                     if not current_mes_type.empty else '')

        if mtype_str != '6':
            # ---------------- final_plating ----------------
            print(data_current['Machine_Type'])
            print(data_current.shape)

            if data_current['Machine_Type'].iloc[0] == 25:
                data_current = data_current[
                    data_current['Status'] == 'stable'].copy()

            data_current['Fr'] = pd.to_numeric(
                data_current['Fr'], errors='coerce')
            data_current['Nominal'] = pd.to_numeric(
                data_current['Nominal'], errors='coerce')
            data_current = data_current[data_current['Fr'] < 1e12]
            print(data_current.shape)

            # Нормализация применяется ко ВСЕМ final_plating строкам,
            # а не только Machine_Type == 25 (см. логи: там MT=24, но Fr в Гц)
            if len(data_current) > 0:
                Data._normalize_freq_units(data_current)
        else:
            # ---------------- psidata (ПСИ) ----------------
            print(data_current.columns)
            data_current = data_current[data_current['F'].notna()].copy()
            data_current.rename(
                columns={'F': 'Fr', 'Cq': 'C1', 'L': 'L1'},
                inplace=True,
            )
            data_current['Fs'] = data_current['Fr']
            data_current['FL'] = data_current['Fr']

            # PSI Fr уже в ppm; пересчитываем к spec nominal (если нужно)
            Data._normalize_psi_freq_units(data_current)

        # ---------- сохранение ----------
        data = Data.get_data(slot_name)
        print('Данные текущего слота', data)

        if data.empty:
            Data.data_full[slot_name] = data_current
            if 'Use' not in active_list_slot.columns:
                active_list_slot['Use'] = False
            active_list_slot.loc[
                active_list_slot['Name'] == slot_name, 'Use'] = True
        else:
            Data.data_full[slot_name] = pd.concat(
                [Data.data_full[slot_name], data_current])

        if 'Count' not in active_list_slot.columns:
            active_list_slot['Count'] = 0
        active_list_slot.loc[
            active_list_slot['Name'] == slot_name, 'Count'
        ] = Data.data_full[slot_name].shape[0]

        Data.set_active_data(active_list_slot)

    @staticmethod
    def append_data_old(data_current, slot_name):
        print('Append Data')
        print('Data', data_current.shape)
        print('Slot=', slot_name)
        active_list_slot = Data.get_active_data()
        print('Active slot', active_list_slot)
        current_mes_type = active_list_slot[active_list_slot['Name'] == slot_name]
        print('Current_mes_type', current_mes_type)

        if data_current is None or data_current.empty:
            print('Append Data: пустой DataFrame, пропуск')
            return

        mtype_str = (current_mes_type['Value'].to_string(index=False)
                     if not current_mes_type.empty else '')

        if mtype_str != '6':
            # ---------------- final_plating ----------------
            print(data_current['Machine_Type'])
            print(data_current.shape)

            if data_current['Machine_Type'].iloc[0] == 25:
                data_current = data_current[
                    data_current['Status'] == 'stable'].copy()
                data_current['Fr'] = pd.to_numeric(data_current['Fr'],
                                                   errors='coerce')
                data_current['Nominal'] = pd.to_numeric(data_current['Nominal'],
                                                        errors='coerce')
            else:
                data_current['Fr'] = pd.to_numeric(data_current['Fr'],
                                                   errors='coerce')
                data_current['Nominal'] = pd.to_numeric(data_current['Nominal'],
                                                        errors='coerce')
                data_current = data_current[data_current['Fr'] < 1e12]
                print(data_current.shape)

            # NEW: распознаём единицы Fr и приводим к ppm относительно
            # номинала спецификации ПСИ (см. _normalize_freq_units).
            if (len(data_current) > 0
                    and data_current['Machine_Type'].iloc[0] == 25):
                Data._normalize_freq_units(data_current)

        else:
            # ---------------- psidata (ПСИ) ----------------
            print(data_current.columns)
            data_current = data_current[data_current['F'].notna()].copy()
            data_current.rename(
                columns={'F': 'Fr', 'Cq': 'C1', 'L': 'L1'},
                inplace=True,
            )
            data_current['Fs'] = data_current['Fr']
            data_current['FL'] = data_current['Fr']

        # ---------- сохранение ----------
        data = Data.get_data(slot_name)

        print('Данные текущего слота', data)
        if data.empty:
            print("Добавляем новые данные создаем слот")
            Data.data_full[slot_name] = data_current
            print('Данные добавлены')
            print('Data current', data_current.shape)
            data = Data.get_data(slot_name)
            print(data.shape)
            if 'Use' not in active_list_slot.columns:
                active_list_slot['Use'] = False
            active_list_slot.loc[
                active_list_slot['Name'] == slot_name, 'Use'] = True
        else:
            Data.data_full[slot_name] = pd.concat(
                [Data.data_full[slot_name], data_current])

        if 'Count' not in active_list_slot.columns:
            active_list_slot['Count'] = 0
        active_list_slot.loc[
            active_list_slot['Name'] == slot_name, 'Count'
        ] = Data.data_full[slot_name].shape[0]

        Data.set_active_data(active_list_slot)

    # ------------------------------------------------------------------
    # Старый метод оставлен без изменений (не используется)
    # ------------------------------------------------------------------
    @staticmethod
    def append_data_old(data_current, slot_name):
        print('Append Data')
        print('Data', data_current.shape)
        print('Slot=', slot_name)
        active_list_slot = Data.get_active_data()
        print('Active slot', active_list_slot)
        current_mes_type = active_list_slot[active_list_slot['Name'] == slot_name]
        print('Current_mes_type', current_mes_type)
        if current_mes_type['Value'].to_string(index=False) != '6':
            print(data_current['Machine_Type'])
            print(data_current.shape)
            if data_current['Machine_Type'].iloc[0] == 25:
                data_current = data_current[
                    data_current['Status'] == 'stable'].copy()
                data_current['Fr'] = pd.to_numeric(data_current['Fr'],
                                                   errors='coerce')
                data_current['Nominal'] = pd.to_numeric(data_current['Nominal'],
                                                        errors='coerce')
            else:
                data_current['Fr'] = data_current['Fr'].astype(float)
                data_current['Nominal'] = data_current['Nominal'].astype(float)
                data_current = data_current[data_current['Fr'] < 1e12]
                print(data_current.shape)
            if len(data_current) > 0 and data_current['Machine_Type'].iloc[0] == 25:
                mask = (data_current['Fr'] - data_current['Nominal']).abs() < 100000
                data_current.loc[mask, 'Fr'] = (
                    (data_current.loc[mask, 'Fr'] - data_current.loc[mask, 'Nominal'])
                    / data_current.loc[mask, 'Nominal']
                ) * 1e6
        else:
            print(data_current.columns)
            data_current = data_current[data_current['F'].notna()]
            data_current.rename(columns={'F': 'Fr', 'Cq': 'C1', 'L': 'L1'},
                                inplace=True)
            data_current['Fs'] = data_current['Fr']
            data_current['FL'] = data_current['Fr']

        data = Data.get_data(slot_name)
        print('Данные текущего слота', data)
        if data.empty:
            Data.data_full[slot_name] = data_current
            if 'Use' not in active_list_slot.columns:
                active_list_slot['Use'] = False
            active_list_slot.loc[
                active_list_slot['Name'] == slot_name, 'Use'] = True
        else:
            Data.data_full[slot_name] = pd.concat(
                [Data.data_full[slot_name], data_current])
        if 'Count' not in active_list_slot.columns:
            active_list_slot['Count'] = 0
        active_list_slot.loc[active_list_slot['Name'] == slot_name, 'Count'] = \
            Data.data_full[slot_name].shape[0]
        Data.set_active_data(active_list_slot)

    @staticmethod
    def update_slots_data():
        active_slot_list = Data.get_active_data()
        for index, row in active_slot_list.iterrows():
            if row['Name'] not in Data.data_full or Data.data_full[row['Name']] is None:
                Data.data_full[row['Name']] = pd.DataFrame()
        for key in list(Data.data_full.keys()):
            if key not in active_slot_list['Name'].values:
                Data.data_full.pop(key)

    @staticmethod
    def add_slot_data(slot_name):
        Data.data_full[slot_name] = pd.DataFrame()

    @staticmethod
    def del_slot_data(slot_name):
        Data.data_full.pop(slot_name)

    @staticmethod
    def get_active_data():
        if Data.active_data_list.empty:
            Data.active_data_list = pd.DataFrame({
                'Name': [1, 2, 3],
                'Value': [1, 2, 6],
            })
        if 'Use' not in Data.active_data_list.columns:
            Data.active_data_list['Use'] = False
        if 'Count' not in Data.active_data_list.columns:
            Data.active_data_list['Count'] = 0
        return Data.active_data_list

    @staticmethod
    def get_active_data_old():
        if Data.active_data_list.empty:
            Data.active_data_list = pd.DataFrame({
                'Name': [1, 2, 3],
                'Value': [1, 2, 6]
            })
        return Data.active_data_list

    @staticmethod
    def set_active_data(data):
        Data.active_data_list = data

    @staticmethod
    def add_msk_to_list(msk, slot_list):
        Data.msk_list[msk] = slot_list

    @staticmethod
    def get_msk_list():
        return Data.msk_list

    @staticmethod
    def _detect_freq_hz(v):
        """Определяет единицы значения по величине и приводит к Гц."""
        try:
            fv = float(v)
        except (TypeError, ValueError):
            return None
        av = abs(fv)
        if av <= 0:
            return None
        if av >= 1e6:  # уже Гц
            return fv
        if av >= 1e3:  # кГц
            return fv * 1e3
        # иначе — МГц (типично для резонаторов)
        return fv * 1e6

    @staticmethod
    def _normalize_freq_units(df: pd.DataFrame) -> None:
        """final_plating: Fr → ppm относительно spec nominal (Hz).

        • |Fr| > 20000 и Fr близко к Nominal (±10%)  → Fr в Гц
        • |Fr| < 20000                                → Fr в ppm отн. Nominal
        """
        if df is None or df.empty or 'Fr' not in df.columns:
            return
        if 'Nominal' not in df.columns:
            return

        nominal = pd.to_numeric(df['Nominal'], errors='coerce')
        safe_nominal = nominal.where(nominal.abs() > 0)

        abs_fr = df['Fr'].abs()
        rel_diff = (df['Fr'] - nominal).abs() / safe_nominal.abs()

        mask_hz = (abs_fr > 20000) & (rel_diff <= 0.10) & safe_nominal.notna()
        mask_ppm = abs_fr < 20000
        undecided = (~mask_hz) & (~mask_ppm) & safe_nominal.notna()

        spec_hz = Data.get_spec_freq_nominal_hz()
        use_spec = spec_hz is not None and spec_hz > 0

        if use_spec:
            ref = float(spec_hz)
            if mask_hz.any():
                df.loc[mask_hz, 'Fr'] = (
                        (df.loc[mask_hz, 'Fr'] - ref) / ref * 1e6)
            if mask_ppm.any():
                df.loc[mask_ppm, 'Fr'] = (
                                                 nominal.loc[mask_ppm]
                                                 * (1 + df.loc[mask_ppm, 'Fr'] / 1e6)
                                                 - ref
                                         ) / ref * 1e6
        else:
            # Fallback: ppm относительно per-row Nominal
            if mask_hz.any():
                df.loc[mask_hz, 'Fr'] = (
                        (df.loc[mask_hz, 'Fr'] - nominal.loc[mask_hz])
                        / nominal.loc[mask_hz] * 1e6)

        if undecided.any():
            print(f'[append_data] {int(undecided.sum())} строк с '
                  f'неопределёнными единицами Fr — оставлены без изменений')

    @staticmethod
    def _normalize_psi_freq_units(df: pd.DataFrame) -> None:
        """PSI: Fr в ppm относительно Nominal → ppm относительно spec nominal."""
        if df is None or df.empty:
            return
        if 'Fr' not in df.columns or 'Nominal' not in df.columns:
            return

        spec_hz = Data.get_spec_freq_nominal_hz()
        if spec_hz is None or spec_hz <= 0:
            return

        nominal = pd.to_numeric(df['Nominal'], errors='coerce')
        if nominal.isna().all():
            return

        nominal_hz = pd.Series(
            [Data._detect_freq_hz(v) if pd.notna(v) else None for v in nominal],
            index=df.index,
        )
        rel_diff = (nominal_hz - spec_hz).abs() / spec_hz
        needs_conv = (rel_diff > 1e-4) & nominal_hz.notna()
        if not needs_conv.any():
            return

        abs_freq = nominal_hz * (1 + df['Fr'] / 1e6)
        df.loc[needs_conv, 'Fr'] = (
                (abs_freq - spec_hz) / spec_hz * 1e6)[needs_conv]

    @staticmethod
    def del_msk_from_list(msk):
        print("Del MSK FROM LIST")
        Data.msk_list.pop(msk)
        print('MSK', msk)
        active_slot_list = Data.get_active_data()
        print('Original slot list', active_slot_list)
        for index, row in active_slot_list.iterrows():
            data_full = Data.get_data(row['Name'])
            print('Del MSK FROM LIST Slot ', row['Name'], data_full.shape[0])
            if 'Count' in active_slot_list.columns:
                active_slot_list.loc[
                    active_slot_list['Name'] == row['Name'], 'Count'
                ] = data_full.shape[0]
                print('Del MSK FROM LIST Slot Count  ', data_full.shape[0])
        print('slot list', active_slot_list)
        Data.set_active_data(active_slot_list)