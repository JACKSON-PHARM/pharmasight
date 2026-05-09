"""
OPD / Clinic API (patients, encounters, notes, clinic orders).

All routes gated by require_module("clinic"). All data scoped by company_id.
"""
from __future__ import annotations

import logging
import re
from decimal import Decimal
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from app.dependencies import (
    get_current_user,
    get_effective_company_id_for_user,
    get_tenant_db,
    require_company_match,
    ensure_user_has_branch_access,
)
from app.module_enforcement import require_module
from app.models import Branch, Item, User, SalesInvoice, SalesInvoiceItem, InventoryLedger
from app.models.clinic import (
    Patient,
    Encounter,
    EncounterNote,
    ClinicOrder,
    ClinicOrderItem,
    EncounterTriage,
    ClinicalService,
    ClinicalServiceComponent,
    ClinicalServiceAccumulator,
    EncounterServiceExecution,
    EncounterServiceExecutionLine,
    DepartmentStore,
    DepartmentStoreStock,
    DepartmentStoreMovement,
)
from app.schemas.clinic import (
    PatientCreate,
    PatientUpdate,
    PatientResponse,
    EncounterCreate,
    EncounterResponse,
    EncounterStatusUpdate,
    EncounterNoteCreate,
    EncounterNoteResponse,
    ClinicOrderCreate,
    ClinicOrderResponse,
    ClinicOrderItemResponse,
    ClinicOrderItemCreate,
    EncounterTriageUpsert,
    EncounterTriageResponse,
    ClinicalServiceCreate,
    ClinicalServiceUpdate,
    ClinicalServiceResponse,
    ServiceExecutionRequest,
    ServiceExecutionResponse,
    DepartmentStoreCreate,
    DepartmentStoreResponse,
    DepartmentStoreSeedDefaultsRequest,
    DepartmentStoreSeedDefaultsResponse,
    DepartmentStoreIssueRequest,
    DepartmentStoreReconcileRequest,
    DepartmentStoreReturnRequest,
    PatientChartResponse,
    PatientChartEntry,
)
from app.services.clinic_billing_service import ensure_draft_invoice_for_encounter
from app.services.inventory_service import InventoryService
from app.services.snapshot_service import SnapshotService
from app.services.order_book_service import OrderBookService
from app.services.canonical_pricing import CanonicalPricingService

logger = logging.getLogger(__name__)

# Default department mini-stores per branch (codes unique per branch). Idempotent seed via API.
_DEFAULT_DEPARTMENT_STORE_TEMPLATES: Tuple[Tuple[str, str], ...] = (
    ("TRIAGE", "Triage"),
    ("LAB", "Lab"),
    ("INPATIENT", "Inpatient"),
    ("DENTAL", "Dental clinic"),
    ("EYE", "Eye clinic"),
    ("ONCOLOGY", "Oncology clinic"),
    ("EMERGENCY", "Emergency clinic"),
)

router = APIRouter(
    prefix="/clinic",
    tags=["Clinic / OPD"],
    dependencies=[Depends(require_module("clinic"))],
)

_ENCOUNTER_STATUS_ORDER = ("waiting", "in_consultation", "completed")


def _company_id(db: Session, user: User) -> UUID:
    cid = get_effective_company_id_for_user(db, user)
    if cid is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot resolve company",
        )
    return cid


def _get_patient_scoped(db: Session, patient_id: UUID, company_id: UUID) -> Patient:
    p = (
        db.query(Patient)
        .filter(Patient.id == patient_id, Patient.company_id == company_id)
        .first()
    )
    if not p:
        raise HTTPException(status_code=404, detail="Patient not found")
    return p


def _get_encounter_scoped(db: Session, encounter_id: UUID, company_id: UUID) -> Encounter:
    e = (
        db.query(Encounter)
        .filter(Encounter.id == encounter_id, Encounter.company_id == company_id)
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Encounter not found")
    return e


def _encounter_is_completed(enc: Encounter) -> bool:
    return enc.status == "completed"


def _assert_encounter_not_completed(enc: Encounter) -> None:
    if _encounter_is_completed(enc):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encounter already completed",
        )


def _allowed_status_transition(old: str, new: str) -> bool:
    if old == new:
        return True
    if old == "completed":
        return False
    try:
        i = _ENCOUNTER_STATUS_ORDER.index(old)
        j = _ENCOUNTER_STATUS_ORDER.index(new)
    except ValueError:
        return False
    return j == i + 1


def _validate_order_items_company(
    db: Session, company_id: UUID, items: List[ClinicOrderItemCreate]
) -> None:
    for line in items:
        if line.reference_type != "item":
            continue
        it = (
            db.query(Item)
            .filter(Item.id == line.reference_id, Item.company_id == company_id)
            .first()
        )
        if not it:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid inventory item reference in order",
            )


def _clean_text(v: Optional[str]) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _normalize_departments(raw: Optional[List[str]], fallback: Optional[str] = None) -> List[str]:
    vals = []
    if isinstance(raw, list):
        vals.extend(raw)
    if fallback:
        vals.extend(str(fallback).split(","))
    out = []
    seen = set()
    for d in vals:
        s = str(d or "").strip().lower()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _service_dept_prefix(dept: Optional[str]) -> str:
    d = str(dept or "").strip().lower()
    mapping = {
        "triage": "TRI",
        "consultation": "CON",
        "lab": "LAB",
        "radiology": "RAD",
        "procedure": "PRC",
        "dental": "DEN",
        "pharmacy": "PHR",
    }
    return mapping.get(d, "GEN")


def _service_name_code_fragment(name: str) -> str:
    words = [w for w in re.split(r"[^A-Za-z0-9]+", str(name or "").upper()) if w]
    if not words:
        return "SRV"
    if len(words) == 1:
        return words[0][:4]
    frag = "".join(w[0] for w in words[:4])
    return frag[:4] or "SRV"


def _generate_service_code(db: Session, company_id: UUID, name: str, departments: List[str]) -> str:
    primary = departments[0] if departments else None
    prefix = _service_dept_prefix(primary)
    frag = _service_name_code_fragment(name)
    base = f"{prefix}-{frag}"
    existing = (
        db.query(ClinicalService.code)
        .filter(ClinicalService.company_id == company_id, ClinicalService.code.ilike(f"{base}-%"))
        .all()
    )
    nums = []
    for row in existing:
        code = str(row[0] or "")
        m = re.match(rf"^{re.escape(base)}-(\d+)$", code, flags=re.IGNORECASE)
        if m:
            nums.append(int(m.group(1)))
    nxt = (max(nums) + 1) if nums else 1
    return f"{base}-{nxt:03d}"


def _service_billing_item_sku(service_id: UUID) -> str:
    return f"__CLINIC_SERVICE__{service_id}__"


def _get_or_create_service_billing_item(db: Session, service: ClinicalService) -> Item:
    if service.billing_item_id:
        existing = db.query(Item).filter(Item.id == service.billing_item_id).first()
        if existing:
            return existing
    sku = _service_billing_item_sku(service.id)
    existing = (
        db.query(Item)
        .filter(Item.company_id == service.company_id, Item.sku == sku)
        .first()
    )
    if existing:
        service.billing_item_id = existing.id
        db.add(service)
        db.flush()
        return existing
    fee_item = Item(
        company_id=service.company_id,
        name=service.name,
        description=service.description or "Clinical service charge",
        sku=sku,
        category="Clinic",
        product_category="SERVICE",
        pricing_tier="SERVICE",
        base_unit="service",
        retail_unit="service",
        wholesale_unit="service",
        supplier_unit="service",
        pack_size=1,
        wholesale_units_per_supplier=Decimal("1"),
        can_break_bulk=False,
        vat_category="ZERO_RATED",
        vat_rate=Decimal("0"),
        is_active=True,
        setup_complete=True,
        track_expiry=False,
    )
    db.add(fee_item)
    db.flush()
    service.billing_item_id = fee_item.id
    db.add(service)
    db.flush()
    return fee_item


def _apply_service_charge_line(
    db: Session,
    *,
    invoice_id: UUID,
    service: ClinicalService,
    quantity: Decimal,
) -> Decimal:
    if quantity <= 0:
        return Decimal("0")
    unit_price = Decimal(str(service.fee or 0))
    billed_amount = unit_price * quantity
    if billed_amount <= 0:
        return Decimal("0")
    fee_item = _get_or_create_service_billing_item(db, service)
    line = SalesInvoiceItem(
        sales_invoice_id=invoice_id,
        item_id=fee_item.id,
        batch_id=None,
        unit_name=fee_item.retail_unit or "service",
        quantity=quantity,
        unit_price_exclusive=unit_price,
        discount_percent=Decimal("0"),
        discount_amount=Decimal("0"),
        vat_rate=Decimal("0"),
        vat_amount=Decimal("0"),
        line_total_exclusive=billed_amount,
        line_total_inclusive=billed_amount,
        unit_cost_used=None,
        item_name=fee_item.name,
        item_code=fee_item.sku or "",
    )
    db.add(line)
    return billed_amount


def _recompute_invoice_totals(db: Session, invoice_id: UUID) -> None:
    lines = db.query(SalesInvoiceItem).filter(SalesInvoiceItem.sales_invoice_id == invoice_id).all()
    invoice = (
        db.query(SalesInvoice)
        .filter(SalesInvoice.id == invoice_id)
        .with_for_update()
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    total_excl = sum(Decimal(str(l.line_total_exclusive or 0)) for l in lines)
    total_inc = sum(Decimal(str(l.line_total_inclusive or 0)) for l in lines)
    total_vat = sum(Decimal(str(l.vat_amount or 0)) for l in lines)
    invoice.total_exclusive = total_excl
    invoice.total_inclusive = total_inc
    invoice.vat_amount = total_vat
    invoice.vat_rate = (total_vat / total_excl * Decimal("100")) if total_excl > 0 else Decimal("0")
    db.add(invoice)


def _get_department_store_scoped(db: Session, store_id: UUID, company_id: UUID, branch_id: Optional[UUID] = None) -> DepartmentStore:
    q = db.query(DepartmentStore).filter(DepartmentStore.id == store_id, DepartmentStore.company_id == company_id)
    if branch_id is not None:
        q = q.filter(DepartmentStore.branch_id == branch_id)
    s = q.first()
    if not s:
        raise HTTPException(status_code=404, detail="Department store not found")
    return s


def _upsert_department_store_stock(db: Session, store_id: UUID, item_id: UUID, qty_delta_base: Decimal) -> DepartmentStoreStock:
    row = (
        db.query(DepartmentStoreStock)
        .filter(DepartmentStoreStock.store_id == store_id, DepartmentStoreStock.item_id == item_id)
        .with_for_update()
        .first()
    )
    if not row:
        row = DepartmentStoreStock(store_id=store_id, item_id=item_id, quantity_base=Decimal("0"))
        db.add(row)
        db.flush()
    next_qty = Decimal(str(row.quantity_base or 0)) + Decimal(str(qty_delta_base or 0))
    if next_qty < 0:
        raise HTTPException(status_code=400, detail="Insufficient department stock")
    row.quantity_base = next_qty
    db.add(row)
    return row

# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------
@router.post("/patients", response_model=PatientResponse, status_code=status.HTTP_201_CREATED)
def create_patient(
    body: PatientCreate,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    normalized_phone = (body.phone or "").strip() or None
    first = (body.first_name or "").strip()
    last = (body.last_name or "").strip()
    if normalized_phone:
        dup = (
            db.query(Patient)
            .filter(
                Patient.company_id == company_id,
                Patient.phone == normalized_phone,
                Patient.first_name.ilike(first),
                Patient.last_name.ilike(last),
            )
            .first()
        )
        if dup:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Patient already exists with same name and phone",
            )
    p = Patient(
        company_id=company_id,
        first_name=first,
        last_name=last,
        phone=normalized_phone,
        gender=body.gender,
        date_of_birth=body.date_of_birth,
        id_number=(body.id_number or "").strip() or None,
        residence=(body.residence or "").strip() or None,
    )
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.patch("/patients/{patient_id}", response_model=PatientResponse)
def update_patient(
    patient_id: UUID,
    body: PatientUpdate,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    p = _get_patient_scoped(db, patient_id, company_id)

    if body.first_name is not None:
        p.first_name = (body.first_name or "").strip() or p.first_name
    if body.last_name is not None:
        p.last_name = (body.last_name or "").strip() or p.last_name
    if body.phone is not None:
        p.phone = (body.phone or "").strip() or None
    if body.gender is not None:
        p.gender = (body.gender or "").strip() or None
    if body.date_of_birth is not None:
        p.date_of_birth = body.date_of_birth
    if body.id_number is not None:
        p.id_number = (body.id_number or "").strip() or None
    if body.residence is not None:
        p.residence = (body.residence or "").strip() or None

    db.add(p)
    db.commit()
    db.refresh(p)
    return p


@router.get("/patients", response_model=List[PatientResponse])
def list_patients(
    q: Optional[str] = Query(None, description="Search first name, last name, or phone"),
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    query = db.query(Patient).filter(Patient.company_id == company_id)
    if q and str(q).strip():
        term = f"%{str(q).strip()}%"
        query = query.filter(
            or_(
                Patient.first_name.ilike(term),
                Patient.last_name.ilike(term),
                Patient.phone.ilike(term),
            )
        )
    return query.order_by(Patient.created_at.desc()).limit(500).all()


@router.get("/patients/{patient_id}", response_model=PatientResponse)
def get_patient(
    patient_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    return _get_patient_scoped(db, patient_id, company_id)


@router.get("/patients/{patient_id}/chart", response_model=PatientChartResponse)
def get_patient_chart(
    patient_id: UUID,
    exclude_encounter_id: Optional[UUID] = Query(None),
    limit: int = Query(8, ge=1, le=20),
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    _get_patient_scoped(db, patient_id, company_id)

    q = (
        db.query(Encounter)
        .options(joinedload(Encounter.patient))
        .filter(
            Encounter.company_id == company_id,
            Encounter.patient_id == patient_id,
        )
    )
    if exclude_encounter_id is not None:
        q = q.filter(Encounter.id != exclude_encounter_id)
    encounters = q.order_by(Encounter.created_at.desc()).limit(limit).all()
    entries: List[PatientChartEntry] = []
    for enc in encounters:
        triage = (
            db.query(EncounterTriage)
            .filter(
                EncounterTriage.company_id == company_id,
                EncounterTriage.encounter_id == enc.id,
            )
            .first()
        )
        notes = (
            db.query(EncounterNote)
            .filter(EncounterNote.encounter_id == enc.id)
            .order_by(EncounterNote.created_at.desc())
            .limit(10)
            .all()
        )
        orders = (
            db.query(ClinicOrder)
            .filter(ClinicOrder.company_id == company_id, ClinicOrder.encounter_id == enc.id)
            .order_by(ClinicOrder.created_at.desc())
            .all()
        )
        for o in orders:
            o.items = (
                db.query(ClinicOrderItem)
                .filter(ClinicOrderItem.order_id == o.id)
                .all()
            )
        entries.append(
            PatientChartEntry(
                encounter=enc,
                triage=triage,
                notes=notes,
                orders=orders,
                service_executions=(
                    db.query(EncounterServiceExecution)
                    .options(joinedload(EncounterServiceExecution.lines))
                    .filter(
                        EncounterServiceExecution.company_id == company_id,
                        EncounterServiceExecution.encounter_id == enc.id,
                    )
                    .order_by(EncounterServiceExecution.performed_at.desc())
                    .limit(20)
                    .all()
                ),
            )
        )
    return PatientChartResponse(patient_id=patient_id, entries=entries)


# ---------------------------------------------------------------------------
# Encounters
# ---------------------------------------------------------------------------
@router.post("/encounters", response_model=EncounterResponse, status_code=status.HTTP_201_CREATED)
def create_encounter(
    body: EncounterCreate,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    patient = _get_patient_scoped(db, body.patient_id, company_id)

    branch = db.query(Branch).filter(Branch.id == body.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    require_company_match(branch.company_id, company_id)
    ensure_user_has_branch_access(db, user.id, body.branch_id)

    active = (
        db.query(Encounter)
        .filter(
            Encounter.company_id == company_id,
            Encounter.patient_id == body.patient_id,
            Encounter.status != "completed",
        )
        .first()
    )
    if active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Patient already has an active visit",
        )

    enc = Encounter(
        company_id=company_id,
        branch_id=body.branch_id,
        patient_id=body.patient_id,
        status="waiting",
        scheduled_for=body.scheduled_for,
        initial_destination=body.initial_destination,
        intake_payment_mode=(body.payment_mode or "").strip() or None,
        intake_insurance_scheme=(body.insurance_scheme or "").strip() or None,
        created_by=user.id,
    )
    db.add(enc)
    try:
        db.flush()
        ensure_draft_invoice_for_encounter(
            db,
            encounter_id=enc.id,
            company_id=company_id,
            patient=patient,
            user_id=user.id,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        err = str(getattr(exc.orig, "diag", None) or exc.orig or exc)
        if "uq_encounters_active_patient_company" in err or "23505" in err:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Patient already has an active visit",
            ) from exc
        raise
    db.refresh(enc)
    logger.info(
        "clinic encounter_created encounter_id=%s patient_id=%s company_id=%s",
        enc.id,
        body.patient_id,
        company_id,
    )
    return enc


@router.get("/encounters", response_model=List[EncounterResponse])
def list_encounters(
    status_filter: Optional[str] = Query(None, alias="status"),
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    q = (
        db.query(Encounter)
        .options(joinedload(Encounter.patient))
        .filter(Encounter.company_id == company_id)
    )
    if status_filter:
        q = q.filter(Encounter.status == status_filter)
    return q.order_by(Encounter.created_at.desc()).limit(500).all()


@router.get("/encounters/{encounter_id}", response_model=EncounterResponse)
def get_encounter(
    encounter_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    e = (
        db.query(Encounter)
        .options(joinedload(Encounter.patient))
        .filter(Encounter.id == encounter_id, Encounter.company_id == company_id)
        .first()
    )
    if not e:
        raise HTTPException(status_code=404, detail="Encounter not found")
    return e


# ---------------------------------------------------------------------------
# Triage
# ---------------------------------------------------------------------------
@router.get("/encounters/{encounter_id}/triage", response_model=Optional[EncounterTriageResponse])
def get_encounter_triage(
    encounter_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    enc = _get_encounter_scoped(db, encounter_id, company_id)
    t = (
        db.query(EncounterTriage)
        .filter(EncounterTriage.encounter_id == enc.id, EncounterTriage.company_id == company_id)
        .first()
    )
    return t


@router.put("/encounters/{encounter_id}/triage", response_model=EncounterTriageResponse)
def upsert_encounter_triage(
    encounter_id: UUID,
    body: EncounterTriageUpsert,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    enc = (
        db.query(Encounter)
        .filter(Encounter.id == encounter_id, Encounter.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not enc:
        raise HTTPException(status_code=404, detail="Encounter not found")
    _assert_encounter_not_completed(enc)

    existing = (
        db.query(EncounterTriage)
        .filter(EncounterTriage.encounter_id == enc.id, EncounterTriage.company_id == company_id)
        .with_for_update()
        .first()
    )
    if existing is None:
        existing = EncounterTriage(
            encounter_id=enc.id,
            company_id=company_id,
            branch_id=enc.branch_id,
            patient_id=enc.patient_id,
            created_by=user.id,
        )

    def _clean(v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        s = str(v).strip()
        return s or None

    # Insurance/payment source of truth is reception intake on encounter.
    # Keep triage view as read-only context and do not allow triage edits.
    existing.payment_mode = _clean(enc.intake_payment_mode)
    existing.insurance_scheme = _clean(enc.intake_insurance_scheme)
    existing.chief_complaint = _clean(body.chief_complaint)
    existing.allergies = _clean(body.allergies)
    existing.symptoms = _clean(body.symptoms)
    existing.triage_notes = _clean(body.triage_notes)
    existing.vitals = body.vitals or None

    db.add(existing)
    db.commit()
    db.refresh(existing)
    return existing


@router.patch("/encounters/{encounter_id}/status", response_model=EncounterResponse)
def patch_encounter_status(
    encounter_id: UUID,
    body: EncounterStatusUpdate,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    enc = (
        db.query(Encounter)
        .filter(Encounter.id == encounter_id, Encounter.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not enc:
        raise HTTPException(status_code=404, detail="Encounter not found")

    if enc.status == "completed" and body.status != enc.status:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Encounter already completed",
        )

    if not _allowed_status_transition(enc.status, body.status):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid encounter status transition",
        )

    old_status = enc.status
    if body.status != enc.status:
        enc.status = body.status
        if body.status == "completed" and enc.closed_at is None:
            enc.closed_at = datetime.now(timezone.utc)
        db.add(enc)
        db.commit()
        logger.info(
            "clinic encounter_status encounter_id=%s from_status=%s to_status=%s",
            enc.id,
            old_status,
            body.status,
        )
    else:
        db.commit()
    db.refresh(enc)
    return enc


# ---------------------------------------------------------------------------
# Notes
# ---------------------------------------------------------------------------
@router.post(
    "/encounters/{encounter_id}/notes",
    response_model=EncounterNoteResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_encounter_note(
    encounter_id: UUID,
    body: EncounterNoteCreate,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    enc = _get_encounter_scoped(db, encounter_id, company_id)
    _assert_encounter_not_completed(enc)
    notes_val = (body.notes or "").strip() or None
    dx_val = (body.diagnosis or "").strip() or None
    note = EncounterNote(
        encounter_id=enc.id,
        notes=notes_val,
        diagnosis=dx_val,
        created_by=user.id,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.get("/encounters/{encounter_id}/notes", response_model=List[EncounterNoteResponse])
def list_encounter_notes(
    encounter_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    enc = _get_encounter_scoped(db, encounter_id, company_id)
    return (
        db.query(EncounterNote)
        .filter(EncounterNote.encounter_id == enc.id)
        .order_by(EncounterNote.created_at.desc())
        .all()
    )


# ---------------------------------------------------------------------------
# Clinic orders
# ---------------------------------------------------------------------------
@router.post(
    "/encounters/{encounter_id}/orders",
    response_model=ClinicOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_clinic_order(
    encounter_id: UUID,
    body: ClinicOrderCreate,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    enc = (
        db.query(Encounter)
        .filter(Encounter.id == encounter_id, Encounter.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not enc:
        raise HTTPException(status_code=404, detail="Encounter not found")
    _assert_encounter_not_completed(enc)

    _validate_order_items_company(db, company_id, body.items)

    order = ClinicOrder(
        company_id=company_id,
        encounter_id=enc.id,
        order_type=body.order_type,
        status="requested",
    )
    db.add(order)
    db.flush()
    for line in body.items:
        db.add(
            ClinicOrderItem(
                order_id=order.id,
                reference_type=line.reference_type,
                reference_id=line.reference_id,
                quantity=line.quantity,
                notes=(line.notes or "").strip() or None,
            )
        )
    db.commit()
    db.refresh(order)
    items = (
        db.query(ClinicOrderItem)
        .filter(ClinicOrderItem.order_id == order.id)
        .all()
    )
    logger.info(
        "clinic order_created order_id=%s encounter_id=%s order_type=%s item_count=%s",
        order.id,
        enc.id,
        body.order_type,
        len(body.items),
    )
    return ClinicOrderResponse(
        id=order.id,
        company_id=order.company_id,
        encounter_id=order.encounter_id,
        order_type=order.order_type,
        status=order.status,
        created_at=order.created_at,
        items=[ClinicOrderItemResponse.model_validate(i) for i in items],
    )


@router.get("/encounters/{encounter_id}/orders", response_model=List[ClinicOrderResponse])
def list_clinic_orders(
    encounter_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    enc = _get_encounter_scoped(db, encounter_id, company_id)
    orders = (
        db.query(ClinicOrder)
        .filter(
            ClinicOrder.encounter_id == enc.id,
            ClinicOrder.company_id == company_id,
        )
        .order_by(ClinicOrder.created_at.desc())
        .all()
    )
    out: List[ClinicOrderResponse] = []
    for o in orders:
        items = (
            db.query(ClinicOrderItem)
            .filter(ClinicOrderItem.order_id == o.id)
            .all()
        )
        out.append(
            ClinicOrderResponse(
                id=o.id,
                company_id=o.company_id,
                encounter_id=o.encounter_id,
                order_type=o.order_type,
                status=o.status,
                created_at=o.created_at,
                items=[ClinicOrderItemResponse.model_validate(i) for i in items],
            )
        )
    return out


# ---------------------------------------------------------------------------
# Shared services catalog (company-level, cross-branch)
# ---------------------------------------------------------------------------
@router.get("/services", response_model=List[ClinicalServiceResponse])
def list_clinical_services(
    q: Optional[str] = Query(None, description="Search service name/code"),
    department: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    query = (
        db.query(ClinicalService)
        .options(joinedload(ClinicalService.components))
        .filter(ClinicalService.company_id == company_id)
    )
    if not include_inactive:
        query = query.filter(ClinicalService.is_active.is_(True))
    if department and department.strip():
        query = query.filter(ClinicalService.department.ilike(department.strip()))
    if q and q.strip():
        term = f"%{q.strip()}%"
        query = query.filter(or_(ClinicalService.name.ilike(term), ClinicalService.code.ilike(term)))
    return query.order_by(ClinicalService.name.asc()).all()


@router.post("/services", response_model=ClinicalServiceResponse, status_code=status.HTTP_201_CREATED)
def create_clinical_service(
    body: ClinicalServiceCreate,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    allowed_departments = _normalize_departments(body.allowed_departments, body.department)
    service_code = _clean_text(body.code)
    if not service_code:
        service_code = _generate_service_code(db, company_id, body.name, allowed_departments)
    svc = ClinicalService(
        company_id=company_id,
        name=(body.name or "").strip(),
        code=service_code,
        department=allowed_departments[0] if allowed_departments else _clean_text(body.department),
        allowed_departments=allowed_departments,
        strict_department_only=bool(body.strict_department_only),
        description=_clean_text(body.description),
        fee=body.fee,
        is_active=body.is_active,
        created_by=user.id,
    )
    db.add(svc)
    db.flush()
    _get_or_create_service_billing_item(db, svc)
    for idx, c in enumerate(body.components):
        db.add(
            ClinicalServiceComponent(
                service_id=svc.id,
                item_id=c.item_id,
                item_unit_name=_clean_text(c.item_unit_name),
                quantity_per_service=c.quantity_per_service,
                is_optional=bool(c.is_optional),
                deduction_policy=c.deduction_policy,
                accumulator_threshold_qty=c.accumulator_threshold_qty if c.deduction_policy == "accumulator" else None,
                sort_order=c.sort_order if c.sort_order is not None else idx,
                notes=_clean_text(c.notes),
            )
        )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Service with same name/code already exists for this company")
    db.refresh(svc)
    return (
        db.query(ClinicalService)
        .options(joinedload(ClinicalService.components))
        .filter(ClinicalService.id == svc.id, ClinicalService.company_id == company_id)
        .first()
    )


@router.put("/services/{service_id}", response_model=ClinicalServiceResponse)
def update_clinical_service(
    service_id: UUID,
    body: ClinicalServiceUpdate,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    svc = (
        db.query(ClinicalService)
        .options(joinedload(ClinicalService.components))
        .filter(ClinicalService.id == service_id, ClinicalService.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found")
    if body.name is not None:
        svc.name = (body.name or "").strip()
    if body.code is not None:
        next_code = _clean_text(body.code)
        if next_code:
            svc.code = next_code
        else:
            depts = _normalize_departments(body.allowed_departments, body.department if body.department is not None else svc.department)
            svc.code = _generate_service_code(db, company_id, svc.name, depts)
    if body.department is not None:
        svc.department = _clean_text(body.department)
    if body.allowed_departments is not None or body.department is not None:
        depts = _normalize_departments(body.allowed_departments if body.allowed_departments is not None else (svc.allowed_departments or []), svc.department)
        svc.allowed_departments = depts
        svc.department = depts[0] if depts else svc.department
    if body.strict_department_only is not None:
        svc.strict_department_only = bool(body.strict_department_only)
    if body.description is not None:
        svc.description = _clean_text(body.description)
    if body.fee is not None:
        if body.fee < 0:
            raise HTTPException(status_code=400, detail="Service fee must be >= 0")
        svc.fee = body.fee
    if body.is_active is not None:
        svc.is_active = bool(body.is_active)
    _get_or_create_service_billing_item(db, svc)
    if body.components is not None:
        for old in list(svc.components or []):
            db.delete(old)
        db.flush()
        for idx, c in enumerate(body.components):
            db.add(
                ClinicalServiceComponent(
                    service_id=svc.id,
                    item_id=c.item_id,
                    item_unit_name=_clean_text(c.item_unit_name),
                    quantity_per_service=c.quantity_per_service,
                    is_optional=bool(c.is_optional),
                    deduction_policy=c.deduction_policy,
                    accumulator_threshold_qty=c.accumulator_threshold_qty if c.deduction_policy == "accumulator" else None,
                    sort_order=c.sort_order if c.sort_order is not None else idx,
                    notes=_clean_text(c.notes),
                )
            )
    db.add(svc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Service with same name/code already exists for this company")
    return (
        db.query(ClinicalService)
        .options(joinedload(ClinicalService.components))
        .filter(ClinicalService.id == service_id, ClinicalService.company_id == company_id)
        .first()
    )


@router.delete("/services/{service_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_clinical_service(
    service_id: UUID,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    svc = (
        db.query(ClinicalService)
        .filter(ClinicalService.id == service_id, ClinicalService.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not svc:
        return None
    db.delete(svc)
    db.commit()
    return None


@router.get("/department-stores", response_model=List[DepartmentStoreResponse])
def list_department_stores(
    branch_id: Optional[UUID] = Query(None),
    include_inactive: bool = Query(False),
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    q = db.query(DepartmentStore).filter(DepartmentStore.company_id == company_id)
    if branch_id is not None:
        q = q.filter(DepartmentStore.branch_id == branch_id)
    if not include_inactive:
        q = q.filter(DepartmentStore.is_active.is_(True))
    return q.order_by(DepartmentStore.branch_id.asc(), DepartmentStore.code.asc()).all()


@router.post("/department-stores", response_model=DepartmentStoreResponse, status_code=status.HTTP_201_CREATED)
def create_department_store(
    body: DepartmentStoreCreate,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    branch = db.query(Branch).filter(Branch.id == body.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    require_company_match(branch.company_id, company_id)
    ensure_user_has_branch_access(db, user.id, body.branch_id)
    row = DepartmentStore(
        company_id=company_id,
        branch_id=body.branch_id,
        code=(body.code or "").strip().upper(),
        name=(body.name or "").strip(),
        is_active=bool(body.is_active),
        created_by=user.id,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="Department store code already exists for this branch")
    db.refresh(row)
    return row


@router.post(
    "/department-stores/seed-defaults",
    response_model=DepartmentStoreSeedDefaultsResponse,
    status_code=status.HTTP_200_OK,
)
def seed_default_department_stores(
    body: DepartmentStoreSeedDefaultsRequest,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """Create standard department mini-stores for a branch when missing (same codes are skipped)."""
    user, _ = auth
    company_id = _company_id(db, user)
    branch = db.query(Branch).filter(Branch.id == body.branch_id).first()
    if not branch:
        raise HTTPException(status_code=404, detail="Branch not found")
    require_company_match(branch.company_id, company_id)
    ensure_user_has_branch_access(db, user.id, body.branch_id)

    existing = (
        db.query(DepartmentStore)
        .filter(DepartmentStore.company_id == company_id, DepartmentStore.branch_id == body.branch_id)
        .all()
    )
    existing_codes = {(r.code or "").strip().upper() for r in existing if r.code}

    created_models: List[DepartmentStore] = []
    skipped: List[str] = []
    for code, name in _DEFAULT_DEPARTMENT_STORE_TEMPLATES:
        uc = (code or "").strip().upper()
        if not uc:
            continue
        if uc in existing_codes:
            skipped.append(uc)
            continue
        row = DepartmentStore(
            company_id=company_id,
            branch_id=body.branch_id,
            code=uc,
            name=(name or "").strip() or uc,
            is_active=True,
            created_by=user.id,
        )
        db.add(row)
        created_models.append(row)
        existing_codes.add(uc)

    if created_models:
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(status_code=409, detail="Could not create defaults (duplicate code). Refresh and try again.")
        for r in created_models:
            db.refresh(r)

    return DepartmentStoreSeedDefaultsResponse(
        created=[DepartmentStoreResponse.model_validate(r) for r in created_models],
        skipped_codes=skipped,
    )


@router.post("/department-stores/{store_id}/issue", status_code=status.HTTP_200_OK)
def issue_stock_to_department_store(
    store_id: UUID,
    body: DepartmentStoreIssueRequest,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    store = _get_department_store_scoped(db, store_id, company_id)
    ensure_user_has_branch_access(db, user.id, store.branch_id)
    out_ledger: List[InventoryLedger] = []
    issued_item_ids: List[UUID] = []
    for line in body.lines:
        item = db.query(Item).filter(Item.id == line.item_id, Item.company_id == company_id).first()
        if not item:
            raise HTTPException(status_code=400, detail="Invalid item in issue request")
        unit_name = _clean_text(line.unit_name) or item.retail_unit or item.base_unit or "piece"
        qty_base = Decimal(str(InventoryService.convert_to_base_units(db, line.item_id, float(line.quantity), unit_name)))
        if qty_base <= 0:
            raise HTTPException(status_code=400, detail="Issue quantity must be > 0")
        is_available, available_base, required_base = InventoryService.check_stock_availability(
            db, line.item_id, store.branch_id, float(line.quantity), unit_name
        )
        if not is_available:
            try:
                OrderBookService.check_and_add_to_order_book(
                    db=db,
                    company_id=company_id,
                    branch_id=store.branch_id,
                    item_id=line.item_id,
                    user_id=user.id,
                    is_auto=False,
                )
            except Exception:
                pass
            raise HTTPException(
                status_code=400,
                detail=f"Pharmacy stock insufficient for issue. Required {required_base}, available {available_base}. Item flagged to order book.",
            )
        allocations = InventoryService.allocate_stock_fefo_with_lock(
            db, item_id=line.item_id, branch_id=store.branch_id, quantity_needed_base=float(qty_base), exclude_expired=True
        )
        for alloc in allocations:
            qd = Decimal(str(alloc["quantity"]))
            uc = Decimal(str(alloc["unit_cost"]))
            out_ledger.append(
                InventoryLedger(
                    company_id=company_id,
                    branch_id=store.branch_id,
                    item_id=line.item_id,
                    batch_number=alloc["batch_number"],
                    expiry_date=alloc["expiry_date"],
                    transaction_type="DEPARTMENT_ISSUE",
                    reference_type="department_store",
                    reference_id=store.id,
                    quantity_delta=-qd,
                    unit_cost=uc,
                    total_cost=uc * qd,
                    created_by=user.id,
                    notes=f"Issue to {store.code}: {line.notes or ''}".strip(),
                )
            )
        _upsert_department_store_stock(db, store.id, line.item_id, qty_base)
        issued_item_ids.append(line.item_id)
        db.add(
            DepartmentStoreMovement(
                company_id=company_id,
                branch_id=store.branch_id,
                store_id=store.id,
                item_id=line.item_id,
                movement_type="ISSUE_IN",
                quantity_delta_base=qty_base,
                reference_type="department_issue",
                reference_id=store.id,
                notes=_clean_text(line.notes),
                created_by=user.id,
            )
        )
    for led in out_ledger:
        db.add(led)
    db.flush()
    for led in out_ledger:
        SnapshotService.upsert_inventory_balance(db, led.company_id, led.branch_id, led.item_id, led.quantity_delta, document_number=led.document_number)
    db.commit()
    # After issue, run low-stock trigger similar to sales.
    for item_id in set(issued_item_ids):
        try:
            OrderBookService.check_and_add_to_order_book(
                db=db,
                company_id=company_id,
                branch_id=store.branch_id,
                item_id=item_id,
                user_id=user.id,
                is_auto=True,
            )
        except Exception:
            logger.exception("Order-book check failed after department issue item_id=%s", item_id)
    return {"status": "ok", "issued_lines": len(body.lines)}


@router.post("/department-stores/{store_id}/reconcile", status_code=status.HTTP_200_OK)
def reconcile_department_store_stock(
    store_id: UUID,
    body: DepartmentStoreReconcileRequest,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    store = _get_department_store_scoped(db, store_id, company_id)
    ensure_user_has_branch_access(db, user.id, store.branch_id)
    for line in body.lines:
        item = db.query(Item).filter(Item.id == line.item_id, Item.company_id == company_id).first()
        if not item:
            raise HTTPException(status_code=400, detail="Invalid item in reconciliation request")
        unit_name = _clean_text(line.unit_name) or item.retail_unit or item.base_unit or "piece"
        delta_base = Decimal(str(InventoryService.convert_to_base_units(db, line.item_id, float(abs(line.quantity_delta)), unit_name)))
        if line.quantity_delta < 0:
            delta_base = -delta_base
        _upsert_department_store_stock(db, store.id, line.item_id, delta_base)
        db.add(
            DepartmentStoreMovement(
                company_id=company_id,
                branch_id=store.branch_id,
                store_id=store.id,
                item_id=line.item_id,
                movement_type="RECONCILE",
                quantity_delta_base=delta_base,
                reference_type="department_reconcile",
                reference_id=store.id,
                notes=_clean_text(line.reason),
                created_by=user.id,
            )
        )
    db.commit()
    return {"status": "ok", "reconciled_lines": len(body.lines)}


@router.post("/department-stores/{store_id}/return", status_code=status.HTTP_200_OK)
def return_stock_from_department_store(
    store_id: UUID,
    body: DepartmentStoreReturnRequest,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    store = _get_department_store_scoped(db, store_id, company_id)
    ensure_user_has_branch_access(db, user.id, store.branch_id)
    in_ledger: List[InventoryLedger] = []
    item_ids: List[UUID] = []
    for line in body.lines:
        item = db.query(Item).filter(Item.id == line.item_id, Item.company_id == company_id).first()
        if not item:
            raise HTTPException(status_code=400, detail="Invalid item in return request")
        unit_name = _clean_text(line.unit_name) or item.retail_unit or item.base_unit or "piece"
        qty_base = Decimal(str(InventoryService.convert_to_base_units(db, line.item_id, float(line.quantity), unit_name)))
        if qty_base <= 0:
            raise HTTPException(status_code=400, detail="Return quantity must be > 0")
        _upsert_department_store_stock(db, store.id, line.item_id, -qty_base)
        # Return adds stock back to pharmacy branch ledger. Cost defaults to best available.
        unit_cost = Decimal(
            str(
                CanonicalPricingService.get_best_available_cost(
                    db=db,
                    item_id=line.item_id,
                    branch_id=store.branch_id,
                    company_id=company_id,
                )
                or 0
            )
        )
        in_ledger.append(
            InventoryLedger(
                company_id=company_id,
                branch_id=store.branch_id,
                item_id=line.item_id,
                batch_number=None,
                expiry_date=None,
                transaction_type="DEPARTMENT_RETURN",
                reference_type="department_store",
                reference_id=store.id,
                quantity_delta=qty_base,
                unit_cost=unit_cost,
                total_cost=unit_cost * qty_base,
                created_by=user.id,
                notes=f"Return from {store.code}: {line.reason or ''}".strip(),
            )
        )
        db.add(
            DepartmentStoreMovement(
                company_id=company_id,
                branch_id=store.branch_id,
                store_id=store.id,
                item_id=line.item_id,
                movement_type="RETURN_TO_PHARMACY",
                quantity_delta_base=-qty_base,
                reference_type="department_return",
                reference_id=store.id,
                notes=_clean_text(line.reason),
                created_by=user.id,
            )
        )
        item_ids.append(line.item_id)
    for led in in_ledger:
        db.add(led)
    db.flush()
    for led in in_ledger:
        SnapshotService.upsert_inventory_balance(db, led.company_id, led.branch_id, led.item_id, led.quantity_delta, document_number=led.document_number)
    try:
        OrderBookService.mark_items_received(
            db=db,
            company_id=company_id,
            branch_id=store.branch_id,
            item_ids=list(set(item_ids)),
        )
    except Exception:
        logger.exception("mark_items_received failed after department return")
    db.commit()
    return {"status": "ok", "returned_lines": len(body.lines)}


@router.post("/encounters/{encounter_id}/services/execute", response_model=ServiceExecutionResponse, status_code=status.HTTP_201_CREATED)
def execute_clinical_service(
    encounter_id: UUID,
    body: ServiceExecutionRequest,
    auth: Tuple[User, Session] = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    user, _ = auth
    company_id = _company_id(db, user)
    enc = (
        db.query(Encounter)
        .options(joinedload(Encounter.patient))
        .filter(Encounter.id == encounter_id, Encounter.company_id == company_id)
        .with_for_update()
        .first()
    )
    if not enc:
        raise HTTPException(status_code=404, detail="Encounter not found")
    _assert_encounter_not_completed(enc)
    ensure_user_has_branch_access(db, user.id, enc.branch_id)
    store = None
    if body.department_store_id:
        store = _get_department_store_scoped(db, body.department_store_id, company_id, enc.branch_id)
        if not store.is_active:
            raise HTTPException(status_code=400, detail="Department store is inactive")
    svc = (
        db.query(ClinicalService)
        .options(joinedload(ClinicalService.components))
        .filter(ClinicalService.id == body.service_id, ClinicalService.company_id == company_id, ClinicalService.is_active.is_(True))
        .with_for_update()
        .first()
    )
    if not svc:
        raise HTTPException(status_code=404, detail="Service not found or inactive")
    execution_dept = _clean_text(body.execution_department)
    if svc.strict_department_only:
        allowed = _normalize_departments(list(svc.allowed_departments or []), svc.department)
        if execution_dept and allowed and execution_dept.lower() not in allowed:
            raise HTTPException(status_code=400, detail="Service is restricted to configured department(s)")
    qty_multiplier = Decimal(str(body.quantity))
    invoice = ensure_draft_invoice_for_encounter(
        db,
        encounter_id=enc.id,
        company_id=company_id,
        patient=enc.patient,
        user_id=user.id,
    )
    billed_amount = _apply_service_charge_line(db, invoice_id=invoice.id, service=svc, quantity=qty_multiplier)
    execution = EncounterServiceExecution(
        company_id=company_id,
        branch_id=enc.branch_id,
        encounter_id=enc.id,
        service_id=svc.id,
        quantity=qty_multiplier,
        billed_amount=billed_amount,
        notes=_clean_text(body.notes),
        performed_by=user.id,
    )
    db.add(execution)
    db.flush()

    overrides = {str(c.service_component_id): c for c in (body.components or [])}
    ledger_entries: List[InventoryLedger] = []
    for c in sorted(list(svc.components or []), key=lambda x: (x.sort_order or 0, str(x.id))):
        override = overrides.get(str(c.id))
        selected_default = False if c.is_optional else True
        selected = override.selected if override is not None else selected_default
        requested_qty = (override.quantity_override if (override and override.quantity_override is not None) else c.quantity_per_service * qty_multiplier)
        item = db.query(Item).filter(Item.id == c.item_id, Item.company_id == company_id).first()
        if not item:
            raise HTTPException(status_code=400, detail="Service component references invalid item")
        unit_name = _clean_text(c.item_unit_name) or item.retail_unit or item.base_unit or "piece"
        requested_base = Decimal(str(InventoryService.convert_to_base_units(db, c.item_id, float(requested_qty), unit_name))) if selected else Decimal("0")
        deducted_base = Decimal("0")
        deducted_qty_unit = Decimal("0")
        accumulator_before = None
        accumulator_after = None

        if selected and requested_base > 0:
            if c.deduction_policy == "immediate":
                deducted_base = requested_base
            else:
                threshold_raw = c.accumulator_threshold_qty
                if threshold_raw is None or Decimal(str(threshold_raw)) <= 0:
                    raise HTTPException(status_code=400, detail="Accumulator policy requires threshold")
                threshold_base = Decimal(str(InventoryService.convert_to_base_units(db, c.item_id, float(threshold_raw), unit_name)))
                acc = (
                    db.query(ClinicalServiceAccumulator)
                    .filter(
                        ClinicalServiceAccumulator.company_id == company_id,
                        ClinicalServiceAccumulator.branch_id == enc.branch_id,
                        ClinicalServiceAccumulator.service_component_id == c.id,
                    )
                    .with_for_update()
                    .first()
                )
                if not acc:
                    acc = ClinicalServiceAccumulator(
                        company_id=company_id,
                        branch_id=enc.branch_id,
                        service_component_id=c.id,
                        accumulated_qty_base=Decimal("0"),
                    )
                    db.add(acc)
                    db.flush()
                accumulator_before = Decimal(str(acc.accumulated_qty_base or 0))
                total_base = accumulator_before + requested_base
                cycles = int(total_base / threshold_base) if threshold_base > 0 else 0
                deducted_base = threshold_base * cycles
                accumulator_after = total_base - deducted_base
                acc.accumulated_qty_base = accumulator_after
                if deducted_base > 0:
                    acc.last_deducted_at = datetime.now(timezone.utc)
                db.add(acc)

            if deducted_base > 0:
                if store is None:
                    raise HTTPException(status_code=400, detail="Department store is required to consume stocked components")
                _upsert_department_store_stock(db, store.id, c.item_id, -deducted_base)
                db.add(
                    DepartmentStoreMovement(
                        company_id=company_id,
                        branch_id=enc.branch_id,
                        store_id=store.id,
                        item_id=c.item_id,
                        movement_type="CONSUME_OUT",
                        quantity_delta_base=-deducted_base,
                        reference_type="encounter_service_execution",
                        reference_id=execution.id,
                        notes=f"Service consume: {svc.name}",
                        created_by=user.id,
                    )
                )
                # Consumption is deducted from department store stock.
                # Branch pharmacy inventory is deducted at ISSUE_IN time.
            if requested_base > 0:
                unit_to_base_ratio = requested_base / requested_qty
                if unit_to_base_ratio > 0:
                    deducted_qty_unit = deducted_base / unit_to_base_ratio

        line = EncounterServiceExecutionLine(
            execution_id=execution.id,
            service_component_id=c.id,
            item_id=c.item_id,
            policy=c.deduction_policy,
            selected=selected,
            requested_qty=requested_qty if selected else Decimal("0"),
            deducted_qty=deducted_qty_unit,
            item_unit_name=unit_name,
            requested_qty_base=requested_base if selected else Decimal("0"),
            deducted_qty_base=deducted_base,
            accumulator_before_base=accumulator_before,
            accumulator_after_base=accumulator_after,
        )
        db.add(line)

    for led in ledger_entries:
        db.add(led)
    db.flush()
    for led in ledger_entries:
        SnapshotService.upsert_inventory_balance(
            db, led.company_id, led.branch_id, led.item_id, led.quantity_delta, document_number=led.document_number
        )
    _recompute_invoice_totals(db, invoice.id)
    db.commit()
    return (
        db.query(EncounterServiceExecution)
        .options(joinedload(EncounterServiceExecution.lines))
        .filter(EncounterServiceExecution.id == execution.id)
        .first()
    )
