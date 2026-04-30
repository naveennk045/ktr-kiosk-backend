-- Partial READY/COLLECTED: track remaining kitchen vs counter quantities.
-- Uses existing `quantity` as the ordered count (no duplicate actual_quantity).
-- Safe to run multiple times.

ALTER TABLE order_items
  ADD COLUMN IF NOT EXISTS items_need_be_ready INTEGER;

ALTER TABLE order_items
  ADD COLUMN IF NOT EXISTS items_need_be_collected INTEGER;

-- Drop redundant column if a previous migration added it.
ALTER TABLE order_items
  DROP COLUMN IF EXISTS actual_quantity;

-- Backfill from existing line quantity/status.
UPDATE order_items
SET
  items_need_be_ready = COALESCE(
    items_need_be_ready,
    CASE
      WHEN order_status = 'NOT_ACCEPTED' THEN quantity
      WHEN order_status = 'PREPARING' THEN quantity
      WHEN order_status = 'READY' THEN 0
      WHEN order_status = 'COLLECTED' THEN 0
      ELSE quantity
    END
  ),
  items_need_be_collected = COALESCE(
    items_need_be_collected,
    CASE
      WHEN order_status = 'READY' THEN quantity
      ELSE 0
    END
  );

-- Clamp invalid values and enforce non-null/defaults.
UPDATE order_items
SET
  items_need_be_ready = GREATEST(COALESCE(items_need_be_ready, 0), 0),
  items_need_be_collected = GREATEST(COALESCE(items_need_be_collected, 0), 0);

ALTER TABLE order_items
  ALTER COLUMN items_need_be_ready SET NOT NULL,
  ALTER COLUMN items_need_be_ready SET DEFAULT 0,
  ALTER COLUMN items_need_be_collected SET NOT NULL,
  ALTER COLUMN items_need_be_collected SET DEFAULT 0;
