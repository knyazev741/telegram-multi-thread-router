# Phase 2: Session Lifecycle - Research

**Researched:** 2026-03-24
**Domain:** ClaudeSDKClient session management, aiogram forum topics, asyncio task management
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Session Creation Flow**
- `/new` command auto-creates a Telegram forum topic via `createForumTopic` API — no manual topic creation needed
- No model parameter on `/new` — use default model from config (keep simple)
- System prompt for sessions: project CLAUDE.md content + "You are helping in directory {workdir}"
- If `/new` called when session already exists for a topic: error "Session already active, use /stop first"

**Session Communication**
- Each Telegram message → `client.query(text)` — one turn at a time, simple and predictable
- Claude's text output sent immediately as received from `AssistantMessage.content[TextBlock]`
- `/clear`, `/compact`, `/reset` mapped to `client.query("/clear")` etc. — let Claude handle internally
- Messages queued if Claude is already processing — send after current turn completes (ResultMessage received)

**Session Persistence & Health**
- Auto-resume on bot restart: resume ALL sessions that were `running` or `idle` when bot stopped
- Health check every 60 seconds — verify Claude subprocess is alive
- Zombie sessions: kill process, mark session `stopped`, notify topic with error message
- SQLite session columns: session_id, thread_id, workdir, model, state, created_at, updated_at

### Claude's Discretion
- SessionRunner internal implementation details (asyncio task management, error handling patterns)
- SessionManager data structures and concurrency approach
- Exact message formatting for Claude responses in Telegram
- How to handle `client.interrupt()` on /stop (drain receive_response or not)

### Deferred Ideas (OUT OF SCOPE)
- Full permission system with Telegram buttons (Phase 3)
- Status message updates (Phase 4)
- Voice/file handling (Phase 5)
- Multi-server workers (Phase 6)
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SESS-01 | User can create a new session linked to a forum topic with `/new <name> <workdir> [server]` | createForumTopic API verified; ClaudeSDKClient init patterns documented |
| SESS-02 | User can list active sessions with status via `/list` command | SQLite query patterns in Standard Stack; sessions table already exists |
| SESS-03 | User can stop a session via `/stop` command in the topic | interrupt() + drain pattern documented in Architecture Patterns section |
| SESS-04 | ClaudeSDKClient instance created per session with correct cwd, model, system_prompt | ClaudeAgentOptions exact parameters verified from official docs |
| SESS-05 | Session state machine: idle → running → waiting_permission → running → idle | State enum pattern documented; WAITING_PERMISSION is stub for Phase 3 |
| SESS-06 | Session persists session_id to SQLite for resume capability | ResultMessage.session_id extraction documented; cwd co-storage required |
| SESS-07 | Bot auto-resumes all saved sessions on startup | ClaudeAgentOptions(resume=...) pattern verified; on_startup hook integration documented |
| SESS-08 | Health monitoring detects zombie Claude processes and cleans up | asyncio periodic task pattern; process check approach documented |
| SESS-09 | User can interrupt running Claude via `/stop` or dedicated button | interrupt() then drain receive_response() documented; drain is mandatory |
| INPT-01 | Text messages in topic forwarded to session via `client.query()` | Message queue for in-flight turns documented; session_router integration point identified |
| INPT-05 | Slash commands (/clear, /compact, /reset) forwarded to Claude session | Forward as-is via client.query("/clear") — Claude handles internally |
| INPT-06 | 👀 reaction on message when delivered to session | set_message_reaction(ReactionTypeEmoji(emoji="👀")) API verified |
</phase_requirements>

---

## Summary

Phase 2 introduces the entire session lifecycle: creating a forum topic, launching a `ClaudeSDKClient` per session, routing messages to Claude, persisting session state in SQLite, and resuming sessions across bot restarts.

The central object is `SessionRunner` — an asyncio task that owns one `ClaudeSDKClient`. The `SessionManager` maps `thread_id → SessionRunner`. Both live inside the bot process for Phase 2 (Phase 6 extracts workers to remote hosts). The existing Phase 1 codebase provides the dispatcher, routers, and database — Phase 2 wires them together.

The critical design constraints are: (1) `can_use_tool` requires a dummy `PreToolUse` hook to fire at all — Phase 2 needs a placeholder for this even though full permission UI is Phase 3; (2) `interrupt()` must always be followed by draining `receive_response()` before the next `query()`; (3) session resume requires storing and passing the exact same `cwd` that was used at session creation.

**Primary recommendation:** Build `SessionRunner` + `SessionManager` first (in-process), wire to existing routers, then add persistence/resume and health monitoring. Do not reach for TCP/worker separation until Phase 6.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| claude-agent-sdk | add to pyproject.toml | ClaudeSDKClient, ClaudeAgentOptions, event types | Official Anthropic SDK; no alternative for interactive sessions |
| aiogram | 3.26.0 (already installed) | createForumTopic, set_message_reaction, send_message | Already in project; forum topic methods verified |
| aiosqlite | 0.22.x (already installed) | Session persistence, resume state | Already in project; sessions table already defined |

**Note:** `claude-agent-sdk` is NOT yet in `pyproject.toml` — it must be added.

**Installation:**
```bash
uv add claude-agent-sdk
```

Verify current version:
```bash
uv pip index versions claude-agent-sdk 2>/dev/null || pip index versions claude-agent-sdk
```
The STACK.md research cites `0.1.50` as current as of 2026-03-24.

### Imports Verified from Official Docs
```python
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    AssistantMessage,
    SystemMessage,
    ResultMessage,
    UserMessage,
    TextBlock,
    ToolUseBlock,
    PermissionResultAllow,
    PermissionResultDeny,
    HookMatcher,
)
from aiogram.methods import CreateForumTopic
from aiogram.types import ReactionTypeEmoji
```

---

## Architecture Patterns

### Recommended New File Structure

Build on top of existing Phase 1 structure. New files only:

```
src/
├── bot/
│   ├── routers/
│   │   ├── general.py        # ADD: /new, /list handlers
│   │   └── session.py        # ADD: message forward, /stop handler
│   └── dispatcher.py         # MODIFY: init SessionManager on_startup
├── db/
│   ├── schema.py             # ALREADY EXISTS (sessions table present)
│   ├── connection.py         # ALREADY EXISTS
│   └── queries.py            # NEW: named SQL functions (no raw SQL in handlers)
├── sessions/
│   ├── __init__.py
│   ├── manager.py            # NEW: SessionManager (thread_id → SessionRunner)
│   ├── runner.py             # NEW: SessionRunner (owns ClaudeSDKClient)
│   └── state.py              # NEW: SessionState enum
└── config.py                 # ALREADY EXISTS (may add model field)
```

### Pattern 1: SessionRunner Lifecycle

**What:** One asyncio task per session. Owns the `ClaudeSDKClient`. Handles query/response cycle, message queue for in-flight turns, and interrupt.

**State machine:**
```
IDLE ──── query() ──►  RUNNING ──── ResultMessage ──►  IDLE
                          │
                    user sends /stop
                          │
                          ▼
                     INTERRUPTING ──── drain done ──►  STOPPED
```

**WAITING_PERMISSION** state exists in the enum (Phase 3 will use it) but is never entered in Phase 2 — the placeholder `can_use_tool` auto-allows all tools.

**Example (runner.py core loop):**
```python
# Source: official SDK docs + ARCHITECTURE.md pattern
from enum import Enum, auto
import asyncio
from claude_agent_sdk import (
    ClaudeSDKClient, ClaudeAgentOptions,
    AssistantMessage, ResultMessage,
    TextBlock, PermissionResultAllow, HookMatcher,
)

class SessionState(Enum):
    IDLE = auto()
    RUNNING = auto()
    INTERRUPTING = auto()
    WAITING_PERMISSION = auto()  # Phase 3 stub
    STOPPED = auto()

async def _dummy_keep_stream_open(input_data, tool_use_id, context):
    """Required PreToolUse hook — without this, can_use_tool never fires."""
    return {"continue_": True}

async def _auto_allow(tool_name, input_data, context):
    """Phase 2 placeholder: auto-approve all tools. Phase 3 replaces this."""
    return PermissionResultAllow(updated_input=input_data)

class SessionRunner:
    def __init__(self, thread_id: int, workdir: str, bot, chat_id: int,
                 session_id: str | None = None, model: str | None = None):
        self.thread_id = thread_id
        self.workdir = workdir
        self.session_id = session_id  # None for new, set after first ResultMessage
        self.model = model
        self._bot = bot
        self._chat_id = chat_id
        self.state = SessionState.IDLE
        self._client: ClaudeSDKClient | None = None
        self._message_queue: asyncio.Queue[str] = asyncio.Queue()
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Launch the runner asyncio task."""
        self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        options = ClaudeAgentOptions(
            cwd=self.workdir,
            model=self.model,
            can_use_tool=_auto_allow,
            hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_dummy_keep_stream_open])]},
            resume=self.session_id,
            include_partial_messages=True,
        )
        async with ClaudeSDKClient(options=options) as client:
            self._client = client
            while self.state != SessionState.STOPPED:
                text = await self._message_queue.get()
                if text is None:  # sentinel for stop
                    break
                self.state = SessionState.RUNNING
                await client.query(text)
                await self._drain_response(client)
                self.state = SessionState.IDLE

    async def _drain_response(self, client: ClaudeSDKClient) -> None:
        async for msg in client.receive_response():
            if isinstance(msg, AssistantMessage):
                for block in msg.content:
                    if isinstance(block, TextBlock) and block.text:
                        await self._bot.send_message(
                            chat_id=self._chat_id,
                            message_thread_id=self.thread_id,
                            text=block.text,
                        )
            elif isinstance(msg, ResultMessage):
                if self.session_id is None:
                    self.session_id = msg.session_id
                    # Caller must persist to DB

    async def enqueue(self, text: str) -> None:
        """Queue a message. If RUNNING, waits until current turn finishes."""
        await self._message_queue.put(text)

    async def stop(self) -> None:
        """Interrupt and stop the runner."""
        self.state = SessionState.INTERRUPTING
        if self._client:
            await self._client.interrupt()
        # Drain is handled inside _drain_response loop automatically
        await self._message_queue.put(None)  # sentinel
        self.state = SessionState.STOPPED
```

### Pattern 2: SessionManager

**What:** Dict mapping `thread_id → SessionRunner`. Single point of truth for all active sessions. Initialized in `on_startup`, stored in bot data for handler access via aiogram DI.

```python
# Source: ARCHITECTURE.md Pattern 4 + aiogram DI pattern
import asyncio
from typing import Optional

class SessionManager:
    def __init__(self):
        self._sessions: dict[int, SessionRunner] = {}
        self._lock = asyncio.Lock()

    async def create(self, thread_id: int, workdir: str, name: str,
                     bot, chat_id: int, session_id: str | None = None,
                     model: str | None = None) -> SessionRunner:
        async with self._lock:
            if thread_id in self._sessions:
                raise ValueError(f"Session for topic {thread_id} already exists")
            runner = SessionRunner(thread_id, workdir, bot, chat_id,
                                   session_id=session_id, model=model)
            self._sessions[thread_id] = runner
            await runner.start()
            return runner

    def get(self, thread_id: int) -> Optional[SessionRunner]:
        return self._sessions.get(thread_id)

    async def stop(self, thread_id: int) -> None:
        async with self._lock:
            runner = self._sessions.pop(thread_id, None)
            if runner:
                await runner.stop()

    def list_all(self) -> list[tuple[int, SessionRunner]]:
        return list(self._sessions.items())
```

**How to pass to handlers via aiogram DI:**
```python
# dispatcher.py
async def on_startup(bot: Bot, dispatcher: Dispatcher) -> None:
    await init_db()
    manager = SessionManager()
    await manager.resume_all_from_db(bot, settings.group_chat_id)
    dispatcher["session_manager"] = manager  # aiogram stores in workflow_data

# Handler receives it:
async def handle_new(message: Message, session_manager: SessionManager) -> None:
    ...
```

### Pattern 3: /new Command — Forum Topic Creation

**What:** Create Telegram forum topic, insert into `topics` table, insert session into `sessions` table, start `SessionRunner`.

```python
# Source: aiogram docs CreateForumTopic
from aiogram.methods import CreateForumTopic
from aiogram.types import Message

@general_router.message(Command("new"))
async def handle_new(message: Message, bot: Bot, session_manager: SessionManager) -> None:
    # Parse: /new <name> <workdir>
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        await message.reply("Usage: /new <name> <workdir>")
        return
    _, name, workdir = args

    # Create forum topic
    topic = await bot(CreateForumTopic(
        chat_id=settings.group_chat_id,
        name=name,
    ))
    thread_id = topic.message_thread_id

    # Read system prompt
    system_prompt = _build_system_prompt(workdir)

    # Persist
    async with get_connection() as conn:
        await conn.execute(
            "INSERT INTO topics (thread_id, name) VALUES (?, ?)",
            (thread_id, name),
        )
        await conn.execute(
            "INSERT INTO sessions (thread_id, workdir, state) VALUES (?, ?, 'idle')",
            (thread_id, workdir),
        )
        await conn.commit()

    # Start runner
    runner = await session_manager.create(
        thread_id=thread_id, workdir=workdir, name=name,
        bot=bot, chat_id=settings.group_chat_id,
    )

    await bot.send_message(
        chat_id=settings.group_chat_id,
        message_thread_id=thread_id,
        text=f"Session '{name}' started. Working directory: {workdir}",
    )
```

### Pattern 4: Session Resume on Startup

**What:** On `on_startup`, query SQLite for sessions in `running` or `idle` state, recreate `SessionRunner` for each with `resume=session_id`.

```python
# Source: PITFALLS.md Pitfall 3 (cwd must match exactly)
async def resume_all_from_db(self, bot: Bot, chat_id: int) -> None:
    async with get_connection() as conn:
        cursor = await conn.execute(
            "SELECT thread_id, session_id, workdir, model, state FROM sessions "
            "WHERE state IN ('running', 'idle') AND session_id IS NOT NULL"
        )
        rows = await cursor.fetchall()

    for row in rows:
        thread_id = row["thread_id"]
        session_id = row["session_id"]
        workdir = row["workdir"]
        model = row["model"] if "model" in row.keys() else None
        try:
            runner = await self.create(
                thread_id=thread_id, workdir=workdir, name="",
                bot=bot, chat_id=chat_id,
                session_id=session_id, model=model,
            )
            # Notify topic
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text="Session resumed after bot restart.",
            )
        except Exception as e:
            logger.error("Failed to resume session %s: %s", session_id, e)
```

**CRITICAL:** The `workdir` stored in SQLite must be the exact path used at session creation. If `workdir` doesn't match, SDK silently starts a fresh session (PITFALLS.md Pitfall 3).

### Pattern 5: 👀 Reaction on Message Delivery (INPT-06)

```python
# Source: aiogram docs setMessageReaction
from aiogram.types import ReactionTypeEmoji

async def handle_session_message(message: Message, session_manager: SessionManager) -> None:
    thread_id = message.message_thread_id
    runner = session_manager.get(thread_id)
    if runner is None:
        return  # no active session for this topic

    # React 👀 immediately to confirm receipt
    await message.react(reaction=[ReactionTypeEmoji(emoji="👀")])

    # Enqueue (will wait if RUNNING)
    await runner.enqueue(message.text or "")
```

### Pattern 6: Health Check — Zombie Detection (SESS-08)

```python
# Source: PITFALLS.md Pitfall 4
import asyncio

async def health_check_loop(manager: SessionManager, bot: Bot, chat_id: int,
                             interval: int = 60) -> None:
    """Runs as a background task. Checks every 60s for dead runners."""
    while True:
        await asyncio.sleep(interval)
        dead = []
        for thread_id, runner in manager.list_all():
            if runner._client and hasattr(runner._client, '_process'):
                proc = runner._client._process
                if proc and proc.returncode is not None:
                    dead.append(thread_id)

        for thread_id in dead:
            await manager.stop(thread_id)
            # Mark stopped in DB
            async with get_connection() as conn:
                await conn.execute(
                    "UPDATE sessions SET state='stopped', updated_at=datetime('now') "
                    "WHERE thread_id=?", (thread_id,)
                )
                await conn.commit()
            await bot.send_message(
                chat_id=chat_id,
                message_thread_id=thread_id,
                text="Session terminated: Claude process died unexpectedly.",
            )
```

Start health check in `on_startup`:
```python
asyncio.create_task(health_check_loop(manager, bot, settings.group_chat_id))
```

### Anti-Patterns to Avoid

- **Sharing one ClaudeSDKClient across topics:** `ClaudeSDKClient` is a single-session object. Multiplexing causes undefined behavior. One instance per `SessionRunner` only.
- **Calling `query()` while receive_response() is active:** The SDK does not support concurrent turns. Always drain `receive_response()` fully before next `query()`. Use `asyncio.Queue` in `SessionRunner` to serialize.
- **Skipping drain after `interrupt()`:** SDK docs state you must drain the interrupted response stream including its `ResultMessage` before sending a new query. Skipping causes stale events on next turn.
- **Storing `session_id` without `cwd`:** Resume silently starts fresh if `cwd` differs. Always co-persist both.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Forum topic creation | Manual thread management | `bot(CreateForumTopic(...))` | Telegram handles ID assignment |
| Session subprocess management | Custom subprocess | `ClaudeSDKClient` context manager | Handles stdio, handshake, cleanup |
| Message queue for in-flight turns | Complex locking | `asyncio.Queue` with sentinels | Queue serializes naturally; no locks needed |
| Emoji reactions | Manual API call | `message.react([ReactionTypeEmoji(...)])` | aiogram shortcut method |
| Asyncio task concurrency | Thread pools | `asyncio.create_task()` + `TaskGroup` | SDK is asyncio-native; threads cause race conditions |

**Key insight:** The SDK subprocess lifecycle (spawn, handshake, teardown, zombie cleanup) has multiple edge cases. Never manage `claude` subprocesses manually — use the `ClaudeSDKClient` context manager exclusively.

---

## Common Pitfalls

### Pitfall 1: `can_use_tool` never fires without dummy PreToolUse hook
**What goes wrong:** Permission callback silently skipped; Claude stalls or proceeds without your handler.
**Why it happens:** SDK closes the stdio stream without a `PreToolUse` hook present (GitHub #18735).
**How to avoid:** Always register alongside `can_use_tool`:
```python
hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_dummy_keep_stream_open])]}
```
This is a Phase 2 requirement even though Phase 3 handles full permission UI — without the hook, Phase 3's `can_use_tool` will silently fail.
**Warning signs:** No permission messages in Telegram; Claude proceeds immediately on all tools.

### Pitfall 2: Resume fails silently when `cwd` differs
**What goes wrong:** `resume=session_id` passed but Claude starts fresh session with no prior context.
**Why it happens:** SDK stores sessions at `~/.claude/projects/<encoded-cwd>/`. Different path = different storage directory.
**How to avoid:** Store `workdir` in SQLite at creation. Pass exactly the same path on resume.

### Pitfall 3: `query()` while previous turn in-flight
**What goes wrong:** Second query receives events from both turns merged; state corruption.
**How to avoid:** `asyncio.Queue` in `SessionRunner` ensures messages are processed sequentially.

### Pitfall 4: Forgetting to drain after `interrupt()`
**What goes wrong:** Next query receives stale events from interrupted turn.
**How to avoid:** `_drain_response()` always runs to completion. In INTERRUPTING state, drain still runs — just discards output.

### Pitfall 5: `message_thread_id` not passed on send
**What goes wrong:** Bot reply lands in General topic instead of session topic.
**How to avoid:** ALL `bot.send_message()` calls in session context MUST include `message_thread_id=runner.thread_id`. Use a thin wrapper or always pass it explicitly.

### Pitfall 6: Sessions table missing `model` column
**What goes wrong:** Resume can't restore the model used originally.
**Why it happens:** Current schema has no `model` column (only `workdir`, `state`, `session_id`).
**How to avoid:** Add `model TEXT` column in schema migration or accept `None` model (uses SDK default). Phase 2 uses config default model — storing it is optional but cleanest.

---

## Code Examples

### ClaudeAgentOptions for Phase 2 Sessions
```python
# Source: https://platform.claude.com/docs/en/agent-sdk/python
options = ClaudeAgentOptions(
    cwd=workdir,                           # working directory — MUST match resume path
    model=model or None,                   # None = SDK default
    system_prompt=system_prompt,           # CLAUDE.md + workdir hint
    can_use_tool=_auto_allow,              # Phase 2 placeholder (Phase 3 replaces)
    hooks={
        "PreToolUse": [
            HookMatcher(matcher=None, hooks=[_dummy_keep_stream_open])
        ]
    },
    resume=session_id or None,             # None for new sessions
    include_partial_messages=True,         # ready for Phase 4 streaming
)
```

### Extract session_id from ResultMessage
```python
# Source: official docs ResultMessage
async for msg in client.receive_response():
    if isinstance(msg, ResultMessage):
        new_session_id = msg.session_id
        # Persist to DB
        async with get_connection() as conn:
            await conn.execute(
                "UPDATE sessions SET session_id=?, updated_at=datetime('now') "
                "WHERE thread_id=?",
                (new_session_id, self.thread_id),
            )
            await conn.commit()
```

### createForumTopic and extract thread_id
```python
# Source: https://docs.aiogram.dev/en/latest/api/methods/create_forum_topic.html
from aiogram.methods import CreateForumTopic

topic = await bot(CreateForumTopic(
    chat_id=settings.group_chat_id,
    name=name,
))
thread_id: int = topic.message_thread_id
```

### Running multiple SessionRunners concurrently
```python
# Source: official SDK docs concurrent usage + asyncio.create_task
# Each SessionRunner is an independent asyncio task
# No shared state between ClaudeSDKClient instances
runner_a = SessionRunner(thread_id=101, ...)
runner_b = SessionRunner(thread_id=102, ...)
await runner_a.start()   # creates asyncio.create_task(runner_a._run())
await runner_b.start()   # creates asyncio.create_task(runner_b._run())
# Both run concurrently in the same event loop
```

### System prompt builder
```python
def _build_system_prompt(workdir: str) -> str:
    """Read CLAUDE.md if present, append workdir context."""
    claude_md = Path(workdir) / "CLAUDE.md"
    base = claude_md.read_text() if claude_md.exists() else ""
    return f"{base}\n\nYou are helping in directory {workdir}".strip()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `--dangerously-skip-permissions` flag | `can_use_tool` callback in `ClaudeAgentOptions` | SDK 0.1.x | Proper permission control without bypassing |
| One-shot `query()` functional API | Stateful `ClaudeSDKClient` context manager with `query()` + `receive_response()` | SDK 0.1.x | Supports multi-turn sessions with state |
| Manual subprocess management | `ClaudeSDKClient.__aenter__`/`__aexit__` | SDK 0.1.x | Handles zombie cleanup automatically |

**Note on `connect()` vs no explicit connect:** The verified API shows `ClaudeSDKClient` as an async context manager — `async with ClaudeSDKClient(options=options) as client`. The `connect()` method exists but `async with` is the standard pattern per official docs.

---

## Open Questions

1. **Does `sessions` table need a `model` column?**
   - What we know: Current schema has no `model` column. `ClaudeAgentOptions` accepts `model=None` (uses default).
   - What's unclear: Whether saving the original model for resume matters in practice.
   - Recommendation: Add `model TEXT` column with NULL default in a schema migration task in Wave 1. Add it to `ClaudeAgentOptions` on resume.

2. **Does `asyncio.Queue` in `SessionRunner` need bounded size?**
   - What we know: Unbounded queues can grow without limit if messages arrive faster than Claude processes them.
   - What's unclear: Real-world rate from a single owner user is very low.
   - Recommendation: Use `asyncio.Queue(maxsize=0)` (unbounded) for Phase 2. Add size limit in Phase 4 if needed.

3. **How to detect zombie process in `health_check_loop`?**
   - What we know: `client._process.returncode` is not None when process has exited. But `_process` is a private SDK attribute.
   - What's unclear: Whether the SDK exposes a public `is_alive()` or similar.
   - Recommendation: Use `_process` check as documented in PITFALLS.md. If SDK version changes the attribute, fall back to `psutil` process check.

4. **General topic thread_id value in production**
   - What we know: Phase 1 uses `F.message_thread_id.in_({1, None})` defensively.
   - Decision logged in STATE.md: Phase 2 live testing will confirm.
   - Recommendation: Keep the defensive filter; adjust after first live test.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio 0.24 |
| Config file | `pyproject.toml` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| Quick run command | `uv run pytest tests/test_sessions.py -x` |
| Full suite command | `uv run pytest tests/ -x` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SESS-01 | `/new` creates topic + DB records + runner | unit (mocked bot) | `uv run pytest tests/test_sessions.py::test_new_command -x` | ❌ Wave 0 |
| SESS-02 | `/list` returns sessions from DB | unit | `uv run pytest tests/test_sessions.py::test_list_command -x` | ❌ Wave 0 |
| SESS-03 | `/stop` interrupts runner, marks stopped in DB | unit | `uv run pytest tests/test_sessions.py::test_stop_command -x` | ❌ Wave 0 |
| SESS-04 | SessionRunner creates ClaudeSDKClient with correct options | unit (mock SDK) | `uv run pytest tests/test_runner.py::test_runner_options -x` | ❌ Wave 0 |
| SESS-05 | State transitions: IDLE→RUNNING→IDLE, RUNNING→INTERRUPTING→STOPPED | unit | `uv run pytest tests/test_runner.py::test_state_machine -x` | ❌ Wave 0 |
| SESS-06 | session_id persisted to DB after ResultMessage | unit | `uv run pytest tests/test_runner.py::test_session_id_persisted -x` | ❌ Wave 0 |
| SESS-07 | on_startup resumes sessions from DB with correct cwd | unit (mock DB) | `uv run pytest tests/test_sessions.py::test_resume_on_startup -x` | ❌ Wave 0 |
| SESS-08 | health check detects dead process, marks stopped, notifies | unit (mock process) | `uv run pytest tests/test_sessions.py::test_health_check -x` | ❌ Wave 0 |
| SESS-09 | interrupt() called on /stop, receive_response drained | unit | `uv run pytest tests/test_runner.py::test_interrupt -x` | ❌ Wave 0 |
| INPT-01 | Text message enqueued to SessionRunner | unit | `uv run pytest tests/test_routing.py::test_text_forwarded -x` | ❌ Wave 0 |
| INPT-05 | /clear command forwarded via enqueue | unit | `uv run pytest tests/test_routing.py::test_slash_forwarded -x` | ❌ Wave 0 |
| INPT-06 | 👀 reaction set on message delivery | unit (mock bot) | `uv run pytest tests/test_routing.py::test_reaction_set -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_sessions.py tests/test_runner.py -x`
- **Per wave merge:** `uv run pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_sessions.py` — covers SESS-01, SESS-02, SESS-03, SESS-07, SESS-08
- [ ] `tests/test_runner.py` — covers SESS-04, SESS-05, SESS-06, SESS-09
- [ ] `tests/test_routing.py` — covers INPT-01, INPT-05, INPT-06
- [ ] `tests/conftest.py` — add mock `ClaudeSDKClient`, mock `Bot`, mock `SessionManager` fixtures

---

## Sources

### Primary (HIGH confidence)
- `https://platform.claude.com/docs/en/agent-sdk/python` — ClaudeSDKClient API, ClaudeAgentOptions all parameters, event types, HookMatcher, PermissionResultAllow/Deny, concurrent usage
- `https://docs.aiogram.dev/en/latest/api/methods/create_forum_topic.html` — CreateForumTopic parameters, return type
- `https://docs.aiogram.dev/en/latest/api/methods/set_message_reaction.html` — SetMessageReaction, ReactionTypeEmoji usage
- `.planning/research/STACK.md` (2026-03-24) — verified package versions, SDK lifecycle patterns
- `.planning/research/ARCHITECTURE.md` (2026-03-24) — SessionRunner/SessionManager patterns, state machine, data flows
- `.planning/research/PITFALLS.md` (2026-03-24) — Pitfalls 1-4 directly affect Phase 2 implementation

### Secondary (MEDIUM confidence)
- GitHub issue #18735 (anthropics/claude-code) — dummy PreToolUse hook requirement confirmed January 2026 (cited in PITFALLS.md)
- GitHub issue #18666 — zombie subprocess accumulation on failed init

### Tertiary (LOW confidence)
- None for this phase

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — claude-agent-sdk API verified directly from official docs; aiogram methods verified from official docs
- Architecture: HIGH — patterns from verified SDK docs + existing Phase 1 codebase inspection
- Pitfalls: HIGH — confirmed in official docs and tracked GitHub issues

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (SDK is actively maintained; check for minor API changes before planning)
