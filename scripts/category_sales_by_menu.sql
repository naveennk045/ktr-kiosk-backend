-- Category sales from orders.items × latest Petpooja menu (public.menus).
-- Line amount: SUM(quantity * unit_price) ex. tax. Only COMPLETED payments.
--
-- Allowed Petpooja category IDs (all other categories / unknown SKUs excluded):
--   9534536 Idli, 9534539 Wada/Snacks, 9534538 Bengaluru Dose, 9534537 Davanagere Dose,
--   9534540 Coffee, 9534541 Rice, 9593393 Extras, 9593400 Merchandise
--
-- Dates use orders.kot_date (business/KOT day). For calendar date on created_at in IST:
--   replace kot_date below with: (o.created_at AT TIME ZONE 'Asia/Kolkata')::date
--
-- Optional: AND o.channel = 'your_channel'
--
-- 3) Merchandise-only item report uses Petpooja category id 9593400 (see sku_merchandise CTE).


-- =============================================================================
-- 1) Date-wise category sales — one row per (sale_date, category)
-- =============================================================================
WITH latest_menu AS (
  SELECT data
  FROM menus
  WHERE provider = 'petpooja'
  ORDER BY id DESC
  LIMIT 1
),
categories AS (
  SELECT
    c.elem->>'categoryid'   AS category_id,
    c.elem->>'categoryname' AS category_name
  FROM latest_menu lm
  CROSS JOIN LATERAL jsonb_array_elements(lm.data->'categories') AS c(elem)
),
sku_category AS (
  SELECT
    i.elem->>'itemid' AS sku_code,
    cat.category_id,
    cat.category_name
  FROM latest_menu lm
  CROSS JOIN LATERAL jsonb_array_elements(lm.data->'items') AS i(elem)
  INNER JOIN categories cat ON cat.category_id = (i.elem->>'item_categoryid')
  WHERE cat.category_id IN (
    '9534536', '9534539', '9534538', '9534537',
    '9534540', '9534541', '9593393', '9593400'
  )
),
order_lines AS (
  SELECT
    o.kot_date AS sale_date,
    line.elem->>'sku_code' AS sku_code,
    (line.elem->>'quantity')::numeric   AS qty,
    (line.elem->>'unit_price')::numeric AS unit_price
  FROM orders o
  CROSS JOIN LATERAL jsonb_array_elements(o.items) AS line(elem)
  WHERE o.payment_status = 'COMPLETED'
)
SELECT
  ol.sale_date,
  sc.category_id,
  sc.category_name,
  SUM(ol.qty) AS total_quantity,
  SUM(ol.qty * ol.unit_price) AS total_amount_ex_tax
FROM order_lines ol
INNER JOIN sku_category sc ON sc.sku_code = ol.sku_code
GROUP BY ol.sale_date, sc.category_id, sc.category_name
ORDER BY ol.sale_date DESC, sc.category_name;


-- =============================================================================
-- 2) Category sales for a date range — one row per category (inclusive bounds)
-- =============================================================================
-- Replace start_date / end_date (inclusive) with your range, e.g. '2026-04-01' and '2026-04-13'.
WITH latest_menu AS (
  SELECT data
  FROM menus
  WHERE provider = 'petpooja'
  ORDER BY id DESC
  LIMIT 1
),
categories AS (
  SELECT
    c.elem->>'categoryid'   AS category_id,
    c.elem->>'categoryname' AS category_name
  FROM latest_menu lm
  CROSS JOIN LATERAL jsonb_array_elements(lm.data->'categories') AS c(elem)
),
sku_category AS (
  SELECT
    i.elem->>'itemid' AS sku_code,
    cat.category_id,
    cat.category_name
  FROM latest_menu lm
  CROSS JOIN LATERAL jsonb_array_elements(lm.data->'items') AS i(elem)
  INNER JOIN categories cat ON cat.category_id = (i.elem->>'item_categoryid')
  WHERE cat.category_id IN (
    '9534536', '9534539', '9534538', '9534537',
    '9534540', '9534541', '9593393', '9593400'
  )
),
order_lines AS (
  SELECT
    line.elem->>'sku_code' AS sku_code,
    (line.elem->>'quantity')::numeric   AS qty,
    (line.elem->>'unit_price')::numeric AS unit_price
  FROM orders o
  CROSS JOIN LATERAL jsonb_array_elements(o.items) AS line(elem)
  WHERE o.payment_status = 'COMPLETED'
    AND o.kot_date >= '2026-01-01'::date
    AND o.kot_date <= '2026-04-13'::date
)
SELECT
  sc.category_id,
  sc.category_name,
  SUM(ol.qty) AS total_quantity,
  SUM(ol.qty * ol.unit_price) AS total_amount_ex_tax
FROM order_lines ol
INNER JOIN sku_category sc ON sc.sku_code = ol.sku_code
GROUP BY sc.category_id, sc.category_name
ORDER BY total_amount_ex_tax DESC;


-- =============================================================================
-- 3) Merchandise sales till now — item-wise (units + revenue ex. tax)
-- =============================================================================
-- Only SKUs mapped to Petpooja category 9593400 (Merchandise) in the latest menu.
-- One row per (sku_code, item_name as stored on the order line).
WITH latest_menu AS (
  SELECT data
  FROM menus
  WHERE provider = 'petpooja'
  ORDER BY id DESC
  LIMIT 1
),
categories AS (
  SELECT
    c.elem->>'categoryid'   AS category_id,
    c.elem->>'categoryname' AS category_name
  FROM latest_menu lm
  CROSS JOIN LATERAL jsonb_array_elements(lm.data->'categories') AS c(elem)
),
sku_merchandise AS (
  SELECT i.elem->>'itemid' AS sku_code
  FROM latest_menu lm
  CROSS JOIN LATERAL jsonb_array_elements(lm.data->'items') AS i(elem)
  INNER JOIN categories cat ON cat.category_id = (i.elem->>'item_categoryid')
  WHERE cat.category_id = '9593400'
),
order_lines AS (
  SELECT
    line.elem->>'sku_code' AS sku_code,
    line.elem->>'item_name' AS item_name,
    (line.elem->>'quantity')::numeric   AS qty,
    (line.elem->>'unit_price')::numeric AS unit_price
  FROM orders o
  CROSS JOIN LATERAL jsonb_array_elements(o.items) AS line(elem)
  WHERE o.payment_status = 'COMPLETED'
)
SELECT
  ol.sku_code,
  ol.item_name,
  SUM(ol.qty) AS total_quantity,
  SUM(ol.qty * ol.unit_price) AS total_amount_ex_tax
FROM order_lines ol
INNER JOIN sku_merchandise sm ON sm.sku_code = ol.sku_code
GROUP BY ol.sku_code, ol.item_name
ORDER BY total_amount_ex_tax DESC;
