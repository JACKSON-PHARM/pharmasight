"""Customer-linked invoice header rules."""
from unittest.mock import MagicMock, patch
from uuid import uuid4

from app.services.customer_sales_service import apply_customer_to_invoice


def test_apply_customer_keeps_retail_sales_type_on_retail_counter_branch():
    db = MagicMock()
    invoice = MagicMock()
    invoice.branch_id = uuid4()
    invoice.company_id = uuid4()
    invoice.sales_type = "RETAIL"

    customer = MagicMock()
    customer.id = uuid4()
    customer.name = "Legacy Account"
    customer.pin = None
    customer.phone = "0700000000"
    customer.default_sales_type = "WHOLESALE"
    customer.is_active = True

    db.query.return_value.filter.return_value.first.return_value = customer

    with patch(
        "app.services.customer_sales_service.is_wholesale_distribution_branch",
        return_value=False,
    ), patch(
        "app.services.customer_sales_service.default_sales_type_for_branch",
        return_value="RETAIL",
    ):
        apply_customer_to_invoice(db, invoice, customer.id, invoice.company_id)

    assert invoice.sales_type == "RETAIL"
    assert invoice.customer_name == "Legacy Account"
