"""
Database models for PharmaSight
"""
from app.database import Base

# Import all models
from .company import Company, Branch, BranchSetting
from .company_kra_profile import CompanyKraProfile
from .company_module import CompanyModule
from .user import User, UserRole, UserBranchRole
from .item import Item, ItemPricing, CompanyPricingDefault, CompanyMarginTier, PricingSettings, ItemBranchKraSync
from .inventory import InventoryLedger, ItemMovement
from .snapshot import InventoryBalance, ItemBranchPurchaseSnapshot, ItemBranchSearchSnapshot, ItemBranchSnapshot
from .supplier import Supplier
from .expense import ExpenseCategory, Expense
from .purchase import GRN, GRNItem, SupplierInvoice, SupplierInvoiceItem, PurchaseOrder, PurchaseOrderItem
from .supplier_financial import (
    SupplierPayment,
    SupplierPaymentAllocation,
    SupplierReturn,
    SupplierReturnLine,
    SupplierLedgerEntry,
)
from .insurance_financial import (
    InsuranceProvider,
    InsuranceClaim,
    InsuranceSettlement,
    InsuranceSettlementAllocation,
    InsuranceLedgerEntry,
)
# Cashbook (money movement tracking)
from .cashbook import CashbookEntry
# Backward compatibility aliases
PurchaseInvoice = SupplierInvoice
PurchaseInvoiceItem = SupplierInvoiceItem
from .sale import SalesInvoice, SalesInvoiceItem, Payment, CreditNote, CreditNoteItem, Quotation, QuotationItem, InvoicePayment
from .settings import DocumentSequence, CompanySetting, PublicSiteSettings
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
from .clinic import (
    Patient,
    Encounter,
    EncounterNote,
    ClinicOrder,
    ClinicOrderItem,
    EncounterTriage,
    ClinicalService,
    ClinicalServiceComponent,
    ClinicalServiceAccumulator,
    EncounterServiceExecution,
    EncounterServiceExecutionLine,
    DepartmentStore,
    DepartmentStoreStock,
    DepartmentStoreMovement,
)
from .department_supply import (
    DepartmentSupplyOrder,
    DepartmentSupplyOrderLine,
    DepartmentSupplyTransfer,
    DepartmentSupplyTransferLine,
    DepartmentSupplyReceipt,
    DepartmentSupplyReceiptLine,
)
from .etims_sync_cursor import EtimsSyncCursor
from .kra_audit_event import KraAuditEvent
from .kra_event_outbox import KraEventOutbox
from .commercial_transaction import CommercialTransaction, CommercialTransactionTransition

__all__ = [
    "Base",
    "Company",
    "Branch",
    "BranchSetting",
    "CompanyKraProfile",
    "CompanyModule",
    "User",
    "UserRole",
    "UserBranchRole",
    "Item",
    "ItemPricing",
    "CompanyPricingDefault",
    "CompanyMarginTier",
    "PricingSettings",
    "ItemBranchKraSync",
    "InventoryLedger",
    "ItemMovement",
    "InventoryBalance",
    "ItemBranchPurchaseSnapshot",
    "ItemBranchSearchSnapshot",
    "ItemBranchSnapshot",
    "Supplier",
    "ExpenseCategory",
    "Expense",
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
    "PublicSiteSettings",
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
    "SupplierPayment",
    "SupplierPaymentAllocation",
    "SupplierReturn",
    "SupplierReturnLine",
    "SupplierLedgerEntry",
    "InsuranceProvider",
    "InsuranceClaim",
    "InsuranceSettlement",
    "InsuranceSettlementAllocation",
    "InsuranceLedgerEntry",
    "CashbookEntry",
    "Patient",
    "Encounter",
    "EncounterNote",
    "ClinicOrder",
    "ClinicOrderItem",
    "EncounterTriage",
    "ClinicalService",
    "ClinicalServiceComponent",
    "ClinicalServiceAccumulator",
    "EncounterServiceExecution",
    "EncounterServiceExecutionLine",
    "DepartmentStore",
    "DepartmentStoreStock",
    "DepartmentStoreMovement",
    "DepartmentSupplyOrder",
    "DepartmentSupplyOrderLine",
    "DepartmentSupplyTransfer",
    "DepartmentSupplyTransferLine",
    "DepartmentSupplyReceipt",
    "DepartmentSupplyReceiptLine",
    "EtimsSyncCursor",
    "KraAuditEvent",
    "KraEventOutbox",
    "CommercialTransaction",
    "CommercialTransactionTransition",
]
