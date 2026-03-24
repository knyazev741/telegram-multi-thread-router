---
phase: 2
slug: session-lifecycle
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 8.x + pytest-asyncio |
| **Config file** | pyproject.toml |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~10 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 10 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 2-01-01 | 01 | 1 | SESS-04, SESS-05 | unit | `python -m pytest tests/test_session_runner.py -v` | W0 | pending |
| 2-02-01 | 02 | 2 | SESS-01, SESS-02, SESS-03, INPT-01 | unit | `python -m pytest tests/test_commands.py -v` | W0 | pending |
| 2-02-02 | 02 | 2 | SESS-09, INPT-05, INPT-06 | unit | `python -m pytest tests/test_session_handler.py -v` | W0 | pending |
| 2-03-01 | 03 | 3 | SESS-06, SESS-07 | unit | `python -m pytest tests/test_session_persistence.py -v` | W0 | pending |
| 2-03-02 | 03 | 3 | SESS-08 | unit | `python -m pytest tests/test_health_monitor.py -v` | W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_session_runner.py` — stubs for SESS-04, SESS-05
- [ ] `tests/test_commands.py` — stubs for SESS-01, SESS-02, SESS-03
- [ ] `tests/test_session_handler.py` — stubs for SESS-09, INPT-01, INPT-05, INPT-06
- [ ] `tests/test_session_persistence.py` — stubs for SESS-06, SESS-07
- [ ] `tests/test_health_monitor.py` — stubs for SESS-08
- [ ] `claude-agent-sdk` added to pyproject.toml dependencies

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| /new creates Telegram forum topic and Claude responds | SESS-01 | Requires live Telegram + Claude API | Run bot, send /new test ~/tmp, verify topic created and response received |
| Bot restart auto-resumes sessions | SESS-07 | Requires process restart + live APIs | Start bot, create session, restart bot, verify session auto-resumes |
| Zombie cleanup notifies topic | SESS-08 | Requires killing a real Claude subprocess | Start session, kill -9 the claude process, wait 60s, check topic for error message |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
