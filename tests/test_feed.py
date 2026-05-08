"""Tests for feed.xml injection and deduplication guard."""

import base64
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import tempfile

import pytest

from pipeline.uploader import upload_episode, update_feeds_json


# ── Helpers ────────────────────────────────────────────────────────────────

_EMPTY_FEED = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">
  <channel>
    <title>Venrock Daily — Racquel</title>
    <!-- Add new <item> blocks above this line, newest first -->
  </channel>
</rss>
"""

_SCRIPT = "Good morning, Racquel. Today is a great day for biotech. We cover three stories."


def _b64(text: str) -> str:
    return base64.b64encode(text.encode()).decode()


def _feed_api_resp(xml: str, sha: str = "abc123") -> dict:
    return {"content": _b64(xml), "sha": sha}


# ── Tests ──────────────────────────────────────────────────────────────────

def test_item_injected_before_marker():
    today = datetime(2025, 5, 7, 14, 0, 0, tzinfo=timezone.utc)

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(b"\xff\xfb" * 100)  # fake MP3 bytes
        mp3_path = Path(f.name)

    put_calls: list[dict] = []

    def fake_gh(method, path, token, data=None):
        if method == "GET" and "feed.xml" in path:
            return _feed_api_resp(_EMPTY_FEED)
        if method == "GET" and "episodes" in path:
            return {"sha": None}
        if method == "PUT":
            put_calls.append({"path": path, "data": data})
            return {}
        return {}

    with patch("pipeline.uploader.gh", side_effect=fake_gh), \
         patch("pipeline.uploader._get_sha", return_value=None):
        url = upload_episode(
            mp3_path=mp3_path,
            script=_SCRIPT,
            repo="rbracken2026/venrock-daily",
            token="fake-token",
            person_id="racquel",
            show_title="Venrock Daily — Racquel",
            today=today,
        )

    mp3_path.unlink(missing_ok=True)

    assert url == "https://rbracken2026.github.io/venrock-daily/shows/racquel/episodes/2025-05-07.mp3"

    feed_put = next(c for c in put_calls if "feed.xml" in c["path"])
    updated_xml = base64.b64decode(feed_put["data"]["content"]).decode()
    assert "<item>" in updated_xml
    assert "racquel-2025-05-07" in updated_xml
    # Marker still present (for future injections)
    assert "<!-- Add new <item> blocks above this line, newest first -->" in updated_xml
    # New item appears BEFORE the marker
    item_pos = updated_xml.index("<item>")
    marker_pos = updated_xml.index("<!-- Add new")
    assert item_pos < marker_pos


def test_duplicate_episode_skipped():
    episode_id = "racquel-2025-05-07"
    feed_with_existing = _EMPTY_FEED.replace(
        "<!-- Add new <item> blocks above this line, newest first -->",
        f'<guid isPermaLink="false">{episode_id}</guid>\n    <!-- Add new <item> blocks above this line, newest first -->',
    )
    today = datetime(2025, 5, 7, 14, 0, 0, tzinfo=timezone.utc)

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        f.write(b"\xff\xfb" * 100)
        mp3_path = Path(f.name)

    put_calls: list[str] = []

    def fake_gh(method, path, token, data=None):
        if method == "GET" and "feed.xml" in path:
            return _feed_api_resp(feed_with_existing)
        if method == "PUT":
            put_calls.append(path)
            return {}
        return {}

    with patch("pipeline.uploader.gh", side_effect=fake_gh), \
         patch("pipeline.uploader._get_sha", return_value=None):
        upload_episode(
            mp3_path=mp3_path,
            script=_SCRIPT,
            repo="rbracken2026/venrock-daily",
            token="fake-token",
            person_id="racquel",
            show_title="Venrock Daily — Racquel",
            today=today,
        )

    mp3_path.unlink(missing_ok=True)

    # MP3 was uploaded, but feed.xml was NOT written again
    feed_puts = [p for p in put_calls if "feed.xml" in p]
    assert len(feed_puts) == 0


def test_feeds_json_adds_new_entry():
    captured: list[dict] = []

    def fake_gh(method, path, token, data=None):
        if method == "GET":
            raise Exception("not found")
        if method == "PUT":
            captured.append(data)
            return {}
        return {}

    with patch("pipeline.uploader.gh", side_effect=fake_gh):
        update_feeds_json(
            repo="rbracken2026/venrock-daily",
            token="fake-token",
            person_id="racquel",
            person_name="Racquel",
            date_str="2025-05-07",
        )

    assert len(captured) == 1
    written = json.loads(base64.b64decode(captured[0]["content"]).decode())
    assert written[0]["id"] == "racquel"
    assert written[0]["last_episode"] == "2025-05-07"
    assert "racquel" in written[0]["feed_url"]


def test_feeds_json_updates_existing_entry():
    existing = [{"id": "racquel", "name": "Racquel",
                 "feed_url": "https://rbracken2026.github.io/venrock-daily/shows/racquel/feed.xml",
                 "last_episode": "2025-05-06"}]
    captured: list[dict] = []

    def fake_gh(method, path, token, data=None):
        if method == "GET":
            return {"content": _b64(json.dumps(existing)), "sha": "oldsha"}
        if method == "PUT":
            captured.append(data)
            return {}
        return {}

    with patch("pipeline.uploader.gh", side_effect=fake_gh):
        update_feeds_json(
            repo="rbracken2026/venrock-daily",
            token="fake-token",
            person_id="racquel",
            person_name="Racquel",
            date_str="2025-05-07",
        )

    written = json.loads(base64.b64decode(captured[0]["content"]).decode())
    assert len(written) == 1  # no duplicate entry added
    assert written[0]["last_episode"] == "2025-05-07"
