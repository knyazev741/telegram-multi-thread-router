# Pitfalls Research

**Domain:** Telegram bot controlling Claude Code sessions via Agent SDK (Python rewrite)
**Researched:** 2026-03-24
**Confidence:** HIGH (critical pitfalls verified against official SDK docs and known GitHub issues)

---

## Critical Pitfalls

### Pitfall 1: `can_use_tool` silently drops if the dummy PreToolUse hook is missing

**What goes wrong:**
The `can_use_tool` callback is never invoked. Claude requests a tool, the stream closes before the permission callback fires, and the session appears to hang or silently deny the tool without calling your handler. No error is raised.

**Why it happens:**
In the Python SDK, `can_use_tool` only works when the underlying stdio stream is held open. Without a `PreToolUse` hook present, the stream closes as soon as the CLI would normally prompt for input. The official docs label this a "required workaround" — it is an acknowledged design flaw (GitHub issue #18735, January 2026).

**How to avoid:**
Always register a pass-through `PreToolUse` hook alongside `can_use_tool`:

```python
async def _keep_stream_open(input_data, tool_use_id, context):
    return {"continue_": True}

options = ClaudeAgentOptions(
    can_use_tool=handle_permission,
    hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_keep_stream_open])]},
)
```

This is not optional — it is required for every session that uses interactive permissions.

**Warning signs:**
- Permission request messages never appear in Telegram
- Claude seems to proceed immediately or stall without ever calling your handler
- No exception, just silence or a timeout

**Phase to address:** Session Worker setup — very first working session must validate this with a test tool call.

---

### Pitfall 2: `can_use_tool` callback blocks the entire worker indefinitely when user never responds

**What goes wrong:**
The `can_use_tool` callback `await`s a future that resolves when the Telegram user clicks a button. If the user never responds (closed app, disconnected, distracted), the Claude subprocess is permanently blocked: it holds the tool call open, no timeout fires, and the session is frozen. No more output arrives, no cleanup runs.

**Why it happens:**
The SDK pauses the agent loop until `can_use_tool` returns. There is no built-in timeout in the callback protocol. If your async code `await`s indefinitely, so does the agent.

**How to avoid:**
Every `can_use_tool` implementation must use `asyncio.wait_for` with a hard timeout (e.g., 5 minutes):

```python
async def can_use_tool(tool_name, input_data, context):
    try:
        result = await asyncio.wait_for(
            wait_for_user_response(tool_name, input_data),
            timeout=300.0  # 5 minutes
        )
        return result
    except asyncio.TimeoutError:
        return PermissionResultDeny(
            message="Permission request timed out — user did not respond within 5 minutes"
        )
```

Also send a timeout notification to the user's Telegram thread so they know the session auto-denied.

**Warning signs:**
- Sessions stuck in "working" state for hours
- `ClaudeSDKClient` not producing any new events
- Pending permission entry in DB never resolving

**Phase to address:** Permission Manager implementation phase. Timeout must be part of the initial design, not added later.

---

### Pitfall 3: Session resume silently starts a fresh session when `cwd` doesn't match

**What goes wrong:**
You call `resume=session_id` expecting to continue a prior session, but Claude starts from scratch with no prior context. No error is raised. The user sees Claude forgetting everything.

**Why it happens:**
Sessions are stored at `~/.claude/projects/<encoded-cwd>/<session-id>.jsonl` where the directory path is encoded into the storage path. If the worker starts with a different `cwd` than when the session was created, the SDK looks in the wrong directory and silently creates a new session.

**How to avoid:**
- Store the working directory alongside the session ID in SQLite
- Pass the exact same `cwd` when spawning `ClaudeSDKClient` for a resumed session
- Validate that the session file exists before telling the user "resuming session"

```python
# When creating a session
session_id = result.session_id
db.save_session(topic_id, session_id, cwd=str(working_dir))

# When resuming
session = db.get_session(topic_id)
client = ClaudeSDKClient(options=options, cwd=Path(session.cwd))
await client.query(..., resume=session.session_id)
```

**Warning signs:**
- Users complain Claude "forgot" the project context after bot restart
- Session IDs in DB are valid but sessions behave as fresh starts

**Phase to address:** Session lifecycle phase (create/resume/stop).

---

### Pitfall 4: Claude subprocess leaves zombie processes on failed initialization

**What goes wrong:**
`ClaudeSDKClient.connect()` hangs during the initialization handshake. After a timeout, the failed process is abandoned but not killed. Repeated reconnect attempts accumulate zombie `claude` processes that eventually block new connections or exhaust file descriptors.

**Why it happens:**
The SDK spawns the Claude CLI as a subprocess and waits for the init handshake over stdio. If initialization times out (network issue, process crash, auth problem), the subprocess is not guaranteed to be cleaned up. Each retry spawns another orphan. This is a documented issue (GitHub issue #18666 on anthropics/claude-code).

**How to avoid:**
Wrap `ClaudeSDKClient` initialization in a timeout with explicit process cleanup:

```python
async def create_worker_session(options, cwd):
    client = ClaudeSDKClient(options=options, cwd=cwd)
    try:
        await asyncio.wait_for(client.__aenter__(), timeout=30.0)
        return client
    except asyncio.TimeoutError:
        # Force-kill subprocess if it exists
        if hasattr(client, '_process') and client._process:
            client._process.terminate()
            await asyncio.sleep(1)
            client._process.kill()
        raise RuntimeError("Claude session initialization timed out")
```

Periodically run `ps aux | grep claude` in a health-check task to detect accumulated zombies.

**Warning signs:**
- `ps aux` shows many `claude` processes accumulating
- New sessions fail to start after several failed attempts
- File descriptor exhaustion errors in logs

**Phase to address:** Session Worker setup and health monitoring phase.

---

### Pitfall 5: TCP message framing — partial reads cause silent protocol corruption

**What goes wrong:**
The central bot receives a half-written JSON message from a worker over TCP, passes the partial data to `json.loads()`, and either crashes with a parse error or — worse — silently truncates an event. If the crash is swallowed, subsequent messages are misaligned and the session produces garbage.

**Why it happens:**
TCP is a stream protocol. A single `await reader.read(4096)` call can return any number of bytes: half a message, one message, or three messages. Developers who test on localhost (where TCP behaves like a pipe) never see this until a slow network or large payload triggers it in production.

**How to avoid:**
Use length-prefixed framing for every message. Sender prepends a 4-byte big-endian length, receiver reads exactly that many bytes:

```python
# Sender
async def send_message(writer, payload: dict):
    data = json.dumps(payload).encode()
    writer.write(len(data).to_bytes(4, 'big') + data)
    await writer.drain()

# Receiver
async def recv_message(reader) -> dict:
    length_bytes = await reader.readexactly(4)
    length = int.from_bytes(length_bytes, 'big')
    data = await reader.readexactly(length)
    return json.loads(data)
```

`readexactly()` raises `asyncio.IncompleteReadError` on connection close, which is the correct signal to trigger reconnection.

**Warning signs:**
- `json.JSONDecodeError` in bot logs intermittently
- Events appear truncated or events from different sessions appear merged
- Only happens under load or with large file payloads

**Phase to address:** TCP transport layer — must be built correctly from day one.

---

### Pitfall 6: Status message edits hit the 20-edits-per-minute Telegram limit

**What goes wrong:**
The status updater edits the persistent status message every 30 seconds per session. With several active sessions, the bot exceeds Telegram's limit of 20 `editMessageText` calls per minute per chat, receiving `TelegramRetryAfter` errors. If not handled, aiogram raises an exception that kills the update loop for all sessions.

**Why it happens:**
20 edits/minute = one edit every 3 seconds across all topics in the group. With 4+ active sessions each editing every 30s, you hit 8 edits/min — fine. But during bursts (session start, parallel tool calls), multiple status updates can cluster.

**How to avoid:**
- Catch `TelegramRetryAfter` and respect the `retry_after` value
- Implement a shared per-group edit rate limiter using an `asyncio.Semaphore` or token bucket
- Consider coalescing rapid status updates: only edit if the status text actually changed

```python
from aiogram.exceptions import TelegramRetryAfter

async def safe_edit_message(bot, chat_id, message_id, text):
    while True:
        try:
            await bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
            return
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 0.5)
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return  # Not an error — content unchanged
            raise
```

**Warning signs:**
- `TelegramRetryAfter` in logs during active sessions
- Status messages stop updating silently
- Multiple sessions showing stale status

**Phase to address:** Status Updater implementation phase.

---

### Pitfall 7: Stale inline keyboard buttons after session completes or bot restarts

**What goes wrong:**
A permission request message with numbered buttons is sent. The session completes, the bot restarts, or the permission times out. The user then clicks a button from the old message. The callback query arrives but has no matching pending permission entry in memory (or DB). The bot fails to `answer_callback_query`, leaving the Telegram client showing a spinner indefinitely.

**Why it happens:**
Telegram delivers callback queries for inline keyboards forever (or at least for a very long time after the message was sent). Bots that only track pending permissions in memory lose all state on restart. Bots that forget to call `answer_callback_query` even on stale buttons cause client-side UX hangs.

**How to avoid:**
- Always call `answer_callback_query` immediately for every callback, even if it's stale:

```python
@router.callback_query()
async def handle_permission_callback(query: CallbackQuery):
    await query.answer()  # ALWAYS call this first, unconditionally

    permission = await db.get_pending_permission(query.data)
    if not permission:
        await query.answer("This request has already been handled or expired.", show_alert=True)
        return
    # ... process permission
```

- Store pending permissions in SQLite with status (pending/resolved/expired), not only in memory
- On resolution, edit the original message to remove the keyboard and show result

**Warning signs:**
- Telegram clients show loading spinner when clicking old buttons
- `aiogram.exceptions.TelegramBadRequest: query is too old` in logs

**Phase to address:** Permission Manager implementation phase.

---

### Pitfall 8: Forum topic `message_thread_id` confusion — messages land in wrong topic

**What goes wrong:**
A message sent without `message_thread_id` goes to the General topic. A message sent with the wrong `message_thread_id` silently succeeds but appears in the wrong thread. With multi-session routing, this means one session's output can appear in another session's topic.

**Why it happens:**
Two common confusions:
1. `reply_to_message_id` (reply to a specific message) vs `message_thread_id` (which topic to post in) — these are different fields and easy to swap.
2. When replying to a message within a topic, the bot must set `message_thread_id` to the topic's thread ID, not the message being replied to.

**How to avoid:**
- Store `message_thread_id` in the session record at creation time, never derive it from incoming message
- In all `send_message` / `send_document` calls, explicitly pass `message_thread_id=session.thread_id`
- Write a thin wrapper that enforces this:

```python
async def send_to_session(bot, session, text, **kwargs):
    """Always sends to the correct thread. Never call bot.send_message directly."""
    return await bot.send_message(
        chat_id=session.chat_id,
        message_thread_id=session.thread_id,
        text=text,
        **kwargs
    )
```

**Warning signs:**
- Messages appearing in General topic instead of expected session topic
- Wrong session receiving output from another Claude instance
- Users reporting mixed-up responses

**Phase to address:** Telegram Handler and Session Manager setup (day one).

---

### Pitfall 9: SQLite concurrent write contention with async workers

**What goes wrong:**
Multiple asyncio tasks writing to the same SQLite database simultaneously cause `sqlite3.OperationalError: database is locked` errors. This happens under load when the session manager, permission manager, status updater, and TCP handler all try to write concurrently.

**Why it happens:**
SQLite uses a database-level write lock. `aiosqlite` wraps sqlite3 in a thread but doesn't solve write contention — it just moves blocking to that thread. Multiple coroutines acquiring separate connections then attempting simultaneous writes collide on the file lock.

**How to avoid:**
- Enable WAL (Write-Ahead Logging) mode at DB initialization — this allows concurrent reads alongside writes and dramatically reduces contention:

```python
async def init_db(db_path):
    async with aiosqlite.connect(db_path) as db:
        await db.execute("PRAGMA journal_mode=WAL")
        await db.execute("PRAGMA synchronous=NORMAL")
        await db.execute("PRAGMA busy_timeout=5000")  # Wait up to 5s before SQLITE_BUSY
        await db.commit()
```

- Use a single long-lived connection (not per-request) managed through a mutex:

```python
class Database:
    def __init__(self, path):
        self._path = path
        self._conn = None
        self._lock = asyncio.Lock()

    async def execute(self, sql, params=()):
        async with self._lock:
            return await self._conn.execute(sql, params)
```

**Warning signs:**
- `OperationalError: database is locked` in logs under any real load
- Missing events in DB (swallowed write errors)
- Session state inconsistencies

**Phase to address:** Database layer — before any async write patterns are established.

---

### Pitfall 10: faster-whisper OOM on long or concurrent voice messages

**What goes wrong:**
A voice note longer than ~2 minutes (or several arriving simultaneously) causes the transcription process to run out of memory and crash. The OOM kill is silent from the Telegram handler's perspective, leaving the user with no feedback.

**Why it happens:**
Whisper has a 30-second receptive field and uses a sliding window for longer audio. Memory grows proportionally with audio length and can spike during chunking. Loading multiple model instances concurrently multiplies memory use. Documented in faster-whisper GitHub issue #249.

**How to avoid:**
- Use a semaphore to limit concurrent transcriptions to 1 (single-server use case):

```python
_transcription_semaphore = asyncio.Semaphore(1)

async def transcribe_voice(audio_path: Path) -> str:
    async with _transcription_semaphore:
        return await asyncio.get_event_loop().run_in_executor(
            None, _do_transcribe, audio_path
        )
```

- Set a max audio duration check before transcription (e.g., reject files over 10 minutes)
- Run transcription in a subprocess or separate thread pool to isolate OOM from the main bot process
- Use the `small` model by default (the existing codebase already does this — do not change to `medium` or `large` without memory profiling)

**Warning signs:**
- Bot process crashes without traceback (OOM kill)
- Long voice messages never produce a reply
- Memory usage climbs during transcription and doesn't fully return

**Phase to address:** Voice transcription feature phase.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Store pending permissions in memory only | No DB schema needed | All pending permissions lost on restart; users get stuck spinners | Never — restart scenarios are real |
| Skip `answer_callback_query` for stale callbacks | Simpler handler | Telegram client spins forever; user confusion | Never |
| Use `asyncio.sleep(30)` polling for status updates | Simple | Doesn't coalesce rapid changes; wastes edit quota | Acceptable in MVP if rate limiter wraps it |
| One aiosqlite connection per request | Simpler code | Write lock contention under any load | Never — use a shared connection with lock |
| Hard-code `message_thread_id` from incoming message | Simpler routing | Breaks if messages arrive from other topics | Never — store at session creation |
| Skip length-prefixed framing, use newline-delimited JSON | Faster to write | Silent corruption on large payloads or slow network | Only for localhost-only single-machine mode |
| No timeout on `can_use_tool` callback | Simpler implementation | Sessions hang forever on unresponsive users | Never |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| Claude Agent SDK Python | Using `can_use_tool` without the dummy PreToolUse hook | Always register `HookMatcher(matcher=None, hooks=[keep_stream_open])` alongside `can_use_tool` |
| Claude Agent SDK sessions | Not storing `cwd` with session ID | Store cwd in SQLite; pass exact same path on resume |
| Telegram editMessageText | Not catching `message is not modified` as a non-error | Treat `TelegramBadRequest("message is not modified")` as success, not failure |
| Telegram callback queries | Calling `answer_callback_query` after doing async work | Call `await query.answer()` as first line of every callback handler |
| Telegram forum topics | Using `reply_to_message_id` to route to a topic | Use `message_thread_id` for topic routing; `reply_to_message_id` is only for threading within a topic |
| aiosqlite | Opening a new connection per operation | Maintain a single shared connection with an `asyncio.Lock` |
| faster-whisper | Loading model for each request | Load model once at startup and keep in memory; use semaphore for concurrent access |
| TCP protocol | Using `reader.read(N)` for message parsing | Use `readexactly()` with length-prefix framing |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Editing status message every 30s without rate limiting | `TelegramRetryAfter` errors; status stops updating | Token bucket limiter per group chat | 4+ concurrent active sessions |
| Loading faster-whisper model on demand | 5-10 second delay before transcription starts | Load at startup, keep warm | Every voice message |
| Unbounded status update queue | Memory growth if status events arrive faster than they're edited | Fixed-size queue with latest-wins semantics | Long-running sessions with many tool calls |
| Creating new DB connection per request | Connection overhead, lock contention | Single persistent connection + lock | >5 concurrent writes/second |
| No session cleanup for terminated Claude processes | Zombie sessions in DB that never resolve | Health check task that detects and cleans dead sessions | After any crash or network partition |

---

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| Not checking `OWNER_USER_ID` before processing messages | Any Telegram user can trigger Claude sessions | Middleware that rejects all non-owner messages before routing |
| Logging full `can_use_tool` input (which may contain file contents) | Secrets in logs | Log tool name and summary only; never log `input_data` contents verbatim |
| Sending worker-to-bot auth token in plaintext over TCP | Token interception on shared networks | Use a pre-shared `AUTH_TOKEN` validated on every message; consider TLS for non-localhost workers |
| Allowing Bash tool without command filtering | Arbitrary code execution by Claude | Use `disallowed_tools` or `can_use_tool` review for dangerous patterns; never `bypassPermissions` |
| Storing session files outside project directory | Session files may contain sensitive command history | Ensure `cwd` always points to an isolated working directory per session |

---

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| No confirmation when `can_use_tool` times out | User doesn't know session is stuck | Send a message: "Permission request timed out. Claude has auto-denied. Reply to restart." |
| Sending "Session started" then nothing for 30s while Claude initializes | User thinks bot is broken | Send typing indicator immediately; follow with status message once subprocess is ready |
| Splitting long Claude output at 4096 chars mid-sentence or mid-code-block | Garbled output; broken code blocks | Split at paragraph boundaries; never split inside a fenced code block |
| Editing buttons away immediately on any click (not just valid ones) | Double-click or network retry removes keyboard before first click is processed | Only remove/update keyboard after successfully processing the permission in DB |
| No indicator that Claude is waiting for permission | User sees no activity, thinks it crashed | Status message must show "Waiting for your approval" state |

---

## "Looks Done But Isn't" Checklist

- [ ] **Permission handling:** `can_use_tool` fires correctly — verify by running a session that requires `Bash` permission and confirming the Telegram message appears
- [ ] **Permission timeout:** sessions auto-deny and notify the user after timeout — verify by not clicking any button for 5+ minutes
- [ ] **Session resume:** after bot restart, existing sessions re-attach correctly — verify session ID and cwd are both stored and used
- [ ] **Stale button handling:** clicking a button from a completed session calls `answer_callback_query` without crashing — verify by completing a session then clicking old buttons
- [ ] **TCP reconnect:** worker reconnects to bot after bot restart without manual intervention — verify by restarting bot mid-session
- [ ] **Status edit rate limit:** with 5 concurrent sessions, status updates don't throw `TelegramRetryAfter` — verify under simulated load
- [ ] **Forum topic routing:** messages from different topics route to different sessions — verify by running two sessions simultaneously in different topics
- [ ] **Voice OOM:** a 5-minute voice message transcribes without crashing the bot process — verify with actual long audio
- [ ] **SQLite WAL mode:** DB writes don't throw `database is locked` under concurrent access — verify with multiple sessions writing simultaneously

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Zombie Claude processes accumulated | LOW | Add `pkill -f "claude"` to worker startup; detect via health check |
| Permission callback hung, session frozen | LOW | Send `/stop` command; implement session interrupt via `client.interrupt()` |
| Session resume silently starting fresh | MEDIUM | Verify cwd in DB; match against current worker path; may need session recreation |
| SQLite locked under load | MEDIUM | Restart bot; enable WAL + busy_timeout prevents recurrence |
| TCP message corruption | HIGH | Full reconnect; events lost since last corruption point; session may need restart |
| Status updater rate-limited and silently stopped | LOW | Catch `TelegramRetryAfter` with retry loop; self-healing |
| Voice transcription OOM killed bot | MEDIUM | Bot restarts via process supervisor (systemd); active sessions reconnect via TCP |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| `can_use_tool` requires dummy hook | Session Worker setup (Phase 1) | Test permission callback fires in integration test |
| Permission callback no timeout | Permission Manager (Phase 2) | Manually leave permission unanswered for >5 min |
| Session resume `cwd` mismatch | Session lifecycle (Phase 2) | Restart bot, verify session resumes with full context |
| Zombie subprocess accumulation | Session Worker setup + health monitor (Phase 1/4) | Repeatedly fail initialization, check `ps` |
| TCP partial reads | TCP transport layer (Phase 1) | Send large payload (>4KB), verify no corruption |
| Status edit rate limit | Status Updater (Phase 3) | Run 5+ concurrent sessions, verify no errors |
| Stale inline keyboard buttons | Permission Manager (Phase 2) | Restart bot, click old permission button |
| Forum topic `message_thread_id` routing | Telegram Handler (Phase 1) | Run two parallel sessions, verify message isolation |
| SQLite concurrent write contention | Database layer (Phase 1) | Concurrent write load test |
| Voice transcription OOM | Voice feature phase (Phase 3) | Long audio file test |

---

## Sources

- [Claude Agent SDK — Handle approvals and user input](https://platform.claude.com/docs/en/agent-sdk/user-input) — `can_use_tool` callback behavior, dummy hook requirement
- [Claude Agent SDK — Work with sessions](https://platform.claude.com/docs/en/agent-sdk/sessions) — session resume, `cwd` matching, persistence
- [Claude Agent SDK — Configure permissions](https://platform.claude.com/docs/en/agent-sdk/permissions) — permission modes, evaluation order
- [GitHub issue #18735 — Python `can_use_tool` dummy hook design flaw](https://github.com/anthropics/claude-code/issues/18735) — confirmed January 2026
- [GitHub issue #18666 — SDK subprocess hangs leaving zombie processes](https://github.com/anthropics/claude-code/issues/18666)
- [GitHub issue — `canUseTool` not working #227](https://github.com/anthropics/claude-agent-sdk-python/issues/227) — known callback skip in multi-turn
- [aiogram 3 — TelegramRetryAfter strategy discussion](https://github.com/aiogram/aiogram/discussions/1489)
- [faster-whisper — High Memory Use issue #249](https://github.com/guillaumekln/faster-whisper/issues/249) — OOM on long audio
- [aiosqlite — Concurrent write contention patterns](https://www.sqlpey.com/python/top-5-methods-to-handle-sqlite3-concurrency-issues-in-python/)
- [Python docs — asyncio CancelledError propagation](https://docs.python.org/3/library/asyncio-task.html)
- [Telegram core API — Threads and forum topics](https://core.telegram.org/api/threads)
- [grammY — Flood limits deep-dive](https://grammy.dev/advanced/flood) — 20 message edits/min per group

---
*Pitfalls research for: Python Telegram bot + Claude Agent SDK (multi-session forum router)*
*Researched: 2026-03-24*
