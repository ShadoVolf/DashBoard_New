"""
Работа с таблицами документации в БД.

Таблицы:
    * documentation       — статьи справки (Slug, Section, Title, Content…)
    * documentation_image — картинки к статьям (Placeholder + LONGBLOB)
"""
from ResonatorGraph import db
from ResonatorGraph.db import execute_raw

_tables_ready = False


def ensure_tables():
    """Создать таблицы документации при первом обращении."""
    global _tables_ready
    if _tables_ready:
        return

    ddl_docs = (
        "CREATE TABLE IF NOT EXISTS `documentation` ("
        "`ID` INT UNSIGNED NOT NULL AUTO_INCREMENT,"
        "`Section` VARCHAR(100) NOT NULL DEFAULT 'Общее',"
        "`Title` VARCHAR(255) NOT NULL,"
        "`Slug` VARCHAR(150) NOT NULL,"
        "`Content` MEDIUMTEXT,"
        "`SortOrder` INT NOT NULL DEFAULT 0,"
        "`CreatedAt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "`UpdatedAt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP "
        "            ON UPDATE CURRENT_TIMESTAMP,"
        "`CreatedBy` VARCHAR(255),"
        "`UpdatedBy` VARCHAR(255),"
        "PRIMARY KEY (`ID`),"
        "UNIQUE KEY `uq_doc_slug` (`Slug`),"
        "KEY `idx_doc_section` (`Section`),"
        "KEY `idx_doc_order` (`SortOrder`)"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )

    ddl_images = (
        "CREATE TABLE IF NOT EXISTS `documentation_image` ("
        "`ID` INT UNSIGNED NOT NULL AUTO_INCREMENT,"
        "`DocID` INT UNSIGNED NOT NULL,"
        "`Placeholder` VARCHAR(100) NOT NULL,"
        "`MimeType` VARCHAR(50) DEFAULT 'image/png',"
        "`Data` LONGBLOB NOT NULL,"
        "`Caption` VARCHAR(255),"
        "`CreatedAt` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,"
        "PRIMARY KEY (`ID`),"
        "UNIQUE KEY `uq_doc_img` (`DocID`, `Placeholder`),"
        "CONSTRAINT `fk_doc_img` FOREIGN KEY (`DocID`) "
        "REFERENCES `documentation` (`ID`) ON DELETE CASCADE"
        ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"
    )

    try:
        execute_raw(ddl_docs, {})
        execute_raw(ddl_images, {})
        _tables_ready = True
    except Exception as e:
        print(f"[Documentation] ensure_tables error: {e}")


# ---------------------------------------------------------------------------
# Статьи
# ---------------------------------------------------------------------------
def list_docs(search: str = "") -> list:
    ensure_tables()
    sql = "SELECT `ID`, `Section`, `Title`, `Slug`, `SortOrder` FROM `documentation`"
    params = {}
    if search:
        sql += (" WHERE `Title` LIKE :q OR `Content` LIKE :q "
                "OR `Section` LIKE :q")
        params["q"] = f"%{search}%"
    sql += " ORDER BY `Section`, `SortOrder`, `Title`"
    try:
        return [dict(r) for r in db.fetchall(sql, **params)]
    except Exception as e:
        print(f"[Documentation] list_docs error: {e}")
        return []


def get_doc(doc_id: int):
    ensure_tables()
    try:
        row = db.fetchone(
            "SELECT * FROM `documentation` WHERE `ID` = :id", id=doc_id
        )
    except Exception as e:
        print(f"[Documentation] get_doc error: {e}")
        return None
    return dict(row) if row else None


def get_doc_by_slug(slug: str):
    ensure_tables()
    try:
        row = db.fetchone(
            "SELECT * FROM `documentation` WHERE `Slug` = :s", s=slug
        )
    except Exception as e:
        print(f"[Documentation] get_doc_by_slug error: {e}")
        return None
    return dict(row) if row else None


def upsert_doc(slug: str, section: str, title: str, content: str,
               sort_order: int = 0, user: str = "unknown"):
    ensure_tables()
    sql = (
        "INSERT INTO `documentation` "
        "(`Slug`, `Section`, `Title`, `Content`, `SortOrder`, "
        " `CreatedBy`, `UpdatedBy`) "
        "VALUES (%(slug)s, %(section)s, %(title)s, %(content)s, "
        "        %(ord)s, %(user)s, %(user)s) "
        "ON DUPLICATE KEY UPDATE "
        "`Section`=VALUES(`Section`), `Title`=VALUES(`Title`), "
        "`Content`=VALUES(`Content`), `SortOrder`=VALUES(`SortOrder`), "
        "`UpdatedBy`=VALUES(`UpdatedBy`)"
    )
    try:
        execute_raw(sql, {
            "slug": slug,
            "section": section or "Общее",
            "title": title or "",
            "content": content or "",
            "ord": int(sort_order or 0),
            "user": user or "unknown",
        })
    except Exception as e:
        print(f"[Documentation] upsert_doc error: {e}")
        raise
    row = get_doc_by_slug(slug)
    return row["ID"] if row else None


def delete_doc(doc_id: int):
    ensure_tables()
    execute_raw("DELETE FROM `documentation` WHERE `ID` = %(id)s",
                {"id": doc_id})


# ---------------------------------------------------------------------------
# Изображения
# ---------------------------------------------------------------------------
def get_image(doc_id: int, placeholder: str):
    ensure_tables()
    try:
        row = db.fetchone(
            "SELECT `Data`, `Caption`, `MimeType` FROM `documentation_image` "
            "WHERE `DocID` = :d AND `Placeholder` = :p",
            d=doc_id, p=placeholder,
        )
    except Exception as e:
        print(f"[Documentation] get_image error: {e}")
        return None
    return dict(row) if row else None


def save_image(doc_id: int, placeholder: str, blob: bytes,
               mime: str = "image/png", caption: str = None):
    ensure_tables()
    execute_raw(
        "INSERT INTO `documentation_image` "
        "(`DocID`, `Placeholder`, `Data`, `MimeType`, `Caption`) "
        "VALUES (%(d)s, %(p)s, %(data)s, %(mime)s, %(cap)s) "
        "ON DUPLICATE KEY UPDATE "
        "`Data`=VALUES(`Data`), `MimeType`=VALUES(`MimeType`), "
        "`Caption`=VALUES(`Caption`)",
        {"d": doc_id, "p": placeholder, "data": blob,
         "mime": mime, "cap": caption},
    )


def list_images(doc_id: int) -> list:
    ensure_tables()
    try:
        rows = db.fetchall(
            "SELECT `Placeholder`, `Caption`, `MimeType`, "
            "       LENGTH(`Data`) AS `size` "
            "FROM `documentation_image` WHERE `DocID` = :d "
            "ORDER BY `Placeholder`",
            d=doc_id,
        )
    except Exception as e:
        print(f"[Documentation] list_images error: {e}")
        return []
    return [dict(r) for r in rows]


def delete_image(doc_id: int, placeholder: str):
    ensure_tables()
    execute_raw(
        "DELETE FROM `documentation_image` "
        "WHERE `DocID` = %(d)s AND `Placeholder` = %(p)s",
        {"d": doc_id, "p": placeholder},
    )