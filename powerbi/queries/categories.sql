SELECT p.category,
       round(sum(f.net_revenue), 2) AS net_revenue,
       round(sum(f.gross_revenue), 2) AS gross_revenue,
       count(DISTINCT f.order_id) AS orders
FROM public.fact_sales f
JOIN public.dim_product p ON p.product_id = f.product_id
WHERE f.order_status IS DISTINCT FROM 'Cancelled' AND p.category IS NOT NULL
GROUP BY p.category
