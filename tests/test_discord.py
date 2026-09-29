import json

import httpx

from usmarket.models import DailySummary
from usmarket.notify.discord import COLOR_DOWN, COLOR_UP, DiscordNotifier, build_payload, error_payload

URL = "https://example.github.io/repo/2026-09-25/"


def test_payload_shape_and_limits(sample: DailySummary) -> None:
    p = build_payload(sample, URL)
    e = p["embeds"][0]
    assert e["title"] == "2026/09/25(金) NY引け" and e["url"] == URL and p["username"] == "NY引けノート"
    assert URL in e["description"]
    names = [f["name"] for f in e["fields"]]
    assert names[:4] == ["▲ 上位セクター", "▼ 下位セクター", "🔥 強いテーマ", "🧊 弱いテーマ"]
    assert "📰 ニュース" in names and "⚠️ 注意" in names
    assert all(len(f["value"]) <= 1024 for f in e["fields"]) and len(e["fields"]) <= 25
    total = (
        len(e["title"]) + len(e["description"]) + sum(len(f["name"]) + len(f["value"]) for f in e["fields"])
    )
    assert total <= 6000
    sp = sample.quote("sp500")
    assert sp is not None and e["color"] == (COLOR_UP if sp.change_pct > 0 else COLOR_DOWN)
    assert COLOR_UP == 0x1A7C55  # green = up (US convention)
    assert e["description"].startswith("**S&P500** ") and "**NYダウ**" in e["description"]
    assert "S&P500は" not in e["description"]  # the index sentence of the comment is not repeated
    macro = next(f["value"] for f in e["fields"] if f["name"] == "金利・為替・商品")
    assert "米国 10年" in macro and "bp)" in macro and "VIX" in macro
    json.dumps(p)  # serializable


def test_send_and_dry_run(sample: DailySummary) -> None:
    sent: list[dict[str, object]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        sent.append(json.loads(req.content))
        return httpx.Response(204)

    n = DiscordNotifier(
        "https://discord.test/hook", client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    n.send(sample, URL, dry_run=True)
    assert sent == []
    n.send(sample, URL)
    n.send_error("boom", run_url="https://github.com/run/1")
    assert len(sent) == 2
    assert "run/1" in error_payload("boom", "https://github.com/run/1")["embeds"][0]["description"]


def test_disclosure_moves_in_payload(sample: DailySummary) -> None:
    e = build_payload(sample, URL)["embeds"][0]
    field = next(f for f in e["fields"] if f["name"].startswith("📄"))
    assert field["name"] == "📄 引け後の決算・開示（8-K）"
    assert (
        "[MU](https://example.com/edgar/MU-index.htm) Micron Technology 決算・Reg FD開示（時間外 +9.2%）"
        in field["value"]
    )
