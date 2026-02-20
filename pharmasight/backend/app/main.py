"""
PharmaSight - Main FastAPI Application
"""
import logging
from pathlib import Path

from fastapi import FastAPI, Request

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
async def public_config(request: Request):
    """Public config for frontend (e.g. app URL for invite links, API base URL). No secrets."""
    from app.services.email_service import EmailService
    # When frontend is served from same origin as API, empty string = use same origin for API calls
    api_base_url = getattr(settings, "BACKEND_PUBLIC_URL", None) or ""
    if not api_base_url:
        try:
            api_base_url = str(request.base_url).rstrip("/")
        except Exception:
            pass
    return {
        "app_public_url": settings.APP_PUBLIC_URL.rstrip("/"),
        "smtp_configured": EmailService.is_configured(),
        "api_base_url": api_base_url,
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
    if smtp_ok:
        print("  [SMTP] Password reset emails: configured (SMTP_HOST/SMTP_USER/SMTP_PASSWORD set on this service)")
    else:
        print("  [SMTP] Password reset emails: NOT configured. Set SMTP_HOST, SMTP_USER, SMTP_PASSWORD on this Render service (the one running the API).")
        logger.warning(
            "Password reset emails will not be sent until SMTP_HOST, SMTP_USER, and SMTP_PASSWORD are set on the backend service. Restart after changing env."
        )


@app.on_event("startup")
def run_tenant_migrations():
    """Apply missing migrations on default/master app DB and on all tenant DBs. Runs every restart to reach latest version."""
    try:
        from app.services.migration_service import MigrationService, run_migrations_for_url

        print("")
        print("========================================")
        print("  MIGRATIONS: Starting (run on every restart to latest version)")
        print("========================================")

        default_url = settings.database_connection_string
        if not default_url:
            print("  [Migrations] SKIP: DATABASE_URL not set. App tables will not exist.")
            logger.warning("DATABASE_URL not set; skipping startup migrations. App tables will not exist.")
        else:
            # Show which DB we're targeting (verify this matches your Supabase project in the dashboard)
            try:
                from urllib.parse import urlparse
                p = urlparse(default_url)
                db_target = f"{p.hostname or '?'} / {(p.path or '/').strip('/') or 'postgres'}"
            except Exception:
                db_target = "(connection string set)"
            print(f"  [Migrations] Target DB: {db_target}")
            print("  [Migrations] Default/master DB...")
            try:
                ran_default = run_migrations_for_url(default_url)
                if ran_default:
                    print(f"  [Migrations] Default DB: applied {len(ran_default)} migration(s) -> {', '.join(ran_default)}")
                    logger.info("Startup migrations applied on default/master DB: %s", ran_default)
                else:
                    print("  [Migrations] Default DB: already at latest version.")
                    print("  [Migrations] (If you don't see app tables in Supabase, check you're in the project above: Dashboard -> Table Editor -> public schema)")
                    logger.info("Default/master DB already up to date (no new migrations applied).")
            except Exception as e:
                print(f"  [Migrations] Default DB: FAILED - {e}")
                logger.error(
                    "Startup migrations on default/master DB FAILED: %s. App tables (companies, users, branches, etc.) may be missing. Fix: ensure database/migrations is deployed and DB is reachable.",
                    e,
                    exc_info=True,
                )

        print("  [Migrations] Tenant DBs...")
        svc = MigrationService()
        out = svc.run_migrations_all_tenant_dbs()
        if out["applied"]:
            for tid, versions in out["applied"].items():
                print(f"  [Migrations] Tenant {tid}: applied {len(versions)} migration(s)")
            logger.info("Startup migrations applied on tenant DBs: %s", out["applied"])
        else:
            print("  [Migrations] No tenant DBs to migrate (or already up to date).")
        if out["errors"]:
            for tid, err in out["errors"].items():
                print(f"  [Migrations] Tenant {tid}: ERROR - {err}")
            logger.warning(
                "Startup migration errors on tenant DBs: %s (To skip a deleted tenant, run: python scripts/mark_tenant_cancelled.py <tenant_id_or_name>)",
                out["errors"],
            )

        print("  MIGRATIONS: Complete.")
        print("========================================")
        print("")
    except Exception as e:
        print(f"  [Migrations] FATAL: {e}")
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

