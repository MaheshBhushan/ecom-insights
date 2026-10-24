-- Monthly revenue over revenue statuses. NULL statuses remain included, as in compute_kpis().
SELECT date_trunc('month', d.date_key)::date AS month,
       round(sum(f.gross_revenue), 2) AS gross_revenue,
       round(sum(f.discount_amount), 2) AS discount_amount,
       round(sum(f.net_revenue), 2) AS net_revenue,
       round(sum(f.cost), 2) AS cost,
       count(DISTINCT f.order_id) AS orders
FROM public.fact_sales f
JOIN public.dim_date d ON d.date_key = f.date_key
WHERE f.order_status IS DISTINCT FROM 'Cancelled'
GROUP BY 1
