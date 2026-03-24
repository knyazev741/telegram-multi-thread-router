---
phase: 3
slug: permission-system
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 3 — Validation Strategy

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
| 3-01-01 | 01 | 1 | PERM-01, PERM-02, PERM-03 | unit | `python -m pytest tests/test_permissions.py -v` | W0 | pending |
| 3-01-02 | 01 | 1 | PERM-04, PERM-05, PERM-08 | unit | `python -m pytest tests/test_permission_callbacks.py -v` | W0 | pending |
| 3-02-01 | 02 | 2 | PERM-06, PERM-07 | unit | `python -m pytest tests/test_permission_allowlist.py -v` | W0 | pending |
| 3-02-02 | 02 | 2 | PERM-09 | unit | `python -m pytest tests/test_permission_hook.py -v` | W0 | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_permissions.py` — stubs for PERM-01, PERM-02, PERM-03
- [ ] `tests/test_permission_callbacks.py` — stubs for PERM-04, PERM-05, PERM-08
- [ ] `tests/test_permission_allowlist.py` — stubs for PERM-06, PERM-07
- [ ] `tests/test_permission_hook.py` — stubs for PERM-09
- [ ] `claude-agent-sdk` types importable (PermissionResultAllow, PermissionResultDeny)

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Permission buttons appear in Telegram topic | PERM-02, PERM-03 | Requires live Telegram API | Trigger Bash tool, verify numbered buttons appear |
| Button tap resolves permission within 1s | PERM-04 | Requires live bot + real Claude session | Tap button, measure response time |
| Timeout auto-deny after 5 min | PERM-05 | Requires waiting 5 minutes | Start session, trigger permission, wait 5 min |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 10s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
