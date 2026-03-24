"""Voice transcription module using faster-whisper (medium model, int8, CPU)."""

import asyncio
import logging

from faster_whisper import WhisperModel

logger = logging.getLogger(__name__)

_model: WhisperModel | None = None
_semaphore = asyncio.Semaphore(1)


def _get_model() -> WhisperModel:
    """Lazy-load WhisperModel on first call. Subsequent calls return cached instance."""
    global _model
    if _model is None:
        logger.info("Loading Whisper model...")
        _model = WhisperModel("medium", compute_type="int8", device="cpu")
    return _model


async def transcribe_voice(ogg_path: str) -> str:
    """Transcribe a voice .ogg file to text using faster-whisper.

    Acquires a semaphore to prevent concurrent transcriptions (OOM prevention).
    Runs the blocking transcription in a thread pool via asyncio.to_thread.

    Args:
        ogg_path: Path to the .ogg voice file to transcribe.

    Returns:
        Transcribed text as a single string.

    Raises:
        Exception: Re-raises any transcription error after logging.
    """
    async with _semaphore:
        try:
            model = _get_model()
            segments, _info = await asyncio.to_thread(
                model.transcribe, ogg_path, beam_size=5
            )
            text = " ".join(seg.text.strip() for seg in segments)
            return text
        except Exception as e:
            logger.error("Voice transcription failed for %s: %s", ogg_path, e)
            raise
