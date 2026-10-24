# Tableau warehouse validation dashboard

Open [EcomInsights.twb](EcomInsights.twb) in Tableau Desktop. The workbook
connects to the PostgreSQL star schema and contains one dashboard,
**Warehouse validation**, with three worksheets:

- **Monthly net revenue:** net revenue per month over revenue statuses.
- **Cohort activity:** customers grouped by first revenue month, with active
  customers per month since the first order.
- **Missing values:** NULL counts per nullable warehouse column and calendar
  days without sales.

The data is synthetic. Cohort activity reflects the sample generator.

## Connect

1. Load the PostgreSQL warehouse with the repository Quickstart.
2. Open the workbook. Each data source points to `localhost:5433/ecommerce`,
   the Compose default. Edit the connection if the server differs.
3. Enter database credentials when Tableau prompts. The workbook stores no
   username or password.

## Source lineage

| Data source | Custom SQL | Warehouse tables | Reconciles with |
|---|---|---|---|
| Revenue | [queries/revenue_monthly.sql](queries/revenue_monthly.sql) | `fact_sales`, `dim_date` | `powerbi/queries/kpis.sql` gross, net, discount, cost, and order totals; `reports/kpis.json` |
| Cohorts | [queries/cohorts.sql](queries/cohorts.sql) | `fact_sales` | `kpis.sql` net revenue; month-0 size equals customers with revenue orders |
| Missing Data | [queries/missing_data.sql](queries/missing_data.sql) | `fact_sales`, `dim_product`, `dim_customer`, `dim_date` | NULL counts in the loaded star-schema CSVs |

All revenue views exclude Cancelled orders and keep NULL statuses, matching
`compute_kpis()`. The warehouse tables come from `src/load/warehouse_loader.py`
and the DDL in `sql/star_schema.postgres.sql`.

## Reconciliation

```bash
venv/bin/python -m pytest -q tests/test_tableau.py
```

The test reads the SQL embedded in the committed workbook. It loads the
committed star-schema CSVs and an edge-case fixture into a disposable,
network-isolated `postgres:16-alpine` container. It sums each visual's rows and
compares them with the Power BI KPI query and `reports/kpis.json`. It also
checks missing-value counts against pandas and verifies worksheet field
bindings.

SQL changes require regeneration:

```bash
venv/bin/python -m src.reporting.tableau_workbook
```

Automated checks cover the SQL results and the workbook XML structure. Tableau
Desktop rendering has not been exercised on this Linux host.
