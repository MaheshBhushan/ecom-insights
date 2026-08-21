-- Star schema for the E-commerce Data Pipeline warehouse (PostgreSQL).
-- Grain of fact_sales: one row per order line item (order_id, product_id).
-- Columns are derived from data/processed/{customers,products,orders,order_items}_transformed.csv.

DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_customer;
DROP TABLE IF EXISTS dim_product;
DROP TABLE IF EXISTS dim_date;

CREATE TABLE dim_customer (
    customer_id VARCHAR(10) PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL,
    registration_date DATE NOT NULL,
    country VARCHAR(50),
    full_name VARCHAR(101)
);

CREATE TABLE dim_product (
    product_id VARCHAR(10) PRIMARY KEY,
    product_name VARCHAR(100) NOT NULL,
    description TEXT,
    category VARCHAR(50),
    brand VARCHAR(50),
    price NUMERIC(10, 2) NOT NULL,
    cost NUMERIC(10, 2),
    profit_margin NUMERIC(6, 4),
    price_tier VARCHAR(20)
);

CREATE TABLE dim_date (
    date_key DATE PRIMARY KEY,
    year INT NOT NULL,
    month INT NOT NULL,
    day INT NOT NULL,
    day_of_week INT NOT NULL,
    quarter INT NOT NULL,
    is_weekend BOOLEAN NOT NULL
);

CREATE TABLE fact_sales (
    item_id VARCHAR(15) PRIMARY KEY,
    order_id VARCHAR(10) NOT NULL,
    customer_id VARCHAR(10) NOT NULL REFERENCES dim_customer(customer_id),
    product_id VARCHAR(10) NOT NULL REFERENCES dim_product(product_id),
    date_key DATE NOT NULL REFERENCES dim_date(date_key),
    order_status VARCHAR(20),
    quantity INT NOT NULL,
    unit_price NUMERIC(10, 2) NOT NULL,
    discount_rate NUMERIC(5, 4) DEFAULT 0,
    discount_amount NUMERIC(10, 2) DEFAULT 0,
    gross_revenue NUMERIC(12, 2) NOT NULL,
    net_revenue NUMERIC(12, 2) NOT NULL,
    cost NUMERIC(12, 2),
    UNIQUE (order_id, product_id)
);

CREATE INDEX idx_fact_sales_customer_id ON fact_sales(customer_id);
CREATE INDEX idx_fact_sales_product_id ON fact_sales(product_id);
CREATE INDEX idx_fact_sales_date_key ON fact_sales(date_key);
