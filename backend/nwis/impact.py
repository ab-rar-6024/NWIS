"""Fleet-wide leave-one-well-out backtest: how much recorded downtime would this system have flagged in advance?

For every completed well, its own reports are hidden and formation tops / hazard zones are predicted from
ONLY its neighbours (exactly the situation faced before that well had a completion report of its own). Its
own recorded events are then checked against those zones. This is the same mechanism the live monitor uses
for the active well, applied retrospectively to every well in the knowledge base, so the number is not
tuned to any one demo well.

The result is a measured coverage figure (event count and NPT hours that fall inside a same-type forecast
zone). Turning that into a rupee figure requires a rig day-rate and an assumption about how much of that
downtime proactive action actually avoids — those are inputs the caller supplies (the UI exposes them as
adjustable sliders) rather than constants buried here, so the estimate is never presented as more precise
than it is.
"""
from __future__ import annotations

from .analytics import hazard_zones, predict_tops
from .kb import KnowledgeIndex

TOL_M = 50.0  # an event within this many metres of a same-type zone's bounds counts as "flagged"


def backtest_well(kb: KnowledgeIndex, well_id: int, radius_km: float, min_prevalence: float = 0.1) -> dict | None:
    tr = kb.traj.get(well_id)
    if tr is None or (tr.status or "").upper() == "ACTIVE":
        return None
    evs = [e for e in kb.events_by_well.get(well_id, []) if e["type"] != "fishing" and e["md"] is not None]
    if not evs:
        return None
    tops = predict_tops(kb, tr, radius_km)  # foresight-only: neighbours never include this well itself
    zones = hazard_zones(kb, tr, tops, 0.0, tr.td_md, radius_km, min_prevalence=min_prevalence)
    rows = []
    for e in evs:
        hit = next((z for z in zones if z.type == e["type"] and z.md_from - TOL_M <= e["md"] <= z.md_to + TOL_M), None)
        rows.append({"id": e["id"], "type": e["type"], "md": e["md"], "npt_h": e["npt_h"] or 0.0,
                     "flagged": hit is not None, "zone_level": hit.level if hit else None})
    total_npt = sum(r["npt_h"] for r in rows)
    flagged_npt = sum(r["npt_h"] for r in rows if r["flagged"])
    return {
        "well_id": well_id, "well": tr.name, "field": tr.field, "n_events": len(rows),
        "n_flagged": sum(r["flagged"] for r in rows), "total_npt_h": round(total_npt, 1),
        "flagged_npt_h": round(flagged_npt, 1), "n_offsets": len(kb.nearby(tr, radius_km)), "events": rows,
    }


def fleet_backtest(kb: KnowledgeIndex, radius_km: float = 8.0, min_prevalence: float = 0.1) -> dict:
    rows = [r for wid in kb.traj if (r := backtest_well(kb, wid, radius_km, min_prevalence))]
    rows.sort(key=lambda r: -r["total_npt_h"])
    total_events = sum(r["n_events"] for r in rows)
    flagged_events = sum(r["n_flagged"] for r in rows)
    total_npt = sum(r["total_npt_h"] for r in rows)
    flagged_npt = sum(r["flagged_npt_h"] for r in rows)
    exemplar = rows[0] if rows else None
    return {
        "radius_km": radius_km, "min_prevalence": min_prevalence, "n_wells": len(rows),
        "total_events": total_events, "flagged_events": flagged_events, "total_npt_h": round(total_npt, 1),
        "flagged_npt_h": round(flagged_npt, 1),
        "event_coverage": flagged_events / total_events if total_events else None,
        "npt_coverage": flagged_npt / total_npt if total_npt else None,
        "wells": rows, "exemplar": exemplar,
        "method": "Leave-one-well-out: each well's own reports are hidden; formation tops and hazard zones are "
                  "predicted from its neighbours only, then checked against that well's own recorded events.",
    }
