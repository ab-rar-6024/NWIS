"""End-to-end pipeline tests on the synthetic dataset (PDF -> OCR/NLP -> consolidated events)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from conftest import DATA, needs_data

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from nwis.db import connect, init_db  # noqa: E402
from nwis.extraction.documents import classify, parse_wcr  # noqa: E402
from nwis.extraction.pdf_text import extract_pdf  # noqa: E402
from nwis.ingest import ingest_well_dir  # noqa: E402

pytestmark = needs_data


def _match(truth, preds, tol=15.0):
    used, tp = set(), 0
    for t in truth:
        for j, p in enumerate(preds):
            if j not in used and p["type"] == t["type"] and abs(p["md"] - t["md"]) <= tol:
                used.add(j)
                tp += 1
                break
    return tp


def test_native_pdf_parse_matches_header_and_tables():
    doc = extract_pdf(DATA / "raw" / "MRH-12" / "WCR.pdf")
    assert not doc.ocr_used and classify(doc, "WCR.pdf") == "WCR"
    w = parse_wcr(doc)
    assert w.header["name"] == "MRH-12" and w.header["field"] == "Moranhat"
    assert len(w.tops) == 10 and w.tops[0]["formation"] == "Alluvium"
    assert len(w.casing) >= 3 and w.casing[0]["size"] == '20"'
    assert all(t["md"] >= 0 for t in w.tops) and [t["md"] for t in w.tops] == sorted(t["md"] for t in w.tops)


def test_scanned_pdf_uses_ocr_and_recovers_well_identity():
    scanned = DATA / "raw" / "MRH-07" / "WCR.pdf"
    doc = extract_pdf(scanned)
    assert doc.ocr_used and doc.mean_confidence and doc.mean_confidence > 0.8
    w = parse_wcr(doc)
    assert w.header["name"] == "MRH-07"  # OCR confuses 0/O; the parser repairs it
    # MRH-07 is a shallow well (TD 3,008 m TVD): it only penetrates 7 of the 10 formations
    assert [t["formation"] for t in w.tops][-1] == "Kopili Shale" and len(w.tops) == 7
    assert w.header["td_md"] == 3130 and w.casing[-1]["shoe_md"] == 3130


def test_ingest_one_well_recovers_ground_truth_events(tmp_path):
    conn = connect(tmp_path / "t.db")
    init_db(conn)
    res = ingest_well_dir(conn, DATA / "raw" / "MRH-12")
    assert res["wcr"]["events"] > 0 and res["ddr"]["consolidated"] > 0
    truth = json.loads((DATA / "truth" / "MRH-12.json").read_text())["events"]
    got = [dict(r) for r in conn.execute("SELECT type, md, formation, tvd, corroborated FROM events")]
    tp = _match(truth, got)
    assert tp / len(truth) >= 0.9, (tp, len(truth))
    assert len(got) <= len(truth) + 2  # no runaway duplicates
    assert all(g["formation"] for g in got) and all(g["tvd"] is not None for g in got)
    assert sum(g["corroborated"] for g in got) > 0  # DDR and WCR mentions were merged
    n_logs = conn.execute("SELECT COUNT(*) FROM drilling_logs").fetchone()[0]
    assert n_logs > 500


def test_reingesting_the_same_document_is_idempotent(tmp_path):
    conn = connect(tmp_path / "t.db")
    init_db(conn)
    ingest_well_dir(conn, DATA / "raw" / "MRH-12")
    n1 = conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
    ingest_well_dir(conn, DATA / "raw" / "MRH-12")
    assert conn.execute("SELECT COUNT(*) FROM events").fetchone()[0] == n1
    assert conn.execute("SELECT COUNT(*) FROM wells").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 2
