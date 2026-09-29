"""News source interface. Only headline/link/metadata are stored — never article bodies."""

from __future__ import annotations

import datetime as dt
from typing import Protocol

from usmarket.models import NewsItem


class NewsSource(Protocol):
    name: str

    def fetch(self, since: dt.datetime) -> list[NewsItem]:
        """Items published at or after `since` (tz-aware). Tags are filled later by the tagger."""
        ...
