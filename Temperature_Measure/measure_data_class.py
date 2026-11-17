import pandas as pd

from Authorization.Login import LoginUser
from Temperature_Measure.Save_To_mySql import insert_msk_value


class MEASURE_DATA:
    """
    Общие данные файла
    """
    measure_file = {'FileName': {},  # Содержит данные измерительного файла
                    'File_ID': {},
                    'Machine_Serial': {},
                    'Machine_Type': {},
                    'Archive': {},
                    'Status': {},
                    'Configuration': pd.DataFrame(),
                    'Size': {},
                    'Poverka': {},
                    'Poverka_Date': {},
                    'Poverka_Actual': {},
                    'Machine_Type_ID': None}
    '''
    Номер активного слота файла
    '''
    active_slot_number = None
    '''
    Содержит данные выбранных спецификаций и номер партии SETUPNUM
    '''
    spc_select_data = pd.DataFrame()
    '''
    Содержит данные для номеров для выбранного файла формат SETUPNUM, Positions, Numbers
    '''

    numbers_select_dict = {}
    '''
    Содержит данные на установленные МСК словарь
    '''
    msk = {}

    '''
    Словарь содержит данные обработок по номеру slota обработки
    '''
    measure_data = {}

    '''
    Словарь содержит данные о типе контрольного образца для слота файла
    '''
    etalon_type = {}

    '''
    Содержит словарь данных контрольных образцов тип 
    '''
    etalon = {}

    '''
    Содержит таблицу коррекции температуры для контрольных образцов
    '''
    control_rk_correction_temp_table = None

    '''
        Содержит таблицу коррекции точности настройки  для контрольных образцов
    '''
    control_rk_correction_f_table = None

    # Содержит статус возможности использования контрольных образцов
    control_rk_status = False

    '''
    Содержит словарь с полученными идентификаторами замеров (слоты измерений)
    '''
    measure_id = {}
    measure_id_otk = {}

    '''
    Содержит словарь с отметкой сохраненных слотов
    '''
    measure_save = {}
    measure_save_otk = {}
    '''
    Содержит словарь с отметкой выполненной печати
    '''
    measure_print = {}
    measure_print_otk = {}

    # Создаем словарь множителей для приставок СИ
    UNIT_PREFIXES = {
        'T': 1e12,  # тера
        'G': 1e9,  # гига
        'M': 1e6,  # мега
        'k': 1e3,  # кило
        '': 1,  # базовая единица
        'd': 1e-1,  # деци
        'c': 1e-2,  # санти
        'm': 1e-3,  # милли
        'μ': 1e-6,  # микро (u если латиница)
        'n': 1e-9,  # нано
        'p': 1e-12,  # пико
        'f': 1e-15  # фемто

    }

    # Список режимов измерения
    LoadType_Dict = {
        'SERIES': 'Fs_ppm',
        'EQREACT': 'Fs_ppm',
        'PHYSICAL': 'Fl_ppm',
        'NUMERICAL': 'Fs_ppm',
        'Physical': 'Fl_ppm'
    }

    # текущий фокус выбора номеров
    current_focus = None

    # Содержит количество активных слотов в файле
    slot_count = 0
    # Содержит словарь со статусов выбора печати протоколов

    print_select_dict = {
        'Main_Table': True,
        'Temperatures_Table':  True,
        'Correction': False
    }
    '''
    Блок для работы с выбором типов протоколов
    '''
    @staticmethod
    def get_protokol_print_sel():
        return MEASURE_DATA.print_select_dict

    @staticmethod
    def set_protokol_print_sel(protokol_type, value):
        MEASURE_DATA.print_select_dict[protokol_type] = value
        print("Выбор протокола", protokol_type, 'Установлен в', value)

    '''
    Блок для работы с отметками сохранения и печати
    '''

    # устанавливает статус выполнен ия печати и сохранения файлов в БД
    @staticmethod
    def set_save_status(slot, status_type, status, protokol_type):
        if protokol_type == 'ПСИ':
            if status_type == 'Print':
                MEASURE_DATA.measure_print[str(slot)] = status
            elif status_type == 'Save':
                MEASURE_DATA.measure_save[str(slot)] = status
        elif protokol_type == 'ОТК':
            if status_type == 'Print':
                MEASURE_DATA.measure_print_otk[str(slot)] = status
            elif status_type == 'Save':
                MEASURE_DATA.measure_save_otk[str(slot)] = status

    @staticmethod
    def get_save_status(slot):
        slot_str = str(slot)
        return {
            'Print_PSI': MEASURE_DATA.measure_print.get(slot_str, False),
            'Save_PSI': MEASURE_DATA.measure_save.get(slot_str, False),
            'Print_OTK': MEASURE_DATA.measure_print_otk.get(slot_str, False),
            'Save_OTK': MEASURE_DATA.measure_save_otk.get(slot_str, False)
        }

    '''
    Блок для работы с идентификаторами замеров
    '''

    # Устанавливает значение идентификатора замера для заданного слота измерений
    @staticmethod
    def set_measure_id(slot, type_, value):
        if type_ == 'ПСИ':
            MEASURE_DATA.measure_id[str(slot)] = value
        elif type_ == 'ОТК':
            MEASURE_DATA.measure_id_otk[str(slot)] = value

    @staticmethod
    def get_measure_id(slot, type_):
        if type_ == 'ПСИ':
            print('ПСИ')
            if str(slot) in MEASURE_DATA.measure_id.keys():
                id_s = MEASURE_DATA.measure_id[str(slot)]
            else:
                id_s = None

            if id_s is not None:
                return MEASURE_DATA.measure_id[str(slot)]
            else:
                file_data = MEASURE_DATA.get_data()
                operator = str(LoginUser.login[3]) + " " + str(LoginUser.login[5])
                # регистрируем замер
                id = insert_msk_value(MEASURE_DATA.get_msk(slot), file_data['FileName'], file_data['File_ID'],
                                      operator, type_)
                # Сохраняем данные в память
                MEASURE_DATA.set_measure_id(slot, type_, id)
                print('Измерение зарегистрированно', id)
                return id
        elif type_ == 'ОТК':
            print('OTK')
            if str(slot) in MEASURE_DATA.measure_id_otk.keys():
                id_s = MEASURE_DATA.measure_id_otk[str(slot)]
            else:
                id_s = None

            if id_s is not None:
                return MEASURE_DATA.measure_id_otk[str(slot)]
            else:
                file_data = MEASURE_DATA.get_data()
                operator = str(LoginUser.login[3]) + " " + str(LoginUser.login[5])
                # регистрируем замер
                id = insert_msk_value(MEASURE_DATA.get_msk(slot), file_data['FileName'], file_data['File_ID'],
                                      operator, type_)
                # Сохраняем данные в память
                MEASURE_DATA.set_measure_id(slot, type_, id)
                print('Измерение зарегистрированно', id)
                return id



    '''
    Блок для работы с контрольными образцами
    *********************************************************************************************************
    '''

    # Устанавливает тип Контрольного образца для выбранного слота
    @staticmethod
    def set_control_type(slot, value):
        MEASURE_DATA.etalon_type[str(slot)] = value

    # Возвращает значение
    @staticmethod
    def get_control_type(slot):
        return MEASURE_DATA.etalon_type.get(str(slot))

    # добавляет данные в список эталонов возможно только один набор на каждый тип эталонов
    @staticmethod
    def set_control_data(slot, value: {}):
        control_type = MEASURE_DATA.get_control_type(slot)
        MEASURE_DATA.etalon[control_type] = value

    # Возвращает данные для датчика типа T
    @staticmethod
    def get_control_data_T():
        if 'T' in MEASURE_DATA.etalon:
            return MEASURE_DATA.etalon['T']
        else:
            return {}

    # Возвращает данные для датчика типа RK
    @staticmethod
    def get_control_data_RK():
        if 'RK' in MEASURE_DATA.etalon:
            return MEASURE_DATA.etalon['RK']
        else:
            return {}

    # Запоминает протокол коррекции температуры для контрольных образцов
    @staticmethod
    def set_control_RK_corection_temp_table(value):
        MEASURE_DATA.control_rk_correction_temp_table = value

    # Возвращает протокол коррекции температуры для контрольных образцов
    @staticmethod
    def get_control_RK_corection_temp_table():
        return MEASURE_DATA.control_rk_correction_temp_table

    # Запоминает протокол коррекции точности настройки для контрольных образцов

    @staticmethod
    def set_control_RK_corection_f_table(value):
        MEASURE_DATA.control_rk_correction_f_table = value

    # Возвращает протокол коррекции точности настройки для контрольных образцов
    @staticmethod
    def get_control_RK_corection_f_table():
        return MEASURE_DATA.control_rk_correction_f_table

    # Вовращает статус использования контрольных образцов
    @staticmethod
    def get_control_RK_status():
        if len(MEASURE_DATA.get_control_data_T()) > 0 or len(MEASURE_DATA.get_control_data_RK()) > 0:
            MEASURE_DATA.control_rk_status = True
            return True
        else:
            MEASURE_DATA.control_rk_status = False
            return False

    # Возвращает тип используемого контрольного образца
    @staticmethod
    def get_control_RK_type():
        if len(MEASURE_DATA.get_control_data_T()) > 0:
            return 'Тип Т'
        else:
            return 'Тип RK'

    '''
    Блок функций для работы с сохраненным словарем МСК
    **************************************************************************************************
    '''

    @staticmethod
    def add_msk(slot, msk_str):
        MEASURE_DATA.msk[str(slot)] = msk_str

    @staticmethod
    def delete_msk(slot):
        if str(slot) in MEASURE_DATA.msk:
            del MEASURE_DATA.msk[str(slot)]

    @staticmethod
    def get_msk(slot):
        if str(slot) in MEASURE_DATA.msk:
            return MEASURE_DATA.msk[str(slot)]
        else:
            return None

    '''
    ****************************************************************************************************
    '''
    '''
    Блок функций для работы с данным файла
    *******************************************************************************************************************
    '''

    # Функция воозвращает данные партии по ее номеру. Полученная конфигурация файла
    @staticmethod
    def get_setupnum_data(setupnum: str) -> pd.DataFrame():
        """
        Метод получает активный номер слота выбора файла
        :param setupnum:
        :return:
        """
        if not MEASURE_DATA.measure_file['Configuration'].empty:
            # Преобразовать строку в число
            position = int(setupnum)

            # Получить строку по позиции
            row = MEASURE_DATA.measure_file['Configuration'].iloc[position - 1]
        else:
            row = None
        return row

    # Функция воозвращает данные файла
    @staticmethod
    def get_data():
        return MEASURE_DATA.measure_file

    # Функция возвращает заданный параметр из информации о файле кроме конфигурации
    @staticmethod
    def get_data_inf(name):
        return MEASURE_DATA.measure_file[name]

    '''
    *******************************************************************************************************************
    '''
    '''
    Блок функция для работы с данными спецификаций
    *******************************************************************************************************************
    '''

    # добавляем новую спецификацию к имеющимся данным
    @staticmethod
    def add_spc_to_list(row_number: str, spc_select_df: pd.DataFrame):
        spc_select_df['SETUPNUM'] = row_number
        if MEASURE_DATA.spc_select_data.empty:
            MEASURE_DATA.spc_select_data = spc_select_df.copy()
        else:
            spc_df = MEASURE_DATA.spc_select_data
            # Поиск уникальных комбинаций (Name, SETUPNUM) в основной таблице
            existing_pairs = spc_df[['Name', 'SETUPNUM']].drop_duplicates()
            # Фильтрация spc_new: оставляем только те строки, где комбинация (Name, SETUPNUM) отсутствует в main_df
            new_entries = spc_select_df[
                ~spc_select_df.set_index(['Name', 'SETUPNUM']).index.isin(
                    existing_pairs.set_index(['Name', 'SETUPNUM']).index
                )
            ]
            # Объединение с основным датафреймом
            MEASURE_DATA.spc_select_data = pd.concat([MEASURE_DATA.spc_select_data, new_entries], ignore_index=True)

    # Возвращает полный лист сохраненых спецификаций
    @staticmethod
    def get_spc_sel_list(setupnum: str):
        if not MEASURE_DATA.spc_select_data.empty:
            df = MEASURE_DATA.spc_select_data[MEASURE_DATA.spc_select_data['SETUPNUM'] == setupnum]
            if not df.empty:
                return MEASURE_DATA.spc_select_data[MEASURE_DATA.spc_select_data['SETUPNUM'] == setupnum]
        return None

    # Удаляет спецификации для заданной партии
    @staticmethod
    def delete_spc_slot(slot):
        df1 = MEASURE_DATA.spc_select_data
        if not df1.empty:
            if 'SETUPNUM' in df1.columns:
                filtered_df = df1[df1['SETUPNUM'] != slot]
                MEASURE_DATA.spc_select_data = filtered_df

    '''
    *******************************************************************************************************************
    '''
    '''
    Блок функция для работы с номерами
    *******************************************************************************************************************
    '''

    @staticmethod
    def get_numbers_list(slot):
        slot_key = str(slot)
        all_numbers = MEASURE_DATA.numbers_select_dict

        if all_numbers.get(slot_key) is not None and not all_numbers[slot_key].empty:
            return all_numbers[slot_key]

        # Создаем DataFrame, если его нет
        row = MEASURE_DATA.measure_file['Configuration'].iloc[int(slot) - 1]
        position_list = row['Position']
        new_df = pd.DataFrame({
            'Positions': position_list,
            'SETUPNUM': slot
        })
        MEASURE_DATA.numbers_select_dict[slot_key] = new_df
        return new_df

    @staticmethod
    def delete_number_slot(slot):
        slot_key = str(slot)
        if slot_key in MEASURE_DATA.numbers_select_dict:
            del MEASURE_DATA.numbers_select_dict[slot_key]

    @staticmethod
    def set_numbers_list(setupnum: str, df2: pd.DataFrame):
        # Объединяем df1 с df2 по ключевым колонкам
        df1 = MEASURE_DATA.get_numbers_list(setupnum)
        # Объединяем df1 и df2 по ключевым колонкам
        merged_df = df1.merge(
            df2[['SETUPNUM', 'Positions', 'Numbers']],
            on=['SETUPNUM', 'Positions'],
            how='left',
            suffixes=('', '_new')
        )
        # Если колонка Numbers уже была в df1, заменяем её значения
        if 'Numbers' in df1.columns:
            df1['Numbers'] = merged_df.get('Numbers_new', merged_df['Numbers'])
        else:
            df1['Numbers'] = merged_df['Numbers']
        # Удаляем временные колонки (если есть)
        df1.drop(columns=['Numbers_new'], errors='ignore', inplace=True)
        MEASURE_DATA.numbers_select_dict[setupnum] = df1

    '''
    **********************************************************************************************************************
    '''

    '''
    Блок общий функций
    '''

    # Удаление всех данных установленных пользователем для данного слота
    @staticmethod
    def clear_number_spc_data():
        MEASURE_DATA.numbers_select_dict = {}
        MEASURE_DATA.spc_select_data = pd.DataFrame()
        MEASURE_DATA.active_slot_number = None
        MEASURE_DATA.msk = {}
        MEASURE_DATA.measure_data = {}
        MEASURE_DATA.etalon = {}
        MEASURE_DATA.etalon_type = {}
        MEASURE_DATA.measure_id = {}
        MEASURE_DATA.measure_save = {}
        MEASURE_DATA.measure_print = {}
        MEASURE_DATA.slot_count = 0
        MEASURE_DATA.measure_id_otk = {}
        MEASURE_DATA.measure_save_otk = {}
        MEASURE_DATA.measure_print_otk = {}
