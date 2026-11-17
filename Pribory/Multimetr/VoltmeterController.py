import time
from abc import ABC, abstractmethod
# Убедитесь, что импортируются классы, а не модули
from Pribory.Multimetr.HP34401 import HP34401  # Импорт класса HP34401
from Pribory.Multimetr.DM858 import DM858  # Импорт класса DM858


class VoltmeterController_Multy:
    # Словарь для сопоставления имен приборов с классами
    DEVICE_CLASSES = {
        '34401A': HP34401,  # Теперь храним класс, а не модуль
        'DM858': DM858
    }

    def __init__(self, voltmeter=None, device_name=None, device_params=None,
                 measurement_type='VOLT', emulate=False):
        if voltmeter is not None:
            self.voltmeter = voltmeter
        elif device_name is not None:
            self.voltmeter = self.create_voltmeter(device_name, device_params or {})
        else:
            raise ValueError("Необходимо указать либо voltmeter, либо device_name")

        self.is_measuring = False
        self.data_queue = ''
        self.measurement_type = measurement_type
        self.voltmeter.set_emulate(emulate)

    @classmethod
    def create_voltmeter(cls, device_name, device_params):
        device_name = device_name.upper()
        if device_name not in cls.DEVICE_CLASSES:
            raise ValueError(f"Неизвестное устройство: {device_name}. Поддерживаются: 34401A, DM858")

        # Получаем класс из словаря и создаем экземпляр
        device_class = cls.DEVICE_CLASSES[device_name]
        return device_class(**device_params)

    # Остальные методы остаются без изменений
    def connect(self):
        return self.voltmeter.connect()

    def setup(self):
        self.voltmeter.setup(self.measurement_type)

    def serial_worker(self):
        if not self.voltmeter.connection_established:
            if not self.connect():
                self.data_queue = "ERROR"
                return self.data_queue
            self.setup()

        self.data_queue = self.voltmeter.read()
        return self.data_queue

    def end_measure(self):
        self.is_measuring = False
        self.voltmeter.disconnect()

    def get_id(self):
        return self.voltmeter.get_id()

    def test(self):
        if self.connect():
            self.setup()
            idn = self.get_id()
            self.end_measure()
            return 'OK', idn
        else:
            return 'ERROR', None

    def set_measurement_type(self, measurement_type):
        self.measurement_type = measurement_type
        if self.voltmeter.connection_established:
            self.voltmeter.setup(measurement_type)

    def get_device_info(self):
        return {
            'type': type(self.voltmeter).__name__,
            'connected': self.voltmeter.connection_established,
            'emulation': self.voltmeter.emulate,
            'measurement_type': self.measurement_type
        }