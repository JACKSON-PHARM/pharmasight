"""
Script to create quotation tables in the database
Run this once to add the new quotation tables
"""
from app.database import engine, Base
from app.models import Quotation, QuotationItem

def create_quotation_tables():
    """Create quotation tables"""
    print("Creating quotation tables...")
    try:
        # Create only quotation tables
        Quotation.__table__.create(engine, checkfirst=True)
        QuotationItem.__table__.create(engine, checkfirst=True)
        print("✅ Quotation tables created successfully!")
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        raise

if __name__ == "__main__":
    create_quotation_tables()
