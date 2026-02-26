"""
Database models for PharmaSight
"""
from app.database import Base

# Import all models
from .company import Company, Branch, BranchSetting
from .user import User, UserRole, UserBranchRole
from .item import Item, ItemPricing, CompanyPricingDefault, CompanyMarginTier
from .inventory import InventoryLedger, ItemMovement
from .snapshot import InventoryBalance, ItemBranchPurchaseSnapshot, ItemBranchSearchSnapshot
from .supplier import Supplier
from .purchase import GRN, GRNItem, SupplierInvoice, SupplierInvoiceItem, PurchaseOrder, PurchaseOrderItem
# Backward compatibility aliases
PurchaseInvoice = SupplierInvoice
PurchaseInvoiceItem = SupplierInvoiceItem
from .sale import SalesInvoice, SalesInvoiceItem, Payment, CreditNote, CreditNoteItem, Quotation, QuotationItem, InvoicePayment
from .settings import DocumentSequence, CompanySetting
from .stock_take import StockTakeSession, StockTakeCount, StockTakeCounterLock, StockTakeAdjustment
from .order_book import DailyOrderBook, OrderBookHistory
from .import_job import ImportJob
from .permission import Permission, RolePermission
from .branch_inventory import (
    BranchOrder,
    BranchOrderLine,
    BranchTransfer,
    BranchTransferLine,
    BranchReceipt,
    BranchReceiptLine,
)

__all__ = [
    "Base",
    "Company",
    "Branch",
    "BranchSetting",
    "User",
    "UserRole",
    "UserBranchRole",
    "Item",
    "ItemPricing",
    "CompanyPricingDefault",
    "CompanyMarginTier",
    "InventoryLedger",
    "ItemMovement",
    "InventoryBalance",
    "ItemBranchPurchaseSnapshot",
    "ItemBranchSearchSnapshot",
    "Supplier",
    "GRN",
    "GRNItem",
    "SupplierInvoice",
    "SupplierInvoiceItem",
    "PurchaseInvoice",  # Backward compatibility alias
    "PurchaseInvoiceItem",  # Backward compatibility alias
    "PurchaseOrder",
    "PurchaseOrderItem",
    "SalesInvoice",
    "SalesInvoiceItem",
    "Payment",
    "CreditNote",
    "CreditNoteItem",
    "Quotation",
    "QuotationItem",
    "InvoicePayment",
    "DocumentSequence",
    "CompanySetting",
    "StockTakeSession",
    "StockTakeCount",
    "StockTakeCounterLock",
    "StockTakeAdjustment",
    "DailyOrderBook",
    "OrderBookHistory",
    "ImportJob",
    "Permission",
    "RolePermission",
    "BranchOrder",
    "BranchOrderLine",
    "BranchTransfer",
    "BranchTransferLine",
    "BranchReceipt",
    "BranchReceiptLine",
]
