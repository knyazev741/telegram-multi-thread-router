# Phase 1: Foundation - Research

**Researched:** 2026-03-24
**Domain:** aiogram 3 / Python async bot scaffold / SQLite WAL
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
All implementation choices are at Claude's discretion — pure infrastructure phase. Key constraints from research:
- Python 3.11+ with uvloop event loop
- aiogram 3.26+ with Router + middleware pattern
- aiosqlite for async SQLite with WAL mode enabled at init
- Project structure: `src/` package with `bot/`, `db/`, `config.py`
- Delete all old Node.js code (proxy/, plugin/, scripts/, orchestrator/)

### Claude's Discretion
All implementation details — file layout within src/, naming conventions, config loading approach, schema details, test structure.

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| FOUND-01 | Bot starts with aiogram 3 long polling and connects to configured group chat | `dp.start_polling(bot)` pattern; Bot initialized with token from env; Dispatcher.start_polling is async |
| FOUND-02 | Bot only processes messages from OWNER_USER_ID | Outer middleware on `dp.message.outer_middleware(...)` — return without calling handler to silently drop non-owner events |
| FOUND-03 | SQLite database with WAL mode stores topics, sessions, and message history | aiosqlite + `PRAGMA journal_mode=WAL` executed once at startup; three-table schema |
| FOUND-04 | Forum topic routing: messages dispatched by message_thread_id to correct session slot | `F.message_thread_id == thread_id` magic filter; Router-per-topic pattern |
| FOUND-05 | Bot handles General topic (thread_id=1) for management commands | Dedicated Router with `F.message_thread_id == 1` filter; Command handlers registered there |
</phase_requirements>

---

## Summary

Phase 1 is a clean-room Python rewrite of the existing Node.js/grammy codebase. The entire proxy/, plugin/, scripts/, and orchestrator/ tree is deleted. A new Python package is created under `src/` with aiogram 3 providing all Telegram I/O, aiosqlite providing async SQLite access, and uvloop replacing the default asyncio event loop for performance.

aiogram 3 separates routing concerns cleanly: a `Dispatcher` is the root router, sub-Routers handle domain-specific events, and middlewares intercept the event pipeline at two levels (outer = before filters, inner = after filters). Owner auth is best implemented as an outer middleware on the dispatcher so it fires for every incoming event before any routing logic runs. Forum topic routing maps each `message_thread_id` to a router via `F.message_thread_id` magic filters; the General topic (thread_id=1) is a special-case router with command handlers.

SQLite WAL mode is set once at database init via `PRAGMA journal_mode=WAL`. Since WAL mode is persistent across connections, subsequent `aiosqlite.connect()` calls do not need to repeat it, but additional performance PRAGMAs (`synchronous=NORMAL`, `foreign_keys=ON`) should be set on every new connection.

**Primary recommendation:** Use `pydantic-settings` with `BaseSettings` for typed config loading from `.env`; use `aiogram.Router` per concern (general_topic, session_topics); apply owner auth as `dp.message.outer_middleware`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| aiogram | 3.26.0 | Telegram Bot API async framework | Official standard for Python Telegram bots; Router/middleware architecture; full Bot API 7.x support |
| aiosqlite | 0.22.1 | Async SQLite access via asyncio bridge | Single-file DB with async API; no separate server; WAL mode gives concurrent reads |
| uvloop | 0.22.1 | Fast asyncio event loop (libuv) | 2-4x faster than default asyncio loop; Python 3.11+ recommended via asyncio.Runner |
| pydantic-settings | 2.13.1 | Typed config from .env / env vars | Auto type coercion, validation, .env file reading; replaces raw python-dotenv |
| pydantic | 2.12.5 | Data validation (pulled by pydantic-settings) | Type safety for config models |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| python-dotenv | 1.2.2 | .env file loading | Pulled automatically by pydantic-settings; no direct usage needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| pydantic-settings | python-dotenv directly | dotenv has no type validation; pydantic-settings is strictly better for typed config |
| aiosqlite | SQLAlchemy async | SQLAlchemy adds ORM/migration overhead; overkill for simple schema |
| uvloop | default asyncio | Default loop works; uvloop measurably improves throughput for I/O-heavy bots |

**Installation:**
```bash
pip install aiogram==3.26.0 aiosqlite==0.22.1 uvloop==0.22.1 pydantic-settings==2.13.1
```

**Versions verified:** 2026-03-24 via `https://pypi.org/pypi/{package}/json`

---

## Architecture Patterns

### Recommended Project Structure
```
src/
├── __main__.py          # Entry point: asyncio.Runner + uvloop
├── config.py            # pydantic-settings BaseSettings
├── bot/
│   ├── __init__.py
│   ├── dispatcher.py    # Build and configure dp, include all routers
│   ├── middlewares.py   # OwnerAuthMiddleware
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── general.py   # General topic (thread_id=1) — management commands
│   │   └── session.py   # Session topic messages (thread_id != 1)
│   └── filters.py       # Reusable F-based filter helpers (optional)
└── db/
    ├── __init__.py
    ├── connection.py    # get_connection() context manager + WAL init
    └── schema.py        # CREATE TABLE statements + init_db()
pyproject.toml
.env                     # BOT_TOKEN, OWNER_USER_ID, GROUP_CHAT_ID, AUTH_TOKEN
```

### Pattern 1: Owner Auth Outer Middleware

**What:** Intercepts every incoming Message before filters run. If `from_user.id != OWNER_USER_ID`, returns without calling handler — silently drops the event.
**When to use:** Always; registered once on `dp.message` at startup.

```python
# Source: https://docs.aiogram.dev/en/latest/dispatcher/middlewares.html
from typing import Any, Awaitable, Callable
from aiogram import BaseMiddleware
from aiogram.types import Message

class OwnerAuthMiddleware(BaseMiddleware):
    def __init__(self, owner_id: int) -> None:
        self.owner_id = owner_id

    async def __call__(
        self,
        handler: Callable[[Message, dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: dict[str, Any],
    ) -> Any:
        if event.from_user and event.from_user.id == self.owner_id:
            return await handler(event, data)
        # Silent drop — intentionally not calling handler
        return None
```

Registration:
```python
dp.message.outer_middleware(OwnerAuthMiddleware(owner_id=settings.owner_user_id))
```

### Pattern 2: Forum Topic Routing with F Magic Filter

**What:** Each Router is gated with `F.message_thread_id == N`. General topic gets `thread_id == 1`; session topics match dynamically.
**When to use:** Separating General topic management from session message forwarding.

```python
# Source: https://docs.aiogram.dev/en/latest/dispatcher/filters/index.html
from aiogram import Router, F
from aiogram.types import Message

general_router = Router(name="general")

@general_router.message(F.message_thread_id == 1)
async def handle_general(message: Message) -> None:
    await message.reply("General topic handler")

session_router = Router(name="sessions")

@session_router.message(F.message_thread_id != 1, F.is_topic_message == True)
async def handle_session_message(message: Message) -> None:
    thread_id = message.message_thread_id
    # route to session by thread_id
```

### Pattern 3: Bot Startup with uvloop (Python 3.11+)

**What:** Use `asyncio.Runner` with `loop_factory=uvloop.new_event_loop` — the Python 3.11+ idiomatic approach.
**When to use:** Always on Python 3.11+.

```python
# Source: uvloop PyPI README + Python 3.11 asyncio.Runner docs
import asyncio
import uvloop
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

async def main() -> None:
    bot = Bot(
        token=settings.bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = build_dispatcher()
    await dp.start_polling(bot)

if __name__ == "__main__":
    with asyncio.Runner(loop_factory=uvloop.new_event_loop) as runner:
        runner.run(main())
```

### Pattern 4: pydantic-settings Config

**What:** Typed config loaded from `.env` file with automatic validation.
**When to use:** Single `Settings` instance created at import time.

```python
# Source: https://docs.pydantic.dev/latest/concepts/pydantic_settings/
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    bot_token: str
    owner_user_id: int
    group_chat_id: int
    auth_token: str

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

settings = Settings()
```

### Pattern 5: aiosqlite WAL Init and Connection Helper

**What:** One-time schema + WAL setup at startup. Per-connection performance PRAGMAs on every open.
**When to use:** `init_db()` called once in `on_startup`; `get_connection()` used in every handler.

```python
# Source: https://aiosqlite.omnilib.dev/en/stable/api.html
# WAL persistence note: https://www.sqlite.org/wal.html
import aiosqlite
from contextlib import asynccontextmanager

DB_PATH = "data/bot.db"

async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("PRAGMA journal_mode=WAL;")
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.executescript(SCHEMA_SQL)
        await conn.commit()

@asynccontextmanager
async def get_connection():
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA foreign_keys=ON;")
        await conn.execute("PRAGMA synchronous=NORMAL;")
        yield conn
```

### Pattern 6: Dispatcher Assembly with on_startup

**What:** Attach startup hook to call `init_db()` and register all sub-routers.
**When to use:** Standard aiogram 3 composition approach.

```python
# Source: https://docs.aiogram.dev/en/latest/dispatcher/index.html
from aiogram import Dispatcher

def build_dispatcher(settings: Settings) -> Dispatcher:
    dp = Dispatcher()

    dp.message.outer_middleware(OwnerAuthMiddleware(settings.owner_user_id))

    dp.include_router(general_router)
    dp.include_router(session_router)

    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    return dp

async def on_startup() -> None:
    await init_db()

async def on_shutdown() -> None:
    pass  # aiosqlite connections are context-managed; nothing to close globally
```

### Anti-Patterns to Avoid
- **Registering middleware on sub-router instead of dp:** Owner auth must be on `dp.message.outer_middleware`, not on a sub-router, or messages routing to the unmatched sub-router bypass the check.
- **Calling `PRAGMA journal_mode=WAL` on every connection:** WAL is persistent after first set. Re-executing it is harmless but unnecessary noise.
- **Using `uvloop.install()` on Python 3.11+:** Deprecated pattern. Use `asyncio.Runner(loop_factory=uvloop.new_event_loop)` instead.
- **Using `parse_mode` directly on Bot constructor:** Removed in aiogram 3.7+. Use `DefaultBotProperties(parse_mode=...)` exclusively.
- **Importing `settings` inside handler functions:** Create a single module-level `settings = Settings()` and pass via `dp.workflow_data` or module-level import.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| .env parsing and type coercion | Custom os.environ reader | pydantic-settings BaseSettings | Handles missing keys, type casting, validation errors with clear messages |
| Async SQLite connection pooling | Custom connection cache | aiosqlite context manager per operation | aiosqlite uses thread-per-connection model; connection is cheap to open |
| Bot polling loop with signal handling | Manual asyncio signal handlers | `dp.start_polling(bot)` | aiogram handles SIGINT/SIGTERM gracefully, includes allowed_updates optimization |
| Magic filter evaluation | Manual `if message.message_thread_id == X` chains | `F.message_thread_id == X` | Evaluated before handler invocation; composable with other filters |

**Key insight:** aiogram's Router/filter/middleware pipeline replaces all manual dispatch logic. Never implement "if thread_id == X: do Y" branching inside a single handler.

---

## Common Pitfalls

### Pitfall 1: Non-owner messages reaching handlers despite middleware
**What goes wrong:** Messages from non-owner users trigger handlers even with auth middleware registered.
**Why it happens:** Middleware registered on a sub-router only fires when that router's filters already matched. If middleware is on `session_router` instead of `dp`, messages that hit `general_router` bypass the session router's middleware.
**How to avoid:** Always register `OwnerAuthMiddleware` on `dp.message.outer_middleware(...)` — the dispatcher-level observer, not a sub-router observer.
**Warning signs:** Test with a non-owner user ID; if any reply comes back, middleware is in wrong scope.

### Pitfall 2: from_user is None for channel posts
**What goes wrong:** `event.from_user.id` raises `AttributeError` for channel posts or anonymous admin messages.
**Why it happens:** Channel posts have `from_user = None`; anonymous group admin messages may also have it None.
**How to avoid:** Guard with `if event.from_user and event.from_user.id == self.owner_id` in middleware.
**Warning signs:** `AttributeError: 'NoneType' object has no attribute 'id'` in logs.

### Pitfall 3: message_thread_id is None for non-forum messages
**What goes wrong:** `F.message_thread_id == 1` never matches; General topic handler never fires.
**Why it happens:** In a regular group (not a forum/supergroup with topics enabled), `message_thread_id` is always `None`. The group must have "Topics" enabled in Telegram group settings.
**How to avoid:** Ensure test group has Topics enabled. Add `F.message_thread_id.is_not(None)` guard to topic routers. Log `message.message_thread_id` on startup to verify.
**Warning signs:** No handlers fire for any topic message; debug log shows `message_thread_id=None`.

### Pitfall 4: WAL mode not persisting
**What goes wrong:** Database reverts to DELETE journal mode after restart.
**Why it happens:** WAL is persistent once set, but only if the file was created with WAL. If `init_db()` creates the file with `CREATE TABLE` before `PRAGMA journal_mode=WAL`, the mode sets correctly. If you check with a new connection before committing the init transaction, you may see DELETE mode transiently.
**How to avoid:** Execute `PRAGMA journal_mode=WAL` as the first statement in `init_db()`, before schema creation.
**Warning signs:** `PRAGMA journal_mode;` query returns `delete` instead of `wal`.

### Pitfall 5: aiogram handler receives group messages not from configured chat
**What goes wrong:** Bot responds to messages from random groups it was added to.
**Why it happens:** Bot token responds to all updates from any chat it's a member of.
**How to avoid:** Add `F.chat.id == settings.group_chat_id` filter to every router, or add a second check in the outer middleware alongside owner auth.
**Warning signs:** Logs show `chat_id` values that aren't the configured group.

---

## Code Examples

Verified patterns from official sources:

### Bot initialization (aiogram 3.7+)
```python
# Source: https://docs.aiogram.dev/en/latest/api/bot.html
from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

bot = Bot(
    token=settings.bot_token,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML),
)
```

### SQLite schema bootstrap
```python
# WAL note: https://www.sqlite.org/wal.html (WAL persists after first set)
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
```

### F filter combining for chat + topic guard
```python
# Source: https://docs.aiogram.dev/en/latest/dispatcher/filters/index.html
from aiogram import F

# Both conditions must pass (implicit AND)
@router.message(
    F.chat.id == settings.group_chat_id,
    F.message_thread_id == 1,
)
async def general_handler(message: Message) -> None: ...
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `bot = Bot(token=..., parse_mode=...)` | `Bot(token=..., default=DefaultBotProperties(parse_mode=...))` | aiogram 3.7 | Direct parse_mode arg removed; code using old form raises TypeError |
| `uvloop.install(); asyncio.run(main())` | `asyncio.Runner(loop_factory=uvloop.new_event_loop)` | Python 3.11 | Cleaner; no global state mutation |
| `dp.register_message_handler(fn, ...)` | `@router.message(filter)` decorator | aiogram 3.0 | Old aiogram 2.x pattern entirely removed |
| Raw `python-dotenv` + `os.getenv()` | `pydantic-settings BaseSettings` | pydantic v2 era | Type safety, validation, better error messages |

**Deprecated/outdated:**
- `aiogram 2.x` API: Completely different API surface; not compatible with aiogram 3
- `dp.middleware.setup(...)`: Removed in aiogram 3; use `router.<event>.middleware(...)` or `outer_middleware(...)`
- `grammy` (Node.js): Entire existing codebase deleted in Plan 01-01

---

## Open Questions

1. **General topic thread_id value**
   - What we know: Telegram's General topic uses `message_thread_id = 1` by convention per Bot API docs, but some sources say it may be `None` for the main General topic.
   - What's unclear: Whether `F.message_thread_id == 1` or `F.message_thread_id.is_(None)` is the correct filter for the General topic in a supergroup with topics enabled.
   - Recommendation: Log actual `message.message_thread_id` values during Plan 01-02 testing; adjust filter accordingly. Both `1` and `None` should be handled defensively.

2. **Group chat ID filter scope**
   - What we know: Owner auth middleware handles user filtering; group chat filtering is separate.
   - What's unclear: Whether to add `F.chat.id == group_chat_id` to every router or in the middleware.
   - Recommendation: Add it to the middleware alongside owner auth for a single enforcement point.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` [tool.pytest.ini_options] — Wave 0 |
| Quick run command | `pytest tests/ -x -q` |
| Full suite command | `pytest tests/ -v` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| FOUND-01 | Bot connects and enters polling loop | smoke (manual) | manual — requires live token | N/A |
| FOUND-02 | Non-owner messages silently dropped | unit | `pytest tests/test_middleware.py -x` | Wave 0 |
| FOUND-03 | DB file created with WAL mode + correct schema | unit | `pytest tests/test_db.py -x` | Wave 0 |
| FOUND-04 | message_thread_id logged for topic messages | unit | `pytest tests/test_router.py::test_thread_routing -x` | Wave 0 |
| FOUND-05 | General topic command handler responds; other topics don't cross-receive | unit | `pytest tests/test_router.py::test_general_isolation -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/ -x -q`
- **Per wave merge:** `pytest tests/ -v`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/__init__.py` — package marker
- [ ] `tests/conftest.py` — shared fixtures (mock Bot, in-memory DB)
- [ ] `tests/test_middleware.py` — covers FOUND-02
- [ ] `tests/test_db.py` — covers FOUND-03
- [ ] `tests/test_router.py` — covers FOUND-04, FOUND-05
- [ ] Framework install: `pip install pytest pytest-asyncio` — no test infrastructure exists yet

---

## Sources

### Primary (HIGH confidence)
- https://docs.aiogram.dev/en/latest/dispatcher/middlewares.html — outer middleware pattern, BaseMiddleware signature
- https://docs.aiogram.dev/en/latest/dispatcher/filters/index.html — F magic filter, combining filters
- https://docs.aiogram.dev/en/latest/dispatcher/router.html — Router, include_router, event observers
- https://aiosqlite.omnilib.dev/en/stable/api.html — aiosqlite connect, execute, context manager API
- https://docs.pydantic.dev/latest/concepts/pydantic_settings/ — BaseSettings, SettingsConfigDict
- https://pypi.org/pypi/{package}/json — version verification for all 5 packages (2026-03-24)

### Secondary (MEDIUM confidence)
- https://www.sqlite.org/wal.html — WAL persistence behavior, PRAGMA journal_mode
- https://github.com/aiogram/aiogram/blob/dev-3.x/examples/echo_bot.py — Bot init, DefaultBotProperties, dp.start_polling
- https://pypi.org/project/uvloop/ — asyncio.Runner loop_factory pattern for Python 3.11+

### Tertiary (LOW confidence)
- WebSearch results on General topic thread_id value — conflicting; needs live verification

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all versions verified against PyPI registry 2026-03-24
- Architecture: HIGH — patterns verified against official aiogram 3 docs (v3.26.0)
- Pitfalls: MEDIUM — some from official docs (from_user None), some from reasoning about API behavior
- Test mapping: MEDIUM — framework choices standard; exact test shapes are design decisions for planner

**Research date:** 2026-03-24
**Valid until:** 2026-06-24 (stable ecosystem; aiogram patch releases don't break API)
