"""
Excel Import API endpoint
"""
import logging
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form
from sqlalchemy.orm import Session
from typing import Optional
from uuid import UUID
import pandas as pd
from io import BytesIO

from app.database import get_db
from app.services.excel_import_service import ExcelImportService

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/import")
async def import_excel(
    company_id: UUID = Form(...),
    branch_id: UUID = Form(...),
    user_id: UUID = Form(...),
    file: UploadFile = File(...),
    force_mode: Optional[str] = Form(None),
    db: Session = Depends(get_db)
):
    """
    Import items from Excel file with inventory integrity enforcement.
    
    Two modes:
    - AUTHORITATIVE: Delete and recreate (only if no live transactions)
    - NON_DESTRUCTIVE: Create missing data only (when live transactions exist)
    
    Excel columns expected:
    - Item_Name (required)
    - Current_Stock_Quantity (required)
    - Item_Code / SKU
    - Generic_Name
    - Base_Unit
    - Price_List_Last_Cost
    - Retail_Price
    - Wholesale_Price
    - Trade_Price
    - Supplier
    - Category
    - Barcode
    """
    try:
        # Read Excel file
        contents = await file.read()
        df = pd.read_excel(BytesIO(contents))
        
        # Convert to list of dictionaries
        excel_data = df.to_dict('records')
        
        # Import using service
        result = ExcelImportService.import_excel_data(
            db=db,
            company_id=company_id,
            branch_id=branch_id,
            user_id=user_id,
            excel_data=excel_data,
            force_mode=force_mode
        )
        
        return {
            'success': True,
            'message': f'Import completed in {result["mode"]} mode',
            **result
        }
        
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Excel import error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import failed: {str(e)}"
        )


@router.get("/mode/{company_id}")
def get_import_mode(company_id: UUID, db: Session = Depends(get_db)):
    """
    Get the current import mode for a company.
    
    Returns:
        - mode: 'AUTHORITATIVE' or 'NON_DESTRUCTIVE'
        - has_live_transactions: bool
    """
    has_live = ExcelImportService.has_live_transactions(db, company_id)
    mode = ExcelImportService.detect_import_mode(db, company_id)
    
    return {
        'mode': mode,
        'has_live_transactions': has_live,
        'message': 'AUTHORITATIVE mode allows reset. NON_DESTRUCTIVE mode preserves existing data.'
    }
