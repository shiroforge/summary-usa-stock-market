from pathlib import Path

import pytest

from usmarket.models import DailySummary

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample() -> DailySummary:
    return DailySummary.model_validate_json((FIXTURES / "sample_summary.json").read_text(encoding="utf-8"))
