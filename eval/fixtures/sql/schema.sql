-- Fixture schema for the text-to-SQL and SQL-safety eval suites.
-- `M4-EVAL-TEST-112`. Loaded, as `askwell_sandbox_owner`, into a fresh
-- sandbox database `eval.sql_fixture.seed_sql_fixture` creates the same way
-- a real dump import would (`askwell.sandbox.create_database`) -- this file
-- is trusted content the harness controls, not an untrusted dump, so it is
-- fed straight to psql rather than through `askwell.dump_import`.
--
-- `orders.stat_cd` is the one deliberately unguessable column the ticket's
-- Scope names: a single-letter status code with no self-describing value.
-- Auto-introspection (`askwell.schema_introspect.write_schema_inventory`)
-- only ever infers "text, not null" for it; `eval.sql_fixture` writes the
-- user-origin note that actually explains the encoding, the same shape a
-- clarification answer would produce -- several tasks in
-- `text_to_sql.v1.json` can only be answered correctly with that note in
-- place, matching `docs/states-and-edge-cases.md`'s "result depends on
-- schema notes" edge case.

CREATE TABLE customers (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT NOT NULL,
    region TEXT NOT NULL,
    tier TEXT NOT NULL,
    created_at DATE NOT NULL
);

CREATE TABLE products (
    id SERIAL PRIMARY KEY,
    sku TEXT NOT NULL,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    price_cents INTEGER NOT NULL
);

CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers (id),
    stat_cd CHAR(1) NOT NULL,
    placed_at DATE NOT NULL
);

CREATE TABLE order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (id),
    product_id INTEGER NOT NULL REFERENCES products (id),
    qty INTEGER NOT NULL,
    unit_price_cents INTEGER NOT NULL
);

CREATE TABLE support_tickets (
    id SERIAL PRIMARY KEY,
    customer_id INTEGER NOT NULL REFERENCES customers (id),
    order_id INTEGER REFERENCES orders (id),
    priority SMALLINT NOT NULL,
    opened_at DATE NOT NULL,
    closed_at DATE,
    subject TEXT NOT NULL
);
