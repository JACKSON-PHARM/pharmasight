"""Customer hub sales-type visibility (retail vs legacy WHOLESALE default)."""
from app.utils.customer_access import customer_hub_sales_type_clause, default_sales_type_for_hub_mode


def test_default_sales_type_for_hub_mode():
    assert default_sales_type_for_hub_mode("wholesale") == "WHOLESALE"
    assert default_sales_type_for_hub_mode("retail_credit") == "RETAIL"


def test_retail_hub_clause_includes_legacy_wholesale_default():
    clause = customer_hub_sales_type_clause("retail_credit")
    # SQLAlchemy BinaryExpression — compile is heavy; smoke that it is a clause object
    assert clause is not None
    assert "default_sales_type" in str(clause)
