"""
YouTube playlist fetcher — pulls transcripts from recent episodes.
Used for podcasts like More or Less that publish to YouTube.
"""

import logging
import re
import urllib.request
from datetime import datetime, timezone, timedelta

from .base import FetchedItem
from ..config import PodcastSource

logger = logging.getLogger(__name__)

_TRANSCRIPT_CHARS = 6000


def _get_playlist_videos(playlist_id: str) -> list[dict]:
    url = f"https://www.youtube.com/playlist?list={playlist_id}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=15) as r:
        html = r.read().decode("utf-8", errors="replace")

    video_ids = list(dict.fromkeys(re.findall(r'"videoId":"([a-zA-Z0-9_-]{11})"', html)))
    titles = re.findall(r'"title":\{"runs":\[\{"text":"([^"]+)"', html)

    videos = []
    for i, vid in enumerate(video_ids[:10]):
        title = titles[i] if i < len(titles) else ""
        videos.append({"id": vid, "title": title})
    return videos


def _get_transcript(video_id: str) -> str:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        api = YouTubeTranscriptApi()
        transcript = api.fetch(video_id)
        return " ".join(t.text for t in transcript)[:_TRANSCRIPT_CHARS]
    except Exception as exc:
        logger.warning("Transcript fetch failed for %s: %s", video_id, exc)
        return ""


def fetch_youtube_podcast(source: PodcastSource, section: str, lookback_days: int = 7) -> list[FetchedItem]:
    if not source.active:
        return []

    playlist_id = source.playlist_id
    if not playlist_id:
        logger.warning("YouTube source %s has no playlist_id", source.name)
        return []

    try:
        videos = _get_playlist_videos(playlist_id)
    except Exception as exc:
        logger.warning("YouTube playlist fetch failed for %s: %s", source.name, exc)
        return []

    items: list[FetchedItem] = []
    cutoff = datetime.now(timezone.utc) - timedelta(days=lookback_days)

    for video in videos[:3]:
        transcript = _get_transcript(video["id"])
        if not transcript:
            continue

        items.append(
            FetchedItem(
                title=video["title"] or source.name,
                url=f"https://www.youtube.com/watch?v={video['id']}",
                source_name=source.name,
                section=section,
                published=None,
                summary=transcript,
                author="Sam Lessin & Jess Lessin",
            )
        )
        logger.info("YouTube %s: fetched transcript for '%s' (%d chars)",
                    source.name, video["title"][:60], len(transcript))

    return items
