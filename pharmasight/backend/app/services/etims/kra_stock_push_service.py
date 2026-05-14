"""
Push PharmaSight stock-in movements to KRA OSCU: ``insertStockIO`` (inbound) + ``saveStockMaster``.

Persists SAR sequence on ``branch_etims_credentials.kra_last_stock_io_sar_no`` and mirrors KRA ``rsdQty``
on ``item_branch_kra_sync.kra_stock_rsd_qty`` after a successful pair (supports retries).

Root ``sarTyCd`` and line ``ioTyCd`` are chosen from the ledger (see ``kra_insert_stock_io_codes_for_positive_ledger``).
Negative quantities and most outbound flows are **not** ``insertStockIO`` here — they use ``inventory.stock_ledger_align``
(``saveStockMaster`` only), which is a separate lifecycle gap until KRA-outbound IO is modeled.

Customs-sourced lines may need ``sarTyCd=01`` **and** KRA's import API prelude (``selectImportItemList`` through
``updateImportItem``) before OSCU accepts stock — only ``reference_type`` hints switch SAR to import today;
full import orchestration is not in this service (see ``constants``).
"""
from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from uuid import UUID

import requests
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.attributes import flag_modified

from app.config import settings
from app.models.company import BranchEtimsCredentials, Company
from app.models.inventory import InventoryLedger
from app.models.purchase import GRN, SupplierInvoice
from app.models.item import Item, ItemBranchKraSync
from app.models.kra_event_outbox import KraEventOutbox
from app.services.etims.branch_credentials import (
    effective_etims_environment,
    get_cmc_key_plain,
    get_oauth_username_password,
)
from app.services.etims.codes_service import map_item_master_vat_to_etims_category
from app.services.etims.constants import (
    INSERT_STOCK_IO_PATH,
    INSERT_STOCK_IO_SAR_TY_ADJUSTMENT,
    INSERT_STOCK_IO_SAR_TY_IMPORT,
    INSERT_STOCK_IO_SAR_TY_PURCHASE,
    INSERT_STOCK_IO_SAR_TY_STOCK_MOVEMENT,
    SAVE_STOCK_MASTER_PATH,
    SELECT_STOCK_MASTER_PATH,
    SELECT_STOCK_MOVE_LIST_PATH,
)
from app.services.etims.etims_invoice_payload_builder import (
    _norm_pkg_unit_sale,
    _norm_qty_unit_sale,
    _stock_io_line_amounts_for_tax_ty,
)
from app.services.etims.etims_invoice_submitter import api_base_for_branch_credentials, find_etims_result_cd
from app.services.etims.etims_oauth_client import get_access_token
from app.services.inventory_service import InventoryService

logger = logging.getLogger(__name__)

_STOCK_IN_TRANSACTION_TYPES = frozenset(
    {
        "PURCHASE",
        "TRANSFER_IN",
        "SALE_RETURN",
        "OPENING_BALANCE",
        "ADJUSTMENT",
    }
)


def _reference_type_implies_kra_import_sar(reference_type: str | None) -> bool:
    """Heuristic until purchase/GRN models persist an explicit import/customs flag."""
    r = (reference_type or "").strip().upper()
    if not r:
        return False
    if "IMPORT" in r or "CUSTOMS" in r or "DECLARATION" in r or "KRA_IMPT" in r:
        return True
    return r in {"CIM", "IMPT", "IMPT_DECL"}


def sar_ty_cd_for_positive_stock_in(ledger: InventoryLedger) -> str:
    """
    KRA ``insertStockIO`` root ``sarTyCd`` (stock I/O document type).

    Code meanings from gavaetims / portal: ``01`` Import, ``02`` Purchase, ``04`` Stock movement, ``06`` Adjustment.
    ``reference_type`` can force ``01`` when the row is clearly customs/import-tagged (heuristic).
    """
    if _reference_type_implies_kra_import_sar(getattr(ledger, "reference_type", None)):
        return INSERT_STOCK_IO_SAR_TY_IMPORT
    tt = (ledger.transaction_type or "").strip().upper()
    if tt == "PURCHASE":
        return INSERT_STOCK_IO_SAR_TY_PURCHASE
    if tt == "OPENING_BALANCE":
        return INSERT_STOCK_IO_SAR_TY_ADJUSTMENT
    if tt == "ADJUSTMENT":
        return INSERT_STOCK_IO_SAR_TY_ADJUSTMENT
    if tt == "TRANSFER_IN":
        return INSERT_STOCK_IO_SAR_TY_STOCK_MOVEMENT
    if tt == "SALE_RETURN":
        return INSERT_STOCK_IO_SAR_TY_STOCK_MOVEMENT
    return INSERT_STOCK_IO_SAR_TY_PURCHASE


def kra_insert_stock_io_codes_for_positive_ledger(ledger: InventoryLedger) -> tuple[str, str]:
    """``(sarTyCd, ioTyCd)`` for one positive stock-in ``InventoryLedger`` row."""
    return (sar_ty_cd_for_positive_stock_in(ledger), io_ty_cd_for_positive_stock_in(ledger.transaction_type))


def io_ty_cd_for_positive_stock_in(transaction_type: str | None) -> str:
    """
    KRA ``insertStockIO`` line ``ioTyCd`` (OSCU). Missing/wrong values can default movement direction wrong on SBX
    (gavaetims: missing ioTyCd defaults to OUT; ``1`` = stock IN).

    ``gavaetims`` minimal ledger matrix treats ``ioTyCd="3"`` as adjustment vs ``"1"`` as baseline inbound.
    We map inventory **positive** stock-in ledger rows only (see ``should_enqueue_kra_stock_in``).
    """
    tt = (transaction_type or "").strip().upper()
    if tt == "ADJUSTMENT":
        return "3"
    if tt in _STOCK_IN_TRANSACTION_TYPES:
        return "1"
    return "1"


def kra_expected_next_sar_no_from_message(msg: str | None) -> int | None:
    """Parse ``Invalid sarNo: Expected: X but found: Y`` (gavaetims-aligned)."""
    if not msg:
        return None
    m = re.search(r"Invalid\s+sarNo:\s*Expected:\s*(\d+)\s+but\s+found:\s*\d+", msg, re.IGNORECASE)
    if not m:
        m = re.search(r"Expected:\s*(\d+)\s+but\s+found:\s*\d+", msg, re.IGNORECASE)
    if not m:
        return None
    try:
        v = int(m.group(1))
        return v if v >= 1 else None
    except ValueError:
        return None


def kra_expected_rsd_qty_from_mismatch_message(msg: str | None) -> float | None:
    """
    Parse KRA ``rsdQty mismatch`` style text for ``Expected: <n>`` (``kra_min.py`` / certification runners).

    Only used after ``saveStockMaster`` failure so SAR-only ``Expected:`` lines are not confused here.
    """
    if not msg:
        return None
    low = msg.lower()
    if "mismatch" not in low and "rsdqty" not in low.replace(" ", ""):
        return None
    m = re.search(r"Expected:\s*(\d+(?:\.\d+)?)\b", msg, re.IGNORECASE)
    if not m:
        return None
    try:
        v = float(m.group(1))
        return v if v >= 0 else None
    except ValueError:
        return None


def _post_save_stock_master_with_rsd_mismatch_retry(
    *,
    base: str,
    hdr_common: dict[str, str],
    kra_cd: str,
    rsd_qty: float,
    timeout: int,
    allow_mismatch_expected_retry: bool = True,
) -> tuple[bool, int, dict | None, float, str | None]:
    """
    POST ``saveStockMaster``. On failure, if body hints ``rsdQty mismatch`` / ``Expected:``,
    retry once with that quantity (same pattern as ``kra_min.py``) when ``allow_mismatch_expected_retry``.

    When ``allow_mismatch_expected_retry`` is False (e.g. posting PharmaSight ledger truth), a single
    POST is made so we do not accept an ``Expected:`` hint that would move OSCU away from ledger.
    """
    url_sm = f"{base.rstrip('/')}{SAVE_STOCK_MASTER_PATH}"
    sm_payload: dict[str, Any] = {
        "itemCd": kra_cd.strip().upper(),
        "rsdQty": round(float(rsd_qty), 4),
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
    }
    last_parsed: dict | None = None
    last_status = 0
    last_err: str | None = None
    max_attempts = 2 if allow_mismatch_expected_retry else 1
    for attempt in range(max_attempts):
        try:
            r_sm = requests.post(url_sm, headers=hdr_common, json=sm_payload, timeout=timeout)
        except requests.RequestException as e:
            return False, 0, None, float(sm_payload["rsdQty"]), f"save_stock_master_transport:{e}"
        last_status = int(r_sm.status_code)
        parsed_sm = r_sm.json() if (r_sm.text or "").strip() else None
        last_parsed = parsed_sm if isinstance(parsed_sm, dict) else None
        if _post_ok(last_parsed, r_sm.status_code):
            return True, last_status, last_parsed, float(sm_payload["rsdQty"]), None
        err_txt = _hdr_err(last_parsed) or (r_sm.text or "")[:1200]
        last_err = err_txt
        if attempt == 0 and allow_mismatch_expected_retry:
            exp = kra_expected_rsd_qty_from_mismatch_message(err_txt)
            if exp is not None and abs(float(exp) - float(sm_payload["rsdQty"])) > 1e-6:
                sm_payload["rsdQty"] = round(float(exp), 4)
                continue
        break
    return False, last_status, last_parsed, float(sm_payload["rsdQty"]), f"save_stock_master_failed:{last_err or 'unknown'}"


def _norm_tty(val: object | None) -> str:
    s = str(val or "").strip().upper()
    return s if s else "A"


def _stock_io_tax_ty_cd_for_item(item: Item) -> str:
    """
    ``insertStockIO`` line ``taxTyCd`` must match what ``saveTrnsSalesOsdc`` will use for the same item.

    When ``kra_tax_ty_cd`` is not yet hydrated, the old code defaulted to ``A``, which breaks zero-rated
    pharmacy rows (sales use ``C`` from item VAT) and KRA returns SIM \"not in your stock\".
    """
    s = str(getattr(item, "kra_tax_ty_cd", None) or "").strip().upper()
    if s:
        return _norm_tty(s)
    return _norm_tty(map_item_master_vat_to_etims_category(item).tax_ty_cd)


def _hdr_err(parsed: dict | None) -> str | None:
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
    return " | ".join(parts) if parts else None


def _post_ok(parsed: dict | None, http_status: int) -> bool:
    if 200 <= int(http_status or 0) < 300:
        rc = find_etims_result_cd(parsed if isinstance(parsed, dict) else None)
        if rc == "000":
            return True
        hdr = _hdr_err(parsed if isinstance(parsed, dict) else None)
        if hdr and "success" in hdr.lower():
            return True
    return False


def _extract_stock_master_rsd(parsed: dict | None, want_item_cd: str) -> float | None:
    """Best-effort ``rsdQty`` from ``selectStockMaster`` (gava-style deep walk)."""
    want = (want_item_cd or "").strip().upper()
    if not want:
        return None

    def walk(o: object) -> float | None:
        if isinstance(o, dict):
            ic = str(o.get("itemCd") or "").strip().upper()
            if ic == want:
                for k in ("rsdQty", "stkQty", "qty", "rplQty", "stockQty", "remainQty"):
                    if k in o and o[k] is not None:
                        try:
                            return float(o[k])
                        except (TypeError, ValueError):
                            pass
            for v in o.values():
                r = walk(v)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for x in o:
                r = walk(x)
                if r is not None:
                    return r
        return None

    return walk(parsed)


def _utc_move_list_last_req_dt() -> str:
    """Fresh ``lastReqDt`` for ``selectStockMoveList`` (``YYYYMMDDHHmmss`` UTC)."""
    return datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")


def _first_rsd_qty_in_move_list_tree(parsed: dict | None, want_item_cd: str) -> float | None:
    """
    Depth-first: first **on-hand** quantity on a dict whose ``itemCd`` matches.

    Do **not** read ``qty`` / ``rplQty`` here: on ``selectStockMoveList`` those fields are often the
    **movement** quantity for one IO row (e.g. +1), not remaining stock. Using them for
    ``saveStockMaster`` sets ``rsdQty`` too low and OSDC sales fail with "not in your stock".
    """
    want = (want_item_cd or "").strip().upper()
    if not want or not isinstance(parsed, dict):
        return None

    def walk(o: object) -> float | None:
        if isinstance(o, dict):
            ic = str(o.get("itemCd") or "").strip().upper()
            if ic == want:
                for k in ("rsdQty", "stkQty", "stockQty", "remainQty"):
                    if k in o and o[k] is not None:
                        try:
                            return float(o[k])
                        except (TypeError, ValueError):
                            pass
            for v in o.values():
                r = walk(v)
                if r is not None:
                    return r
        elif isinstance(o, list):
            for x in o:
                r = walk(x)
                if r is not None:
                    return r
        return None

    return walk(parsed)


def fetch_move_list_rsd_qty_for_item(
    *,
    base: str,
    token: str,
    tin: str,
    bhf_id: str,
    cmc_key: str,
    apigee_app_id: str,
    device_serial: str,
    item_cd: str,
    timeout: int,
    probes: int = 3,
    sleep_between_sec: float = 1.0,
) -> float | None:
    """
    ``selectStockMoveList`` with a **fresh UTC** ``lastReqDt`` per probe (gavaetims / ``kra_certify`` pattern).

    Used as a **fallback** when ``selectStockMaster`` has not yet returned a row after ``insertStockIO``.
    Values are parsed conservatively (balance fields only — see ``_first_rsd_qty_in_move_list_tree``).
    """
    want = (item_cd or "").strip().upper()
    if not want:
        return None
    url = f"{base.rstrip('/')}{SELECT_STOCK_MOVE_LIST_PATH}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "tin": tin.strip(),
        "bhfId": bhf_id.strip(),
        "dvcSrlNo": str(device_serial or "").strip(),
        "cmcKey": cmc_key,
    }
    if apigee_app_id:
        headers["apigee_app_id"] = apigee_app_id.strip()
    last: float | None = None
    for i in range(max(1, int(probes))):
        payload = {
            "tin": tin.strip(),
            "bhfId": bhf_id.strip(),
            "lastReqDt": _utc_move_list_last_req_dt(),
            "itemCd": want,
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            parsed = r.json() if (r.text or "").strip() else None
        except requests.RequestException as e:
            logger.warning("selectStockMoveList transport for %s: %s", want, e)
            parsed = None
        if isinstance(parsed, dict):
            got = _first_rsd_qty_in_move_list_tree(parsed, want)
            if got is not None:
                last = float(got)
                break
        if i + 1 < max(1, int(probes)) and sleep_between_sec > 0:
            time.sleep(float(sleep_between_sec))
    return last


def _stock_master_row_rsd(row: dict, want_cd: str) -> float | None:
    if not isinstance(row, dict):
        return None
    if str(row.get("itemCd") or "").strip().upper() != want_cd:
        return None
    for k in ("rsdQty", "stkQty", "qty", "rplQty", "stockQty", "remainQty"):
        if k in row and row[k] is not None:
            try:
                return float(row[k])
            except (TypeError, ValueError):
                pass
    return None


def _extract_rsd_from_stock_master_body(rb: dict, want_cd: str) -> float | None:
    """Parse ``responseBody.data`` variants for ``selectStockMaster``."""
    want = want_cd.strip().upper()
    data = rb.get("data")
    if not isinstance(data, dict):
        return None
    for list_key in ("stockMasterList", "stockMstList", "stockList", "stkMasterList"):
        lst = data.get(list_key)
        if isinstance(lst, list):
            for row in lst:
                r = _stock_master_row_rsd(row, want) if isinstance(row, dict) else None
                if r is not None:
                    return r
    sm = data.get("stockMaster")
    if isinstance(sm, dict):
        r = _stock_master_row_rsd(sm, want)
        if r is not None:
            return r
    if isinstance(sm, list):
        for row in sm:
            r = _stock_master_row_rsd(row, want) if isinstance(row, dict) else None
            if r is not None:
                return r
    return None


def fetch_select_stock_master_rsd_qty(
    *,
    base: str,
    token: str,
    tin: str,
    bhf_id: str,
    cmc_key: str,
    apigee_app_id: str,
    device_serial: str,
    item_cd: str,
    timeout: int,
) -> float | None:
    want = item_cd.strip().upper()
    url = f"{base.rstrip('/')}{SELECT_STOCK_MASTER_PATH}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "tin": tin.strip(),
        "bhfId": bhf_id.strip(),
        "dvcSrlNo": str(device_serial or "").strip(),
        "cmcKey": cmc_key,
    }
    if apigee_app_id:
        headers["apigee_app_id"] = apigee_app_id.strip()
    for lrd in ("20100101000000", _utc_move_list_last_req_dt()):
        payload = {
            "tin": tin.strip(),
            "bhfId": bhf_id.strip(),
            "itemCd": want,
            "lastReqDt": lrd,
        }
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=timeout)
            parsed = r.json() if (r.text or "").strip() else None
        except requests.RequestException as e:
            logger.warning("selectStockMaster failed for %s (lastReqDt=%s): %s", want, lrd, e)
            continue
        if not isinstance(parsed, dict):
            continue
        rb = parsed.get("responseBody")
        if isinstance(rb, dict):
            hit = _extract_rsd_from_stock_master_body(rb, want)
            if hit is not None:
                return hit
        hit = _extract_stock_master_rsd(parsed, want)
        if hit is not None:
            return hit
    return None


def _get_or_create_ib_sync(db: Session, *, company_id: UUID, item_id: UUID, branch_id: UUID) -> ItemBranchKraSync:
    row = (
        db.query(ItemBranchKraSync)
        .filter(ItemBranchKraSync.item_id == item_id, ItemBranchKraSync.branch_id == branch_id)
        .first()
    )
    if row:
        return row
    row = ItemBranchKraSync(company_id=company_id, item_id=item_id, branch_id=branch_id)
    db.add(row)
    db.flush()
    return row


def should_enqueue_kra_stock_in(ledger: InventoryLedger) -> bool:
    if ledger is None:
        return False
    try:
        q = float(ledger.quantity_delta or 0)
    except (TypeError, ValueError):
        return False
    if q <= 0:
        return False
    tt = (ledger.transaction_type or "").strip().upper()
    return tt in _STOCK_IN_TRANSACTION_TYPES


def _insert_stock_io_root_extras_for_ledger(db: Session, ledger: InventoryLedger) -> Dict[str, Any]:
    """
    Optional root fields on ``insertStockIO`` for purchase-style SAR (gavaetims: ``spplrTin`` / ``spplrNm`` on IO root).

    Helps OSCU classify supplier purchases; ``spplrBhfId`` is omitted until we persist supplier branch on KRA.
    """
    out: Dict[str, Any] = {}
    rt = (ledger.reference_type or "").strip().lower()
    rid = getattr(ledger, "reference_id", None)
    cid = getattr(ledger, "company_id", None)
    if rid is None or cid is None:
        return out
    supplier = None
    if rt == "purchase_invoice":
        inv = (
            db.query(SupplierInvoice)
            .options(joinedload(SupplierInvoice.supplier))
            .filter(SupplierInvoice.id == rid, SupplierInvoice.company_id == cid)
            .first()
        )
        if inv:
            supplier = inv.supplier
    elif rt == "grn":
        grn = (
            db.query(GRN)
            .options(joinedload(GRN.supplier))
            .filter(GRN.id == rid, GRN.company_id == cid)
            .first()
        )
        if grn:
            supplier = grn.supplier
    if supplier is None:
        return out
    pin = (getattr(supplier, "pin", None) or "").strip()
    if pin:
        out["spplrTin"] = pin
    nm = (getattr(supplier, "name", None) or "").strip()
    if nm:
        out["spplrNm"] = nm[:200]
    return out


def build_insert_stock_io_payload(
    *,
    tin: str,
    sar_no: int,
    qty_in: float,
    unit_price: float,
    item_cd: str,
    item_nm: str,
    item_cls_cd: str,
    tax_ty_cd: str,
    pkg_unit_cd: str,
    qty_unit_cd: str,
    io_ty_cd: str = "1",
    sar_ty_cd: str | None = None,
    io_root_extras: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    tty = _norm_tty(tax_ty_cd)
    io_line_ty = (io_ty_cd or "1").strip() or "1"
    sar_root = (sar_ty_cd or INSERT_STOCK_IO_SAR_TY_PURCHASE).strip() or INSERT_STOCK_IO_SAR_TY_PURCHASE
    prc = max(round(float(unit_price), 2), 0.01)
    qty_f = float(qty_in)
    sply, tb, tx, tot = _stock_io_line_amounts_for_tax_ty(unit_prc=prc, qty=qty_f, tax_ty_cd=tty)
    tot_taxbl = round(tb, 2)
    tot_tax = round(tx, 2)
    tot_amt = round(tot, 2)
    org_sar = 0 if int(sar_no) <= 1 else int(sar_no) - 1
    root: Dict[str, Any] = {
        "sarNo": int(sar_no),
        "regTyCd": "M",
        "custTin": tin.strip(),
        "sarTyCd": sar_root,
        "ocrnDt": datetime.now(timezone.utc).strftime("%Y%m%d"),
        "totItemCnt": 1,
        "totTaxblAmt": tot_taxbl,
        "totTaxAmt": tot_tax,
        "totAmt": tot_amt,
        "orgSarNo": org_sar,
        "regrId": "system",
        "regrNm": "system",
        "modrId": "system",
        "modrNm": "system",
        "itemList": [
            {
                "itemSeq": 1,
                "itemCd": item_cd.strip().upper(),
                "ioTyCd": io_line_ty,
                "itemClsCd": (item_cls_cd or "1010000000").strip(),
                "itemNm": (item_nm or item_cd)[:200],
                "pkgUnitCd": pkg_unit_cd,
                "pkg": qty_f,
                "qtyUnitCd": qty_unit_cd,
                "qty": qty_f,
                "prc": prc,
                "splyAmt": round(sply, 2),
                "totDcAmt": 0.0,
                "taxblAmt": tot_taxbl,
                "taxTyCd": tty,
                "taxAmt": tot_tax,
                "totAmt": tot_amt,
            }
        ],
    }
    if io_root_extras:
        for k, v in io_root_extras.items():
            if k == "itemList":
                continue
            if v is None:
                continue
            if isinstance(v, str) and not v.strip():
                continue
            root[k] = v
    return root


def process_inventory_stock_in_event(db: Session, outbox: KraEventOutbox, *, timeout: int = 90) -> Dict[str, Any]:
    """
    Execute item sync (if needed), ``insertStockIO``, ``saveStockMaster`` for one ledger-driven stock-in.
    Mutates ``outbox.payload_json`` for IO retry semantics (``io_posted``, ``target_rsd_qty``, ``sar_no_used``).
    """
    if settings.KRA_OUTBOX_SHADOW_MODE:
        return {"ok": True, "skipped": "shadow_mode"}

    ledger = db.query(InventoryLedger).filter(InventoryLedger.id == outbox.aggregate_id).first()
    if not ledger:
        return {"ok": False, "error": "ledger_not_found"}
    if not should_enqueue_kra_stock_in(ledger):
        return {"ok": False, "error": "ledger_not_stock_in_eligible"}

    branch_id = ledger.branch_id
    company_id = ledger.company_id
    creds = (
        db.query(BranchEtimsCredentials)
        .filter(BranchEtimsCredentials.company_id == company_id, BranchEtimsCredentials.branch_id == branch_id)
        .first()
    )
    if not creds or not creds.enabled:
        return {"ok": False, "error": "branch_kra_not_enabled"}
    if not (creds.kra_bhf_id and str(creds.kra_bhf_id).strip()):
        return {"ok": False, "error": "branch_bhf_missing"}
    if not (creds.device_serial and str(creds.device_serial).strip()):
        return {"ok": False, "error": "device_serial_missing"}
    cmc = get_cmc_key_plain(creds)
    if not cmc:
        return {"ok": False, "error": "cmc_key_missing"}

    company = db.query(Company).filter(Company.id == company_id).first()
    tin = ((getattr(creds, "client_tax_pin", None) or "") if creds else "") or ((company.pin if company else "") or "")
    tin = str(tin or "").strip()
    if not tin:
        return {"ok": False, "error": "company_tin_missing"}

    item = db.query(Item).filter(Item.id == ledger.item_id, Item.company_id == company_id).first()
    if not item:
        return {"ok": False, "error": "item_not_found"}

    user, password = get_oauth_username_password(creds)
    if not user or not password:
        return {"ok": False, "error": "oauth_not_configured"}

    env_eff = effective_etims_environment(creds)
    base = api_base_for_branch_credentials(env_eff)
    try:
        token = get_access_token(api_base=base, username=user, password=password, timeout=timeout, environment=env_eff)
    except Exception as e:
        return {"ok": False, "error": f"oauth_failed:{e}"}

    bhf_s = str(creds.kra_bhf_id).strip()
    apigee_app_id = (getattr(creds, "apigee_app_id", None) or "").strip()
    dev_serial = str(creds.device_serial).strip()

    # Stock operations must not run catalog refresh/saveItem side effects.
    # Use the stored code as authoritative; fail fast when missing.
    db.refresh(item)
    kra_cd = str(getattr(item, "kra_item_code", None) or "").strip().upper()
    logger.info(
        "kra_item_code_usage op=inventory_stock_in item_id=%s branch_id=%s stored_code=%s used_code=%s",
        item.id,
        branch_id,
        kra_cd or "<empty>",
        kra_cd or "<empty>",
    )
    if not kra_cd:
        return {"ok": False, "error": "item_missing_kra_item_code"}

    ib = _get_or_create_ib_sync(db, company_id=company_id, item_id=item.id, branch_id=branch_id)

    if outbox.payload_json is None:
        outbox.payload_json = {}
    flag_modified(outbox, "payload_json")
    body_pl = outbox.payload_json
    if not isinstance(body_pl, dict):
        body_pl = {}
        outbox.payload_json = body_pl
        flag_modified(outbox, "payload_json")

    body_pl.setdefault("version", 1)
    io_posted = bool(body_pl.get("io_posted"))

    try:
        user_delta = float(ledger.quantity_delta or 0)
    except (TypeError, ValueError):
        return {"ok": False, "error": "invalid_ledger_qty"}

    unit_cost = ledger.unit_cost
    try:
        unit_price = max(float(unit_cost or 0), 0.01)
    except (TypeError, ValueError):
        unit_price = 0.01

    item_cls = str(getattr(item, "kra_item_cls_cd", None) or "").strip() or "1010000000"
    tax_ty = _stock_io_tax_ty_cd_for_item(item)
    # Persist early so outbox JSON always shows the tax sent on insertStockIO (even if IO qty is 0 later).
    body_pl["insert_stock_tax_ty_cd"] = tax_ty
    flag_modified(outbox, "payload_json")
    db.flush()
    pkg_u = _norm_pkg_unit_sale(getattr(item, "kra_pkg_unit_cd", None))
    qty_u = _norm_qty_unit_sale(getattr(item, "kra_qty_unit_cd", None))
    item_nm = (item.name or kra_cd)[:200]

    hdr_common = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "tin": tin,
        "bhfId": bhf_s,
        "dvcSrlNo": dev_serial,
        "cmcKey": cmc,
    }
    if apigee_app_id:
        hdr_common["apigee_app_id"] = apigee_app_id

    baseline: float
    if ib.kra_stock_rsd_qty is not None:
        try:
            baseline = float(ib.kra_stock_rsd_qty)
        except (TypeError, ValueError):
            baseline = 0.0
    else:
        remote = fetch_select_stock_master_rsd_qty(
            base=base,
            token=token,
            tin=tin,
            bhf_id=bhf_s,
            cmc_key=cmc,
            apigee_app_id=apigee_app_id,
            device_serial=dev_serial,
            item_cd=kra_cd,
            timeout=timeout,
        )
        baseline = float(remote) if remote is not None else 0.0

    target_local_qty = round(float(InventoryService.get_current_stock(db, ledger.item_id, branch_id)), 4)
    reconciliation_delta = round(float(target_local_qty) - float(baseline), 4)
    try:
        stored_recon_delta = float(body_pl.get("reconciliation_delta"))
    except (TypeError, ValueError):
        stored_recon_delta = None
    qty_for_io = max(float(stored_recon_delta if (io_posted and stored_recon_delta is not None) else reconciliation_delta), 0.0)
    body_pl["user_delta"] = float(user_delta)
    body_pl["previous_kra_qty"] = float(baseline)
    body_pl["target_local_qty"] = float(target_local_qty)
    body_pl["reconciliation_delta"] = float(reconciliation_delta)
    body_pl["reconciliation_delta_used"] = float(qty_for_io)
    flag_modified(outbox, "payload_json")
    db.flush()

    if not io_posted and qty_for_io > 0:
        last_sar = max(int(getattr(creds, "kra_last_stock_io_sar_no", None) or 0), 0)
        sar_no = last_sar + 1
        sar_ty, io_ty = kra_insert_stock_io_codes_for_positive_ledger(ledger)
        body_pl["insert_stock_sar_ty_cd"] = sar_ty
        body_pl["insert_stock_io_ty_cd"] = io_ty
        flag_modified(outbox, "payload_json")
        db.flush()
        logger.info(
            "kra_insert_stock_io ledger_id=%s transaction_type=%s reference_type=%s sarTyCd=%s ioTyCd=%s taxTyCd=%s qty_in=%s",
            ledger.id,
            (ledger.transaction_type or "").strip(),
            (ledger.reference_type or "").strip() or None,
            sar_ty,
            io_ty,
            tax_ty,
            qty_for_io,
        )
        payload_io = build_insert_stock_io_payload(
            tin=tin,
            sar_no=sar_no,
            qty_in=qty_for_io,
            unit_price=unit_price,
            item_cd=kra_cd,
            item_nm=item_nm,
            item_cls_cd=item_cls,
            tax_ty_cd=tax_ty,
            pkg_unit_cd=pkg_u,
            qty_unit_cd=qty_u,
            io_ty_cd=io_ty,
            sar_ty_cd=sar_ty,
            io_root_extras=_insert_stock_io_root_extras_for_ledger(db, ledger) or None,
        )
        url_io = f"{base.rstrip('/')}{INSERT_STOCK_IO_PATH}"
        try:
            r_io = requests.post(url_io, headers=hdr_common, json=payload_io, timeout=timeout)
            parsed_io = r_io.json() if (r_io.text or "").strip() else None
        except requests.RequestException as e:
            return {"ok": False, "error": f"insert_stock_io_transport:{e}"}

        if not _post_ok(parsed_io if isinstance(parsed_io, dict) else None, r_io.status_code):
            err_txt = _hdr_err(parsed_io if isinstance(parsed_io, dict) else None) or (r_io.text or "")[:1200]
            expected_sar = kra_expected_next_sar_no_from_message(err_txt)
            if expected_sar is not None:
                creds.kra_last_stock_io_sar_no = max(0, expected_sar - 1)
                db.flush()
            try:
                raw_excerpt = json.dumps(parsed_io, default=str)[:1200] if parsed_io else (r_io.text or "")[:1200]
            except Exception:
                raw_excerpt = (r_io.text or "")[:1200]
            return {"ok": False, "error": f"insert_stock_io_failed:{err_txt or raw_excerpt}"}

        creds.kra_last_stock_io_sar_no = int(sar_no)
        body_pl["io_posted"] = True
        body_pl["sar_no_used"] = int(sar_no)
        body_pl["baseline_kra_rsd_used"] = float(baseline)
        flag_modified(outbox, "payload_json")
        db.flush()

    # Convergence model:
    # - ``insertStockIO`` uses reconciliation delta (target_local_qty - previous_kra_qty), not raw user delta.
    # - ``saveStockMaster`` posts strict PharmaSight ledger quantity (target_local_qty).
    sm_qty = round(float(target_local_qty), 4)
    body_pl["target_rsd_qty"] = float(sm_qty)
    flag_modified(outbox, "payload_json")
    db.flush()

    ok_sm, http_st, _, posted, err_sm = _post_save_stock_master_with_rsd_mismatch_retry(
        base=base,
        hdr_common=hdr_common,
        kra_cd=kra_cd,
        rsd_qty=sm_qty,
        timeout=timeout,
        allow_mismatch_expected_retry=False,
    )
    if not ok_sm:
        return {"ok": False, "error": err_sm or "save_stock_master_failed"}
    sm_qty = round(float(posted), 4)

    ib.kra_stock_rsd_qty = Decimal(str(sm_qty))
    ib.kra_stock_mirror_updated_at = datetime.now(timezone.utc)
    db.flush()

    kra_ledger_align_failed: str | None = None
    body_pl["resulting_kra_qty"] = float(sm_qty)
    body_pl["result_http_status"] = int(http_st)
    flag_modified(outbox, "payload_json")

    body_pl.pop("io_posted", None)
    body_pl.pop("sar_no_used", None)
    body_pl.pop("target_rsd_qty", None)
    body_pl.pop("baseline_kra_rsd_used", None)
    flag_modified(outbox, "payload_json")

    return {
        "ok": True,
        "kra_stock_rsd_qty": float(sm_qty),
        "item_cd": kra_cd,
        "kra_ledger_align_failed": kra_ledger_align_failed,
        "user_delta": float(user_delta),
        "previous_kra_qty": float(baseline),
        "target_local_qty": float(target_local_qty),
        "reconciliation_delta": float(reconciliation_delta),
        "reconciliation_delta_used": float(qty_for_io),
        "resulting_kra_qty": float(sm_qty),
        "insert_stock_sar_ty_cd": body_pl.get("insert_stock_sar_ty_cd"),
        "insert_stock_io_ty_cd": body_pl.get("insert_stock_io_ty_cd"),
        "insert_stock_tax_ty_cd": body_pl.get("insert_stock_tax_ty_cd"),
    }


def reconcile_kra_stock_master_read_through(
    db: Session,
    *,
    company_id: UUID,
    branch_id: UUID,
    item_id: UUID,
    timeout: int = 90,
    align_with_ledger: bool = False,
) -> Dict[str, Any]:
    """
    Read ``selectStockMaster`` (then move-list balance fields), optionally last mirror or PharmaSight ledger,
    POST ``saveStockMaster`` with that ``rsdQty`` (no ``insertStockIO``), and refresh ``item_branch_kra_sync``.

    When OSCU returns no rows (common on SBX), use ``align_with_ledger=true`` to post **current PharmaSight
    ledger base stock** as ``rsdQty`` (ignores ``item_branch_kra_sync.kra_stock_rsd_qty`` so a stale zero
    mirror cannot block the push). Without that flag, fallbacks are select reads then last mirror.
    """
    if settings.KRA_OUTBOX_SHADOW_MODE:
        return {"ok": False, "error": "KRA_OUTBOX_SHADOW_MODE is enabled; reconcile skipped."}

    item = db.query(Item).filter(Item.id == item_id, Item.company_id == company_id).first()
    if not item:
        return {"ok": False, "error": "item_not_found"}

    creds = (
        db.query(BranchEtimsCredentials)
        .filter(BranchEtimsCredentials.company_id == company_id, BranchEtimsCredentials.branch_id == branch_id)
        .first()
    )
    if not creds or not creds.enabled:
        return {"ok": False, "error": "branch_kra_not_enabled"}
    if not (creds.kra_bhf_id and str(creds.kra_bhf_id).strip()):
        return {"ok": False, "error": "branch_bhf_missing"}
    if not (creds.device_serial and str(creds.device_serial).strip()):
        return {"ok": False, "error": "device_serial_missing"}
    cmc = get_cmc_key_plain(creds)
    if not cmc:
        return {"ok": False, "error": "cmc_key_missing"}

    company = db.query(Company).filter(Company.id == company_id).first()
    tin = ((getattr(creds, "client_tax_pin", None) or "") if creds else "") or ((company.pin if company else "") or "")
    tin = str(tin or "").strip()
    if not tin:
        return {"ok": False, "error": "company_tin_missing"}

    user, password = get_oauth_username_password(creds)
    if not user or not password:
        return {"ok": False, "error": "oauth_not_configured"}

    env_eff = effective_etims_environment(creds)
    base = api_base_for_branch_credentials(env_eff)
    try:
        token = get_access_token(api_base=base, username=user, password=password, timeout=timeout, environment=env_eff)
    except Exception as e:
        return {"ok": False, "error": f"oauth_failed:{e}"}

    bhf_s = str(creds.kra_bhf_id).strip()
    apigee_app_id = (getattr(creds, "apigee_app_id", None) or "").strip()
    dev_serial = str(creds.device_serial).strip()

    # Reconcile is also operational: never trigger catalog refresh/saveItem.
    db.refresh(item)
    kra_cd = str(getattr(item, "kra_item_code", None) or "").strip().upper()
    logger.info(
        "kra_item_code_usage op=stock_reconcile item_id=%s branch_id=%s stored_code=%s used_code=%s align_with_ledger=%s",
        item.id,
        branch_id,
        kra_cd or "<empty>",
        kra_cd or "<empty>",
        bool(align_with_ledger),
    )
    if not kra_cd:
        return {"ok": False, "error": "item_missing_kra_item_code"}

    hdr_common = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "tin": tin,
        "bhfId": bhf_s,
        "dvcSrlNo": dev_serial,
        "cmcKey": cmc,
    }
    if apigee_app_id:
        hdr_common["apigee_app_id"] = apigee_app_id

    ib = _get_or_create_ib_sync(db, company_id=company_id, item_id=item.id, branch_id=branch_id)

    rsd: float | None = None
    rsd_qty_source: str | None = None

    if align_with_ledger:
        # Explicit operator intent: post ledger base qty — do not let a stale kra_stock_rsd_qty mirror
        # (e.g. 0 after a prior Expected: retry) override PharmaSight stock.
        rsd = float(InventoryService.get_current_stock(db, item_id, branch_id))
        rsd_qty_source = "pharmasight_ledger"
    else:
        rsd_master = fetch_select_stock_master_rsd_qty(
            base=base,
            token=token,
            tin=tin,
            bhf_id=bhf_s,
            cmc_key=cmc,
            apigee_app_id=apigee_app_id,
            device_serial=dev_serial,
            item_cd=kra_cd,
            timeout=timeout,
        )
        rsd_move = (
            None
            if rsd_master is not None
            else fetch_move_list_rsd_qty_for_item(
                base=base,
                token=token,
                tin=tin,
                bhf_id=bhf_s,
                cmc_key=cmc,
                apigee_app_id=apigee_app_id,
                device_serial=dev_serial,
                item_cd=kra_cd,
                timeout=timeout,
            )
        )
        rsd = rsd_master if rsd_master is not None else rsd_move
        if rsd_master is not None:
            rsd_qty_source = "select_stock_master"
        elif rsd_move is not None:
            rsd_qty_source = "select_stock_move_list"

        if rsd is None and ib.kra_stock_rsd_qty is not None:
            try:
                rsd = float(ib.kra_stock_rsd_qty)
                rsd_qty_source = "last_mirror"
            except (TypeError, ValueError):
                rsd = None

        if rsd is None:
            return {
                "ok": False,
                "error": (
                    "kra_rsd_qty_unavailable: OSCU returned no balance from selectStockMaster or selectStockMoveList, "
                    "and no last mirror rsdQty. Pass align_with_ledger=true to post PharmaSight ledger base stock, "
                    "or use adjust-stock (insertStockIO + saveStockMaster uses baseline+qty_in when reads are empty)."
                ),
            }

    sm_qty_read = round(float(rsd), 4)
    ok_sm, http_st, _, posted, err_sm = _post_save_stock_master_with_rsd_mismatch_retry(
        base=base,
        hdr_common=hdr_common,
        kra_cd=kra_cd,
        rsd_qty=sm_qty_read,
        timeout=timeout,
        allow_mismatch_expected_retry=not align_with_ledger,
    )
    if not ok_sm:
        return {"ok": False, "error": err_sm or "save_stock_master_failed"}

    posted_f = round(float(posted), 4)
    if abs(posted_f - sm_qty_read) > 1e-6:
        rsd_qty_source = "kra_mismatch_expected"

    ib.kra_stock_rsd_qty = Decimal(str(posted_f))
    ib.kra_stock_mirror_updated_at = datetime.now(timezone.utc)
    db.flush()

    return {
        "ok": True,
        "kra_item_code": kra_cd,
        "rsd_qty_read": float(sm_qty_read),
        "rsd_qty_posted": posted_f,
        "rsd_qty_source": rsd_qty_source,
        "http_status": int(http_st),
    }
