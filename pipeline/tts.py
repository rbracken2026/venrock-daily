"""
OpenAI TTS — model tts-1-hd, voice configurable per person (default: nova).
Adapted from research-podcast-maker skill: sentence-chunked to stay within
the 4096-character per-request limit.
"""

import json
import logging
import re
import time
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)

_API_URL = "https://api.openai.com/v1/audio/speech"
_CHUNK_LIMIT = 4000


def _split_chunks(text: str, limit: int = _CHUNK_LIMIT) -> list[str]:
    sentences = re.split(r"(?<=[.!?])\s+", text)
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if len(current) + len(sentence) < limit:
            current = (current + " " + sentence).lstrip()
        else:
            if current:
                chunks.append(current.strip())
            current = sentence
    if current:
        chunks.append(current.strip())
    return chunks


def generate_mp3(
    script: str,
    output_path: Path,
    api_key: str,
    voice: str = "nova",
    model: str = "tts-1-hd",
) -> Path:
    chunks = _split_chunks(script)
    logger.info("TTS: %d chunks, %d chars total, voice=%s", len(chunks), len(script), voice)

    audio_parts: list[bytes] = []
    for i, chunk in enumerate(chunks):
        payload = json.dumps({"model": model, "input": chunk, "voice": voice}).encode()
        req = urllib.request.Request(
            _API_URL,
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            audio_parts.append(resp.read())
        logger.debug("TTS chunk %d/%d done", i + 1, len(chunks))
        if i < len(chunks) - 1:
            time.sleep(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for part in audio_parts:
            f.write(part)

    size_kb = output_path.stat().st_size // 1024
    logger.info("MP3 saved: %s (%d KB)", output_path, size_kb)
    return output_path
