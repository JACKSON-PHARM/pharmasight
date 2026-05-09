"""Item master sync with KRA saveItem endpoint (gavaetims-aligned payload)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import UUID

import requests
from sqlalchemy.orm import Session

from app.models.company import BranchEtimsCredentials, Company
from app.models.item import Item
from app.services.etims.branch_credentials import (
    effective_etims_environment,
    get_cmc_key_plain,
    get_oauth_username_password,
)
from app.services.etims.codes_service import map_vat_to_etims_category
from app.services.etims.constants import SAVE_ITEM_PATH
from app.services.etims.etims_invoice_submitter import api_base_for_branch_credentials, find_etims_result_cd
from app.services.etims.etims_oauth_client import get_access_token


def _item_code(item: Item) -> str:
    sku = (item.sku or "").strip()
    if sku:
        return sku[:50]
    return str(item.id).replace("-", "")[:32]


def build_save_item_payload(item: Item) -> Dict[str, Any]:
    mapping = map_vat_to_etims_category(
        vat_category=getattr(item, "vat_category", None),
        vat_rate_percent=float(getattr(item, "vat_rate", 0) or 0),
    )
    tax_ty = (item.kra_tax_ty_cd or "").strip() or mapping.tax_ty_cd
    payload: Dict[str, Any] = {
        "itemCd": _item_code(item),
        "itemClsCd": (item.kra_item_cls_cd or "50302517").strip(),
        "itemTyCd": "2",
        "itemNm": (item.name or "ITEM").strip()[:200],
        "orgnNatCd": "KE",
        "pkgUnitCd": (item.kra_pkg_unit_cd or "NT").strip(),
        "qtyUnitCd": (item.kra_qty_unit_cd or "U").strip(),
        "taxTyCd": tax_ty,
        "dftPrc": float(getattr(item, "promo_price_retail", None) or getattr(item, "floor_price_retail", None) or 0),
        "isrcAplcbYn": "N",
        "useYn": "Y" if bool(getattr(item, "is_active", True)) else "N",
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
    }
    return payload


def _payload_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def sync_item_to_kra(
    db: Session,
    *,
    item_id: UUID,
    company_id: UUID,
    branch_id: UUID,
    timeout: int = 60,
) -> Dict[str, Any]:
    item = db.query(Item).filter(Item.id == item_id, Item.company_id == company_id).first()
    if not item:
        return {"ok": False, "error": "item_not_found"}

    creds = (
        db.query(BranchEtimsCredentials)
        .filter(BranchEtimsCredentials.company_id == company_id, BranchEtimsCredentials.branch_id == branch_id)
        .first()
    )
    if not creds or not bool(creds.enabled):
        return {"ok": False, "error": "branch_kra_not_enabled"}

    company = db.query(Company).filter(Company.id == company_id).first()
    tin = ((getattr(creds, "client_tax_pin", None) or "") if creds else "") or ((company.pin if company else "") or "")
    tin = str(tin or "").strip()
    if not tin:
        return {"ok": False, "error": "company_tin_missing"}
    if not (creds.kra_bhf_id and str(creds.kra_bhf_id).strip()):
        return {"ok": False, "error": "branch_bhf_missing"}
    cmc = get_cmc_key_plain(creds)
    if not cmc:
        return {"ok": False, "error": "cmc_missing"}
    user, password = get_oauth_username_password(creds)
    if not user or not password:
        return {"ok": False, "error": "oauth_missing"}

    env_eff = effective_etims_environment(creds)
    base = api_base_for_branch_credentials(env_eff)
    payload = build_save_item_payload(item)
    p_hash = _payload_hash(payload)
    item.kra_last_attempt_at = datetime.now(timezone.utc)
    item.kra_sync_attempt_count = int(item.kra_sync_attempt_count or 0) + 1
    item.kra_sync_status = "syncing"
    db.flush()
    try:
        token = get_access_token(
            api_base=base,
            username=user,
            password=password,
            timeout=45,
            environment=env_eff,
        )
        r = requests.post(
            f"{base}{SAVE_ITEM_PATH}",
            json=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {token}",
                "tin": tin,
                "bhfId": str(creds.kra_bhf_id).strip(),
                "cmcKey": cmc,
            },
            timeout=timeout,
        )
        parsed = r.json() if (r.text or "").strip() else None
        rc = find_etims_result_cd(parsed) if isinstance(parsed, dict) else None
        ok = (200 <= r.status_code < 300) and (rc == "000")
        if ok:
            item.kra_payload_hash = p_hash
            item.kra_sync_status = "synced"
            item.kra_sync_error = None
            item.kra_synced_at = datetime.now(timezone.utc)
            item.kra_needs_resync = False
            db.flush()
            return {"ok": True, "result_cd": rc, "http_status": r.status_code}
        item.kra_sync_status = "failed"
        item.kra_sync_error = f"saveItem_failed http={r.status_code} rc={rc or 'none'}"
        item.kra_needs_resync = True
        db.flush()
        return {"ok": False, "error": item.kra_sync_error}
    except Exception as e:
        item.kra_sync_status = "failed"
        item.kra_sync_error = f"saveItem_exception: {str(e)[:300]}"
        item.kra_needs_resync = True
        db.flush()
        return {"ok": False, "error": item.kra_sync_error}

