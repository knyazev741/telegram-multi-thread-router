"""Session topic router — messages forwarded to Claude sessions."""

import logging
import os
import tempfile
from pathlib import Path

from aiogram import F, Router
from aiogram.enums import ContentType
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message, ReactionTypeEmoji

from src.sessions.manager import SessionManager
from src.sessions.permissions import PermissionCallback, PermissionManager
from src.sessions.state import SessionState
from src.sessions.voice import transcribe_voice
from src.config import settings

logger = logging.getLogger(__name__)

session_router = Router(name="sessions")


@session_router.callback_query(PermissionCallback.filter())
async def handle_permission_callback(
    query: CallbackQuery,
    callback_data: PermissionCallback,
    permission_manager: PermissionManager,
) -> None:
    """Handle inline button taps for tool permission requests.

    Resolves the pending future in PermissionManager so can_use_tool() can return.
    """
    # Defensive owner check — OwnerAuthMiddleware covers Message events only
    if query.from_user and query.from_user.id != settings.owner_user_id:
        await query.answer()
        return

    resolved = permission_manager.resolve(callback_data.request_id, callback_data.action)

    if not resolved:
        # Stale button tap — future already resolved or expired
        await query.answer(text="This permission has expired", show_alert=True)
        return

    # CRITICAL: call answer() before any other awaits to dismiss spinner (Pitfall 1)
    await query.answer()

    # Remove inline keyboard and append resolution label to the message
    action_labels = {
        "allow": "Allowed once",
        "always": "Always allowed",
        "deny": "Denied",
    }
    label = action_labels.get(callback_data.action, callback_data.action)

    if query.message:
        try:
            await query.message.edit_text(
                query.message.text + f"\n\n<b>Result:</b> {label}",
                parse_mode="HTML",
                reply_markup=None,
            )
        except Exception as e:
            logger.warning("Failed to edit permission message: %s", e)


@session_router.message(
    F.message_thread_id.is_not(None),
    F.message_thread_id != 1,
    Command("stop"),
)
async def handle_stop(message: Message, session_manager: SessionManager) -> None:
    """Stop the Claude session in this topic."""
    thread_id = message.message_thread_id
    runner = session_manager.get(thread_id)
    if runner is None:
        await message.reply("No active session in this topic.")
        return

    await session_manager.stop(thread_id)
    await message.reply("Session stopped.")


@session_router.message(
    F.message_thread_id.is_not(None),
    F.message_thread_id != 1,
    F.content_type == ContentType.VOICE,
)
async def handle_voice(message: Message, session_manager: SessionManager) -> None:
    """Transcribe voice message and enqueue text to Claude session (INPT-02)."""
    thread_id = message.message_thread_id
    runner = session_manager.get(thread_id)

    if runner is None:
        return

    if runner.state == SessionState.STOPPED:
        await message.reply("Session is stopped. Use /new to create a new one.")
        return

    # React with 👀 to confirm receipt
    try:
        await message.react(reaction=[ReactionTypeEmoji(emoji="👀")])
    except Exception as e:
        logger.warning("Failed to add reaction: %s", e)

    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tmp_path = tmp.name
        await message.bot.download(file=message.voice.file_id, destination=tmp_path)
        text = await transcribe_voice(tmp_path)
        if not text.strip():
            await message.reply("Could not transcribe voice message.")
            return
        await runner.enqueue(text)
    except Exception as e:
        logger.error("Voice transcription error in thread %d: %s", thread_id, e)
        await message.reply(f"Voice transcription failed: {e}")
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


@session_router.message(
    F.message_thread_id.is_not(None),
    F.message_thread_id != 1,
    F.content_type == ContentType.PHOTO,
)
async def handle_photo(message: Message, session_manager: SessionManager) -> None:
    """Download photo to workdir and enqueue path description to Claude session (INPT-03)."""
    thread_id = message.message_thread_id
    runner = session_manager.get(thread_id)

    if runner is None:
        return

    if runner.state == SessionState.STOPPED:
        await message.reply("Session is stopped. Use /new to create a new one.")
        return

    # React with 👀 to confirm receipt
    try:
        await message.react(reaction=[ReactionTypeEmoji(emoji="👀")])
    except Exception as e:
        logger.warning("Failed to add reaction: %s", e)

    try:
        photo = message.photo[-1]
        dest = Path(runner.workdir) / f"photo_{photo.file_unique_id}.jpg"
        await message.bot.download(file=photo.file_id, destination=str(dest))
        caption = message.caption or ""
        enqueue_text = f"User sent a photo: {dest}\n{caption}".strip()
        await runner.enqueue(enqueue_text)
    except Exception as e:
        logger.error("Photo download error in thread %d: %s", thread_id, e)
        await message.reply(f"Failed to download photo: {e}")


@session_router.message(
    F.message_thread_id.is_not(None),
    F.message_thread_id != 1,
    F.content_type == ContentType.DOCUMENT,
)
async def handle_document(message: Message, session_manager: SessionManager) -> None:
    """Download document to workdir and enqueue path description to Claude session (INPT-04)."""
    thread_id = message.message_thread_id
    runner = session_manager.get(thread_id)

    if runner is None:
        return

    if runner.state == SessionState.STOPPED:
        await message.reply("Session is stopped. Use /new to create a new one.")
        return

    # React with 👀 to confirm receipt
    try:
        await message.react(reaction=[ReactionTypeEmoji(emoji="👀")])
    except Exception as e:
        logger.warning("Failed to add reaction: %s", e)

    try:
        filename = message.document.file_name or f"file_{message.document.file_unique_id}"
        dest = Path(runner.workdir) / filename
        await message.bot.download(file=message.document.file_id, destination=str(dest))
        caption = message.caption or ""
        enqueue_text = f"User sent file: {filename} at {dest}\n{caption}".strip()
        await runner.enqueue(enqueue_text)
    except Exception as e:
        logger.error("Document download error in thread %d: %s", thread_id, e)
        await message.reply(f"Failed to download file: {e}")


@session_router.message(
    F.message_thread_id.is_not(None),
    F.message_thread_id != 1,
)
async def handle_session_message(message: Message, session_manager: SessionManager) -> None:
    """Forward text messages to the Claude session, including /clear /compact /reset.

    Note: /clear, /compact, /reset are NOT intercepted by Command filters — they are
    forwarded as raw text via runner.enqueue(text). This lets Claude handle them internally.
    """
    thread_id = message.message_thread_id
    runner = session_manager.get(thread_id)

    if runner is None:
        return  # No active session — silently ignore

    if runner.state == SessionState.STOPPED:
        await message.reply("Session is stopped. Use /new to create a new one.")
        return

    text = message.text or ""
    if not text:
        return

    # React with 👀 to confirm receipt
    try:
        await message.react(reaction=[ReactionTypeEmoji(emoji="👀")])
    except Exception as e:
        logger.warning("Failed to add reaction: %s", e)

    # Enqueue to session (will wait if Claude is processing current turn)
    await runner.enqueue(text)
