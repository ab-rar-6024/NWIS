"""Engineer review queue for uncertain extracted events."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from conftest import needs_data
from nwis.api import app

pytestmark = needs_data


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_queue_lists_flagged_events_with_reasons(client):
    r = client.get("/api/review-queue").json()
    assert r["total_flagged"] <= r["total_events"]
    assert r["events"] and all(e["reasons"] for e in r["events"])
    assert sum(r["counts"].values()) == r["total_flagged"]


def test_review_round_trip_and_unknown_event(client):
    first = client.get("/api/review-queue").json()["events"][0]["id"]
    assert client.post(f"/api/events/{first}/review", json={"status": "confirmed"}).json()["review"] == "confirmed"
    assert first in [e["id"] for e in client.get("/api/review-queue?status=confirmed").json()["events"]]
    client.post(f"/api/events/{first}/review", json={"status": "pending"})
    assert first in [e["id"] for e in client.get("/api/review-queue?status=pending").json()["events"]]
    assert client.post("/api/events/99999999/review", json={"status": "confirmed"}).status_code == 404
    assert client.post(f"/api/events/{first}/review", json={"status": "bogus"}).status_code == 422
