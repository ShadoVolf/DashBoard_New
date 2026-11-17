"""Окно справочника номеров резонаторов."""
import dearpygui.dearpygui as dpg

LOOKUP_WINDOW = 'archive_lookup_window'


def open_lookup_window():
    if dpg.does_item_exist(LOOKUP_WINDOW):
        dpg.configure_item(LOOKUP_WINDOW, show=True)
        try:
            dpg.focus_item(LOOKUP_WINDOW)
        except Exception:
            pass
        return

    # импорт внутри функции — избегаем циклической зависимости
    from .Archive_UI import _on_lookup_check, _on_lookup_sync

    with dpg.window(label='Справочник номеров резонаторов',
                    tag=LOOKUP_WINDOW, width=600, height=300,
                    pos=(200, 150)):
        dpg.add_text(
            'Ускоряет поиск Measure_ID по номерам. Справочник индексирует '
            'только основную таблицу psidata (временная и архивная '
            'ищутся напрямую).',
            color=(150, 200, 255), wrap=570)
        dpg.add_separator()
        dpg.add_text("Статус:", color=(180, 220, 255))
        dpg.add_text('***', tag='archive_lookup_status',
                     color=(150, 200, 255), wrap=570)
        dpg.add_separator()
        dpg.add_button(label='Проверить', width=-1, height=30,
                       callback=lambda s, a: _on_lookup_check())
        dpg.add_button(label='Досинхронизировать', width=-1, height=30,
                       callback=lambda s, a: _on_lookup_sync(False))
        dpg.add_button(label='Полная пересборка', width=-1, height=30,
                       callback=lambda s, a: _on_lookup_sync(True))