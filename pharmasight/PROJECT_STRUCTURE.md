# PharmaSight Project Structure

## 📁 Directory Layout

```
pharmasight/
├── backend/                    # FastAPI backend application
│   ├── app/
│   │   ├── __init__.py        # Package initialization
│   │   ├── main.py            # FastAPI app entry point
│   │   ├── config.py          # Configuration & settings
│   │   ├── database.py        # Database connection & session
│   │   ├── models/            # SQLAlchemy database models
│   │   │   └── __init__.py
│   │   ├── schemas/           # Pydantic request/response schemas
│   │   │   └── __init__.py
│   │   ├── api/               # API route handlers
│   │   │   └── __init__.py
│   │   └── services/          # Business logic services
│   │       └── __init__.py
│   └── requirements.txt       # Python dependencies
│
├── database/
│   └── schema.sql             # Complete database schema
│
├── .env.example               # Environment variables template
├── .gitignore                # Git ignore rules
├── README.md                 # Project overview
├── SETUP.md                  # Setup instructions
└── PROJECT_STRUCTURE.md      # This file
```

## 🗄️ Database Schema Overview

### Core Tables

**Multi-Tenancy & Auth**
- `companies` - Company profiles
- `branches` - Branch locations
- `user_roles` - Role definitions
- `user_branch_roles` - User-role assignments per branch

**Items & Pricing**
- `items` - SKU master data
- `item_units` - Breaking bulk configuration
- `item_pricing` - Item-specific pricing rules
- `company_pricing_defaults` - Default markup rules

**Inventory (Ledger-First)**
- `inventory_ledger` - **Single source of truth** (append-only)
  - All stock movements
  - Base unit storage
  - Batch & expiry tracking
  - Cost per transaction

**Purchases**
- `suppliers` - Supplier master
- `grns` - Goods Received Notes
- `grn_items` - GRN line items
- `purchase_invoices` - VAT input documents
- `purchase_invoice_items` - Purchase invoice lines

**Sales (KRA Compliant)**
- `sales_invoices` - KRA sales documents
- `sales_invoice_items` - Sales line items
- `payments` - Payment settlements
- `credit_notes` - Return documents (KRA)
- `credit_note_items` - Credit note lines

**Expenses**
- `expense_categories` - Expense categories
- `expenses` - Expense records

**Settings**
- `company_settings` - Company configuration
- `document_sequences` - Sequential numbering

### Key Design Principles

1. **Inventory Ledger is Append-Only**
   - Never update or delete
   - All stock = SUM(quantity_delta)
   - Base units only

2. **Breaking Bulk at Item Setup**
   - Defined in `item_units`
   - Applied automatically
   - No manual conversion

3. **KRA Compliance**
   - Sequential invoices
   - Immutable financial records
   - VAT tracking
   - Credit notes reference originals

4. **FEFO Logic**
   - Batch & expiry in ledger
   - Allocation at sale time
   - Cost per batch preserved

## 🔧 Backend Architecture

### FastAPI Application
- **Entry Point**: `app/main.py`
- **Config**: Environment-based settings
- **Database**: SQLAlchemy with connection pooling
- **Auth**: Supabase Auth (to be integrated)

### Planned API Structure

```
/api
  /auth          # Authentication
  /companies     # Company management
  /branches      # Branch management
  /items         # Item master data
  /inventory     # Stock queries & adjustments
  /sales         # Sales invoices & POS
  /purchases     # GRN & purchase invoices
  /expenses      # Expense management
  /reports       # Analytics & reports
  /settings      # Configuration
```

## 🚀 Next Development Steps

1. **Models** (SQLAlchemy)
   - Company & Branch models
   - Item & Unit models
   - Inventory Ledger model
   - Sales & Purchase models

2. **Schemas** (Pydantic)
   - Request validation
   - Response serialization
   - Business rule validation

3. **Services** (Business Logic)
   - Inventory calculation
   - FEFO allocation
   - Pricing engine
   - Document numbering

4. **API Routes**
   - CRUD operations
   - Complex queries
   - Transaction posting

5. **Authentication**
   - Supabase Auth integration
   - Role-based access control
   - JWT token handling

## 📊 Key Features Implemented

✅ Database schema (complete)
✅ Project structure
✅ FastAPI foundation
✅ Configuration management
✅ Database connection pooling
✅ Environment setup

## 🔄 Features To Build

- [ ] SQLAlchemy models
- [ ] Pydantic schemas
- [ ] Inventory calculation service
- [ ] FEFO allocation algorithm
- [ ] Pricing engine
- [ ] Sales invoice posting
- [ ] GRN posting
- [ ] Credit note processing
- [ ] Document numbering
- [ ] Authentication & authorization
- [ ] Reporting queries
- [ ] Excel import/export

## 🎯 MVP Scope

**Must Have:**
- Item management
- Inventory ledger
- Sales invoices (POS)
- Purchase/GRN
- Stock queries
- Basic pricing

**Nice to Have:**
- Advanced analytics
- Multi-branch transfers
- Supplier management
- Expense tracking
- Credit sales

**Future:**
- Patient records
- Prescription management
- Insurance integration
- Mobile app

