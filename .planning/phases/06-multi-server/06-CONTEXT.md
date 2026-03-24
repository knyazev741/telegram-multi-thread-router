# Phase 6: Multi-Server - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning

<domain>
## Phase Boundary

Delivers multi-server support: remote worker processes that manage ClaudeSDKClient locally, authenticated TCP connection to central bot, event forwarding protocol, and bot-side worker registry with session-to-worker routing.

</domain>

<decisions>
## Implementation Decisions

### Worker Architecture
- TCP framing: 4-byte length prefix + msgspec-encoded payload (binary, validated)
- Auth handshake: first message {type: "auth", token: AUTH_TOKEN} — server validates, drops on fail
- Worker reconnection: exponential backoff 1s → 2s → 4s → 8s... max 60s
- Worker entry point: `python -m src.worker` — standalone script

### Bot-Side Routing
- /new name workdir server-name — server-name maps to registered worker connection
- Local sessions (no server specified): in-process SessionRunner — current behavior unchanged
- Worker disconnect mid-session: mark "disconnected", notify topic, auto-reconnect restores session
- /list shows server name + connection status per session

### Claude's Discretion
- TCP protocol message type definitions (exact msgspec Struct schemas)
- Worker-side SessionRunner reuse vs new wrapper
- How to forward permission requests/responses over TCP
- How to forward MCP tool calls over TCP

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `src/sessions/runner.py` — SessionRunner with full lifecycle (reuse on worker side)
- `src/sessions/manager.py` — SessionManager with create/get/stop/list
- `src/sessions/permissions.py` — PermissionManager (needs to bridge over TCP)
- `src/bot/status.py` — StatusUpdater (bot-side only, receives events from worker)
- `src/bot/output.py` — split_message, TypingIndicator (bot-side)

### Established Patterns
- asyncio streams for TCP (asyncio.start_server, asyncio.open_connection)
- msgspec for serialization (already in dependencies)
- DI pattern through dispatcher for singleton services

### Integration Points
- SessionManager needs to route to remote workers vs local runners
- Worker runs SessionRunner locally, forwards events to bot via TCP
- Bot receives events from worker, renders in Telegram as if local
- Permission requests: worker sends to bot, bot shows buttons, bot sends response back

</code_context>

<specifics>
## Specific Ideas

- Worker reuses the same SessionRunner class but with a different output callback (TCP send instead of direct Telegram)
- Bot-side "RemoteSession" acts as a proxy — receives events from TCP, calls StatusUpdater/split_message/PermissionManager
- Protocol messages: auth, create_session, stop_session, user_message, permission_request, permission_response, assistant_text, tool_use, result, error, status_update

</specifics>

<deferred>
## Deferred Ideas

None — this is the final phase

</deferred>
