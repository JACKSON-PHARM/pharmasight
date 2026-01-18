"""
PharmaSight - Main FastAPI Application
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings

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


@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "name": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "status": "running",
    }


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy"}


# Import and include routers
from app.api import items_router, sales_router, purchases_router, inventory_router
from app.api.company import router as company_router
from app.api.startup import router as startup_router
from app.api.invite import router as invite_router
from app.api.users import router as users_router
from app.api.suppliers import router as suppliers_router
from app.api.excel_import import router as excel_import_router

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

