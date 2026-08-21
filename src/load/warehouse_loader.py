"""
Warehouse load step for the E-commerce Data Pipeline.

Builds the star schema (dim_customer, dim_product, dim_date, fact_sales) from the
transformed CSVs in data/processed/, validates it, then loads it into the
warehouse database (Postgres by default, see src/utils.get_db_connection) inside
a single transaction, truncating first so re-running the load is idempotent.
It also writes the same four modelled tables back out as CSVs so the star
schema can be inspected without a database.
"""
import os
import sys
import logging

import pandas as pd
from sqlalchemy import text

from src.config import PATHS
from src.utils import get_db_connection, ensure_dir, save_dataframe

logger = logging.getLogger(__name__)

REQUIRED_COLUMNS = {
    'customers': ['customer_id', 'first_name', 'last_name', 'email', 'registration_date', 'country'],
    'products': ['product_id', 'product_name', 'category', 'brand', 'price', 'cost'],
    'orders': ['order_id', 'customer_id', 'order_date', 'order_status'],
    'order_items': ['item_id', 'order_id', 'product_id', 'quantity', 'price', 'discount_rate'],
}

# Load order matters: dimensions before the fact table (FK-safe), and truncate
# in the reverse order so the fact table (which references the dimensions) is
# cleared first.
LOAD_ORDER = ['dim_customer', 'dim_product', 'dim_date', 'fact_sales']
TRUNCATE_ORDER = list(reversed(LOAD_ORDER))


class ValidationError(Exception):
    """Raised when the source data fails a trust-boundary check before load."""


def _read_source_data():
    """Read the transformed CSVs the star schema is derived from."""
    processed = PATHS['processed_data']
    paths = {
        'customers': os.path.join(processed, 'customers_transformed.csv'),
        'products': os.path.join(processed, 'products_transformed.csv'),
        'orders': os.path.join(processed, 'orders_transformed.csv'),
        'order_items': os.path.join(processed, 'order_items_transformed.csv'),
    }
    missing = [name for name, path in paths.items() if not os.path.exists(path)]
    if missing:
        raise ValidationError(f"Missing transformed source file(s) for: {', '.join(missing)}")

    return {name: pd.read_csv(path) for name, path in paths.items()}


def _validate_source_data(sources):
    """Validate raw source data before any modelling happens."""
    violations = []

    for name, required in REQUIRED_COLUMNS.items():
        missing_cols = set(required) - set(sources[name].columns)
        if missing_cols:
            violations.append(f"{name}: missing required column(s) {sorted(missing_cols)}")

    if violations:
        raise ValidationError("; ".join(violations))

    customers = sources['customers']
    products = sources['products']
    order_items = sources['order_items']

    if customers['customer_id'].isna().any():
        violations.append("customers: null customer_id (primary key)")
    if products['product_id'].isna().any():
        violations.append("products: null product_id (primary key)")
    if order_items['order_id'].isna().any():
        violations.append("order_items: null order_id (foreign key)")
    if order_items['product_id'].isna().any():
        violations.append("order_items: null product_id (foreign key)")

    dup_grain = order_items.duplicated(subset=['order_id', 'product_id'])
    if dup_grain.any():
        n = int(dup_grain.sum())
        violations.append(f"order_items: {n} duplicate (order_id, product_id) row(s) in the fact grain")

    if (order_items['quantity'] < 0).any():
        violations.append("order_items: negative quantity")
    if (order_items['price'] < 0).any():
        violations.append("order_items: negative price")

    customer_ids = set(customers['customer_id'])
    product_ids = set(products['product_id'])
    orphan_customers = ~sources['orders']['customer_id'].isin(customer_ids)
    if orphan_customers.any():
        n = int(orphan_customers.sum())
        violations.append(f"orders: {n} order(s) with customer_id not present in dim_customer")
    orphan_products = ~order_items['product_id'].isin(product_ids)
    if orphan_products.any():
        n = int(orphan_products.sum())
        violations.append(f"order_items: {n} row(s) with product_id not present in dim_product")

    if violations:
        raise ValidationError("; ".join(violations))


def _build_star_schema(sources):
    """Derive the four modelled tables from the validated source data."""
    customers = sources['customers']
    products = sources['products']
    orders = sources['orders']
    order_items = sources['order_items']

    dim_customer = customers[['customer_id', 'first_name', 'last_name', 'email',
                               'registration_date', 'country', 'full_name']].drop_duplicates('customer_id')

    dim_product = products[['product_id', 'product_name', 'description', 'category', 'brand',
                             'price', 'cost', 'profit_margin', 'price_tier']].drop_duplicates('product_id')

    orders_dates = orders[['order_date', 'order_date_year', 'order_date_month', 'order_date_day',
                            'order_date_dayofweek', 'order_date_quarter', 'order_date_is_weekend']]
    dim_date = orders_dates.drop_duplicates('order_date').rename(columns={
        'order_date': 'date_key',
        'order_date_year': 'year',
        'order_date_month': 'month',
        'order_date_day': 'day',
        'order_date_dayofweek': 'day_of_week',
        'order_date_quarter': 'quarter',
        'order_date_is_weekend': 'is_weekend',
    })

    fact_sales = order_items.merge(
        orders[['order_id', 'customer_id', 'order_date', 'order_status']],
        on='order_id', how='left',
    )
    fact_sales['gross_revenue'] = fact_sales['item_total']
    fact_sales['net_revenue'] = fact_sales['gross_revenue'] - fact_sales['discount_amount']
    fact_sales['cost'] = fact_sales['quantity'] * fact_sales['product_id'].map(
        products.set_index('product_id')['cost']
    )
    fact_sales = fact_sales.rename(columns={'price': 'unit_price', 'order_date': 'date_key'})
    fact_sales = fact_sales[['item_id', 'order_id', 'customer_id', 'product_id', 'date_key',
                              'order_status', 'quantity', 'unit_price', 'discount_rate',
                              'discount_amount', 'gross_revenue', 'net_revenue', 'cost']]

    return {
        'dim_customer': dim_customer,
        'dim_product': dim_product,
        'dim_date': dim_date,
        'fact_sales': fact_sales,
    }


def _write_csv_mirror(tables):
    """Write the modelled star schema tables to data/processed/ as CSVs."""
    ensure_dir(PATHS['processed_data'])
    for name in LOAD_ORDER:
        save_dataframe(tables[name], name)


def _load_to_db(tables, engine):
    """Truncate and reload all four tables inside a single transaction."""
    with engine.begin() as conn:
        for name in TRUNCATE_ORDER:
            conn.execute(text(f"TRUNCATE TABLE {name} CASCADE"))
        for name in LOAD_ORDER:
            tables[name].to_sql(name, conn, if_exists='append', index=False)


def run_warehouse_load():
    """Build, validate, and load the star schema. Returns the modelled tables."""
    sources = _read_source_data()
    _validate_source_data(sources)
    tables = _build_star_schema(sources)
    _write_csv_mirror(tables)

    engine = get_db_connection()
    _load_to_db(tables, engine)

    logger.info("Warehouse load completed: %s", {name: len(df) for name, df in tables.items()})
    return tables


def main():
    try:
        run_warehouse_load()
    except ValidationError as exc:
        logger.error("Warehouse load validation failed: %s", exc)
        print(f"Warehouse load validation failed: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
