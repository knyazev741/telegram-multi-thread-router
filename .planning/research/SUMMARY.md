# Project Research Summary

**Project:** Telegram Multi-Thread Router (Python rewrite)
**Domain:** Telegram bot for distributed Claude Agent SDK session management
**Researched:** 2026-03-24
**Confidence:** HIGH

## Executive Summary

This project is a personal Telegram bot that acts as a control plane for Claude Code sessions running on one or more servers. The central bot receives Telegram messages from a single authenticated owner, routes them by forum topic to the correct Claude session, and bridges permission requests from Claude's `can_use_tool` callback back to the owner as interactive inline buttons. The recommended build approach is Python/aiogram 3 on the bot side with asyncio TCP IPC to worker processes that each run a `ClaudeSDKClient` — one client per session, one session per forum topic. aiosqlite with WAL mode provides durable state; uvloop improves throughput for concurrent sessions.

The MVP scope is deliberately narrow: single-server deployment (bot and worker on the same host), owner auth middleware, forum-topic-to-session routing, the permission callback flow with inline buttons, an editable status message per topic, and SQLite-backed session persistence. Multi-server TCP worker routing and custom MCP tools (reply/react/send_file) are v2 concerns that depend on the single-server architecture being stable first. Voice transcription is a v1.x addition after core text-based session management is validated.

The most significant risks are all in the Claude Agent SDK integration: `can_use_tool` silently fails without a dummy PreToolUse hook (a known SDK design flaw), session resume silently creates a fresh session if the working directory path doesn't match exactly, and `ClaudeSDKClient` initialization can leave zombie subprocesses if not wrapped in a timeout with explicit process cleanup. These three pitfalls must be treated as invariants built into the session runner from day one — they cannot be patched in later without refactoring the session lifecycle.

## Key Findings

### Recommended Stack

The stack is well-settled with no meaningful alternatives for the core choices. aiogram 3.26 is the only actively-maintained async Python Telegram library with full forum topics support. `claude-agent-sdk 0.1.50` is the official Anthropic SDK with no substitutes. aiosqlite handles persistent state at this scale without ORM overhead. uvloop is a drop-in event loop replacement that handles concurrent streaming sessions efficiently.

**Core technologies:**
- **Python 3.11+**: Runtime — widest compatibility across aiogram, claude-agent-sdk, and ctranslate2 (faster-whisper dependency)
- **aiogram 3.26.0**: Telegram framework — only async-native library with forum topic `message_thread_id` support
- **claude-agent-sdk 0.1.50**: Claude session control — official SDK; `ClaudeSDKClient`, `can_use_tool`, `create_sdk_mcp_server` are all needed
- **aiosqlite 0.22.1**: Persistent state — zero-infra SQLite with async wrapper; must use WAL mode and a single shared connection
- **uvloop 0.22.1**: Event loop — 2-4x faster than stdlib; required for production multi-session handling
- **faster-whisper 1.2.1**: Voice transcription — 4x faster than openai-whisper, local inference, CPU-compatible with int8 quantization
- **msgspec 0.20.0**: Wire serialization — fastest MessagePack + schema validation for TCP IPC (if multi-server)
- **uv**: Dependency management — replaces pip/venv; `uv sync` is the install command

### Expected Features

**Must have (v1 — table stakes):**
- OWNER_USER_ID auth middleware — security gate; all non-owner updates silently dropped
- Forum topic to session routing — `message_thread_id` is the session key; wrong here breaks everything
- Session create, stop, resume via slash commands — core lifecycle control
- Permission requests as numbered inline buttons with full command context — the primary value of the rewrite
- Editable status message per topic (30s refresh) — visibility that Claude is working
- Typing indicator renewed every 5s in background — basic UX expectation
- Claude output split at 4096 chars, code-block-aware — prevents garbled responses
- SQLite session persistence — survive bot restarts without losing session IDs

**Should have (v1.x — after validation):**
- Voice message transcription via faster-whisper
- File and photo input to Claude (write to session working directory)
- File output from Claude (MCP send_file tool)
- Permission timeout with auto-deny (5-minute default)
- Session list command with inline keyboard
- Allow-always permission allowlist for safe tools

**Defer (v2+):**
- Multi-server worker TCP routing — adds significant complexity; defer until a second server is needed
- Custom MCP tools (reply, react, edit_message) — depend on worker architecture being stable
- `sendMessageDraft` streaming for topics — pending Telegram Bot API 9.5 stability confirmation for groups

### Architecture Approach

The system splits into two deployable units: a central bot process (aiogram + SQLite + IPC server) and one or more worker processes (ClaudeSDKClient + optional MCP tools). For v1 (single-server), the worker can run in the same process or as a co-located asyncio task group, eliminating TCP complexity entirely. For v2 (multi-server), workers connect via authenticated asyncio TCP using newline-delimited JSON with length-prefix framing. The key architectural invariant is one `ClaudeSDKClient` per `SessionRunner` per topic — sharing clients across sessions is explicitly unsupported by the SDK.

**Major components:**
1. **TelegramDispatcher** — aiogram 3 dispatcher with owner-check middleware; routes to handler modules by message type
2. **SessionManager** — maps `topic_id` to active worker connection or in-process `SessionRunner`; owns asyncio.Lock per session
3. **PermissionManager** — holds `asyncio.Future` per pending `can_use_tool` request; resolved by inline button callback handler
4. **SessionRunner** — owns one `ClaudeSDKClient`; manages state machine (IDLE/RUNNING/INTERRUPTING/STOPPED); must drain after interrupt
5. **StatusUpdater** — edits one persistent message per topic every 30s; must catch `TelegramRetryAfter` and coalesce updates
6. **SQLite (bot-side)** — persists topics, session IDs with their `cwd`, pending permission records; WAL mode + single connection + asyncio.Lock

### Critical Pitfalls

1. **`can_use_tool` never fires without dummy PreToolUse hook** — SDK design flaw (GitHub #18735); always register `HookMatcher(matcher=None, hooks=[keep_stream_open])` alongside every `can_use_tool` implementation; test on first working session
2. **Session resume silently starts fresh when `cwd` doesn't match** — store working directory alongside session ID in SQLite; pass identical `cwd` path on resume; validate session file exists before telling user "resuming"
3. **`ClaudeSDKClient` initialization leaves zombie subprocesses on timeout** — wrap `__aenter__()` in `asyncio.wait_for(timeout=30)`; explicitly kill `_process` on timeout; add health-check task to detect accumulation
4. **`can_use_tool` callback blocks indefinitely if user never responds** — every implementation must use `asyncio.wait_for(timeout=300)`; send "auto-denied" Telegram message on timeout; this must be in the initial design, not added later
5. **Forum topic `message_thread_id` vs `reply_to_message_id` confusion** — store `thread_id` in session record at creation; wrap all `send_message` calls in a thin helper that enforces `message_thread_id`; never derive thread_id from incoming message at send time

## Implications for Roadmap

Based on combined research, the build order follows strict dependency chains. Each phase must be fully working before the next begins — partial implementations of the permission system or session lifecycle will cause silent failures that are hard to diagnose.

### Phase 1: Foundation — Transport, Storage, and Bot Scaffold

**Rationale:** Everything else depends on these three primitives. Forum topic routing is the session key; get this wrong and all subsequent phases break. SQLite with WAL mode and the shared-connection pattern must be established before any async writes are added. The TCP protocol (if building multi-server from the start) must use length-prefix framing from day one — retrofitting is painful.

**Delivers:** A bot that can receive messages from the owner, route by topic, store session records, and (if multi-server) exchange framed messages with a worker.

**Addresses:** OWNER_USER_ID auth, forum topic routing, SQLite persistence
**Avoids:** Forum topic routing pitfall (Pitfall 8), SQLite write contention (Pitfall 9), TCP partial read corruption (Pitfall 5)

### Phase 2: Session Lifecycle — Create, Run, Stop, Resume

**Rationale:** The session runner with correct `ClaudeSDKClient` lifecycle is the most complex component and the source of the three hardest-to-debug pitfalls. Build the state machine (IDLE/RUNNING/INTERRUPTING/STOPPED) and validate the dummy PreToolUse hook before adding any UX on top of it.

**Delivers:** Owner can start a Claude session in a topic, send it messages, receive responses, and stop or resume it across bot restarts.

**Addresses:** Session create/stop/resume, session persistence, Claude output message splitting
**Avoids:** `can_use_tool` dummy hook pitfall (Pitfall 1), session resume cwd mismatch (Pitfall 3), zombie subprocess accumulation (Pitfall 4), not draining after interrupt (Architecture Anti-Pattern 5)

### Phase 3: Permission System

**Rationale:** This is the primary value of the rewrite. Depends on Phase 2's session runner being stable. The `asyncio.Future`-based bridge between worker `can_use_tool` and Telegram button callback is non-trivial; the timeout and stale-button cases must be handled in the initial implementation.

**Delivers:** Every tool call from Claude surfaces as a numbered inline button in the session topic; owner approves or denies; session proceeds or is denied cleanly.

**Addresses:** Permission inline buttons, permission timeout with auto-deny, structured permission display
**Avoids:** Permission callback no timeout (Pitfall 2), stale inline keyboard buttons (Pitfall 7)

### Phase 4: Status and UX Polish

**Rationale:** Depends on Phase 2 (needs session event stream) and Phase 3 (status must show "waiting for approval" state). The Telegram rate-limiting concern for status edits is real but only manifests with 4+ concurrent sessions — add the rate limiter here, not later.

**Delivers:** One editable status message per topic showing current tool, elapsed time, and session state; typing indicator; rate-limit-safe edit wrapper.

**Addresses:** Real-time status message, typing indicator, Telegram edit rate limiting
**Avoids:** Status edit rate limit (Pitfall 6), unbounded status update queue (Performance Trap)

### Phase 5: Voice and File I/O

**Rationale:** Standalone feature with no dependencies on Phase 3 or 4 other than active sessions existing. Add after the text-based workflow is validated in daily use.

**Delivers:** Owner can send voice messages (transcribed locally by faster-whisper) and file/photo attachments to active Claude sessions.

**Addresses:** Voice transcription, file input to Claude
**Avoids:** faster-whisper OOM on long/concurrent audio (Pitfall 10)

### Phase 6: Multi-Server Worker Routing (v2)

**Rationale:** Deferred until a second server is actually needed. Requires refactoring session management to route by worker connection rather than in-process task. The TCP framing from Phase 1 makes this incremental rather than a rewrite.

**Delivers:** Workers on remote servers connect via authenticated TCP; bot routes session commands and events transparently; file output via MCP send_file tool.

**Addresses:** Multi-server TCP routing, custom MCP tools (reply/react/send_file)
**Avoids:** All TCP and worker-routing pitfalls; anti-patterns around blocking event loop on worker events (Architecture Anti-Pattern 1)

### Phase Ordering Rationale

- Phase 1 before everything: forum routing is the session lookup key; no session management is correct without it
- Phase 2 before Phase 3: permission system requires a working session runner; testing `can_use_tool` without Phase 2 complete is impossible
- Phase 3 before Phase 4: status message must show "waiting for approval" state, which requires Phase 3 semantics
- Phase 5 standalone: voice/file are additive; can be developed in parallel with Phase 4 if resources allow
- Phase 6 deferred: avoids premature complexity; single-server covers the owner's primary use case

### Research Flags

Phases that may need deeper research during planning:

- **Phase 3 (Permission System):** The `can_use_tool` API has documented quirks (dummy hook requirement, multi-turn callback skip issue #227) that may have additional edge cases. Validate the exact `HookMatcher` API signature against SDK 0.1.50 before implementing.
- **Phase 6 (Multi-Server):** Worker registration, session handoff on reconnect, and in-flight permission state recovery across TCP disconnects have nontrivial edge cases. Research reconnect protocol and state transfer patterns when this phase begins.

Phases with standard patterns (skip research-phase):

- **Phase 1:** aiogram middleware, SQLite WAL setup, and asyncio TCP are all textbook patterns with official documentation. No research needed.
- **Phase 4:** Telegram rate limiting with `TelegramRetryAfter` is well-documented; the fix is in PITFALLS.md verbatim.
- **Phase 5:** faster-whisper in asyncio via `run_in_executor` with a semaphore is a solved pattern; STACK.md has the exact code.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | All versions verified against PyPI; no speculative choices |
| Features | HIGH | Requirements well-defined; competitor analysis confirms scope; one MEDIUM item (sendMessageDraft for groups in Bot API 9.5) |
| Architecture | HIGH | Official SDK docs and aiogram docs both verified; patterns are production-proven asyncio patterns |
| Pitfalls | HIGH | 7 of 10 pitfalls verified against official SDK docs or GitHub issues with issue numbers; 3 derived from asyncio/SQLite community patterns |

**Overall confidence:** HIGH

### Gaps to Address

- **`sendMessageDraft` for group topics (Bot API 9.5):** Currently confirmed only for private DMs. Status is MEDIUM confidence. Treat as unavailable for v1; re-evaluate when Bot API 9.5 group support is confirmed.
- **`can_use_tool` multi-turn skip (GitHub issue #227):** A separate bug where the callback is skipped in subsequent turns of a multi-turn session. The dummy hook fix addresses the initial call but may not cover all multi-turn cases. Verify with multi-turn session testing in Phase 3 validation.
- **Single-server vs multi-server split decision:** If the owner only ever uses one server, the TCP IPC layer adds complexity with no benefit. Phase 1 should decide whether to build TCP transport immediately or defer it. The architecture is designed to allow in-process sessions first and TCP sessions later without a rewrite.

## Sources

### Primary (HIGH confidence)

- [Claude Agent SDK Python Reference](https://platform.claude.com/docs/en/agent-sdk/python) — ClaudeSDKClient API, can_use_tool, create_sdk_mcp_server, session resume
- [Claude Agent SDK — Handle approvals](https://platform.claude.com/docs/en/agent-sdk/user-input) — dummy PreToolUse hook requirement
- [Claude Agent SDK — Work with sessions](https://platform.claude.com/docs/en/agent-sdk/sessions) — session resume, cwd matching
- [aiogram 3 Docs — Middlewares, Router, Forum Topics](https://docs.aiogram.dev/en/latest/) — message_thread_id, callback data, file upload
- [PyPI: aiogram 3.26.0, claude-agent-sdk 0.1.50, aiosqlite 0.22.1, uvloop 0.22.1, faster-whisper 1.2.1, msgspec 0.20.0](https://pypi.org) — version and compatibility verification
- [Python asyncio Streams](https://docs.python.org/3/library/asyncio-stream.html) — TCP server/client, readexactly()
- [Telegram Bot API — sendChatAction, inline keyboards, rate limits](https://core.telegram.org/bots/api)

### Secondary (MEDIUM confidence)

- [Telegram Bot API 9.5 — sendMessageDraft](https://news.aibase.com/news/25881) — third-party report; verify against official changelog before implementing
- [grammY flood limits deep-dive](https://grammy.dev/advanced/flood) — 20 edits/min per group; community-derived
- [OpenClaw docs — per-topic forum routing patterns](https://docs.openclaw.ai/channels/telegram) — competitor reference

### Tertiary (LOW confidence)

- [GitHub issue #18735 — dummy hook design flaw](https://github.com/anthropics/claude-code/issues/18735) — confirmed January 2026; specific API shape may evolve
- [GitHub issue #227 — canUseTool skip in multi-turn](https://github.com/anthropics/claude-agent-sdk-python/issues/227) — needs validation against 0.1.50
- [GitHub issue #18666 — zombie subprocess on init timeout](https://github.com/anthropics/claude-code/issues/18666) — internal process field name `_process` may differ; verify at implementation time

---
*Research completed: 2026-03-24*
*Ready for roadmap: yes*
