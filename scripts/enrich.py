"""Reproduce la lógica del contrato (idéntica al dashboard) a partir de filas crudas.
Net EPH After VAT = (GMV * (1-commission) / (1+vat)) / online_hours
Comp. Rate        = finished / (finished + driver_cancelled)
qualifies         = peak_hours >= min_peak_hours AND CR*100 >= min_cr
Payout            = qualifies ? max(0, (guaranteed_eph - net_eph) * oh) : 0
"""
def calc_net(gmv, c): return gmv * (1 - c["commission"]) / (1 + c["vat"])
def calc_eph(gmv, oh, c): return calc_net(gmv, c) / oh if oh > 0 else 0.0
def calc_cr(fin, dc): d = fin + dc; return fin / d if d > 0 else 1.0
def calc_payout(net_eph, oh, c): return max(0.0, (c["guaranteedNetEPH"] - net_eph) * oh)

def enrich_entity(rows, c, id_key):
    out = []
    for r in rows:
        cr = calc_cr(r["finished"], r["driver_cancelled"])
        net_eph = calc_eph(r["gmv"], r["oh"], c)
        q_peak = r["peak_hours"] >= c["minPeakHours"]
        q_cr = cr * 100 >= c["minCR"]
        qualifies = q_peak and q_cr
        payout = calc_payout(net_eph, r["oh"], c) if qualifies else 0.0
        e = dict(r); e.update(cr=cr, net_eph=net_eph, qPeak=q_peak, qCR=q_cr,
                              qualifies=qualifies, payout=payout)
        if id_key == "driver_id":
            e["rph"] = r["finished"] / r["oh"] if r["oh"] > 0 else 0
        out.append(e)
    return out
