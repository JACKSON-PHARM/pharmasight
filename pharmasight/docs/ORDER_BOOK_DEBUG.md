# Order book: debugging 500 / Decimal JSON errors

## What the API actually returns

FastAPI’s `HTTPException` only exposes a **`detail`** field (e.g. `{"detail": "Failed to load order book: Object of type Decimal is not JSON serializable"}`). There is **no separate `error` key** unless something else (client, proxy, or old code) adds it.

If you see **`detail` and `error` as two keys**, compare the raw response in **Network → Response** with what the backend route returns.

## Get a full stack trace (recommended)

1. Set **`DEBUG=true`** in your `.env` (or environment) so optional stderr dumps run.
2. **Restart** the API (`Ctrl+C`, then `python start.py` from the project root). Confirm you are hitting the same host/port as the process you restarted.
3. Reproduce **GET** `/api/order-book?...` with data (non-empty list).
4. Watch the **terminal** where `start.py` runs:
   - **`Order book list failed`** — failure before/during query, maps, or per-row serialization.
   - **`Order book: _everything_json_safe failed`** — unexpected value during deep sanitize.
   - **`Order book: json.dumps failed after sanitize`** — should be rare after sanitize (report if you see this).

`logger.exception(...)` lines include the **full traceback** in normal log output.

## Temporary “bare raise” (only for local debugging)

To mirror a raw stack trace at the cost of an unhandled 500, you can **temporarily** replace the outer `except` in `list_order_book_entries` with `raise` after `traceback.print_exc()`. **Do not commit** that to production.

## Code paths: empty day vs day with rows

- **No rows** → trivial `[]` and little work.
- **With rows** → wholesale cost map, stock, `_serialize_order_book_entry` for each row, then `_everything_json_safe` + `json.dumps`. Any Decimal must be converted before `json.dumps`; the sanitizer also walks **`Mapping`** (not only `dict`) for ORM row–like objects.
