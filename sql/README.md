# SQL Scripts for E-commerce Data Pipeline

This directory contains the warehouse star schema for the e-commerce data pipeline.

## Scripts

1. **star_schema.postgres.sql** - The schema actually loaded by `src/load/warehouse_loader.py` (via `python -m src.main --load`). Runs against local Postgres.
2. **star_schema.azuresql.sql** - T-SQL equivalent, documenting the Azure SQL cloud target. Not executed anywhere in this project (the project's Azure subscription is disabled/read-only).

## Database Schema

Star schema, grain of `fact_sales` = one row per order line item:

- `dim_customer` - Customer dimension
- `dim_product` - Product dimension
- `dim_date` - Date dimension (one row per order date)
- `fact_sales` - Order line item facts, FK'd to the three dimensions above

## Usage

Start local Postgres (see `docker-compose.yml` in the repo root), then apply the schema:

```bash
docker compose up -d
psql "$DATABASE_URL" -f sql/star_schema.postgres.sql
```

Load the star schema from the transformed CSVs:

```bash
python -m src.main --load
```

## Database Connection

The data pipeline connects to the database via `DATABASE_URL` (see `.env.example` in the repo root and `src/config.py`). 