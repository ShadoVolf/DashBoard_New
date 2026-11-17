"""
Слой доступа к БД через SQLAlchemy.
Использует существующий Options.get_connection_string() из основного проекта.
"""
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

# ВАЖНО: используем уже существующий в проекте источник строки подключения
from Options import get_connection_string


_engine = None
_Session = None


def get_engine():
    """Ленивая инициализация движка на основе Options.get_connection_string()."""
    global _engine
    if _engine is None:
        _engine = create_engine(
            str(get_connection_string()),
            pool_pre_ping=True,
            future=True,
        )
    return _engine


def get_session():
    global _Session
    if _Session is None:
        _Session = sessionmaker(bind=get_engine(), future=True)
    return _Session()


def fetchall(sql: str, **params):
    """Вернуть список строк (Mapping) по SQL с именованными параметрами."""
    with get_engine().connect() as conn:
        return list(conn.execute(text(sql), params).mappings())


def fetchone(sql: str, **params):
    with get_engine().connect() as conn:
        return conn.execute(text(sql), params).mappings().first()


def execute(sql: str, **params):
    with get_engine().begin() as conn:
        conn.execute(text(sql), params)


def execute_raw(sql: str, params: dict | None = None) -> None:
    """Выполнить SQL, минуя SQLAlchemy.text().

    В отличие от execute(), здесь SQL передаётся в DBAPI как есть —
    символ '%' в идентификаторах (например, `DopuskT_%`) не экранируется
    в '%%' и не ломает UPDATE.
    """
    with get_engine().begin() as conn:
        conn.exec_driver_sql(sql, params or {})