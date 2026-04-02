"""
Sales document submission to eTIMS (invoices / receipts).

Responsibilities (when implemented):
- Build payload from immutable posted invoice snapshot (batch-complete state).
- Invoke official sales/trnsSalesSave (or equivalent) from the collection.
- Persist kra_receipt_number, kra_signature, kra_qr_code / payload, submission_status.
- Called only from background workers — not from FastAPI request thread.
"""


def placeholder() -> None:
    raise NotImplementedError("eTIMS sales submit not wired yet")
