"""
Content safety filter for Outlook email items.

Runs a single batched Claude API call against all emails retrieved from a source
before they reach the curation step. Skips any email that fails the newsletter
test — personal communications, reply threads, forwarded chains, and anything
containing confidential business content are all rejected.

Conservative by design: when in doubt, skip.
"""

import json
import logging

import anthropic

from .base import FetchedItem

logger = logging.getLogger(__name__)

_MODEL = "claude-haiku-4-5-20251001"  # fast and cheap; filter doesn't need reasoning depth

_SYSTEM = """\
You are a content safety filter for a VC firm's automated news briefing pipeline.
Determine whether email items are safe to pass to an AI news curator.
Respond with valid JSON only — no markdown fences, no explanation outside the array.
"""

_PROMPT = """\
Review these email items. Each will be passed to an automated investor briefing system
if you mark it safe. Apply the criteria below strictly.

## SAFE: include only if ALL conditions are met
1. Sender is a publication, newsletter service, or media organization — not an individual person
   (e.g. "newsletters@statnews.com" is safe; "John Smith <john@gmail.com>" is not)
2. Looks like a broadcast newsletter:
   - No personal salutation ("Hi Racquel", "Dear Racquel", first-name-only openers)
   - No reply thread (no "Re:", "Fwd:", quoted text, "--- Original Message ---", "> wrote:")
   - No personal commentary added by a forwarder
3. No confidential or sensitive business content:
   - No specific deal names, term sheet details, or fund economics
   - No portfolio company financials or board-level specifics
   - No internal firm names, partner names in a business context, or Venrock-specific references

## UNSAFE: skip if ANY of the following are true
- Sender appears to be an individual person (personal email domain, first+last name)
- Subject line starts with "Re:" or "Fwd:"
- Body contains a personal greeting addressing the recipient by name
- Body contains reply-chain formatting (quoted text blocks, "wrote:", horizontal separators)
- Body contains deal-specific language: "term sheet", "closing", "cap table", "carry", "LP",
  "fund size", "valuation at", "pre-money", "post-money", "Series [A-Z]" in a deal context,
  portfolio company names paired with financial figures
- Any other indicator this is a personal, internal, or confidential communication

Be conservative: when in doubt, mark unsafe.

## Items to review
{items_json}

Return a JSON array, one object per item (preserve input order and ids):
[
  {{
    "id": <integer matching input>,
    "safe": true or false,
    "reason": "<if unsafe: one short phrase explaining why. If safe: \\"newsletter\\">"
  }}
]
"""


def filter_emails(
    items: list[FetchedItem],
    api_key: str,
    source_name: str,
) -> list[FetchedItem]:
    """
    Run safety checks on a batch of Outlook-fetched items.
    Returns only items that pass all checks.
    Logs every skipped item with a reason.
    """
    if not items:
        return []

    payload = json.dumps(
        [
            {
                "id": i,
                "sender": item.author,
                "subject": item.title,
                "preview": item.summary[:800],
            }
            for i, item in enumerate(items)
        ],
        indent=2,
    )

    prompt = _PROMPT.format(items_json=payload)

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=_MODEL,
            max_tokens=1024,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = response.content[0].text.strip()
        results: list[dict] = json.loads(raw)
    except Exception as exc:
        # If the filter itself errors, skip all items from this source (conservative)
        logger.warning(
            "Content filter error for source '%s' — skipping all %d items: %s",
            source_name, len(items), exc,
        )
        return []

    id_to_result = {r["id"]: r for r in results}
    passed: list[FetchedItem] = []

    for i, item in enumerate(items):
        verdict = id_to_result.get(i)
        if verdict is None:
            logger.warning(
                "Content filter: no verdict for item %d ('%s') from '%s' — skipping",
                i, item.title[:60], source_name,
            )
            continue
        if verdict.get("safe"):
            passed.append(item)
        else:
            reason = verdict.get("reason", "unknown")
            logger.info(
                "Content filter SKIP [%s] '%s' — %s",
                source_name, item.title[:80], reason,
            )

    logger.info(
        "Content filter '%s': %d/%d items passed",
        source_name, len(passed), len(items),
    )
    return passed
