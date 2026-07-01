-- entity_week.sql  ·  metricas por entidad (vehiculo/conductor) para UNA semana
-- Fuente unica: ng_public.etl_partner_data (diaria) + etl_partner_data_order (horaria, para peak).
-- etl_partner_data_order es la misma fuente que usa el Look de conexion por hora en Looker.
-- Validado: online reconcilia con etl_partner_data y peak <= online en todos los coches.
-- Placeholders (fetch.py): :company_id  :pd_id (driver_car_id MM / driver_id IBL)  :week_start :week_end
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
peak AS (
  -- online hours dentro de las ventanas punta del contrato (mismo (has_order+waiting_orders)/60),
  -- usando el grano horario de etl_partner_data_order.
  -- DAYOFWEEK: 1=Dom, 2=Lun, ... 7=Sab. Ventanas: Lun 00-05 · Jue 18-24 · Vie/Sab/Dom 00-05 y 18-24.
  SELECT :pd_id AS entity_id,
    SUM(CASE WHEN
      (DAYOFWEEK(created_hour_local)=2 AND HOUR(created_hour_local) BETWEEN 0 AND 4) OR
      (DAYOFWEEK(created_hour_local)=5 AND HOUR(created_hour_local) BETWEEN 18 AND 23) OR
      (DAYOFWEEK(created_hour_local) IN (6,7,1) AND
         (HOUR(created_hour_local) BETWEEN 0 AND 4 OR HOUR(created_hour_local) BETWEEN 18 AND 23))
      THEN (has_order + waiting_orders)/60.0 ELSE 0 END) AS peak_hours
  FROM main.ng_public.etl_partner_data_order
  WHERE company_id = :company_id
    AND created_hour_local >= DATE':week_start'
    AND created_hour_local <  DATE_ADD(DATE':week_end', 1)
  GROUP BY :pd_id
)
SELECT m.entity_id, m.finished, m.dispatched, m.driver_cancelled, m.gmv, m.oh,
       COALESCE(p.peak_hours, 0) AS peak_hours
FROM metrics m LEFT JOIN peak p ON p.entity_id = m.entity_id
WHERE m.entity_id IS NOT NULL
ORDER BY m.gmv DESC
