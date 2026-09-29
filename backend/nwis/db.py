"""SQLite storage for the NWIS knowledge base."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS wells(
    id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, field TEXT, lat REAL, lon REAL, status TEXT,
    spud_date TEXT, rig TEXT, kb_m REAL, td_md REAL, td_tvd REAL, directional INTEGER DEFAULT 0,
    planned_td_md REAL, source TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS surveys(well_id INTEGER, md REAL, inc REAL, azi REAL, tvd REAL, north REAL, east REAL);
CREATE INDEX IF NOT EXISTS ix_surveys ON surveys(well_id, md);
CREATE TABLE IF NOT EXISTS formation_tops(well_id INTEGER, formation TEXT, md REAL, tvd REAL);
CREATE INDEX IF NOT EXISTS ix_tops ON formation_tops(well_id);
CREATE TABLE IF NOT EXISTS casing(well_id INTEGER, size TEXT, hole TEXT, shoe_md REAL, grade TEXT, toc_md REAL);
CREATE TABLE IF NOT EXISTS mud_program(well_id INTEGER, hole TEXT, from_md REAL, to_md REAL, mud_type TEXT, mw_min REAL, mw_max REAL);
CREATE TABLE IF NOT EXISTS documents(
    id INTEGER PRIMARY KEY, well_id INTEGER, kind TEXT, filename TEXT, pages INTEGER, ocr_used INTEGER,
    ocr_pages TEXT, mean_conf REAL, n_events INTEGER, status TEXT, ingested_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS events_raw(
    id INTEGER PRIMARY KEY, well_id INTEGER, doc_id INTEGER, kind TEXT, page INTEGER, type TEXT, md REAL,
    depth_source TEXT, npt_h REAL, severity TEXT, confidence REAL, outcome TEXT, mitigations TEXT,
    details TEXT, text TEXT, date TEXT, day_formation TEXT
);
CREATE INDEX IF NOT EXISTS ix_raw_well ON events_raw(well_id);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY, well_id INTEGER, type TEXT, md REAL, tvd REAL, formation TEXT, severity TEXT,
    npt_h REAL, confidence REAL, depth_source TEXT, mitigations TEXT, outcome TEXT, details TEXT,
    summary TEXT, description TEXT, sources TEXT, corroborated INTEGER, date TEXT
);
CREATE INDEX IF NOT EXISTS ix_events_well ON events(well_id, md);
CREATE INDEX IF NOT EXISTS ix_events_type ON events(type, formation);
CREATE TABLE IF NOT EXISTS ddr_days(
    id INTEGER PRIMARY KEY, well_id INTEGER, doc_id INTEGER, page INTEGER, report_no INTEGER, date TEXT,
    depth_md REAL, formation TEXT, text TEXT
);
CREATE INDEX IF NOT EXISTS ix_ddr_well ON ddr_days(well_id, depth_md);
CREATE TABLE IF NOT EXISTS lessons(id INTEGER PRIMARY KEY, well_id INTEGER, doc_id INTEGER, formation TEXT, text TEXT);
CREATE TABLE IF NOT EXISTS drilling_logs(
    well_id INTEGER, md REAL, tvd REAL, inc REAL, rop REAL, wob REAL, rpm REAL, torque REAL, spp REAL,
    flow_in REAL, flow_out REAL, pit_delta REAL, mw REAL, gas REAL, overpull REAL
);
CREATE INDEX IF NOT EXISTS ix_logs ON drilling_logs(well_id, md);
CREATE TABLE IF NOT EXISTS alerts(
    id INTEGER PRIMARY KEY, well_id INTEGER, ts TEXT DEFAULT CURRENT_TIMESTAMP, level TEXT, kind TEXT,
    md REAL, title TEXT, message TEXT, payload TEXT, feedback TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS search_fts USING fts5(
    kind UNINDEXED, well UNINDEXED, formation UNINDEXED, etype UNINDEXED, ref UNINDEXED, md UNINDEXED, text,
    tokenize='porter unicode61'
);
"""


def connect(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    cols = {r["name"] for r in conn.execute("PRAGMA table_info(alerts)")}
    if "feedback" not in cols:  # migration for databases built before the feedback loop was added
        conn.execute("ALTER TABLE alerts ADD COLUMN feedback TEXT")
    conn.commit()


def reset_db(path: str | Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else DB_PATH
    for suffix in ("", "-wal", "-shm"):
        f = Path(str(p) + suffix)
        if f.exists():
            f.unlink()
    conn = connect(p)
    init_db(conn)
    return conn


@contextmanager
def session(path: str | Path | None = None):
    conn = connect(path)
    try:
        init_db(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def j(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def rows(cur) -> list[dict]:
    return [dict(r) for r in cur.fetchall()]
