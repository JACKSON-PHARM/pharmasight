# Order book: large packs & history filter

## Large wholesale packs (break-bulk)

For items with `pack_size >= 48` and `can_break_bulk` true, the automatic rule
“at or below one wholesale unit” no longer uses **full pack size** as the retail
threshold. Instead it uses:

`min(pack_size, max(20, int(pack_size * 0.25)))` retail units

Example: 100 tablets per wholesale → threshold **25** tablets. **50** tablets on
hand does **not** trigger that rule (fewer false positives when sales are 2–20
tablets at a time).

The “below monthly sales” rule uses **monthly_sales / 4** instead of **/ 2** for
the same items.

Constants live in `backend/app/services/order_book_service.py` (tune there if needed).

## Order book history API

`GET /api/order-book/history` accepts `history_status`:

| Value | Meaning |
|-------|---------|
| `ordered` (default) | PO placed from order book; stock **not yet received** (sourcing). |
| `closed` | Archived after receipt (replenished). |
| `cancelled` | Deleted from daily book. |
| `all` | All of the above. |
| Comma-separated | e.g. `closed,ordered` |

Previously the endpoint only returned **CLOSED** rows; the UI now defaults to
**ORDERED** so open sourcing lines are visible.

**Stale ORDERED rows:** When stock is received, a **CLOSED** row is added; any matching
**ORDERED** audit row with the same `purchase_order_id` + `item_id` is deleted. The
history query also excludes **ORDERED** rows that already have a matching **CLOSED**
row (for older databases).

**UI (Purchases → Order book → history card):** three primary filters plus combined + all archived:

| Show (UI) | Behaviour |
|-----------|-----------|
| **Items replenished (stock received)** | `GET /api/order-book/history?history_status=closed` — **CLOSED** only. |
| **Ordered, not replenished yet** | `history?history_status=ordered` **merged** with **daily** `ORDERED` lines from `GET /api/order-book` (same date range, `include_ordered=true`). |
| **Not ordered nor replenished** | `history?history_status=cancelled` **merged** with **daily** `PENDING` lines from the list endpoint. |
| **Combined: all shortage** | `GET /api/order-book/no-replenishment` — daily PENDING/ORDERED + history ORDERED/CANCELLED, never **CLOSED**. |
| **All archived** | `history_status=all` |

Legacy: `history_status=no_replenishment` on `/history` filters **ORDERED + CANCELLED** only (not CLOSED).
`history_status=cancelled` is **CANCELLED** only.

**Troubleshooting 500 on `/api/order-book`:** Ensure the API base URL matches the running
backend port (e.g. if `start.py` uses port **8001**, point the frontend at `http://localhost:8001`).
