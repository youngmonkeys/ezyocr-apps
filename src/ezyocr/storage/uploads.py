import sqlite3
import threading
import time
from dataclasses import dataclass

SCHEMA = """
CREATE TABLE IF NOT EXISTS uploads (
    image_id TEXT PRIMARY KEY,
    file_path TEXT NOT NULL,
    delivery_order_code TEXT,
    media_id INTEGER,
    attempts INTEGER NOT NULL DEFAULT 0,
    next_attempt_at REAL NOT NULL DEFAULT 0,
    created_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_uploads_next_attempt_at ON uploads (next_attempt_at);
"""


@dataclass(frozen=True)
class UploadJob:
    image_id: str
    file_path: str
    delivery_order_code: str | None
    media_id: int | None
    attempts: int


class UploadQueue:
    def __init__(self, path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path), check_same_thread=False)
        self._db.executescript(SCHEMA)
        self._db.commit()

    def add(self, image_id, file_path, ready_after_seconds):
        now = time.time()
        with self._lock:
            self._db.execute(
                "INSERT OR IGNORE INTO uploads (image_id, file_path, next_attempt_at, created_at) VALUES (?, ?, ?, ?)",
                (image_id, file_path, now + ready_after_seconds, now),
            )
            self._db.commit()

    def mark_ready(self, image_id):
        self._execute("UPDATE uploads SET next_attempt_at = 0 WHERE image_id = ?", (image_id,))

    def set_delivery_order_code(self, image_id, delivery_order_code):
        self._execute(
            "UPDATE uploads SET delivery_order_code = ?, attempts = 0, next_attempt_at = 0 WHERE image_id = ?",
            (delivery_order_code, image_id),
        )

    def set_media_id(self, image_id, media_id):
        self._execute(
            "UPDATE uploads SET media_id = ?, attempts = 0, next_attempt_at = 0 WHERE image_id = ?",
            (media_id, image_id),
        )

    def retry_later(self, image_id, delay_seconds):
        self._execute(
            "UPDATE uploads SET attempts = attempts + 1, next_attempt_at = ? WHERE image_id = ?",
            (time.time() + delay_seconds, image_id),
        )

    def next_due(self):
        with self._lock:
            row = self._db.execute(
                "SELECT image_id, file_path, delivery_order_code, media_id, attempts FROM uploads "
                "WHERE next_attempt_at <= ? AND (media_id IS NULL OR delivery_order_code IS NOT NULL) "
                "ORDER BY next_attempt_at, created_at LIMIT 1",
                (time.time(),),
            ).fetchone()
        return UploadJob(*row) if row else None

    def get(self, image_id):
        with self._lock:
            row = self._db.execute(
                "SELECT image_id, file_path, delivery_order_code, media_id, attempts FROM uploads WHERE image_id = ?",
                (image_id,),
            ).fetchone()
        return UploadJob(*row) if row else None

    def remove(self, image_id):
        self._execute("DELETE FROM uploads WHERE image_id = ?", (image_id,))

    def file_paths(self):
        with self._lock:
            return {row[0] for row in self._db.execute("SELECT file_path FROM uploads")}

    def count(self):
        with self._lock:
            return self._db.execute("SELECT COUNT(*) FROM uploads").fetchone()[0]

    def close(self):
        with self._lock:
            self._db.close()

    def _execute(self, sql, params):
        with self._lock:
            self._db.execute(sql, params)
            self._db.commit()
