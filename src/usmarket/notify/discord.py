"""Discord webhook notifier: one embed with the day's highlights and a link to the page."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from usmarket.models import DailySummary, Disclosure, Quote
from usmarket.news.rss import highlight
from usmarket.render.builder import WEEKDAYS_JA

log = logging.getLogger(__name__)

COLOR_UP = 0x1A7C55  # 上昇=緑（米国式、DECISIONS D-09）
COLOR_DOWN = 0xC4382F
COLOR_FLAT = 0x778097
COLOR_ERROR = 0xB7791F
FIELD_MAX = 1024


def _pct(v: float | None) -> str:
    return "—" if v is None else f"{v:+.2f}%"


def _arrow(v: float | None) -> str:
    if v is None or abs(v) < 0.005:
        return "→"
    return "▲" if v > 0 else "▼"


def _level(v: float) -> str:
    return f"{v:,.2f}"


def _quote_line(q: Quote | None) -> str | None:
    if q is None:
        return None
    if q.unit == "%":
        return f"{q.name} {q.close:.3f}% ({q.change * 100:+.1f}bp)"
    return f"{q.name} {_level(q.close)} ({_pct(q.change_pct)})"


def _disc_move(d: Disclosure) -> str:
    if d.move_pct is None:
        return ""
    basis = "時間外" if d.move_basis == "ah" else "当日"
    return f"（{basis} {d.move_pct:+.1f}%）"


def _clip(text: str, limit: int = FIELD_MAX) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_payload(summary: DailySummary, page_url: str) -> dict[str, Any]:
    d = summary.date
    heads = [summary.quote(k) for k in ("sp500", "nasdaq", "dow")]
    sp = heads[0]
    lead = sp.change_pct if sp else None
    color = COLOR_FLAT if lead is None or abs(lead) < 0.005 else COLOR_UP if lead > 0 else COLOR_DOWN

    head = "\n".join(
        f"**{q.name}** {_level(q.close)} {_arrow(q.change_pct)} {_pct(q.change_pct)}"
        for q in heads
        if q is not None
    )
    desc = [head] if head else []
    if summary.comment:
        # the index sentence duplicates the headline above
        comment = summary.comment
        if comment.startswith("S&P500は"):
            comment = comment.split("。", 1)[1]
        if comment.strip():
            desc.append(comment.strip())
    if summary.breadth and summary.breadth.total:
        b = summary.breadth
        desc.append(f"値上がり {b.advancers} ／ 値下がり {b.decliners} ／ 変わらず {b.unchanged}")

    fields: list[dict[str, Any]] = []
    if summary.sectors:
        top = "\n".join(f"{s.name} {_pct(s.change_pct)}" for s in summary.sectors[:3])
        bottom = "\n".join(f"{s.name} {_pct(s.change_pct)}" for s in summary.sectors[::-1][:3])
        fields += [
            {"name": "▲ 上位セクター", "value": top, "inline": True},
            {"name": "▼ 下位セクター", "value": bottom, "inline": True},
        ]
    if summary.themes:
        strong = "\n".join(f"{t.name} {_pct(t.change_pct)}" for t in summary.themes[:3])
        weak = "\n".join(f"{t.name} {_pct(t.change_pct)}" for t in summary.themes[::-1][:3])
        fields += [
            {"name": "🔥 強いテーマ", "value": strong, "inline": True},
            {"name": "🧊 弱いテーマ", "value": weak, "inline": True},
        ]
    macro = [
        _quote_line(summary.quote(k))
        for k in ("sox", "vix", "us10y", "ust2y", "usdjpy", "wti", "gold", "bitcoin")
    ]
    macro_lines = [m for m in macro if m]
    if macro_lines:
        fields.append({"name": "金利・為替・商品", "value": "\n".join(macro_lines), "inline": False})
    movers = summary.rankings.gainers[:3]
    if movers:
        fields.append(
            {
                "name": "値上がり率上位",
                "value": "\n".join(f"{m.code} {m.name} {_pct(m.change_pct)}" for m in movers),
                "inline": True,
            }
        )
    surge = summary.rankings.volume_surge[:3]
    if surge:
        fields.append(
            {
                "name": "出来高急増",
                "value": "\n".join(
                    f"{m.code} {m.name} {m.volume_ratio:.1f}倍" for m in surge if m.volume_ratio
                ),
                "inline": True,
            }
        )
    news = highlight(summary.news, 3)
    if news:
        fields.append(
            {
                "name": "📰 ニュース",
                "value": _clip("\n".join(f"・[{n.title}]({n.url})" for n in news)),
                "inline": False,
            }
        )
    discs = (summary.disclosures_after or summary.disclosures_session)[:3]
    if discs:
        label = (
            "📄 引け後の決算・開示（8-K）" if summary.disclosures_after else "📄 注目の開示（8-K、〜引け）"
        )
        fields.append(
            {
                "name": label,
                "value": _clip(
                    "\n".join(
                        f"・[{x.code}]({x.url}) {x.name} {'・'.join(x.tags[:2])}{_disc_move(x)}"
                        for x in discs
                    )
                ),
                "inline": False,
            }
        )
    if summary.warnings:
        fields.append({"name": "⚠️ 注意", "value": _clip("\n".join(summary.warnings)), "inline": False})

    title = f"{d.year}/{d.month:02d}/{d.day:02d}({WEEKDAYS_JA[d.weekday()]}) NY引け"
    return {
        "username": "NY引けノート",
        "embeds": [
            {
                "title": title,
                "url": page_url,
                "description": _clip("\n".join(desc) + f"\n\n👉 [ページを開く]({page_url})", 4096),
                "color": color,
                "fields": fields,
                "footer": {"text": "NY引けノート ・ 情報提供のみを目的としており、投資助言ではありません"},
                "timestamp": summary.generated_at.isoformat(),
            }
        ],
    }


def error_payload(message: str, run_url: str | None = None) -> dict[str, Any]:
    desc = _clip(message, 3500) + (f"\n\n[実行ログを見る]({run_url})" if run_url else "")
    return {
        "username": "NY引けノート",
        "embeds": [
            {"title": "⚠️ NY引けノートの生成に失敗しました", "description": desc, "color": COLOR_ERROR}
        ],
    }


class DiscordNotifier:
    name = "discord"

    def __init__(self, webhook_url: str, *, client: httpx.Client | None = None) -> None:
        self.webhook_url = webhook_url
        self._client = client or httpx.Client(timeout=20)

    def _post(self, payload: dict[str, Any]) -> None:
        r = self._client.post(self.webhook_url, json=payload)
        r.raise_for_status()

    def send(self, summary: DailySummary, page_url: str, *, dry_run: bool = False) -> dict[str, object]:
        payload = build_payload(summary, page_url)
        if not dry_run:
            self._post(payload)
        return payload

    def send_error(self, message: str, *, dry_run: bool = False, run_url: str | None = None) -> None:
        if not dry_run:
            self._post(error_payload(message, run_url))
