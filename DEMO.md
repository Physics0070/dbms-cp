# Demo dataset & sample queries

The demo is **only a demonstration dataset**. The optimizer contains no logic specific to
it — see [LIMITATIONS.md](LIMITATIONS.md) and the schema-agnostic test.

## The e-commerce schema (`seed/generate.py`)

```
categories(category_id PK, name, parent_id → categories)
customers(customer_id PK, name, email, city, country, created_at)
products(product_id PK, name, category_id → categories, price, stock)
orders(order_id PK, customer_id → customers, status, order_date, total)
order_items(order_item_id PK, order_id → orders, product_id → products, quantity, unit_price)
```

Indexes created: `products(category_id)`, `order_items(order_id)`,
`unique customers(email)`. Foreign keys `orders.customer_id`, `order_items.product_id`
are intentionally left **unindexed** so the What-If advisor has realistic suggestions.

## Generation

Data is generated programmatically and deterministically (fixed `SEED`) — there are no
hand-written INSERTs. Configurable via `.env` or CLI flags:

```bash
python -m seed.generate --seed 42 --customers 2000 --orders 8000 --products 500
```

### Deliberate skew

- **Customer activity** follows a Zipf/power law — a few customers place many orders.
- **Product popularity** is power-law — a few products dominate `order_items`.
- **Category sizes** are uneven.
- **Order status** is skewed: `completed` is common, `refunded` is rare.

None of the resulting numbers are recorded anywhere — the optimizer computes them.

## Sample queries to try

**Selective filter (rare value) — index scan wins:**
```sql
SELECT * FROM orders WHERE status = 'refunded';
```

**Common value — sequential scan often wins:**
```sql
SELECT * FROM orders WHERE status = 'completed';
```

**Join + filter + sort (multiple join orders, hash join):**
```sql
SELECT c.name, o.total
FROM customers c
JOIN orders o ON o.customer_id = c.customer_id
WHERE o.status = 'completed' AND c.country = 'India'
ORDER BY o.total DESC;
```

**Three-way join (join-order search):**
```sql
SELECT c.name, o.total, oi.quantity
FROM customers c
JOIN orders o ON o.customer_id = c.customer_id
JOIN order_items oi ON oi.order_id = o.order_id
WHERE o.status = 'completed';
```

**Aggregation:**
```sql
SELECT status, COUNT(*) AS n FROM orders GROUP BY status ORDER BY n DESC;
```

## Proving it is not hardcoded

Generate the unrelated library schema and optimize against it — every page still works:
```bash
python -m seed.generate --schema library --db library.db
# set LOCAL_DB_PATH=library.db and restart the API
```
```sql
SELECT a.name, b.title
FROM authors a JOIN books b ON b.author_id = a.author_id
WHERE b.genre = 'Fiction' ORDER BY b.title;
```
