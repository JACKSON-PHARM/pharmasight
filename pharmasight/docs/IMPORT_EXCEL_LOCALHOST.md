# Import Excel on Localhost (Default DB)

Use this to load your Excel sheet into the **default database** so the **items** and **inventory_ledger** (opening balance) tables are populated.

## 1. Prerequisites

- **Default DB** is set up and migrations have run (companies, branches, users, `items`, `inventory_ledger`, `import_jobs` exist).
- Backend running (e.g. `http://localhost:8000`).
- Frontend running (e.g. `http://localhost:3000`).
- Log in **without** a tenant (no tenant invite link). That way all requests use the default DB.

## 2. Excel columns that populate data

| What gets populated | Required? | Map your Excel column to this system field |
|---------------------|-----------|---------------------------------------------|
| **Items table**     |           |                                             |
| Item name           | **Yes**   | **Item Name**                               |
| Description         | No        | Description / Generic Name                  |
| Item code (SKU)     | No        | Item Code (SKU)                             |
| Barcode             | No        | Barcode                                     |
| Category            | No        | Category                                    |
| Wholesale unit      | No        | Wholesale Unit (e.g. box, bottle)           |
| Retail unit         | No        | Retail Unit (e.g. tablet, piece)            |
| Pack size           | No        | Pack Size (retail per wholesale)            |
| **Opening balance (inventory_ledger)** | | |
| Units in stock      | No        | **Current Stock Quantity**                  |
| Unit cost (per wholesale unit) | No | **Wholesale Unit Price** (or Purchase Price per Supplier Unit) |
| Supplier name       | No        | **Supplier**                                |

- **Items**: every row with an **Item Name** becomes (or updates) an item.
- **Opening balance**: for each item, if you map **Current Stock Quantity** and optionally **Wholesale Unit Price** (or **Purchase Price per Supplier Unit**) and **Supplier**, the import creates an `OPENING_BALANCE` row in `inventory_ledger` with:
  - `quantity_delta` = current stock quantity (in base/wholesale units)
  - `unit_cost` = cost per base (wholesale) unit
  - `total_cost` = quantity × unit cost  
  Suppliers are created/linked from the **Supplier** column.

## 3. Steps on localhost

1. Open the app at `http://localhost:3000` (or your frontend URL). Log in (no tenant).
2. Go to **Items** (or **Inventory** → Items).
3. Click **Import** (or **Import Items**).
4. Choose your Excel file.
5. In **Map your columns**:
   - Map your **item name** column → **Item Name (required)**.
   - For opening balance, map:
     - Your **stock quantity** column → **Current Stock Quantity**
     - Your **cost/price** column → **Wholesale Unit Price** (or **Purchase Price per Supplier Unit** if you have cost per supplier unit)
     - Your **supplier/vendor** column → **Supplier**
   - Map any other columns you have (Description, Item Code, Category, units, Pack Size, etc.) to the matching system fields.
6. Click **Import**. The job runs in the background (default DB).
7. Wait until the modal shows **Import completed** and the progress bar reaches 100%.
8. Check:
   - **items** table: one row per imported item.
   - **inventory_ledger** table: rows with `transaction_type = 'OPENING_BALANCE'` and `reference_type = 'OPENING_BALANCE'` (quantity_delta, unit_cost, total_cost, item_id, branch_id).

## 4. If items or ledger stay empty

- **Backend log**: You should see `Background task STARTED for job ... (database=default)` and then batch progress. If the thread never starts or the process exits, the default DB might not be getting the writes.
- **Same DB**: Confirm the DB you’re querying (e.g. in pgAdmin or Supabase) is the same as `DATABASE_URL` used by the backend.
- **Mode**: On a fresh DB with no sales/purchases, the import runs in **AUTHORITATIVE** mode, which creates items and opening balances. If you already have live transactions, it runs in **NON_DESTRUCTIVE** mode (no new opening balances).
- **Column mapping**: Ensure **Item Name** is mapped. For opening balance, **Current Stock Quantity** and at least one cost field (**Wholesale Unit Price** or **Purchase Price per Supplier Unit**) should be mapped; **Supplier** is optional but recommended.
