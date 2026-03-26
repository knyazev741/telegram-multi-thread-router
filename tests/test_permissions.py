"""Tests covering PERM-01 through PERM-09 permission system requirements."""

from __future__ import annotations

import asyncio
import html
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from claude_agent_sdk import PermissionResultAllow, PermissionResultDeny


# ---------------------------------------------------------------------------
# PERM-01: can_use_tool callback intercepts tool permission requests
# ---------------------------------------------------------------------------

async def test_can_use_tool_called(session_runner, permission_manager):
    """PERM-01: _can_use_tool sends a Telegram message and awaits user decision."""

    async def _auto_resolve():
        # Wait until the request appears in pending, then resolve it.
        for _ in range(50):
            await asyncio.sleep(0.01)
            if permission_manager.pending_count > 0:
                for request_id in list(permission_manager._pending.keys()):
                    permission_manager.resolve(request_id, "allow")
                return
        raise RuntimeError("Permission request never appeared in pending")

    resolve_task = asyncio.create_task(_auto_resolve())
    result = await session_runner._can_use_tool("Bash", {"command": "ls"}, MagicMock())
    await resolve_task

    assert isinstance(result, PermissionResultAllow)
    assert session_runner._bot.send_message.called


# ---------------------------------------------------------------------------
# PERM-02: Permission message format
# ---------------------------------------------------------------------------

async def test_permission_message_format():
    """PERM-02: format_permission_message produces correct HTML with escaped input."""
    from src.sessions.permissions import format_permission_message

    msg = format_permission_message("Bash", {"command": "rm -rf /"})
    assert "<code>Bash</code>" in msg
    assert "<pre>" in msg
    assert "Allow once" in msg
    assert "Allow always" in msg
    assert "Deny" in msg

    # XSS safety: angle brackets must be escaped
    xss_msg = format_permission_message("Bash", {"command": "<script>alert(1)</script>"})
    assert "<script>" not in xss_msg
    assert html.escape("<script>") in xss_msg or "&lt;script&gt;" in xss_msg


# ---------------------------------------------------------------------------
# PERM-03: Inline keyboard has 3 numbered buttons
# ---------------------------------------------------------------------------

async def test_keyboard_has_three_buttons():
    """PERM-03: build_permission_keyboard returns 1 row with exactly 3 emoji buttons."""
    from src.sessions.permissions import build_permission_keyboard

    markup = build_permission_keyboard("test-uuid")
    assert len(markup.inline_keyboard) == 1
    row = markup.inline_keyboard[0]
    assert len(row) == 3
    texts = [btn.text for btn in row]
    assert "1\ufe0f\u20e3" in texts
    assert "2\ufe0f\u20e3" in texts
    assert "3\ufe0f\u20e3" in texts


# ---------------------------------------------------------------------------
# PERM-04: Button tap resolves future, Claude continues
# ---------------------------------------------------------------------------

async def test_callback_resolves_future(permission_manager):
    """PERM-04: resolve() completes the future with the chosen action."""
    request_id, future = permission_manager.create_request()
    resolved = permission_manager.resolve(request_id, "allow")

    assert resolved is True
    assert future.done()
    assert future.result() == "allow"


# ---------------------------------------------------------------------------
# PERM-05: Timeout auto-deny after 5 minutes
# ---------------------------------------------------------------------------

async def test_timeout_auto_deny(session_runner, permission_manager):
    """PERM-05: If user does not respond, _can_use_tool returns PermissionResultDeny."""
    with patch("asyncio.wait_for", side_effect=asyncio.TimeoutError):
        result = await session_runner._can_use_tool("Bash", {"command": "ls"}, MagicMock())

    assert isinstance(result, PermissionResultDeny)
    assert "permission timeout" in result.message.lower()
    assert permission_manager.pending_count == 0


# ---------------------------------------------------------------------------
# PERM-06: "Allow always" adds tool to _allowed_tools + returns PermissionUpdate
# ---------------------------------------------------------------------------

async def test_allow_always_updates_list(session_runner, permission_manager):
    """PERM-06: 'always' action adds tool to session allowed list with PermissionUpdate."""

    async def _auto_resolve():
        for _ in range(50):
            await asyncio.sleep(0.01)
            if permission_manager.pending_count > 0:
                for request_id in list(permission_manager._pending.keys()):
                    permission_manager.resolve(request_id, "always")
                return
        raise RuntimeError("Permission request never appeared in pending")

    resolve_task = asyncio.create_task(_auto_resolve())
    result = await session_runner._can_use_tool("Bash", {"command": "ls"}, MagicMock())
    await resolve_task

    assert "Bash" in session_runner._allowed_tools
    assert result.updated_permissions is not None
    assert len(result.updated_permissions) == 1
    perm = result.updated_permissions[0]
    assert perm.type == "addRules"
    assert perm.rules[0].tool_name == "Bash"


# ---------------------------------------------------------------------------
# PERM-07: Safe tools auto-approved without Telegram message
# ---------------------------------------------------------------------------

async def test_auto_allow_skip_message(session_runner):
    """PERM-07: Pre-approved safe tools are allowed without sending a Telegram message."""
    safe_tools = ["Read", "Glob", "Grep", "Agent"]
    for tool in safe_tools:
        result = await session_runner._can_use_tool(tool, {}, MagicMock())
        assert isinstance(result, PermissionResultAllow), f"{tool} should be auto-allowed"

    assert session_runner._bot.send_message.call_count == 0


# ---------------------------------------------------------------------------
# PERM-08: Stale callback answered with "expired"
# ---------------------------------------------------------------------------

async def test_stale_callback_answered(permission_manager):
    """PERM-08: Resolving a nonexistent or already-resolved request returns False."""
    # Unknown request_id
    resolved = permission_manager.resolve("nonexistent-uuid", "allow")
    assert resolved is False

    # Already resolved — second call should return False
    request_id, future = permission_manager.create_request()
    first = permission_manager.resolve(request_id, "allow")
    assert first is True
    second = permission_manager.resolve(request_id, "deny")
    assert second is False


# ---------------------------------------------------------------------------
# PERM-09: Dummy PreToolUse hook preserved
# ---------------------------------------------------------------------------

async def test_dummy_hook_registered():
    """PERM-09: _dummy_pretool_hook is callable and returns continue_=True."""
    from src.sessions.runner import _dummy_pretool_hook

    assert callable(_dummy_pretool_hook)
    result = await _dummy_pretool_hook({}, "test-id", MagicMock())
    assert result == {"continue_": True}
