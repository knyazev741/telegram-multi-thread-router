"""Permission bridge — asyncio.Future store and Telegram UI helpers for tool permission requests."""

from __future__ import annotations

import asyncio
import html
import json
import uuid

from aiogram.filters.callback_data import CallbackData
from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder


class PermissionCallback(CallbackData, prefix="perm"):
    """Inline button callback data for tool permission requests.

    Packs to "perm:allow:<uuid>" = 47 bytes max — safely within Telegram's 64-byte limit.
    """

    action: str     # "allow" | "always" | "deny"
    request_id: str  # uuid4 string (36 chars)


def build_permission_keyboard(request_id: str) -> InlineKeyboardMarkup:
    """Build a 3-button inline keyboard for a permission request.

    Buttons: 1️⃣ Allow once, 2️⃣ Allow always, 3️⃣ Deny
    """
    builder = InlineKeyboardBuilder()
    builder.button(text="1\ufe0f\u20e3", callback_data=PermissionCallback(action="allow", request_id=request_id))
    builder.button(text="2\ufe0f\u20e3", callback_data=PermissionCallback(action="always", request_id=request_id))
    builder.button(text="3\ufe0f\u20e3", callback_data=PermissionCallback(action="deny", request_id=request_id))
    builder.adjust(3)
    return builder.as_markup()


def format_permission_message(tool_name: str, input_data: dict) -> str:
    """Format an HTML permission request message.

    Tool input is truncated to 500 chars and HTML-escaped before embedding in <pre> tags.
    """
    raw = json.dumps(input_data, indent=2)
    summary = raw[:500] + ("..." if len(raw) > 500 else "")
    summary_escaped = html.escape(summary)
    return (
        f"<b>Tool permission request</b>\n\n"
        f"<b>Tool:</b> <code>{tool_name}</code>\n"
        f"<b>Input:</b>\n<pre>{summary_escaped}</pre>\n\n"
        f"1\ufe0f\u20e3 Allow once\n"
        f"2\ufe0f\u20e3 Allow always\n"
        f"3\ufe0f\u20e3 Deny"
    )


class PermissionManager:
    """Stores pending permission futures keyed by request_id.

    Thread-safe only within a single asyncio event loop (which is the project's deployment model).
    Futures do not survive bot restart — this is by design (CONTEXT.md decision).
    """

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future] = {}

    def create_request(self) -> tuple[str, asyncio.Future]:
        """Create a new pending permission request.

        Returns (request_id, future). Caller should await the future to receive the user's action.
        Uses asyncio.get_running_loop() per Python 3.14 requirement (Pitfall 3).
        """
        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future = loop.create_future()
        self._pending[request_id] = future
        return request_id, future

    def resolve(self, request_id: str, action: str) -> bool:
        """Resolve a pending future with the user's action choice.

        Returns True if resolved successfully, False if request not found or already done (stale).
        """
        future = self._pending.pop(request_id, None)
        if future is None or future.done():
            return False
        future.set_result(action)
        return True

    def expire(self, request_id: str) -> None:
        """Remove a pending request without resolving it. Called on timeout."""
        self._pending.pop(request_id, None)

    @property
    def pending_count(self) -> int:
        """Number of pending permission requests (useful for testing)."""
        return len(self._pending)
