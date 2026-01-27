# Stock Take Shelf-Based Workflow with Verification

## ✅ New Workflow Implemented

### 1. **Shelf-Based Counting**
- **Counter Flow:**
  1. Counter clicks "Start Counting a Shelf"
  2. Enters shelf name once (e.g., "A1", "Shelf 3")
  3. System validates shelf name is unique (no two counters can use same shelf name)
  4. Counter counts all items for that shelf
  5. Items are saved immediately as they're counted
  6. Counter clicks "Submit Shelf Count" when done with shelf
  7. Shelf is marked as ready for verification

### 2. **Verification Workflow**
- **Verifier Flow:**
  1. Verifier sees "Verify Count" interface (role-based)
  2. Lists all counted shelves grouped by status:
     - **Pending** (awaiting verification)
     - **Approved** (verified correct)
     - **Rejected** (returned to counter)
  3. Verifier clicks "Review" on a pending shelf
  4. Sees all items counted for that shelf
  5. Can **Approve** (all items correct) or **Reject** (with reason)
  6. Rejected shelves return to counter for correction

### 3. **Shelf Name Uniqueness**
- **Rule:** No two shelves can have the same name in the same session
- **Exception:** Same counter can continue their own shelf (resume counting)
- **Validation:** Backend checks if shelf name exists with different counter
- **Assisted Naming:** Optional suggestions from existing shelf names

### 4. **Edit Before Verification**
- Counters can edit/delete their counts **before verification**
- Once **approved**, counts are locked (only admin can revert)
- **Rejected** counts can be edited by the counter

## 📋 Database Migration Required

**File**: `database/add_stock_take_verification.sql`

**What it adds:**
- `verification_status` (PENDING, APPROVED, REJECTED)
- `verified_by` (user who verified)
- `verified_at` (timestamp)
- `rejection_reason` (why rejected)

**How to Run:**
1. Go to Supabase SQL Editor
2. Copy contents of `database/add_stock_take_verification.sql`
3. Paste and Run
4. Verify: Check that `verification_status` column exists

## 🎯 User Workflows

### Counter Workflow

1. **Start Counting:**
   - Enter shelf name (e.g., "A1")
   - Click "Start Counting This Shelf"
   - System validates name is unique

2. **Count Items:**
   - Search for items
   - Click "Count" on item
   - Enter batch/expiry (if required)
   - Select unit and quantity
   - Click "Add to Shelf Count"
   - Item is saved immediately

3. **View Current Shelf:**
   - See all items counted for current shelf
   - Edit/delete items before submitting
   - See verification status per item

4. **Submit Shelf:**
   - Click "Submit Shelf Count"
   - Shelf marked as ready for verification
   - Can start counting another shelf

5. **Handle Rejected Shelves:**
   - See rejected shelves in "My Counted Items"
   - Edit items to correct errors
   - Re-submit for verification

### Verifier Workflow

1. **View Shelves:**
   - See list of all counted shelves
   - Grouped by status (Pending, Approved, Rejected)

2. **Review Shelf:**
   - Click "Review" on pending shelf
   - See all items with:
     - Item name
     - Batch number
     - Expiry date
     - Counted quantity
     - System quantity
     - Difference

3. **Approve:**
   - Click "Approve" if all items correct
   - All counts for shelf marked as APPROVED
   - Shelf locked (cannot be edited)

4. **Reject:**
   - Click "Reject" if errors found
   - Enter rejection reason
   - All counts for shelf marked as REJECTED
   - Returned to counter for correction

## 🔧 Technical Details

### Frontend Changes
- **Shelf Selection:** User enters shelf name once at start
- **Shelf Context:** All counts use current shelf (no per-item shelf input)
- **Shelf Submission:** Button to mark shelf as ready for verification
- **Verification Interface:** Role-based view for verifiers
- **Shelf Suggestions:** Optional assisted naming from existing shelves

### Backend Changes
- **Shelf Uniqueness:** Validates no two counters use same shelf name
- **Verification Status:** Tracks PENDING, APPROVED, REJECTED
- **Shelf Endpoints:**
  - `GET /api/stock-take/branch/{id}/shelves` - List all shelves
  - `GET /api/stock-take/branch/{id}/shelves/{name}/counts` - Get shelf counts
  - `POST /api/stock-take/branch/{id}/shelves/{name}/approve` - Approve shelf
  - `POST /api/stock-take/branch/{id}/shelves/{name}/reject` - Reject shelf

### Database Schema
```sql
-- New columns in stock_take_counts:
verification_status VARCHAR(20) DEFAULT 'PENDING' NOT NULL
verified_by UUID REFERENCES users(id)
verified_at TIMESTAMPTZ
rejection_reason TEXT
```

## ✅ Validation Rules

1. **Shelf Name:** Must be unique per session (different counters cannot use same name)
2. **Same Counter:** Can continue their own shelf (resume counting)
3. **Edit Before Verification:** Counters can edit PENDING or REJECTED counts
4. **Edit After Approval:** Only admin can revert APPROVED counts
5. **Verification:** Only verifiers can approve/reject shelves

## 📝 Notes

- **Shelf Name Suggestions:** Optional feature - shows existing shelf names as clickable suggestions
- **Immediate Save:** Items are saved to server immediately (not batched in memory)
- **Verification Status:** Per-count status, but approval/rejection applies to entire shelf
- **Rejected Counts:** Can be edited and re-submitted by counter
- **Approved Counts:** Locked until admin reverts (after stock take completion)

## 🚀 Next Steps

1. **Run Database Migration:** `database/add_stock_take_verification.sql`
2. **Restart Backend:** To load new model fields
3. **Test Workflow:**
   - Counter: Start shelf → Count items → Submit shelf
   - Verifier: Review shelf → Approve/Reject
   - Counter: Edit rejected shelf → Re-submit
