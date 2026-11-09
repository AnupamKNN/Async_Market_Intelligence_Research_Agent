BEGIN;

-- Temporary staging table. All source values initially enter as text.
CREATE TEMP TABLE retail_transactions_stage (
    invoice_no TEXT,
    stock_code TEXT,
    description TEXT,
    quantity TEXT,
    invoice_date TEXT,
    unit_price TEXT,
    customer_id TEXT,
    country TEXT
) ON COMMIT DROP;

-- Load the canonical CSV into staging.
\copy retail_transactions_stage (invoice_no, stock_code, description, quantity, invoice_date, unit_price, customer_id, country) FROM 'data/interim/online_retail_ii_canonical.csv' WITH (FORMAT csv, HEADER true, NULL '')

-- Validate the complete staging dataset before modifying the destination.
DO $$
DECLARE
    staged_rows BIGINT;
    invalid_required BIGINT;
    invalid_quantity BIGINT;
    invalid_price BIGINT;
BEGIN
    SELECT COUNT(*) INTO staged_rows
    FROM retail_transactions_stage;

    IF staged_rows <> 1044848 THEN
        RAISE EXCEPTION
            'Unexpected row count: expected 1044848, received %',
            staged_rows;
    END IF;

    SELECT COUNT(*) INTO invalid_required
    FROM retail_transactions_stage
    WHERE NULLIF(BTRIM(invoice_no), '') IS NULL
       OR NULLIF(BTRIM(stock_code), '') IS NULL
       OR NULLIF(BTRIM(quantity), '') IS NULL
       OR NULLIF(BTRIM(invoice_date), '') IS NULL
       OR NULLIF(BTRIM(unit_price), '') IS NULL
       OR NULLIF(BTRIM(country), '') IS NULL;

    IF invalid_required > 0 THEN
        RAISE EXCEPTION
            'Found % rows with missing required fields',
            invalid_required;
    END IF;

    SELECT COUNT(*) INTO invalid_quantity
    FROM retail_transactions_stage
    WHERE quantity !~ '^[+-]?[0-9]+(\.0+)?$';

    IF invalid_quantity > 0 THEN
        RAISE EXCEPTION
            'Found % rows with non-integer quantities',
            invalid_quantity;
    END IF;

    SELECT COUNT(*) INTO invalid_price
    FROM retail_transactions_stage
    WHERE unit_price !~ '^[+-]?([0-9]+(\.[0-9]*)?|\.[0-9]+)$';

    IF invalid_price > 0 THEN
        RAISE EXCEPTION
            'Found % rows with invalid unit prices',
            invalid_price;
    END IF;

    RAISE NOTICE 'Staging validation successful: % rows', staged_rows;
END $$;

-- Replace the destination contents only after staging validation succeeds.
TRUNCATE TABLE analytics.retail_transactions RESTART IDENTITY;

-- Insert normalized records. Generated columns are intentionally omitted.
INSERT INTO analytics.retail_transactions (
    invoice_no,
    stock_code,
    description,
    quantity,
    invoice_date,
    unit_price,
    customer_id,
    country,
    source_dataset
)
SELECT
    invoice_no,
    stock_code,
    NULLIF(description, ''),
    quantity::NUMERIC::INTEGER,
    invoice_date::TIMESTAMP,
    unit_price::NUMERIC(14, 4),
    CASE
        WHEN NULLIF(BTRIM(customer_id), '') IS NULL THEN NULL
        WHEN BTRIM(customer_id) ~ '^[0-9]+\.0+$'
            THEN REGEXP_REPLACE(BTRIM(customer_id), '\.0+$', '')
        ELSE BTRIM(customer_id)
    END,
    country,
    'online_retail_ii'
FROM retail_transactions_stage;

ANALYZE analytics.retail_transactions;

-- Final load verification.
SELECT
    COUNT(*) AS loaded_rows,
    COUNT(DISTINCT invoice_no) AS unique_invoices,
    COUNT(DISTINCT stock_code) AS unique_products,
    COUNT(DISTINCT customer_id) AS unique_customers,
    COUNT(*) FILTER (WHERE customer_id IS NULL) AS missing_customer_ids,
    COUNT(*) FILTER (WHERE quantity < 0) AS negative_quantity_rows,
    COUNT(*) FILTER (WHERE unit_price < 0) AS negative_price_rows,
    MIN(invoice_date) AS first_transaction,
    MAX(invoice_date) AS last_transaction
FROM analytics.retail_transactions;

COMMIT;
