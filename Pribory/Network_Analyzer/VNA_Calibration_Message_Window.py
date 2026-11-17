
def show_calibration_dialog(current_channel, ch_count, callback, dpg):
    # Удаляем предыдущее окно, если оно существует
    if dpg.does_alias_exist("calibration_dialog"):
        dpg.delete_item("calibration_dialog")
    # Создаем модальное окно
    with dpg.window(
            label="Калибровка канала",
            modal=False,
            tag="calibration_dialog",
            width=330,
            height=120,
            no_resize=True,
            pos=[dpg.get_viewport_width() // 2 - 200, dpg.get_viewport_height() // 2 - 100]
    ):
        dpg.add_text(f"Канал {current_channel + 1} из {ch_count}")
        dpg.add_separator()
        dpg.add_text("Выберите действие:")

        with dpg.group(horizontal=True):
            dpg.add_button(
                label="Калибровать",
                width=100,
                height=30,
                callback=lambda: _handle_choice("continue", callback, dpg)
            )
            dpg.add_button(
                label="Пропустить",
                width=100,
                height=30,
                callback=lambda: _handle_choice("skip", callback, dpg)
            )
            dpg.add_button(
                label="Отменить",
                width=100,
                height=30,
                callback=lambda: _handle_choice("cancel", callback, dpg)
            )




def _handle_choice(choice, callback, dpg):

    dpg.delete_item("calibration_dialog")  # Закрываем окно
    callback(choice, dpg)  # Вызываем callback с выбором пользователя