import datetime as dt
import json
from pathlib import Path

import httpx

from usmarket.calendar import ET
from usmarket.models import Disclosure
from usmarket.news.edgar import classify, fetch_recent, load_cik_map, notable, parse_feed, window

FIX = Path(__file__).parent / "fixtures"
FEED = (FIX / "edgar_current_sample.xml").read_text(encoding="latin-1")
CIKS = {"0001674335": "JELD", "0000089800": "SHW", "0001832038": "IVVD"}


def test_classify() -> None:
    assert classify(["2.02", "9.01"]) == (["決算"], "neutral")
    assert classify(["8.01", "1.01"]) == (["重要な契約", "その他の重要事項"], "neutral")
    assert classify(["2.06", "2.02"]) == (["決算", "減損"], "neg")
    assert classify(["5.07", "9.01"]) == ([], "neutral")


def test_parse_feed() -> None:
    items = parse_feed(FEED, CIKS)
    assert [d.code for d in items] == ["IVVD", "JELD", "SHW"]  # others not in the map; 8-K/A dropped
    jeld = items[1]
    assert jeld.time == dt.datetime(2026, 9, 29, 7, 9, 35, tzinfo=ET)
    assert jeld.items == ["1.01", "7.01", "9.01"] and jeld.tags == ["重要な契約", "Reg FD開示"]
    assert jeld.url.startswith("https://www.sec.gov/Archives/edgar/data/1674335/")
    assert "9.01" not in jeld.title and jeld.title.startswith("1.01 Entry into a Material")


def test_fetch_recent_pages_until_since() -> None:
    pages: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        pages.append(req.url.params["start"])
        assert req.headers["User-Agent"] == "test agent@example.com"
        return httpx.Response(200, text=FEED)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    since = dt.datetime(2026, 9, 29, 7, 10, tzinfo=ET)  # the page reaches back past it -> one page
    got = fetch_recent(since, CIKS, client=client, user_agent="test agent@example.com", sleep=lambda s: None)
    assert got is not None and len(got) == 3 and pages == ["0"]
    earlier = dt.datetime(2026, 9, 28, 16, 0, tzinfo=ET)  # every page is newer -> keep paging (max 6)
    fetch_recent(earlier, CIKS, client=client, user_agent="test agent@example.com", sleep=lambda s: None)
    assert pages[1:] == ["0", "100", "200", "300", "400", "500"]
    down = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(403)))
    assert fetch_recent(since, CIKS, client=down, user_agent="x", sleep=lambda s: None) is None


def test_cik_map(tmp_path: Path) -> None:
    data = {
        "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA CORP"},
        "1": {"cik_str": 1067983, "ticker": "BRK.B", "title": "BERKSHIRE"},
        "2": {"cik_str": 1067983, "ticker": "BRK.A", "title": "BERKSHIRE"},
    }
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, text=json.dumps(data))))
    m = load_cik_map(tmp_path, client=client, user_agent="x", today=dt.date(2026, 9, 29))
    assert m == {"0001045810": "NVDA", "0001067983": "BRK-B"}


def d(code: str, hour: int, tags: list[str], url: str) -> Disclosure:
    return Disclosure(
        code=code, name=code, time=dt.datetime(2026, 9, 25, hour, 0, tzinfo=ET), title="t", url=url, tags=tags
    )


def test_window_and_notable() -> None:
    items = [
        d("A", 9, ["決算"], "u1"),
        d("B", 17, ["役員の異動"], "u2"),
        d("B", 17, ["役員の異動"], "u2"),
        d("C", 12, [], "u3"),
        d("D", 15, ["Reg FD開示"], "u4"),
    ]
    w = window(items, dt.datetime(2026, 9, 25, 9, 0, tzinfo=ET), dt.datetime(2026, 9, 25, 16, 0, tzinfo=ET))
    assert [x.url for x in w] == ["u4", "u3", "u1"]
    assert [x.code for x in notable(w, {"A": 5.0, "D": 1.0})] == ["A", "D"]  # C has no notable tag
