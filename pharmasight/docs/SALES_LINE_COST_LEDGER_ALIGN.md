# Sales line cost snapshot vs ledger (COGS alignment)

## Rule

- **Posted `inventory_ledger` SALE rows** are the source of truth for cost of goods removed at batch (FEFO, multi-layer).
- **`sales_invoice_items.unit_cost_used`** is a **cached per–retail-unit cost** used for margin display and for gross-profit **fallback** when no ledger exists.

## Batching (new behaviour)

When an invoice is batched:

1. FEFO `allocate_stock_fefo` builds `allocations[]` (same quantities/costs as posted SALE lines).
2. `total_line_ledger_cost = sum(allocation.qty × allocation.unit_cost)` — matches `SUM(ledger.total_cost)` for that invoice line after post.
3. `unit_cost_used = total_line_ledger_cost ÷ quantity_in_base_units`  
   where base units = `convert_to_base_units(quantity, unit_name)` (same as batching).
4. If the **draft** `unit_cost_used` implied COGS differed from `total_line_ledger_cost` by more than **1% of `line_total_exclusive`**, a **warning** is logged (pre-reconcile diagnostic).

**Ledger rows are unchanged** — only the snapshot column on the line is updated.

## Gross profit / dashboard / financial reports

- **`GET /api/sales/branch/{id}/gross-profit`** uses **ledger COGS** (sum of `SALE` `total_cost`) when any exist for the period; invoice-line math is **fallback** only.
- After batch reconciliation, **fallback** (`qty × mult × unit_cost_used`) should match ledger totals for normal lines.

## Invoice margin in the UI

- For **BATCHED/PAID** invoices, **`unit_cost_base` in the response** uses **`unit_cost_used`** on the line (ledger-reconciled), not a fresh `get_item_cost` lookup, so margin % matches the stored sale cost.

## Backfill existing data

One-off (tenant DB):

```bash
cd pharmasight/backend
python scripts/reconcile_sales_line_unit_cost_from_ledger.py --dry-run
python scripts/reconcile_sales_line_unit_cost_from_ledger.py
```

Optional: `--company-id <uuid>` or `--invoice-id <uuid>`.

## Analysis script

```bash
python scripts/analyze_margin_distribution.py --branch-id ... --company-id ...
```

Compares snapshot COGS vs ledger per line for investigation.
