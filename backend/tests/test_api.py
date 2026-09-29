from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from conftest import DATA, needs_data

pytestmark = needs_data


@pytest.fixture(scope="module")
def client():
    from nwis.api import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def active_id(client):
    return next(w["id"] for w in client.get("/api/wells").json() if w["status"] == "ACTIVE")


def test_summary_and_wells(client):
    s = client.get("/api/summary").json()
    assert s["wells"] >= 40 and s["events"] > 300 and s["corroborated"] > 0
    wells = client.get("/api/wells").json()
    assert all(w["lat"] and w["lon"] for w in wells)


def test_offsets_respect_radius_and_are_sorted(client, active_id):
    r = client.get(f"/api/wells/{active_id}/offsets?radius_km=4").json()["offsets"]
    assert r and all(o["distance_km"] <= 4 for o in r)
    assert [o["distance_km"] for o in r] == sorted(o["distance_km"] for o in r)
    wide = client.get(f"/api/wells/{active_id}/offsets?radius_km=10").json()["offsets"]
    assert len(wide) > len(r)


def test_correlation_and_lookahead_shapes(client, active_id):
    c = client.get(f"/api/wells/{active_id}/correlation?radius_km=6&limit=5").json()
    assert c["target"]["predicted"] is True and len(c["offsets"]) == 5 and c["offsets"][0]["tops"]
    la = client.get(f"/api/wells/{active_id}/lookahead?md=2800&window=500").json()
    assert la["zones"] and all(2800 - 200 <= z["md_center"] <= 3400 for z in la["zones"])
    assert all("recommendation" in z for z in la["zones"])


def test_search_highlights_and_filters(client):
    r = client.get("/api/search?q=lost circulation&type=mud_loss&kinds=event").json()["results"]
    assert r and all(x["etype"] == "mud_loss" for x in r)
    r = client.get("/api/search?q=pack-off stuck&kinds=ddr").json()["results"]
    assert r and "<mark>" in r[0]["snip"]
    assert client.get("/api/search?q=%22%22").json()["results"] == []


def test_lessons_and_ask(client):
    l = client.get("/api/lessons?formation=Kopili Shale&hazard=overpressure").json()["lessons"]
    assert l and l[0]["hazard"] == "overpressure" and l[0]["actions"]
    a = client.post("/api/ask", json={"question": "What problems occur in the Sylhet Limestone?"}).json()
    assert a["formation"] == "Sylhet Limestone" and "mud loss" in a["answer"][0].lower()
    assert client.post("/api/ask", json={"question": "x"}).status_code == 422


def test_upload_validation(client):
    assert client.post("/api/documents/upload", files={"file": ("x.pdf", b"not a pdf")}).status_code == 400
    assert client.post("/api/documents/upload", files={"file": ("x.txt", b"%PDF-1.4")}).status_code == 400
    assert client.post("/api/documents/ingest-sample?name=../../etc/passwd").status_code == 404


def test_upload_real_report_creates_well_on_map(client):
    n0 = len(client.get("/api/wells").json())
    with (DATA / "samples" / "BRS-15_WCR.pdf").open("rb") as f:
        r = client.post("/api/documents/upload", files={"file": ("BRS-15_WCR.pdf", f, "application/pdf")})
    assert r.status_code == 200 and r.json()["well"] == "BRS-15"
    with (DATA / "samples" / "BRS-15_DDR.pdf").open("rb") as f:
        r = client.post("/api/documents/upload", files={"file": ("BRS-15_DDR.pdf", f, "application/pdf")})
    assert r.status_code == 200 and r.json()["consolidated"] > 3
    wells = client.get("/api/wells").json()
    assert len(wells) == n0 + 1 and any(w["name"] == "BRS-15" and w["events"] > 3 for w in wells)


def test_live_control_and_external_push(client, active_id):
    st = client.post(f"/api/live/{active_id}/control", json={"action": "reset", "start_md": 3000}).json()
    assert not st["running"] and st["md"] is None
    sample = dict(md=3010, rop=9, wob=10, rpm=110, torque=14, spp=210, flow_in=2500, flow_out=2500, pit_delta=0, mw=1.3, gas=40, overpull=3.5)
    for i in range(6):  # steady baseline
        client.post(f"/api/live/{active_id}/sample", json={**sample, "md": 3000 + 5 * i})
    kick = client.post(f"/api/live/{active_id}/sample", json={**sample, "md": 3040, "flow_out": 2640, "pit_delta": 1.5}).json()
    kinds = {(a["kind"], a["hazard"]) for a in kick["alerts"]}
    assert ("realtime", "kick") in kinds
    snap = client.get(f"/api/live/{active_id}/snapshot").json()
    assert len(snap["history"]) == 7 and snap["alerts"]
    assert client.post(f"/api/live/{active_id}/control", json={"action": "bogus"}).status_code == 422


def test_live_replay_runs_in_background(client, active_id):
    client.post(f"/api/live/{active_id}/control", json={"action": "reset", "start_md": 1300})
    client.post(f"/api/live/{active_id}/control", json={"action": "start", "speed": 60})
    time.sleep(4)
    st = client.post(f"/api/live/{active_id}/control", json={"action": "pause"}).json()
    snap = client.get(f"/api/live/{active_id}/snapshot").json()
    assert st["md"] > 1300 and len(snap["history"]) > 20
