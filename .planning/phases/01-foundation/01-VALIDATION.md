---
phase: 1
slug: foundation
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 1 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~5 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 5 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 1-01-01 | 01 | 1 | FOUND-01 | integration | `python -m pytest tests/test_bot_startup.py -v` | ❌ W0 | ⬜ pending |
| 1-02-01 | 02 | 1 | FOUND-02 | unit | `python -m pytest tests/test_auth_middleware.py -v` | ❌ W0 | ⬜ pending |
| 1-02-02 | 02 | 1 | FOUND-04 | unit | `python -m pytest tests/test_topic_router.py -v` | ❌ W0 | ⬜ pending |
| 1-02-03 | 02 | 1 | FOUND-05 | unit | `python -m pytest tests/test_general_topic.py -v` | ❌ W0 | ⬜ pending |
| 1-03-01 | 03 | 1 | FOUND-03 | unit | `python -m pytest tests/test_database.py -v` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_bot_startup.py` — stubs for FOUND-01
- [ ] `tests/test_auth_middleware.py` — stubs for FOUND-02
- [ ] `tests/test_topic_router.py` — stubs for FOUND-04
- [ ] `tests/test_general_topic.py` — stubs for FOUND-05
- [ ] `tests/test_database.py` — stubs for FOUND-03
- [ ] `tests/conftest.py` — shared fixtures (mock bot, mock update)
- [ ] `pytest` + `pytest-asyncio` in dev dependencies

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Bot connects to Telegram and receives messages | FOUND-01 | Requires live Telegram API | Start bot, send message in group, verify log output |
| Forum topic routing in live group | FOUND-04 | Requires real Telegram forum topics | Send messages in different topics, verify message_thread_id in logs |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 5s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
