-- Relational line items for orders (PostgreSQL). Run once on existing DBs after deploying the OrderItem model.
-- Fresh installs: SQLAlchemy create_all also creates this table; this script is safe to skip if `order_items` already exists.

DO $$ BEGIN
  CREATE TYPE orderitemstatus AS ENUM (
    'NOT_ACCEPTED', 'PREPARING', 'READY', 'COLLECTED'
  );
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;

CREATE TABLE IF NOT EXISTS order_items (
  id SERIAL PRIMARY KEY,
  order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  item_skuid VARCHAR(128) NOT NULL,
  item_name VARCHAR(512) NOT NULL,
  quantity INTEGER NOT NULL,
  items_need_be_ready INTEGER NOT NULL DEFAULT 0,
  items_need_be_collected INTEGER NOT NULL DEFAULT 0,
  price NUMERIC(12, 2) NOT NULL,
  order_status orderitemstatus NOT NULL DEFAULT 'NOT_ACCEPTED',
  variation_id VARCHAR(64),
  addon_items JSONB NOT NULL DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS ix_order_items_order_id ON order_items(order_id);

-- Backfill from legacy `orders.items` JSON (only for orders with no rows in order_items yet)
INSERT INTO order_items (
  order_id, item_skuid, item_name, quantity, items_need_be_ready, items_need_be_collected, price, order_status, variation_id, addon_items
)
SELECT o.id,
  COALESCE(elem->>'sku_code', ''),
  COALESCE(elem->>'item_name', ''),
  GREATEST(COALESCE((elem->>'quantity')::int, 1), 1),
  GREATEST(COALESCE((elem->>'quantity')::int, 1), 1),
  0,
  COALESCE((elem->>'unit_price')::numeric, 0),
  'NOT_ACCEPTED'::orderitemstatus,
  NULLIF(TRIM(elem->>'variation_id'), ''),
  COALESCE(elem->'addon_items', '[]'::jsonb)
FROM orders o
CROSS JOIN LATERAL jsonb_array_elements(
  CASE
    WHEN o.items IS NOT NULL AND jsonb_typeof(o.items) = 'array' THEN o.items
    ELSE '[]'::jsonb
  END
) AS elem
WHERE jsonb_array_length(
  CASE
    WHEN o.items IS NOT NULL AND jsonb_typeof(o.items) = 'array' THEN o.items
    ELSE '[]'::jsonb
  END
) > 0
  AND NOT EXISTS (SELECT 1 FROM order_items oi WHERE oi.order_id = o.id);
