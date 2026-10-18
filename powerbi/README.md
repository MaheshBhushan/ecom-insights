# Power BI warehouse report

Open [EcomInsights.pbip](EcomInsights.pbip) in current Power BI Desktop on
Windows. The project contains an import-mode semantic model and a native PBIR
report with two pages:

- **Revenue and customers:** net revenue, revenue orders, net AOV, net-basis
  gross margin, cancellation share, repeat-customer rate, monthly net revenue,
  and category net revenue.
- **KPI definitions and audit:** every numeric KPI, reporting period, included
  and excluded statuses, top and weakest category, and margin basis.

The data is synthetic. The repeat-customer rate reflects the sample generator
and does not establish real customer retention.

## Connect and refresh

1. Load the PostgreSQL star schema using the repository's Quickstart. Use an
   existing loaded warehouse if one is available. The report executes only
   `SELECT` statements against `public.fact_sales`, `public.dim_product`, and
   `public.dim_date`.
2. Open the project. It contains source definitions and no imported data cache.
3. In **Transform data > Edit parameters**, set `WarehouseServer` and
   `WarehouseDatabase`. Defaults match the repository's Compose configuration:
   `localhost:5433` and `ecommerce`. For a remote Desktop machine, use the
   PostgreSQL host reachable from that machine.
4. Choose **Refresh**, approve the native read-only SQL queries, and provide
   database credentials through Power BI's data source dialog. Credentials
   belong in Power BI's credential store. The project does not store them.
   The local sample database uses the development credentials documented in
   `docker-compose.yml`.
5. Verify the reporting period on the overview page. Refresh after each
   completed warehouse load. Keep the warehouse stable during refresh because
   the three imports run separate queries.

Power BI Desktop can open PBIP projects without a tenant connection. Publishing
and scheduled refresh require the user's Power BI access and an appropriate
gateway for a private PostgreSQL server. This repository does not provision
those services.

## Metric contract

[queries/kpis.sql](queries/kpis.sql) computes a one-row snapshot from the
warehouse. [queries/monthly.sql](queries/monthly.sql) and
[queries/categories.sql](queries/categories.sql) provide chart series.
Power Query embeds these SQL statements in the semantic model. DAX only
selects a snapshot value or sums chart rows; it introduces no separate KPI
formulas.

- Revenue orders count distinct order IDs. Fact rows represent line items.
- Gross revenue sums pre-discount line totals. Net revenue subtracts discounts.
  Both exclude Cancelled orders. Shipping and tax are excluded.
- Cost, net AOV, net-basis margin, and repeat-customer rate exclude Cancelled
  orders. Repeat rate divides customers with multiple distinct revenue orders
  by customers with any revenue orders.
- Customer count includes customers with only Cancelled orders. Cancellation
  share divides distinct cancelled orders by distinct orders of all statuses.
- Dates cover every status. NULL statuses remain included in revenue, matching
  `compute_kpis()`. Financial totals round to cents before the AOV and margin
  calculations. Percentages use percentage points with a literal `%` format.
- Top and weakest categories use net revenue. Ties use alphabetical order
  (first for top, last for weakest).
- The report shows a full-warehouse snapshot. It has no slicers or relationships
  between its three aggregate tables. Chart selections do not filter other
  visuals. This keeps the cards comparable with `reports/kpis.json`.

## Reconciliation and maintenance

Install `requirements.txt` in the repository's `venv`. Tests require Docker
and the local `postgres:16-alpine` image. Obtain the image with
`docker pull postgres:16-alpine` if it is absent.

```bash
venv/bin/python -m pytest -q tests/test_powerbi.py tests/test_office_reports.py tests/test_grounding.py
```

The tests run the **SQL embedded in the committed model** against a disposable
PostgreSQL instance. They load the committed star-schema CSVs and compare every
numeric KPI, date, status list, and category result with `compute_kpis()` and
`reports/kpis.json`. Chart totals reconcile to those KPIs. Additional fixtures
cover multiple items per order, a cancelled-only customer, NULL statuses, zero
net revenue, cancelled-only data, and an empty fact table. Tests also validate
PBIR against pinned Microsoft schemas and check every visual's field binding.
The existing Office and grounding tests remain part of the check.

SQL changes require regeneration:

```bash
venv/bin/python -m src.reporting.powerbi_project
```

The generator overwrites the committed project definitions. Keep report layout
changes in the generator so regeneration preserves them.

Automated checks validate PostgreSQL calculations, schemas, and bindings.
Power BI Desktop rendering, Power Query execution, and service publication
have not been exercised on this Linux host. After the first Desktop refresh,
check the two report pages and compare the audit page with a fresh
`python -m src.insights.kpis` result from the same unchanged warehouse.

Microsoft documents the [PBIR report format](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-report),
the [TMSL semantic model format](https://learn.microsoft.com/en-us/power-bi/developer/projects/projects-dataset),
and the [PostgreSQL Power Query connector](https://learn.microsoft.com/en-us/powerquery-m/postgresql-database).
