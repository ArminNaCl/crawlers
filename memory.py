import logging
import sqlite3
from pathlib import Path

DEFAULT_DB = Path.home() / ".cache" / "product_exporter" / "memory.db"

log = logging.getLogger(__name__)


class ExportMemory:
    """SQLite-backed store of already-exported product IDs, scoped per vendor.

    The PRIMARY KEY is (source_site, vendor_id, source_id) so that products
    from different vendors are independent: the same product exported from
    vendor A will NOT be skipped when crawling vendor B. Re-running the same
    URL after a cancel will correctly skip the already-exported products and
    export the remaining ones.
    """

    def __init__(self, db_path=None):
        path = Path(db_path) if db_path else DEFAULT_DB
        path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path))
        self._init_schema()

    def _init_schema(self):
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS exported_products (
                source_site  TEXT NOT NULL,
                vendor_id    TEXT NOT NULL DEFAULT '',
                source_id    TEXT NOT NULL,
                exported_at  TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (source_site, vendor_id, source_id)
            )
        """)
        self._conn.commit()
        self._maybe_migrate()

    def _maybe_migrate(self):
        """Migrate from the old (source_site, source_id) schema to the vendor-scoped one."""
        cur = self._conn.execute("PRAGMA table_info(exported_products)")
        pk_cols = {row[1] for row in cur.fetchall() if row[5] > 0}
        if "vendor_id" in pk_cols:
            return  # already on new schema

        log.info("Migrating memory DB to vendor-scoped schema …")
        self._conn.execute("ALTER TABLE exported_products RENAME TO _exported_products_old")
        self._conn.execute("""
            CREATE TABLE exported_products (
                source_site  TEXT NOT NULL,
                vendor_id    TEXT NOT NULL DEFAULT '',
                source_id    TEXT NOT NULL,
                exported_at  TEXT NOT NULL DEFAULT (datetime('now')),
                PRIMARY KEY (source_site, vendor_id, source_id)
            )
        """)
        self._conn.execute("""
            INSERT OR IGNORE INTO exported_products (source_site, vendor_id, source_id, exported_at)
            SELECT source_site, COALESCE(vendor_id, ''), source_id, exported_at
            FROM _exported_products_old
        """)
        self._conn.execute("DROP TABLE _exported_products_old")
        self._conn.commit()
        log.info("Memory DB migration complete.")

    def is_exported(self, source_site: str, source_id: str, vendor_id: str = "") -> bool:
        cur = self._conn.execute(
            "SELECT 1 FROM exported_products "
            "WHERE source_site=? AND vendor_id=? AND source_id=?",
            (source_site, vendor_id, source_id),
        )
        return cur.fetchone() is not None

    def mark_exported(self, source_site: str, source_id: str, vendor_id: str = ""):
        self._conn.execute(
            "INSERT OR IGNORE INTO exported_products (source_site, vendor_id, source_id) "
            "VALUES (?, ?, ?)",
            (source_site, vendor_id, source_id),
        )
        self._conn.commit()

    def close(self):
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
