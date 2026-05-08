#!/usr/bin/env python3
"""
Venrock Daily — morning briefing pipeline.

Usage:
    python briefing.py --config configs/racquel.yaml
    python briefing.py --config configs/racquel.yaml --dry-run
    python briefing.py --config configs/racquel.yaml --init-show
"""

import argparse
import asyncio
import logging
import os
import sys
from datetime import date
from pathlib import Path

from pipeline.config import BriefingConfig
from pipeline.fetcher import fetch_all
from pipeline.curator import curate
from pipeline.scripter import write_script
from pipeline.tts import generate_mp3
from pipeline.uploader import upload_episode, update_feeds_json
from pipeline.feed import init_show

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("briefing")


def _require_env(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        sys.exit(f"Error: {name} environment variable is not set")
    return val


async def run(config: BriefingConfig, dry_run: bool) -> None:
    anthropic_key = _require_env("ANTHROPIC_API_KEY")
    openai_key = _require_env("OPENAI_API_KEY")
    github_token = _require_env("GITHUB_TOKEN")
    github_repo = os.environ.get("GITHUB_REPO", "rbracken2026/venrock-daily")

    today = date.today()
    outputs_dir = Path("outputs")
    outputs_dir.mkdir(exist_ok=True)

    # ── Step 1: Fetch ────────────────────────────────────────────────────────
    logger.info("=== Step 1: Fetch ===")
    items = await fetch_all(config, anthropic_key)
    if not items:
        logger.warning("No items fetched — nothing to brief today")
        return

    # ── Step 2: Curate ───────────────────────────────────────────────────────
    logger.info("=== Step 2: Curate (%d raw items) ===", len(items))
    curated = curate(items, config, anthropic_key)
    if not curated:
        logger.warning("No items survived curation — nothing to brief today")
        return

    # ── Step 3: Script ───────────────────────────────────────────────────────
    logger.info("=== Step 3: Script (%d curated items) ===", len(curated))
    script = write_script(curated, config, anthropic_key, today)
    script_path = outputs_dir / f"{config.person.id}-script-{today}.txt"
    script_path.write_text(script, encoding="utf-8")
    logger.info("Script saved: %s", script_path)

    if dry_run:
        logger.info("--dry-run: stopping before TTS and upload")
        print("\n" + "─" * 60)
        print("SCRIPT PREVIEW (first 600 chars)")
        print("─" * 60)
        print(script[:600] + (" …" if len(script) > 600 else ""))
        return

    # ── Step 4: TTS ──────────────────────────────────────────────────────────
    logger.info("=== Step 4: TTS ===")
    mp3_path = outputs_dir / f"{config.person.id}-{today}.mp3"
    generate_mp3(script, mp3_path, openai_key, config.person.voice)

    # ── Step 5: Upload + publish ─────────────────────────────────────────────
    logger.info("=== Step 5: Upload ===")
    mp3_url = upload_episode(
        mp3_path=mp3_path,
        script=script,
        repo=github_repo,
        token=github_token,
        person_id=config.person.id,
        show_title=f"Venrock Daily — {config.person.name}",
    )
    update_feeds_json(
        repo=github_repo,
        token=github_token,
        person_id=config.person.id,
        person_name=config.person.name,
        date_str=str(today),
    )

    logger.info("=== Done ===")
    logger.info("Episode: %s", mp3_url)


def main() -> None:
    parser = argparse.ArgumentParser(description="Venrock Daily briefing pipeline")
    parser.add_argument("--config", required=True, help="Path to YAML config file")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch, curate, and script — skip TTS and upload",
    )
    parser.add_argument(
        "--init-show",
        action="store_true",
        help="Create feed.xml and episodes/ folder in GitHub (run once per person)",
    )
    args = parser.parse_args()

    config = BriefingConfig.from_yaml(args.config)

    if args.init_show:
        token = _require_env("GITHUB_TOKEN")
        repo = os.environ.get("GITHUB_REPO", "rbracken2026/venrock-daily")
        email = os.environ.get("OWNER_EMAIL", "rbracken@venrock.com")
        init_show(config, repo, token, email)
        logger.info("Show initialized for '%s' — feed is live at shows/%s/feed.xml",
                    config.person.name, config.person.id)
        return

    asyncio.run(run(config, args.dry_run))


if __name__ == "__main__":
    main()
