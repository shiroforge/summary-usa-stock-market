"""Runtime settings (env / Secrets) and typed loaders for config/*.yaml."""

from __future__ import annotations

from functools import cached_property
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from usmarket.models import QuoteCategory

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class QuoteSpec(BaseModel):
    key: str
    name: str
    ticker: str
    category: QuoteCategory
    source: Literal["yfinance", "treasury"] = "yfinance"
    is_proxy: bool = False
    unit: str = ""
    links: dict[str, str] = Field(default_factory=dict)  # external chart links (label -> URL)


class SectorSpec(BaseModel):
    key: str  # GICS sector name as published (English)
    name: str  # Japanese label
    etf: str  # Select Sector SPDR ticker


class ThemeSpec(BaseModel):
    key: str
    name: str
    keywords: list[str] = Field(default_factory=list)
    members: dict[str, str] = Field(default_factory=dict)  # ticker -> display name
    # dynamic themes get their members at run time: "ipo" = priced within `window_days` (Nasdaq IPO calendar)
    dynamic: Literal["ipo"] | None = None
    window_days: int = 365

    @field_validator("members", mode="before")
    @classmethod
    def _tickers_as_str(cls, v: dict[object, str]) -> dict[str, str]:
        return {str(k): val for k, val in v.items()}


class FeedSpec(BaseModel):
    name: str
    url: str
    filter: list[str] = Field(default_factory=list)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    config_dir: Path = PROJECT_ROOT / "config"
    data_dir: Path = PROJECT_ROOT / "data"
    site_dir: Path = PROJECT_ROOT / "site"
    cache_dir: Path = PROJECT_ROOT / ".cache"

    site_base_url: str = ""  # e.g. https://user.github.io/repo  (used in notifications)
    discord_webhook_url: str = ""
    # SEC asks automated clients to identify themselves with a contact address,
    # e.g. "usmarket you@example.com". Empty -> EDGAR filings are skipped.
    sec_user_agent: str = ""

    yf_chunk_size: int = 100
    yf_pause_sec: float = 1.0
    yf_max_retries: int = 3
    min_turnover_for_ranking: float = 1e8  # USD
    coverage_warn_pct: float = 95.0
    ipo_min_offer_usd: float = 1e8  # smaller deals are left out of the IPO theme

    def _yaml(self, name: str) -> dict[str, Any]:
        data = yaml.safe_load((self.config_dir / name).read_text(encoding="utf-8"))
        assert isinstance(data, dict), name
        return data

    @cached_property
    def quotes(self) -> list[QuoteSpec]:
        return [QuoteSpec.model_validate(q) for q in self._yaml("indices.yaml")["quotes"]]

    @cached_property
    def sectors(self) -> list[SectorSpec]:
        return [SectorSpec.model_validate(e) for e in self._yaml("indices.yaml")["sectors"]]

    @cached_property
    def themes(self) -> list[ThemeSpec]:
        return [ThemeSpec.model_validate(t) for t in self._yaml("themes.yaml")["themes"]]

    @cached_property
    def feeds(self) -> list[FeedSpec]:
        return [FeedSpec.model_validate(f) for f in self._yaml("news_feeds.yaml")["feeds"]]

    @cached_property
    def news_max_items(self) -> int:
        return int(self._yaml("news_feeds.yaml").get("max_items", 30))
