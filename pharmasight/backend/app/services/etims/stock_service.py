"""
Stock movement / adjustment reporting to eTIMS (if required by OSCU scope).

Responsibilities (when implemented):
- Map inventory ledger events (transfers, adjustments) to KRA stock APIs when mandated.
- Stay consistent with existing single-DB multi-company tenancy (filter by company_id).
"""


def placeholder() -> None:
    raise NotImplementedError("eTIMS stock reporting not wired yet")
