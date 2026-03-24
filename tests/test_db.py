"""Tests for database schema, WAL mode, and connection helper."""

import pytest
from pathlib import Path

import aiosqlite

from src.db.schema import init_db
from src.db.connection import get_connection


@pytest.fixture
async def tmp_db(tmp_path):
    """Create a temporary database and initialize it."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    return db_path


async def test_wal_mode_enabled(tmp_db):
    """FOUND-03: WAL journal mode is set after init_db()."""
    async with aiosqlite.connect(str(tmp_db)) as conn:
        cursor = await conn.execute("PRAGMA journal_mode;")
        row = await cursor.fetchone()
        assert row[0] == "wal"


async def test_topics_table_exists(tmp_db):
    """FOUND-03: topics table has correct columns."""
    async with aiosqlite.connect(str(tmp_db)) as conn:
        cursor = await conn.execute("PRAGMA table_info(topics);")
        columns = {row[1] for row in await cursor.fetchall()}
        assert columns == {"thread_id", "name", "created_at"}


async def test_sessions_table_exists(tmp_db):
    """FOUND-03: sessions table has correct columns."""
    async with aiosqlite.connect(str(tmp_db)) as conn:
        cursor = await conn.execute("PRAGMA table_info(sessions);")
        columns = {row[1] for row in await cursor.fetchall()}
        assert columns == {"id", "thread_id", "session_id", "workdir", "server", "state", "created_at", "updated_at", "model"}


async def test_message_history_table_exists(tmp_db):
    """FOUND-03: message_history table has correct columns."""
    async with aiosqlite.connect(str(tmp_db)) as conn:
        cursor = await conn.execute("PRAGMA table_info(message_history);")
        columns = {row[1] for row in await cursor.fetchall()}
        assert columns == {"id", "thread_id", "role", "content", "created_at"}


async def test_get_connection_has_foreign_keys(tmp_db):
    """get_connection() enables foreign_keys pragma."""
    async with get_connection(tmp_db) as conn:
        cursor = await conn.execute("PRAGMA foreign_keys;")
        row = await cursor.fetchone()
        assert row[0] == 1


async def test_init_db_idempotent(tmp_db):
    """Calling init_db() twice does not raise."""
    await init_db(tmp_db)  # second call
    async with aiosqlite.connect(str(tmp_db)) as conn:
        cursor = await conn.execute("SELECT count(*) FROM sqlite_master WHERE type='table';")
        row = await cursor.fetchone()
        assert row[0] >= 3  # topics, sessions, message_history


async def test_foreign_key_constraint(tmp_db):
    """Foreign key from sessions -> topics is enforced."""
    async with get_connection(tmp_db) as conn:
        with pytest.raises(aiosqlite.IntegrityError):
            await conn.execute(
                "INSERT INTO sessions (thread_id, workdir) VALUES (?, ?)",
                (999999, "/tmp"),
            )
            await conn.commit()
