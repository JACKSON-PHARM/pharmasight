"""
PharmaSight - Main FastAPI Application
"""
import logging
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse

from app.config import settings
from app.rate_limit import limiter
from slowapi.errors import RateLimitExceeded
from slowapi import _rate_limit_exceeded_handler

class RequestTimingMiddleware(BaseHTTPMiddleware):
    """Set request.state._req_start_time at entry; if route set request.state.timings, add X-Timing-* and Server-Timing response headers for Network tab."""

    # Short descriptions for Chrome DevTools Server Timing display
    _TIMING_DESCS = {
        "LoadMs": "Load document",
        "CompanyCheckMs": "Company check",
        "InsertMs": "Insert line",
        "ItemsMapMs": "Items batch",
        "CostMs": "Cost lookup",
        "BuildMs": "Build response",
        "TotalMs": "Total",
        "CommitMs": "Commit",
        "CostEnrichMs": "Cost/margin per line",
        "LedgerMs": "Batch allocations",
    }

    async def dispatch(self, request: Request, call_next):
        request.state._req_start_time = time.perf_counter()
        response = await call_next(request)
        timings = getattr(request.state, "timings", None)
        if timings and isinstance(timings, dict):
            parts = []
            for key, value in timings.items():
                try:
                    response.headers[f"X-Timing-{key}"] = str(value)
                    desc = self._TIMING_DESCS.get(key, key)
                    parts.append(f"{key};dur={value};desc=\"{desc}\"")
                except Exception:
                    pass
            if parts:
                try:
                    response.headers["Server-Timing"] = ", ".join(parts)
                except Exception:
                    pass
        return response

# Frontend directory (pharmasight/frontend, relative to backend/app)
_BACKEND_APP = Path(__file__).resolve().parent
_BACKEND = _BACKEND_APP.parent
_FRONTEND_DIR = _BACKEND.parent / "frontend"
_MARKETING_DIR = _BACKEND.parent / "marketing"

# Create FastAPI app
app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    description="Pharmacy Management System with Inventory Intelligence",
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
)
# Attach slowapi limiter to FastAPI (no init_app; use state + exception handler)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware — explicit origins plus (in non-production) any localhost / 127.0.0.1 port so
# dev frontends on dynamic ports (start.py) match Origin and OPTIONS preflight succeeds.
_cors_kw = dict(
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Server-Timing", "X-Search-Path", "X-Timing-LoadMs", "X-Timing-CompanyCheckMs", "X-Timing-InsertMs", "X-Timing-ItemsMapMs", "X-Timing-CostMs", "X-Timing-BuildMs", "X-Timing-TotalMs"],
)
if getattr(settings, "ENVIRONMENT", "development") != "production":
    _cors_kw["allow_origin_regex"] = r"https?://(localhost|127\.0\.0\.1)(:\d+)?"
app.add_middleware(CORSMiddleware, **_cors_kw)
app.add_middleware(RequestTimingMiddleware)


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


@app.get("/api/debug/tenants")
async def debug_tenants_count():
    """When DEBUG=true and not production: returns count of tenants with database_url. Disabled in production."""
    if getattr(settings, "ENVIRONMENT", "development") == "production":
        raise HTTPException(status_code=404, detail="Not found")
    if not settings.DEBUG:
        return {"error": "Enable DEBUG in .env to use this endpoint."}
    try:
        from app.services.migration_service import MigrationService
        svc = MigrationService()
        tenants = svc.get_all_tenants_with_db()
        return {
            "tenants_with_db": len(tenants),
            "subdomains": [t.subdomain for t in tenants],
            "master_ok": True,
        }
    except Exception as e:
        logger.exception("Debug tenants: %s", e)
        return {"master_ok": False, "error": str(e)}


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
                # Master public.tenants must match Tenant ORM before MigrationService queries it (schema drift guard).
                from app.services.migration_service import ensure_master_tenant_storage_columns
                ensure_master_tenant_storage_columns(default_url)
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
        try:
            svc = MigrationService()
            tenants_with_db = svc.get_all_tenants_with_db()
            subdomains = [t.subdomain for t in tenants_with_db]
            print(f"  [Migrations] Found {len(tenants_with_db)} tenant(s) with database_url: {subdomains or '(none)'}")
            if not tenants_with_db:
                print("  [Migrations] Tip: In master DB (public.tenants), ensure each row has database_url set (e.g. session pooler URL).")
            out = svc.run_migrations_all_tenant_dbs()
            if out["applied"]:
                for tid, versions in out["applied"].items():
                    print(f"  [Migrations] Tenant {tid}: applied {len(versions)} migration(s)")
                logger.info("Startup migrations applied on tenant DBs: %s", out["applied"])
            elif tenants_with_db:
                print("  [Migrations] All tenant DBs already at latest version.")
            else:
                print("  [Migrations] No tenant DBs to migrate (or already up to date).")
            if out["errors"]:
                for tid, err in out["errors"].items():
                    print(f"  [Migrations] Tenant {tid}: ERROR - {err}")
                logger.warning(
                    "Startup migration errors on tenant DBs: %s (To skip a deleted tenant, run: python scripts/mark_tenant_cancelled.py <tenant_id_or_name>)",
                    out["errors"],
                )
        except Exception as e:
            print(f"  [Migrations] Tenant DBs: SKIP - {e}")
            logger.warning(
                "Could not run tenant DB migrations (master DB unreachable?). App will start; API may fail until DB is reachable. Error: %s",
                e,
            )

        print("  MIGRATIONS: Complete.")
        print("========================================")
        print("")
    except Exception as e:
        print(f"  [Migrations] FATAL: {e}")
        logger.exception("Startup migrations failed: %s", e)
        # Do not re-raise: allow app to start so health/docs work; API will fail until DB is reachable


# Import and include routers
from app.api import (
    items_router,
    sales_router,
    purchases_router,
    inventory_router,
    quotations_router,
    stock_take_router,
    order_book_router,
    branch_inventory_router,
    modules_router,
    clinic_router,
)
from app.api import etims
from app.api.company import router as company_router
from app.api.startup import router as startup_router
from app.api.invite import router as invite_router
from app.api.users import router as users_router
from app.api.suppliers import router as suppliers_router
from app.api.supplier_management import router as supplier_management_router
from app.api.expenses import router as expenses_router
from app.api.cashbook import router as cashbook_router
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
from app.api.public_marketing import router as public_marketing_router
from app.api.company_billing import router as company_billing_router
from app.api.reports import router as reports_router
from app.api.impersonation import router as impersonation_router
from app.api.admin_metrics import router as admin_metrics_router
from app.api.admin_platform_licensing import router as admin_platform_licensing_router
from app.api.platform_admin import router as platform_admin_router

app.include_router(invite_router, prefix="/api", tags=["User Invitation & Setup"])
app.include_router(startup_router, prefix="/api", tags=["Startup & Initialization"])
app.include_router(company_router, prefix="/api", tags=["Company & Branch"])
app.include_router(users_router, prefix="/api", tags=["User Management"])
app.include_router(items_router, prefix="/api/items", tags=["Items"])
app.include_router(sales_router, prefix="/api/sales", tags=["Sales"])
app.include_router(purchases_router, prefix="/api/purchases", tags=["Purchases"])
app.include_router(inventory_router, prefix="/api/inventory", tags=["Inventory"])
# Expenses (OPEX)
app.include_router(expenses_router, prefix="/api/expenses", tags=["Expenses"])
# Cashbook (money movement tracking; sourced from expenses + supplier payments)
app.include_router(cashbook_router, prefix="/api", tags=["Cashbook"])
# Supplier management (payments, returns, etc.) must come before suppliers_router so /payments matches before /{supplier_id}
app.include_router(supplier_management_router, prefix="/api/suppliers", tags=["Supplier Management"])
app.include_router(suppliers_router, prefix="/api/suppliers", tags=["Suppliers"])
app.include_router(excel_import_router, prefix="/api/excel", tags=["Excel Import"])
app.include_router(quotations_router, prefix="/api/quotations", tags=["Quotations"])
app.include_router(stock_take_router, prefix="/api/stock-take", tags=["Stock Take"])
app.include_router(order_book_router, prefix="/api/order-book", tags=["Order Book"])
app.include_router(branch_inventory_router, prefix="/api/branch-inventory", tags=["Branch Inventory"])
app.include_router(modules_router, prefix="/api", tags=["Modules"])
app.include_router(clinic_router, prefix="/api", tags=["Clinic / OPD"])
app.include_router(etims.router, prefix="/api/etims", tags=["ETIMS"])
app.include_router(reports_router, prefix="/api", tags=["Reports"])
app.include_router(tenants_router, prefix="/api/admin", tags=["Tenant Management (Admin)"])
app.include_router(impersonation_router, prefix="/api/admin", tags=["Admin Impersonation"])
app.include_router(admin_metrics_router, prefix="/api/admin", tags=["Platform Admin Dashboard"])
app.include_router(admin_platform_licensing_router, prefix="/api/admin", tags=["Platform Licensing (Admin)"])
app.include_router(platform_admin_router, prefix="/api", tags=["Platform Admin (RBAC)"])
app.include_router(onboarding_router, prefix="/api", tags=["Client Onboarding"])
if migrations_router:
    app.include_router(migrations_router, prefix="/api", tags=["Migration Management (Admin)"])
if stripe_webhooks_router:
    app.include_router(stripe_webhooks_router, prefix="/api", tags=["Stripe Webhooks"])
app.include_router(admin_auth_router, prefix="/api", tags=["Admin Authentication"])
app.include_router(public_marketing_router, prefix="/api", tags=["Public marketing"])
app.include_router(company_billing_router, prefix="/api", tags=["Billing"])
app.include_router(auth_router, prefix="/api", tags=["Authentication"])

# Serve frontend static files (must NOT depend on backend/uploads — Render often has no uploads dir on first deploy).
if _FRONTEND_DIR.is_dir():
    app.mount("/css", StaticFiles(directory=str(_FRONTEND_DIR / "css")), name="css")
    app.mount("/js", StaticFiles(directory=str(_FRONTEND_DIR / "js")), name="js")

# Uploaded files (logos, etc.) — register before SPA catch-all so /uploads/* is not served as index.html
_UPLOADS_DIR = _BACKEND / "uploads"
if _UPLOADS_DIR.is_dir():
    app.mount("/uploads", StaticFiles(directory=str(_UPLOADS_DIR)), name="uploads")

if _FRONTEND_DIR.is_dir():
    _index_path = _FRONTEND_DIR / "index.html"
    _admin_path = _FRONTEND_DIR / "admin.html"

    if _MARKETING_DIR.is_dir():
        @app.get("/marketing")
        async def marketing_redirect():
            return RedirectResponse(url="/marketing/", status_code=302)

        app.mount(
            "/marketing",
            StaticFiles(directory=str(_MARKETING_DIR), html=True),
            name="marketing",
        )

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

