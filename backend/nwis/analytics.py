"""Offset-well analytics: formation-top prediction, hazard zones ahead of the bit, per-formation risk profiles."""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

import numpy as np

from .config import EVENT_LABELS, EVENT_TYPES
from .kb import KnowledgeIndex, Trajectory, closest_approach_km

SUCCESS = {"cured", "freed", "controlled", "normalised", "remediated", "recovered", "reduced"}


def weight(dist_km: float) -> float:
    return 1.0 / (dist_km + 0.5) ** 2


# ---------------------------------------------------------------------------- formation tops
def predict_tops(kb: KnowledgeIndex, target: Trajectory, radius_km: float) -> list[dict]:
    """Predict formation tops at the target location from offset wells.

    Weighted plane fit (TVD ~ a + b*east + c*north) when >=5 offsets penetrate the formation, else a weighted mean.
    Returns [{formation, tvd, md, sigma_m, n_offsets}] ordered by depth.
    """
    offs = kb.nearby(target, radius_km * 1.5)
    out = []
    for fm in kb.formation_order:
        pts = []
        for t, d in offs:
            tv = t.top_tvd(fm)
            if tv is not None:
                pts.append((t.east0, t.north0, tv, weight(d)))
        if not pts:
            continue
        arr = np.array(pts)
        w = arr[:, 3]
        if len(arr) >= 5:
            X = np.column_stack([np.ones(len(arr)), arr[:, 0] - target.east0, arr[:, 1] - target.north0])
            W = np.diag(w)
            A = X.T @ W @ X + 1e-3 * np.eye(3)
            beta = np.linalg.solve(A, X.T @ W @ arr[:, 2])
            pred = float(beta[0])
            resid = arr[:, 2] - X @ beta
            sigma = float(np.sqrt(np.average(resid**2, weights=w) * len(arr) / max(1, len(arr) - 3)))
        else:
            pred = float(np.average(arr[:, 2], weights=w))
            sigma = float(np.sqrt(np.average((arr[:, 2] - pred) ** 2, weights=w))) if len(arr) > 1 else 25.0
        sigma = max(sigma, 5.0)
        out.append({"formation": fm, "tvd": pred, "md": float(target.md_at_tvd(pred)), "sigma_m": sigma, "n_offsets": len(arr)})
    out.sort(key=lambda t: t["tvd"])
    # enforce monotonic order with a minimum thickness
    for i in range(1, len(out)):
        if out[i]["tvd"] < out[i - 1]["tvd"] + 30:
            out[i]["tvd"] = out[i - 1]["tvd"] + 30
            out[i]["md"] = float(target.md_at_tvd(out[i]["tvd"]))
    return out


def as_trajectory_tops(pred: list[dict]) -> list[dict]:
    return [{"formation": p["formation"], "tvd": p["tvd"], "md": p["md"]} for p in pred]


# ---------------------------------------------------------------------------- recommendations
def _mw_text(evs: list[dict]) -> str | None:
    mws = [e["details"].get("mw1") for e in evs if e["details"].get("mw1")]
    if len(mws) < 2:
        return None
    return f"offsets weighted up to {min(mws):.2f}-{max(mws):.2f} SG (median {float(np.median(mws)):.2f})"


def mitigation_stats(evs: list[dict]) -> list[dict]:
    """Rank the actions taken on offsets by success rate and downtime."""
    groups: dict[str, list[dict]] = defaultdict(list)
    for e in evs:
        key = e["mitigations"][0] if e["mitigations"] else None
        if key:
            groups[key].append(e)
    stats = []
    for k, g in groups.items():
        ok = sum(1 for e in g if e["outcome"] in SUCCESS)
        npts = [e["npt_h"] for e in g if e["npt_h"] is not None]
        stats.append({"action": k, "n": len(g), "success": ok, "success_rate": ok / len(g),
                      "mean_npt_h": float(np.mean(npts)) if npts else None})
    stats.sort(key=lambda s: (-s["success_rate"], s["mean_npt_h"] if s["mean_npt_h"] is not None else 99, -s["n"]))
    return stats


ACTION_TEXT = {
    "lcm_pill": "pump LCM pill", "reduce_rate": "reduce flow rate + fine LCM", "cement_plug": "set cement plug",
    "weight_up": "raise mud weight", "shut_in": "shut in / kill", "jarring": "jar the string", "freeing_pill": "spot pipe-freeing pill",
    "backoff": "back off / fish", "reduce_rpm": "reduce RPM + clean hole", "wiper_trip": "wiper trip",
    "squeeze": "remedial squeeze", "fishing_run": "fishing run",
}

PREVENT_TEXT = {
    "mud_loss": "Have LCM pills mixed and ready; consider reducing ECD before entering the zone.",
    "kick": "Run flow checks every connection; raise mud weight ahead of the zone and keep kill mud available.",
    "stuck_pipe": "Limit open-hole time, run wiper trips, watch torque/overpull trends on connections.",
    "overpressure": "Monitor d-exponent and gas trends; be ready to increase MW before drilling through the interval.",
    "torque_spike": "Reduce RPM, use lubricant, and circulate hole clean when torque trends up.",
    "cementing_issue": "Verify centralizer placement and spacer volumes; plan CBL after the job.",
    "fishing": "Inspect BHA before running; limit jarring time.",
}


def recommendation(etype: str, evs: list[dict]) -> str:
    parts = [PREVENT_TEXT.get(etype, "")]
    ms = mitigation_stats(evs)
    if ms:
        best = ms[0]
        txt = ACTION_TEXT.get(best["action"], best["action"].replace("_", " "))
        parts.append(f"Best offset outcome: {txt} ({best['success']}/{best['n']} successful"
                     + (f", avg NPT {best['mean_npt_h']:.0f} h" if best["mean_npt_h"] is not None else "") + ").")
    if etype in ("kick", "overpressure"):
        t = _mw_text(evs)
        if t:
            parts.append(t.capitalize() + ".")
    return " ".join(p for p in parts if p)


# ---------------------------------------------------------------------------- hazard zones ahead
@dataclass
class Zone:
    id: str
    type: str
    md_from: float
    md_to: float
    md_center: float
    tvd_center: float
    tvd_from: float
    tvd_to: float
    formation: str | None
    n_events: int
    n_wells: int
    prevalence: float
    mean_npt_h: float | None
    score: float
    level: str
    wells: list[str]
    event_ids: list[int]
    recommendation: str
    sigma_m: float

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        d["label"] = EVENT_LABELS.get(self.type, self.type)
        return d


def _level(score: float) -> str:
    return "high" if score >= 0.35 else "medium" if score >= 0.15 else "low"


def hazard_zones(
    kb: KnowledgeIndex,
    target: Trajectory,
    pred_tops: list[dict],
    md_from: float,
    md_to: float,
    radius_km: float,
    types: list[str] | None = None,
    min_prevalence: float = 0.0,
) -> list[Zone]:
    """Project offset events onto the target well and cluster them into hazard zones within [md_from, md_to]."""
    types = types or [t for t in EVENT_TYPES if t != "fishing"]
    top_pred = {p["formation"]: p for p in pred_tops}
    sigma_by_fm = {p["formation"]: p["sigma_m"] for p in pred_tops}
    offs = kb.nearby(target, radius_km)
    if not offs:
        return []
    pts: list[dict] = []
    for t, d in offs:
        w = weight(d)
        for e in kb.events_by_well.get(t.id, []):
            if e["type"] not in types or e["tvd"] is None or not e["formation"]:
                continue
            p = top_pred.get(e["formation"])
            otop = t.top_tvd(e["formation"])
            if p is None or otop is None:
                continue
            tvd_pred = p["tvd"] + (e["tvd"] - otop)
            md_pred = float(target.md_at_tvd(tvd_pred))
            if md_from - 30 <= md_pred <= md_to + 30:
                pts.append({"e": e, "tvd": tvd_pred, "md": md_pred, "w": w, "well": t, "dist": d})
    zones: list[Zone] = []
    for et in types:
        sub = sorted((p for p in pts if p["e"]["type"] == et), key=lambda p: p["md"])
        if not sub:
            continue
        clusters: list[list[dict]] = [[sub[0]]]
        for p in sub[1:]:
            if p["md"] - clusters[-1][-1]["md"] <= 45:
                clusters[-1].append(p)
            else:
                clusters.append([p])
        for ci, cl in enumerate(clusters):
            mds = np.array([p["md"] for p in cl])
            ws = np.array([p["w"] for p in cl])
            center = float(np.average(mds, weights=ws))
            lo, hi = float(mds.min() - 15), float(mds.max() + 15)
            wells_hit = {p["well"].id for p in cl}
            tvd_c = float(np.average([p["tvd"] for p in cl], weights=ws))
            tvds = [p["tvd"] for p in cl]
            # prevalence: weighted share of offsets that reach this depth and had this event type nearby
            tot_w = hit_w = 0.0
            for t, d in offs:
                if t.td_tvd >= tvd_c - 10:
                    tot_w += weight(d)
                    if t.id in wells_hit:
                        hit_w += weight(d)
            prevalence = hit_w / tot_w if tot_w else 0.0
            if prevalence < min_prevalence:
                continue
            npts = [p["e"]["npt_h"] for p in cl if p["e"]["npt_h"] is not None]
            mean_npt = float(np.mean(npts)) if npts else None
            score = prevalence * (0.5 + min(mean_npt or 0.0, 48.0) / 96.0)
            fm = target.formation_at_tvd(tvd_c) or max(Counter(p["e"]["formation"] for p in cl).items(), key=lambda kv: kv[1])[0]
            zones.append(Zone(
                id=f"{et}:{int(round(center / 10) * 10)}", type=et, md_from=lo, md_to=hi, md_center=center, tvd_center=tvd_c,
                tvd_from=float(min(tvds) - 15), tvd_to=float(max(tvds) + 15), formation=fm, n_events=len(cl), n_wells=len(wells_hit), prevalence=round(prevalence, 3),
                mean_npt_h=mean_npt, score=round(score, 3), level=_level(score),
                wells=sorted({p["well"].name for p in cl}), event_ids=[p["e"]["id"] for p in cl],
                recommendation=recommendation(et, [p["e"] for p in cl]),
                sigma_m=float(sigma_by_fm.get(fm, 15.0)),
            ))
    zones.sort(key=lambda z: z.md_center)
    return zones


# ---------------------------------------------------------------------------- per-formation risk profile
def risk_profile(kb: KnowledgeIndex, target: Trajectory, pred_tops: list[dict], radius_km: float) -> list[dict]:
    """For each formation: how often each hazard occurred in offsets that penetrated it (distance weighted)."""
    offs = kb.nearby(target, radius_km)
    rows = []
    for i, p in enumerate(pred_tops):
        fm = p["formation"]
        nxt = pred_tops[i + 1]["tvd"] if i + 1 < len(pred_tops) else p["tvd"] + 250
        thickness = max(nxt - p["tvd"], 1.0)
        pen = []
        for t, d in offs:
            top = t.top_tvd(fm)
            if top is not None and t.td_tvd > top + 30:
                pen.append((t, d))
        tot_w = sum(weight(d) for _, d in pen)
        by_type = {}
        exp_npt = 0.0
        for et in EVENT_TYPES:
            hit_w = 0.0
            evs_all: list[dict] = []
            rel_depths = []
            for t, d in pen:
                evs = [e for e in kb.events_by_well.get(t.id, []) if e["type"] == et and e["formation"] == fm]
                if evs:
                    hit_w += weight(d)
                    evs_all += evs
                    top = t.top_tvd(fm)
                    rel_depths += [e["tvd"] - top for e in evs if e["tvd"] is not None]
            prev = hit_w / tot_w if tot_w else 0.0
            npts = [e["npt_h"] for e in evs_all if e["npt_h"] is not None]
            mean_npt = float(np.mean(npts)) if npts else None
            if et != "fishing":
                exp_npt += prev * (mean_npt or 0.0)
            by_type[et] = {
                "prevalence": round(prev, 3), "events": len(evs_all), "mean_npt_h": mean_npt,
                "typical_depth_below_top_m": float(np.median(rel_depths)) if rel_depths else None,
                "level": _level(prev * (0.5 + min(mean_npt or 0.0, 48.0) / 96.0)) if evs_all else "none",
            }
        rows.append({
            "formation": fm, "top_tvd": p["tvd"], "top_md": p["md"], "thickness_m": thickness, "sigma_m": p["sigma_m"],
            "n_offsets": len(pen), "risk": by_type, "expected_npt_h": round(exp_npt, 1),
        })
    return rows
