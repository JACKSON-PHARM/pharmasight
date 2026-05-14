"""
Temporary eTIMS OSDC forensic HTTP API (payload parity vs gavaetims).

Mounted at ``/etims`` so routes are ``POST /etims/debug/...``.

Gated by ``settings.DEBUG`` or ``ETIMS_DEBUG_API_ENABLED=true``.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.users import _user_has_owner_or_admin_role
from app.api.platform_admin import require_platform_super_admin
from app.config import settings
from app.dependencies import (
    get_tenant_db,
    ensure_user_has_branch_access,
    require_document_belongs_to_user_company,
)
from app.module_enforcement import require_module
from app.models.company import BranchEtimsCredentials, Company
from app.services.etims.constants import SAVE_TRNS_SALES_OSDC_PATH
from app.services.etims.etims_invoice_submitter import assert_invoice_eligible_for_etims_submit
from app.services.etims.etims_osdc_forensic import (
    build_pharmasight_osdc_sale_attempt_bundle,
    load_invoice_for_osdc,
    post_save_trns_sales_osdc_raw_body,
    post_save_trns_sales_osdc_via_prepared,
    prepare_save_trns_sales_osdc_post,
    prepared_wire_view,
    serialize_creds_public,
)
from app.services.etims.stock_identity_report import build_stock_identity_report

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/debug", tags=["ETIMS Debug"])


def _etims_debug_allowed() -> bool:
    return bool(getattr(settings, "DEBUG", False) or getattr(settings, "ETIMS_DEBUG_API_ENABLED", False))


def _require_debug_gate() -> None:
    if not _etims_debug_allowed():
        raise HTTPException(status_code=404, detail="ETIMS debug API disabled")


def _require_owner_admin_or_platform(user, db: Session) -> None:
    if _user_has_owner_or_admin_role(db, user.id):
        return
    try:
        require_platform_super_admin((user, db))
    except Exception:
        raise HTTPException(status_code=403, detail="Only owner/admin can use eTIMS debug endpoints.")


class ReplaySaveTrnsSalesOsdcBody(BaseModel):
    """Replay a captured payload through the same HTTP stack as production (branch from ``invoice_id``)."""

    invoice_id: UUID
    payload: Optional[Dict[str, Any]] = Field(
        None,
        description="Exact JSON object for saveTrnsSalesOsdc root (mutually exclusive with body_raw_utf8).",
    )
    body_raw_utf8: Optional[str] = Field(
        None,
        description="Exact UTF-8 JSON string as sent on the wire (no re-serialization). Overrides ``payload``.",
    )
    query_params: Optional[Dict[str, Any]] = Field(None, description="Optional query string, e.g. invcNo.")
    include_select_invoice_type: bool = Field(
        True,
        description="If true, run selectInvoiceType prelude like production before POST.",
    )
    timeout_seconds: int = Field(60, ge=5, le=180)


def _bundle_response_dict(bundle: Dict[str, Any], *, reveal_secrets: bool) -> Dict[str, Any]:
    out: Dict[str, Any] = {k: v for k, v in bundle.items() if k != "prepared_request"}
    if not reveal_secrets and "oauth_token" in out:
        out["oauth_token"] = "***"
    return out


@router.post("/sales-payload/{invoice_id}")
def debug_sales_payload(
    invoice_id: UUID,
    *,
    reveal_secrets: bool = False,
    include_select_invoice_type: bool = True,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    """
    Build the final ``saveTrnsSalesOsdc`` POST (payload, prepared wire body/headers, resolved TIN/bhf/device).

    Set ``reveal_secrets=true`` only on trusted machines — exposes Bearer token and ``cmcKey`` in ``headers_final``.
    """
    _require_debug_gate()
    user, _ = current_user_and_db
    _require_owner_admin_or_platform(user, db)

    invoice = load_invoice_for_osdc(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", None)
    ensure_user_has_branch_access(db, user.id, invoice.branch_id)

    creds = (
        db.query(BranchEtimsCredentials)
        .filter(
            BranchEtimsCredentials.company_id == invoice.company_id,
            BranchEtimsCredentials.branch_id == invoice.branch_id,
        )
        .first()
    )
    if not creds:
        raise HTTPException(status_code=400, detail="Branch eTIMS credentials row missing")

    company = db.query(Company).filter(Company.id == invoice.company_id).first()

    try:
        assert_invoice_eligible_for_etims_submit(invoice)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    bundle = build_pharmasight_osdc_sale_attempt_bundle(
        db,
        invoice,
        creds=creds,
        company=company,
        timeout=60,
        include_select_invoice_type=include_select_invoice_type,
    )
    prep = bundle["prepared_request"]
    wire = prepared_wire_view(prep)
    payload = bundle["payload_final"]
    il0: Optional[Dict[str, Any]] = None
    item_list = payload.get("itemList")
    if isinstance(item_list, list) and item_list and isinstance(item_list[0], dict):
        il0 = dict(item_list[0])

    out = _bundle_response_dict(bundle, reveal_secrets=reveal_secrets)
    out["prepared_wire"] = wire
    out["branch_credentials_public"] = serialize_creds_public(creds)
    out["company_pin_raw"] = getattr(company, "pin", None) if company else None
    out["item_list_first_line_exact"] = il0
    return out


@router.post("/stock-identity-tuple/{invoice_id}")
def debug_stock_identity_tuple(
    invoice_id: UUID,
    *,
    include_osdc_bundle: bool = Query(True),
    timeout_seconds: int = Query(60, ge=5, le=180),
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    """
    Read-only report: (itemCd, taxTyCd, pkgUnitCd, qtyUnitCd, itemClsCd, tin, bhfId) for
    reconstructed insertStockIO, saveStockMaster (N/A fields), and saveTrnsSalesOsdc; plus header/JWT preview.
    """
    _require_debug_gate()
    user, _ = current_user_and_db
    _require_owner_admin_or_platform(user, db)

    invoice = load_invoice_for_osdc(db, invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", None)
    ensure_user_has_branch_access(db, user.id, invoice.branch_id)

    creds = (
        db.query(BranchEtimsCredentials)
        .filter(
            BranchEtimsCredentials.company_id == invoice.company_id,
            BranchEtimsCredentials.branch_id == invoice.branch_id,
        )
        .first()
    )
    if not creds:
        raise HTTPException(status_code=400, detail="Branch eTIMS credentials row missing")

    company = db.query(Company).filter(Company.id == invoice.company_id).first()

    try:
        assert_invoice_eligible_for_etims_submit(invoice)
    except Exception as ex:
        raise HTTPException(status_code=400, detail=str(ex)) from ex

    return build_stock_identity_report(
        db,
        invoice,
        creds=creds,
        company=company,
        timeout=timeout_seconds,
        include_osdc_bundle=include_osdc_bundle,
    )


@router.post("/replay-save-trns-sales-osdc")
def debug_replay_save_trns_sales_osdc(
    body: ReplaySaveTrnsSalesOsdcBody,
    *,
    reveal_secrets: bool = False,
    current_user_and_db: tuple = Depends(require_module("pharmacy")),
    db: Session = Depends(get_tenant_db),
) -> Dict[str, Any]:
    """
    POST the exact ``payload`` or ``body_raw_utf8`` from gavaetims (or prior forensic capture) using
    PharmaSight OAuth + KRA headers for the invoice's branch.
    """
    _require_debug_gate()
    user, _ = current_user_and_db
    _require_owner_admin_or_platform(user, db)

    invoice = load_invoice_for_osdc(db, body.invoice_id)
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    require_document_belongs_to_user_company(db, user, invoice, "Invoice", None)
    ensure_user_has_branch_access(db, user.id, invoice.branch_id)

    creds = (
        db.query(BranchEtimsCredentials)
        .filter(
            BranchEtimsCredentials.company_id == invoice.company_id,
            BranchEtimsCredentials.branch_id == invoice.branch_id,
        )
        .first()
    )
    if not creds or not creds.enabled:
        raise HTTPException(status_code=400, detail="Branch eTIMS credentials missing or disabled")

    company = db.query(Company).filter(Company.id == invoice.company_id).first()

    bundle = build_pharmasight_osdc_sale_attempt_bundle(
        db,
        invoice,
        creds=creds,
        company=company,
        timeout=body.timeout_seconds,
        include_select_invoice_type=body.include_select_invoice_type,
    )
    headers = dict(bundle["headers_final"])
    base = str(bundle["resolved_api_base"] or "").rstrip("/")

    url = f"{base}{SAVE_TRNS_SALES_OSDC_PATH}"
    params = body.query_params
    if params is None and isinstance(body.payload, dict):
        invc_qp = str(body.payload.get("invcNo") or "").strip()
        if invc_qp:
            params = {"invcNo": invc_qp, "requestedInvcNo": invc_qp}

    if body.body_raw_utf8 is not None:
        prep, resp = post_save_trns_sales_osdc_raw_body(
            url=url,
            headers=headers,
            body_utf8=body.body_raw_utf8,
            params=params,
            timeout=body.timeout_seconds,
        )
    elif body.payload is not None:
        prep = prepare_save_trns_sales_osdc_post(
            url=url, headers=headers, payload=body.payload, params=params
        )
        resp = post_save_trns_sales_osdc_via_prepared(prep, timeout=body.timeout_seconds)
    else:
        raise HTTPException(status_code=400, detail="Provide payload or body_raw_utf8")

    text = resp.text or ""
    parsed: Any = None
    try:
        parsed = resp.json()
    except Exception:
        pass
    wire = prepared_wire_view(prep)
    redacted_headers = dict(headers)
    if not reveal_secrets:
        if redacted_headers.get("Authorization"):
            redacted_headers["Authorization"] = "Bearer ***"
        if redacted_headers.get("cmcKey"):
            redacted_headers["cmcKey"] = "***"

    return {
        "request_prepared_url": wire.get("prepared_url"),
        "request_prepared_headers": wire.get("prepared_headers"),
        "request_prepared_body_utf8": wire.get("prepared_body_utf8"),
        "request_headers_redacted": redacted_headers,
        "response_http_status": resp.status_code,
        "response_headers": dict(resp.headers),
        "response_body_text": text[:32000],
        "response_body_json": parsed,
    }
