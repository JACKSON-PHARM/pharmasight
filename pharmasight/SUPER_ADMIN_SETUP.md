# Super Admin Setup

## Overview
The first admin user created in the database is now automatically assigned the "Super Admin" role, which gives them full permissions to:
- Create users
- Create and manage roles
- Edit users
- Delete users
- Manage all aspects of the system

## Changes Made

### 1. Database Schema Updates
- Added "Super Admin" role to the default roles
- Created a database trigger that automatically assigns "Super Admin" to the first user
- Created a helper function `promote_first_user_to_super_admin()` for manual promotion

### 2. Frontend Updates
- Updated permission checking functions to recognize "Super Admin" role
- Super Admin users now have access to all user management features

### 3. SQL Script
- Created `database/promote_first_user_to_super_admin.sql` to promote existing first users

## For New Installations

The first user you create will automatically get "Super Admin" role when:
1. They are the first user in the database (by creation date)
2. At least one branch exists in the system

This happens automatically via database trigger.

## For Existing Installations

If you already have an admin user that needs Super Admin permissions:

### Option 1: Run the SQL Script (Recommended)
1. Open Supabase SQL Editor
2. Copy and paste the contents of `database/promote_first_user_to_super_admin.sql`
3. Click "Run"
4. The script will:
   - Create the "Super Admin" role if it doesn't exist
   - Promote your first user (by creation date) to Super Admin
   - Show you a verification query

### Option 2: Manual SQL
```sql
-- Insert Super Admin role
INSERT INTO user_roles (role_name, description) VALUES
    ('Super Admin', 'Full system access with all permissions - can manage users and roles')
ON CONFLICT (role_name) DO NOTHING;

-- Get your user ID (replace email with your actual email)
SELECT id FROM users WHERE email = 'your-email@example.com';

-- Get Super Admin role ID
SELECT id FROM user_roles WHERE role_name = 'Super Admin';

-- Get your branch ID
SELECT id FROM branches ORDER BY created_at ASC LIMIT 1;

-- Assign Super Admin role (replace UUIDs with actual IDs from above queries)
INSERT INTO user_branch_roles (user_id, branch_id, role_id)
VALUES ('your-user-id', 'your-branch-id', 'super-admin-role-id');
```

## Verify Super Admin Assignment

Run this query to verify:
```sql
SELECT 
    u.email,
    u.full_name,
    ur.role_name,
    b.name as branch_name
FROM users u
JOIN user_branch_roles ubr ON u.id = ubr.user_id
JOIN user_roles ur ON ubr.role_id = ur.id
JOIN branches b ON ubr.branch_id = b.id
WHERE ur.role_name = 'Super Admin';
```

## Role Hierarchy

1. **Super Admin** - Full access, can manage users and roles
2. **Admin** - Full system access (legacy role)
3. **Secondary Admin** - Limited admin access
4. **Pharmacist** - Can sell, purchase, view reports
5. **Cashier** - Can sell only
6. **Procurement** - Can purchase and view inventory
7. **Viewer** - Read-only access

## Notes

- Only "Super Admin" can create new roles
- Only "Super Admin" and "Admin" can create users
- The first user (by creation date) automatically gets Super Admin
- You can only have one Super Admin initially (the first user)
- Additional users can be promoted to Super Admin if needed (manual SQL required)

## Troubleshooting

**Issue**: "You do not have permission to create users" message still appears
**Solution**: 
1. Verify you have "Super Admin" role assigned (see verification query above)
2. Refresh the page or log out and log back in
3. Check browser console for any errors

**Issue**: Super Admin role doesn't exist in database
**Solution**: 
1. Run the SQL script `promote_first_user_to_super_admin.sql`
2. Or manually insert the role (see Option 2 above)

**Issue**: Trigger didn't assign Super Admin automatically
**Solution**:
1. Check that the trigger exists: `SELECT * FROM pg_trigger WHERE tgname = 'trigger_ensure_first_user_super_admin';`
2. Ensure at least one branch exists before creating the first user
3. Run the promotion script manually
