SELECT date_trunc('month', d.date_key)::date AS month,
       round(sum(f.net_revenue), 2) AS net_revenue,
       round(sum(f.gross_revenue), 2) AS gross_revenue,
       count(DISTINCT f.order_id) AS orders
FROM public.fact_sales f
JOIN public.dim_date d ON d.date_key = f.date_key
WHERE f.order_status IS DISTINCT FROM 'Cancelled'
GROUP BY date_trunc('month', d.date_key)::date
