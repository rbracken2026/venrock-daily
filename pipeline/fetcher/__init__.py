import asyncio
import logging
from datetime import datetime, timezone

from .base import FetchedItem
from .rss import fetch_all_rss
from .scraper import fetch_all_scraped
from .outlook import fetch_all_outlook
from .youtube import fetch_youtube_podcast
from ..config import BriefingConfig, SourceGroup

logger = logging.getLogger(__name__)


def _dedup(items: list[FetchedItem]) -> list[FetchedItem]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    out: list[FetchedItem] = []
    for item in items:
        url_key = item.url.rstrip("/").lower()
        title_key = item.title.lower()[:60]
        if url_key and url_key in seen_urls:
            continue
        if title_key in seen_titles:
            continue
        if url_key:
            seen_urls.add(url_key)
        seen_titles.add(title_key)
        out.append(item)
    return out


async def _fetch_section(group: SourceGroup, section: str, api_key: str, rss_lookback_hours: int = 24) -> list[FetchedItem]:
    loop = asyncio.get_event_loop()
    youtube_items: list[FetchedItem] = []
    for source in group.podcasts:
        if source.active and source.playlist_id:
            try:
                result = await loop.run_in_executor(
                    None, lambda s=source: fetch_youtube_podcast(s, section)
                )
                youtube_items.extend(result)
            except Exception as exc:
                logger.warning("YouTube fetch error for %s: %s", source.name, exc)

    tasks = [
        fetch_all_rss(group.rss, section, rss_lookback_hours),
        fetch_all_scraped(group.scraped_urls, section),
        fetch_all_outlook(group.outlook, section, api_key),
    ]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    items: list[FetchedItem] = list(youtube_items)
    for r in results:
        if isinstance(r, list):
            items.extend(r)
        else:
            logger.warning("Section %s fetch error: %s", section, r)
    return items


async def fetch_all(config: BriefingConfig, api_key: str) -> list[FetchedItem]:
    # On Mondays, extend RSS lookback to 72 h to catch Friday and weekend stories.
    is_monday = datetime.now(timezone.utc).weekday() == 0
    rss_lookback_hours = 72 if is_monday else 24
    if is_monday:
        logger.info("Monday run — RSS lookback extended to 72 h")

    sections = {
        "biotech_news": config.sources.biotech_news,
        "tech_insights": config.sources.tech_insights,
        "macro_and_markets": config.sources.macro_and_markets,
    }
    tasks = [_fetch_section(group, name, api_key, rss_lookback_hours) for name, group in sections.items()]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    all_items: list[FetchedItem] = []
    for r in results:
        if isinstance(r, list):
            all_items.extend(r)
        else:
            logger.warning("Fetch error: %s", r)

    deduped = _dedup(all_items)
    logger.info("Fetched %d items total (%d after dedup)", len(all_items), len(deduped))
    return deduped
