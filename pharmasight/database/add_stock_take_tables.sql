-- =====================================================
-- STOCK TAKE MULTI-USER SESSION MANAGEMENT
-- =====================================================
-- This migration adds support for multi-user stock take sessions
-- where multiple counters can count different shelves simultaneously
-- =====================================================

-- Stock Take Sessions Table
CREATE TABLE IF NOT EXISTS stock_take_sessions (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    company_id UUID NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    branch_id UUID NOT NULL REFERENCES branches(id) ON DELETE CASCADE,
    session_code VARCHAR(10) UNIQUE NOT NULL, -- e.g., "ST-MAR25A"
    status VARCHAR(50) NOT NULL DEFAULT 'DRAFT', -- DRAFT, ACTIVE, PAUSED, COMPLETED, CANCELLED
    created_by UUID NOT NULL REFERENCES users(id),
    allowed_counters UUID[] DEFAULT ARRAY[]::UUID[], -- Array of user IDs allowed to count
    assigned_shelves JSONB DEFAULT '{}'::JSONB, -- Map of user_id -> shelf_locations array
    is_multi_user BOOLEAN DEFAULT true,
    notes TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT valid_status CHECK (status IN ('DRAFT', 'ACTIVE', 'PAUSED', 'COMPLETED', 'CANCELLED'))
);

COMMENT ON TABLE stock_take_sessions IS 'Stock take sessions for multi-user counting. Only one active session per branch at a time.';
COMMENT ON COLUMN stock_take_sessions.session_code IS 'Short memorable code for easy reference (e.g., ST-MAR25A)';
COMMENT ON COLUMN stock_take_sessions.allowed_counters IS 'Array of user IDs who can participate as counters';
COMMENT ON COLUMN stock_take_sessions.assigned_shelves IS 'JSONB map: {"user_id": ["shelf1", "shelf2", ...]}';

-- Stock Take Counts Table (stores actual counts)
CREATE TABLE IF NOT EXISTS stock_take_counts (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES stock_take_sessions(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    counted_by UUID NOT NULL REFERENCES users(id),
    shelf_location VARCHAR(100), -- Optional shelf location
    counted_quantity INTEGER NOT NULL, -- Counted quantity in base units
    system_quantity INTEGER NOT NULL, -- System quantity at time of count (base units)
    variance INTEGER NOT NULL, -- counted_quantity - system_quantity
    notes TEXT,
    counted_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, item_id, counted_by) -- One count per item per counter per session
);

COMMENT ON TABLE stock_take_counts IS 'Individual counts entered by counters. Multiple counters can count same item.';
COMMENT ON COLUMN stock_take_counts.counted_quantity IS 'Quantity counted by user (in base units)';
COMMENT ON COLUMN stock_take_counts.system_quantity IS 'System stock at time of count (in base units)';
COMMENT ON COLUMN stock_take_counts.variance IS 'Difference: counted_quantity - system_quantity';

-- Stock Take Counter Locks Table (prevents duplicate counting)
CREATE TABLE IF NOT EXISTS stock_take_counter_locks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES stock_take_sessions(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    counter_id UUID NOT NULL REFERENCES users(id),
    locked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at TIMESTAMPTZ NOT NULL DEFAULT NOW() + INTERVAL '5 minutes',
    UNIQUE(session_id, item_id) -- One counter per item at a time
);

COMMENT ON TABLE stock_take_counter_locks IS 'Locks items during counting to prevent duplicate counting. Auto-expires after 5 minutes.';

-- Stock Take Adjustments Table (final adjustments after session completion)
CREATE TABLE IF NOT EXISTS stock_take_adjustments (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    session_id UUID NOT NULL REFERENCES stock_take_sessions(id) ON DELETE CASCADE,
    item_id UUID NOT NULL REFERENCES items(id) ON DELETE CASCADE,
    adjustment_quantity INTEGER NOT NULL, -- Final adjustment (can be positive or negative, base units)
    reason TEXT,
    approved_by UUID REFERENCES users(id),
    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(session_id, item_id) -- One adjustment per item per session
);

COMMENT ON TABLE stock_take_adjustments IS 'Final adjustments applied to inventory after stock take completion.';

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_stock_take_sessions_branch ON stock_take_sessions(branch_id);
CREATE INDEX IF NOT EXISTS idx_stock_take_sessions_status ON stock_take_sessions(status);
CREATE INDEX IF NOT EXISTS idx_stock_take_sessions_code ON stock_take_sessions(session_code);
CREATE INDEX IF NOT EXISTS idx_stock_take_counts_session ON stock_take_counts(session_id);
CREATE INDEX IF NOT EXISTS idx_stock_take_counts_item ON stock_take_counts(item_id);
CREATE INDEX IF NOT EXISTS idx_stock_take_counts_counter ON stock_take_counts(counted_by);
CREATE INDEX IF NOT EXISTS idx_stock_take_locks_session_item ON stock_take_counter_locks(session_id, item_id);
CREATE INDEX IF NOT EXISTS idx_stock_take_locks_expires ON stock_take_counter_locks(expires_at);
CREATE INDEX IF NOT EXISTS idx_stock_take_adjustments_session ON stock_take_adjustments(session_id);

-- Function to generate session code (e.g., ST-MAR25A)
CREATE OR REPLACE FUNCTION generate_stock_take_session_code()
RETURNS VARCHAR(10) AS $$
DECLARE
    v_date_prefix VARCHAR(6);
    v_suffix CHAR(1);
    v_code VARCHAR(10);
    v_exists BOOLEAN;
    v_suffix_num INTEGER := 0;
BEGIN
    -- Format: ST-{MON}{DAY}{SUFFIX}
    -- e.g., ST-MAR25A, ST-MAR25B, etc.
    v_date_prefix := 'ST-' || UPPER(TO_CHAR(CURRENT_DATE, 'MON')) || TO_CHAR(CURRENT_DATE, 'DD');
    
    -- Try A, B, C, etc. until we find a unique code
    LOOP
        v_suffix := CHR(65 + (v_suffix_num % 26)); -- A-Z
        v_code := v_date_prefix || v_suffix;
        
        -- Check if code exists
        SELECT EXISTS(SELECT 1 FROM stock_take_sessions WHERE session_code = v_code) INTO v_exists;
        
        IF NOT v_exists THEN
            RETURN v_code;
        END IF;
        
        v_suffix_num := v_suffix_num + 1;
        
        -- Safety: prevent infinite loop (max 26 codes per day)
        IF v_suffix_num >= 26 THEN
            -- Fallback: use timestamp
            v_code := 'ST-' || TO_CHAR(CURRENT_TIMESTAMP, 'MMDDHH24MI');
            RETURN v_code;
        END IF;
    END LOOP;
END;
$$ LANGUAGE plpgsql;

-- Function to clean up expired locks
CREATE OR REPLACE FUNCTION cleanup_expired_stock_take_locks()
RETURNS INTEGER AS $$
DECLARE
    v_deleted_count INTEGER;
BEGIN
    DELETE FROM stock_take_counter_locks
    WHERE expires_at < NOW();
    
    GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
    RETURN v_deleted_count;
END;
$$ LANGUAGE plpgsql;

-- Trigger to update updated_at timestamp
CREATE OR REPLACE FUNCTION update_stock_take_sessions_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_stock_take_sessions_updated_at
    BEFORE UPDATE ON stock_take_sessions
    FOR EACH ROW
    EXECUTE FUNCTION update_stock_take_sessions_updated_at();

-- Add stock take roles to user_roles if they don't exist
INSERT INTO user_roles (role_name, description) VALUES
    ('admin', 'Can start, pause, complete, cancel sessions. Has all rights. Can review variances.'),
    ('counter', 'Can only count items in assigned sessions.'),
    ('auditor', 'Can start sessions and review all counts.')
ON CONFLICT (role_name) DO UPDATE SET
    description = EXCLUDED.description
WHERE user_roles.description IS NULL OR user_roles.description = '';

-- Note: 'admin' role already exists, so this will update its description if needed
-- 'counter' and 'auditor' are new roles
