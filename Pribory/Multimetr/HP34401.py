import time

import serial
import random
from Pribory.Multimetr.abstract_voltmeter import AbstractVoltmeter


class HP34401(AbstractVoltmeter):
    def __init__(self, port='COM1', baudrate=9600):
        self.port = port
        self.baudrate = baudrate
        self.ser = None
        self.connection_established = False
        self.emulate = False
        self.measurement_type = 'VOLT'

    def connect(self):
        if self.emulate:
            self.connection_established = True
            return True

        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=serial.EIGHTBITS,
                parity=serial.PARITY_NONE,
                stopbits=serial.STOPBITS_ONE,
                timeout=1
            )
            self._set_setup()
            return True
        except Exception as e:
            print(f"Ошибка подключения: {str(e)}")
            return False

    def _set_setup(self):
        if self.emulate:
            return

        if self.measurement_type == 'VOLT':
            self.ser.write(b'*RST\n')
            self.ser.write(b'SYST:REM\n')
            self.ser.write(b'CONF:VOLT:DC 100,0.001\n')
            time.sleep(0.1)
            self.ser.write(b'VOLT:DC:RANG:AUTO 1\n')
        elif self.measurement_type == 'AMP':
            self.ser.write(b'*RST\n')
            self.ser.write(b'SYST:REM\n')
            self.ser.write(b'CONF:CURR:DC\n')
            time.sleep(0.1)
            self.ser.write(b'CURR:DC:RANG:AUTO 1\n')

        time.sleep(0.5)
        self.connection_established = True

    def setup(self, measurement_type):
        self.measurement_type = measurement_type
        if self.connection_established:
            self._set_setup()

    def read(self):
        if self.emulate:
            if self.measurement_type == 'AMP':
                measurement = random.uniform(0.01, 0.7) * 1000
                return f"{measurement:.2f}"
            else:
                measurement = random.uniform(0.0, 12.0)
                return f"{measurement:.3f}"

        try:
            self.ser.write(b'READ?\n')
            time.sleep(0.3)
            raw_data = self.ser.read_all()

            if raw_data:
                measurement = float(raw_data.decode().strip())
                if self.measurement_type == 'AMP':
                    measurement = measurement * 1E3
                    return f"{measurement:.2f}"
                else:
                    return f"{measurement:.3f}"
            return "ERROR"
        except Exception as e:
            print("ERROR", e)
            return "ERROR"

    def get_id(self):
        if self.emulate:
            return "HEWLETT-PACKARD,34401A,0,EMULATED_VOLTMETER"

        self.ser.write(b'*IDN?\r\n')
        time.sleep(0.1)
        str_id = self.ser.read_until(b'\n').decode().strip()
        print(str_id)
        return str_id

    def disconnect(self):
        if self.ser and self.ser.is_open:
            self.ser.close()
        self.connection_established = False

    def set_emulate(self, emulate):
        self.emulate = emulate