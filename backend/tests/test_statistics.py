def test_row_count_matches_data(ecommerce_adapter):
    st = ecommerce_adapter.get_statistics("orders")
    assert st.row_count == 1200
    assert st.source == "Computed from the connected database"
    assert st.collected_at


def test_distinct_and_null_fraction(ecommerce_adapter):
    st = ecommerce_adapter.get_statistics("orders")
    status = st.columns["status"]
    assert status.distinct_count >= 2
    assert 0.0 <= status.null_fraction <= 1.0


def test_skew_present_in_mcv(ecommerce_adapter):
    # status is intentionally skewed; MCV should be populated and ordered by count.
    st = ecommerce_adapter.get_statistics("orders")
    mcv = st.columns["status"].most_common
    assert len(mcv) >= 2
    counts = [c for _, c in mcv]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] > counts[-1]  # genuine skew


def test_min_max_numeric(ecommerce_adapter):
    st = ecommerce_adapter.get_statistics("products")
    price = st.columns["price"]
    assert price.min_value is not None and price.max_value is not None
    assert float(price.min_value) <= float(price.max_value)


def test_library_statistics(library_adapter):
    st = library_adapter.get_statistics("loans")
    assert st.row_count > 0
    assert "book_id" in st.columns
