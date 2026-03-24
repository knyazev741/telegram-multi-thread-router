# Phase 3: Permission System — Research

**Researched:** 2026-03-24
**Domain:** claude-agent-sdk can_use_tool callback + asyncio.Future bridge + aiogram 3 inline keyboards
**Confidence:** HIGH (all SDK internals inspected from installed package; aiogram APIs verified from installed package)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Permission Message Format:**
- Tool name + input summary (first 500 chars, "..." if truncated) + numbered options in message body
- 3 inline buttons: 1️⃣ Allow once, 2️⃣ Allow always, 3️⃣ Deny
- HTML parse mode for code formatting in tool input display
- Options text written in message body, buttons only show numbers

**Permission Lifecycle:**
- asyncio.Future per permission request — can_use_tool awaits future, callback query handler resolves it
- Timeout 5 min → auto-deny + "⏱ Permission timed out — denied" message + edit original to show expired
- Stale button taps → answer_callback_query with "This permission has expired" alert (never leave spinner)
- Pending permissions in memory only (asyncio.Future) — don't survive bot restart

**Auto-Allow Rules:**
- Default auto-allow: Read, Glob, Grep, Agent (Explore subagent) — safe read-only tools
- "Allow always" adds tool name to session's allowed_tools list — checked before can_use_tool fires
- Per-session allowed_tools — different projects have different risk profiles
- No revoke in v1 — restart session to reset

### Claude's Discretion
- PermissionManager internal data structures
- Callback data encoding scheme for inline buttons
- Exact HTML formatting template for permission messages
- How to handle rapid sequential permission requests (queue vs display all)

### Deferred Ideas (OUT OF SCOPE)
- Batched permission display for rapid requests (v2)
- Per-session permission profiles stored in SQLite (v2)
- /revoke command to reset allowed_tools (v2)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PERM-01 | `can_use_tool` callback intercepts tool permission requests | SDK `CanUseTool` type alias + `_handle_control_request` flow verified |
| PERM-02 | Permission request displayed as Telegram message with question + full option text in body | aiogram `bot.send_message` + HTML parse_mode pattern |
| PERM-03 | Inline keyboard shows only numbered buttons (1️⃣, 2️⃣, 3️⃣) mapped to options | `InlineKeyboardBuilder.button(callback_data=...)` verified |
| PERM-04 | User taps button → callback resolved → Claude continues | asyncio.Future + `PermissionManager.resolve()` + `@router.callback_query` pattern |
| PERM-05 | Permission timeout (5 min) auto-denies if user doesn't respond | `asyncio.wait_for(future, timeout=300)` + `PermissionResultDeny` |
| PERM-06 | "Allow always" option adds tool pattern to session's allowed_tools | `PermissionResultAllow(updated_permissions=[PermissionUpdate(type='addRules', ...)])` + per-session list |
| PERM-07 | Safe tools (Read, Glob, Grep, Explore agent) auto-approved via allowed_tools list | Pre-check in `can_use_tool` before creating Future |
| PERM-08 | Stale permission buttons answered with "expired" on callback query | `query.answer(text="This permission has expired", show_alert=True)` |
| PERM-09 | Dummy PreToolUse hook registered to ensure can_use_tool fires (SDK requirement) | Already implemented in `runner.py` — must be preserved |
</phase_requirements>

---

## Summary

Phase 3 replaces the `_auto_allow_tool` placeholder in `SessionRunner` with a real permission system. The core mechanism is an `asyncio.Future` stored in `PermissionManager`: `can_use_tool` creates the future, sends a Telegram message with inline buttons, and awaits the future (with a 5-minute timeout). When the user taps a button, the aiogram `callback_query` handler resolves the future and `can_use_tool` returns the appropriate `PermissionResultAllow` or `PermissionResultDeny`.

The "Allow always" path is more nuanced than it appears. `allowed_tools` is passed as a CLI flag (`--allowedTools`) to the Claude subprocess **at startup time only** — it cannot be updated at runtime through `ClaudeAgentOptions`. Instead, "Allow always" uses two mechanisms: (1) `PermissionResultAllow(updated_permissions=[PermissionUpdate(type='addRules', rules=[PermissionRuleValue(tool_name=...)], behavior='allow')])` which sends the update through the control protocol JSON back to the CLI subprocess's internal permission engine, and (2) a per-session `allowed_tools: set[str]` stored in `SessionRunner` that is checked first in `can_use_tool` to short-circuit future requests for the same tool.

The dummy `PreToolUse` hook is already correctly implemented in `runner.py` (Phase 2 decision) and must be preserved. The existing `SessionState.WAITING_PERMISSION` state is stubbed and ready to activate.

**Primary recommendation:** Implement `PermissionManager` as a standalone class in `src/sessions/permissions.py`, wire it into dispatcher DI in `on_startup`, pass it to `SessionRunner` at construction, and add `@router.callback_query(PermissionCallback.filter())` to `session_router`.

---

## Standard Stack

### Core (already installed — no new dependencies needed)

| Library | Version | Purpose | Notes |
|---------|---------|---------|-------|
| claude-agent-sdk | 0.1.50 (installed) | `CanUseTool` callback, `PermissionResultAllow`, `PermissionResultDeny`, `PermissionUpdate`, `PermissionRuleValue` | All types verified from installed package |
| aiogram | 3.26.0 (installed) | `CallbackData`, `InlineKeyboardBuilder`, `@router.callback_query` | All APIs verified from installed package |
| asyncio | stdlib | `asyncio.Future`, `asyncio.wait_for` | No new install |

**No new packages required for Phase 3.**

---

## Architecture Patterns

### Recommended Project Structure (additions for Phase 3)

```
src/
├── sessions/
│   ├── runner.py          # MODIFY: replace _auto_allow_tool, add PermissionManager ref
│   ├── permissions.py     # NEW: PermissionManager class
│   └── state.py           # UNCHANGED: WAITING_PERMISSION already stubbed
├── bot/
│   ├── dispatcher.py      # MODIFY: wire PermissionManager in on_startup, pass to runners
│   └── routers/
│       └── session.py     # MODIFY: add callback_query handler
```

### Pattern 1: PermissionManager — asyncio.Future Store

**What:** Singleton class that maps `request_id → asyncio.Future`. Created in `on_startup`, stored in dispatcher dict, injected into `SessionRunner` and callback handler via aiogram DI.

**Example:**
```python
# src/sessions/permissions.py
import asyncio
import uuid

class PermissionManager:
    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future] = {}

    def create_request(self) -> tuple[str, asyncio.Future]:
        """Returns (request_id, future). Caller awaits the future."""
        request_id = str(uuid.uuid4())
        loop = asyncio.get_event_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = future
        return request_id, future

    def resolve(self, request_id: str, action: str) -> bool:
        """Resolve a pending future. Returns False if not found (stale)."""
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(action)
        return True

    def expire(self, request_id: str) -> None:
        """Called on timeout — removes from pending without resolving."""
        self._pending.pop(request_id, None)
```

### Pattern 2: CanUseTool Callback with Pre-Check and Future Await

**What:** Replaces `_auto_allow_tool`. Checks per-session `allowed_tools` first (skips Telegram message for auto-approved tools). For all others, creates a future, sends Telegram permission message, awaits with timeout.

**Critical: `can_use_tool` is called by the SDK with signature `(tool_name: str, input_data: dict, context: ToolPermissionContext) -> PermissionResultAllow | PermissionResultDeny`.**

```python
# Inside SessionRunner — replaces _auto_allow_tool
async def _can_use_tool(
    self,
    tool_name: str,
    input_data: dict,
    context: ToolPermissionContext,
) -> PermissionResultAllow | PermissionResultDeny:
    # Check per-session always-allow list first
    if tool_name in self._allowed_tools:
        return PermissionResultAllow(updated_input=input_data)

    # Transition state
    prev_state = self.state
    self.state = SessionState.WAITING_PERMISSION

    request_id, future = self._permission_manager.create_request()
    try:
        await self._send_permission_message(request_id, tool_name, input_data)
        action = await asyncio.wait_for(future, timeout=300.0)
    except asyncio.TimeoutError:
        self._permission_manager.expire(request_id)
        self.state = prev_state
        await self._bot.send_message(
            chat_id=self._chat_id,
            message_thread_id=self.thread_id,
            text="⏱ Permission timed out — denied",
        )
        return PermissionResultDeny(message="Timed out — user did not respond within 5 minutes")
    finally:
        self.state = prev_state

    if action == "allow":
        return PermissionResultAllow(updated_input=input_data)
    elif action == "always":
        self._allowed_tools.add(tool_name)
        return PermissionResultAllow(
            updated_input=input_data,
            updated_permissions=[
                PermissionUpdate(
                    type="addRules",
                    rules=[PermissionRuleValue(tool_name=tool_name)],
                    behavior="allow",
                )
            ],
        )
    else:  # "deny"
        return PermissionResultDeny(message="Denied by user")
```

### Pattern 3: CallbackData Factory for Type-Safe Callbacks

**What:** aiogram `CallbackData` subclass with `prefix` keyword argument. Packs to `"perm:allow:uuid"` format. Max callback data length is 64 bytes — a full UUID (`36 chars`) + `"perm:allow:"` = 47 bytes total, safely within limit.

```python
# src/bot/routers/session.py (or separate callbacks.py)
from aiogram.filters.callback_data import CallbackData

class PermissionCallback(CallbackData, prefix="perm"):
    action: str      # "allow", "always", "deny"
    request_id: str  # full UUID, verified 47 bytes max
```

### Pattern 4: Inline Keyboard Builder

**What:** `InlineKeyboardBuilder` builds 3-button row. Buttons pass `PermissionCallback` instances directly as `callback_data`.

```python
# Source: aiogram 3.26.0 InlineKeyboardBuilder.button() signature (verified)
from aiogram.utils.keyboard import InlineKeyboardBuilder

def _build_permission_keyboard(request_id: str) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="1️⃣", callback_data=PermissionCallback(action="allow", request_id=request_id))
    builder.button(text="2️⃣", callback_data=PermissionCallback(action="always", request_id=request_id))
    builder.button(text="3️⃣", callback_data=PermissionCallback(action="deny", request_id=request_id))
    builder.adjust(3)  # all 3 buttons in one row
    return builder.as_markup()
```

### Pattern 5: Callback Query Handler Registration

**What:** `@router.callback_query(PermissionCallback.filter())` registers the handler only for matching callbacks. The `callback_data` kwarg is automatically parsed and injected by aiogram DI when the type annotation is present.

```python
# src/bot/routers/session.py
from aiogram.types import CallbackQuery

@session_router.callback_query(PermissionCallback.filter())
async def handle_permission_callback(
    query: CallbackQuery,
    callback_data: PermissionCallback,
    permission_manager: PermissionManager,
) -> None:
    # MUST answer immediately — even for stale requests
    resolved = permission_manager.resolve(callback_data.request_id, callback_data.action)
    if not resolved:
        await query.answer(text="This permission has expired", show_alert=True)
        return
    await query.answer()  # dismiss spinner
    # Edit original message to remove keyboard + show result
    if query.message:
        label = {"allow": "Allowed once", "always": "Always allowed", "deny": "Denied"}
        await query.message.edit_reply_markup(reply_markup=None)
        # Optionally edit text to show resolution
```

### Pattern 6: Wiring PermissionManager in Dispatcher

**What:** `PermissionManager` created in `on_startup`, stored in dispatcher dict, propagated by aiogram DI to handlers and runners.

```python
# src/bot/dispatcher.py on_startup
async def on_startup(bot: Bot, dispatcher: Dispatcher) -> None:
    await init_db()
    permission_manager = PermissionManager()
    dispatcher["permission_manager"] = permission_manager

    manager = SessionManager()
    dispatcher["session_manager"] = manager
    # Pass permission_manager to runners when creating them
    resumed = await manager.resume_all(bot, settings.group_chat_id, permission_manager)
    ...
```

**SessionRunner constructor needs new parameter:**
```python
class SessionRunner:
    def __init__(
        self,
        thread_id: int,
        workdir: str,
        bot: Bot,
        chat_id: int,
        permission_manager: PermissionManager,   # NEW
        session_id: str | None = None,
        model: str | None = None,
    ) -> None:
        ...
        self._permission_manager = permission_manager
        self._allowed_tools: set[str] = {"Read", "Glob", "Grep", "Agent"}  # PERM-07
```

### Pattern 7: Permission Message Formatting (HTML)

**What:** Message body contains full question text with numbered options. Buttons show only numbers. Tool input truncated to 500 chars.

```python
async def _send_permission_message(
    self,
    request_id: str,
    tool_name: str,
    input_data: dict,
) -> None:
    import json
    raw = json.dumps(input_data, indent=2)
    summary = raw[:500] + ("..." if len(raw) > 500 else "")
    text = (
        f"<b>Tool permission request</b>\n\n"
        f"<b>Tool:</b> <code>{tool_name}</code>\n"
        f"<b>Input:</b>\n<pre>{summary}</pre>\n\n"
        f"1️⃣ Allow once\n"
        f"2️⃣ Allow always\n"
        f"3️⃣ Deny"
    )
    await self._bot.send_message(
        chat_id=self._chat_id,
        message_thread_id=self.thread_id,
        text=text,
        parse_mode="HTML",
        reply_markup=_build_permission_keyboard(request_id),
    )
```

### Anti-Patterns to Avoid

- **Calling `query.answer()` after async work**: Call `await query.answer()` as the FIRST line of every callback handler (or at minimum before any awaits that could fail). Telegram shows a spinner until `answer_callback_query` is called.
- **Not handling stale callbacks**: Always check if `resolve()` returned `False` and call `query.answer(show_alert=True)` with an expiry message. Never silently skip `answer_callback_query`.
- **Passing `allowed_tools` as runtime-updateable**: `allowed_tools` is a CLI flag at subprocess start — it cannot be changed after the ClaudeSDKClient is connected. For "allow always", use `PermissionResultAllow(updated_permissions=[...])` to update the CLI subprocess's internal engine AND maintain a Python-side `_allowed_tools: set[str]` in `SessionRunner` for pre-checks.
- **Storing `PermissionManager` futures in SQLite**: CONTEXT.md decision: memory-only. Futures don't survive restart — that is acceptable and expected.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Callback data encoding | Custom string formatting/parsing | `CallbackData` factory subclass | Handles max-length validation (64 bytes), separator escaping, type-safe parsing |
| Inline keyboard layout | Raw `InlineKeyboardMarkup` + `InlineKeyboardButton` lists | `InlineKeyboardBuilder` + `.adjust()` | Cleaner API, less boilerplate |
| UUID generation for request IDs | Custom ID schemes | `uuid.uuid4()` | Collision-free, fits within 64-byte callback limit (47 bytes total with prefix) |
| Future-based async bridge | Custom event/queue | `asyncio.Future` + `asyncio.wait_for` | Exactly designed for this: pause coroutine, resume from external event |

---

## Common Pitfalls

### Pitfall 1: Callback Spinner Left Hanging (CRITICAL)

**What goes wrong:** `answer_callback_query` not called → Telegram client shows loading spinner indefinitely.

**How to avoid:** In `handle_permission_callback`, resolve the future first, then call `await query.answer()`. For stale requests, call `await query.answer(text="...", show_alert=True)` before returning. Never exit the handler without answering.

**Verified in:** `aiogram.types.CallbackQuery.answer(self, text=None, show_alert=None, ...)` — confirmed callable with no args for dismissal.

### Pitfall 2: allowed_tools Cannot Be Updated at Runtime

**What goes wrong:** Developer stores "allow always" selections in `ClaudeAgentOptions.allowed_tools` expecting them to affect the running session. They won't — `allowed_tools` is passed as `--allowedTools` CLI flag only at subprocess startup.

**Confirmed by:** `subprocess_cli.py` lines 162-163: `cmd.extend(["--allowedTools", ",".join(self._options.allowed_tools)])`.

**How to avoid:** Two-track approach:
1. `PermissionResultAllow(updated_permissions=[PermissionUpdate(type='addRules', ...)])` — updates CLI subprocess's internal permission engine via control protocol JSON.
2. `SessionRunner._allowed_tools: set[str]` — Python-side pre-check, bypasses the `can_use_tool` callback entirely for future calls in the same session.

### Pitfall 3: asyncio.Future Created in Wrong Event Loop

**What goes wrong:** `asyncio.get_event_loop().create_future()` in Python 3.10+ may behave unexpectedly if called from a different context. In Python 3.14 (project is on Python 3.14 per `.venv/lib/python3.14/`), use `asyncio.get_running_loop()`.

**How to avoid:** Use `asyncio.get_running_loop().create_future()` inside `PermissionManager.create_request()` — this is always called from within a running async context.

### Pitfall 4: State Not Restored on Timeout

**What goes wrong:** `SessionState.WAITING_PERMISSION` set before awaiting future, but state not restored to previous value if timeout fires.

**How to avoid:** Use `try/except asyncio.TimeoutError/finally` to restore `self.state` in all code paths (shown in Pattern 2).

### Pitfall 5: OwnerAuthMiddleware Not Applied to callback_query

**What goes wrong:** `OwnerAuthMiddleware` is registered only on `dp.message.outer_middleware`. `CallbackQuery` updates bypass it entirely.

**How to avoid:** For a single-owner bot this is acceptable — the inline buttons are only shown to the owner in the first place. However, the callback handler should verify the `query.from_user.id` matches `settings.owner_user_id` defensively if the bot is ever in a shared group. Add a guard if paranoia is warranted:

```python
if query.from_user and query.from_user.id != settings.owner_user_id:
    await query.answer()  # silently dismiss
    return
```

### Pitfall 6: Permission Message Escaping in HTML Mode

**What goes wrong:** Tool input data (e.g., bash commands with `<`, `>`, `&`) breaks HTML parse mode.

**How to avoid:** Escape the `summary` string before embedding in HTML `<pre>` tags:

```python
import html
summary_escaped = html.escape(summary)
text = f"...<pre>{summary_escaped}</pre>..."
```

---

## Code Examples

### Exact `can_use_tool` Callback Signature (verified from SDK source)

```python
# Source: claude_agent_sdk.types.CanUseTool type alias (verified)
# Callable[[str, dict[str, Any], ToolPermissionContext], Awaitable[PermissionResultAllow | PermissionResultDeny]]

async def can_use_tool(
    tool_name: str,
    input_data: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionResultAllow | PermissionResultDeny:
    ...
```

### PermissionResultAllow (verified from SDK source)

```python
# Source: claude_agent_sdk.types.PermissionResultAllow (verified from .venv)
@dataclass
class PermissionResultAllow:
    behavior: Literal["allow"] = "allow"        # auto-set, don't pass
    updated_input: dict[str, Any] | None = None  # pass original input_data
    updated_permissions: list[PermissionUpdate] | None = None  # for "allow always"
```

### PermissionResultDeny (verified from SDK source)

```python
# Source: claude_agent_sdk.types.PermissionResultDeny (verified from .venv)
@dataclass
class PermissionResultDeny:
    behavior: Literal["deny"] = "deny"  # auto-set
    message: str = ""                    # shown to Claude
    interrupt: bool = False              # True = also interrupt current task
```

### PermissionUpdate for "Allow Always" (verified from SDK source)

```python
# Source: claude_agent_sdk.types.PermissionUpdate + PermissionRuleValue (verified from .venv)
from claude_agent_sdk.types import PermissionUpdate, PermissionRuleValue

PermissionResultAllow(
    updated_input=input_data,
    updated_permissions=[
        PermissionUpdate(
            type="addRules",
            rules=[PermissionRuleValue(tool_name=tool_name)],
            behavior="allow",
        )
    ],
)
# Serializes to: {"behavior": "allow", "updatedInput": ..., "updatedPermissions": [{"type": "addRules", "rules": [{"toolName": "Bash", "ruleContent": null}], "behavior": "allow"}]}
```

### PermissionCallback (64-byte limit verified)

```python
# Full UUID packs to 47 bytes with prefix "perm" — safely within 64-byte limit
# Verified: perm:allow:649ce0ad-47c3-4077-9db1-84fb71b421e3 = 47 bytes
from aiogram.filters.callback_data import CallbackData

class PermissionCallback(CallbackData, prefix="perm"):
    action: str      # "allow" | "always" | "deny"
    request_id: str  # uuid4 string
```

### Registering ClaudeAgentOptions with Method Reference

```python
# In SessionRunner._run():
options = ClaudeAgentOptions(
    cwd=self.workdir,
    model=self.model,
    system_prompt=system_prompt,
    can_use_tool=self._can_use_tool,   # bound method replaces _auto_allow_tool
    hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[_dummy_pretool_hook])]},  # KEEP THIS
    resume=self.session_id,
    include_partial_messages=True,
)
```

---

## State of the Art

| Old Approach | Current Approach | Notes |
|--------------|-----------------|-------|
| `--dangerously-skip-permissions` | `can_use_tool` callback | SDK 0.1.50 provides proper hook |
| `allowed_tools` runtime update | `PermissionResultAllow(updated_permissions=[...])` + Python-side set | CLI flag only at startup |

---

## Open Questions

1. **GitHub issue #227 — `can_use_tool` may be skipped in multi-turn sessions**
   - What we know: Issue exists, noted in STATE.md under Blockers/Concerns
   - What's unclear: Whether it affects this project's specific usage pattern (single session, always a PreToolUse hook present)
   - Recommendation: During Phase 3 validation, explicitly test multi-turn permission flow (send a message that triggers multiple tool uses across turns). If can_use_tool is skipped, the CONTEXT.md notes the dummy PreToolUse hook is already in place per the Phase 2 decision.

2. **Rapid sequential permission requests (Claude's discretion)**
   - What we know: Multiple tool calls within one turn each trigger `can_use_tool` sequentially
   - What's unclear: User experience when 3+ permission requests queue up
   - Recommendation: Display all concurrently (each gets its own Telegram message + buttons). The `asyncio.wait_for` for each runs independently. Simpler than batching and avoids blocking later requests on earlier ones.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio 0.24 |
| Config file | `pyproject.toml` — `asyncio_mode = "auto"` |
| Quick run command | `uv run pytest tests/test_permissions.py -x -q` |
| Full suite command | `uv run pytest tests/ -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PERM-01 | `can_use_tool` is called by SDK | unit | `pytest tests/test_permissions.py::test_can_use_tool_called -x` | ❌ Wave 0 |
| PERM-02 | Permission message sent to Telegram with correct format | unit | `pytest tests/test_permissions.py::test_permission_message_format -x` | ❌ Wave 0 |
| PERM-03 | Inline keyboard has 3 numbered buttons | unit | `pytest tests/test_permissions.py::test_keyboard_has_three_buttons -x` | ❌ Wave 0 |
| PERM-04 | Button tap resolves future → Claude continues | unit | `pytest tests/test_permissions.py::test_callback_resolves_future -x` | ❌ Wave 0 |
| PERM-05 | Timeout fires after 5 min → auto-deny + message | unit | `pytest tests/test_permissions.py::test_timeout_auto_deny -x` | ❌ Wave 0 |
| PERM-06 | "Allow always" adds to session allowed_tools + PermissionUpdate | unit | `pytest tests/test_permissions.py::test_allow_always_updates_list -x` | ❌ Wave 0 |
| PERM-07 | Auto-allow tools skip Telegram message entirely | unit | `pytest tests/test_permissions.py::test_auto_allow_skip_message -x` | ❌ Wave 0 |
| PERM-08 | Stale callback answered with "expired" alert | unit | `pytest tests/test_permissions.py::test_stale_callback_answered -x` | ❌ Wave 0 |
| PERM-09 | Dummy PreToolUse hook present in ClaudeAgentOptions | unit | `pytest tests/test_permissions.py::test_dummy_hook_registered -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `uv run pytest tests/test_permissions.py -x -q`
- **Per wave merge:** `uv run pytest tests/ -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_permissions.py` — new file covering all PERM-01 through PERM-09
- [ ] `tests/conftest.py` — add `permission_manager` fixture (already exists, needs extension)

No framework install needed — pytest + pytest-asyncio already installed and configured.

---

## Sources

### Primary (HIGH confidence — inspected from installed package at `.venv/lib/python3.14/site-packages/claude_agent_sdk/`)

- `claude_agent_sdk/__init__.py` — full export list, confirmed `PermissionResultAllow`, `PermissionResultDeny`, `PermissionUpdate`, `PermissionRuleValue`, `CanUseTool`, `ToolPermissionContext`
- `claude_agent_sdk/types.py` — dataclass definitions for all permission types, `ClaudeAgentOptions` fields
- `claude_agent_sdk/_internal/query.py` — `_handle_control_request()` — exact can_use_tool invocation, response serialization, `updated_permissions` → `updatedPermissions` control protocol
- `claude_agent_sdk/_internal/transport/subprocess_cli.py` — `--allowedTools` passed at subprocess start (lines 162-163), confirmed not runtime-updatable
- `aiogram.filters.callback_data.CallbackData` — `MAX_CALLBACK_LENGTH = 64`, separator pattern, pack/unpack
- `aiogram.utils.keyboard.InlineKeyboardBuilder.button()` — signature verified, accepts `CallbackData` directly as `callback_data`
- `aiogram.types.CallbackQuery.answer()` — signature: `(text=None, show_alert=None, ...)` verified

### Secondary (MEDIUM confidence)

- `.planning/research/ARCHITECTURE.md` — Permission Future pattern, PermissionManager design (previously researched, consistent with SDK inspection)
- `.planning/research/PITFALLS.md` — Stale callback pitfall, timeout pitfall (consistent with SDK inspection)

### Known Issues (from STATE.md)

- GitHub issue #18735 — dummy PreToolUse hook required (already addressed in Phase 2, `runner.py` line 80)
- GitHub issue #227 — `can_use_tool` may be skipped in multi-turn sessions; flagged for Phase 3 validation

---

## Metadata

**Confidence breakdown:**
- SDK callback signatures: HIGH — inspected from installed `.venv` package source
- `allowed_tools` runtime behavior: HIGH — confirmed from `subprocess_cli.py` source
- `PermissionUpdate` → `updated_permissions` serialization: HIGH — traced through `query.py` control protocol
- aiogram `CallbackData` 64-byte limit: HIGH — `MAX_CALLBACK_LENGTH` constant verified
- `answer_callback_query` must-call requirement: HIGH — verified from aiogram docs + pitfalls research

**Research date:** 2026-03-24
**Valid until:** 2026-04-24 (stable SDK — unlikely to change within 30 days)
