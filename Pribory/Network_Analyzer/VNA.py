from typing import Tuple, List, Optional
import re

import numpy as np
import pandas as pd
from sqlalchemy import create_engine

import Options
from Pribory.Network_Analyzer import VNA_Data
from Pribory.Network_Analyzer.VNA_COM import VNA_Constants, VNA_COM
from Pribory.Network_Analyzer.VNA_Socket import VNA_Socket

import os
import math
from tqdm import tqdm
import glob

from Pribory.Network_Analyzer.Vna_Options import read_power_data
from scipy.interpolate import interp1d
from scipy.misc import derivative


# Мета класс для контроля запуска единственного экземпляра
class VNA_Meta(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            instance = super().__call__(*args, **kwargs)
            cls._instances[cls] = instance
        return cls._instances[cls]


# Класс для работы с анализатором цепей
class VNA(metaclass=VNA_Meta):
    def __init__(self, vna_type='OBZOR 304', connection_type='COM', port='5025', channel=1):
        self.current_spec = None
        self.vna_type = vna_type
        self.connection_type = connection_type
        self.port = port
        self.serial = None
        self.status = None
        self.channel = channel
        self.path = ''
        # Получаем имя COM объекта
        self.app_name = VNA_Constants.get_active_x_name(self.vna_type)
        # Если тип соединения Active-X
        self.vna_com = None
        if self.connection_type == 'COM':
            print(self.app_name)
            self.vna_com = VNA_COM(self.app_name)

        id_ = self.vna_com.get_id()
        if 'ERROR' not in id_:
            self.serial = id_.split(", ")[2]
        self.get_serial_()
        print('Векторный анализатор цепей', self.vna_type)
        print("Серийный номер:", self.serial)
        print('Статус соединения COM ', self.status)
        self.vna_socket = VNA_Socket(port=int(port), serial=self.serial)
        print('Статус соединения Socket ', self.vna_socket.status)

    # Устанавливает значение номера канала для анализатора цепей
    def set_channel(self, value):
        self.channel = value

    # Проверка серийного номера
    def get_serial_(self):
        engine = create_engine(Options.get_connection_string())
        # SQL-запрос для выборки данных
        df = pd.DataFrame()
        query = f"Select * from `tr1300_id` order by `ID`"
        try:
            # Извлекаем данные в DataFrame
            df = pd.read_sql(query, engine)
            data = df[df['TR1300_ID'] == self.serial]
            if len(data) > 0:
                self.status = 'OK'
                self.path = data['Path'].iloc[0]
            else:
                self.status = 'ERROR'
        except Exception as e:
            print(f"Ошибка: {str(e)}")
        finally:
            engine.dispose()
        return df

    # Создает интервал калибровки с учетом запаса по краям 10%
    def create_calibration_bands(self, f_start, f_end, bandwidth, n_points_str):
        """Генерация калибровочных интервалов с ограничением 1-200 МГц"""
        n_points = int(n_points_str)
        if f_end < f_start:
            f_start, f_end = f_end, f_start

        f_start = max(1.0, f_start)
        f_end = min(200.0, f_end)

        if float(bandwidth) <= 0:
            raise ValueError("bandwidth must be positive")
        if n_points <= 0:
            raise ValueError("n_points must be positive")

        margin = 0.1 * float(bandwidth)

        if float(bandwidth) > (f_end - f_start):
            start_band = max(1.0, f_start - margin)
            end_band = min(200.0, f_end + margin)
            return [(start_band, end_band)]

        num_bands = math.ceil((f_end - f_start) / float(bandwidth))
        bands = []

        for i in range(num_bands):
            center_start = f_start + i * float(bandwidth)
            center_end = min(f_end, center_start + float(bandwidth))

            band_start = max(1.0, center_start - margin)
            band_end = min(200.0, center_end + margin)

            bands.append((band_start, band_end))

        return bands

    # Выполняет калибровку в заданных диапазонах частот
    def perform_calibration(self, dpg, ranges_dict, progress_bar_value, status_bar, bandwidth=10, n_points=301,
                            delay=0, filtr=100, power='100, 50', apperture=0, channel_name='1'):
        """Выполнение калибровки для всех диапазонов с индикацией прогресса"""
        # Инициализация директории
        state_dir = os.path.join(self.path, "State")
        os.makedirs(state_dir, exist_ok=True)

        '''Расчет мощности сигнала'''
        Power, R_res = read_power_data(power)
        power_value = VNA_Data.VNA_DATA.calculate_vna_power(Power, R_res)
        # Очистка старых файлов калибровки
        for file_path in glob.glob(os.path.join(state_dir, f"{channel_name}_*.cal")):
            try:
                os.remove(file_path)
            except Exception as e:
                print(f"Ошибка при удалении {file_path}: {e}")

        # Инициализация интерфейса
        print(f'Калибровка канала {channel_name}')
        dpg.set_value(status_bar, f'Калибровка канала {channel_name}')
        dpg.set_value(progress_bar_value, 0.0)

        # Подсчет общего количества полос
        total_bands = sum(
            len(self.create_calibration_bands(band['start'], band['end'], bandwidth, n_points))
            for band in ranges_dict.values()
        )

        with tqdm(total=total_bands, desc="Общий прогресс", unit="полос") as progress_bar:
            for band_id, band_info in ranges_dict.items():
                calibration_bands = self.create_calibration_bands(
                    band_info['start'], band_info['end'], bandwidth, n_points
                )

                for start_band, end_band in calibration_bands:
                    # Настройка параметров прибора
                    setup_dict = {
                        'Center': (start_band + end_band) / 2 * 1e6,
                        'Span': (end_band - start_band) * 1e6,
                        'Point': n_points,
                        'Delay': delay,
                        'Filtr': filtr,
                        'Power': power_value,
                        'Apperture': apperture
                    }
                    self.vna_com.set_options(setup_dict)

                    # Выполнение калибровки
                    filename = f"{channel_name}_{start_band:.1f}_{end_band:.1f}_{n_points}.cal"
                    self.vna_com.calibration_short(filename, self.path)

                    # Обновление прогресса
                    progress_bar.update(1)
                    progress_percent = progress_bar.n / total_bands
                    dpg.set_value(progress_bar_value, progress_percent)
                    dpg.configure_item(progress_bar_value, overlay=f"{progress_percent:.1%}")

        # Завершение
        dpg.set_value(status_bar, f'Калибровка канала {channel_name} завершена')
        tqdm.write(f"✅ Калибровка канала {channel_name} завершена")
        dpg.set_value(progress_bar_value, 1.0)

    def find_calibration_data(self) -> Tuple[List[int], str]:
        """
        Находит все файлы калибровки в указанной директории и возвращает
        список доступных каналов и интервалы частот.

        Args:
            path (str): Базовый путь к директории
            state (str): Поддиректория/состояние

        Returns:
            Tuple[List[int], str]: Список каналов и строка с интервалами частот
        """
        # Формируем полный путь к директории
        full_path = os.path.join(self.path, 'State')

        # Проверяем существование директории
        if not os.path.isdir(full_path):
            raise ValueError(f"Директория {full_path} не существует.")

        # Регулярное выражение для匹配 файлов по шаблону
        pattern = re.compile(r'^(\d+)_(\d+\.\d+)_(\d+\.\d+)_(\d+)\.cal$')
        channels = set()
        all_intervals = []

        # Проходим по всем файлам в директории
        for filename in os.listdir(full_path):
            if filename.endswith('.cal'):
                match = pattern.match(filename)
                if match:
                    channel = int(match.group(1))
                    start_freq = float(match.group(2))
                    end_freq = float(match.group(3))
                    channels.add(channel)
                    all_intervals.append((start_freq, end_freq))

        # Если файлы не найдены
        if not channels:
            return [], "Файлы калибровки не найдены"

        # Сортируем интервалы по начальной частоте
        all_intervals.sort(key=lambda x: x[0])

        # Объединяем интервалы
        merged = []
        if all_intervals:
            current_start, current_end = all_intervals[0]
            for start, end in all_intervals[1:]:
                if start <= current_end:
                    # Интервалы перекрываются или соприкасаются
                    current_end = max(current_end, end)
                else:
                    merged.append((current_start, current_end))
                    current_start, current_end = start, end
            merged.append((current_start, current_end))

        # Форматируем результат
        channel_list = sorted(channels)
        intervals_str = " ".join([f"{start:.2f}...{end:.2f} Мгц" for start, end in merged])

        return channel_list, intervals_str

    # Загружает данные калибровки для текущей номинальной частоты
    def load_call_short(self, nominal: float, select_channel: int, printall_=False):
        if printall_:
            print('Select calibration file')
        # Получаем все файлы для канала
        channel_files = self.get_calibration_files_for_channel(select_channel)
        if printall_:
            print('Channel', select_channel)
            print(f"Файлы для канала {select_channel}: {channel_files}")
        file_name = self.find_best_calibration_file(select_channel, nominal)
        if file_name is not None:
            self.vna_socket.load_calibration(file_name, self.path, printall_)
        else:
            print("Калибровка отсутствует")

    def find_best_calibration_file(self, channel: int, nominal_freq: float) -> Optional[str]:
        """
        Находит файл калибровки для заданного канала и частоты, который имеет
        максимальную разницу от края диапазона калибровки.

        Args:
            channel (int): Номер канала
            nominal_freq (float): Номинальная частота работы

        Returns:
            Optional[str]: Имя лучшего файла калибровки или None, если подходящий не найден
        """
        # Формируем полный путь к директории
        full_path = os.path.join(self.path, 'State')

        # Проверяем существование директории
        if not os.path.isdir(full_path):
            raise ValueError(f"Директория {full_path} не существует.")

        # Регулярное выражение для匹配 файлов по шаблону
        pattern = re.compile(r'^(\d+)_(\d+\.\d+)_(\d+\.\d+)_(\d+)\.cal$')
        candidate_files = []

        # Проходим по всем файлам в директории
        for filename in os.listdir(full_path):
            if filename.endswith('.cal'):
                match = pattern.match(filename)
                if match:
                    file_channel = int(match.group(1))
                    start_freq = float(match.group(2))
                    end_freq = float(match.group(3))

                    # Проверяем, подходит ли файл по каналу и частоте
                    if file_channel == channel and start_freq <= nominal_freq <= end_freq:
                        # Вычисляем минимальное расстояние до края диапазона
                        min_edge_distance = min(nominal_freq - start_freq, end_freq - nominal_freq)
                        candidate_files.append((min_edge_distance, filename, start_freq, end_freq))

        # Если нет подходящих файлов
        if not candidate_files:
            return None

        # Сортируем по минимальному расстоянию до края (в порядке убывания)
        candidate_files.sort(key=lambda x: x[0], reverse=True)

        # Возвращаем файл с максимальным минимальным расстоянием до края
        return candidate_files[0][1]

    def get_calibration_files_for_channel(self, channel: int) -> List[str]:
        """
        Возвращает все файлы калибровки для заданного канала.

        Args:
            channel (int): Номер канала

        Returns:
            List[str]: Список файлов калибровки для канала
        """
        # Формируем полный путь к директории
        full_path = os.path.join(self.path, 'State')

        # Проверяем существование директории
        if not os.path.isdir(full_path):
            raise ValueError(f"Директория {full_path} не существует.")

        # Регулярное выражение для匹配 файлов по шаблону
        pattern = re.compile(r'^(\d+)_(\d+\.\d+)_(\d+\.\d+)_(\d+)\.cal$')
        channel_files = []

        # Проходим по всем файлам в директории
        for filename in os.listdir(full_path):
            if filename.endswith('.cal'):
                match = pattern.match(filename)
                if match:
                    file_channel = int(match.group(1))
                    if file_channel == channel:
                        channel_files.append(filename)

        return channel_files

    # Результат проверки запуска анализатора цепей
    def test(self):
        return self.status, self.serial

    def close(self):
        self.vna_com.close()

    # Выполняет цикл сканирования указанных параметров
    def vna_measure(self, spc, par, channel, print_log=False):
        if print_log:
            print('Измерений канал', channel)
        self.current_spec = spc
        # Устанавливаем параметры измерения
        key_width = max(len(key) for key in spc.keys()) + 2
        value_width = max(len(str(value)) for value in spc.values()) + 2

        # Создаем разделитель
        separator = f"+{'-' * key_width}+{'-' * value_width}+"
        if print_log:
            # Выводим таблицу
            print(separator)
            for key, value in spc.items():
                print(f"| {key:<{key_width - 2}} | {value:>{value_width - 2}} |")
                print(separator)

        # self.vna_com.set_parameters(self.current_spec)
        self.vna_socket.set_options(self.current_spec)
        # Загружаем текущую калибровку
        self.load_call_short(float(self.current_spec['Center']) / 1e+6, channel)
        # Выполняем измерения
        res = self.vna_socket.Measure(par)
        VNA_Data.VNA_DATA.set_vna_measure_data(res)
        return VNA_Data.VNA_DATA.get_vna_measure_data()
        # return self.vna_com.Measure(par)

    # Функция для измерения статической емкости

    def measure_c0(self, channel, print_log=True):
        """
           Измеряет ёмкость C0 пьезоэлектрического элемента с помощью анализатора цепей.

           Параметры:
           ----------
           channel : int
               Номер канала анализатора цепей для измерения

           Возвращает:
           -----------
           tuple
               (c0_mean, c0_std) - среднее значение и стандартное отклонение ёмкости C0 в фарадах

           Действия:
           ---------
           1. Получает текущие настройки измерения от VNA
           2. Настраивает параметры для измерения C0
           3. Выполняет измерение реальной и мнимой составляющих импеданса
           4. Вычисляет значения C0 для каждой частотной точки
           5. Рассчитывает среднее значение и стандартное отклонение
           6. Выводит результаты в пикофарадах с округлением до 3 знаков
           """
        spc = VNA_Data.VNA_DATA.get_current_measure_spc()
        if print_log:
            print('Измерение С0...')
        spc_c0 = {
            'Center': spc['C0_Freq'],
            'Span': 1000,
            'Point': 30,
            'Filtr': 100,
            'Delay': 0,
            'Power': -10
        }
        par = ['IMAG', 'REAL']
        data = self.vna_measure(spc_c0, par, channel)

        freq = data['FREQ']
        Z = data['Z']
        c0_values = [VNA.solve_c0(z, f) for z, f in zip(Z, freq)]

        c0_mean = np.mean(c0_values)
        c0_std = np.std(c0_values, ddof=1)
        if print_log:
            # Форматированный вывод в пФ
            print(f'C0 = {c0_mean * 1e12:.3f} пФ, STdev = {c0_std * 1e12:.3f} пФ')

        return c0_mean, c0_std

    # Функция для расчета значения С0 по результатам измерений
    @staticmethod
    def solve_c0(Z: complex, F: float) -> float:
        """
            Вычисляет ёмкость C0 пьезоэлектрического элемента на основе комплексного импеданса и частоты.

            Использует формулу: C0 = -Im(Z) / (2 * π * F * |Z|²)
            где |Z|² = Re(Z)² + Im(Z)²

            Параметры:
            ----------
            Z : complex
                Комплексный импеданс элемента, полученный из измерений VNA
            F : float
                Частота измерения в герцах

            Возвращает:
            -----------
            float
                Ёмкость C0 в фарадах. Возвращает 0 в случае:
                - деления на ноль (когда знаменатель формулы равен 0)
                - отрицательного результата (физически невозможное значение)

            Примечания:
            -----------
            - Формула основана на эквивалентной схеме пьезоэлектрического резонатора
            - Отрицательные значения возникают из-за погрешностей измерения и отбрасываются
            - Метод является статическим и не требует создания экземпляра класса
            """
        real_part = Z.real
        imag_part = Z.imag
        denominator = 2 * math.pi * F * (real_part ** 2 + imag_part ** 2)

        if denominator == 0:
            return 0  # Чтобы избежать деления на ноль

        result = -imag_part / denominator

        if result < 0:
            result = 0

        return result

    def fast_scan(self, spc, channel, target_phi: float = 0):
        precision = float(spc['Precision'])
        F_data, f_error = self.Scan_iteration(spc, channel, target_phi)
        if f_error is not None:
            while f_error > precision:
                spc['Span'] = precision * 100
                spc['Center'] = F_data
                spc['Point'] = 201
                F_data, f_error = self.Scan_iteration(spc, channel, target_phi)
            return F_data, f_error
        else:
            return 0, 10000

    def search_scan(self, spc, channel, precision: float = 500):
        F_data, f_error = self.Scan_iteration(spc, channel, 0)
        while f_error > precision:
            spc['Span'] = f_error * 10
            spc['Center'] = F_data
            F_data, f_error = self.Scan_iteration(spc, channel, 0)
        dict_ = {
                'Freq': F_data,
                'ER': f_error
            }
        VNA_Data.VNA_DATA.set_measure_data_search(dict_)
        #print('Search result', dict_)
        return F_data, f_error

    def Scan_iteration(self, spc, channel, target_phi: float = 0):
        # Предполагается, что vna_measure возвращает данные в нужном формате
        data = self.vna_measure(spc, ["IMAG", "REAL"], channel)
        freqs = data['FREQ']
        phases = data['PHASE']
        dd, error = self.find_angle_crossing_with_error(freqs, phases, target_phi)

        return dd, error

    def find_angle_crossing_with_error(self, frequencies, phases, target_angle: float = 0):
        freqs = np.array(frequencies)
        phases = np.array(phases)

        # Ищем точки, где разность фаз и целевого угла меняет знак
        adjusted_phases = phases - target_angle
        sign_changes = np.where(np.diff(np.sign(adjusted_phases)))[0]

        if len(sign_changes) == 0:
            print(f"Не удалось найти пересечение с углом {target_angle}: знак разности фаз не меняется")
            return None, None

        idx = sign_changes[0]

        if np.sign(adjusted_phases[idx]) == np.sign(adjusted_phases[idx + 1]):
            print(f"Не удалось найти пересечение с углом {target_angle}: знак разности фаз не меняется")
            return None, None

        # Линейная интерполяция для нахождения целевого угла
        x1 = phases[idx]
        x2 = phases[idx + 1]
        y1 = freqs[idx]
        y2 = freqs[idx + 1]

        # Интерполяция для target_angle
        crossing_freq = y1 + (target_angle - x1) * (y2 - y1) / (x2 - x1)

        # Оценка погрешности
        df = y2 - y1
        dphase_df = (x2 - x1) / df

        if idx > 0 and idx + 2 < len(phases):
            dphase_df_left = (phases[idx] - phases[idx - 1]) / (freqs[idx] - freqs[idx - 1])
            dphase_df_right = (phases[idx + 2] - phases[idx + 1]) / (freqs[idx + 2] - freqs[idx + 1])
            d2phase_df2 = abs(dphase_df_right - dphase_df_left) / df
            error_nonlinear = 0.25 * abs(d2phase_df2) * df ** 2 / abs(dphase_df)
        else:
            error_nonlinear = df / 4

        max_error = error_nonlinear
        return crossing_freq, max_error

    def measure(self, channel):
        spc = VNA_Data.VNA_DATA.get_current_measure_spc().copy()
        precision = float(spc['Precision'])
        spc_main = VNA_Data.VNA_DATA.extract_current_measure_spc_data(None).copy()
        if 'Search' in spc.keys():
            if spc['Search'] == 'ON':
                spc_local = VNA_Data.VNA_DATA.extract_current_measure_spc_data('Search')
                precision_local = float(spc['Span']) / 2
                f, f_error = self.search_scan(spc_local, channel, precision=precision_local)
                spc_main['Center'] = f
        c0, c0_error = self.measure_c0(channel, print_log=False)
        result = self.measure_two_point(spc_main, channel, float(c0), precision)
        F_ppm = ((result['Freq'] - float(spc['Nominal'])) / float(spc['Nominal'])) * 1E+6
        result['F_ppm'] = F_ppm
        return result

    # Выполняет быстрое измерения на АЦ
    def Scan(self):
        spc = VNA_Data.VNA_DATA.get_current_measure_spc()
        scan_type = spc['Scan']
        spc_scan = VNA_Data.VNA_DATA.extract_current_measure_spc_data('Scan')
        temp_data = VNA_Data.VNA_DATA.get_measure_data_scan()
        if len(temp_data) > 0:
            spc_scan['Center'] = temp_data['Freq']
            spc_scan['Phi'] = temp_data['Phi']
        else:
            spc_scan['Phi'] = 0
        if scan_type == 'Full':
            result = self.measure(self.channel)
            result_dict = result
        elif scan_type == 'Normal':
            c0, c0_error = self.measure_c0(self.channel, print_log=False)
            result = self.measure_two_point(spc_scan, self.channel, float(c0), float(spc['Precision']))
            F_ppm = ((result['Freq'] - float(spc['Nominal'])) / float(spc['Nominal'])) * 1E+6
            result['F_ppm'] = F_ppm
            result_dict = result
        elif scan_type == 'Fast':
            result, error = self.fast_scan(spc_scan, self.channel, float(spc_scan['Phi']))
            if result is not None:
                F_ppm = ((result - float(spc['Nominal'])) / float(spc['Nominal'])) * 1E+6
            else:
                F_ppm = None
            if len(temp_data) == 0:
                temp_data['Phi'] = 0
            result_dict = {'Freq': result,
                           'ER': error,
                           'F_ppm': F_ppm,
                           'Phi': temp_data['Phi']
                           }
        else:
            result_dict = {'ER': 'Ошибка выбора режима сканирования'}

        VNA_Data.VNA_DATA.set_measure_data_scan(result_dict)
        if 'Freq' in result_dict.keys():
            return format(result_dict['Freq'], '.3f')
        else:
            return None

    def measure_two_point(self, spc, channel, C0: float, precision: float = 0.05) -> dict:
        """
        Измерение параметров резонатора двухточечным методом

        Parameters:
        measurement_data: словарь с данными измерений VNA
        C0: паразитная емкость
        precision: точность измерения

        Returns:
        Словарь с результатами измерений
        """
        # Выполняем измерений

        data = self.vna_measure(spc, ["IMAG", "REAL"], channel)
        # Извлекаем необходимые массивы
        freqs = data['FREQ']
        phases = data['PHASE']  # Фаза в радианах

        # Преобразуем фазу в градусы для проверок
        phase_deg = np.rad2deg(phases)
        dfi_max = np.max(phase_deg)
        dfi_min = np.min(phase_deg)
        # Проверка возможности измерения
        if dfi_max - dfi_min < 50:
            return {
                'Freq': 0.0,
                'Phi': 0.0,
                'R': 0.0,
                'C': 0.0,
                'L': 0.0,
                'Q': 0.0,
                'ER': 0.0,
                'error': 'Недостаточный диапазон фазы для измерения'
            }

        # Коррекция фазы
        temp = phases[0] - (phases[0] - np.min(phases)) / 2
        if dfi_max + dfi_min > 10:
            phases -= temp  # Коррекция смещения фазы
            data['PHASE'] = phases  # Обновляем данные

        # Итерационный поиск параметров
        result = {
            'Freq': float(spc['Center']),
            'Phi': 0.0,
            'R': 0.0,
            'C': 0.0,
            'L': 0.0,
            'Q': 0.0,
            'ER': 0.0
        }
        count = 1000
        freq_prev = float(spc['Center'])
        iter_ = True
        while iter_:

            phase_target = np.deg2rad(result['Phi'])
            freq_prev = result['Freq']

            result = self.get_fr(data, phase_target, C0, 0.001)
            if count > 0 and abs(freq_prev - result['Freq']) > precision:
                iter_ = True
            else:
                iter_ = False
            count -= 1

        result['ER'] = abs(freq_prev - result['Freq'])
        result['C0'] = C0
        VNA_Data.VNA_DATA.set_measure_data(result)
        return result

    def get_fr(self, data: dict, phase_angle: float, C0: float, precision: float = 0.01, ph_border=20) -> dict:
        """
        Расчет параметров резонансного контура

        Parameters:
        data: обработанные данные измерений VNA
        phase_angle: целевой фазовый угол
        C0: паразитная емкость
        precision: точность расчета

        Returns:
        Словарь с результатами расчетов
        """
        # Извлекаем необходимые массивы
        freqs = data['FREQ']
        phases = data['PHASE']
        reals = data['REAL']
        imags = data['IMAG']
        # Преобразование целевых фаз в радианы
        ph1 = phase_angle + np.deg2rad(ph_border)
        ph2 = phase_angle - np.deg2rad(ph_border)
        #print('PH', ph1, ph2)
        # Поиск частот для заданных фаз
        f_minus45, error1 = self.find_freq_at_phase(freqs, phases, ph2, precision)
        f_plus45, error2 = self.find_freq_at_phase(freqs, phases, ph1, precision)
        #print('F', f_minus45, f_plus45)
        # Расчет комплексных проводимостей
        Y1 = self.get_admittance(freqs, reals, imags, C0, f_minus45)
        Y2 = self.get_admittance(freqs, reals, imags, C0, f_plus45)
        #print('Y', Y1, Y2)
        a1, b1 = Y1.real, Y1.imag
        a2, b2 = Y2.real, Y2.imag
        #print('A', a1, a2)
        #print('B', b1, b2)
        # Расчет параметров
        w1 = 2 * np.pi * f_minus45
        w2 = 2 * np.pi * f_plus45
        #print('W', w1, w2)
        R1 = (abs(a1) + abs(a2)) / 2
        C1 = (w2 ** 2 - w1 ** 2) / (w1 ** 2 * w2 * b2 - w2 ** 2 * w1 * b1)
        L1 = (w1 * b1 - w2 * b2) / (w1 ** 2 - w2 ** 2)

        Fr = 1 / (2 * np.pi * np.sqrt(L1 * C1))
        Q = (2 * np.pi * Fr * L1) / R1 if R1 != 0 else 0

        # Интерполяция фазы на резонансной частоте
        phase_interp = interp1d(freqs, phases, kind='cubic', fill_value='extrapolate')
        ph = phase_interp(Fr)

        return {
            'Freq': Fr,
            'Phi': np.rad2deg(ph),
            'R': R1,
            'C1': C1,
            'L1': L1,
            'Q': Q,
            'ER': 0.0
        }

    @staticmethod
    def get_admittance(freqs: np.ndarray, reals: np.ndarray, imags: np.ndarray,
                       C0: float, target_freq: float) -> complex:
        """
        Расчет комплексной проводимости

        Parameters:
        freqs: массив частот
        reals: действительная часть S21
        imags: мнимая часть S21
        C0: паразитная емкость
        target_freq: частота для расчета
        Z0: характеристическое сопротивление

        Returns:
        Комплексная проводимость
        """
        Z0 = VNA_Data.VNA_DATA.get_vna_z0()
        # Интерполяция S-параметров
        real_interp = interp1d(freqs, reals, kind='cubic', fill_value='extrapolate')
        imag_interp = interp1d(freqs, imags, kind='cubic', fill_value='extrapolate')

        s21_real = real_interp(target_freq)
        s21_imag = imag_interp(target_freq)
        S21 = complex(s21_real, s21_imag)

        # Расчет импеданса и проводимости
        Z = 2 * Z0 * (1 - S21) / S21
        Y = 1 / Z

        # Коррекция емкости
        C0_corr = C0 * 1e-12
        Y_corr = complex(Y.real, Y.imag - 2 * np.pi * target_freq * C0_corr)
        return 1 / Y_corr

    @staticmethod
    def find_freq_at_phase(freqs: np.ndarray, phases: np.ndarray,
                           target_phase: float, precision: float) -> tuple:
        """
        Поиск частоты по заданному фазовому углу с оценкой погрешности

        Parameters:
        freqs: массив частот
        phases: массив фаз (в радианах)
        target_phase: целевой фазовый угол (в радианах)
        precision: точность поиска

        Returns:
        Кортеж (частота, погрешность частоты), соответствующая целевому фазовому углу
        """
        phase_interp = interp1d(freqs, phases, kind='cubic', fill_value='extrapolate')

        # Поиск методом деления отрезка пополам
        f_min, f_max = np.min(freqs), np.max(freqs)

        while f_max - f_min > precision:
            f_mid = (f_min + f_max) / 2
            phase_mid = phase_interp(f_mid)
            if phase_mid < target_phase:
                f_max = f_mid
            else:
                f_min = f_mid

        freq_result = (f_min + f_max) / 2

        # Оценка погрешности через производную фазы по частоте
        try:
            # Вычисляем производную d(phase)/df в найденной точке
            dphase_df = derivative(phase_interp, freq_result, dx=precision)

            # Оценка погрешности измерения фазы (можно адаптировать под конкретные условия)
            phase_error = 0.01  # примерное значение погрешности измерения фазы в радианах

            # Погрешность частоты: delta_f = delta_phase / |dphase/df|
            freq_error = phase_error / abs(dphase_df) if abs(dphase_df) > 1e-10 else np.inf
        except:
            # Если не удалось вычислить производную, используем консервативную оценку
            freq_error = precision * 2

        return freq_result, freq_error
