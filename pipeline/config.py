from __future__ import annotations

from pathlib import Path
from typing import Optional

import yaml
from pydantic import BaseModel, model_validator


class PersonConfig(BaseModel):
    id: str
    name: str
    voice: str = "en-US-JennyNeural"
    timezone: str = "America/Los_Angeles"


class ScheduleConfig(BaseModel):
    days: list[str]
    time: str


class OutputConfig(BaseModel):
    target_words: int = 1600
    quiet_day_threshold: int = 5
    quiet_day_words: int = 650
    format: str = "mp3"


class ThoughtLeader(BaseModel):
    name: str
    handles: Optional[list[str]] = None
    aliases: Optional[list[str]] = None


class FocusAreasConfig(BaseModel):
    relevance_threshold: int = 6
    topics: list[str]
    thought_leaders: list[ThoughtLeader] = []
    exclude_topics: list[str] = []


class RssSource(BaseModel):
    name: str
    url: str
    filter_topics: Optional[list[str]] = None


class OutlookSource(BaseModel):
    name: str
    search_query: str
    lookback_hours: Optional[int] = None
    lookback_days: Optional[int] = None
    active: bool = False

    @model_validator(mode="after")
    def check_lookback(self) -> "OutlookSource":
        if self.lookback_hours is None and self.lookback_days is None:
            raise ValueError("OutlookSource requires lookback_hours or lookback_days")
        return self


class ScrapedSource(BaseModel):
    name: str
    url: str
    lookback_days: int = 1


class PodcastSource(BaseModel):
    name: str
    site_url: str
    active: bool = False


class SourceGroup(BaseModel):
    rss: list[RssSource] = []
    outlook: list[OutlookSource] = []
    scraped_urls: list[ScrapedSource] = []
    podcasts: list[PodcastSource] = []


class SourcesConfig(BaseModel):
    biotech_news: SourceGroup = SourceGroup()
    tech_insights: SourceGroup = SourceGroup()
    macro_and_markets: SourceGroup = SourceGroup()


class StyleConfig(BaseModel):
    greeting: str
    tone: str
    story_treatment: str
    signoff: str
    section_order: list[str]


class BriefingConfig(BaseModel):
    person: PersonConfig
    schedule: ScheduleConfig
    output: OutputConfig
    focus_areas: FocusAreasConfig
    sources: SourcesConfig
    style: StyleConfig

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BriefingConfig":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return cls.model_validate(data)
