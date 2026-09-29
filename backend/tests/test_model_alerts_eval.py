"""Unit tests for the episode-grouping logic used by eval_model_alerts.py (fast; no model retraining)."""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from eval_model_alerts import episodes  # noqa: E402


def test_no_positives_gives_no_episodes():
    md = np.arange(0, 100, 10.0)
    assert episodes(md, np.zeros(len(md), bool)) == []


def test_contiguous_positives_form_one_episode():
    md = np.array([100.0, 110.0, 120.0, 130.0])
    pos = np.array([True, True, True, True])
    assert episodes(md, pos) == [(100.0, 130.0)]


def test_gap_larger_than_threshold_splits_into_two_episodes():
    md = np.array([100.0, 110.0, 300.0, 310.0])  # 190 m gap >> EPISODE_GAP_M
    pos = np.array([True, True, True, True])
    assert episodes(md, pos) == [(100.0, 110.0), (300.0, 310.0)]


def test_gap_smaller_than_threshold_merges_into_one_episode():
    md = np.array([100.0, 110.0, 130.0, 140.0])  # 20 m gap < EPISODE_GAP_M (30 m)
    pos = np.array([True, True, True, True])
    assert episodes(md, pos) == [(100.0, 140.0)]


def test_trailing_positive_run_is_closed_at_end_of_series():
    md = np.array([0.0, 10.0, 20.0, 30.0])
    pos = np.array([False, False, True, True])
    assert episodes(md, pos) == [(20.0, 30.0)]


def test_interleaved_positive_and_negative_runs():
    # isolated hit, then a run broken by a gap wider than the merge threshold: three separate episodes
    md = np.array([0.0, 10.0, 20.0, 200.0, 210.0])
    pos = np.array([True, False, True, True, False])
    assert episodes(md, pos) == [(0.0, 0.0), (20.0, 20.0), (200.0, 200.0)]
