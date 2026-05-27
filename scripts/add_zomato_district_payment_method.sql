-- Migration script to add 'ZOMATO_DISTRICT' to the PaymentMethod enum in PostgreSQL.

-- Note: In PostgreSQL, ENUM types cannot be altered within a transaction block
-- unless you are on PostgreSQL 12 or newer. 
-- The IF NOT EXISTS clause is also available in PostgreSQL 9.3+.

ALTER TYPE paymentmethod ADD VALUE IF NOT EXISTS 'ZOMATO_DISTRICT';

-- If the enum type is named differently (e.g., payment_method), use this instead:
-- ALTER TYPE payment_method ADD VALUE IF NOT EXISTS 'ZOMATO_DISTRICT';
