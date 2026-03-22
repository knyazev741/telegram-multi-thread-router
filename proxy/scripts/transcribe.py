#!/usr/bin/env python3
"""Transcribe audio file using faster-whisper. Prints text to stdout."""

import sys
from faster_whisper import WhisperModel

MODEL_SIZE = "small"
model = None

def get_model():
    global model
    if model is None:
        model = WhisperModel(MODEL_SIZE, device="cpu", compute_type="int8")
    return model

def transcribe(path: str) -> str:
    m = get_model()
    segments, _ = m.transcribe(path, language=None, beam_size=5)
    return " ".join(seg.text.strip() for seg in segments)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: transcribe.py <audio_file>", file=sys.stderr)
        sys.exit(1)
    text = transcribe(sys.argv[1])
    print(text)
