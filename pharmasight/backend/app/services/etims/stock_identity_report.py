"""
Read-only stock identity tuple report: insertStockIO line vs saveStockMaster vs saveTrnsSalesOsdc.

Lazy-imports ``kra_stock_push_service`` only inside ``build_stock_identity_report`` to reduce import cycles.
"""
from __future__ import annotations

import base64
import json
import logging
from typing import Any, Dict, List, Optional, Tuple

import requests
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.company import BranchEtimsCredentials, Company
from app.models.inventory import InventoryLedger
from app.models.item import Item, ItemBranchKraSync
from app.models.kra_event_outbox import KraEventOutbox
from app.models.sale import SalesInvoice
from app.services.etims.branch_credentials import get_cmc_key_plain
from app.services.etims.etims_invoice_payload_builder import _norm_pkg_unit_sale, _norm_qty_unit_sale
from app.services.etims.etims_osdc_forensic import (
    build_pharmasight_osdc_sale_attempt_bundle,
    resolve_osdc_tin,
)

logger = logging.getLogger(__name__)

STOCK_TUPLE_KEYS = ("itemCd", "taxTyCd", "pkgUnitCd", "qtyUnitCd", "itemClsCd", "tin", "bhfId")

# Fields to diff between reconstructed insertStockIO line and OSDC sale line (same names on both when present).
SALE_LINE_PARITY_KEYS = ("itemCd", "taxTyCd", "vatCatCd", "pkgUnitCd", "qtyUnitCd", "qty", "pkg", "prc", "itemClsCd")


def jwt_payload_preview_unverified(authorization_header: Optional[str]) -> Any:
    """Decode JWT payload segment without signature verification (diagnostic only)."""
    if not authorization_header:
        return None
    s = str(authorization_header).strip()
    if not s.lower().startswith("bearer "):
        return None
    token = s.split(None, 1)[1].strip() if len(s.split(None, 1)) > 1 else ""
    parts = token.split(".")
    if len(parts) < 2:
        return None

    def _pad(b: str) -> str:
        return b + "=" * (-len(b) % 4)

    try:
        raw = base64.urlsafe_b64decode(_pad(parts[1]))
        return json.loads(raw.decode("utf-8"))
    except Exception as ex:
        return {"jwt_decode_error": str(ex)}


def _tuple_from_insert_line(line: Dict[str, Any], *, tin: str, bhf_id: str) -> Dict[str, Any]:
    return {
        "itemCd": line.get("itemCd"),
        "taxTyCd": line.get("taxTyCd"),
        "pkgUnitCd": line.get("pkgUnitCd"),
        "qtyUnitCd": line.get("qtyUnitCd"),
        "itemClsCd": line.get("itemClsCd"),
        "tin": tin,
        "bhfId": bhf_id,
    }


def _tuple_from_osdc_line(line: Dict[str, Any], *, tin: str, bhf_id: str) -> Dict[str, Any]:
    return {
        "itemCd": line.get("itemCd"),
        "taxTyCd": line.get("taxTyCd"),
        "pkgUnitCd": line.get("pkgUnitCd"),
        "qtyUnitCd": line.get("qtyUnitCd"),
        "itemClsCd": line.get("itemClsCd"),
        "vatCatCd": line.get("vatCatCd"),
        "tin": tin,
        "bhfId": bhf_id,
    }


def _tuple_diff(
    a: Dict[str, Any],
    b: Dict[str, Any],
    keys: Tuple[str, ...],
    *,
    left_label: str,
    right_label: str,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k in keys:
        av = a.get(k)
        bv = b.get(k)
        if av != bv:
            out[k] = {left_label: av, right_label: bv}
    return out


def _latest_stock_in_outbox_rows(
    db: Session,
    *,
    company_id: Any,
    branch_id: Any,
    item_id: Any,
    limit: int = 8,
) -> List[KraEventOutbox]:
    return (
        db.query(KraEventOutbox)
        .join(InventoryLedger, InventoryLedger.id == KraEventOutbox.aggregate_id)
        .filter(
            KraEventOutbox.company_id == company_id,
            KraEventOutbox.branch_id == branch_id,
            KraEventOutbox.event_type == "inventory.stock_in",
            InventoryLedger.item_id == item_id,
        )
        .order_by(desc(KraEventOutbox.updated_at))
        .limit(limit)
        .all()
    )


def _pick_osdc_item_line(item_list: Any, *, kra_cd: str) -> Optional[Dict[str, Any]]:
    if not isinstance(item_list, list):
        return None
    want = kra_cd.strip().upper()
    for row in item_list:
        if isinstance(row, dict) and str(row.get("itemCd") or "").strip().upper() == want:
            return dict(row)
    return None


def build_stock_identity_report(
    db: Session,
    invoice: SalesInvoice,
    *,
    creds: BranchEtimsCredentials,
    company: Optional[Company],
    timeout: int = 60,
    include_osdc_bundle: bool = True,
) -> Dict[str, Any]:
    """
    Build tuples for parity testing. ``insertStockIO`` line is **reconstructed** with the same builders
    as production, using qty from the latest processed outbox row when available (else current ledger stock).
    """
    from app.services.etims.kra_stock_push_service import (
        build_insert_stock_io_payload,
        kra_insert_stock_io_codes_for_positive_ledger,
        _stock_io_tax_ty_cd_for_item,
    )
    from app.services.inventory_service import InventoryService

    tin = resolve_osdc_tin(creds, company)
    bhf_s = str(creds.kra_bhf_id).strip()
    dev = str(creds.device_serial).strip()
    cmc = get_cmc_key_plain(creds) or ""

    osdc_bundle: Optional[Dict[str, Any]] = None
    osdc_build_error: Optional[str] = None
    if include_osdc_bundle:
        try:
            osdc_bundle = build_pharmasight_osdc_sale_attempt_bundle(
                db,
                invoice,
                creds=creds,
                company=company,
                timeout=timeout,
                include_select_invoice_type=True,
            )
        except Exception as ex:
            osdc_build_error = str(ex)
            logger.warning("build_stock_identity_report: OSDC bundle failed: %s", ex)

    osdc_payload: Dict[str, Any] = {}
    osdc_headers: Dict[str, Any] = {}
    if osdc_bundle:
        osdc_payload = osdc_bundle.get("payload_final") or {}
        osdc_headers = dict(osdc_bundle.get("headers_final") or {})

    auth_hdr = osdc_headers.get("Authorization")
    jwt_preview = jwt_payload_preview_unverified(auth_hdr) if auth_hdr else None

    osdc_hdr_subset: Dict[str, Any] = {}
    for k in ("tin", "bhfId", "dvcSrlNo", "cmcKey", "User-Agent", "Content-Type", "apigee_app_id"):
        if k in osdc_headers:
            osdc_hdr_subset[k] = osdc_headers[k]

    lines_out: List[Dict[str, Any]] = []

    for inv_line in list(invoice.items or []):
        it = getattr(inv_line, "item", None)
        if it is None or not getattr(inv_line, "item_id", None):
            continue

        item: Item = it
        kra_cd = str(getattr(item, "kra_item_code", None) or "").strip().upper()
        ib = (
            db.query(ItemBranchKraSync)
            .filter(
                ItemBranchKraSync.company_id == invoice.company_id,
                ItemBranchKraSync.branch_id == invoice.branch_id,
                ItemBranchKraSync.item_id == item.id,
            )
            .first()
        )

        out_rows = _latest_stock_in_outbox_rows(
            db,
            company_id=invoice.company_id,
            branch_id=invoice.branch_id,
            item_id=item.id,
            limit=8,
        )

        qty_hint = 0.0
        ledger_for_codes: Optional[InventoryLedger] = None
        chosen_pl: Optional[Dict[str, Any]] = None
        for ob in out_rows:
            pl = ob.payload_json if isinstance(ob.payload_json, dict) else {}
            if str(ob.processing_status or "").strip().lower() == "processed":
                try:
                    q = float(pl.get("reconciliation_delta_used"))
                except (TypeError, ValueError):
                    q = 0.0
                if q > 0:
                    qty_hint = q
                    chosen_pl = pl
                    ledger_for_codes = db.query(InventoryLedger).filter(InventoryLedger.id == ob.aggregate_id).first()
                    break
        if qty_hint <= 0 and out_rows:
            ob0 = out_rows[0]
            pl0 = ob0.payload_json if isinstance(ob0.payload_json, dict) else {}
            chosen_pl = pl0
            try:
                qty_hint = max(
                    float(pl0.get("reconciliation_delta_used") or 0),
                    float(pl0.get("target_local_qty") or 0),
                    1.0,
                )
            except (TypeError, ValueError):
                qty_hint = 1.0
            ledger_for_codes = db.query(InventoryLedger).filter(InventoryLedger.id == ob0.aggregate_id).first()
        if qty_hint <= 0:
            qty_hint = max(float(InventoryService.get_current_stock(db, item.id, invoice.branch_id) or 0), 1.0)

        item_cls = str(getattr(item, "kra_item_cls_cd", None) or "").strip() or "1010000000"
        tax_ty = _stock_io_tax_ty_cd_for_item(item)
        pkg_u = _norm_pkg_unit_sale(getattr(item, "kra_pkg_unit_cd", None))
        qty_u = _norm_qty_unit_sale(getattr(item, "kra_qty_unit_cd", None))
        item_nm = (item.name or kra_cd)[:200]
        try:
            unit_price = max(float(getattr(inv_line, "unit_cost_used", None) or getattr(item, "cost_price", None) or 0), 0.01)
        except (TypeError, ValueError):
            unit_price = 0.01

        io_ty = "1"
        sar_ty = "02"
        if ledger_for_codes is not None:
            sar_ty, io_ty = kra_insert_stock_io_codes_for_positive_ledger(ledger_for_codes)

        payload_io = build_insert_stock_io_payload(
            tin=tin,
            sar_no=1,
            qty_in=float(qty_hint),
            unit_price=float(unit_price),
            item_cd=kra_cd,
            item_nm=item_nm,
            item_cls_cd=item_cls,
            tax_ty_cd=tax_ty,
            pkg_unit_cd=pkg_u,
            qty_unit_cd=qty_u,
            io_ty_cd=io_ty,
            sar_ty_cd=sar_ty,
            io_root_extras=None,
        )
        il0: Dict[str, Any] = {}
        if isinstance(payload_io.get("itemList"), list) and payload_io["itemList"]:
            il0 = dict(payload_io["itemList"][0])
        tuple_io = _tuple_from_insert_line(il0, tin=tin, bhf_id=bhf_s)

        rsd = float(ib.kra_stock_rsd_qty) if ib and ib.kra_stock_rsd_qty is not None else None
        tuple_sm: Dict[str, Any] = {
            "itemCd": kra_cd,
            "taxTyCd": None,
            "pkgUnitCd": None,
            "qtyUnitCd": None,
            "itemClsCd": None,
            "tin": tin,
            "bhfId": bhf_s,
            "rsdQty": rsd,
            "note": "saveStockMaster wire body is itemCd+rsdQty only; other tuple keys intentionally null.",
        }

        osdc_line: Optional[Dict[str, Any]] = None
        tuple_osdc: Optional[Dict[str, Any]] = None
        diff_io_vs_osdc: Dict[str, Any] = {}
        diff_sm_vs_osdc: Dict[str, Any] = {}

        if osdc_payload:
            root_tin = str(osdc_payload.get("tin") or tin).strip()
            root_bhf = str(osdc_payload.get("bhfId") or bhf_s).strip()
            osdc_line = _pick_osdc_item_line(osdc_payload.get("itemList"), kra_cd=kra_cd)
            if osdc_line is None:
                il = osdc_payload.get("itemList")
                if isinstance(il, list) and il and isinstance(il[0], dict):
                    osdc_line = dict(il[0])
            if osdc_line:
                tuple_osdc = _tuple_from_osdc_line(osdc_line, tin=root_tin, bhf_id=root_bhf)
                diff_io_vs_osdc = _tuple_diff(
                    tuple_io,
                    tuple_osdc,
                    STOCK_TUPLE_KEYS,
                    left_label="insertStockIO_reconstructed",
                    right_label="saveTrnsSalesOsdc",
                )
                diff_sm_vs_osdc = _tuple_diff(
                    tuple_sm,
                    tuple_osdc,
                    STOCK_TUPLE_KEYS,
                    left_label="saveStockMaster",
                    right_label="saveTrnsSalesOsdc",
                )

        insert_parity = {k: il0.get(k) for k in SALE_LINE_PARITY_KEYS}
        osdc_parity: Optional[Dict[str, Any]] = None
        scalar_diff_io_vs_osdc: Dict[str, Any] = {}
        if osdc_line:
            osdc_parity = {k: osdc_line.get(k) for k in SALE_LINE_PARITY_KEYS}
            for k in SALE_LINE_PARITY_KEYS:
                a, b = insert_parity.get(k), osdc_parity.get(k) if osdc_parity else None
                if a != b:
                    scalar_diff_io_vs_osdc[k] = {"insertStockIO_reconstructed": a, "saveTrnsSalesOsdc": b}

        lines_out.append(
            {
                "item_id": str(item.id),
                "kra_item_code": kra_cd,
                "outbox_rows_returned": len(out_rows),
                "outbox_latest_payload_excerpt": chosen_pl,
                "outbox_insert_stock_tax_ty_cd": (chosen_pl or {}).get("insert_stock_tax_ty_cd"),
                "insert_stock_io_qty_used_for_reconstruction": qty_hint,
                "insert_stock_io_reconstruction_note": (
                    "insertStockIO itemList[0] rebuilt via build_insert_stock_io_payload(sarNo=1 placeholder); "
                    "qty from latest processed outbox reconciliation_delta_used when present, else target_local_qty/stock."
                ),
                "insert_stock_io_itemList_line0": il0,
                "tuple_insert_stock_io": tuple_io,
                "tuple_save_stock_master": tuple_sm,
                "tuple_save_trns_sales_osdc": tuple_osdc,
                "diff_tuple_insert_vs_osdc": diff_io_vs_osdc,
                "diff_tuple_sm_vs_osdc": diff_sm_vs_osdc,
                "osdc_item_list_line_matched": osdc_line,
                "insert_vs_osdc_line_scalar_fields": {
                    "insertStockIO_reconstructed": insert_parity,
                    "saveTrnsSalesOsdc": osdc_parity,
                },
                "scalar_field_diff_insert_vs_osdc": scalar_diff_io_vs_osdc,
            }
        )

    hdr_stock = {
        "tin": tin,
        "bhfId": bhf_s,
        "dvcSrlNo": dev,
        "cmcKey": cmc,
        "User-Agent": requests.utils.default_user_agent(),
        "note": "insertStockIO/saveStockMaster add Authorization Bearer at runtime (same shape as OSDC).",
    }

    return {
        "invoice_id": str(invoice.id),
        "branch_id": str(invoice.branch_id),
        "company_id": str(invoice.company_id),
        "experiment_matrix": {
            "TEST_1_gava_direct": "Run gavaetims for same itemCd/TIN/bhfId/device; set GAVA_ETIMS_FORENSIC_SAVE_INVOICE_JSONL.",
            "TEST_2_replay": "POST /etims/debug/replay-save-trns-sales-osdc with body_raw_utf8 from gava JSONL (no re-serialization).",
            "A_if_replay_ok": "PharmaSight payload builder differs from gava.",
            "B_if_replay_fail": "Suspect OAuth/session/device/SIM/stock partition — continue header parity.",
        },
        "headers_insert_stock_io_and_save_stock_master_template": hdr_stock,
        "headers_save_trns_sales_osdc": osdc_hdr_subset,
        "jwt_payload_preview_unverified_osdc": jwt_preview,
        "osdc_full_url": (osdc_bundle or {}).get("full_url"),
        "osdc_bundle_build_error": osdc_build_error,
        "endpoint_insert_stock_io": "/insertStockIO",
        "endpoint_save_stock_master": "/saveStockMaster",
        "endpoint_save_trns_sales_osdc": "/saveTrnsSalesOsdc",
        "body_osdc_root_compare": {
            "tin": osdc_payload.get("tin"),
            "bhfId": osdc_payload.get("bhfId"),
            "totItemCnt": osdc_payload.get("totItemCnt"),
        },
        "per_item_rows": lines_out,
    }
