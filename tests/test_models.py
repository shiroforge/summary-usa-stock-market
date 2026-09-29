from usmarket.models import SCHEMA_VERSION, DailySummary


def test_sample_roundtrip(sample: DailySummary) -> None:
    again = DailySummary.model_validate_json(sample.model_dump_json())
    assert again == sample
    assert sample.schema_version == SCHEMA_VERSION


def test_sample_invariants(sample: DailySummary) -> None:
    assert len(sample.sectors) == 11
    pcts = [s.change_pct for s in sample.sectors]
    assert pcts == sorted(pcts, reverse=True)
    assert sample.quote("sp500") is not None
    assert sample.quote("missing") is None
    for name, series in sample.sector_history.series.items():
        assert len(series) == len(sample.sector_history.dates), name
