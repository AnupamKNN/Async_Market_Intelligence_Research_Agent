CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.retail_transactions (
    transaction_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,

    invoice_no TEXT NOT NULL,
    stock_code TEXT NOT NULL,
    description TEXT,

    quantity INTEGER NOT NULL,
    invoice_date TIMESTAMP NOT NULL,

    unit_price NUMERIC(14, 4) NOT NULL,

    customer_id TEXT,
    country TEXT NOT NULL,

    source_dataset TEXT NOT NULL DEFAULT 'online_retail_ii',

    line_total NUMERIC(18, 4)
        GENERATED ALWAYS AS (quantity * unit_price) STORED,

    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Date-oriented analytical queries
CREATE INDEX IF NOT EXISTS idx_retail_invoice_date
    ON analytics.retail_transactions (invoice_date);

-- Customer purchase history
CREATE INDEX IF NOT EXISTS idx_retail_customer_date
    ON analytics.retail_transactions (customer_id, invoice_date);

-- Product performance analysis
CREATE INDEX IF NOT EXISTS idx_retail_stock_code
    ON analytics.retail_transactions (stock_code);

-- Country-level analytics
CREATE INDEX IF NOT EXISTS idx_retail_country
    ON analytics.retail_transactions (country);

-- Invoice-level aggregation
CREATE INDEX IF NOT EXISTS idx_retail_invoice_no
    ON analytics.retail_transactions (invoice_no);