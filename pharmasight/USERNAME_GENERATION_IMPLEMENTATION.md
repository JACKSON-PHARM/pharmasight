# Username Generation Implementation

## Overview
Implemented automatic username generation for users based on their full name. Usernames follow the format: **First Letter - Last Name** (e.g., "Dr. Jackson" → "D-JACKSON", "Sarah Wambui" → "S-WAMBUI").

## Changes Made

### 1. Username Generator Utility
**File:** `backend/app/utils/username_generator.py`
- Created utility function `generate_username_from_name()` that:
  - Extracts first letter of first name
  - Extracts last name (uppercase)
  - Removes titles (Dr., Mr., Mrs., etc.)
  - Handles duplicates by appending numbers
  - Validates against existing usernames in database

### 2. Database Schema Updates
**File:** `database/add_admin_full_name.sql`
- Added `admin_full_name` column to `tenants` table
- Allows storing admin's full name for username generation during invite creation

### 3. Backend Model Updates
**File:** `backend/app/models/tenant.py`
- Added `admin_full_name` field to `Tenant` model

### 4. Schema Updates
**File:** `backend/app/schemas/tenant.py`
- Added `admin_full_name` to `TenantBase`, `TenantUpdate`, and `TenantResponse`
- Added `username` to `TenantInviteResponse`

**File:** `backend/app/schemas/user.py`
- Made `username` optional in `UserCreate` (auto-generated if not provided)
- Added `username` to `InvitationResponse`

### 5. API Endpoint Updates

#### Tenant Management (`backend/app/api/tenants.py`)
- **Create Tenant:** Now accepts `admin_full_name` and stores it
- **Update Tenant:** Can update `admin_full_name`
- **Create Invite:** 
  - Generates username from `admin_full_name` if available
  - Falls back to email-based generation if no full name
  - Returns username in response

#### User Management (`backend/app/api/users.py`)
- **Create User:** 
  - Auto-generates username from `full_name` if `username` not provided
  - Requires either `username` or `full_name` to be provided
  - Returns generated username in `InvitationResponse`

### 6. Frontend Updates
**File:** `frontend/js/pages/admin_tenants.js`
- **Create Tenant Modal:** Added `admin_full_name` field (required)
- **Tenant Detail Modal:** Added `admin_full_name` field (editable)
- **Invite Modal:** Displays generated username to admin
- Updated `createInvite()` to pass username to modal

## Username Generation Rules

1. **Format:** `{FirstLetter}-{LASTNAME}`
   - Example: "Dr. Jackson" → "D-JACKSON"
   - Example: "Sarah Wambui" → "S-WAMBUI"

2. **Title Removal:** Automatically removes common titles:
   - Dr., Mr., Mrs., Ms., Miss, Prof., Professor, Eng., Engineer

3. **Duplicate Handling:** If username exists, appends number:
   - "D-JACKSON" → "D-JACKSON1" → "D-JACKSON2", etc.

4. **Fallback:** If no full name provided:
   - Extracts from email (e.g., "john.doe@example.com" → "J-DOE")
   - Final fallback: First letter + email local part

## Usage

### Creating a Tenant (Admin)
1. Fill in **Company Name**
2. Fill in **Admin Email**
3. Fill in **Admin Full Name** (required) - e.g., "Dr. Jackson"
4. System generates username: "D-JACKSON"

### Creating an Invite
1. Click "Invite" button on tenant
2. System generates username from `admin_full_name`
3. Username is displayed in invite modal
4. Share username with client along with invite link

### Creating a User (Admin)
1. Provide **Email** and **Full Name** (or **Username**)
2. If only full name provided, username auto-generates
3. Username is returned in response

## Migration

Run the migration to add `admin_full_name` column:
```bash
cd backend
python run_migration.py database/add_admin_full_name.sql
```

## Testing

1. **Create Tenant with Full Name:**
   - Company: "Test Pharmacy"
   - Admin Email: "admin@test.com"
   - Admin Full Name: "Dr. Jackson"
   - Expected Username: "D-JACKSON"

2. **Create Invite:**
   - Click "Invite" on tenant
   - Verify username "D-JACKSON" appears in modal

3. **Create User:**
   - Email: "user@test.com"
   - Full Name: "Sarah Wambui"
   - Expected Username: "S-WAMBUI" (auto-generated)

## Notes

- Usernames are case-insensitive for uniqueness checks
- Username generation is deterministic (same input = same output)
- Admin can override username by providing it explicitly when creating users
- Username is included in invite responses for easy sharing with clients
