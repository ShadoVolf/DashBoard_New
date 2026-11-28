# -*- coding: utf-8 -*-
"""
Загрузка и предсказание спецификации по sklearn-модели (spc_model).

Признаки: Nominal, F, R, C0, Cq, Q
Метка:    имя спецификации (Spc)

Модель может браться:
  1) из файлов Temperature_Measure/Models/spc_model/*.joblib
  2) из таблицы БД spc_ai_model (BLOB), если запись есть и свежее/приоритетнее
"""

from __future__ import annotations

import io
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np
import pandas as pd

try:
    import joblib
except ImportError:  # pragma: no cover
    joblib = None

FEATURES_DEFAULT = ['Nominal', 'F', 'R', 'C0', 'Cq', 'Q']

_model_bundle: Optional[Dict[str, Any]] = None
_model_source: str = ''  # 'files' | 'db' | ''


def _models_dir() -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'spc_model')


def model_files_present(base_dir: Optional[str] = None) -> bool:
    d = base_dir or _models_dir()
    needed = ('preprocessor.joblib', 'classifier.joblib',
              'label_encoder.joblib', 'features.joblib')
    return all(os.path.isfile(os.path.join(d, n)) for n in needed)


def load_model_from_files(base_dir: Optional[str] = None) -> Dict[str, Any]:
    if joblib is None:
        raise RuntimeError('joblib не установлен')
    d = base_dir or _models_dir()
    prep = joblib.load(os.path.join(d, 'preprocessor.joblib'))
    clf = joblib.load(os.path.join(d, 'classifier.joblib'))
    le = joblib.load(os.path.join(d, 'label_encoder.joblib'))
    features = joblib.load(os.path.join(d, 'features.joblib'))
    if not isinstance(features, (list, tuple)):
        features = list(features)
    return {
        'prep': prep,
        'clf': clf,
        'le': le,
        'features': list(features),
    }


def load_model_from_db(engine=None) -> Optional[Dict[str, Any]]:
    """
    Читает последнюю активную запись из spc_ai_model.
    Ожидаемые колонки: id, name, created_at, is_active,
      preprocessor BLOB, classifier BLOB, label_encoder BLOB, features BLOB
    """
    if joblib is None:
        return None
    try:
        from sqlalchemy import text
        if engine is None:
            from Options import get_connection_string
            from sqlalchemy import create_engine
            engine = create_engine(get_connection_string(), pool_pre_ping=True)
        q = text(
            "SELECT preprocessor, classifier, label_encoder, features "
            "FROM `spc_ai_model` WHERE is_active = 1 "
            "ORDER BY id DESC LIMIT 1"
        )
        with engine.connect() as conn:
            row = conn.execute(q).fetchone()
        if not row:
            return None
        prep = joblib.load(io.BytesIO(row[0]))
        clf = joblib.load(io.BytesIO(row[1]))
        le = joblib.load(io.BytesIO(row[2]))
        features = joblib.load(io.BytesIO(row[3]))
        if not isinstance(features, (list, tuple)):
            features = list(features)
        return {
            'prep': prep,
            'clf': clf,
            'le': le,
            'features': list(features),
        }
    except Exception as e:
        print(f'[SpcAI] load_model_from_db: {e}', flush=True)
        return None


def ensure_db_table(engine=None) -> bool:
    """Создаёт таблицу spc_ai_model, если её ещё нет."""
    try:
        from sqlalchemy import text
        if engine is None:
            from Options import get_connection_string
            from sqlalchemy import create_engine
            engine = create_engine(get_connection_string(), pool_pre_ping=True)
        ddl = """
        CREATE TABLE IF NOT EXISTS `spc_ai_model` (
            `id` INT NOT NULL AUTO_INCREMENT,
            `name` VARCHAR(128) NOT NULL DEFAULT 'spc_model',
            `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            `is_active` TINYINT(1) NOT NULL DEFAULT 1,
            `preprocessor` LONGBLOB NOT NULL,
            `classifier` LONGBLOB NOT NULL,
            `label_encoder` LONGBLOB NOT NULL,
            `features` LONGBLOB NOT NULL,
            `note` VARCHAR(512) NULL,
            PRIMARY KEY (`id`),
            KEY `idx_active` (`is_active`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """
        with engine.begin() as conn:
            conn.execute(text(ddl))
        return True
    except Exception as e:
        print(f'[SpcAI] ensure_db_table: {e}', flush=True)
        return False


def save_model_to_db(
    base_dir: Optional[str] = None,
    name: str = 'spc_model',
    note: str = '',
    engine=None,
    deactivate_others: bool = True,
) -> bool:
    """
    Сохраняет текущие joblib-файлы из spc_model/ в таблицу spc_ai_model.
    """
    if joblib is None:
        print('[SpcAI] joblib не установлен', flush=True)
        return False
    d = base_dir or _models_dir()
    if not model_files_present(d):
        print(f'[SpcAI] нет файлов модели в {d}', flush=True)
        return False
    try:
        from sqlalchemy import text
        if engine is None:
            from Options import get_connection_string
            from sqlalchemy import create_engine
            engine = create_engine(get_connection_string(), pool_pre_ping=True)
        if not ensure_db_table(engine):
            return False

        def _read(path: str) -> bytes:
            with open(path, 'rb') as f:
                return f.read()

        blobs = {
            'preprocessor': _read(os.path.join(d, 'preprocessor.joblib')),
            'classifier': _read(os.path.join(d, 'classifier.joblib')),
            'label_encoder': _read(os.path.join(d, 'label_encoder.joblib')),
            'features': _read(os.path.join(d, 'features.joblib')),
        }

        with engine.begin() as conn:
            if deactivate_others:
                conn.execute(text('UPDATE `spc_ai_model` SET is_active = 0'))
            conn.execute(
                text(
                    "INSERT INTO `spc_ai_model` "
                    "(name, is_active, preprocessor, classifier, label_encoder, features, note) "
                    "VALUES (:name, 1, :preprocessor, :classifier, :label_encoder, :features, :note)"
                ),
                {
                    'name': name,
                    'note': note or '',
                    **blobs,
                },
            )
        print(f'[SpcAI] модель сохранена в БД (name={name!r})', flush=True)
        return True
    except Exception as e:
        print(f'[SpcAI] save_model_to_db: {e}', flush=True)
        return False


def get_model(force_reload: bool = False, prefer_db: bool = True) -> Optional[Dict[str, Any]]:
    """Ленивая загрузка бандла модели (сначала БД, затем файлы)."""
    global _model_bundle, _model_source
    if _model_bundle is not None and not force_reload:
        return _model_bundle

    bundle = None
    source = ''
    if prefer_db:
        bundle = load_model_from_db()
        if bundle:
            source = 'db'
    if bundle is None and model_files_present():
        try:
            bundle = load_model_from_files()
            source = 'files'
        except Exception as e:
            print(f'[SpcAI] load_model_from_files: {e}', flush=True)
    _model_bundle = bundle
    _model_source = source
    if bundle:
        print(f'[SpcAI] модель загружена из {source}', flush=True)
    else:
        print('[SpcAI] модель недоступна', flush=True)
    return _model_bundle


def clear_model_cache() -> None:
    global _model_bundle, _model_source
    _model_bundle = None
    _model_source = ''


def _row_to_features(
    sample: Union[dict, pd.Series, pd.DataFrame],
    feature_names: Sequence[str],
) -> pd.DataFrame:
    if isinstance(sample, pd.DataFrame):
        df = sample.copy()
    elif isinstance(sample, pd.Series):
        df = sample.to_frame().T
    else:
        df = pd.DataFrame([dict(sample)])

    out = {}
    for col in feature_names:
        if col not in df.columns:
            # синонимы
            aliases = {
                'Nominal': ['Nominal', 'Номинал', 'nominal', 'Target_Hz'],
                'F': ['F', 'Fs', 'Fs_ppm', 'freq'],
                'R': ['R', 'Rs', 'Resistance'],
                'C0': ['C0', 'C0_pF'],
                'Cq': ['Cq', 'C1', 'C1_pF'],
                'Q': ['Q', 'Qfactor'],
            }.get(col, [col])
            val = None
            for a in aliases:
                if a in df.columns:
                    val = df[a].iloc[0]
                    break
            out[col] = val
        else:
            out[col] = df[col].iloc[0]

    # Nominal как строка (как при обучении)
    if 'Nominal' in out and out['Nominal'] is not None:
        try:
            # если пришла частота в Гц — переведём в «номинал» как в данных (МГц-подобное)
            n = float(out['Nominal'])
            if n > 1000:  # похоже на Гц
                out['Nominal'] = str(round(n / 1e6, 6))
            else:
                out['Nominal'] = str(n)
        except (TypeError, ValueError):
            out['Nominal'] = str(out['Nominal']).strip()

    for col in feature_names:
        if col == 'Nominal':
            continue
        try:
            out[col] = float(out[col]) if out[col] is not None else np.nan
        except (TypeError, ValueError):
            out[col] = np.nan

    return pd.DataFrame([out])[list(feature_names)]


def predict_spc(
    sample: Union[dict, pd.Series, pd.DataFrame],
    top_k: int = 3,
) -> Tuple[Optional[str], List[Tuple[str, float]]]:
    """
    Предсказать спецификацию.

    Returns:
        (best_name, [(name, proba), ... top_k])
        или (None, []) если модель/данные недоступны.
    """
    bundle = get_model()
    if not bundle:
        return None, []

    try:
        X = _row_to_features(sample, bundle['features'])
        X_pp = bundle['prep'].transform(X.to_numpy(dtype=np.float64))
        y_pred = bundle['clf'].predict(X_pp)
        best = bundle['le'].inverse_transform(y_pred)[0]

        top: List[Tuple[str, float]] = []
        if hasattr(bundle['clf'], 'predict_proba'):
            proba = bundle['clf'].predict_proba(X_pp)[0]
            idx = np.argsort(proba)[-max(1, top_k):][::-1]
            classes = bundle['le'].classes_
            top = [(str(classes[i]), float(proba[i])) for i in idx]
        else:
            top = [(str(best), 1.0)]
        return str(best), top
    except Exception as e:
        print(f'[SpcAI] predict_spc: {e}', flush=True)
        return None, []


def rank_spc_list_with_ai(
    candidates: Sequence[str],
    sample: Optional[Union[dict, pd.Series, pd.DataFrame]] = None,
    top_k: int = 5,
) -> List[str]:
    """
    Переупорядочить список кандидатов: предсказанные моделью имена — в начало.
    Если sample нет — возвращает candidates без изменений.
    Работает вместе с текущими режимами (fast/classic): только меняет порядок.
    """
    if not candidates:
        return list(candidates)
    if sample is None:
        return list(candidates)

    best, top = predict_spc(sample, top_k=top_k)
    if not top and not best:
        return list(candidates)

    preferred = []
    seen = set()
    for name, _p in top:
        if name in candidates and name not in seen:
            preferred.append(name)
            seen.add(name)
    if best and best in candidates and best not in seen:
        preferred.insert(0, best)
        seen.add(best)

    rest = [c for c in candidates if c not in seen]
    result = preferred + rest
    if preferred:
        print(f'[SpcAI] rank: top={preferred[:3]} (из {len(candidates)} кандидатов)',
              flush=True)
    return result


# CLI-пример (как раньше)
if __name__ == '__main__':
    X_new = {
        'Nominal': 58.941176,
        'F': 12.56, 'R': 127.537, 'C0': 0.58, 'Cq': 0.18, 'Q': 114.07,
    }
    spc, top3 = predict_spc(X_new, top_k=3)
    print('Predicted specification:', spc)
    print('Top-3 candidates:', top3)
