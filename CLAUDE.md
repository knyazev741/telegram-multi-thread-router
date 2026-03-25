# Telegram Multi-Thread Router

## Architecture

Python asyncio bot using aiogram 3 + Claude Agent SDK. Each Telegram bot thread = one Claude Code session.

- **Bot**: aiogram 3 Dispatcher with Router-per-concern pattern
- **Sessions**: ClaudeSDKClient per thread, managed by SessionManager
- **Orchestrator**: Auto-created Sonnet session with MCP tools for managing other sessions
- **Permissions**: can_use_tool callback → asyncio.Future → Telegram inline buttons
- **DB**: aiosqlite with WAL mode for session/topic persistence
- **Config**: pydantic-settings loading from .env

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in values
python -m src
```

## Restart (pick up new code)

Two ways to restart:
1. **From Telegram General topic**: `/restart`
2. **Manual**: `kill $(pgrep -f 'python -m src') && python -m src`

On restart, all sessions resume automatically via `resume_all()` — sessions stay as `idle` in DB during graceful shutdown and are re-created with their `session_id` on next startup.

**CRITICAL — DO NOT restart the bot from sessions:**
- **NEVER** run `os.execv`, `kill`, `pkill`, or any command that restarts/kills the bot process from within a Claude Code session running inside this bot.
- You ARE running inside this bot. Restarting it kills YOUR OWN process and causes infinite restart loops.
- If code changes need a restart, tell the user to run `/restart` from the Telegram General topic manually.
- This applies to ALL sessions, including the orchestrator.

**IMPORTANT**: Never `kill -9` the bot — use SIGTERM so on_shutdown runs and preserves session state.

## Project Structure

```
src/
  __main__.py          - Entry point (asyncio.Runner + uvloop)
  config.py            - pydantic-settings BaseSettings
  bot/
    dispatcher.py      - Dispatcher factory, startup/shutdown lifecycle
    middlewares.py      - OwnerAuthMiddleware
    routers/
      general.py       - /new, /list, /restart (General topic / no thread)
      session.py       - Message forwarding, /stop, /close, permissions, voice/photo/doc
    status.py          - StatusUpdater (editable status message per turn)
    output.py          - split_message, TypingIndicator
  sessions/
    runner.py          - SessionRunner (ClaudeSDKClient wrapper, state machine)
    manager.py         - SessionManager (thread_id → runner mapping)
    permissions.py     - PermissionManager (asyncio.Future bridge to Telegram buttons)
    orchestrator.py    - Auto-created orchestrator session with management MCP tools
    mcp_tools.py       - Telegram output MCP tools (reply, send_file, react, edit_message)
    voice.py           - faster-whisper transcription
    health.py          - Zombie session detection
    state.py           - SessionState enum
    remote.py          - RemoteSession proxy for TCP workers
  db/
    schema.py          - SQLite schema + migrations
    connection.py      - aiosqlite connection helper
    queries.py         - Named SQL query functions
  ipc/
    protocol.py        - msgspec Struct message types for TCP
    server.py          - Bot-side TCP server for remote workers
  worker/
    __main__.py        - Worker entry point (python -m src.worker)
    client.py          - TCP client with reconnection
    output_channel.py  - Bot adapter for worker side
```

## Telegram Bot Commands

**General topic (no thread / thread_id=1/None):**
- `/new <name> <workdir> [server]` — create session in new thread
- `/list` — list active sessions
- `/restart` — restart bot, resume all sessions

**Inside a session thread:**
- `/stop` — stop the session
- `/close` — stop + delete thread
- `/clear`, `/compact`, `/reset` — forwarded to Claude Code
- Text → forwarded to Claude
- Voice → transcribed → forwarded
- Photo/Document → downloaded to workdir → path sent to Claude

## Security
- All secrets in `.env` (gitignored), chmod 600
- No credentials in source code
- OWNER_USER_ID enforced via outer middleware on all messages
- AUTH_TOKEN for TCP worker authentication

## Infrastructure

### Servers
- **Personal server**: `167.235.155.73` (SSH: `ssh personal-server`) — all autonomous services, Gitea, backups
- **Business server**: `116.203.112.192`
- **Club server**: `128.140.111.201` — club chat bots and automation

### Repos
- **This repo (local/Mac)**: `/Users/knyaz/Telegram Multi-Thread Router/` — new architecture (aiogram 3 + Claude Agent SDK)
- **Agent repo**: `/Users/knyaz/agent/` (Mac) / `/root/agent/` (server) — main agent-orchestrator, services, memory
- **Gitea (private Git)**: `https://git.knyazevai.work` — primary remote for all repos
