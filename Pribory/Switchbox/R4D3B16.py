from pymodbus import ModbusException
from pymodbus.client import ModbusSerialClient
from typing import List, Optional
import serial
import time

from RT.RT_TECH_Parameters.RT_Data import RT_DATA

N_RELAYS = 16
BAUDRATE = 9600
DELAY_AFTER_OPERATION = 0.005  # 5 ms
RELAY_CMD_ON = 0x0100
RELAY_CMD_OFF = 0x0200


class RelayController:
    def __init__(self, port: str, slave_id: int = 1, simulation_mode: bool = False):
        self.simulation_mode = simulation_mode
        self.client: Optional[ModbusSerialClient] = None
        self.slave_id = slave_id
        self.simulated_states: List[bool] = []
        self.port = port

        if not self.simulation_mode:
            self.client = ModbusSerialClient(
                port=port,
                baudrate=BAUDRATE,
                stopbits=1,
                bytesize=8,
                parity='N',
                timeout=1
            )
        else:
            self.simulated_states = RT_DATA.get_relay_states(slave_id)

    def reset_port(self):
        try:
            ser = serial.Serial(self.port)

            # Аппаратный сброс через DTR
            ser.setDTR(False)  # Установить DTR в 0
            time.sleep(0.1)  # Пауза для сброса устройства
            ser.setDTR(True)  # Вернуть DTR в 1

            ser.close()
            time.sleep(0.2)
            self.disconnect()
            time.sleep(0.1)
            self.connect()
            print("Аппаратный сброс выполнен.")
        except Exception as e:
            print(f"Ошибка: {e}")

    def connect(self) -> bool:
        if self.simulation_mode:
            return True
        return self.client.connect()  # type: ignore

    def disconnect(self):
        if not self.simulation_mode and self.client:
            self.client.close()

    def set_relays(self, states: List[bool]) -> None:
        if len(states) != N_RELAYS:
            raise ValueError(f"States list must have exactly {N_RELAYS} elements")

        # Группируем операции по состоянию для минимизации переключений
        for operation in [False, True]:
            for i, state in enumerate(states):
                if state == operation:
                    result = self.set_single_relay(i + 1, operation)
                    if not self.simulation_mode:
                        time.sleep(DELAY_AFTER_OPERATION)


    def set_single_relay(self, relay_number: int, state: bool) -> str:
        if not 0 <= relay_number <= N_RELAYS:
            return 'ERROR'

        if self.simulation_mode:
            self.simulated_states[relay_number - 1] = state
            RT_DATA.set_relay_states(self.slave_id, self.simulated_states)
            return 'OK'

        address = relay_number  # Addressing starts from 1
        value = RELAY_CMD_ON if state else RELAY_CMD_OFF
        response = self.client.write_register(  # type: ignore
            address=address,
            value=value,
            slave=self.slave_id
        )
        return 'OK' if not response.isError() else 'ERROR'

    def get_relays(self) -> tuple[List[bool], str]:
        """
            Получает текущее состояние реле через Modbus-протокол.

            Метод работает в двух режимах:
            - В режиме симуляции возвращает заранее заданные состояния
            - В реальном режиме читает holding-регистры Modbus-устройства

            Returns:
                tuple[List[bool], str]: Кортеж содержащий:
                    - List[bool]: Список булевых значений состояния реле,
                                 где True - реле включено, False - выключено
                    - str: Статус выполнения операции:
                          - 'OK' - операция выполнена успешно
                          - 'ERROR' - ошибка Modbus-протокола
                          - 'ERROR: {описание ошибки}' - исключение при выполнении

            Raises:
                ModbusException: При проблемах связи с Modbus-устройством
                                (перехватывается и возвращается как строка ошибки)

            Examples:
                >>> device.get_relays()
                ([True, False, True, False], 'OK')

                >>> device.get_relays()
                ([], 'ERROR: Connection timeout')

            Notes:
                - Адрес первого регистра реле: 0x01
                - Количество читаемых регистров определяется константой N_RELAYS
                - Для работы в реальном режиме требуется корректная настройка
                  Modbus-клиента (self.client) и slave_id
            """
        if self.simulation_mode:
            return self.simulated_states.copy(), 'OK'

        try:
            response = self.client.read_holding_registers(  # type: ignore
                address=0x01,
                count=N_RELAYS,
                slave=self.slave_id
            )
            if response.isError():
                return [], 'ERROR'
            return [reg == 1 for reg in response.registers], 'OK'
        except ModbusException as e:
            return [], f'ERROR: {str(e)}'

    @staticmethod
    def state_str_to_bool(state_str: str) -> List[bool]:
        if len(state_str) != N_RELAYS or any(c not in '01' for c in state_str):
            raise ValueError(f"State string must be {N_RELAYS} characters of 0/1")
        return [c == '1' for c in state_str]

    @staticmethod
    def state_bool_to_str(states: List[bool]) -> str:
        if len(states) != N_RELAYS:
            raise ValueError(f"States list must have exactly {N_RELAYS} elements")
        return ''.join('1' if s else '0' for s in states)

    def switch_test(self) -> str:
        try:
            _, status = self.get_relays()
            return status
        except Exception as e:
            return f'ERROR: {str(e)}'
