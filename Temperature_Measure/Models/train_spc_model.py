# -*- coding: utf-8 -*-
"""
Классификация спецификаций (specification) по данным резонаторов из psidata.
Признаки: Nominal, F, R, C0, Cq, Q
Метка:    Spc  (имя спецификации)
"""

import os
import joblib
import numpy as np
import pandas as pd
from sqlalchemy import create_engine, text

from sklearn.model_selection import train_test_split, StratifiedKFold, GridSearchCV
from sklearn.preprocessing import LabelEncoder, OneHotEncoder, StandardScaler
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (classification_report, confusion_matrix,
                             accuracy_score, balanced_accuracy_score)
from sklearn.impute import SimpleImputer

# ----------------------------------------------------------------------------
# 1. Подключение к БД
# ----------------------------------------------------------------------------
sqlengine = 'mysql+mysqlconnector://xampp:43FPa!29S8HQeAW@MES1:3306/coordinator'
engine = create_engine(sqlengine, pool_pre_ping=True)

# ----------------------------------------------------------------------------
# 2. Загрузка данных
# ----------------------------------------------------------------------------
FEATURES = ['Nominal', 'F', 'R', 'C0', 'Cq', 'Q']
TARGET = 'Spc'

query = f"""
    SELECT {', '.join(FEATURES)}, {TARGET}
    FROM psidata
    WHERE {TARGET} IS NOT NULL
      AND {TARGET} <> ''
      AND {TARGET} <> '0'
"""

print("Загрузка данных из psidata ...")
df = pd.read_sql(text(query), engine, coerce_float=True)
print(f"Загружено строк: {len(df)}")

# Приводим числовые колонки к float, ошибки -> NaN
for col in FEATURES:
    df[col] = pd.to_numeric(df[col], errors='coerce')

# Nominal — строковый код (например "58.941176" или иной), оставляем как категорию
df['Nominal'] = df['Nominal'].astype(str).str.strip()

# Удаляем строки без метки
df = df.dropna(subset=[TARGET]).copy()
df[TARGET] = df[TARGET].astype(str).str.strip()
df = df[df[TARGET] != '']

print(f"Строк после очистки: {len(df)}")
print(f"Уникальных спецификаций: {df[TARGET].nunique()}")
print(df[TARGET].value_counts().head(20))

# ----------------------------------------------------------------------------
# 3. Отбор спецификаций с достаточным числом примеров (для стратификации)
# ----------------------------------------------------------------------------
MIN_SAMPLES = 20          # минимум записей на класс
counts = df[TARGET].value_counts()
valid_classes = counts[counts >= MIN_SAMPLES].index
df = df[df[TARGET].isin(valid_classes)].copy()
print(f"Классов после фильтра (>= {MIN_SAMPLES}): {df[TARGET].nunique()}, "
      f"строк: {len(df)}")

if df[TARGET].nunique() < 2:
    raise SystemExit("Недостаточно классов для обучения модели.")

# ----------------------------------------------------------------------------
# 4. Разделение на train / test
# ----------------------------------------------------------------------------
X = df[FEATURES]
y = df[TARGET]

label_enc = LabelEncoder()
y_enc = label_enc.fit_transform(y)

X_train, X_test, y_train, y_test = train_test_split(
    X, y_enc,
    test_size=0.2,
    random_state=42,
    stratify=y_enc
)

# ----------------------------------------------------------------------------
# 5. Препроцессинг + модель
# ----------------------------------------------------------------------------
numeric_features = ['F', 'R', 'C0', 'Cq', 'Q']
categorical_features = ['Nominal']

numeric_pipe = Pipeline([
    ('imputer', SimpleImputer(strategy='median')),
    ('scaler', StandardScaler()),
])

categorical_pipe = Pipeline([
    ('imputer', SimpleImputer(strategy='most_frequent')),
    ('onehot', OneHotEncoder(handle_unknown='ignore', sparse_output=False)),
])

preprocessor = ColumnTransformer([
    ('num', numeric_pipe, numeric_features),
    ('cat', categorical_pipe, categorical_features),
])

pipeline = Pipeline([
    ('prep', preprocessor),
    ('clf', RandomForestClassifier(
        random_state=42,
        class_weight='balanced',
        n_jobs=-1
    ))
])

# ----------------------------------------------------------------------------
# 6. Кросс-валидация + подбор гиперпараметров
# ----------------------------------------------------------------------------
cv = StratifiedKFold(n_splits=min(5, counts[counts >= MIN_SAMPLES].min()),
                     shuffle=True, random_state=42)

param_grid = {
    'clf__n_estimators': [200, 400],
    'clf__max_depth': [None, 20, 40],
    'clf__min_samples_leaf': [1, 2, 4],
}

print("Подбор гиперпараметров (GridSearchCV) ...")
grid = GridSearchCV(
    pipeline, param_grid,
    cv=cv,
    scoring='balanced_accuracy',
    n_jobs=-1,
    verbose=1
)
grid.fit(X_train, y_train)
print(f"Лучшие параметры: {grid.best_params_}")
print(f"Лучший CV score (balanced_accuracy): {grid.best_score_:.4f}")

best_model = grid.best_estimator_

# ----------------------------------------------------------------------------
# 7. Оценка на тесте
# ----------------------------------------------------------------------------
y_pred = best_model.predict(X_test)
acc = accuracy_score(y_test, y_pred)
bal_acc = balanced_accuracy_score(y_test, y_pred)
print(f"\nTest accuracy         : {acc:.4f}")
print(f"Test balanced accuracy: {bal_acc:.4f}")

# Отчёт по классам (только для классов, встретившихся в тесте)
present = np.unique(np.concatenate([y_test, y_pred]))
report = classification_report(
    y_test, y_pred,
    labels=present,
    target_names=label_enc.inverse_transform(present),
    zero_division=0
)
print("\nClassification report:\n", report)

# Матрица ошибок
cm = confusion_matrix(y_test, y_pred, labels=present)
cm_df = pd.DataFrame(
    cm,
    index=label_enc.inverse_transform(present),
    columns=label_enc.inverse_transform(present)
)

# ----------------------------------------------------------------------------
# 8. Сохранение артефактов
# ----------------------------------------------------------------------------
OUT_DIR = "spc_model"
os.makedirs(OUT_DIR, exist_ok=True)

joblib.dump(best_model,   os.path.join(OUT_DIR, "model.joblib"))
joblib.dump(label_enc,    os.path.join(OUT_DIR, "label_encoder.joblib"))

with open(os.path.join(OUT_DIR, "report.txt"), "w", encoding="utf-8") as f:
    f.write(f"Best params: {grid.best_params_}\n")
    f.write(f"CV balanced_accuracy: {grid.best_score_:.4f}\n")
    f.write(f"Test accuracy: {acc:.4f}\n")
    f.write(f"Test balanced accuracy: {bal_acc:.4f}\n\n")
    f.write(report)
    f.write("\n\nConfusion matrix:\n")
    f.write(cm_df.to_string())

# Сохраняем карту "спецификация -> класс" для интерпретации
pd.DataFrame({
    'label': label_enc.classes_,
    'class_id': range(len(label_enc.classes_)),
    'support': [counts.get(c, 0) for c in label_enc.classes_]
}).to_csv(os.path.join(OUT_DIR, "classes.csv"), index=False, encoding="utf-8")

print(f"\nАртефакты сохранены в '{OUT_DIR}/'")

# ----------------------------------------------------------------------------
# 9. Пример предсказания для новой записи (закомментировано)
# ----------------------------------------------------------------------------
# new_sample = pd.DataFrame([{
#     'Nominal': '58.941176',
#     'F': 12.56, 'R': 127.537, 'C0': 0.58,
#     'Cq': 0.18, 'Q': 114.07
# }])
# pred = best_model.predict(new_sample)
# proba = best_model.predict_proba(new_sample).max()
# print("Предсказанная спецификация:", label_enc.inverse_transform(pred)[0],
#       f"(уверенность {proba:.3f})")