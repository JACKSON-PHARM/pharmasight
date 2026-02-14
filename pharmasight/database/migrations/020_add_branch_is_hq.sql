-- Migration 020: Add is_hq to branches (HQ-only permissions)
-- Only one branch per company can be HQ. HQ has exclusive access to: create items, suppliers, users, roles, branches.

ALTER TABLE branches ADD COLUMN IF NOT EXISTS is_hq BOOLEAN DEFAULT FALSE;

-- Set the first branch (by created_at) as HQ if none is set
UPDATE branches b
SET is_hq = TRUE
WHERE b.id = (
    SELECT id FROM branches
    WHERE company_id = b.company_id
    ORDER BY created_at ASC
    LIMIT 1
)
AND NOT EXISTS (SELECT 1 FROM branches WHERE company_id = b.company_id AND is_hq = TRUE);

CREATE INDEX IF NOT EXISTS idx_branches_is_hq ON branches(is_hq) WHERE is_hq = TRUE;
