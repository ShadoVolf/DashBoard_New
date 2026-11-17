import pickle
import socket
import os
from typing import Dict, List, Any

from Pribory.Network_Analyzer.VNA_Utils import parse_cal_filename, plot_text_graph


class VNA_Socket:
    def __init__(self, port=5025, serial=None):
        self.IP = "127.0.0.1"
        self.port = port
        self.status = None
        self.client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.client.connect((self.IP, self.port))
            self.id = self.get_type()
            if serial in self.id:
                self.status = 'OK'
        except socket.error as e:
            print(f"Socket error: {e}")
            self.client = None

    def _send_command(self, command: str, wait_response: bool = True) -> str:
        if not self.client:
            return ""
        try:
            self.client.sendall(f"{command}\n".encode())
            if not wait_response:
                return ""

            response = b""
            while True:
                part = self.client.recv(4096)
                # print(len(part), part)
                response += part
                if b'\n' in part:
                    break
            return response.decode().strip()
        except socket.error as e:
            print(f"Communication error: {e}")
            return ""

    def _send_control(self, command: str) -> str:
        if not self.client:
            return ""
        try:
            self.client.sendall(f"{command}\n".encode())
        except socket.error as e:
            print(f"Communication error: {e}")
            return ""

    def get_type(self) -> str:
        return self._send_command("*IDN?")

    def set_options(self, data: Dict[str, Any]) -> None:
        commands = []

        # Smoothing (аналогично COM-логике)
        aperture = data.get('Apperture', 0)
        if aperture > 0:
            commands.append(f"CALC:SMO:APER {aperture}")
            commands.append("CALC:SMO:STATE ON")
        else:
            commands.append("CALC:SMO:STATE OFF")

        # Frequency (Center/Span вместо Start/Stop)
        commands.extend([
            f"SENS:FREQ:CENT {data['Center']}",
            f"SENS:FREQ:SPAN {data['Span']}"
        ])

        # Sweep settings
        commands.extend([
            f"SENS:SWE:POIN {data['Point']}",
            f"SENS:SWE:POIN:TIME {data['Delay']}"
        ])

        # Bandwidth and power
        commands.extend([
            f"SENS:BAND:RES {data['Filtr']}",
            f"SOUR:POW:LEV:IMM:AMPL {data['Power']}"
        ])

        # Measurement and selection
        commands.extend([
            "CALC:PAR:DEF 'S21'",
            "CALC:PAR:SEL 'S21'"
        ])

        # Averaging (явное отключение)
        commands.extend([
            "SENS:AVER:COUN 1",
            "SENS:AVER:STATE OFF"
        ])

        # Trigger
        commands.append("TRIG:SOUR BUS")

        # Отправка всех команд
        for cmd in commands:
            self._send_control(cmd)

    def calibrate(self, data: Dict[str, Any], path: str, file_name: str) -> None:
        self.set_options(data)

        self._send_command("SENS:CORR:STATE OFF")
        self._send_command("SENS:CORR:COLL:METH:RESP:THRU 2,1")
        self._send_command("SENS:CORR:COLL:ACQ:THRU 2,1")
        self._send_command("*OPC?")

        self._send_command("SENS:CORR:COLL:SAVE")
        cal_data = self._send_command("SENS:CORR:COEF? ET,2,1")

        os.makedirs(path, exist_ok=True)
        with open(f"{path}/{file_name}.bin", "w") as f:
            f.write(cal_data)

        freq_data = self._send_command("SENS:FREQ:DATA?")
        freq_list = [float(x) for x in freq_data.split(',')]

        cal_list = [float(x) for x in cal_data.split(',')]
        real = cal_list[::2]
        imag = cal_list[1::2]

        with open(f"{path}/{file_name}.txt", "w") as f:
            for f_val, r_val, i_val in zip(freq_list, real, imag):
                f.write(f"{f_val}\t{r_val}\t{i_val}\n")

        self._send_command(f"MMEM:STOR:CHAN1:CAL {path}/{file_name}")

    def calibration_short(self, file_name, path):
        """
        Выполняет калибровку короткого замыкания (Short Calibration) с использованием SCPI-команд
        и сохраняет результаты в указанной директории.

        Parameters:
            file_name (str): Имя файла для сохранения данных калибровки.
            path (str): Путь к директории, где будет создана поддиректория "State" для хранения файла.
        """
        if not self.client:
            return

        try:
            # Очищаем коррекцию
            self._send_command("SENS:CORR:CLE", wait_response=False)

            # Устанавливаем метод калибровки THRU между портами 2 и 1
            self._send_command("SENS:CORR:COLL:METH:RESP:THRU 2,1", wait_response=False)

            # Запускаем измерение калибровки
            self._send_command("SENS:CORR:COLL:ACQ:THRU 2,1", wait_response=False)

            # Ожидаем завершения измерения
            self._send_command("*WAI", wait_response=True)

            # Получаем данные калибровки
            data_response = self._send_command("SENS:CORR:COLL:DATA:THRU:TRAN? 2,1")
            try:
                data = list(map(float, data_response.split(',')))
            except:
                data = []

            # Получаем частотные данные
            freq_response = self._send_command("SENS:FREQ:DATA?")
            try:
                freq_data = list(map(float, freq_response.split(',')))
            except:
                freq_data = []

            # Сохраняем калибровку
            self._send_command("SENS:CORR:COLL:SAVE", wait_response=False)

            # Создаем директорию, если она не существует
            state_path = os.path.join(path, "State")
            os.makedirs(state_path, exist_ok=True)

            # Сохраняем данные с использованием pickle
            with open(os.path.join(state_path, file_name), 'wb') as stream:
                pickle.dump(data, stream)
            with open(os.path.join(state_path, file_name + "_Freq"), 'wb') as stream:
                pickle.dump(freq_data, stream)

        except Exception as e:
            print(f"Ошибка при выполнении калибровки: {e}")


    def Measure(self, Parameters):
        """
        Выполняет измерение заданных параметров на анализаторе цепей.

        Отправляет команду на одиночный запуск измерения, дожидается его завершения
        и возвращает данные по частоте и запрошенным параметрам в виде словаря.

        Аргументы:
            Parameters (list): Список строк-идентификаторов параметров (например, ["S11", "S21"]).

        Возвращает:
            dict: Словарь с данными измерений. Ключи:
                - "FREQ": список частот
                - Для каждого параметра из Parameters: соответствующий список данных
            Если подключение к прибору не установлено, возвращает словарь с ключами "FREQ" и параметрами, значения None.
        """
        if not self.client:
            # Создаем словарь с None для всех ключей
            return {"FREQ": None, **{param: None for param in Parameters}}

        # Запуск измерения и ожидание завершения
        self._send_control("TRIG:SEQ:SING")
        self._send_control("*WAI")

        # Получение частотных данных
        try:
            freq_response = self._send_command("SENS:FREQ:DATA?")
            frequencies = list(map(float, freq_response.split(',')))
        except (ValueError, AttributeError):
            frequencies = []

        # Инициализация словаря результатов
        result_dict = {"FREQ": frequencies}

        # Обработка каждого параметра
        for param in Parameters:
            self._send_control(f"CALC:SEL:FORM {param}")  # Установка формата данных

            # Получение сырых данных параметра
            p_response = self._send_command("CALC:SEL:DATA:FDAT?")
            try:
                raw_data = list(map(float, p_response.split(',')))
            except (ValueError, AttributeError):
                result_dict[param] = []
                continue

            # Обработка данных в зависимости от размера
            if len(raw_data) == 2 * len(frequencies):
                processed_data = raw_data[0::2]  # Извлечение каждого второго элемента
            elif len(raw_data) > len(frequencies):
                # Фильтрация ненулевых значений (но не более чем len(frequencies) элементов)
                processed_data = [
                                     val for val in raw_data
                                     if val != 0
                                 ][:len(frequencies)]
            else:
                processed_data = raw_data

            result_dict[param] = processed_data

        return result_dict


    '''
    Загружает и применяет калибровочные данные из указанного файла к измерительному устройству.

    Метод выполняет следующие действия:
    1. Проверяет наличие файла калибровки в указанной директории
    2. Временно изменяет частотный диапазон и количество точек измерения на значения, 
       извлеченные из имени файла калибровки
    3. Загружает калибровочные коэффициенты в устройство
    4. Сохраняет новые калибровочные коэффициенты
    5. Восстанавливает исходные настройки частотного диапазона и количества точек

    Примечание: Метод использует временные изменения настроек устройства для корректного 
    применения калибровочных данных, соответствующих конкретному частотному диапазону.

    Args:
        FileName (str): Имя файла калибровки (формат: CH{канал}_FREQ{начало}-{конец}_POIN{точки}.cal)
        Path (str): Базовый путь к директории, содержащей подкаталог 'State'

    Raises:
        FileNotFoundError: Если указанный файл калибровки отсутствует
        ValueError: При некорректном формате имени файла калибровки
        RuntimeError: При ошибках взаимодействия с измерительным устройством

    Example:
        >>> load_calibration("CH1_FREQ1000000-3000000000_POIN1001.cal", "/calibration/data")
        Загрузка калибровки канал 1 от 1000000 до 3000000000 точек 1001

    Notes:
        - Файл калибровки должен находиться в подкаталоге 'State' указанного пути
        - Метод автоматически извлекает параметры калибровки (канал, частоты, точки) из имени файла
        - Текущие настройки частотного диапазона сохраняются и восстанавливаются после применения калибровки
        - Использует метод parse_cal_filename() для разбора имени файла
        - Требует поддержки команд SENS:CORR:COLL для калибровки типа THRU 2-port
    '''

    def load_calibration(self, FileName: str, Path: str, print_plot=False) -> None:
        file_path = os.path.join(Path, "State", FileName)
        if not os.path.exists(file_path):
            print('File_NOT_Found')
            return

        with open(file_path, "rb") as f:
            data2 = pickle.load(f)

        file_path = os.path.join(Path, "State", FileName + '_Freq')
        if not os.path.exists(file_path):
            print('File_NOT_Found')
            return

        with open(file_path, "rb") as f:
            data_freq = pickle.load(f)
        # Преобразование данных в правильный формат
        start = self._send_command(f"SENSe:FREQuency:STARt?")
        stop = self._send_command(f"SENSe:FREQuency:STOP?")
        n = self._send_command(f"SENSe:SWEep:POINts?")

        ch, start1, stop1, n1 = parse_cal_filename(FileName)
        self._send_command(f"SENSe:SWEep:POINts {n1}", wait_response=False)
        self._send_command(f"SENS:FREQ:STAR {start1}", wait_response=False)
        self._send_command(f"SENSe:FREQuency:STOP {stop1}", wait_response=False)
        if print_plot:
            print(f"Загрузка калибровки канал {ch} от {format(start1/1E+6, '.2f')} до {format(stop1/1E6,'.2f')} точек {n1}")

        self._send_command(f"SENS:CORR:COLL:METH:THRU 2, 1", wait_response=False)
        self._send_command(f"SENS:CORR:COEF:METH:THRU 2, 1", wait_response=False)
        self._send_control(f"SENS:CORR:COLL:DATA:THRU:TRAN 2, 1, {data2}")
        self._send_control(f"SENSe:CORR:COLL:SAVE")
        self._send_control(f"SENSe:CORR:COEF:SAVE")

        self._send_command(f"SENSe:SWEep:POINts {n}", wait_response=False)
        self._send_command(f"SENS:FREQ:STAR {start}", wait_response=False)
        self._send_command(f"SENSe:FREQuency:STOP {stop}", wait_response=False)
        # Разделение данных на амплитуды и фазы
        frequencies = data_freq
        amplitudes = data2[::2]  # Четные индексы
        phases = data2[1::2]  # Нечетные индексы
        if print_plot:
            # Построение графиков
            plot_text_graph(frequencies, amplitudes, "Зависимость амплитуды от частоты")
            plot_text_graph(frequencies, phases, "Зависимость фазы от частоты")
