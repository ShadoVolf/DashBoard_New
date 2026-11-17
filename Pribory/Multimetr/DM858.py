import time
import pyvisa as visa
import random
import warnings
from Pribory.Multimetr.abstract_voltmeter import AbstractVoltmeter


class DM858(AbstractVoltmeter):
    def __init__(self, port=None):
        warnings.filterwarnings("ignore", category=visa.VisaIOWarning)
        self.resource_address = port
        self.rm = None
        self.instr = None
        self.connection_established = False
        self.emulate = False
        self.measurement_type = 'VOLT'

    def connect(self):
        if self.emulate:
            self.connection_established = True
            return True

        try:
            self.rm = visa.ResourceManager()

            if self.resource_address is None:
                resources = self.rm.list_resources()
                if resources:
                    self.resource_address = resources[0]
                else:
                    return False

            self.instr = self.rm.open_resource(self.resource_address)
            self.instr.timeout = 2000

            # Проверяем соединение
            idn = self.instr.query("*IDN?")
            print(f"Подключен к: {idn.strip()}")
            self.instr.write("*RST")
            time.sleep(1)

            self.connection_established = True
            return True
        except Exception as e:
            print(f"Ошибка подключения: {e}")
            return False

    def setup(self, measurement_type):
        self.measurement_type = measurement_type
        if not self.connection_established and not self.emulate:
            return

        if measurement_type == 'VOLT':
            if not self.emulate:
                self.instr.write("CONF:VOLT:DC AUTO,MIN")
        elif measurement_type == 'AMP':
            if not self.emulate:
                self.instr.write("CONF:CURR:DC AUTO,MIN")

    def read(self):
        if self.emulate:
            if self.measurement_type == 'AMP':
                measurement = random.uniform(0.01, 0.7) * 1000
                return f"{measurement:.2f}"
            else:
                measurement = random.uniform(0.0, 12.0)
                return f"{measurement:.3f}"

        if not self.connection_established:
            return "ERROR"

        try:
            measurement = float(self.instr.query("READ?"))
            if self.measurement_type == 'AMP':
                measurement = measurement * 1E3
                return f"{measurement:.2f}"
            else:
                return f"{measurement:.3f}"
        except Exception as e:
            print(f"Ошибка измерения: {e}")
            return "ERROR"

    def get_id(self):
        if self.emulate:
            return "Rigol Technologies,DM858E,EMULATED_VOLTMETER,00.01.00.00.20"

        if not self.connection_established:
            return "NOT CONNECTED"

        return self.instr.query("*IDN?").strip()

    def disconnect(self):
        if not self.emulate and self.instr:
            self.instr.close()
        if not self.emulate and self.rm:
            self.rm.close()
        self.connection_established = False

    def set_emulate(self, emulate):
        self.emulate = emulate