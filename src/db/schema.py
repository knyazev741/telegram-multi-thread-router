"""Database schema and initialization."""

import logging
from pathlib import Path

import aiosqlite

logger = logging.getLogger(__name__)

DB_PATH = Path("data/bot.db")

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS topics (
    thread_id   INTEGER PRIMARY KEY,
    name        TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id   INTEGER NOT NULL REFERENCES topics(thread_id),
    session_id  TEXT,
    workdir     TEXT    NOT NULL,
    server      TEXT    NOT NULL DEFAULT 'local',
    state       TEXT    NOT NULL DEFAULT 'idle',
    created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
    updated_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS message_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id   INTEGER NOT NULL REFERENCES topics(thread_id),
    role        TEXT    NOT NULL,
    content     TEXT    NOT NULL,
    created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);
"""


async def init_db(db_path: Path | None = None) -> None:
    """Initialize database: set WAL mode, create schema.

    WAL mode is set FIRST before any schema creation (see Research pitfall #4).
    WAL persists across connections once set.

    Args:
        db_path: Override for testing. Defaults to DB_PATH.
    """
    path = db_path or DB_PATH

    # Ensure parent directory exists
    path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(str(path)) as conn:
        # WAL mode FIRST — before schema creation
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()

    logger.info("Database initialized at %s (WAL mode)", path)
