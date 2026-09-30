"""FastAPI application: REST + SSE API for the NWIS dashboard."""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import numpy as np
import pandas as pd
from fastapi import Depends, FastAPI, File, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import analytics, knowledge
from .config import DATA_DIR, DEFAULT_RADIUS_KM, EVENT_LABELS, EVENT_TYPES, ROOT, UPLOAD_DIR
from .db import connect, init_db, rows
from .impact import fleet_backtest
from .ingest import ingest_pdf
from .kb import KnowledgeIndex, Trajectory
from .live import LiveSession
from .risk_model import RiskModel, load_metrics, model_available

SAMPLES_DIR = DATA_DIR / "samples"
MAX_UPLOAD_MB = 50
FRONTEND_DIST = ROOT / "frontend" / "dist"


class AppState:
    def __init__(self):
        conn = connect()
        init_db(conn)
        self.kb_conn = conn
        self.kb = KnowledgeIndex(conn)
        self.model = RiskModel() if model_available() else None
        self.sessions: dict[int, LiveSession] = {}
        self.lock = threading.RLock()
        self._impact_cache: dict[tuple[float, float], dict] = {}
        self.reviews: dict[int, str] = {}  # event id -> confirmed | rejected (engineer sign-off on extracted events)

    def reload(self) -> None:
        with self.lock:
            self.kb.reload()
            self._impact_cache.clear()
            self.reviews.clear()  # event ids are reassigned when the knowledge base is rebuilt
            for wid, s in list(self.sessions.items()):
                if not s.running and wid in self.kb.traj:
                    s.kb = self.kb
                    s.prepare()

    def impact(self, radius_km: float, min_prevalence: float) -> dict:
        key = (radius_km, min_prevalence)
        with self.lock:
            if key not in self._impact_cache:
                self._impact_cache[key] = fleet_backtest(self.kb, radius_km, min_prevalence)
            return self._impact_cache[key]

    def session(self, well_id: int) -> LiveSession:
        with self.lock:
            if well_id not in self.kb.traj:
                raise HTTPException(404, "Unknown well")
            if well_id not in self.sessions:
                conn = connect()
                self.sessions[well_id] = LiveSession(self.kb, conn, well_id, model=self.model)
            return self.sessions[well_id]


state: AppState | None = None


def get_state() -> AppState:
    assert state is not None
    return state


def get_conn():
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    global state
    state = AppState()
    yield
    for s in state.sessions.values():
        s.running = False


app = FastAPI(title="eRTMAC-NWIS", version="1.0", lifespan=lifespan)
# NWIS_CORS_ORIGINS: comma-separated allow-list (e.g. your Vercel deployment's origin) for when the frontend
# and backend are hosted separately. Left unset, this stays wide open — there is no auth and no cookie-based
# session on this API, so an open CORS policy carries no credential-leak risk; it only matters if you later
# add authentication, at which point this should become an explicit allow-list.
_cors_env = [o.strip() for o in os.environ.get("NWIS_CORS_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(CORSMiddleware, allow_origins=_cors_env or ["*"], allow_methods=["*"], allow_headers=["*"])


# ------------------------------------------------------------------------------------------------ helpers
def _traj(st: AppState, well_id: int) -> Trajectory:
    tr = st.kb.traj.get(well_id)
    if tr is None:
        raise HTTPException(404, "Well not found or has no surface location yet")
    return tr


def _target_tops(st: AppState, tr: Trajectory, radius_km: float) -> tuple[list[dict], bool]:
    """Real tops when the well has been completed; otherwise predicted from offsets."""
    if tr.tops:
        tops = [{"formation": t["formation"], "tvd": t["tvd"], "md": t["md"], "sigma_m": 0.0, "n_offsets": 0} for t in tr.tops]
        return tops, False
    return analytics.predict_tops(st.kb, tr, radius_km), True


def _event_public(e: dict, wells: dict[int, dict]) -> dict:
    return {
        "id": e["id"], "well_id": e["well_id"], "well": wells[e["well_id"]]["name"], "type": e["type"], "label": EVENT_LABELS[e["type"]],
        "md": e["md"], "tvd": e["tvd"], "formation": e["formation"], "severity": e["severity"], "npt_h": e["npt_h"],
        "confidence": e["confidence"], "depth_source": e["depth_source"], "mitigations": e["mitigations"], "outcome": e["outcome"],
        "details": e["details"], "summary": e["summary"], "corroborated": bool(e["corroborated"]), "date": e["date"],
    }


# ------------------------------------------------------------------------------------------------ basic
@app.get("/api/health")
def health(st: AppState = Depends(get_state)):
    return {"ok": True, "wells": len(st.kb.wells), "events": len(st.kb.events), "model": model_available()}


@app.get("/api/summary")
def summary(st: AppState = Depends(get_state), conn=Depends(get_conn)):
    by_type = {t: 0 for t in EVENT_TYPES}
    npt = 0.0
    for e in st.kb.events:
        by_type[e["type"]] += 1
        npt += e["npt_h"] or 0
    docs = rows(conn.execute("SELECT kind, COUNT(*) n, SUM(ocr_used) ocr, SUM(pages) pages FROM documents GROUP BY kind"))
    active = [w for w in st.kb.wells.values() if (w["status"] or "").upper() == "ACTIVE"]
    return {
        "wells": len(st.kb.wells), "fields": len({w["field"] for w in st.kb.wells.values() if w["field"]}),
        "events": len(st.kb.events), "events_by_type": by_type, "total_npt_h": round(npt, 1), "documents": docs,
        "active_wells": [{"id": w["id"], "name": w["name"]} for w in active],
        "model": load_metrics() is not None,
        "corroborated": sum(1 for e in st.kb.events if e["corroborated"]),
    }


@app.get("/api/wells")
def list_wells(st: AppState = Depends(get_state), conn=Depends(get_conn)):
    docs = {r["well_id"]: r for r in conn.execute(
        "SELECT well_id, COUNT(*) n, SUM(kind='WCR') wcr, SUM(kind='DDR') ddr, SUM(ocr_used) ocr FROM documents GROUP BY well_id")}
    out = []
    for w in st.kb.wells.values():
        evs = st.kb.events_by_well.get(w["id"], [])
        counts = {t: 0 for t in EVENT_TYPES}
        for e in evs:
            counts[e["type"]] += 1
        d = docs.get(w["id"])
        out.append({
            "id": w["id"], "name": w["name"], "field": w["field"], "lat": w["lat"], "lon": w["lon"], "status": w["status"],
            "td_md": w["td_md"] or w["planned_td_md"], "td_tvd": w["td_tvd"], "spud_date": w["spud_date"], "rig": w["rig"],
            "directional": bool(w["directional"]), "events": len(evs), "event_counts": counts,
            "npt_h": round(sum(e["npt_h"] or 0 for e in evs), 1),
            "documents": {"wcr": bool(d and d["wcr"]), "ddr": bool(d and d["ddr"]), "ocr": bool(d and d["ocr"])},
        })
    out.sort(key=lambda x: x["name"])
    return out


@app.get("/api/wells/{well_id}")
def well_detail(well_id: int, st: AppState = Depends(get_state), conn=Depends(get_conn)):
    w = st.kb.wells.get(well_id)
    if not w:
        raise HTTPException(404, "Well not found")
    return {
        "well": w,
        "tops": rows(conn.execute("SELECT formation, md, tvd FROM formation_tops WHERE well_id=? ORDER BY md", (well_id,))),
        "casing": rows(conn.execute("SELECT size, hole, shoe_md, grade, toc_md FROM casing WHERE well_id=? ORDER BY shoe_md", (well_id,))),
        "mud": rows(conn.execute("SELECT hole, from_md, to_md, mud_type, mw_min, mw_max FROM mud_program WHERE well_id=? ORDER BY from_md", (well_id,))),
        "documents": rows(conn.execute("SELECT id, kind, filename, pages, ocr_used, ocr_pages, mean_conf, n_events, ingested_at FROM documents WHERE well_id=?", (well_id,))),
        "events": [_event_public(e, st.kb.wells) for e in sorted(st.kb.events_by_well.get(well_id, []), key=lambda x: x["md"])],
    }


@app.get("/api/wells/{well_id}/trajectory")
def trajectory(well_id: int, st: AppState = Depends(get_state)):
    tr = _traj(st, well_id)
    idx = np.arange(0, len(tr.md), max(1, len(tr.md) // 120))
    from .geo import km_to_latlon
    path = [km_to_latlon(tr.east0 + tr.e_m[i] / 1000, tr.north0 + tr.n_m[i] / 1000) for i in idx]
    return {"md": tr.md[idx].tolist(), "tvd": tr.tvd[idx].tolist(), "east_m": tr.e_m[idx].tolist(), "north_m": tr.n_m[idx].tolist(),
            "path": path}


@app.get("/api/wells/{well_id}/offsets")
def offsets(well_id: int, radius_km: float = Query(DEFAULT_RADIUS_KM, ge=0.5, le=50), st: AppState = Depends(get_state)):
    tr = _traj(st, well_id)
    res = []
    for t, d in st.kb.nearby(tr, radius_km):
        evs = st.kb.events_by_well.get(t.id, [])
        counts = {et: 0 for et in EVENT_TYPES}
        for e in evs:
            counts[e["type"]] += 1
        surface = float(np.hypot(tr.east0 - t.east0, tr.north0 - t.north0))
        res.append({"id": t.id, "name": t.name, "field": t.field, "lat": t.lat, "lon": t.lon, "distance_km": round(d, 2),
                    "surface_distance_km": round(surface, 2), "td_md": t.td_md, "td_tvd": t.td_tvd, "events": len(evs),
                    "event_counts": counts, "npt_h": round(sum(e["npt_h"] or 0 for e in evs), 1)})
    return {"radius_km": radius_km, "target": {"id": tr.id, "name": tr.name, "lat": tr.lat, "lon": tr.lon}, "offsets": res}


@app.get("/api/wells/{well_id}/correlation")
def correlation(well_id: int, radius_km: float = Query(DEFAULT_RADIUS_KM, ge=0.5, le=50), limit: int = Query(10, ge=1, le=30),
                st: AppState = Depends(get_state)):
    tr = _traj(st, well_id)
    tops, predicted = _target_tops(st, tr, radius_km)
    offs = st.kb.nearby(tr, radius_km, max_n=limit)

    def pack(t: Trajectory, tops_list: list[dict], d: float | None, predicted_flag: bool = False):
        evs = sorted(st.kb.events_by_well.get(t.id, []), key=lambda e: e["md"])
        return {"id": t.id, "name": t.name, "distance_km": None if d is None else round(d, 2), "td_md": t.td_md, "td_tvd": t.td_tvd,
                "status": t.status, "predicted": predicted_flag, "tops": tops_list,
                "events": [{"id": e["id"], "type": e["type"], "md": e["md"], "tvd": e["tvd"], "severity": e["severity"],
                            "npt_h": e["npt_h"], "summary": e["summary"], "formation": e["formation"]} for e in evs]}
    return {"radius_km": radius_km, "formations": st.kb.formation_order, "target": pack(tr, tops, None, predicted),
            "offsets": [pack(t, [{"formation": x["formation"], "tvd": x["tvd"], "md": x["md"]} for x in t.tops], d) for t, d in offs]}


@app.get("/api/wells/{well_id}/risk-profile")
def well_risk_profile(well_id: int, radius_km: float = Query(DEFAULT_RADIUS_KM, ge=0.5, le=50), st: AppState = Depends(get_state)):
    tr = _traj(st, well_id)
    tops, predicted = _target_tops(st, tr, radius_km)
    return {"predicted_tops": predicted, "tops": tops, "profile": analytics.risk_profile(st.kb, tr, tops, radius_km),
            "n_offsets": len(st.kb.nearby(tr, radius_km))}


@app.get("/api/wells/{well_id}/lookahead")
def lookahead(well_id: int, md: float = Query(0.0, ge=0), window: float = Query(400.0, ge=50, le=6000),
              radius_km: float = Query(DEFAULT_RADIUS_KM, ge=0.5, le=50), min_prevalence: float = Query(0.1, ge=0, le=1),
              st: AppState = Depends(get_state)):
    tr = _traj(st, well_id)
    tops, predicted = _target_tops(st, tr, radius_km)
    zones = analytics.hazard_zones(st.kb, tr, tops, md, md + window, radius_km, min_prevalence=min_prevalence)
    zones = [z for z in zones if z.md_to >= md and z.md_from <= md + window]
    return {"md": md, "window": window, "predicted_tops": predicted, "tops": tops, "zones": [z.to_dict() for z in zones]}


@app.get("/api/wells/{well_id}/logs")
def well_logs(well_id: int, step: int = Query(2, ge=1, le=20), conn=Depends(get_conn)):
    df = pd.read_sql_query("SELECT md, tvd, rop, wob, torque, spp, flow_in, flow_out, pit_delta, mw, gas, overpull FROM drilling_logs WHERE well_id=? ORDER BY md",
                           conn, params=(well_id,))
    return df.iloc[::step].round(3).to_dict(orient="list")


# ------------------------------------------------------------------------------------------------ knowledge
@app.get("/api/events")
def list_events(well: str | None = None, type: str | None = None, formation: str | None = None, severity: str | None = None,
                min_confidence: float = 0.0, limit: int = Query(300, le=2000), st: AppState = Depends(get_state)):
    res = []
    for e in st.kb.events:
        if type and e["type"] != type:
            continue
        if formation and e["formation"] != formation:
            continue
        if severity and e["severity"] != severity:
            continue
        if well and st.kb.wells[e["well_id"]]["name"] != well:
            continue
        if (e["confidence"] or 0) < min_confidence:
            continue
        res.append(e)
    res.sort(key=lambda e: -(e["npt_h"] or 0))
    return {"total": len(res), "events": [_event_public(e, st.kb.wells) for e in res[:limit]]}


# ------------------------------------------------------------------------------------------------ review queue
class ReviewBody(BaseModel):
    status: str = Field(pattern="^(confirmed|rejected|pending)$")


def _review_reasons(e: dict) -> list[str]:
    reasons = []
    if (e["confidence"] or 0) < 0.85:
        reasons.append("low extraction confidence")
    if e["depth_source"] != "explicit":
        reasons.append("depth inferred from report day")
    if not e["corroborated"]:
        reasons.append("reported in one document only")
    return reasons


@app.get("/api/review-queue")
def review_queue(status: str = Query("pending", pattern="^(pending|confirmed|rejected|all)$"), limit: int = Query(200, le=1000),
                 st: AppState = Depends(get_state)):
    rows = []
    for e in st.kb.events:
        reasons = _review_reasons(e)
        if not reasons:
            continue
        cur = st.reviews.get(e["id"], "pending")
        if status != "all" and cur != status:
            continue
        rows.append({**_event_public(e, st.kb.wells), "reasons": reasons, "review": cur})
    # least trustworthy first: most reasons, then lowest confidence
    rows.sort(key=lambda r: (-len(r["reasons"]), r["confidence"] or 0))
    flagged = [e for e in st.kb.events if _review_reasons(e)]
    counts = {"pending": 0, "confirmed": 0, "rejected": 0}
    for e in flagged:
        counts[st.reviews.get(e["id"], "pending")] += 1
    return {"counts": counts, "total_flagged": len(flagged), "total_events": len(st.kb.events), "events": rows[:limit]}


@app.post("/api/events/{event_id}/review")
def review_event(event_id: int, body: ReviewBody, st: AppState = Depends(get_state)):
    if not any(e["id"] == event_id for e in st.kb.events):
        raise HTTPException(404, "Event not found")
    if body.status == "pending":
        st.reviews.pop(event_id, None)
    else:
        st.reviews[event_id] = body.status
    return {"id": event_id, "review": body.status}


@app.get("/api/events/{event_id}")
def event_detail(event_id: int, radius_km: float = 8.0, st: AppState = Depends(get_state), conn=Depends(get_conn)):
    r = conn.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
    if not r:
        raise HTTPException(404, "Event not found")
    e = next(x for x in st.kb.events if x["id"] == event_id)
    tr = st.kb.traj.get(e["well_id"])
    similar = []
    if tr:
        for t, d in st.kb.nearby(tr, radius_km):
            for o in st.kb.events_by_well.get(t.id, []):
                if o["type"] == e["type"] and o["formation"] == e["formation"]:
                    similar.append({**_event_public(o, st.kb.wells), "distance_km": round(d, 2)})
        similar.sort(key=lambda x: x["distance_km"])
    out = _event_public(e, st.kb.wells)
    out.update({"description": e["description"], "sources": e["sources"], "similar": similar[:8]})
    return out


@app.get("/api/search")
def search(q: str = Query(..., min_length=2), type: str | None = None, formation: str | None = None, well: str | None = None,
           kinds: str | None = None, limit: int = Query(30, le=100), conn=Depends(get_conn)):
    k = [x for x in (kinds or "").split(",") if x in ("event", "ddr", "lesson")] or None
    return {"q": q, "results": knowledge.search(conn, q, type, formation, well, k, limit)}


@app.get("/api/lessons")
def get_lessons(formation: str | None = None, hazard: str | None = None, st: AppState = Depends(get_state), conn=Depends(get_conn)):
    return {"formations": st.kb.formation_order, "lessons": knowledge.lessons(st.kb, conn, formation, hazard)}


class AskBody(BaseModel):
    question: str = Field(min_length=3, max_length=500)


@app.post("/api/ask")
def ask(body: AskBody, st: AppState = Depends(get_state), conn=Depends(get_conn)):
    return knowledge.answer_question(st.kb, conn, body.question)


# ------------------------------------------------------------------------------------------------ documents
@app.get("/api/documents")
def documents(conn=Depends(get_conn)):
    return rows(conn.execute(
        "SELECT d.id, w.name well, d.kind, d.filename, d.pages, d.ocr_used, d.ocr_pages, d.mean_conf, d.n_events, d.ingested_at "
        "FROM documents d JOIN wells w ON w.id=d.well_id ORDER BY d.ingested_at DESC, d.id DESC"))


@app.get("/api/samples")
def samples():
    if not SAMPLES_DIR.exists():
        return []
    return [{"name": p.name, "size_kb": round(p.stat().st_size / 1024)} for p in sorted(SAMPLES_DIR.glob("*.pdf"))]


def _do_ingest(st: AppState, path: Path, filename: str) -> dict:
    conn = connect()
    try:
        init_db(conn)
        res = ingest_pdf(conn, path, filename)
        res["events_detail"] = rows(conn.execute(
            "SELECT id, type, md, formation, severity, npt_h, confidence, summary, corroborated FROM events WHERE well_id=? ORDER BY md", (res["well_id"],)))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    finally:
        conn.close()
    st.reload()
    return res


@app.post("/api/documents/upload")
def upload(file: UploadFile = File(...), st: AppState = Depends(get_state)):
    name = Path(file.filename or "upload.pdf").name
    if not name.lower().endswith(".pdf"):
        raise HTTPException(400, "Only PDF files are supported")
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{re.sub(r'[^A-Za-z0-9._-]', '_', name)}"
    size = 0
    with dest.open("wb") as fh:
        head = file.file.read(5)
        if head != b"%PDF-":
            fh.close()
            dest.unlink(missing_ok=True)
            raise HTTPException(400, "File does not look like a PDF")
        fh.write(head)
        size = len(head)
        while chunk := file.file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                fh.close()
                dest.unlink(missing_ok=True)
                raise HTTPException(413, f"File exceeds {MAX_UPLOAD_MB} MB")
            fh.write(chunk)
    return _do_ingest(st, dest, name)


@app.post("/api/documents/ingest-sample")
def ingest_sample(name: str = Query(...), st: AppState = Depends(get_state)):
    p = SAMPLES_DIR / Path(name).name
    if not p.exists() or p.suffix.lower() != ".pdf":
        raise HTTPException(404, "Sample not found")
    return _do_ingest(st, p, p.name)


@app.get("/api/impact")
def impact(radius_km: float = Query(DEFAULT_RADIUS_KM, ge=0.5, le=50), min_prevalence: float = Query(0.1, ge=0, le=1),
           st: AppState = Depends(get_state)):
    """Fleet-wide leave-one-well-out backtest: what share of recorded downtime would have been flagged in advance.

    Cached per (radius, min_prevalence) and invalidated whenever a new document is ingested.
    """
    return st.impact(radius_km, min_prevalence)


@app.get("/api/model/metrics")
def model_metrics():
    m = load_metrics()
    if not m:
        raise HTTPException(404, "Model not trained yet (run scripts/train_model.py)")
    return m


# ------------------------------------------------------------------------------------------------ live
class ControlBody(BaseModel):
    action: str = Field(pattern="^(start|pause|reset|speed)$")
    speed: float | None = Field(default=None, ge=0.5, le=60)
    start_md: float | None = Field(default=None, ge=0)


class SampleBody(BaseModel):
    md: float
    rop: float
    wob: float
    rpm: float
    torque: float
    spp: float
    flow_in: float
    flow_out: float
    pit_delta: float
    mw: float
    gas: float
    overpull: float
    inc: float = 0.0
    elapsed_h: float | None = None


@app.get("/api/live/{well_id}/snapshot")
async def live_snapshot(well_id: int, st: AppState = Depends(get_state)):
    return st.session(well_id).snapshot()


@app.post("/api/live/{well_id}/control")
async def live_control(well_id: int, body: ControlBody, st: AppState = Depends(get_state)):
    s = st.session(well_id)
    s.ensure_task()
    if body.speed is not None:
        s.speed = body.speed
    if body.action == "start":
        if s.idx >= len(s.replay):
            s.reset(body.start_md)
        elif body.start_md is not None and not s.history:
            s.reset(body.start_md)
        s.running = True
    elif body.action == "pause":
        s.running = False
    elif body.action == "reset":
        s.reset(body.start_md)
        s.publish("reset", s.state())
    s.publish("state", s.state())
    return s.state()


@app.post("/api/live/{well_id}/sample")
async def live_push(well_id: int, body: SampleBody, st: AppState = Depends(get_state)):
    """Entry point for a real eRTMAC feed: push one depth-based sample; alerts are computed identically to the replay."""
    s = st.session(well_id)
    s.running = False
    sample = body.model_dump(exclude_none=True)
    alerts = s.process_sample(sample)
    enriched = s.history[-1]  # process_sample() enriches a copy (tvd, mse, probs, ...); publish/return that, not the raw input
    s.publish("sample", enriched)
    for a in alerts:
        s.publish("alert", a)
    return {"sample": enriched, "alerts": alerts, "probs": s.probs}


class FeedbackBody(BaseModel):
    status: str = Field(pattern="^(confirmed|dismissed)$")


@app.post("/api/live/{well_id}/alerts/{alert_id}/feedback")
async def alert_feedback(well_id: int, alert_id: int, body: FeedbackBody, st: AppState = Depends(get_state)):
    """Operator marks an alert accurate or a false alarm — closes the loop between the system and the crew."""
    s = st.session(well_id)
    a = s.set_feedback(alert_id, body.status)
    if a is None:
        raise HTTPException(404, "Alert not found in this session")
    stats = s.feedback_stats()
    s.publish("feedback", {"alert_id": alert_id, "status": body.status, "stats": stats})
    return {"alert": a, "stats": stats}


@app.get("/api/live/{well_id}/feedback-stats")
async def feedback_stats(well_id: int, st: AppState = Depends(get_state)):
    return st.session(well_id).feedback_stats()


@app.get("/api/live/{well_id}/stream")
async def live_stream(well_id: int, st: AppState = Depends(get_state)):
    s = st.session(well_id)
    s.ensure_task()
    q = s.subscribe()

    async def gen():
        try:
            yield f"data: {json.dumps({'type': 'hello', 'data': s.state()})}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), 15)
                    yield f"data: {msg}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            s.unsubscribe(q)

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------------------------------------ static frontend
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = FRONTEND_DIST / path
        if path and f.is_file() and FRONTEND_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(FRONTEND_DIST / "index.html")
