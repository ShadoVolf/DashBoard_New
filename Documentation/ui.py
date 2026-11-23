"""
Окно документации: дерево разделов слева, содержимое статьи справа.

Изменения:
    * рендер без декоративных символов;
    * окна адаптируются к размеру вьюпорта;
    * в диалоге редактирования кнопки закреплены в нижней полосе,
      поля прокручиваются в child_window;
    * фильтры изображений регистронезависимы (.png/.PNG и т.д.);
    * при загрузке изображения путь берётся из selections, а не
      из file_path_name (там при фильтре `.*` приходит wildcard);
    * после успешной загрузки поле «Плейсхолдер» ОЧИЩАЕТСЯ,
      чтобы следующая загрузка не перезаписала первый файл;
      если автогенерируемое имя уже занято, добавляется суффикс
      _2, _3 и т.д.;
    * удаление изображений: кнопка «Удалить» в каждой строке
      таблицы + кнопка удаления по введённому плейсхолдеру;
    * панель вставки разметки в редакторе: H1/H2/H3, список,
      заметка, блок кода, тег картинки. Вставка пытается
      использовать позицию курсора, если DPG её отдаёт;
      иначе — в конец текста;
    * в рендере изображения явный widget tag и диагностика
      в консоль (размер, MIME, длина blob), чтобы при
      необходимости было видно, на каком шаге ломается;
    * заголовки разделов в дереве выделяются цветом, крупным
      и жирным системным шрифтом, а также мягким фоном через
      bind_item_theme / bind_item_font. Если bold-TTF на системе
      не найден, используется обычный шрифт увеличенного
      размера — визуальная «толщина» сохраняется.
"""
import io
import os
import re
import traceback

import dearpygui.dearpygui as dpg

from . import db as doc_db
from .seed import seed_all
from .seed import seed_all
from .seed_phasenoise import seed_phasenoise_docs

try:
    from .seed_assistant import seed_assistant_docs
except Exception:
    def seed_assistant_docs():
        pass
try:
    from Authorization.Login import LoginUser
except Exception:                                   # pragma: no cover
    LoginUser = None

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ---------------------------------------------------------------------------
# Теги и константы
# ---------------------------------------------------------------------------
WIN_DOC_TAG       = "doc_main_window"
WIN_DOC_EDIT_TAG  = "doc_edit_window"
TAG_DOC_TREE      = "doc_tree"
TAG_DOC_CONTENT   = "doc_content"
TAG_DOC_SEARCH    = "doc_search"
TAG_DOC_STATUS    = "doc_status"
TEX_REGISTRY      = "doc_tex_registry"
FONT_REGISTRY     = "doc_font_registry"
SECTION_THEME_TAG = "doc_section_theme"

COLOR_SECTION = (200, 225, 200)
COLOR_HEADER  = (210, 220, 255)
COLOR_HINT    = (140, 140, 140)
COLOR_WARN    = (220, 160, 120)
COLOR_CODE    = (180, 220, 255)

# Заголовки разделов в дереве: насыщенный зелёный + крупный жирный шрифт
SECTION_TREE_COLOR        = (150, 220, 170)
SECTION_FONT_SIZE         = 18   # крупнее стандартного 13
SECTION_FONT_SIZE_FALLBK  = 20   # если bold не найден — ещё крупнее

# Мягкий фон заголовка раздела, чтобы дополнительно «утолщить» вид
SECTION_BG_NORMAL   = (40, 60, 50, 200)
SECTION_BG_HOVERED  = (55, 80, 65, 220)
SECTION_BG_ACTIVE   = (70, 100, 80, 240)

WRAP_PX   = 900
IMG_MAX_W = 900

ALLOWED_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp"}

_section_font_tag    = None
_section_theme_ready = False


def _is_allowed_image(path: str) -> bool:
    """Проверка расширения без учёта регистра."""
    ext = os.path.splitext(path or "")[1].lower()
    return ext in ALLOWED_IMAGE_EXTS


def _extract_paths_from_appdata(app_data):
    """Достать пути к выбранным файлам из app_data file_dialog.

    При активном фильтре `.*` DPG кладёт в file_path_name путь
    с wildcard-суффиксом (folder/file.*), реальные пути лежат
    в словаре selections — его проверяем первым.
    """
    if not app_data:
        return []

    if isinstance(app_data, str):
        return [app_data.strip()] if app_data.strip() else []

    if isinstance(app_data, dict):
        paths = []

        sel = app_data.get("selections")
        if isinstance(sel, dict) and sel:
            for _name, p in sel.items():
                if isinstance(p, str) and p.strip():
                    paths.append(p)
        if paths:
            return paths

        for key in ("file_path_name", "file_path"):
            v = app_data.get(key)
            if isinstance(v, str) and v.strip():
                if v.endswith(".*"):
                    v = v[:-2]
                return [v]
        return []

    if isinstance(app_data, (list, tuple)):
        return [p for p in app_data if isinstance(p, str) and p.strip()]

    return []


def _extract_path_from_appdata(app_data):
    """Одиночный путь (обёртка)."""
    paths = _extract_paths_from_appdata(app_data)
    return paths[0] if paths else None


# ---------------------------------------------------------------------------
# Общее состояние
# ---------------------------------------------------------------------------
_current_doc_id  = None
_editing_doc_id  = None
_texture_cache: dict = {}


def _get_login_user() -> str:
    try:
        if LoginUser is not None and getattr(LoginUser, "login", None):
            v = str(LoginUser.login[0]).strip()
            if v:
                return v
    except Exception:
        pass
    return "unknown"


def _get_screen_size():
    try:
        w = dpg.get_viewport_client_width()
        h = dpg.get_viewport_client_height()
        if w > 100 and h > 100:
            return int(w), int(h)
    except Exception:
        pass
    return 1600, 900


def _show_error(msg, exc=None):
    text = str(msg)
    if exc is not None:
        text += f"\n{exc}"
        traceback.print_exc()
    tag = "doc_err_win"
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.window(label="Сообщение", modal=True, autosize=True,
                    pos=(500, 300), tag=tag):
        dpg.add_text(text, wrap=520)
        dpg.add_button(label="OK",
                       callback=lambda: dpg.delete_item(tag))


def _show_info(msg: str):
    tag = "doc_info_win"
    if dpg.does_item_exist(tag):
        dpg.delete_item(tag)
    with dpg.window(label="Готово", modal=True, autosize=True,
                    pos=(500, 300), tag=tag):
        dpg.add_text(msg, wrap=520)
        dpg.add_button(label="OK",
                       callback=lambda: dpg.delete_item(tag))


# ---------------------------------------------------------------------------
# Текстуры
# ---------------------------------------------------------------------------
def _ensure_registry():
    if not dpg.does_item_exist(TEX_REGISTRY):
        with dpg.texture_registry(tag=TEX_REGISTRY):
            pass


def _ensure_font_registry():
    if not dpg.does_item_exist(FONT_REGISTRY):
        with dpg.font_registry(tag=FONT_REGISTRY):
            pass


def _invalidate_textures(doc_id=None):
    for key, tag in list(_texture_cache.items()):
        if doc_id is None or key[0] == doc_id:
            if dpg.does_item_exist(tag):
                try:
                    dpg.delete_item(tag)
                except Exception:
                    pass
            _texture_cache.pop(key, None)


def _blob_to_texture(blob: bytes, tag: str):
    _ensure_registry()
    if dpg.does_item_exist(tag):
        try:
            dpg.delete_item(tag)
        except Exception:
            pass

    if HAS_PIL:
        img = Image.open(io.BytesIO(blob)).convert("RGBA")
        w, h = img.size
        data = [v / 255.0 for v in img.tobytes()]
        dpg.add_static_texture(w, h, data, tag=tag, parent=TEX_REGISTRY)
    else:
        import tempfile
        fd, path = tempfile.mkstemp(suffix=".png")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(blob)
            w, h, _ch, data = dpg.load_image(path)
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass
        dpg.add_static_texture(w, h, data, tag=tag, parent=TEX_REGISTRY)

    try:
        return dpg.get_texture_size(tag)
    except Exception:
        return (0, 0)


# ---------------------------------------------------------------------------
# Шрифт и тема заголовков разделов в дереве
# ---------------------------------------------------------------------------
def _get_section_font():
    """Шрифт для заголовков разделов: сначала bold, иначе — крупный обычный."""
    global _section_font_tag
    if _section_font_tag and dpg.does_item_exist(_section_font_tag):
        return _section_font_tag

    _ensure_font_registry()

    # 1) Пытаемся найти жирный (bold) шрифт.
    bold_candidates = [
        "C:/Windows/Fonts/segoeuib.ttf",              # Segoe UI Bold
        "C:/Windows/Fonts/arialbd.ttf",               # Arial Bold
        "C:/Windows/Fonts/tahomabd.ttf",              # Tahoma Bold
        "C:/Windows/Fonts/calibrib.ttf",              # Calibri Bold
        "C:/Windows/Fonts/verdanab.ttf",              # Verdana Bold
        "C:/Windows/Fonts/timesbd.ttf",               # Times New Roman Bold
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/TTF/DejaVuSans-Bold.ttf",
        "/Library/Fonts/Arial Bold.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in bold_candidates:
        if os.path.isfile(path):
            try:
                _section_font_tag = dpg.add_font(
                    path, SECTION_FONT_SIZE, parent=FONT_REGISTRY
                )
                print(f"[Documentation] section bold font: {path} "
                      f"({SECTION_FONT_SIZE}px)")
                return _section_font_tag
            except Exception as e:
                print(f"[Documentation] bold font fail {path}: {e}")

    # 2) Fallback: обычный шрифт, но крупнее — визуальная «толщина»
    #    компенсируется размером.
    regular_candidates = [
        "C:/Windows/Fonts/segoeui.ttf",
        "C:/Windows/Fonts/arial.ttf",
        "C:/Windows/Fonts/calibri.ttf",
        "C:/Windows/Fonts/tahoma.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "/usr/share/fonts/TTF/DejaVuSans.ttf",
        "/Library/Fonts/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
    ]
    for path in regular_candidates:
        if os.path.isfile(path):
            try:
                _section_font_tag = dpg.add_font(
                    path, SECTION_FONT_SIZE_FALLBK, parent=FONT_REGISTRY
                )
                print(f"[Documentation] section regular font (larger): "
                      f"{path} ({SECTION_FONT_SIZE_FALLBK}px)")
                return _section_font_tag
            except Exception as e:
                print(f"[Documentation] font fail {path}: {e}")

    print("[Documentation] no font for sections found - only color "
          "and background will be applied")
    return None


def _get_section_theme():
    """Тема для tree_node разделов: цветной текст + мягкий фон."""
    global _section_theme_ready
    if _section_theme_ready and dpg.does_item_exist(SECTION_THEME_TAG):
        return SECTION_THEME_TAG

    if not dpg.does_item_exist(SECTION_THEME_TAG):
        with dpg.theme(tag=SECTION_THEME_TAG):
            with dpg.theme_component(dpg.mvTreeNode):
                dpg.add_theme_color(
                    dpg.mvThemeCol_Text,
                    (*SECTION_TREE_COLOR, 255)
                )
                # Мягкий фон заголовка раздела — усиливает «толщину»
                try:
                    dpg.add_theme_color(
                        dpg.mvThemeCol_Header,
                        SECTION_BG_NORMAL
                    )
                    dpg.add_theme_color(
                        dpg.mvThemeCol_HeaderHovered,
                        SECTION_BG_HOVERED
                    )
                    dpg.add_theme_color(
                        dpg.mvThemeCol_HeaderActive,
                        SECTION_BG_ACTIVE
                    )
                except Exception as e:
                    print(f"[Documentation] theme color header err: {e}")
    _section_theme_ready = True
    return SECTION_THEME_TAG


# ---------------------------------------------------------------------------
# Отрисовка контента (без спецсимволов)
# ---------------------------------------------------------------------------
_RE_IMG = re.compile(r"^\[\[img:([\w\-.]+)\]\]$")


def _render_content(doc_id: int, content: str):
    in_code = False
    for raw in (content or "").splitlines():
        stripped = raw.strip()

        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            dpg.add_text(raw if raw else " ", color=COLOR_CODE)
            continue

        _render_line(doc_id, raw)


def _render_line(doc_id: int, line: str):
    stripped = line.strip()

    if not stripped:
        dpg.add_spacer(height=6)
        return

    m = _RE_IMG.match(stripped)
    if m:
        _render_image(doc_id, m.group(1))
        return

    if stripped.startswith("### "):
        dpg.add_text(stripped[4:], color=COLOR_SECTION)
        return
    if stripped.startswith("## "):
        dpg.add_text(stripped[3:], color=COLOR_HEADER)
        dpg.add_separator()
        return
    if stripped.startswith("# "):
        dpg.add_text(stripped[2:], color=COLOR_HEADER)
        return
    if stripped.startswith("- "):
        dpg.add_text("    " + stripped[2:], wrap=WRAP_PX)
        return
    if stripped.startswith("> "):
        dpg.add_text("    " + stripped[2:], color=COLOR_WARN, wrap=WRAP_PX)
        return

    dpg.add_text(stripped, wrap=WRAP_PX)


def _render_image(doc_id: int, placeholder: str):
    print(f"[Documentation] render image doc={doc_id} ph='{placeholder}'")

    row = doc_db.get_image(doc_id, placeholder)
    if not row or not row.get("Data"):
        dpg.add_text(f"[Скриншот {placeholder} еще не добавлен]",
                     color=COLOR_HINT)
        print(f"[Documentation]   -> no data for '{placeholder}'")
        return

    data_len = len(row["Data"])
    print(f"[Documentation]   -> blob {data_len} bytes, "
          f"mime={row.get('MimeType')!r}")

    key = (doc_id, placeholder)
    tag = f"doc_tex_{doc_id}_{placeholder}"

    # Пересоздаём текстуру, если её нет в кэше или её нет в DPG
    if (key not in _texture_cache
            or not dpg.does_item_exist(_texture_cache.get(key, ""))
            or not dpg.does_item_exist(tag)):
        try:
            tw, th = _blob_to_texture(row["Data"], tag)
            _texture_cache[key] = tag
            print(f"[Documentation]   -> texture created "
                  f"'{tag}' {tw}x{th}")
        except Exception as e:
            dpg.add_text(f"[Ошибка загрузки изображения: {e}]",
                         color=COLOR_HINT)
            print(f"[Documentation]   -> texture error: {e}")
            return
    else:
        print(f"[Documentation]   -> texture cached '{tag}'")

    try:
        w, h = dpg.get_texture_size(tag)
    except Exception:
        w, h = 0, 0

    # Явный widget tag, чтобы не пересекаться с texture tag
    widget_tag = f"doc_img_w_{doc_id}_{placeholder}"

    try:
        if w > IMG_MAX_W and w > 0:
            scale = IMG_MAX_W / w
            dpg.add_image(tag, tag=widget_tag,
                          width=IMG_MAX_W, height=int(h * scale))
        else:
            dpg.add_image(tag, tag=widget_tag)
    except Exception as e:
        print(f"[Documentation]   -> add_image error: {e}")
        dpg.add_text(f"[Ошибка: image widget не создан: {e}]",
                     color=COLOR_HINT)
        return

    if row.get("Caption"):
        dpg.add_text(row["Caption"], color=COLOR_HINT)


# ---------------------------------------------------------------------------
# Главное окно документации
# ---------------------------------------------------------------------------
def _create_main_window():
    global _current_doc_id

    if dpg.does_item_exist(WIN_DOC_TAG):
        dpg.configure_item(WIN_DOC_TAG, show=True)
        try:
            dpg.focus_item(WIN_DOC_TAG)
        except Exception:
            pass
        return

    try:
        doc_db.ensure_tables()
        seed_all()
        seed_assistant_docs()
        seed_phasenoise_docs()
    except Exception as e:
        print(f"[Documentation] init error: {e}")

    sw, sh = _get_screen_size()
    w = max(640, int(sw * 0.9))
    h = max(480, int(sh * 0.9))
    x = max(10, (sw - w) // 2)
    y = max(10, (sh - h) // 2)

    with dpg.window(label="Документация", tag=WIN_DOC_TAG,
                    width=w, height=h, pos=(x, y), no_close=True):

        with dpg.group(horizontal=True):
            dpg.add_input_text(tag=TAG_DOC_SEARCH, width=-450,
                               hint="Поиск по документации",
                               callback=lambda s, a, u: _rebuild_tree())
            dpg.add_button(label="Обновить", width=100,
                           callback=lambda: _rebuild_tree())
            dpg.add_button(label="Редактировать", width=130,
                           callback=_on_edit_current)
            dpg.add_button(label="Новая", width=100,
                           callback=lambda: _open_edit_dialog(None))

        with dpg.group(horizontal=True):
            dpg.add_text("", tag=TAG_DOC_STATUS, color=COLOR_SECTION)

        dpg.add_separator()

        with dpg.group(horizontal=True):
            with dpg.child_window(width=320, height=-1, border=True):
                with dpg.group(tag=TAG_DOC_TREE):
                    pass
            with dpg.child_window(tag=TAG_DOC_CONTENT, width=-1, height=-1,
                                  border=False, horizontal_scrollbar=True):
                pass

    _rebuild_tree()


# ---------------------------------------------------------------------------
# Дерево статей
# ---------------------------------------------------------------------------
def _rebuild_tree():
    global _current_doc_id
    if not dpg.does_item_exist(TAG_DOC_TREE):
        return

    for c in dpg.get_item_children(TAG_DOC_TREE, 1) or []:
        dpg.delete_item(c)

    search = ""
    if dpg.does_item_exist(TAG_DOC_SEARCH):
        search = dpg.get_value(TAG_DOC_SEARCH) or ""

    try:
        items = doc_db.list_docs(search=search)
    except Exception as e:
        with dpg.group(parent=TAG_DOC_TREE):
            dpg.add_text(f"Ошибка чтения БД: {e}", color=COLOR_WARN)
        return

    if not items:
        with dpg.group(parent=TAG_DOC_TREE):
            dpg.add_text("(нет статей)", color=COLOR_HINT)
        if dpg.does_item_exist(TAG_DOC_STATUS):
            dpg.set_value(TAG_DOC_STATUS, "Статей: 0")
        return

    sections = {}
    for r in items:
        sections.setdefault(r["Section"] or "Без раздела", []).append(r)

    section_theme = _get_section_theme()
    section_font  = _get_section_font()

    for sec_name in sorted(sections.keys()):
        sec_tag = f"doc_sec_{abs(hash(sec_name))}"
        # Ведущие пробелы визуально «раздувают» заголовок — усиливают
        # эффект жирного шрифта даже если bold-TTF не найден.
        with dpg.tree_node(label=f"  {sec_name}", parent=TAG_DOC_TREE,
                           default_open=True, tag=sec_tag):
            for row in sections[sec_name]:
                dpg.add_selectable(
                    label=row["Title"] or "(без названия)",
                    parent=sec_tag,
                    callback=_on_select_click,
                    user_data=row["ID"],
                )

        # Выделение заголовка раздела: цвет + фон + жирный/крупный шрифт
        if section_theme:
            try:
                dpg.bind_item_theme(sec_tag, section_theme)
            except Exception as e:
                print(f"[Documentation] bind theme error: {e}")
        if section_font:
            try:
                dpg.bind_item_font(sec_tag, section_font)
            except Exception as e:
                print(f"[Documentation] bind font error: {e}")

    if dpg.does_item_exist(TAG_DOC_STATUS):
        dpg.set_value(TAG_DOC_STATUS, f"Статей: {len(items)}")

    if _current_doc_id is None and items:
        _on_select(items[0]["ID"])


# ---------------------------------------------------------------------------
# Просмотр статьи
# ---------------------------------------------------------------------------
def _on_select_click(sender, app_data, user_data):
    _on_select(user_data)


def _on_select(doc_id: int):
    global _current_doc_id

    if dpg.does_item_exist(TAG_DOC_CONTENT):
        for c in dpg.get_item_children(TAG_DOC_CONTENT, 1) or []:
            dpg.delete_item(c)

    try:
        doc = doc_db.get_doc(doc_id)
    except Exception as e:
        with dpg.group(parent=TAG_DOC_CONTENT):
            dpg.add_text(f"Ошибка: {e}", color=COLOR_WARN)
        return

    if not doc:
        return

    _current_doc_id = doc["ID"]

    with dpg.group(parent=TAG_DOC_CONTENT):
        dpg.add_text(doc.get("Title") or "(без названия)",
                     color=COLOR_HEADER)
        dpg.add_text(f"Раздел: {doc.get('Section') or '-'}",
                     color=COLOR_HINT)
        dpg.add_separator()
        dpg.add_spacer(height=4)
        try:
            _render_content(doc["ID"], doc.get("Content") or "")
        except Exception as e:
            dpg.add_text(f"[Ошибка отрисовки: {e}]", color=COLOR_WARN)
            traceback.print_exc()


# ---------------------------------------------------------------------------
# Диалог редактирования статьи
# ---------------------------------------------------------------------------
def _on_edit_current():
    if not _current_doc_id:
        _show_error("Не выбрана статья")
        return
    _open_edit_dialog(_current_doc_id)


def _open_edit_dialog(doc_id):
    global _editing_doc_id

    if dpg.does_item_exist(WIN_DOC_EDIT_TAG):
        dpg.delete_item(WIN_DOC_EDIT_TAG)

    doc = doc_db.get_doc(doc_id) if doc_id else None
    _editing_doc_id = doc["ID"] if doc else None

    sw, sh = _get_screen_size()
    w = min(960, max(640, int(sw * 0.92)))
    h = min(900, max(650, int(sh * 0.92)))
    x = max(10, (sw - w) // 2)
    y = max(10, (sh - h) // 2)

    with dpg.window(label="Редактирование статьи", tag=WIN_DOC_EDIT_TAG,
                    width=w, height=h, pos=(x, y), no_close=True):

        with dpg.child_window(width=-1, height=-260, border=False):

            dpg.add_input_text(label="Slug", tag="doc_edit_slug",
                               width=-1,
                               default_value=(doc or {}).get("Slug", ""))
            dpg.add_input_text(label="Раздел", tag="doc_edit_section",
                               width=-1,
                               default_value=(doc or {}).get("Section",
                                                             "Общее"))
            dpg.add_input_text(label="Заголовок", tag="doc_edit_title",
                               width=-1,
                               default_value=(doc or {}).get("Title", ""))
            dpg.add_input_int(label="Порядок", tag="doc_edit_sort",
                              width=120,
                              default_value=int(
                                  (doc or {}).get("SortOrder") or 0))

            if doc:
                dpg.configure_item("doc_edit_slug", enabled=False)

            dpg.add_separator()

            dpg.add_text("Вставка разметки:", color=COLOR_HINT)
            with dpg.group(horizontal=True):
                dpg.add_button(label="H1", width=45,
                               callback=lambda: _insert_tag("# "))
                dpg.add_button(label="H2", width=45,
                               callback=lambda: _insert_tag("## "))
                dpg.add_button(label="H3", width=45,
                               callback=lambda: _insert_tag("### "))
                dpg.add_spacer(width=8)
                dpg.add_button(label="Список", width=90,
                               callback=lambda: _insert_tag("- "))
                dpg.add_button(label="Заметка", width=90,
                               callback=lambda: _insert_tag("> "))
                dpg.add_button(label="Код", width=70,
                               callback=lambda: _insert_tag("```\n\n```"))
                dpg.add_spacer(width=8)
                dpg.add_button(label="Картинка", width=110,
                               callback=_insert_image_tag)

            dpg.add_spacer(height=4)
            dpg.add_input_text(tag="doc_edit_content", multiline=True,
                               width=-1, height=-1,
                               default_value=(doc or {}).get("Content", ""))

        dpg.add_separator()
        dpg.add_text("Изображения", color=COLOR_SECTION)
        with dpg.group(horizontal=True):
            dpg.add_input_text(label="Плейсхолдер",
                               tag="doc_img_placeholder", width=280)
            dpg.add_button(label="Загрузить файл...",
                           callback=_open_file_dialog)
            dpg.add_button(label="Удалить по плейсхолдеру",
                           callback=_on_delete_image)

        with dpg.child_window(width=-1, height=140, border=True):
            with dpg.table(tag="doc_img_table", header_row=True,
                           borders_innerH=True, borders_innerV=True,
                           row_background=True,
                           policy=dpg.mvTable_SizingStretchProp):
                dpg.add_table_column(label="Плейсхолдер",
                                     init_width_or_weight=0.40)
                dpg.add_table_column(label="Тип",
                                     init_width_or_weight=0.20)
                dpg.add_table_column(label="Размер, байт",
                                     init_width_or_weight=0.15)
                dpg.add_table_column(label="",
                                     init_width_or_weight=0.25)

        dpg.add_separator()
        with dpg.group(horizontal=True):
            dpg.add_button(label="Сохранить", width=140,
                           callback=lambda: _save_doc(silent=False))
            dpg.add_button(label="Отмена", width=140,
                           callback=_on_cancel_edit)
            if doc:
                dpg.add_spacer(width=20)
                dpg.add_button(label="Удалить статью", width=180,
                               callback=_on_delete_doc)

    _refresh_image_table(doc)


# ---------------------------------------------------------------------------
# Вставка разметки (с попыткой использовать курсор)
# ---------------------------------------------------------------------------
def _get_text_cursor_pos(tag):
    """Попытка получить позицию курсора в input_text.

    В актуальных версиях DearPyGui публичного API для этого нет,
    поэтому функция проверяет несколько возможных имён и
    возвращает None, если ни одно не сработало.
    """
    for name in ("get_text_cursor_pos", "get_input_cursor_pos",
                 "get_cursor_pos_text"):
        func = getattr(dpg, name, None)
        if func is None:
            continue
        try:
            return int(func(tag))
        except Exception:
            continue
    return None


def _set_text_cursor_pos(tag, pos: int) -> None:
    """Попытка установить позицию курсора после вставки."""
    for name in ("set_text_cursor_pos", "set_input_cursor_pos",
                 "set_cursor_pos_text"):
        func = getattr(dpg, name, None)
        if func is None:
            continue
        try:
            func(tag, pos)
            return
        except Exception:
            continue


def _insert_tag(text: str, blank_line_before: bool = False):
    """Вставить маркер разметки в текст статьи.

    Если DPG отдаёт позицию курсора — вставляем туда, иначе в конец.
    Пустая строка перед маркером (для картинок и кодовых блоков)
    добавляется только когда вставка идёт в конец.
    """
    if not dpg.does_item_exist("doc_edit_content"):
        return

    content = dpg.get_value("doc_edit_content") or ""
    cursor = _get_text_cursor_pos("doc_edit_content")

    if cursor is not None and 0 <= cursor <= len(content):
        prefix = ""
        if blank_line_before and cursor > 0 and content[cursor - 1] != "\n":
            prefix = "\n"
        insert = prefix + text
        new_content = content[:cursor] + insert + content[cursor:]
        dpg.set_value("doc_edit_content", new_content)
        _set_text_cursor_pos("doc_edit_content", cursor + len(insert))
        print(f"[Documentation] inserted tag at cursor {cursor}")
        return

    # Fallback — вставка в конец
    if content:
        if not content.endswith("\n"):
            content += "\n"
        if blank_line_before and not content.endswith("\n\n"):
            content += "\n"
    content += text
    if not content.endswith("\n"):
        content += "\n"
    dpg.set_value("doc_edit_content", content)
    print("[Documentation] inserted tag at end (no cursor API)")


def _insert_image_tag():
    ph = ""
    if dpg.does_item_exist("doc_img_placeholder"):
        ph = (dpg.get_value("doc_img_placeholder") or "").strip()
    if not ph:
        _show_error(
            "Укажите плейсхолдер изображения в поле рядом с "
            "кнопкой загрузки или выберите существующее имя."
        )
        return
    if not re.match(r"^[\w\-.]+$", ph):
        _show_error(
            "Плейсхолдер может содержать только латинские буквы, цифры, "
            "дефис, подчеркивание и точку."
        )
        return
    _insert_tag(f"[[img:{ph}]]", blank_line_before=True)


# ---------------------------------------------------------------------------
# Таблица изображений
# ---------------------------------------------------------------------------
def _refresh_image_table(doc):
    if not dpg.does_item_exist("doc_img_table"):
        return
    for c in dpg.get_item_children("doc_img_table", 1) or []:
        dpg.delete_item(c)

    if not doc:
        with dpg.table_row(parent="doc_img_table"):
            dpg.add_text("(статья не сохранена)")
            dpg.add_text("")
            dpg.add_text("")
            dpg.add_text("")
        return

    try:
        imgs = doc_db.list_images(doc["ID"])
    except Exception:
        imgs = []

    if not imgs:
        with dpg.table_row(parent="doc_img_table"):
            dpg.add_text("(нет изображений)")
            dpg.add_text("")
            dpg.add_text("")
            dpg.add_text("")
        return

    for img in imgs:
        ph = img.get("Placeholder") or ""
        with dpg.table_row(parent="doc_img_table"):
            dpg.add_text(ph)
            dpg.add_text(img.get("MimeType") or "")
            dpg.add_text(str(img.get("size") or 0))
            dpg.add_button(
                label="Удалить", width=-1,
                callback=_on_delete_image_row,
                user_data=ph,
            )


def _on_delete_image_row(sender, app_data, user_data):
    ph = user_data
    if not ph:
        return
    if not _editing_doc_id:
        _show_error("Статья не сохранена - изображений нет")
        return
    try:
        doc_db.delete_image(_editing_doc_id, ph)
    except Exception as e:
        _show_error("Не удалось удалить изображение", e)
        return
    _invalidate_textures(_editing_doc_id)
    _refresh_image_table(doc_db.get_doc(_editing_doc_id))
    print(f"[Documentation] deleted image '{ph}' "
          f"from doc {_editing_doc_id}")


def _on_delete_image():
    ph = ""
    if dpg.does_item_exist("doc_img_placeholder"):
        ph = (dpg.get_value("doc_img_placeholder") or "").strip()
    if not ph:
        _show_error(
            "Введите плейсхолдер изображения для удаления. "
            "Имя можно подсмотреть в таблице ниже."
        )
        return
    if not _editing_doc_id:
        _show_error("Статья не сохранена - изображений нет")
        return
    try:
        doc_db.delete_image(_editing_doc_id, ph)
    except Exception as e:
        _show_error("Не удалось удалить изображение", e)
        return
    _invalidate_textures(_editing_doc_id)
    _refresh_image_table(doc_db.get_doc(_editing_doc_id))
    print(f"[Documentation] deleted image '{ph}' "
          f"from doc {_editing_doc_id}")


# ---------------------------------------------------------------------------
# Сохранение и удаление статьи
# ---------------------------------------------------------------------------
def _save_doc(silent: bool = False) -> bool:
    global _editing_doc_id, _current_doc_id

    if not dpg.does_item_exist("doc_edit_slug"):
        return False

    slug    = (dpg.get_value("doc_edit_slug") or "").strip()
    section = (dpg.get_value("doc_edit_section") or "").strip() or "Общее"
    title   = (dpg.get_value("doc_edit_title") or "").strip()
    content = dpg.get_value("doc_edit_content") or ""
    sort    = dpg.get_value("doc_edit_sort") or 0

    if not slug:
        if not silent:
            _show_error("Укажите Slug - уникальный идентификатор статьи")
        return False
    if not title:
        if not silent:
            _show_error("Укажите заголовок")
        return False

    try:
        new_id = doc_db.upsert_doc(slug, section, title, content,
                                   sort_order=int(sort),
                                   user=_get_login_user())
    except Exception as e:
        _show_error("Ошибка сохранения статьи", e)
        return False

    if new_id is None:
        _show_error("Не удалось получить ID статьи")
        return False

    _editing_doc_id = new_id
    _current_doc_id = new_id

    try:
        dpg.configure_item("doc_edit_slug", enabled=False)
    except Exception:
        pass

    if silent:
        try:
            _rebuild_tree()
        except Exception:
            pass
    else:
        try:
            dpg.delete_item(WIN_DOC_EDIT_TAG)
        except Exception:
            pass
        _invalidate_textures(new_id)
        _rebuild_tree()
        _on_select(new_id)

    return True


def _on_cancel_edit():
    global _editing_doc_id
    _editing_doc_id = None
    try:
        _rebuild_tree()
    except Exception:
        pass
    if dpg.does_item_exist(WIN_DOC_EDIT_TAG):
        try:
            dpg.delete_item(WIN_DOC_EDIT_TAG)
        except Exception:
            pass


def _on_delete_doc():
    global _editing_doc_id, _current_doc_id
    if not _editing_doc_id:
        return
    doc_id = _editing_doc_id
    doc_db.delete_doc(doc_id)
    _invalidate_textures(doc_id)
    _editing_doc_id = None
    _current_doc_id = None

    if dpg.does_item_exist(WIN_DOC_EDIT_TAG):
        dpg.delete_item(WIN_DOC_EDIT_TAG)
    _rebuild_tree()


def _ensure_edit_doc_saved():
    if _editing_doc_id:
        return _editing_doc_id

    try:
        slug = (dpg.get_value("doc_edit_slug") or "").strip()
        title = (dpg.get_value("doc_edit_title") or "").strip()
    except Exception:
        slug, title = "", ""

    if not slug or not title:
        _show_error(
            "Перед загрузкой изображения заполните поля "
            "Slug и Заголовок и нажмите Сохранить."
        )
        return None

    if not _save_doc(silent=True):
        return None

    if not _editing_doc_id:
        _show_error("Не удалось получить ID статьи после сохранения")
        return None

    try:
        if dpg.does_item_exist(TAG_DOC_STATUS):
            dpg.set_value(TAG_DOC_STATUS, f"Статья сохранена: {slug}")
    except Exception:
        pass

    return _editing_doc_id


# ---------------------------------------------------------------------------
# Генерация плейсхолдера с защитой от перезаписи
# ---------------------------------------------------------------------------
def _make_unique_placeholder(doc_id: int, base: str) -> str:
    """Если base уже занят, добавлять _2, _3 и т.д."""
    ph = base or "image"
    if not doc_db.get_image(doc_id, ph):
        return ph
    n = 1
    while True:
        n += 1
        candidate = f"{base}_{n}"
        if not doc_db.get_image(doc_id, candidate):
            return candidate


# ---------------------------------------------------------------------------
# Загрузка изображений
# ---------------------------------------------------------------------------
def _open_file_dialog(sender=None, app_data=None, user_data=None):
    print("[Documentation] _open_file_dialog called")
    if not dpg.does_item_exist("doc_file_dialog"):
        with dpg.file_dialog(
            directory_selector=False, show=False,
            callback=_on_file_selected, tag="doc_file_dialog",
            width=720, height=500, modal=True,
            default_filename="",
        ):
            dpg.add_file_extension(".png",  custom_text="PNG (*.png)")
            dpg.add_file_extension(".PNG",  custom_text="PNG (*.PNG)")
            dpg.add_file_extension(".jpg",  custom_text="JPG (*.jpg)")
            dpg.add_file_extension(".JPG",  custom_text="JPG (*.JPG)")
            dpg.add_file_extension(".jpeg", custom_text="JPEG (*.jpeg)")
            dpg.add_file_extension(".JPEG", custom_text="JPEG (*.JPEG)")
            dpg.add_file_extension(".bmp",  custom_text="BMP (*.bmp)")
            dpg.add_file_extension(".BMP",  custom_text="BMP (*.BMP)")
            dpg.add_file_extension(".*",    custom_text="Все файлы (*.*)")
    try:
        dpg.configure_item("doc_file_dialog", show=True)
    except Exception:
        try:
            dpg.show_item("doc_file_dialog")
        except Exception as e:
            _show_error("Не удалось открыть диалог выбора файла", e)


def _on_file_selected(sender, app_data, user_data=None):
    print(f"[Documentation] _on_file_selected, app_data={app_data!r}")

    paths = _extract_paths_from_appdata(app_data)
    print(f"[Documentation] extracted paths = {paths!r}")

    if not paths:
        print("[Documentation] empty selection - cancel")
        return

    if len(paths) > 1:
        _show_error(
            f"Выбрано файлов: {len(paths)}. "
            "Будет загружен только первый."
        )

    path = paths[0]
    print(f"[Documentation] using path = {path!r}")

    if not os.path.isfile(path):
        _show_error(f"Файл не найден:\n{path}")
        return

    if not _is_allowed_image(path):
        _show_error(
            "Поддерживаются только изображения PNG, JPG, JPEG, BMP.\n"
            f"Выбранный файл: {os.path.basename(path)}"
        )
        return

    doc_id = _ensure_edit_doc_saved()
    if not doc_id:
        return

    # Плейсхолдер: ручной, если введён, иначе из имени файла.
    # После успешной загрузки — автогенерация с суффиксом, чтобы
    # не перезаписать существующее изображение.
    manual_ph = ""
    if dpg.does_item_exist("doc_img_placeholder"):
        manual_ph = (dpg.get_value("doc_img_placeholder") or "").strip()

    if manual_ph:
        if not re.match(r"^[\w\-.]+$", manual_ph):
            _show_error(
                "Плейсхолдер может содержать только латинские буквы, "
                "цифры, дефис, подчеркивание и точку."
            )
            return
        # Пользователь задал имя осознанно — используем как есть,
        # даже если оно занято (замена с его согласия).
        ph = manual_ph
    else:
        base = os.path.splitext(os.path.basename(path))[0]
        base = re.sub(r"[^\w\-.]", "_", base) or "image"
        ph = _make_unique_placeholder(doc_id, base)
        print(f"[Documentation] auto placeholder: {ph}")

    try:
        with open(path, "rb") as f:
            blob = f.read()
    except OSError as e:
        _show_error("Не удалось прочитать файл", e)
        return

    if not blob:
        _show_error("Файл пустой")
        return

    ext = os.path.splitext(path)[1].lower()
    mime = {"jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "bmp": "image/bmp"}.get(ext.lstrip("."), "image/png")

    existed_before = bool(doc_db.get_image(doc_id, ph))

    try:
        doc_db.save_image(doc_id, ph, blob, mime=mime)
    except Exception as e:
        _show_error("Не удалось сохранить изображение в БД", e)
        return

    try:
        dpg.configure_item("doc_file_dialog", show=False)
    except Exception:
        pass

    _invalidate_textures(doc_id)
    _refresh_image_table(doc_db.get_doc(doc_id))

    # Маркер в текст
    try:
        content = dpg.get_value("doc_edit_content") or ""
        marker = f"[[img:{ph}]]"
        if marker not in content:
            content = content.rstrip() + "\n\n" + marker + "\n"
            dpg.set_value("doc_edit_content", content)
        _save_doc(silent=True)
    except Exception as e:
        print(f"[Documentation] marker insert error: {e}")

    # Очищаем поле, чтобы следующая загрузка шла со свежим именем
    try:
        dpg.set_value("doc_img_placeholder", "")
    except Exception:
        pass

    verb = "обновлено" if existed_before else "загружено"
    print(f"[Documentation] image '{ph}' {verb} for doc {doc_id}, "
          f"{len(blob)} bytes")
    _show_info(
        f"Изображение {verb}.\n"
        f"Плейсхолдер: {ph}\n"
        f"Размер: {len(blob)} байт\n"
        f"Тег вставлен в текст статьи."
    )


# ---------------------------------------------------------------------------
# Публичный API
# ---------------------------------------------------------------------------
def _register_in_window_manager():
    try:
        from window_manager import register, rebuild_menu
    except Exception:
        return
    try:
        register(WIN_DOC_TAG, "Документация", _create_main_window)
        rebuild_menu()
    except Exception as e:
        print(f"[Documentation] register error: {e}")


def create_documentation_window():
    """Открыть (или показать) окно документации."""
    try:
        doc_db.ensure_tables()
        seed_all()
        seed_assistant_docs()
        seed_phasenoise_docs()
    except Exception as e:
        print(f"[Documentation] init error: {e}")

    _create_main_window()
    _register_in_window_manager()