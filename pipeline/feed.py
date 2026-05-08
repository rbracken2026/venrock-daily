"""
Initialize a show's feed.xml and episodes/ folder in GitHub.
Run once per new person: python briefing.py --config configs/<person>.yaml --init-show
"""

import base64
import logging
from datetime import datetime, timezone
from email.utils import format_datetime

from .config import BriefingConfig
from .uploader import gh, _get_sha

logger = logging.getLogger(__name__)

_FEED_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"
     xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/">
  <channel>
    <title>__TITLE__</title>
    <link>__FEED_URL__</link>
    <language>en-us</language>
    <description><![CDATA[__DESCRIPTION__]]></description>
    <itunes:author>__OWNER_NAME__</itunes:author>
    <itunes:summary><![CDATA[__DESCRIPTION__]]></itunes:summary>
    <itunes:owner>
      <itunes:name>__OWNER_NAME__</itunes:name>
      <itunes:email>__OWNER_EMAIL__</itunes:email>
    </itunes:owner>
    <itunes:explicit>false</itunes:explicit>
    <itunes:category text="Business">
      <itunes:category text="Investing"/>
    </itunes:category>
    <itunes:type>episodic</itunes:type>
    <lastBuildDate>__PUBDATE__</lastBuildDate>
    <!-- Add new <item> blocks above this line, newest first -->
  </channel>
</rss>
"""


def init_show(
    config: BriefingConfig,
    repo: str,
    token: str,
    owner_email: str,
) -> None:
    username, repo_name = repo.split("/", 1)
    person_id = config.person.id
    feed_url = f"https://{username}.github.io/{repo_name}/shows/{person_id}/feed.xml"

    feed_xml = (
        _FEED_TEMPLATE
        .replace("__TITLE__", f"Venrock Daily — {config.person.name}")
        .replace("__FEED_URL__", feed_url)
        .replace("__DESCRIPTION__", f"Daily investor briefing for {config.person.name}")
        .replace("__OWNER_NAME__", config.person.name)
        .replace("__OWNER_EMAIL__", owner_email)
        .replace("__PUBDATE__", format_datetime(datetime.now(timezone.utc)))
    )

    files = [
        (f"shows/{person_id}/feed.xml", feed_xml.encode(), "RSS feed"),
        (f"shows/{person_id}/episodes/.gitkeep", b"", "episodes folder"),
    ]

    for repo_path, content_bytes, label in files:
        sha = _get_sha(repo_path, repo, token)
        data: dict = {
            "message": f"[{person_id}] Init {label}",
            "content": base64.b64encode(content_bytes).decode(),
            "branch": "main",
        }
        if sha:
            data["sha"] = sha
        gh("PUT", f"/repos/{repo}/contents/{repo_path}", token, data)
        logger.info("Initialized %s: %s", label, repo_path)
