import datetime as dt
from pathlib import Path

import httpx

from usmarket.config import FeedSpec, ThemeSpec
from usmarket.news.rss import fetch_feeds, highlight, keyword_pattern, parse_feed, rank, select, tag

XML = (Path(__file__).parent / "fixtures" / "sample_feed.xml").read_bytes()
UTC = dt.UTC
THEMES = [
    ThemeSpec(key="rates", name="金利", keywords=["FRB", "利下げ"], members={"JPM": "JPMorgan"}),
    ThemeSpec(key="semi", name="半導体", keywords=["半導体", "chipmaker"], members={"NVDA": "Nvidia"}),
    ThemeSpec(key="ai", name="AI", keywords=["AI"], members={"PLTR": "Palantir"}),
]


def test_parse_google_style_source() -> None:
    items = parse_feed(XML, FeedSpec(name="Google News 米国株", url="x"))
    assert items[0].title == "FRB、追加利下げを検討" and items[0].source == "テスト新聞"
    assert items[0].published_at == dt.datetime(2026, 9, 25, 5, 0, tzinfo=UTC)
    assert all(i.url.startswith("http") for i in items)  # item without link dropped
    other = parse_feed(XML, FeedSpec(name="CNBC", url="x"))
    assert other[0].source == "CNBC" and other[0].title.endswith("テスト新聞")


def test_filter() -> None:
    items = parse_feed(XML, FeedSpec(name="x", url="x", filter=["ナスダック"]))
    assert [i.title for i in items] == ["半導体株が高い ナスダック"]  # whitespace normalized


def test_select_window_and_dedupe() -> None:
    items = parse_feed(XML, FeedSpec(name="Google News 米国株", url="x"))
    got = select(
        items,
        since=dt.datetime(2026, 9, 24, 6, 30, tzinfo=UTC),
        until=dt.datetime(2026, 9, 25, 7, 30, tzinfo=UTC),
        max_items=10,
    )
    assert [i.url for i in got] == [
        "https://example.com/c",
        "https://example.com/b",
        "https://example.com/a",  # the older duplicate a2 is dropped
        "https://example.com/d",
    ]


def test_keyword_matching() -> None:
    p = keyword_pattern(["AI", "chip", "半導体"])
    assert p is not None
    assert p.search("Nvidia's AI boom") and p.search("Chip stocks rally") and p.search("米半導体株")
    assert not p.search("AIG shares slip") and not p.search("said the chief")  # whole words only
    assert not p.search("the ai of it")  # all-caps acronyms are case-sensitive
    assert not p.search("chips") and keyword_pattern([]) is None


def test_tag_and_highlight() -> None:
    items = tag(parse_feed(XML, FeedSpec(name="Google News 米国株", url="x")), THEMES)
    by_url = {i.url: i.tags for i in items}
    assert by_url["https://example.com/a"] == ["rates"] and by_url["https://example.com/b"] == ["semi"]
    assert by_url["https://example.com/d"] == ["semi"]  # "AIG" is not "AI"
    assert by_url["https://example.com/c"] == []
    top = highlight(items, n=2)
    assert [i.url for i in top] == ["https://example.com/a", "https://example.com/a2"]


def test_fetch_records_failures() -> None:
    def handler(req: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=XML) if "ok" in str(req.url) else httpx.Response(403)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    items, failed = fetch_feeds(
        [FeedSpec(name="A", url="https://ok/"), FeedSpec(name="B", url="https://ng/")], client=client
    )
    assert len(items) == 6 and failed == ["B"]


def test_rank_puts_relevant_first() -> None:
    items = tag(parse_feed(XML, FeedSpec(name="Google News 米国株", url="x")), THEMES)
    ranked = rank(items)
    assert ranked[-1].title in ("Weekend weather outlook", "古いニュース")
    assert ranked[0].url == "https://example.com/a"


def test_strip_site_suffix() -> None:
    xml = (
        b'<?xml version="1.0"?><rss version="2.0"><channel><item><title>'
        + b"Headline here | Markets | Some Site"
        + b"</title><link>https://example.com/x</link></item></channel></rss>"
    )
    assert parse_feed(xml, FeedSpec(name="Site", url="x"))[0].title == "Headline here"
