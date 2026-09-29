"""Replay the live demo well through the alert engine and score alerts against ground truth (synthetic data)."""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nwis.config import TRUTH_DIR
from nwis.db import connect
from nwis.kb import KnowledgeIndex
from nwis.live import LiveSession


def run(start_md: float = 1300.0, verbose: bool = True) -> dict:
    conn = connect()
    kb = KnowledgeIndex(conn)
    active = next(w for w in kb.wells.values() if (w["status"] or "").upper() == "ACTIVE")
    sess = LiveSession(kb, conn, active["id"], start_md=start_md)
    sess.reset(start_md)
    while sess.step() is not None:
        pass
    truth = [e for e in json.loads((TRUTH_DIR / f"{active['name']}.json").read_text())["events"]
             if e["type"] != "fishing" and e["md"] >= start_md]
    by_kind = defaultdict(list)
    for a in sess.alerts:
        by_kind[a["kind"]].append(a)
    if verbose:
        print(f"{len(sess.alerts)} alerts:", {k: len(v) for k, v in by_kind.items()})
    rows = []
    for t in truth:
        cands = [a for a in sess.alerts if a["hazard"] == t["type"] and a["md"] <= t["md"] + 5 and a["md"] >= t["md"] - 450]
        first = min(cands, key=lambda a: a["md"]) if cands else None
        any_kind = {a["kind"] for a in cands}
        rows.append({"type": t["type"], "md": t["md"], "lead_m": (t["md"] - first["md"]) if first else None,
                     "first_kind": first["kind"] if first else None, "kinds": sorted(any_kind)})
        if verbose:
            lead = f"{t['md'] - first['md']:.0f} m ahead via {first['kind']}" if first else "MISSED"
            print(f"  truth {t['type']:14s} @ {t['md']:6.0f}: {lead}   (kinds: {sorted(any_kind)})")
    detected = [r for r in rows if r["lead_m"] is not None]
    # precision of hazard alerts (lookahead+model+realtime): alert has a truth event of that type within [md-30, md+400]
    hazard_alerts = [a for a in sess.alerts if a["kind"] in ("lookahead", "model", "realtime")]
    tp = 0
    for a in hazard_alerts:
        if any(t["type"] == a["hazard"] and a["md"] - 30 <= t["md"] <= a["md"] + 400 for t in json.loads((TRUTH_DIR / f"{active['name']}.json").read_text())["events"]):
            tp += 1
    res = {
        "truth_events": len(rows), "detected": len(detected),
        "median_lead_m": sorted(r["lead_m"] for r in detected)[len(detected) // 2] if detected else None,
        "alerts": len(hazard_alerts), "alert_precision": tp / len(hazard_alerts) if hazard_alerts else None,
    }
    # stricter, separate views ---------------------------------------------------------------------------------
    all_truth = [e for e in json.loads((TRUTH_DIR / f"{active['name']}.json").read_text())["events"] if e["type"] != "fishing"]
    zones = [z for z in sess.zones if z.level != "low" and z.md_to >= start_md]
    z_hit = sum(1 for z in zones if any(t["type"] == z.type and z.md_from - 50 <= t["md"] <= z.md_to + 50 for t in all_truth))
    ev_cov = sum(1 for t in truth if any(z.type == t["type"] and z.md_from - 50 <= t["md"] <= z.md_to + 50 for z in sess.zones if z.level != "low"))
    short = []
    for t in truth:
        c = [a for a in sess.alerts if a["kind"] in ("realtime", "model") and a["hazard"] == t["type"] and t["md"] - 100 <= a["md"] <= t["md"] + 5]
        if c:
            short.append(t["md"] - min(a["md"] for a in c))
    res.update({
        "zones_medium_high": len(zones), "zone_precision": z_hit / len(zones) if zones else None,
        "events_covered_by_zone": f"{ev_cov}/{len(truth)}",
        "short_range_detected": f"{len(short)}/{len(truth)}", "short_range_median_lead_m": sorted(short)[len(short) // 2] if short else None,
    })
    if verbose:
        print(res)
    return res


if __name__ == "__main__":
    run(float(sys.argv[1]) if len(sys.argv) > 1 else 1300.0)
