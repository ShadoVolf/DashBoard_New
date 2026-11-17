"""
Класс для управления магазином сопротивлений
"""
from itertools import product
from typing import Tuple, Dict, List

from Pribory.Switchbox.R4D3B16 import RelayController


class SDPRB:
    def __init__(self, switch, port: str = 'NA', slave_id: int = 1, map_data: dict = None,
                 simulation_mode: bool = False):
        self.simulation_mode = simulation_mode
        self.switch_name = switch
        self.port = port
        self.slave_id = slave_id
        self.map = map_data
        self.controller = None


    # Подключаем контроллер коммутатора
    def _connect_switch(self):
        self.controller = RelayController(port=self.port, slave_id=self.slave_id, simulation_mode=self.simulation_mode)
        if not self.controller.connect():
            print("Не удалось подключиться к устройству")

    # Отключаем контроллер
    def _disconnect_switch(self):
        if self.controller is not None:
            self.controller.disconnect()

    # Получаем границы переключения магазина сопротивления на основе MAP
    def get_min_max_resistance_and_step(self):
        # Группируем сопротивления по типу
        grouped = {}
        for resistance, (addr, relay_num, r_type) in self.map.items():
            if r_type not in grouped:
                grouped[r_type] = []
            grouped[r_type].append(resistance)

        # Считаем минимум и максимум
        min_total = sum(min(resistances) for resistances in grouped.values())
        max_total = sum(max(resistances) for resistances in grouped.values())

        # Находим шаг магазина: минимальный шаг в любом из типов
        min_step = float('inf')
        for resistances in grouped.values():
            if len(resistances) < 2:
                continue  # Нужно хотя бы 2 значения для шага
            sorted_res = sorted(resistances)
            steps = [sorted_res[i + 1] - sorted_res[i] for i in range(len(sorted_res) - 1)]
            type_min_step = min(steps)
            if type_min_step < min_step:
                min_step = type_min_step

        # Если не нашли ни одного шага (например, все типы с одним реле), шаг = 0 или None
        if min_step == float('inf'):
            min_step = 0

        return min_total, max_total, min_step

    # Устанавливает ближайшее возможное сопротивление магазина.
    def set_resistance(self, target):
        # Определяем все возможные множители
        multipliers = ['x1', 'x10', 'x100', 'x1000', 'x10000', 'x100000', 'x1000000']

        # Создаем словарь с резисторами по типам
        resistors_by_type = {}
        for mult in multipliers:
            resistors_by_type[mult] = {k: v for k, v in self.map.items() if v[2] == mult}

        # Определяем границы диапазона
        min_val = sum(min(resistors) for resistors in resistors_by_type.values() if resistors)
        max_val = sum(max(resistors) for resistors in resistors_by_type.values() if resistors)

        # Корректируем целевое значение, если оно вне диапазона
        if target < min_val:
            target = min_val
        elif target > max_val:
            target = max_val

        # Инициализация переменных для поиска лучшей комбинации
        best_diff = float('inf')
        best_combination = {}

        # Сортируем множители по убыванию для жадного алгоритма
        sorted_multipliers = sorted(multipliers,
                                    key=lambda x: int(x[1:]) if x[1:] else 1,
                                    reverse=True)

        def find_best_combination(current_sum, current_combination, remaining_multipliers):
            nonlocal best_diff, best_combination

            if not remaining_multipliers:
                # Все множители обработаны, проверяем результат
                diff = abs(current_sum - target)
                if diff < best_diff:
                    best_diff = diff
                    best_combination = current_combination.copy()
                return

            # Берем следующий множитель
            current_mult = remaining_multipliers[0]
            next_multipliers = remaining_multipliers[1:]

            # Получаем доступные резисторы для текущего множителя
            available_resistors = resistors_by_type[current_mult]
            if not available_resistors:
                # Если для этого множителя нет резисторов, пропускаем его
                find_best_combination(current_sum, current_combination, next_multipliers)
                return

            # Сортируем резисторы по близости к оставшейся части
            remaining = target - current_sum
            sorted_resistors = sorted(available_resistors.items(),
                                      key=lambda x: abs(x[0] - remaining))

            # Берем только несколько наиболее подходящих вариантов для оптимизации
            for resistance, params in sorted_resistors[:3]:  # Ограничиваем поиск
                current_combination[resistance] = params
                find_best_combination(current_sum + resistance, current_combination, next_multipliers)
                current_combination.pop(resistance)

        # Запускаем рекурсивный поиск
        find_best_combination(0, {}, sorted_multipliers)

        # Формируем выходные данные
        result_value = sum(best_combination.keys())
        return result_value, best_combination

    # Выключает все реле магазина сопротивлений
    def magazine_off(self):
        new_states = [False] * 16
        self._connect_switch()
        self.controller.set_relays(new_states)
        self._disconnect_switch()
        return 'OK'

    # Устанавливает заданное сопротивление на магазине сопротивлений через реле
    def set_resistance_on_device(self, target_resistance: int) -> Tuple[int, Dict[int, List], str]:
        """
        Устанавливает заданное сопротивление на магазине сопротивлений через реле.

        Параметры:
            target_resistance (int): Целевое сопротивление в Омах.

        Возвращает:
            tuple: (actual_resistance, selected_relays, status)
                - actual_resistance (int): Фактически установленное сопротивление
                - selected_relays (dict): Словарь реле, которые были включены
                - status (str): 'OK' или 'ERROR: <описание>'
        """
        try:
            # 1. Определяем, какие реле нужно включить
            actual_resistance, selected_relays = self.set_resistance(target_resistance)

            # Проверяем, что выбран хотя бы один релейный набор
            if not selected_relays:
                return 0, {}, "ERROR: Не удалось подобрать комбинацию реле для установки сопротивления"

            # 2. Получаем список всех реле, которые нужно включить (по индексу в контроллере)
            required_relay_indices = {config[1] for _, config in selected_relays.items()}

            self._connect_switch()

            # 3. Получаем текущее состояние всех реле
            current_states, status = self.controller.get_relays()
            if status != 'OK':
                self._disconnect_switch()
                return 0, {}, f"ERROR: Не удалось получить состояние реле: {status}"

            # 4. Создаём промежуточное состояние: включаем ВСЕ требуемые реле, не выключая текущие
            intermediate_states = current_states.copy()  # Начинаем с текущего состояния

            # Включаем все требуемые реле (добавляем к текущим)
            for relay_index in required_relay_indices:
                if not (1 <= int(relay_index) <= 16):
                    self._disconnect_switch()
                    return 0, {}, f"ERROR: Недопустимый номер реле: {relay_index}"
                intermediate_states[relay_index - 1] = True

            # 5. Применяем промежуточное состояние (гарантируем, что есть включенные реле)
            self.controller.set_relays(intermediate_states)

            # 6. Создаём финальное состояние: выключаем ВСЕ, потом включаем только нужные
            final_states = [False] * 16  # Все выключены
            # Включаем только требуемые
            for relay_index in required_relay_indices:
                final_states[relay_index - 1] = True

            # 7. Применяем финальное состояние
            self.controller.set_relays(final_states)

            # 8. Проверка: убедимся, что реле действительно включились
            post_states, check_status = self.controller.get_relays()
            self._disconnect_switch()

            if check_status != 'OK':
                return 0, {}, f"ERROR: Не удалось проверить состояние после установки"

            # Сравниваем: должны совпадать с final_states
            if post_states != final_states:
                return 0, {}, "ERROR: Не удалось установить требуемые реле"

            return actual_resistance, selected_relays, 'OK'

        except Exception as e:
            return 0, {}, f"ERROR: Исключение при установке сопротивления: {str(e)}"

    def get_current_resistance(self) -> Tuple[str, str]:
        """
        Получает текущее сопротивление магазина на основе состояния реле.

        Возвращает:
            tuple: (current_resistance, status)
                - current_resistance (str): текущее сопротивление в Омах или 'NA' если все реле разомкнуты
                - status (str): 'OK' или 'ERROR: <описание>'
        """
        try:
            self._connect_switch()
            current_states, status = self.controller.get_relays()
            self._disconnect_switch()

            if status != 'OK':
                return "0", f"ERROR: Не удалось получить состояние реле: {status}"

            # Проверяем, есть ли хотя бы одно включенное реле
            if not any(current_states):
                return "NA", 'OK'

            # Суммируем сопротивления включенных реле
            current_resistance = 0
            for nominal, config in self.map.items():
                relay_index = config[1] - 1  # преобразуем в 0-индексированный
                if 0 <= relay_index < len(current_states) and current_states[relay_index]:
                    current_resistance += nominal

            return str(current_resistance), 'OK'

        except Exception as e:
            return "0", f"ERROR: Исключение при получении текущего сопротивления: {str(e)}"

    def get_current_resistance_with_details(self) -> Tuple[str, Dict, str]:
        """
        Получает текущее сопротивление магазина с детализацией по включенным реле.

        Возвращает:
            tuple: (current_resistance, active_relays, status)
                - current_resistance (str): текущее сопротивление в Омах или 'NA' если все реле разомкнуты
                - active_relays (dict): словарь включенных реле {nominal: [addr, relay_num, r_type]}
                - status (str): 'OK' или 'ERROR: <описание>'
        """
        try:
            self._connect_switch()
            current_states, status = self.controller.get_relays()
            self._disconnect_switch()

            if status != 'OK':
                return "0", {}, f"ERROR: Не удалось получить состояние реле: {status}"

            current_resistance = 0
            active_relays = {}

            for nominal, config in self.map.items():
                relay_index = config[1] - 1  # преобразуем в 0-индексированный
                if 0 <= relay_index < len(current_states) and current_states[relay_index]:
                    current_resistance += nominal
                    active_relays[nominal] = config

            # Если нет активных реле, возвращаем 'NA'
            if not active_relays:
                return "NA", active_relays, 'OK'

            return str(current_resistance), active_relays, 'OK'

        except Exception as e:
            return "0", {}, f"ERROR: Исключение при получении текущего сопротивления: {str(e)}"

    def get_resistance_status(self) -> Dict:
        """
        Получает полную информацию о состоянии магазина сопротивлений.

        Возвращает:
            dict: словарь с информацией о состоянии
        """
        current_res, active_relays, status = self.get_current_resistance_with_details()
        min_r, max_r, step = self.get_min_max_resistance_and_step()

        return {
            'current_resistance': current_res,
            'active_relays': active_relays,
            'min_resistance': min_r,
            'max_resistance': max_r,
            'min_step': step,
            'status': status,
            'simulation_mode': self.simulation_mode,
            'all_relays_open': current_res == "NA"  # Дополнительное поле для удобства
        }

    def is_circuit_open(self) -> Tuple[bool, str]:
        """
        Проверяет, разомкнута ли цепь (все реле выключены).

        Возвращает:
            tuple: (is_open, status)
                - is_open (bool): True если все реле разомкнуты, False если есть включенные реле
                - status (str): 'OK' или 'ERROR: <описание>'
        """
        try:
            self._connect_switch()
            current_states, status = self.controller.get_relays()
            self._disconnect_switch()

            if status != 'OK':
                return False, f"ERROR: Не удалось получить состояние реле: {status}"

            # Если все реле выключены, цепь разомкнута
            is_open = not any(current_states)
            return is_open, 'OK'

        except Exception as e:
            return False, f"ERROR: Исключение при проверке состояния цепи: {str(e)}"
