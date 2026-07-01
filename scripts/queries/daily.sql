-- daily.sql  ·  serie diaria de flota (todo el mes)
-- Placeholders: :company_id  :start  :end  (YYYY-MM-DD)
-- Devuelve: date | finished | dispatched | gmv | oh
SELECT created_date_local                  AS date,
  SUM(finished_rides)                      AS finished,
  SUM(order_tries_count)                   AS dispatched,
  SUM(gmv_eur)                             AS gmv,
  SUM((has_order + waiting_orders)/60.0)   AS oh
FROM main.ng_public.etl_partner_data
WHERE company_id = :company_id
  AND created_date_local BETWEEN DATE':start' AND DATE':end'
GROUP BY created_date_local
ORDER BY created_date_local
