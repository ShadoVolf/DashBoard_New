import time


class Timer_Controller:
    def __init__(self, dpg, button_id: int, display_id: int):
        self.dpg = dpg
        self.button_id = button_id
        self.display_id = display_id
        self.is_running = False
        self.start_time = 0.0
        self.elapsed_time = 0.0

        # Настройка обработчиков
        with dpg.item_handler_registry() as handler:
            dpg.add_item_clicked_handler(callback=self._toggle_handler)
        dpg.bind_item_handler_registry(self.button_id, handler)

        # Инициализация отображения
        self.reset()
        self._update_display()

    def reset(self):
        """Полный сброс таймера"""
        self.is_running = False
        self.start_time = 0.0
        self.elapsed_time = 0.0
        self.dpg.configure_item(self.button_id, label="СТАРТ")
        self._update_display()

    def _toggle_handler(self, sender):
        """Обработчик клика по кнопке"""
        self.toggle()

    def _update_display(self):
        """Обновление текстового поля с текущим временем"""
        total = self.elapsed_time + (time.time() - self.start_time if self.is_running else 0)
        self.dpg.set_value(self.display_id, f"{int(total // 60):02}:{int(total % 60):02}")

    def toggle(self):
        """Переключение состояния таймера"""
        self.is_running = not self.is_running
        if self.is_running:
            self.start_time = time.time()
            self.dpg.configure_item(self.button_id, label="СТОП")
            self.dpg.bind_item_theme('Start_button', 'Use_button_theme_rt_regime')
        else:
            # self.elapsed_time += time.time() - self.start_time
            self.elapsed_time = 0.0
            self.dpg.configure_item(self.button_id, label="СТАРТ")
            self.dpg.bind_item_theme('Start_button', 'Use_button_theme_green_regime_1')

        # Запускаем периодическое обновление
        self._schedule_update()

    def _schedule_update(self):
        """Планирование следующего обновления интерфейса"""
        if self.is_running:
            self.dpg.set_frame_callback(self.dpg.get_frame_count() + 1, self._update_cycle)

    def _update_cycle(self):
        """Цикл обновления интерфейса"""
        self._update_display()
        self._schedule_update()