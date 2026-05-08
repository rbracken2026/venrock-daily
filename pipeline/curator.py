import json
import logging
from dataclasses import dataclass

import anthropic

from .config import BriefingConfig
from .fetcher.base import FetchedItem

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"

_SYSTEM = """\
You are an expert news curator for a venture capital firm focused on biotech and technology investing.
Evaluate news items for relevance, score them, and group them by theme.
Respond with valid JSON only — no markdown fences, no explanation outside the JSON array.
"""

_PROMPT = """\
Curate a morning briefing for {name}, a VC investor.

## Focus topics (score 1–10)
{topics}

## Thought leaders — apply +2 bonus (cap at 10) if item mentions or quotes any of these
{thought_leaders}

## Exclude entirely (score = 0) if item is primarily about
{exclude_topics}

## Items to evaluate
{items_json}

## Instructions
For each item score relevance 1–10, add +2 for thought leader mentions (cap 10), set 0 for excluded topics.
Items below {threshold} will be dropped automatically — still include them in your response.

Return a JSON array, one object per item:
[
  {{
    "id": <integer matching input id>,
    "title": "<title>",
    "source": "<source_name>",
    "section": "<section>",
    "relevance_score": <0–10>,
    "theme": "<brief theme label>",
    "summary": "<1 sentence plain-English summary suitable for spoken delivery>",
    "thought_leader_match": "<name or null>"
  }}
]
"""


@dataclass
class CuratedItem:
    id: int
    title: str
    source: str
    section: str
    relevance_score: float
    theme: str
    summary: str
    thought_leader_match: str | None
    original: FetchedItem


def _thought_leaders_str(config: BriefingConfig) -> str:
    parts = []
    for tl in config.focus_areas.thought_leaders:
        ids = (tl.handles or []) + (tl.aliases or [])
        line = f"- {tl.name}" + (f": {', '.join(ids)}" if ids else "")
        parts.append(line)
    return "\n".join(parts) or "None specified"


_BATCH_SIZE = 15


def _score_batch(
    batch: list[tuple[int, FetchedItem]],
    config: BriefingConfig,
    client: anthropic.Anthropic,
) -> list[dict]:
    """Score one batch of (global_id, item) pairs. Returns the raw scored dicts."""
    items_payload = json.dumps(
        [
            {
                "id": global_id,
                "title": item.title,
                "source": item.source_name,
                "section": item.section,
                "summary": item.summary,
                "author": item.author,
            }
            for global_id, item in batch
        ],
        indent=2,
    )

    prompt = _PROMPT.format(
        name=config.person.name,
        topics="\n".join(f"- {t}" for t in config.focus_areas.topics),
        thought_leaders=_thought_leaders_str(config),
        exclude_topics="\n".join(f"- {t}" for t in config.focus_areas.exclude_topics),
        items_json=items_payload,
        threshold=config.focus_areas.relevance_threshold,
    )

    response = client.messages.create(
        model=_MODEL,
        max_tokens=4096,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    raw = (
        response.content[0].text.strip()
        .removeprefix("```json")
        .removeprefix("```")
        .removesuffix("```")
        .strip()
    )
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.error("Curator batch returned invalid JSON: %s\n---\n%s", exc, raw[:500])
        raise


def curate(
    items: list[FetchedItem],
    config: BriefingConfig,
    api_key: str,
) -> list[CuratedItem]:
    if not items:
        return []

    client = anthropic.Anthropic(api_key=api_key)
    item_map = {i: item for i, item in enumerate(items)}
    batches = [
        list(enumerate(items))[i : i + _BATCH_SIZE]
        for i in range(0, len(items), _BATCH_SIZE)
    ]

    logger.info(
        "Curator: %d items across %d batch(es) of %d (%s)",
        len(items), len(batches), _BATCH_SIZE, _MODEL,
    )

    scored: list[dict] = []
    for batch_num, batch in enumerate(batches, 1):
        logger.info("Curator batch %d/%d (%d items)", batch_num, len(batches), len(batch))
        scored.extend(_score_batch(batch, config, client))

    threshold = config.focus_areas.relevance_threshold
    curated: list[CuratedItem] = []
    for obj in scored:
        score = float(obj.get("relevance_score", 0))
        if score < threshold:
            continue
        item_id = int(obj["id"])
        curated.append(
            CuratedItem(
                id=item_id,
                title=obj.get("title", ""),
                source=obj.get("source", ""),
                section=obj.get("section", ""),
                relevance_score=score,
                theme=obj.get("theme", ""),
                summary=obj.get("summary", ""),
                thought_leader_match=obj.get("thought_leader_match"),
                original=item_map.get(item_id, items[0]),
            )
        )

    curated.sort(key=lambda x: x.relevance_score, reverse=True)
    logger.info(
        "Curation: %d/%d items passed threshold %d",
        len(curated), len(items), threshold,
    )
    return curated
