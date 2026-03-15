# Unified Transaction Engine — Manual Test Matrix

Use this checklist to verify Phase 8 behaviour manually (after automated tests pass).

| # | Scenario | Steps | Expected |
|---|----------|--------|----------|
| 1 | **Create credit note** | Sales → Returns → New Return; select a batched invoice; set return qty ≤ sold for one or more lines; enter reason and date; Create Return. | Credit note created; stock increases; ledger has `SALE_RETURN` rows; `document_number` set (e.g. CN-01-000014). |
| 2 | **Over-return** | Same flow; set return qty **greater than** sold for a line. | 400 error; no credit note created; message about return quantity exceeding remaining. |
| 3 | **Double return** | Create first return for part of a line (e.g. return 3 of 10). Create second return for same line (e.g. return 5). | Both succeed; total returned (8) ≤ sold (10). Third return of 3 more for same line fails (would exceed). |
| 4 | **Gross profit** | Create a sale and batch it; create a return for part of it; run Gross Profit report for that period. | Net sales = sales − credit notes; COGS reduced by return cost; margin reflects return. |
| 5 | **Supplier return** | Purchases → approve a supplier return. | Ledger has `PURCHASE_RETURN`; stock decreases; `document_number` set (e.g. PR-…). |
| 6 | **Transfer** | Complete a branch transfer; confirm receipt at receiving branch. | Ledger has `TRANSFER_OUT` (supplying branch) and `TRANSFER_IN` (receiving branch); both rows have `document_number` (e.g. TRF-…). |
| 7 | **Return from invoice** | Open a BATCHED/PAID sales invoice; click **Return**. | Create-return flow opens with that invoice pre-selected; submit return as in scenario 1. |

## Notes

- **Rollback:** If a test fails mid-flow, ensure no partial commit (e.g. ledger row without snapshot). All stock mutations run in a single transaction.
- **Concurrency (optional):** Two simultaneous return requests for the same invoice: one should succeed, the other fail validation when total return would exceed sold.
