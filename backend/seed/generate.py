"""Programmatic, deterministic demo-data generator.

Creates a 5-table e-commerce schema and fills it with algorithmically generated
rows that contain realistic *skew* (power-law popularity, uneven category sizes,
common/rare status values). No statistics are hardcoded — the optimizer computes
them from whatever this generator produces.

The e-commerce schema is ONLY a demonstration dataset. The optimizer never refers
to these table or column names.

Usage:
    python -m seed.generate                 # uses .env config
    python -m seed.generate --db other.db --customers 500 --orders 1500
    python -m seed.generate --schema library  # a totally unrelated schema
"""
from __future__ import annotations

import argparse
import random
import sqlite3
from datetime import date, timedelta

# Allow running both as `python -m seed.generate` and `python seed/generate.py`.
try:
    from app.config import get_settings
except Exception:  # pragma: no cover
    get_settings = None  # type: ignore


ECOMMERCE_DDL = """
DROP TABLE IF EXISTS order_items;
DROP TABLE IF EXISTS orders;
DROP TABLE IF EXISTS products;
DROP TABLE IF EXISTS categories;
DROP TABLE IF EXISTS customers;

CREATE TABLE categories (
    category_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    parent_id   INTEGER REFERENCES categories(category_id)
);

CREATE TABLE customers (
    customer_id INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    email       TEXT NOT NULL,
    city        TEXT,
    country     TEXT,
    created_at  TEXT NOT NULL
);

CREATE TABLE products (
    product_id  INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    category_id INTEGER NOT NULL REFERENCES categories(category_id),
    price       REAL NOT NULL,
    stock       INTEGER NOT NULL
);

CREATE TABLE orders (
    order_id    INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers(customer_id),
    status      TEXT NOT NULL,
    order_date  TEXT NOT NULL,
    total       REAL NOT NULL
);

CREATE TABLE order_items (
    order_item_id INTEGER PRIMARY KEY,
    order_id      INTEGER NOT NULL REFERENCES orders(order_id),
    product_id    INTEGER NOT NULL REFERENCES products(product_id),
    quantity      INTEGER NOT NULL,
    unit_price    REAL NOT NULL
);

-- Intentionally index only SOME foreign keys, so the index advisor has
-- realistic recommendations to make (e.g. orders.customer_id is left unindexed).
CREATE INDEX idx_products_category ON products(category_id);
CREATE INDEX idx_order_items_order ON order_items(order_id);
CREATE UNIQUE INDEX idx_customers_email ON customers(email);
"""


CITIES = [
    ("New York", "USA"), ("London", "UK"), ("Mumbai", "India"),
    ("Tokyo", "Japan"), ("Berlin", "Germany"), ("Sydney", "Australia"),
    ("Toronto", "Canada"), ("Paris", "France"), ("Sao Paulo", "Brazil"),
    ("Singapore", "Singapore"),
]
STATUSES = [
    ("completed", 60), ("shipped", 20), ("pending", 12),
    ("cancelled", 6), ("refunded", 2),
]
CATEGORY_NAMES = [
    "Electronics", "Books", "Home & Kitchen", "Clothing", "Sports",
    "Toys", "Beauty", "Automotive", "Garden", "Office",
]


def _zipf_weights(n: int, s: float = 1.15) -> list[float]:
    """Zipf-like weights so lower indices are much more popular (skew)."""
    return [1.0 / ((i + 1) ** s) for i in range(n)]


def _weighted_choice(rng: random.Random, weights: list[float]) -> int:
    total = sum(weights)
    r = rng.random() * total
    upto = 0.0
    for i, w in enumerate(weights):
        upto += w
        if r <= upto:
            return i
    return len(weights) - 1


def seed_ecommerce(
    conn: sqlite3.Connection,
    seed: int,
    customer_count: int,
    order_count: int,
    product_count: int,
) -> dict:
    rng = random.Random(seed)
    conn.executescript(ECOMMERCE_DDL)

    # --- categories (uneven sizes come later via product assignment) --------
    category_count = min(len(CATEGORY_NAMES), max(3, product_count // 40 + 3))
    categories = []
    for i in range(category_count):
        parent = None
        if i > 2 and rng.random() < 0.3:
            parent = rng.randint(1, 3)  # a few sub-categories
        categories.append((i + 1, CATEGORY_NAMES[i], parent))
    conn.executemany(
        "INSERT INTO categories(category_id, name, parent_id) VALUES (?,?,?)",
        categories,
    )

    # --- customers ----------------------------------------------------------
    base_day = date(2023, 1, 1)
    customers = []
    for cid in range(1, customer_count + 1):
        city, country = rng.choice(CITIES)
        created = base_day + timedelta(days=rng.randint(0, 900))
        customers.append(
            (
                cid,
                f"Customer {cid}",
                f"user{cid}@example.com",
                city,
                country,
                created.isoformat(),
            )
        )
    conn.executemany(
        "INSERT INTO customers(customer_id, name, email, city, country, created_at) "
        "VALUES (?,?,?,?,?,?)",
        customers,
    )

    # --- products (category popularity is skewed) ---------------------------
    cat_weights = _zipf_weights(category_count, s=0.9)
    products = []
    for pid in range(1, product_count + 1):
        cat = _weighted_choice(rng, cat_weights) + 1
        price = round(rng.uniform(3, 900) * (1 + rng.random()), 2)
        stock = rng.randint(0, 500)
        products.append((pid, f"Product {pid}", cat, price, stock))
    conn.executemany(
        "INSERT INTO products(product_id, name, category_id, price, stock) "
        "VALUES (?,?,?,?,?)",
        products,
    )

    # --- orders (customer activity is power-law skewed) ---------------------
    cust_weights = _zipf_weights(customer_count, s=1.2)
    status_pop = [w for _, w in STATUSES]
    orders = []
    for oid in range(1, order_count + 1):
        cust = _weighted_choice(rng, cust_weights) + 1
        status = STATUSES[_weighted_choice(rng, status_pop)][0]
        odate = base_day + timedelta(days=rng.randint(0, 900))
        orders.append((oid, cust, status, odate.isoformat(), 0.0))
    conn.executemany(
        "INSERT INTO orders(order_id, customer_id, status, order_date, total) "
        "VALUES (?,?,?,?,?)",
        orders,
    )

    # --- order_items (product popularity is power-law skewed) ---------------
    prod_weights = _zipf_weights(product_count, s=1.1)
    price_by_pid = {p[0]: p[3] for p in products}
    order_totals: dict[int, float] = {}
    items = []
    item_id = 0
    for oid in range(1, order_count + 1):
        n_items = 1 + _weighted_choice(rng, _zipf_weights(5, s=0.8))
        for _ in range(n_items):
            item_id += 1
            pid = _weighted_choice(rng, prod_weights) + 1
            qty = rng.randint(1, 6)
            unit = price_by_pid[pid]
            items.append((item_id, oid, pid, qty, unit))
            order_totals[oid] = order_totals.get(oid, 0.0) + qty * unit
    conn.executemany(
        "INSERT INTO order_items(order_item_id, order_id, product_id, quantity, unit_price) "
        "VALUES (?,?,?,?,?)",
        items,
    )

    # backfill order totals
    conn.executemany(
        "UPDATE orders SET total = ? WHERE order_id = ?",
        [(round(t, 2), oid) for oid, t in order_totals.items()],
    )
    conn.commit()

    return {
        "categories": category_count,
        "customers": customer_count,
        "products": product_count,
        "orders": order_count,
        "order_items": item_id,
    }


# ---------------------------------------------------------------------------
# A second, unrelated schema — used by tests to prove the optimizer is NOT
# hardcoded to e-commerce. It works exactly the same way.
# ---------------------------------------------------------------------------
LIBRARY_DDL = """
DROP TABLE IF EXISTS loans;
DROP TABLE IF EXISTS books;
DROP TABLE IF EXISTS authors;
DROP TABLE IF EXISTS members;

CREATE TABLE authors (
    author_id INTEGER PRIMARY KEY,
    name      TEXT NOT NULL,
    country   TEXT
);
CREATE TABLE books (
    book_id   INTEGER PRIMARY KEY,
    title     TEXT NOT NULL,
    author_id INTEGER NOT NULL REFERENCES authors(author_id),
    year      INTEGER,
    genre     TEXT
);
CREATE TABLE members (
    member_id  INTEGER PRIMARY KEY,
    full_name  TEXT NOT NULL,
    joined_on  TEXT
);
CREATE TABLE loans (
    loan_id    INTEGER PRIMARY KEY,
    book_id    INTEGER NOT NULL REFERENCES books(book_id),
    member_id  INTEGER NOT NULL REFERENCES members(member_id),
    loan_date  TEXT NOT NULL,
    returned   INTEGER NOT NULL
);
CREATE INDEX idx_books_author ON books(author_id);
"""

GENRES = ["Fiction", "Science", "History", "Fantasy", "Biography", "Poetry"]
COUNTRIES = ["USA", "UK", "France", "Japan", "India", "Germany"]


def seed_library(conn: sqlite3.Connection, seed: int, scale: int = 1) -> dict:
    rng = random.Random(seed)
    conn.executescript(LIBRARY_DDL)
    n_authors = 40 * scale
    n_books = 300 * scale
    n_members = 200 * scale
    n_loans = 1200 * scale

    conn.executemany(
        "INSERT INTO authors(author_id, name, country) VALUES (?,?,?)",
        [(i + 1, f"Author {i+1}", rng.choice(COUNTRIES)) for i in range(n_authors)],
    )
    aw = _zipf_weights(n_authors, s=1.0)
    conn.executemany(
        "INSERT INTO books(book_id, title, author_id, year, genre) VALUES (?,?,?,?,?)",
        [
            (
                i + 1,
                f"Book {i+1}",
                _weighted_choice(rng, aw) + 1,
                rng.randint(1950, 2024),
                rng.choice(GENRES),
            )
            for i in range(n_books)
        ],
    )
    base = date(2022, 1, 1)
    conn.executemany(
        "INSERT INTO members(member_id, full_name, joined_on) VALUES (?,?,?)",
        [
            (i + 1, f"Member {i+1}", (base + timedelta(days=rng.randint(0, 700))).isoformat())
            for i in range(n_members)
        ],
    )
    bw = _zipf_weights(n_books, s=1.15)
    mw = _zipf_weights(n_members, s=1.1)
    conn.executemany(
        "INSERT INTO loans(loan_id, book_id, member_id, loan_date, returned) VALUES (?,?,?,?,?)",
        [
            (
                i + 1,
                _weighted_choice(rng, bw) + 1,
                _weighted_choice(rng, mw) + 1,
                (base + timedelta(days=rng.randint(0, 700))).isoformat(),
                1 if rng.random() < 0.7 else 0,
            )
            for i in range(n_loans)
        ],
    )
    conn.commit()
    return {
        "authors": n_authors,
        "books": n_books,
        "members": n_members,
        "loans": n_loans,
    }


def main() -> None:
    defaults = get_settings() if get_settings else None
    p = argparse.ArgumentParser(description="Generate demo data for the SQL optimizer.")
    p.add_argument("--db", default=getattr(defaults, "local_db_path", "optimizer_demo.db"))
    p.add_argument("--seed", type=int, default=getattr(defaults, "seed", 42))
    p.add_argument("--customers", type=int, default=getattr(defaults, "customer_count", 2000))
    p.add_argument("--orders", type=int, default=getattr(defaults, "order_count", 8000))
    p.add_argument("--products", type=int, default=getattr(defaults, "product_count", 500))
    p.add_argument("--schema", choices=["ecommerce", "library"], default="ecommerce")
    args = p.parse_args()

    conn = sqlite3.connect(args.db)
    if args.schema == "library":
        result = seed_library(conn, args.seed)
    else:
        result = seed_ecommerce(
            conn, args.seed, args.customers, args.orders, args.products
        )
    conn.close()
    print(f"Seeded '{args.schema}' into {args.db} (seed={args.seed}):")
    for table, count in result.items():
        print(f"  {table:<14} {count:>8} rows")


if __name__ == "__main__":
    main()
