# Roadmap: Telegram Multi-Thread Router v2

## Overview

A clean Python rewrite of a Node.js bot that proxied Claude sessions through tmux hacks. The new system uses the Claude Agent SDK for proper programmatic control: real permission callbacks, real status events, real session lifecycle. The build proceeds in strict dependency order — foundation first, session runner second, permissions third — because each layer depends on the previous being solid. Multi-server routing is deferred until the single-server workflow is validated in daily use.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Foundation** - Bot scaffold, forum topic routing, and SQLite persistence (completed 2026-03-24)
- [x] **Phase 2: Session Lifecycle** - Create, run, stop, and resume Claude sessions (completed 2026-03-24)
- [x] **Phase 3: Permission System** - `can_use_tool` bridged to Telegram inline buttons (completed 2026-03-24)
- [x] **Phase 4: Status and UX** - Editable status message, typing indicator, rate-limit safety (completed 2026-03-24)
- [ ] **Phase 5: Voice and File I/O** - Voice transcription, file/photo input, MCP output tools
- [ ] **Phase 6: Multi-Server** - TCP worker routing for remote Claude instances

## Phase Details

### Phase 1: Foundation
**Goal**: A running bot that accepts only owner messages, routes by forum topic, and persists records to SQLite
**Depends on**: Nothing (first phase)
**Requirements**: FOUND-01, FOUND-02, FOUND-03, FOUND-04, FOUND-05
**Success Criteria** (what must be TRUE):
  1. Bot starts and receives messages from the configured group chat via long polling
  2. Any message from a non-owner user is silently dropped — owner messages are processed
  3. A message sent in a forum topic produces the correct `message_thread_id` in logs, proving routing resolves to the right session slot
  4. SQLite database file exists with WAL mode enabled and correct schema (topics, sessions, message_history tables)
  5. General topic (thread_id=1) receives management commands and responds — other topics do not receive each other's messages
**Plans**: 3 plans

Plans:
- [ ] 01-01: Project scaffold, dependencies, and bot startup (aiogram 3 + uvloop + aiosqlite)
- [ ] 01-02: Owner auth middleware, forum topic router, and General topic handler
- [ ] 01-03: SQLite schema, WAL mode setup, and async write wrapper

### Phase 2: Session Lifecycle
**Goal**: Owner can start a Claude session in a forum topic, send messages, receive responses, and stop or resume it across bot restarts
**Depends on**: Phase 1
**Requirements**: SESS-01, SESS-02, SESS-03, SESS-04, SESS-05, SESS-06, SESS-07, SESS-08, SESS-09, INPT-01, INPT-05, INPT-06
**Success Criteria** (what must be TRUE):
  1. Owner types `/new myproject ~/projects/foo` in General topic — a new forum topic is created, a `ClaudeSDKClient` starts, and Claude responds to the first message
  2. Owner types `/list` — active sessions appear with their topic name, working directory, and current state (idle/running)
  3. Owner sends a message in a session topic — Claude receives it, processes it, and the response appears in that same topic
  4. Owner types `/stop` in a session topic — Claude is interrupted cleanly and the session transitions to stopped state
  5. Bot restarts — all sessions with saved `session_id` in SQLite auto-resume without losing working directory context
  6. A Claude subprocess that becomes unresponsive is detected by health monitoring and cleaned up, with the topic notified
**Plans**: 3 plans

Plans:
- [ ] 02-01: `ClaudeSDKClient` wrapper, `SessionRunner` state machine (IDLE/RUNNING/INTERRUPTING/STOPPED), and dummy PreToolUse hook
- [ ] 02-02: `/new`, `/stop`, `/list` command handlers and `SessionManager` topic-to-runner mapping
- [ ] 02-03: SQLite session persistence, auto-resume on startup, health check task, and zombie cleanup

### Phase 3: Permission System
**Goal**: Every tool call from Claude surfaces as a numbered inline button message in the session topic; owner approves or denies; session proceeds or stops cleanly
**Depends on**: Phase 2
**Requirements**: PERM-01, PERM-02, PERM-03, PERM-04, PERM-05, PERM-06, PERM-07, PERM-08, PERM-09
**Success Criteria** (what must be TRUE):
  1. When Claude attempts a Bash command, a Telegram message appears in the topic showing the tool name, command, and numbered options (1. Allow once, 2. Allow always, 3. Deny) with inline buttons [1] [2] [3]
  2. Owner taps a button — the permission resolves within 1 second and Claude continues (or stops on deny)
  3. If owner does not respond within 5 minutes, the permission auto-denies and a "timed out" message appears in the topic
  4. Owner taps "Allow always" — that tool pattern is added to `allowed_tools` and subsequent calls to that tool are auto-approved without prompting
  5. Read, Glob, Grep, and Explore agent tool calls are auto-approved without any Telegram prompt appearing
  6. Tapping a button on an expired permission request shows "This permission has expired" instead of crashing
**Plans**: 3 plans

Plans:
- [ ] 03-01-PLAN.md — PermissionManager + SessionRunner can_use_tool (Future bridge, timeout, auto-allow)
- [ ] 03-02-PLAN.md — Callback query handler, DI wiring (dispatcher, manager, general router)
- [ ] 03-03-PLAN.md — Tests covering PERM-01 through PERM-09

### Phase 4: Status and UX
**Goal**: Owner sees a live status message per topic and a typing indicator while Claude works; Telegram rate limits are respected
**Depends on**: Phase 3
**Requirements**: STAT-01, STAT-02, STAT-03, STAT-04, STAT-05, STAT-06, STAT-07
**Success Criteria** (what must be TRUE):
  1. One persistent status message exists per active session topic, showing current tool, elapsed time, and tool call count — it updates every 30 seconds
  2. While Claude is running, the topic shows a typing indicator that refreshes every 4 seconds without spamming the Telegram API
  3. Claude's text output arrives as regular messages in the correct topic, with messages longer than 4096 characters split at code-block boundaries
  4. When a session completes, the status message shows final cost, duration, and total tool calls
  5. Error conditions (SDK crash, connection loss) produce a clearly formatted error message in the topic instead of silent failure
**Plans**: 3 plans

Plans:
- [ ] 04-01-PLAN.md — StatusUpdater class, message splitter, typing indicator utilities
- [ ] 04-02-PLAN.md — Wire status/typing/splitter into SessionRunner._drain_response + error formatting
- [ ] 04-03-PLAN.md — Tests for STAT-01 through STAT-07

### Phase 5: Voice and File I/O
**Goal**: Owner can send voice messages, photos, and files to Claude sessions; Claude can send files back via MCP tools
**Depends on**: Phase 2
**Requirements**: INPT-02, INPT-03, INPT-04, FILE-01, FILE-02, FILE-03, FILE-04
**Success Criteria** (what must be TRUE):
  1. Owner sends a voice message in a session topic — it is transcribed locally by faster-whisper and the text is delivered to Claude as if typed
  2. Owner sends a photo or document — the file is downloaded to the session working directory and the path is passed to Claude
  3. Claude calls the `reply` MCP tool with a message string — a Telegram message appears in the correct topic
  4. Claude calls the `send_file` MCP tool with a file path — that file appears as a Telegram document in the session topic
  5. Claude calls the `react` or `edit_message` MCP tool — the reaction or edit appears in Telegram within 2 seconds
**Plans**: 3 plans

Plans:
- [ ] 05-01-PLAN.md — Voice transcription module (faster-whisper) + MCP tools factory (4 Telegram output tools)
- [ ] 05-02-PLAN.md — Wire voice/photo/doc handlers into session router + MCP server into SessionRunner
- [ ] 05-03-PLAN.md — Tests for INPT-02, INPT-03, INPT-04, FILE-01 through FILE-04

### Phase 6: Multi-Server
**Goal**: Workers running on remote servers connect to the central bot via authenticated TCP; session routing is transparent from the owner's perspective
**Depends on**: Phase 5
**Requirements**: MSRV-01, MSRV-02, MSRV-03, MSRV-04, MSRV-05, MSRV-06, MSRV-07, MSRV-08
**Success Criteria** (what must be TRUE):
  1. A worker process started on a remote server connects to the central bot via TCP with the shared auth token — the bot logs the worker as registered
  2. Owner types `/new myproject ~/projects/foo remote-server` — the session is created on that specific worker, not the local process
  3. All Claude output, permission requests, and status events from the remote worker appear in Telegram identically to a local session
  4. If the TCP connection drops, the worker reconnects automatically with exponential backoff — no manual intervention required
  5. `/list` shows which server each session is running on
  6. A local session (no server specified) still works through the in-process path without requiring a TCP worker
**Plans**: 3 plans

Plans:
- [ ] 06-01: TCP protocol — length-prefixed msgspec-encoded frames, auth handshake, worker registration
- [ ] 06-02: Worker process (`worker.py`) — `ClaudeSDKClient` management, event forwarding, permission relay
- [ ] 06-03: Bot-side worker registry — session-to-worker routing, reconnect handling, in-process fallback

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Foundation | 3/3 | Complete   | 2026-03-24 |
| 2. Session Lifecycle | 3/3 | Complete   | 2026-03-24 |
| 3. Permission System | 3/3 | Complete   | 2026-03-24 |
| 4. Status and UX | 3/3 | Complete   | 2026-03-24 |
| 5. Voice and File I/O | 1/3 | In Progress|  |
| 6. Multi-Server | 0/3 | Not started | - |
