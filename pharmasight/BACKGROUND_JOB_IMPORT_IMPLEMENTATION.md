# Background Job Import Implementation

## Problem Solved ✅
- **Before**: Frontend request timed out after 600 seconds while backend was still processing
- **After**: API returns job_id immediately (< 1 second), frontend polls for progress

## Implementation

### 1. Database Table
**File**: `database/create_import_jobs_table.sql`

Created `import_jobs` table to track:
- Job status (pending, processing, completed, failed)
- Progress (processed_rows / total_rows)
- Statistics (items created, updated, etc.)
- Error messages

### 2. Import Job Model
**File**: `backend/app/models/import_job.py`

- Tracks import progress
- Provides `to_dict()` for API responses
- Stores file hash for duplicate detection

### 3. API Endpoints

#### POST `/api/excel/import`
- **Before**: Blocked for 2-10 minutes waiting for import to complete
- **After**: Returns `job_id` immediately (< 1 second)
- Starts background task using FastAPI `BackgroundTasks`
- Checks for duplicate imports in progress

#### GET `/api/excel/import/{job_id}/progress`
- Returns current progress, status, and statistics
- Frontend polls this endpoint every 2 seconds
- Shows real-time progress percentage

### 4. Import Service Updates
**File**: `backend/app/services/excel_import_service.py`

- Accepts optional `job_id` parameter
- Updates `ImportJob.processed_rows` after each batch commit
- Tracks `last_batch` for resume capability (future)

### 5. Frontend Updates
**File**: `frontend/js/pages/items.js`

**Before**:
- Simulated progress (not real)
- Single request with 600-second timeout
- No way to know if backend was still working

**After**:
- Polls `/api/excel/import/{job_id}/progress` every 2 seconds
- Shows **real** progress percentage
- Shows processed/total items
- Shows elapsed time
- Handles all statuses (pending, processing, completed, failed)

**File**: `frontend/js/api.js`

- Added `API.excel.getProgress(jobId)` method
- Reduced import timeout to 30 seconds (just to start job)

## Benefits

1. **No More Timeouts**: API responds immediately
2. **Real Progress**: Shows actual backend progress, not simulation
3. **Better UX**: User sees exactly what's happening
4. **Resilient**: Can handle network interruptions (polling resumes)
5. **Future-Proof**: Foundation for resume/retry mechanism

## Usage Flow

1. User clicks "Import Items"
2. Frontend uploads file → Backend creates `ImportJob` → Returns `job_id` (< 1 second)
3. Frontend starts polling `/api/excel/import/{job_id}/progress` every 2 seconds
4. Backend processes import in background, updates `ImportJob` after each batch
5. Frontend shows real progress: "Processing 2500/9713 items... (45s elapsed)"
6. When status = "completed", frontend shows results and closes modal

## Next Steps (Future Enhancements)

1. **Resume/Retry**: Use `last_batch` to resume from failure point
2. **WebSocket**: Replace polling with WebSocket for real-time updates
3. **Job History**: Show list of past imports
4. **Cancel Job**: Allow user to cancel in-progress imports
