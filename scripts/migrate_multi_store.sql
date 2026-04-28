-- Multi-store schema evolution (PostgreSQL). Backup before running.
-- Scenarios:
-- A) Fresh install: use SQLAlchemy create_all, then INSERT stores + store_*_credentials (no env-based credential bootstrap).
-- B) Existing DB with UUID stores + edc_config: use the steps below as a TEMPLATE;
--    adjust UUIDs and names to match your data.

-- ---------------------------------------------------------------------------
-- 1) stores: UUID id -> integer id + store_code + store_name
-- ---------------------------------------------------------------------------
-- Example approach (destructive / requires downtime):
-- CREATE TABLE stores_new (
--   id SERIAL PRIMARY KEY,
--   store_code VARCHAR(32) NOT NULL UNIQUE,
--   store_name VARCHAR(255) NOT NULL,
--   is_active BOOLEAN NOT NULL DEFAULT true,
--   created_at TIMESTAMPTZ NOT NULL DEFAULT now()
-- );
-- INSERT INTO stores_new (store_code, store_name)
-- VALUES ('STORE-001', 'Default');
-- -- Map old UUID -> new id in a temp table, then UPDATE orders SET store_id = ...
-- -- Finally swap tables and recreate FKs.

-- ---------------------------------------------------------------------------
-- 2) store_pinelabs_credentials (1:1 with stores.id)
-- ---------------------------------------------------------------------------
-- INSERT INTO store_pinelabs_credentials (store_id, base_url, merchant_id, user_id, security_token)
-- VALUES (1, '<from env PINELABS_EDC_BASE_URL>', '<MERCHANT>', '<USER>', '<TOKEN>');

-- ---------------------------------------------------------------------------
-- 3) kiosk_terminals (replaces edc_config)
-- ---------------------------------------------------------------------------
-- INSERT INTO kiosk_terminals (store_id, terminal_id, pinelabs_store_id, mid_on_device, label, is_active)
-- SELECT ktr_store_id, terminal_id, store_id, mid_on_device, store_name, true
-- FROM edc_config;
-- DROP TABLE edc_config;

-- ---------------------------------------------------------------------------
-- 4) Redis: after migration, call POST /admin/cache/invalidate with X-Store-Id
--    or restart app so credential caches repopulate from DB.

-- Sample two-outlet seed (KTR Bandra + KTR Versova): see sample_data_ktr_bandra_versova.sql
