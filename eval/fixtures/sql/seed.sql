-- Fixture rows for `schema.sql`. `M4-EVAL-TEST-112`.
--
-- `orders.stat_cd`: 'P' = placed/pending, 'S' = shipped, 'C' = cancelled,
-- 'R' = returned -- the encoding `eval.sql_fixture` writes as a user-origin
-- schema note, never repeated here as a comment a model could read: the
-- point of the fixture is that the note, not this file, is what a
-- generation call sees.

INSERT INTO customers (id, name, email, region, tier, created_at) VALUES
    (1, 'Alice Ng', 'alice@example.com', 'US', 'standard', '2024-01-15'),
    (2, 'Bob Diaz', 'bob@example.com', 'US', 'premium', '2024-02-20'),
    (3, 'Carla Smith', 'carla@example.com', 'UK', 'standard', '2024-03-05'),
    (4, 'Dev Patel', 'dev@example.com', 'IN', 'enterprise', '2024-03-22'),
    (5, 'Elin Karlsson', 'elin@example.com', 'SE', 'premium', '2024-04-10'),
    (6, 'Farid Haidari', 'farid@example.com', 'AE', 'standard', '2024-05-01'),
    (7, 'Grace Lin', 'grace@example.com', 'SG', 'standard', '2024-05-19'),
    (8, 'Hugo Silva', 'hugo@example.com', 'BR', 'premium', '2024-06-02'),
    (9, 'Ines Moreau', 'ines@example.com', 'FR', 'enterprise', '2024-06-30'),
    (10, 'Jonas Weber', 'jonas@example.com', 'DE', 'standard', '2024-07-14');
SELECT setval('customers_id_seq', 10);

INSERT INTO products (id, sku, name, category, price_cents) VALUES
    (1, 'SKU-100', 'Trail Runner Jacket', 'outerwear', 12000),
    (2, 'SKU-101', 'Alpine Fleece', 'outerwear', 8500),
    (3, 'SKU-102', 'Summit Backpack 30L', 'gear', 9500),
    (4, 'SKU-103', 'Trekking Poles', 'gear', 4200),
    (5, 'SKU-104', 'Merino Base Layer', 'apparel', 3600),
    (6, 'SKU-105', 'Insulated Bottle', 'accessories', 2200),
    (7, 'SKU-106', 'Camp Stove', 'gear', 6800),
    (8, 'SKU-107', 'Rain Shell', 'outerwear', 11000);
SELECT setval('products_id_seq', 8);

INSERT INTO orders (id, customer_id, stat_cd, placed_at) VALUES
    (1, 1, 'S', '2025-01-05'),
    (2, 1, 'C', '2025-02-11'),
    (3, 2, 'S', '2025-01-20'),
    (4, 3, 'P', '2025-03-01'),
    (5, 4, 'S', '2025-01-15'),
    (6, 4, 'S', '2025-04-02'),
    (7, 5, 'R', '2025-02-08'),
    (8, 6, 'S', '2025-03-19'),
    (9, 7, 'C', '2025-04-25'),
    (10, 8, 'S', '2025-01-30'),
    (11, 9, 'S', '2025-05-06'),
    (12, 9, 'S', '2025-05-20'),
    (13, 10, 'P', '2025-06-01'),
    (14, 2, 'S', '2025-06-10'),
    (15, 5, 'S', '2025-06-15'),
    (16, 3, 'S', '2025-06-18');
SELECT setval('orders_id_seq', 16);

INSERT INTO order_items (order_id, product_id, qty, unit_price_cents) VALUES
    (1, 1, 1, 12000),
    (1, 6, 2, 2200),
    (2, 2, 1, 8500),
    (3, 3, 1, 9500),
    (3, 4, 2, 4200),
    (4, 5, 3, 3600),
    (5, 7, 1, 6800),
    (6, 1, 1, 12000),
    (6, 8, 1, 11000),
    (7, 6, 1, 2200),
    (8, 2, 2, 8500),
    (9, 5, 1, 3600),
    (10, 3, 1, 9500),
    (11, 4, 1, 4200),
    (11, 6, 1, 2200),
    (12, 1, 2, 12000),
    (13, 7, 1, 6800),
    (14, 8, 1, 11000),
    (15, 2, 1, 8500),
    (15, 5, 2, 3600),
    (16, 3, 1, 9500);

INSERT INTO support_tickets (customer_id, order_id, priority, opened_at, closed_at, subject) VALUES
    (1, 2, 3, '2025-02-12', '2025-02-15', 'Wrong item cancelled'),
    (4, 6, 1, '2025-04-05', '2025-04-06', 'Delivery delay question'),
    (5, 7, 3, '2025-02-09', NULL, 'Return not processed'),
    (7, 9, 2, '2025-04-26', '2025-04-28', 'Order cancellation confirmation'),
    (2, NULL, 1, '2025-05-01', '2025-05-02', 'General product question'),
    (9, 11, 2, '2025-05-07', NULL, 'Missing item in shipment'),
    (3, NULL, 3, '2025-06-19', NULL, 'Account access issue'),
    (8, 10, 1, '2025-02-01', '2025-02-03', 'Invoice request');
