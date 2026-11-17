"""Темы оформления: прогресс-бар и кнопки.

Все удаления выполняются только для существующих тегов, чтобы
повторное открытие окон не падало с ошибкой Item not found.
"""


def load_themes(dpg):
    # Обнуляем все теги, которые могут быть созданы этим модулем,
    # но только если они реально существуют в текущем контексте DPG.
    for tag in (
        'progress_bar_theme', 'progress_bar_theme_comp',
        'Use_button_theme_rt',   'Use_button_theme_rt_comp',
        'Use_button_theme_rt_1', 'Use_button_theme_rt_1_comp',
        'Use_button_theme_rt_2', 'Use_button_theme_rt_2_comp',
        'Use_button_theme_rt_3', 'Use_button_theme_rt_3_comp',
    ):
        if dpg.does_item_exist(tag):
            try:
                dpg.delete_item(tag)
            except Exception as e:
                print(f"[load_themes] cannot delete '{tag}': {e}")

    # ---------------- Прогресс-бар ----------------
    with dpg.theme(tag='progress_bar_theme'):
        with dpg.theme_component(dpg.mvProgressBar,
                                 tag='progress_bar_theme_comp'):
            dpg.add_theme_color(dpg.mvThemeCol_PlotHistogram,
                                (56, 189, 113))
            dpg.add_theme_style(dpg.mvPlotStyleVar_PlotPadding, 0, 0)

    # ---------------- Кнопки: красная ----------------
    with dpg.theme(tag='Use_button_theme_rt'):
        with dpg.theme_component(dpg.mvButton,
                                 tag='Use_button_theme_rt_comp'):
            dpg.add_theme_color(dpg.mvThemeCol_Button,
                                (255, 0, 0, 100))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,
                                (255, 0, 0, 120))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,
                                (255, 0, 0, 150))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 20)

    # ---------------- Кнопки: голубая ----------------
    with dpg.theme(tag='Use_button_theme_rt_1'):
        with dpg.theme_component(dpg.mvButton,
                                 tag='Use_button_theme_rt_1_comp'):
            dpg.add_theme_color(dpg.mvThemeCol_Button,
                                (135, 206, 250, 80))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,
                                (135, 206, 250, 120))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,
                                (135, 206, 250, 150))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 20)

    # ---------------- Кнопки: фиолетовая ----------------
    with dpg.theme(tag='Use_button_theme_rt_2'):
        with dpg.theme_component(dpg.mvButton,
                                 tag='Use_button_theme_rt_2_comp'):
            dpg.add_theme_color(dpg.mvThemeCol_Button,
                                (204, 153, 255, 80))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,
                                (204, 153, 255, 120))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,
                                (204, 153, 255, 150))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 20)

    # ---------------- Кнопки: бирюзовая ----------------
    with dpg.theme(tag='Use_button_theme_rt_3'):
        with dpg.theme_component(dpg.mvButton,
                                 tag='Use_button_theme_rt_3_comp'):
            dpg.add_theme_color(dpg.mvThemeCol_Button,
                                (127, 255, 212, 80))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonHovered,
                                (127, 255, 212, 120))
            dpg.add_theme_color(dpg.mvThemeCol_ButtonActive,
                                (127, 255, 212, 150))
            dpg.add_theme_style(dpg.mvStyleVar_FrameRounding, 20)