"""Test-only SQL catalog fixture (not used in production)."""
from __future__ import annotations

from sql_catalog import JoinEdge, SqlCatalog


def golden_dupont_catalog() -> SqlCatalog:
    tables = {
        ("dupoint_email_data", "orders"): {
            "OrderID",
            "Order_Date",
            "Total_Amount",
            "Product_Name",
            "Customer_ID",
        },
        ("dbo", "customers"): {"customer_id", "customer_name", "email"},
        ("dbo", "orders"): {
            "order_id",
            "customer_id",
            "total_amount",
            "order_date",
        },
        ("dbo", "amh_data"): {"document_type", "fine_amount"},
        ("dbo", "dupoint_email_data.orders"): {"OrderID", "Total_Amount"},
    }
    display = {
        ("dupoint_email_data", "orders"): ("dupoint_email_data", "Orders"),
        ("dbo", "dupoint_email_data.orders"): ("dbo", "dupoint_email_data.orders"),
        ("dbo", "orders"): ("dbo", "orders"),
        ("dbo", "customers"): ("dbo", "customers"),
        ("dbo", "amh_data"): ("dbo", "AMH_Data"),
    }
    return SqlCatalog(tables=tables, display_names=display, join_edges=[])


def golden_catalog() -> SqlCatalog:
    """Canonical test catalog (import only from tests/)."""
    return golden_dupont_catalog()