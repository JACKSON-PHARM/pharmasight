"""Item master sync with KRA saveItem endpoint (gavaetims-aligned payload)."""
from __future__ import annotations

import hashlib
import json
import logging
import re
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
from app.services.etims.codes_service import map_item_master_vat_to_etims_category, map_vat_to_etims_category
from app.services.etims.constants import SAVE_ITEM_PATH, SELECT_ITEM_CLASS_LIST_PATH, SELECT_ITEM_LIST_PATH
from app.services.etims.etims_invoice_submitter import api_base_for_branch_credentials, find_etims_result_cd
from app.services.etims.etims_oauth_client import get_access_token


_KRA_ITEM_CODE_RE = re.compile(r"^KE[A-Z0-9]{1,30}\d{7}$")
_ITEM_CLASS_PREF_ORDER = ("1010000000", "9901200000")
_KRA_SEQ_HINT_PATTERNS = (
    r"Expected sequence ending with[:\s]*\*+(\d+)",
    r"Expected sequence ending with\s*\*+(\d+)",
)

logger = logging.getLogger(__name__)


def _audit_kra_item_code_update(item: Item, new_code: str | None, *, reason: str) -> None:
    """Centralized, explicit audit log whenever Item.kra_item_code changes."""
    old_code = str(getattr(item, "kra_item_code", None) or "").strip().upper()
    next_code = str(new_code or "").strip().upper()
    if not next_code:
        return
    if old_code != next_code:
        logger.warning(
            "kra_item_code_changed reason=%s item_id=%s company_id=%s old_code=%s new_code=%s",
            reason,
            getattr(item, "id", None),
            getattr(item, "company_id", None),
            old_code or "<empty>",
            next_code,
        )
    item.kra_item_code = next_code


def _is_kra_item_code_valid(v: str | None) -> bool:
    code = (v or "").strip().upper()
    return bool(code and _KRA_ITEM_CODE_RE.match(code))


def _norm_unit_code(v: str | None, default_code: str) -> str:
    code = re.sub(r"[^A-Z0-9]", "", (v or "").strip().upper())
    return code or default_code


def _norm_qty_unit_code(v: str | None) -> str:
    # gavaetims default path uses TU; KRA rejects generic U for many saveItem prefixes.
    code = _norm_unit_code(v, "TU")
    if code == "U":
        return "TU"
    return code


def _item_cd_prefix(*, item_ty_cd: str = "2", pkg_unit_cd: str, qty_unit_cd: str) -> str:
    # KRA itemCd prefix must align with item type + package unit + quantity unit.
    return f"KE{_norm_unit_code(item_ty_cd, '2')}{_norm_unit_code(pkg_unit_cd, 'NT')}{_norm_unit_code(qty_unit_cd, 'U')}"


def _next_kra_item_code(db: Session, *, company_id: UUID, prefix: str) -> str:
    max_suffix = 0
    rows = db.query(Item.kra_item_code).filter(Item.company_id == company_id, Item.kra_item_code.isnot(None)).all()
    upfx = prefix.upper()
    for (code_raw,) in rows:
        code = (code_raw or "").strip().upper()
        if not code.startswith(upfx):
            continue
        tail = code[len(upfx) :]
        if len(tail) != 7 or not tail.isdigit():
            continue
        max_suffix = max(max_suffix, int(tail))
    return f"{upfx}{max_suffix + 1:07d}"


def _item_cd_suffix(code: str | None) -> int | None:
    c = (code or "").strip().upper()
    if len(c) < 7:
        return None
    tail = c[-7:]
    if not tail.isdigit():
        return None
    return int(tail)


def _parse_kra_sequence_tail_hint(msg: str | None) -> tuple[int, int] | None:
    text = (msg or "").strip()
    if not text:
        return None
    for p in _KRA_SEQ_HINT_PATTERNS:
        m = re.search(p, text, flags=re.IGNORECASE)
        if not m:
            continue
        digits = (m.group(1) or "").strip()
        if not digits.isdigit():
            continue
        return (10 ** len(digits), int(digits))
    return None


def _next_suffix_matching_tail(min_suffix: int, modulus: int, residue: int) -> int:
    # Smallest n >= min_suffix satisfying n % modulus == residue
    n = int(min_suffix)
    r = n % modulus
    if r == residue:
        return n
    return n + ((residue - r) % modulus)


def _suggested_item_cd_after_sequence_error(item_cd_sent: str | None, msg: str | None) -> str | None:
    """Build next ``itemCd`` from KRA ``Invalid itemCd Sequence`` / ``Expected sequence ending with`` hint."""
    ic = (item_cd_sent or "").strip().upper()
    if len(ic) < 8:
        return None
    hint = _parse_kra_sequence_tail_hint(msg)
    if not hint:
        return None
    seq_base = (_item_cd_suffix(ic) or 0) + 1
    seq_base = _next_suffix_matching_tail(seq_base, hint[0], hint[1])
    tail = ic[-7:]
    if not tail.isdigit():
        return None
    return f"{ic[:-7]}{seq_base:07d}"


def _extract_item_cls_list(parsed: Dict[str, Any] | None) -> list[dict]:
    if not isinstance(parsed, dict):
        return []
    rb = parsed.get("responseBody")
    if not isinstance(rb, dict):
        return []
    data = rb.get("data")
    if not isinstance(data, dict):
        return []
    lst = data.get("itemClsList")
    return [x for x in lst if isinstance(x, dict)] if isinstance(lst, list) else []


def _extract_item_list(parsed: Dict[str, Any] | None) -> list[dict]:
    if not isinstance(parsed, dict):
        return []
    rb = parsed.get("responseBody")
    if not isinstance(rb, dict):
        return []
    data = rb.get("data")
    if not isinstance(data, dict):
        return []
    for key in ("itemList", "items", "list"):
        lst = data.get(key)
        if isinstance(lst, list):
            return [x for x in lst if isinstance(x, dict)]
    return []


def _fetch_item_list(
    *,
    base: str,
    token: str,
    tin: str,
    bhf_id: str,
    cmc_key: str,
    apigee_app_id: str,
    timeout: int,
    item_cd: str | None = None,
) -> list[dict]:
    """
    POST ``selectItemList``. When ``itemCd`` is set, mirrors gavaetims strict pre-sale probes
    (filtered list for one product) so we hydrate ``taxTyCd`` / class / units from KRA's catalog row.
    """
    body: Dict[str, Any] = {"tin": tin, "bhfId": bhf_id, "lastReqDt": "20100101000000"}
    ic = (item_cd or "").strip().upper()
    if ic:
        body["itemCd"] = ic
    r = requests.post(
        f"{base}{SELECT_ITEM_LIST_PATH}",
        json=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "tin": tin,
            "bhfId": bhf_id,
            "cmcKey": cmc_key,
            "apigee_app_id": apigee_app_id,
        },
        timeout=timeout,
    )
    if r.status_code >= 400:
        return []
    parsed = r.json() if (r.text or "").strip() else None
    return _extract_item_list(parsed)


def _kra_catalog_row_jsonb(row: dict | None) -> dict | None:
    """Normalize a selectItemList row for JSONB (JSON-serializable copy)."""
    if not isinstance(row, dict) or not row:
        return None
    try:
        return json.loads(json.dumps(row, default=str))
    except (TypeError, ValueError):
        return dict(row)


def _pick_item_row_by_cd(rows: list[dict], item_cd: str) -> dict | None:
    want = (item_cd or "").strip().upper()
    if not want:
        return None
    for row in rows:
        cd = str(row.get("itemCd") or "").strip().upper()
        if cd == want:
            return row
    return None


def apply_kra_select_item_list_row(item: Item, row: dict, *, allow_item_code_update: bool = True) -> None:
    """Persist authoritative KRA catalog fields from one ``selectItemList`` row onto ``Item``."""
    snap = _kra_catalog_row_jsonb(row)
    if snap is not None:
        item.kra_catalog_snapshot = snap
    cd = str(row.get("itemCd") or "").strip().upper()
    if cd and allow_item_code_update:
        _audit_kra_item_code_update(item, cd, reason="apply_kra_select_item_list_row")
    tty = str(row.get("taxTyCd") or "").strip().upper()
    if tty:
        item.kra_tax_ty_cd = tty
    vcat = str(row.get("vatCatCd") or row.get("vat_cat_cd") or "").strip().upper()
    if vcat:
        item.kra_vat_cat_cd = vcat
    micls = str(row.get("itemClsCd") or "").strip()
    if micls:
        item.kra_item_cls_cd = micls
    pkg = str(row.get("pkgUnitCd") or "").strip().upper()
    if pkg:
        item.kra_pkg_unit_cd = _norm_unit_code(pkg, "NT")
    qty_raw = str(row.get("qtyUnitCd") or "").strip().upper()
    if qty_raw:
        item.kra_qty_unit_cd = _norm_qty_unit_code(qty_raw)

    _coerce_zero_rated_vat_cat_cd_after_catalog_row(item)


def _coerce_zero_rated_vat_cat_cd_after_catalog_row(item: Item) -> None:
    """
    KRA often omits ``vatCatCd`` on zero-rated ``selectItemList`` rows. Older PharmaSight used ``vatCatCd`` ``B``
    with ``taxTyCd`` ``C``, which OSDC rejects (``taxRtB`` / 16% mismatch). When master is zero-rated and
    ``taxTyCd`` is ``C``, align ``kra_vat_cat_cd`` with the current map (``D``) if still blank or legacy ``B``.
    """
    if str(getattr(item, "kra_tax_ty_cd", None) or "").strip().upper() != "C":
        return
    m = map_item_master_vat_to_etims_category(item)
    if m.tax_ty_cd != "C":
        return
    cur = str(getattr(item, "kra_vat_cat_cd", None) or "").strip().upper()
    if cur in ("", "B"):
        item.kra_vat_cat_cd = m.vat_cat_cd


def ensure_item_catalog_for_stock_push(
    db: Session,
    *,
    item: Item,
    branch_id: UUID,
    base: str,
    token: str,
    tin: str,
    bhf_id: str,
    cmc_key: str,
    apigee_app_id: str,
    timeout: int = 90,
) -> Dict[str, Any]:
    """
    Confirm the item exists on KRA under ``items.kra_item_code`` via ``selectItemList`` only.

    Stock IO (`insertStockIO` / ``saveStockMaster``) does not require ``saveItem``. Calling full
    ``sync_item_to_kra`` here can hit ``saveItem`` and allocate/advance itemCd sequence. For stock
    operations we must be read-only with respect to itemCd: use the stored code or fail fast so
    operators can run explicit item sync / catalog refresh manually.
    """
    kra_cd = (item.kra_item_code or "").strip().upper()
    if not _is_kra_item_code_valid(kra_cd):
        return {
            "ok": False,
            "error": (
                "item_missing_or_invalid_kra_item_code:"
                " stock/reconcile will not auto-register or change itemCd; "
                "open the item and run Sync to KRA explicitly."
            ),
        }

    rows = _fetch_item_list(
        base=base,
        token=token,
        tin=tin,
        bhf_id=bhf_id,
        cmc_key=cmc_key,
        apigee_app_id=apigee_app_id,
        timeout=timeout,
        item_cd=kra_cd,
    )
    hit = _pick_item_row_by_cd(rows, kra_cd)
    if hit:
        apply_kra_select_item_list_row(item, hit)
        db.flush()
        return {
            "ok": True,
            "result_msg": "catalog_probe_stock_push",
            "http_status": 200,
        }

    return {
        "ok": False,
        "error": (
            f"kra_catalog_missing_item_cd:{kra_cd} "
            "(itemCd not returned by selectItemList — open the item and run Sync to KRA, or verify the code in eTIMS)."
        ),
    }


def refresh_item_kra_catalog_fields(
    db: Session,
    *,
    item_id: UUID,
    company_id: UUID,
    branch_id: UUID,
    timeout: int = 60,
) -> Dict[str, Any]:
    """
    HTTP-only: ``selectItemList`` with ``itemCd`` = ``items.kra_item_code``, apply row to Item.
    Does not call ``saveItem``. Use after KRA registration changes or to fix local tax/class drift.
    """
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
    apigee_app_id = (getattr(creds, "apigee_app_id", None) or "").strip()
    if not apigee_app_id:
        return {"ok": False, "error": "apigee_app_id_missing"}
    cmc = get_cmc_key_plain(creds)
    if not cmc:
        return {"ok": False, "error": "cmc_missing"}
    user, password = get_oauth_username_password(creds)
    if not user or not password:
        return {"ok": False, "error": "oauth_missing"}

    existing_cd = (item.kra_item_code or "").strip().upper()
    if not existing_cd or not _is_kra_item_code_valid(existing_cd):
        return {"ok": False, "error": "item_missing_kra_item_code"}

    env_eff = effective_etims_environment(creds)
    base = api_base_for_branch_credentials(env_eff)
    try:
        token = get_access_token(
            api_base=base,
            username=user,
            password=password,
            timeout=45,
            environment=env_eff,
        )
    except Exception as e:
        return {"ok": False, "error": f"oauth_failed:{str(e)[:200]}"}

    rows = _fetch_item_list(
        base=base,
        token=token,
        tin=tin,
        bhf_id=str(creds.kra_bhf_id).strip(),
        cmc_key=cmc,
        apigee_app_id=apigee_app_id,
        timeout=timeout,
        item_cd=existing_cd,
    )
    hit = _pick_item_row_by_cd(rows, existing_cd)
    if not hit:
        return {"ok": False, "error": "catalog_row_not_found", "item_cd": existing_cd}

    apply_kra_select_item_list_row(item, hit, allow_item_code_update=False)
    db.flush()
    _persist_item_kra_last_sync_detail(
        item,
        branch_id=branch_id,
        ok=True,
        sync_path="catalog_refresh_only",
        save_item_called=False,
        result_msg="kra_catalog_refresh",
        http_status=200,
    )
    db.flush()
    return {"ok": True, "item_cd": existing_cd, "catalog_row": hit}


def _choose_item_cls_and_tax(
    item_cls_list: list[dict],
    *,
    preferred_tax_ty_cd: str | None = None,
) -> tuple[str, str] | None:
    """
    Pick (itemClsCd, taxTyCd) from OSCU ``selectItemClsList`` rows.

    When ``preferred_tax_ty_cd`` is set (e.g. ``C`` for zero-rated PharmaSight VAT), prefer a class row
    whose ``taxTyCd`` matches before falling back to ``_ITEM_CLASS_PREF_ORDER`` (sandbox often lists
    ``1010000000`` with ``A`` and another class with ``C``).
    """
    by_cd: dict[str, str] = {}
    for row in item_cls_list:
        icd = str(row.get("itemClsCd") or "").strip()
        tty = str(row.get("taxTyCd") or "").strip().upper()
        if icd and tty:
            by_cd[icd] = tty
    pref = (preferred_tax_ty_cd or "").strip().upper()
    if pref:
        for want in _ITEM_CLASS_PREF_ORDER:
            if want in by_cd and by_cd[want] == pref:
                return want, by_cd[want]
        for icd, tty in sorted(by_cd.items()):
            if tty == pref:
                return icd, tty
    for want in _ITEM_CLASS_PREF_ORDER:
        if want in by_cd:
            return want, by_cd[want]
    for icd, tty in by_cd.items():
        return icd, tty
    return None


def _fetch_item_cls_and_tax(
    *,
    base: str,
    token: str,
    tin: str,
    bhf_id: str,
    cmc_key: str,
    apigee_app_id: str,
    timeout: int,
    preferred_tax_ty_cd: str | None = None,
) -> tuple[str, str] | None:
    r = requests.post(
        f"{base}{SELECT_ITEM_CLASS_LIST_PATH}",
        json={"tin": tin, "bhfId": bhf_id, "lastReqDt": "20100101000000"},
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "tin": tin,
            "bhfId": bhf_id,
            "cmcKey": cmc_key,
            "apigee_app_id": apigee_app_id,
        },
        timeout=timeout,
    )
    if r.status_code >= 400:
        return None
    parsed = r.json() if (r.text or "").strip() else None
    return _choose_item_cls_and_tax(
        _extract_item_cls_list(parsed),
        preferred_tax_ty_cd=preferred_tax_ty_cd,
    )


def build_save_item_payload(db: Session, item: Item) -> Dict[str, Any]:
    mapping = map_vat_to_etims_category(
        vat_category=getattr(item, "vat_category", None),
        vat_rate_percent=float(getattr(item, "vat_rate", 0) or 0),
    )
    # PharmaSight VAT drives saveItem taxTyCd; KRA catalog copies overwrite ``items.kra_*`` after sync / lookup.
    tax_ty = mapping.tax_ty_cd

    item_ty_cd = "2"
    pkg_unit_cd = _norm_unit_code(item.kra_pkg_unit_cd, "NT")
    qty_unit_cd = _norm_qty_unit_code(item.kra_qty_unit_cd)
    code_prefix = _item_cd_prefix(item_ty_cd=item_ty_cd, pkg_unit_cd=pkg_unit_cd, qty_unit_cd=qty_unit_cd)
    item_cd = (item.kra_item_code or "").strip().upper()
    # Never replace a syntactically valid KRA itemCd with _next_kra_item_code: local max-suffix
    # often disagrees with KRA's sequence ("Invalid itemCd Sequence"). Registration only when absent/invalid.
    if not _is_kra_item_code_valid(item_cd):
        item_cd = _next_kra_item_code(db, company_id=item.company_id, prefix=code_prefix)
    payload: Dict[str, Any] = {
        "itemCd": item_cd,
        "itemClsCd": (item.kra_item_cls_cd or "50302517").strip(),
        "itemTyCd": item_ty_cd,
        "itemNm": (item.name or "ITEM").strip()[:200],
        "orgnNatCd": "KE",
        "pkgUnitCd": pkg_unit_cd,
        "qtyUnitCd": qty_unit_cd,
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


def _ps_vat_mapping_for_item(item: Item):
    return map_vat_to_etims_category(
        vat_category=getattr(item, "vat_category", None),
        vat_rate_percent=float(getattr(item, "vat_rate", 0) or 0),
    )


def _kra_catalog_row_matches_ps_mapping(item: Item, row: dict | None) -> bool:
    """True when KRA selectItemList row tax/vat matches PharmaSight item VAT (same rules as saveItem payload)."""
    if not row or not isinstance(row, dict):
        return False
    m = _ps_vat_mapping_for_item(item)
    tty = str(row.get("taxTyCd") or "").strip().upper()
    vcat = str(row.get("vatCatCd") or row.get("vat_cat_cd") or "").strip().upper()
    if not tty:
        return False
    if tty != m.tax_ty_cd:
        return False
    if vcat and vcat != m.vat_cat_cd:
        return False
    return True


def _item_kra_columns_match_ps_mapping(item: Item) -> bool:
    """True when persisted kra_tax_ty_cd / kra_vat_cat_cd match PharmaSight VAT (after any catalog hydrate)."""
    m = _ps_vat_mapping_for_item(item)
    tty = str(getattr(item, "kra_tax_ty_cd", None) or "").strip().upper()
    vcat = str(getattr(item, "kra_vat_cat_cd", None) or "").strip().upper()
    if not tty:
        return False
    if tty != m.tax_ty_cd:
        return False
    if vcat and vcat != m.vat_cat_cd:
        return False
    return True


def _persist_item_kra_last_sync_detail(
    item: Item,
    *,
    branch_id: UUID,
    ok: bool,
    sync_path: str,
    save_item_called: bool,
    result_msg: str | None = None,
    result_cd: str | None = None,
    http_status: int | None = None,
    error_summary: str | None = None,
    payload_tax_ty_cd: str | None = None,
) -> None:
    """
    Persist one structured audit row for the item edit screen (whether saveItem ran vs lookup-only, VAT match).

    ``sync_path`` examples: ``blocked_before_http``, ``already_synced_no_changes``,
    ``catalog_lookup_aligned_no_save_item``, ``save_item_success``, ``save_item_failed``, ``exception``.
    """
    m = _ps_vat_mapping_for_item(item)
    kra_tty = str(getattr(item, "kra_tax_ty_cd", None) or "").strip().upper()
    kra_vcat = str(getattr(item, "kra_vat_cat_cd", None) or "").strip().upper()
    vat_aligned = bool(kra_tty) and kra_tty == m.tax_ty_cd and (not kra_vcat or kra_vcat == m.vat_cat_cd)

    user_hint: str | None = None
    if ok and vat_aligned:
        if sync_path == "catalog_lookup_aligned_no_save_item":
            user_hint = (
                "KRA catalogue already matched PharmaSight VAT (same taxTyCd/vatCatCd). "
                "saveItem was not needed — this is correct."
            )
        elif sync_path == "save_item_success":
            user_hint = (
                "saveItem ran successfully and catalogue fields were refreshed from KRA. "
                "Your zero-rated / standard mapping should now match selectItemList."
            )
        elif sync_path == "already_synced_no_changes":
            user_hint = (
                "No saveItem call: last payload hash unchanged and catalogue already matched PharmaSight VAT."
            )
        elif sync_path == "catalog_refresh_only":
            user_hint = (
                "selectItemList refresh only — local catalogue columns updated from KRA. "
                "saveItem was not called; use Sync to KRA now to push PharmaSight VAT when you need KRA to change."
            )
    elif ok and not vat_aligned:
        if sync_path == "catalog_lookup_aligned_no_save_item":
            user_hint = (
                "Inconsistent: sync reported catalog lookup success but stored taxTyCd still differs from PharmaSight. "
                "Use an updated backend (lookup shortcut only when VAT matches) and re-sync."
            )
        elif sync_path == "save_item_success":
            user_hint = (
                "saveItem succeeded but catalogue tax codes still differ from PharmaSight after refresh. "
                "KRA may refuse changing tax type on this itemCd — check the eTIMS portal or register a new item code."
            )
        else:
            user_hint = "Sync reported OK but VAT alignment failed; compare PharmaSight VAT to kra_catalog_snapshot."
    elif not ok:
        user_hint = error_summary or result_msg or "Sync did not finish; see Error above or branch row."

    detail: Dict[str, Any] = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "branch_id": str(branch_id),
        "ok": ok,
        "sync_path": sync_path,
        "save_item_called": save_item_called,
        "result_msg": result_msg,
        "result_cd": result_cd,
        "http_status": http_status,
        "pharmasight_tax_ty_cd": m.tax_ty_cd,
        "pharmasight_vat_cat_cd": m.vat_cat_cd,
        "catalog_tax_ty_cd": kra_tty or None,
        "catalog_vat_cat_cd": kra_vcat or None,
        "vat_aligned": vat_aligned,
        "payload_tax_ty_cd_sent": payload_tax_ty_cd,
        "user_hint": user_hint,
    }
    try:
        item.kra_last_sync_detail = json.loads(json.dumps(detail, default=str))
    except (TypeError, ValueError):
        item.kra_last_sync_detail = detail


def _payload_hash(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _extract_result_msg(parsed: Dict[str, Any] | None) -> str | None:
    if not isinstance(parsed, dict):
        return None
    for k in ("resultMsg", "resultMessage", "msg", "message"):
        v = parsed.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    data = parsed.get("data")
    if isinstance(data, dict):
        for k in ("resultMsg", "resultMessage", "msg", "message"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                return v.strip()
    return None


def _extract_header_error_msg(parsed: Dict[str, Any] | None) -> str | None:
    """Extract KRA gateway error text commonly sent in responseHeader on HTTP 400."""
    if not isinstance(parsed, dict):
        return None
    hdr = parsed.get("responseHeader") or parsed.get("header")
    if not isinstance(hdr, dict):
        return None
    parts = []
    for k in ("customerMessage", "debugMessage", "resultMsg", "message"):
        v = hdr.get(k)
        if isinstance(v, str) and v.strip():
            parts.append(v.strip())
    if not parts:
        return None
    return " | ".join(parts)


def _is_successful_response_without_result_cd(parsed: Dict[str, Any] | None, http_status: int) -> bool:
    """
    Some saveItem envelopes return success in responseHeader without resultCd.
    Accept this gava-style variant when HTTP is 2xx and header indicates success.
    """
    if not (200 <= int(http_status or 0) < 300):
        return False
    if not isinstance(parsed, dict):
        return False
    hdr = parsed.get("responseHeader") or parsed.get("header")
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
        _persist_item_kra_last_sync_detail(
            item,
            branch_id=branch_id,
            ok=False,
            sync_path="blocked_before_http",
            save_item_called=False,
            result_msg="branch_kra_not_enabled",
            error_summary="Branch KRA credentials missing or disabled.",
        )
        return {"ok": False, "error": "branch_kra_not_enabled"}

    company = db.query(Company).filter(Company.id == company_id).first()
    tin = ((getattr(creds, "client_tax_pin", None) or "") if creds else "") or ((company.pin if company else "") or "")
    tin = str(tin or "").strip()
    if not tin:
        _persist_item_kra_last_sync_detail(
            item,
            branch_id=branch_id,
            ok=False,
            sync_path="blocked_before_http",
            save_item_called=False,
            result_msg="company_tin_missing",
            error_summary="Company TIN / client tax PIN missing for OSCU.",
        )
        return {"ok": False, "error": "company_tin_missing"}
    if not (creds.kra_bhf_id and str(creds.kra_bhf_id).strip()):
        _persist_item_kra_last_sync_detail(
            item,
            branch_id=branch_id,
            ok=False,
            sync_path="blocked_before_http",
            save_item_called=False,
            result_msg="branch_bhf_missing",
            error_summary="Branch bhfId missing on eTIMS credentials.",
        )
        return {"ok": False, "error": "branch_bhf_missing"}
    apigee_app_id = (getattr(creds, "apigee_app_id", None) or "").strip()
    if not apigee_app_id:
        _persist_item_kra_last_sync_detail(
            item,
            branch_id=branch_id,
            ok=False,
            sync_path="blocked_before_http",
            save_item_called=False,
            result_msg="apigee_app_id_missing",
            error_summary="Apigee app id missing on branch credentials.",
        )
        return {"ok": False, "error": "apigee_app_id_missing"}
    cmc = get_cmc_key_plain(creds)
    if not cmc:
        _persist_item_kra_last_sync_detail(
            item,
            branch_id=branch_id,
            ok=False,
            sync_path="blocked_before_http",
            save_item_called=False,
            result_msg="cmc_missing",
            error_summary="CMC key missing or not decryptable.",
        )
        return {"ok": False, "error": "cmc_missing"}
    user, password = get_oauth_username_password(creds)
    if not user or not password:
        _persist_item_kra_last_sync_detail(
            item,
            branch_id=branch_id,
            ok=False,
            sync_path="blocked_before_http",
            save_item_called=False,
            result_msg="oauth_missing",
            error_summary="OAuth username/password missing on branch credentials.",
        )
        return {"ok": False, "error": "oauth_missing"}

    env_eff = effective_etims_environment(creds)
    base = api_base_for_branch_credentials(env_eff)
    try:
        token = get_access_token(
            api_base=base,
            username=user,
            password=password,
            timeout=45,
            environment=env_eff,
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
            "tin": tin,
            "bhfId": str(creds.kra_bhf_id).strip(),
            "cmcKey": cmc,
            "apigee_app_id": apigee_app_id,
        }
        bhf_s = str(creds.kra_bhf_id).strip()
        # Authoritative catalog row for known itemCd (gavaetims: selectItemList + itemCd in POST body).
        existing_cd = (item.kra_item_code or "").strip().upper()
        had_kra_catalog_hit = False
        if existing_cd and _is_kra_item_code_valid(existing_cd):
            targeted_rows = _fetch_item_list(
                base=base,
                token=token,
                tin=tin,
                bhf_id=bhf_s,
                cmc_key=cmc,
                apigee_app_id=apigee_app_id,
                timeout=timeout,
                item_cd=existing_cd,
            )
            targeted_hit = _pick_item_row_by_cd(targeted_rows, existing_cd)
            if targeted_hit:
                had_kra_catalog_hit = True
                apply_kra_select_item_list_row(item, targeted_hit, allow_item_code_update=False)
                db.flush()

        payload = build_save_item_payload(db, item)
        p_hash = _payload_hash(payload)
        # Idempotency: same saveItem body *and* KRA catalog columns already match PharmaSight VAT.
        # Without the alignment check, selectItemList hydrate can set kra_tax_ty_cd to stale KRA values while
        # kra_payload_hash still matches the desired payload — then we skip saveItem and invoice submit fails.
        if (
            str(getattr(item, "kra_sync_status", "") or "").strip().lower() == "synced"
            and not bool(getattr(item, "kra_needs_resync", False))
            and bool(getattr(item, "kra_synced_at", None))
            and str(getattr(item, "kra_payload_hash", "") or "").strip() == p_hash
            and _item_kra_columns_match_ps_mapping(item)
        ):
            _persist_item_kra_last_sync_detail(
                item,
                branch_id=branch_id,
                ok=True,
                sync_path="already_synced_no_changes",
                save_item_called=False,
                result_msg="already_synced_no_changes",
                result_cd="000",
                http_status=200,
            )
            db.flush()
            return {
                "ok": True,
                "result_cd": "000",
                "result_msg": "already_synced_no_changes",
                "http_status": 200,
                "response_payload_json": None,
            }

        if not _is_kra_item_code_valid(existing_cd):
            _audit_kra_item_code_update(item, str(payload.get("itemCd") or "").strip(), reason="sync_item_to_kra_payload_seed")
        item.kra_last_attempt_at = datetime.now(timezone.utc)
        item.kra_sync_attempt_count = int(item.kra_sync_attempt_count or 0) + 1
        item.kra_sync_status = "syncing"
        db.flush()

        # Lookup-first behavior: if item already exists in KRA catalog, do not re-register.
        item_list = _fetch_item_list(
            base=base,
            token=token,
            tin=tin,
            bhf_id=bhf_s,
            cmc_key=cmc,
            apigee_app_id=apigee_app_id,
            timeout=timeout,
        )
        payload_item_cd = str(payload.get("itemCd") or "").strip().upper()
        payload_item_nm = str(payload.get("itemNm") or "").strip().upper()
        matched_row = None
        for row in item_list:
            cd = str(row.get("itemCd") or "").strip().upper()
            nm = str(row.get("itemNm") or "").strip().upper()
            if payload_item_cd and cd == payload_item_cd:
                matched_row = row
                break
            # Name-based fallback is only safe before first KRA itemCd is established.
            if (not _is_kra_item_code_valid(existing_cd)) and payload_item_nm and nm and nm == payload_item_nm:
                matched_row = row
                break
        # Lookup shortcut only when KRA row already matches PharmaSight VAT; otherwise saveItem must run
        # to update the KRA master (otherwise re-sync never pushes taxTyCd / vatCatCd).
        if matched_row and _kra_catalog_row_matches_ps_mapping(item, matched_row):
            apply_kra_select_item_list_row(item, matched_row, allow_item_code_update=False)
            db.flush()
            payload_m = build_save_item_payload(db, item)
            p_hash_m = _payload_hash(payload_m)
            item.kra_payload_hash = p_hash_m
            item.kra_sync_status = "synced"
            item.kra_sync_error = None
            item.kra_synced_at = datetime.now(timezone.utc)
            item.kra_needs_resync = False
            db.flush()
            _persist_item_kra_last_sync_detail(
                item,
                branch_id=branch_id,
                ok=True,
                sync_path="catalog_lookup_aligned_no_save_item",
                save_item_called=False,
                result_msg="already_registered_lookup_match",
                result_cd="000",
                http_status=200,
            )
            db.flush()
            return {
                "ok": True,
                "result_cd": "000",
                "result_msg": "already_registered_lookup_match",
                "http_status": 200,
                "response_payload_json": {"itemListMatch": matched_row},
            }
        # gavaetims-style alignment: if item class is missing/legacy-invalid, resolve from selectItemClsList.
        cls_in = str(payload.get("itemClsCd") or "").strip()
        if not cls_in or cls_in == "50302517":
            cls_pick = _fetch_item_cls_and_tax(
                base=base,
                token=token,
                tin=tin,
                bhf_id=str(creds.kra_bhf_id).strip(),
                cmc_key=cmc,
                apigee_app_id=apigee_app_id,
                timeout=timeout,
                preferred_tax_ty_cd=str(payload.get("taxTyCd") or "").strip().upper() or None,
            )
            if cls_pick:
                payload["itemClsCd"] = cls_pick[0]
                # Do not set ``payload["taxTyCd"]`` from the class list. ``build_save_item_payload`` already
                # derives ``taxTyCd`` from PharmaSight ``vat_category`` / ``vat_rate``. OSCU class rows often
                # default to standard-rated (``A``), which incorrectly registers zero-rated items and later
                # fails invoice submit (KRA catalogue ``A`` vs PharmaSight ``C`` guard).
        r = requests.post(
            f"{base}{SAVE_ITEM_PATH}",
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        parsed = r.json() if (r.text or "").strip() else None
        rc = find_etims_result_cd(parsed) if isinstance(parsed, dict) else None
        msg = _extract_result_msg(parsed if isinstance(parsed, dict) else None)
        hdr_msg = _extract_header_error_msg(parsed if isinstance(parsed, dict) else None)
        msg_eff = msg or hdr_msg
        if not msg_eff and (r.text or "").strip():
            # Last-resort visibility when gateway returns non-JSON errors.
            msg_eff = (r.text or "").strip()[:500]
        ok = ((200 <= r.status_code < 300) and (rc == "000")) or (
            rc is None and _is_successful_response_without_result_cd(parsed if isinstance(parsed, dict) else None, r.status_code)
        )
        if ok:
            tty_sent = str(payload.get("taxTyCd") or "").strip().upper()
            if tty_sent:
                item.kra_tax_ty_cd = tty_sent
            cls_sent = str(payload.get("itemClsCd") or "").strip()
            if cls_sent:
                item.kra_item_cls_cd = cls_sent
            sent_cd = str(payload.get("itemCd") or "").strip().upper()
            if sent_cd:
                _audit_kra_item_code_update(item, sent_cd, reason="sync_item_to_kra_save_item_success")
            cd_final = (item.kra_item_code or "").strip().upper()
            if cd_final and _is_kra_item_code_valid(cd_final):
                rows_done = _fetch_item_list(
                    base=base,
                    token=token,
                    tin=tin,
                    bhf_id=bhf_s,
                    cmc_key=cmc,
                    apigee_app_id=apigee_app_id,
                    timeout=timeout,
                    item_cd=cd_final,
                )
                hit_done = _pick_item_row_by_cd(rows_done, cd_final)
                if hit_done:
                    apply_kra_select_item_list_row(item, hit_done, allow_item_code_update=False)
            payload_final = build_save_item_payload(db, item)
            item.kra_payload_hash = _payload_hash(payload_final)
            item.kra_sync_status = "synced"
            item.kra_sync_error = None
            item.kra_synced_at = datetime.now(timezone.utc)
            item.kra_needs_resync = False
            db.flush()
            _persist_item_kra_last_sync_detail(
                item,
                branch_id=branch_id,
                ok=True,
                sync_path="save_item_success",
                save_item_called=True,
                result_msg=msg_eff,
                result_cd=str(rc) if rc is not None else None,
                http_status=r.status_code,
                payload_tax_ty_cd=tty_sent or None,
            )
            db.flush()
            return {
                "ok": True,
                "result_cd": rc,
                "result_msg": msg_eff,
                "http_status": r.status_code,
                "response_payload_json": parsed if isinstance(parsed, dict) else None,
            }
        item.kra_sync_status = "failed"
        item_cd_sent = str(payload.get("itemCd") or "").strip().upper()
        msg_l = (msg_eff or "").lower()
        seq_fail = "invalid itemcd sequence" in msg_l or "expected sequence ending with" in msg_l
        non_retryable = False
        suggested_cd = _suggested_item_cd_after_sequence_error(item_cd_sent, msg_eff)

        portal_tail = (
            " KRA already has this itemCd in SIM; changing tax (e.g. A→C) is often rejected with a sequence "
            f"message. Fix tax in the eTIMS portal for {item_cd_sent}, or create a new PharmaSight item to get "
            "a new KRA itemCd (handle stock on the old code per KRA rules)."
        )
        if seq_fail and had_kra_catalog_hit and item_cd_sent == existing_cd:
            non_retryable = True
            item.kra_sync_error = (
                f"saveItem_failed http={r.status_code} rc={rc or 'none'} msg={(msg_eff or 'none')[:220]}"
                + portal_tail
            )[:900]
            item.kra_needs_resync = True
            logger.warning(
                "saveItem sequence rejected for existing catalog itemCd item_id=%s itemCd=%s suggested_next=%s",
                item.id,
                item_cd_sent,
                suggested_cd,
            )
        elif seq_fail and (not had_kra_catalog_hit) and suggested_cd and suggested_cd != item_cd_sent:
            # First-time registration: KRA wants the next suffix; advance local itemCd so the next sync posts it.
            _audit_kra_item_code_update(item, suggested_cd, reason="kra_save_item_sequence_recovery")
            item.kra_sync_error = (
                f"saveItem_failed http={r.status_code} rc={rc or 'none'} msg={(msg_eff or 'none')[:220]} "
                f"— local itemCd advanced to {suggested_cd}; run Sync to KRA again."
            )[:900]
            item.kra_needs_resync = True
            logger.warning(
                "saveItem sequence recovery advanced itemCd item_id=%s from=%s to=%s",
                item.id,
                item_cd_sent,
                suggested_cd,
            )
        else:
            if suggested_cd:
                logger.warning(
                    "saveItem sequence hint observed; preserving current kra_item_code item_id=%s sent_code=%s suggested_next=%s",
                    item.id,
                    item_cd_sent,
                    suggested_cd,
                )
            item.kra_sync_error = f"saveItem_failed http={r.status_code} rc={rc or 'none'} msg={(msg_eff or 'none')[:220]}"
            item.kra_needs_resync = True
        db.flush()
        tty_fail = str(payload.get("taxTyCd") or "").strip().upper() or None
        _persist_item_kra_last_sync_detail(
            item,
            branch_id=branch_id,
            ok=False,
            sync_path="save_item_failed",
            save_item_called=True,
            result_msg=msg_eff,
            result_cd=str(rc) if rc is not None else None,
            http_status=r.status_code,
            error_summary=item.kra_sync_error,
            payload_tax_ty_cd=tty_fail,
        )
        db.flush()
        return {
            "ok": False,
            "error": item.kra_sync_error,
            "non_retryable": non_retryable,
            "result_cd": rc,
            "result_msg": msg_eff,
            "http_status": r.status_code,
            "response_payload_json": parsed if isinstance(parsed, dict) else None,
        }
    except Exception as e:
        item.kra_sync_status = "failed"
        item.kra_sync_error = f"saveItem_exception: {str(e)[:300]}"
        item.kra_needs_resync = True
        db.flush()
        _persist_item_kra_last_sync_detail(
            item,
            branch_id=branch_id,
            ok=False,
            sync_path="exception",
            save_item_called=False,
            error_summary=item.kra_sync_error,
        )
        db.flush()
        return {"ok": False, "error": item.kra_sync_error}

