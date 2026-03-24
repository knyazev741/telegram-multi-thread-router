# Telegram Multi-Thread Router v2

## What This Is

Python-based Telegram bot that manages multiple Claude Code sessions via the Claude Agent SDK. Each Telegram forum topic maps to a separate Claude Code instance with its own working directory. A central bot handles all Telegram communication, routes messages to sessions, proxies permission requests as interactive buttons, and streams real-time status updates. Supports multi-server deployment with lightweight worker processes.

## Core Value

Users can control multiple Claude Code sessions from Telegram with full interactivity — permission approvals, status visibility, and command control — without bypass-permissions hacks.

## Requirements

### Validated

(None yet — ship to validate)

### Active

- [ ] Programmatic Claude Code session management via Claude Agent SDK (ClaudeSDKClient)
- [ ] Forum topic ↔ session routing (each topic = one session)
- [ ] Permission requests displayed as Telegram messages with numbered inline buttons
- [ ] Real-time status updates in thread (editable message, refresh every ~30s)
- [ ] Multi-server support: central bot + remote workers connected via TCP
- [ ] Voice message transcription via faster-whisper
- [ ] File/photo handling (send to Claude, receive from Claude)
- [ ] Session lifecycle: create, resume, stop, list
- [ ] `can_use_tool` callback for programmatic permission control
- [ ] Custom MCP tools for Telegram interaction (reply, react, edit_message)
- [ ] Persistent state in SQLite (topics, sessions, message history)
- [ ] Slash command forwarding (/clear, /compact, /reset)
- [ ] Typing indicator while Claude works
- [ ] Session resume across bot restarts

### Out of Scope

- Web dashboard or admin panel — Telegram is the only interface
- Auto-scaling or container orchestration — manual server management
- Multi-user access control — single owner, OWNER_USER_ID check
- Webhook mode for Telegram — long polling is sufficient

## Context

### Current State (being replaced)
- Node.js/Bun proxy + MCP plugin architecture
- Claude Code launched via tmux with `--dangerously-skip-permissions`
- Auto-confirmation of prompts through tmux send-keys hacks
- No real permission handling — everything auto-approved
- Status not streamed to Telegram
- Plugin loaded via `--dangerously-load-development-channels`

### Why Rewrite
- Claude Agent SDK provides proper programmatic control
- `can_use_tool` callback eliminates need for bypass-permissions
- `ClaudeSDKClient` gives access to all events: tool calls, status, output
- Python ecosystem (aiogram + claude-agent-sdk) is cleaner than Node.js + MCP plugin hacks
- Custom MCP tools run in-process via SDK, no separate plugin needed

### Claude Agent SDK Key Capabilities
- `ClaudeSDKClient`: interactive, bidirectional session control
- `can_use_tool(tool_name, input_data, context)`: programmatic approve/deny
- `receive_response()`: async iterator for all events (text, tool use, status)
- Custom MCP tools via `create_sdk_mcp_server()`
- `allowed_tools` for auto-approving safe tools
- `interrupt()` for cancellation
- `resume` for session persistence
- `include_partial_messages` for streaming

### UX Design for Telegram

**Permission Requests:**
Message text contains the question and full option text. Inline keyboard has only short numbered buttons (1️⃣, 2️⃣, 3️⃣...). Example:
```
🔐 Permission Request

Tool: Bash
Command: rm -rf node_modules

1. ✅ Allow this once
2. ✅ Allow always for this tool
3. ❌ Deny

[1️⃣] [2️⃣] [3️⃣]
```

**Status Updates:**
One persistent message in thread, edited every 30s:
```
⚡ Working...
📁 Reading src/main.py
🔧 Tool: Edit (src/main.py)
⏱ 2m 15s | 3 tool calls
```

**Claude Output:**
Regular messages in thread, split at 4096 chars. Code blocks preserved.

### Architecture

```
Central Bot (Python, aiogram 3)
├─ Telegram Handler: long polling, message routing
├─ Session Manager: tracks active sessions, routes messages
├─ Permission Manager: pending permission requests, callback query handler
├─ Status Updater: periodic message edits with current status
└─ SQLite: topics, sessions, message history

Workers (Python, one per server)
├─ ClaudeSDKClient: manages Claude Code subprocess
├─ Custom MCP tools: reply, react, edit_message, send_file
├─ Event stream: forwards events to central bot
└─ TCP connection to central bot
```

## Constraints

- **Language**: Python 3.10+ — Claude Agent SDK is Python-only
- **Telegram lib**: aiogram 3 — async, good forum topics support
- **Storage**: SQLite — single file, simple deploy
- **Transport**: TCP with auth token between bot and workers
- **Deployment**: Each server needs Python 3.10+, claude CLI, worker script
- **Telegram API**: 4096 char message limit, inline keyboard button text limit ~64 chars

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Python + Claude Agent SDK | Proper programmatic control, no bypass-permissions | — Pending |
| aiogram 3 | Async Python, best Telegram forum topics support | — Pending |
| Monolith bot + remote workers | Bot centralizes Telegram, workers run Claude locally | — Pending |
| Numbered buttons for permissions | Long option text doesn't fit in buttons, numbers are universal | — Pending |
| SQLite over JSON | Better querying, single-file, atomic writes | — Pending |
| Delete old Node.js code | Clean start, no legacy baggage | — Pending |

---
*Last updated: 2026-03-24 after initialization*
