-- NULL counts for every nullable warehouse column, plus calendar gaps.
SELECT 'fact_sales' AS table_name, col AS column_name, total_rows, missing_rows
FROM (SELECT count(*) AS total_rows,
             count(*) FILTER (WHERE order_status IS NULL) AS order_status,
             count(*) FILTER (WHERE discount_rate IS NULL) AS discount_rate,
             count(*) FILTER (WHERE discount_amount IS NULL) AS discount_amount,
             count(*) FILTER (WHERE cost IS NULL) AS cost
      FROM public.fact_sales) t
CROSS JOIN LATERAL (VALUES ('order_status', t.order_status), ('discount_rate', t.discount_rate),
                           ('discount_amount', t.discount_amount), ('cost', t.cost)) v(col, missing_rows)
UNION ALL
SELECT 'dim_product', col, total_rows, missing_rows
FROM (SELECT count(*) AS total_rows,
             count(*) FILTER (WHERE description IS NULL) AS description,
             count(*) FILTER (WHERE category IS NULL) AS category,
             count(*) FILTER (WHERE brand IS NULL) AS brand,
             count(*) FILTER (WHERE cost IS NULL) AS cost,
             count(*) FILTER (WHERE profit_margin IS NULL) AS profit_margin,
             count(*) FILTER (WHERE price_tier IS NULL) AS price_tier
      FROM public.dim_product) t
CROSS JOIN LATERAL (VALUES ('description', t.description), ('category', t.category),
                           ('brand', t.brand), ('cost', t.cost), ('profit_margin', t.profit_margin),
                           ('price_tier', t.price_tier)) v(col, missing_rows)
UNION ALL
SELECT 'dim_customer', col, total_rows, missing_rows
FROM (SELECT count(*) AS total_rows,
             count(*) FILTER (WHERE country IS NULL) AS country,
             count(*) FILTER (WHERE full_name IS NULL) AS full_name
      FROM public.dim_customer) t
CROSS JOIN LATERAL (VALUES ('country', t.country), ('full_name', t.full_name)) v(col, missing_rows)
UNION ALL
-- Calendar days between the first and last sale with no fact rows of any status.
SELECT 'dim_date', 'days_without_sales',
       count(*), count(*) FILTER (WHERE NOT EXISTS
           (SELECT 1 FROM public.fact_sales f WHERE f.date_key = d.date_key))
FROM public.dim_date d
WHERE d.date_key BETWEEN (SELECT min(date_key) FROM public.fact_sales)
                     AND (SELECT max(date_key) FROM public.fact_sales)
