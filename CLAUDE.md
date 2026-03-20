# Telegram Multi-Thread Router

## Architecture

Central proxy bot + per-session Claude Code plugins connected via TCP.

- **Proxy** (runs on server): Telegram bot, IPC server, topic management
- **Plugin** (runs with each Claude Code instance): MCP channel bridge

## Quick Start

See [README.md](README.md) for full setup guide.

## Security
- All secrets in `.env` (gitignored), chmod 600
- No credentials in source code
- AUTH_TOKEN shared between proxy and plugin for session authentication
