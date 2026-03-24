"""Async database connection helper."""

from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncIterator

import aiosqlite

from src.db.schema import DB_PATH


@asynccontextmanager
async def get_connection(db_path: Path | None = None) -> AsyncIterator[aiosqlite.Connection]:
    """Yield an aiosqlite connection with per-connection PRAGMAs set.

    Sets foreign_keys=ON and synchronous=NORMAL on every connection.
    WAL mode is already persistent from init_db() — no need to re-set.

    Args:
        db_path: Override for testing. Defaults to DB_PATH.
    """
    path = db_path or DB_PATH
    async with aiosqlite.connect(str(path)) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        yield conn
