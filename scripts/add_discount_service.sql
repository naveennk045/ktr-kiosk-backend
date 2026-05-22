-- 1. Create discounts table
CREATE TABLE IF NOT EXISTS discounts (
    id BIGSERIAL PRIMARY KEY,
    store_id INT REFERENCES stores(id) ON DELETE CASCADE,
    name VARCHAR(255) NOT NULL,
    application_type VARCHAR(50) NOT NULL,
    code VARCHAR(100),
    discount_type VARCHAR(50) NOT NULL,
    value DECIMAL(10,2),
    max_discount_amount DECIMAL(10,2),
    min_order_amount DECIMAL(10,2),
    usage_limit INT,
    start_date TIMESTAMP,
    end_date TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    is_deleted BOOLEAN DEFAULT FALSE,
    created_by BIGINT,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_discount_code_store UNIQUE(code, store_id),
    CONSTRAINT chk_discount_value_non_negative CHECK (value >= 0),
    CONSTRAINT chk_discount_valid_dates CHECK (end_date > start_date)
);

-- 2. Create indexes for discounts
CREATE INDEX IF NOT EXISTS idx_discount_code ON discounts(code);
CREATE INDEX IF NOT EXISTS idx_discount_active ON discounts(is_active, is_deleted);
CREATE INDEX IF NOT EXISTS idx_discount_dates ON discounts(start_date, end_date);
CREATE INDEX IF NOT EXISTS idx_discount_store ON discounts(store_id, is_active, is_deleted);

-- 3. Create discount_usages table
CREATE TABLE IF NOT EXISTS discount_usages (
    id BIGSERIAL PRIMARY KEY,
    discount_id BIGINT REFERENCES discounts(id) ON DELETE CASCADE,
    order_id INT REFERENCES orders(id) ON DELETE CASCADE,
    discount_amount DECIMAL(10,2),
    used_at TIMESTAMP DEFAULT NOW()
);

-- 4. Alter orders table to support discount snapshotting
ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_discount_applied BOOLEAN DEFAULT FALSE;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_id BIGINT;
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_amount DECIMAL(10,2);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_code VARCHAR(100);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_type VARCHAR(50);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS discount_value DECIMAL(10,2);
