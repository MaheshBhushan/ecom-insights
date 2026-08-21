# SQL Scripts for E-commerce Data Pipeline

This directory contains SQL scripts for database setup, queries, and data extraction for the e-commerce data pipeline.

## Scripts

1. **create_tables.sql** - Creates the database schema with all necessary tables

## Database Schema

The database schema includes the following main tables:

- `customers` - Customer information
- `products` - Product catalog
- `orders` - Order header information
- `order_items` - Order line items
- `product_categories` - Product category hierarchy
- `inventory` - Product inventory information
- `customer_reviews` - Product reviews from customers
- `promotions` - Marketing promotions

## Usage

To set up the database:

1. Connect to your database server:
```bash
# For MySQL/MariaDB
mysql -u username -p

# For PostgreSQL
psql -U username -d database
```

2. Run the create_tables.sql script:
```sql
-- In MySQL/MariaDB
SOURCE /path/to/create_tables.sql;

-- In PostgreSQL
\i /path/to/create_tables.sql
```

## Database Connection

The data pipeline connects to the database using the configuration in `src/config.py`. Make sure to update the connection parameters to match your database setup. 