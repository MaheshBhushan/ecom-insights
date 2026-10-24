-- Staging tables for the chunked raw import (src/load/chunked_import.py).
-- Rows reach these tables only after schema validation. Rejects go to
-- data/quarantine/<source>_quarantine.csv.

CREATE TABLE IF NOT EXISTS staging_customers (
    customer_id VARCHAR(10) PRIMARY KEY,
    first_name VARCHAR(50) NOT NULL,
    last_name VARCHAR(50) NOT NULL,
    email VARCHAR(100) NOT NULL,
    registration_date DATE NOT NULL,
    country VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS staging_products (
    product_id VARCHAR(10) PRIMARY KEY,
    product_name VARCHAR(100) NOT NULL,
    description TEXT,
    category VARCHAR(50),
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    cost NUMERIC(10, 2) CHECK (cost >= 0),
    brand VARCHAR(50)
);

CREATE TABLE IF NOT EXISTS staging_orders (
    order_id VARCHAR(10) PRIMARY KEY,
    customer_id VARCHAR(10) NOT NULL,
    order_date DATE NOT NULL,
    order_status VARCHAR(20) NOT NULL,
    order_total NUMERIC(12, 2),
    shipping_cost NUMERIC(10, 2),
    tax NUMERIC(10, 2),
    payment_method VARCHAR(30),
    shipping_method VARCHAR(30)
);

CREATE TABLE IF NOT EXISTS staging_order_items (
    item_id VARCHAR(15) PRIMARY KEY,
    order_id VARCHAR(10) NOT NULL,
    product_id VARCHAR(10) NOT NULL,
    quantity INT NOT NULL CHECK (quantity > 0),
    price NUMERIC(10, 2) NOT NULL CHECK (price >= 0),
    discount_rate NUMERIC(5, 4) CHECK (discount_rate BETWEEN 0 AND 1)
);
