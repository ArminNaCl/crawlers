import sqlite3
from pathlib import Path

DEFAULT_DB = Path.home() / ".cache" / "product_exporter" / "memory.db"


class ExportMemory:
    """SQLite-backed store of already-exported product IDs."""

    def __init__(self, db_path=None):
        path = Path(db_path) if db_path else DEFAULT_DB
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._init_schema()

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS exported_products (
                source_site  TEXT NOT NULL,
                source_id    TEXT NOT NULL,
                vendor_id    TEXT,
                exported_at  TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (source_site, source_id)
            )
        """)
        self._conn.commit()

    def is_exported(self, source_site: str, source_id: str) -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM exported_products WHERE source_site=? AND source_id=?",
            (source_site, source_id),
        )
        return cur.fetchone() is not None

    def mark_exported(self, source_site: str, source_id: str, vendor_id: str = ""):
        self._conn.execute(
            "INSERT OR IGNORE INTO exported_products (source_site, source_id, vendor_id) "
            "VALUES (?, ?, ?)",
            (source_site, source_id, vendor_id),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
