from Temperature_Measure import _layout
from Temperature_Measure.Report_Export.spur_export import export_spur_data
from Temperature_Measure.Spur_Operations import add_spur_files


def create_add_spur_window(dpg):
    for tag in ('spur_add_measure_window', 'spur_dir_selector'):
        if dpg.does_item_exist(tag):
            dpg.delete_item(tag)

    pos, size = _layout.dialog_rect(fraction_w=0.5, fraction_h=0.55,
                                    min_w=600, min_h=450,
                                    max_w=900, max_h=800)

    with dpg.window(label="Добавления АЧХ резонатора",
                    width=size[0], height=size[1], pos=pos,
                    tag='spur_add_measure_window'):
        dpg.add_radio_button(
            items=["По номеру", "По позиции"], horizontal=True,
            tag="measure_spur_add_select_type")
        dpg.add_separator()
        dpg.add_separator()
        dpg.add_input_text(label='Номер протокола измерения',
                           tag='spur_add_measure_id_sel')

        with dpg.file_dialog(
                directory_selector=True, show=False,
                callback=lambda s, a: dpg.set_value('spur_selected_dir',
                                                     a['file_path_name']),
                tag="spur_dir_selector", width=500, height=400):
            pass

        dpg.add_text("Выбранная директория:", tag="spur_dir_label")
        dpg.add_input_text(tag='spur_selected_dir', readonly=True, width=-1)
        dpg.add_separator()
        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Выбрать директорию",
                           callback=lambda: dpg.show_item("spur_dir_selector"),
                           tag='add_spur_select_dir_button')
            dpg.add_spacer(height=30)
            dpg.add_button(label="Записать",
                           callback=lambda: add_spur_files(
                               dpg,
                               measure_id=int(dpg.get_value('spur_add_measure_id_sel')),
                               folder_path=dpg.get_value('spur_selected_dir'),
                               progress_bar_tag="add_spur_progress",
                               log_widget_tag='add_spur_log_process_window',
                               file_type=dpg.get_value('measure_spur_add_select_type')),
                           tag='add_spur_begin_write_button')
            dpg.add_button(label='Экспорт',
                           callback=lambda: export_spur_data(
                               dpg,
                               measure_id=int(dpg.get_value('spur_add_measure_id_sel'))),
                           tag='export_spur_start_button', enabled=False)

        dpg.add_separator()
        dpg.add_separator()
        dpg.add_progress_bar(tag="add_spur_progress", default_value=0.0,
                             width=-1)
        dpg.add_text('Лог:')
        dpg.add_input_text(tag='add_spur_log_process_window',
                           multiline=True, readonly=True,
                           width=-1, height=-1,
                           tracked=True, track_offset=1.0)

        dpg.bind_item_theme("add_spur_progress", 'progress_bar_theme')
        dpg.bind_item_theme("add_spur_select_dir_button",
                            'Use_button_theme_rt_1')
        dpg.bind_item_theme("add_spur_begin_write_button",
                            'Use_button_theme_rt_3')
        dpg.bind_item_theme("export_spur_start_button",
                            'Use_button_theme_rt_3')