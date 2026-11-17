def create_control_panel_rt_window(dpg):
    with dpg.window(label="Результаты измерения", width=870, height=610, pos=(450, 275), tag='result_RT_Panel'):
        with dpg.group(horizontal=True, horizontal_spacing=70, width=150):
            dpg.add_button(label="Сохранить", tag='rt_save_result_button',height=25, width=100)
            dpg.add_button(label="Печать", tag='rt_print_result_button', height=25, width=100)
            dpg.add_button(label="Очистить", tag='rt_clear_result_button', height=25, width=100)
            dpg.add_button(label="Экспорт(Excel)", tag='rt_export_result_button', height=25, width=100)
        dpg.add_separator()
        dpg.add_separator()
        with dpg.table(header_row=True, borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True,
                       scrollY=True, height=300, tag='result_RT_table'):
            dpg.add_table_column(label="NN", width_fixed=True, init_width_or_weight=20)
            dpg.add_table_column(label="Номер", width_fixed=True, init_width_or_weight=90)
            dpg.add_table_column(label="F, ppm", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="R1, Ом", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="С1, пФ", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="L1, мГн", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="C0, пФ", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="Q, x1000", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="U, В", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="I, мА", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="P, мВ", width_fixed=True, init_width_or_weight=60)
            dpg.add_table_column(label="Статус", width_fixed=True, init_width_or_weight=60)



