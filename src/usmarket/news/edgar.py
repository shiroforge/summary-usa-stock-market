"""SEC EDGAR 8-K filings from the "latest filings" Atom feed. DECISIONS D-23.

Only the form, item numbers, time and the filing-index link are kept; filing documents are never fetched.
SEC's fair-access policy asks for a User-Agent with a contact address and at most 10 requests/second; we
make a handful of sequential requests per run.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import logging
import re
import time
from collections.abc import Callable, Iterable, Mapping, Sequence
from pathlib import Path

import httpx

from usmarket.models import Disclosure

log = logging.getLogger(__name__)

FEED_URL = (
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcurrent&type=8-K&count=100&start={start}&output=atom"
)
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
MAX_PAGES = 6  # the feed holds ~3 business days (~400 filings)

ENTRY = re.compile(r"<entry>(.*?)</entry>", re.S)
TITLE = re.compile(
    r"<title>\s*(?P<form>[^<]+?) - (?P<name>.*?) \((?P<cik>\d{10})\) \((?P<role>\w+)\)\s*</title>"
)
LINK = re.compile(r'<link[^>]*href="(?P<href>[^"]+)"')
UPDATED = re.compile(r"<updated>(?P<t>[^<]+)</updated>")
ITEM = re.compile(r"Item (?P<no>\d\.\d{2}):\s*(?P<text>[^<\n]+)")

# item -> (category, tone). Only these items make a filing "notable"; others (9.01 exhibits, 5.07 votes,
# 5.03 bylaws, ...) are counted but not listed.
ITEM_RULES: dict[str, tuple[str, str]] = {
    "2.02": ("決算", "neutral"),
    "1.01": ("重要な契約", "neutral"),
    "1.02": ("契約の終了", "neutral"),
    "2.01": ("買収・売却の完了", "neutral"),
    "5.01": ("支配権の異動", "neutral"),
    "1.03": ("破産・更生", "neg"),
    "2.05": ("リストラ", "neg"),
    "2.06": ("減損", "neg"),
    "3.01": ("上場廃止・基準抵触", "neg"),
    "3.02": ("未登録株式の発行", "neg"),
    "4.02": ("過去決算の訂正", "neg"),
    "5.02": ("役員の異動", "neutral"),
    "7.01": ("Reg FD開示", "neutral"),
    "8.01": ("その他の重要事項", "neutral"),
}
NOTABLE = {tag for tag, _ in ITEM_RULES.values()}
# display priority (lower = more important) for choosing which filings to attach to a stock
PRIORITY = {tag: i for i, (tag, _) in enumerate(ITEM_RULES.values())}


def classify(items: Sequence[str]) -> tuple[list[str], str]:
    rules = [ITEM_RULES[i] for i in items if i in ITEM_RULES]
    tags = sorted(dict.fromkeys(t for t, _ in rules), key=lambda t: PRIORITY[t])
    tone = "neg" if any(tone == "neg" for _, tone in rules) else "neutral"
    return tags, tone


def parse_feed(xml: str, tickers_by_cik: Mapping[str, str]) -> list[Disclosure]:
    """8-K filings (amendments excluded) by companies in `tickers_by_cik`."""
    out = []
    for m in ENTRY.finditer(xml):
        body = m.group(1)
        t, link, upd = TITLE.search(body), LINK.search(body), UPDATED.search(body)
        if not (t and link and upd) or t["form"].strip() != "8-K" or t["role"] != "Filer":
            continue
        code = tickers_by_cik.get(t["cik"])
        if code is None:
            continue
        summary = html.unescape(body)
        found = [(i["no"], i["text"].strip()) for i in ITEM.finditer(summary)]
        items = [no for no, _ in found]
        tags, tone = classify(items)
        title = "; ".join(f"{no} {text}" for no, text in found if no != "9.01") or "8-K"
        out.append(
            Disclosure(
                code=code,
                name=html.unescape(t["name"]).strip(),
                time=dt.datetime.fromisoformat(upd["t"]),
                title=title,
                url=link["href"],
                items=items,
                tags=tags,
                tone=tone,
            )
        )
    return out


def load_cik_map(cache_dir: Path, *, client: httpx.Client, user_agent: str, today: dt.date) -> dict[str, str]:
    """{10-digit CIK: ticker} from SEC's company_tickers.json (cached for 30 days)."""
    path = cache_dir / "edgar" / "company_tickers.json"
    fresh = path.exists() and dt.date.fromtimestamp(path.stat().st_mtime) > today - dt.timedelta(days=30)
    if not fresh:
        try:
            r = client.get(TICKERS_URL, headers={"User-Agent": user_agent})
            r.raise_for_status()
            r.json()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(r.content)
        except (httpx.HTTPError, ValueError) as e:
            log.warning("SEC company_tickers.json failed: %s", e)
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for row in data.values():
        cik = f"{int(row['cik_str']):010d}"
        out.setdefault(cik, str(row["ticker"]).upper().replace(".", "-"))  # first listed = primary class
    return out


def fetch_recent(
    since: dt.datetime,
    tickers_by_cik: Mapping[str, str],
    *,
    client: httpx.Client,
    user_agent: str,
    pause: float = 0.3,
    sleep: Callable[[float], None] = time.sleep,
) -> list[Disclosure] | None:
    """Filings accepted at or after `since`, or None if EDGAR could not be read."""
    items: list[Disclosure] = []
    for page in range(MAX_PAGES):
        if page:
            sleep(pause)
        try:
            r = client.get(FEED_URL.format(start=page * 100), headers={"User-Agent": user_agent})
            r.raise_for_status()
        except httpx.HTTPError as e:
            log.warning("EDGAR page %d failed: %s", page, e)
            return items or None
        times = [dt.datetime.fromisoformat(u) for u in UPDATED.findall(r.text)[1:]]  # [0] = feed itself
        items.extend(parse_feed(r.text, tickers_by_cik))
        if not times or min(times) < since:
            break
    return items


def window(items: Iterable[Disclosure], start: dt.datetime, end: dt.datetime) -> list[Disclosure]:
    """Filings with start <= time < end, newest first, de-duplicated by URL."""
    seen: set[str] = set()
    out = []
    for d in sorted(items, key=lambda d: d.time, reverse=True):
        if start <= d.time < end and d.url not in seen:
            seen.add(d.url)
            out.append(d)
    return out


def priority(d: Disclosure) -> int:
    """Lower = more important (the filing's most important category)."""
    return min((PRIORITY.get(t, 99) for t in d.tags), default=99)


def notable(
    items: Sequence[Disclosure], weights: Mapping[str, float], *, limit: int = 40
) -> list[Disclosure]:
    """Market-moving items only, larger companies (index weight) first, then newest."""
    picked = [d for d in items if NOTABLE.intersection(d.tags)]
    return sorted(picked, key=lambda d: (-weights.get(d.code, 0.0), -d.time.timestamp()))[:limit]
