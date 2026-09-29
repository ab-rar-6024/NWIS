"""Generates the free-text content of synthetic Daily Drilling Reports (DDR) and Well Completion Reports (WCR).

The text deliberately mixes phrasing variants, unit spellings, negations and contingency statements so the
extraction pipeline is exercised against something harder than a fixed template.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import timedelta

import numpy as np

from . import geology as G
from .wellgen import ROP_BASE, Event, Well


@dataclass
class DayReport:
    report_no: int
    date: object
    depth_md: float
    formation: str
    hole: str
    mw: float
    sentences: list[str] = field(default_factory=list)
    event_ids: list[str] = field(default_factory=list)


def fmt_md(x: float, rng: np.random.Generator) -> str:
    v = int(round(x))
    style = rng.choice(5, p=[0.35, 0.2, 0.15, 0.15, 0.15])
    if style == 0:
        return f"{v:,} m"
    if style == 1:
        return f"{v} m"
    if style == 2:
        return f"{v}m"
    if style == 3:
        return f"{v:,} mMD"
    return f"{v} mts"


def _c(rng, options):
    return options[int(rng.integers(0, len(options)))]


# ------------------------------------------------------------------ DDR event sentences
def ddr_event_sentences(ev: Event, rng, hole: str, well: Well) -> list[str]:
    d = ev.details
    D = fmt_md(ev.md, rng)
    show_depth = rng.random() > 0.10
    at = f"at {D}" if show_depth else "while drilling ahead"
    out: list[str] = []
    npt = f"NPT {ev.npt_h:g} hrs."

    if ev.type == "mud_loss":
        sev = {"seepage": "Seepage losses", "partial": "Partial losses", "severe": "Severe losses",
               "total": "Total loss of returns"}[d["severity"]]
        rate = d["rate_m3h"]
        out.append(_c(rng, [
            f"{sev} encountered {at} while drilling {hole} hole in {ev.formation}. Loss rate {rate:g} m3/hr.",
            f"Lost circulation observed {at.replace('at ', '@ ')}; pit volume dropping, losses of {rate:g} m3/hr.",
            f"{sev} noted {at} ({ev.formation}), static loss {rate:g} m3/hr.",
            f"Observed mud losses {at} with flow-out reduction, estimated loss {rate:g} m3/hr.",
        ]))
        v, ppb, lcm = d["lcm_vol_m3"], d["lcm_ppb"], d["lcm_type"]
        if d["mitigation"] == "lcm_pill":
            out.append(_c(rng, [
                f"Pumped {v} m3 LCM pill ({ppb} ppb {lcm}).",
                f"Spotted {v} m3 LCM pill with {lcm} at {ppb} ppb.",
                f"Mixed and pumped {lcm} LCM sweep, {v} m3 at {ppb} ppb.",
            ]))
        elif d["mitigation"] == "reduce_rate":
            out.append(_c(rng, ["Reduced pump rate and continued drilling with LCM in the active system.",
                                "Lowered flow rate and added fine LCM to active system."]))
        else:
            out.append(_c(rng, [f"Set balanced cement plug across the loss zone near {fmt_md(ev.md, rng)} and dressed off.",
                                "Spotted cement plug over thief zone; WOC and drilled out."]))
        if d["outcome"] == "cured":
            out.append(_c(rng, ["Losses cured.", "Full returns regained.", "Returns restored, drilling resumed."]))
        elif d["outcome"] == "reduced":
            r2 = d["residual_m3h"]
            out.append(_c(rng, [f"Losses reduced to {r2:g} m3/hr.", f"Partial returns regained; residual loss {r2:g} m3/hr."]))
        else:
            out.append(_c(rng, ["Losses continued; drilled ahead blind with water.",
                                "Unable to cure losses, decided to drill ahead without returns."]))
    elif ev.type == "kick":
        out.append(_c(rng, [
            f"Well flowing {at}. Shut in well; SIDPP {d['sidpp_bar']} bar, SICP {d['sicp_bar']} bar, pit gain {d['gain_m3']:g} m3.",
            f"Positive flow check {at}, gas-cut mud observed. Shut in; pit gain {d['gain_m3']:g} m3, SIDPP {d['sidpp_bar']} bar.",
            f"Kick taken {at} in {ev.formation} - pit gain of {d['gain_m3']:g} m3, well shut in (SIDPP {d['sidpp_bar']} bar / SICP {d['sicp_bar']} bar).",
        ]))
        out.append(_c(rng, [
            f"Killed well using {d['method']}; MW raised from {d['mw0']:.2f} to {d['mw1']:.2f} SG.",
            f"Circulated out kick with {d['method']}, weighted up mud {d['mw0']:.2f} -> {d['mw1']:.2f} SG.",
        ]))
        out.append(_c(rng, ["Well stable after kill, resumed drilling.", "Well dead, flow check negative."]))
    elif ev.type == "stuck_pipe":
        mech = d["mechanism"]
        op = d["op"]
        out.append(_c(rng, [
            f"String became stuck {at} while {op}. Overpull {d['overpull_t']} t, no rotation.",
            f"Pipe stuck {at} ({mech}); max overpull {d['overpull_t']} t.",
            f"Tight hole and pack-off {at}, pipe stuck, overpull {d['overpull_t']} t.",
        ]))
        if d["mitigation"] == "jarring":
            out.append(f"Worked pipe with jars and torque; pipe freed after {ev.npt_h:g} hrs.")
        elif d["mitigation"] == "freeing_pill":
            out.append(f"Spotted {int(rng.integers(8, 20))} m3 pipe-freeing pill; pipe freed after soak of {ev.npt_h:g} hrs.")
        else:
            out.append(f"Unable to free pipe; ran free-point and backed off near {fmt_md(ev.md + rng.uniform(0, 12), rng)} leaving BHA in hole.")
        if d["mitigation"] != "backoff" and rng.random() < 0.85:
            out.append(npt)
    elif ev.type == "overpressure":
        out.append(_c(rng, [
            f"Drilling break observed {at}; gas increased to {d['gas_units']} units with cavings on shakers. Estimated pore pressure {d['pp_sg']:.2f} SG.",
            f"Overpressured zone indicated {at} (d-exponent trend reversal, gas {d['gas_units']} units), formation pressure approx {d['pp_sg']:.2f} SG EMW.",
        ]))
        out.append(f"Increased MW from {d['mw0']:.2f} to {d['mw1']:.2f} SG and circulated bottoms up.")
    elif ev.type == "torque_spike":
        out.append(_c(rng, [
            f"Torque spikes up to {d['peak_knm']:g} kNm (normal {d['baseline_knm']:g} kNm) {at}. Reduced RPM, worked string and circulated hole clean.",
            f"High and erratic torque {at}, peak {d['peak_knm']:g} kNm versus {d['baseline_knm']:g} kNm baseline; performed wiper trip.",
        ]))
    elif ev.type == "fishing":
        if d["recovered"]:
            out.append(f"Fishing operation {at}: lost {d['tool']} in hole. RIH with overshot; fish recovered after {ev.npt_h:g} hrs.")
        else:
            out.append(f"Fishing operation {at}: lost {d['tool']} in hole. Fish not recovered after {ev.npt_h:g} hrs; decided to abandon fish and sidetrack.")
    if ev.type in ("mud_loss", "kick", "overpressure", "torque_spike") and ev.npt_h and rng.random() < 0.85:
        out.append(npt)
    return out


def ddr_cementing_sentences(ev: Event, rng) -> list[str]:
    d = ev.details
    shoe = fmt_md(ev.md, rng)
    casing = d.get("casing", '9-5/8"')
    v = d["squeeze_vol_m3"]
    if d["kind"] == "poor bond":
        s = [f"Cemented {casing} casing at {shoe}. CBL indicated poor cement bond; performed remedial squeeze with {v} m3 slurry."]
    elif d["kind"] == "low top of cement":
        s = [f"Ran and cemented {casing} casing at {shoe}. Cement top found lower than planned; top-up cement job with {v} m3 performed."]
    else:
        s = [f"Cement channeling suspected on {casing} casing at {shoe} per CBL/VDL; squeezed {v} m3 cement across the shoe track."]
    s.append(f"NPT {ev.npt_h:g} hrs.")
    return s


# ------------------------------------------------------------------ DDR assembly
def _routine_sentences(rng, hole, fm, a, b, mw, gas):
    rop = ROP_BASE.get(fm, 15) * rng.uniform(0.6, 1.3)
    s = [f"Drilled {hole} hole from {fmt_md(a, rng)} to {fmt_md(b, rng)} in {fm} formation. "
         f"Avg ROP {rop:.1f} m/hr, WOB {rng.uniform(6, 14):.0f} t, RPM {int(rng.integers(80, 140))}."]
    opts = [
        "Performed wiper trip; hole condition good.",
        "Circulated bottoms up; shakers clean.",
        "Changed out bit after trip; RIH and reamed last stand.",
        "Rig maintenance carried out on mud pumps.",
        "Conducted BOP function test.",
        f"MW {mw:.2f} SG, Vis {int(rng.integers(42, 68))} s, PV {int(rng.integers(12, 26))}, YP {int(rng.integers(14, 30))}.",
        f"Background gas {int(gas)} units.",
        "Took survey and surface checks; deviation within plan.",
    ]
    for k in rng.choice(len(opts), size=int(rng.integers(1, 4)), replace=False):
        s.append(opts[int(k)])
    return s


def _hard_negatives(rng, a, b):
    opts = [
        "No losses observed while drilling this section.",
        f"Flow check at {fmt_md(b, rng)} negative.",
        "Well stable, no kick indicators.",
        "Torque and drag within normal range.",
        "No tight hole or overpull noted on connections.",
        "Mud losses: nil.",
        "No gas shows above background.",
        "Kept 30 m3 LCM pill ready as precaution against losses.",
        "Pit volume steady; no gain or loss.",
    ]
    return [opts[int(k)] for k in rng.choice(len(opts), size=int(rng.integers(0, 3)), replace=False)]


def build_ddr(well: Well, rng: np.random.Generator) -> list[DayReport]:
    days: list[DayReport] = []
    md = 0.0
    date = well.spud_date
    shoes = [c["shoe_md"] for c in well.casing]
    drill_events = [e for e in well.events if e.type not in ("cementing_issue",)]
    cement_by_shoe = {e.md: e for e in well.events if e.type == "cementing_issue"}
    log_idx = well.logs.set_index("md")
    no = 1

    def mw_at(x):
        i = well.logs["md"].searchsorted(x)
        i = min(max(i, 0), len(well.logs) - 1)
        return float(well.logs["mw"].iloc[i])

    def gas_at(x):
        i = well.logs["md"].searchsorted(x)
        i = min(max(i, 0), len(well.logs) - 1)
        return float(well.logs["gas"].iloc[i])

    def fm_at(x):
        tvd = float(np.interp(x, well.survey["md"], well.survey["tvd"]))
        return G.formation_at_tvd(tvd, well.tops_tvd)

    def hole_at(x):
        for c in well.casing:
            if x <= c["shoe_md"] + 1e-6:
                return c["hole"]
        return well.casing[-1]["hole"]

    while md < well.td_md - 1e-6:
        remaining_shoes = [s for s in shoes if s > md + 1e-6]
        nxt_shoe = remaining_shoes[0] if remaining_shoes else well.td_md
        fm = fm_at(md + 1)
        step = float(np.clip(ROP_BASE.get(fm, 15) * rng.uniform(5, 9), 25, 220))
        target = min(md + step, nxt_shoe, well.td_md)
        hole = hole_at(md + 1)
        evs = [e for e in drill_events if md < e.md <= target + 1e-6]
        sents = [f"Spud well." ] if no == 1 else []
        sents += _routine_sentences(rng, hole, fm, md, target, mw_at(target), gas_at(target))
        for e in evs:
            sents += ddr_event_sentences(e, rng, hole, well)
        sents += _hard_negatives(rng, md, target)
        days.append(DayReport(no, date, round(target, 1), fm, hole, mw_at(target), sents, [e.id for e in evs]))
        no += 1
        date += timedelta(days=1)
        md = target
        if abs(md - nxt_shoe) < 1e-6:
            casing = next(c for c in well.casing if abs(c["shoe_md"] - nxt_shoe) < 1e-6)
            cs = [f"Reached casing point {fmt_md(nxt_shoe, rng)}. Circulated and conditioned hole; POOH.",
                  f"Ran {casing['size']} {casing['grade']} casing to {fmt_md(nxt_shoe, rng)} and circulated.",
                  f"Cemented {casing['size']} casing with {int(rng.integers(20, 90))} m3 slurry; bumped plug."]
            ids: list[str] = []
            ce = cement_by_shoe.get(nxt_shoe)
            if ce:
                cs = cs[:2] + ddr_cementing_sentences(ce, rng)
                ids.append(ce.id)
            cs.append("Nipple up BOP and pressure test." if nxt_shoe < well.td_md else "Rig down and release rig.")
            days.append(DayReport(no, date, round(nxt_shoe, 1), fm_at(nxt_shoe), casing["hole"], mw_at(nxt_shoe), cs, ids))
            no += 1
            date += timedelta(days=1)
    return days


# ------------------------------------------------------------------ WCR
def wcr_problem_sentences(ev: Event, rng) -> str:
    d = ev.details
    D = fmt_md(ev.md, rng)
    fm = ev.formation
    if ev.type == "mud_loss":
        mit = {"lcm_pill": f"cured with LCM pills ({d['lcm_type']})", "reduce_rate": "managed by reduced flow rate and fine LCM",
               "cement_plug": "treated with a cement plug"}[d["mitigation"]]
        return (f"Lost circulation ({d['severity']}) was experienced at {D} in the {fm} with a maximum loss of "
                f"{d['rate_m3h']:g} m3/hr; {mit}. NPT {ev.npt_h:g} hrs.")
    if ev.type == "kick":
        return (f"A gas kick was taken at {D} in the {fm} (pit gain {d['gain_m3']:g} m3). Well was controlled using the "
                f"{d['method']} and mud weight was increased to {d['mw1']:.2f} SG. NPT {ev.npt_h:g} hrs.")
    if ev.type == "stuck_pipe":
        base = f"Drillstring stuck at {D} in the {fm} ({d['mechanism']}, overpull {d['overpull_t']} t)."
        tail = {"jarring": " Freed by jarring.", "freeing_pill": " Freed after spotting a pipe-freeing pill.",
                "backoff": " Pipe could not be freed and BHA was backed off."}[d["mitigation"]]
        return base + tail + f" NPT {ev.npt_h:g} hrs."
    if ev.type == "overpressure":
        return (f"Overpressure was encountered at {D} in the {fm}; estimated pore pressure {d['pp_sg']:.2f} SG. "
                f"Mud weight raised from {d['mw0']:.2f} to {d['mw1']:.2f} SG.")
    if ev.type == "torque_spike":
        return (f"High torque (peak {d['peak_knm']:g} kNm) recorded at {D} in the {fm}; RPM reduced and hole cleaned. "
                f"NPT {ev.npt_h:g} hrs.")
    if ev.type == "cementing_issue":
        kind = {"poor bond": "poor cement bond", "low top of cement": "cement top lower than planned", "channeling": "cement channeling"}[d["kind"]]
        return (f"Cementing of the {d.get('casing', '')} casing at {D} showed {kind}; a remedial squeeze of "
                f"{d['squeeze_vol_m3']} m3 was performed. NPT {ev.npt_h:g} hrs.")
    if ev.type == "fishing":
        res = "recovered" if d["recovered"] else "not recovered"
        return f"Fishing operation at {D}: {d['tool']} left in hole, fish {res} after {ev.npt_h:g} hrs."
    return ""


LESSON_TEXT = {
    "mud_loss": "Recommend having LCM pills mixed and ready before entering the {fm}; mud losses recur in this interval.",
    "kick": "Recommend raising mud weight ahead of the {fm} and running flow checks on every connection; kicks were taken in this interval.",
    "stuck_pipe": "Recommend limiting open-hole time and running wiper trips through the {fm} to avoid stuck pipe.",
    "overpressure": "Recommend pore-pressure monitoring (d-exponent, gas trend) through the {fm}; overpressure encountered.",
    "torque_spike": "Recommend reducing RPM and adding lubricant when torque trends rise in the {fm}.",
    "cementing_issue": "Recommend using spacer and centralizers to improve cement quality on the {fm} casing point.",
}


def build_wcr(well: Well, rng: np.random.Generator):
    """Return structured WCR content as a list of blocks for the PDF renderer."""
    blocks: list[tuple] = []
    blocks.append(("title", f"WELL COMPLETION REPORT - {well.name}"))
    blocks.append(("kv", [
        ("Well Name", well.name), ("Field", well.field),
        ("Latitude", f"{well.lat:.5f} N"), ("Longitude", f"{well.lon:.5f} E"),
        ("Spud Date", well.spud_date.isoformat()),
        ("Rig", well.rig), ("KB Elevation", f"{well.kb_m:g} m"),
        ("Total Depth (MD)", f"{well.td_md:,.0f} m"), ("Total Depth (TVD)", f"{well.td_tvd:,.0f} m"),
        ("Well Type", "Directional" if well.directional else "Vertical"),
        ("Status", well.status.title()),
    ]))
    blocks.append(("h", "1. FORMATION TOPS"))
    rows = [[f, f"{md:,.0f}", f"{well.tops_tvd[f]:,.0f}"] for f, md in well.tops_md.items()]
    blocks.append(("table", ["Formation", "Top MD (m)", "Top TVD (m)"], rows))
    blocks.append(("h", "2. CASING PROGRAM"))
    crow = [[c["size"], c["hole"], f"{c['shoe_md']:,.0f}", c["grade"], f"{c['toc_md']:,.0f}"] for c in well.casing]
    blocks.append(("table", ["Casing", "Hole", "Shoe MD (m)", "Grade", "TOC MD (m)"], crow))
    blocks.append(("h", "3. MUD PROGRAM"))
    mrow = [[m["hole"], f"{m['from_md']:,.0f} - {m['to_md']:,.0f}", m["mud_type"], f"{m['mw_min']:.2f} - {m['mw_max']:.2f}"] for m in well.mud]
    blocks.append(("table", ["Hole", "Interval MD (m)", "Mud Type", "MW (SG)"], mrow))
    blocks.append(("h", "4. DRILLING PROBLEMS AND LESSONS LEARNED"))
    seen_types: dict[str, str] = {}
    for ev in well.events:
        keep = ev.type == "cementing_issue" or rng.random() < 0.8
        if keep:
            blocks.append(("p", wcr_problem_sentences(ev, rng)))
        seen_types.setdefault(ev.type, ev.formation)
    if not well.events:
        blocks.append(("p", "No significant drilling problems were encountered."))
    blocks.append(("h", "5. RECOMMENDATIONS"))
    for et, fm in seen_types.items():
        if et in LESSON_TEXT and rng.random() < 0.7:
            blocks.append(("p", LESSON_TEXT[et].format(fm=fm)))
    return blocks
