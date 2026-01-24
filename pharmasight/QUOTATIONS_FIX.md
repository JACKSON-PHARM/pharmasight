# Quotations Module - Fix Instructions

## Problem
- CORS error when accessing `/api/quotations/branch/{branch_id}`
- 500 Internal Server Error
- Tables were missing from database

## Solution Applied

### ✅ Step 1: Database Tables Created
The `quotations` and `quotation_items` tables have been created in your database.

**Verification:**
```bash
cd pharmasight\backend
python -c "from app.database import engine; from sqlalchemy import inspect; inspector = inspect(engine); tables = inspector.get_table_names(); print('quotations' in tables, 'quotation_items' in tables)"
```
Should output: `True True`

### ✅ Step 2: Backend Code
- Router is registered in `app/main.py`
- Endpoints are defined in `app/api/quotations.py`
- Models exist in `app/models/sale.py`
- Schemas exist in `app/schemas/sale.py`

## Required Action: Restart Backend Server

**The backend server MUST be restarted** to register the new quotations router.

### How to Restart:

1. **Stop the current backend server** (Ctrl+C in the terminal where it's running)

2. **Start it again:**
   ```bash
   cd pharmasight\backend
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
   ```

   Or if you're using a script:
   ```bash
   python start.py
   ```

3. **Verify the endpoint is available:**
   - Open: http://localhost:8000/docs
   - Look for "Quotations" section in the API docs
   - You should see endpoints like:
     - `GET /api/quotations/branch/{branch_id}`
     - `POST /api/quotations`
     - etc.

4. **Test the endpoint:**
   - In the browser, go to: http://localhost:8000/api/quotations/branch/{your-branch-id}
   - Should return an empty array `[]` (if no quotations exist yet)

## Expected Result

After restarting:
- ✅ No more CORS errors
- ✅ No more 500 errors
- ✅ Quotations page loads successfully
- ✅ Can create new quotations
- ✅ Can view existing quotations

## Troubleshooting

If you still get errors after restarting:

1. **Check backend logs** for any Python errors
2. **Verify CORS settings** in `app/config.py` includes `http://localhost:3000`
3. **Check database connection** is working
4. **Verify branch_id** in the frontend request matches an existing branch

## Files Modified/Created

- ✅ `pharmasight/backend/app/api/quotations.py` - API endpoints
- ✅ `pharmasight/backend/app/models/sale.py` - Quotation models
- ✅ `pharmasight/backend/app/schemas/sale.py` - Quotation schemas
- ✅ `pharmasight/backend/app/services/document_service.py` - Quotation numbering
- ✅ `pharmasight/backend/app/main.py` - Router registration
- ✅ `pharmasight/database/add_quotations_tables.sql` - Migration script
- ✅ `pharmasight/backend/create_quotations_tables.py` - Migration runner
