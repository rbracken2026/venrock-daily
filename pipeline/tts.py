"""
Azure Cognitive Services TTS.

Uses the same app registration credentials already in the project
(M365_CLIENT_ID / M365_CLIENT_SECRET / M365_TENANT_ID) with the
Cognitive Services scope to obtain an AAD bearer token, then calls
the Azure Speech REST API.

Required env vars:
  AZURE_SPEECH_REGION       — Azure region slug, e.g. "eastus"
  AZURE_SPEECH_RESOURCE_ID  — Full ARM resource path:
                               /subscriptions/{sub}/resourceGroups/{rg}
                               /providers/Microsoft.CognitiveServices/accounts/{name}
  M365_CLIENT_ID            — existing (shared with Outlook fetcher)
  M365_CLIENT_SECRET        — existing
  M365_TENANT_ID            — existing
"""

import logging
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from xml.sax.saxutils import escape as xml_escape

logger = logging.getLogger(__name__)

# Azure Speech REST API
_TTS_URL = "https://{region}.tts.speech.microsoft.com/cognitiveservices/v1"
_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_SCOPE = "https://cognitiveservices.azure.com/.default"

# Azure Speech REST API text limit per request is ~1000 chars; stay comfortably under.
_CHUNK_LIMIT = 900

# Cached token: (token_string, expiry_epoch).  AAD tokens live 60 min; refresh at 55.
_token_cache: tuple[str, float] | None = None


def _get_token() -> str:
    global _token_cache
    now = time.monotonic()
    if _token_cache and now < _token_cache[1]:
        return _token_cache[0]

    tenant = os.environ["M365_TENANT_ID"]
    body = urllib.parse.urlencode(
        {
            "grant_type": "client_credentials",
            "client_id": os.environ["M365_CLIENT_ID"],
            "client_secret": os.environ["M365_CLIENT_SECRET"],
            "scope": _SCOPE,
        }
    ).encode()
    req = urllib.request.Request(
        _TOKEN_URL.format(tenant=tenant),
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        data = __import__("json").loads(resp.read())

    token: str = data["access_token"]
    expires_in: int = int(data.get("expires_in", 3600))
    _token_cache = (token, now + expires_in - 60)  # 60-second safety margin
    logger.debug("Azure AAD token refreshed (expires in %ds)", expires_in)
    return token


def _build_ssml(text: str, voice: str) -> bytes:
    return (
        f"<speak version='1.0' xml:lang='en-US'>"
        f"<voice name='{voice}'>{xml_escape(text)}</voice>"
        f"</speak>"
    ).encode("utf-8")


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
    region: str,
    voice: str = "en-US-JennyNeural",
) -> Path:
    """
    Synthesise *script* to MP3 at *output_path* using Azure Speech.

    Args:
        script:       Full spoken-word script text.
        output_path:  Destination .mp3 file path.
        region:       Azure region slug (e.g. "eastus").
        voice:        Azure Neural voice name (default: en-US-JennyNeural).
    """
    resource_id = os.environ["AZURE_SPEECH_RESOURCE_ID"]
    url = _TTS_URL.format(region=region)
    chunks = _split_chunks(script)
    logger.info(
        "Azure TTS: %d chunks, %d chars total, voice=%s, region=%s",
        len(chunks), len(script), voice, region,
    )

    audio_parts: list[bytes] = []
    for i, chunk in enumerate(chunks):
        token = _get_token()
        ssml = _build_ssml(chunk, voice)
        req = urllib.request.Request(
            url,
            data=ssml,
            headers={
                "Authorization": f"Bearer {token}",
                "X-Microsoft-Azure-ResourceId": resource_id,
                "Content-Type": "application/ssml+xml",
                "X-Microsoft-OutputFormat": "audio-48khz-192kbitrate-mono-mp3",
                "User-Agent": "VenrockDaily/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            audio_parts.append(resp.read())
        logger.debug("TTS chunk %d/%d done (%d bytes)", i + 1, len(chunks), len(audio_parts[-1]))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for part in audio_parts:
            f.write(part)

    size_kb = output_path.stat().st_size // 1024
    logger.info("MP3 saved: %s (%d KB)", output_path, size_kb)
    return output_path
