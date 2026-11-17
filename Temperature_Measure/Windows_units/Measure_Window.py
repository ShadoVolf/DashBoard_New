from Temperature_Measure import _layout


def create_measure_window(dpg):
    pos, size = _layout.compute_main_layout()["measure_window"]
    with dpg.window(label="Обработка измерений",
                    width=size[0], height=size[1], pos=pos,
                    tag='measure_window'):
        with dpg.group(horizontal=True, tag='file_inf_gr'):
            dpg.add_input_text(label='Установка:', width=100, decimal=True,
                               tag='machine_name')
            dpg.add_input_text(label='Тип', width=200, decimal=True,
                               tag='machine_type')
            dpg.add_input_text(label='Файл', width=200, decimal=True,
                               tag='file_name')
            dpg.add_input_text(label='Остаток поверки, дней', width=200,
                               decimal=True, tag='poverka_actual_dif')
        dpg.add_separator()
        dpg.add_separator()
        with dpg.table(header_row=True, row_background=True,
                       borders_innerH=True, borders_outerH=True,
                       borders_innerV=True, borders_outerV=True,
                       user_data=dpg, tag='measure_table', label='Данные'):
            dpg.add_table_column(label='N')
            dpg.add_table_column(label='Обработка')
            dpg.add_table_column(label='Номинал, Гц')
            dpg.add_table_column(label='Количество, шт.')
            dpg.add_table_column(label='Температуры')
            dpg.add_table_column(label='Нагрузка')
            dpg.add_table_column(label='CL')
            dpg.add_table_column(label='Спецификация')
            dpg.add_table_column(label='Номера')