-- Migration 002: Username and invitation fields on users

ALTER TABLE users ADD COLUMN IF NOT EXISTS username VARCHAR(100) UNIQUE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS invitation_token VARCHAR(255);
ALTER TABLE users ADD COLUMN IF NOT EXISTS invitation_code VARCHAR(50);
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_pending BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS password_set BOOLEAN DEFAULT FALSE;
ALTER TABLE users ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
CREATE INDEX IF NOT EXISTS idx_users_invitation_token ON users(invitation_token);
CREATE INDEX IF NOT EXISTS idx_users_invitation_code ON users(invitation_code);
CREATE INDEX IF NOT EXISTS idx_users_is_pending ON users(is_pending);
CREATE INDEX IF NOT EXISTS idx_users_deleted_at ON users(deleted_at);

CREATE UNIQUE INDEX IF NOT EXISTS idx_users_invitation_token_unique
    ON users(invitation_token) WHERE invitation_token IS NOT NULL;
CREATE UNIQUE INDEX IF NOT EXISTS idx_users_invitation_code_unique
    ON users(invitation_code) WHERE invitation_code IS NOT NULL;

CREATE OR REPLACE FUNCTION ensure_first_user_is_super_admin()
RETURNS TRIGGER AS $$
DECLARE
    v_user_count INTEGER;
    v_super_admin_role_id UUID;
    v_first_branch_id UUID;
BEGIN
    SELECT COUNT(*) INTO v_user_count FROM users
    WHERE deleted_at IS NULL AND id != NEW.id;
    IF v_user_count = 0 THEN
        SELECT id INTO v_super_admin_role_id FROM user_roles WHERE role_name = 'Super Admin' LIMIT 1;
        IF v_super_admin_role_id IS NOT NULL THEN
            SELECT id INTO v_first_branch_id FROM branches ORDER BY created_at ASC LIMIT 1;
            IF v_first_branch_id IS NOT NULL AND NOT EXISTS (
                SELECT 1 FROM user_branch_roles
                WHERE user_id = NEW.id AND branch_id = v_first_branch_id AND role_id = v_super_admin_role_id
            ) THEN
                INSERT INTO user_branch_roles (user_id, branch_id, role_id)
                VALUES (NEW.id, v_first_branch_id, v_super_admin_role_id);
            END IF;
        END IF;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_ensure_first_user_super_admin ON users;
CREATE TRIGGER trigger_ensure_first_user_super_admin
    AFTER INSERT ON users
    FOR EACH ROW
    EXECUTE FUNCTION ensure_first_user_is_super_admin();

CREATE OR REPLACE FUNCTION promote_first_user_to_super_admin() RETURNS VOID AS $$
DECLARE
    v_first_user_id UUID;
    v_super_admin_role_id UUID;
    v_first_branch_id UUID;
BEGIN
    SELECT id INTO v_first_user_id FROM users WHERE deleted_at IS NULL ORDER BY created_at ASC LIMIT 1;
    IF v_first_user_id IS NULL THEN RETURN; END IF;
    SELECT id INTO v_super_admin_role_id FROM user_roles WHERE role_name = 'Super Admin' LIMIT 1;
    IF v_super_admin_role_id IS NULL THEN RETURN; END IF;
    SELECT id INTO v_first_branch_id FROM branches ORDER BY created_at ASC LIMIT 1;
    IF v_first_branch_id IS NULL THEN RETURN; END IF;
    IF NOT EXISTS (
        SELECT 1 FROM user_branch_roles
        WHERE user_id = v_first_user_id AND branch_id = v_first_branch_id AND role_id = v_super_admin_role_id
    ) THEN
        INSERT INTO user_branch_roles (user_id, branch_id, role_id)
        VALUES (v_first_user_id, v_first_branch_id, v_super_admin_role_id);
    END IF;
END;
$$ LANGUAGE plpgsql;
