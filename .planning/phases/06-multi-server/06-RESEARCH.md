# Phase 6: Multi-Server - Research

**Researched:** 2026-03-25
**Domain:** asyncio TCP, msgspec binary protocol, distributed session routing
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- TCP framing: 4-byte length prefix + msgspec-encoded payload (binary, validated)
- Auth handshake: first message {type: "auth", token: AUTH_TOKEN} — server validates, drops on fail
- Worker reconnection: exponential backoff 1s → 2s → 4s → 8s... max 60s
- Worker entry point: `python -m src.worker` — standalone script
- /new name workdir server-name — server-name maps to registered worker connection
- Local sessions (no server specified): in-process SessionRunner — current behavior unchanged
- Worker disconnect mid-session: mark "disconnected", notify topic, auto-reconnect restores session
- /list shows server name + connection status per session

### Claude's Discretion
- TCP protocol message type definitions (exact msgspec Struct schemas)
- Worker-side SessionRunner reuse vs new wrapper
- How to forward permission requests/responses over TCP
- How to forward MCP tool calls over TCP

### Deferred Ideas (OUT OF SCOPE)
None — this is the final phase
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| MSRV-01 | Worker process runs on remote server, manages ClaudeSDKClient locally | Worker is `python -m src.worker`; reuses existing SessionRunner with TCP output callback |
| MSRV-02 | Worker connects to central bot via authenticated TCP (auth_token) | asyncio.open_connection + auth handshake on connect |
| MSRV-03 | TCP protocol: length-prefixed msgspec-encoded messages | msgspec official example: 4-byte big-endian prefix + msgpack payload; readexactly(4) then readexactly(n) |
| MSRV-04 | Worker forwards all SDK events (text, tool use, permission, status) to bot | _drain_response loop sends TCP messages instead of calling Bot directly |
| MSRV-05 | Bot forwards user messages and permission responses to worker | IPCServer receives TCP message, routes to RemoteSession proxy |
| MSRV-06 | Worker auto-reconnects on TCP disconnect with exponential backoff | while-True loop with delay = min(delay*2, 60) pattern |
| MSRV-07 | Bot tracks which server each session runs on | sessions.server column already in DB schema; SessionManager stores worker_id per thread_id |
| MSRV-08 | Local sessions also supported (bot runs worker in-process) | SessionManager.create() defaults to local path; server-name parameter absent → existing SessionRunner path |
</phase_requirements>

---

## Summary

Phase 6 adds a TCP-based distributed execution layer. Workers run on remote hosts, each managing one or more `ClaudeSDKClient` instances locally. The bot acts as a routing hub: it receives Telegram updates, finds the registered worker connection for the session's server name, forwards commands over TCP, and renders the events it receives back from the worker in Telegram.

The key insight from studying the existing code: `SessionRunner` currently takes a `Bot` instance and calls it directly (sending messages, editing status). On the worker side, that same runner can be reused if we replace its Bot dependency with a "TCP-sending Bot proxy" (a `RemoteOutputChannel`). Bot-side, a `RemoteSession` proxy object implements the same interface as `SessionRunner` so `SessionManager` needs minimal changes — it just needs to route `get(thread_id)` to either a local `SessionRunner` or a `RemoteSession` depending on which server hosts that topic.

The `sessions.server` column is already in the database schema (`TEXT NOT NULL DEFAULT 'local'`), so DB migration is not needed. `insert_session` in `queries.py` needs a `server` parameter; `get_resumable_sessions` must return the `server` field.

**Primary recommendation:** Implement in three self-contained modules: `src/ipc/protocol.py` (shared framing + Struct definitions), `src/ipc/server.py` (bot-side TCP accept loop), `src/worker/__main__.py` + `src/worker/client.py` (worker-side TCP connect loop). Then wire `SessionManager` to route by server.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| asyncio (stdlib) | Python 3.14 (project) | TCP streams, connection management | No external deps; `start_server`/`open_connection` are idiomatic for in-process async IPC |
| msgspec | 0.18.x (latest on PyPI) | Binary message encoding/decoding with type validation | Already planned as dependency; official example shows exact TCP framing pattern we need |
| struct (stdlib) | Python 3.14 | Pack/unpack 4-byte length prefix | Used internally by msgspec example; `int.from_bytes` / `int.to_bytes` is the idiomatic Python 3 form |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| msgspec.msgpack | bundled with msgspec | Binary serialization for TCP payload | Binary is ~30% smaller than JSON, zero extra deps |
| asyncio.Queue | stdlib | Worker-side pending permission futures delivery | Already used in SessionRunner message queue; same pattern for permission responses |

### Installation
```bash
# Add to pyproject.toml dependencies:
"msgspec>=0.18.0",
```

**Version verification:** msgspec 0.18.6 is current as of PyPI (March 2025). The project does not yet have msgspec in pyproject.toml — it must be added.

---

## Architecture Patterns

### Recommended File Layout

```
src/
├── ipc/
│   ├── __init__.py
│   ├── protocol.py      # Struct definitions + framing helpers (shared bot/worker)
│   └── server.py        # Bot-side: asyncio.start_server, WorkerRegistry
├── worker/
│   ├── __init__.py
│   ├── __main__.py      # Entry: python -m src.worker (reads config, connects, loops)
│   └── client.py        # WorkerClient: connect_with_retry, receive loop, SessionRunner management
```

Existing files modified:
- `src/sessions/manager.py` — add `create_remote()`, route `get()` to local or remote
- `src/sessions/runner.py` — accept optional `output_channel` for remote output
- `src/bot/routers/general.py` — parse optional server-name arg in `/new`
- `src/db/queries.py` — pass `server` to `insert_session`, return it from `get_resumable_sessions`
- `src/bot/dispatcher.py` — start IPC server alongside polling, register in dispatcher dict
- `src/config.py` — add `ipc_host`/`ipc_port` with defaults

### Pattern 1: msgspec Struct Protocol with Tagged Union

**What:** All messages over TCP are typed msgspec Structs. A Union type covers all message variants, enabling discriminated decode on either side.

**Source:** [msgspec asyncio TCP example](https://jcristharif.com/msgspec/examples/asyncio-kv.html) + [structs docs](https://jcristharif.com/msgspec/structs.html)

```python
# src/ipc/protocol.py
import msgspec
from typing import Union

# ---- Worker → Bot ----
class AuthMsg(msgspec.Struct, tag=True):
    token: str
    worker_id: str

class SessionStartedMsg(msgspec.Struct, tag=True):
    topic_id: int
    session_id: str

class AssistantTextMsg(msgspec.Struct, tag=True):
    topic_id: int
    text: str

class PermissionRequestMsg(msgspec.Struct, tag=True):
    topic_id: int
    request_id: str
    tool_name: str
    input_data: dict

class StatusUpdateMsg(msgspec.Struct, tag=True):
    topic_id: int
    tool_name: str
    elapsed_ms: int
    tool_calls: int

class SessionEndedMsg(msgspec.Struct, tag=True):
    topic_id: int
    error: str | None = None

class McpSendMessageMsg(msgspec.Struct, tag=True):
    topic_id: int
    text: str

class McpReactMsg(msgspec.Struct, tag=True):
    topic_id: int
    message_id: int
    emoji: str

class McpEditMessageMsg(msgspec.Struct, tag=True):
    topic_id: int
    message_id: int
    text: str

class McpSendFileMsg(msgspec.Struct, tag=True):
    topic_id: int
    file_path: str
    caption: str | None = None

# ---- Bot → Worker ----
class AuthOkMsg(msgspec.Struct, tag=True):
    worker_id: str

class AuthFailMsg(msgspec.Struct, tag=True):
    reason: str

class StartSessionMsg(msgspec.Struct, tag=True):
    topic_id: int
    cwd: str
    session_id: str | None = None
    model: str | None = None

class StopSessionMsg(msgspec.Struct, tag=True):
    topic_id: int

class UserMessageMsg(msgspec.Struct, tag=True):
    topic_id: int
    text: str

class PermissionResponseMsg(msgspec.Struct, tag=True):
    request_id: str
    action: str  # "allow" | "always" | "deny"

class SlashCommandMsg(msgspec.Struct, tag=True):
    topic_id: int
    command: str

# Union types for each direction
WorkerToBot = Union[
    AuthMsg, SessionStartedMsg, AssistantTextMsg, PermissionRequestMsg,
    StatusUpdateMsg, SessionEndedMsg, McpSendMessageMsg, McpReactMsg,
    McpEditMessageMsg, McpSendFileMsg,
]
BotToWorker = Union[
    AuthOkMsg, AuthFailMsg, StartSessionMsg, StopSessionMsg,
    UserMessageMsg, PermissionResponseMsg, SlashCommandMsg,
]

# Reusable encoder/decoder
_encoder = msgspec.msgpack.Encoder()
_w2b_decoder = msgspec.msgpack.Decoder(WorkerToBot)
_b2w_decoder = msgspec.msgpack.Decoder(BotToWorker)
```

### Pattern 2: Length-Prefix TCP Framing

**What:** 4-byte big-endian length prefix + msgpack payload. Uses `asyncio.StreamReader.readexactly()` so it never over-reads.

**Source:** [msgspec official asyncio TCP example](https://jcristharif.com/msgspec/examples/asyncio-kv.html)

```python
# src/ipc/protocol.py (framing helpers)
import asyncio

async def send_msg(writer: asyncio.StreamWriter, msg) -> None:
    """Encode msg and write with 4-byte length prefix."""
    payload = _encoder.encode(msg)
    prefix = len(payload).to_bytes(4, "big")
    writer.write(prefix + payload)
    await writer.drain()

async def recv_w2b(reader: asyncio.StreamReader) -> WorkerToBot | None:
    """Read one WorkerToBot message. Returns None on EOF."""
    try:
        prefix = await reader.readexactly(4)
        n = int.from_bytes(prefix, "big")
        payload = await reader.readexactly(n)
        return _w2b_decoder.decode(payload)
    except asyncio.IncompleteReadError:
        return None  # clean EOF

async def recv_b2w(reader: asyncio.StreamReader) -> BotToWorker | None:
    """Read one BotToWorker message. Returns None on EOF."""
    try:
        prefix = await reader.readexactly(4)
        n = int.from_bytes(prefix, "big")
        payload = await reader.readexactly(n)
        return _b2w_decoder.decode(payload)
    except asyncio.IncompleteReadError:
        return None
```

### Pattern 3: Bot-Side IPC Server + WorkerRegistry

**What:** `asyncio.start_server` fires a callback per connection. Each connection runs an auth handshake, then loops reading messages and dispatching them to `SessionManager` / `PermissionManager` / `Bot`.

```python
# src/ipc/server.py
import asyncio
import logging
from src.ipc.protocol import (
    send_msg, recv_w2b, AuthMsg, AuthOkMsg, AuthFailMsg,
    AssistantTextMsg, PermissionRequestMsg, PermissionResponseMsg,
    SessionEndedMsg, StatusUpdateMsg, McpSendMessageMsg,
)

logger = logging.getLogger(__name__)

class WorkerRegistry:
    """Tracks live worker connections keyed by worker_id."""
    def __init__(self):
        self._workers: dict[str, asyncio.StreamWriter] = {}

    def register(self, worker_id: str, writer: asyncio.StreamWriter) -> None:
        self._workers[worker_id] = writer

    def unregister(self, worker_id: str) -> None:
        self._workers.pop(worker_id, None)

    async def send_to(self, worker_id: str, msg) -> bool:
        """Send a message to a specific worker. Returns False if not connected."""
        writer = self._workers.get(worker_id)
        if writer is None or writer.is_closing():
            return False
        await send_msg(writer, msg)
        return True

    def is_connected(self, worker_id: str) -> bool:
        w = self._workers.get(worker_id)
        return w is not None and not w.is_closing()


async def start_ipc_server(host: str, port: int, auth_token: str,
                           bot, session_manager, permission_manager,
                           worker_registry: WorkerRegistry):
    """Start the TCP IPC server. Returns the Server object."""
    async def handle_connection(reader: asyncio.StreamReader,
                                writer: asyncio.StreamWriter):
        asyncio.create_task(  # don't block the accept loop
            _handle_worker(reader, writer, auth_token, bot,
                           session_manager, permission_manager, worker_registry)
        )

    server = await asyncio.start_server(handle_connection, host, port)
    logger.info("IPC server listening on %s:%d", host, port)
    return server
```

### Pattern 4: Worker-Side Reconnect Loop

**What:** Worker wraps `asyncio.open_connection` in an exponential-backoff loop. On reconnect, it re-registers all locally running sessions with the bot.

```python
# src/worker/client.py
import asyncio
import logging
import uuid
from src.ipc.protocol import send_msg, recv_b2w, AuthMsg, AuthOkMsg

logger = logging.getLogger(__name__)
WORKER_ID = str(uuid.uuid4())  # stable within process lifetime

async def connect_with_retry(host: str, port: int, auth_token: str,
                              on_connected, on_disconnected):
    """Connect to bot IPC, call on_connected(reader, writer), retry on failure."""
    delay = 1.0
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            await send_msg(writer, AuthMsg(token=auth_token, worker_id=WORKER_ID))
            response = await recv_b2w(reader)
            if not isinstance(response, AuthOkMsg):
                logger.error("Auth rejected: %s", response)
                writer.close()
                await writer.wait_closed()
                break  # permanent failure, don't retry
            delay = 1.0  # reset on success
            logger.info("Connected to bot IPC as worker %s", WORKER_ID)
            try:
                await on_connected(reader, writer)
            finally:
                await on_disconnected()
        except (ConnectionRefusedError, OSError, asyncio.TimeoutError) as e:
            logger.warning("IPC connect failed: %s — retrying in %.0fs", e, delay)
        await asyncio.sleep(delay)
        delay = min(delay * 2, 60.0)
```

### Pattern 5: Worker-Side SessionRunner with TCP Output

**What:** `SessionRunner` is refactored to accept an optional `output_channel` abstraction. When running on a worker, the channel sends TCP messages instead of calling `Bot` directly.

The key dependency injection point: `SessionRunner.__init__` currently takes `bot: Bot`. For the worker, we pass a `TcpOutputChannel` that implements the same async interface. All `await self._bot.send_message(...)` calls go through the channel.

**Recommended approach (minimal change):** Create a `WorkerOutputChannel` adapter that wraps the IPC writer and exposes `send_message`, `edit_message_text`, `delete_message`, `send_document`, `set_message_reaction` — matching the `aiogram.Bot` interface shape that `SessionRunner` and `StatusUpdater` actually call. Then `SessionRunner` accepts `bot: Bot | WorkerOutputChannel`.

This is simpler than creating a full wrapper class because:
1. SessionRunner only calls 5 Bot methods
2. No import of aiogram needed in the worker
3. Avoids spawning a real aiogram bot on the worker

### Pattern 6: Permission Bridge over TCP

**What:** Worker's `_can_use_tool` creates a local `asyncio.Future`, registers it by `request_id`, sends `PermissionRequestMsg` to bot. Worker's TCP receive loop listens for `PermissionResponseMsg` and resolves the stored future.

```python
# src/worker/client.py (permission bridge)
class WorkerClient:
    def __init__(self, writer):
        self._writer = writer
        self._pending_permissions: dict[str, asyncio.Future] = {}

    async def request_permission(self, topic_id: int, tool_name: str,
                                  input_data: dict) -> str:
        """Send permission request, await user response. Returns action string."""
        import uuid
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending_permissions[request_id] = future
        await send_msg(self._writer, PermissionRequestMsg(
            topic_id=topic_id,
            request_id=request_id,
            tool_name=tool_name,
            input_data=input_data,
        ))
        try:
            return await asyncio.wait_for(future, timeout=300.0)
        except asyncio.TimeoutError:
            self._pending_permissions.pop(request_id, None)
            return "deny"

    def resolve_permission(self, request_id: str, action: str) -> None:
        """Called from TCP receive loop when PermissionResponseMsg arrives."""
        future = self._pending_permissions.pop(request_id, None)
        if future and not future.done():
            future.set_result(action)
```

### Pattern 7: RemoteSession — Bot-Side Proxy

**What:** `SessionManager` stores either a `SessionRunner` (local) or a `RemoteSession` (remote). Both expose `.enqueue(text)`, `.stop()`, `.state`, `.workdir`, `.is_alive`.

```python
# src/sessions/remote.py
class RemoteSession:
    """Bot-side proxy for a session running on a remote worker."""

    def __init__(self, thread_id: int, workdir: str, worker_id: str,
                 worker_registry: WorkerRegistry):
        self.thread_id = thread_id
        self.workdir = workdir
        self.worker_id = worker_id
        self._registry = worker_registry
        self.state = SessionState.IDLE

    @property
    def is_alive(self) -> bool:
        return self._registry.is_connected(self.worker_id)

    async def enqueue(self, text: str) -> None:
        await self._registry.send_to(
            self.worker_id,
            UserMessageMsg(topic_id=self.thread_id, text=text),
        )

    async def stop(self) -> None:
        await self._registry.send_to(
            self.worker_id,
            StopSessionMsg(topic_id=self.thread_id),
        )
        self.state = SessionState.STOPPED
```

### Pattern 8: SessionManager Routing Extension

**What:** `SessionManager` stores `dict[int, SessionRunner | RemoteSession]`. Two creation paths: existing `create()` for local, new `create_remote()` for remote. The `get()` and `stop()` methods work on either type.

```python
# src/sessions/manager.py (additions)
async def create_remote(
    self,
    thread_id: int,
    workdir: str,
    worker_id: str,
    worker_registry,
    bot: Bot,
    chat_id: int,
) -> "RemoteSession":
    from src.sessions.remote import RemoteSession
    async with self._lock:
        if thread_id in self._sessions:
            raise ValueError(f"Session for topic {thread_id} already exists")
        session = RemoteSession(thread_id, workdir, worker_id, worker_registry)
        self._sessions[thread_id] = session
        # Tell the worker to start the session
        await worker_registry.send_to(
            worker_id,
            StartSessionMsg(topic_id=thread_id, cwd=workdir),
        )
        return session
```

### Anti-Patterns to Avoid

- **Blocking the asyncio event loop on connection accept**: Spawn each connection handler as `asyncio.create_task()` inside `handle_connection`. Never `await` directly in the accept callback.
- **Using readline() instead of readexactly()**: `readline()` works only for newline-delimited text. For binary msgpack, always use `readexactly(4)` + `readexactly(n)`.
- **Storing WorkerRegistry outside of the dispatcher dict**: Add it to `dispatcher["worker_registry"]` in `on_startup` so handlers and health tasks can access it.
- **Forgetting to drain the interrupted session on worker disconnect**: When TCP drops mid-session (RUNNING state), the `_can_use_tool` future is orphaned. The worker must cancel pending permission futures before disconnecting and notify the bot via `SessionEndedMsg(error="connection lost")`.
- **Re-creating SessionRunner on reconnect without resume**: Worker reconnect must re-register existing sessions (with their `session_id`) using `StartSessionMsg(session_id=...)` so Claude resumes conversation context.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Binary serialization for TCP | Custom JSON + escape encoding | `msgspec.msgpack` | Type-validated, schema-enforced, 5x faster than json.dumps, official TCP framing example |
| Message type discrimination | Manual `type` field parsing with if/elif | `msgspec.Struct` with `tag=True` | Decoder auto-routes to correct Struct; validation errors raised on malformed input |
| Reconnection with backoff | Custom sleep loop with mutable state | Pattern 4 above with `delay = min(delay*2, 60)` | Simple, correct, battle-tested |
| Permission async bridge | Shared queue between coroutines | `asyncio.Future` in `_pending_permissions` dict | Same pattern already proven in PermissionManager; minimal surface area |

---

## Common Pitfalls

### Pitfall 1: msgspec tag=True uses class name as tag value

**What goes wrong:** With `tag=True`, msgspec uses the class name as the tag. `AuthMsg` serializes as `{"type": "AuthMsg", ...}` in JSON, or the equivalent in msgpack. If you rename the class, the protocol breaks.

**How to avoid:** Use explicit tags: `class AuthMsg(msgspec.Struct, tag="auth")`. This decouples wire format from Python class names and matches the naming in CONTEXT.md.

**Warning signs:** `msgspec.DecodeError: Expected object, got ...` after a rename.

### Pitfall 2: readexactly() raises IncompleteReadError on clean EOF

**What goes wrong:** When the remote side closes the connection cleanly, `readexactly(4)` raises `asyncio.IncompleteReadError`, not returns empty bytes. Code that catches `EOFError` will miss it.

**How to avoid:** In the receive helpers, catch `asyncio.IncompleteReadError` (not `EOFError`) and return `None` to signal disconnection.

### Pitfall 3: writer.drain() not awaited after large writes

**What goes wrong:** If you write a large payload (long Claude output) without draining, the write buffer fills and subsequent writes silently queue until the OS socket buffer overflows — causing backpressure or silent data loss.

**How to avoid:** Always `await writer.drain()` in `send_msg()`. The framing helper in Pattern 2 already does this.

### Pitfall 4: Worker creates new WORKER_ID on each reconnect

**What goes wrong:** If `WORKER_ID = str(uuid.uuid4())` is inside the reconnect loop, each reconnect appears as a new worker to the bot. The bot cannot correlate "worker that disconnected" with "worker that just reconnected", so it cannot restore pending sessions.

**How to avoid:** Generate `WORKER_ID` once at module level (outside the reconnect loop). It identifies the worker process, not the connection.

### Pitfall 5: In-flight permission Future orphaned on TCP disconnect

**What goes wrong:** Worker is mid-session, `can_use_tool` is awaiting a `Future`. TCP drops. The bot will never send `PermissionResponseMsg`. The Future awaits forever, blocking the `ClaudeSDKClient` coroutine.

**How to avoid:** Worker's `on_disconnected` callback must iterate `_pending_permissions` and cancel all pending futures (or set them to "deny"). `SessionRunner` will then receive a `PermissionResultDeny` and the turn ends cleanly.

### Pitfall 6: asyncio.start_server server object not kept alive

**What goes wrong:** `asyncio.start_server` returns a `Server` object. If it goes out of scope (garbage collected), the server stops accepting connections.

**How to avoid:** Store the Server in `dispatcher["ipc_server"]`. Call `server.close()` + `await server.wait_closed()` in `on_shutdown`.

### Pitfall 7: msgspec not in pyproject.toml

**What goes wrong:** `import msgspec` fails at startup. The library is not currently in the project dependencies.

**How to avoid:** Add `"msgspec>=0.18.0"` to `pyproject.toml` dependencies and run `uv sync` or `pip install -e .` before implementation.

---

## Code Examples

### Complete framing module (verified pattern)

```python
# src/ipc/protocol.py
# Source: https://jcristharif.com/msgspec/examples/asyncio-kv.html
import asyncio
import msgspec
from typing import Union

# --- Message type definitions with explicit wire tags ---

class AuthMsg(msgspec.Struct, tag="auth"):
    token: str
    worker_id: str

class AuthOkMsg(msgspec.Struct, tag="auth_ok"):
    worker_id: str

class AuthFailMsg(msgspec.Struct, tag="auth_fail"):
    reason: str

class StartSessionMsg(msgspec.Struct, tag="start_session"):
    topic_id: int
    cwd: str
    session_id: str | None = None
    model: str | None = None

class StopSessionMsg(msgspec.Struct, tag="stop_session"):
    topic_id: int

class UserMessageMsg(msgspec.Struct, tag="user_message"):
    topic_id: int
    text: str

class PermissionResponseMsg(msgspec.Struct, tag="permission_response"):
    request_id: str
    action: str

class SlashCommandMsg(msgspec.Struct, tag="slash_command"):
    topic_id: int
    command: str

class SessionStartedMsg(msgspec.Struct, tag="session_started"):
    topic_id: int
    session_id: str

class AssistantTextMsg(msgspec.Struct, tag="assistant_text"):
    topic_id: int
    text: str

class PermissionRequestMsg(msgspec.Struct, tag="permission_request"):
    topic_id: int
    request_id: str
    tool_name: str
    input_data: dict

class StatusUpdateMsg(msgspec.Struct, tag="status_update"):
    topic_id: int
    tool_name: str
    elapsed_ms: int
    tool_calls: int

class SessionEndedMsg(msgspec.Struct, tag="session_ended"):
    topic_id: int
    error: str | None = None

class McpSendMessageMsg(msgspec.Struct, tag="mcp_send_message"):
    topic_id: int
    text: str

class McpReactMsg(msgspec.Struct, tag="mcp_react"):
    topic_id: int
    message_id: int
    emoji: str

class McpEditMessageMsg(msgspec.Struct, tag="mcp_edit_message"):
    topic_id: int
    message_id: int
    text: str

class McpSendFileMsg(msgspec.Struct, tag="mcp_send_file"):
    topic_id: int
    file_path: str
    caption: str | None = None

WorkerToBot = Union[
    AuthMsg, SessionStartedMsg, AssistantTextMsg, PermissionRequestMsg,
    StatusUpdateMsg, SessionEndedMsg,
    McpSendMessageMsg, McpReactMsg, McpEditMessageMsg, McpSendFileMsg,
]
BotToWorker = Union[
    AuthOkMsg, AuthFailMsg, StartSessionMsg, StopSessionMsg,
    UserMessageMsg, PermissionResponseMsg, SlashCommandMsg,
]

_enc = msgspec.msgpack.Encoder()
_w2b_dec = msgspec.msgpack.Decoder(WorkerToBot)
_b2w_dec = msgspec.msgpack.Decoder(BotToWorker)


async def send_msg(writer: asyncio.StreamWriter, msg) -> None:
    payload = _enc.encode(msg)
    writer.write(len(payload).to_bytes(4, "big") + payload)
    await writer.drain()


async def recv_w2b(reader: asyncio.StreamReader) -> WorkerToBot | None:
    try:
        n = int.from_bytes(await reader.readexactly(4), "big")
        return _w2b_dec.decode(await reader.readexactly(n))
    except asyncio.IncompleteReadError:
        return None


async def recv_b2w(reader: asyncio.StreamReader) -> BotToWorker | None:
    try:
        n = int.from_bytes(await reader.readexactly(4), "big")
        return _b2w_dec.decode(await reader.readexactly(n))
    except asyncio.IncompleteReadError:
        return None
```

### `/new` command with optional server-name

```python
# src/bot/routers/general.py — updated handle_new
@general_router.message(F.message_thread_id.in_({1, None}), Command("new"))
async def handle_new(message, bot, session_manager, permission_manager,
                     worker_registry) -> None:
    """Usage: /new <name> <workdir> [server-name]"""
    args = message.text.split(maxsplit=3)
    if len(args) < 3:
        await message.reply("Usage: /new <name> <workdir> [server-name]")
        return

    name = args[1]
    workdir = args[2]
    server_name = args[3] if len(args) > 3 else "local"

    # Create topic ...
    if server_name == "local":
        await session_manager.create(thread_id=..., workdir=workdir, bot=bot, ...)
    else:
        if not worker_registry.is_connected(server_name):
            await message.reply(f"Server '{server_name}' is not connected.")
            return
        await session_manager.create_remote(
            thread_id=..., workdir=workdir, worker_id=server_name, ...
        )
```

### DB changes needed

```python
# src/db/queries.py — insert_session needs server parameter
async def insert_session(thread_id: int, workdir: str,
                         model: str | None = None,
                         server: str = "local") -> None:
    async with get_connection() as conn:
        await conn.execute(
            "INSERT INTO sessions (thread_id, workdir, model, state, server) "
            "VALUES (?, ?, ?, 'idle', ?)",
            (thread_id, workdir, model, server),
        )
        await conn.commit()

# get_resumable_sessions already returns all columns via SELECT *
# but explicit column list is safer — ensure server is included
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| NDJSON text over TCP (initial architecture research doc) | 4-byte length prefix + msgspec msgpack | Phase 6 CONTEXT.md decision | Binary, validated, schema-enforced — NDJSON is out |
| Shared ClaudeSDKClient across sessions | One per SessionRunner (anti-pattern from ARCHITECTURE.md) | Established in Phase 2 | Not changing — maintaining |
| asyncio.get_event_loop().create_future() | asyncio.get_running_loop().create_future() | Python 3.10+ (Python 3.14 project) | Already correct in PermissionManager |

---

## Open Questions

1. **Worker config: how does worker know which server name to use?**
   - What we know: CONTEXT.md says bot uses `server-name` to look up worker connection; worker connects and sends its `worker_id` in auth.
   - What's unclear: Does worker_id == server_name? Or does the user configure the server name independently?
   - Recommendation: Use `WORKER_ID` env var on the worker side; this becomes the server name the user specifies in `/new ... server-name`. Simple: `WORKER_ID=myserver python -m src.worker`.

2. **MCP tools on the worker: do they call bot over TCP or stay in-process?**
   - What we know: Current `create_telegram_mcp_server` takes a real `Bot` instance and calls it directly. Worker has no aiogram Bot.
   - Recommendation: Worker's MCP tools send TCP messages (`McpSendMessageMsg`, etc.) via the `WorkerClient` singleton. The bot receives them in its IPC message handler and calls `bot.send_message(...)`. This is cleaner than spawning an aiogram bot on every worker.

3. **Resume after worker reconnect: session state recovery**
   - What we know: STATE.md flags this as a blocker ("in-flight permission requests on TCP disconnect").
   - Recommendation: On reconnect, worker iterates its local `_sessions` dict and for each session with `session_id`, sends `SessionStartedMsg(topic_id, session_id)` to re-register. Bot's `RemoteSession` state is updated. The `ClaudeSDKClient` in the worker was never stopped — it kept running. Permission futures that were pending get cancelled via `on_disconnected`.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24 |
| Config file | `pyproject.toml` → `[tool.pytest.ini_options]` asyncio_mode = "auto" |
| Quick run command | `pytest tests/test_ipc.py -x` |
| Full suite command | `pytest tests/ -x` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MSRV-01 | Worker SessionRunner starts and runs locally | unit | `pytest tests/test_worker.py::test_worker_session_runner -x` | ❌ Wave 0 |
| MSRV-02 | Auth handshake: valid token → auth_ok, invalid → auth_fail + close | unit | `pytest tests/test_ipc.py::test_auth_handshake -x` | ❌ Wave 0 |
| MSRV-03 | Length-prefix framing: encode/decode round-trip for all Struct types | unit | `pytest tests/test_ipc.py::test_protocol_roundtrip -x` | ❌ Wave 0 |
| MSRV-04 | Worker forwards AssistantTextMsg → bot calls send_message | integration | `pytest tests/test_ipc.py::test_worker_forwards_text -x` | ❌ Wave 0 |
| MSRV-05 | Bot sends UserMessageMsg → worker enqueues to SessionRunner | integration | `pytest tests/test_ipc.py::test_bot_forwards_user_message -x` | ❌ Wave 0 |
| MSRV-06 | Reconnect: client retries with backoff, resets delay on success | unit | `pytest tests/test_worker.py::test_reconnect_backoff -x` | ❌ Wave 0 |
| MSRV-07 | SessionManager.get() returns RemoteSession for remote thread_id | unit | `pytest tests/test_session_routing.py::test_remote_routing -x` | ❌ Wave 0 |
| MSRV-08 | /new without server-name creates local SessionRunner (existing path) | unit | `pytest tests/test_session_routing.py::test_local_default -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `pytest tests/test_ipc.py -x`
- **Per wave merge:** `pytest tests/ -x`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_ipc.py` — protocol round-trip, auth handshake, framing errors (MSRV-02, MSRV-03, MSRV-04, MSRV-05)
- [ ] `tests/test_worker.py` — WorkerClient reconnect loop, permission bridge (MSRV-01, MSRV-06)
- [ ] `tests/test_session_routing.py` — SessionManager routing, RemoteSession proxy (MSRV-07, MSRV-08)
- [ ] Install msgspec: add `"msgspec>=0.18.0"` to pyproject.toml + `uv sync`

---

## Sources

### Primary (HIGH confidence)
- [msgspec asyncio TCP Key-Value Server example](https://jcristharif.com/msgspec/examples/asyncio-kv.html) — exact length-prefix framing pattern, Struct with tag=True, decoder usage
- [msgspec Structs documentation](https://jcristharif.com/msgspec/structs.html) — tagged unions, discriminated decode, explicit tag values
- Python 3.14 stdlib `asyncio.streams` — `readexactly`, `start_server`, `open_connection` (verified by inspecting source in project venv)
- Existing source code: `src/sessions/runner.py`, `src/sessions/manager.py`, `src/sessions/permissions.py`, `src/bot/dispatcher.py`, `src/db/schema.py` — direct inspection of code to reuse

### Secondary (MEDIUM confidence)
- [msgspec PyPI page](https://pypi.org/project/msgspec/) — current version 0.18.6 (March 2025)
- `.planning/research/ARCHITECTURE.md` — original architecture decisions, data flow diagrams, protocol message table

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — msgspec official docs verified via WebFetch; asyncio API verified via Python source inspection
- Architecture: HIGH — derived directly from existing codebase analysis and CONTEXT.md locked decisions
- Pitfalls: HIGH — derived from existing codebase patterns + official msgspec docs

**Research date:** 2026-03-25
**Valid until:** 2026-09-25 (msgspec API is stable; asyncio streams API is stable in CPython)
