# Order Book validation scripts

Use these scripts to confirm why items do or do not appear in the order book (trigger rules).

## 1. Replace UUIDs

In both SQL files, edit the `params` CTE at the top:

- **company_id**: your company UUID  
- **branch_id**: branch UUID (e.g. Main Branch HQ). Must match the branch where you batch sales and view the order book.

## 2. Scripts

| File | Purpose |
|------|--------|
| `order_book_trigger_validation.sql` | All items: current stock, 30-day sales, and the three trigger rules. Use to see who would trigger and why. |
| `order_book_pack_size_audit.sql` | Only items with `pack_size` NULL or 1. Use to find items that may need correct pack size (e.g. 30 for 30’s). |

## 3. Interpreting your CSV (from the corrected query)

If you used **inventory_balances** for current stock but had **monthly_sales as placeholder** (no rows), then in your export:

- **monthly_sales_retail_units** = 0 for every row  
- **below_half_monthly** = always **false** (rule needs monthly_sales > 0 and stock < monthly_sales/2)  
- **would_trigger_order_book** is therefore only true when either:
  - **below_one_wholesale** is true (current_stock_retail_units **< pack_size**), or  
  - **stock_fell_to_zero** is true (current_stock_retail_units **≤ 0**).

So from that CSV:

- For **PAUSE-MF**: if `pack_size` is 1 (or NULL treated as 1), then `below_one_wholesale` is (8 < 1) = **false**. With monthly_sales = 0, **would_trigger_order_book** = false → **item would not be auto-added**. Fix: set `pack_size = 30` for that item so that (8 < 30) = true.
- Any item with **pack_size = 1** and stock ≥ 1 will never satisfy Rule 1; they only trigger on Rule 2 (needs real 30-day sales) or Rule 3 (stock 0).

## 4. After fixing monthly_sales (use the new validation script)

Run `order_book_trigger_validation.sql` with real 30-day sales from `inventory_ledger`. Then:

- **below_one_wholesale** = (current_stock < pack_size)  
- **below_half_monthly** = (monthly_sales > 0 and current_stock < monthly_sales/2)  
- **stock_fell_to_zero** = (current_stock ≤ 0)  
- **would_trigger_order_book** = true if any of the three is true (and item has sales history in the app).

For **PAUSE-MF** with 8 tablets and pack_size 30: below_one_wholesale = true → should appear in the order book when a sale is batched, provided pack_size is 30 in the DB.
