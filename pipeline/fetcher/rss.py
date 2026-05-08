import asyncio
import calendar
import logging
from datetime import datetime, timezone, timedelta
from typing import Sequence

import feedparser
import httpx

from .base import FetchedItem
from ..config import RssSource

logger = logging.getLogger(__name__)


def _parse_published(entry) -> datetime | None:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime.fromtimestamp(
            calendar.timegm(entry.published_parsed), tz=timezone.utc
        )
    return None


def _matches_filter(entry, filter_topics: list[str] | None) -> bool:
    if not filter_topics:
        return True
    text = f"{entry.get('title', '')} {entry.get('summary', '')}".lower()
    return any(t.lower() in text for t in filter_topics)


async def fetch_rss(
    source: RssSource,
    section: str,
    lookback_hours: int = 24,
    client: httpx.AsyncClient | None = None,
) -> list[FetchedItem]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    own_client = client is None
    _client = client or httpx.AsyncClient(timeout=15)
    try:
        resp = await _client.get(
            source.url,
            follow_redirects=True,
            headers={"User-Agent": "VenrockDaily/1.0"},
        )
        feed = feedparser.parse(resp.text)
    except Exception as exc:
        logger.warning("RSS fetch failed for %s: %s", source.name, exc)
        return []
    finally:
        if own_client:
            await _client.aclose()

    items: list[FetchedItem] = []
    for entry in feed.entries:
        pub = _parse_published(entry)
        if pub is None or pub < cutoff:
            continue
        if not _matches_filter(entry, source.filter_topics):
            continue
        items.append(
            FetchedItem(
                title=entry.get("title", "").strip(),
                url=entry.get("link", ""),
                source_name=source.name,
                section=section,
                published=pub,
                summary=entry.get("summary", "")[:2000],
                author=entry.get("author", ""),
            )
        )

    logger.info("RSS %s: %d items from %s", section, len(items), source.name)
    return items


async def fetch_all_rss(
    sources: Sequence[RssSource],
    section: str,
    lookback_hours: int = 24,
) -> list[FetchedItem]:
    if not sources:
        return []
    async with httpx.AsyncClient(timeout=15) as client:
        tasks = [fetch_rss(s, section, lookback_hours, client) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[FetchedItem] = []
    for r in results:
        if isinstance(r, list):
            items.extend(r)
        else:
            logger.warning("RSS gather error: %s", r)
    return items
