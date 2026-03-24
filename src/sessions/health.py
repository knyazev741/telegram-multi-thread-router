"""Background health monitoring for Claude session subprocesses."""

import asyncio
import logging

from aiogram import Bot

from src.db.queries import update_session_state
from src.sessions.manager import SessionManager

logger = logging.getLogger(__name__)


async def health_check_loop(
    manager: SessionManager,
    bot: Bot,
    chat_id: int,
    interval: int = 60,
) -> None:
    """Run forever as a background task. Every `interval` seconds, check for dead runners.

    A runner is considered dead if:
    - Its asyncio task has completed (task.done()) but state is not STOPPED
    - This indicates the ClaudeSDKClient subprocess died unexpectedly

    Dead sessions are stopped, marked in DB, and their topic is notified.
    """
    while True:
        await asyncio.sleep(interval)
        try:
            dead_threads: list[int] = []

            for thread_id, runner in manager.list_all():
                # Check if the runner task died unexpectedly
                if not runner.is_alive and runner.state.name not in ("STOPPED",):
                    dead_threads.append(thread_id)
                    logger.warning(
                        "Zombie detected: thread %d, state=%s, task_alive=%s",
                        thread_id,
                        runner.state.name,
                        runner.is_alive,
                    )

            for thread_id in dead_threads:
                try:
                    await manager.stop(thread_id)
                except Exception as e:
                    logger.error("Error stopping zombie session %d: %s", thread_id, e)

                try:
                    await update_session_state(thread_id, "stopped")
                except Exception as e:
                    logger.error("Error updating DB for zombie %d: %s", thread_id, e)

                try:
                    await bot.send_message(
                        chat_id=chat_id,
                        message_thread_id=thread_id,
                        text="Session terminated: Claude process died unexpectedly.",
                    )
                except Exception as e:
                    logger.error("Error notifying topic %d about zombie: %s", thread_id, e)

            if dead_threads:
                logger.info("Health check cleaned up %d zombie session(s)", len(dead_threads))

        except Exception as e:
            logger.error("Health check loop error: %s", e)
