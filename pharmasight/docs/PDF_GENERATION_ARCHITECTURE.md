# PDF Generation Architecture

## Overview

PDF generation uses a **single common generator** and **document-specific wrappers** so that:

- One template flow drives all transaction documents.
- Each document type gets only what it needs (no mixing of concerns).
- New document types or sections can be added in one place.

## Layers

### 1. `document_pdf_commons.py`

**Role:** Low-level building blocks (shared across all documents).

- **Header:** Company name, address, phone, PIN, branch, logo (bordered).
- **Metadata + client table:** Document metadata rows + “Customer”/“Supplier” block (bordered).
- **Payment details table:** Till number and Paybill (sales invoice only).
- **Approval block:** Approver name, designation, PPB No., date; stamp (faded) and signature (solid) at bottom-right.
- **Styles:** Shared paragraph/heading styles.

Use these to assemble flowables; do not put document-specific logic here.

### 2. `document_pdf_generator.py`

**Role:** Single entry point that builds the full PDF from a `doc_type` and a `payload`.

**Flow (common template):**

1. Header (all documents).
2. Document title + number (e.g. “SALES INVOICE”, “CS041”).
3. Metadata + client table (all documents).
4. **Payment details** only if `doc_type == "sales_invoice"` and payload has `till_number` or `paybill`.
5. Items table (all documents).
6. Totals (format depends on doc type: Net/VAT/Total vs Total vs Total cost).
7. **Approval block** only if `doc_type == "purchase_order"`.
8. Notes (optional).

**Document types:**

| doc_type           | Payment (till/paybill) | Approval block |
|--------------------|------------------------|----------------|
| sales_invoice      | Yes (optional)         | No             |
| quotation          | No                     | No             |
| purchase_order     | No                     | Yes            |
| supplier_invoice   | No                     | No             |
| grn                | No                     | No             |

**Payload:** One flat dict. The generator reads only the keys it needs for the chosen `doc_type`. Possible keys include: company/branch fields, `document_title`, `document_number`, `metadata_rows`, `client_label`, `client_name`, `extra_client_rows`, `items`, totals, `notes`, and for PO: `approver_name`, `approved_at_str`, `stamp_bytes`, `signature_bytes`, etc.

### 3. Document-specific wrappers (in `document_pdf_generator.py`)

The same module defines thin wrappers that build the payload and call `build_document_pdf(doc_type, payload)`. The API imports these from `document_pdf_generator` only.

| Function                     | doc_type         |
|-----------------------------|------------------|
| `build_quotation_pdf(...)`  | quotation        |
| `build_po_pdf(...)`         | purchase_order   |
| `build_sales_invoice_pdf(...)` | sales_invoice  |
| `build_grn_pdf(...)`        | grn              |
| `build_supplier_invoice_pdf(...)` | supplier_invoice |

**API layer:** Routes import from `app.services.document_pdf_generator` (e.g. `build_sales_invoice_pdf`, `build_po_pdf`). When you add till/paybill (e.g. on Company or Branch), pass them into `build_sales_invoice_pdf` so the sales invoice PDF shows the payment block.

## What goes where

- **Sales invoice:** Payment details (till number, paybill) — only in sales invoice payload and only rendered when `doc_type == "sales_invoice"`.
- **Purchase order:** Approvals (stamp, signature, approver details) — only in PO payload and only when `doc_type == "purchase_order"`.
- **Quotation:** No payment, no approval; header + metadata + customer + items + totals + notes.
- **Supplier invoice:** Document skeleton only: header + metadata + supplier + items + totals + notes.

## Adding a new document type

1. Add a `DOC_TYPE_*` constant and branch in `document_pdf_generator.build_document_pdf` for any special sections or totals.
2. Add a thin wrapper (e.g. `build_xyz_pdf(...)`) that builds the payload and calls `build_document_pdf("xyz", payload)`.
3. Call the wrapper from the API as usual.

## Adding a new optional section

- If it’s a new block (e.g. terms and conditions), add a builder in `document_pdf_commons` and call it from `document_pdf_generator` for the doc types that need it.
- Keep document-specific flags in the payload and branch in the generator so only the right documents get the new section.
