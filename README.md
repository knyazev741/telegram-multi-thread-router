# Telegram Multi-Thread Router

> Run multiple [Claude Code](https://docs.anthropic.com/en/docs/claude-code) sessions in Telegram — each forum topic is an isolated workspace.

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![aiogram 3](https://img.shields.io/badge/aiogram-3.x-blue.svg)](https://docs.aiogram.dev/)
[![Claude Agent SDK](https://img.shields.io/badge/Claude-Agent%20SDK-orange.svg)](https://docs.anthropic.com/en/docs/claude-code/sdk)

---

## What is this?

A Telegram bot that turns a **group chat with forum topics** into a multi-session Claude Code interface. Each topic runs an independent Claude Code session with full tool access — Bash, file editing, web search, and more.

**Think of it as Claude Code CLI, but in Telegram** — with voice messages, file sharing, permission buttons, and multi-server support.

### Key Features

- **1 topic = 1 session** — isolated Claude Code sessions per forum thread
- **Orchestrator** — a meta-session that can create and manage other sessions
- **Permission system** — tool approvals via inline buttons (auto-allow safe tools)
- **Voice messages** — transcribed via Whisper and forwarded to Claude
- **Photo & file support** — files downloaded to workdir, paths sent to Claude
- **Multi-server** — run workers on different machines via TCP IPC
- **Session persistence** — sessions survive bot restarts via SQLite + session resume
- **Real-time status** — editable status message shows what Claude is doing
- **Custom MCP tools** — Claude can reply, send files, react with emoji directly in Telegram

## Architecture

```
Telegram Group (Forum)
  ├── General Topic     → /new, /list, /restart
  ├── 🎯 Orchestrator   → Meta-session (creates/manages others)
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
- A Telegram group chat with **forum topics enabled**

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
| `OWNER_USER_ID` | Your Telegram user ID (only you can use the bot) |
| `GROUP_CHAT_ID` | ID of the group chat with forum topics |
| `AUTH_TOKEN` | Shared secret for TCP worker authentication |

### Run

```bash
python -m src
```

The bot will create an **Orchestrator** topic automatically on first start.

## Usage

### Commands

**General topic:**
| Command | Description |
|---------|-------------|
| `/new <name> <workdir> [server]` | Create a new session in a forum topic |
| `/list` | List all active sessions |
| `/restart` | Graceful restart (preserves sessions) |

**Inside a session topic:**
| Command | Description |
|---------|-------------|
| `/stop` | Interrupt current turn (like Escape in CLI) |
| `/close` | Stop session + delete topic |
| `/clear`, `/compact`, `/reset` | Forwarded to Claude Code |

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

Safe tools (Read, Glob, Grep, etc.) are auto-approved. Dangerous tools require explicit approval.

## Multi-Server Support

Run Claude Code sessions on different machines by connecting **workers** via TCP:

**On the worker machine:**
```bash
pip install -e .
python -m src.ipc.client --host <bot-server-ip> --port 9800 --token $AUTH_TOKEN --worker-id my-worker
```

**Create a session on the worker:**
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
      general.py           /new, /list, /restart (General topic)
      session.py           Message forwarding, /stop, /close, permissions
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
