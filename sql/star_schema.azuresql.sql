-- Star schema for the E-commerce Data Pipeline warehouse (Azure SQL / T-SQL).
-- Documented cloud target only -- NOT executed against a real Azure SQL instance
-- (the project's Azure subscription is disabled). Mirrors star_schema.postgres.sql,
-- which is the schema actually loaded and verified in this project.
-- Grain of fact_sales: one row per order line item (order_id, product_id).

IF OBJECT_ID('fact_sales', 'U') IS NOT NULL DROP TABLE fact_sales;
IF OBJECT_ID('dim_customer', 'U') IS NOT NULL DROP TABLE dim_customer;
IF OBJECT_ID('dim_product', 'U') IS NOT NULL DROP TABLE dim_product;
IF OBJECT_ID('dim_date', 'U') IS NOT NULL DROP TABLE dim_date;

CREATE TABLE dim_customer (
    customer_id VARCHAR(10) NOT NULL PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL,
    registration_date DATE NOT NULL,
    country VARCHAR(50) NULL,
    full_name VARCHAR(101) NULL
);

CREATE TABLE dim_product (
    product_id VARCHAR(10) NOT NULL PRIMARY KEY,
    product_name VARCHAR(100) NOT NULL,
    description VARCHAR(MAX) NULL,
    category VARCHAR(50) NULL,
    brand VARCHAR(50) NULL,
    price DECIMAL(10, 2) NOT NULL,
    cost DECIMAL(10, 2) NULL,
    profit_margin DECIMAL(6, 4) NULL,
    price_tier VARCHAR(20) NULL CHECK (price_tier IN ('Low', 'Medium', 'High'))
);

CREATE TABLE dim_date (
    date_key DATE NOT NULL PRIMARY KEY,
    year INT NOT NULL,
    month INT NOT NULL,
    day INT NOT NULL,
    day_of_week INT NOT NULL,
    quarter INT NOT NULL,
    is_weekend BIT NOT NULL
);

CREATE TABLE fact_sales (
    item_id VARCHAR(15) NOT NULL PRIMARY KEY,
    order_id VARCHAR(10) NOT NULL,
    customer_id VARCHAR(10) NOT NULL REFERENCES dim_customer(customer_id),
    product_id VARCHAR(10) NOT NULL REFERENCES dim_product(product_id),
    date_key DATE NOT NULL REFERENCES dim_date(date_key),
    order_status VARCHAR(20) NULL,
    quantity INT NOT NULL,
    unit_price DECIMAL(10, 2) NOT NULL,
    discount_rate DECIMAL(5, 4) NULL DEFAULT 0,
    discount_amount DECIMAL(10, 2) NULL DEFAULT 0,
    gross_revenue DECIMAL(12, 2) NOT NULL,
    net_revenue DECIMAL(12, 2) NOT NULL,
    cost DECIMAL(12, 2) NULL,
    CONSTRAINT uq_fact_sales_order_product UNIQUE (order_id, product_id)
);

CREATE INDEX idx_fact_sales_customer_id ON fact_sales(customer_id);
CREATE INDEX idx_fact_sales_product_id ON fact_sales(product_id);
CREATE INDEX idx_fact_sales_date_key ON fact_sales(date_key);
