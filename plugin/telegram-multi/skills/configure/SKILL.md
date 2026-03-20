---
name: telegram-multi:configure
description: Configure the Telegram Multi-Thread channel — set proxy socket path, thread ID, and chat ID.
allowed_tools:
  - Read
  - Write
  - "Bash(ls *)"
  - "Bash(mkdir *)"
---

# /telegram-multi:configure

Configure the Telegram Multi-Thread channel for this Claude Code session.

## State directory

`~/.claude/channels/telegram-multi/`

## .env file

`~/.claude/channels/telegram-multi/.env` — stores configuration:
```
TELEGRAM_THREAD_ID=42
TELEGRAM_PROXY_SOCKET=/tmp/claude-proxy/control.sock
TELEGRAM_CHAT_ID=412587349
```

## Usage

- `/telegram-multi:configure` — show current config
- `/telegram-multi:configure thread <id>` — set thread ID
- `/telegram-multi:configure socket <path>` — set proxy socket path
- `/telegram-multi:configure chat <id>` — set chat ID
- `/telegram-multi:configure clear` — remove all config

## Behavior

1. Read `~/.claude/channels/telegram-multi/.env` if it exists.
2. If no arguments: display current values (thread_id, socket path, chat_id).
3. If arguments provided: update the .env file accordingly.
4. Create the directory `~/.claude/channels/telegram-multi/` if it doesn't exist.
