from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class FetchedItem:
    title: str
    url: str
    source_name: str
    section: str  # biotech_news | tech_insights | macro_and_markets
    published: Optional[datetime]
    summary: str = ""
    full_text: str = ""
    author: str = ""
