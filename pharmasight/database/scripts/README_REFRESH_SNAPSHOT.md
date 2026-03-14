# Snapshot refresh script (run in Supabase)

**File:** `refresh_snapshot_harte_one_branch.sql`

Use this when item search returns "No items match" after an Excel import because the **item_branch_snapshot** table was not refreshed (e.g. no queue worker ran).

## How to run

1. Open **Supabase Dashboard** → your project → **SQL Editor**.
2. Run the script in the **database where Harte’s data lives** (same DB your app uses for that tenant).
3. Execute the full script (one statement). It fills/updates `item_branch_snapshot` for:
   - **company_id:** `79c297dc-0091-4f9a-b918-e768aaf80b14`
   - **branch_id:** `d21e22be-fb42-40f2-bcdc-0a4c94bc9889`
4. After it completes, item search (e.g. "keppra") should work.

## Different company/branch

Edit the script and replace the two UUIDs at the top and in the CTEs:

- `79c297dc-0091-4f9a-b918-e768aaf80b14` → your `company_id`
- `d21e22be-fb42-40f2-bcdc-0a4c94bc9889` → your `branch_id`

## Alternative from backend

From the repo (backend), you can also run the bulk refresh for this branch:

```bash
cd pharmasight/backend
python -m scripts.run_bulk_snapshot_refresh --company-id 79c297dc-0091-4f9a-b918-e768aaf80b14 --branch-id d21e22be-fb42-40f2-bcdc-0a4c94bc9889
```

That uses the same logic and requires the app database connection (e.g. `DATABASE_URL`).
