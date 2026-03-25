"""
Order Book API routes
"""
import json
import logging
import math
import numbers
import traceback
from collections.abc import Mapping
from fastapi import APIRouter, Depends, HTTPException, status, Query, Body
from starlette.responses import Response
from sqlalchemy.orm import Session, selectinload, aliased
from sqlalchemy import func, and_, or_, select, exists
from sqlalchemy.exc import IntegrityError
from typing import List, Optional, Tuple
from uuid import UUID
from decimal import Decimal
from datetime import date, datetime, timedelta
from app.dependencies import get_current_user
from app.models import (
    DailyOrderBook, OrderBookHistory,
    Item, Supplier, PurchaseOrder, PurchaseOrderItem,
    SupplierInvoice, SupplierInvoiceItem,
    InventoryLedger, InventoryBalance, Branch, User
)
from app.schemas.order_book import (
    OrderBookEntryCreate, OrderBookEntryResponse, OrderBookEntryUpdate,
    OrderBookBulkCreate, OrderBookBulkCreateResponse, CreatePurchaseOrderFromBook,
    OrderBookHistoryResponse
)
from app.services.document_service import DocumentService
from app.services.snapshot_service import SnapshotService
from app.services.order_book_service import OrderBookService
from app.api.users import _user_has_owner_or_admin_role
from app.config import settings

router = APIRouter()


def _to_int_stock(val) -> int:
    """Convert ledger/balance numeric to int without raising on edge Decimal/None values."""
    try:
        if val is None:
            return 0
        return int(Decimal(str(val)))
    except Exception:
        return 0


def _everything_json_safe(obj):
    """
    Deep-convert any structure to JSON-serializable primitives only.
    - Coerces dict keys to str (UUID keys break json.dumps).
    - Converts Decimal and all numbers.Number (incl. SQLAlchemy/numpy scalars) to float.
    - Never leaves a value that stdlib json.dumps cannot encode (no default= hook needed).
    """
    if obj is None:
        return None
    if isinstance(obj, bool):
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, int):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else 0.0
    if isinstance(obj, Decimal):
        try:
            f = float(obj)
            return f if math.isfinite(f) else 0.0
        except Exception:
            return 0.0
    if isinstance(obj, UUID):
        return str(obj)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    # dict and mapping-like rows (e.g. SQLAlchemy Row) — not just dict
    if isinstance(obj, Mapping):
        out = {}
        for k, v in obj.items():
            sk = str(k) if not isinstance(k, str) else k
            out[sk] = _everything_json_safe(v)
        return out
    if isinstance(obj, (list, tuple)):
        return [_everything_json_safe(v) for v in obj]
    if isinstance(obj, set):
        return [_everything_json_safe(v) for v in obj]
    if isinstance(obj, numbers.Number) and not isinstance(obj, bool):
        try:
            f = float(obj)
            return f if math.isfinite(f) else 0.0
        except Exception:
            return 0.0
    if isinstance(obj, (bytes, bytearray)):
        try:
            return obj.decode("utf-8", errors="replace")
        except Exception:
            return ""
    try:
        return str(obj)
    except Exception:
        return None


def _json_response_list(payload: list) -> Response:
    """Encode list to JSON bytes using only primitive-safe data (no Decimal left for stdlib json)."""
    log = logging.getLogger(__name__)
    try:
        safe = _everything_json_safe(payload)
    except Exception as e:
        log.exception("Order book: _everything_json_safe failed (unexpected)")
        if settings.DEBUG:
            traceback.print_exc()
        raise
    try:
        body = json.dumps(safe, ensure_ascii=False).encode("utf-8")
    except Exception as e:
        log.exception("Order book: json.dumps failed after sanitize (unexpected)")
        if settings.DEBUG:
            traceback.print_exc()
        raise
    return Response(content=body, media_type="application/json")


def _get_days_in_order_book_90(db: Session, branch_id: UUID, item_ids: List[UUID]) -> dict:
    """Return map item_id -> number of distinct days the item appeared in the order book in the past 90 days."""
    if not item_ids:
        return {}
    since = date.today() - timedelta(days=90)
    since_dt = datetime.combine(since, datetime.min.time())

    try:
        # Distinct (item_id, date) from current order book
        daily_rows = (
            db.query(DailyOrderBook.item_id, DailyOrderBook.entry_date)
            .filter(
                DailyOrderBook.branch_id == branch_id,
                DailyOrderBook.item_id.in_(item_ids),
                DailyOrderBook.entry_date >= since,
            )
            .distinct()
            .all()
        )
        # Distinct (item_id, date) from history
        history_rows = (
            db.query(
                OrderBookHistory.item_id,
                func.date(OrderBookHistory.created_at).label("d"),
            )
            .filter(
                OrderBookHistory.branch_id == branch_id,
                OrderBookHistory.item_id.in_(item_ids),
                OrderBookHistory.created_at >= since_dt,
            )
            .distinct()
            .all()
        )
    except Exception as e:
        logging.getLogger(__name__).warning("days_in_order_book_90 query failed: %s", e)
        return {}

    # Merge and count distinct dates per item_id
    from collections import defaultdict
    def to_date(v):
        return v.date() if isinstance(v, datetime) else v
    by_item = defaultdict(set)
    for item_id, d in daily_rows:
        by_item[item_id].add(to_date(d))
    for row in history_rows:
        by_item[row.item_id].add(to_date(row.d))
    return {item_id: len(dates) for item_id, dates in by_item.items()}


def _reason_display(entry) -> str:
    """Display reason: AUTO_* as-is, otherwise show creator name."""
    try:
        reason = (entry.reason or "").strip()
        if reason.upper().startswith("AUTO_"):
            return reason
        creator = getattr(entry, "creator", None)
        if creator:
            return (creator.full_name or creator.username or "Unknown").strip() or "Unknown"
        return reason or "Unknown"
    except Exception:
        return (getattr(entry, "reason", None) or "").strip() or "Unknown"


def _safe_int(v, default: int = 5) -> int:
    try:
        if v is None:
            return default
        return int(v)
    except Exception:
        return default


def _get_last_wholesale_unit_cost_map(
    db: Session,
    branch_id: UUID,
    company_id: UUID,
    item_ids: List[UUID],
) -> dict[UUID, Decimal]:
    """
    Return latest purchase-like unit cost converted to *wholesale* unit.

    Assumptions:
    - `inventory_ledger.unit_cost` is stored per retail/base unit (see inventory/base-unit migrations).
    - wholesale unit cost = retail/base unit cost * pack_size.
    - We treat `PURCHASE` and incoming `ADJUSTMENT` (stock additions) as "purchase-like" sources,
      because manual valuation corrections can update historical incoming layers.
    - If there is no purchase-like history, fall back to `items.default_cost_per_base * pack_size`.
    """
    if not item_ids:
        return {}

    items = {i.id: i for i in db.query(Item).filter(Item.id.in_(item_ids)).all()}

    # Latest PURCHASE-like cost per item (avoid window functions — portable & fewer edge-case DB errors).
    agg = (
        db.query(
            InventoryLedger.item_id.label("iid"),
            func.max(InventoryLedger.created_at).label("mx"),
        )
        .filter(
            InventoryLedger.item_id.in_(item_ids),
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.company_id == company_id,
            InventoryLedger.transaction_type.in_(["PURCHASE", "ADJUSTMENT"]),
            InventoryLedger.quantity_delta > 0,
            InventoryLedger.unit_cost > 0,
        )
        .group_by(InventoryLedger.item_id)
        .subquery()
    )
    rows = (
        db.query(InventoryLedger.item_id, InventoryLedger.unit_cost)
        .join(
            agg,
            and_(
                InventoryLedger.item_id == agg.c.iid,
                InventoryLedger.created_at == agg.c.mx,
            ),
        )
        .filter(
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.company_id == company_id,
            InventoryLedger.transaction_type.in_(["PURCHASE", "ADJUSTMENT"]),
            InventoryLedger.quantity_delta > 0,
            InventoryLedger.unit_cost > 0,
        )
        .all()
    )
    seen: set[UUID] = set()
    out: dict[UUID, Decimal] = {}
    for r in rows:
        if r.item_id in seen:
            continue
        seen.add(r.item_id)
        item = items.get(r.item_id)
        if not item:
            continue
        pack_size = max(1, int(item.pack_size or 1))
        unit_cost_retail = Decimal(str(r.unit_cost or 0))
        out[r.item_id] = unit_cost_retail * Decimal(str(pack_size))

    # Fill missing with default_cost_per_base * pack_size
    for iid in item_ids:
        if iid in out:
            continue
        item = items.get(iid)
        if not item:
            out[iid] = Decimal("0")
            continue
        pack_size = max(1, int(item.pack_size or 1))
        default_cost = getattr(item, "default_cost_per_base", None)
        out[iid] = Decimal(str(default_cost or 0)) * Decimal(str(pack_size))

    return out


def _safe_float(v, default=0.0):
    try:
        x = float(v) if v is not None else default
        return default if not math.isfinite(x) else x
    except Exception:
        return default


def _serialize_order_book_entry(
    entry,
    _get_stock,
    days_in_book_90: Optional[int] = None,
    last_wholesale_unit_cost_map: Optional[dict[UUID, Decimal]] = None,
):
    """Build a JSON-serializable dict for one order book entry."""
    def _num(v):
        if v is None:
            return None
        try:
            x = float(v)
            if not math.isfinite(x):
                return 0.0
            return x
        except Exception:
            return 0.0
    def _dt(d):
        return d.isoformat() if d and hasattr(d, "isoformat") else str(d) if d else None
    def _uuid(u):
        return str(u) if u else None
    entry_date = getattr(entry, "entry_date", None)
    return {
        "id": _uuid(entry.id),
        "company_id": _uuid(entry.company_id),
        "branch_id": _uuid(entry.branch_id),
        "item_id": _uuid(entry.item_id),
        "entry_date": _dt(entry_date) if entry_date else None,
        "supplier_id": _uuid(entry.supplier_id),
        "quantity_needed": _safe_float(entry.quantity_needed, 1.0),
        "unit_name": entry.unit_name or "unit",
        "reason": _reason_display(entry),
        "source_reference_type": (
            str(entry.source_reference_type) if entry.source_reference_type is not None else None
        ),
        "source_reference_id": _uuid(entry.source_reference_id),
        "notes": entry.notes,
        "priority": _safe_int(entry.priority, 5),
        "days_in_order_book_90": days_in_book_90,
        "status": entry.status or "PENDING",
        "purchase_order_id": _uuid(entry.purchase_order_id),
        "branch_order_id": _uuid(getattr(entry, "branch_order_id", None)),
        "ordered_at": _dt(getattr(entry, "ordered_at", None)),
        "received_at": _dt(getattr(entry, "received_at", None)),
        "created_by": _uuid(entry.created_by),
        "created_at": _dt(entry.created_at),
        "updated_at": _dt(entry.updated_at),
        "item_name": entry.item.name if entry.item else "Unknown",
        "item_sku": entry.item.sku if entry.item else None,
        "last_wholesale_unit_cost": _num(
            last_wholesale_unit_cost_map.get(entry.item_id) if last_wholesale_unit_cost_map else None
        ),
        "supplier_name": entry.supplier.name if entry.supplier else None,
        "current_stock": _get_stock(entry.item_id),
    }


@router.get("/no-replenishment")
def get_order_book_no_replenishment(
    branch_id: UUID = Query(..., description="Branch ID"),
    company_id: UUID = Query(..., description="Company ID"),
    date_from: Optional[str] = Query(None, description="Filter by entry_date >= (YYYY-MM-DD)"),
    date_to: Optional[str] = Query(None, description="Filter by entry_date <= (YYYY-MM-DD)"),
    limit: int = Query(500, ge=1, le=2000),
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Items that appeared on the order book but have **not** been replenished (no CLOSED / received row).

    Combines **daily** PENDING/ORDERED lines in the date range with **history** ORDERED or CANCELLED
    (excluding ORDERED rows superseded by a CLOSED receipt for the same PO+item). **Never** returns CLOSED.
    """
    user, db = user_and_db
    # --- Daily: still open (not received / not cleared) ---
    dq = db.query(DailyOrderBook).filter(
        DailyOrderBook.branch_id == branch_id,
        DailyOrderBook.company_id == company_id,
        DailyOrderBook.status.in_(["PENDING", "ORDERED"]),
    )
    if date_from:
        try:
            start = date.fromisoformat(date_from.strip())
            if hasattr(DailyOrderBook, "entry_date"):
                dq = dq.filter(DailyOrderBook.entry_date >= start)
            else:
                dq = dq.filter(func.date(DailyOrderBook.created_at) >= start)
        except (ValueError, TypeError):
            pass
    if date_to:
        try:
            end = date.fromisoformat(date_to.strip())
            if hasattr(DailyOrderBook, "entry_date"):
                dq = dq.filter(DailyOrderBook.entry_date <= end)
            else:
                dq = dq.filter(func.date(DailyOrderBook.created_at) <= end)
        except (ValueError, TypeError):
            pass

    daily_entries = (
        dq.options(
            selectinload(DailyOrderBook.item),
            selectinload(DailyOrderBook.supplier),
            selectinload(DailyOrderBook.creator),
        )
        .order_by(DailyOrderBook.priority.desc(), DailyOrderBook.created_at.desc())
        .all()
    )

    # --- History: ORDERED + CANCELLED only (never CLOSED) ---
    hq = (
        db.query(OrderBookHistory)
        .options(
            selectinload(OrderBookHistory.item),
            selectinload(OrderBookHistory.supplier),
        )
        .filter(
            OrderBookHistory.branch_id == branch_id,
            OrderBookHistory.company_id == company_id,
            OrderBookHistory.status.in_(["ORDERED", "CANCELLED"]),
        )
    )
    if date_from:
        try:
            start = date.fromisoformat(date_from.strip())
            if hasattr(OrderBookHistory, "entry_date"):
                hq = hq.filter(OrderBookHistory.entry_date >= start)
            else:
                hq = hq.filter(func.date(OrderBookHistory.created_at) >= start)
        except (ValueError, TypeError):
            pass
    if date_to:
        try:
            end = date.fromisoformat(date_to.strip())
            if hasattr(OrderBookHistory, "entry_date"):
                hq = hq.filter(OrderBookHistory.entry_date <= end)
            else:
                hq = hq.filter(func.date(OrderBookHistory.created_at) <= end)
        except (ValueError, TypeError):
            pass

    _ObClosed = aliased(OrderBookHistory)
    _superseded_ordered = exists(
        select(1).where(
            and_(
                _ObClosed.company_id == OrderBookHistory.company_id,
                _ObClosed.branch_id == OrderBookHistory.branch_id,
                _ObClosed.item_id == OrderBookHistory.item_id,
                _ObClosed.status == "CLOSED",
                _ObClosed.purchase_order_id == OrderBookHistory.purchase_order_id,
                OrderBookHistory.purchase_order_id.isnot(None),
            )
        )
    )
    hq = hq.filter(or_(OrderBookHistory.status != "ORDERED", ~_superseded_ordered))
    hist_entries = (
        hq.order_by(
            func.coalesce(
                OrderBookHistory.archived_at,
                OrderBookHistory.ordered_at,
                OrderBookHistory.updated_at,
                OrderBookHistory.created_at,
            ).desc()
        )
        .limit(limit * 2)
        .all()
    )

    daily_item_ids = {e.item_id for e in daily_entries}
    hist_only = [h for h in hist_entries if h.item_id not in daily_item_ids]

    all_item_ids = list({e.item_id for e in daily_entries} | {h.item_id for h in hist_only})
    days_map = _get_days_in_order_book_90(db, branch_id, all_item_ids)
    try:
        last_wholesale_cost_map = _get_last_wholesale_unit_cost_map(db, branch_id, company_id, all_item_ids)
    except Exception as e:
        logging.getLogger(__name__).warning("no-replenishment cost map failed: %s", e)
        last_wholesale_cost_map = {}

    stock_map = {}
    if all_item_ids:
        try:
            balances = (
                db.query(InventoryBalance.item_id, InventoryBalance.current_stock)
                .filter(
                    InventoryBalance.item_id.in_(all_item_ids),
                    InventoryBalance.company_id == company_id,
                    InventoryBalance.branch_id == branch_id,
                )
                .all()
            )
            stock_map = {row.item_id: _to_int_stock(row.current_stock) for row in balances}
        except Exception:
            stock_map = {}

    def _get_stock(item_id):
        if item_id in stock_map:
            return stock_map[item_id]
        val = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
            InventoryLedger.item_id == item_id,
            InventoryLedger.branch_id == branch_id,
            InventoryLedger.company_id == company_id,
        ).scalar()
        return _to_int_stock(val)

    out: List[dict] = []

    for entry in daily_entries:
        try:
            row = _serialize_order_book_entry(
                entry,
                _get_stock,
                days_in_book_90=days_map.get(entry.item_id, 0),
                last_wholesale_unit_cost_map=last_wholesale_cost_map,
            )
            row["row_source"] = "daily"
            row["replenishment_label"] = (
                "No PO yet" if (entry.status or "") == "PENDING" else "PO placed — no receipt recorded yet"
            )
            ed = getattr(entry, "entry_date", None) or (
                entry.created_at.date() if entry.created_at else date.today()
            )
            row["_sort_d"] = ed
            out.append(row)
        except Exception as e:
            logging.getLogger(__name__).warning("no-replenishment daily row skip %s: %s", entry.id, e)

    for h in hist_only:
        try:
            cost = last_wholesale_cost_map.get(h.item_id)
            entry_dict = {
                "id": str(h.id),
                "company_id": str(h.company_id),
                "branch_id": str(h.branch_id),
                "item_id": str(h.item_id),
                "item_name": h.item.name if h.item else None,
                "item_sku": h.item.sku if h.item else None,
                "supplier_name": h.supplier.name if h.supplier else None,
                "quantity_needed": _safe_float(h.quantity_needed, 0.0),
                "unit_name": h.unit_name or "unit",
                "last_wholesale_unit_cost": _safe_float(cost, 0.0),
                "status": h.status,
                "replenishment_label": (
                    "PO placed — no receipt recorded yet"
                    if h.status == "ORDERED"
                    else "Removed from order book (no replenishment recorded)"
                ),
                "row_source": "history",
                "entry_date": h.entry_date.isoformat() if h.entry_date else None,
                "ordered_at": h.ordered_at.isoformat() if h.ordered_at else None,
                "created_at": h.created_at.isoformat() if h.created_at else None,
                "received_at": None,
                "reason": (h.reason or "")[:200],
                "purchase_order_id": str(h.purchase_order_id) if h.purchase_order_id else None,
                "current_stock": _get_stock(h.item_id),
                "days_in_order_book_90": days_map.get(h.item_id, 0),
            }
            ed = h.entry_date or (h.created_at.date() if h.created_at else date.today())
            entry_dict["_sort_d"] = ed
            out.append(entry_dict)
        except Exception as e:
            logging.getLogger(__name__).warning("no-replenishment history row skip %s: %s", h.id, e)

    out.sort(key=lambda r: r.get("_sort_d", date.min), reverse=True)
    for r in out:
        r.pop("_sort_d", None)
    return _json_response_list(out[:limit])


@router.get("")
@router.get("/")
def list_order_book_entries(
    branch_id: UUID = Query(..., description="Branch ID"),
    company_id: UUID = Query(..., description="Company ID"),
    status_filter: Optional[str] = Query(None, description="Filter by status: PENDING, ORDERED, CANCELLED"),
    date_from: Optional[str] = Query(None, description="Start date (YYYY-MM-DD) for entry_date filter"),
    date_to: Optional[str] = Query(None, description="End date (YYYY-MM-DD) for entry_date filter"),
    include_ordered: Optional[bool] = Query(False, description="If true, include ORDERED entries (for showing converted)"),
    supplier_id: Optional[UUID] = Query(None, description="Filter by supplier: show only items from this supplier"),
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    List order book entries for a branch, optionally filtered by date and supplier.
    Returns JSON array with item details and current stock levels.
    """
    user, db = user_and_db
    try:
        query = db.query(DailyOrderBook).filter(
            DailyOrderBook.branch_id == branch_id,
            DailyOrderBook.company_id == company_id
        )
        if supplier_id is not None:
            query = query.filter(DailyOrderBook.supplier_id == supplier_id)
        if status_filter:
            query = query.filter(DailyOrderBook.status == status_filter)
        elif include_ordered:
            query = query.filter(DailyOrderBook.status.in_(["PENDING", "ORDERED"]))
        else:
            query = query.filter(DailyOrderBook.status == "PENDING")

        # Filter by entry_date when present (date-unique order book); fallback to created_at for pre-migration data
        if date_from:
            try:
                start = date.fromisoformat(date_from.strip())
                if hasattr(DailyOrderBook, "entry_date"):
                    query = query.filter(DailyOrderBook.entry_date >= start)
                else:
                    query = query.filter(func.date(DailyOrderBook.created_at) >= start)
            except (ValueError, TypeError):
                pass
        if date_to:
            try:
                end = date.fromisoformat(date_to.strip())
                if hasattr(DailyOrderBook, "entry_date"):
                    query = query.filter(DailyOrderBook.entry_date <= end)
                else:
                    query = query.filter(func.date(DailyOrderBook.created_at) <= end)
            except (ValueError, TypeError):
                pass

        # Do not selectinload(creator): batch-loading User can fail under RLS or if FK is stale;
        # _reason_display() lazy-loads creator per row inside a try/except.
        entries = (
            query.options(
                selectinload(DailyOrderBook.item),
                selectinload(DailyOrderBook.supplier),
            )
            .order_by(
                DailyOrderBook.priority.desc(),
                DailyOrderBook.created_at.desc()
            )
            .all()
        )

        item_ids = [e.item_id for e in entries]
        days_map = _get_days_in_order_book_90(db, branch_id, item_ids)
        try:
            last_wholesale_cost_map = _get_last_wholesale_unit_cost_map(db, branch_id, company_id, item_ids)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "last wholesale cost map failed; falling back to 0. err=%s", e
            )
            last_wholesale_cost_map = {}
        stock_map = {}
        if item_ids:
            try:
                balances = (
                    db.query(InventoryBalance.item_id, InventoryBalance.current_stock)
                    .filter(
                        InventoryBalance.item_id.in_(item_ids),
                        InventoryBalance.company_id == company_id,
                        InventoryBalance.branch_id == branch_id
                    )
                    .all()
                )
                stock_map = {row.item_id: _to_int_stock(row.current_stock) for row in balances}
            except Exception:
                stock_map = {}

        def _get_stock(item_id):
            try:
                if item_id in stock_map:
                    return stock_map[item_id]
                val = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
                    InventoryLedger.item_id == item_id,
                    InventoryLedger.branch_id == branch_id,
                    InventoryLedger.company_id == company_id,
                ).scalar()
                return _to_int_stock(val)
            except Exception:
                return 0

        result = []
        for entry in entries:
            try:
                days_in_book = days_map.get(entry.item_id, 0)
                result.append(
                    _serialize_order_book_entry(
                        entry,
                        _get_stock,
                        days_in_book_90=days_in_book,
                        last_wholesale_unit_cost_map=last_wholesale_cost_map,
                    )
                )
            except Exception as e:
                logging.getLogger(__name__).warning("Skipping order book entry %s: %s", entry.id, e)
        try:
            return _json_response_list(result)
        except Exception as enc_err:
            # _json_response_list logs the traceback on sanitize/json.dumps failure
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to serialize order book: {enc_err!s}",
            ) from enc_err
    except HTTPException:
        raise
    except Exception as e:
        logging.getLogger(__name__).exception("Order book list failed")
        if settings.DEBUG:
            traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to load order book: {e!s}",
        ) from e


@router.get("/today-summary", response_model=dict)
def get_order_book_today_summary(
    branch_id: UUID = Query(..., description="Branch ID"),
    company_id: UUID = Query(..., description="Company ID"),
    limit: int = Query(10, ge=0, le=200, description="Max entries to include (0 = none)"),
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Lightweight dashboard endpoint: number of PENDING order book entries for *today*,
    plus an optional small list of entries for quick preview.
    """
    user, db = user_and_db
    today = date.today()

    q = db.query(DailyOrderBook).filter(
        DailyOrderBook.branch_id == branch_id,
        DailyOrderBook.company_id == company_id,
        DailyOrderBook.status == "PENDING",
    )
    if hasattr(DailyOrderBook, "entry_date"):
        q = q.filter(DailyOrderBook.entry_date == today)
    else:
        q = q.filter(func.date(DailyOrderBook.created_at) == today)

    pending_count = q.count()

    entries_out = []
    if limit and limit > 0 and pending_count > 0:
        rows = (
            q.options(
                selectinload(DailyOrderBook.item),
                selectinload(DailyOrderBook.supplier),
                selectinload(DailyOrderBook.creator),
            )
            .order_by(DailyOrderBook.priority.desc(), DailyOrderBook.created_at.desc())
            .limit(limit)
            .all()
        )
        item_ids = [e.item_id for e in rows]
        days_map = _get_days_in_order_book_90(db, branch_id, item_ids)
        try:
            last_wholesale_cost_map = _get_last_wholesale_unit_cost_map(db, branch_id, company_id, item_ids)
        except Exception as e:
            logging.getLogger(__name__).warning(
                "today-summary last wholesale cost map failed; falling back to 0. err=%s", e
            )
            last_wholesale_cost_map = {}
        for e in rows:
            entries_out.append(
                {
                    "id": str(e.id),
                    "item_id": str(e.item_id),
                    "item_name": e.item.name if e.item else None,
                    "item_sku": e.item.sku if e.item else None,
                    "quantity_needed": float(e.quantity_needed) if e.quantity_needed is not None else 1,
                    "unit_name": e.unit_name or "unit",
                    "last_wholesale_unit_cost": float(last_wholesale_cost_map.get(e.item_id) or 0),
                    "supplier_id": str(e.supplier_id) if e.supplier_id else None,
                    "supplier_name": e.supplier.name if e.supplier else None,
                    "reason": _reason_display(e),
                    "priority": days_map.get(e.item_id, 0),
                    "created_at": e.created_at.isoformat() if e.created_at else None,
                }
            )

    return {
        "date": today.isoformat(),
        "pending_count": int(pending_count),
        "entries": entries_out,
    }


@router.post("", response_model=OrderBookEntryResponse, status_code=status.HTTP_201_CREATED)
@router.post("/", response_model=OrderBookEntryResponse, status_code=status.HTTP_201_CREATED)
def create_order_book_entry(
    entry: OrderBookEntryCreate,
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: UUID = Query(..., description="Branch ID"),
    created_by: UUID = Query(..., description="User ID creating the entry"),
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Create a new order book entry.
    Returns 409 if the item is already in today's order book.
    """
    user, db = user_and_db
    # Check if item exists
    item = db.query(Item).filter(Item.id == entry.item_id).first()
    if not item:
        raise HTTPException(status_code=404, detail=f"Item {entry.item_id} not found")
    
    # Check if supplier exists (if provided)
    if entry.supplier_id:
        supplier = db.query(Supplier).filter(Supplier.id == entry.supplier_id).first()
        if not supplier:
            raise HTTPException(status_code=404, detail=f"Supplier {entry.supplier_id} not found")
    
    # Entry date: request or today (items unique per branch, item, entry_date)
    entry_date_val = getattr(entry, "entry_date", None) or date.today()
    if hasattr(entry_date_val, "date") and callable(getattr(entry_date_val, "date", None)):
        entry_date_val = entry_date_val.date()

    # Item can only be in the order book once per date; if already PENDING or ORDERED for this date, tell the user
    existing_filter = [
        DailyOrderBook.branch_id == branch_id,
        DailyOrderBook.item_id == entry.item_id,
        DailyOrderBook.status.in_(["PENDING", "ORDERED"])
    ]
    if hasattr(DailyOrderBook, "entry_date"):
        existing_filter.append(DailyOrderBook.entry_date == entry_date_val)
    existing_entry = db.query(DailyOrderBook).filter(*existing_filter).first()

    if existing_entry:
        if existing_entry.status == "ORDERED":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="This item is already on a purchase order (ordered). Check the order book."
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This item is already in the order book for this date."
        )
    # Resolve supplier when not provided: lowest unit cost (per wholesale) or item default from import
    resolved_supplier_id = entry.supplier_id
    if not resolved_supplier_id:
        resolved_supplier_id = OrderBookService.get_supplier_lowest_unit_cost(db, entry.item_id, company_id)
    # Default to wholesale unit (last unit costs are in wholesale)
    unit_name_val = (entry.unit_name or "").strip() or (item.wholesale_unit or item.base_unit or "unit").strip() or "unit"

    # Create new entry (catch race condition: duplicate insert from another request)
    reason = entry.reason or "MANUAL_ADD"
    create_kw = dict(
        company_id=company_id,
        branch_id=branch_id,
        item_id=entry.item_id,
        supplier_id=resolved_supplier_id,
        quantity_needed=entry.quantity_needed,
        unit_name=unit_name_val,
        reason=reason,
        source_reference_type=None,
        source_reference_id=None,
        notes=entry.notes,
        priority=entry.priority,
        status="PENDING",
        created_by=created_by
    )
    if hasattr(DailyOrderBook, "entry_date"):
        create_kw["entry_date"] = entry_date_val
    db_entry = DailyOrderBook(**create_kw)
    db.add(db_entry)
    try:
        db.flush()
        SnapshotService.upsert_search_snapshot_last_order_book(
            db, company_id, branch_id, entry.item_id, db_entry.created_at or datetime.utcnow()
        )
        db.commit()
        db.refresh(db_entry)
    except IntegrityError as e:
        db.rollback()
        logging.getLogger(__name__).warning("Order book duplicate on create (race or constraint): %s", e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This item is already in the order book."
        )

    # Load creator for reason display and compute days-in-book for priority
    db.refresh(db_entry, ["creator", "supplier"])
    days_map = _get_days_in_order_book_90(db, branch_id, [db_entry.item_id])
    reason_display = _reason_display(db_entry)
    priority_display = days_map.get(db_entry.item_id, 0)

    entry_dict = {
        "id": db_entry.id,
        "company_id": db_entry.company_id,
        "branch_id": db_entry.branch_id,
        "item_id": db_entry.item_id,
        "supplier_id": db_entry.supplier_id,
        "entry_date": getattr(db_entry, "entry_date", None),
        "quantity_needed": db_entry.quantity_needed,
        "unit_name": db_entry.unit_name,
        "reason": reason_display,
        "source_reference_type": db_entry.source_reference_type,
        "source_reference_id": db_entry.source_reference_id,
        "notes": db_entry.notes,
        "priority": db_entry.priority if db_entry.priority is not None else 5,
        "days_in_order_book_90": priority_display,
        "status": db_entry.status,
        "purchase_order_id": db_entry.purchase_order_id,
        "created_by": db_entry.created_by,
        "created_at": db_entry.created_at,
        "updated_at": db_entry.updated_at,
        "item_name": item.name,
        "item_sku": item.sku,
        "supplier_name": db_entry.supplier.name if db_entry.supplier else None,
        "current_stock": None
    }
    stock_query = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
        InventoryLedger.item_id == entry.item_id,
        InventoryLedger.branch_id == branch_id
    )
    current_stock = stock_query.scalar() or 0
    entry_dict["current_stock"] = int(current_stock)
    return OrderBookEntryResponse(**entry_dict)


@router.post("/bulk", response_model=OrderBookBulkCreateResponse, status_code=status.HTTP_201_CREATED)
def bulk_create_order_book_entries(
    bulk_data: OrderBookBulkCreate,
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: UUID = Query(..., description="Branch ID"),
    created_by: UUID = Query(..., description="User ID creating the entries"),
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Bulk create order book entries from selected items.
    Items already in the order book (PENDING or ORDERED) for the given date are skipped and returned.
    """
    user, db = user_and_db
    created_entries = []
    skipped_item_ids: List[UUID] = []
    skipped_item_names: List[str] = []

    entry_date_val = getattr(bulk_data, "entry_date", None) or date.today()
    if hasattr(entry_date_val, "date") and callable(getattr(entry_date_val, "date", None)):
        entry_date_val = entry_date_val.date()

    for item_id in bulk_data.item_ids:
        item = db.query(Item).filter(Item.id == item_id).first()
        if not item:
            continue

        existing_filter = [
            DailyOrderBook.branch_id == branch_id,
            DailyOrderBook.item_id == item_id,
            DailyOrderBook.status.in_(["PENDING", "ORDERED"])
        ]
        if hasattr(DailyOrderBook, "entry_date"):
            existing_filter.append(DailyOrderBook.entry_date == entry_date_val)
        existing = db.query(DailyOrderBook).filter(*existing_filter).first()

        if existing:
            skipped_item_ids.append(item_id)
            skipped_item_names.append(item.name or str(item_id))
            continue

        # Resolve supplier per item when not provided: lowest unit cost or item default
        resolved_supplier_id = bulk_data.supplier_id
        if not resolved_supplier_id:
            resolved_supplier_id = OrderBookService.get_supplier_lowest_unit_cost(db, item_id, company_id)
        # Default to wholesale unit (last unit costs are in wholesale)
        unit_name_val = (item.wholesale_unit or item.base_unit or "unit").strip() or "unit"

        create_kw = dict(
            company_id=company_id,
            branch_id=branch_id,
            item_id=item_id,
            supplier_id=resolved_supplier_id,
            quantity_needed=Decimal("1"),
            unit_name=unit_name_val,
            reason=bulk_data.reason or "MANUAL_ADD",
            source_reference_type=None,
            source_reference_id=None,
            notes=bulk_data.notes,
            priority=5,
            status="PENDING",
            created_by=created_by
        )
        if hasattr(DailyOrderBook, "entry_date"):
            create_kw["entry_date"] = entry_date_val
        entry = DailyOrderBook(**create_kw)
        db.add(entry)
        created_entries.append(entry)

    try:
        db.commit()
    except IntegrityError as e:
        db.rollback()
        logging.getLogger(__name__).warning("Order book bulk duplicate (race): %s", e)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="One or more items are already in the order book. Please refresh and try again."
        )

    item_ids_created = [e.item_id for e in created_entries]
    days_map = _get_days_in_order_book_90(db, branch_id, item_ids_created)
    result = []
    for entry in created_entries:
        db.refresh(entry, ["creator", "item", "supplier"])
        entry_dict = {
            "id": entry.id,
            "company_id": entry.company_id,
            "branch_id": entry.branch_id,
            "item_id": entry.item_id,
            "entry_date": getattr(entry, "entry_date", None),
            "supplier_id": entry.supplier_id,
            "quantity_needed": entry.quantity_needed,
            "unit_name": entry.unit_name,
            "reason": _reason_display(entry),
            "source_reference_type": entry.source_reference_type,
            "source_reference_id": entry.source_reference_id,
            "notes": entry.notes,
            "priority": entry.priority if entry.priority is not None else 5,
            "days_in_order_book_90": days_map.get(entry.item_id, 0),
            "status": entry.status,
            "purchase_order_id": entry.purchase_order_id,
            "created_by": entry.created_by,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "item_name": entry.item.name if entry.item else None,
            "item_sku": entry.item.sku if entry.item else None,
            "supplier_name": entry.supplier.name if entry.supplier else None,
            "current_stock": None
        }
        stock_query = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
            InventoryLedger.item_id == entry.item_id,
            InventoryLedger.branch_id == branch_id
        )
        current_stock = stock_query.scalar() or 0
        entry_dict["current_stock"] = int(current_stock)
        result.append(OrderBookEntryResponse(**entry_dict))

    return OrderBookBulkCreateResponse(
        entries=result,
        skipped_item_ids=skipped_item_ids,
        skipped_item_names=skipped_item_names
    )


@router.put("/{entry_id}", response_model=OrderBookEntryResponse)
def update_order_book_entry(
    entry_id: UUID,
    entry_update: OrderBookEntryUpdate,
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Update an order book entry
    
    Only PENDING entries can be updated.
    """
    user, db = user_and_db
    entry = db.query(DailyOrderBook).filter(DailyOrderBook.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Order book entry not found")
    
    if entry.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update entry with status {entry.status}. Only PENDING entries can be updated."
        )
    
    # Update fields
    if entry_update.quantity_needed is not None:
        entry.quantity_needed = entry_update.quantity_needed
    if entry_update.supplier_id is not None:
        entry.supplier_id = entry_update.supplier_id
    if entry_update.priority is not None:
        entry.priority = entry_update.priority
    if entry_update.notes is not None:
        entry.notes = entry_update.notes
    
    entry.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(entry, ["creator", "item", "supplier"])
    days_map = _get_days_in_order_book_90(db, entry.branch_id, [entry.item_id])
    priority_display = days_map.get(entry.item_id, 0)

    # Enhance response
    entry_dict = {
        "id": entry.id,
        "company_id": entry.company_id,
        "branch_id": entry.branch_id,
        "item_id": entry.item_id,
        "supplier_id": entry.supplier_id,
        "quantity_needed": entry.quantity_needed,
        "unit_name": entry.unit_name,
        "reason": _reason_display(entry),
        "source_reference_type": entry.source_reference_type,
        "source_reference_id": entry.source_reference_id,
        "notes": entry.notes,
        "priority": entry.priority if entry.priority is not None else 5,
        "days_in_order_book_90": priority_display,
        "status": entry.status,
        "purchase_order_id": entry.purchase_order_id,
        "created_by": entry.created_by,
        "created_at": entry.created_at,
        "updated_at": entry.updated_at,
        "item_name": entry.item.name if entry.item else None,
        "item_sku": entry.item.sku if entry.item else None,
        "supplier_name": entry.supplier.name if entry.supplier else None,
        "current_stock": None
    }
    
    # Get current stock
    stock_query = db.query(func.sum(InventoryLedger.quantity_delta)).filter(
        InventoryLedger.item_id == entry.item_id,
        InventoryLedger.branch_id == entry.branch_id
    )
    current_stock = stock_query.scalar() or 0
    entry_dict["current_stock"] = int(current_stock)
    
    return OrderBookEntryResponse(**entry_dict)


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_order_book_entry(
    entry_id: UUID,
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Delete (cancel) an order book entry
    
    Moves entry to history with CANCELLED status.
    """
    user, db = user_and_db
    entry = db.query(DailyOrderBook).filter(DailyOrderBook.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=404, detail="Order book entry not found")
    
    if entry.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete entry with status {entry.status}. Only PENDING entries can be deleted."
        )
    
    # Move to history
    history_entry = OrderBookHistory(
        company_id=entry.company_id,
        branch_id=entry.branch_id,
        item_id=entry.item_id,
        supplier_id=entry.supplier_id,
        quantity_needed=entry.quantity_needed,
        unit_name=entry.unit_name,
        reason=entry.reason,
        source_reference_type=entry.source_reference_type,
        source_reference_id=entry.source_reference_id,
        notes=entry.notes,
        priority=entry.priority,
        status="CANCELLED",
        purchase_order_id=entry.purchase_order_id,
        created_by=entry.created_by,
        created_at=entry.created_at,
        updated_at=datetime.utcnow()
    )
    db.add(history_entry)
    
    # Delete from active table
    db.delete(entry)
    db.commit()
    
    return None


# Items enter the order book only via: sale-triggered, stock-level-triggered, or manual add.
# There is no bulk "auto-generate" that creates new entries; use the Date filter and list
# endpoint to see "unserviced" items (open entries for a period).


@router.post("/create-purchase-order", response_model=dict)
def create_purchase_order_from_book(
    request: CreatePurchaseOrderFromBook,
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: UUID = Query(..., description="Branch ID"),
    created_by: UUID = Query(..., description="User ID creating the purchase order"),
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Create a purchase order from selected order book entries
    
    Converts selected order book entries to a purchase order and marks them as ORDERED.
    """
    user, db = user_and_db
    # Get all entries
    entries = db.query(DailyOrderBook).filter(
        DailyOrderBook.id.in_(request.entry_ids),
        DailyOrderBook.branch_id == branch_id,
        DailyOrderBook.status == "PENDING"
    ).all()
    
    if not entries:
        raise HTTPException(status_code=400, detail="No valid entries found")
    
    # Use the supplier selected in the modal for the entire purchase order.
    # Order book entries may have different or null supplier_id; the user's choice in the modal is the source of truth.
    supplier_id = request.supplier_id
    if not supplier_id:
        raise HTTPException(status_code=400, detail="Supplier ID is required")
    
    # Verify supplier exists
    supplier = db.query(Supplier).filter(Supplier.id == supplier_id).first()
    if not supplier:
        raise HTTPException(status_code=404, detail=f"Supplier {supplier_id} not found")
    
    # Parse order date once
    order_date = datetime.fromisoformat(request.order_date.replace('Z', '+00:00')).date() if isinstance(request.order_date, str) else request.order_date

    for attempt in range(2):
        try:
            order_number = DocumentService.get_purchase_order_number(
                db, company_id, branch_id
            )

            total_amount = Decimal("0")
            order_items = []

            for entry in entries:
                item = db.query(Item).filter(Item.id == entry.item_id).first()
                if not item:
                    continue
                quantity = entry.quantity_needed
                unit_name = entry.unit_name
                last_price = Decimal("0")
                last_purchase = db.query(SupplierInvoiceItem).join(SupplierInvoice).filter(
                    SupplierInvoiceItem.item_id == entry.item_id,
                    SupplierInvoice.branch_id == branch_id
                ).order_by(SupplierInvoice.invoice_date.desc()).first()
                if last_purchase:
                    last_price = last_purchase.unit_cost_exclusive
                unit_price = last_price
                total_price = quantity * unit_price
                total_amount += total_price
                order_item = PurchaseOrderItem(
                    purchase_order_id=None,
                    item_id=entry.item_id,
                    unit_name=unit_name,
                    quantity=quantity,
                    unit_price=unit_price,
                    total_price=total_price
                )
                order_items.append(order_item)

            purchase_order = PurchaseOrder(
                company_id=company_id,
                branch_id=branch_id,
                supplier_id=supplier_id,
                order_number=order_number,
                order_date=order_date,
                reference=request.reference,
                notes=request.notes,
                total_amount=total_amount,
                status="PENDING",
                created_by=created_by
            )
            db.add(purchase_order)
            db.flush()

            for item in order_items:
                item.purchase_order_id = purchase_order.id
                db.add(item)

            db.flush()
            for item in order_items:
                SnapshotService.upsert_search_snapshot_last_order(
                    db, company_id, branch_id, item.item_id, order_date
                )

            order_time = datetime.utcnow()
            for entry in entries:
                entry.status = "ORDERED"
                entry.purchase_order_id = purchase_order.id
                entry.supplier_id = supplier_id  # record the supplier used for this PO
                entry.ordered_at = order_time
                entry.updated_at = order_time
                # Optional ORDERED row in history for audit; CLOSED row added when stock is received
                history_entry = OrderBookHistory(
                    company_id=entry.company_id,
                    branch_id=entry.branch_id,
                    item_id=entry.item_id,
                    supplier_id=supplier_id,
                    quantity_needed=entry.quantity_needed,
                    unit_name=entry.unit_name,
                    reason=entry.reason,
                    source_reference_type=entry.source_reference_type,
                    source_reference_id=entry.source_reference_id,
                    notes=entry.notes,
                    priority=entry.priority,
                    status="ORDERED",
                    purchase_order_id=purchase_order.id,
                    branch_order_id=getattr(entry, "branch_order_id", None),
                    entry_date=entry.entry_date,
                    ordered_at=order_time,
                    received_at=None,
                    created_by=entry.created_by,
                    created_at=entry.created_at,
                    updated_at=order_time,
                )
                db.add(history_entry)
                # Entry stays in daily_order_book until stock received (then archived as CLOSED)

            db.commit()
            db.refresh(purchase_order)

            return {
                "purchase_order_id": str(purchase_order.id),
                "order_number": purchase_order.order_number,
                "entries_processed": len(entries)
            }
        except IntegrityError as e:
            db.rollback()
            if attempt == 0:
                logging.getLogger(__name__).warning("Duplicate order number on create from order book, retrying: %s", e)
                continue
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A purchase order was already created (possible duplicate click). Check Purchase Orders list."
            ) from e


@router.get("/history", response_model=List[OrderBookHistoryResponse])
def get_order_book_history(
    branch_id: UUID = Query(..., description="Branch ID"),
    company_id: UUID = Query(..., description="Company ID"),
    limit: int = Query(100, ge=1, le=1000),
    date_from: Optional[str] = Query(None, description="Filter by entry_date >= (YYYY-MM-DD) for day/week/month review"),
    date_to: Optional[str] = Query(None, description="Filter by entry_date <= (YYYY-MM-DD)"),
    history_status: str = Query(
        "ordered",
        description=(
            "Which rows: 'ordered' (PO placed, awaiting receipt — sourcing), "
            "'closed' (replenished/received), 'cancelled', 'all', or comma-separated e.g. closed,ordered"
        ),
    ),
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Order book history: archived rows (ORDERED = on order awaiting receipt; CLOSED = replenished;
    CANCELLED = deleted from daily book). Default is ORDERED so sourcing candidates are visible.
    """
    user, db = user_and_db
    query = (
        db.query(OrderBookHistory)
        .options(
            selectinload(OrderBookHistory.item),
            selectinload(OrderBookHistory.supplier),
        )
        .filter(
            OrderBookHistory.branch_id == branch_id,
            OrderBookHistory.company_id == company_id,
        )
    )
    _hist = (history_status or "ordered").strip().lower()
    allowed = {"ORDERED", "CLOSED", "CANCELLED"}
    if _hist == "all":
        query = query.filter(OrderBookHistory.status.in_(["ORDERED", "CLOSED", "CANCELLED"]))
    elif "," in _hist:
        statuses = []
        for part in _hist.split(","):
            p = part.strip().upper()
            if p == "ORDERED":
                statuses.append("ORDERED")
            elif p == "CLOSED":
                statuses.append("CLOSED")
            elif p == "CANCELLED":
                statuses.append("CANCELLED")
        statuses = [s for s in statuses if s in allowed]
        if not statuses:
            statuses = ["ORDERED"]
        query = query.filter(OrderBookHistory.status.in_(statuses))
    else:
        if _hist in ("ordered", "open", "unclosed"):
            query = query.filter(OrderBookHistory.status == "ORDERED")
        elif _hist in ("closed", "replenished", "received"):
            query = query.filter(OrderBookHistory.status == "CLOSED")
        elif _hist in ("cancelled", "never_fulfilled"):
            query = query.filter(OrderBookHistory.status == "CANCELLED")
        elif _hist in ("no_replenishment", "unserviced", "not_replenished"):
            # ORDERED (awaiting receipt) + CANCELLED (removed); never CLOSED
            query = query.filter(OrderBookHistory.status.in_(["ORDERED", "CANCELLED"]))
        else:
            query = query.filter(OrderBookHistory.status == "ORDERED")
    if date_from:
        try:
            start = date.fromisoformat(date_from.strip())
            if hasattr(OrderBookHistory, "entry_date"):
                query = query.filter(OrderBookHistory.entry_date >= start)
            else:
                query = query.filter(func.date(OrderBookHistory.created_at) >= start)
        except (ValueError, TypeError):
            pass
    if date_to:
        try:
            end = date.fromisoformat(date_to.strip())
            if hasattr(OrderBookHistory, "entry_date"):
                query = query.filter(OrderBookHistory.entry_date <= end)
            else:
                query = query.filter(func.date(OrderBookHistory.created_at) <= end)
        except (ValueError, TypeError):
            pass
    # ORDERED audit rows are created when a PO is placed; CLOSED rows are added when stock is
    # received. Hide ORDERED rows that already have a matching CLOSED row (same PO + item).
    _ObClosed = aliased(OrderBookHistory)
    _superseded_ordered = exists(
        select(1).where(
            and_(
                _ObClosed.company_id == OrderBookHistory.company_id,
                _ObClosed.branch_id == OrderBookHistory.branch_id,
                _ObClosed.item_id == OrderBookHistory.item_id,
                _ObClosed.status == "CLOSED",
                _ObClosed.purchase_order_id == OrderBookHistory.purchase_order_id,
                OrderBookHistory.purchase_order_id.isnot(None),
            )
        )
    )
    query = query.filter(or_(OrderBookHistory.status != "ORDERED", ~_superseded_ordered))
    # ORDERED rows may not have archived_at; CLOSED uses archived_at.
    order_col = func.coalesce(
        OrderBookHistory.archived_at,
        OrderBookHistory.ordered_at,
        OrderBookHistory.updated_at,
        OrderBookHistory.created_at,
    )
    entries = query.order_by(order_col.desc()).limit(limit).all()
    
    last_wholesale_cost_map = _get_last_wholesale_unit_cost_map(
        db,
        branch_id,
        company_id,
        [e.item_id for e in entries],
    )
    result = []
    for entry in entries:
        entry_dict = {
            "id": entry.id,
            "company_id": entry.company_id,
            "branch_id": entry.branch_id,
            "item_id": entry.item_id,
            "supplier_id": entry.supplier_id,
            "quantity_needed": entry.quantity_needed,
            "unit_name": entry.unit_name,
            "reason": entry.reason,
            "source_reference_type": entry.source_reference_type,
            "source_reference_id": entry.source_reference_id,
            "notes": entry.notes,
            "priority": entry.priority,
            "status": entry.status,
            "purchase_order_id": entry.purchase_order_id,
            "branch_order_id": getattr(entry, "branch_order_id", None),
            "entry_date": getattr(entry, "entry_date", None),
            "ordered_at": getattr(entry, "ordered_at", None),
            "received_at": getattr(entry, "received_at", None),
            "created_by": entry.created_by,
            "created_at": entry.created_at,
            "updated_at": entry.updated_at,
            "archived_at": entry.archived_at,
            "item_name": entry.item.name if entry.item else None,
            "item_sku": entry.item.sku if entry.item else None,
            "last_wholesale_unit_cost": last_wholesale_cost_map.get(entry.item_id),
            "supplier_name": entry.supplier.name if entry.supplier else None
        }
        result.append(OrderBookHistoryResponse(**entry_dict))
    
    return result


@router.get("/intelligence/aging", response_model=List[dict])
def get_aging_order_book_entries(
    branch_id: UUID = Query(..., description="Branch ID"),
    company_id: UUID = Query(..., description="Company ID"),
    threshold_days: int = Query(7, ge=1, le=365, description="Minimum age in days for an entry to be considered aging"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Intelligence: aging order book entries.

    Returns open PENDING entries whose entry_date is older than threshold_days.
    """
    user, db = user_and_db
    today = date.today()
    cutoff_date = today - timedelta(days=threshold_days)

    q = (
        db.query(DailyOrderBook, Item.name.label("item_name"))
        .join(Item, Item.id == DailyOrderBook.item_id)
        .filter(
            DailyOrderBook.company_id == company_id,
            DailyOrderBook.branch_id == branch_id,
            DailyOrderBook.status == "PENDING",
            DailyOrderBook.entry_date < cutoff_date,
        )
        .order_by(DailyOrderBook.entry_date.asc())
        .offset(offset)
        .limit(limit)
    )

    rows = q.all()
    result = []
    for entry, item_name in rows:
        age_days = (today - (entry.entry_date or entry.created_at.date())).days
        result.append(
            {
                "item_id": str(entry.item_id),
                "item_name": item_name,
                "branch_id": str(entry.branch_id),
                "entry_date": (entry.entry_date or entry.created_at.date()).isoformat(),
                "age_days": age_days,
                "quantity_needed": float(entry.quantity_needed or 0),
                "reason": entry.reason,
            }
        )
    return result


@router.get("/intelligence/repeated", response_model=List[dict])
def get_repeated_shortages(
    branch_id: UUID = Query(..., description="Branch ID"),
    company_id: UUID = Query(..., description="Company ID"),
    days_window: int = Query(30, ge=1, le=365, description="Lookback window in days"),
    min_count: int = Query(3, ge=1, le=365, description="Minimum shortage occurrences to include"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Intelligence: repeated shortages.

    Uses order_book_history to find items that have appeared frequently in the
    order book within the time window (any status).
    """
    user, db = user_and_db
    today = date.today()
    since = today - timedelta(days=days_window)

    subq = (
        db.query(
            OrderBookHistory.item_id.label("item_id"),
            OrderBookHistory.branch_id.label("branch_id"),
            func.count().label("shortage_count"),
            func.max(
                func.coalesce(
                    OrderBookHistory.entry_date,
                    func.date(OrderBookHistory.created_at),
                )
            ).label("last_entry_date"),
        )
        .filter(
            OrderBookHistory.company_id == company_id,
            OrderBookHistory.branch_id == branch_id,
            func.coalesce(
                OrderBookHistory.entry_date,
                func.date(OrderBookHistory.created_at),
            )
            >= since,
        )
        .group_by(OrderBookHistory.item_id, OrderBookHistory.branch_id)
        .having(func.count() >= min_count)
        .subquery()
    )

    q = (
        db.query(
            subq.c.item_id,
            subq.c.branch_id,
            subq.c.shortage_count,
            subq.c.last_entry_date,
            Item.name.label("item_name"),
        )
        .join(Item, Item.id == subq.c.item_id)
        .order_by(subq.c.shortage_count.desc(), subq.c.last_entry_date.desc())
        .offset(offset)
        .limit(limit)
    )

    rows = q.all()
    result = []
    for row in rows:
        result.append(
            {
                "item_id": str(row.item_id),
                "item_name": row.item_name,
                "branch_id": str(row.branch_id),
                "shortage_count": int(row.shortage_count or 0),
                "last_entry_date": row.last_entry_date.isoformat() if row.last_entry_date else None,
            }
        )
    return result


@router.get("/intelligence/multiple-open", response_model=List[dict])
def get_multiple_open_entries(
    branch_id: UUID = Query(..., description="Branch ID"),
    company_id: UUID = Query(..., description="Company ID"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Intelligence: multiple open entries.

    Finds items with more than one open PENDING entry in the order book.
    """
    user, db = user_and_db
    subq = (
        db.query(
            DailyOrderBook.item_id.label("item_id"),
            DailyOrderBook.branch_id.label("branch_id"),
            func.count().label("open_entries"),
            func.min(
                func.coalesce(
                    DailyOrderBook.entry_date,
                    func.date(DailyOrderBook.created_at),
                )
            ).label("oldest_entry_date"),
        )
        .filter(
            DailyOrderBook.company_id == company_id,
            DailyOrderBook.branch_id == branch_id,
            DailyOrderBook.status == "PENDING",
        )
        .group_by(DailyOrderBook.item_id, DailyOrderBook.branch_id)
        .having(func.count() > 1)
        .subquery()
    )

    q = (
        db.query(
            subq.c.item_id,
            subq.c.branch_id,
            subq.c.open_entries,
            subq.c.oldest_entry_date,
            Item.name.label("item_name"),
        )
        .join(Item, Item.id == subq.c.item_id)
        .order_by(subq.c.oldest_entry_date.asc(), subq.c.open_entries.desc())
        .offset(offset)
        .limit(limit)
    )

    rows = q.all()
    result = []
    for row in rows:
        result.append(
            {
                "item_id": str(row.item_id),
                "item_name": row.item_name,
                "branch_id": str(row.branch_id),
                "open_entries": int(row.open_entries or 0),
                "oldest_entry_date": row.oldest_entry_date.isoformat() if row.oldest_entry_date else None,
            }
        )
    return result


@router.post("/{entry_id}/manual-close", response_model=dict)
def manual_close_order_book_entry(
    entry_id: UUID,
    reason: Optional[str] = Body(None, embed=True, description="Optional manual close reason or note"),
    user_and_db: Tuple[User, Session] = Depends(get_current_user),
):
    """
    Manually close an order book entry.

    - Only allowed for owner/admin users.
    - Does NOT change inventory or procurement flows.
    - Moves the entry to order_book_history with status=CLOSED and a manual note.
    """
    user, db = user_and_db
    if not _user_has_owner_or_admin_role(db, user.id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only owner or admin users can manually close order book entries.",
        )

    entry = db.query(DailyOrderBook).filter(DailyOrderBook.id == entry_id).first()
    if not entry:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order book entry not found")

    if entry.status not in ("PENDING", "ORDERED"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Cannot manually close entry with status {entry.status}. Only PENDING or ORDERED entries can be closed.",
        )

    now = datetime.utcnow()

    manual_note = "MANUAL_CLOSE"
    if reason:
        manual_note = f"MANUAL_CLOSE: {reason.strip()}"
    notes = (entry.notes or "").strip()
    if notes:
        notes = notes + "\n" + manual_note
    else:
        notes = manual_note

    history_row = OrderBookHistory(
        company_id=entry.company_id,
        branch_id=entry.branch_id,
        item_id=entry.item_id,
        supplier_id=entry.supplier_id,
        quantity_needed=entry.quantity_needed,
        unit_name=entry.unit_name,
        reason=entry.reason,
        source_reference_type=entry.source_reference_type,
        source_reference_id=entry.source_reference_id,
        notes=notes,
        priority=entry.priority,
        status="CLOSED",
        purchase_order_id=entry.purchase_order_id,
        branch_order_id=getattr(entry, "branch_order_id", None),
        entry_date=getattr(entry, "entry_date", None),
        ordered_at=getattr(entry, "ordered_at", None),
        received_at=None,
        created_by=entry.created_by,
        created_at=entry.created_at,
        updated_at=now,
        archived_at=now,
    )
    db.add(history_row)
    db.delete(entry)
    db.commit()

    return {
        "entry_id": str(entry_id),
        "status": "CLOSED",
        "closed_at": now.isoformat(),
        "reason": reason,
    }
