-- Petpooja: menu sharing code (restID in save-order / fetch-menu). Run once on existing DBs.
-- New installs: SQLAlchemy create_all includes this column + constraints.

ALTER TABLE store_petpooja_credentials
  ADD COLUMN IF NOT EXISTS menu_sharing_code VARCHAR(64);

UPDATE store_petpooja_credentials
SET menu_sharing_code = petpooja_restaurant_id
WHERE menu_sharing_code IS NULL OR trim(menu_sharing_code) = '';

ALTER TABLE store_petpooja_credentials
  ALTER COLUMN menu_sharing_code SET NOT NULL;

-- Match ORM name uq_petpooja_menu_sharing_code (safe if already applied)
DO $$ BEGIN
  ALTER TABLE store_petpooja_credentials
    ADD CONSTRAINT uq_petpooja_menu_sharing_code UNIQUE (menu_sharing_code);
EXCEPTION
  WHEN duplicate_object THEN NULL;
END $$;
