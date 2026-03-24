---
phase: 01-foundation
plan: 01
subsystem: infra
tags: [python, aiogram, pydantic-settings, uvloop, aiosqlite, asyncio]

# Dependency graph
requires: []
provides:
  - Python 3.11+ package scaffold at src/ with bot/ and db/ subpackages
  - pyproject.toml with all four core dependencies declared and installable
  - pydantic-settings BaseSettings config with typed env var loading
  - uvloop asyncio.Runner entry point in src/__main__.py
  - dev environment via .venv with aiogram 3.26, aiosqlite, uvloop, pydantic-settings
affects: [02-foundation, 03-foundation, 04-foundation, 05-foundation]

# Tech tracking
tech-stack:
  added:
    - aiogram 3.26.0 (Telegram bot framework)
    - aiosqlite 0.22.1 (async SQLite)
    - uvloop 0.22.1 (fast asyncio event loop)
    - pydantic-settings 2.13.1 (typed config from .env)
    - pytest 9.0.2 + pytest-asyncio 1.3.0 (test framework)
  patterns:
    - asyncio.Runner with loop_factory=uvloop.new_event_loop (Python 3.11+ pattern)
    - pydantic-settings BaseSettings with extra="ignore" for forward-compatible .env loading
    - DefaultBotProperties(parse_mode=ParseMode.HTML) for aiogram 3.7+ bot init

key-files:
  created:
    - pyproject.toml
    - src/__init__.py
    - src/bot/__init__.py
    - src/db/__init__.py
    - src/config.py
    - src/__main__.py
  modified:
    - CLAUDE.md
    - .env.example
    - .gitignore

key-decisions:
  - "Added extra='ignore' to Settings model to handle legacy .env variables gracefully without validation errors"
  - "Deleted .claude-plugin/ directory (not listed in plan but correctly identified as old Node.js artifact)"

patterns-established:
  - "Settings model uses extra='ignore' so old/extra .env variables never break startup"
  - "Module-level settings = Settings() provides single import-time validated config instance"

requirements-completed: [FOUND-01]

# Metrics
duration: 3min
completed: 2026-03-24
---

# Phase 1 Plan 01: Python project scaffold with aiogram 3, uvloop, pydantic-settings, and clean deletion of Node.js codebase

**aiogram 3.26 + pydantic-settings + uvloop scaffold replacing full Node.js/grammy codebase, installable via pip install -e ".[dev]"**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-03-24T09:56:44Z
- **Completed:** 2026-03-24T09:59:15Z
- **Tasks:** 2
- **Files modified:** 9

## Accomplishments
- Deleted entire Node.js codebase (proxy/, plugin/, scripts/, orchestrator/, SPEC.MD, README.md, .claude-plugin/)
- Created pyproject.toml declaring aiogram>=3.26, aiosqlite>=0.22, uvloop>=0.22, pydantic-settings>=2.13 with dev extras
- Created src/config.py with typed pydantic-settings BaseSettings — 4 required fields (bot_token, owner_user_id, group_chat_id, auth_token)
- Created src/__main__.py with asyncio.Runner + uvloop.new_event_loop entry point and aiogram Dispatcher skeleton
- Installed all deps in .venv via pip install -e ".[dev]"

## Task Commits

Each task was committed atomically:

1. **Task 1: Delete old Node.js codebase and create Python project scaffold** - `0e803e4` (chore)
2. **Task 2: Create config.py and __main__.py entry point** - `27e0604` (feat)

**Plan metadata:** (docs commit — pending)

## Files Created/Modified
- `pyproject.toml` - Project metadata, all 4 core deps + dev extras, pytest config
- `src/__init__.py` - Package marker (empty)
- `src/bot/__init__.py` - Bot subpackage marker (empty)
- `src/db/__init__.py` - DB subpackage marker (empty)
- `src/config.py` - pydantic-settings BaseSettings with 4 typed fields + extra="ignore"
- `src/__main__.py` - Entry point: asyncio.Runner + uvloop, Bot + Dispatcher init, dp.start_polling
- `CLAUDE.md` - Updated to reflect new Python/aiogram architecture
- `.env.example` - Updated with 4 vars: BOT_TOKEN, OWNER_USER_ID, GROUP_CHAT_ID, AUTH_TOKEN
- `.gitignore` - Updated for Python project (data/, __pycache__/, .venv/, etc.)

## Decisions Made
- Added `extra="ignore"` to Settings model — the existing `.env` contains legacy `IPC_PORT` variable from the old Node.js bot; without this setting, pydantic-settings raises a validation error on extra fields. This makes config loading forward-compatible with .env drift.
- Deleted `.claude-plugin/` directory — not listed in the plan's delete list but clearly an old Node.js artifact; deleted for cleanliness.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Added extra="ignore" to Settings model**
- **Found during:** Task 2 (Settings import verification)
- **Issue:** Existing `.env` file contains `IPC_PORT=9600` from the old Node.js config. pydantic-settings v2 raises `ValidationError: Extra inputs are not permitted` when loading, preventing any import of `src.config`.
- **Fix:** Added `extra="ignore"` to `SettingsConfigDict` in `src/config.py`
- **Files modified:** src/config.py
- **Verification:** `BOT_TOKEN=test OWNER_USER_ID=1 GROUP_CHAT_ID=-1 AUTH_TOKEN=test python -c "from src.config import Settings; s = Settings(); assert s.bot_token == 'test'; assert s.owner_user_id == 1; print('PASS')"` — PASS
- **Committed in:** 27e0604 (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug fix)
**Impact on plan:** Required fix — without it, the Settings import fails immediately on any machine with the old .env. No scope creep.

## Issues Encountered
- Real `.env` file is missing `GROUP_CHAT_ID` (new required field for Python bot). User must add `GROUP_CHAT_ID=-100XXXXXXXXXX` to their `.env` before running `python -m src`. The `.env.example` documents this requirement.

## User Setup Required

User must update their `.env` file before the bot can start:
```
GROUP_CHAT_ID=-100XXXXXXXXXX  # Add this — the Telegram supergroup/forum chat ID
```

The old `.env` has `IPC_PORT` and `PUBLIC_HOST` that are no longer needed and can be removed, but they won't cause errors due to `extra="ignore"`.

## Next Phase Readiness
- Python scaffold is installable and all dependencies resolve correctly
- Settings class validated with correct types — ready for use in all subsequent plans
- src/bot/ and src/db/ subpackages ready to receive routers, middlewares, and schema files
- No blockers for Plan 01-02 (owner auth middleware + dispatcher assembly)

---
*Phase: 01-foundation*
*Completed: 2026-03-24*
