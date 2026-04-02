-- Run on existing databases (new empty DBs pick this up from SQLAlchemy metadata).

CREATE TABLE IF NOT EXISTS cash_pin (
    id SERIAL PRIMARY KEY,
    pin VARCHAR(64) NOT NULL,
    staff_name VARCHAR(255) NOT NULL,
    CONSTRAINT uq_cash_pin_pin UNIQUE (pin)
);

CREATE INDEX IF NOT EXISTS ix_cash_pin_pin ON cash_pin (pin);

ALTER TABLE orders ADD COLUMN IF NOT EXISTS cash_pin_id INTEGER REFERENCES cash_pin (id);
ALTER TABLE orders ADD COLUMN IF NOT EXISTS cash_collected_by_staff_name VARCHAR(255);

CREATE INDEX IF NOT EXISTS ix_orders_cash_pin_id ON orders (cash_pin_id);

-- Example staff (change PINs in production)
INSERT INTO cash_pin (pin, staff_name) VALUES ('9580', 'Devesh');
