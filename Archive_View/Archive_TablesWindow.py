"""Окно управления таблицами: перезапись, архивирование, журнал операций."""
import dearpygui.dearpygui as dpg

TABLES_WINDOW = 'archive_tables_window'


def open_tables_window():
    if dpg.does_item_exist(TABLES_WINDOW):
        dpg.configure_item(TABLES_WINDOW, show=True)
        try:
            dpg.focus_item(TABLES_WINDOW)
        except Exception:
            pass
        return

    from .Archive_Transfer_UI import (
        open_overwrite_dialog, open_archive_dialog, open_actions_log_window,
    )

    with dpg.window(label='Управление таблицами', tag=TABLES_WINDOW,
                    width=560, height=380, pos=(200, 150)):
        dpg.add_text(
            'Перезапись (временная → основная), архивирование '
            '(основная → архивная) и журнал операций с откатом.',
            color=(150, 200, 255), wrap=530)
        dpg.add_separator()
        dpg.add_button(label='Перезапись: временная -> основная',
                       width=-1, height=32,
                       callback=lambda s, a: open_overwrite_dialog())
        dpg.add_button(label='Архивировать: основная -> архивная',
                       width=-1, height=32,
                       callback=lambda s, a: open_archive_dialog())
        dpg.add_separator()
        dpg.add_button(label='Журнал операций / откат',
                       width=-1, height=32,
                       callback=lambda s, a: open_actions_log_window())
        dpg.add_separator()
        dpg.add_button(label='Очистить временную таблицу...',
                       width=-1, height=32,
                       callback=lambda s, a: _on_clear_temp())
        dpg.add_separator()
        dpg.add_text("Синхронизация структуры таблиц",
                     color=(180, 220, 255))
        dpg.add_text('', tag='tables_sync_status',
                     color=(150, 200, 255), wrap=530)
        dpg.add_button(label='Проверить структуру', width=-1, height=28,
                       callback=lambda s, a: _on_check_structure())
        dpg.add_button(label='Синхронизировать структуру', width=-1, height=28,
                       callback=lambda s, a: _on_sync_structure())


def _on_check_structure():
    from .Archive_TableSync import check_structure
    try:
        miss = check_structure()
        if not miss:
            dpg.set_value('tables_sync_status',
                          'Структура везде совпадает')
            return
        lines = [f"{tgt}: нет {len(info['missing'])} колонок"
                 for tgt, info in miss.items()]
        dpg.set_value('tables_sync_status', ' | '.join(lines))
    except Exception as e:
        dpg.set_value('tables_sync_status', f'Ошибка: {e}')


def _on_sync_structure():
    from .Archive_TableSync import sync_table_structure
    try:
        report = sync_table_structure()
        changes = [r for r in report if 'OK' not in r]
        if not changes:
            dpg.set_value('tables_sync_status', 'Всё уже синхронизировано')
        else:
            head = ' | '.join(changes[:5])
            tail = f" (+{len(changes) - 5})" if len(changes) > 5 else ''
            dpg.set_value('tables_sync_status', head + tail)
    except Exception as e:
        dpg.set_value('tables_sync_status', f'Ошибка: {e}')

def _on_clear_temp():
    from .Archive_Transfer import clear_temp_tables
    tag = 'archive_confirm_clear_temp'
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.window(label='Очистка временной таблицы', tag=tag,
                    modal=True, width=560, height=230, no_collapse=True):
        dpg.add_text(
            'Полностью очистить psidata_temporary и '
            'psidatatemp_temporary?\n\n'
            'Данные будут удалены безвозвратно, операция пишется в журнал.',
            wrap=530)
        dpg.add_separator()

        def _ok():
            dpg.delete_item(tag)
            res = clear_temp_tables()
            if not res['ok']:
                dpg.set_value('tables_sync_status',
                              f"Ошибка очистки: {res.get('error', '?')}")
                return
            dpg.set_value(
                'tables_sync_status',
                f"Очищено: main {res['deleted_main']} (было "
                f"{res['was_main']}), temp {res['deleted_temp']} (было "
                f"{res['was_temp']}). Журнал id={res['log_id']}")

        with dpg.group(horizontal=True):
            dpg.add_button(label='Очистить', width=130, callback=_ok)
            dpg.add_button(label='Отмена', width=130,
                           callback=lambda s, a: dpg.delete_item(tag))