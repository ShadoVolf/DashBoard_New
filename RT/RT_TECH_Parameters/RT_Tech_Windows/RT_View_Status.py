import dearpygui.dearpygui as dpg
from PIL import Image
import numpy as np

import Options
from RT.RT_TECH_Parameters.RT_Data import RT_DATA
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_Control_Manual import get_res_state_color
from RT.RT_TECH_Parameters.RT_Tech_Windows.RT_R_Magazine_Window import create_rt_r_magazine_window


class LampController:
    def __init__(self, dpg_context):
        self.dpg = dpg_context
        self.texture_tag = "lamp_texture_uid"
        self.window_tag = "lamp_window_uid"
        self.texture_loaded = False
        path_ = Options.get_pict_path()
        # Инициализация текстур при создании объекта
        self._init_texture(path_ + "\\RT_Resonator_View.png")

    def _init_texture(self, image_path):
        try:
            image = Image.open(image_path).convert("RGBA")
            width, height = image.size
            image_data = np.array(image.getdata(), dtype=np.float32).flatten() / 255.0

            with self.dpg.texture_registry(show=False):
                self.dpg.add_raw_texture(
                    width=width,
                    height=height,
                    default_value=image_data,
                    format=self.dpg.mvFormat_Float_rgba,
                    tag=self.texture_tag
                )
            self.texture_loaded = True
        except Exception as e:
            print(f"Texture initialization error: {e}")

    def _create_lamp_element(self, parent, lamp_id):
        with self.dpg.group(parent=parent, horizontal=False):
            # Контейнер для графики
            with self.dpg.drawlist(width=150, height=150):
                bg = self.dpg.draw_rectangle(
                    (0, 0), (150, 150),
                    color=[0, 0, 0, 128],
                    fill=[0, 0, 0, 128],
                    tag=f"bg_{lamp_id}"
                )

                if self.texture_loaded:
                    self.dpg.draw_image(
                        self.texture_tag,
                        (10, 10), (140, 140),
                        uv_min=(0, 0),
                        uv_max=(1, 1)
                    )

            # Элементы управления
            slider = self.dpg.add_slider_int(
                min_value=0,
                max_value=10,
                default_value=0,
                width=150,
                callback=self._update_lamp,
                tag=f"slider_{lamp_id}",
                user_data=bg
            )

            self.dpg.add_text("Уровень разогрева", tag=f"text_{lamp_id}")
            self.dpg.add_text("Номер  ----", tag=f"number_{lamp_id}")
            with dpg.popup(f"number_{lamp_id}", min_size=[120, 30]):
                dpg.add_selectable(label='Электронный магазин',
                                   user_data=dpg, callback=self._show_r_window,
                                   tag=f'r_magazine_menu_pop_{lamp_id}')

    def _update_lamp(self, sender, app_data):
        bg_item = self.dpg.get_item_user_data(sender)
        value = self.dpg.get_value(sender)

        # Расчет цвета
        if value == 0:
            color = [0, 0, 0, 128]
        else:
            ratio = (value - 1) / 9.0
            color = [
                int((1 - ratio) * 255),
                int(ratio * 255),
                0,
                128
            ]

        # Обновление цвета
        self.dpg.configure_item(bg_item, color=color, fill=color)
        self.dpg.set_value(f"text_{self.dpg.get_item_alias(sender).split('_')[-1]}", f"Уровень разогрева: {value}")

    def create_window(self):
        # Удаление предыдущего окна если существует
        if self.dpg.does_item_exist(self.window_tag):
            self.dpg.delete_item(self.window_tag)

        # Создание нового окна
        with self.dpg.window(
                tag=self.window_tag,
                label="Установленные резонаторы",
                width=900,
                height=300,
                autosize=True,
                pos=(450, 0)
        ):
            main_group = self.dpg.add_group(horizontal=True, horizontal_spacing=20)
            for i in range(5):
                self._create_lamp_element(main_group, i)

    @staticmethod
    def _show_r_window(sender, data, dpg):
        parts = sender.split('_')
        slot = int(parts[-1]) + 1
        chanel = dpg.get_value(f'Channel_select_{slot}')
        create_rt_r_magazine_window(dpg, chanel)
        # Options.center_window(dpg, 'RT_r_magazine_Window')


# Функция установки индикатора канала (channel) в соответсвующее состояние (0...10)
def set_lamp_state(channel, state_value: int, dpg):
    RT_DATA.current_state[channel] = state_value
    color = get_res_state_color(state_value)
    dpg.configure_item(f'bg_{int(channel) - 1}', color=color, fill=color)
    dpg.configure_item(f'slider_{int(channel) - 1}', default_value=state_value)
