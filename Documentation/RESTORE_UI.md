# Восстановление полного Documentation/ui.py

На ветке `fix/assistant-protocol` файл `Documentation/ui.py` временно
заменён bootstrap-версией (из-за лимита размера коммита через API).

## Быстрый restore

```bash
git checkout main -- Documentation/ui.py
```

Затем добавьте в начало (после импорта seed):

```python
from .seed import seed_all
try:
    from .seed_assistant import seed_assistant_docs
except Exception:
    def seed_assistant_docs():
        pass
```

И в оба места, где вызывается `seed_all()`, добавьте следом:

```python
seed_assistant_docs()
```

## Что уже есть на ветке

- `Documentation/seed_assistant.py` — 5 статей раздела «Ассистент»
- Bootstrap `ui.py` вызывает `seed_assistant_docs()` при открытии окна
