"""
OPD / Clinic API (patients, encounters, notes, clinic orders).

All routes gated by require_module("clinic"). All data scoped by company_id.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import List, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.dependencies import (
    get_current_user,
    get_effective_company_id_for_user,
    get_tenant_db,
    require_company_match,
    ensure_user_has_branch_access,
)
from app.module_enforcement import require_module
from app.models import Branch, Item, User
from app.models.clinic import (
    Patient,
    Encounter,
    EncounterNote,
    ClinicOrder,
    ClinicOrderItem,
)
from app.schemas.clinic import (
    PatientCreate,
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
)
from app.services.clinic_billing_service import ensure_draft_invoice_for_encounter

logger = logging.getLogger(__name__)

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
    p = Patient(
        company_id=company_id,
        first_name=body.first_name,
        last_name=body.last_name,
        phone=body.phone,
        gender=body.gender,
        date_of_birth=body.date_of_birth,
    )
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
    q = db.query(Encounter).filter(Encounter.company_id == company_id)
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
    return _get_encounter_scoped(db, encounter_id, company_id)


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
