"""
Microsoft Graph API email fetcher.

All sources default to active: false and are skipped unless active: true is set
in the YAML config. To enable, set M365_CLIENT_ID, M365_CLIENT_SECRET, and
M365_TENANT_ID as environment variables or GitHub Actions secrets, then flip
active: true on the relevant source in configs/<person>.yaml.

Every batch of fetched emails is passed through content_filter.filter_emails()
before being returned. The filter rejects personal communications, reply threads,
forwarded chains, and anything containing confidential business content.
"""

import asyncio
import functools
import logging
import os
from datetime import datetime, timezone, timedelta

import httpx

from .base import FetchedItem
from .content_filter import filter_emails
from ..config import OutlookSource

logger = logging.getLogger(__name__)

_TOKEN_URL = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
_MESSAGES_URL = "https://graph.microsoft.com/v1.0/me/messages"


async def _get_token(client: httpx.AsyncClient) -> str:
    tenant = os.environ["M365_TENANT_ID"]
    resp = await client.post(
        _TOKEN_URL.format(tenant=tenant),
        data={
            "grant_type": "client_credentials",
            "client_id": os.environ["M365_CLIENT_ID"],
            "client_secret": os.environ["M365_CLIENT_SECRET"],
            "scope": "https://graph.microsoft.com/.default",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


async def fetch_outlook(source: OutlookSource, section: str, api_key: str) -> list[FetchedItem]:
    if not source.active:
        return []

    hours = source.lookback_hours or (source.lookback_days or 1) * 24
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    cutoff_str = cutoff.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            token = await _get_token(client)
            resp = await client.get(
                _MESSAGES_URL,
                params={
                    "$search": f'"{source.search_query}"',
                    "$filter": f"receivedDateTime ge {cutoff_str}",
                    "$select": "subject,bodyPreview,receivedDateTime,from",
                    "$top": "25",
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "ConsistencyLevel": "eventual",
                },
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception as exc:
        logger.warning("Outlook fetch failed for %s: %s", source.name, exc)
        return []

    items: list[FetchedItem] = []
    for msg in data.get("value", []):
        received = msg.get("receivedDateTime", "")
        try:
            pub = datetime.fromisoformat(received.replace("Z", "+00:00"))
        except ValueError:
            pub = None
        items.append(
            FetchedItem(
                title=msg.get("subject", "").strip(),
                url="",
                source_name=source.name,
                section=section,
                published=pub,
                summary=msg.get("bodyPreview", "")[:1500],
                author=msg.get("from", {}).get("emailAddress", {}).get("address", ""),
            )
        )

    logger.info("Outlook %s: %d raw items from %s (pre-filter)", section, len(items), source.name)

    # Run content safety filter — rejects personal emails, reply threads, confidential content.
    # filter_emails() is synchronous (one Claude API call); run in a thread to stay non-blocking.
    filtered = await asyncio.get_event_loop().run_in_executor(
        None, functools.partial(filter_emails, items, api_key, source.name)
    )
    return filtered


async def fetch_all_outlook(
    sources: list[OutlookSource],
    section: str,
    api_key: str,
) -> list[FetchedItem]:
    active = [s for s in sources if s.active]
    if not active:
        return []
    results = await asyncio.gather(
        *[fetch_outlook(s, section, api_key) for s in active],
        return_exceptions=True,
    )
    items: list[FetchedItem] = []
    for r in results:
        if isinstance(r, list):
            items.extend(r)
        else:
            logger.warning("Outlook gather error: %s", r)
    return items
