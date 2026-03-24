"""Named SQL query functions for session and topic CRUD."""

from src.db.connection import get_connection


async def insert_topic(thread_id: int, name: str) -> None:
    """Insert a new topic record."""
    async with get_connection() as conn:
        await conn.execute(
            "INSERT INTO topics (thread_id, name) VALUES (?, ?)",
            (thread_id, name),
        )
        await conn.commit()


async def insert_session(thread_id: int, workdir: str, model: str | None = None) -> None:
    """Insert a new session record with state='idle'."""
    async with get_connection() as conn:
        await conn.execute(
            "INSERT INTO sessions (thread_id, workdir, model, state) VALUES (?, ?, ?, 'idle')",
            (thread_id, workdir, model),
        )
        await conn.commit()


async def update_session_id(thread_id: int, session_id: str) -> None:
    """Update the Claude session_id for a thread after first ResultMessage."""
    async with get_connection() as conn:
        await conn.execute(
            "UPDATE sessions SET session_id=?, updated_at=datetime('now') WHERE thread_id=?",
            (session_id, thread_id),
        )
        await conn.commit()


async def update_session_state(thread_id: int, state: str) -> None:
    """Update the state of the most recent session for a thread."""
    async with get_connection() as conn:
        await conn.execute(
            "UPDATE sessions SET state=?, updated_at=datetime('now') WHERE thread_id=?",
            (state, thread_id),
        )
        await conn.commit()


async def get_resumable_sessions() -> list[dict]:
    """Return all sessions that were running or idle and have a session_id (resumable on startup)."""
    async with get_connection() as conn:
        cursor = await conn.execute(
            "SELECT thread_id, session_id, workdir, model, state FROM sessions "
            "WHERE state IN ('running', 'idle') AND session_id IS NOT NULL"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_session_by_thread(thread_id: int) -> dict | None:
    """Return the most recent session row for a thread, or None."""
    async with get_connection() as conn:
        cursor = await conn.execute(
            "SELECT * FROM sessions WHERE thread_id=? ORDER BY id DESC LIMIT 1",
            (thread_id,),
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_all_active_sessions() -> list[dict]:
    """Return all sessions in idle or running state, joined with topic name."""
    async with get_connection() as conn:
        cursor = await conn.execute(
            "SELECT s.*, t.name FROM sessions s "
            "JOIN topics t ON s.thread_id=t.thread_id "
            "WHERE s.state IN ('idle', 'running')"
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
