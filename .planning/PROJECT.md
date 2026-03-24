# Telegram Multi-Thread Router v2

## What This Is

Python-based Telegram bot that manages multiple Claude Code sessions via the Claude Agent SDK. Each Telegram forum topic maps to a separate Claude Code instance with its own working directory. A central bot handles all Telegram communication, routes messages to sessions, proxies permission requests as interactive buttons, and streams real-time status updates. Supports multi-server deployment with lightweight worker processes.

## Core Value

Users can control multiple Claude Code sessions from Telegram with full interactivity — permission approvals, status visibility, and command control — without bypass-permissions hacks.

## Requirements

### Validated

- ✓ Programmatic Claude Code session management via ClaudeSDKClient — v1.0
- ✓ Forum topic ↔ session routing (each topic = one session) — v1.0
- ✓ Permission requests as Telegram numbered inline buttons — v1.0
- ✓ Real-time status updates (editable message, 30s refresh) — v1.0
- ✓ Multi-server support: central bot + TCP workers — v1.0
- ✓ Voice message transcription via faster-whisper — v1.0
- ✓ File/photo handling (send to Claude, receive via MCP tools) — v1.0
- ✓ Session lifecycle: create, resume, stop, list, auto-resume — v1.0
- ✓ can_use_tool callback with safe tool auto-allow — v1.0
- ✓ Custom MCP tools (reply, send_file, react, edit_message) — v1.0
- ✓ SQLite persistence with WAL mode — v1.0
- ✓ Slash command forwarding (/clear, /compact, /reset) — v1.0
- ✓ Typing indicator while Claude works — v1.0
- ✓ Health monitoring and zombie cleanup — v1.0

### Active

(None — planning next milestone)

### Out of Scope

- Web dashboard or admin panel — Telegram is the only interface
- Auto-scaling or container orchestration — manual server management
- Multi-user access control — single owner, OWNER_USER_ID check
- Webhook mode for Telegram — long polling is sufficient
- Streaming partial text (edit message as Claude generates) — v2 candidate
- Cost/token tracking dashboard — v2 candidate
- Batched permission display for rapid requests — v2 candidate

## Context

### Current State (v1.0 shipped)
- Python 3.11+, aiogram 3.26, claude-agent-sdk 0.1.50, aiosqlite, uvloop
- 2,862 LOC source + 2,002 LOC tests across 43 Python files
- 104 tests passing, 6 phases complete
- Central bot + remote TCP workers architecture
- SQLite with WAL mode for persistence

### Architecture

```
Central Bot (Python, aiogram 3)
├─ Telegram Handler: long polling, message routing
├─ Session Manager: tracks active sessions, routes messages
├─ Permission Manager: asyncio.Future bridge to inline buttons
├─ Status Updater: 30s edit loop with tool tracking
├─ Voice: faster-whisper transcription
└─ SQLite: topics, sessions, message history

Workers (Python, one per server)
├─ ClaudeSDKClient: manages Claude Code subprocess
├─ WorkerOutputChannel: Bot adapter → TCP messages
├─ Permission bridge: can_use_tool → TCP → bot buttons → TCP → resolve
└─ TCP connection with auth + exponential backoff reconnect
```

## Constraints

- **Language**: Python 3.11+ — Claude Agent SDK requirement
- **Telegram lib**: aiogram 3.26+ — async, forum topics support
- **Storage**: SQLite with WAL mode — single file, simple deploy
- **Transport**: Length-prefixed msgspec over TCP with auth token
- **Deployment**: Each server needs Python 3.11+, claude CLI, worker script
- **Telegram API**: 4096 char message limit, 64-byte callback data limit

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Python + Claude Agent SDK | Proper programmatic control, no bypass-permissions | ✓ Good |
| aiogram 3 | Async Python, best Telegram forum topics support | ✓ Good |
| Monolith bot + remote workers | Bot centralizes Telegram, workers run Claude locally | ✓ Good |
| Numbered buttons for permissions | Long option text doesn't fit in buttons, numbers are universal | ✓ Good |
| SQLite over JSON | Better querying, single-file, atomic writes | ✓ Good |
| Delete old Node.js code | Clean start, no legacy baggage | ✓ Good |
| asyncio.Future for permission bridge | Bridges async can_use_tool callback to Telegram callback queries | ✓ Good |
| msgspec for TCP framing | Schema validation + binary encoding, prevents protocol drift | ✓ Good |
| WorkerOutputChannel adapter | Reuses SessionRunner unchanged on worker side | ✓ Good |

---
*Last updated: 2026-03-25 after v1.0 milestone*
