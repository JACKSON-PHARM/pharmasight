# Snapshot refresh – night batch (high throughput)

When you have many items per branch (e.g. ~10,000) and several branches (e.g. 6), the default refresh rate can be too slow for a single maintenance window. Use these options to finish in one night.

## Fastest: bulk SQL (one query per branch, ~2 hours total)

For **~2 hours or less** for 6 branches × 10k items, use the **bulk SQL** script. It runs **one set-based SQL statement per branch** instead of 10k Python round-trips per branch.

```powershell
cd pharmasight\backend
$env:PYTHONPATH="."
python -m scripts.run_bulk_snapshot_refresh
```

This processes all pending **branch-wide** jobs in `snapshot_refresh_queue` (one SQL execution per branch). Each execution updates the entire branch’s `item_branch_snapshot` in one go (typically **minutes** per branch, not hours).

- **Single branch:** `python -m scripts.run_bulk_snapshot_refresh --company-id <uuid> --branch-id <uuid>`
- **Dry run:** `python -m scripts.run_bulk_snapshot_refresh --dry-run`

## 1. Increase throughput per process

- **`--quiet`** – Turns off SQL logging (SQLAlchemy at WARNING). Saves a lot of I/O and often **roughly doubles** effective speed.
- **`--chunk-size=1000`** – Commits every 1000 items instead of 200. Fewer commits → less overhead (typically 10–20% faster for large branches).

Example (one batch, then exit):

```powershell
cd pharmasight\backend
$env:PYTHONPATH="."
python -m scripts.run_snapshot_refresh_with_progress --once --quiet --chunk-size=1000
```

Or with the basic queue script (no progress lines):

```powershell
python -m scripts.process_snapshot_refresh_queue --once --quiet --chunk-size=1000
```

## 2. Run multiple branches in parallel

The queue has **one job per (company, branch)**. With `FOR UPDATE SKIP LOCKED`, each process claims a different job. So you can run **one process per branch** in parallel.

**Option A – Multiple terminals (e.g. 6 branches)**

Open 6 terminals. In each:

```powershell
cd pharmasight\backend
$env:PYTHONPATH="."
python -m scripts.run_snapshot_refresh_with_progress --once --quiet --chunk-size=1000
```

Each run will take one branch job; all 6 branches run at the same time. Wall-clock time ≈ time for **one** branch (~10k items) instead of six.

**Option B – Single process, sequential**

One process, all jobs in one batch (branches run one after another):

```powershell
python -m scripts.run_snapshot_refresh_with_progress --once --quiet --chunk-size=1000 --batch-size=10
```

Use `--batch-size` ≥ number of branch-wide jobs so one run takes all of them.

## 3. Rough time estimates

| Setup                    | ~10k items/branch | 6 branches (sequential) | 6 branches (6 parallel) |
|--------------------------|-------------------|--------------------------|--------------------------|
| Default (no quiet)      | ~8–9 h/branch     | ~2–3 days                | ~8–9 h                   |
| `--quiet`                | ~4–5 h/branch     | ~1–1.5 days              | ~4–5 h                   |
| `--quiet --chunk-size=1000` | ~3.5–4.5 h/branch | ~21–27 h                 | ~3.5–4.5 h               |

So for a single night (e.g. 8 h), **run 6 processes in parallel with `--quiet --chunk-size=1000`** to complete all 6 branches.

## 4. Check status before/after

```powershell
python -m scripts.run_snapshot_refresh_with_progress --status
```

Shows pending jobs and estimated item count per branch.
