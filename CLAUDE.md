# Telegram Multi-Thread Router

## Architecture

Python asyncio bot using aiogram 3 + Claude Agent SDK. Single-server, single-owner.

- **Bot**: aiogram 3 Dispatcher with Router-per-concern pattern
- **DB**: aiosqlite with WAL mode for session/topic persistence
- **Config**: pydantic-settings loading from .env

## Quick Start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env  # fill in values
python -m src
```

## Project Structure

```
src/
  __main__.py      - Entry point (asyncio.Runner + uvloop)
  config.py        - pydantic-settings BaseSettings
  bot/             - aiogram dispatcher, routers, middlewares
  db/              - aiosqlite connection, schema, queries
```

## Security
- All secrets in `.env` (gitignored), chmod 600
- No credentials in source code
- OWNER_USER_ID enforced via outer middleware on all messages
