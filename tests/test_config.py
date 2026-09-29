from usmarket.config import Settings


def test_load_real_config() -> None:
    s = Settings()
    keys = [q.key for q in s.quotes]
    assert {"sp500", "nasdaq", "dow", "vix", "us10y", "ust2y", "usdjpy"} <= set(keys)
    assert len(keys) == len(set(keys))
    assert len(s.sectors) == 11 and len({x.etf for x in s.sectors}) == 11
    assert len(s.themes) >= 25
    theme_keys = [t.key for t in s.themes]
    assert len(theme_keys) == len(set(theme_keys))
    for t in s.themes:
        # YAML 1.1 would read tickers like ON / YES as booleans unless quoted
        assert all(isinstance(c, str) and c == c.upper() and 1 <= len(c) <= 6 for c in t.members), t.key
    assert any(t.dynamic == "ipo" for t in s.themes)
    assert s.feeds and s.news_max_items > 0
