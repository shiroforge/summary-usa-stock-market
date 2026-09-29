import datetime as dt
import io
from pathlib import Path

import httpx
import pytest
from openpyxl import Workbook

from usmarket.sources.master import (
    combine,
    load_master,
    parse_spy_holdings,
    parse_wiki_list,
    short_name,
    to_symbol,
)

WIKI = """<html><body>
<table class="wikitable sortable" id="constituents"><tbody>
<tr><th>Symbol</th><th>Security</th><th>GICS Sector</th><th>GICS Sub-Industry</th>
<th>Headquarters Location</th><th>Date added</th><th>CIK</th><th>Founded</th></tr>
{rows}
</tbody></table></body></html>"""
ROWS = [
    ("NVDA", "Nvidia", "Information Technology", "Semiconductors", "1045810"),
    ("BRK.B", "Berkshire Hathaway", "Financials", "Multi-Sector Holdings", "1067983"),
    ("KO", "Coca-Cola Company (The)", "Consumer Staples", "Soft Drinks", "21344"),
    ("LLY", "Lilly (Eli)", "Health Care", "Pharmaceuticals", "59478"),
    ("GOOGL", "Alphabet Inc. (Class A)", "Communication Services", "Interactive Media", "1652044"),
]


def wiki_html(n_extra: int = 400) -> str:
    rows = list(ROWS) + [
        (f"X{i}", f"Filler {i} Inc.", "Industrials", "Misc", str(1000 + i)) for i in range(n_extra)
    ]
    return WIKI.format(
        rows="\n".join(
            f"<tr><td>{s}</td><td>{n}</td><td>{g}</td><td>{sub}</td><td>HQ</td><td>2000-01-01</td>"
            f"<td>{cik}</td><td>1900</td></tr>"
            for s, n, g, sub, cik in rows
        )
    )


def spy_xlsx(n_extra: int = 400) -> bytes:
    wb = Workbook()
    ws = wb.active
    assert ws is not None
    ws.append(["Fund Name:", "SPDR S&P 500 ETF Trust"])
    ws.append(["Ticker Symbol:", "SPY"])
    ws.append(["Holdings:", "As of 28-Sep-2026"])
    ws.append([])
    ws.append(["Name", "Ticker", "Identifier", "SEDOL", "Weight", "Sector", "Shares Held", "Local Currency"])
    ws.append(["NVIDIA CORP", "NVDA", "x", "x", 8.36, "-", 1, "USD"])
    ws.append(["BERKSHIRE HATHAWAY INC CL B", "BRK.B", "x", "x", 1.61, "-", 1, "USD"])
    ws.append(["COCA COLA CO/THE", "KO", "x", "x", 0.4, "-", 1, "USD"])
    ws.append(["ELI LILLY", "LLY", "x", "x", 1.2, "-", 1, "USD"])
    for i in range(n_extra):
        ws.append([f"FILLER {i}", f"X{i}", "x", "x", 0.2, "-", 1, "USD"])
    ws.append(["US DOLLAR", "CASH_USD", "x", "x", 0.05, "-", 1, "USD"])  # not an equity -> skipped
    ws.append([])
    ws.append(["Past performance is no guarantee of future results."])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_names_and_symbols() -> None:
    assert to_symbol("BRK.B") == "BRK-B" and to_symbol("nvda") == "NVDA"
    assert short_name("Apple Inc.") == "Apple"
    assert short_name("Alphabet Inc. (Class A)") == "Alphabet (Class A)"
    assert short_name("Lilly (Eli)") == "Eli Lilly"
    assert short_name("Coca-Cola Company (The)") == "Coca-Cola"
    assert short_name("JPMorgan Chase & Co.") == "JPMorgan Chase"


def test_parse_and_combine() -> None:
    as_of, weights = parse_spy_holdings(spy_xlsx())
    assert as_of == dt.date(2026, 9, 28)
    assert weights["NVDA"] == 8.36 and weights["BRK-B"] == 1.61 and "CASH_USD" not in weights
    wiki = parse_wiki_list(wiki_html())
    m = combine(as_of, weights, wiki)
    by = m.by_code()
    assert by["BRK-B"].sector == "Financials" and by["BRK-B"].cik == "0001067983"
    assert by["LLY"].name == "Eli Lilly" and by["KO"].name == "Coca-Cola"
    assert "GOOGL" not in by  # no SPY weight in this sample -> skipped


def test_parse_rejects_truncated_files() -> None:
    with pytest.raises(ValueError):
        parse_spy_holdings(spy_xlsx(n_extra=10))
    with pytest.raises(ValueError):
        parse_wiki_list(wiki_html(n_extra=10))


def test_load_master_uses_cache_when_offline(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(str(req.url))
        if "ssga" in str(req.url):
            return httpx.Response(200, content=spy_xlsx())
        return httpx.Response(200, text=wiki_html())

    today = dt.date(2026, 9, 29)
    m = load_master(tmp_path, today=today, client=httpx.Client(transport=httpx.MockTransport(handler)))
    assert len(m.constituents) == 404 and len(calls) == 2
    offline = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(503)))
    again = load_master(tmp_path, today=today, client=offline)  # fresh cache: no request at all
    assert len(again.constituents) == 404
    later = load_master(tmp_path, today=today + dt.timedelta(days=30), client=offline)  # stale + offline
    assert len(later.constituents) == 404
