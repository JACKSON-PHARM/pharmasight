"""
Fix triggers that failed during setup
Run this after setup_master_database.py to create the triggers
"""
import sys
from pathlib import Path

backend_dir = Path(__file__).parent
sys.path.insert(0, str(backend_dir))

from sqlalchemy import text
from app.database_master import master_engine

def fix_triggers():
    """Create the trigger function and triggers"""
    print("Creating trigger function and triggers...")
    
    # The function must be executed as a single statement
    function_sql = """
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';
"""
    
    triggers_sql = """
CREATE TRIGGER update_tenants_updated_at BEFORE UPDATE ON tenants
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_subscription_plans_updated_at BEFORE UPDATE ON subscription_plans
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tenant_subscriptions_updated_at BEFORE UPDATE ON tenant_subscriptions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_tenant_modules_updated_at BEFORE UPDATE ON tenant_modules
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
"""
    
    try:
        with master_engine.connect() as conn:
            # Execute function as single statement
            conn.execute(text(function_sql))
            conn.commit()
            print("✓ Trigger function created")
            
            # Execute triggers (they can fail if already exist, that's OK)
            for trigger in triggers_sql.strip().split(';'):
                trigger = trigger.strip()
                if trigger:
                    try:
                        conn.execute(text(trigger))
                        conn.commit()
                    except Exception as e:
                        if "already exists" not in str(e).lower():
                            print(f"Warning creating trigger: {e}")
            
            print("✓ Triggers created successfully!")
            return True
    
    except Exception as e:
        print(f"ERROR: Failed to create triggers: {e}")
        return False


if __name__ == "__main__":
    success = fix_triggers()
    sys.exit(0 if success else 1)
