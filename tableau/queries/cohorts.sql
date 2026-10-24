-- Customers grouped by the month of their first revenue order.
-- months_since_first = 0 holds each cohort's full size.
WITH activity AS (
    SELECT f.customer_id, date_trunc('month', f.date_key)::date AS month,
           sum(f.net_revenue) AS net_revenue
    FROM public.fact_sales f
    WHERE f.order_status IS DISTINCT FROM 'Cancelled'
    GROUP BY 1, 2
), firsts AS (
    SELECT customer_id, min(month) AS cohort_month FROM activity GROUP BY 1
)
SELECT c.cohort_month,
       ((extract(year FROM a.month) - extract(year FROM c.cohort_month)) * 12
        + extract(month FROM a.month) - extract(month FROM c.cohort_month))::int AS months_since_first,
       count(*) AS active_customers,
       round(sum(a.net_revenue), 2) AS net_revenue
FROM activity a
JOIN firsts c ON c.customer_id = a.customer_id
GROUP BY 1, 2
