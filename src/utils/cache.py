"""Lightweight thread-safe SQLite cache with TTL for public API responses."""
from __future__ import annotations

import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

DEFAULT_CACHE_PATH = Path(__file__).resolve().parents[2] / ".cache" / "api_cache.sqlite"
TTL_LITERATURE_SECONDS = 24 * 60 * 60      # 24 hours
TTL_ENTITY_SECONDS = 7 * 24 * 60 * 60      # 7 days
CACHEABLE_STATUSES = {"ok", "empty", "truncated"}


class SQLiteCache:
    """Persistent SQLite key-value cache with per-entry TTL."""

    @staticmethod
    def _open_connection(target: str) -> sqlite3.Connection:
        conn = sqlite3.connect(target, check_same_thread=False)
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS api_cache (
                cache_key TEXT PRIMARY KEY,
                payload TEXT NOT NULL,
                expires_at REAL NOT NULL
            )
            """
        )
        conn.commit()
        return conn

    def __init__(self, db_path: str | Path = DEFAULT_CACHE_PATH):
        self._lock = threading.Lock()
        if str(db_path) == ":memory:":
            self.db_path = Path(":memory:")
            self._conn = self._open_connection(":memory:")
            return

        requested = Path(db_path)
        fallback_path = (
            Path(tempfile.gettempdir()) / "chemistry_discovery_hub_cache" / "api_cache.sqlite"
        )
        candidates = [requested] if requested == fallback_path else [requested, fallback_path]
        for candidate in candidates:
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                self._conn = self._open_connection(str(candidate))
                self.db_path = candidate
                return
            except (OSError, sqlite3.OperationalError):
                continue

        self.db_path = Path(":memory:")
        self._conn = self._open_connection(":memory:")

    def get(self, key: str) -> Any | None:
        """Return cached payload if present and unexpired, else None."""
        now = time.time()
        with self._lock:
            row = self._conn.execute(
                "SELECT payload, expires_at FROM api_cache WHERE cache_key = ?",
                (key,),
            ).fetchone()
            if row is None:
                return None
            payload_str, expires_at = row
            if expires_at <= now:
                self._conn.execute(
                    "DELETE FROM api_cache WHERE cache_key = ?", (key,)
                )
                self._conn.commit()
                return None
            try:
                return json.loads(payload_str)
            except json.JSONDecodeError:
                return None

    def set(self, key: str, value: Any, ttl_seconds: int = TTL_LITERATURE_SECONDS) -> None:
        """Store JSON-serializable payload with TTL."""
        expires_at = time.time() + max(1, int(ttl_seconds))
        payload_str = json.dumps(value, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO api_cache (cache_key, payload, expires_at)
                VALUES (?, ?, ?)
                """,
                (key, payload_str, expires_at),
            )
            self._conn.commit()

    def clear(self) -> int:
        """Delete all entries and return deleted row count."""
        with self._lock:
            cur = self._conn.execute("DELETE FROM api_cache")
            self._conn.commit()
            return cur.rowcount or 0

    def count(self) -> int:
        """Return number of unexpired entries currently stored."""
        now = time.time()
        with self._lock:
            self._conn.execute("DELETE FROM api_cache WHERE expires_at <= ?", (now,))
            self._conn.commit()
            row = self._conn.execute("SELECT COUNT(*) FROM api_cache").fetchone()
            return int(row[0]) if row else 0
