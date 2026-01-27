# Setup Instructions for Background Job Import

## Step 1: Create Database Table

Run the SQL migration to create the `import_jobs` table:

```bash
psql -U your_user -d pharmasight -f database/create_import_jobs_table.sql
```

Or manually execute the SQL in `database/create_import_jobs_table.sql`.

## Step 2: Restart Backend Server

The backend needs to be restarted to load the new `ImportJob` model:

```bash
# Windows PowerShell
cd pharmasight\backend
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Step 3: Test the Import

1. Open the Items page in your browser
2. Click "Import Items"
3. Select your Excel file
4. Click "Import Items" button

**Expected Behavior**:
- Modal shows "Import started - Processing in background..." immediately
- Progress bar updates every 2 seconds with real progress
- Shows "Processing 2500/9713 items... (45s elapsed)"
- When complete, shows results and closes modal

## What Changed

### Before ❌
- Frontend waited 600 seconds for response
- Request timed out while backend was still processing
- No real progress updates
- User couldn't tell if import was working

### After ✅
- API returns `job_id` immediately (< 1 second)
- Frontend polls for progress every 2 seconds
- Shows real progress: "Processing X/Y items..."
- No timeouts - import continues in background
- User can see exactly what's happening

## Troubleshooting

### Import job not found
- Check that database table was created
- Check backend logs for errors
- Verify `ImportJob` model is imported in `models/__init__.py`

### Progress not updating
- Check browser console for polling errors
- Verify backend is updating `ImportJob.processed_rows`
- Check network tab to see if `/api/excel/import/{job_id}/progress` is being called

### Job stuck in "pending" status
- Check backend logs for errors in `process_import_job`
- Verify background task is running
- Check database connection
