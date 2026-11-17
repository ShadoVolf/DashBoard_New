import datetime

from sqlalchemy import (create_engine, Column, Integer, Float,
                        String, DateTime, ForeignKey, UniqueConstraint,
                        inspect, text)
from sqlalchemy.orm import declarative_base, sessionmaker, relationship


# Колонки, которые могут отсутствовать в старых БД.
# При запуске приложения они будут добавлены автоматически.
_MIGRATIONS = {
    'ch3_measurements': [
        ('max_outlier_ppm', 'FLOAT'),
    ],
    'ch3_measurement_points': [
        ('ppm', 'FLOAT'),
    ],
    'ch3_summary': [
        ('max_outlier_ppm', 'FLOAT'),
    ],
}


def _auto_migrate(engine):
    """Добавляет недостающие колонки в существующие таблицы.
    Работает безопасно: если колонка уже есть - пропускает.
    """
    inspector = inspect(engine)
    existing_tables = set(inspector.get_table_names())
    with engine.begin() as conn:
        for table, cols in _MIGRATIONS.items():
            if table not in existing_tables:
                continue
            existing_cols = {c['name'] for c in inspector.get_columns(table)}
            for col_name, col_type in cols:
                if col_name not in existing_cols:
                    conn.execute(text(
                        f'ALTER TABLE {table} ADD COLUMN {col_name} {col_type}'))
                    print(f'[migration] {table}.{col_name} {col_type} добавлена')


Base = declarative_base()


class Measurement(Base):
    __tablename__ = 'ch3_measurements'

    id = Column(Integer, primary_key=True, autoincrement=True)
    mcu_number = Column(String(64), index=True, nullable=False)
    resonator_number = Column(String(64), index=True, nullable=False)
    cycle_type = Column(String(32), nullable=False)
    nominal_khz = Column(Float)
    start_time = Column(DateTime)
    end_time = Column(DateTime)
    max_freq = Column(Float)
    min_freq = Column(Float)
    max_ppm = Column(Float)
    min_ppm = Column(Float)
    monotonicity_ppm = Column(Float)
    max_outlier_ppm = Column(Float)
    epsilon = Column(Float)
    points_count = Column(Integer)

    points = relationship('MeasurementPoint',
                          back_populates='measurement',
                          cascade='all, delete-orphan')


class MeasurementPoint(Base):
    __tablename__ = 'ch3_measurement_points'

    id = Column(Integer, primary_key=True, autoincrement=True)
    measurement_id = Column(Integer,
                            ForeignKey('ch3_measurements.id',
                                       ondelete='CASCADE'),
                            index=True)
    t = Column(Float)
    frequency = Column(Float)
    ppm = Column(Float)

    measurement = relationship('Measurement', back_populates='points')


class Summary(Base):
    __tablename__ = 'ch3_summary'

    id = Column(Integer, primary_key=True, autoincrement=True)
    mcu_number = Column(String(64), index=True, nullable=False)
    resonator_number = Column(String(64), index=True, nullable=False)
    nominal_khz = Column(Float)
    max_ppm = Column(Float)
    min_ppm = Column(Float)
    monotonicity_ppm = Column(Float)
    cycles_count = Column(Integer)
    max_outlier_ppm = Column(Float)
    updated_at = Column(DateTime,
                        default=datetime.datetime.utcnow,
                        onupdate=datetime.datetime.utcnow)

    __table_args__ = (
        UniqueConstraint('mcu_number', 'resonator_number',
                         name='uq_mcu_resonator'),
    )


def get_engine(db_cfg):
    """Создать engine для БД измерений.

    Принимает:
      * строку-URL   - "mysql+mysqlconnector://user:pass@host/db";
      * dict с 'url' - как пишет FrequencyMeasure.config._db_from_options();
      * dict {host,user,password,database} - legacy-формат.

    Логика:
      1) привязать конкретный драйвер к mysql:// (в SQLAlchemy 2.x
         голый mysql:// не допускается);
      2) если указан mysql+mysqlconnector, но пакет не установлен -
         прозрачно переключиться на pymysql;
      3) гарантировать charset=utf8mb4.
    """
    if isinstance(db_cfg, str):
        url = db_cfg
    elif isinstance(db_cfg, dict) and db_cfg.get('url'):
        url = db_cfg['url']
    elif isinstance(db_cfg, dict):
        url = (f"mysql+pymysql://{db_cfg['user']}:{db_cfg['password']}"
               f"@{db_cfg['host']}/{db_cfg['database']}")
    else:
        raise ValueError(f"Некорректный db_cfg: {db_cfg!r}")

    if url.startswith('mysql+mysqlconnector://'):
        try:
            import mysql.connector  # noqa: F401
        except ImportError:
            print('[models] mysql-connector-python не установлен - '
                  'переключаюсь на pymysql')
            url = url.replace('mysql+mysqlconnector://', 'mysql+pymysql://')
    elif url.startswith('mysql://'):
        try:
            import pymysql  # noqa: F401
            url = url.replace('mysql://', 'mysql+pymysql://', 1)
        except ImportError:
            try:
                import mysql.connector  # noqa: F401
                url = url.replace('mysql://',
                                  'mysql+mysqlconnector://', 1)
            except ImportError:
                pass

    if 'charset=' not in url:
        url += ('&' if '?' in url else '?') + 'charset=utf8mb4'

    return create_engine(url, pool_pre_ping=True, future=True)


def init_db(engine):
    Base.metadata.create_all(engine)
    _auto_migrate(engine)
    return sessionmaker(bind=engine, future=True)