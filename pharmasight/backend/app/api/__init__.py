"""
API routes for PharmaSight
"""
from .items import router as items_router
from .inventory import router as inventory_router
from .sales import router as sales_router
from .purchases import router as purchases_router
from .quotations import router as quotations_router
from .stock_take import router as stock_take_router
from .order_book import router as order_book_router
from .branch_inventory import router as branch_inventory_router

__all__ = [
    "items_router",
    "inventory_router",
    "sales_router",
    "purchases_router",
    "quotations_router",
    "stock_take_router",
    "order_book_router",
    "branch_inventory_router",
]
