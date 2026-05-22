-- ==========================================
-- ROLLBACK SCRIPT FOR DISCOUNT SERVICE
-- ==========================================

-- OPTION 1: Roll back ONLY the Store-Wise Alterations
-- (Uncomment this block if you only want to restore to the global discounts state)
/*
ALTER TABLE discount_usages ADD COLUMN IF NOT EXISTS user_id BIGINT;

DROP INDEX IF EXISTS idx_discount_store;
ALTER TABLE discounts DROP CONSTRAINT IF EXISTS uq_discount_code_store;
ALTER TABLE discounts ADD CONSTRAINT uq_discount_code UNIQUE (code);
ALTER TABLE discounts DROP COLUMN IF EXISTS store_id;
*/


-- OPTION 2: Completely REMOVE the entire Discount Service
-- (WARNING: This deletes all discounts, usage history, and removes discount columns from orders!)

-- 1. Remove discount snapshot columns from orders table
ALTER TABLE orders DROP COLUMN IF EXISTS is_discount_applied;
ALTER TABLE orders DROP COLUMN IF EXISTS discount_id;
ALTER TABLE orders DROP COLUMN IF EXISTS discount_amount;
ALTER TABLE orders DROP COLUMN IF EXISTS discount_code;
ALTER TABLE orders DROP COLUMN IF EXISTS discount_type;
ALTER TABLE orders DROP COLUMN IF EXISTS discount_value;

-- 2. Drop the discount tables (automatically drops their indexes and constraints)
DROP TABLE IF EXISTS discount_usages CASCADE;
DROP TABLE IF EXISTS discounts CASCADE;
