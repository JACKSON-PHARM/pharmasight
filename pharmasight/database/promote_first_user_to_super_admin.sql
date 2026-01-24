-- =====================================================
-- PROMOTE FIRST USER TO SUPER ADMIN
-- =====================================================
-- Run this script to promote your existing first user to Super Admin role
-- This gives them full permissions to create users and manage roles
-- =====================================================

-- Step 1: Insert Super Admin role if it doesn't exist
INSERT INTO user_roles (role_name, description) VALUES
    ('Super Admin', 'Full system access with all permissions - can manage users and roles')
ON CONFLICT (role_name) DO NOTHING;

-- Step 2: Promote the first user (by creation date) to Super Admin
DO $$
DECLARE
    v_first_user_id UUID;
    v_super_admin_role_id UUID;
    v_first_branch_id UUID;
BEGIN
    -- Get the first user (by creation date, excluding soft-deleted)
    SELECT id INTO v_first_user_id
    FROM users
    WHERE deleted_at IS NULL
    ORDER BY created_at ASC
    LIMIT 1;
    
    IF v_first_user_id IS NULL THEN
        RAISE NOTICE 'No users found';
        RETURN;
    END IF;
    
    RAISE NOTICE 'First user ID: %', v_first_user_id;
    
    -- Get Super Admin role
    SELECT id INTO v_super_admin_role_id
    FROM user_roles
    WHERE role_name = 'Super Admin'
    LIMIT 1;
    
    IF v_super_admin_role_id IS NULL THEN
        RAISE NOTICE 'Super Admin role not found - please run schema.sql first';
        RETURN;
    END IF;
    
    RAISE NOTICE 'Super Admin role ID: %', v_super_admin_role_id;
    
    -- Get first branch
    SELECT id INTO v_first_branch_id
    FROM branches
    ORDER BY created_at ASC
    LIMIT 1;
    
    IF v_first_branch_id IS NULL THEN
        RAISE NOTICE 'No branches found - cannot assign role. Please create a branch first.';
        RETURN;
    END IF;
    
    RAISE NOTICE 'First branch ID: %', v_first_branch_id;
    
    -- Assign Super Admin role if not already assigned
    IF NOT EXISTS (
        SELECT 1 FROM user_branch_roles
        WHERE user_id = v_first_user_id
        AND branch_id = v_first_branch_id
        AND role_id = v_super_admin_role_id
    ) THEN
        INSERT INTO user_branch_roles (user_id, branch_id, role_id)
        VALUES (v_first_user_id, v_first_branch_id, v_super_admin_role_id);
        RAISE NOTICE 'Successfully promoted first user to Super Admin!';
    ELSE
        RAISE NOTICE 'First user already has Super Admin role';
    END IF;
END $$;

-- Verify the assignment
SELECT 
    u.email,
    u.full_name,
    ur.role_name,
    b.name as branch_name
FROM users u
JOIN user_branch_roles ubr ON u.id = ubr.user_id
JOIN user_roles ur ON ubr.role_id = ur.id
JOIN branches b ON ubr.branch_id = b.id
WHERE ur.role_name = 'Super Admin'
ORDER BY u.created_at ASC;
