import random
import time

# Настройки
update_interval = 0.5  # 500 мс (уменьшено для комфортного чтения)
last_update_time = time.time()


def update_data(dpg):
    global last_update_time
    if time.time() - last_update_time < update_interval:
        return

    # Генерация значений
    voltage = random.uniform(0, 50)
    current = random.uniform(0, 10)
    power = voltage * current

    # Обновление с форматированием
    dpg.set_value("voltage_val", f"{voltage:5.3f}")
    dpg.set_value("current_val", f"{current:5.3f}")
    dpg.set_value("power_val", f"{power:7.3f}")

    last_update_time = time.time()


def create_rt_measure_power_window(dpg):
    # Главное окно
    with dpg.window(tag="RT_Measurements_power", width=525, height=340, pos=(1350, 0),
                    label='Результаты измерения мощности'):
        # Верхний ряд (Voltage + Current)
        with dpg.group(horizontal=True, horizontal_spacing=10):
            # Панель напряжения
            with dpg.child_window(width=250, height=150, tag="voltage_panel"):
                dpg.add_text("Напряжение (В):", indent=20)
                dpg.add_text("0.000", tag="voltage_val", indent=20)

            # Панель тока
            with dpg.child_window(width=250, height=150, tag="current_panel"):
                dpg.add_text("Ток (мA):", indent=20)
                dpg.add_text("0.000", tag="current_val", indent=20)

        # Нижняя панель мощности
        with dpg.child_window(width=510, height=150, tag="power_panel"):
            dpg.add_text("Мощность (mW):", indent=20)
            dpg.add_text("0.000", tag="power_val", indent=20)

    # Темы с подсветкой и стилями
    with dpg.theme(tag="voltage_theme"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (255, 255, 0, 80))  # Yellow background
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 12)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 20, 20)
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, (200, 200, 0))

    with dpg.theme(tag="current_theme"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (0, 191, 255, 80))  # Blue background
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 12)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 20, 20)
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, (0, 120, 200))

    with dpg.theme(tag="power_theme"):
        with dpg.theme_component(dpg.mvChildWindow):
            dpg.add_theme_color(dpg.mvThemeCol_ChildBg, (255, 165, 0, 80))  # Orange background
            dpg.add_theme_style(dpg.mvStyleVar_ChildRounding, 12)
            dpg.add_theme_style(dpg.mvStyleVar_WindowPadding, 20, 20)
        with dpg.theme_component(dpg.mvText):
            dpg.add_theme_color(dpg.mvThemeCol_Text, (200, 100, 0))

    # Применяем темы к панелям
    dpg.bind_item_theme("voltage_panel", "voltage_theme")
    dpg.bind_item_theme("current_panel", "current_theme")
    dpg.bind_item_theme("power_panel", "power_theme")

    # Привязываем шрифты к тексту
    dpg.bind_item_font("voltage_val", 'large_font')
    dpg.bind_item_font("current_val", 'large_font')
    dpg.bind_item_font("power_val", 'large_font')
