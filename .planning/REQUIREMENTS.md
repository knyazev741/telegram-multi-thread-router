# Requirements: Telegram Multi-Thread Router v2

**Defined:** 2026-03-24
**Core Value:** Users can control multiple Claude Code sessions from Telegram with full interactivity — permissions, status, commands — without bypass-permissions hacks.

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Foundation

- [x] **FOUND-01**: Bot starts with aiogram 3 long polling and connects to configured group chat
- [x] **FOUND-02**: Bot only processes messages from OWNER_USER_ID
- [x] **FOUND-03**: SQLite database with WAL mode stores topics, sessions, and message history
- [x] **FOUND-04**: Forum topic routing: messages dispatched by message_thread_id to correct session
- [x] **FOUND-05**: Bot handles General topic (thread_id=1) for management commands

### Session Lifecycle

- [x] **SESS-01**: User can create a new session linked to a forum topic with `/new <name> <workdir> [server]`
- [x] **SESS-02**: User can list active sessions with status via `/list` command
- [x] **SESS-03**: User can stop a session via `/stop` command in the topic
- [x] **SESS-04**: ClaudeSDKClient instance created per session with correct cwd, model, system_prompt
- [x] **SESS-05**: Session state machine: idle → running → waiting_permission → running → idle
- [x] **SESS-06**: Session persists session_id to SQLite for resume capability
- [x] **SESS-07**: Bot auto-resumes all saved sessions on startup
- [x] **SESS-08**: Health monitoring detects zombie Claude processes and cleans up
- [x] **SESS-09**: User can interrupt running Claude via `/stop` or dedicated button

### Permission System

- [x] **PERM-01**: `can_use_tool` callback intercepts tool permission requests
- [x] **PERM-02**: Permission request displayed as Telegram message with question + full option text in body
- [x] **PERM-03**: Inline keyboard shows only numbered buttons (1️⃣, 2️⃣, 3️⃣) mapped to options
- [x] **PERM-04**: User taps button → callback resolved → Claude continues
- [x] **PERM-05**: Permission timeout (5 min) auto-denies if user doesn't respond
- [x] **PERM-06**: "Allow always" option adds tool pattern to session's allowed_tools
- [x] **PERM-07**: Safe tools (Read, Glob, Grep, Explore agent) auto-approved via allowed_tools list
- [x] **PERM-08**: Stale permission buttons answered with "expired" on callback query
- [x] **PERM-09**: Dummy PreToolUse hook registered to ensure can_use_tool fires (SDK requirement)

### Status & Output

- [x] **STAT-01**: Editable status message in thread showing current activity, updated every 30s
- [x] **STAT-02**: Status includes: current tool, elapsed time, tool call count
- [x] **STAT-03**: Claude text output sent as regular messages in correct thread
- [x] **STAT-04**: Long messages split at 4096 chars preserving code blocks
- [x] **STAT-05**: Typing indicator (sendChatAction) renewed every 4s while Claude works
- [x] **STAT-06**: ResultMessage triggers status update with final cost/duration summary
- [x] **STAT-07**: Error messages displayed with clear formatting in thread

### Input Handling

- [x] **INPT-01**: Text messages in topic forwarded to session via `client.query()`
- [x] **INPT-02**: Voice messages transcribed via faster-whisper, text sent to session
- [ ] **INPT-03**: Photos downloaded and path passed to Claude session
- [ ] **INPT-04**: Documents downloaded and path passed to Claude session
- [x] **INPT-05**: Slash commands (/clear, /compact, /reset) forwarded to Claude session
- [x] **INPT-06**: 👀 reaction on message when delivered to session

### File Output

- [x] **FILE-01**: Custom MCP tool `reply` sends text message to Telegram thread
- [x] **FILE-02**: Custom MCP tool `send_file` sends file/photo back to Telegram thread
- [x] **FILE-03**: Custom MCP tool `react` adds emoji reaction to a message
- [x] **FILE-04**: Custom MCP tool `edit_message` edits a previously sent message

### Multi-Server

- [ ] **MSRV-01**: Worker process runs on remote server, manages ClaudeSDKClient locally
- [ ] **MSRV-02**: Worker connects to central bot via authenticated TCP (auth_token)
- [ ] **MSRV-03**: TCP protocol: length-prefixed msgspec-encoded messages
- [ ] **MSRV-04**: Worker forwards all SDK events (text, tool use, permission, status) to bot
- [ ] **MSRV-05**: Bot forwards user messages and permission responses to worker
- [ ] **MSRV-06**: Worker auto-reconnects on TCP disconnect with exponential backoff
- [ ] **MSRV-07**: Bot tracks which server each session runs on
- [ ] **MSRV-08**: Local sessions also supported (bot runs worker in-process)

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Advanced UX

- **UX-01**: Streaming partial text (edit message as Claude generates)
- **UX-02**: Cost/token tracking dashboard per session
- **UX-03**: Session activity log searchable via Telegram

### Advanced Permissions

- **APERM-01**: Batched permission display (group rapid sequential requests)
- **APERM-02**: Per-session permission profiles (different auto-allow sets)

## Out of Scope

| Feature | Reason |
|---------|--------|
| Web dashboard | Telegram is the only interface |
| Multi-user access | Single owner only, OWNER_USER_ID check |
| Webhook mode | Long polling sufficient for single-user bot |
| Container orchestration | Manual server management |
| Chat history context in messages | SDK handles context internally |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| FOUND-01 | Phase 1 | Complete |
| FOUND-02 | Phase 1 | Complete |
| FOUND-03 | Phase 1 | Complete |
| FOUND-04 | Phase 1 | Complete |
| FOUND-05 | Phase 1 | Complete |
| SESS-01 | Phase 2 | Complete |
| SESS-02 | Phase 2 | Complete |
| SESS-03 | Phase 2 | Complete |
| SESS-04 | Phase 2 | Complete |
| SESS-05 | Phase 2 | Complete |
| SESS-06 | Phase 2 | Complete |
| SESS-07 | Phase 2 | Complete |
| SESS-08 | Phase 2 | Complete |
| SESS-09 | Phase 2 | Complete |
| PERM-01 | Phase 3 | Complete |
| PERM-02 | Phase 3 | Complete |
| PERM-03 | Phase 3 | Complete |
| PERM-04 | Phase 3 | Complete |
| PERM-05 | Phase 3 | Complete |
| PERM-06 | Phase 3 | Complete |
| PERM-07 | Phase 3 | Complete |
| PERM-08 | Phase 3 | Complete |
| PERM-09 | Phase 3 | Complete |
| STAT-01 | Phase 4 | Complete |
| STAT-02 | Phase 4 | Complete |
| STAT-03 | Phase 4 | Complete |
| STAT-04 | Phase 4 | Complete |
| STAT-05 | Phase 4 | Complete |
| STAT-06 | Phase 4 | Complete |
| STAT-07 | Phase 4 | Complete |
| INPT-01 | Phase 2 | Complete |
| INPT-02 | Phase 5 | Complete |
| INPT-03 | Phase 5 | Pending |
| INPT-04 | Phase 5 | Pending |
| INPT-05 | Phase 2 | Complete |
| INPT-06 | Phase 2 | Complete |
| FILE-01 | Phase 5 | Complete |
| FILE-02 | Phase 5 | Complete |
| FILE-03 | Phase 5 | Complete |
| FILE-04 | Phase 5 | Complete |
| MSRV-01 | Phase 6 | Pending |
| MSRV-02 | Phase 6 | Pending |
| MSRV-03 | Phase 6 | Pending |
| MSRV-04 | Phase 6 | Pending |
| MSRV-05 | Phase 6 | Pending |
| MSRV-06 | Phase 6 | Pending |
| MSRV-07 | Phase 6 | Pending |
| MSRV-08 | Phase 6 | Pending |

**Coverage:**
- v1 requirements: 40 total
- Mapped to phases: 40
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-24*
*Last updated: 2026-03-24 after initial definition*
