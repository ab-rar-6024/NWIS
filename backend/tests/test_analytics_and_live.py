"""Analytics, risk model and live alert engine against the synthetic ground truth."""
from __future__ import annotations

import json

import numpy as np
import pytest

from conftest import DATA, needs_data
from nwis.analytics import hazard_zones, predict_tops, risk_profile
from nwis.db import connect
from nwis.kb import KnowledgeIndex
from nwis.risk_model import RiskModel, load_metrics, model_available

pytestmark = needs_data


@pytest.fixture(scope="module")
def kb():
    return KnowledgeIndex(connect())


@pytest.fixture(scope="module")
def active(kb):
    w = next(w for w in kb.wells.values() if (w["status"] or "").upper() == "ACTIVE")
    return kb.traj[w["id"]], json.loads((DATA / "truth" / f"{w['name']}.json").read_text())


def test_predicted_tops_are_close_to_truth(kb, active):
    tr, truth = active
    pred = {p["formation"]: p for p in predict_tops(kb, tr, 8.0)}
    errs = [abs(pred[f]["md"] - md) for f, md in truth["tops_md"].items() if f in pred and md > 0]
    assert len(errs) >= 8 and float(np.mean(errs)) < 30 and max(errs) < 60


def test_predicted_formations_are_unique_and_ordered(kb, active):
    tr, _ = active
    pt = predict_tops(kb, tr, 8.0)
    names = [p["formation"] for p in pt]
    assert len(names) == len(set(names))
    assert [p["tvd"] for p in pt] == sorted(p["tvd"] for p in pt)


def test_hazard_zones_cover_the_forced_scenario(kb, active):
    tr, truth = active
    pt = predict_tops(kb, tr, 8.0)
    zones = hazard_zones(kb, tr, pt, 0, tr.td_md, 8.0, min_prevalence=0.1)
    for etype in ("overpressure", "kick", "stuck_pipe"):
        evs = [e for e in truth["events"] if e["type"] == etype]
        covered = sum(1 for e in evs if any(z.type == etype and z.md_from - 50 <= e["md"] <= z.md_to + 50 for z in zones))
        assert covered >= max(1, len(evs) - 1), (etype, covered, len(evs))
    z = next(z for z in zones if z.type == "overpressure" and z.level == "high")
    assert "mud weight" in z.recommendation.lower() or "mw" in z.recommendation.lower()


def test_risk_profile_flags_kopili_as_costly(kb, active):
    tr, _ = active
    prof = {r["formation"]: r for r in risk_profile(kb, tr, predict_tops(kb, tr, 8.0), 8.0)}
    assert prof["Kopili Shale"]["risk"]["overpressure"]["prevalence"] > 0.3
    assert prof["Kopili Shale"]["expected_npt_h"] > prof["Alluvium"]["expected_npt_h"]


def test_model_metrics_are_grouped_cv_and_better_than_chance():
    assert model_available()
    m = load_metrics()
    assert "grouped by well" in m["cv"]
    for et, r in m["results"]["full"].items():
        assert r["auc"] > 0.65, (et, r)
        assert r["ap"] > r["base_rate"], (et, r)


def test_model_predicts_higher_risk_inside_hazard_than_outside(kb):
    from nwis.features import OffsetContext, build_feature_frame
    from nwis.risk_model import load_logs

    conn = connect()
    wid = next(w["id"] for w in kb.wells.values() if w["name"] == "MRH-12")
    logs = load_logs(conn, wid)
    tr = kb.traj[wid]
    X = build_feature_frame(OffsetContext(kb, tr, tr.tops), logs)
    p = RiskModel().predict(X)["kick"]
    kicks = [e["md"] for e in kb.events_by_well[wid] if e["type"] == "kick"]
    near = np.zeros(len(logs), bool)
    for k in kicks:
        near |= (logs["md"].values >= k - 40) & (logs["md"].values <= k)
    assert near.any() and p[near].mean() > 3 * p[~near].mean()


def test_live_replay_alerts_precede_events():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import eval_live

    r = eval_live.run(1300.0, verbose=False)
    assert r["detected"] >= r["truth_events"] - 1
    assert r["median_lead_m"] > 100  # look-ahead warns hundreds of metres early
    assert int(r["short_range_detected"].split("/")[0]) >= r["truth_events"] - 2
    assert r["alert_precision"] > 0.7
