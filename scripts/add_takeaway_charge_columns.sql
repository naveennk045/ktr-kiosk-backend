-- Run once on existing PostgreSQL databases (new installs get columns from SQLAlchemy create_all on empty DB only).
-- For existing tables, add:

ALTER TABLE orders ADD COLUMN IF NOT EXISTS takeaway_charges_exclude_tax NUMERIC(10, 2) NOT NULL DEFAULT 0;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS takeaway_charges_include_tax NUMERIC(10, 2) NOT NULL DEFAULT 0;
