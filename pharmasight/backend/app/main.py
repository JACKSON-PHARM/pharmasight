"""
PharmaSight - Main FastAPI Application
"""
import logging
from pathlib import Path

from fastapi import FastAPI

logger = logging.getLogger(__name__)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings

# Frontend directory (pharmasight/frontend, relative to backend/app)
_BACKEND_APP = Path(__file__).resolve().parent
_BACKEND = _BACKEND_APP.parent
_FRONTEND_DIR = _BACKEND.parent / "frontend"

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Pharmacy Management System with Inventory Intelligence",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/api/config")
async def public_config():
    """Public config for frontend (e.g. app URL for invite links). No secrets."""
    from app.services.email_service import EmailService
    return {
        "app_public_url": settings.APP_PUBLIC_URL.rstrip("/"),
        "smtp_configured": EmailService.is_configured(),
    }


@app.on_event("startup")
def log_smtp_and_migrations():
    """Log SMTP status and run migrations so we can see why reset emails might not send."""
    from app.services.email_service import EmailService
    smtp_ok = EmailService.is_configured()
    logger.info(
        "SMTP for password reset: %s (SMTP_HOST=%s, SMTP_USER=%s, SMTP_PASSWORD=%s)",
        "configured" if smtp_ok else "NOT CONFIGURED",
        "set" if settings.SMTP_HOST else "empty",
        "set" if settings.SMTP_USER else "empty",
        "set" if settings.SMTP_PASSWORD else "empty",
    )
    if not smtp_ok:
        logger.warning(
            "Password reset emails will not be sent until SMTP_HOST, SMTP_USER, and SMTP_PASSWORD are set (e.g. in pharmasight/.env). Restart the server after changing .env."
        )


@app.on_event("startup")
def run_tenant_migrations():
    """Apply missing migrations on default/master app DB and on all tenant DBs (locked architecture)."""
    try:
        from app.services.migration_service import MigrationService, run_migrations_for_url

        # 1) Run app migrations on the default/master app DB (tenant management + transactions when no tenant)
        try:
            default_url = settings.database_connection_string
            if default_url:
                ran_default = run_migrations_for_url(default_url)
                if ran_default:
                    logger.info("Startup migrations applied on default/master DB: %s", ran_default)
        except Exception as e:
            logger.warning("Startup migrations on default/master DB failed: %s", e)

        # 2) Run app migrations on each tenant DB (Supabase per tenant)
        svc = MigrationService()
        out = svc.run_migrations_all_tenant_dbs()
        if out["applied"]:
            logger.info("Startup migrations applied on tenant DBs: %s", out["applied"])
        if out["errors"]:
            logger.warning(
                "Startup migration errors on tenant DBs: %s (To skip a deleted tenant, run: python scripts/mark_tenant_cancelled.py <tenant_id_or_name>)",
                out["errors"],
            )
    except Exception as e:
        logger.exception("Startup migrations failed: %s", e)


# Import and include routers
from app.api import items_router, sales_router, purchases_router, inventory_router, quotations_router, stock_take_router, order_book_router
from app.api.company import router as company_router
from app.api.startup import router as startup_router
from app.api.invite import router as invite_router
from app.api.users import router as users_router
from app.api.suppliers import router as suppliers_router
from app.api.excel_import import router as excel_import_router
from app.api.tenants import router as tenants_router
from app.api.onboarding import router as onboarding_router
# Optional imports - app can run without these
try:
    from app.api.migrations import router as migrations_router
except ImportError:
    migrations_router = None

try:
    from app.api.stripe_webhooks import router as stripe_webhooks_router
except ImportError:
    stripe_webhooks_router = None
from app.api.admin_auth import router as admin_auth_router
from app.api.auth import router as auth_router

app.include_router(invite_router, prefix="/api", tags=["User Invitation & Setup"])
app.include_router(startup_router, prefix="/api", tags=["Startup & Initialization"])
app.include_router(company_router, prefix="/api", tags=["Company & Branch"])
app.include_router(users_router, prefix="/api", tags=["User Management"])
app.include_router(items_router, prefix="/api/items", tags=["Items"])
app.include_router(sales_router, prefix="/api/sales", tags=["Sales"])
app.include_router(purchases_router, prefix="/api/purchases", tags=["Purchases"])
app.include_router(inventory_router, prefix="/api/inventory", tags=["Inventory"])
app.include_router(suppliers_router, prefix="/api/suppliers", tags=["Suppliers"])
app.include_router(excel_import_router, prefix="/api/excel", tags=["Excel Import"])
app.include_router(quotations_router, prefix="/api/quotations", tags=["Quotations"])
app.include_router(stock_take_router, prefix="/api/stock-take", tags=["Stock Take"])
app.include_router(order_book_router, prefix="/api/order-book", tags=["Order Book"])
app.include_router(tenants_router, prefix="/api/admin", tags=["Tenant Management (Admin)"])
app.include_router(onboarding_router, prefix="/api", tags=["Client Onboarding"])
if migrations_router:
    app.include_router(migrations_router, prefix="/api", tags=["Migration Management (Admin)"])
if stripe_webhooks_router:
    app.include_router(stripe_webhooks_router, prefix="/api", tags=["Stripe Webhooks"])
app.include_router(admin_auth_router, prefix="/api", tags=["Admin Authentication"])
app.include_router(auth_router, prefix="/api", tags=["Authentication"])

# Serve frontend static files and SPA
if _FRONTEND_DIR.is_dir():
    app.mount("/css", StaticFiles(directory=str(_FRONTEND_DIR / "css")), name="css")
    
# Serve uploaded files (logos, etc.)
_UPLOADS_DIR = _BACKEND / "uploads"
if _UPLOADS_DIR.is_dir():
    app.mount("/uploads", StaticFiles(directory=str(_UPLOADS_DIR)), name="uploads")
    app.mount("/js", StaticFiles(directory=str(_FRONTEND_DIR / "js")), name="js")
    _index_path = _FRONTEND_DIR / "index.html"
    _admin_path = _FRONTEND_DIR / "admin.html"

    @app.get("/")
    async def root():
        return FileResponse(_index_path, media_type="text/html")

    @app.get("/admin.html")
    async def admin_page():
        """Serve the real admin panel page so admin login redirect lands here (not the SPA index)."""
        if _admin_path.is_file():
            return FileResponse(_admin_path, media_type="text/html")
        return FileResponse(_index_path, media_type="text/html")

    @app.get("/{full_path:path}")
    async def spa_fallback(full_path: str):
        return FileResponse(_index_path, media_type="text/html")

