"""Bootstrap окна документации + seed раздела «Ассистент».

Полный UI восстанавливается из _ui_body_a/b при их наличии.
Иначе — краткое окно со списком статей «Ассистент».
"""
import dearpygui.dearpygui as dpg
from . import db as doc_db

try:
    from .seed import seed_all
except Exception:
    def seed_all():
        pass

try:
    from .seed_assistant import seed_assistant_docs
except Exception:
    def seed_assistant_docs():
        pass

WIN = "doc_main_window"


def create_documentation_window():
    try:
        doc_db.ensure_tables()
        seed_all()
        seed_assistant_docs()
    except Exception as e:
        print(f"[Documentation] init error: {e}")

    from pathlib import Path
    p = Path(__file__).resolve().parent
    a, b = p / "_ui_body_a.py", p / "_ui_body_b.py"
    if (a.is_file() and b.is_file()
            and a.stat().st_size > 1000 and b.stat().st_size > 1000):
        src = a.read_text(encoding="utf-8") + b.read_text(encoding="utf-8")
        ns = {}
        exec(compile(src, "Documentation/ui_body.py", "exec"), ns)
        fn = ns.get("create_documentation_window")
        if callable(fn):
            return fn()

    if dpg.does_item_exist(WIN):
        dpg.configure_item(WIN, show=True)
        return

    with dpg.window(label="Документация", tag=WIN, width=900, height=600):
        dpg.add_text("Раздел «Ассистент» добавлен в базу документации.")
        dpg.add_spacer(height=8)
        dpg.add_text("Статьи (откроются после полного восстановления UI):")
        try:
            docs = doc_db.list_docs("Ассистент")
            for d in docs:
                dpg.add_text(f"  - {d.get('Title')}  [{d.get('Slug')}]")
            if not docs:
                dpg.add_text("  (статьи ещё не созданы — переоткройте окно)")
        except Exception as e:
            dpg.add_text(f"  ошибка списка: {e}")
