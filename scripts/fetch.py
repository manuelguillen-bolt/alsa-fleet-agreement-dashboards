#!/usr/bin/env python3
"""Refresca data/<id>.json consultando Databricks.

Fuentes (validadas contra el snapshot 2026-06-22):
  main.ng_public.etl_partner_data        viajes, GMV y online hours por dia/entidad
  main.core_models.fact_driver_state_log estados del conductor (para peak hours)

Mapeo de columnas:
  finished         = SUM(finished_rides)
  dispatched       = SUM(order_tries_count)
  driver_cancelled = SUM(driver_rejections_tries)
  gmv              = SUM(gmv_eur)
  oh               = SUM((has_order + waiting_orders)/60.0)
  peak_hours       = online (has_order|waiting_orders) intersectado con ventanas del contrato

Granularidad: MM (112579) por driver_car_id/car_id ; IBL (108683) por driver_id.

Secrets/env (GitHub -> Settings -> Secrets -> Actions):
  DATABRICKS_HOST  DATABRICKS_TOKEN  DATABRICKS_WAREHOUSE_ID
"""
import os, sys, json, time, datetime as dt, urllib.request
sys.path.insert(0, os.path.dirname(__file__))
from enrich import enrich_entity, calc_net, calc_eph

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HOST = os.environ.get("DATABRICKS_HOST", "").rstrip("/")
TOKEN = os.environ.get("DATABRICKS_TOKEN", "")
WAREHOUSE = os.environ.get("DATABRICKS_WAREHOUSE_ID", "")

FLEETS = [
    {"id": 112579, "entity": "vehicle", "id_key": "vehicle_id",
     "pd_id": "driver_car_id", "sl_id": "car_id", "coll": "VEHICLES", "labels": "VEHICLE_PLATES",
     "label_table": "main.core_models.dim_car", "label_id": "car_id", "label_col": "car_reg_number"},
    {"id": 108683, "entity": "driver", "id_key": "driver_id",
     "pd_id": "driver_id", "sl_id": "driver_id", "coll": "DRIVERS", "labels": "DRIVER_NAMES",
     "label_table": "main.ng_public.driver_earnings_driver", "label_id": "driver_id", "label_col": "name"},
]


def get_labels(fleet, ids):
    """Matriculas (coche) o nombres (conductor) para TODAS las entidades presentes."""
    ids = [i for i in ids if i]
    if not ids:
        return {}
    idlist = ",".join(str(int(i)) for i in sorted(set(ids)))
    rows = run_sql(f"SELECT {fleet['label_id']} AS eid, {fleet['label_col']} AS lbl "
                   f"FROM {fleet['label_table']} WHERE {fleet['label_id']} IN ({idlist})")
    out = {}
    for r in rows:
        lbl = r.get("lbl")
        if lbl not in (None, ""):
            out[str(int(num(r["eid"])))] = lbl
    return out


def run_sql(query):
    body = json.dumps({"warehouse_id": WAREHOUSE, "statement": query,
                       "wait_timeout": "50s", "format": "JSON_ARRAY"}).encode()
    req = urllib.request.Request(f"{HOST}/api/2.0/sql/statements", data=body, method="POST",
        headers={"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"})
    res = json.load(urllib.request.urlopen(req))
    sid = res["statement_id"]
    while res["status"]["state"] in ("PENDING", "RUNNING"):
        time.sleep(2)
        req = urllib.request.Request(f"{HOST}/api/2.0/sql/statements/{sid}",
            headers={"Authorization": f"Bearer {TOKEN}"})
        res = json.load(urllib.request.urlopen(req))
    if res["status"]["state"] != "SUCCEEDED":
        raise RuntimeError(f"SQL fallo: {res['status']}")
    cols = [c["name"] for c in res["manifest"]["schema"]["columns"]]
    return [dict(zip(cols, v)) for v in res["result"].get("data_array", [])]


def load_query(name, **subs):
    sql = open(os.path.join(ROOT, "scripts", "queries", name)).read()
    for k, v in subs.items():
        sql = sql.replace(f":{k}", str(v))
    return sql


def num(v):
    return float(v) if v not in (None, "") else 0.0


def build_fleet(fleet):
    cfg = json.load(open(os.path.join(ROOT, "config", f"{fleet['id']}.json")))
    c = cfg["CONTRACT"]
    idk = fleet["id_key"]

    # Calendario dinamico: una semana esta "vencida" (completa) cuando ya termino.
    # Asi cada lunes el dashboard avanza solo a la ultima semana cerrada.
    today = dt.date.today()
    months = json.loads(json.dumps(cfg["MONTHS"]))
    for m in months.values():
        for w in m["weeks"]:
            ws = dt.date.fromisoformat(w["start"]); we = dt.date.fromisoformat(w["end"])
            w["complete"] = we < today
            w["inProgress"] = ws <= today <= we
    weeks_meta = {w["label"]: w for m in months.values() for w in m["weeks"] if w["complete"]}

    coll, weekly = {}, []
    for label, w in weeks_meta.items():
        rows = run_sql(load_query("entity_week.sql", company_id=fleet["id"],
                                  pd_id=fleet["pd_id"], sl_id=fleet["sl_id"],
                                  week_start=w["start"], week_end=w["end"]))
        raw = [{idk: int(num(r["entity_id"])), "finished": int(num(r["finished"])),
                "dispatched": int(num(r["dispatched"])), "driver_cancelled": int(num(r["driver_cancelled"])),
                "gmv": round(num(r["gmv"]), 2), "oh": round(num(r["oh"]), 2),
                "peak_hours": round(num(r["peak_hours"]), 2)} for r in rows]
        coll[label] = enrich_entity(raw, c, idk)
        ft = sum(e["finished"] for e in coll[label]); dsp = sum(e["dispatched"] for e in coll[label])
        g = sum(e["gmv"] for e in coll[label]); o = sum(e["oh"] for e in coll[label])
        qual = sum(1 for e in coll[label] if e["qualifies"]); tot = len(coll[label])
        weekly.append({"week": label, "start": w["start"], "end": w["end"],
                       "finished_trips": ft, "dispatched_trips": dsp, "gmv": round(g, 2), "oh": round(o, 2),
                       "fr": ft / dsp if dsp else 0, "net_eph": calc_eph(g, o, c),
                       "qualifying_pct": (qual / tot * 100) if tot else 0,
                       "net_revenue": calc_net(g, c),
                       "payout": sum(e["payout"] for e in coll[label]), "trips": ft})

    # serie diaria de todo el mes (min start .. max end de semanas completas)
    starts = [w["start"] for w in weeks_meta.values()]; ends = [w["end"] for w in weeks_meta.values()]
    daily_rows = run_sql(load_query("daily.sql", company_id=fleet["id"],
                                    start=min(starts), end=max(ends))) if starts else []
    daily = [{"date": d["date"], "finished": int(num(d["finished"])),
              "dispatched": int(num(d["dispatched"])), "gmv": round(num(d["gmv"]), 2),
              "oh": round(num(d["oh"]), 2)} for d in daily_rows]

    out = {"CONTRACT": c, "PEAK_HOURS": cfg["PEAK_HOURS"], "MONTHS": months,
           fleet["coll"]: coll, "WEEKLY": weekly, "DAILY": daily}
    # etiquetas (matriculas/nombres) para TODAS las entidades presentes, desde Databricks
    all_ids = {e[idk] for wk in coll.values() for e in wk}
    labels = get_labels(fleet, all_ids)
    if fleet["labels"] in cfg:  # fusiona: dinamico manda, config como respaldo
        merged = dict(cfg[fleet["labels"]]); merged.update(labels); labels = merged
    out[fleet["labels"]] = labels

    if weekly:
        g = sum(w["gmv"] for w in weekly); o = sum(w["oh"] for w in weekly)
        f = sum(w["finished_trips"] for w in weekly); ds = sum(w["dispatched_trips"] for w in weekly)
        nr = calc_net(g, c)
        qids, aids = set(), set()
        for wk in coll.values():
            qids |= {e[idk] for e in wk if e["qualifies"]}
            aids |= {e[idk] for e in wk if e["finished"] > 0}
        key = "qualifying_vehicles" if fleet["entity"] == "vehicle" else "qualifying_drivers"
        out["MTD_JUNE"] = {"gmv": round(g, 2), "net_revenue_after_vat": nr,
                           "total_guarantee_payout": sum(w["payout"] for w in weekly),
                           "finished_trips": f, "online_hours": round(o, 2),
                           "active_cars": len(aids),
                           "net_eph_after_vat": nr / o if o else 0,
                           "rph": f / o if o else 0, "fleet_fr": f / ds if ds else 0, key: len(qids)}

        # baseline MoM like-for-like: misma ventana de dias en el mes anterior
        mtd_start = dt.date.fromisoformat(min(starts))
        mtd_end = dt.date.fromisoformat(max(ends))
        n_days = (mtd_end - mtd_start).days + 1
        prev_first = (mtd_start.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
        prev_end = prev_first + dt.timedelta(days=n_days - 1)
        agg = run_sql(load_query("month_agg.sql", company_id=fleet["id"], pd_id=fleet["pd_id"],
                                 start=prev_first.isoformat(), end=prev_end.isoformat()))
        if agg:
            a = agg[0]; pg = num(a["gmv"]); po = num(a["oh"]); pnr = calc_net(pg, c)
            pf = int(num(a["finished"])); pds = int(num(a["dispatched"]))
            prev = {"gmv": round(pg, 2), "net_revenue_after_vat": pnr, "total_guarantee_payout": None,
                    "finished_trips": pf, "online_hours": round(po, 2), "active_cars": int(num(a["active"])),
                    "utilization": None, "net_eph_after_vat": pnr / po if po else 0,
                    "rph": pf / po if po else 0, "fleet_fr": pf / pds if pds else 0}
            month_key = next((k for k, m in months.items()
                              if any(w.get("complete") for w in m["weeks"])), None)
            if month_key:
                out["MONTHS"][month_key]["prevData"] = prev
                out["MONTHS"][month_key]["prevLabel"] = prev_first.strftime("%B %Y")
    return out


def is_ready(data, fleet):
    """La ultima semana cerrada debe tener datos; si no, el ETL aun no ha cargado."""
    wk = data.get("WEEKLY") or []
    if not wk:
        return False
    last = wk[-1]
    return last["finished_trips"] > 0 and bool(data[fleet["coll"]].get(last["week"]))


def main():
    had_error = False   # error real (SQL/red/parseo) -> workflow en rojo
    for fleet in FLEETS:
        try:
            data = build_fleet(fleet)
        except Exception as e:
            print(f"[error] {fleet['id']}: fallo consultando datos: {e}")
            had_error = True
            continue
        if not is_ready(data, fleet):
            # No es un error: el ETL aun no cargo la semana. Verde y se reintenta la proxima hora.
            print(f"[skip] {fleet['id']}: datos de la ultima semana aun no disponibles; se reintenta la proxima hora")
            continue
        json.dump(data, open(os.path.join(ROOT, "data", f"{fleet['id']}.json"), "w"), ensure_ascii=False)
        print(f"[ok] data/{fleet['id']}.json actualizado")
    if had_error:
        sys.exit(1)   # marca el workflow como fallido para que se vea


if __name__ == "__main__":
    main()
