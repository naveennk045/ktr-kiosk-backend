-- Migration: rename orders.store_id -> orders.terminal_id
-- Run once against the production/staging database.
-- Safe to run even if the column was already renamed (will error if column doesn't exist).

ALTER TABLE orders RENAME COLUMN store_id TO terminal_id;
