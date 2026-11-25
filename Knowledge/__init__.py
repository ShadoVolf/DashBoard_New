# -*- coding: utf-8 -*-
"""
Модуль Knowledge - применение моделей Filtr_Freq к замерам psidata.

- Каскад выбора замера (как Archive_View)
- Автоподбор модели: Spc содержит "РК731" -> по спецификации;
  иначе Ref_f (Гц->МГц) -> ближайший nominal, max test-score
- Каскад смены типа/модели
- Предсказание, таблица, печать протокола (F,R,C0,C1,Q + Filtr_Freq),
  сохранение filtr_freq в БД, экспорт CSV
"""

from .window import create_knowledge_window

__all__ = ["create_knowledge_window"]
