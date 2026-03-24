# Phase 2: Session Lifecycle - Context

**Gathered:** 2026-03-24
**Status:** Ready for planning

<domain>
## Phase Boundary

Delivers the core session management: ClaudeSDKClient wrapper with state machine, /new /stop /list commands, message routing from Telegram to Claude and back, session persistence in SQLite, auto-resume on bot restart, and health monitoring for zombie cleanup.

</domain>

<decisions>
## Implementation Decisions

### Session Creation Flow
- `/new` command auto-creates a Telegram forum topic via `createForumTopic` API — no manual topic creation needed
- No model parameter on `/new` — use default model from config (keep simple)
- System prompt for sessions: project CLAUDE.md content + "You are helping in directory {workdir}"
- If `/new` called when session already exists for a topic: error "Session already active, use /stop first"

### Session Communication
- Each Telegram message → `client.query(text)` — one turn at a time, simple and predictable
- Claude's text output sent immediately as received from `AssistantMessage.content[TextBlock]`
- `/clear`, `/compact`, `/reset` mapped to `client.query("/clear")` etc. — let Claude handle internally
- Messages queued if Claude is already processing — send after current turn completes (ResultMessage received)

### Session Persistence & Health
- Auto-resume on bot restart: resume ALL sessions that were `running` or `idle` when bot stopped
- Health check every 60 seconds — verify Claude subprocess is alive
- Zombie sessions: kill process, mark session `stopped`, notify topic with error message
- SQLite session columns: session_id, thread_id, workdir, model, state, created_at, updated_at

### Claude's Discretion
- SessionRunner internal implementation details (asyncio task management, error handling patterns)
- SessionManager data structures and concurrency approach
- Exact message formatting for Claude responses in Telegram
- How to handle `client.interrupt()` on /stop (drain receive_response or not)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/bot/dispatcher.py` — `build_dispatcher()` with on_startup hook, ready for session manager init
- `src/bot/routers/general.py` — General topic router, add /new /list commands here
- `src/bot/routers/session.py` — Session topic router, add message forwarding and /stop here
- `src/db/schema.py` — `init_db()` with sessions table already defined
- `src/db/connection.py` — `get_connection()` async context manager
- `src/config.py` — Settings with BOT_TOKEN, OWNER_USER_ID, GROUP_CHAT_ID, AUTH_TOKEN

### Established Patterns
- aiogram 3 Router pattern with `@router.message()` decorators
- Outer middleware for auth (OwnerAuthMiddleware)
- aiosqlite with WAL mode for async DB access
- pydantic-settings for typed config

### Integration Points
- `build_dispatcher()` on_startup — add SessionManager initialization
- `general_router` — add /new, /list command handlers
- `session_router` — add message handler that forwards to ClaudeSDKClient
- sessions table in SQLite — persist session_id, state, workdir

</code_context>

<specifics>
## Specific Ideas

- ClaudeSDKClient requires `can_use_tool` callback — Phase 3 handles full permission system, but Phase 2 needs a placeholder (auto-allow-all or raise NotImplementedError)
- The dummy PreToolUse hook MUST be registered (SDK requirement from research — can_use_tool silently fails without it)
- Session state machine: IDLE → RUNNING → WAITING_PERMISSION → RUNNING → IDLE (WAITING_PERMISSION is Phase 3, stub it)
- `include_partial_messages=True` for future streaming support

</specifics>

<deferred>
## Deferred Ideas

- Full permission system with Telegram buttons (Phase 3)
- Status message updates (Phase 4)
- Voice/file handling (Phase 5)
- Multi-server workers (Phase 6)

</deferred>
