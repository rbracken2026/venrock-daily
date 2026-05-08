"""
GitHub Contents API uploader.
Adapted from research-podcast-maker skill: gh() helper + feed.xml injection,
extended with feeds.json manifest update.
"""

import base64
import json
import logging
import urllib.request
from datetime import datetime, timezone, time as dt_time
from email.utils import format_datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"


def gh(method: str, path: str, token: str, data: dict | None = None) -> dict:
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(
        f"{_GITHUB_API}{path}",
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read())


def _get_sha(path: str, repo: str, token: str) -> str | None:
    try:
        return gh("GET", f"/repos/{repo}/contents/{path}", token)["sha"]
    except Exception:
        return None


def _put_file(
    repo_path: str,
    content_bytes: bytes,
    commit_msg: str,
    repo: str,
    token: str,
) -> None:
    sha = _get_sha(repo_path, repo, token)
    data: dict = {
        "message": commit_msg,
        "content": base64.b64encode(content_bytes).decode(),
        "branch": "main",
    }
    if sha:
        data["sha"] = sha
    gh("PUT", f"/repos/{repo}/contents/{repo_path}", token, data)


def upload_episode(
    mp3_path: Path,
    script: str,
    repo: str,
    token: str,
    person_id: str,
    show_title: str,
    today: datetime | None = None,
) -> str:
    today = today or datetime.now(timezone.utc)
    date_str = today.strftime("%Y-%m-%d")
    username, repo_name = repo.split("/", 1)
    base_url = f"https://{username}.github.io/{repo_name}"

    # Upload MP3
    mp3_bytes = mp3_path.read_bytes()
    mp3_repo_path = f"shows/{person_id}/episodes/{date_str}.mp3"
    mp3_url = f"{base_url}/shows/{person_id}/episodes/{date_str}.mp3"
    _put_file(mp3_repo_path, mp3_bytes, f"[{person_id}] Add episode {date_str}", repo, token)
    logger.info("MP3 uploaded: %s", mp3_url)

    # Inject item into feed.xml
    feed_resp = gh("GET", f"/repos/{repo}/contents/shows/{person_id}/feed.xml", token)
    feed_xml: str = base64.b64decode(feed_resp["content"]).decode()
    feed_sha: str = feed_resp["sha"]
    episode_id = f"{person_id}-{date_str}"

    if episode_id in feed_xml:
        logger.info("Episode %s already in feed, skipping", date_str)
        return mp3_url

    sentences = [s.strip() for s in script.split(".") if s.strip()]
    summary = ". ".join(sentences[:2]) + "." if len(sentences) >= 2 else script[:300]

    pub_dt = datetime.combine(today.date(), dt_time(7, 0), tzinfo=timezone.utc)
    pub_date = format_datetime(pub_dt)
    day_num = str(today.day)
    title = f"{show_title} — {today.strftime('%A, %B ')+day_num+today.strftime(', %Y')}"

    item = f"""
    <item>
      <title>{title}</title>
      <description><![CDATA[{summary}]]></description>
      <pubDate>{pub_date}</pubDate>
      <guid isPermaLink="false">{episode_id}</guid>
      <enclosure
        url="{mp3_url}"
        length="{len(mp3_bytes)}"
        type="audio/mpeg"/>
      <itunes:title>{title}</itunes:title>
      <itunes:duration>10:00</itunes:duration>
      <itunes:episodeType>full</itunes:episodeType>
      <itunes:explicit>false</itunes:explicit>
    </item>
"""

    marker = "<!-- Add new <item> blocks above this line, newest first -->"
    new_feed = feed_xml.replace(marker, item + "\n    " + marker)
    sha_data: dict = {
        "message": f"[{person_id}] Update feed {date_str}",
        "content": base64.b64encode(new_feed.encode()).decode(),
        "branch": "main",
        "sha": feed_sha,
    }
    gh("PUT", f"/repos/{repo}/contents/shows/{person_id}/feed.xml", token, sha_data)
    logger.info("feed.xml updated with episode %s", date_str)
    return mp3_url


def update_feeds_json(
    repo: str,
    token: str,
    person_id: str,
    person_name: str,
    date_str: str,
) -> None:
    feeds_path = "feeds.json"
    try:
        resp = gh("GET", f"/repos/{repo}/contents/{feeds_path}", token)
        feeds: list[dict] = json.loads(base64.b64decode(resp["content"]).decode())
        sha: str | None = resp["sha"]
    except Exception:
        feeds = []
        sha = None

    username, repo_name = repo.split("/", 1)
    feed_url = f"https://{username}.github.io/{repo_name}/shows/{person_id}/feed.xml"

    entry = next((f for f in feeds if f["id"] == person_id), None)
    if entry:
        entry["last_episode"] = date_str
    else:
        feeds.append(
            {"id": person_id, "name": person_name, "feed_url": feed_url, "last_episode": date_str}
        )

    payload: dict = {
        "message": f"[feeds] Update {person_id} last episode {date_str}",
        "content": base64.b64encode(json.dumps(feeds, indent=2).encode()).decode(),
        "branch": "main",
    }
    if sha:
        payload["sha"] = sha
    gh("PUT", f"/repos/{repo}/contents/{feeds_path}", token, payload)
    logger.info("feeds.json updated for %s", person_id)
