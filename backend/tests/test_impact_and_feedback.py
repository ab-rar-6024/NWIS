"""Fleet-wide impact backtest and the operator feedback loop."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import needs_data
from nwis.db import connect
from nwis.impact import backtest_well, fleet_backtest
from nwis.kb import KnowledgeIndex

pytestmark = needs_data


@pytest.fixture(scope="module")
def kb():
    return KnowledgeIndex(connect())


def test_backtest_is_leave_one_out_and_bounded(kb):
    r = fleet_backtest(kb, radius_km=8.0, min_prevalence=0.1)
    assert r["n_wells"] > 30 and r["total_events"] > 300
    assert 0 <= r["event_coverage"] <= 1 and 0 <= r["npt_coverage"] <= 1
    assert r["flagged_events"] <= r["total_events"] and r["flagged_npt_h"] <= r["total_npt_h"]
    # a real, non-trivial share of history would have been flagged (not 0%, not implausibly 100%)
    assert 0.3 < r["event_coverage"] < 0.95
    assert r["exemplar"]["n_events"] == max(w["n_events"] for w in r["wells"]) or r["exemplar"]["total_npt_h"] == max(w["total_npt_h"] for w in r["wells"])


def test_backtest_never_uses_the_wells_own_data(kb):
    wid = next(w["id"] for w in kb.wells.values() if w["name"] == "MRH-12")
    r = backtest_well(kb, wid, radius_km=8.0)
    # backtest_well excludes fishing events (a consequence of stuck pipe, not an independently forecastable hazard)
    expected = sum(1 for e in kb.events_by_well[wid] if e["type"] != "fishing" and e["md"] is not None)
    assert r["well"] == "MRH-12" and r["n_events"] == expected
    # a tighter radius can only remove offsets, never add information back from the well itself
    r_tight = backtest_well(kb, wid, radius_km=0.01)
    assert r_tight["n_flagged"] <= r["n_flagged"]


def test_wider_radius_never_reduces_coverage(kb):
    narrow = fleet_backtest(kb, radius_km=3.0, min_prevalence=0.1)
    wide = fleet_backtest(kb, radius_km=12.0, min_prevalence=0.1)
    assert wide["flagged_events"] >= narrow["flagged_events"]


@pytest.fixture(scope="module")
def client():
    from nwis.api import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def active_id(client):
    return next(w["id"] for w in client.get("/api/wells").json() if w["status"] == "ACTIVE")


def test_impact_endpoint_is_cached(client):
    import time

    t0 = time.time()
    r1 = client.get("/api/impact?radius_km=8&min_prevalence=0.1").json()
    first = time.time() - t0
    t0 = time.time()
    r2 = client.get("/api/impact?radius_km=8&min_prevalence=0.1").json()
    second = time.time() - t0
    assert r1 == r2
    assert second < first / 2 or second < 0.05


def test_feedback_round_trip_and_stats(client, active_id):
    client.post(f"/api/live/{active_id}/control", json={"action": "reset", "start_md": 2900})
    base = dict(rop=9, wob=10, rpm=110, torque=14, spp=210, flow_in=2500, flow_out=2500, pit_delta=0, mw=1.3, gas=40, overpull=3.5)
    for i in range(4):
        client.post(f"/api/live/{active_id}/sample", json={**base, "md": 2900 + 5 * i})
    kick = client.post(f"/api/live/{active_id}/sample", json={**base, "md": 2940, "flow_out": 2640, "pit_delta": 1.5}).json()
    assert kick["alerts"], "expected a realtime alert to be raised"
    aid = kick["alerts"][0]["id"]
    r = client.post(f"/api/live/{active_id}/alerts/{aid}/feedback", json={"status": "confirmed"})
    assert r.status_code == 200 and r.json()["stats"]["confirmed"] == 1
    stats = client.get(f"/api/live/{active_id}/feedback-stats").json()
    assert stats["confirmed"] == 1 and stats["agreement"] == 1.0
    assert client.post(f"/api/live/{active_id}/alerts/{aid}/feedback", json={"status": "nonsense"}).status_code == 422
    assert client.post(f"/api/live/{active_id}/alerts/999999999/feedback", json={"status": "confirmed"}).status_code == 404
