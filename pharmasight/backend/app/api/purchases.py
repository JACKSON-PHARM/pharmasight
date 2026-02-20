"""
Purchases API routes (GRN and Supplier Invoices)
"""
from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session, selectinload
from typing import List, Optional
from uuid import UUID
from decimal import Decimal
from datetime import date, datetime, timezone, timedelta
from app.dependencies import get_tenant_db
from app.models import (
    GRN, GRNItem, SupplierInvoice, SupplierInvoiceItem,
    PurchaseOrder, PurchaseOrderItem,
    DailyOrderBook,
    InventoryLedger, Item, Supplier, Branch, User
)
from app.services.item_units_helper import get_unit_multiplier_from_item
from app.schemas.purchase import (
    GRNCreate, GRNResponse,
    SupplierInvoiceCreate, SupplierInvoiceResponse,
    PurchaseOrderCreate, PurchaseOrderResponse
)
from app.services.inventory_service import InventoryService
from app.services.document_service import DocumentService
from app.services.snapshot_service import SnapshotService
from app.utils.vat import vat_rate_to_percent

router = APIRouter()


def _require_batch_and_expiry_for_track_expiry_item(
    item_name: str,
    batches: Optional[List],
    *,
    from_dict: bool = False,
) -> None:
    """
    If item has track_expiry, batches must be present, non-empty, and each batch
    must have batch_number and expiry_date. Raises HTTPException 400 otherwise.
    from_dict: if True, each batch is a dict with keys batch_number, expiry_date.
    """
    if not batches or len(batches) == 0:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Item '{item_name}' has Track Expiry enabled. You must use 'Manage Batches' and enter "
                "at least one batch with Batch Number and Expiry Date before saving."
            ),
        )
    for i, batch in enumerate(batches):
        if from_dict:
            batch_num = batch.get("batch_number") if isinstance(batch.get("batch_number"), str) else None
            expiry = batch.get("expiry_date")
        else:
            batch_num = getattr(batch, "batch_number", None)
            expiry = getattr(batch, "expiry_date", None)
        if not (batch_num and str(batch_num).strip()):
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Item '{item_name}' has Track Expiry enabled. Batch number is required for every batch "
                    "(use Manage Batches and fill Batch Number)."
                ),
            )
        if not expiry:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Item '{item_name}' has Track Expiry enabled. Expiry date is required for every batch "
                    "(use Manage Batches and fill Expiry Date)."
                ),
            )


@router.post("/grn", response_model=GRNResponse, status_code=status.HTTP_201_CREATED)
def create_grn(grn: GRNCreate, db: Session = Depends(get_tenant_db)):
    """
    Create GRN (Goods Received Note)
    
    This updates inventory ledger with stock and cost.
    VAT is handled separately in Purchase Invoice.
    """
    # Generate GRN number
    grn_no = DocumentService.get_grn_number(
        db, grn.company_id, grn.branch_id
    )
    
    total_cost = Decimal("0")
    grn_items = []
    ledger_entries = []
    
    for item_data in grn.items:
        # Get item
        item = db.query(Item).filter(Item.id == item_data.item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
        
        # Unit multiplier from item columns (items table is source of truth)
        multiplier = get_unit_multiplier_from_item(item, item_data.unit_name)
        if multiplier is None:
            raise HTTPException(status_code=404, detail=f"Unit '{item_data.unit_name}' not found for item {item_data.item_id}")
        
        # Handle batch distribution: if batches array is provided, use it; otherwise use legacy single batch
        if item_data.batches and len(item_data.batches) > 0:
            # Multiple batches per item
            total_batch_quantity = sum(batch.quantity for batch in item_data.batches)
            if abs(total_batch_quantity - item_data.quantity) > Decimal("0.01"):  # Allow small rounding differences
                raise HTTPException(
                    status_code=400,
                    detail=f"Sum of batch quantities ({total_batch_quantity}) must equal item quantity ({item_data.quantity})"
                )
            
            # Calculate weighted average cost for validation
            weighted_cost = sum(batch.quantity * batch.unit_cost for batch in item_data.batches) / total_batch_quantity
            cost_variance = abs(weighted_cost - item_data.unit_cost) / item_data.unit_cost if item_data.unit_cost > 0 else 0
            if cost_variance > Decimal("0.01"):  # 1% variance allowed
                raise HTTPException(
                    status_code=400,
                    detail=f"Weighted average batch cost ({weighted_cost}) differs significantly from item unit cost ({item_data.unit_cost})"
                )
            
            # Create GRN item (with first batch info for legacy compatibility)
            first_batch = item_data.batches[0]
            grn_item = GRNItem(
                grn_id=None,
                item_id=item_data.item_id,
                unit_name=item_data.unit_name,
                quantity=item_data.quantity,
                unit_cost=item_data.unit_cost,
                batch_number=first_batch.batch_number,  # Legacy field
                expiry_date=first_batch.expiry_date,  # Legacy field
                total_cost=sum(batch.quantity * batch.unit_cost for batch in item_data.batches)
            )
            grn_items.append(grn_item)
            total_cost += grn_item.total_cost
            
            # Create ledger entries for each batch
            for batch_idx, batch in enumerate(item_data.batches):
                quantity_base = int(float(batch.quantity) * float(multiplier))
                unit_cost_base = Decimal(str(batch.unit_cost)) / multiplier
                
                ledger_entry = InventoryLedger(
                    company_id=grn.company_id,
                    branch_id=grn.branch_id,
                    item_id=item_data.item_id,
                    batch_number=batch.batch_number,
                    expiry_date=batch.expiry_date,
                    transaction_type="PURCHASE",
                    reference_type="grn",
                    quantity_delta=quantity_base,
                    unit_cost=unit_cost_base,
                    total_cost=unit_cost_base * quantity_base,
                    batch_cost=unit_cost_base,  # Store batch-specific cost
                    remaining_quantity=quantity_base,  # Initialize remaining quantity
                    is_batch_tracked=True,
                    split_sequence=batch_idx,  # 0 for first batch, 1, 2, 3... for subsequent
                    created_by=grn.created_by
                )
                ledger_entries.append(ledger_entry)
        else:
            # Legacy: single batch (backward compatibility)
            quantity_base = InventoryService.convert_to_base_units(
                db, item_data.item_id, float(item_data.quantity), item_data.unit_name
            )
            
            unit_cost_base = Decimal(str(item_data.unit_cost)) / multiplier
            
            total_item_cost = Decimal(str(item_data.unit_cost)) * item_data.quantity
            total_cost += total_item_cost
            
            # Create GRN item
            grn_item = GRNItem(
                grn_id=None,
                item_id=item_data.item_id,
                unit_name=item_data.unit_name,
                quantity=item_data.quantity,
                unit_cost=item_data.unit_cost,
                batch_number=item_data.batch_number,
                expiry_date=item_data.expiry_date,
                total_cost=total_item_cost
            )
            grn_items.append(grn_item)
            
            # Create ledger entry (positive for purchase)
            ledger_entry = InventoryLedger(
                company_id=grn.company_id,
                branch_id=grn.branch_id,
                item_id=item_data.item_id,
                batch_number=item_data.batch_number,
                expiry_date=item_data.expiry_date,
                transaction_type="PURCHASE",
                reference_type="grn",
                quantity_delta=quantity_base,
                unit_cost=unit_cost_base,
                total_cost=unit_cost_base * quantity_base,
                batch_cost=unit_cost_base,
                remaining_quantity=quantity_base,
                is_batch_tracked=bool(item_data.batch_number),  # Track if batch number provided
                created_by=grn.created_by
            )
            ledger_entries.append(ledger_entry)
    # Reject duplicate POST within same request window (e.g. double submit)
    window = datetime.now(timezone.utc) - timedelta(seconds=2)
    recent_same = (
        db.query(GRN)
        .filter(
            GRN.company_id == grn.company_id,
            GRN.branch_id == grn.branch_id,
            GRN.supplier_id == grn.supplier_id,
            GRN.date_received == grn.date_received,
            GRN.total_cost >= total_cost - Decimal("0.01"),
            GRN.total_cost <= total_cost + Decimal("0.01"),
            GRN.created_at >= window,
        )
        .first()
    )
    if recent_same:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A GRN with the same details was just created. If this was a duplicate request, ignore.",
        )
    # Create GRN
    db_grn = GRN(
        company_id=grn.company_id,
        branch_id=grn.branch_id,
        supplier_id=grn.supplier_id,
        grn_no=grn_no,
        date_received=grn.date_received,
        total_cost=total_cost,
        notes=grn.notes,
        created_by=grn.created_by
    )
    db.add(db_grn)
    db.flush()
    
    # Link items to GRN
    for item in grn_items:
        item.grn_id = db_grn.id
        db.add(item)
    
    # Add ledger entries
    for entry in ledger_entries:
        entry.reference_id = db_grn.id
        db.add(entry)

    db.flush()

    # Update snapshots in same transaction
    for entry in ledger_entries:
        SnapshotService.upsert_inventory_balance(db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta)
        SnapshotService.upsert_purchase_snapshot(
            db, entry.company_id, entry.branch_id, entry.item_id,
            entry.unit_cost, getattr(entry, "created_at", None) or datetime.now(timezone.utc),
            db_grn.supplier_id
        )

    db.commit()
    db.refresh(db_grn)
    return db_grn


@router.get("/grn/{grn_id}", response_model=GRNResponse)
def get_grn(grn_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get GRN by ID"""
    # Eagerly load items relationship to avoid lazy loading issues
    grn = db.query(GRN).options(
        selectinload(GRN.items)
    ).filter(GRN.id == grn_id).first()
    if not grn:
        raise HTTPException(status_code=404, detail="GRN not found")
    return grn


@router.post("/invoice", response_model=SupplierInvoiceResponse, status_code=status.HTTP_201_CREATED)
def create_supplier_invoice(invoice: SupplierInvoiceCreate, db: Session = Depends(get_tenant_db)):
    """
    Create Supplier Invoice (DRAFT - No Stock Added Yet)
    
    Saves the invoice as DRAFT. Stock is NOT added until invoice is batched.
    Use the /invoice/{id}/batch endpoint to add stock to inventory.
    System document number is ALWAYS auto-generated.
    Supplier's invoice number (external) is stored in reference field.
    """
    # ALWAYS auto-generate system document number (internal document number)
    # Supplier's invoice number is stored separately in reference field
    invoice_number = DocumentService.get_supplier_invoice_number(
        db, invoice.company_id, invoice.branch_id
    )
    
    total_exclusive = Decimal("0")
    total_vat = Decimal("0")
    invoice_items = []
    # NO ledger entries here - stock is added when batching
    
    for item_data in invoice.items:
        # Get item
        item = db.query(Item).filter(Item.id == item_data.item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
        
        multiplier = get_unit_multiplier_from_item(item, item_data.unit_name)
        if multiplier is None:
            raise HTTPException(status_code=404, detail=f"Unit '{item_data.unit_name}' not found for item {item_data.item_id}")
        
        # Enforce batch + expiry for items with Track Expiry enabled
        if getattr(item, "track_expiry", False):
            _require_batch_and_expiry_for_track_expiry_item(
                item.name or str(item_data.item_id),
                item_data.batches,
                from_dict=False,
            )
        
        # Calculate line totals (VAT) — normalize vat_rate (e.g. 0.16 -> 16%)
        line_total_exclusive = item_data.unit_cost_exclusive * item_data.quantity
        vat_rate_pct = Decimal(str(vat_rate_to_percent(item_data.vat_rate)))
        line_vat = line_total_exclusive * vat_rate_pct / Decimal("100")
        line_total_inclusive = line_total_exclusive + line_vat
        
        # Store batch data as JSON for later batching
        batch_data_json = None
        if item_data.batches and len(item_data.batches) > 0:
            import json
            batch_data_json = json.dumps([{
                "batch_number": batch.batch_number or "",
                "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
                "quantity": float(batch.quantity),
                "unit_cost": float(batch.unit_cost)
            } for batch in item_data.batches])
        
        invoice_item = SupplierInvoiceItem(
            purchase_invoice_id=None,  # Will be set after invoice creation (keep column name for backward compatibility)
            item_id=item_data.item_id,
            unit_name=item_data.unit_name,
            quantity=item_data.quantity,
            unit_cost_exclusive=item_data.unit_cost_exclusive,
            vat_rate=vat_rate_pct,
            vat_amount=line_vat,
            line_total_exclusive=line_total_exclusive,
            line_total_inclusive=line_total_inclusive,
            batch_data=batch_data_json  # Store batch data for later
        )
        invoice_items.append(invoice_item)
        
        total_exclusive += line_total_exclusive
        total_vat += line_vat
        
        # NOTE: Stock is NOT added here. It's added when invoice is batched via /invoice/{id}/batch
    
    total_inclusive = total_exclusive + total_vat
    balance = total_inclusive - (invoice.amount_paid or Decimal("0"))
    
    # Create supplier invoice (DRAFT status - no stock added yet)
    db_invoice = SupplierInvoice(
        company_id=invoice.company_id,
        branch_id=invoice.branch_id,
        supplier_id=invoice.supplier_id,
        invoice_number=invoice_number,  # System-generated document number (always auto-generated)
        pin_number=None,  # Deprecated field
        reference=invoice.supplier_invoice_number or invoice.reference,  # Store supplier's invoice number (external) in reference
        invoice_date=invoice.invoice_date,
        linked_grn_id=invoice.linked_grn_id,
        total_exclusive=total_exclusive,
        vat_rate=invoice.vat_rate,
        vat_amount=total_vat,
        total_inclusive=total_inclusive,
        status=invoice.status or "DRAFT",  # Save as DRAFT
        payment_status=invoice.payment_status or "UNPAID",
        amount_paid=invoice.amount_paid or Decimal("0"),
        balance=balance,
        created_by=invoice.created_by
    )
    db.add(db_invoice)
    db.flush()
    
    # Link items (store batch data in items for later batching)
    for item in invoice_items:
        item.purchase_invoice_id = db_invoice.id
        db.add(item)
    
    # NOTE: NO stock ledger entries here - stock is added when batching
    
    db.commit()
    db.refresh(db_invoice)
    return db_invoice


@router.get("/invoice", response_model=List[SupplierInvoiceResponse])
def list_supplier_invoices(
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: Optional[UUID] = Query(None, description="Branch ID"),
    supplier_id: Optional[UUID] = Query(None, description="Supplier ID"),
    date_from: Optional[date] = Query(None, description="Filter invoices from this date"),
    date_to: Optional[date] = Query(None, description="Filter invoices to this date"),
    db: Session = Depends(get_tenant_db)
):
    """
    List supplier invoices with filtering
    
    Supplier Invoices are receiving documents that ADD STOCK to inventory.
    Can only be reversed by supplier credit notes.
    """
    query = db.query(SupplierInvoice).filter(SupplierInvoice.company_id == company_id)
    
    if branch_id:
        query = query.filter(SupplierInvoice.branch_id == branch_id)
    
    if supplier_id:
        query = query.filter(SupplierInvoice.supplier_id == supplier_id)
    
    if date_from:
        query = query.filter(SupplierInvoice.invoice_date >= date_from)
    
    if date_to:
        query = query.filter(SupplierInvoice.invoice_date <= date_to)
    
    # Order by date descending (newest first)
    # Eagerly load items relationship to avoid lazy loading issues
    invoices = query.options(
        selectinload(SupplierInvoice.items)
    ).order_by(SupplierInvoice.invoice_date.desc(), SupplierInvoice.created_at.desc()).all()
    
    # Load supplier and branch names, and ensure all invoices have document numbers
    for invoice in invoices:
        if invoice.supplier:
            invoice.supplier_name = invoice.supplier.name
        if invoice.branch:
            invoice.branch_name = invoice.branch.name
        # Load created_by user name
        created_by_user = db.query(User).filter(User.id == invoice.created_by).first()
        if created_by_user:
            invoice.created_by_name = created_by_user.full_name or created_by_user.email
        
        # Ensure invoice has system document number (SPV{BRANCH}-{N})
        # Assign if missing or invalid
        if not invoice.invoice_number or not str(invoice.invoice_number).strip().startswith("SPV"):
            try:
                invoice.invoice_number = DocumentService.get_supplier_invoice_number(
                    db, invoice.company_id, invoice.branch_id
                )
                db.commit()  # Commit the assignment
                # Refresh to get the updated value
                db.refresh(invoice)
            except Exception as e:
                # If branch code is missing, log but don't fail
                import logging
                logger = logging.getLogger(__name__)
                logger.warning(f"Could not assign invoice number to invoice {invoice.id}: {e}")
                # Try to get branch info for better error message
                branch = db.query(Branch).filter(Branch.id == invoice.branch_id).first()
                if branch and not branch.code:
                    logger.warning(f"Branch {invoice.branch_id} is missing a code. Please set branch code in settings.")
                pass
    
    return invoices


@router.get("/invoice/{invoice_id}", response_model=SupplierInvoiceResponse)
def get_supplier_invoice(invoice_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get supplier invoice by ID with full item details"""
    # Load invoice with items and item relationships (similar to get_purchase_order)
    invoice = db.query(SupplierInvoice).options(
        selectinload(SupplierInvoice.items).selectinload(SupplierInvoiceItem.item)
    ).filter(SupplierInvoice.id == invoice_id).first()
    
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    # Load supplier and branch names
    if invoice.supplier:
        invoice.supplier_name = invoice.supplier.name
    if invoice.branch:
        invoice.branch_name = invoice.branch.name
    # Load created_by user name
    created_by_user = db.query(User).filter(User.id == invoice.created_by).first()
    if created_by_user:
        invoice.created_by_name = created_by_user.full_name or created_by_user.email
    
    # Enhance items with full item details (similar to purchase order response)
    for invoice_item in invoice.items:
        if invoice_item.item:
            # Add item details to invoice_item object (will be serialized by response model)
            invoice_item.item_code = invoice_item.item.sku or ''
            invoice_item.item_name = invoice_item.item.name or ''
            invoice_item.item_category = invoice_item.item.category or ''
            invoice_item.base_unit = invoice_item.item.base_unit or ''
        # batch_data is already stored in the database and will be included in response
    
    return invoice


@router.put("/invoice/{invoice_id}", response_model=SupplierInvoiceResponse)
def update_supplier_invoice(invoice_id: UUID, invoice_update: SupplierInvoiceCreate, db: Session = Depends(get_tenant_db)):
    """
    Update supplier invoice (only if status is DRAFT)
    
    Only DRAFT invoices can be updated. BATCHED invoices cannot be updated
    (stock already added to inventory).
    
    This endpoint is called:
    - When user clicks "Update Invoice" button
    - Automatically when changes occur (auto-save)
    """
    db_invoice = db.query(SupplierInvoice).filter(SupplierInvoice.id == invoice_id).first()
    if not db_invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if db_invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update invoice with status {db_invoice.status}. Only DRAFT invoices can be updated. Stock has already been added to inventory."
        )
    
    # Ensure DRAFT has system document number (SPV{BRANCH}-{N}); assign if missing
    if not db_invoice.invoice_number or not str(db_invoice.invoice_number).strip().startswith("SPV"):
        try:
            db_invoice.invoice_number = DocumentService.get_supplier_invoice_number(
                db, db_invoice.company_id, db_invoice.branch_id
            )
        except Exception:
            pass  # Branch may lack code; keep existing value
    
    # Update invoice fields
    db_invoice.supplier_id = invoice_update.supplier_id
    db_invoice.invoice_date = invoice_update.invoice_date
    db_invoice.reference = invoice_update.supplier_invoice_number or invoice_update.reference
    db_invoice.linked_grn_id = invoice_update.linked_grn_id
    db_invoice.vat_rate = invoice_update.vat_rate
    db_invoice.payment_status = invoice_update.payment_status or "UNPAID"
    db_invoice.amount_paid = invoice_update.amount_paid or Decimal("0")
    
    # Recalculate totals
    total_exclusive = Decimal("0")
    total_vat = Decimal("0")
    
    # Delete existing items
    db.query(SupplierInvoiceItem).filter(SupplierInvoiceItem.purchase_invoice_id == invoice_id).delete()
    
    # Add new items
    invoice_items = []
    for item_data in invoice_update.items:
        # Get item
        item = db.query(Item).filter(Item.id == item_data.item_id).first()
        if not item:
            raise HTTPException(status_code=404, detail=f"Item {item_data.item_id} not found")
        
        multiplier = get_unit_multiplier_from_item(item, item_data.unit_name)
        if multiplier is None:
            raise HTTPException(status_code=404, detail=f"Unit '{item_data.unit_name}' not found for item {item_data.item_id}")
        
        # Enforce batch + expiry for items with Track Expiry enabled
        if getattr(item, "track_expiry", False):
            _require_batch_and_expiry_for_track_expiry_item(
                item.name or str(item_data.item_id),
                item_data.batches,
                from_dict=False,
            )
        
        # Calculate line totals (VAT) — normalize vat_rate (e.g. 0.16 -> 16%)
        line_total_exclusive = item_data.unit_cost_exclusive * item_data.quantity
        vat_rate_pct = Decimal(str(vat_rate_to_percent(item_data.vat_rate)))
        line_vat = line_total_exclusive * vat_rate_pct / Decimal("100")
        line_total_inclusive = line_total_exclusive + line_vat
        
        # Store batch data as JSON for later batching
        batch_data_json = None
        if item_data.batches and len(item_data.batches) > 0:
            import json
            batch_data_json = json.dumps([{
                "batch_number": batch.batch_number or "",
                "expiry_date": batch.expiry_date.isoformat() if batch.expiry_date else None,
                "quantity": float(batch.quantity),
                "unit_cost": float(batch.unit_cost)
            } for batch in item_data.batches])
        
        invoice_item = SupplierInvoiceItem(
            purchase_invoice_id=invoice_id,
            item_id=item_data.item_id,
            unit_name=item_data.unit_name,
            quantity=item_data.quantity,
            unit_cost_exclusive=item_data.unit_cost_exclusive,
            vat_rate=vat_rate_pct,
            vat_amount=line_vat,
            line_total_exclusive=line_total_exclusive,
            line_total_inclusive=line_total_inclusive,
            batch_data=batch_data_json  # Store batch data for later
        )
        invoice_items.append(invoice_item)
        db.add(invoice_item)
        
        total_exclusive += line_total_exclusive
        total_vat += line_vat
    
    total_inclusive = total_exclusive + total_vat
    balance = total_inclusive - db_invoice.amount_paid
    
    # Update invoice totals
    db_invoice.total_exclusive = total_exclusive
    db_invoice.vat_amount = total_vat
    db_invoice.total_inclusive = total_inclusive
    db_invoice.balance = balance
    
    # Update payment status based on amount paid
    if db_invoice.amount_paid <= 0:
        db_invoice.payment_status = "UNPAID"
    elif db_invoice.amount_paid >= total_inclusive:
        db_invoice.payment_status = "PAID"
        db_invoice.balance = Decimal("0")
    else:
        db_invoice.payment_status = "PARTIAL"
    
    db.commit()
    db.refresh(db_invoice)
    
    # Load relationships for response
    if db_invoice.supplier:
        db_invoice.supplier_name = db_invoice.supplier.name
    if db_invoice.branch:
        db_invoice.branch_name = db_invoice.branch.name
    created_by_user = db.query(User).filter(User.id == db_invoice.created_by).first()
    if created_by_user:
        db_invoice.created_by_name = created_by_user.full_name or created_by_user.email
    
    # Enhance items with full item details
    for invoice_item in db_invoice.items:
        if invoice_item.item:
            invoice_item.item_code = invoice_item.item.sku or ''
            invoice_item.item_name = invoice_item.item.name or ''
            invoice_item.item_category = invoice_item.item.category or ''
            invoice_item.base_unit = invoice_item.item.base_unit or ''
        # batch_data is already stored in the database and will be included in response
    
    return db_invoice


@router.post("/invoice/{invoice_id}/batch", response_model=SupplierInvoiceResponse)
def batch_supplier_invoice(invoice_id: UUID, db: Session = Depends(get_tenant_db)):
    """
    Batch Supplier Invoice - Add Stock to Inventory

    Row-level lock on invoice prevents concurrent batch; status checked after lock.
    Only DRAFT invoices can be batched. Once batched, status changes to BATCHED.
    Ensures invoice has a system document number (SPV...) before batching; assigns one if missing.
    """
    invoice = (
        db.query(SupplierInvoice)
        .options(selectinload(SupplierInvoice.items))
        .filter(SupplierInvoice.id == invoice_id)
        .with_for_update()
        .first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice.status == "BATCHED":
        raise HTTPException(
            status_code=400,
            detail="Invoice is already batched. Stock has already been added to inventory."
        )
    
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot batch invoice with status {invoice.status}. Only DRAFT invoices can be batched."
        )
    
    # Ensure invoice has system document number (SPV{BRANCH}-{N}); assign if missing (e.g. legacy invoices)
    if not invoice.invoice_number or not str(invoice.invoice_number).strip().startswith("SPV"):
        try:
            invoice.invoice_number = DocumentService.get_supplier_invoice_number(
                db, invoice.company_id, invoice.branch_id
            )
        except Exception as e:
            raise HTTPException(
                status_code=400,
                detail=f"Cannot batch: could not assign document number. Ensure branch has a code. {e!s}"
            )
    
    if not invoice.items or len(invoice.items) == 0:
        raise HTTPException(
            status_code=400,
            detail="Invoice has no line items. Add items before batching."
        )
    
    # Process each item and add stock based on batch data
    ledger_entries = []
    import json
    
    for invoice_item in invoice.items:
        item = db.query(Item).filter(Item.id == invoice_item.item_id).first()
        if not item:
            raise HTTPException(
                status_code=400,
                detail=f"Item {invoice_item.item_id} not found. Cannot batch."
            )
        
        multiplier = get_unit_multiplier_from_item(item, invoice_item.unit_name)
        if multiplier is None:
            raise HTTPException(
                status_code=400,
                detail=f"Unit '{invoice_item.unit_name}' not found for item {item.name}. Cannot batch."
            )
        
        # Enforce batch + expiry for items with Track Expiry enabled (before batching)
        if getattr(item, "track_expiry", False):
            if not (invoice_item.batch_data and str(invoice_item.batch_data).strip()):
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Item '{item.name}' has Track Expiry enabled. Use 'Manage Batches' and enter "
                        "at least one batch with Batch Number and Expiry Date before batching."
                    ),
                )
            try:
                batches_validate = json.loads(invoice_item.batch_data)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Item '{item.name}' has invalid batch data. Use 'Manage Batches' and enter "
                        "Batch Number and Expiry Date for each batch."
                    ),
                )
            if not batches_validate:
                raise HTTPException(
                    status_code=400,
                    detail=(
                        f"Item '{item.name}' has Track Expiry enabled. Use 'Manage Batches' and enter "
                        "at least one batch with Batch Number and Expiry Date before batching."
                    ),
                )
            _require_batch_and_expiry_for_track_expiry_item(
                item.name or str(invoice_item.item_id),
                batches_validate,
                from_dict=True,
            )
        
        # Parse batch data from JSON
        if invoice_item.batch_data:
            try:
                batches = json.loads(invoice_item.batch_data)
                # Empty batch list = no distribution; add full quantity as single entry so stock is still added
                if not batches:
                    quantity_base = InventoryService.convert_to_base_units(
                        db, invoice_item.item_id, float(invoice_item.quantity), invoice_item.unit_name
                    )
                    unit_cost_base = Decimal(str(invoice_item.unit_cost_exclusive)) / multiplier
                    ledger_entry = InventoryLedger(
                        company_id=invoice.company_id,
                        branch_id=invoice.branch_id,
                        item_id=invoice_item.item_id,
                        batch_number=None,
                        expiry_date=None,
                        transaction_type="PURCHASE",
                        reference_type="purchase_invoice",
                        quantity_delta=quantity_base,
                        unit_cost=unit_cost_base,
                        total_cost=unit_cost_base * quantity_base,
                        batch_cost=unit_cost_base,
                        remaining_quantity=quantity_base,
                        is_batch_tracked=False,
                        reference_id=invoice.id,
                        created_by=invoice.created_by
                    )
                    ledger_entries.append(ledger_entry)
                    continue
                # Validate batch quantities sum to item quantity
                total_batch_quantity = sum(batch.get("quantity", 0) for batch in batches)
                if abs(total_batch_quantity - float(invoice_item.quantity)) > 0.01:
                    raise HTTPException(
                        status_code=400,
                        detail=f"Sum of batch quantities ({total_batch_quantity}) must equal item quantity ({invoice_item.quantity}) for item {item.name}"
                    )
                
                # Create ledger entries for each batch
                for batch_idx, batch in enumerate(batches):
                    expiry_date = None
                    if batch.get("expiry_date"):
                        expiry_date = datetime.fromisoformat(batch["expiry_date"]).date()
                    
                    quantity_base = int(float(batch["quantity"]) * float(multiplier))
                    unit_cost_base = Decimal(str(batch["unit_cost"])) / multiplier
                    
                    ledger_entry = InventoryLedger(
                        company_id=invoice.company_id,
                        branch_id=invoice.branch_id,
                        item_id=invoice_item.item_id,
                        batch_number=batch.get("batch_number") or None,
                        expiry_date=expiry_date,
                        transaction_type="PURCHASE",
                        reference_type="purchase_invoice",
                        quantity_delta=quantity_base,  # Positive = add stock
                        unit_cost=unit_cost_base,
                        total_cost=unit_cost_base * quantity_base,
                        batch_cost=unit_cost_base,
                        remaining_quantity=quantity_base,
                        is_batch_tracked=bool(batch.get("batch_number")),
                        split_sequence=batch_idx,
                        reference_id=invoice.id,
                        created_by=invoice.created_by
                    )
                    ledger_entries.append(ledger_entry)
            except json.JSONDecodeError:
                # If batch_data is invalid JSON, create single entry without batch
                quantity_base = InventoryService.convert_to_base_units(
                    db, invoice_item.item_id, float(invoice_item.quantity), invoice_item.unit_name
                )
                unit_cost_base = Decimal(str(invoice_item.unit_cost_exclusive)) / multiplier
                
                ledger_entry = InventoryLedger(
                    company_id=invoice.company_id,
                    branch_id=invoice.branch_id,
                    item_id=invoice_item.item_id,
                    batch_number=None,
                    expiry_date=None,
                    transaction_type="PURCHASE",
                    reference_type="purchase_invoice",
                    quantity_delta=quantity_base,
                    unit_cost=unit_cost_base,
                    total_cost=unit_cost_base * quantity_base,
                    batch_cost=unit_cost_base,
                    remaining_quantity=quantity_base,
                    is_batch_tracked=False,
                    reference_id=invoice.id,
                    created_by=invoice.created_by
                )
                ledger_entries.append(ledger_entry)
        else:
            # No batch data - create single entry
            quantity_base = InventoryService.convert_to_base_units(
                db, invoice_item.item_id, float(invoice_item.quantity), invoice_item.unit_name
            )
            unit_cost_base = Decimal(str(invoice_item.unit_cost_exclusive)) / multiplier
            
            ledger_entry = InventoryLedger(
                company_id=invoice.company_id,
                branch_id=invoice.branch_id,
                item_id=invoice_item.item_id,
                batch_number=None,
                expiry_date=None,
                transaction_type="PURCHASE",
                reference_type="purchase_invoice",
                quantity_delta=quantity_base,
                unit_cost=unit_cost_base,
                total_cost=unit_cost_base * quantity_base,
                batch_cost=unit_cost_base,
                remaining_quantity=quantity_base,
                is_batch_tracked=False,
                reference_id=invoice.id,
                created_by=invoice.created_by
            )
            ledger_entries.append(ledger_entry)
    
    # Add all ledger entries
    for entry in ledger_entries:
        db.add(entry)

    db.flush()

    # Update snapshots in same transaction
    for entry in ledger_entries:
        SnapshotService.upsert_inventory_balance(db, entry.company_id, entry.branch_id, entry.item_id, entry.quantity_delta)
    for inv_item in invoice.items:
        SnapshotService.upsert_purchase_snapshot(
            db, invoice.company_id, invoice.branch_id, inv_item.item_id,
            inv_item.unit_cost_exclusive, invoice.created_at, invoice.supplier_id
        )

    # Update invoice status to BATCHED
    invoice.status = "BATCHED"

    db.commit()
    db.refresh(invoice)
    
    # Load relationships for response
    if invoice.supplier:
        invoice.supplier_name = invoice.supplier.name
    if invoice.branch:
        invoice.branch_name = invoice.branch.name
    created_by_user = db.query(User).filter(User.id == invoice.created_by).first()
    if created_by_user:
        invoice.created_by_name = created_by_user.full_name or created_by_user.email
    
    return invoice


@router.put("/invoice/{invoice_id}/payment", response_model=SupplierInvoiceResponse)
def update_invoice_payment(
    invoice_id: UUID,
    amount_paid: Decimal = Query(..., description="Amount paid to supplier"),
    db: Session = Depends(get_tenant_db)
):
    """
    Update payment information for supplier invoice.
    Only BATCHED or DRAFT; amount_paid must not exceed total_inclusive.
    """
    invoice = (
        db.query(SupplierInvoice).filter(SupplierInvoice.id == invoice_id).with_for_update().first()
    )
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    if invoice.status not in ("DRAFT", "BATCHED"):
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update payment for invoice with status {invoice.status}. Only DRAFT or BATCHED."
        )
    if amount_paid > invoice.total_inclusive:
        raise HTTPException(
            status_code=400,
            detail=f"Amount paid ({amount_paid}) cannot exceed invoice total ({invoice.total_inclusive})."
        )
    invoice.amount_paid = amount_paid
    invoice.balance = invoice.total_inclusive - amount_paid
    if amount_paid <= 0:
        invoice.payment_status = "UNPAID"
    elif amount_paid >= invoice.total_inclusive:
        invoice.payment_status = "PAID"
        invoice.balance = Decimal("0")
        # Mark as complete when fully paid (if already batched)
        if invoice.status == "BATCHED":
            # Could add a "COMPLETE" status or keep as BATCHED with PAID status
            pass
    else:
        invoice.payment_status = "PARTIAL"
    
    db.commit()
    db.refresh(invoice)
    
    # Load relationships for response
    if invoice.supplier:
        invoice.supplier_name = invoice.supplier.name
    if invoice.branch:
        invoice.branch_name = invoice.branch.name
    created_by_user = db.query(User).filter(User.id == invoice.created_by).first()
    if created_by_user:
        invoice.created_by_name = created_by_user.full_name or created_by_user.email
    
    return invoice


@router.delete("/invoice/{invoice_id}", status_code=status.HTTP_200_OK)
def delete_supplier_invoice(invoice_id: UUID, db: Session = Depends(get_tenant_db)):
    """
    Delete Supplier Invoice (Only if DRAFT status)
    
    Only DRAFT invoices can be deleted. BATCHED invoices cannot be deleted
    (stock already added to inventory).
    """
    invoice = db.query(SupplierInvoice).filter(SupplierInvoice.id == invoice_id).first()
    if not invoice:
        raise HTTPException(status_code=404, detail="Invoice not found")
    
    if invoice.status != "DRAFT":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete invoice with status {invoice.status}. Only DRAFT invoices can be deleted."
        )
    
    # Delete invoice items (cascade should handle this, but explicit is safer)
    db.query(SupplierInvoiceItem).filter(SupplierInvoiceItem.purchase_invoice_id == invoice_id).delete()
    
    # Delete invoice
    db.delete(invoice)
    db.commit()
    
    return {"message": "Invoice deleted successfully", "deleted": True}


# =====================================================
# PURCHASE ORDERS
# =====================================================

@router.post("/order", response_model=PurchaseOrderResponse, status_code=status.HTTP_201_CREATED)
def create_purchase_order(order: PurchaseOrderCreate, db: Session = Depends(get_tenant_db)):
    """
    Create Purchase Order
    
    Purchase orders are created before receiving goods.
    They can later be converted to GRN when goods are received.
    """
    # Generate order number
    order_no = DocumentService.get_purchase_order_number(
        db, order.company_id, order.branch_id
    )
    
    total_amount = Decimal("0")
    order_items = []
    
    for item_data in order.items:
        total_item_price = Decimal(str(item_data.unit_price)) * item_data.quantity
        total_amount += total_item_price
        
        order_item = PurchaseOrderItem(
            purchase_order_id=None,  # Will be set after order creation
            item_id=item_data.item_id,
            unit_name=item_data.unit_name,
            quantity=item_data.quantity,
            unit_price=item_data.unit_price,
            total_price=total_item_price
        )
        order_items.append(order_item)
    
    # Create purchase order
    db_order = PurchaseOrder(
        company_id=order.company_id,
        branch_id=order.branch_id,
        supplier_id=order.supplier_id,
        order_number=order_no,
        order_date=order.order_date,
        reference=order.reference,
        notes=order.notes,
        total_amount=total_amount,
        status=order.status or "PENDING",
        created_by=order.created_by
    )
    db.add(db_order)
    db.flush()
    
    # Link items to order
    for item in order_items:
        item.purchase_order_id = db_order.id
        db.add(item)

    db.flush()
    for item in order_items:
        SnapshotService.upsert_search_snapshot_last_order(
            db, order.company_id, order.branch_id, item.item_id, db_order.order_date
        )

    # Add each PO line to the order book as ORDERED so auto-ordering and manual add skip them
    for item in order_items:
        ob_entry = DailyOrderBook(
            company_id=order.company_id,
            branch_id=order.branch_id,
            item_id=item.item_id,
            supplier_id=db_order.supplier_id,
            quantity_needed=item.quantity,
            unit_name=item.unit_name,
            reason="DIRECT_PO",
            source_reference_type="purchase_order",
            source_reference_id=db_order.id,
            status="ORDERED",
            purchase_order_id=db_order.id,
            created_by=order.created_by,
        )
        db.add(ob_entry)

    db.commit()
    db.refresh(db_order)
    
    # Load relationships for response
    if db_order.supplier:
        db_order.supplier_name = db_order.supplier.name
    if db_order.branch:
        db_order.branch_name = db_order.branch.name
    # Load created_by user name
    created_by_user = db.query(User).filter(User.id == db_order.created_by).first()
    if created_by_user:
        db_order.created_by_name = created_by_user.full_name or created_by_user.email
    
    return db_order


@router.get("/order", response_model=List[PurchaseOrderResponse])
def list_purchase_orders(
    company_id: UUID = Query(..., description="Company ID"),
    branch_id: Optional[UUID] = Query(None, description="Branch ID"),
    supplier_id: Optional[UUID] = Query(None, description="Supplier ID"),
    date_from: Optional[date] = Query(None, description="Filter orders from this date"),
    date_to: Optional[date] = Query(None, description="Filter orders to this date"),
    status: Optional[str] = Query(None, description="Filter by status (PENDING, APPROVED, RECEIVED, CANCELLED)"),
    db: Session = Depends(get_tenant_db)
):
    """
    List purchase orders with filtering
    
    Filters:
    - branch_id: Filter by branch
    - supplier_id: Filter by supplier
    - date_from: Filter orders from this date
    - date_to: Filter orders to this date
    - status: Filter by status (PENDING, APPROVED, RECEIVED, CANCELLED)
    """
    query = db.query(PurchaseOrder).filter(PurchaseOrder.company_id == company_id)
    
    if branch_id:
        query = query.filter(PurchaseOrder.branch_id == branch_id)
    
    if supplier_id:
        query = query.filter(PurchaseOrder.supplier_id == supplier_id)
    
    if date_from:
        query = query.filter(PurchaseOrder.order_date >= date_from)
    
    if date_to:
        query = query.filter(PurchaseOrder.order_date <= date_to)
    
    if status:
        query = query.filter(PurchaseOrder.status == status)
    
    # Order by date descending (newest first)
    # Eagerly load items relationship to avoid lazy loading issues
    orders = query.options(
        selectinload(PurchaseOrder.items)
    ).order_by(PurchaseOrder.order_date.desc(), PurchaseOrder.created_at.desc()).all()
    
    # Load supplier, branch, and user names
    for order in orders:
        if order.supplier:
            order.supplier_name = order.supplier.name
        if order.branch:
            order.branch_name = order.branch.name
        # Load created_by user name
        created_by_user = db.query(User).filter(User.id == order.created_by).first()
        if created_by_user:
            order.created_by_name = created_by_user.full_name or created_by_user.email
    
    return orders


@router.get("/order/{order_id}", response_model=PurchaseOrderResponse)
def get_purchase_order(order_id: UUID, db: Session = Depends(get_tenant_db)):
    """Get purchase order by ID with full item details"""
    # Load order with items and item relationships
    order = db.query(PurchaseOrder).options(
        selectinload(PurchaseOrder.items).selectinload(PurchaseOrderItem.item)
    ).filter(PurchaseOrder.id == order_id).first()
    
    if not order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    # Load supplier, branch, and user names
    if order.supplier:
        order.supplier_name = order.supplier.name
    if order.branch:
        order.branch_name = order.branch.name
    # Load created_by user name
    created_by_user = db.query(User).filter(User.id == order.created_by).first()
    if created_by_user:
        order.created_by_name = created_by_user.full_name or created_by_user.email
    
    # Enhance items with full item details (similar to phAMACore response)
    for order_item in order.items:
        if order_item.item:
            # Add item details to order_item object (will be serialized by response model)
            order_item.item_code = order_item.item.sku or ''
            order_item.item_name = order_item.item.name or ''
            order_item.item_category = order_item.item.category or ''
            order_item.base_unit = order_item.item.base_unit or ''
            # Cost from inventory_ledger only (never from items table)
            from app.services.canonical_pricing import CanonicalPricingService
            order_item.default_cost = float(CanonicalPricingService.get_best_available_cost(db, order_item.item_id, order.branch_id, order.company_id)) if order.branch_id else 0.0
    
    return order


@router.put("/order/{order_id}", response_model=PurchaseOrderResponse)
def update_purchase_order(order_id: UUID, order_update: PurchaseOrderCreate, db: Session = Depends(get_tenant_db)):
    """Update purchase order (only if status is PENDING)"""
    db_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    if db_order.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot update purchase order with status {db_order.status}. Only PENDING orders can be updated."
        )
    
    # Update order fields
    db_order.supplier_id = order_update.supplier_id
    db_order.order_date = order_update.order_date
    db_order.reference = order_update.reference
    db_order.notes = order_update.notes
    db_order.status = order_update.status or "PENDING"
    
    # Delete existing items
    db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == order_id).delete()
    
    # Add new items
    total_amount = Decimal("0")
    for item_data in order_update.items:
        total_item_price = Decimal(str(item_data.unit_price)) * item_data.quantity
        total_amount += total_item_price
        
        order_item = PurchaseOrderItem(
            purchase_order_id=order_id,
            item_id=item_data.item_id,
            unit_name=item_data.unit_name,
            quantity=item_data.quantity,
            unit_price=item_data.unit_price,
            total_price=total_item_price
        )
        db.add(order_item)
    
    db_order.total_amount = total_amount
    db.commit()
    db.refresh(db_order)
    
    # Load supplier, branch, and user names
    if db_order.supplier:
        db_order.supplier_name = db_order.supplier.name
    if db_order.branch:
        db_order.branch_name = db_order.branch.name
    # Load created_by user name
    created_by_user = db.query(User).filter(User.id == db_order.created_by).first()
    if created_by_user:
        db_order.created_by_name = created_by_user.full_name or created_by_user.email
    
    return db_order


@router.delete("/order/{order_id}", status_code=status.HTTP_200_OK)
def delete_purchase_order(order_id: UUID, db: Session = Depends(get_tenant_db)):
    """Delete purchase order (only if status is PENDING)"""
    db_order = db.query(PurchaseOrder).filter(PurchaseOrder.id == order_id).first()
    if not db_order:
        raise HTTPException(status_code=404, detail="Purchase order not found")
    
    if db_order.status != "PENDING":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete purchase order with status {db_order.status}. Only PENDING orders can be deleted."
        )
    
    # Delete order items (cascade should handle this, but explicit is safer)
    db.query(PurchaseOrderItem).filter(PurchaseOrderItem.purchase_order_id == order_id).delete()
    
    # Delete order
    db.delete(db_order)
    db.commit()
    
    return {"message": "Purchase order deleted successfully", "deleted": True}

