from __future__ import annotations

import pytest

from sql_catalog import CatalogUnavailableError, SqlCatalog, _apply_shadow_metadata, get_catalog
from tests.fixtures.catalog_golden import golden_catalog


def test_get_catalog_is_live_only():
    with pytest.raises(Exception):
        get_catalog(live=False)  # type: ignore[call-arg]


def test_golden_catalog_fixture():
    cat = golden_catalog()
    assert cat.tables


def test_shadow_dbo_dot_name_maps_to_real_schema():
    cat = SqlCatalog(
        tables={
            ("dbo", "email.orders"): {"Total_Amount", "OrderID"},
            ("email", "orders"): {"Total_Amount", "OrderID", "Product_Name"},
        },
        display_names={
            ("dbo", "email.orders"): ("dbo", "email.orders"),
            ("email", "orders"): ("email", "orders"),
        },
    )
    _apply_shadow_metadata(cat)
    assert cat.is_shadow_table("dbo", "email.orders")
    assert cat.resolve_table_key("dbo", "email.orders") == ("email", "orders")


def test_load_live_raises_without_cache(monkeypatch):
    import sql_catalog as sc

    sc._catalog_cache = None
    import metadata

    monkeypatch.setattr(metadata, "fetch_dataframe_readonly", lambda _sql: (_ for _ in ()).throw(RuntimeError("db down")))
    with pytest.raises(CatalogUnavailableError):
        sc.load_live_catalog(force=True)