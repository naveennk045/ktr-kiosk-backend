-- Kitchen line items for KDS/TMS (run on existing DBs that already have `orders`).
-- Safe to re-run: skips enum/table if they exist; backfill only inserts when an order has no rows.

DO $$ BEGIN
    CREATE TYPE kitchenlinestatus AS ENUM (
        'GETTING_READY',
        'READY_FOR_PICKUP',
        'PICKED_UP'
    );
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS order_items (
    id SERIAL PRIMARY KEY,
    order_id INTEGER NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
    line_index INTEGER NOT NULL,
    sku_code VARCHAR NOT NULL,
    item_name VARCHAR,
    quantity INTEGER NOT NULL DEFAULT 1,
    kitchen_status kitchenlinestatus NOT NULL DEFAULT 'GETTING_READY'
);

CREATE INDEX IF NOT EXISTS idx_order_items_order_id ON order_items (order_id);
CREATE INDEX IF NOT EXISTS idx_order_items_kitchen_status ON order_items (kitchen_status);

-- Backfill from legacy JSONB `orders.items` (one row per element; preserves order).
INSERT INTO order_items (order_id, line_index, sku_code, item_name, quantity, kitchen_status)
SELECT o.id,
       (t.ord - 1)::int AS line_index,
       COALESCE(t.elem->>'sku_code', '') AS sku_code,
       NULLIF(t.elem->>'item_name', '') AS item_name,
       COALESCE((t.elem->>'quantity')::int, 1) AS quantity,
       'GETTING_READY'::kitchenlinestatus
FROM orders o
CROSS JOIN LATERAL jsonb_array_elements(o.items) WITH ORDINALITY AS t(elem, ord)
WHERE NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.order_id = o.id)
  AND jsonb_typeof(o.items) = 'array';
