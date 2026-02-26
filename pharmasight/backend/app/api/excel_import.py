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
from typing import Optional, Dict, Any
from uuid import UUID
import pandas as pd
from io import BytesIO
from datetime import datetime, timezone
import hashlib

from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from app.dependencies import get_tenant_db, get_tenant_from_header, get_current_user, _session_factory_for_url
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
    column_mapping: Optional[Dict[str, str]] = None,
    database_url: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Process Excel import (sync or background). Updates ImportJob in DB.
    Returns final job state dict (status, processed_rows, stats, error_message, etc.)
    so sync callers can respond without re-using a possibly-dead request session.
    """
    from app.database import SessionLocal

    logger.info(f"🚀 Background task STARTED for job {job_id} - Processing {len(excel_data)} rows (tenant_db={bool(database_url)})")

    if database_url:
        db = _session_factory_for_url(database_url)()
    else:
        db = SessionLocal()

    total_rows = len(excel_data)
    out: Dict[str, Any] = {
        "status": "unknown",
        "processed_rows": 0,
        "stats": None,
        "error_message": None,
        "total_rows": total_rows,
        "completed_at": None,
    }

    try:
        job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
        if not job:
            logger.error(f"❌ Import job {job_id} not found in database")
            return out

        logger.info(f"✅ Found job {job_id}, status: {job.status}, total_rows: {job.total_rows}")

        job.status = "processing"
        job.started_at = datetime.now(timezone.utc)
        db.commit()
        logger.info(f"📊 Job {job_id} status updated to 'processing'")

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

        db.refresh(job)
        job.status = "completed"
        job.completed_at = datetime.now(timezone.utc)
        job.processed_rows = job.total_rows
        job.stats = result.get("stats", {})
        db.commit()

        out["status"] = "completed"
        out["processed_rows"] = job.total_rows
        out["stats"] = job.stats
        out["completed_at"] = job.completed_at.isoformat() if job.completed_at else None
        logger.info(f"🎉 Import job {job_id} completed successfully - {job.processed_rows}/{job.total_rows} rows processed")
        return out

    except Exception as e:
        logger.error(f"❌ Import job {job_id} failed: {str(e)}", exc_info=True)
        import traceback
        error_traceback = traceback.format_exc()
        logger.error(f"Full traceback for job {job_id}:\n{error_traceback}")
        err_msg = str(e)[:1000]
        out["status"] = "failed"
        out["error_message"] = err_msg
        out["completed_at"] = datetime.now(timezone.utc).isoformat()
        try:
            job = db.query(ImportJob).filter(ImportJob.id == job_id).first()
            if job:
                job.status = "failed"
                job.error_message = err_msg
                job.completed_at = datetime.now(timezone.utc)
                db.commit()
                logger.error(f"❌ Job {job_id} marked as failed in database")
        except Exception as db_error:
            logger.error(f"❌ Failed to update job status in database: {db_error}")
        return out
    finally:
        db.close()
        logger.info(f"🔒 Database session closed for job {job_id}")


@router.get("/expected-fields")
def get_expected_fields(current_user_and_db: tuple = Depends(get_current_user)):
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
    sync: Optional[str] = Form("0"),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    tenant=Depends(get_tenant_from_header),
):
    """
    Start Excel import. By default runs in background; use sync=1 to run in request (recommended for localhost so data is written before response).
    
    sync=1: Run import in the same request (blocking). Request may take several minutes. Returns when done with final job status/stats.
    sync=0: Start background thread, return job_id immediately; poll GET /api/excel/import/{job_id}/progress.
    
    column_mapping: optional JSON string mapping Excel header names to system field ids (Vyper-style).
    Two modes: AUTHORITATIVE (no live tx) / NON_DESTRUCTIVE (live tx exist).
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
        
        # Parse Excel — coerce NaN to None so service never sees float('nan') or np.nan
        df = pd.read_excel(BytesIO(contents))
        raw = df.to_dict('records')
        excel_data = [
            {k: (None if pd.isna(v) else v) for k, v in row.items()}
            for row in raw
        ]
        
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
        
        tenant_db_url = tenant.database_url if tenant else None
        run_sync = str(sync or "0").strip().lower() in ("1", "true", "yes")
        
        if run_sync:
            # Run import in this request (blocking). process_import_job uses its own DB session.
            # It returns the final job state so we do NOT re-query with the request's db (that
            # connection may be closed by the server after a long idle during import).
            logger.info(f"📤 Running import SYNCHRONOUSLY for job {job.id} with {len(excel_data)} rows (database={('tenant' if tenant else 'default')})")
            try:
                r = process_import_job(
                    job.id, company_id, branch_id, user_id, excel_data,
                    force_mode, mapping_dict, tenant_db_url
                )
            except Exception as sync_error:
                logger.error(f"❌ Sync import failed for job {job.id}: {sync_error}", exc_info=True)
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Import failed: {str(sync_error)}"
                ) from sync_error
            if not r:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Import job not found or did not return result.",
                )
            status_val = r.get("status", "unknown")
            return {
                "success": status_val == "completed",
                "message": "Import completed" if status_val == "completed" else (r.get("error_message") or "Import finished with errors"),
                "job_id": str(job.id),
                "total_rows": len(excel_data),
                "status": status_val,
                "processed_rows": r.get("processed_rows", 0),
                "stats": r.get("stats"),
                "error_message": r.get("error_message"),
            }
        
        # Start background task in a separate thread
        logger.info(f"📤 Starting background thread for job {job.id} with {len(excel_data)} rows (database={('tenant' if tenant else 'default')})")
        try:
            thread = threading.Thread(
                target=process_import_job,
                args=(job.id, company_id, branch_id, user_id, excel_data, force_mode, mapping_dict, tenant_db_url),
                daemon=False,
                name=f"ImportJob-{job.id}"
            )
            thread.start()
            logger.info(f"✅ Background thread started for job {job.id} (thread ID: {thread.ident}) - API returning immediately")
        except Exception as thread_error:
            logger.error(f"❌ Failed to start background thread for job {job.id}: {thread_error}", exc_info=True)
            job.status = "failed"
            job.error_message = f"Failed to start background task: {str(thread_error)}"
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to start import: {str(thread_error)}"
            ) from thread_error
        
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
def get_import_progress(
    job_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
    tenant=Depends(get_tenant_from_header),
):
    """
    Get progress of an import job.
    Returns current status, progress percentage, and statistics.
    Uses the same DB as the request (tenant or default). database_scope tells
    which DB the progress is from so the UI can warn if expecting tenant (Supabase).
    """
    try:
        row = db.execute(
            text("""
                SELECT id, company_id, branch_id, user_id, file_hash, file_name,
                       status, total_rows, processed_rows, last_batch, stats,
                       error_message, created_at, updated_at, started_at, completed_at
                FROM import_jobs WHERE id = :id
            """),
            {"id": job_id},
        ).first()
    except OperationalError as e:
        logger.warning(f"Tenant DB unreachable when fetching import progress: {e}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Cannot reach tenant database (Supabase). Check your network, "
                "Supabase status page, or try again later. Import may still be running."
            ),
        ) from e

    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Import job not found"
        )
    
    total_rows = row.total_rows or 0
    processed_rows = row.processed_rows or 0
    progress_pct = round((processed_rows / total_rows * 100), 1) if total_rows > 0 else 0.0

    # So the UI can warn when progress is from default DB but user expects Supabase
    database_scope = "tenant" if tenant else "default"

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
        "database_scope": database_scope,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        "started_at": row.started_at.isoformat() if row.started_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
    }


@router.get("/mode/{company_id}")
def get_import_mode(
    company_id: UUID,
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Get the current import mode for a company.
    If the database is unreachable (e.g. timeout to Supabase), returns a safe default
    so the frontend can still proceed with import and get a clear error from the import step if needed.

    Returns:
        - mode: 'AUTHORITATIVE' or 'NON_DESTRUCTIVE'
        - has_live_transactions: bool
        - mode_detection_failed: bool (true when DB was unreachable; frontend can show a warning)
    """
    try:
        has_live = ExcelImportService.has_live_transactions(db, company_id)
        mode = ExcelImportService.detect_import_mode(db, company_id)
        return {
            'mode': mode,
            'has_live_transactions': has_live,
            'mode_detection_failed': False,
            'message': 'AUTHORITATIVE mode allows reset. NON_DESTRUCTIVE mode preserves existing data.'
        }
    except OperationalError as e:
        logger.warning("Import mode detection failed (database unreachable): %s", e)
        return {
            'mode': 'AUTHORITATIVE',
            'has_live_transactions': False,
            'mode_detection_failed': True,
            'message': 'Could not detect mode (database connection issue). Proceeding with default. If import fails, check database connectivity.'
        }
    except Exception as e:
        logger.warning("Import mode detection failed: %s", e)
        return {
            'mode': 'AUTHORITATIVE',
            'has_live_transactions': False,
            'mode_detection_failed': True,
            'message': 'Could not detect mode. Proceeding with default.'
        }


class ClearForReimportBody(BaseModel):
    """Body for clear-for-reimport: company_id only."""

    company_id: UUID = Field(..., description="Company to clear (all data including transactions)")


@router.post("/clear-for-reimport")
def clear_for_reimport(
    body: ClearForReimportBody = Body(...),
    current_user_and_db: tuple = Depends(get_current_user),
    db: Session = Depends(get_tenant_db),
):
    """
    Clear all company data (items, inventory, sales, purchases, quotations, ledger, etc.) so you can run a fresh Excel import.

    Deletes all transactional and master data for the company; table schemas are left intact.
    Companies, branches, and users are NOT deleted.
    """
    company_id = body.company_id
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
