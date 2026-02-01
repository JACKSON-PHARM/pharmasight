"""
Excel Import API endpoint with background job processing.
Supports Vyper-style column mapping: user maps Excel headers to system fields before import.
"""
import json
import logging
import threading
from fastapi import APIRouter, Depends, HTTPException, status, UploadFile, File, Form, Body
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session
from typing import Optional, Dict
from uuid import UUID
import pandas as pd
from io import BytesIO
from datetime import datetime, timezone
import hashlib

from sqlalchemy import text

from app.dependencies import get_tenant_db
from app.services.excel_import_service import ExcelImportService, EXPECTED_EXCEL_FIELDS
from app.services.clear_for_reimport_service import run_clear as run_clear_for_reimport
from app.models import ImportJob

logger = logging.getLogger(__name__)
router = APIRouter()


def process_import_job(
    job_id: UUID,
    company_id: UUID,
    branch_id: UUID,
    user_id: UUID,
    excel_data: list,
    force_mode: Optional[str],
    column_mapping: Optional[Dict[str, str]] = None
):
    """
    Background task to process Excel import.
    Updates ImportJob progress as it processes.
    column_mapping: optional dict Excel header -> system field id (Vyper-style).
    """
    from app.database import SessionLocal
    
    logger.info(f"🚀 Background task STARTED for job {job_id} - Processing {len(excel_data)} rows")
    
    db = SessionLocal()
    try:
        # Get job record
        job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if not job:
            logger.error(f"❌ Import job {job_id} not found in database")
            return
        
        logger.info(f"✅ Found job {job_id}, status: {job.status}, total_rows: {job.total_rows}")
        
        # Update status to processing
        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"📊 Job {job_id} status updated to 'processing'")
        
        # Import with progress tracking
        logger.info(f"🔄 Starting Excel import for job {job_id}...")
        result = ExcelImportService.import_excel_data(
            db=db,
            company_id=company_id,
            branch_id=branch_id,
            user_id=user_id,
            excel_data=excel_data,
            force_mode=force_mode,
            job_id=job_id,
            column_mapping=column_mapping
        )
        
        logger.info(f"✅ Import completed for job {job_id}, result: {result}")
        
        # Refresh job to get latest state
        db.refresh(job)
        
        # Update job with results
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.processed_rows = job.total_rows
        job.stats = result.get('stats', {})
        db.commit()
        
        logger.info(f"🎉 Import job {job_id} completed successfully - {job.processed_rows}/{job.total_rows} rows processed")
        
    except Exception as e:
        logger.error(f"❌ Import job {job_id} failed: {str(e)}", exc_info=True)
        import traceback
        error_traceback = traceback.format_exc()
        logger.error(f"Full traceback for job {job_id}:\n{error_traceback}")
        try:
            # Refresh job
            db.refresh(job) if 'job' in locals() else None
            job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_message = str(e)[:1000]  # Limit error message length
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
                logger.error(f"❌ Job {job_id} marked as failed in database")
        except Exception as db_error:
            logger.error(f"❌ Failed to update job status in database: {db_error}")
    finally:
        db.close()
        logger.info(f"🔒 Database session closed for job {job_id}")


@router.get("/expected-fields")
def get_expected_fields():
    """
    Return list of system fields that can be mapped from Excel columns (Vyper-style).
    Frontend uses this to build the "Map your columns" dropdown.
    """
    return {"fields": EXPECTED_EXCEL_FIELDS}


@router.post("/import")
async def import_excel(
    company_id: UUID = Form(...),
    branch_id: UUID = Form(...),
    user_id: UUID = Form(...),
    file: UploadFile = File(...),
    force_mode: Optional[str] = Form(None),
    column_mapping: Optional[str] = Form(None),
    db: Session = Depends(get_tenant_db)
):
    """
    Start Excel import as background job.
    Returns job_id immediately. Use GET /api/excel/import/{job_id}/progress to track progress.
    
    column_mapping: optional JSON string mapping Excel header names to system field ids (Vyper-style).
    When provided, each row is remapped before processing.
    
    Two modes:
    - AUTHORITATIVE: Delete and recreate (only if no live transactions)
    - NON_DESTRUCTIVE: Create missing data only (when live transactions exist)
    """
    try:
        # Parse column_mapping if provided
        mapping_dict: Optional[Dict[str, str]] = None
        if column_mapping and column_mapping.strip():
            try:
                mapping_dict = json.loads(column_mapping)
                if not isinstance(mapping_dict, dict):
                    mapping_dict = None
            except json.JSONDecodeError:
                mapping_dict = None

        # Read Excel file
        contents = await file.read()
        
        # Calculate file hash for duplicate detection
        file_hash = hashlib.md5(contents).hexdigest()
        logger.info(f"Importing file with hash: {file_hash[:8]}...")
        
        # Check for duplicate import in progress
        existing_job = db.query(ImportJob).filter(
            ImportJob.company_id == company_id,
            ImportJob.file_hash == file_hash,
            ImportJob.status.in_(["pending", "processing"])
        ).first()
        
        if existing_job:
            return {
                'success': False,
                'message': 'Import already in progress',
                'job_id': str(existing_job.id),
                'status': existing_job.status,
                'progress_percent': (existing_job.processed_rows / existing_job.total_rows * 100) if existing_job.total_rows > 0 else 0
            }
        
        # Parse Excel
        df = pd.read_excel(BytesIO(contents))
        excel_data = df.to_dict('records')
        
        # Create import job record
        job = ImportJob(
            company_id=company_id,
            branch_id=branch_id,
            user_id=user_id,
            file_hash=file_hash,
            file_name=file.filename,
            status="pending",
            total_rows=len(excel_data),
            processed_rows=0
        )
        db.add(job)
        db.commit()
        db.refresh(job)
        
        # Start background task in a separate thread (more reliable than FastAPI BackgroundTasks)
        logger.info(f"📤 Starting background thread for job {job.id} with {len(excel_data)} rows")
        try:
            thread = threading.Thread(
                target=process_import_job,
                args=(job.id, company_id, branch_id, user_id, excel_data, force_mode, mapping_dict),
                daemon=False,  # Don't kill thread when main process exits
                name=f"ImportJob-{job.id}"
            )
            thread.start()
            logger.info(f"✅ Background thread started for job {job.id} (thread ID: {thread.ident}) - API returning immediately")
        except Exception as thread_error:
            logger.error(f"❌ Failed to start background thread for job {job.id}: {thread_error}", exc_info=True)
            # Mark job as failed
            job.status = "failed"
            job.error_message = f"Failed to start background task: {str(thread_error)}"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start import: {str(thread_error)}"
            )
        
        return {
            'success': True,
            'message': 'Import started in background',
            'job_id': str(job.id),
            'total_rows': len(excel_data),
            'status': 'pending'
        }
        
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        logger.error(f"Excel import error: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Import failed: {str(e)}"
        )


@router.get("/import/{job_id}/progress")
def get_import_progress(job_id: UUID, db: Session = Depends(get_tenant_db)):
    """
    Get progress of an import job.
    Returns current status, progress percentage, and statistics.
    Uses a direct SQL read so we always see the latest committed progress
    from the background import thread.
    """
    # Direct SQL read to avoid any session/ORM caching and see latest committed data
    row = db.execute(
        text("""
            SELECT id, company_id, branch_id, user_id, file_hash, file_name,
                   status, total_rows, processed_rows, last_batch, stats,
                   error_message, created_at, updated_at, started_at, completed_at
            FROM import_jobs WHERE id = :id
        """),
        {"id": job_id},
    ).first()
    
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import job not found"
        )
    
    total_rows = row.total_rows or 0
    processed_rows = row.processed_rows or 0
    progress_pct = round((processed_rows / total_rows * 100), 1) if total_rows > 0 else 0.0
    
    return {
        "id": str(row.id),
        "company_id": str(row.company_id),
        "branch_id": str(row.branch_id) if row.branch_id else None,
        "user_id": str(row.user_id),
        "file_hash": row.file_hash,
        "file_name": row.file_name,
        "status": row.status,
        "total_rows": total_rows,
        "processed_rows": processed_rows,
        "last_batch": row.last_batch or 0,
        "progress_percent": progress_pct,
        "stats": row.stats,
        "error_message": row.error_message,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


@router.get("/mode/{company_id}")
def get_import_mode(company_id: UUID, db: Session = Depends(get_tenant_db)):
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


class ClearForReimportBody(BaseModel):
    """Body for clear-for-reimport: company_id only."""

    company_id: UUID = Field(..., description="Company to clear (only when no live transactions)")


@router.post("/clear-for-reimport")
def clear_for_reimport(
    body: ClearForReimportBody = Body(...),
    db: Session = Depends(get_tenant_db),
):
    """
    Clear all company data (items, inventory, sales, purchases, etc.) so you can run a fresh Excel import.

    **Only allowed when there are no live transactions** (no sales, purchases, or stock movements beyond opening balance).
    If the company has any live transactions, returns 403 and does not delete anything.

    Call this from the UI before re-importing when you want to start from a clean slate.
    """
    company_id = body.company_id
    has_live = ExcelImportService.has_live_transactions(db, company_id)
    if has_live:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Cannot clear: company has live transactions (sales, purchases, or stock movements). "
                "Clear is only allowed when there are no transactions yet. "
                "Use NON_DESTRUCTIVE import to add/update data without clearing."
            ),
        )
    success, messages = run_clear_for_reimport(company_id)
    if not success:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"message": "Clear failed", "details": messages},
        )
    return {
        "success": True,
        "message": "Company data cleared. You can now run a fresh Excel import.",
        "details": messages,
    }
