import json
import sqlite3
import threading
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tracking_number TEXT NOT NULL,
    image_id TEXT,
    payload TEXT NOT NULL,
    created_at REAL NOT NULL
);
"""


class Outbox:
    def __init__(self, path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._migrate()
        self._db.commit()

    def _migrate(self):
        columns = {row[1] for row in self._db.execute("PRAGMA table_info(outbox)")}
        if "image_id" not in columns:
            self._db.execute("ALTER TABLE outbox ADD COLUMN image_id TEXT")
            self._db.execute("UPDATE outbox SET image_id = json_extract(payload, '$.image_id')")
        self._db.execute("CREATE INDEX IF NOT EXISTS idx_outbox_image_id ON outbox (image_id)")

    def add(self, tracking_number, image_id, payload):
        with self._lock:
            self._db.execute(
                "INSERT INTO outbox (tracking_number, image_id, payload, created_at) VALUES (?, ?, ?, ?)",
                (tracking_number, image_id, json.dumps(payload, ensure_ascii=False), time.time()),
            )
            self._db.commit()

    def pending(self, limit=100):
        with self._lock:
            rows = self._db.execute(
                "SELECT payload FROM outbox ORDER BY id LIMIT ?", (limit,)
            ).fetchall()
        return [json.loads(payload) for (payload,) in rows]

    def acknowledge(self, image_id):
        with self._lock:
            self._db.execute("DELETE FROM outbox WHERE image_id = ?", (image_id,))
            self._db.commit()

    def count(self):
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM outbox").fetchone()[0]

    def close(self):
        with self._lock:
            self._db.close()
