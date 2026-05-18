"""
Financial event operational lifecycle (E4) — reliability metadata only, not accounting status.
"""
from __future__ import annotations

OPERATIONAL_STATUS_EMITTED = "emitted"
OPERATIONAL_STATUS_REPLAYED = "replayed"
OPERATIONAL_STATUS_COMPENSATED = "compensated"
OPERATIONAL_STATUS_DUPLICATE_IGNORED = "duplicate_ignored"

EMISSION_CHANNEL_ORIGINAL = "original"
EMISSION_CHANNEL_REPLAY = "replay"
EMISSION_CHANNEL_BACKFILL = "backfill"

ALL_OPERATIONAL_STATUSES = frozenset(
    {
        OPERATIONAL_STATUS_EMITTED,
        OPERATIONAL_STATUS_REPLAYED,
        OPERATIONAL_STATUS_COMPENSATED,
        OPERATIONAL_STATUS_DUPLICATE_IGNORED,
    }
)

ALL_EMISSION_CHANNELS = frozenset(
    {
        EMISSION_CHANNEL_ORIGINAL,
        EMISSION_CHANNEL_REPLAY,
        EMISSION_CHANNEL_BACKFILL,
    }
)
