"""
Draft sales invoice for OPD encounters (reuses sales_invoices / sales_invoice_items).

Does not call the retail sales API (no stock allocation at draft time).
Consultation uses a dedicated SERVICE item per company (auto-created).
Exactly one draft invoice per encounter (idempotent under row lock).
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models import Item, SalesInvoice, SalesInvoiceItem
from app.models.clinic import Encounter, Patient
from app.services.document_service import DocumentService
from app.utils.vat import vat_rate_to_percent

CONSULTATION_ITEM_SKU = "__CLINIC_CONSULTATION_FEE__"


def get_or_create_consultation_fee_item(db: Session, company_id: UUID) -> Item:
    existing = (
        db.query(Item)
        .filter(
            Item.company_id == company_id,
            Item.sku == CONSULTATION_ITEM_SKU,
        )
        .first()
    )
    if existing:
        return existing
    item = Item(
        company_id=company_id,
        name="Consultation Fee",
        description="OPD consultation (system)",
        sku=CONSULTATION_ITEM_SKU,
        category="Clinic",
        product_category="SERVICE",
        pricing_tier="SERVICE",
        base_unit="visit",
        retail_unit="visit",
        wholesale_unit="visit",
        supplier_unit="visit",
        pack_size=1,
        wholesale_units_per_supplier=Decimal("1"),
        can_break_bulk=False,
        vat_category="STANDARD_RATED",
        vat_rate=Decimal("16"),
        is_active=True,
        setup_complete=True,
        track_expiry=False,
    )
    db.add(item)
    db.flush()
    return item


def ensure_draft_invoice_for_encounter(
    db: Session,
    *,
    encounter_id: UUID,
    company_id: UUID,
    patient: Patient,
    user_id: UUID,
    consult_unit_price_exclusive: Optional[Decimal] = None,
) -> SalesInvoice:
    """
    Under row lock: return existing linked invoice, or reconcile by encounter_id, or create once.
    Never creates a second invoice for the same encounter.
    """
    enc = (
        db.query(Encounter)
        .filter(Encounter.id == encounter_id, Encounter.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not enc:
        raise ValueError("Encounter not found for billing")

    if enc.sales_invoice_id:
        inv = (
            db.query(SalesInvoice)
            .filter(
                SalesInvoice.id == enc.sales_invoice_id,
                SalesInvoice.company_id == company_id,
            )
            .with_for_update()
            .first()
        )
        if inv:
            return inv
        enc.sales_invoice_id = None
        db.add(enc)
        db.flush()

    orphan = (
        db.query(SalesInvoice)
        .filter(
            SalesInvoice.encounter_id == encounter_id,
            SalesInvoice.company_id == company_id,
        )
        .with_for_update()
        .first()
    )
    if orphan:
        enc.sales_invoice_id = orphan.id
        db.add(enc)
        db.flush()
        return orphan

    fee_item = get_or_create_consultation_fee_item(db, company_id)
    unit_name = fee_item.retail_unit or "visit"
    unit_price = consult_unit_price_exclusive
    if unit_price is None:
        unit_price = Decimal("0")

    item_vat_rate = Decimal(str(vat_rate_to_percent(fee_item.vat_rate)))
    qty = Decimal("1")
    line_total_exclusive = qty * unit_price
    line_vat = line_total_exclusive * item_vat_rate / Decimal("100")
    line_total_inclusive = line_total_exclusive + line_vat

    invoice_no = DocumentService.get_sales_invoice_number(
        db, company_id, enc.branch_id
    )
    customer_name = f"{(patient.first_name or '').strip()} {(patient.last_name or '').strip()}".strip() or "Patient"
    customer_phone = (patient.phone or "").strip() or None

    db_invoice = SalesInvoice(
        company_id=company_id,
        branch_id=enc.branch_id,
        invoice_no=invoice_no,
        invoice_date=date.today(),
        customer_name=customer_name,
        customer_phone=customer_phone,
        payment_mode="cash",
        payment_status="UNPAID",
        sales_type="RETAIL",
        status="DRAFT",
        total_exclusive=line_total_exclusive,
        vat_rate=item_vat_rate if line_total_exclusive > 0 else Decimal("0"),
        vat_amount=line_vat,
        discount_amount=Decimal("0"),
        total_inclusive=line_total_inclusive,
        created_by=user_id,
        encounter_id=enc.id,
    )
    db.add(db_invoice)
    db.flush()

    line = SalesInvoiceItem(
        sales_invoice_id=db_invoice.id,
        item_id=fee_item.id,
        batch_id=None,
        unit_name=unit_name,
        quantity=qty,
        unit_price_exclusive=unit_price,
        discount_percent=Decimal("0"),
        discount_amount=Decimal("0"),
        vat_rate=item_vat_rate,
        vat_amount=line_vat,
        line_total_exclusive=line_total_exclusive,
        line_total_inclusive=line_total_inclusive,
        unit_cost_used=None,
        item_name=fee_item.name,
        item_code=fee_item.sku or "",
    )
    db.add(line)

    enc.sales_invoice_id = db_invoice.id
    db.add(enc)
    db.flush()
    db.refresh(db_invoice)
    return db_invoice
