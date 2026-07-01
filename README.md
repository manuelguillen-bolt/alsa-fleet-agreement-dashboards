# Fleet Agreement Tracker

Dashboards estáticos (GitHub Pages) de cualificación semanal y guaranteed payout por flota.
Mismo contrato base: 28 €/h EPH neto garantizado, 25% comisión, 10% IVA, mínimo 32 peak hours y 85% completion rate.

## Cómo funciona

Las páginas son HTML estático que cargan React + Recharts desde CDN y leen su `data/<id>.json`.
Un GitHub Action consulta Databricks los lunes (cada hora 09:00–17:00 Madrid, reintentando hasta que
el ETL tenga la semana), regenera esos JSON y hace commit; Pages se redepliega solo.

Idioma: botón ES/EN arriba a la derecha (por defecto español; recuerda la elección en el navegador).
Semanas: el calendario es dinámico — cada lunes avanza solo a la última semana cerrada (a semana vencida).

```
index.html              landing con las flotas
f/<id>.html             dashboard de cada flota (fetch de data/<id>.json)
assets/app.vehicle.js   app compilada (flota por vehículo)
assets/app.driver.js    app compilada (flota por conductor)
data/<id>.json          datos (se actualizan solos cada semana)
config/<id>.json        config estática: contrato, peak windows, calendario, matrículas/nombres
scripts/fetch.py        Databricks -> data/<id>.json
scripts/enrich.py       lógica de cualificación (validada vs snapshot)
scripts/queries/*.sql   <-- ÚNICO punto a completar con la query real
.github/workflows/refresh.yml   cron semanal (lunes 06:00 UTC)
```

## Puesta en marcha

1. Crear un repo en GitHub y subir esta carpeta (`git init`, `add`, `commit`, `push`).
2. **Settings → Pages**: Source = `Deploy from a branch`, branch `main`, carpeta `/ (root)`.
   La URL será `https://<usuario>.github.io/<repo>/`.
3. **Settings → Secrets and variables → Actions** → añadir:
   - `DATABRICKS_HOST` (ej. `https://xxx.cloud.databricks.com`)
   - `DATABRICKS_TOKEN`
   - `DATABRICKS_WAREHOUSE_ID`
4. Completar las 3 queries en `scripts/queries/` (ver columnas requeridas en cada archivo).
5. **Actions → Refresh fleet data → Run workflow** para la primera carga.

> Los secrets se añaden en la interfaz de GitHub; no se guardan en el repo ni los gestiona nadie más.

## Añadir una flota

1. `config/<nuevo_id>.json` con su contrato, peak windows y calendario.
2. Añadir la flota a `fleets.json` y a `FLEETS` en `scripts/fetch.py`.
3. Copiar un `f/<id>.html` cambiando el id y el `app.<entity>.js`.

## Nota de privacidad

Con GitHub Pages **público**, cualquiera con el link ve GMV, payouts y cualificación.
Para restringir a Fleet Owners hace falta hosting con login (Pages privado Enterprise, o Cloudflare/Vercel con auth).

## Fuentes de datos (validadas vs snapshot 2026-06-22)

- `main.ng_public.etl_partner_data` — viajes, GMV y online hours por día/entidad
- `main.core_models.fact_driver_state_log` — estados del conductor (peak hours)

Mapeo: `finished`=SUM(finished_rides), `dispatched`=SUM(order_tries_count),
`driver_cancelled`=SUM(driver_rejections_tries), `gmv`=SUM(gmv_eur),
`oh`=SUM((has_order+waiting_orders)/60), `peak_hours`=online intersectado con ventanas del contrato.
MM (112579) por `driver_car_id`/`car_id`; IBL (108683) por `driver_id`.

## Estado

Pipeline cableado y reconciliado: trips, GMV, online hours y agregados semanales coinciden
**al céntimo** con el snapshot. Las peak hours pueden variar ~3-4% por eventos de estado que
llegan tarde al `fact_driver_state_log` (no altera la cualificación de 32h en los casos vistos).
Listo para subir: añade los 3 secrets de Databricks y ejecuta el workflow.
