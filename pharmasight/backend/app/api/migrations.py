"""
Migration Management API - Admin endpoints for managing database migrations
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import Optional, List

from app.database_master import get_master_db
from app.services.migration_service import MigrationService

router = APIRouter()


class MigrationRequest(BaseModel):
    """Request to run a migration"""
    migration_sql: str
    version: str
    tenant_ids: Optional[List[str]] = None  # If None, migrate all tenants


class MigrationResponse(BaseModel):
    """Migration execution result"""
    total: int
    success: int
    failed: int
    skipped: int
    results: List[dict]


@router.post("/admin/migrations/run", response_model=MigrationResponse)
def run_migration(
    request: MigrationRequest,
    db: Session = Depends(get_master_db)
):
    """
    Run a migration on all tenants (or specified tenants)
    
    WARNING: This will modify all tenant databases. Use with caution!
    """
    service = MigrationService()
    
    result = service.run_migration_for_all_tenants(
        migration_sql=request.migration_sql,
        version=request.version,
        tenant_ids=request.tenant_ids
    )
    
    return MigrationResponse(**result)


@router.get("/admin/migrations/status")
def get_migration_status(db: Session = Depends(get_master_db)):
    """Get migration status for all tenants"""
    service = MigrationService()
    return service.get_migration_status()
