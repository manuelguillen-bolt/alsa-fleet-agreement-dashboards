-- entity_week.sql  ·  metricas por entidad (vehiculo/conductor) para UNA semana
-- Validado contra el snapshot 2026-06-22 (trips/GMV/oh coinciden al centimo).
-- Placeholders que sustituye fetch.py:
--   :company_id   id de flota (112579 MM / 108683 IBL)
--   :pd_id        columna de entidad en partner_data  (driver_car_id MM / driver_id IBL)
--   :sl_id        columna de entidad en state_log     (car_id MM / driver_id IBL)
--   :week_start :week_end   fechas YYYY-MM-DD
-- Devuelve: entity_id | finished | dispatched | driver_cancelled | gmv | oh | peak_hours
WITH metrics AS (
  SELECT :pd_id AS entity_id,
    SUM(finished_rides)                    AS finished,
    SUM(order_tries_count)                 AS dispatched,
    SUM(driver_rejections_tries)           AS driver_cancelled,
    SUM(gmv_eur)                           AS gmv,
    SUM((has_order + waiting_orders)/60.0) AS oh
  FROM main.ng_public.etl_partner_data
  WHERE company_id = :company_id
    AND created_date_local BETWEEN DATE':week_start' AND DATE':week_end'
  GROUP BY :pd_id
),
peak_windows AS (
  SELECT col1 AS dow, col2 AS ws, col3 AS we FROM (VALUES
    (2,'00:00:00','05:00:00'),
    (5,'18:00:00','24:00:00'),
    (6,'00:00:00','05:00:00'),(6,'18:00:00','24:00:00'),
    (7,'00:00:00','05:00:00'),(7,'18:00:00','24:00:00'),
    (1,'00:00:00','05:00:00'),(1,'18:00:00','24:00:00')
  ) t(col1,col2,col3)
),
week_days AS (SELECT EXPLODE(SEQUENCE(DATE':week_start', DATE':week_end', INTERVAL 1 DAY)) AS d),
windows_with_ts AS (
  SELECT TIMESTAMP(CONCAT(wd.d,' ',pw.ws)) AS ws,
    CASE WHEN pw.we='24:00:00'
      THEN TIMESTAMP(CONCAT(DATE_ADD(wd.d,1),' 00:00:00'))
      ELSE TIMESTAMP(CONCAT(wd.d,' ',pw.we)) END AS we
  FROM week_days wd JOIN peak_windows pw ON DAYOFWEEK(wd.d)=pw.dow
),
states AS (
  SELECT :sl_id AS entity_id, created_ts_local AS ss,
    COALESCE(next_driver_state_ts_local, created_ts_local) AS se
  FROM main.core_models.fact_driver_state_log
  WHERE created_date_local BETWEEN DATE':week_start' AND DATE':week_end'
    AND driver_state IN ('has_order','waiting_orders')
),
peak AS (
  SELECT s.entity_id,
    SUM(GREATEST(0, UNIX_TIMESTAMP(LEAST(s.se,w.we)) - UNIX_TIMESTAMP(GREATEST(s.ss,w.ws)))/3600.0) AS peak_hours
  FROM states s CROSS JOIN windows_with_ts w GROUP BY s.entity_id
)
SELECT m.entity_id, m.finished, m.dispatched, m.driver_cancelled, m.gmv, m.oh,
       COALESCE(p.peak_hours,0) AS peak_hours
FROM metrics m LEFT JOIN peak p ON p.entity_id = m.entity_id
WHERE m.entity_id IS NOT NULL
ORDER BY m.gmv DESC
