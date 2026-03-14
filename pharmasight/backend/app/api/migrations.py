"""
Migration Management API - Admin endpoints for managing database migrations.

Requires PLATFORM_ADMIN authentication. In production, only predefined migrations
(referenced by version) may be run; arbitrary SQL from request body is not allowed.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List

from app.config import settings
from app.database_master import get_master_db
from app.dependencies import get_current_admin
from app.services.migration_service import (
    MigrationService,
    run_predefined_migration_by_version,
)

router = APIRouter()


class RunMigrationByVersionRequest(BaseModel):
    """Request to run a predefined migration by version (e.g. 069_items_setup_complete)."""
    version: str


class RunMigrationByVersionResponse(BaseModel):
    """Result of running a single migration by version."""
    success: bool
    message: str
    applied: bool


@router.post("/admin/migrations/run", response_model=RunMigrationByVersionResponse)
def run_migration(
    request: RunMigrationByVersionRequest,
    _admin: None = Depends(get_current_admin),
):
    """
    Run a predefined migration by version on the application database.

    Requires PLATFORM_ADMIN authentication. Only migrations stored in
    database/migrations/*.sql (referenced by version identifier) are executed.
    Arbitrary SQL from the request body is not accepted.
    """
    version = (request.version or "").strip()
    if not version:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="version is required",
        )
    database_url = settings.database_connection_string
    if not database_url:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DATABASE_URL not configured",
        )
    result = run_predefined_migration_by_version(database_url, version)
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=result["message"],
        )
    return RunMigrationByVersionResponse(
        success=result["success"],
        message=result["message"],
        applied=result["applied"],
    )


@router.get("/admin/migrations/status")
def get_migration_status(
    _admin: None = Depends(get_current_admin),
    db: Session = Depends(get_master_db),
):
    """Get migration status. Requires PLATFORM_ADMIN authentication."""
    service = MigrationService()
    return service.get_migration_status()
