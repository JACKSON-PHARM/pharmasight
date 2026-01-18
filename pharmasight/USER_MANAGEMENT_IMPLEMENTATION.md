# User Management System Implementation

## Overview

This document describes the User Management system implemented for the PharmaSight application. The system allows Admin and Secondary Admin users to manage organization users through the Settings → Users & Roles tab.

## What Was Added

### 1. Database Schema Updates

**Migration File**: `database/add_user_invitation_fields.sql`

Added new fields to the `users` table:
- `invitation_token` (VARCHAR 255, unique) - Token for invitation links
- `invitation_code` (VARCHAR 50, unique) - Simple 6-digit invitation code
- `is_pending` (BOOLEAN, default FALSE) - Whether user is pending password setup
- `password_set` (BOOLEAN, default FALSE) - Whether user has completed password setup
- `deleted_at` (TIMESTAMPTZ, nullable) - Soft delete timestamp

**Important**: Run this migration on your database before using the user management features:
```sql
-- Run the migration file
\i database/add_user_invitation_fields.sql
```

### 2. Backend Implementation

#### Models (`backend/app/models/user.py`)
- Updated `User` model with new invitation fields
- All new fields are nullable to maintain backward compatibility

#### Schemas (`backend/app/schemas/user.py`)
- `UserCreate` - Schema for creating new users
- `UserUpdate` - Schema for updating user details
- `UserResponse` - User response with role information
- `UserListResponse` - List of users
- `UserRoleResponse` - Role information
- `UserBranchRoleResponse` - Branch-role assignment info
- `UserActivateRequest` - Activate/deactivate request
- `UserRoleUpdate` - Role assignment update
- `InvitationResponse` - Response when user is created

#### API Endpoints (`backend/app/api/users.py`)

**User Management:**
- `GET /api/users` - List all users (with optional `include_deleted` parameter)
- `GET /api/users/{user_id}` - Get user by ID with role information
- `POST /api/users` - Create new user (with invitation code)
- `PUT /api/users/{user_id}` - Update user details
- `PATCH /api/users/{user_id}/activate` - Activate/deactivate user
- `DELETE /api/users/{user_id}` - Soft delete user
- `POST /api/users/{user_id}/roles` - Assign role to user for a branch

**Role Management:**
- `GET /api/users/roles` - List all available roles

#### Router Registration (`backend/app/main.py`)
- Added `users_router` to the main application with tag "User Management"

### 3. Frontend Implementation

#### API Client (`frontend/js/api.js`)
Added `API.users` object with methods:
- `list(includeDeleted)` - List users
- `get(userId)` - Get user by ID
- `create(data)` - Create new user
- `update(userId, data)` - Update user
- `activate(userId, isActive)` - Activate/deactivate
- `delete(userId)` - Delete user
- `assignRole(userId, roleData)` - Assign role
- `listRoles()` - List all roles

#### Settings Page (`frontend/js/pages/settings.js`)

**Updated `renderUsersPage()` function:**
- Displays list of users in a table
- Shows user email, name, roles, and status
- Includes action buttons: Edit, Activate/Deactivate, Delete, Copy Invitation Code

**New Functions:**
- `showCreateUserModal()` - Modal for creating new users
- `createUser(event)` - Handle user creation
- `copyInvitationCode(code, email)` - Copy invitation code to clipboard
- `editUser(userId)` - Edit user (placeholder for now)
- `toggleUserActive(userId, isActive)` - Activate/deactivate user
- `deleteUser(userId, email)` - Soft delete user with confirmation

**UI Features:**
- Table view with user information
- Status badges (Active/Inactive, Pending)
- Role badges showing assigned roles
- Invitation code display and copy functionality
- Create user form with role and branch selection

## How It Works

### User Creation Flow

1. **Admin creates user**:
   - Opens Settings → Users & Roles
   - Clicks "New User"
   - Fills form: Email (required), Name, Phone, Role (required), Branch (optional)
   - Submits form

2. **System generates invitation**:
   - Creates user record in database as `inactive` and `pending`
   - Generates unique `invitation_token` and `invitation_code`
   - Assigns role to branch (if branch selected)
   - Returns invitation code to admin

3. **Admin shares invitation**:
   - System shows invitation code in alert
   - Admin can copy code to clipboard
   - Admin shares code with new user

4. **User first login** (Future implementation):
   - User uses invitation code to access system
   - System prompts for password setup (minimum 4-digit PIN)
   - After password is set:
     - `password_set` = true
     - `is_pending` = false
     - `is_active` = true (or admin activates)

### Role Assignment

- Users can have multiple role-branch assignments
- Roles are assigned per branch (via `user_branch_roles` table)
- Available roles from seed data: `admin`, `pharmacist`, `cashier`, `procurement`, `viewer`
- Additional roles can be added to the `user_roles` table

**Note**: The requirement mentions more roles (Secondary Admin, Sales Person, Manager, Delivery, Auditor), but these are not yet in the seed data. They can be added to `user_roles` table as needed.

### User Management Actions

- **View Users**: List all active users with their roles
- **Activate/Deactivate**: Toggle user active status (soft disable)
- **Delete**: Soft delete user (sets `deleted_at` timestamp)
- **Edit**: Update user details (placeholder - basic update available via API)

## Security Notes

**Important**: The current implementation does NOT include:
- Admin-only access checks (endpoints are publicly accessible)
- Authentication/authorization middleware
- Password setup flow (future implementation)
- Supabase Auth integration for invited users (future implementation)

**TODO for Production**:
1. Add admin role check before allowing user management actions
2. Implement password setup flow for invited users
3. Integrate with Supabase Auth for user creation and password setting
4. Add audit logging for user management actions

## Database Migration

Before using the user management features, run the migration:

```bash
# Connect to your database and run:
psql -h your-db-host -U your-user -d your-database -f pharmasight/database/add_user_invitation_fields.sql
```

Or in Supabase SQL Editor, copy and paste the contents of `add_user_invitation_fields.sql`.

## Testing

1. **Create a user**:
   - Navigate to Settings → Users & Roles
   - Click "New User"
   - Fill in email, role, and optional branch
   - Submit and verify invitation code is shown

2. **List users**:
   - Verify users appear in the table
   - Check status badges are correct

3. **Activate/Deactivate**:
   - Click activate/deactivate button
   - Verify status changes

4. **Delete user**:
   - Click delete button
   - Confirm deletion
   - Verify user is soft-deleted (not shown in list)

## Future Enhancements

1. **Password Setup Flow**: Implement invitation code → password setup flow
2. **Role Permissions**: Add permission system based on roles
3. **Admin Access Control**: Add middleware to check admin role
4. **Email Invitations**: Send invitation emails with codes/links
5. **User Profile Editing**: Complete edit user modal with all fields
6. **Role Management UI**: UI to create/edit roles
7. **Bulk User Import**: Import users from CSV/Excel

## Files Modified/Created

### Backend
- ✅ `database/add_user_invitation_fields.sql` (NEW)
- ✅ `backend/app/models/user.py` (MODIFIED)
- ✅ `backend/app/schemas/user.py` (NEW)
- ✅ `backend/app/api/users.py` (NEW)
- ✅ `backend/app/main.py` (MODIFIED)

### Frontend
- ✅ `frontend/js/api.js` (MODIFIED)
- ✅ `frontend/js/pages/settings.js` (MODIFIED)

## Summary

The User Management system is now implemented with:
- ✅ User creation with invitation codes
- ✅ User listing with roles and status
- ✅ Activate/Deactivate functionality
- ✅ Soft delete functionality
- ✅ Role assignment per branch
- ✅ Frontend UI for all operations

The system is ready for testing. The next steps would be to:
1. Add admin authentication/authorization
2. Implement password setup flow for invited users
3. Integrate with Supabase Auth for complete user lifecycle
