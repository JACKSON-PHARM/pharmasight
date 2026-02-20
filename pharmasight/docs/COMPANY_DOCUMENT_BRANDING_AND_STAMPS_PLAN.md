# Company Document Branding, Stamps & Signatures – Implementation Plan

**Status:** Implemented (Supabase storage, document_branding, stamp/signature upload, PO approval workflow, frontend Settings > Document Branding and User edit signature).

**Context:** Kenyan pharmacies (tenants) need company names, branch names, logos, addresses, and optionally **digital stamps** and **signatures** on transactional documents. Stamps/signatures are required for compliance (e.g. controlled substances, official purchase orders). These are **company settings**, editable by admins, and can change over time.

---

## 1. Current State Summary

| Area | Current state |
|------|----------------|
| **Company** | Has `name`, `logo_url`, `address`, `phone`, `email`, `registration_number`, `pin`, `currency`, `timezone`. Logo upload exists (`POST /companies/{id}/logo`). |
| **Branch** | Has `name`, `code`, `address`, `phone`. Used in invoice numbering and document context. |
| **Company settings** | Key-value table `company_settings` (e.g. `print_config` for receipt/print layout). No permission check on GET/PUT in code seen. |
| **Documents** | **Purchase order** print (frontend HTML in `purchases.js`) shows order number, date, supplier, branch name, reference, status, created by — but **no company name, logo, or address** in header. **Quotations** and **sales invoices** use print_config (company name, address, etc.) for receipts. |
| **Controlled items** | `items.is_controlled` exists. Used in stock take and item management. No “controlled order” flag on PO yet. |
| **Permissions** | `settings.view`, `settings.edit`, `settings.create` (create = branches). HQ-only permissions in `permission_config.py`. |

---

## 2. Goals

1. **Branding on all transactional documents**  
   Company name, branch name, logo, and address (company and/or branch) appear on:
   - Purchase orders  
   - Quotations  
   - Invoices (sales)  
   - Any other printed/exported documents  

2. **Digital stamp and signature (Kenyan pharmacy compliance)**  
   - **Digital stamp:** e.g. pharmacy seal / rubber stamp image.  
   - **Digital signature:** image of authorized person’s signature.  
   Used on:
   - **Controlled-item orders** (e.g. POs containing at least one controlled item).  
   - **Official purchase orders** (all POs, or a future “official” flag).  

3. **Admin-only, company settings**  
   - Only users with appropriate admin permission (e.g. `settings.edit`) can change company profile and document branding (including stamps/signatures).  
   - All stored per company (and where relevant, branch is chosen by document context).  
   - Settings are **editable over time** (no one-time setup only).  

4. **Kenyan context**  
   - KES, Africa/Nairobi already in place.  
   - Stamps/signatures stored as images (no PKI/certificates in v1).  
   - Design should align with PPB-style expectations (authorized signature + stamp on controlled/official orders).  

---

## 3. Data Model & Storage

### 3.1 Use existing tables where possible

- **Company name, address, logo:** Already on `companies` and updated via existing company APIs.  
- **Branch name, address:** Already on `branches`.  
- **Document branding options** (e.g. “show logo on PO”, “use branch address on PO”): Store in `company_settings` as a single JSON key to avoid many columns and migrations.

### 3.2 New: stamp and signature assets

**Option A – New columns on `companies`**  
- `stamp_image_url`, `signature_image_url` (TEXT, nullable).  
- Simple, but every new asset type needs a migration.  

**Option B – Company settings + upload endpoints (recommended)**  
- Store URLs in `company_settings`: e.g. key `document_branding` value JSON:
  - `stamp_url`, `signature_url`  
  - `show_stamp_on_controlled_orders`, `show_stamp_on_official_po`  
  - `show_signature_on_controlled_orders`, `show_signature_on_official_po`  
  - Optional: `use_branch_address_on_po`, `use_company_address_on_invoice`, etc.  
- Add two new upload endpoints (similar to logo):
  - `POST /companies/{company_id}/stamp`  
  - `POST /companies/{company_id}/signature`  
- Store files under e.g. `uploads/stamps/` and `uploads/signatures/` (or `uploads/company_assets/stamp|signature`).  
- **Benefit:** No schema change; easy to add more options (e.g. “show stamp on quotations”) later.  

**Recommendation:** Option B.

### 3.3 “Official” purchase order

- For “official” POs you can either:
  - **Option 1:** Treat every PO as official (simplest).  
  - **Option 2:** Add `is_official` (boolean) to purchase orders later; when true, show stamp/signature.  
- For **controlled-item orders:** At print/preview time, derive from order line items: if any item has `is_controlled === true`, treat as controlled order and show stamp/signature per company settings. No new column required.

---

## 4. API Design

### 4.1 Existing (keep using)

- `GET/PUT /companies/{id}` – company profile (name, address, logo_url, etc.).  
- `GET/PUT /companies/{id}/settings` – get/update by key (e.g. `document_branding`, `print_config`).  
- `POST /companies/{id}/logo` – logo upload.  

### 4.2 New

- `POST /companies/{company_id}/stamp`  
  - Body: multipart file (image).  
  - Validates type (e.g. PNG, JPG) and size (e.g. max 2MB).  
  - Saves file; sets `document_branding.stamp_url` in company_settings (create key if missing).  
  - Returns updated `document_branding` or 204.  

- `POST /companies/{company_id}/signature`  
  - Same as stamp, key `signature_url` in `document_branding`.  

- Optional: `DELETE /companies/{company_id}/stamp` and `DELETE /companies/{company_id}/signature` to clear and remove file.  

All of the above must require **admin** permission (e.g. `settings.edit` or a dedicated `settings.manage_document_branding`). Enforce at route level (dependency that checks permission for current user + company).

### 4.3 Document branding payload

Example `document_branding` in company_settings:

```json
{
  "stamp_url": "/uploads/stamps/xxx.png",
  "signature_url": "/uploads/signatures/yyy.png",
  "show_stamp_on_controlled_orders": true,
  "show_stamp_on_official_po": true,
  "show_signature_on_controlled_orders": true,
  "show_signature_on_official_po": true,
  "show_logo_on_po": true,
  "show_company_address_on_po": true,
  "show_branch_address_on_po": true
}
```

Frontend and print logic read this (from GET company settings or from a single “document branding” API that returns company + branch + this JSON).

---

## 5. Permissions

- **View company profile / document branding:** `settings.view` (or same as today if unconstrained).  
- **Edit company profile, upload logo/stamp/signature, change document branding:** `settings.edit`.  
- Optionally restrict to **HQ branch** for these edits (similar to `settings.create` for branches), so only HQ admins can change company-wide branding.  

**Backend:** Add a dependency (e.g. `require_settings_edit`) that loads current user, checks `settings.edit`, and optionally HQ. Use it on:
- `PUT /companies/{id}`  
- `PUT /companies/{id}/settings`  
- `POST /companies/{id}/logo`  
- `POST /companies/{id}/stamp`  
- `POST /companies/{id}/signature`  

**Frontend:** Show “Company profile” and “Document branding” (or “Documents & stamps”) only to users with `settings.edit` (or equivalent).

---

## 6. Frontend – Company Settings UI

### 6.1 Where to put it

- **Settings > Company** (existing “Company profile”): Keep company name, registration, PIN, phone, email, address, logo upload, currency, timezone.  
- Add a new sub-page: **Settings > Document branding** (or “Documents & stamps”) with:
  - **Header / document content**
    - Checkboxes: Show company name / branch name / logo / company address / branch address on:
      - Purchase orders  
      - Quotations  
      - Invoices  
    (Or one set of toggles that apply to “all documents” with overrides later if needed.)  
  - **Digital stamp**
    - Upload area + preview.  
    - Checkboxes: “Use on controlled-item orders”, “Use on official purchase orders”.  
  - **Digital signature**
    - Upload area + preview.  
    - Same two checkboxes.  
  - Save writes to `document_branding` via `PUT /companies/{id}/settings` and optionally calls stamp/signature upload if user selected new files.  

If you prefer fewer menu items, “Document branding” can be a section inside **Settings > Company** (same page, second card).

### 6.2 Loading data for print/preview

- When opening PO print (or quotation/invoice print), frontend needs:
  - Company (name, logo_url, address).  
  - Current branch (name, address).  
  - `document_branding` (stamp_url, signature_url, flags).  
  - Order lines with `is_controlled` for each item (for “controlled order” detection).  

Either:
- Add a single endpoint e.g. `GET /api/companies/{id}/document-context?branch_id=...` that returns company + branch + document_branding, or  
- Use existing `GET company`, `GET branch`, `GET company settings (key=document_branding)` and combine in frontend.  

---

## 7. Document Print/Preview Changes

### 7.1 Purchase order (purchases.js)

- **Header:** Add company name, logo (if `document_branding.show_logo_on_po` or default true), company and/or branch address (based on settings).  
- **Footer (or signature block):** If order has any controlled item and `show_stamp_on_controlled_orders` / `show_signature_on_controlled_orders`, show stamp image and signature image. Same if “official PO” is enabled and `show_stamp_on_official_po` / `show_signature_on_official_po`.  
- Ensure backend returns `items[].is_controlled` for the order so frontend can decide.

### 7.2 Quotations

- Use same branding (company name, logo, address) and, if you later define “controlled quotation”, same stamp/signature rules.  
- Reuse the same “document context” (company + branch + document_branding).

### 7.3 Sales invoices / receipts

- Already use print_config (company name, address, etc.). Ensure they also use company logo from company profile when printing.  
- Stamps/signatures on invoices can be added later with the same pattern (e.g. show on controlled-item sales if needed).

---

## 8. Backend Checklist

- [ ] Add `document_branding` default/merge when returning company settings.  
- [ ] Implement `POST /companies/{id}/stamp` and `POST /companies/{id}/signature` (file upload, save under uploads/, update `document_branding` in company_settings).  
- [ ] Optional: `DELETE` for stamp/signature (clear URL and delete file).  
- [ ] Enforce `settings.edit` (and optionally HQ) on company update, settings update, logo/stamp/signature upload.  
- [ ] Ensure purchase order detail API returns `is_controlled` per line item so frontend can detect controlled orders.

---

## 9. Frontend Checklist

- [ ] New Settings sub-page (or section) “Document branding” with toggles and uploads for stamp/signature.  
- [ ] Save/load `document_branding` via company settings API.  
- [ ] PO print: fetch company, branch, document_branding; render header (name, logo, address) and conditional stamp/signature block.  
- [ ] Quotation print: same branding.  
- [ ] Hide or disable document branding section for users without `settings.edit`.  
- [ ] (Optional) Document context endpoint to reduce round-trips.

---

## 10. Kenyan Pharmacy Notes

- **PPB:** Pharmacy and Poisons Board expectations (authorized person signature, pharmacy stamp on controlled orders) are met by allowing the tenant to upload their own stamp and signature images and to choose where they appear (controlled orders, official POs).  
- **No PKI in v1:** Stored images are sufficient for many audits; digital certificates can be a later enhancement.  
- **Addresses:** Company and branch addresses on documents support compliance and clarity (e.g. for suppliers and inspectors).  

---

## 11. Implementation Order (Suggested)

1. **Backend: document_branding + permissions**  
   - Implement `document_branding` in company_settings (GET/PUT).  
   - Add permission check for company update and settings update.  

2. **Backend: stamp & signature upload**  
   - `POST /companies/{id}/stamp`, `POST /companies/{id}/signature`; update `document_branding`.  

3. **Frontend: Document branding UI**  
   - New section under Settings; load/save `document_branding`; upload stamp/signature.  

4. **Frontend: PO print**  
   - Load company, branch, document_branding; add header (name, logo, address); add stamp/signature when controlled or official.  

5. **Quotations & invoices**  
   - Apply same branding; add stamp/signature if/when business rules are defined.  

6. **Optional:** `is_official` on POs and “official” filter in UI; then use it in stamp/signature conditions.  

This plan keeps everything under company settings, admin-only, and changeable over time, and aligns with Kenyan pharmacy use cases (controlled items, official POs, company/branch identity on documents).
