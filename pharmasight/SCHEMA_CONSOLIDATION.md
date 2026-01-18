# ✅ Schema Consolidation Complete

## What Was Done

1. **Replaced `schema.sql`** with the new ONE COMPANY architecture schema
2. **Deleted duplicate** `schema_one_company.sql` file
3. **Updated `check_database.py`** to verify new required tables

## Current State

- ✅ **Single authoritative schema**: `database/schema.sql` (ONE COMPANY architecture)
- ✅ **All references updated**: Documentation now points to correct schema
- ✅ **No duplicates**: Old multi-tenant schema removed

## What Changed in the Schema

### New Tables Added
- `users` - Application users (no company_id, belongs to single company)
- `user_roles` - System role definitions
- `user_branch_roles` - **ONLY way** users access branches
- `document_sequences` - Branch-specific document numbering

### Updated Tables
- `branches.code` - Now **REQUIRED** (NOT NULL)
- All tables have proper comments explaining ONE COMPANY architecture

### New Functions
- `get_next_document_number()` - Enforces branch code in invoice numbers
- `get_company_id()` - Helper to get single company ID
- `enforce_single_company()` - Trigger function to prevent multiple companies

## For Existing Databases

If you already have a database with the old schema:

1. **Backup your data** first!
2. You have two options:

### Option A: Fresh Start (Recommended for new setups)
- Drop all tables
- Run the new `schema.sql`
- Use `/api/startup` to initialize

### Option B: Migration (If you have important data)
- Keep existing data
- Add new tables: `users`, `user_roles`, `user_branch_roles`
- Update `branches` table: Make `code` NOT NULL (update existing branches first!)
- Add trigger: `enforce_single_company()`
- Migrate existing users to new `users` table

## Verification

Run the database checker:
```powershell
cd C:\PharmaSight\pharmasight
python check_database.py
```

This will verify:
- ✅ All required tables exist
- ✅ ONE COMPANY trigger is installed
- ✅ Schema is up to date

## Next Steps

1. **If starting fresh**: Run `database/schema.sql` in Supabase
2. **If migrating**: Follow Option B above
3. **Start your app**: Use `start.bat` or `start.py`
4. **Complete setup**: Use the setup wizard to create company, admin user, and branch

## Files Reference

- **Authoritative Schema**: `database/schema.sql` ✅
- **Start Script**: `start.py` (no changes needed - doesn't reference schema)
- **Start Batch**: `start.bat` (no changes needed)
- **Database Checker**: `check_database.py` (updated ✅)

All documentation now correctly references `database/schema.sql`!

