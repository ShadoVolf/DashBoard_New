import numpy as np
from sqlalchemy import create_engine, func
from sqlalchemy.orm import sessionmaker
from sqlalchemy import update, MetaData, Table
import pandas as pd

from Options import get_connection_string


# Функция получает идентификатор из БД
def insert_msk_value(msk_value, filename, file_id, login, protokol_type):
    """Вставляет значение MSK и возвращает MeasureID с использованием pandas"""
    engine = create_engine(str(get_connection_string()))
    metadata = MetaData()

    # Автоматически определяем структуру таблицы
    my_table = Table('psi_measure_id', metadata, autoload_with=engine)

    # Создаем сессию
    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Вставка записи
        insert_stmt = my_table.insert().values(MSK=msk_value, File=filename,
                                               Program_Type='Measure ver 1.0.2', File_ID=file_id,
                                               Operator=login,
                                               ProtokolN=protokol_type)
        result = session.execute(insert_stmt)
        session.commit()

        # Получение сгенерированного ID
        measure_id = session.execute(func.last_insert_id()).scalar()
        return measure_id

    except Exception as e:
        session.rollback()
        return f"Ошибка: {str(e)}"

    finally:
        session.close()
        engine.dispose()


# Сохранение данных в таблицу psidata(psidata_temporary)
def save_psidata(
        data: pd.DataFrame,
        static_data: dict,
        measure_id: int,
        table_name: str,
        temp: bool = False  # Новый параметр
) -> None:
    """
    Сохраняет данные в указанную таблицу с использованием соответствующей map-таблицы.

    Args:
        data: Исходные данные для сохранения
        static_data: Статические данные для обновления
        measure_id: ID измерения для связи данных
        table_name: Базовое название таблицы
        temp: Если True, данные сохраняются в таблицу с суффиксом '_temporary'
    """
    db_engine = create_engine(str(get_connection_string()))
    # Определение имен таблиц
    target_table_name = f"{table_name}_temporary" if temp else table_name
    map_table_name = f"{table_name}_map_table"  # map-таблица всегда без суффикса

    # Загрузка таблицы соответствия
    map_df = pd.read_sql_table(map_table_name, db_engine)

    # Фильтрация доступных параметров
    available_params = map_df['Parameter'].isin(data.columns)
    filtered_map = map_df[available_params]

    # Подготовка словарей преобразований
    rename_dict = filtered_map.set_index('Parameter')['Field'].to_dict()
    round_dict = (
        filtered_map.set_index('Parameter')['Round']
        .dropna()
        .astype(int)
        .to_dict()
    )

    # Применение округления
    data_rounded = data.copy()
    if round_dict:
        round_columns = list(round_dict.keys())  # Явное преобразование в список
        data_rounded[round_columns] = data[round_columns].round(round_dict)

    # Переименование колонок
    data_renamed = data_rounded.rename(columns=rename_dict)
    # Формирование финального набора колонок
    valid_columns = filtered_map['Field'].tolist()
    # Находим дублирующиеся названия столбцов
    duplicate_columns = data_renamed.columns[data_renamed.columns.duplicated()].tolist()

    # Удаляем дубликаты, оставляя первое вхождение
    df_unique = data_renamed.loc[:, ~data_renamed.columns.duplicated(keep='first')]

    # Выводим результат
    print("Удаленные дублирующиеся колонки:", duplicate_columns)
    data_final = df_unique.reindex(columns=valid_columns)
    data_final = data_final.astype(str).replace(r'\b1E\+30\b', 0, regex=True)
    # Сохранение основных данных
    if not data_final.empty:
        data_final.to_sql(
            target_table_name,  # Используем целевое имя
            db_engine,
            if_exists='append',
            index=False
        )

    # Обновление статических данных
    stat_data = convert_numpy_values(static_data)
    metadata = MetaData()
    # Загружаем целевую таблицу (с учетом суффикса)
    target_table = Table(target_table_name, metadata, autoload_with=db_engine)

    stmt = (
        update(target_table)
        .where(target_table.c.Measure_ID == measure_id)
        .values(**stat_data)
    )

    with db_engine.begin() as conn:
        conn.execute(stmt)
    if not temp:
        print(f'Данные таблицы {table_name} добавлены в основную БД Протокол №', measure_id)
    else:
        print(f'Данные таблицы {table_name} добавлены во временную БД Протокол №', measure_id)


def convert_numpy_values(data_dict: dict) -> dict:
    """Конвертирует numpy-типы в нативные Python-типы"""
    for key in data_dict:
        value = data_dict[key]
        if isinstance(value, (np.integer, np.floating)):
            data_dict[key] = value.item()
        elif isinstance(value, np.ndarray):
            data_dict[key] = value.tolist()
    return data_dict
