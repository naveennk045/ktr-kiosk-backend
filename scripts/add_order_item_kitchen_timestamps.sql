-- TMS board: per-line kitchen timestamps (also applied on app startup).
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS preparing_at TIMESTAMPTZ;
ALTER TABLE order_items ADD COLUMN IF NOT EXISTS ready_at TIMESTAMPTZ;
