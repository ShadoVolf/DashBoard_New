"""Окно документации: дерево разделов слева, содержимое статьи справа."""
from pathlib import Path as _Path
_p = _Path(__file__).resolve().parent
_src = (_p / "_ui_body_a.py").read_text(encoding="utf-8")
_src += (_p / "_ui_body_b.py").read_text(encoding="utf-8")
exec(compile(_src, "Documentation/ui_body.py", "exec"), globals())
