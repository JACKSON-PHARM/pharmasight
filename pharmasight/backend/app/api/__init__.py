"""
API routes for PharmaSight
"""
from .items import router as items_router
from .inventory import router as inventory_router
from .sales import router as sales_router
from .purchases import router as purchases_router

__all__ = [
    "items_router",
    "inventory_router",
    "sales_router",
    "purchases_router",
]
