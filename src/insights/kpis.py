"""
Deterministic KPI computation for the executive briefing (T5).

Reads only from the verified Postgres warehouse (fact_sales + dims). No LLM
is involved in this module -- every figure here is a plain SQL aggregation,
so anything the briefing model later reports must trace back to a number
computed here.
"""
import json
import os

import pandas as pd

from src.config import PATHS
from src.utils import ensure_dir, get_db_connection

KPIS_PATH = os.path.join(PATHS['reports'], 'kpis.json')

# Cancelled orders never realized revenue -- excluded from every revenue,
# margin, and AOV figure below. Their volume is still reported separately
# (cancelled_order_count / cancelled_order_share_pct) so it isn't hidden.
REVENUE_EXCLUDED_STATUSES = ['Cancelled']


def _load_fact_sales(engine):
    """Load fact_sales joined to dim_product for category rollups."""
    query = """
        SELECT f.order_id, f.customer_id, f.product_id, f.date_key, f.order_status,
               f.quantity, f.gross_revenue, f.net_revenue, f.discount_amount, f.cost,
               p.category
        FROM fact_sales f
        JOIN dim_product p ON p.product_id = f.product_id
    """
    return pd.read_sql(query, engine)


def compute_kpis():
    """Compute the KPI set from the warehouse. Returns a plain JSON-safe dict."""
    engine = get_db_connection()
    df = _load_fact_sales(engine)

    period_start = str(df['date_key'].min())
    period_end = str(df['date_key'].max())

    total_customers = int(df['customer_id'].nunique())

    revenue_df = df[~df['order_status'].isin(REVENUE_EXCLUDED_STATUSES)]
    cancelled_df = df[df['order_status'].isin(REVENUE_EXCLUDED_STATUSES)]

    total_orders = int(revenue_df['order_id'].nunique())
    gross_revenue_total = round(float(revenue_df['gross_revenue'].sum()), 2)
    net_revenue_total = round(float(revenue_df['net_revenue'].sum()), 2)
    total_discount_amount = round(float(revenue_df['discount_amount'].sum()), 2)
    total_cost = round(float(revenue_df['cost'].sum()), 2)

    average_order_value_net = (
        round(net_revenue_total / total_orders, 2) if total_orders else None
    )
    gross_margin_pct = (
        round((net_revenue_total - total_cost) / net_revenue_total * 100, 2)
        if net_revenue_total else None
    )

    orders_per_customer = revenue_df.groupby('customer_id')['order_id'].nunique()
    customers_with_orders = int(orders_per_customer.shape[0])
    repeat_customers = int((orders_per_customer > 1).sum())
    repeat_customer_rate_pct = (
        round(repeat_customers / customers_with_orders * 100, 2)
        if customers_with_orders else None
    )

    category_revenue = (
        revenue_df.groupby('category')['net_revenue'].sum().sort_values(ascending=False)
    )
    top_category = {
        "category": str(category_revenue.index[0]),
        "net_revenue": round(float(category_revenue.iloc[0]), 2),
    }
    weakest_category = {
        "category": str(category_revenue.index[-1]),
        "net_revenue": round(float(category_revenue.iloc[-1]), 2),
    }

    cancelled_order_count = int(cancelled_df['order_id'].nunique())
    total_order_count_all_statuses = int(df['order_id'].nunique())
    cancelled_order_share_pct = (
        round(cancelled_order_count / total_order_count_all_statuses * 100, 2)
        if total_order_count_all_statuses else None
    )

    kpis = {
        "period_start": period_start,
        "period_end": period_end,
        "order_statuses_included_in_revenue": sorted(revenue_df['order_status'].unique().tolist()),
        "order_statuses_excluded_from_revenue": REVENUE_EXCLUDED_STATUSES,
        "revenue_basis_note": (
            "gross_revenue_total is the pre-discount line total "
            "(sum of fact_sales.gross_revenue); net_revenue_total is "
            "gross_revenue minus discount_amount (sum of fact_sales.net_revenue). "
            "Both exclude Cancelled orders. gross_margin_pct uses the net_revenue "
            "basis: (net_revenue_total - total_cost) / net_revenue_total. The "
            "analysis layer (src/analysis) has no post-discount revenue "
            "definition of its own -- this margin is defined here, on net_revenue."
        ),
        "total_orders": total_orders,
        "total_customers": total_customers,
        "gross_revenue_total": gross_revenue_total,
        "net_revenue_total": net_revenue_total,
        "total_discount_amount": total_discount_amount,
        "total_cost": total_cost,
        "average_order_value_net": average_order_value_net,
        "gross_margin_pct": gross_margin_pct,
        "gross_margin_basis": "net_revenue",
        "repeat_customer_rate_pct": repeat_customer_rate_pct,
        "top_category": top_category,
        "weakest_category": weakest_category,
        "cancelled_order_count": cancelled_order_count,
        "cancelled_order_share_pct": cancelled_order_share_pct,
    }
    return kpis


def write_kpis(path=None):
    """Compute KPIs and write them to reports/kpis.json (deterministic, sorted keys)."""
    path = path or KPIS_PATH
    kpis = compute_kpis()
    ensure_dir(os.path.dirname(path))
    with open(path, 'w') as f:
        json.dump(kpis, f, indent=2, sort_keys=True)
        f.write('\n')
    return kpis


if __name__ == '__main__':
    write_kpis()
    print(f"Wrote {KPIS_PATH}")
