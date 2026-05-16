"""
Submit batched sales invoices to KRA eTIMS OSCU (`saveTrnsSalesOsdc`).

Runs outside the batch transaction. Uses OAuth + Bearer token and branch CMC key header
(per community SDK). Does not modify inventory or ledger.
"""
from __future__ import annotations

import hashlib
import json
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import requests
from sqlalchemy import desc
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models.company import BranchEtimsCredentials, Company
from app.models.etims_submission import EtimsSubmissionLog
from app.models.sale import SalesInvoice, SalesInvoiceItem
from app.services.etims.branch_credentials import get_cmc_key_plain
from app.services.etims.codes_service import map_item_master_vat_to_etims_category, map_vat_to_etims_category
from app.services.etims.etims_osdc_forensic import (
    build_pharmasight_osdc_sale_attempt_bundle,
    bump_kra_osdc_next_invc_no_after_success,
    maybe_append_pharmasight_forensic_jsonl,
    parse_kra_expected_osdc_invc_no_from_error,
    post_save_trns_sales_osdc_via_prepared,
    realign_kra_osdc_next_invc_no,
    resolve_osdc_tin,
)

logger = logging.getLogger(__name__)


def _is_osdc_sale_stock_visibility_error(text: str | None) -> bool:
    """
    KRA sometimes rejects ``saveTrnsSalesOsdc`` immediately after stock updates while OSCU stock master
    has not yet propagated to the sales engine (gavaetims retries the same pattern).
    """
    if not text:
        return False
    low = text.lower()
    return (
        "do not exist in your stock" in low
        or "does not exist in your stock master" in low
        or "stock information management" in low
    )


def _should_retry_osdc_sale_stock_propagation(*, parsed: dict | None, detail_json: str | None) -> bool:
    """
    ``build_etims_error_detail`` may surface only ``customerMessage`` (e.g. \"Validation failed\") while the
    stock hint lives in ``debugMessage`` — read the raw response header too.
    """
    if _is_osdc_sale_stock_visibility_error(detail_json):
        return True
    if not isinstance(parsed, dict):
        return False
    rh = parsed.get("responseHeader") or parsed.get("header")
    if not isinstance(rh, dict):
        return False
    parts = []
    for k in ("debugMessage", "customerMessage", "resultMsg", "message"):
        v = rh.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    return _is_osdc_sale_stock_visibility_error(" | ".join(parts))


class EtimsSubmissionSkipped(Exception):
    """Invoice or branch not eligible for submission (non-fatal)."""


def api_base_for_branch_credentials(env: Optional[str]) -> str:
    e = (env or "sandbox").strip().lower()
    if e == "production":
        return settings.ETIMS_PRODUCTION_API_BASE.rstrip("/")
    return settings.ETIMS_SANDBOX_API_BASE.rstrip("/")




def _norm_cd(val: object | None) -> str:
    if val is None:
        return ""
    return str(val).strip().upper()


def assert_invoice_eligible_for_etims_submit(invoice: SalesInvoice) -> None:
    st = getattr(invoice, "status", None)
    if st not in ("BATCHED", "PAID"):
        raise EtimsSubmissionSkipped(f"invoice status {st!r} is not BATCHED/PAID")
    sub = (getattr(invoice, "submission_status", None) or "").strip().lower()
    if sub == "submitted":
        raise EtimsSubmissionSkipped("invoice already submitted to KRA")
    if sub not in ("", "pending"):
        raise EtimsSubmissionSkipped(f"submission_status {sub!r} is not eligible for KRA submit")
    for line in invoice.items:
        if not (getattr(line, "vat_cat_cd", None) and str(line.vat_cat_cd).strip()):
            raise EtimsSubmissionSkipped("line missing vat_cat_cd snapshot")
        if not (getattr(line, "tax_ty_cd", None) and str(line.tax_ty_cd).strip()):
            raise EtimsSubmissionSkipped("line missing tax_ty_cd snapshot")
        it = getattr(line, "item", None)
        kra_cd = str(getattr(it, "kra_item_code", None) or "").strip() if it else ""
        if it is not None:
            logger.info(
                "kra_item_code_usage op=sales_submit_guard item_id=%s invoice_id=%s stored_code=%s used_code=%s",
                getattr(it, "id", None),
                getattr(invoice, "id", None),
                kra_cd or "<empty>",
                kra_cd or "<empty>",
            )
        if not kra_cd:
            raise EtimsSubmissionSkipped(
                "line item missing KRA item code (items.kra_item_code). Sync the product to KRA first; "
                "invoice item_code in the API is your internal SKU, not the KRA-registered itemCd."
            )
        if it is None:
            continue
        synced = str(getattr(it, "kra_sync_status", "") or "").strip().lower() == "synced"
        needs_resync = bool(getattr(it, "kra_needs_resync", False))
        if not synced:
            raise EtimsSubmissionSkipped(
                "Product is not synced to KRA (items.kra_sync_status). Run item sync, then submit the invoice."
            )
        if needs_resync:
            raise EtimsSubmissionSkipped(
                "Product VAT or class changed since last KRA sync (kra_needs_resync). Re-sync the item to KRA "
                "so the catalogue matches PharmaSight, then submit."
            )
        mapping = map_item_master_vat_to_etims_category(it)
        kra_tty = _norm_cd(getattr(it, "kra_tax_ty_cd", None))
        kra_vcat = _norm_cd(getattr(it, "kra_vat_cat_cd", None))
        if not kra_tty:
            raise EtimsSubmissionSkipped(
                "KRA catalogue taxTyCd is missing on the product after sync. Run item sync or "
                "\"refresh codes from KRA catalog\", then submit."
            )
        if kra_tty != mapping.tax_ty_cd:
            raise EtimsSubmissionSkipped(
                f"KRA catalogue taxTyCd ({kra_tty}) does not match this product's VAT in PharmaSight ({mapping.tax_ty_cd}). "
                "Re-sync the item to KRA (saveItem) so the master list matches, then submit — do not rely on "
                "sale-time code swaps for filing."
            )
        if kra_vcat and kra_vcat != mapping.vat_cat_cd:
            raise EtimsSubmissionSkipped(
                f"KRA catalogue vatCatCd ({kra_vcat}) does not match PharmaSight ({mapping.vat_cat_cd}). "
                "Re-sync the item to KRA, then submit."
            )


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
    rb = body.get("responseBody")
    if isinstance(rb, dict):
        rc = _result_cd_from_dict(rb)
        if rc is not None:
            return rc
        rbd = rb.get("data")
        if isinstance(rbd, dict):
            rc = _result_cd_from_dict(rbd)
            if rc is not None:
                return rc
    return None


def _parse_success(body: Any) -> bool:
    """Accept standard resultCd=000 and gava-style successful responseHeader envelopes."""
    if not isinstance(body, dict):
        return False
    rc = find_etims_result_cd(body)
    if rc == "000":
        return True
    hdr = body.get("responseHeader") or body.get("header")
    if not isinstance(hdr, dict):
        return False
    h_code = str(hdr.get("responseCode") or "").strip()
    if h_code and h_code != "200":
        return False
    msg = " ".join(
        str(hdr.get(k) or "").strip().lower()
        for k in ("customerMessage", "debugMessage", "resultMsg", "message")
    ).strip()
    return "success" in msg


def _first_non_empty_str(*values: Any) -> Optional[str]:
    for v in values:
        if v is None:
            continue
        s = str(v).strip()
        if s:
            return s[:8000]
    return None


def _dicts_for_receipt_scan(root: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Breadth-first over common KRA OSCU envelopes.

    Fiscal receipt fields (``rcptNo``, ``intrlData``, signatures) usually live under
    ``responseBody`` / ``responseBody.data`` (see ``kra_certify._response_body_dict``), not at the JSON root.
    """
    out: List[Dict[str, Any]] = []
    if not isinstance(root, dict):
        return out

    def push(d: object) -> None:
        if isinstance(d, dict) and d:
            out.append(d)

    push(root)
    for k in ("data", "result", "response", "responseBody"):
        push(root.get(k))

    rb = root.get("responseBody")
    if isinstance(rb, dict):
        push(rb)
        rbd = rb.get("data")
        if isinstance(rbd, dict):
            push(rbd)
            push(rbd.get("receipt"))
        push(rb.get("receipt"))

    for parent_key in ("data", "result", "response"):
        parent = root.get(parent_key)
        if isinstance(parent, dict):
            push(parent.get("receipt"))
            pd = parent.get("data")
            if isinstance(pd, dict):
                push(pd)
                push(pd.get("receipt"))

    push(root.get("receipt"))

    seen: set[int] = set()
    unique: List[Dict[str, Any]] = []
    for d in out:
        id_ = id(d)
        if id_ not in seen:
            seen.add(id_)
            unique.append(d)
    return unique


_QR_JSON_KEY_NORMALIZED: frozenset[str] = frozenset(
    {
        "qrcode",
        "qrcd",
        "qrvalue",
        "qrdata",
        "intrldata",
        "vsdcintrldata",
        "etimsverfcd",
        "etimsverfcode",
        "prtcrccnpt",
    }
)


def _norm_json_key(k: object) -> str:
    return str(k or "").strip().lower().replace("_", "")


def _deep_find_kra_qr_payload(obj: Any, depth: int = 0) -> Optional[str]:
    """If flat scan missed, walk the tree for any dict key that KRA uses for QR / internal verification payload."""
    if depth > 18 or obj is None:
        return None
    if isinstance(obj, dict):
        for key, val in obj.items():
            nk = _norm_json_key(key)
            if nk in _QR_JSON_KEY_NORMALIZED or nk.endswith("qrcode") or nk.endswith("intrldata"):
                s = _first_non_empty_str(val)
                if s and len(s) >= 4:
                    return s
            hit = _deep_find_kra_qr_payload(val, depth + 1)
            if hit:
                return hit
    elif isinstance(obj, list):
        for it in obj[:300]:
            hit = _deep_find_kra_qr_payload(it, depth + 1)
            if hit:
                return hit
    return None


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
            d.get("vsdcRcptNo"),
            d.get("mrcNo"),
        )
        sig = sig or _first_non_empty_str(
            d.get("signature"),
            d.get("sdcIdSignature"),
            d.get("sig"),
            d.get("rcptSign"),
            d.get("vsdcSign"),
            d.get("signData"),
        )
        qr = qr or _first_non_empty_str(
            d.get("qrCode"),
            d.get("qrCd"),
            d.get("qrValue"),
            d.get("qrData"),
            d.get("intrlData"),
            d.get("vsdcIntrlData"),
            d.get("INTRL_DATA"),
        )
    if not qr:
        qr = _deep_find_kra_qr_payload(body)
    return rcpt, sig, qr


def apply_kra_receipt_from_latest_submitted_log(db: Session, invoice: SalesInvoice) -> Dict[str, Any]:
    """
    Parse the latest successful ``etims_submission_log`` JSON and copy receipt / signature / QR onto the
    invoice when the submit path did not persist them (e.g. older extractor missed ``responseBody.data``).
    """
    out: Dict[str, Any] = {"updated": False, "fields": []}
    if (getattr(invoice, "submission_status", None) or "").strip().lower() != "submitted":
        out["reason"] = "invoice_not_submitted"
        return out
    log_row = (
        db.query(EtimsSubmissionLog)
        .filter(
            EtimsSubmissionLog.sales_invoice_id == invoice.id,
            EtimsSubmissionLog.response_status == "submitted",
        )
        .order_by(desc(EtimsSubmissionLog.created_at))
        .first()
    )
    raw = (getattr(log_row, "response_body", None) or "").strip() if log_row else ""
    if not raw:
        out["reason"] = "no_submitted_log_body"
        return out
    try:
        body = json.loads(raw)
    except json.JSONDecodeError:
        out["reason"] = "log_body_not_json"
        return out
    if not isinstance(body, dict):
        out["reason"] = "log_body_not_object"
        return out
    rcpt, sig, qr = _extract_receipt_fields(body)
    if rcpt and not (str(getattr(invoice, "kra_receipt_number", None) or "").strip()):
        invoice.kra_receipt_number = rcpt[:100]
        out["fields"].append("kra_receipt_number")
        out["updated"] = True
    if sig and not (str(getattr(invoice, "kra_signature", None) or "").strip()):
        invoice.kra_signature = sig
        out["fields"].append("kra_signature")
        out["updated"] = True
    if qr and not (str(getattr(invoice, "kra_qr_code", None) or "").strip()):
        invoice.kra_qr_code = qr
        out["fields"].append("kra_qr_code")
        out["updated"] = True
    if not out["fields"]:
        out["reason"] = "nothing_new_in_log_or_invoice_already_populated"
    return out


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
        hdr = body.get("responseHeader")
        if isinstance(hdr, dict):
            cm_s = str(hdr.get("customerMessage") or "").strip()
            dm_s = str(hdr.get("debugMessage") or "").strip()
            if cm_s and dm_s and cm_s != dm_s:
                hdr_msg = f"{cm_s} | {dm_s}"
            else:
                hdr_msg = _first_non_empty_str(
                    hdr.get("customerMessage"),
                    hdr.get("debugMessage"),
                    hdr.get("resultMsg"),
                    hdr.get("message"),
                )
            if hdr_msg and not (str(detail.get("errorMessage") or "").strip()):
                detail["errorMessage"] = hdr_msg
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
    Load invoice, validate, POST saveTrnsSalesOsdc, update invoice + audit log.
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

    from app.services.invoice_workflow_policy import note_kra_submission_workflow_anchor

    note_kra_submission_workflow_anchor(db, invoice)

    # Match worker behaviour: clear failed state so operators / print-PDF path can retry submit.
    if (invoice.submission_status or "").strip().lower() == "failed":
        invoice.submission_status = "pending"
        invoice.kra_last_error = None
        db.flush()

    assert_invoice_eligible_for_etims_submit(invoice)

    creds = (
        db.query(BranchEtimsCredentials)
        .filter(
            BranchEtimsCredentials.company_id == invoice.company_id,
            BranchEtimsCredentials.branch_id == invoice.branch_id,
        )
        .first()
    )
    if not creds or not creds.enabled:
        raise EtimsSubmissionSkipped("branch eTIMS credentials missing or disabled")
    if (getattr(creds, "connection_status", None) or "").strip().lower() != "verified":
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
    tin = resolve_osdc_tin(creds, company)
    if not tin:
        raise EtimsSubmissionSkipped(
            "branch client_tax_pin or company PIN (TIN) not configured — must match the TIN used for KRA stock IO"
        )

    realigned_sequence = False
    while True:
        try:
            bundle = build_pharmasight_osdc_sale_attempt_bundle(
                db,
                invoice,
                creds=creds,
                company=company,
                timeout=timeout,
                include_select_invoice_type=True,
            )
        except EtimsSubmissionSkipped:
            raise
        except ValueError as ve:
            if str(ve) == "oauth_not_configured":
                raise EtimsSubmissionSkipped(
                    "KRA OAuth not configured: set ETIMS_APP_CONSUMER_KEY/ETIMS_APP_CONSUMER_SECRET on the server, or branch OAuth fields, or ETIMS_OAUTH_* env"
                ) from ve
            if str(ve) == "missing_tin":
                raise EtimsSubmissionSkipped(
                    "branch client_tax_pin or company PIN (TIN) not configured — must match the TIN used for KRA stock IO"
                ) from ve
            raise
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

        maybe_append_pharmasight_forensic_jsonl(bundle)

        prep = bundle["prepared_request"]
        payload = bundle["payload_final"]
        payload_hash = hashlib.sha256(prep.body or b"").hexdigest()

        max_prop = max(int(settings.KRA_OSDC_SALE_STOCK_PROPAGATION_RETRIES or 1), 1)
        sleep_min = float(settings.KRA_OSDC_SALE_STOCK_PROPAGATION_SLEEP_MIN or 0.5)
        sleep_max = float(settings.KRA_OSDC_SALE_STOCK_PROPAGATION_SLEEP_MAX or sleep_min)

        r: requests.Response | None = None
        last_detail: str | None = None
        last_excerpt: str | None = None

        for attempt in range(max_prop):
            try:
                r = post_save_trns_sales_osdc_via_prepared(prep, timeout=timeout)
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
                try:
                    used_invc = int(str(payload.get("invcNo") or "0").strip() or "0")
                except ValueError:
                    used_invc = 0
                if used_invc >= 1:
                    bump_kra_osdc_next_invc_no_after_success(
                        db, creds_id=creds.id, used_invc_no=used_invc
                    )
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
                try:
                    from app.services.commercial_transaction_lifecycle import on_kra_submit_success

                    on_kra_submit_success(db, invoice, actor_user_id=None)
                except Exception:
                    logger.exception(
                        "commercial_transaction_lifecycle: KRA success hook failed (non-fatal)"
                    )
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
            last_detail = detail
            last_excerpt = excerpt
            if attempt + 1 < max_prop and _should_retry_osdc_sale_stock_propagation(
                parsed=parsed, detail_json=detail
            ):
                delay = random.uniform(sleep_min, max(sleep_min, sleep_max))
                logger.warning(
                    "saveTrnsSalesOsdc: OSCU stock not yet visible to sales API (attempt %s/%s); retry after %.1fs — %s",
                    attempt + 1,
                    max_prop,
                    delay,
                    (detail or "")[:400],
                )
                time.sleep(delay)
                continue

            break

        exp = parse_kra_expected_osdc_invc_no_from_error(last_detail or "")
        if exp is not None and not realigned_sequence:
            realign_kra_osdc_next_invc_no(db, creds_id=creds.id, expected_invc_no=exp)
            db.flush()
            realigned_sequence = True
            logger.warning(
                "saveTrnsSalesOsdc: set kra_osdc_next_invc_no to KRA expected %s and rebuilding payload once",
                exp,
            )
            continue

        fail_detail = last_detail or "{}"
        _fail_invoice(db, invoice, fail_detail)
        _write_log(
            db,
            invoice=invoice,
            payload_hash=payload_hash,
            http_status=r.status_code if r is not None else None,
            response_status="failed",
            error_message=fail_detail[:4000],
            response_body=(last_excerpt or "")[:16000] if last_excerpt else None,
        )
        _record_etims_connection_after_submit_attempt(db, invoice.branch_id, success=False)
        db.commit()
        return {"ok": False, "error": fail_detail}


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
    # Do not downgrade branch connection_status on invoice submit errors; a business payload
    # failure should not invalidate verified branch connectivity.
    if success:
        row.connection_status = "verified"


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
