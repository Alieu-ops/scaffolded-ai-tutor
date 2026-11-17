"""
SQLite connection and migrations.

Why SQLite: a single file, built into Python, with transactions and foreign
keys. Enough for a laptop or small campus pilot; a later move to PostgreSQL
would replace this module and the repositories, not the domain rules.

Migrations: every file in storage/migrations/ named NNN_description.sql is
applied once, in order, inside a transaction, and recorded in the
schema_migrations table. Running migrate() again is safe (it skips applied ones).
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def utc_now() -> str:
    """Timestamps are stored in UTC ISO format so laptops in different places agree."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Database:
    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        # One shared connection; check_same_thread=False because Streamlit may
        # call from different threads. Writes go through transaction() below.
        self.connection = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")
        if self.path != ":memory:":
            self.connection.execute("PRAGMA journal_mode = WAL")   # readers do not block the writer
        self.connection.execute("PRAGMA busy_timeout = 5000")
        # Streamlit serves each browser session from its own thread, all sharing this
        # connection. The lock makes transactions take turns instead of interleaving.
        self._lock = threading.RLock()

    @contextmanager
    def transaction(self):
        """All statements inside commit together, or none do (rollback on any error)."""
        with self._lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                yield self.connection
            except BaseException:
                self.connection.execute("ROLLBACK")
                raise
            else:
                self.connection.execute("COMMIT")

    def query(self, sql: str, params: tuple | dict = ()) -> list[sqlite3.Row]:
        with self._lock:
            return self.connection.execute(sql, params).fetchall()

    def query_one(self, sql: str, params: tuple | dict = ()) -> sqlite3.Row | None:
        with self._lock:
            return self.connection.execute(sql, params).fetchone()

    # -
    def applied_migrations(self) -> set[str]:
        self.connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL)")
        return {row["version"] for row in self.query("SELECT version FROM schema_migrations")}

    def migrate(self) -> list[str]:
        """Apply any migrations not yet recorded. Returns the versions applied now."""
        done = self.applied_migrations()
        applied_now = []
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem.split("_", 1)[0]
            if version in done:
                continue
            statements = [s.strip() for s in _split_sql(path.read_text(encoding="utf-8")) if s.strip()]
            with self.transaction() as conn:
                for statement in statements:
                    conn.execute(statement)
                conn.execute("INSERT INTO schema_migrations VALUES (?, ?)", (version, utc_now()))
            applied_now.append(version)
        return applied_now


def _split_sql(script: str) -> list[str]:
    """Split a migration file into statements, ignoring '--' comment lines."""
    lines = [line for line in script.splitlines() if not line.strip().startswith("--")]
    return "\n".join(lines).split(";")


def open_database(path: str | Path) -> Database:
    """Open (creating if needed) and migrate the database."""
    db = Database(path)
    db.migrate()
    return db
