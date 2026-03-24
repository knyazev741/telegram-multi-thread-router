# Feature Research

**Domain:** Telegram bot for AI coding agent session control
**Researched:** 2026-03-24
**Confidence:** HIGH (project requirements are well-defined; research confirms and refines scope)

## Feature Landscape

### Table Stakes (Users Expect These)

Features the system must have or it fails at its core purpose. These come directly from the project's defined value proposition.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| Session create / stop / resume | Core of the product — without this it's just a chatbot | MEDIUM | Claude Agent SDK `resume` param handles persistence; SQLite tracks session_id per topic |
| Forum topic ↔ session routing | Each topic = isolated workspace; bleed between topics breaks trust | LOW | Session key must include thread_id; topic 1 (General) requires special handling — Telegram rejects message_thread_id for it |
| Permission request as inline buttons | Eliminates bypass-permissions hacks; the whole reason for the rewrite | MEDIUM | Numbered buttons (1/2/3) because option text overflows 64-byte callback_data limit; answer within 30s or Telegram drops callback query |
| Real-time status in thread | User needs to know Claude is working without polling | MEDIUM | One persistent message, edited every ~30s; Telegram Bot API 9.5 (Mar 2026) adds native `sendMessageDraft` for streaming — evaluate for groups/topics |
| Typing indicator while Claude works | Standard Telegram bot expectation; absence = bot looks broken | LOW | `sendChatAction` expires every 5s, must be renewed in background loop; must pass `message_thread_id` for forum topics or indicator shows in wrong topic |
| Claude output as regular messages | Text responses must be readable | LOW | Split at 4096 chars; split at paragraph/sentence boundaries, not mid-word; preserve code block fences across splits |
| Session persistence across bot restarts | Claude Code writes sessions to `~/.claude/projects/<cwd>/<id>.jsonl`; restart should not lose context | MEDIUM | Store session_id in SQLite; pass back on resume; verify file still exists before resume attempt |
| Slash command forwarding (/clear, /compact, /reset) | Power-user controls over Claude state; expected by anyone using Claude Code | LOW | Intercept in bot, translate to SDK calls or CLI flags before forwarding |
| OWNER_USER_ID authentication | Single-user bot; all requests from non-owner must be silently dropped | LOW | Check `message.from_user.id` against env var on every handler; fail silently to avoid leaking bot existence |

### Differentiators (Competitive Advantage)

Features that make this system meaningfully better than alternatives (tmux hacks, auto-approval, dashboard UIs).

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| `can_use_tool` permission callback with allow-once vs allow-always | Granular control without bypass-permissions; user sees exactly what Claude wants to run | HIGH | Allow-always updates an in-memory allowlist or SQLite table; allow-once is one-shot; deny sends cancellation to SDK |
| Voice message transcription (faster-whisper local) | Hands-free task dispatch; works offline without OpenAI API dependency | MEDIUM | Download voice via Telegram file API, run faster-whisper, inject transcript as text message; queue-per-session to avoid CPU contention |
| Multi-server worker routing | Run Claude sessions on machines with large codebases without copying code to central bot | HIGH | TCP connection with auth token; central bot proxies events; worker registers with bot on connect; bot tracks worker-to-session map in SQLite |
| Custom MCP tools (reply, react, edit_message, send_file) | Claude can drive its own Telegram output — self-updating status, reactions, file delivery | HIGH | Tools run in-process via `create_sdk_mcp_server()`; no separate plugin process; Claude calls these during normal execution |
| Session list command with live status | User can see all running/paused sessions across topics without remembering topic names | LOW | Query SQLite + check which sessions have active worker connections; format as inline keyboard for quick resume/stop actions |
| Structured permission display (tool name + full command) | Reviewer sees exactly what's being approved, not just a type name | LOW | Parse `tool_name` and `input_data` from `can_use_tool` callback; format code blocks in message body; truncate long commands with "..." at 3900 chars |
| Permission timeout with auto-deny | Long-running tasks don't stall indefinitely when user is away | LOW | Asyncio timeout on `await permission_event`; send "auto-denied (timeout)" message; resume or cancel session |
| File/photo input to Claude | Send screenshots, logs, diffs to Claude without copy-paste | MEDIUM | Download Telegram file, write to temp path in working directory, pass path as message context; clean up after session ends |
| File output from Claude | Claude can deliver generated files (code, reports) as Telegram documents | LOW | MCP `send_file` tool; use `FSInputFile`; save file_id to avoid re-upload on retry |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Auto-approve all permissions | Convenience; replicates old behavior | Defeats the purpose of the rewrite; --dangerously-skip-permissions was the problem being solved | Use `allowed_tools` list for genuinely safe tools (read-only filesystem, search); require approval for write/exec |
| Web dashboard / admin panel | Centralized view of all sessions | Out of scope per PROJECT.md; adds auth surface, hosting complexity, maintenance burden | Telegram IS the dashboard — /list command + inline buttons cover this |
| Webhook mode instead of long polling | Lower latency for high-traffic bots | Single-user bot doesn't need it; requires public HTTPS endpoint; complicates local dev and deployment | Long polling is sufficient; latency is not a concern at one user |
| Real-time streaming of every Claude token | Looks impressive | Hits Telegram edit-rate limits (1 edit/second per message); causes 429 floods; no practical value since user reads at human speed | Update status message every 30s; send complete response when done; use `sendMessageDraft` in private DMs only |
| Per-message conversation branching | Power-user feature seen in some AI chat UIs | Complex state management; confusing UX in forum threads; session model doesn't support it | Use /reset or /clear to start fresh context instead |
| Multi-user access control | Team sharing | Out of scope per PROJECT.md; adds permission complexity | OWNER_USER_ID check is sufficient; separate deployment per user if needed |
| Inline bot mode (@bot query) | Convienent invocation pattern | Sessions are stateful; inline mode is stateless per query; incompatible | Use direct messages or topic messages |
| Session auto-start on first message | No setup friction | Ambiguous working directory; silent failures hard to debug | Require explicit /new <path> command to start session with known working directory |

## Feature Dependencies

```
[OWNER_USER_ID Auth]
    └──required by──> [All other features] (security gate)

[Forum Topic Routing]
    └──required by──> [Session Create/Stop/Resume]
    └──required by──> [Typing Indicator in Correct Topic]
    └──required by──> [Permission Request Display]
    └──required by──> [Status Message in Thread]

[Session Create/Stop/Resume]
    └──required by──> [Permission callback (can_use_tool)]
    └──required by──> [Voice Input]
    └──required by──> [File Input/Output]
    └──required by──> [Custom MCP Tools]
    └──required by──> [Multi-server Worker Routing]

[SQLite State]
    └──required by──> [Session Persistence across Restarts]
    └──required by──> [Session List Command]
    └──required by──> [Multi-server Worker Routing] (worker-to-session map)

[Multi-server Worker Routing]
    └──required by──> [Custom MCP Tools] (tools run on worker, events proxied to bot)

[Permission Request Display]
    └──enhanced by──> [Permission Timeout with Auto-Deny]
    └──enhanced by──> [Allow-Always Allowlist]

[Voice Transcription]
    └──depends on──> [Session Create] (needs active session to forward transcript to)

[File Input]
    └──depends on──> [Session Create] (needs working directory to write file to)

[File Output]
    └──depends on──> [Custom MCP Tools] (send_file MCP tool triggers delivery)
```

### Dependency Notes

- **Forum Topic Routing required by everything:** Thread ID is the primary session lookup key. Get this wrong and all session routing breaks.
- **SQLite required before persistence:** Session IDs must be persisted before bot restart recovery works. In-memory state is lost on restart.
- **Multi-server Worker required before Custom MCP Tools:** MCP tools run inside the worker process alongside ClaudeSDKClient; they cannot run on the central bot.
- **Permission Display conflicts with Auto-Approve:** Do not combine these. The allowlist pattern (`allowed_tools` in SDK) handles safe tools; everything else requires human approval.

## MVP Definition

### Launch With (v1)

Minimum to replace the old Node.js/tmux hack system with something better.

- [ ] OWNER_USER_ID auth — non-negotiable security gate
- [ ] Forum topic ↔ session routing with thread_id isolation — core routing primitive
- [ ] Session create, stop, resume via slash commands — lifecycle control
- [ ] Permission requests as numbered inline buttons with full context — the primary value of the rewrite
- [ ] Real-time status message (one editable message per thread, 30s refresh) — visibility
- [ ] Typing indicator (renewed every 5s in background) — basic UX expectation
- [ ] Claude output split and sent as messages (4096 limit, code block-aware) — basic output
- [ ] Session persistence in SQLite — survive bot restarts
- [ ] Single-server deployment (no worker TCP routing yet) — simplest deploy path

### Add After Validation (v1.x)

- [ ] Voice message transcription — add when text-only workflow is validated
- [ ] File/photo input to Claude — add when session stability is confirmed
- [ ] File output from Claude (MCP send_file tool) — add alongside file input
- [ ] Permission timeout with auto-deny — add when real usage reveals wait-time pain
- [ ] Session list command with inline keyboard — add when multiple sessions are routine
- [ ] Allow-always permission allowlist — add when permission fatigue is reported

### Future Consideration (v2+)

- [ ] Multi-server worker TCP routing — defer until second server is needed; adds significant complexity
- [ ] Custom MCP tools (reply, react, edit_message) — defer until worker architecture is stable; these depend on worker running
- [ ] `sendMessageDraft` streaming for topics — defer pending Telegram API stability confirmation for groups/topics (currently confirmed for private DMs only as of Bot API 9.5)

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| OWNER_USER_ID auth | HIGH | LOW | P1 |
| Forum topic routing | HIGH | LOW | P1 |
| Session lifecycle (create/stop/resume) | HIGH | MEDIUM | P1 |
| Permission inline buttons | HIGH | MEDIUM | P1 |
| Status message (editable) | HIGH | MEDIUM | P1 |
| Typing indicator | MEDIUM | LOW | P1 |
| Message splitting (4096 limit) | HIGH | LOW | P1 |
| SQLite persistence | HIGH | MEDIUM | P1 |
| Session list command | MEDIUM | LOW | P2 |
| Voice transcription | MEDIUM | MEDIUM | P2 |
| File input to Claude | MEDIUM | MEDIUM | P2 |
| File output from Claude | MEDIUM | LOW | P2 |
| Permission timeout/auto-deny | MEDIUM | LOW | P2 |
| Allow-always allowlist | MEDIUM | LOW | P2 |
| Multi-server worker TCP | LOW | HIGH | P3 |
| Custom MCP tools | MEDIUM | HIGH | P3 |
| Streaming output (sendMessageDraft) | LOW | MEDIUM | P3 |

**Priority key:**
- P1: Must have for launch
- P2: Should have, add when possible
- P3: Nice to have, future consideration

## Competitor Feature Analysis

| Feature | OpenClaw/ZeroClaw (Telegram) | Old Node.js proxy (this project) | Our Approach |
|---------|------------------------------|----------------------------------|--------------|
| Per-topic session isolation | Feature-requested, partial support | Not implemented (single session) | Core primitive — thread_id in session key from day 1 |
| Permission approval | Inline button for exec prompts (feature request as of 2025) | Auto-approved via tmux hacks | `can_use_tool` callback with numbered buttons and full context |
| Status visibility | Polling or periodic messages | None | Editable status message every 30s |
| Voice input | Not standard | Implemented via faster-whisper | Same approach, add in v1.x |
| Multi-server | Agent-based routing (cloud) | TCP proxy | Lightweight TCP worker per server |
| Custom MCP tools | Plugin ecosystem | MCP via development channel (hack) | In-process via `create_sdk_mcp_server()` |

## Sources

- [Telegram Bot Features — official](https://core.telegram.org/bots/features) — HIGH confidence
- [Telegram Bot API — sendChatAction, inline keyboards, rate limits](https://core.telegram.org/bots/api) — HIGH confidence
- [Claude Agent SDK — sessions, can_use_tool, resume](https://platform.claude.com/docs/en/agent-sdk/sessions) — HIGH confidence
- [Claude Agent SDK Python reference](https://platform.claude.com/docs/en/agent-sdk/python) — HIGH confidence
- [aiogram 3 — file upload patterns](https://docs.aiogram.dev/en/latest/api/upload_file.html) — HIGH confidence
- [Telegram Bot API 9.5 — sendMessageDraft for streaming](https://news.aibase.com/news/25881) — MEDIUM confidence (third-party report; verify against official changelog)
- [OpenClaw — per-topic forum routing patterns](https://docs.openclaw.ai/channels/telegram) — MEDIUM confidence (competing product, useful reference)
- [faster-whisper Telegram integration patterns](https://github.com/FlyingFathead/whisper-transcriber-telegram-bot) — MEDIUM confidence
- [Telegram rate limits — retry_after field, 1 msg/sec per chat](https://gramio.dev/rate-limits) — MEDIUM confidence (community-derived, not officially published)
- [OpenClaw issue: inline button for exec approval](https://github.com/openclaw/openclaw/issues/22078) — LOW confidence (competitor issue tracker, confirms demand exists)

---
*Feature research for: Telegram bot controlling Claude Code sessions via Agent SDK*
*Researched: 2026-03-24*
