import math

import numpy as np


class VNA_DATA:
    # Состояние анализатора цепей
    vna_id = None
    vna_status = False
    vna_type = None

    # данные измерений с анализатора цепей
    VNA_Measure_Data = {}

    # Сопротивление прибора
    Z0 = 50

    # Текущая спецификация измерений
    current_measure_spc = {}

    # Результаты измерения последовательного резонанса
    current_measure_result = {}

    # Результаты быстрого сканирования
    current_measure_fast_scan ={}

    # реузльтаты измерения поиска

    current_measure_search = {}

    current_F = None
    current_F_ppm = None
    current_dF_ppm = None
    current_F_status = False
    current_R = None

    # Устанавливает значение текущего измерения последовательного резонанса
    @staticmethod
    def set_measure_data(value):
        VNA_DATA.current_measure_result = value
        VNA_DATA.current_measure_fast_scan = value
    # Получает текущие значения измерения последовательного резонанса
    @staticmethod
    def get_measure_data():
        return VNA_DATA.current_measure_result

    # Устанавливает значения текущего измерения поиска
    @staticmethod
    def set_measure_data_search(value):
        VNA_DATA.current_measure_search = value

    # Получает текущие значения измерения поиска
    @staticmethod
    def get_measure_data_search():
        return VNA_DATA.current_measure_search

    @staticmethod
    def set_measure_data_scan(value):
        VNA_DATA.current_measure_fast_scan = value

    # Получает текущие значения измерения поиска
    @staticmethod
    def get_measure_data_scan():
        return VNA_DATA.current_measure_fast_scan


    # задает значение входного сопротивления анализатора цепей
    @staticmethod
    def set_vna_z0(value):
        VNA_DATA.Z0 = value

    @staticmethod
    def get_vna_z0():
        return VNA_DATA.Z0

    # Возвращает значения id анализатора если он есть иначе None
    @staticmethod
    def get_vna_id():
        return VNA_DATA.vna_id

    # Устанавливает серийный номер текущего анализатора цепей
    @staticmethod
    def set_vna_id(vna_id):
        VNA_DATA.vna_id = vna_id

    # Устанавливает статус включения анализатора цепей
    @staticmethod
    def set_vna_status(status):
        VNA_DATA.vna_status = status

    # Получает статус включения анализатора
    @staticmethod
    def get_vna_status():
        return VNA_DATA.vna_status

    # Получает тип анализатора цепей
    @staticmethod
    def get_vna_type():
        return VNA_DATA.vna_type

    # Устанавливает тип анализатора цепей
    @staticmethod
    def set_vna_type(vna_type):
        VNA_DATA.vna_type = vna_type
    # Устанавливает состояние анализатора цепей
    @staticmethod
    def set_vna(vna_type, vna_id, status):
        VNA_DATA.vna_type = vna_type
        VNA_DATA.vna_status = status
        VNA_DATA.vna_id = vna_id


    # Возвращает результаты измерений
    @staticmethod
    def get_vna_measure_data():
        return VNA_DATA.VNA_Measure_Data

    # Записывает результаты измерений
    @staticmethod
    def set_vna_measure_data(value: dict):
        if all(key in value for key in ['FREQ', 'IMAG', 'REAL']):
            # Копируем данные и преобразуем списки в массивы NumPy
            VNA_DATA.VNA_Measure_Data = value.copy()
            real = np.array(value['REAL'])
            imag = np.array(value['IMAG'])

            # Вычисляем комплексные значения S
            S21 = real + 1j * imag

            # Обновляем данные в словаре
            VNA_DATA.VNA_Measure_Data['S'] = S21
            VNA_DATA.VNA_Measure_Data['PHASE'] = np.angle(S21)
            VNA_DATA.VNA_Measure_Data['MAG'] = np.abs(S21)

            # Исправленная формула для импеданса (с использованием правильного уравнения)
            # Расчет импеданса по указанной формуле: Z = (2 * Z0 * (1 - S21)) / S21
            VNA_DATA.VNA_Measure_Data['Z'] = 2*VNA_DATA.Z0 * ((1 - S21) / S21)

    # Возвращает текущую спецификацию измерений
    @staticmethod
    def get_current_measure_spc():
        return VNA_DATA.current_measure_spc

    # Устанавливает значение текущей спецификации измерений РТ
    @staticmethod
    def set_current_measure_spc(value):
        VNA_DATA.current_measure_spc = value
        power_str = VNA_DATA.current_measure_spc.get("Power", "")
        if power_str:
            try:
                # Разделяем строку и преобразуем в числа
                values = power_str.split(',')
                P_diss_microW = float(values[0].strip())  # Мощность в мкВт
                R_res = float(values[1].strip())  # Сопротивление резонатора

                # Конвертируем мкВт в Ватты (1 мкВт = 1e-6 Вт)
                P_diss_W = P_diss_microW * 1e-6

                # Вычисляем выходную мощность (значения Z0, R1, R2 по умолчанию)
                output_power = VNA_DATA.calculate_vna_power(P_diss_W, R_res)

                # Обновляем значение ключа "Power"
                VNA_DATA.current_measure_spc["Power"] = output_power
            except (ValueError, IndexError):
                print("Ошибка: некорректный формат данных в ключе 'Power'")

    # Функция выбирает из текущей спецификации данные для указанного сканирования
    @staticmethod
    def extract_current_measure_spc_data(prefix):
        data = VNA_DATA.current_measure_spc
        suffixes = ['Span', 'Precision', 'Filtr', 'Point', 'Delay']
        result = {}

        # Добавляем основные ключи Nominal и Power, если они есть
        if 'Nominal' in data:
            result['Nominal'] = data['Nominal']
            result['Center'] = data['Nominal']
        if 'Power' in data:
            result['Power'] = data['Power']

        # Добавляем значения для каждого суффикса
        for suffix in suffixes:
            if prefix is not None:
                key = f"{prefix}_{suffix}"  # Ключ с префиксом
            else:
                key = suffix  # Ключ без префикса

            # Используем значение из исходного словаря, если ключ существует
            if key in data:
                result[suffix] = data[key]
            else:
                # Если ключа нет, устанавливаем значение None
                result[suffix] = None

        return result

    # Функция для расчета выходной мощности прибора по мощности рассеивания на резонаторе
    @staticmethod
    def calculate_vna_power(P_diss, R_res, Z0=50, R1=0, R2=0):
        """
        Calculate the required VNA output power in dBm.

        :param P_diss: Dissipation power on the resonator (Watts)
        :param R_res: Expected resistance of the resonator (Ohms)
        :param Z0: Characteristic impedance of the VNA (Ohms)
        :param R1: First series resistor (Ohms), default 0
        :param R2: Second series resistor (Ohms), default 0
        :return: Required VNA output level (dBm)
        """
        try:
            # Calculate the argument for the logarithm
            numerator = 1000 * P_diss * (Z0 + R_res + R1 + R2) ** 2
            denominator = 4 * Z0 * R_res
            power_mW = numerator / denominator

            # Calculate dBm value
            P_dBm = 10 * math.log10(power_mW)
            return P_dBm
        except ValueError as e:
            raise ValueError(
                "Invalid input parameters: ensure all values are positive and non-zero where required.") from e
        except ZeroDivisionError:
            raise ZeroDivisionError("R_res cannot be zero.")

    # Функция для расчета мощности резонатора при известном выходе прибора
    @staticmethod
    def calculate_resonator_power(P_dBm, R_res, Z0, R1=0, R2=0):
        """
        Вычисляет мощность рассеяния на резонаторе по уровню выходного сигнала VNA.

        :param P_dBm: Уровень выходного сигнала VNA в дБм
        :param R_res: Сопротивление резонатора в Омах
        :param Z0: Волновое сопротивление системы в Омах
        :param R1: Первый дополнительный резистор в Омах (по умолчанию 0)
        :param R2: Второй дополнительный резистор в Омах (по умолчанию 0)
        :return: Мощность рассеяния на резонаторе в Ваттах
        """
        try:
            # Преобразуем мощность из дБм в милливатты
            P_mW = 10 ** (P_dBm / 10)

            # Преобразуем милливатты в ватты
            P_W = P_mW / 1000

            # Вычисляем мощность рассеяния на резонаторе
            numerator = P_W * 4 * Z0 * R_res
            denominator = (Z0 + R_res + R1 + R2) ** 2
            P_diss = numerator / denominator

            return P_diss
        except ValueError as e:
            raise ValueError(
                "Неверные параметры: убедитесь, что все значения положительны и ненулевые где требуется") from e
        except ZeroDivisionError:
            raise ZeroDivisionError("Сумма сопротивлений не может быть нулевой")
