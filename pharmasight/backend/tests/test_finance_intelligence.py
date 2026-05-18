"""Branch confidence scoring (unit-level, no DB)."""
from app.finance.intelligence.branch_confidence import _level_from_score


def test_confidence_levels_progressive():
    assert _level_from_score(90) == "projection_trusted"
    assert _level_from_score(70) == "projection_assisted"
    assert _level_from_score(50) == "shadow"
    assert _level_from_score(20) == "reconciliation_only"
