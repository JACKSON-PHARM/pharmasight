"""
Deterministic saveTrnsSalesOsdc (OSDC) forensic helpers: wire-level body/headers, field extraction, JSONL.

Does **not** import ``etims_invoice_submitter`` (avoids import cycles). Callers run eligibility checks first.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

import requests
from requests import PreparedRequest
from sqlalchemy.orm import Session, selectinload

from app.config import settings
from app.models.company import BranchEtimsCredentials, Company
from app.models.sale import SalesInvoice, SalesInvoiceItem
from app.services.etims.branch_credentials import (
    effective_etims_environment,
    get_cmc_key_plain,
    get_oauth_username_password,
)
from app.services.etims.constants import SAVE_TRNS_SALES_OSDC_PATH, SELECT_INVOICE_TYPE_PATH
from app.services.etims.etims_invoice_payload_builder import build_save_trns_sales_osdc_payload
from app.services.etims.etims_oauth_client import get_access_token

logger = logging.getLogger(__name__)


def _lock_branch_etims_credentials_row(db: Session, creds_id: UUID) -> Optional[BranchEtimsCredentials]:
    return (
        db.query(BranchEtimsCredentials)
        .filter(BranchEtimsCredentials.id == creds_id)
        .with_for_update()
        .first()
    )


def read_osdc_invc_no_for_next_sale(db: Session, creds: BranchEtimsCredentials) -> int:
    """
    KRA ``saveTrnsSalesOsdc`` ``invcNo`` is a monotonic OSCU sequence per branch (gava ``osdc_invc_no_next``),
    not digits from the POS ``invoice_no`` string.
    """
    locked = _lock_branch_etims_credentials_row(db, creds.id)
    if not locked:
        raise ValueError("branch_etims_credentials_row_missing")
    raw = getattr(locked, "kra_osdc_next_invc_no", None)
    try:
        n = int(raw) if raw is not None else 1
    except (TypeError, ValueError):
        n = 1
    return n if n >= 1 else 1


def bump_kra_osdc_next_invc_no_after_success(db: Session, *, creds_id: UUID, used_invc_no: int) -> None:
    """After resultCd 000, set next ``invcNo`` to ``used + 1`` (matches gava post-save bump)."""
    locked = _lock_branch_etims_credentials_row(db, creds_id)
    if not locked:
        return
    try:
        u = int(used_invc_no)
    except (TypeError, ValueError):
        return
    if u < 1:
        return
    locked.kra_osdc_next_invc_no = u + 1


def parse_kra_expected_osdc_invc_no_from_error(detail_json: str) -> Optional[int]:
    """
    Parse KRA messages like ``expected: 1 but found: 14`` / ``use the expected value: 1`` so we can realign
    ``kra_osdc_next_invc_no`` when another client consumed sequence numbers.
    """
    if not detail_json or not str(detail_json).strip():
        return None
    s = str(detail_json)
    for pattern in (
        r"expected:\s*(\d+)",
        r"expected\s+value:\s*(\d+)",
        r"use\s+the\s+expected\s+value:\s*(\d+)",
    ):
        m = re.search(pattern, s, re.IGNORECASE)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                return None
    return None


def realign_kra_osdc_next_invc_no(db: Session, *, creds_id: UUID, expected_invc_no: int) -> None:
    locked = _lock_branch_etims_credentials_row(db, creds_id)
    if not locked:
        return
    n = int(expected_invc_no)
    locked.kra_osdc_next_invc_no = n if n >= 1 else 1


def api_base_for_branch_env(env: Optional[str]) -> str:
    e = (env or "sandbox").strip().lower()
    if e == "production":
        return settings.ETIMS_PRODUCTION_API_BASE.rstrip("/")
    return settings.ETIMS_SANDBOX_API_BASE.rstrip("/")


ROOT_COMPARE_KEYS = (
    "tin",
    "bhfId",
    "custTin",
    "salesTyCd",
    "rcptTyCd",
    "pmtTyCd",
    "salesSttsCd",
    "cfmDt",
    "salesDt",
    "stockRlsDt",
    "totItemCnt",
    "totTaxblAmt",
    "totTaxAmt",
    "totAmt",
)

ITEM_COMPARE_KEYS = (
    "itemCd",
    "itemClsCd",
    "itemNm",
    "pkgUnitCd",
    "pkg",
    "qtyUnitCd",
    "qty",
    "prc",
    "splyAmt",
    "dcRt",
    "dcAmt",
    "vatCatCd",
    "taxTyCd",
    "taxAmt",
    "totAmt",
)


def resolve_osdc_tin(creds: BranchEtimsCredentials, company: Optional[Company]) -> str:
    """Same rule as stock push / item sync: branch ``client_tax_pin`` overrides ``company.pin``."""
    return (
        str(getattr(creds, "client_tax_pin", None) or "").strip()
        or str((company.pin if company else None) or "").strip()
    )


def mask_secrets_in_headers(h: Dict[str, Any]) -> Dict[str, Any]:
    """Copy headers for API responses; mask Bearer and ``cmcKey`` only."""
    out: Dict[str, Any] = {}
    for k, v in (h or {}).items():
        ks = str(k)
        vs = str(v) if v is not None else ""
        lk = ks.lower()
        if lk == "authorization" and vs.lower().startswith("bearer "):
            out[ks] = "Bearer ***"
        elif lk == "cmckey":
            out[ks] = "***"
        else:
            out[ks] = v
    return out


def headers_to_str_dict(headers: Any) -> Dict[str, str]:
    """Normalize ``requests``/``urllib3`` header structures to ``str -> str``."""
    if headers is None:
        return {}
    try:
        items = list(headers.items())
    except Exception:
        return {}
    out: Dict[str, str] = {}
    for k, v in items:
        key = k.decode("latin-1") if isinstance(k, bytes) else str(k)
        val = v.decode("latin-1") if isinstance(v, bytes) else str(v)
        out[key] = val
    return out


def prepare_save_trns_sales_osdc_post(
    *,
    url: str,
    headers: Dict[str, Any],
    payload: Dict[str, Any],
    params: Optional[Dict[str, Any]],
) -> PreparedRequest:
    """Build the same PreparedRequest ``requests`` would use for ``json=payload`` + ``params``."""
    req = requests.Request(method="POST", url=url, headers=headers, json=payload, params=params)
    return requests.Session().prepare_request(req)


def prepared_wire_view(prep: PreparedRequest) -> Dict[str, Any]:
    """Exact wire fields after prepare (no value coercion beyond header decoding)."""
    return {
        "prepared_method": prep.method,
        "prepared_url": prep.url,
        "prepared_path_url": getattr(prep, "path_url", None),
        "prepared_headers": headers_to_str_dict(prep.headers),
        "prepared_body_utf8": prep.body.decode("utf-8") if prep.body else None,
        "prepared_body_length": len(prep.body) if prep.body else 0,
    }


def extract_root_compare(payload: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in ROOT_COMPARE_KEYS:
        out[k] = payload.get(k) if isinstance(payload, dict) else None
    return out


def extract_item_lines_compare(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    il = payload.get("itemList") if isinstance(payload, dict) else None
    if not isinstance(il, list):
        return rows
    for line in il:
        if not isinstance(line, dict):
            continue
        rows.append({k: line.get(k) for k in ITEM_COMPARE_KEYS})
    return rows


def append_forensic_jsonl(path: str, record: Dict[str, Any]) -> None:
    """Append one JSON object per line; values must be JSON-serializable (use ``default=str`` on dump)."""
    line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)


def _post_select_invoice_type_optional(
    *,
    base: str,
    token: str,
    tin: str,
    bhf_id: str,
    headers_extra: Dict[str, str],
    timeout: int,
) -> Dict[str, Any]:
    """Same contract as submitter prelude; returns minimal status dict for diagnostics."""
    url = f"{base.rstrip('/')}{SELECT_INVOICE_TYPE_PATH}"
    hdr = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        **headers_extra,
    }
    body = {
        "tin": tin.strip(),
        "bhfId": bhf_id.strip(),
        "salesTyCd": "N",
        "rcptTyCd": "S",
        "pmtTyCd": "01",
    }
    try:
        resp = requests.post(url, json=body, headers=hdr, timeout=timeout)
        text = resp.text or ""
        parsed = None
        try:
            parsed = resp.json()
        except Exception:
            pass
        return {
            "http_status": resp.status_code,
            "response_text_excerpt": text[:8000],
            "response_json": parsed,
        }
    except requests.RequestException as ex:
        return {"http_status": None, "error": str(ex)}


def build_pharmasight_osdc_sale_attempt_bundle(
    db: Session,
    invoice: SalesInvoice,
    *,
    creds: BranchEtimsCredentials,
    company: Optional[Company],
    timeout: int = 60,
    include_select_invoice_type: bool = True,
) -> Dict[str, Any]:
    """
    Resolve OAuth, optional ``selectInvoiceType``, build ``saveTrnsSalesOsdc`` payload, prepare wire POST.

    Caller must have already validated eligibility. Returns dict safe to JSON-serialize except
    ``oauth_token`` (included for parity debugging — treat as secret).
    """
    tin = resolve_osdc_tin(creds, company)
    if not tin:
        raise ValueError("missing_tin")

    user, password = get_oauth_username_password(creds)
    if not user or not password:
        raise ValueError("oauth_not_configured")

    env_eff = effective_etims_environment(creds)
    base = api_base_for_branch_env(env_eff)
    token = get_access_token(
        api_base=base,
        username=user,
        password=password,
        timeout=timeout,
        environment=env_eff,
    )

    bhf_s = str(creds.kra_bhf_id).strip()
    cmc = get_cmc_key_plain(creds) or ""
    dev = str(creds.device_serial).strip()

    headers_extra: Dict[str, str] = {
        "tin": tin,
        "bhfId": bhf_s,
        "cmcKey": cmc,
        "dvcSrlNo": dev,
    }
    apigee_app_id = (getattr(creds, "apigee_app_id", None) or "").strip()
    if apigee_app_id:
        headers_extra["apigee_app_id"] = apigee_app_id

    post_headers: Dict[str, Any] = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        **headers_extra,
    }

    select_invoice_type_result: Optional[Dict[str, Any]] = None
    if include_select_invoice_type:
        select_invoice_type_result = _post_select_invoice_type_optional(
            base=base,
            token=token,
            tin=tin,
            bhf_id=bhf_s,
            headers_extra=headers_extra,
            timeout=timeout,
        )

    osdc_invc_no = read_osdc_invc_no_for_next_sale(db, creds)
    payload = build_save_trns_sales_osdc_payload(
        tin=tin,
        bhf_id=bhf_s,
        invoice=invoice,
        invoice_items=list(invoice.items),
        sales_ty_cd="N",
        rcpt_ty_cd="S",
        pmt_ty_cd="01",
        reg_ty_cd="M",
        trd_invc_no=str(invoice.invoice_no or "").strip(),
        org_invc_no=0,
        db=db,
        osdc_invc_no=osdc_invc_no,
    )
    invc_qp = str(payload.get("invcNo") or "").strip()
    query_params: Optional[Dict[str, str]] = None
    if invc_qp:
        query_params = {"invcNo": invc_qp, "requestedInvcNo": invc_qp}

    url = f"{base.rstrip('/')}{SAVE_TRNS_SALES_OSDC_PATH}"
    prep = prepare_save_trns_sales_osdc_post(
        url=url, headers=post_headers, payload=payload, params=query_params
    )
    wire = prepared_wire_view(prep)
    line_rows = payload.get("itemList")

    return {
        "source": "pharmasight",
        "prepared_request": prep,
        "resolved_tin": tin,
        "resolved_bhf_id": bhf_s,
        "resolved_dvc_srl_no": dev,
        "resolved_api_base": base,
        "resolved_environment": env_eff,
        "endpoint_path": SAVE_TRNS_SALES_OSDC_PATH,
        "full_url": wire["prepared_url"],
        "query_params": query_params,
        "user_agent": requests.utils.default_user_agent(),
        "oauth_token": token,
        "headers_final": post_headers,
        "headers_final_masked": mask_secrets_in_headers(post_headers),
        "payload_final": payload,
        "root_compare": extract_root_compare(payload),
        "item_lines_compare": extract_item_lines_compare(payload),
        "transformed_item_list_from_builder": line_rows if isinstance(line_rows, list) else None,
        "prepared_wire": wire,
        "select_invoice_type": select_invoice_type_result,
    }


def load_invoice_for_osdc(db: Session, invoice_id: Any) -> Optional[SalesInvoice]:
    return (
        db.query(SalesInvoice)
        .options(selectinload(SalesInvoice.items).selectinload(SalesInvoiceItem.item))
        .filter(SalesInvoice.id == invoice_id)
        .first()
    )


def maybe_append_pharmasight_forensic_jsonl(bundle: Dict[str, Any]) -> None:
    """If ``settings.ETIMS_OSDC_FORENSIC_JSONL_PATH`` is set, append one forensic line (exact payload dict)."""
    path = (getattr(settings, "ETIMS_OSDC_FORENSIC_JSONL_PATH", None) or "").strip()
    if not path:
        return
    rec = {
        "source": bundle.get("source"),
        "full_url": bundle.get("full_url"),
        "query_params": bundle.get("query_params"),
        "headers": bundle.get("headers_final"),
        "payload": bundle.get("payload_final"),
        "prepared_wire": bundle.get("prepared_wire"),
        "user_agent": bundle.get("user_agent"),
    }
    try:
        append_forensic_jsonl(path, rec)
    except Exception:
        logger.exception("ETIMS_OSDC_FORENSIC_JSONL_PATH append failed path=%s", path)


def post_save_trns_sales_osdc_via_prepared(
    prep: PreparedRequest,
    *,
    timeout: int = 60,
) -> requests.Response:
    """Send a prepared OSDC POST (same Session path as forensic capture)."""
    sess = requests.Session()
    return sess.send(prep, timeout=timeout)


def post_save_trns_sales_osdc_raw_body(
    *,
    url: str,
    headers: Dict[str, Any],
    body_utf8: str,
    params: Optional[Dict[str, Any]],
    timeout: int = 60,
) -> Tuple[PreparedRequest, requests.Response]:
    """
    Replay exact UTF-8 JSON body bytes (no ``json=`` re-encoding). Caller must set Content-Type: application/json.
    """
    b = body_utf8.encode("utf-8")
    sess = requests.Session()
    req = requests.Request(method="POST", url=url, headers=headers, data=b, params=params)
    prep = sess.prepare_request(req)
    resp = sess.send(prep, timeout=timeout)
    return prep, resp


def serialize_creds_public(creds: BranchEtimsCredentials) -> Dict[str, Any]:
    return {
        "branch_id": str(creds.branch_id),
        "company_id": str(creds.company_id),
        "enabled": bool(creds.enabled),
        "environment": getattr(creds, "environment", None),
        "kra_bhf_id": creds.kra_bhf_id,
        "device_serial": creds.device_serial,
        "apigee_app_id": getattr(creds, "apigee_app_id", None),
        "client_tax_pin_raw": getattr(creds, "client_tax_pin", None),
        "connection_status": getattr(creds, "connection_status", None),
        "has_cmc_key": bool(get_cmc_key_plain(creds)),
    }
