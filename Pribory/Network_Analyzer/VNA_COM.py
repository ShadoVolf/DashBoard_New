import time
from ctypes import Array

import pythoncom
import win32com.client
import os
import pickle

from Pribory.Network_Analyzer.VNA_Utils import parse_cal_filename


# Класс для подключения VNA по COM
class VNA_COM:
    def __init__(self, vna_type):
        self.VNA_Type = vna_type
        self.format = "MLOG"
        self.type = "LOG"
        self.setup = None

        try:
            pythoncom.CoInitialize()
            print('vna', self.VNA_Type)
            self._app = win32com.client.GetActiveObject(self.VNA_Type)
            print("Подключен к существующему анализатору")
        except Exception as e:
            # Если активного объекта нет, создаем новый
            try:
                pythoncom.CoInitialize()
                self._app = win32com.client.Dispatch(self.VNA_Type)
                while not self._app.Ready:
                    time.sleep(0.5)
                # self._app.SCPI.SYSTem.HIDe()
                print("Анализатор цепей успешно запущен")
            except Exception as e:
                raise RuntimeError(f"Не удалось создать COM-объект: {e}")
            # Проверяем, что объект создан
        if not self._app:
            raise RuntimeError("Соединение с анализатором не установлено")

    def close(self):
        pythoncom.CoUninitialize()
        del self._app

    # Возвращает ИД анализатора цепей и ERROR если подключение не удалось
    def get_id(self):
        if self._app is not None:
            return self._app.Name
        else:
            return 'ERROR'

    def measure(self):
        raise NotImplementedError("Not supported yet")

    # остановить выполнение операции
    def terminate(self):
        scpi = self._app.SCPI
        system = scpi.System
        system.Terminate()

    # Скрыть окно анализатора
    def hide(self):
        scpi = self._app.SCPI
        system = scpi.System
        system.Hide()

    # Показ окна анализатора
    def show(self):
        scpi = self._app.SCPI
        system = scpi.System
        system.Show()

    # Перезапуск анализатора
    def reset(self) -> None:
        if self._app is not None:
            self._app.SCPI.IEEE4882.RST()

    # Калибровка с использованием перемычки
    def calibration_short(self, file_name, path):
        """
            Выполняет калибровку короткого замыкания (Short Calibration) с использованием SCPI-команд
            и сохраняет результаты в указанной директории.

            Метод предполагает наличие инициализированного SCPI-интерфейса (self._app) и
            взаимодействует с оборудованием для выполнения калибровки типа "THRU", которая,
            согласно контексту, соответствует короткому замыканию. Результаты сохраняются
            в бинарном формате с использованием модуля pickle.

            Parameters:
                file_name (str): Имя файла для сохранения данных калибровки.
                path (str): Путь к директории, где будет создана поддиректория "State" для хранения файла.

            Raises:
                AttributeError: Если self._app не инициализирован.
                OSError: Если возникли ошибки при создании директории или записи файла.
                SCPIError: Если оборудование вернуло ошибку при выполнении SCPI-команд.

            Notes:
                - Требуется импорт модулей `os` и `pickle`.
                - Убедитесь, что оборудование поддерживает команды SCPI, используемые в методе.
                - Сохраненные данные специфичны для устройства и могут содержать комплексные значения
                  передачи (Transmission) между портами 2 и 1.
            """
        if self._app is not None:
            # Assuming SCPI interface methods are properly implemented in Python
            self._app.SCPI.SENSe.CORRection.CLEar()
            self._app.SCPI.SENSe.CORRection.COLLect.METHod.RESPonse.THRU = (2, 1)
            self._app.SCPI.SENSe.CORRection.COLLect.ACQuire.THRU = (2, 1)

            data = self._app.SCPI.SENSe.CORRection.COLLect.DATA.THRU.TRANsmission(2, 1)
            freq_data = self._app.SCPI.SENSe.FREQuency.DATA
            self._app.SCPI.SENSe.CORRection.COLLect.SAVE()
            # Create directory if it doesn't exist
            state_path = os.path.join(path, "State")
            os.makedirs(state_path, exist_ok=True)

            # Save data using pickle serialization
            with open(os.path.join(state_path, file_name), 'wb') as stream:
                pickle.dump(data, stream)
            with open(os.path.join(state_path, file_name + "_Freq"), 'wb') as stream:
                pickle.dump(freq_data, stream)

    def set_options(self, setup):
        self.show()
        if self._app and setup:
            # Smoothing settings
            if setup.get('Apperture', 0) > 0:  # Используем get для безопасного доступа
                self._app.SCPI.CALCulate.Selected.SMOothing.APERture = setup['Apperture']
                if not self._app.SCPI.CALCulate.Selected.SMOothing.STATe:
                    self._app.SCPI.CALCulate.Selected.SMOothing.STATe = True
            else:
                if self._app.SCPI.CALCulate.Selected.SMOothing.STATe:
                    self._app.SCPI.CALCulate.Selected.SMOothing.STATe = False

            # Frequency settings
            self._app.SCPI.SENSe.FREQuency.CENTer = setup['Center']  # Предполагаем, что значение уже числовое
            self._app.SCPI.SENSe.FREQuency.SPAN = setup['Span']

            # Sweep settings
            self._app.SCPI.SENSe.SWEep.POINts = setup['Point']
            self._app.SCPI.SENSe.SWEep.POINt.TIME = setup['Delay']

            # Bandwidth and power
            self._app.SCPI.SENSe.BANDwidth.RESolution = setup['Filtr']
            self._app.SCPI.SOURce.POWer.LEVel.IMMediate.AMPLitude = setup['Power']

            # Measurement parameters
            self._app.SCPI.CALCulate.PARameter.DEFine = "S21"

            # Averaging
            self._app.SCPI.SENSe.AVERage.COUNt = 1
            self._app.SCPI.SENSe.AVERage.STATe = False

            # Trigger
            self._app.SCPI.TRIGger.SEQuence.Source = "bus"

    def _convert_to_flat_array(self, loaded_data):
        """Преобразует данные в плоский массив [real1, imag1, real2, imag2, ...]"""
        # Если данные уже в правильном формате
        if isinstance(loaded_data, (list, tuple)) and all(isinstance(x, (float, int)) for x in loaded_data):
            return list(loaded_data)

        # Если данные представлены как список комплексных чисел
        if isinstance(loaded_data, (list, tuple)) and all(isinstance(x, complex) for x in loaded_data):
            flat_data = []
            for comp in loaded_data:
                flat_data.append(comp.real)
                flat_data.append(comp.imag)
            return flat_data

        # Если данные в другом формате
        raise ValueError("Неподдерживаемый формат данных")

    # Функция выполнения измерений списка заданных параметров
    def Measure_1(self, Parameters):
        """
        Выполняет измерения на подключенном приборе для заданных параметров.

        Args:
            Parameters (list): Список строковых идентификаторов измеряемых параметров
                              (например, ['S11', 'S21']).

        Returns:
            list: Список списков измеренных данных в формате:
                  [frequencies, param1_data, param2_data, ...]
                  None - если прибор не подключен
        """
        if self._app is None:
            return None

        # Инициируем измерение и ожидаем завершения
        self._app.SCPI.TRIGger.SEQuence.Single()
        self._app.SCPI.IEEE4882.WAI()

        # Получаем частотную сетку измерений
        frequencies = list(self._app.SCPI.SENSe.Frequency.Data)
        results = [frequencies]  # Первый элемент - список частот

        # Получаем данные для каждого запрошенного параметра
        for param in Parameters:
            self._app.SCPI.Calculate.Selected.Format = param
            param_data = list(self._app.SCPI.Calculate.Selected.Data.FDATa)

            # Обрабатываем данные в зависимости от их размера
            if len(param_data) == 2 * len(frequencies):
                # Данные содержат реальную и мнимую компоненты - берем каждое второе значение
                results.append(param_data[0::2])
            else:
                # Для других случаев берем данные как есть
                results.append(param_data)

        return results

    def Measure(self, Parameters):
        """
        Выполняет измерения на подключенном приборе для заданных параметров.

        Args:
            Parameters (list): Список строковых идентификаторов измеряемых параметров
                              (например, ['S11', 'S21']).

        Returns:
            dict: Словарь с измеренными данными в формате:
                  {
                      "FREQ": список частот,
                      "S11": данные для параметра S11,
                      "S21": данные для параметра S21,
                      ...
                  }
                  None - если прибор не подключен
        """
        if self._app is None:
            return None

        # Инициируем измерение и ожидаем завершения
        self._app.SCPI.TRIGger.SEQuence.Single()
        self._app.SCPI.IEEE4882.WAI()

        # Получаем частотную сетку измерений
        frequencies = list(self._app.SCPI.SENSe.Frequency.Data)

        # Создаем словарь для результатов, начиная с частот
        results = {"FREQ": frequencies}

        # Получаем данные для каждого запрошенного параметра
        for param in Parameters:
            self._app.SCPI.Calculate.Selected.Format = param
            param_data = list(self._app.SCPI.Calculate.Selected.Data.FDATa)

            # Обрабатываем данные в зависимости от их размера
            if len(param_data) == 2 * len(frequencies):
                # Данные содержат реальную и мнимую компоненты - берем каждое второе значение
                results[param] = param_data[0::2]
            else:
                # Для других случаев берем данные как есть
                results[param] = param_data

        return results


# Класс с константами VNA
class VNA_Constants:
    ActiveXObjectNames = {
        "OBZOR TR1300": "TRVNA.Application",
        "OBZOR 304": "S2VNA.Application",
        "C1209": "S2VNA.Application",
        "S5045": "S2VNA.Application",
        "OBZOR 103": "Obzor103.Application"
    }

    VNA_Fields = ["TR1300_ID", "Bar_Code", "Path", "VNA", "Ref", "RefCorection", "F_Correction"]
    PRS_Fields = ["Type", "Serial", "Bar_Code"]
    Call_Fields = ["Type", "SN", "Bar_Code"]

    Options_Fields = {
        "TR1300_ID": VNA_Fields,
        "VNA_PRS": PRS_Fields,
        "VNA_CALL": Call_Fields
    }

    @staticmethod
    def get_active_x_name(temp):
        return VNA_Constants.ActiveXObjectNames.get(temp)

    @staticmethod
    def get_options_fields():
        return VNA_Constants.Options_Fields
