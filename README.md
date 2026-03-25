# Telegram Multi-Thread Router

> Run multiple [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions in Telegram — each thread is an isolated workspace.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![aiogram 3](https://img.shields.io/badge/aiogram-3.x-blue.svg)](https://docs.aiogram.dev/)
[![Claude Agent SDK](https://img.shields.io/badge/Claude-Agent%20SDK-orange.svg)](https://docs.anthropic.com/en/docs/claude-code/sdk)

---

## What is this?

A Telegram bot that runs **multiple Claude Code sessions in parallel** — each thread is an independent workspace with full tool access (Bash, file editing, web search, and more).

**Think of it as Claude Code CLI, but in Telegram** — with voice messages, file sharing, permission buttons, and multi-server support.

### Key Features

- **1 thread = 1 session** — isolated Claude Code sessions per Telegram thread
- **Orchestrator** — a dedicated Claude session that manages all other sessions via natural language
- **Auto-mode** — per-session toggle to auto-approve all permissions (no buttons needed)
- **Permission system** — tool approvals via inline buttons (safe tools auto-approved)
- **Voice messages** — transcribed via Whisper and forwarded to Claude
- **Photo & file support** — files downloaded to workdir, paths sent to Claude
- **Multi-server** — run sessions on different machines via TCP IPC workers
- **Session persistence** — sessions survive bot restarts via SQLite + session resume
- **Real-time status** — editable status message shows what Claude is doing
- **Telegram MCP tools** — Claude can reply, send files, react with emoji directly in Telegram

## Architecture

```
Telegram Bot (threads)
  ├── 🎯 Orchestrator   → Main interface: creates/manages sessions via chat
  ├── 📁 my-project     → Claude Code session (workdir: /path/to/project)
  ├── 🔧 api-server     → Claude Code session (remote worker)
  └── ...
```

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Telegram    │────▶│  Bot (aiogram 3) │────▶│  Claude Code     │
│  Messages    │◀────│  + Dispatcher    │◀────│  SDK Sessions    │
└─────────────┘     └──────────────────┘     └─────────────────┘
                           │                         │
                    ┌──────┴──────┐           ┌──────┴──────┐
                    │  SQLite DB  │           │  TCP IPC     │
                    │  (sessions, │           │  (remote     │
                    │   topics)   │           │   workers)   │
                    └─────────────┘           └─────────────┘
```

## Quick Start

### Prerequisites

- Python 3.11+
- [Claude Code](https://docs.anthropic.com/en/docs/claude-code) installed and authenticated
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))

### Bot Setup in BotFather

1. Create a bot via [@BotFather](https://t.me/BotFather) and copy the token
2. Go to **Bot Settings → Threaded Mode → Enable**
3. **Send `/start` to your bot** before launching the script — the bot needs an active chat with you to create threads

### Installation

```bash
git clone https://github.com/knyazev741/telegram-multi-thread-router.git
cd telegram-multi-thread-router

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

### Configuration

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Description |
|----------|-------------|
| `BOT_TOKEN` | Telegram bot token from @BotFather |
| `OWNER_USER_ID` | Your Telegram user ID — get it from [@Get_myidrobot](https://t.me/Get_myidrobot) |
| `AUTH_TOKEN` | Shared secret for TCP worker authentication |

### Run

```bash
python -m src
```

Send any message to the bot. It auto-detects the chat and creates an **🎯 Orchestrator** thread — this is the main interface for managing sessions.

## Usage

### Orchestrator (main interface)

The Orchestrator is a Claude Code session (Sonnet) with extra management tools. Talk to it in natural language:

- *"Create a session for my-project in /home/user/my-project"*
- *"List all sessions"*
- *"Stop session 12345"*
- *"Enable auto-mode for session 12345"* — auto-approves all permissions

The Orchestrator is also a full Claude Code session itself — it can SSH into servers, browse filesystems, run commands.

### Commands

All commands work from **any thread** (including Orchestrator):

| Command | Description |
|---------|-------------|
| `/new <name> <workdir> [server]` | Create a new session in a new thread |
| `/list` | List all active sessions |
| `/restart` | Graceful restart (preserves sessions) |
| `/stop` | Interrupt current turn (like Escape in CLI) |
| `/close` | Stop session + delete thread |
| Any other `/command` | Forwarded to Claude Code (`/model`, `/clear`, `/compact`, etc.) |

### Input Types

| Input | Behavior |
|-------|----------|
| 💬 Text | Forwarded to Claude as a message |
| 🎤 Voice | Transcribed via Whisper, then forwarded |
| 📷 Photo | Downloaded to workdir, path sent to Claude |
| 📎 Document | Downloaded to workdir, path sent to Claude |

### Permission System

When Claude wants to use a tool (e.g., run a bash command), you get inline buttons:

```
🔧 Bash: rm -rf node_modules
[✅ Allow] [✅ Allow All] [❌ Deny]
```

Safe tools (Read, Glob, Grep, etc.) are auto-approved. Dangerous tools require explicit approval. Use **auto-mode** (via Orchestrator) to skip all permission prompts for a session.

## Multi-Server Support

Run Claude Code sessions on different machines by connecting **workers** via TCP:

**On the worker machine:**
```bash
pip install -e .
python -m src.ipc.client --host <bot-server-ip> --port 9800 --token $AUTH_TOKEN --worker-id my-worker
```

**Create a session on the worker** (via Orchestrator or `/new`):
```
/new my-project /path/to/project my-worker
```

The bot acts as a **hub** — it handles Telegram and dispatches to workers. Workers run Claude Code sessions locally on their machines.

## Project Structure

```
src/
  __main__.py              Entry point (asyncio.Runner + uvloop)
  config.py                pydantic-settings configuration
  bot/
    dispatcher.py          Dispatcher factory, startup/shutdown lifecycle
    middlewares.py          OwnerAuthMiddleware
    routers/
      general.py           General topic fallback (minimal)
      session.py           All commands + message forwarding + permissions
    status.py              StatusUpdater (editable status message per turn)
    output.py              Message splitting, TypingIndicator
  sessions/
    runner.py              SessionRunner (ClaudeSDKClient wrapper)
    manager.py             SessionManager (thread_id → runner mapping)
    permissions.py         PermissionManager (Future → inline buttons)
    orchestrator.py        Orchestrator session with MCP management tools
    mcp_tools.py           Telegram MCP tools (reply, send_file, react)
    voice.py               faster-whisper transcription
    health.py              Zombie session detection
    state.py               SessionState enum
    remote.py              RemoteSession proxy for TCP workers
  db/
    schema.py              SQLite schema + migrations
    connection.py          aiosqlite connection helper
    queries.py             Named SQL query functions
  ipc/
    protocol.py            msgspec message types for TCP
    server.py              Bot-side TCP server
  worker/
    __main__.py            Worker entry point
    client.py              TCP client with reconnection
    output_channel.py      Bot adapter for worker side
```

## Tech Stack

- **[aiogram 3](https://docs.aiogram.dev/)** — async Telegram bot framework
- **[Claude Agent SDK](https://docs.anthropic.com/en/docs/claude-code/sdk)** — programmatic Claude Code sessions
- **[aiosqlite](https://github.com/omnilib/aiosqlite)** — async SQLite with WAL mode
- **[uvloop](https://github.com/MagicStack/uvloop)** — high-performance event loop
- **[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/)** — configuration management
- **[faster-whisper](https://github.com/SYSTRAN/faster-whisper)** — voice transcription
- **[msgspec](https://github.com/jcrist/msgspec)** — fast binary serialization for IPC

## Testing

```bash
pytest
```

104 tests covering database operations, IPC protocol, middleware, permissions, routing, and more.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request.

## License

[MIT](LICENSE)

## Author

**Knyazev AI** — [@knyazev741](https://github.com/knyazev741)

- Telegram: [@manintg_blog](https://t.me/manintg_blog)

## Support

If you find this project useful, consider supporting its development:

- **BTC:** `bc1qekweh0kxrgzxftefnlyuavqqrfgza60s0qq95g`
- **EVM (ETH/USDT/USDC):** `0x23a7A8eC8f9b4386a6714e5B5A0d8340f0AE1749`
- **SOL:** `5dcuDRDGCgwBXN72uUeaN5ahGvWzFY1hpv2kF7jUmf7R`
- **TON:** `UQB2fqymhGrMsA7MgRfIpd2qgc4_gXaCvtZ32l55tuirrukZ`

---

*Built with [Claude Code](https://docs.anthropic.com/en/docs/claude-code) and [Claude Agent SDK](https://docs.anthropic.com/en/docs/claude-code/sdk)*
