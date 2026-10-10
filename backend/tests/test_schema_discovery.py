"""Schema discovery works identically on both schemas."""


def test_ecommerce_tables(ecommerce_adapter):
    tables = ecommerce_adapter.get_tables()
    assert set(tables) == {"categories", "customers", "order_items", "orders", "products"}


def test_ecommerce_columns_and_pk(ecommerce_adapter):
    ts = ecommerce_adapter.get_table_schema("orders")
    names = [c.name for c in ts.columns]
    assert "order_id" in names and "customer_id" in names
    assert ts.primary_key == ["order_id"]


def test_ecommerce_foreign_keys(ecommerce_adapter):
    fks = ecommerce_adapter.get_foreign_keys("order_items")
    ref_tables = {fk.ref_table for fk in fks}
    assert {"orders", "products"} <= ref_tables


def test_ecommerce_indexes(ecommerce_adapter):
    idx = ecommerce_adapter.get_indexes("products")
    assert any(i.columns == ["category_id"] for i in idx)


def test_library_schema_discovered(library_adapter):
    tables = library_adapter.get_tables()
    assert set(tables) == {"authors", "books", "members", "loans"}
    ts = library_adapter.get_table_schema("books")
    assert ts.primary_key == ["book_id"]
    fks = library_adapter.get_foreign_keys("loans")
    assert {"books", "members"} <= {fk.ref_table for fk in fks}
