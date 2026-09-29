"""Teale's Mechanical Specific Energy: formula sanity, casing-driven hole lookup, and live-session wiring."""
from __future__ import annotations

import numpy as np
import pytest

from conftest import needs_data
from nwis.features import DEFAULT_HOLE_IN, MSE_CAP_MPA, teale_mse_mpa
from nwis.kb import Trajectory


def _traj(casing):
    return Trajectory(id=1, name="T", field=None, status="ACTIVE", east0=0.0, north0=0.0,
                      md=np.array([0.0, 4000.0]), tvd=np.array([0.0, 4000.0]), e_m=np.zeros(2), n_m=np.zeros(2),
                      td_md=4000.0, td_tvd=4000.0, casing=casing)


def test_mse_is_positive_and_within_the_physical_cap():
    v = teale_mse_mpa(10.0, 110.0, 14.0, 25.0, 12.25)
    assert 0 < float(v) < MSE_CAP_MPA


def test_higher_torque_for_the_same_progress_means_higher_mse():
    low = teale_mse_mpa(10.0, 110.0, 10.0, 25.0, 12.25)
    high = teale_mse_mpa(10.0, 110.0, 20.0, 25.0, 12.25)
    assert high > low


def test_faster_penetration_for_the_same_effort_means_lower_mse():
    slow = teale_mse_mpa(10.0, 110.0, 14.0, 10.0, 12.25)
    fast = teale_mse_mpa(10.0, 110.0, 14.0, 40.0, 12.25)
    assert fast < slow


def test_smaller_hole_for_the_same_wob_and_torque_means_higher_mse():
    big_hole = teale_mse_mpa(10.0, 110.0, 14.0, 25.0, 17.5)
    small_hole = teale_mse_mpa(10.0, 110.0, 14.0, 25.0, 8.5)
    assert small_hole > big_hole


def test_unknown_hole_size_falls_back_to_a_sane_default_not_a_crash():
    assert teale_mse_mpa(10.0, 110.0, 14.0, 25.0, None) == pytest.approx(teale_mse_mpa(10.0, 110.0, 14.0, 25.0, DEFAULT_HOLE_IN))
    assert np.isfinite(teale_mse_mpa(np.array([10.0]), np.array([110.0]), np.array([14.0]), np.array([25.0]), np.array([np.nan])))[0]


def test_vectorised_and_scalar_calls_agree():
    scalar = [float(teale_mse_mpa(w, 110.0, 14.0, 25.0, 12.25)) for w in (5.0, 10.0, 15.0)]
    vec = teale_mse_mpa(np.array([5.0, 10.0, 15.0]), np.full(3, 110.0), np.full(3, 14.0), np.full(3, 25.0), np.full(3, 12.25))
    assert np.allclose(scalar, vec)


def test_trajectory_hole_lookup_tracks_the_casing_programme():
    tr = _traj([{"hole_in": 26.0, "shoe_md": 60.0}, {"hole_in": 17.5, "shoe_md": 985.0},
                {"hole_in": 12.25, "shoe_md": 2835.0}, {"hole_in": 8.5, "shoe_md": 3900.0}])
    assert tr.hole_diameter_at_md(0) == 26.0
    assert tr.hole_diameter_at_md(985) == 17.5  # exactly at a shoe: still the hole above it
    assert tr.hole_diameter_at_md(1000) == 12.25
    assert tr.hole_diameter_at_md(3999) == 8.5  # open hole past the last shoe, drilling ahead
    arr = tr.hole_diameter_at_md_arr(np.array([0, 500, 1000, 3000, 3999]))
    assert list(arr) == [26.0, 17.5, 12.25, 8.5, 8.5]


def test_trajectory_with_no_casing_returns_none_or_nan_not_a_crash():
    tr = _traj([])
    assert tr.hole_diameter_at_md(1000) is None
    assert np.all(np.isnan(tr.hole_diameter_at_md_arr(np.array([100.0, 200.0]))))


@needs_data
def test_live_sample_carries_a_plausible_mse_using_the_real_casing_plan():
    from nwis.db import connect
    from nwis.kb import KnowledgeIndex
    from nwis.live import LiveSession

    kb = KnowledgeIndex(connect())
    active = next(w for w in kb.wells.values() if (w["status"] or "").upper() == "ACTIVE")
    tr = kb.traj[active["id"]]
    assert tr.casing, "the active well's planned casing programme should have been loaded from plan_casing.csv"

    sess = LiveSession(kb, connect(), active["id"])
    sess.reset(1500)
    stepped = sess.step()
    assert stepped is not None
    # regression check: step() must return the enriched sample (mse, tvd, ...), not the raw replay row —
    # the SSE stream publishes exactly this value, and a raw-row leak here means live charts silently go blank
    assert "mse" in stepped and "tvd" in stepped
    sample = sess.history[-1]
    assert sample is stepped
    assert "mse" in sample
    assert 0 < sample["mse"] < 800
    # at 1500 m the well is drilling the 12-1/4" intermediate hole per the planned casing programme
    hole = tr.hole_diameter_at_md(sample["md"])
    assert hole == pytest.approx(12.25)
    expected = float(teale_mse_mpa(sample["wob"], sample["rpm"], sample["torque"], sample["rop"], hole))
    assert sample["mse"] == pytest.approx(expected, rel=1e-6)
