# Project Retrospective

## Milestone: v1.0 — Full Rewrite

**Shipped:** 2026-03-25
**Phases:** 6 | **Plans:** 18 | **Tests:** 104

### What Was Built
- Complete Python rewrite of Node.js Telegram bot → Claude Agent SDK integration
- SessionRunner with ClaudeSDKClient lifecycle, state machine, message queue
- Permission system: can_use_tool → asyncio.Future → Telegram inline buttons
- StatusUpdater with 30s refresh, tool tracking, typing indicator
- Voice transcription via faster-whisper, file I/O with MCP tools
- Multi-server TCP workers with auth, reconnection, permission bridge

### What Worked
- GSD autonomous mode drove the entire rewrite start-to-finish
- Research phase caught critical SDK gotchas (dummy PreToolUse hook, allowed_tools not runtime-updateable)
- Plan checker caught dependency conflict (01-03 vs 01-02 on dispatcher.py) before execution
- Integration checker found closure late-binding bug before shipping
- TDD approach in several phases caught issues early
- Sequential wave execution prevented cross-plan conflicts

### What Was Inefficient
- Phase 5 and 6 could have had research + verification in parallel to save time
- Some test files were not created by Wave 0 plans (VALIDATION.md Wave 0 lists diverged from plan structure)
- SUMMARY.md one_liner extraction didn't work (format mismatch with CLI tool)

### Patterns Established
- asyncio.Future bridge pattern for Telegram ↔ SDK callbacks
- WorkerOutputChannel adapter pattern for reusing SessionRunner on remote workers
- Length-prefixed msgspec framing for IPC protocol
- DI pattern through aiogram dispatcher for singleton services

### Key Lessons
- claude-agent-sdk API surface verified from installed source is more reliable than docs
- Closure late-binding in Python async loops is a real production risk — always pass by parameter
- aiogram 3 CallbackData 64-byte limit is safe for UUID-based callback schemes

### Cost Observations
- Model mix: opus for planning, sonnet for research/verification/execution
- 6 phases completed in ~1 session
- Notable: plan checker iterations were minimal (1-2 per phase), research was targeted

---

## Cross-Milestone Trends

| Metric | v1.0 |
|--------|------|
| Phases | 6 |
| Plans | 18 |
| Tests | 104 |
| LOC (src) | 2,862 |
| LOC (tests) | 2,002 |
| Bugs caught pre-ship | 2 |
