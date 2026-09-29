"""Document ingestion: PDF -> structured records in the knowledge base."""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path

import numpy as np
import pandas as pd

from .config import EVENT_LABELS
from .db import j
from .extraction.documents import DDRDay, WCRData, classify, parse_ddr, parse_wcr
from .extraction.events import RawEvent
from .extraction.pdf_text import ExtractedDoc, extract_pdf
from .geo import min_curvature

SAME_TOL_M = 20.0  # explicit-depth mentions closer than this describe the same incident
DAY_SPAN_M = 260.0  # a day-level depth is an upper bound; the event lies within this span above it


def _upsert_well(conn: sqlite3.Connection, name: str, **fields) -> int:
    row = conn.execute("SELECT id FROM wells WHERE name=?", (name,)).fetchone()
    clean = {k: v for k, v in fields.items() if v is not None}
    if row:
        if clean:
            sets = ", ".join(f"{k}=?" for k in clean)
            conn.execute(f"UPDATE wells SET {sets} WHERE id=?", (*clean.values(), row["id"]))
        return row["id"]
    cols = ["name", *clean.keys()]
    conn.execute(f"INSERT INTO wells({','.join(cols)}) VALUES({','.join('?' * len(cols))})", (name, *clean.values()))
    return conn.execute("SELECT id FROM wells WHERE name=?", (name,)).fetchone()["id"]


def _clear_doc(conn: sqlite3.Connection, well_id: int, kind: str, filename: str) -> None:
    for d in conn.execute("SELECT id FROM documents WHERE well_id=? AND kind=? AND filename=?", (well_id, kind, filename)).fetchall():
        conn.execute("DELETE FROM events_raw WHERE doc_id=?", (d["id"],))
        conn.execute("DELETE FROM ddr_days WHERE doc_id=?", (d["id"],))
        conn.execute("DELETE FROM lessons WHERE doc_id=?", (d["id"],))
        conn.execute("DELETE FROM documents WHERE id=?", (d["id"],))


def _insert_doc(conn, well_id, kind, filename, doc: ExtractedDoc, n_events: int, status: str = "ok") -> int:
    conn.execute(
        "INSERT INTO documents(well_id,kind,filename,pages,ocr_used,ocr_pages,mean_conf,n_events,status) VALUES(?,?,?,?,?,?,?,?,?)",
        (well_id, kind, filename, len(doc.pages), int(doc.ocr_used), j(doc.ocr_pages), doc.mean_confidence, n_events, status),
    )
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _insert_raw(conn, well_id, doc_id, kind, ev: RawEvent, date: str | None = None, day_formation: str | None = None) -> None:
    conn.execute(
        "INSERT INTO events_raw(well_id,doc_id,kind,page,type,md,depth_source,npt_h,severity,confidence,outcome,mitigations,details,text,date,day_formation)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (well_id, doc_id, kind, ev.page, ev.type, ev.md, ev.depth_source, ev.npt_h, ev.severity, ev.confidence, ev.outcome,
         j(ev.mitigations), j(ev.details), " ".join(ev.sentences), date, day_formation),
    )


# --------------------------------------------------------------------------- WCR / DDR
def _ingest_wcr(conn, doc: ExtractedDoc, filename: str) -> dict:
    data: WCRData = parse_wcr(doc)
    h = data.header
    if not h.get("name"):
        raise ValueError("Could not read the well name from this completion report")
    well_id = _upsert_well(
        conn, h["name"], field=h.get("field"), lat=h.get("lat"), lon=h.get("lon"), status=h.get("status"),
        spud_date=h.get("spud_date"), rig=h.get("rig"), kb_m=h.get("kb_m"), td_md=h.get("td_md"), td_tvd=h.get("td_tvd"),
        directional=int(bool(h.get("directional"))), source="wcr",
    )
    _clear_doc(conn, well_id, "WCR", filename)
    conn.execute("DELETE FROM formation_tops WHERE well_id=?", (well_id,))
    conn.execute("DELETE FROM casing WHERE well_id=?", (well_id,))
    conn.execute("DELETE FROM mud_program WHERE well_id=?", (well_id,))
    conn.executemany("INSERT INTO formation_tops VALUES(?,?,?,?)", [(well_id, t["formation"], t["md"], t["tvd"]) for t in data.tops])
    conn.executemany("INSERT INTO casing VALUES(?,?,?,?,?,?)", [(well_id, c["size"], c["hole"], c["shoe_md"], c["grade"], c["toc_md"]) for c in data.casing])
    conn.executemany("INSERT INTO mud_program VALUES(?,?,?,?,?,?,?)", [(well_id, m["hole"], m["from_md"], m["to_md"], m["mud_type"], m["mw_min"], m["mw_max"]) for m in data.mud])
    doc_id = _insert_doc(conn, well_id, "WCR", filename, doc, len(data.events))
    for ev in data.events:
        _insert_raw(conn, well_id, doc_id, "WCR", ev)
    for r in data.recommendations:
        conn.execute("INSERT INTO lessons(well_id,doc_id,formation,text) VALUES(?,?,?,?)", (well_id, doc_id, r["formation"], r["text"]))
    return {"well": h["name"], "well_id": well_id, "kind": "WCR", "events": len(data.events), "tops": len(data.tops),
            "casing": len(data.casing), "lessons": len(data.recommendations), "ocr_pages": doc.ocr_pages,
            "ocr_confidence": doc.mean_confidence}


def _ingest_ddr(conn, doc: ExtractedDoc, filename: str) -> dict:
    days: list[DDRDay] = parse_ddr(doc)
    if not days or not days[0].well:
        raise ValueError("Could not read the well name from this daily drilling report")
    name = days[0].well
    well_id = _upsert_well(conn, name, field=days[0].field)
    _clear_doc(conn, well_id, "DDR", filename)
    n_ev = sum(len(d.events) for d in days)
    doc_id = _insert_doc(conn, well_id, "DDR", filename, doc, n_ev)
    for d in days:
        conn.execute("INSERT INTO ddr_days(well_id,doc_id,page,report_no,date,depth_md,formation,text) VALUES(?,?,?,?,?,?,?,?)",
                     (well_id, doc_id, d.page, d.report_no, d.date, d.depth_md, d.formation, " ".join(d.sentences)))
        for ev in d.events:
            _insert_raw(conn, well_id, doc_id, "DDR", ev, d.date, d.formation)
    return {"well": name, "well_id": well_id, "kind": "DDR", "events": n_ev, "days": len(days),
            "ocr_pages": doc.ocr_pages, "ocr_confidence": doc.mean_confidence}


def ingest_pdf(conn: sqlite3.Connection, path: str | Path, filename: str | None = None) -> dict:
    path = Path(path)
    filename = filename or path.name
    doc = extract_pdf(path)
    kind = classify(doc, filename)
    if kind == "WCR":
        res = _ingest_wcr(conn, doc, filename)
    elif kind == "DDR":
        res = _ingest_ddr(conn, doc, filename)
    else:
        raise ValueError("Unrecognised document: expected a Well Completion Report or Daily Drilling Report")
    res["consolidated"] = consolidate_well(conn, res["well_id"])
    conn.commit()
    return res


# --------------------------------------------------------------------------- consolidation
def _well_geometry(conn, well_id: int):
    tops = conn.execute("SELECT formation, md, tvd FROM formation_tops WHERE well_id=? ORDER BY md", (well_id,)).fetchall()
    sv = conn.execute("SELECT md, tvd FROM surveys WHERE well_id=? ORDER BY md", (well_id,)).fetchall()
    return tops, sv


def _formation_and_tvd(md: float, tops, sv, td_md, td_tvd) -> tuple[str | None, float | None]:
    fm = None
    for t in tops:
        if md >= t["md"]:
            fm = t["formation"]
        else:
            break
    tvd = None
    if sv:
        tvd = float(np.interp(md, [s["md"] for s in sv], [s["tvd"] for s in sv]))
    elif tops:
        xs = [t["md"] for t in tops]
        ys = [t["tvd"] for t in tops]
        if td_md and td_tvd:
            xs, ys = xs + [td_md], ys + [td_tvd]
        tvd = float(np.interp(md, xs, ys))
    return fm, tvd


def _same_event(a: dict, b: dict) -> bool:
    if a["type"] != b["type"]:
        return False
    a_day, b_day = a["depth_source"] != "explicit", b["depth_source"] != "explicit"
    if not a_day and not b_day:
        return abs(a["md"] - b["md"]) <= SAME_TOL_M
    if a_day and b_day:
        return False  # two day-level mentions of the same type are treated as distinct incidents
    day, other = (a, b) if a_day else (b, a)
    return day["md"] - DAY_SPAN_M <= other["md"] <= day["md"] + 5.0


SEV_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}


def build_summary(etype: str, md: float, formation: str | None, d: dict, mitigations: list[str], outcome: str | None, npt: float | None) -> str:
    label = EVENT_LABELS.get(etype, etype)
    bits: list[str] = []
    if etype == "mud_loss":
        if d.get("severity"):
            label = f"{d['severity'].capitalize()} mud loss"
        if d.get("rate_m3h") is not None:
            bits.append(f"{d['rate_m3h']:g} m3/hr")
    elif etype == "kick":
        if d.get("gain_m3") is not None:
            bits.append(f"pit gain {d['gain_m3']:g} m3")
        if d.get("mw1") is not None:
            bits.append(f"MW to {d['mw1']:.2f} SG")
    elif etype == "stuck_pipe":
        if d.get("mechanism"):
            bits.append(d["mechanism"])
        if d.get("overpull_t") is not None:
            bits.append(f"overpull {d['overpull_t']:g} t")
    elif etype == "overpressure":
        if d.get("pp_sg") is not None:
            bits.append(f"PP ~{d['pp_sg']:.2f} SG")
        if d.get("mw1") is not None:
            bits.append(f"MW to {d['mw1']:.2f} SG")
    elif etype == "torque_spike":
        if d.get("peak_knm") is not None:
            bits.append(f"peak {d['peak_knm']:g} kNm")
    elif etype == "cementing_issue":
        if d.get("kind"):
            bits.append(d["kind"])
    elif etype == "fishing":
        if d.get("tool"):
            bits.append(d["tool"])
    if mitigations:
        bits.append("action: " + ", ".join(m.replace("_", " ") for m in mitigations))
    if outcome:
        bits.append(outcome.replace("_", " "))
    if npt is not None:
        bits.append(f"NPT {npt:g} h")
    where = f" at {md:,.0f} m" + (f" ({formation})" if formation else "")
    return f"{label}{where}" + (": " + "; ".join(bits) if bits else "")


def consolidate_well(conn: sqlite3.Connection, well_id: int) -> int:
    """Merge raw mentions (DDR + WCR) into one record per incident; assign formation/TVD; refresh the search index."""
    well = conn.execute("SELECT * FROM wells WHERE id=?", (well_id,)).fetchone()
    tops, sv = _well_geometry(conn, well_id)
    raw = [dict(r) for r in conn.execute("SELECT * FROM events_raw WHERE well_id=?", (well_id,))]
    for r in raw:
        r["mitigations"] = json.loads(r["mitigations"] or "[]")
        r["details"] = json.loads(r["details"] or "{}")
    raw.sort(key=lambda r: (r["type"], r["md"]))

    clusters: list[list[dict]] = []
    for r in raw:
        placed = False
        for c in clusters:
            if any(_same_event(r, m) for m in c):
                c.append(r)
                placed = True
                break
        if not placed:
            clusters.append([r])

    conn.execute("DELETE FROM events WHERE well_id=?", (well_id,))
    conn.execute("DELETE FROM search_fts WHERE well=? AND kind IN ('event','ddr','lesson')", (well["name"],))
    docs = {d["id"]: dict(d) for d in conn.execute("SELECT * FROM documents WHERE well_id=?", (well_id,))}
    n = 0
    for c in clusters:
        c.sort(key=lambda r: (r["depth_source"] != "explicit", r["kind"] != "DDR", -(r["confidence"] or 0)))
        p = c[0]
        details: dict = {}
        for m in reversed(c):
            details.update({k: v for k, v in m["details"].items() if v is not None})
        details.update({k: v for k, v in p["details"].items() if v is not None})
        mitig: list[str] = []
        for m in c:
            for t in m["mitigations"]:
                if t not in mitig:
                    mitig.append(t)
        outcome = next((m["outcome"] for m in c if m["outcome"]), None)
        npt = next((m["npt_h"] for m in c if m["npt_h"] is not None), None)
        sev = max((m["severity"] for m in c if m["severity"]), key=lambda s: SEV_ORDER.get(s, 0), default="low")
        kinds = {m["kind"] for m in c}
        conf = min(0.99, max(m["confidence"] or 0 for m in c) + (0.05 if len(kinds) > 1 else 0.0))
        md = p["md"]
        fm, tvd = _formation_and_tvd(md, tops, sv, well["td_md"], well["td_tvd"])
        if fm is None:
            fm = next((m["day_formation"] for m in c if m["day_formation"]), None)
        srcs = [{"doc_id": m["doc_id"], "kind": m["kind"], "page": m["page"], "filename": docs.get(m["doc_id"], {}).get("filename")} for m in c]
        desc_parts = []
        for m in sorted(c, key=lambda r: r["kind"] != "DDR"):
            desc_parts.append(f"[{m['kind']}{' p.' + str(m['page']) if m['page'] else ''}] {m['text']}")
        description = "\n".join(desc_parts)
        summary = build_summary(p["type"], md, fm, details, mitig, outcome, npt)
        date = next((m["date"] for m in c if m["date"]), None)
        cur = conn.execute(
            "INSERT INTO events(well_id,type,md,tvd,formation,severity,npt_h,confidence,depth_source,mitigations,outcome,details,summary,description,sources,corroborated,date)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (well_id, p["type"], md, tvd, fm, sev, npt, round(conf, 2), p["depth_source"], j(mitig), outcome, j(details), summary,
             description, j(srcs), int(len(kinds) > 1), date),
        )
        eid = cur.lastrowid
        conn.execute("INSERT INTO search_fts(kind,well,formation,etype,ref,md,text) VALUES('event',?,?,?,?,?,?)",
                     (well["name"], fm, p["type"], f"event:{eid}", md, f"{summary}. {EVENT_LABELS.get(p['type'], '')} {description}"))
        n += 1
    for d in conn.execute("SELECT id, formation, depth_md, text FROM ddr_days WHERE well_id=?", (well_id,)).fetchall():
        conn.execute("INSERT INTO search_fts(kind,well,formation,etype,ref,md,text) VALUES('ddr',?,?,NULL,?,?,?)",
                     (well["name"], d["formation"], f"ddr:{d['id']}", d["depth_md"], d["text"]))
    for l in conn.execute("SELECT id, formation, text FROM lessons WHERE well_id=?", (well_id,)).fetchall():
        conn.execute("INSERT INTO search_fts(kind,well,formation,etype,ref,md,text) VALUES('lesson',?,?,NULL,?,NULL,?)",
                     (well["name"], l["formation"], f"lesson:{l['id']}", l["text"]))
    return n


# --------------------------------------------------------------------------- structured data (DB/eRTMAC exports)
LOG_COLS = ["md", "tvd", "inc", "rop", "wob", "rpm", "torque", "spp", "flow_in", "flow_out", "pit_delta", "mw", "gas", "overpull"]


def load_survey(conn: sqlite3.Connection, well_id: int, csv_path: str | Path) -> int:
    df = pd.read_csv(csv_path)[["md", "inc", "azi"]].sort_values("md").reset_index(drop=True)
    tvd, north, east = min_curvature(df["md"], df["inc"], df["azi"])  # recomputed, never trusted from the file
    conn.execute("DELETE FROM surveys WHERE well_id=?", (well_id,))
    conn.executemany("INSERT INTO surveys VALUES(?,?,?,?,?,?,?)",
                     [(well_id, float(a), float(b), float(c), float(t), float(n), float(e))
                      for a, b, c, t, n, e in zip(df["md"], df["inc"], df["azi"], tvd, north, east)])
    return len(df)


def load_logs(conn: sqlite3.Connection, well_id: int, csv_path: str | Path) -> int:
    df = pd.read_csv(csv_path)
    conn.execute("DELETE FROM drilling_logs WHERE well_id=?", (well_id,))
    data = [(well_id, *[float(r[c]) for c in LOG_COLS]) for _, r in df.iterrows()]
    conn.executemany(f"INSERT INTO drilling_logs VALUES({','.join('?' * (len(LOG_COLS) + 1))})", data)
    return len(data)


def load_casing_plan(conn: sqlite3.Connection, well_id: int, csv_path: str | Path) -> int:
    """Load a well's PLANNED casing programme (known before spud, same as a real drilling programme) into the
    same `casing` table a completion report would populate. This only carries mechanical hole sizes — never
    formation tops or hazard data — so it doesn't leak anything the live monitor shouldn't have in advance.
    """
    df = pd.read_csv(csv_path)
    conn.execute("DELETE FROM casing WHERE well_id=?", (well_id,))
    conn.executemany("INSERT INTO casing VALUES(?,?,?,?,?,?)",
                     [(well_id, r["size"], r["hole"], float(r["shoe_md"]), r["grade"], float(r["toc_md"])) for _, r in df.iterrows()])
    return len(df)


def load_active_well(conn: sqlite3.Connection, wdir: Path) -> int:
    hdr = json.loads((wdir / "well_header.json").read_text())
    well_id = _upsert_well(conn, hdr["name"], field=hdr["field"], lat=hdr["lat"], lon=hdr["lon"], status="ACTIVE",
                           spud_date=hdr["spud_date"], rig=hdr["rig"], kb_m=hdr["kb_m"], planned_td_md=hdr["planned_td_md"],
                           directional=int(hdr["directional"]), source="well_plan")
    load_survey(conn, well_id, wdir / "plan_survey.csv")
    if (wdir / "plan_casing.csv").exists():
        load_casing_plan(conn, well_id, wdir / "plan_casing.csv")
    conn.commit()
    return well_id


def ingest_well_dir(conn: sqlite3.Connection, wdir: Path, log=print) -> dict:
    """Ingest one well folder: WCR first (defines the well, tops, casing), then DDR, then structured CSVs."""
    out: dict = {"dir": wdir.name}
    if (wdir / "WCR.pdf").exists():
        out["wcr"] = ingest_pdf(conn, wdir / "WCR.pdf")
    if (wdir / "DDR.pdf").exists():
        out["ddr"] = ingest_pdf(conn, wdir / "DDR.pdf")
    row = conn.execute("SELECT id FROM wells WHERE name=?", (wdir.name,)).fetchone()
    if row:
        if (wdir / "survey.csv").exists():
            out["survey_rows"] = load_survey(conn, row["id"], wdir / "survey.csv")
            consolidate_well(conn, row["id"])  # refresh TVD using the real survey
        if (wdir / "logs.csv").exists():
            out["log_rows"] = load_logs(conn, row["id"], wdir / "logs.csv")
    conn.commit()
    return out
