"""
Event temporal semantics (E5.5 / E6).

occurred_at = economic/business time (immutable after emit)
emitted_at   = system persistence time
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Literal, Optional, Tuple

TemporalBasis = Literal["occurred_at", "emitted_at", "as_of_query"]

TEMPORAL_SEMANTICS: dict[str, str] = {
    "occurred_at": "Business/economic time — used for projections and backfill chronology",
    "emitted_at": "System persistence time — audit ordering only",
    "as_of_query": "Read-time snapshot — not a stored economic position",
    "backfill_preserves_occurred_at": "Backfill must not rewrite occurred_at on existing events",
    "no_smart_recomputation": "Backfill replays hooks; does not reinterpret policy historically",
}


def resolve_temporal_filter(
    *,
    temporal_basis: TemporalBasis,
    since: Optional[date],
    until: Optional[date],
) -> Tuple[Optional[datetime], datetime]:
    """Map projection temporal_basis + date range to query bounds."""
    until_dt = (
        datetime.combine(until, datetime.max.time(), tzinfo=timezone.utc)
        if until
        else datetime.now(timezone.utc)
    )
    if since is None:
        return None, until_dt
    since_dt = datetime.combine(since, datetime.min.time(), tzinfo=timezone.utc)
    return since_dt, until_dt
