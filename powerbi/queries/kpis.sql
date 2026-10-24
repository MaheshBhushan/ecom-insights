-- Full-warehouse snapshot. NULL statuses remain included, as in compute_kpis().
WITH sales AS (
    SELECT f.*, p.category
    FROM public.fact_sales f
    JOIN public.dim_product p ON p.product_id = f.product_id
), revenue AS (
    SELECT * FROM sales WHERE order_status IS DISTINCT FROM 'Cancelled'
), totals AS (
    SELECT count(DISTINCT order_id) AS total_orders,
           round(coalesce(sum(gross_revenue), 0), 2) AS gross_revenue_total,
           round(coalesce(sum(net_revenue), 0), 2) AS net_revenue_total,
           round(coalesce(sum(discount_amount), 0), 2) AS total_discount_amount,
           round(coalesce(sum(cost), 0), 2) AS total_cost
    FROM revenue
), customer_orders AS (
    SELECT customer_id, count(DISTINCT order_id) AS orders
    FROM revenue WHERE customer_id IS NOT NULL GROUP BY customer_id
), categories AS (
    SELECT category, round(sum(net_revenue), 2) AS net_revenue
    FROM revenue WHERE category IS NOT NULL GROUP BY category
)
SELECT t.*,
       (SELECT count(DISTINCT customer_id) FROM sales) AS total_customers,
       (SELECT min(date_key) FROM sales) AS period_start,
       (SELECT max(date_key) FROM sales) AS period_end,
       round(net_revenue_total / nullif(total_orders, 0), 2) AS average_order_value_net,
       round((net_revenue_total - total_cost) * 100 / nullif(net_revenue_total, 0), 2) AS gross_margin_pct,
       (SELECT round(count(*) FILTER (WHERE orders > 1) * 100.0 / nullif(count(*), 0), 2)
        FROM customer_orders) AS repeat_customer_rate_pct,
       (SELECT count(DISTINCT order_id) FROM sales WHERE order_status = 'Cancelled') AS cancelled_order_count,
       (SELECT round(count(DISTINCT order_id) FILTER (WHERE order_status = 'Cancelled') * 100.0
                     / nullif(count(DISTINCT order_id), 0), 2) FROM sales) AS cancelled_order_share_pct,
       (SELECT category FROM categories ORDER BY net_revenue DESC, category LIMIT 1) AS top_category,
       (SELECT net_revenue FROM categories ORDER BY net_revenue DESC, category LIMIT 1) AS top_category_net_revenue,
       (SELECT category FROM categories ORDER BY net_revenue, category DESC LIMIT 1) AS weakest_category,
       (SELECT net_revenue FROM categories ORDER BY net_revenue, category DESC LIMIT 1) AS weakest_category_net_revenue,
       (SELECT string_agg(DISTINCT order_status, ', ' ORDER BY order_status) FROM revenue) AS included_statuses,
       'Cancelled'::text AS excluded_statuses,
       'net_revenue'::text AS gross_margin_basis
FROM totals t
