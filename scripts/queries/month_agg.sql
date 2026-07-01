-- month_agg.sql  ·  agregado de flota para una ventana (para baseline MoM)
-- Placeholders: :company_id  :pd_id  :start  :end
-- Devuelve: finished | dispatched | gmv | oh | active
SELECT
  SUM(finished_rides)                      AS finished,
  SUM(order_tries_count)                   AS dispatched,
  SUM(gmv_eur)                             AS gmv,
  SUM((has_order + waiting_orders)/60.0)   AS oh,
  COUNT(DISTINCT CASE WHEN finished_rides > 0 THEN :pd_id END) AS active
FROM main.ng_public.etl_partner_data
WHERE company_id = :company_id
  AND created_date_local BETWEEN DATE':start' AND DATE':end'
