"""
Phase 8: Unified Transaction Engine tests.

- Unit tests: Credit note schema validation (return quantity, items required).
- Integration tests: Customer return flow (create invoice, batch, credit note);
  over-return rejected (400); valid return creates ledger with SALE_RETURN and document_number.

Run unit tests only: pytest backend/tests/test_transaction_engine.py -v -m "not integration"
Run all (requires DB with company, branch, user with branch role, and item):
  pytest backend/tests/test_transaction_engine.py -v
Skip integration if no DB: set RUN_INTEGRATION_TESTS=0 or omit -k integration
"""
import sys
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

backend_dir = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(backend_dir))

import pytest
from pydantic import ValidationError

# --- Unit tests: schema validation (no DB) ---


def test_credit_note_create_requires_non_empty_items():
    """CreditNoteCreate with items=[] must raise ValidationError (min_items=1)."""
    from app.schemas.sale import CreditNoteCreate, CreditNoteItemCreate

    with pytest.raises(ValidationError) as exc_info:
        CreditNoteCreate(
            original_invoice_id=uuid4(),
            credit_note_date=date.today(),
            reason="Test",
            company_id=uuid4(),
            branch_id=uuid4(),
            items=[],  # invalid: min_items=1
            created_by=uuid4(),
        )
    err = exc_info.value
    assert "items" in str(err).lower() or any("items" in str(e) for e in err.errors())


def test_credit_note_item_requires_positive_quantity():
    """CreditNoteItemCreate with quantity_returned <= 0 must raise ValidationError."""
    from app.schemas.sale import CreditNoteItemCreate

    with pytest.raises(ValidationError):
        CreditNoteItemCreate(
            item_id=uuid4(),
            original_sale_item_id=uuid4(),
            unit_name="tablet",
            quantity_returned=Decimal("0"),
            unit_price_exclusive=Decimal("10"),
        )


def test_credit_note_item_requires_non_negative_price():
    """CreditNoteItemCreate with unit_price_exclusive < 0 must raise ValidationError."""
    from app.schemas.sale import CreditNoteItemCreate

    with pytest.raises(ValidationError):
        CreditNoteItemCreate(
            item_id=uuid4(),
            original_sale_item_id=uuid4(),
            unit_name="tablet",
            quantity_returned=Decimal("1"),
            unit_price_exclusive=Decimal("-1"),
        )


def test_credit_note_create_valid_schema():
    """Valid CreditNoteCreate and CreditNoteItemCreate pass validation."""
    from app.schemas.sale import CreditNoteCreate, CreditNoteItemCreate

    item_id = uuid4()
    orig_id = uuid4()
    cn = CreditNoteCreate(
        original_invoice_id=uuid4(),
        credit_note_date=date.today(),
        reason="Faulty",
        company_id=uuid4(),
        branch_id=uuid4(),
        items=[
            CreditNoteItemCreate(
                item_id=item_id,
                original_sale_item_id=orig_id,
                unit_name="tablet",
                quantity_returned=Decimal("2"),
                unit_price_exclusive=Decimal("10.50"),
            )
        ],
        created_by=uuid4(),
    )
    assert len(cn.items) == 1
    assert cn.items[0].quantity_returned == 2
    assert cn.items[0].unit_price_exclusive == Decimal("10.50")


# --- Integration tests (require DB with company, branch, user with branch role, item) ---


@pytest.mark.integration
def test_credit_note_over_return_returns_400(client_and_auth):
    """POST credit-notes with return qty > sold qty must return 400."""
    client, auth, company_id, branch_id, user_id, item_id = client_and_auth
    if not all([company_id, branch_id, user_id, item_id]):
        pytest.skip("Integration fixture: need company, branch, user, item in DB")

    # Create draft invoice with one line (qty 5)
    inv_resp = client.post(
        "/api/sales/invoice",
        json={
            "company_id": str(company_id),
            "branch_id": str(branch_id),
            "invoice_date": date.today().isoformat(),
            "customer_name": "Test",
            "payment_mode": "cash",
            "status": "DRAFT",
            "items": [
                {
                    "item_id": str(item_id),
                    "unit_name": "tablet",
                    "quantity": 5,
                    "unit_price_exclusive": 10,
                }
            ],
            "created_by": str(user_id),
        },
        headers=auth,
    )
    assert inv_resp.status_code == 201
    invoice_id = inv_resp.json()["id"]
    line_id = inv_resp.json()["items"][0]["id"]

    # Batch the invoice
    batch_resp = client.post(
        f"/api/sales/invoice/{invoice_id}/batch?batched_by={user_id}",
        headers=auth,
    )
    assert batch_resp.status_code == 200

    # Return more than sold (10 > 5) -> 400
    cn_resp = client.post(
        "/api/sales/credit-notes",
        json={
            "original_invoice_id": invoice_id,
            "credit_note_date": date.today().isoformat(),
            "reason": "Over-return test",
            "company_id": str(company_id),
            "branch_id": str(branch_id),
            "items": [
                {
                    "item_id": str(item_id),
                    "original_sale_item_id": line_id,
                    "unit_name": "tablet",
                    "quantity_returned": 10,
                    "unit_price_exclusive": 10,
                }
            ],
            "created_by": str(user_id),
        },
        headers=auth,
    )
    assert cn_resp.status_code == 400
    assert "exceeds" in (cn_resp.json().get("detail") or "").lower() or "return" in (cn_resp.json().get("detail") or "").lower()


@pytest.mark.integration
def test_credit_note_valid_creates_document_and_ledger_with_document_number(client_and_auth):
    """POST credit-notes with valid qty creates credit note and SALE_RETURN ledger rows with document_number set."""
    from app.database import SessionLocal
    from app.models import CreditNote, InventoryLedger

    client, auth, company_id, branch_id, user_id, item_id = client_and_auth
    if not all([company_id, branch_id, user_id, item_id]):
        pytest.skip("Integration fixture: need company, branch, user, item in DB")

    # Create draft invoice, one line (qty 5)
    inv_resp = client.post(
        "/api/sales/invoice",
        json={
            "company_id": str(company_id),
            "branch_id": str(branch_id),
            "invoice_date": date.today().isoformat(),
            "customer_name": "Test",
            "payment_mode": "cash",
            "status": "DRAFT",
            "items": [
                {
                    "item_id": str(item_id),
                    "unit_name": "tablet",
                    "quantity": 5,
                    "unit_price_exclusive": 10,
                }
            ],
            "created_by": str(user_id),
        },
        headers=auth,
    )
    assert inv_resp.status_code == 201
    invoice_id = inv_resp.json()["id"]
    line_id = inv_resp.json()["items"][0]["id"]

    # Batch the invoice
    batch_resp = client.post(
        f"/api/sales/invoice/{invoice_id}/batch?batched_by={user_id}",
        headers=auth,
    )
    assert batch_resp.status_code == 200

    # Valid return: qty 2
    cn_resp = client.post(
        "/api/sales/credit-notes",
        json={
            "original_invoice_id": invoice_id,
            "credit_note_date": date.today().isoformat(),
            "reason": "Valid return",
            "company_id": str(company_id),
            "branch_id": str(branch_id),
            "items": [
                {
                    "item_id": str(item_id),
                    "original_sale_item_id": line_id,
                    "unit_name": "tablet",
                    "quantity_returned": 2,
                    "unit_price_exclusive": 10,
                }
            ],
            "created_by": str(user_id),
        },
        headers=auth,
    )
    assert cn_resp.status_code == 201
    data = cn_resp.json()
    assert "credit_note_no" in data
    assert data["credit_note_no"]
    assert data["original_invoice_id"] == invoice_id
    cn_id = data["id"]

    # Assert ledger has SALE_RETURN rows with document_number set
    db = SessionLocal()
    try:
        ledger_rows = (
            db.query(InventoryLedger)
            .filter(
                InventoryLedger.reference_type == "credit_note",
                InventoryLedger.reference_id == cn_id,
            )
            .all()
        )
        assert len(ledger_rows) >= 1
        for row in ledger_rows:
            assert row.transaction_type == "SALE_RETURN"
            assert row.quantity_delta > 0
            assert row.document_number is not None and str(row.document_number).strip() != ""
    finally:
        db.close()


@pytest.mark.integration
def test_double_return_within_limit_both_succeed(client_and_auth):
    """Two credit notes for the same line, each within remaining qty, both succeed; total returned <= sold."""
    from app.database import SessionLocal
    from app.models import CreditNote

    client, auth, company_id, branch_id, user_id, item_id = client_and_auth
    if not all([company_id, branch_id, user_id, item_id]):
        pytest.skip("Integration fixture: need company, branch, user, item in DB")

    # Create and batch invoice: one line qty 10
    inv_resp = client.post(
        "/api/sales/invoice",
        json={
            "company_id": str(company_id),
            "branch_id": str(branch_id),
            "invoice_date": date.today().isoformat(),
            "customer_name": "Test",
            "payment_mode": "cash",
            "status": "DRAFT",
            "items": [
                {
                    "item_id": str(item_id),
                    "unit_name": "tablet",
                    "quantity": 10,
                    "unit_price_exclusive": 10,
                }
            ],
            "created_by": str(user_id),
        },
        headers=auth,
    )
    assert inv_resp.status_code == 201
    invoice_id = inv_resp.json()["id"]
    line_id = inv_resp.json()["items"][0]["id"]

    batch_resp = client.post(
        f"/api/sales/invoice/{invoice_id}/batch?batched_by={user_id}",
        headers=auth,
    )
    assert batch_resp.status_code == 200

    # First return: 4
    cn1 = client.post(
        "/api/sales/credit-notes",
        json={
            "original_invoice_id": invoice_id,
            "credit_note_date": date.today().isoformat(),
            "reason": "First",
            "company_id": str(company_id),
            "branch_id": str(branch_id),
            "items": [
                {
                    "item_id": str(item_id),
                    "original_sale_item_id": line_id,
                    "unit_name": "tablet",
                    "quantity_returned": 4,
                    "unit_price_exclusive": 10,
                }
            ],
            "created_by": str(user_id),
        },
        headers=auth,
    )
    assert cn1.status_code == 201

    # Second return: 6 (remaining 10 - 4 = 6)
    cn2 = client.post(
        "/api/sales/credit-notes",
        json={
            "original_invoice_id": invoice_id,
            "credit_note_date": date.today().isoformat(),
            "reason": "Second",
            "company_id": str(company_id),
            "branch_id": str(branch_id),
            "items": [
                {
                    "item_id": str(item_id),
                    "original_sale_item_id": line_id,
                    "unit_name": "tablet",
                    "quantity_returned": 6,
                    "unit_price_exclusive": 10,
                }
            ],
            "created_by": str(user_id),
        },
        headers=auth,
    )
    assert cn2.status_code == 201

    # Third return would exceed: 1 more -> total 11 > 10 -> 400
    cn3 = client.post(
        "/api/sales/credit-notes",
        json={
            "original_invoice_id": invoice_id,
            "credit_note_date": date.today().isoformat(),
            "reason": "Over",
            "company_id": str(company_id),
            "branch_id": str(branch_id),
            "items": [
                {
                    "item_id": str(item_id),
                    "original_sale_item_id": line_id,
                    "unit_name": "tablet",
                    "quantity_returned": 1,
                    "unit_price_exclusive": 10,
                }
            ],
            "created_by": str(user_id),
        },
        headers=auth,
    )
    assert cn3.status_code == 400


# --- Fixture for integration tests ---


@pytest.fixture(scope="module")
def client_and_auth():
    """Build TestClient and auth headers; resolve company, branch, user, item from DB. Skip if any missing."""
    from fastapi.testclient import TestClient
    from app.main import app
    from app.database import SessionLocal
    from app.models import Company, Branch, User, Item
    from app.models.user import UserBranchRole
    from app.utils.auth_internal import create_access_token

    client = TestClient(app)
    db = SessionLocal()
    try:
        company = db.query(Company).first()
        if not company:
            return client, {}, None, None, None, None
        branch = db.query(Branch).filter(Branch.company_id == company.id).first()
        if not branch:
            return client, {}, str(company.id), None, None, None
        # User that has access to this branch
        ubr = (
            db.query(UserBranchRole)
            .filter(UserBranchRole.branch_id == branch.id)
            .first()
        )
        if not ubr:
            user = db.query(User).filter(User.deleted_at.is_(None)).first()
            if not user:
                return client, {}, str(company.id), str(branch.id), None, None
            user_id = user.id
        else:
            user_id = ubr.user_id
        user = db.query(User).filter(User.id == user_id, User.deleted_at.is_(None)).first()
        if not user:
            return client, {}, str(company.id), str(branch.id), None, None
        item = db.query(Item).first()
        if not item:
            return client, {}, str(company.id), str(branch.id), str(user_id), None

        token = create_access_token(
            str(user_id),
            getattr(user, "email", None) or "test@test.com",
            None,
            company_id=str(company.id),
        )
        auth = {"Authorization": f"Bearer {token}"}
        return (
            client,
            auth,
            str(company.id),
            str(branch.id),
            str(user_id),
            str(item.id),
        )
    finally:
        db.close()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-m", "not integration"])
