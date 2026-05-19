"""HQ auto-assignment helpers."""
from unittest.mock import MagicMock
from uuid import uuid4

from app.services.branch_provisioning_service import ensure_user_assigned_to_company_hq


def test_ensure_user_assigned_skips_when_already_assigned(monkeypatch):
    db = MagicMock()
    user_id = uuid4()
    company_id = uuid4()
    monkeypatch.setattr(
        "app.services.branch_provisioning_service.branch_ids_assigned_to_user",
        lambda _db, _uid, _cid: [uuid4()],
    )
    assert ensure_user_assigned_to_company_hq(db, user_id, company_id) is False
    db.add.assert_not_called()
