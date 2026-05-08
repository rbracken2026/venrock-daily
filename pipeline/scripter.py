import logging
from datetime import date, datetime, timezone

import anthropic

from .config import BriefingConfig
from .curator import CuratedItem

logger = logging.getLogger(__name__)

_MODEL = "claude-sonnet-4-5"

_SYSTEM = """\
You are writing a spoken audio news briefing. Your output is read aloud by a TTS engine.
Write in natural spoken English. No bullets, no markdown, no URLs, no symbols —
spell out "percent," "dollars," etc. No headers. Flowing prose only.
"""

_PROMPT = """\
Write the Venrock Daily morning briefing for {name}. Today is {date}.

## Style
- Greeting: {greeting}
- Tone: {tone}
- Story treatment: {story_treatment}
- Sign-off: {signoff}
- Section order: {section_order}

## Curated news ({item_count} items — target {target_words} words)
{items_text}

## Instructions
1. Open exactly per the greeting style, including today's date spoken naturally
2. After the greeting, preview 2–3 top stories in 1–2 sentences
3. Group stories by section following section_order; skip empty sections silently
4. Each story: 30–60 seconds (75–150 words). Lead with implication, then facts.
   - Clinical data: name the comparator and competitive implication
   - Deals: note the valuation signal
5. {biocentury_instruction}
6. Close with the exact sign-off: "One thing to watch today:" then 2 forward-looking sentences
7. Target {target_words} words total

Start directly with the greeting — no preamble.
"""


def _format_items(curated: list[CuratedItem], section_order: list[str]) -> str:
    by_section: dict[str, list[CuratedItem]] = {}
    for item in curated:
        by_section.setdefault(item.section, []).append(item)

    parts: list[str] = []
    for section in section_order:
        section_items = by_section.get(section, [])
        if not section_items:
            continue
        parts.append(f"\n### {section.replace('_', ' ').title()}")
        for item in section_items:
            tl = f" [mentions: {item.thought_leader_match}]" if item.thought_leader_match else ""
            parts.append(
                f"- {item.title} ({item.source}, score {item.relevance_score:.0f}{tl})\n"
                f"  {item.summary}"
            )
    return "\n".join(parts)


def write_script(
    curated: list[CuratedItem],
    config: BriefingConfig,
    api_key: str,
    today: date | None = None,
) -> str:
    today = today or date.today()
    is_quiet = len(curated) < config.output.quiet_day_threshold
    target_words = config.output.quiet_day_words if is_quiet else config.output.target_words
    if is_quiet:
        logger.info("Quiet day (%d items) — targeting %d words", len(curated), target_words)

    is_monday = datetime.now(timezone.utc).weekday() == 0
    has_biocentury = any(
        item.source == "BioCentury Weekend" for item in curated
    )
    if is_monday and has_biocentury:
        target_words += 600
        biocentury_instruction = (
            "Today is Monday. The BioCentury Weekend summary is included in biotech_news. "
            "Place it as the final story in the biotech section, before tech_insights. "
            "Allot approximately 4 minutes (400-500 words) to summarising the most important "
            "developments from the BioCentury report. Only cover it if the material is substantive."
        )
    else:
        biocentury_instruction = "No BioCentury weekend report today — skip this step."

    # Cross-platform day without leading zero
    date_str = today.strftime("%A, %B ") + str(today.day) + today.strftime(", %Y")

    prompt = _PROMPT.format(
        name=config.person.name,
        date=date_str,
        greeting=config.style.greeting,
        tone=config.style.tone,
        story_treatment=config.style.story_treatment,
        signoff=config.style.signoff,
        section_order=", ".join(config.style.section_order),
        item_count=len(curated),
        target_words=target_words,
        biocentury_instruction=biocentury_instruction,
        items_text=_format_items(curated, config.style.section_order),
    )

    logger.info("Writing script via %s (%d items, %d target words)", _MODEL, len(curated), target_words)
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=_MODEL,
        max_tokens=3000,
        system=_SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )

    script = response.content[0].text.strip()
    logger.info("Script written: ~%d words", len(script.split()))
    return script
