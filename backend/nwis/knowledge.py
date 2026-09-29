"""Searchable knowledge repository: full-text search over events, daily narratives and lessons; lesson aggregation."""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict

import numpy as np

from .analytics import ACTION_TEXT, SUCCESS, mitigation_stats, recommendation
from .config import EVENT_LABELS, EVENT_TYPES, FORMATION_LEXICON
from .kb import KnowledgeIndex

SYNONYMS = [
    {"loss", "losses", "lost", "circulation", "seepage"},
    {"kick", "influx", "flowing"},
    {"stuck", "packoff", "pack-off", "overpull", "jarring"},
    {"overpressure", "overpressured", "overpressured", "pressure"},
    {"torque", "erratic"},
    {"cement", "cementing", "squeeze", "channeling", "bond"},
]
HAZARD_WORDS = {
    "mud_loss": ["loss", "losses", "lost circulation", "lcm", "seepage"],
    "kick": ["kick", "influx", "well control", "flowing", "kill"],
    "stuck_pipe": ["stuck", "pack-off", "packoff", "overpull", "jar", "fishing"],
    "overpressure": ["overpressure", "pore pressure", "abnormal pressure", "drilling break"],
    "torque_spike": ["torque"],
    "cementing_issue": ["cement", "cbl", "squeeze", "bond"],
}


def _fts_query(q: str) -> str | None:
    toks = re.findall(r"[A-Za-z0-9][A-Za-z0-9\-]*", q)
    parts = []
    for t in toks:
        tl = t.lower()
        group = next((g for g in SYNONYMS if tl in g), None)
        opts = sorted(group | {tl}) if group else [tl]
        terms = []
        for o in opts:
            o = o.replace("-", " ")
            terms.append(f'"{o}"' + ("*" if len(o) >= 3 and " " not in o else ""))
        parts.append("(" + " OR ".join(terms) + ")")
    return " AND ".join(parts) if parts else None


def search(conn: sqlite3.Connection, q: str, etype: str | None = None, formation: str | None = None, well: str | None = None,
           kinds: list[str] | None = None, limit: int = 30) -> list[dict]:
    fq = _fts_query(q)
    if not fq:
        return []
    where = ["search_fts MATCH ?"]
    args: list = [fq]
    if kinds:
        where.append(f"kind IN ({','.join('?' * len(kinds))})")
        args += kinds
    if etype:
        where.append("etype = ?")
        args.append(etype)
    if formation:
        where.append("formation = ?")
        args.append(formation)
    if well:
        where.append("well = ?")
        args.append(well)
    sql = (
        "SELECT kind, well, formation, etype, ref, md, snippet(search_fts, 6, '<mark>', '</mark>', ' ... ', 28) AS snip, "
        f"bm25(search_fts) AS rank FROM search_fts WHERE {' AND '.join(where)} ORDER BY rank LIMIT ?"
    )
    out = []
    for r in conn.execute(sql, (*args, limit)).fetchall():
        d = dict(r)
        kind, rid = d["ref"].split(":")
        d["id"] = int(rid)
        if kind == "event":
            e = conn.execute("SELECT summary, severity, npt_h, confidence, corroborated, date FROM events WHERE id=?", (int(rid),)).fetchone()
            if e:
                d.update({"summary": e["summary"], "severity": e["severity"], "npt_h": e["npt_h"], "confidence": e["confidence"],
                          "corroborated": bool(e["corroborated"]), "date": e["date"]})
        elif kind == "ddr":
            e = conn.execute("SELECT report_no, date, page FROM ddr_days WHERE id=?", (int(rid),)).fetchone()
            if e:
                d.update({"report_no": e["report_no"], "date": e["date"], "page": e["page"]})
        out.append(d)
    # BM25 ties are common (events share boilerplate); surface the costliest incidents first among equals
    out.sort(key=lambda d: (round(d["rank"], 1), -(d.get("npt_h") or 0)))
    return out


def _wells_penetrating(kb: KnowledgeIndex, formation: str) -> list:
    out = []
    for t in kb.traj.values():
        if (t.status or "").upper() == "ACTIVE":
            continue
        top = t.top_tvd(formation)
        if top is not None and t.td_tvd > top + 30:
            out.append(t)
    return out


def lessons(kb: KnowledgeIndex, conn: sqlite3.Connection, formation: str | None = None, hazard: str | None = None) -> list[dict]:
    """Aggregate offset experience per (formation, hazard) into lessons learned."""
    groups: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for e in kb.events:
        if not e["formation"]:
            continue
        if formation and e["formation"] != formation:
            continue
        if hazard and e["type"] != hazard:
            continue
        groups[(e["formation"], e["type"])].append(e)
    wcr = defaultdict(list)
    for r in conn.execute("SELECT l.formation, l.text, w.name FROM lessons l JOIN wells w ON w.id=l.well_id WHERE l.formation IS NOT NULL"):
        wcr[r["formation"]].append((r["text"], r["name"]))
    out = []
    for (fm, et), evs in groups.items():
        pen = _wells_penetrating(kb, fm)
        wells_hit = {e["well_id"] for e in evs}
        npts = [e["npt_h"] for e in evs if e["npt_h"] is not None]
        tvds = []
        for e in evs:
            t = kb.traj.get(e["well_id"])
            top = t.top_tvd(fm) if t else None
            if top is not None and e["tvd"] is not None:
                tvds.append(e["tvd"] - top)
        sev = Counter(e["severity"] for e in evs)
        ms = mitigation_stats(evs)
        detail: dict = {}
        if et == "mud_loss":
            rates = [e["details"].get("rate_m3h") for e in evs if e["details"].get("rate_m3h") is not None]
            if rates:
                detail["loss_rate_m3h"] = {"median": float(np.median(rates)), "max": float(max(rates))}
        if et in ("kick", "overpressure"):
            mws = [e["details"].get("mw1") for e in evs if e["details"].get("mw1")]
            if mws:
                detail["mw_after_sg"] = {"min": min(mws), "median": float(np.median(mws)), "max": max(mws)}
        if et == "stuck_pipe":
            mech = Counter(e["details"].get("mechanism") for e in evs if e["details"].get("mechanism"))
            if mech:
                detail["mechanisms"] = dict(mech.most_common(3))
        out.append({
            "formation": fm, "hazard": et, "label": EVENT_LABELS[et], "n_events": len(evs), "n_wells": len(wells_hit),
            "n_wells_penetrating": len(pen), "prevalence": len(wells_hit) / len(pen) if pen else None,
            "total_npt_h": float(sum(npts)), "mean_npt_h": float(np.mean(npts)) if npts else None,
            "severity": dict(sev), "depth_below_top_m": ({"p10": float(np.percentile(tvds, 10)), "median": float(np.median(tvds)),
                                                          "p90": float(np.percentile(tvds, 90))} if tvds else None),
            "actions": [{**m, "text": ACTION_TEXT.get(m["action"], m["action"])} for m in ms],
            "recommendation": recommendation(et, evs), "detail": detail,
            "wells": sorted({kb.wells[e["well_id"]]["name"] for e in evs}),
            "event_ids": [e["id"] for e in sorted(evs, key=lambda x: -(x["npt_h"] or 0))[:25]],
            "documented_lessons": [{"text": t, "well": w} for t, w in wcr.get(fm, []) if _lesson_matches(t, et)][:4],
        })
    out.sort(key=lambda r: -r["total_npt_h"])
    return out


def _lesson_matches(text: str, et: str) -> bool:
    t = text.lower()
    return any(w in t for w in HAZARD_WORDS.get(et, []))


def answer_question(kb: KnowledgeIndex, conn: sqlite3.Connection, question: str) -> dict:
    """Retrieval-based Q&A: resolves formation/hazard mentions, then answers from aggregated offset experience."""
    ql = question.lower()
    fm = next((f for f in FORMATION_LEXICON if re.sub(r"[^a-z]", "", f.lower()) in re.sub(r"[^a-z]", "", ql)
               or f.split()[0].lower() in ql), None)
    hz = [et for et, words in HAZARD_WORDS.items() if any(w in ql for w in words)]
    ls = lessons(kb, conn, fm, hz[0] if len(hz) == 1 else None)
    if hz and len(hz) > 1:
        ls = [l for l in ls if l["hazard"] in hz]
    hits = search(conn, question, formation=fm, kinds=["event"], limit=6) if not ls else []
    lines = []
    for l in ls[:4]:
        p = f"{l['prevalence']:.0%}" if l["prevalence"] is not None else "n/a"
        lines.append(f"{l['label']} in {l['formation']}: {l['n_events']} events across {l['n_wells']} of {l['n_wells_penetrating']} wells ({p}), "
                     f"mean NPT {l['mean_npt_h'] or 0:.0f} h. {l['recommendation']}")
    if not lines and hits:
        lines = [h.get("summary") or h["snip"] for h in hits[:4]]
    return {"question": question, "formation": fm, "hazards": hz, "answer": lines or ["No matching offset experience found."],
            "lessons": ls[:4], "evidence": hits}
