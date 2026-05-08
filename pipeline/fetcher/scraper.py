import asyncio
import logging
import re
from datetime import datetime, timezone, timedelta
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .base import FetchedItem
from ..config import ScrapedSource

logger = logging.getLogger(__name__)

_DATE_FORMATS = (
    "%Y-%m-%d",
    "%B %d, %Y",
    "%B %d %Y",
    "%b %d, %Y",
    "%b %d %Y",
)
_DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}|\w+ \d{1,2},? \d{4}")


def _extract_date(text: str) -> datetime | None:
    m = _DATE_PATTERN.search(text)
    if not m:
        return None
    raw = m.group(0)
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


async def scrape_source(
    source: ScrapedSource,
    section: str,
    client: httpx.AsyncClient,
) -> list[FetchedItem]:
    cutoff = datetime.now(timezone.utc) - timedelta(days=source.lookback_days)
    try:
        resp = await client.get(
            source.url,
            follow_redirects=True,
            headers={"User-Agent": "VenrockDaily/1.0"},
        )
        soup = BeautifulSoup(resp.text, "html.parser")
    except Exception as exc:
        logger.warning("Scrape failed for %s: %s", source.name, exc)
        return []

    items: list[FetchedItem] = []
    seen: set[str] = set()
    candidates = soup.find_all(
        ["article", "li", "div"],
        class_=re.compile(r"post|article|entry|item", re.I),
    )
    for tag in candidates:
        a = tag.find("a", href=True)
        if not a:
            continue
        title = a.get_text(strip=True)
        if len(title) < 10:
            continue
        href: str = a["href"]
        if not href.startswith("http"):
            href = urljoin(source.url, href)
        if href in seen:
            continue
        seen.add(href)

        pub = _extract_date(tag.get_text())
        if pub and pub < cutoff:
            continue

        summary_tag = tag.find(
            ["p", "span"],
            class_=re.compile(r"excerpt|desc|summary|preview", re.I),
        )
        summary = summary_tag.get_text(strip=True)[:1000] if summary_tag else ""

        items.append(
            FetchedItem(
                title=title,
                url=href,
                source_name=source.name,
                section=section,
                published=pub,
                summary=summary,
            )
        )
        if len(items) >= 20:
            break

    logger.info("Scraper %s: %d items from %s", section, len(items), source.name)
    return items


async def fetch_all_scraped(
    sources: list[ScrapedSource],
    section: str,
) -> list[FetchedItem]:
    if not sources:
        return []
    async with httpx.AsyncClient(timeout=20) as client:
        tasks = [scrape_source(s, section, client) for s in sources]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    items: list[FetchedItem] = []
    for r in results:
        if isinstance(r, list):
            items.extend(r)
        else:
            logger.warning("Scraper gather error: %s", r)
    return items
