import os
import pandas as pd
from sqlalchemy import create_engine, update, MetaData, Table
from sqlalchemy.orm import sessionmaker
import dearpygui.dearpygui as dpg

import Options


def add_spur_files(dpg, measure_id, folder_path, progress_bar_tag=None, log_widget_tag=None, file_type="По позиции"):
    """
    Добавляет spur файлы в базу данных с отображением прогресса в процентах и логом процесса

    Args:
        measure_id (int): ID измерения
        folder_path (str): путь к папке с файлами
        progress_bar_tag (str): тег прогресс-бара в DearPyGUI (опционально)
        log_widget_tag (str): тег виджета для лога в DearPyGUI (опционально)
        file_type (str): тип сопоставления файлов - "По позиции" или "По номеру"
    """
    if log_widget_tag is not None:
        dpg.set_value(log_widget_tag, "")

    def log_message(message):
        """Вспомогательная функция для логирования сообщений"""
        timestamp = pd.Timestamp.now().strftime("%H:%M:%S")
        formatted_message = f"[{timestamp}] {message}"

        if log_widget_tag and dpg.does_item_exist(log_widget_tag):
            # Получаем текущий текст и добавляем новое сообщение
            current_text = dpg.get_value(log_widget_tag)
            new_text = f"{current_text}\n{formatted_message}" if current_text else formatted_message
            dpg.set_value(log_widget_tag, new_text)
            # Прокручиваем к концу
            dpg.set_item_height(log_widget_tag, -1)  # Автоматическая высота
        else:
            # Выводим в консоль если виджет не указан
            print(formatted_message)

    # Подключение к базе данных
    engine_string = Options.get_connection_string()
    engine = create_engine(engine_string)
    metadata = MetaData()

    # Отражение таблицы
    spur_table = Table('psidata_spur', metadata, autoload_with=engine)

    # Создание сессии
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        log_message(f"Начало обработки Measure_ID: {measure_id}")
        log_message(f"Путь к файлам: {folder_path}")
        log_message(f"Тип сопоставления файлов: {file_type}")

        # Получение всех позиций для указанного Measure_ID
        query = session.query(spur_table).filter(spur_table.c.Measure_ID == measure_id)
        df = pd.read_sql(query.statement, session.bind)

        total_files = len(df)
        processed_files = 0

        log_message(f"Найдено записей в базе данных: {total_files}")

        # Инициализация прогресс-бара
        if progress_bar_tag and dpg.does_item_exist(progress_bar_tag):
            dpg.set_value(progress_bar_tag, 0)
            dpg.configure_item(progress_bar_tag, overlay="0%")

        for index, row in df.iterrows():
            position = row['Position']

            # Определяем имя файла в зависимости от типа сопоставления
            if file_type == "По номеру":
                # Используем значение из колонки N (серийный номер)
                file_name = str(row['N']) if 'N' in row and pd.notna(row['N']) else None
                if not file_name:
                    log_message(f"ПРЕДУПРЕЖДЕНИЕ: Для позиции {position} не указан серийный номер (колонка N)")
                    continue
                log_message(f"Обработка позиции: {position}, серийный номер: {file_name}")
            else:
                # Используем значение позиции (текущая реализация)
                file_name = position
                log_message(f"Обработка позиции: {position}")

            base_file_path = os.path.join(folder_path, file_name)

            # Обработка DAT файла
            dat_path = base_file_path + '.dat'
            if os.path.exists(dat_path):
                with open(dat_path, 'rb') as f:
                    dat_data = f.read()
                log_message(f"  Файл {dat_path} успешно прочитан")
            else:
                dat_data = None
                log_message(f"  ВНИМАНИЕ: Файл {dat_path} не найден")

            # Обновление записи
            update_stmt = update(spur_table).where(
                (spur_table.c.Measure_ID == measure_id) &
                (spur_table.c.Position == position)
            ).values(
                Spur_Plot=None,  # JPG данные не обрабатываются в текущей реализации
                Spur_Plot_Data=dat_data
            )
            session.execute(update_stmt)
            log_message(f"  Запись для позиции {position} обновлена в базе данных")

            # Обновление прогресса в процентах
            processed_files += 1
            if progress_bar_tag and dpg.does_item_exist(progress_bar_tag):
                progress = processed_files / total_files
                percentage = int(progress * 100)
                dpg.set_value(progress_bar_tag, progress)
                dpg.configure_item(progress_bar_tag, overlay=f"{percentage}%")

        session.commit()
        result_message = f"Данные для Measure_ID {measure_id} успешно обновлены. Обработано файлов: {processed_files}/{total_files}"
        log_message(result_message)

        # Финальное обновление прогресс-бара
        if progress_bar_tag and dpg.does_item_exist(progress_bar_tag):
            dpg.set_value(progress_bar_tag, 1.0)
            dpg.configure_item(progress_bar_tag, overlay="100%")

        return True, result_message

    except Exception as e:
        session.rollback()
        error_message = f"Ошибка: {str(e)}"
        log_message(f"ОШИБКА: {error_message}")

        # Сброс прогресс-бара при ошибке
        if progress_bar_tag and dpg.does_item_exist(progress_bar_tag):
            dpg.set_value(progress_bar_tag, 0)
            dpg.configure_item(progress_bar_tag, overlay="Ошибка!")

        return False, error_message

    finally:
        session.close()
        log_message("Обработка завершена")
        dpg.configure_item('export_spur_start_button', enabled=True)


# Пример использования с DearPyGUI
if __name__ == "__main__":
    # Создание простого интерфейса для демонстрации
    dpg.create_context()
    dpg.create_viewport(title='Spur Files Processor', width=800, height=600)

    with dpg.window(label="Main Window", width=800, height=600):
        dpg.add_text("Обработка Spur файлов")

        # Прогресс-бар
        progress_bar = dpg.add_progress_bar(label="Прогресс", default_value=0, width=400)

        # Выбор типа сопоставления файлов
        dpg.add_text("Тип сопоставления файлов:")
        file_type_combo = dpg.add_combo(
            items=["По позиции", "По номеру"],
            default_value="По позиции",
            width=150,
            tag="file_type_combo"
        )

        # Виджет для лога
        dpg.add_text("Лог выполнения:")
        log_widget = dpg.add_input_text(
            multiline=True,
            readonly=True,
            width=780,
            height=400,
            tag="log_widget"
        )

        # Кнопка запуска
        dpg.add_button(
            label="Запуск обработки",
            callback=lambda: add_spur_files(
                measure_id=245751,
                folder_path="E://051125-1",
                progress_bar_tag=progress_bar,
                log_widget_tag=log_widget,
                file_type=dpg.get_value(file_type_combo)
            )
        )

        # Кнопка очистки лога
        dpg.add_button(
            label="Очистить лог",
            callback=lambda: dpg.set_value(log_widget, "")
        )

    dpg.setup_dearpygui()
    dpg.show_viewport()
    dpg.start_dearpygui()
    dpg.destroy_context()
