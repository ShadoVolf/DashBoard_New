from sqlalchemy import create_engine, text
import pandas as pd

from Options import get_connection_string

_engine = None

def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_connection_string())
    return _engine

def execute_query(query: str) -> pd.DataFrame:
    with get_engine().connect() as conn:
        return pd.read_sql_query(query, conn)

def execute_update(update_sql: str, params: dict):
    with get_engine().connect() as conn:
        conn.execute(text(update_sql), params)
        conn.commit()

def execute_many_updates(update_sql: str, list_of_params: list):
    with get_engine().connect() as conn:
        conn.execute(text(update_sql), list_of_params)
        conn.commit()

def insert_and_get_id(insert_sql: str, params: dict) -> int:
    """Вставляет запись и возвращает сгенерированный AUTO_INCREMENT ID."""
    with get_engine().connect() as conn:
        result = conn.execute(text(insert_sql), params)
        conn.commit()
        # Получаем последний вставленный ID (для MySQL)
        return result.lastrowid