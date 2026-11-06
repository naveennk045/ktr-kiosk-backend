-- Kiosk revamp: mixed dine-in/parcel orders and free-text item options/notes.
-- Idempotent and safe to re-run (also applied on app startup). Run on each primary cluster.
-- order_type: NULL means the line follows orders.order_type.
-- options: JSONB DEFAULT is a constant, so Postgres 11+ adds it without rewriting the table.
BEGIN;

SET LOCAL lock_timeout = '5s';

ALTER TABLE order_items ADD COLUMN IF NOT EXISTS order_type ordertype;
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS options    JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS note       VARCHAR(200);

COMMIT;

-- Check: should return 3 rows
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'order_items' AND column_name IN ('order_type', 'options', 'note');
