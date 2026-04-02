"""
Submit batched sales invoices to KRA eTIMS OSCU (`sendSalesTransaction`).

Runs outside the batch transaction. Uses OAuth + Bearer token and branch CMC key header
(per community SDK). Does not modify inventory or ledger.
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import requests
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models.company import BranchEtimsCredentials, Company
from app.models.etims_submission import EtimsSubmissionLog
from app.models.sale import SalesInvoice, SalesInvoiceItem
from app.services.etims.constants import SEND_SALES_TRANSACTION_PATH
from app.services.etims.branch_credentials import (
    effective_etims_environment,
    get_cmc_key_plain,
    get_oauth_username_password,
)
from app.services.etims.etims_invoice_payload_builder import build_send_sales_trns_payload
from app.services.etims.etims_oauth_client import get_access_token

logger = logging.getLogger(__name__)


class EtimsSubmissionSkipped(Exception):
    """Invoice or branch not eligible for submission (non-fatal)."""


def api_base_for_branch_credentials(env: Optional[str]) -> str:
    e = (env or "sandbox").strip().lower()
    if e == "production":
        return settings.ETIMS_PRODUCTION_API_BASE.rstrip("/")
    return settings.ETIMS_SANDBOX_API_BASE.rstrip("/")




def assert_invoice_eligible_for_etims_submit(invoice: SalesInvoice) -> None:
    st = getattr(invoice, "status", None)
    if st not in ("BATCHED", "PAID"):
        raise EtimsSubmissionSkipped(f"invoice status {st!r} is not BATCHED/PAID")
    sub = getattr(invoice, "submission_status", None)
    if sub != "pending":
        raise EtimsSubmissionSkipped(f"submission_status {sub!r} is not pending")
    for line in invoice.items:
        if not (getattr(line, "vat_cat_cd", None) and str(line.vat_cat_cd).strip()):
            raise EtimsSubmissionSkipped("line missing vat_cat_cd snapshot")
        if not (getattr(line, "tax_ty_cd", None) and str(line.tax_ty_cd).strip()):
            raise EtimsSubmissionSkipped("line missing tax_ty_cd snapshot")


def _coerce_result_cd(value: Any) -> Optional[str]:
    if value is None:
        return None
    s = str(value).strip()
    return s if s else None


def _result_cd_from_dict(d: Dict[str, Any]) -> Optional[str]:
    for key in ("resultCd", "resultCode"):
        if key in d and d.get(key) is not None:
            return _coerce_result_cd(d.get(key))
    return None


def find_etims_result_cd(body: Any) -> Optional[str]:
    """
    Resolve KRA result code from sandbox/production wrappers (root, data, result).
    Returns None if absent (treated as failure — success requires explicit '000').
    """
    if not isinstance(body, dict):
        return None
    rc = _result_cd_from_dict(body)
    if rc is not None:
        return rc
    nested = body.get("data")
    if isinstance(nested, dict):
        rc = _result_cd_from_dict(nested)
        if rc is not None:
            return rc
    nested = body.get("result")
    if isinstance(nested, dict):
        rc = _result_cd_from_dict(nested)
        if rc is not None:
            return rc
    nested = body.get("response")
    if isinstance(nested, dict):
        rc = _result_cd_from_dict(nested)
        if rc is not None:
            return rc
    return None


def _parse_success(body: Any) -> bool:
    """Strict: HTTP body must be JSON object with resultCd (any supported nesting) == '000'."""
    if not isinstance(body, dict):
        return False
    rc = find_etims_result_cd(body)
    return rc == "000"


def _first_non_empty_str(*values: Any) -> Optional[str]:
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s[:8000]
    return None


def _dicts_for_receipt_scan(root: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Order: shallow breadth-first over common OSCU envelopes + receipt object."""
    out: List[Dict[str, Any]] = []
    if not isinstance(root, dict):
        return out
    out.append(root)
    for k in ("data", "result", "response"):
        sub = root.get(k)
        if isinstance(sub, dict):
            out.append(sub)
    for parent_key in ("data", "result", "response"):
        parent = root.get(parent_key)
        if isinstance(parent, dict):
            rec = parent.get("receipt")
            if isinstance(rec, dict):
                out.append(rec)
    rec = root.get("receipt")
    if isinstance(rec, dict):
        out.append(rec)
    # de-dupe preserving order
    seen = set()
    unique: List[Dict[str, Any]] = []
    for d in out:
        id_ = id(d)
        if id_ not in seen:
            seen.add(id_)
            unique.append(d)
    return unique


def _extract_receipt_fields(body: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    Pull receipt / signature / QR from official field names across nested objects.
    Optional fields: any may be missing after a successful '000' response.
    """
    rcpt: Optional[str] = None
    sig: Optional[str] = None
    qr: Optional[str] = None
    for d in _dicts_for_receipt_scan(body):
        rcpt = rcpt or _first_non_empty_str(
            d.get("rcptNo"),
            d.get("receiptNo"),
            d.get("invcRcptNo"),
            d.get("rptNo"),
        )
        sig = sig or _first_non_empty_str(
            d.get("signature"),
            d.get("sdcIdSignature"),
            d.get("sig"),
            d.get("rcptSign"),
        )
        qr = qr or _first_non_empty_str(
            d.get("qrCode"),
            d.get("qrCd"),
            d.get("qrValue"),
            d.get("qrData"),
            d.get("intrlData"),
        )
    return rcpt, sig, qr


def _shallow_error_fields(d: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "resultCd": _coerce_result_cd(d.get("resultCd")) or _coerce_result_cd(d.get("resultCode")),
        "resultMsg": _first_non_empty_str(d.get("resultMsg"), d.get("message")),
        "errorCode": _first_non_empty_str(d.get("errorCode"), d.get("errCd")),
        "errorMessage": _first_non_empty_str(
            d.get("errorMessage"),
            d.get("error"),
            d.get("detail"),
            d.get("description"),
        ),
    }


def build_etims_error_detail(
    *,
    body: Any,
    http_status: Optional[int],
    raw_text: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Tuple[str, str]:
    """
    Structured error for kra_last_error (truncated JSON) and audit log body excerpt.
    Returns (detail_json_for_invoice, excerpt_for_log).
    """
    detail: Dict[str, Any] = {
        "httpStatus": http_status,
        "resultCd": None,
        "resultMsg": None,
        "errorCode": None,
        "errorMessage": None,
    }
    if isinstance(body, dict):
        sf = _shallow_error_fields(body)
        for k, v in sf.items():
            if v is not None:
                detail[k] = v
        if detail.get("resultCd") is None:
            detail["resultCd"] = find_etims_result_cd(body)
        for nest_key in ("data", "result", "response", "error"):
            nested = body.get(nest_key)
            if isinstance(nested, dict):
                nf = _shallow_error_fields(nested)
                for k, v in nf.items():
                    if detail.get(k) is None and v is not None:
                        detail[k] = v
    if extra:
        for k, v in extra.items():
            if v is not None:
                detail[k] = v
    has_kra_field = any(
        detail.get(x) is not None for x in ("resultCd", "resultMsg", "errorCode", "errorMessage")
    )
    if not has_kra_field and raw_text and raw_text.strip():
        detail["rawExcerpt"] = raw_text.strip()[:2500]
    try:
        json_str = json.dumps(detail, default=str, ensure_ascii=False)
    except Exception:
        json_str = str(detail)[:4000]
    excerpt = (raw_text or json_str)[:16000]
    return json_str[:4000], excerpt


def submit_sales_invoice(
    db: Session,
    invoice_id: UUID,
    *,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    Load invoice, validate, POST sendSalesTransaction, update invoice + audit log.
    Returns a small result dict for workers.
    """
    invoice = (
        db.query(SalesInvoice)
        .options(selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item))
        .filter(SalesInvoice.id == invoice_id)
        .first()
    )
    if not invoice:
        raise ValueError("Invoice not found")

    assert_invoice_eligible_for_etims_submit(invoice)

    creds = (
        db.query(BranchEtimsCredentials)
        .filter(BranchEtimsCredentials.branch_id == invoice.branch_id)
        .first()
    )
    if not creds or not creds.enabled:
        raise EtimsSubmissionSkipped("branch eTIMS credentials missing or disabled")
    if getattr(creds, "connection_status", None) != "verified":
        raise EtimsSubmissionSkipped(
            "branch eTIMS connection is not verified; run Test eTIMS Connection in Settings"
        )
    if not (creds.kra_bhf_id and str(creds.kra_bhf_id).strip()):
        raise EtimsSubmissionSkipped("branch kra_bhf_id not configured")
    if not (creds.device_serial and str(creds.device_serial).strip()):
        raise EtimsSubmissionSkipped("branch device_serial not configured")
    cmc = get_cmc_key_plain(creds)
    if not cmc:
        raise EtimsSubmissionSkipped("branch cmc_key not configured")

    company = db.query(Company).filter(Company.id == invoice.company_id).first()
    tin = (company.pin if company else None) or ""
    tin = str(tin).strip()
    if not tin:
        raise EtimsSubmissionSkipped("company PIN (tin) not configured")

    user, password = get_oauth_username_password(creds)
    if not user or not password:
        raise EtimsSubmissionSkipped(
            "KRA OAuth not configured: set ETIMS_APP_CONSUMER_KEY/ETIMS_APP_CONSUMER_SECRET on the server, or branch OAuth fields, or ETIMS_OAUTH_* env"
        )

    env_eff = effective_etims_environment(creds)
    base = api_base_for_branch_credentials(env_eff)
    try:
        token = get_access_token(
            api_base=base,
            username=user,
            password=password,
            timeout=timeout,
            environment=env_eff,
        )
    except Exception as e:
        detail, excerpt = build_etims_error_detail(
            body=None,
            http_status=None,
            raw_text=str(e),
            extra={"oauthError": str(e)},
        )
        _fail_invoice(db, invoice, detail)
        _write_log(
            db,
            invoice=invoice,
            payload_hash=None,
            http_status=None,
            response_status="oauth_failed",
            error_message=detail[:4000],
            response_body=excerpt,
        )
        _record_etims_connection_after_submit_attempt(db, invoice.branch_id, success=False)
        db.commit()
        return {"ok": False, "error": detail}

    payload = build_send_sales_trns_payload(
        tin=tin,
        bhf_id=str(creds.kra_bhf_id).strip(),
        invoice_no=invoice.invoice_no,
        invoice_items=list(invoice.items),
    )
    payload_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    headers_extra = {
        "tin": tin,
        "bhfId": str(creds.kra_bhf_id).strip(),
        "cmcKey": cmc,
    }

    url = f"{base}{SEND_SALES_TRANSACTION_PATH}"
    try:
        r = requests.post(
            url,
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                **headers_extra,
            },
            timeout=timeout,
        )
    except requests.RequestException as e:
        detail, excerpt = build_etims_error_detail(
            body=None,
            http_status=None,
            raw_text=str(e),
            extra={"transportError": str(e)},
        )
        _fail_invoice(db, invoice, detail)
        _write_log(
            db,
            invoice=invoice,
            payload_hash=payload_hash,
            http_status=None,
            response_status="http_error",
            error_message=detail[:4000],
            response_body=excerpt,
        )
        _record_etims_connection_after_submit_attempt(db, invoice.branch_id, success=False)
        db.commit()
        return {"ok": False, "error": detail}

    text = r.text or ""
    try:
        body = r.json()
    except Exception:
        body = None

    parsed = body if isinstance(body, dict) else None
    ok_http = 200 <= r.status_code < 300
    success = ok_http and _parse_success(parsed)

    if success and parsed is not None:
        rcpt, sig, qr = _extract_receipt_fields(parsed)
        invoice.kra_receipt_number = rcpt
        invoice.kra_signature = sig
        invoice.kra_qr_code = qr
        invoice.kra_submitted_at = datetime.now(timezone.utc)
        invoice.submission_status = "submitted"
        invoice.kra_last_error = None
        _write_log(
            db,
            invoice=invoice,
            payload_hash=payload_hash,
            http_status=r.status_code,
            response_status="submitted",
            error_message=None,
            response_body=text[:16000],
        )
        _record_etims_connection_after_submit_attempt(db, invoice.branch_id, success=True)
        db.commit()
        return {"ok": True, "receipt": rcpt}

    extra: Dict[str, Any] = {}
    if not ok_http:
        extra["httpError"] = True
    if parsed is None:
        extra["jsonParseError"] = True
    else:
        rc_found = find_etims_result_cd(parsed)
        if rc_found is None:
            extra["missingResultCd"] = True
        elif rc_found != "000":
            extra["resultCd"] = rc_found

    detail, excerpt = build_etims_error_detail(
        body=parsed if parsed is not None else {},
        http_status=r.status_code,
        raw_text=text,
        extra=extra if extra else None,
    )
    _fail_invoice(db, invoice, detail)
    _write_log(
        db,
        invoice=invoice,
        payload_hash=payload_hash,
        http_status=r.status_code,
        response_status="failed",
        error_message=detail[:4000],
        response_body=excerpt,
    )
    _record_etims_connection_after_submit_attempt(db, invoice.branch_id, success=False)
    db.commit()
    return {"ok": False, "error": detail}


def _fail_invoice(db: Session, invoice: SalesInvoice, message: str) -> None:
    invoice.submission_status = "failed"
    invoice.kra_last_error = (message or "")[:4000]


def _record_etims_connection_after_submit_attempt(
    db: Session,
    branch_id: UUID,
    *,
    success: bool,
) -> None:
    row = (
        db.query(BranchEtimsCredentials)
        .filter(BranchEtimsCredentials.branch_id == branch_id)
        .first()
    )
    if not row:
        return
    row.last_tested_at = datetime.now(timezone.utc)
    row.connection_status = "verified" if success else "failed"


def _write_log(
    db: Session,
    *,
    invoice: SalesInvoice,
    payload_hash: Optional[str],
    http_status: Optional[int],
    response_status: str,
    error_message: Optional[str],
    response_body: Optional[str],
) -> None:
    row = EtimsSubmissionLog(
        sales_invoice_id=invoice.id,
        company_id=invoice.company_id,
        branch_id=invoice.branch_id,
        request_payload_hash=payload_hash,
        response_status=response_status,
        http_status=http_status,
        error_message=error_message,
        response_body=response_body,
    )
    db.add(row)
