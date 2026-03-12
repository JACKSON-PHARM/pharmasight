# Order Book Lifecycle – Design Confirmation

## Core design principle

The PharmaSight Order Book is a **daily operational notebook**, not merely a reorder list.

- Each entry = **shortage or demand event on a specific date** (`entry_date`).
- **daily_order_book** = active operational entries for that day (what still needs attention).
- **order_book_history** = resolved shortage events (full timeline for day/week/month review).

---

## Operational use cases (supported)

| Use case | How the design supports it |
|----------|----------------------------|
| **End-of-day review** | Owner filters Order Book by **today**. Sees PENDING (need to order), ORDERED (already ordered), and a clean list—resolved entries have moved to history. |
| **Weekly ordering** | Owner filters by **this week** (entry_date range). Sees shortages from the week; history holds received/closed events for the same range. |
| **Monthly review** | Owner filters Order Book and/or history by **month**. History provides recurring shortages and demand patterns with full timestamps. |

---

## Lifecycle (no change to triggers or duplicate rules)

| Step | Event | daily_order_book | order_book_history |
|------|--------|-------------------|---------------------|
| 1 | Shortage occurs (sale trigger, low stock, or manual entry) | Insert row: `status = PENDING`, `entry_date = date of event`. | — |
| 2 | Purchase order or branch order created from entry | Update row: `status = ORDERED`, set `ordered_at`, `purchase_order_id` or `branch_order_id`. | Optional: insert ORDERED row (current behavior) for audit. |
| 3 | Stock received (GRN or branch receipt) | Update row: `status = RECEIVED`, set `received_at`. | — |
| 4 | Shortage resolved (receipt recorded) | **Delete** row from daily_order_book. | Insert row: `status = CLOSED`, copy `created_at`, `entry_date`, `ordered_at`, `received_at`, set `archived_at = now`. |

**Result:** The **daily order book stays clean**. Only PENDING and ORDERED entries remain in `daily_order_book`. RECEIVED entries are immediately archived to history and removed from the daily table so owners see only current operational shortages.

---

## Timestamps in order_book_history (for day/week/month review)

Resolved events in history will carry:

| Field | Meaning |
|-------|---------|
| `entry_date` | Day the shortage event belongs to (for filtering by day/week/month). |
| `created_at` | When the shortage was first recorded (detected). |
| `ordered_at` | When the order was placed (PO or branch order creation). |
| `received_at` | When stock arrived (GRN or branch receipt). |
| `archived_at` | When the event was closed and moved to history. |

Existing `order_book_history` has `created_at`, `updated_at`, `archived_at`. To support the above:

- Add **`entry_date`** (DATE) so history can be filtered by day/week/month like the daily book.
- Add **`ordered_at`** (TIMESTAMPTZ) and **`received_at`** (TIMESTAMPTZ).
- Use **`archived_at`** as “closed” time when moving RECEIVED → history.
- Add **`branch_order_id`** where applicable (mirror of daily table).

---

## daily_order_book (additions only)

- **`received_at`** (TIMESTAMPTZ, nullable) – set when status becomes RECEIVED.
- **`ordered_at`** (TIMESTAMPTZ, nullable) – set when status becomes ORDERED (so we can copy to history on archive).
- **status** – allow value **`RECEIVED`** in addition to PENDING, ORDERED. (No DB constraint change if status is a string.)

Unique index stays: one active entry per `(branch_id, item_id, entry_date)` where `status IN ('PENDING', 'ORDERED')`. RECEIVED rows are not “active” for uniqueness; they are about to be archived and removed.

---

## What we do not change

- **Trigger logic** – sale-triggered, auto-generate, and threshold rules unchanged.
- **Duplicate prevention** – unique index and application checks unchanged.
- **Manual entry** – create/update/delete behavior unchanged.
- **Sales batching integration** – `process_sale_for_order_book` unchanged.

---

## What we implement

1. **Schema** – Add `ordered_at`, `received_at` to `daily_order_book`. Add `entry_date`, `ordered_at`, `received_at`, `branch_order_id` to `order_book_history` (if not already present).
2. **Transitions** – When creating PO/branch order: set `ordered_at` on the daily entry. When receiving stock (GRN / branch receipt): set `status = RECEIVED`, `received_at`; then archive to history (status CLOSED, copy timestamps) and delete from daily_order_book.
3. **Receipt detection** – After posting ledger and snapshot, call `OrderBookService.mark_items_received()` in:
   - **GRN** (`create_grn` in `purchases.py`)
   - **Supplier invoice batch** (`batch_supplier_invoice` in `purchases.py`)
   - **Branch receipt confirm** (`confirm_branch_receipt` in `branch_inventory.py`)

This design keeps the Order Book as a **dated operational notebook**: active shortages in the daily table, full request → order → receipt → closed timeline in history, filterable by day, week, or month.

---

## Implementation (done)

- **Migration**: `068_order_book_lifecycle.sql` adds columns and backfills `order_book_history.entry_date`.
- **PO / branch order**: `ordered_at` set when status becomes ORDERED (order_book API and branch_inventory API).
- **Receipt**: `mark_items_received()` finds ORDERED entries, archives to history as CLOSED with `entry_date`, `ordered_at`, `received_at`, `archived_at`, then deletes from daily_order_book.
- **History API**: Optional `date_from` / `date_to` query params filter by `entry_date` for day/week/month review.
