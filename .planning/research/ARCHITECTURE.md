# Architecture Research

**Domain:** Telegram bot + distributed Claude Agent SDK worker system
**Researched:** 2026-03-24
**Confidence:** HIGH (Claude Agent SDK docs verified via official source, aiogram patterns from official docs)

## Standard Architecture

### System Overview

```
┌──────────────────────────────────────────────────────────────┐
│                        Central Bot Process                    │
│                    (Python, aiogram 3, single host)          │
├──────────────────────────────────────────────────────────────┤
│  ┌───────────────┐  ┌─────────────────┐  ┌───────────────┐  │
│  │ Telegram      │  │  Session        │  │  Permission   │  │
│  │ Dispatcher    │  │  Manager        │  │  Manager      │  │
│  │ (handlers,    │  │  (topic→worker  │  │  (pending     │  │
│  │  middleware)  │  │   routing)      │  │   callbacks)  │  │
│  └──────┬────────┘  └────────┬────────┘  └──────┬────────┘  │
│         │                   │                   │           │
│  ┌──────▼───────────────────▼───────────────────▼────────┐  │
│  │                     IPC Server                         │  │
│  │              asyncio TCP (port 9000)                   │  │
│  │         Newline-delimited JSON, AUTH_TOKEN             │  │
│  └──────────────────────────┬─────────────────────────────┘  │
│                             │                                │
│  ┌──────────────────────────▼─────────────────────────────┐  │
│  │                   SQLite (aiosqlite)                    │  │
│  │         topics | sessions | message_history             │  │
│  └────────────────────────────────────────────────────────┘  │
└─────────────────────────────┬────────────────────────────────┘
                              │  TCP connections (one per worker)
         ┌────────────────────┼────────────────────┐
         │                    │                    │
┌────────▼──────┐    ┌────────▼──────┐    ┌────────▼──────┐
│  Worker A     │    │  Worker B     │    │  Worker N     │
│  (server-1)   │    │  (server-2)   │    │  (server-N)   │
├───────────────┤    ├───────────────┤    ├───────────────┤
│ SessionRunner │    │ SessionRunner │    │ SessionRunner │
│  (one per     │    │  (one per     │    │  (one per     │
│   topic)      │    │   topic)      │    │   topic)      │
├───────────────┤    └───────────────┘    └───────────────┘
│ ClaudeSDK-    │
│ Client        │
│ (subprocess)  │
├───────────────┤
│ MCP Tools     │
│ reply/react/  │
│ send_file/    │
│ edit_message  │
└───────────────┘
```

### Component Responsibilities

| Component | Responsibility | Implementation |
|-----------|----------------|----------------|
| `TelegramDispatcher` | Receive Telegram updates, route to handlers | aiogram 3 Dispatcher + Routers |
| `SessionManager` | Map topic_id → worker connection, maintain session registry | Python class with asyncio.Lock |
| `PermissionManager` | Hold pending `can_use_tool` futures, resolve on button press | Dict keyed by permission_request_id |
| `StatusUpdater` | Edit one pinned message per topic every 30s | asyncio periodic task per session |
| `IPCServer` | Accept worker TCP connections, dispatch messages to managers | asyncio.start_server() |
| `SessionRunner` (worker) | Own one ClaudeSDKClient, forward events to bot, receive commands | asyncio task per session |
| `MCPTools` (worker) | In-process tools: reply, react, edit_message, send_file | create_sdk_mcp_server() |
| `SQLite` (bot) | Persist topics, session IDs, message history | aiosqlite, WAL mode |

---

## Recommended Project Structure

```
bot/
├── main.py                  # Entry point: start bot + IPC server
├── config.py                # Settings from .env (pydantic-settings)
├── db/
│   ├── schema.sql           # Table definitions
│   ├── connection.py        # aiosqlite pool setup
│   └── queries.py           # Named query functions (no raw SQL in handlers)
├── handlers/
│   ├── router.py            # Compose all routers
│   ├── messages.py          # Text/voice/file messages from owner
│   ├── commands.py          # /start, /stop, /list, /clear, /compact
│   └── callbacks.py         # Inline button presses (permission responses)
├── managers/
│   ├── session_manager.py   # topic_id → WorkerConnection mapping
│   ├── permission_manager.py# Pending permission futures
│   └── status_updater.py    # Periodic message editing
├── ipc/
│   ├── server.py            # asyncio TCP server, connection registry
│   ├── protocol.py          # Message framing (NDJSON), type definitions
│   └── handlers.py          # Dispatch incoming worker messages to managers
└── middleware/
    └── owner_check.py       # Reject all updates not from OWNER_USER_ID

worker/
├── main.py                  # Entry point: connect to bot, start sessions
├── config.py                # Bot host/port, auth token, working dir
├── ipc/
│   ├── client.py            # asyncio TCP client, reconnect loop
│   └── protocol.py          # Shared message type definitions
├── session/
│   ├── runner.py            # SessionRunner: ClaudeSDKClient lifecycle
│   └── state.py             # Session state machine (enum + transitions)
└── mcp/
    └── tools.py             # Custom MCP tools: reply, react, send_file
```

### Structure Rationale

- **`bot/` and `worker/` as sibling packages:** They deploy to different hosts; shared code (`ipc/protocol.py`) can be extracted to a `shared/` package or duplicated — duplication is fine at this scale.
- **`managers/` isolated from `handlers/`:** Handlers are thin (parse update, call manager). Managers own state. Avoids state spread across handler files.
- **`ipc/` split from `handlers/`:** The TCP server is infrastructure; message routing to managers is business logic. Separation makes testing easier.
- **`db/queries.py`:** All SQL in one file. No ORM needed for this schema. Avoids the overhead of SQLAlchemy for three tables.

---

## Architectural Patterns

### Pattern 1: Permission Future — Async Bridge Between Two Coroutines

**What:** When a worker's `can_use_tool` callback fires, instead of blocking, it stores an `asyncio.Future` in `PermissionManager`, sends a Telegram message with buttons, and awaits the future. When the user taps a button, the callback handler resolves the future.

**When to use:** Any time user interaction must pause a background coroutine.

**Trade-offs:** Simple and correct for single-owner bots. For multi-user scenarios you'd need per-user queues — not needed here.

**Example:**

```python
# worker/session/runner.py
async def can_use_tool(tool_name, input_data, context):
    request_id = str(uuid.uuid4())
    future = asyncio.get_event_loop().create_future()

    # Send permission request to bot over TCP
    await ipc_client.send({
        "type": "permission_request",
        "request_id": request_id,
        "topic_id": self.topic_id,
        "tool_name": tool_name,
        "input_data": input_data,
    })

    # Block this coroutine until bot resolves the future
    result = await asyncio.wait_for(future, timeout=300)
    return result

# bot/handlers/callbacks.py
@router.callback_query(PermissionCallback.filter())
async def on_permission_button(query: CallbackQuery, callback_data: PermissionCallback):
    await permission_manager.resolve(callback_data.request_id, callback_data.choice)
    await query.answer()
    await query.message.edit_reply_markup(reply_markup=None)

# bot/managers/permission_manager.py
class PermissionManager:
    def __init__(self):
        self._pending: dict[str, asyncio.Future] = {}

    def register(self, request_id: str) -> asyncio.Future:
        future = asyncio.get_event_loop().create_future()
        self._pending[request_id] = future
        return future

    async def resolve(self, request_id: str, choice: int):
        future = self._pending.pop(request_id, None)
        if future and not future.done():
            future.set_result(choice)
```

### Pattern 2: Newline-Delimited JSON over asyncio Streams

**What:** TCP framing using `\n`-terminated JSON lines. Writer calls `json.dumps(msg) + "\n"`, reader uses `reader.readline()`. Simple, debuggable, no binary encoding needed.

**When to use:** Low-volume IPC where human readability matters for debugging. This system sends at most a few messages per second per session.

**Trade-offs:** Not suitable for binary payloads (file transfer goes via Telegram's own upload API). Maximum practical message size ~1MB before readline becomes slow.

**Example:**

```python
# shared: ipc/protocol.py
import json

async def send_message(writer: asyncio.StreamWriter, msg: dict):
    line = json.dumps(msg) + "\n"
    writer.write(line.encode())
    await writer.drain()

async def read_message(reader: asyncio.StreamReader) -> dict | None:
    try:
        line = await reader.readline()
        if not line:
            return None  # connection closed
        return json.loads(line.decode())
    except (json.JSONDecodeError, ConnectionResetError):
        return None
```

### Pattern 3: Worker Reconnect Loop with Exponential Backoff

**What:** The worker TCP client wraps its connection attempt in a `while True` loop with exponential backoff. The bot IPC server maintains a registry of live worker connections identified by `worker_id`.

**When to use:** Any long-running client that must survive bot restarts and network blips.

**Trade-offs:** In-flight permission futures are lost on disconnect. Workers must re-register all active sessions on reconnect. This is acceptable — the user will see the permission request fail and can re-run the command.

**Example:**

```python
# worker/ipc/client.py
async def connect_with_retry(host, port, auth_token):
    delay = 1.0
    while True:
        try:
            reader, writer = await asyncio.open_connection(host, port)
            await send_message(writer, {"type": "auth", "token": auth_token,
                                        "worker_id": WORKER_ID})
            response = await read_message(reader)
            if response.get("type") != "auth_ok":
                raise ValueError("Auth failed")
            delay = 1.0  # reset on success
            return reader, writer
        except Exception as e:
            log.warning(f"Connect failed: {e}, retry in {delay}s")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 60.0)
```

### Pattern 4: Session State Machine (Enum-Based)

**What:** Each `SessionRunner` tracks its own state as an enum. Transitions are explicit. Invalid transitions raise errors immediately rather than producing silent bugs.

**When to use:** Any object whose behavior changes depending on lifecycle phase. The ClaudeSDKClient has states that must be respected (can't send query while one is in-flight, must drain after interrupt).

**States and transitions:**

```
IDLE ──────────── user_message ──────────────► RUNNING
  ▲                                                │
  │                                    ResultMessage or error
  │                                                │
  └────────────────────────────────────────────────┘
                                                   │
                                         user presses /stop
                                                   │
                                                   ▼
IDLE ◄──────── drain complete ──────── INTERRUPTING
```

```python
# worker/session/state.py
from enum import Enum, auto

class SessionState(Enum):
    IDLE = auto()        # waiting for user input
    RUNNING = auto()     # ClaudeSDKClient processing, receive_response() active
    INTERRUPTING = auto()# interrupt() called, draining ResultMessage
    STOPPED = auto()     # session terminated, runner should exit

class SessionRunner:
    def __init__(self, ...):
        self.state = SessionState.IDLE

    async def handle_user_message(self, text: str):
        if self.state != SessionState.IDLE:
            # Reject: already running. Tell user to wait or /stop first.
            return
        self.state = SessionState.RUNNING
        await self.client.query(text)
        await self._drain_response()
        self.state = SessionState.IDLE

    async def handle_stop(self):
        if self.state == SessionState.RUNNING:
            self.state = SessionState.INTERRUPTING
            await self.client.interrupt()
            await self._drain_response()  # must drain after interrupt
        self.state = SessionState.IDLE
```

---

## Data Flow

### Flow 1: User Message → Claude → Telegram Reply

```
User types in Telegram topic
    ↓
aiogram MessageHandler (bot/handlers/messages.py)
    ↓ SessionManager.get_worker(topic_id)
    ↓ IPC: {type: "user_message", topic_id, text}  →  Worker TCP client
                                                            ↓
                                                    SessionRunner.handle_user_message()
                                                            ↓
                                                    ClaudeSDKClient.query(text)
                                                            ↓
                                                    async for msg in receive_response():
                                                      AssistantMessage → text block
                                                            ↓
                                                    IPC: {type: "assistant_message", topic_id, text}
                                                            ↓
Worker TCP → Bot IPC server → SessionManager → bot.send_message(topic_id, text)
```

### Flow 2: Permission Request

```
ClaudeSDKClient calls can_use_tool callback (worker)
    ↓
Worker sends: {type: "permission_request", request_id, topic_id, tool_name, input_data}
    ↓
Bot IPC handler → PermissionManager.register(request_id) → returns Future
Bot sends Telegram message with numbered inline buttons to topic
    ↓ (waits for Future)
User taps button [1️⃣] [2️⃣] [3️⃣]
    ↓
aiogram CallbackQueryHandler → PermissionManager.resolve(request_id, choice)
Future resolves → can_use_tool returns PermissionResultAllow/Deny
    ↓
Bot sends: {type: "permission_response", request_id, choice} to worker
(Worker receive loop unblocks, ClaudeSDKClient continues)
```

### Flow 3: Session Resume After Bot Restart

```
Bot starts → reads SQLite: active sessions with session_id
    ↓
When worker reconnects: bot sends {type: "resume_session", topic_id, session_id, cwd}
    ↓
Worker creates SessionRunner with ClaudeAgentOptions(resume=session_id)
    ↓
Session is live again with full conversation history from Claude's storage
```

### Flow 4: Status Update

```
SessionRunner starts RUNNING state
    ↓
StatusUpdater task activates: every 30s, compose status text from:
  - current_tool (last ToolUseBlock seen in event stream)
  - elapsed_time
  - tool_call_count
    ↓
IPC: {type: "status_update", topic_id, text}
    ↓
Bot edits pinned status message in topic (bot.edit_message_text)
```

### Flow 5: Custom MCP Tool Invocation (reply/react)

```
Claude decides to call mcp__telegram__reply(text="Done!")
    ↓ (in-process, no subprocess)
MCPTools.reply() executes in worker process
    ↓
Sends IPC message: {type: "send_message", topic_id, text}
    ↓
Bot sends Telegram message
    ↓
MCPTools.reply() returns {"content": [{"type": "text", "text": "sent"}]}
ClaudeSDKClient receives tool result, continues
```

---

## IPC Protocol Message Types

Full enumeration of messages that cross the TCP connection.

### Worker → Bot

| Message Type | Fields | Purpose |
|---|---|---|
| `auth` | `token`, `worker_id` | First message on connect, authentication |
| `session_started` | `topic_id`, `session_id` | Session is live, persist session_id to SQLite |
| `assistant_message` | `topic_id`, `text` | Send text to Telegram topic |
| `permission_request` | `request_id`, `topic_id`, `tool_name`, `input_data`, `options[]` | Show permission buttons |
| `status_update` | `topic_id`, `tool_name`, `elapsed_ms`, `tool_calls` | Edit status message |
| `session_ended` | `topic_id`, `error?` | Session finished or crashed |
| `mcp_send_message` | `topic_id`, `text` | MCP tool: reply |
| `mcp_react` | `topic_id`, `message_id`, `emoji` | MCP tool: react |
| `mcp_edit_message` | `topic_id`, `message_id`, `text` | MCP tool: edit |
| `mcp_send_file` | `topic_id`, `file_path`, `caption?` | MCP tool: send file |

### Bot → Worker

| Message Type | Fields | Purpose |
|---|---|---|
| `auth_ok` | `worker_id` | Auth accepted |
| `auth_fail` | `reason` | Auth rejected, worker should exit |
| `start_session` | `topic_id`, `cwd`, `session_id?` | Create new or resume session |
| `stop_session` | `topic_id` | Interrupt and stop session |
| `user_message` | `topic_id`, `text` | Forward Telegram message to Claude |
| `permission_response` | `request_id`, `choice` | User selected option N |
| `slash_command` | `topic_id`, `command` | `/clear`, `/compact`, `/reset` |

---

## Scaling Considerations

This is a single-owner system. Scale means "many concurrent Claude sessions", not "many users."

| Scale | Approach |
|-------|----------|
| 1-10 sessions | Single worker on one server handles all sessions |
| 10-50 sessions | Multiple workers on multiple servers, bot routes by topic |
| 50+ sessions | Unlikely for single-owner; if needed, add worker health reporting and bot-side load balancing |

**First bottleneck:** Telegram's rate limits (30 messages/sec globally, 20/min per chat). The status updater at 30s intervals keeps bot well within limits even with 20 sessions.

**Second bottleneck:** ClaudeSDKClient spawns a subprocess per session. Each session uses ~100-200MB RAM. On a 4GB server: 15-20 concurrent sessions is a practical ceiling.

---

## Anti-Patterns

### Anti-Pattern 1: Blocking the Bot Event Loop on Worker Events

**What people do:** Run the IPC receive loop in the same coroutine as aiogram's polling, using `await reader.read()` that blocks indefinitely.

**Why it's wrong:** Blocks Telegram message processing. Any network hiccup on one worker connection stalls the entire bot.

**Do this instead:** Spawn each worker connection handler as an independent `asyncio.create_task()`. The IPC server callback should immediately create a task for the connection handler loop.

### Anti-Pattern 2: Storing Permission Futures in the Worker

**What people do:** Put the pending futures dict in the worker's `SessionRunner`, requiring the bot to send the resolved choice back to the right worker connection.

**Why it's wrong:** Adds round-trip complexity. The `can_use_tool` callback is already running inside the worker — it can hold its own future. The bot only needs to forward the choice integer.

**Do this instead:** Worker holds the future in `SessionRunner._pending_permissions`. Bot sends `permission_response` over IPC. Worker's IPC receive loop resolves the future. The `can_use_tool` coroutine was awaiting that future and unblocks.

### Anti-Pattern 3: Polling for Session Events Instead of Async Iteration

**What people do:** Call `receive_response()` in a polling loop with `asyncio.sleep(0.1)` between attempts.

**Why it's wrong:** `receive_response()` is an `AsyncIterator`. Polling it incorrectly (restarting iteration) will miss events or cause state corruption.

**Do this instead:** Consume the iterator completely in one `async for` loop per `query()` call. Track current status in instance variables that the status updater reads independently.

### Anti-Pattern 4: Sharing ClaudeSDKClient Across Sessions

**What people do:** Create one `ClaudeSDKClient` per worker process and multiplex multiple topics through it using different `session_id` parameters.

**Why it's wrong:** `ClaudeSDKClient` is a stateful, single-session object. Calling `query()` while another query is in-flight is undefined behavior. Session IDs are assigned by Claude, not passed in.

**Do this instead:** One `ClaudeSDKClient` instance per `SessionRunner`. One `SessionRunner` per topic_id per worker.

### Anti-Pattern 5: Not Draining After interrupt()

**What people do:** Call `interrupt()`, then immediately send a new `query()`.

**Why it's wrong:** Official SDK docs state you must drain the interrupted response stream (including its `ResultMessage`) before sending a new query. Skipping drain causes the next query to receive stale events.

**Do this instead:** After `interrupt()`, always run `async for msg in client.receive_response(): pass` (or handle the ResultMessage) before the next query.

---

## Integration Points

### External Services

| Service | Integration Pattern | Notes |
|---------|---------------------|-------|
| Telegram Bot API | aiogram 3 long polling | No webhooks needed for single-owner |
| Claude Agent SDK | ClaudeSDKClient subprocess | One per session, in worker process |
| faster-whisper | Local inference, worker-side | Voice OGG → text before sending to Claude |
| SQLite | aiosqlite, WAL mode | Bot process only; workers are stateless |

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `TelegramDispatcher ↔ SessionManager` | Direct Python call (same process) | No queue needed |
| `SessionManager ↔ IPCServer` | Direct Python call (same process) | IPCServer calls manager methods on message receipt |
| `PermissionManager ↔ handlers/callbacks.py` | Direct Python call | Handler calls `manager.resolve()` |
| `Bot ↔ Worker` | TCP, NDJSON, AUTH_TOKEN | Cross-host boundary |
| `SessionRunner ↔ ClaudeSDKClient` | asyncio (same event loop) | Both in worker process |
| `SessionRunner ↔ MCPTools` | In-process function call | MCP tools are registered with `create_sdk_mcp_server()` |

---

## Suggested Build Order

Dependencies drive this order. Each phase produces a working system.

1. **IPC Protocol + framing** — Both bot and worker depend on this. Build `protocol.py` (NDJSON send/receive) and message type definitions first.

2. **Bot scaffold: aiogram + owner middleware + SQLite schema** — Bot can receive Telegram messages and persist topics before any worker exists.

3. **IPC Server (bot side) + auth handshake** — Bot can accept worker connections and authenticate them.

4. **Worker TCP client + reconnect loop** — Worker can connect, authenticate, and stay connected.

5. **SessionRunner + ClaudeSDKClient lifecycle (no permissions yet)** — Worker can start a session, accept user messages, forward assistant output back to bot. Use `allowed_tools` auto-approve for initial testing.

6. **Custom MCP tools (reply, react, send_file)** — Claude can send Telegram messages from its own tool calls. Depends on step 5.

7. **Permission system** — `can_use_tool` callback, bot button rendering, future resolution. Depends on step 5.

8. **Status updater** — Periodic message edits. Depends on step 5 (needs session event stream).

9. **Session persistence + resume** — Store session_id in SQLite, pass `resume=` option on restart. Depends on steps 2 and 5.

10. **Voice transcription** — Worker-side faster-whisper, converts OGG before sending to Claude. Standalone, add last.

---

## Sources

- [Claude Agent SDK Python Reference](https://platform.claude.com/docs/en/agent-sdk/python) — ClaudeSDKClient API, event types, can_use_tool signature, MCP creation, session resume (HIGH confidence)
- [Claude Agent SDK Overview](https://platform.claude.com/docs/en/agent-sdk/overview) — Capabilities, hooks, subagents, permissions (HIGH confidence)
- [aiogram 3 Middleware Documentation](https://docs.aiogram.dev/en/latest/dispatcher/middlewares.html) — Outer/inner middleware, Dispatcher + Router architecture (HIGH confidence)
- [aiogram 3 Callback Data Factory](https://docs.aiogram.dev/en/dev-3.x/dispatcher/filters/callback_data.html) — Typed callback data pattern for inline keyboards (HIGH confidence)
- [Python asyncio Streams](https://docs.python.org/3/library/asyncio-stream.html) — StreamReader/StreamWriter, readline(), drain() (HIGH confidence)

---
*Architecture research for: Telegram Multi-Thread Router v2*
*Researched: 2026-03-24*
